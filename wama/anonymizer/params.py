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
    toggle à rendu `pills=["YOLO","SAM3"]` (sélecteur segmenté, valeur booléenne inchangée).

La modale ⚙ est SECTIONNÉE par `GROUPS` (ParamGroup) pour matcher les sections du volet droit —
voir le commentaire au-dessus de GROUPS.
"""
from wama.common.utils.param_schema import (
    ParamGroup, derive_from_model, groups_to_dicts, schema_to_dicts,
)
from wama.anonymizer.models import Media


# Groupes de la modale ⚙ — CALQUÉS sur les sections du volet droit (la « bonne représentation ») :
# Mode de détection → Quoi flouter (YOLO) | SAM3 → Comment flouter → Quoi afficher → Sortie.
# Les champs advanced SANS groupe tombent dans le groupe implicite « Avancé » replié (WamaParams).
GROUPS = [
    ParamGroup("mode", "Mode de détection", icon="fa-bullseye"),
    ParamGroup("yolo", "Quoi flouter (YOLO)", icon="fa-eye-slash",
               show_if={"field": "use_sam3", "equals": False}),
    ParamGroup("sam3", "SAM3 — prompt texte", icon="fa-wand-magic-sparkles",
               show_if={"field": "use_sam3", "equals": True}),
    ParamGroup("comment", "Comment flouter", icon="fa-droplet", columns=2),
    ParamGroup("afficher", "Quoi afficher", icon="fa-eye", columns=2),
    ParamGroup("sortie", "Sortie", icon="fa-file-export", columns=2),
]


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
        # ── Segmentation ── (consommé par save_media_settings/tasks : le schéma est la
        # source, un champ consommé mais non déclaré y était invisible — leçon converter)
        "use_segmentation",
        # ── Quoi afficher ──
        "show_preview", "show_boxes", "show_labels", "show_conf",
        # ── Format de sortie ──
        "output_format", "output_quality",
    ],
    overrides={
        "use_sam3": dict(
            # Sélecteur segmenté [YOLO | SAM3] comme le volet droit (label vide : le titre du
            # groupe « Mode de détection » porte le sens ; la valeur reste booléenne).
            type="toggle", label="", group="mode",
            pills=[{"label": "YOLO (Classes)", "icon": "fa-image"},
                   {"label": "SAM3 (Prompt)", "icon": "fa-comment-dots"}],
            icon="fa-wand-magic-sparkles",
            help="SAM3 : segmentation par prompt texte au lieu des classes YOLO.",
            chip=True, chip_label="SAM3",
        ),
        "sam3_prompt": dict(
            type="textarea", label="Prompt SAM3", icon="fa-comment-dots",
            dom_id={"panel": "user_setting_sam3_prompt"}, group="sam3",
            show_if={"field": "use_sam3", "equals": True},
            help='Ex. « blur all faces and license plates ».',
        ),
        "model_to_use": dict(
            type="select", label="Modèle YOLO", icon="fa-microchip",
            dom_id={"panel": "user_setting_model_to_use"}, group="yolo",
            show_if={"field": "use_sam3", "equals": False},
            chip=True,
            # Options peuplées par le JS anonymizer (modèles YOLO découverts) — bridge par dom_id legacy.
            help="Modèle de détection YOLO (vide = auto selon la précision).",
        ),
        "precision_level": dict(
            type="range", label="Niveau de précision", icon="fa-gauge-high",
            dom_id={"panel": "user_setting_precision_level"}, min=0, max=100, step=1,
            help="0=Rapide · 50=Équilibré · 100=Précis (lent).",
            chip=True, group="yolo",
        ),
        "detection_threshold": dict(
            type="range", label="Seuil de détection", icon="fa-crosshairs",
            dom_id={"panel": "user_setting_detection_threshold"}, min=0, max=1, step=0.05,
            group="comment",
        ),
        "blur_ratio": dict(
            type="range", label="Intensité du flou", icon="fa-droplet",
            dom_id={"panel": "user_setting_blur_ratio"}, min=1, max=100, step=1,
            group="comment",
        ),
        "rounded_edges": dict(
            type="number", label="Bords arrondis", icon="fa-border-top-left",
            min=0, max=50, step=1, advanced=True,
        ),
        # roi_enlargement / progressive_blur : advanced=True mais AFFICHÉS dans « Comment
        # flouter » comme au volet droit — le groupe explicite prime sur le repli Avancé.
        "roi_enlargement": dict(
            type="range", label="Agrandissement de la zone", icon="fa-up-right-and-down-left-from-center",
            dom_id={"panel": "user_setting_roi_enlargement"}, min=1.0, max=2.0, step=0.05,
            advanced=True, group="comment",
        ),
        "progressive_blur": dict(
            type="range", label="Flou progressif", icon="fa-chart-line",
            dom_id={"panel": "user_setting_progressive_blur"}, min=0, max=100, step=1,
            advanced=True, group="comment",
        ),
        "interpolate_detections": dict(
            type="toggle", label="Interpoler les détections manquantes", icon="fa-wave-square",
            advanced=True, chip=True, chip_label="Interpolation",
        ),
        "max_interpolation_frames": dict(
            type="number", label="Frames max à interpoler", icon="fa-film",
            min=1, max=60, step=1, advanced=True,
            show_if={"field": "interpolate_detections", "equals": True},
        ),
        "use_segmentation": dict(
            type="toggle", label="Segmentation fine (contours)", icon="fa-draw-polygon",
            help="Masque au contour de l'objet plutôt qu'au rectangle détecté.",
            advanced=True, chip=True, chip_label="Segmentation",
        ),
        "show_preview": dict(type="toggle", label="Afficher l'aperçu", icon="fa-eye",
                             advanced=True, group="afficher"),
        "show_boxes": dict(type="toggle", label="Afficher les boîtes", icon="fa-vector-square",
                           advanced=True, group="afficher"),
        "show_labels": dict(type="toggle", label="Afficher les libellés", icon="fa-tag",
                            advanced=True, group="afficher"),
        "show_conf": dict(type="toggle", label="Afficher la confiance", icon="fa-percent",
                          advanced=True, group="afficher"),
        "output_format": dict(type="select", label="Format de sortie", icon="fa-file-export",
                              advanced=True, group="sortie"),
        "output_quality": dict(type="select", label="Qualité de sortie", icon="fa-gem",
                               advanced=True, group="sortie"),
    },
)


PARAMS_JSON = schema_to_dicts(PARAMS)
GROUPS_JSON = groups_to_dicts(GROUPS)
