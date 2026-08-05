"""
Schéma de paramètres Imager — SOURCE UNIQUE pour la modale « Paramètres » d'un item
(context "item") et, à terme, le volet inspecteur (context "panel").

Imager a DEUX domaines (image / vidéo), chacun avec sa modale item :
  • IMAGE_PARAMS  → modale #generationSettingsModal (form #settingsForm, IDs `settings_*`)
  • VIDEO_PARAMS  → modale #videoSettingsModal    (form #videoSettingsForm, IDs `video_settings_*`)
Cette scission suit le schéma domaines→modes (`common/utils/app_modes.py`, générateur WamaModes) et
le double-schéma d'Enhancer (MEDIA / AUDIO).

Dérivé du modèle `ImageGeneration`. Rendu (P1/P2) par `WamaParams.render(container, JSON, {context})`.
Les `dom_id` reprennent les IDs LEGACY de chaque modale → JS/apparence existants préservés lors du
portage. Gabarit : reader/params.py, transcriber/params.py.

Exceptions app-spécifiques VOLONTAIREMENT hors schéma (widgets bespoke, pas des champs scalaires) :
  • `prompt` : entrée primaire de la card (pas un « réglage »).
  • résolution image : widget à PRÉSETS (`#settings_resolution` → width/height cachés calculés par
    `MODEL_RESOLUTION_CONFIG`), pas un champ modèle direct → reste géré par le JS imager.
  • `generation_mode` : c'est le MODE (badge lecture seule dans la modale) → piloté par WamaModes,
    pas un paramètre éditable.
Descriptions de modèle : déjà rendues app-side (`.model-description` + `model-select-with-tooltip`) ;
`help_source`/`help_fallback` seront branchés au câblage P1 si on unifie sur WamaModelHelp.
"""
from wama.common.utils.param_schema import (
    ParamGroup, derive_from_model, groups_to_dicts, schema_to_dicts,
)
from wama.imager.models import ImageGeneration


# ── Groupes de la modale ⚙ (ParamGroup, brique commune) ──────────────────────
# Sections communes aux deux domaines : Modèle → Qualité → Cadrage/Sortie.
# La RÉSOLUTION image reste HORS schéma (widget à présets par modèle, cf. docstring) :
# elle est rendue par la zone d'app de la modale, dans le groupe 'sortie'.
IMAGE_GROUPS = [
    ParamGroup("modele", "Modèle", icon="fa-microchip"),
    ParamGroup("qualite", "Qualité de génération", icon="fa-sliders", columns=2),
    ParamGroup("sortie", "Sortie", icon="fa-image", columns=2),
]

VIDEO_GROUPS = [
    ParamGroup("modele", "Modèle", icon="fa-microchip"),
    ParamGroup("qualite", "Qualité de génération", icon="fa-sliders", columns=2),
    ParamGroup("sortie", "Sortie vidéo", icon="fa-film", columns=2),
]


# ── Domaine IMAGE ────────────────────────────────────────────────────────────
IMAGE_PARAMS = derive_from_model(
    ImageGeneration,
    include=[
        "model", "negative_prompt", "num_images",
        "steps", "guidance_scale", "seed",
        "image_strength", "upscale",
    ],
    overrides={
        "model": dict(
            type="select", label="Modèle", icon="fa-microchip",
            dom_id={"item": "settings_model", "panel": "imgDefaultModel"},
            group="modele",
            help="Modèle de génération (Auto = tirage VRAM-aware au lancement).",
            # Options peuplées par settings_modal.js depuis les MÊMES groupes de catalogue
            # que la card d'entrée (Images / Logos / Vidéos) — pas de 2ᵉ liste.
        ),
        "negative_prompt": dict(
            type="textarea", label="Prompt négatif", icon="fa-ban",
            dom_id={"item": "settings_negative_prompt"},
            group="modele",
            help="Ce qu'il faut éviter dans l'image.",
        ),
        "num_images": dict(
            type="select", label="Nombre d'images", icon="fa-images",
            dom_id={"item": "settings_num_images"},
            group="sortie",
            choices=[("1", "1"), ("2", "2"), ("3", "3"), ("4", "4")],
            chip=True, chip_label="img",
            help="Nombre d'images à générer en une passe.",
        ),
        "steps": dict(
            type="range", label="Steps", icon="fa-shoe-prints",
            dom_id={"item": "settings_steps"}, min=1, max=100, step=1,
            group="qualite",
            help="Nombre d'étapes de diffusion.",
            chip=True, chip_label="steps",
        ),
        "guidance_scale": dict(
            type="range", label="Guidance scale", icon="fa-sliders-h",
            dom_id={"item": "settings_guidance_scale"}, min=1, max=20, step=0.5,
            group="qualite",
            help="À quel point suivre le prompt.",
        ),
        "seed": dict(
            type="number", label="Seed", icon="fa-dice",
            dom_id={"item": "settings_seed"},
            group="qualite",
            help="Graine aléatoire (vide = aléatoire).",
        ),
        "image_strength": dict(
            type="range", label="Force de l'image de référence", icon="fa-image",
            dom_id={"item": "settings_image_strength"}, min=0, max=1, step=0.05,
            group="qualite",
            advanced=True,
            help="Influence de l'image de référence (img2img / style). 0=ignorer, 1=copier.",
        ),
        "upscale": dict(
            type="toggle", label="Upscaler la sortie", icon="fa-expand",
            dom_id={"item": "settings_upscale"}, advanced=True,
            group="sortie",
            help="Agrandit l'image générée (×2).",
        ),
    },
)


# ── Domaine VIDÉO ────────────────────────────────────────────────────────────
VIDEO_PARAMS = derive_from_model(
    ImageGeneration,
    include=[
        "model", "negative_prompt",
        "video_resolution", "video_duration", "video_fps", "seed",
    ],
    overrides={
        "model": dict(
            type="select", label="Modèle vidéo", icon="fa-film",
            dom_id={"item": "video_settings_model", "panel": "vidDefaultModel"},
            group="modele",
        ),
        "negative_prompt": dict(
            type="textarea", label="Prompt négatif", icon="fa-ban",
            dom_id={"item": "video_settings_negative_prompt"},
            group="modele",
        ),
        "video_resolution": dict(
            type="select", label="Résolution", icon="fa-expand",
            dom_id={"item": "video_settings_resolution"},
            group="sortie",
        ),
        "video_duration": dict(
            type="range", label="Durée (s)", icon="fa-clock",
            dom_id={"item": "video_settings_duration"}, min=1, max=15, step=1,
            group="sortie",
            chip=True, chip_label="s",
        ),
        "video_fps": dict(
            type="number", label="FPS", icon="fa-tachometer-alt",
            dom_id={"item": "video_settings_fps"}, min=8, max=30, step=1,
            group="sortie",
            chip=True, chip_label="fps",
        ),
        "seed": dict(
            type="number", label="Seed", icon="fa-dice",
            dom_id={"item": "video_settings_seed"},
            help="Graine aléatoire (vide = aléatoire).",
            group="qualite",
        ),
    },
)


IMAGE_PARAMS_JSON = schema_to_dicts(IMAGE_PARAMS)
VIDEO_PARAMS_JSON = schema_to_dicts(VIDEO_PARAMS)
IMAGE_GROUPS_JSON = groups_to_dicts(IMAGE_GROUPS)
VIDEO_GROUPS_JSON = groups_to_dicts(VIDEO_GROUPS)
