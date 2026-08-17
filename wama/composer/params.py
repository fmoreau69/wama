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
# Batch = les champs que `views.batch_update` ACCEPTE (model/duration/format/qualité) —
# le prompt reste per-item. Modale batch DÉDIÉE (contrat reader, 17/08) rendue de ce schéma.
PANEL_ITEM_BATCH = ("panel", "item", "batch")

PARAMS = [
    # Ordre = celui du VOLET (Type[switch statique] → Modèle → Durée → Prompt → Format → Qualité).
    # `option_groups` depuis COMPOSER_MODELS (même source que le <select> legacy), groupés par
    # MODE Musique/Bruitages — miroir des optgroups du volet ; le JS masque le groupe non
    # pertinent selon le generation_type de l'item. Volet : select serveur (#modelSelect,
    # initFromSchema lit/applique par dom_id sans re-rendre) ; modale : rendue par WamaParams (P1).
    Param(name="model", type="select", label="Modèle", icon="fa-music", chip=True,
          dom_id={"panel": "modelSelect", "item": "settingsModel", "batch": "batchSettingsModel"},
          contexts=PANEL_ITEM_BATCH,
          option_groups=[
              # « auto-* » en tête de CHAQUE groupe (décision 2026-07-02 : pas de switch de type,
              # le type est dérivé du « modèle » choisi — l'auto respecte ce contrat par groupe).
              # Résolution à l'exécution : capacités catalogue + VRAM libre via select_model()
              # — cf. composer/utils/auto_model.py.
              ("🎵 Musique (MusicGen)", [("auto-music", "🧠 Choix automatique — le plus gros modèle "
                                          "musique tenant dans la VRAM libre au lancement")] +
                                        [(mid, cfg['description']) for mid, cfg in COMPOSER_MODELS.items()
                                         if cfg.get('type') == 'music']),
              ("⚡ Bruitages (AudioGen)", [("auto-sfx", "🧠 Choix automatique — le plus gros modèle "
                                           "bruitages tenant dans la VRAM libre au lancement")] +
                                         [(mid, cfg['description']) for mid, cfg in COMPOSER_MODELS.items()
                                          if cfg.get('type') != 'music']),
          ]),
    Param(name="duration", type="range", label="Durée", icon="fa-clock", min=10, max=600, step=5,
          unit="s", min_label="10s", max_label="10min", chip=True,
          dom_id={"panel": "durationSlider", "item": "settingsDuration",
                  "batch": "batchSettingsDuration"},
          contexts=PANEL_ITEM_BATCH),
    # Prompt éditable par item (modale seulement : le volet a sa zone de composition dédiée).
    Param(name="prompt", type="textarea", label="Prompt", icon="fa-pen",
          dom_id={"item": "settingsPrompt"}, contexts=("item",)),
]

# Format + qualité de sortie depuis la brique commune (audio, early-binding auto via le catalogue).
PARAMS += output_format_params_for_app(
    "composer",
    contexts=PANEL_ITEM_BATCH,
    dom_id_format={"panel": "output_format", "item": "settingsOutputFormat",
                   "batch": "batchSettingsOutputFormat"},
    dom_id_quality={"panel": "output_quality", "item": "settingsOutputQuality",
                    "batch": "batchSettingsOutputQuality"},
)

PARAMS_JSON = schema_to_dicts(PARAMS)
