"""
Valide la passerelle LiteLLM de WAMA — SANS dépendre d'aucune clé cloud par défaut.

Par défaut : route un appel vers Ollama LOCAL via LiteLLM (prouve que la passerelle
fonctionne) + liste les fournisseurs cloud dont la clé est présente dans l'environnement
(détection seule, AUCUN appel). Option --provider/--model pour tester un cloud en réel.

  python manage.py llm_gateway_check                              # Ollama local via LiteLLM
  python manage.py llm_gateway_check --model qwen3.5:9b
  python manage.py llm_gateway_check --provider albert              # appel CLOUD réel (clé requise)

MESURES DES OUTILS (2026-10-23, demande de Fabien : « ajouter des outils de mesures et tests ») —
toujours POUR UN COMPTE (`--user`), donc par sa clé et sous la garde de son profil (niveau cloud,
plafond d'hébergement : `cloud_models.cloud_refusal`), comme un vrai tour :

  python manage.py llm_gateway_check --provider anthropic --model claude-sonnet-5-5 \\
         --tools --user <identifiant> [--repeat 3]
      Un modèle distant appelle-t-il un outil DÉCLARÉ NATIVEMENT (`tools=`), avec la liste même
      que l'assistant lui enverrait (`assistant_engine.native_tool_list`) ? Le verdict dit s'il
      peut entrer dans `ExternalSource.native_tools` — la déclaration reste un geste humain.

  python manage.py llm_gateway_check --provider claude_code --user <identifiant> [--live]
      L'abonnement Claude Code voit-il les outils de WAMA ? La commande préparée porte la surface
      MCP `wama` (`claude_code.prepare`), le serveur répond pour ce compte et annonce ce qu'il doit
      (`mcp_client.surface_tool_names` contre `mcp_server.tools_for`). `--live` : un appel RÉEL au
      CLI (crédit de l'abonnement), dont la réponse est comparée au résultat de l'outil lui-même.
"""
from django.core.management.base import BaseCommand, CommandError

#: L'outil que les mesures font appeler : en lecture seule, sans effet, et d'un résultat vérifiable.
PROBE_TOOL = 'list_ai_models'
PROBE_PROMPT = ("Appelle l'outil {tool} avec l'argument limit=1, puis réponds uniquement par la "
                "valeur du champ key du premier modèle qu'il renvoie.")


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


def called_tool(text) -> str:
    """Le nom de l'outil qu'une réponse APPELLE, lu comme la boucle de l'assistant le lit
    (`assistant_engine._parse_tool_call` : la forme `tool_call_text` d'un appel natif, ou l'appel
    écrit dans le texte) — ''. La mesure juge avec la lecture même qui exécutera l'appel."""
    from wama.common.services.assistant_engine import _parse_tool_call
    call = _parse_tool_call(text or '') if text else None
    return (call or {}).get('tool', '') or ''


def probe_outcome(text, err) -> tuple:
    """`(issue, ligne)` d'un essai — trois issues, jamais deux : l'appel NOMMÉ de l'outil sondé, une
    réponse SANS cet appel (le modèle a parlé : c'est une mesure), une ERREUR du fournisseur (crédit,
    quota, panne : il n'a rien dit du modèle — vécu le 2026-10-23, crédit Anthropic épuisé, que la
    première version comptait comme « ne pas déclarer »)."""
    from wama.common.utils.llm_utils import EMPTY_RESPONSE_ERROR
    tool = called_tool(text)
    if tool == PROBE_TOOL:
        return 'named', f"✓ appel nommé « {tool} »"
    if text is None and err == EMPTY_RESPONSE_ERROR:
        # Répondu SANS texte n'est pas une panne : le modèle a parlé, sans appel — la règle de la
        # boucle de l'assistant (`_llm_call`), et le défaut mesuré sur deepseek le 2026-10-11.
        return 'silent', "✗ réponse vide, sans appel"
    if text is None:
        return 'error', f"⚠ erreur du fournisseur (rien de mesuré) : {str(err)[:160]}"
    return 'silent', ("✗ " + (f"autre outil : {tool}" if tool else
                             f"réponse sans appel : {(text or '')[:120]!r}"))


def verdict(named: int, failed: int, repeat: int, style) -> tuple:
    """La conclusion d'une série — sur les seuls essais MESURÉS ; une erreur ne conclut rien."""
    measured = repeat - failed
    if measured == 0:
        return (style.WARNING(f"Mesure impossible : {failed}/{repeat} erreurs du fournisseur — "
                              "rien à conclure sur le modèle."),)
    if named == measured and failed == 0:
        return (style.SUCCESS(f"{named}/{repeat} appels nommés — déclarable dans `native_tools` "
                              "de la source (geste humain, `external_sources`)."),)
    if named == measured:
        return (style.WARNING(f"{named}/{measured} appels nommés sur les essais mesurés, {failed} "
                              "erreur(s) du fournisseur — refaire la série avant de déclarer."),)
    return (style.WARNING(f"{named}/{measured} appels nommés — ne PAS déclarer : la liste du prompt "
                          "reste la voie de ce modèle."),)


def probe_answer(user) -> str:
    """Ce que l'outil sondé rend VRAIMENT pour `user` — la réponse attendue d'un modèle qui l'a
    appelé (`execute_tool`, la porte de tout appel d'outil)."""
    from wama.tool_api import execute_tool
    result = execute_tool(PROBE_TOOL, {'limit': 1}, user)
    models = result.get('models') if isinstance(result, dict) else None
    return (models[0] or {}).get('key', '') if models else ''


class Command(BaseCommand):
    help = ("Valide la passerelle LiteLLM (Ollama local par défaut ; cloud en option, clé requise) "
            "et mesure l'accès aux outils de WAMA (--tools, --provider claude_code).")

    def add_arguments(self, parser):
        parser.add_argument('--provider', default='ollama',
                            help="ollama (défaut, LOCAL), un fournisseur déclaré au registre des "
                                 "sources externes (albert, ilaas, openrouter, anthropic), ou "
                                 "claude_code (l'abonnement : mesure de sa surface MCP).")
        parser.add_argument('--model', default='',
                            help="Nom du modèle (défaut : résolu par le catalogue, "
                                 "modele_par_defaut — plus de nom en dur, retrait qwen3.5:9b 26/08).")
        parser.add_argument('--timeout', type=int, default=30)
        parser.add_argument('--user', default='',
                            help="Compte pour qui mesurer (identifiant) — exigé par --tools et "
                                 "claude_code : sa clé, ses droits, son profil.")
        parser.add_argument('--tools', action='store_true',
                            help="Mesure un appel d'outil DÉCLARÉ NATIVEMENT par le modèle distant.")
        parser.add_argument('--repeat', type=int, default=1,
                            help="Nombre d'essais de --tools (un appel qui réussit 1 fois sur 3 "
                                 "n'est pas déclarable).")
        parser.add_argument('--live', action='store_true',
                            help="claude_code : un appel RÉEL au CLI (crédit de l'abonnement).")

    def _user(self, options):
        from django.contrib.auth import get_user_model
        if not options['user']:
            raise CommandError("--user est exigé : la mesure se fait pour un compte (sa clé, ses "
                               "droits, son profil).")
        user = get_user_model().objects.filter(username=options['user'], is_active=True).first()
        if user is None:
            raise CommandError(f"Compte actif introuvable : {options['user']!r}")
        return user

    def handle(self, *args, **options):
        provider = options['provider']
        if provider == 'claude_code':
            return self._subscription(options)
        if options['tools']:
            return self._native_tools(options)
        return self._gateway(options)

    # ── La passerelle (comportement d'origine) ───────────────────────────────────────────────
    def _gateway(self, options):
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
                + ", ".join(['ollama', 'claude_code'] + _cloud_providers()) + "."))
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

    # ── Un appel d'outil DÉCLARÉ NATIVEMENT par un modèle distant ────────────────────────────
    def _native_tools(self, options):
        from wama.common import external_sources
        from wama.common.services.assistant_engine import native_tool_list
        from wama.common.utils.llm_utils import chat_with_source, default_cloud_model
        from wama.model_manager.services.cloud_models import CloudAccessRefused

        provider = options['provider']
        if provider not in _cloud_providers():
            raise CommandError(f"--tools mesure un fournisseur distant déclaré : "
                               f"{', '.join(_cloud_providers())}.")
        user = self._user(options)
        source = external_sources.get(provider)
        # L'identifiant du CATALOGUE — celui que la garde des clés juge et que l'assistant passe
        # (le modèle par défaut d'une source est écrit sous sa forme LiteLLM, `openai/gpt-oss-120b`).
        model = source.catalogue_model_id(options['model'] or default_cloud_model(provider))
        specs = native_tool_list(user)
        from wama.common.services.assistant_engine import _accepts_native_tools
        declared = _accepts_native_tools(source, model)
        self.stdout.write(f"Outils déclarés nativement : {len(specs)} (ceux du serveur MCP pour "
                          f"{user.username}) → {provider} / {model} — "
                          f"{'déjà' if declared else 'pas encore'} déclaré `native_tools`.")
        named = failed = 0
        repeat = max(1, options['repeat'])
        for attempt in range(1, repeat + 1):
            try:
                text, err = chat_with_source(
                    provider, model, [{'role': 'user', 'content': PROBE_PROMPT.format(tool=PROBE_TOOL)}],
                    user=user, num_predict=1024, timeout=max(60, options['timeout']),
                    temperature=None, tools=specs)
            except CloudAccessRefused as refused:
                raise CommandError(f"Refusé par le profil de {user.username} : {refused}")
            outcome = probe_outcome(text, err)
            named += outcome[0] == 'named'
            failed += outcome[0] == 'error'
            self.stdout.write(f"  essai {attempt}/{repeat} : {outcome[1]}")
        self.stdout.write(*verdict(named, failed, repeat, self.style))

    # ── L'abonnement Claude Code et la surface MCP `wama` ───────────────────────────────────
    def _subscription(self, options):
        from wama.common.services import claude_code
        from wama.common.services.mcp_client import surface_tool_names
        from wama.common.services.mcp_server import SURFACE_WAMA, TOKEN_ENV, tools_for
        from wama.model_manager.services.cloud_models import cloud_refusal

        user = self._user(options)
        refusal = cloud_refusal(user, claude_code.SUBSCRIPTION_SOURCE)
        if refusal:
            raise CommandError(f"Refusé par le profil de {user.username} : {refusal}")
        prepared = claude_code.prepare('OK', user=user)
        if 'error' in prepared:
            raise CommandError(prepared['error'])
        argv, env = prepared['argv'], prepared['env']
        allowed = argv[argv.index('--allowedTools') + 1:] if '--allowedTools' in argv else []
        windows = claude_code._crosses_to_windows(argv[0])
        checks = [
            ("la surface `wama` est passée au CLI (--mcp-config, --strict-mcp-config)",
             '--mcp-config' in argv and '--strict-mcp-config' in argv),
            ("ses outils sont autorisés (mcp__wama)", f'mcp__{claude_code.MCP_SERVER_NAME}' in allowed),
            ("le jeton d'API voyage par l'environnement, jamais sur la ligne de commande",
             bool(env.get(TOKEN_ENV)) and all(env[TOKEN_ENV] not in a for a in argv)),
            ("CLI Windows : les secrets sont nommés dans WSLENV" if windows else "CLI natif : WSLENV inutile",
             (not windows) or TOKEN_ENV in (env.get('WSLENV') or '').split(':')),
        ]
        try:
            announced = surface_tool_names(user, SURFACE_WAMA)
            expected = sorted(t.name for t in tools_for(user))
            checks.append((f"le serveur MCP répond pour {user.username} et annonce ses "
                           f"{len(expected)} outils ({len(announced)} annoncés)", announced == expected))
        except Exception as e:
            checks.append((f"le serveur MCP répond ({type(e).__name__}: {str(e)[:120]})", False))
        for label, ok in checks:
            self.stdout.write(f"  {'✓' if ok else '✗'} {label}")
        if not options['live']:
            self.stdout.write("(--live : un appel réel au CLI, sur le crédit de l'abonnement)")
            return
        expected_key = probe_answer(user)
        result = claude_code.demander(PROBE_PROMPT.format(tool=f'mcp__{claude_code.MCP_SERVER_NAME}__{PROBE_TOOL}'),
                                      user=user, delai=max(120, options['timeout']))
        if not result.get('success'):
            self.stderr.write(self.style.ERROR(f"  ✗ appel réel : {result.get('error')}"))
            return
        answer = (result.get('texte') or '').strip()
        ok = bool(expected_key) and expected_key in answer
        style = self.style.SUCCESS if ok else self.style.ERROR
        self.stdout.write(style(
            f"  {'✓' if ok else '✗'} appel réel ({result.get('modele') or '?'}, "
            f"{result.get('cout_usd')} $ équivalent API) : réponse {answer[:80]!r}, "
            f"attendu {expected_key!r} (rendu par l'outil lui-même)"))
