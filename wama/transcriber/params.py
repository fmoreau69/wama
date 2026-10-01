"""
Schéma de paramètres du Transcriber — SOURCE UNIQUE pour la modale (item/batch) et le
volet inspecteur (card/batch/file). La structure (type, choices, défaut) est DÉRIVÉE du
modèle `Transcript` ; seule la surcouche UI (libellés, options dynamiques, visibilité
conditionnelle, basique/avancé) est déclarée ici. Voir `common/utils/param_schema.py`.
"""

from wama.common.utils.auto_model import intent_param
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from .models import Transcript

# Ordre = ordre d'affichage. Les libellés/aides vivent ICI (un seul endroit) tant qu'ils
# ne sont pas portés dans le modèle (verbose_name/help_text).
PARAMS = derive_from_model(
    Transcript,
    include=[
        # Ordre = déroulé logique du process : moteur → mots-clés → prétraitement (avant transcription)
        # → diarisation → résumé → cohérence.
        # NB : temperature/max_tokens RETIRÉS des réglages utilisateur — en ASR on veut la
        # REPRODUCTIBILITÉ (pas la créativité), et ces deux réglages étaient inertes/trompeurs
        # (Whisper ne les utilise pas ; le câblage max_tokens était cassé). Le découpage des
        # audios longs se gère en interne (chunking + sync timestamps), pas via un plafond exposé.
        "backend",
        # Curseur rapide/qualité commun (chantier C) : depuis que le select sert « auto » (F4b ⑦,
        # 2026-09-30), toute app qui sert « auto » le porte (`tests_intent_vision`). Hors modèle
        # (pas de colonne), comme au reader : un RÉGLAGE D'APP de l'utilisateur, lu au lancement
        # par `quality_intent_of(item, 'transcriber')`. Il arbitre DANS le palier de la politique
        # « Whisper d'abord » (`AUTO_PRIORITY`), il ne la remplace pas.
        "quality_intent",
        "hotwords",
        "preprocess_audio",
        "level_speech",
        "vad_mode",
        "language_mode",
        "enable_diarization",
        "diarization_model",
        "generate_summary",
        "summary_type",
        "verify_coherence",
    ],
    overrides={
        # dom_id = ID legacy SCOPÉ PAR CONTEXTE → migration sans casse : le volet (panel) et la
        # modale (item) gardent CHACUN leurs IDs/n​oms existants, donc le JS de chaque surface
        # continue de marcher, et on rend les deux depuis CE schéma unique sans collision d'ID.
        "backend": dict(
            chip=True,
            type="select", label="Modèle de transcription",
            icon="fa-microchip", dom_id={"panel": "backendSelect", "item": "settingsBackend"},
            # ── Route F4b ⑦ (2026-09-30, décision de Fabien) — les options viennent du CATALOGUE,
            # au grain MODÈLE (Qwen3-ASR 0.6B OU 1.7B, Canary OU Parakeet), bornées par la TÂCHE —
            # jamais par la source : un modèle installé depuis le model manager entre sans une
            # ligne de code, et s'il n'a pas de backend il est GRISÉ avec la raison (`backend_missing`).
            # Valeurs = CLÉS entières (migration 0027). Jusque-là : une liste de MOTEURS servie par un
            # endpoint propre à l'app et remplie en JS (`loadBackendsAsync`), traduite ensuite en
            # modèle par sous-chaîne.
            options_source="catalog",
            options_query={"task": "transcription"},
            # « auto » + prévision : le lancement résout (`backends.manager.resolve_auto_key`).
            options_auto=True,
            # Les modèles DISTANTS que la clé de l'utilisateur ouvre (Albert…), selon son niveau
            # cloud — et, depuis le même soir, le tirage « auto » les reçoit aussi pour un profil
            # « cloud autorisé » (`auto_model.declared_cloud_keys`).
            options_cloud=True,
            default="auto",
            # Domaine SERVEUR : ce que la porte des outils ACCEPTE et annonce à l'assistant — sans
            # lui elle ne connaîtrait aucun modèle (le navigateur remplit le select).
            options_domain="wama.transcriber.backends.manager.backend_choice_values",
            # Pas d'aide statique : le `help_text` du champ (« Clé de catalogue… ») est une note de
            # DONNÉE, pas un texte pour l'utilisateur — vu à l'écran le 2026-09-30. Le descriptif
            # du modèle choisi s'affiche sous le select (WamaModelHelp, méta lue sur le domaine).
            help="",
            help_source="transcriber",
            help_fallback={"auto": "Choisit le modèle au lancement : Whisper d'abord, puis selon "
                                   "la mémoire GPU libre et, si votre profil l'autorise, un modèle "
                                   "distant."},
        ),
        "quality_intent": intent_param(
            dom_id={"panel": "qualityIntent"}, contexts=("panel",),
            show_if={"field": "backend", "equals": "auto"},
        ),
        "hotwords": dict(
            chip=True,
            type="textarea", label="Mots-clés contextuels", icon="fa-tags",
            dom_id={"panel": "hotwordsInput", "item": "settingsHotwords"},
            help="Séparés par des virgules",
        ),
        "preprocess_audio": dict(
            label="Prétraitement audio", icon="fa-wand-magic-sparkles",
            dom_id={"panel": "preprocessingToggle", "item": "settingsPreprocess"},
            # Risque MESURÉ (2026-09-25, lot #443 ; banc des prétraitements 2026-10-01,
            # WAMA_QUALITE §9bis) : le débruitage ne bat jamais le nivellement seul, et sur un
            # enregistrement BAS il efface la parole — d'où le nivellement imposé avant lui.
            help_html='Débruitage IA (DeepFilterNet), la parole étant d\'abord nivelée<br>'
                      '<span class="text-warning">Dégrade la transcription d\'un enregistrement '
                      'propre ou lointain : à réserver aux fonds très bruyants.</span><br>'
                      '<a href="#" class="text-info text-decoration-none" data-bs-toggle="modal" '
                      'data-bs-target="#preprocessingModal"><i class="fas fa-circle-question"></i> En savoir plus</a>',
        ),
        "level_speech": dict(
            label="Nivellement de la parole", icon="fa-sliders",
            help="Amène chaque voix au même niveau tout au long de l'audio (les voix faibles sont "
                 "remontées, les fortes rabaissées, sans remonter le bruit des silences). Appliqué "
                 "en premier, avant le prétraitement. Mesuré : aide les enregistrements lointains "
                 "ou faits à bas niveau, neutre sur un enregistrement propre."),
        "vad_mode": dict(
            type="select", label="Filtre de parole (VAD)", icon="fa-wave-square",
            help="Whisper et Albert sautent les passages jugés sans parole. « Auto » vérifie "
                 "d'abord que le filtre "
                 "ne rejette pas une parole lointaine (entretien enregistré à distance) et le "
                 "désactive alors. « Désactivé » garde tout, au risque de texte inventé dans les "
                 "longs silences."),
        "language_mode": dict(
            type="select", label="Langues parlées", icon="fa-language",
            help="« Auto » écoute plusieurs passages de l'audio avant de transcrire : s'il entend "
                 "plusieurs langues, chaque passage est transcrit dans la sienne. « Une seule » "
                 "garde la même langue partout (évite qu'un passage bruité soit traduit). "
                 "« Plusieurs » la redécide à chaque passage de 30 s."),
        "enable_diarization": dict(
            chip=True, chip_label="Diarisation",label="Identifier les locuteurs", icon="fa-users",
            dom_id={"panel": "diarizationToggle", "item": "settingsDiarization"},
            help="Séparation des locuteurs (pyannote)"),
        "diarization_model": dict(
            type="select", label="Modèle de diarisation", icon="fa-users-gear",
            show_if="enable_diarization",
            help="community-1 succède à 3.1 (mêmes auteurs). En cours d'évaluation sur des "
                 "réunions annotées : le meilleur des deux n'est pas encore établi."),
        "generate_summary": dict(
            chip=True, chip_label="Résumé",label="Générer un résumé", icon="fa-file-lines",
            dom_id={"panel": "globalGenerateSummary", "item": "settingsGenerateSummary"}),
        "summary_type": dict(
            type="radio", label="", icon="fa-list", show_if="generate_summary",
            radio_name={"panel": "globalSummaryType", "item": "summary_type"}, inline=True,
            choices=[("structured", "Structuré"), ("meeting", "Réunion")],
        ),
        "verify_coherence": dict(
            chip=True, chip_label="Cohérence",label="Vérifier la cohérence", icon="fa-check-double",
            dom_id={"panel": "globalVerifyCoherence", "item": "settingsVerifyCoherence"},
            help="Score + correction proposée côte à côte"),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)

# ── Réglages UTILISATEUR du volet (brique commune `user_settings`) — dérivés du schéma ────
# Même forme que l'imager (`common/utils/param_schema.panel_defaults` & co., 2026-09-26) : le
# volet EST la surface des défauts utilisateur. La clé de stockage est le NOM du param, sauf
# deux clés déjà en base sous un autre nom (frontière des données : elles restent).
_STORED_UNDER = {'enable_diarization': 'diarization', 'preprocess_audio': 'preprocessing_enabled'}


from wama.common.utils.param_schema import panel_defaults, panel_name_key  # noqa: E402


def user_setting_key(p):
    """Clé de stockage d'un param du volet, None s'il n'y figure pas."""
    name = panel_name_key(p)
    return _STORED_UNDER.get(name, name) if name else None


USER_SETTINGS_DEFAULTS = panel_defaults(PARAMS, key=user_setting_key)
