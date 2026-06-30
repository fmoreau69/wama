"""
Schéma de paramètres Describer — SOURCE UNIQUE pour les deux surfaces :
inspecteur (volet droit, context "panel") et modale item/batch (context "item"/"batch").

Dérivé du modèle `Description` (les choix de select viennent des `choices` du modèle) puis rendu
par `WamaParams.render(container, PARAMS_JSON, {context})`. Les `dom_id` reprennent les IDs LEGACY
de chaque surface → JS existant + apparence préservés (migration sans casse).

Voir le gabarit `transcriber/params.py` et `common/utils/param_schema.py`.
"""
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from wama.describer.models import Description

PARAMS = derive_from_model(
    Description,
    include=["output_style", "output_language", "max_length", "generate_summary", "verify_coherence"],
    overrides={
        "output_style": dict(
            type="select", label="Format de sortie", icon="fa-align-left",
            dom_id={"panel": "output_style", "item": "settingsOutputFormat"},
            help="Niveau de détail de la description générée.",
        ),
        "output_language": dict(
            type="select", label="Langue de sortie", icon="fa-language",
            dom_id={"panel": "output_language", "item": "settingsOutputLanguage"},
        ),
        "max_length": dict(
            type="range", label="Longueur max", icon="fa-text-width",
            min=100, max=2000, step=50,
            dom_id={"panel": "max_length", "item": "settingsMaxLength"},
            help="Longueur maximale (caractères) de la description.",
        ),
        "generate_summary": dict(
            type="toggle", label="Générer un résumé LLM", icon="fa-file-lines",
            dom_id={"panel": "globalGenerateSummary", "item": "settingsGenerateSummary"},
        ),
        "verify_coherence": dict(
            type="toggle", label="Vérifier la cohérence", icon="fa-spell-check",
            dom_id={"panel": "globalVerifyCoherence", "item": "settingsVerifyCoherence"},
        ),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)
