"""
Schéma de paramètres Composer — inspecteur contextuel du volet (compose-panel).

Params éditables per-item : `model` (le type music/sfx en est dérivé) + `duration`, et **format/qualité
de fichier via la BRIQUE COMMUNE** (output_format_params_for_app : domaine audio + early-binding déduits
d'APP_CATALOG). On garde les champs compose existants (id=) ; câblage via initFromSchema (panel dom_id-aware).
cardSettings générique lit les data-model/data-duration de la racine de card.
"""
from wama.common.utils.param_schema import Param, schema_to_dicts
from wama.common.utils.output_formats import output_format_params_for_app
from wama.composer.utils.model_config import COMPOSER_MODELS

PANEL = ("panel",)
PANEL_ITEM = ("panel", "item")

PARAMS = [
    # `choices` depuis COMPOSER_MODELS (même source que le <select> legacy : label = description
    # courte) → la MODALE est générée par WamaParams (context 'item', P1) ; le volet garde son
    # select serveur (#modelSelect, initFromSchema lit/applique par dom_id sans re-rendre).
    Param(name="model", type="select", label="Modèle", icon="fa-music",
          dom_id={"panel": "modelSelect", "item": "settingsModel"}, contexts=PANEL_ITEM,
          choices=[(mid, cfg['description']) for mid, cfg in COMPOSER_MODELS.items()]),
    Param(name="duration", type="range", label="Durée (s)", icon="fa-clock", min=10, max=600, step=5,
          dom_id={"panel": "durationSlider", "item": "settingsDuration"}, contexts=PANEL_ITEM),
]

# Format + qualité de sortie depuis la brique commune (audio, early-binding auto via le catalogue).
PARAMS += output_format_params_for_app(
    "composer",
    contexts=PANEL,
    dom_id_format={"panel": "output_format"},
    dom_id_quality={"panel": "output_quality"},
)

PARAMS_JSON = schema_to_dicts(PARAMS)
