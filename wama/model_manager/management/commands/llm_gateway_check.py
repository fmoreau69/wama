"""
Valide la passerelle LiteLLM de WAMA — SANS dépendre d'aucune clé cloud par défaut.

Par défaut : route un appel vers Ollama LOCAL via LiteLLM (prouve que la passerelle
fonctionne) + liste les fournisseurs cloud dont la clé est présente dans l'environnement
(détection seule, AUCUN appel). Option --provider/--model pour tester un cloud en réel.

  python manage.py llm_gateway_check                              # Ollama local via LiteLLM
  python manage.py llm_gateway_check --model qwen3.5:9b
  python manage.py llm_gateway_check --provider xai --model grok-3   # appel CLOUD réel (clé requise)
"""
import os

from django.core.management.base import BaseCommand

# Fournisseurs cloud connus → variable d'env de clé (lue NATIVEMENT par LiteLLM).
_PROVIDER_ENV = {
    'openai':     'OPENAI_API_KEY',
    'anthropic':  'ANTHROPIC_API_KEY',
    'xai':        'XAI_API_KEY',          # Grok
    'gemini':     'GEMINI_API_KEY',
    'mistral':    'MISTRAL_API_KEY',
    'groq':       'GROQ_API_KEY',
    'deepseek':   'DEEPSEEK_API_KEY',
    'openrouter': 'OPENROUTER_API_KEY',
}


class Command(BaseCommand):
    help = "Valide la passerelle LiteLLM (Ollama local par défaut ; cloud en option, clé requise)."

    def add_arguments(self, parser):
        parser.add_argument('--provider', default='ollama',
                            help="ollama (défaut, LOCAL) ou un cloud : xai, gemini, openai, mistral, groq, deepseek, openrouter.")
        parser.add_argument('--model', default='qwen3.5:9b', help="Nom du modèle (défaut qwen3.5:9b).")
        parser.add_argument('--timeout', type=int, default=30)

    def handle(self, *args, **options):
        from django.conf import settings
        try:
            import litellm
        except ImportError:
            self.stderr.write(self.style.ERROR("litellm non installé (pip install litellm)."))
            return

        provider, model = options['provider'], options['model']

        # 1) Détection des clés cloud configurées (AUCUN appel réseau).
        configured = [p for p, env in _PROVIDER_ENV.items() if os.environ.get(env)]
        self.stdout.write("Clés cloud détectées : " + (", ".join(configured) if configured else "(aucune)"))

        # 2) Construction de l'appel de validation.
        if provider == 'ollama':
            base = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434')
            litellm_model = f"ollama/{model}"
            kwargs = {'model': litellm_model, 'api_base': base}
            self.stdout.write(f"\nTest passerelle → {litellm_model}  (LOCAL {base}) …")
        else:
            env = _PROVIDER_ENV.get(provider)
            if env and not os.environ.get(env):
                self.stderr.write(self.style.ERROR(
                    f"Clé absente pour '{provider}' (définir {env}). Test cloud annulé."))
                return
            litellm_model = model if '/' in model else f"{provider}/{model}"
            kwargs = {'model': litellm_model}
            self.stdout.write(f"\nTest passerelle → {litellm_model}  (CLOUD) …")

        # 3) Appel.
        try:
            resp = litellm.completion(
                messages=[{"role": "user", "content": "Réponds uniquement : OK"}],
                timeout=options['timeout'], max_tokens=16, **kwargs)
            text = (resp.choices[0].message.content or '').strip()
            self.stdout.write(self.style.SUCCESS(f"✓ Passerelle OK — réponse : {text[:80]!r}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(
                f"✗ Échec passerelle : {type(e).__name__}: {str(e)[:200]}"))
