from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.common'

    def ready(self):
        # INVENTAIRE DES MOTEURS, dérivé des déclarations `ENGINE` des backends (2026-09-04).
        # ⚠ Pourquoi c'est nécessaire, mesuré : `known_engines()` n'agrégeait que les 2
        # inventaires enregistrés à la main (composer, synthesizer) alors que 18 moteurs sont
        # déclarés. Un modèle exigeant `pyannote` était donc jugé « moteur sans backend
        # installé » — verdict FAUX, masqué aujourd'hui par `backend_ref`. Brancher l'inventaire
        # dérivé est donc le PRÉALABLE au retrait de `backend_ref` (ROADMAP §5b).
        # Enregistrement PARESSEUX : le balayage (statique, ~0,15 s) n'a lieu qu'au premier
        # appel, et il ne consulte JAMAIS `known_engines()` — un producteur ne lit pas le
        # registre qu'il alimente (cycle mesuré à 47 s le 03/09).
        try:
            from wama.common.backends.manager import register_engine_inventory
            from wama.common.services.backend_inventory import declared_engines
            register_engine_inventory(declared_engines)
            # Le DÉMON Ollama est un moteur au même titre qu'une librairie : 29 modèles le
            # nomment, et son mode de panne le plus courant (démon éteint) est mesurable.
            # Il ne peut pas venir de `declared_engines`, qui dérive des classes de backend —
            # Ollama n'en a pas, et n'en aura pas : ce n'est pas du code Python qu'on charge.
            from wama.common.utils.ollama_host import ollama_engine_inventory
            register_engine_inventory(ollama_engine_inventory)
            # Fournisseurs LLM DISTANTS (Albert…) : leurs modèles nomment leur moteur comme les
            # autres ; sans cet inventaire, ils seraient jugés « moteur sans backend installé ».
            from wama.common.external_sources import llm_engine_inventory
            register_engine_inventory(llm_engine_inventory)
        except Exception:
            pass

        # Journal APPLICATIF global `logs/wama.log` — comble le trou mesuré le 2026-08-18 :
        # `settings.LOGGING` n'existe que dans la branche LDAP (django_auth_ldap→console),
        # donc les loggers `wama.*` n'avaient AUCUN handler et le `logger.exception` de
        # l'install de modèle partait dans le vide (seul le toast navigateur portait l'erreur).
        # `propagate=True` — à l'INVERSE de model-sync.log : couper la propagation priverait
        # les `celery-*.log` des traces de tâches (c'est celery-gpu.log qui a permis
        # d'identifier la tâche imager responsable des kernel panics du 29/07).
        # Les loggers déjà cloisonnés (model-sync, console_utils) gardent leur quarantaine :
        # leur `propagate=False` est posé sur un logger PLUS PROFOND que 'wama'.
        try:
            from wama.common.utils.log_rotation import attach_dedicated_log
            attach_dedicated_log(
                'wama', 'wama.log', propagate=True,
                fmt='%(asctime)s [%(levelname)s] [%(name)s] %(message)s')
        except Exception:
            import logging
            logging.getLogger(__name__).debug('Journal wama.log non attaché', exc_info=True)

        # `logs/django-errors.log` — MÊME trou que ci-dessus, un cran plus haut : c'est
        # Django lui-même (`django.request`) qui n'avait aucun handler. Mesuré le
        # 2026-08-24 : 11 réponses 500 en 36 h, aucune trace nulle part. La chaîne était
        # `django.request` (0 handler) → `django` → StreamHandler(stderr), que le
        # `daemon = True` de gunicorn envoyait dans /dev/null (corrigé en parallèle par
        # `capture_output`). L'AdminEmailHandler, lui, est filtré par RequireDebugFalse
        # et `ADMINS` est vide : les deux sorties par défaut étaient donc mortes.
        # `propagate=False` — À L'INVERSE de 'wama' juste au-dessus : avec capture_output
        # la propagation dupliquerait chaque traceback dans gunicorn-error.log. Ici on
        # veut UN endroit. `level=ERROR` : les 4xx que `django.request` émet en WARNING
        # n'ont pas de traceback et sont déjà lisibles dans les access logs.
        try:
            import logging as _logging
            from wama.common.utils.log_rotation import attach_dedicated_log
            attach_dedicated_log(
                'django.request', 'django-errors.log',
                level=_logging.ERROR, propagate=False,
                fmt='%(asctime)s [%(levelname)s] [%(name)s] %(message)s')
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                'Journal django-errors.log non attaché', exc_info=True)

        # Gouverneur de ressources : plafonne l'allocateur CUDA de CE process.
        # Couvre les process Django (workers gunicorn) ; les workers Celery sont
        # couverts par le signal `worker_process_init` (wama/celery.py) et le
        # service TTS par son `startup`. Idempotent — un process déjà configuré
        # ne refait rien. Point d'entrée unique : common/services/resource_governor.py
        # Scénarios nocturnes `consistency` (AVANT le guard RUN_MAIN, comme l'enhancer :
        # ils doivent exister aussi pour les management commands, run_nightly_tests inclus).
        try:
            from .nightly_scenarios import register_scenarios
            register_scenarios()
        except Exception:
            pass

        # Scénarios nocturnes `suite` : la suite Django entre dans la grille fonctionnelle
        # (2026-09-19). Dérivés des apps installées qui ont des tests — voir nightly_suite.py.
        try:
            from .nightly_suite import register_scenarios as register_suite_scenarios
            register_suite_scenarios()
        except Exception:
            pass

        try:
            from wama.common.services.resource_governor import configure_cuda_process
            configure_cuda_process()
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                'Gouverneur de ressources non initialisé', exc_info=True)

        # Branche l'enrichissement de prompt à l'INGESTION sur tout modèle DÉCLARÉ
        # enrichissable (PROMPT_TARGETS). Générique : aucune app n'écrit de récepteur.
        try:
            from wama.common.prompt_ingest import register_prompt_ingest_receivers
            register_prompt_ingest_receivers()
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                'Récepteurs prompt_ingest non enregistrés', exc_info=True)

        # COPIE DE LECTURE (2026-10-06, décision de Fabien) : toute vidéo qu'une card porte et
        # que le navigateur ne lit pas en reçoit une dès son import, quelle que soit la voie.
        # Même forme que ci-dessus : un récepteur générique, aucune app n'écrit rien.
        try:
            from wama.common.utils.video_compat import register_playback_copy_receivers
            register_playback_copy_receivers()
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                'Récepteurs de copie de lecture non enregistrés', exc_info=True)

        # ENTRÉE PAR URL (2026-10-13, décision de Fabien) : toute card créée avec une URL voit son
        # entrée téléchargée dès sa création, hors requête — sur tout modèle qui déclare
        # `WAMA_INGEST`. Même forme que ci-dessus : un récepteur générique, aucune app n'écrit rien.
        try:
            from wama.common.utils.source_ingest import register_source_ingest_receivers
            register_source_ingest_receivers()
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                "Récepteurs d'ingest d'URL non enregistrés", exc_info=True)

        # Registres catalogués : l'import DÉCLARE, il n'actualise rien (voir `registries.py`).
        # C'est ce qui donne aux pages catalogue leur bouton sans une ligne d'UI par page.
        try:
            from . import registries_builtin  # noqa: F401
            from .registries import run_startup
            run_startup()
            # Les Registres sont un OUTIL gardé par la politique d'accès (2026-10-13) : comme tout
            # outil gardé, ils se déclarent en SURFACE (monde, page) — masquables par
            # l'abonnement, relevés par la scène des droits. `nav_hide` : leur entrée reste
            # celle du menu du compte.
            from .app_registry import register_pageless_tool, register_surface
            register_surface('registries', world='transverse', label='Registres',
                             url_name='common:registries', icon='fa-layer-group',
                             description="La carte de ce que WAMA sait nommer, et de la façon "
                                         "dont chaque catalogue se tient à jour.",
                             nav_hide=True, order=40)
            # L'assistant est une APPLICATION sans page (une conversation : web, API,
            # connecteurs, conversation vocale) — outil sans page, gardé sur ses routes web
            # (`permissions.PATH_APP_MAP`) ET dans `conversation_turn`, le tour commun à toutes
            # ses surfaces (2026-10-13).
            register_pageless_tool('assistant', world='transverse', label='Assistant',
                                   icon='fa-robot', probe='/api/ai-chat/thread/',
                                   description="La conversation avec WAMA : web, API, connecteurs, "
                                               "conversation vocale.")
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                'registres catalogués non déclarés', exc_info=True)

        self._register_account_pages()

        # ⚠ Le substrat n'enregistre PLUS les fonctions du monde Data (déport du 2026-08-22) :
        # chaque monde se déclare dans son propre `ready()` — `wama_data/apps.py`,
        # `wama_lab/cam_analyzer/apps.py`. Le substrat ne doit connaître aucun monde par son nom.

    @staticmethod
    def _register_account_pages():
        """Les pages du menu du COMPTE que porte le substrat (2026-10-14, demande de Fabien) : le
        menu en est GÉNÉRÉ et l'assistant y emmène (`app_registry.register_account_page`).

        `access` = le décorateur de la vue, et lui seul : `account` pour `login_required`,
        `public` pour une vue sans décorateur. Une page catalogue sans `description` prend celle
        de son registre (même route). L'ordre est celui du menu tel qu'arbitré le 01/09 — le
        trio journal · RAG · souvenirs se lit dans cet ordre, le calendrier le précède.
        """
        from .app_registry import register_account_page as page
        try:
            page('calendar', section='mine', label='Mon calendrier', icon='fa-calendar-days',
                 tone='primary', access='account', url_name='common:calendar', order=20,
                 description="Votre activité sur l'axe du temps : traitements réalisés, prévus "
                             "et programmés, et les fenêtres de maintenance de WAMA.")
            page('journal', section='mine', label='Mon journal', icon='fa-clock-rotate-left',
                 tone='info', access='account', url_name='common:journal', order=30,
                 description="Tout ce que vous avez produit, dans toutes les applications.")
            page('rag', section='mine', label='Mon RAG', icon='fa-book-open-reader',
                 tone='success', access='account', url_name='common:rag', order=40)
            page('memories', section='mine', label='Mes souvenirs', icon='fa-brain',
                 tone='warning', access='account', url_name='common:memories', order=50)
            page('shares', section='mine', label='Mes partages', icon='fa-share-nodes',
                 color='#c4b5fd', access='account', url_name='common:shares', order=60,
                 description="Ce que vous avez partagé et ce qu'on vous a partagé, avec les "
                             "demandes d'accès en attente.")
            page('skills', section='mine', label='Skills', icon='fa-wand-magic-sparkles',
                 tone='info', access='public', url_name='common:skills_catalog', order=80)
            page('notifications', section='mine', label='Notifications', icon='fa-bell',
                 access='account', url_name='common:notifications', menu=False,
                 description="Vos notifications dans WAMA, lues et non lues.")
            page('apps', section='wama', label='Apps', icon='fa-cubes', tone='primary',
                 access='public', url_name='common:apps_catalog', order=10)
            page('docs', section='wama', label='Documentation', icon='fa-file-lines',
                 tone='success', access='account', url_name='common:docs_catalog', order=20)
            page('licenses', section='wama', label='Licences', icon='fa-scale-balanced',
                 tone='success', access='public', url_name='common:licenses_catalog', order=40)
            page('backends', section='wama', label='Backends', icon='fa-gears', tone='info',
                 access='public', url_name='common:backends_catalog', order=60)
            page('media_formats', section='wama', label='Formats médias', icon='fa-photo-film',
                 tone='primary', access='public', url_name='common:media_formats_catalog',
                 order=70)
            page('ui_bricks', section='wama', label='Briques UI', icon='fa-puzzle-piece',
                 tone='info', access='public', url_name='common:ui_bricks_catalog', order=75)
            # Les Registres : une SURFACE (outil gardé, 2026-10-13), dont la page est aussi le
            # hub de cette section. Sa vue n'a pas de décorateur : le middleware la ferme au
            # visiteur et la garde par la politique `registries`.
            page('registries', section='wama', label='Registres', icon='fa-layer-group',
                 tone='warning', access='public', surface='registries', order=80)
            page('sources', section='wama', label='Sources', icon='fa-satellite-dish',
                 tone='danger', access='public', url_name='common:sources_catalog', order=90)
        except Exception:
            import logging
            logging.getLogger(__name__).warning('pages du compte non déclarées', exc_info=True)
