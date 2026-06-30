"""
Schéma de paramètres Reader — SOURCE UNIQUE pour l'inspecteur (context "panel") et la modale BATCH
(context "batch"). Reader n'a pas de modale item → contexts = panel + batch.

Dérivé du modèle `ReadingItem` (backend/mode = TextChoices du modèle). Rendu par
`WamaParams.render(container, PARAMS_JSON, {context})`. Les `dom_id` reprennent les IDs LEGACY de
chaque surface → JS existant + apparence préservés. Gabarit : transcriber/params.py.
"""
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from wama.reader.models import ReadingItem

PARAMS = derive_from_model(
    ReadingItem,
    include=["backend", "mode", "language"],
    overrides={
        "backend": dict(
            type="select", label="Moteur OCR", icon="fa-microchip",
            dom_id={"panel": "backendSelect", "batch": "batchSettingsBackend", "item": "rSettings_backend"},
        ),
        "mode": dict(
            type="select", label="Mode de lecture", icon="fa-pen-nib",
            dom_id={"panel": "modeSelect", "batch": "batchSettingsMode", "item": "rSettings_mode"},
        ),
        "language": dict(
            type="text", label="Langue", icon="fa-language",
            dom_id={"panel": "languageInput", "batch": "batchSettingsLanguage", "item": "rSettings_language"},
            help="Optionnel (ex. fr, en). Auto-détection si vide.",
        ),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)
