"""
Schéma de paramètres Anonymizer — SOURCE UNIQUE pour le volet inspecteur (context "panel", =
réglages par défaut du panneau droit `user_setting_*`) et les réglages par-média (context "item").

Dérivé du modèle `Media`. Rendu (P1/P2) par `WamaParams.render(container, PARAMS_JSON, {context})`.
Les `dom_id` reprennent les IDs LEGACY du panneau droit → JS/AJAX `setting-button` + apparence
préservés lors du portage. Gabarit : reader/params.py, transcriber/params.py.

Deux `show_if` DÉCLARATIFS remplacent du masquage JS hardcodé (cf. [[feedback_ui_from_model_capabilities]]) :
  • SAM3 actif  → `sam3_prompt` visible, sélection de modèle YOLO (`model_to_use`) masquée ;
  • interpolation active → `max_interpolation_frames` visible.

Exceptions app-spécifiques VOLONTAIREMENT hors schéma (widgets bespoke) :
  • `classes2blur` : multi-sélection d'objets (modale à cases `#modal_classes2blur_*`) — pas un type
    scalaire du schéma (toggle|select|radio|text|textarea|number|range) → reste géré par le JS anonymizer.
  • `use_segmentation` : « déterminé automatiquement par le niveau de précision » → non éditable.
  • `use_sam3` : porté par un couple de radios `name="detection_mode"` (yolo/sam3) côté legacy ; ici
    exposé comme toggle (source de vérité booléenne du modèle) — le pont radio se fait au câblage.
"""
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from wama.anonymizer.models import Media


PARAMS = derive_from_model(
    Media,
    include=[
        # ── Quoi détecter ──
        "use_sam3", "sam3_prompt", "model_to_use",
        # ── Réglage de détection ──
        "precision_level", "detection_threshold",
        # ── Comment flouter ──
        "blur_ratio", "rounded_edges", "roi_enlargement", "progressive_blur",
        # ── Temporel (vidéo) ──
        "interpolate_detections", "max_interpolation_frames",
        # ── Quoi afficher ──
        "show_preview", "show_boxes", "show_labels", "show_conf",
        # ── Format de sortie ──
        "output_format", "output_quality",
    ],
    overrides={
        "use_sam3": dict(
            type="toggle", label="Utiliser SAM3 (prompt texte)", icon="fa-wand-magic-sparkles",
            help="Segmentation par prompt texte au lieu des classes YOLO.",
        ),
        "sam3_prompt": dict(
            type="textarea", label="Prompt SAM3", icon="fa-comment-dots",
            dom_id={"panel": "user_setting_sam3_prompt"},
            show_if={"field": "use_sam3", "equals": True},
            help='Ex. « blur all faces and license plates ».',
        ),
        "model_to_use": dict(
            type="select", label="Modèle YOLO", icon="fa-microchip",
            dom_id={"panel": "user_setting_model_to_use"},
            show_if={"field": "use_sam3", "equals": False},
            # Options peuplées par le JS anonymizer (modèles YOLO découverts) — bridge par dom_id legacy.
            help="Modèle de détection YOLO (vide = auto selon la précision).",
        ),
        "precision_level": dict(
            type="range", label="Niveau de précision", icon="fa-gauge-high",
            dom_id={"panel": "user_setting_precision_level"}, min=0, max=100, step=1,
            help="0=Rapide · 50=Équilibré · 100=Précis (lent).",
        ),
        "detection_threshold": dict(
            type="range", label="Seuil de détection", icon="fa-crosshairs",
            dom_id={"panel": "user_setting_detection_threshold"}, min=0, max=1, step=0.05,
        ),
        "blur_ratio": dict(
            type="range", label="Intensité du flou", icon="fa-droplet",
            dom_id={"panel": "user_setting_blur_ratio"}, min=1, max=100, step=1,
        ),
        "rounded_edges": dict(
            type="number", label="Bords arrondis", icon="fa-border-top-left",
            min=0, max=50, step=1, advanced=True,
        ),
        "roi_enlargement": dict(
            type="range", label="Agrandissement de la zone", icon="fa-up-right-and-down-left-from-center",
            dom_id={"panel": "user_setting_roi_enlargement"}, min=1.0, max=2.0, step=0.05,
            advanced=True,
        ),
        "progressive_blur": dict(
            type="range", label="Flou progressif", icon="fa-chart-line",
            dom_id={"panel": "user_setting_progressive_blur"}, min=0, max=100, step=1,
            advanced=True,
        ),
        "interpolate_detections": dict(
            type="toggle", label="Interpoler les détections manquantes", icon="fa-wave-square",
            advanced=True,
        ),
        "max_interpolation_frames": dict(
            type="number", label="Frames max à interpoler", icon="fa-film",
            min=1, max=60, step=1, advanced=True,
            show_if={"field": "interpolate_detections", "equals": True},
        ),
        "show_preview": dict(type="toggle", label="Afficher l'aperçu", icon="fa-eye", advanced=True),
        "show_boxes": dict(type="toggle", label="Afficher les boîtes", icon="fa-vector-square", advanced=True),
        "show_labels": dict(type="toggle", label="Afficher les libellés", icon="fa-tag", advanced=True),
        "show_conf": dict(type="toggle", label="Afficher la confiance", icon="fa-percent", advanced=True),
        "output_format": dict(type="select", label="Format de sortie", icon="fa-file-export", advanced=True),
        "output_quality": dict(type="select", label="Qualité de sortie", icon="fa-gem", advanced=True),
    },
)


PARAMS_JSON = schema_to_dicts(PARAMS)
