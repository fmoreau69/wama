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
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from wama.imager.models import ImageGeneration


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
            # Options peuplées par le JS imager existant (catalogue model_manager, VRAM-aware) ;
            # pas d'endpoint générique → options_source laissé vide, bridge par dom_id legacy.
        ),
        "negative_prompt": dict(
            type="textarea", label="Prompt négatif", icon="fa-ban",
            dom_id={"item": "settings_negative_prompt"},
            help="Ce qu'il faut éviter dans l'image.",
        ),
        "num_images": dict(
            type="select", label="Nombre d'images", icon="fa-images",
            dom_id={"item": "settings_num_images"},
            choices=[("1", "1"), ("2", "2"), ("3", "3"), ("4", "4")],
        ),
        "steps": dict(
            type="range", label="Steps", icon="fa-shoe-prints",
            dom_id={"item": "settings_steps"}, min=1, max=100, step=1,
            help="Nombre d'étapes de diffusion.",
        ),
        "guidance_scale": dict(
            type="range", label="Guidance scale", icon="fa-sliders-h",
            dom_id={"item": "settings_guidance_scale"}, min=1, max=20, step=0.5,
            help="À quel point suivre le prompt.",
        ),
        "seed": dict(
            type="number", label="Seed", icon="fa-dice",
            dom_id={"item": "settings_seed"},
            help="Graine aléatoire (vide = aléatoire).",
        ),
        "image_strength": dict(
            type="range", label="Force de l'image de référence", icon="fa-image",
            dom_id={"item": "settings_image_strength"}, min=0, max=1, step=0.05,
            advanced=True,
            help="Influence de l'image de référence (img2img / style). 0=ignorer, 1=copier.",
        ),
        "upscale": dict(
            type="toggle", label="Upscaler la sortie", icon="fa-expand",
            dom_id={"item": "settings_upscale"}, advanced=True,
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
        ),
        "negative_prompt": dict(
            type="textarea", label="Prompt négatif", icon="fa-ban",
            dom_id={"item": "video_settings_negative_prompt"},
        ),
        "video_resolution": dict(
            type="select", label="Résolution", icon="fa-expand",
            dom_id={"item": "video_settings_resolution"},
        ),
        "video_duration": dict(
            type="range", label="Durée (s)", icon="fa-clock",
            dom_id={"item": "video_settings_duration"}, min=1, max=15, step=1,
        ),
        "video_fps": dict(
            type="number", label="FPS", icon="fa-tachometer-alt",
            dom_id={"item": "video_settings_fps"}, min=8, max=30, step=1,
        ),
        "seed": dict(
            type="number", label="Seed", icon="fa-dice",
            dom_id={"item": "video_settings_seed"},
            help="Graine aléatoire (vide = aléatoire).",
        ),
    },
)


IMAGE_PARAMS_JSON = schema_to_dicts(IMAGE_PARAMS)
VIDEO_PARAMS_JSON = schema_to_dicts(VIDEO_PARAMS)
