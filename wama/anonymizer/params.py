"""
Schéma de paramètres Anonymizer — SOURCE UNIQUE pour le volet inspecteur (context "panel", =
réglages par défaut du panneau droit `user_setting_*`) et les réglages par-média (context "item").

Dérivé du modèle `Media`. Rendu (P1/P2) par `WamaParams.render(container, PARAMS_JSON, {context})`.
Les `dom_id` reprennent les IDs LEGACY du panneau droit → JS/AJAX `setting-button` + apparence
préservés lors du portage. Gabarit : reader/params.py, transcriber/params.py.

Deux `show_if` DÉCLARATIFS remplacent du masquage JS hardcodé (cf. [[feedback_ui_from_model_capabilities]]) :
  • mode Description → `sam3_prompt` visible ; mode Classes → les classes à flouter ;
  • interpolation active → `max_interpolation_frames` visible.

MODE (2026-09-27, `app_modes`, `mode_param`) : `target_mode` dit COMMENT on désigne ce qu'il faut
flouter — des classes, ou une description. Il BORNE le menu de modèles (`options_mode`) : en
Classes, les modèles à classes ; en Description, ceux qui consomment un prompt. Le résultat
(boîte ou contour) reste au curseur rapide ↔ qualité en « auto », au choix du modèle sinon —
le menu est GROUPÉ par tâche du catalogue (Détection / Segmentation).

Exceptions app-spécifiques VOLONTAIREMENT hors schéma (widgets bespoke) :
  • `classes2blur` : multi-sélection d'objets (modale à cases `#modal_classes2blur_*`) — pas un type
    scalaire du schéma (toggle|select|radio|text|textarea|number|range) → reste géré par le JS anonymizer.
  • `use_segmentation` : « déterminé automatiquement par le niveau de précision » → non éditable.
  • (`use_sam3`, booléen « YOLO/SAM3 », remplacé par le mode `target_mode` le 2026-09-27.)

La modale ⚙ est SECTIONNÉE par `GROUPS` (ParamGroup) pour matcher les sections du volet droit —
voir le commentaire au-dessus de GROUPS.
"""
from wama.common.utils.app_modes import options_mode_for
from wama.common.utils.auto_model import intent_param
from wama.common.utils.output_formats import get_output_formats, get_output_qualities
from wama.common.utils.param_schema import (
    ParamGroup, derive_from_model, groups_to_dicts, schema_to_dicts,
)
from wama.anonymizer.models import Media


# Formats de sortie — BRIQUE COMMUNE (output_formats), en OPTGROUPS car l'app est BI-DOMAINE
# (un Media est image OU vidéo ; la brique `output_format_params_for_app` ne sait déduire qu'UN
# domaine du catalogue). 'original'/'input' = valeurs du pipeline (`_apply_anonymizer_output_format`).
_FORMAT_GROUPS = [
    ("Général", [("original", "Original (inchangé)"),
                 ("input", "Format du fichier source")]),
    ("Vidéo", [c for c in get_output_formats("video") if c[0] != "original"]),
    ("Image", [c for c in get_output_formats("image") if c[0] != "original"]),
]


# Groupes de la modale ⚙ — CALQUÉS sur les sections du volet droit (la « bonne représentation ») :
# Mode de détection → Quoi flouter (YOLO) | SAM3 → Comment flouter → Quoi afficher → Sortie.
# Les champs advanced SANS groupe tombent dans le groupe implicite « Avancé » replié (WamaParams).
GROUPS = [
    ParamGroup("mode", "Quoi flouter", icon="fa-bullseye"),
    ParamGroup("classes", "Classes à flouter", icon="fa-eye-slash",
               show_if={"field": "target_mode", "equals": "classes"}),
    ParamGroup("description", "Description", icon="fa-comment-dots",
               show_if={"field": "target_mode", "equals": "description"}),
    ParamGroup("model", "Modèle", icon="fa-microchip"),
    ParamGroup("comment", "Comment flouter", icon="fa-droplet", columns=2),
    ParamGroup("afficher", "Quoi afficher", icon="fa-eye", columns=2),
    ParamGroup("sortie", "Sortie", icon="fa-file-export", columns=2),
]


PARAMS = derive_from_model(
    Media,
    include=[
        # ── Quoi détecter ──
        "target_mode", "sam3_prompt", "model_to_use",
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
        # Le MODE de l'élément : rendu par `WamaModes` au volet (switch généré d'`app_modes`),
        # en choix à deux positions dans la modale.
        "target_mode": dict(
            type="radio", label="", group="mode", inline=True,
            icon="fa-bullseye", chip=True, chip_label="Désignation",
            help="Classes : une liste d'objets à flouter. Description : ce qu'il faut flouter, "
                 "décrit en texte.",
        ),
        "sam3_prompt": dict(
            type="textarea", label="Prompt SAM3", icon="fa-comment-dots",
            dom_id={"panel": "user_setting_sam3_prompt"}, group="description",
            show_if={"field": "target_mode", "equals": "description"},
            help='Ex. « blur all faces and license plates ».',
        ),
        # Menu de modèle tiré du CATALOGUE (2026-09-27) : les tâches qui localisent ce qu'on
        # floute (pose, classification et boîtes orientées n'y ont pas de sens), bornées par le
        # MODE, groupées par tâche. « auto » : le curseur ci-dessous tranche la taille et la
        # segmentation, la couverture des classes choisit le(s) modèle(s) au lancement.
        "model_to_use": dict(
            type="select", label="Modèle", icon="fa-microchip",
            dom_id={"panel": "user_setting_model_to_use"}, group="model",
            options_source="catalog",
            options_query={"source": "anonymizer", "task": "detect,segment"},
            options_mode=options_mode_for("anonymizer", "image_video"),
            options_group="task", options_auto=True,
            help_source="anonymizer",
            chip=True, default="auto",
            help="Automatique : choisi au lancement selon le curseur et les classes.",
        ),
        # ⚠ step ALIGNÉ SUR LE RÉEL (2026-08-19). Le curseur déclarait 101 positions alors que
        # le moteur n'en distingue que CINQ : `get_model_size_from_precision`
        # (utils/model_selector.py:559) seuille à 20/40/60/80 → n/s/m/l/x, plus un seuil
        # BINAIRE à 50 (`should_use_segmentation`). 75 et 77 donnent donc le MÊME traitement.
        # Le volet déclarait 5 et le schéma 1 : la valeur d'une card était quantifiée
        # différemment selon la surface. À terme, 5 positions nommées (10/30/50/70/90 =
        # un palier par taille de modèle) diraient la vérité — décision UX à prendre.
        # RALLIÉ au curseur commun (2026-09-02, route F4b) : même FORME utilisateur partout
        # (type='intent' — zones Rapide/Équilibré/Qualité, tricolore). La DÉCLINAISON
        # (n/s/m/l/x aux seuils 20/40/60/80, seuil binaire 50 pour la segmentation) est
        # REMONTÉE AU COMMUN le 2026-09-20 (chantier C, décision Fabien du 15/09) :
        # `model_coverage.size_for_intent` / `segmentation_for_intent`, inchangée au cran près
        # (`get_model_size_from_precision` n'est plus qu'un alias). `step=5` CONSERVÉ : 5
        # paliers réels, un pas de 1 afficherait 101 positions pour 5 résultats (2026-08-19).
        "precision_level": intent_param(
            dom_id={"panel": "user_setting_precision_level"}, step=5,
            help="5 paliers effectifs (n/s/m/l/x) ; à partir de 50, segmentation fine.",
            chip=True, group="model",
        ),
        "detection_threshold": dict(
            type="range", label="Seuil de détection", icon="fa-crosshairs",
            dom_id={"panel": "user_setting_detection_threshold"}, min=0, max=1, step=0.05,
            group="comment",
        ),
        # ⚠ step=2 N'ÉTAIT PAS ARBITRAIRE (compris le 2026-08-19) : `blur_ratio` est la TAILLE
        # DE NOYAU d'un flou gaussien, qui DOIT être impaire — `normalize_blur_ratio`
        # (core/blur_utils.py:234) force le +1 sur une valeur paire. Avec step=1 l'utilisateur
        # choisissait 42 et le moteur appliquait 43 : l'affichage mentait. Le pas de 2 depuis
        # min=1 ne produit que des valeurs RÉELLEMENT applicables. Le schéma s'aligne donc sur
        # le volet, et non l'inverse. `max` 49→100 (arbitrage Fabien : la borne 49 n'était pas
        # justifiée ; un noyau de 99 reste valide, seul le coût CPU croît).
        "blur_ratio": dict(
            type="range", label="Intensité du flou", icon="fa-droplet",
            dom_id={"panel": "user_setting_blur_ratio"}, min=1, max=99, step=2,
            help="Taille du noyau gaussien (impaire).",
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
            # Le réglage dit ce qu'il fait depuis le 2026-10-05 : il était plafonné en silence à
            # 0,5 s de vidéo (50 valait 7 à 15 i/s, card #1026).
            help="Un trou de détection d'au plus ce nombre d'images est comblé, entre deux "
                 "détections du même objet (même piste, ou même place).",
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
        # ⚠ Sans options déclarées, ces deux selects rendaient VIDES dans la modale
        # (CharField sans choices → derive_from_model n'a rien à offrir) — constat
        # Fabien 14/08 (« pas accès aux format/qualité »). Options = brique commune.
        "output_format": dict(type="select", label="Format de sortie", icon="fa-file-export",
                              advanced=True, group="sortie", option_groups=_FORMAT_GROUPS,
                              help="Conversion inline après floutage (brique converter). "
                                   "« Original » = format produit par le pipeline."),
        "output_quality": dict(type="select", label="Qualité de sortie", icon="fa-gem",
                               advanced=True, group="sortie",
                               choices=get_output_qualities()),
    },
)


PARAMS_JSON = schema_to_dicts(PARAMS)
GROUPS_JSON = groups_to_dicts(GROUPS)


# ── Réglages UTILISATEUR du volet — brique commune `user_settings` (2026-09-27) ─────────────
# Le volet EST la surface des défauts de l'utilisateur, et un média NAÎT avec eux (modèle
# événementiel, ROADMAP §23.2quater). Lire, garder, remettre à zéro : `user_settings.*_panel_*`.
# Remplace les tables `UserSettings` (défauts recopiés à la main du modèle `Media`) et
# `GlobalSettings` (défauts semés par une liste en dur) : un défaut ne vit plus qu'à UN endroit,
# la colonne de `Media` dont le schéma le dérive. Clé de stockage = le NOM du param.
from wama.common.utils.param_schema import panel_defaults, panel_name_key  # noqa: E402
from wama.anonymizer.models import default_classes2blur  # noqa: E402

user_setting_key = panel_name_key
USER_SETTINGS_DEFAULTS = panel_defaults(PARAMS, key=user_setting_key)

#: `classes2blur` est hors schéma (multi-sélection à cases, cf. en-tête) mais c'est un réglage
#: du volet comme les autres : même stockage, même naissance de l'élément.
CLASSES_SETTING = 'classes2blur'
USER_SETTINGS_EXTRA = {CLASSES_SETTING: default_classes2blur()}


def clean_classes(classes):
    """Une liste postée de classes à flouter, assainie (mêmes règles que la tâche)."""
    from wama.anonymizer.tasks import _classes_saines
    return _classes_saines(classes) if isinstance(classes, list) else default_classes2blur()


#: Tout ce que la brique commune doit savoir des réglages du volet de l'anonymizer.
PANEL_SETTINGS = dict(key=user_setting_key, extra=USER_SETTINGS_EXTRA,
                      clean={CLASSES_SETTING: clean_classes})
