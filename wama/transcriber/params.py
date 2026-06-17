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
        "backend",
        "hotwords",
        "enable_diarization",
        "preprocess_audio",
        "generate_summary",
        "summary_type",
        "verify_coherence",
        "temperature",
        "max_tokens",
    ],
    overrides={
        "backend": dict(
            type="select", options_source="backends", label="Moteur de transcription",
            help="« auto » choisit le meilleur moteur disponible.",
        ),
        "hotwords": dict(
            type="textarea", label="Mots-clés (hotwords)",
            help="Termes métier à favoriser (un par ligne ou séparés par des virgules).",
        ),
        "enable_diarization": dict(label="Diarisation des locuteurs"),
        "preprocess_audio": dict(
            label="Prétraitement audio (débruitage IA)",
            help="DeepFilterNet avant transcription. Par défaut désactivé.",
        ),
        "generate_summary": dict(label="Générer un résumé (LLM)"),
        "summary_type": dict(type="radio", label="Type de résumé", show_if="generate_summary"),
        "verify_coherence": dict(label="Vérifier la cohérence (LLM)"),
        "temperature": dict(label="Température", min=0, max=1, step=0.1, advanced=True),
        "max_tokens": dict(label="Tokens max", min=1, advanced=True),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)
