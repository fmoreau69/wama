"""
Valide la passerelle LiteLLM de WAMA — SANS dépendre d'aucune clé cloud par défaut.

Par défaut : route un appel vers Ollama LOCAL via LiteLLM (prouve que la passerelle
fonctionne) + liste les fournisseurs cloud dont la clé est présente dans l'environnement
(détection seule, AUCUN appel). Option --provider/--model pour tester un cloud en réel.

  python manage.py llm_gateway_check                              # Ollama local via LiteLLM
  python manage.py llm_gateway_check --model qwen3.5:9b
  python manage.py llm_gateway_check --provider albert              # appel CLOUD réel (clé requise)
"""
from django.core.management.base import BaseCommand


def _instance_key(provider: str) -> str:
    """Clé d'instance de `provider` : page « Sources externes », sinon `.env`."""
    from wama.common import external_sources
    return external_sources.api_key(provider)


def _cloud_providers() -> list:
    """Les fournisseurs distants que `llm_chat` sait appeler : les sources DÉCLARÉES, et elles
    seules (2026-10-11, chantier 5 de `WAMA_HARNESS.md`). La table des fournisseurs sans source
    (`openai`, `xai`, `gemini`, `mistral`, `groq`, `deepseek`) est retirée avec eux."""
    from wama.common import external_sources
    from wama.common.utils.llm_utils import declared_llm_source
    return [s.key for s in external_sources.SOURCES if declared_llm_source(s.key)]


class Command(BaseCommand):
    help = "Valide la passerelle LiteLLM (Ollama local par défaut ; cloud en option, clé requise)."

    def add_arguments(self, parser):
        parser.add_argument('--provider', default='ollama',
                            help="ollama (défaut, LOCAL) ou un fournisseur déclaré au registre des "
                                 "sources externes : albert, ilaas, openrouter, anthropic.")
        parser.add_argument('--model', default='',
                            help="Nom du modèle (défaut : résolu par le catalogue, "
                                 "modele_par_defaut — plus de nom en dur, retrait qwen3.5:9b 26/08).")
        parser.add_argument('--timeout', type=int, default=30)

    def handle(self, *args, **options):
        from django.conf import settings
        try:
            import litellm
        except ImportError:
            self.stderr.write(self.style.ERROR("litellm non installé (pip install litellm)."))
            return

        provider, model = options['provider'], options['model']
        if provider == 'ollama' and not model:
            from wama.common.utils.llm_utils import modele_par_defaut
            model = modele_par_defaut()
            self.stdout.write(f"Modèle résolu par le catalogue : {model or '(aucun)'}")

        # 1) Détection des clés cloud configurées (AUCUN appel réseau).
        configured = [p for p in _cloud_providers() if _instance_key(p)]
        self.stdout.write("Clés cloud détectées : " + (", ".join(configured) if configured else "(aucune)"))

        # 2) Construction de l'appel de validation.
        if provider == 'ollama':
            # Une commande de gestion tourne HORS de `start_wama_prod.sh` : c'est exactement le
            # contexte où la lecture brute du réglage laisse `127.0.0.1` (= la VM, pas l'hôte).
            from wama.common.utils.ollama_host import ollama_base
            base = ollama_base()
            litellm_model = f"ollama/{model}"
            self.stdout.write(f"\nTest passerelle → {litellm_model}  (LOCAL {base}) …")
            try:
                resp = litellm.completion(
                    messages=[{"role": "user", "content": "Réponds uniquement : OK"}],
                    timeout=options['timeout'], max_tokens=16,
                    model=litellm_model, api_base=base)
                text = (resp.choices[0].message.content or '').strip()
                self.stdout.write(self.style.SUCCESS(f"✓ Passerelle OK — réponse : {text[:80]!r}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(
                    f"✗ Échec passerelle : {type(e).__name__}: {str(e)[:200]}"))
            return

        if provider not in _cloud_providers():
            self.stderr.write(self.style.ERROR(
                f"'{provider}' n'est pas un fournisseur déclaré : "
                + ", ".join(['ollama'] + _cloud_providers()) + "."))
            return
        if not _instance_key(provider):
            self.stderr.write(self.style.ERROR(
                f"Clé absente pour '{provider}' (page « Sources externes » ou .env). "
                "Test cloud annulé."))
            return
        # 3) Appel CLOUD par `llm_chat` — le chemin qu'emploient réellement l'assistant et les
        # rôles wama-dev-ai. Construire l'appel LiteLLM ici validerait une construction que
        # personne n'utilise (et ne connaîtrait ni l'adresse d'Albert ni son préfixe `openai/`).
        # `num_predict` large : un modèle de raisonnement (gpt-oss) prend sa réflexion sur le
        # même budget, et 16 jetons rendraient une réponse vide sur un fournisseur sain.
        from wama.common.utils.llm_utils import default_cloud_model, llm_chat
        model = model or default_cloud_model(provider)
        self.stdout.write(f"\nTest passerelle → {provider} / {model}  (CLOUD) …")
        text, err = llm_chat(
            [{"role": "user", "content": "Réponds uniquement : OK"}],
            model=model, provider=provider, num_predict=512, timeout=options['timeout'],
            temperature=None)                   # celle du fournisseur : on éprouve la passerelle
        if text is None:
            self.stderr.write(self.style.ERROR(f"✗ Échec passerelle : {str(err)[:300]}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"✓ Passerelle OK — réponse : {text[:80]!r}"))
