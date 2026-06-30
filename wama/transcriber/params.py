"""
Schéma de paramètres du Transcriber — SOURCE UNIQUE pour la modale (item/batch) et le
volet inspecteur (card/batch/file). La structure (type, choices, défaut) est DÉRIVÉE du
modèle `Transcript` ; seule la surcouche UI (libellés, options dynamiques, visibilité
conditionnelle, basique/avancé) est déclarée ici. Voir `common/utils/param_schema.py`.
"""

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
        "hotwords",
        "preprocess_audio",
        "enable_diarization",
        "generate_summary",
        "summary_type",
        "verify_coherence",
    ],
    overrides={
        # dom_id = ID legacy SCOPÉ PAR CONTEXTE → migration sans casse : le volet (panel) et la
        # modale (item) gardent CHACUN leurs IDs/n​oms existants, donc le JS de chaque surface
        # continue de marcher, et on rend les deux depuis CE schéma unique sans collision d'ID.
        "backend": dict(
            type="select", options_source="backends", label="Moteur de transcription",
            icon="fa-microchip", dom_id={"panel": "backendSelect", "item": "settingsBackend"},
            # « auto » rendu en statique (1ʳᵉ option) ; loadBackendsAsync append les modèles ensuite.
            choices=[("auto", "Auto (meilleur disponible)")],
            help="",   # pas d'aide statique : le descriptif du moteur (backendHelp) s'affiche juste dessous
        ),
        "hotwords": dict(
            type="textarea", label="Mots-clés contextuels", icon="fa-tags",
            dom_id={"panel": "hotwordsInput", "item": "settingsHotwords"},
            help="Séparés par des virgules",
        ),
        "preprocess_audio": dict(
            label="Prétraitement audio", icon="fa-wand-magic-sparkles",
            dom_id={"panel": "preprocessingToggle", "item": "settingsPreprocess"},
            help_html='Débruitage IA (DeepFilterNet) + 16 kHz mono<br>'
                      '<a href="#" class="text-info text-decoration-none" data-bs-toggle="modal" '
                      'data-bs-target="#preprocessingModal"><i class="fas fa-circle-question"></i> En savoir plus</a>',
        ),
        "enable_diarization": dict(label="Identifier les locuteurs", icon="fa-users",
            dom_id={"panel": "diarizationToggle", "item": "settingsDiarization"},
            help="Séparation des locuteurs (pyannote)"),
        "generate_summary": dict(label="Générer un résumé", icon="fa-file-lines",
            dom_id={"panel": "globalGenerateSummary", "item": "settingsGenerateSummary"}),
        "summary_type": dict(
            type="radio", label="", icon="fa-list", show_if="generate_summary",
            radio_name={"panel": "globalSummaryType", "item": "summary_type"}, inline=True,
            choices=[("structured", "Structuré"), ("meeting", "Réunion")],
        ),
        "verify_coherence": dict(label="Vérifier la cohérence", icon="fa-check-double",
            dom_id={"panel": "globalVerifyCoherence", "item": "settingsVerifyCoherence"},
            help="Score + correction proposée côte à côte"),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)
