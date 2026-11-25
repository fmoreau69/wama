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
from wama.common.utils.app_metadata import keywords_palette
from wama.common.utils.app_modes import options_mode_for
from wama.common.utils.auto_model import intent_param
from wama.common.utils.output_formats import output_format_params
from wama.common.utils.param_schema import (
    ParamGroup, derive_from_model, groups_to_dicts, schema_to_dicts,
)
from wama.anonymizer.models import Media
from wama.anonymizer.utils.model_config import MODEL_SPEC


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
    ParamGroup("qualify", "Qualification", icon="fa-palette", collapsed=True),
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
        "precision_level", "detection_threshold", "detection_decimation",
        # ── Qualification des objets (couleur, taille, profondeur — 2026-11-24) ──
        "qualify_objects", "qualify_depth",
        # ── Ce qu'on floute parmi ce qui est détecté ──
        "blur_skip_labels", "blur_skip_colors", "blur_skip_sizes", "blur_skip_planes",
        # ── Comment flouter ──
        "blur_mode", "blur_invert",
        "blur_ratio", "rounded_edges", "roi_enlargement", "progressive_blur",
        # ── Temporel (vidéo) ──
        "interpolate_detections", "max_interpolation_frames", "max_extrapolation_frames",
        # ── Segmentation ── (consommé par la route de réglages/tasks : le schéma est la
        # source, un champ consommé mais non déclaré y était invisible — leçon converter)
        "use_segmentation",
        # ── Quoi afficher ──
        "show_preview", "show_boxes", "show_labels", "show_conf",
        # ── Format de sortie : la brique COMMUNE, ajoutée après (`output_format_params`) ──
    ],
    overrides={
        # Le MODE de l'élément : rendu par `WamaModes` au volet (switch généré d'`app_modes`),
        # en choix à deux positions dans la modale.
        "target_mode": dict(
            type="radio", label="", group="mode", inline=True,
            icon="fa-bullseye", chip=True, chip_label="Désignation",
            help="Classes : une liste d'objets à flouter. Description : ce qu'il faut flouter, "
                 "décrit en texte.",
            # Ce que chaque réglage PÉRIME (`Param.stales`, 2026-10-05) : `ProcessSpec.watched`
            # s'en dérive (function_specs.py n'y garde que les champs hors schéma).
            stales=("detect",),
        ),
        # La DESCRIPTION (2026-11-24) : ce qu'il faut anonymiser, en langage naturel, dans la
        # langue de l'utilisateur. Le système la COMPREND (concepts anglais, `sam3_prompt_processed`,
        # montrés dans le champ à deux états) et CHOISIT qui cherche chaque concept — un détecteur
        # dédié quand un modèle installé le couvre, sinon un modèle qui lit une description
        # (`tasks._routed_description`). Le libellé disait « Prompt SAM3 » : SAM3 n'en est plus
        # le seul lecteur.
        "sam3_prompt": dict(
            type="textarea", label="Ce qu'il faut anonymiser", icon="fa-comment-dots",
            dom_id={"panel": "user_setting_sam3_prompt"}, group="description",
            show_if={"field": "target_mode", "equals": "description"},
            help="Les cibles proposées sont cochées d'office : décochez-en, ajoutez les vôtres, ou "
                 "décrivez avec vos mots. Le système comprend la description, puis choisit le "
                 "modèle qui cherche chaque chose.",
            # La palette des cibles proposées (2026-11-24) : celle que la déclaration du champ
            # nomme (`PROMPT_TARGETS[...]['vocabulary']`), rendue par `WamaParams`.
            keywords=keywords_palette("anonymizer", "sam3_prompt"),
            stales=("detect",),
        ),
        # Menu de modèle tiré du CATALOGUE (2026-09-27) : les tâches qui localisent ce qu'on
        # floute (pose, classification et boîtes orientées n'y ont pas de sens), bornées par le
        # MODE, groupées par tâche. « auto » : le curseur ci-dessous tranche la taille et la
        # segmentation, la couverture des classes choisit le(s) modèle(s) au lancement.
        "model_to_use": dict(
            type="select", label="Modèle", icon="fa-microchip",
            dom_id={"panel": "user_setting_model_to_use"}, group="model",
            # Domaine par TÂCHE, déclaré une fois (`utils/model_config.MODEL_SPEC`) ; valeurs =
            # clés de catalogue (route F4b ⑤, 2026-10-07, migration 0036).
            options_source="catalog",
            options_query=MODEL_SPEC,
            options_mode=options_mode_for("anonymizer", "image_video"),
            options_group="task", options_auto=True,
            help_source="anonymizer",
            chip=True, default="auto",
            help="Automatique : choisi au lancement selon le curseur et les classes.",
            stales=("detect",),
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
            chip=True, group="model", stales=("detect",),
        ),
        # CE QU'ON FLOUTE parmi ce que la détection a trouvé (2026-11-19, décision de Fabien :
        # « par défaut tout ce qui a été détecté », et sélectionner / désélectionner) — une case
        # par LIBELLÉ du document de détections de CE média (`options_from`, résolu au service de
        # sa ⚙) : le nom de classe d'un modèle à classes comme le concept d'une description, sans
        # distinction. La valeur garde les décochés (`stores_unchecked`) : un objet qu'une
        # détection relancée trouve en plus est flouté. Le changer ne refait que le floutage.
        "blur_skip_labels": dict(
            type="multiselect", label="Ce qu'on floute", icon="fa-eye-slash", group="mode",
            contexts=("item",), default=[],
            options_from={"port": "detections", "property": "labels"}, stores_unchecked=True,
            empty_label="Rien n'est encore détecté sur ce média : la détection dira ce qu'on "
                        "peut flouter.",
            help="Ce que la détection a trouvé sur ce média. Décocher ce qu'on veut laisser net : "
                 "seul le floutage est refait, sans redétecter.",
            stales=("blur",),
        ),
        # La QUALIFICATION (2026-11-24, `ROADMAP §17quater` B) : l'interrupteur de son process
        # (`ProcessSpec.toggle`), et la profondeur, qui demande un modèle (installé par la route).
        "qualify_objects": dict(
            type="toggle", label="Qualifier les objets (couleur, taille)", icon="fa-palette",
            group="qualify",
            help="Dit la couleur majoritaire et la taille de chaque objet détecté : « Ce qu'on "
                 "floute » peut alors laisser net une couleur, une taille. Aucun modèle n'est "
                 "chargé ; changer ce qu'on floute ne refait que le floutage.",
            stales=("qualify",),
        ),
        "qualify_depth": dict(
            type="toggle", label="Avec la profondeur (premier plan / arrière-plan)",
            icon="fa-layer-group", group="qualify",
            show_if={"field": "qualify_objects", "equals": True},
            help="Situe chaque objet au premier plan ou à l'arrière-plan de la scène, par un "
                 "modèle de profondeur (une image par seconde sur une vidéo).",
            stales=("qualify",),
        ),
        "blur_skip_colors": dict(
            type="multiselect", label="Couleurs floutées", icon="fa-palette", group="mode",
            contexts=("item",), default=[],
            options_from={"port": "detections", "property": "colors"}, stores_unchecked=True,
            empty_label="La qualification dira les couleurs des objets.",
            help="Décocher une couleur laisse net les objets de cette couleur.",
            stales=("blur",),
        ),
        "blur_skip_sizes": dict(
            type="multiselect", label="Tailles floutées", icon="fa-up-right-and-down-left-from-center",
            group="mode", contexts=("item",), default=[],
            options_from={"port": "detections", "property": "sizes"}, stores_unchecked=True,
            empty_label="La qualification dira la taille des objets.",
            help="small : moins de 1 % de l'image ; large : au moins 10 %.",
            stales=("blur",),
        ),
        "blur_skip_planes": dict(
            type="multiselect", label="Plans floutés", icon="fa-layer-group", group="mode",
            contexts=("item",), default=[],
            options_from={"port": "detections", "property": "planes"}, stores_unchecked=True,
            empty_label="La qualification avec profondeur dira le plan des objets.",
            help="foreground : plus proche que le milieu de la scène ; background : au-delà.",
            stales=("blur",),
        ),
        "detection_threshold": dict(
            type="range", label="Seuil de détection", icon="fa-crosshairs",
            dom_id={"panel": "user_setting_detection_threshold"}, min=0, max=1, step=0.05,
            group="comment", stales=("detect",),
        ),
        # La DÉCIMATION de l'analyse d'une vidéo (2026-11-19, décision de Fabien : « un réglage
        # atteignable et modifiable par l'utilisateur », adapté par modèle) : la forme du monde
        # Data (`Declaration.decimation`, une image sur N), « auto » à 0 — chaque détecteur sa
        # cadence déclarée, donc une passe à plusieurs modèles garde la sienne pour chacun.
        "detection_decimation": dict(
            type="number", label="Décimation de l'analyse (vidéo)", icon="fa-forward-fast",
            min=0, max=250, step=1, advanced=True, group="model",
            help="Une image analysée sur N d'une vidéo (1 : toutes). 0 : automatique — chaque "
                 "modèle sa cadence (LocateAnything : une image par seconde ; YOLO, SAM3 : "
                 "toutes). Les images sautées sont déduites des images analysées voisines.",
            stales=("detect",),
        ),
        # ⚠ step=2 N'ÉTAIT PAS ARBITRAIRE (compris le 2026-08-19) : `blur_ratio` est la TAILLE
        # DE NOYAU d'un flou gaussien, qui DOIT être impaire — `normalize_blur_ratio`
        # (core/blur_utils.py:234) force le +1 sur une valeur paire. Avec step=1 l'utilisateur
        # choisissait 42 et le moteur appliquait 43 : l'affichage mentait. Le pas de 2 depuis
        # min=1 ne produit que des valeurs RÉELLEMENT applicables. Le schéma s'aligne donc sur
        # le volet, et non l'inverse. `max` 49→100 (arbitrage Fabien : la borne 49 n'était pas
        # justifiée ; un noyau de 99 reste valide, seul le coût CPU croît).
        # Le MODE de rendu (2026-11-25, `ROADMAP §17quater` C) — ses choix viennent de la brique
        # commune (`detections.RENDER_MODES`, par le champ du modèle) ; l'intensité règle le flou
        # comme la taille des blocs d'une pixellisation.
        "blur_mode": dict(
            type="radio", label="Rendu", icon="fa-shapes", inline=True, group="comment",
            help="Flou, pixellisation ou masque plein (noir) : la zone, ses bords et son fondu "
                 "restent les mêmes.",
            stales=("blur",),
        ),
        "blur_invert": dict(
            type="toggle", label="Inverser : tout sauf la sélection", icon="fa-circle-half-stroke",
            group="comment",
            help="Anonymise toute l'image SAUF ce qui est sélectionné, qui reste net.",
            stales=("blur",),
        ),
        "blur_ratio": dict(
            type="range", label="Intensité du flou", icon="fa-droplet",
            dom_id={"panel": "user_setting_blur_ratio"}, min=1, max=99, step=2,
            help="Taille du noyau gaussien (impaire) ; en pixellisation, des blocs de sa moitié.",
            group="comment", stales=("blur",),
        ),
        "rounded_edges": dict(
            type="number", label="Bords arrondis", icon="fa-border-top-left",
            min=0, max=50, step=1, advanced=True, stales=("blur",),
        ),
        # roi_enlargement / progressive_blur : advanced=True mais AFFICHÉS dans « Comment
        # flouter » comme au volet droit — le groupe explicite prime sur le repli Avancé.
        "roi_enlargement": dict(
            type="range", label="Agrandissement de la zone", icon="fa-up-right-and-down-left-from-center",
            # RÉDUIRE ou agrandir (2026-10-06, Fabien) : 0,75–1,25. Le volet bornait 0,5–1,5
            # (l'intention d'origine) pendant que ce schéma bornait 1,0–2,0 — agrandir seulement.
            dom_id={"panel": "user_setting_roi_enlargement"}, min=0.75, max=1.25, step=0.05,
            help="Aire floutée autour de l'objet : moins de 1 la réduit, plus de 1 l'agrandit.",
            advanced=True, group="comment", stales=("blur",),
        ),
        "progressive_blur": dict(
            type="range", label="Flou progressif", icon="fa-chart-line",
            dom_id={"panel": "user_setting_progressive_blur"}, min=0, max=100, step=1,
            advanced=True, group="comment", stales=("blur",),
        ),
        "interpolate_detections": dict(
            type="toggle", label="Interpoler les détections manquantes", icon="fa-wave-square",
            advanced=True, chip=True, chip_label="Interpolation", stales=("blur",),
        ),
        "max_interpolation_frames": dict(
            type="number", label="Frames max à interpoler", icon="fa-film",
            min=1, max=60, step=1, advanced=True,
            # Le réglage dit ce qu'il fait depuis le 2026-10-05 : il était plafonné en silence à
            # 0,5 s de vidéo (50 valait 7 à 15 i/s, card #1026).
            help="Un trou de détection d'au plus ce nombre d'images est comblé, entre deux "
                 "détections du même objet (même piste, ou même place).",
            show_if={"field": "interpolate_detections", "equals": True}, stales=("blur",),
        ),
        # SÉPARÉ de l'interpolation (2026-10-05, décision de Fabien) : encadrée par deux
        # détections, elle comble 50 images sans inventer ; prolonger n'a qu'un côté et ne vaut
        # que pour quelques images. Un seul nombre aurait forcé à mal régler l'un des deux.
        "max_extrapolation_frames": dict(
            type="number", label="Frames à prolonger avant/après", icon="fa-arrows-left-right",
            min=0, max=30, step=1, advanced=True,
            help="Un objet reste flouté ce nombre d'images avant sa première détection et après "
                 "sa dernière (il entre ou sort du champ), à sa vitesse. 0 : jamais.",
            stales=("blur",),
        ),
        "use_segmentation": dict(
            type="toggle", label="Segmentation fine (contours)", icon="fa-draw-polygon",
            help="Masque au contour de l'objet plutôt qu'au rectangle détecté.",
            advanced=True, chip=True, chip_label="Segmentation", stales=("detect",),
        ),
        # Réglages d'AFFICHAGE : ils ne périment rien (`stales=()`, DÉCLARÉ) — ils ne changent
        # que la vue « Détection » de l'aperçu.
        "show_preview": dict(type="toggle", label="Afficher l'aperçu", icon="fa-eye",
                             advanced=True, group="afficher", stales=()),
        "show_boxes": dict(type="toggle", label="Afficher les boîtes", icon="fa-vector-square",
                           advanced=True, group="afficher", stales=()),
        "show_labels": dict(type="toggle", label="Afficher les libellés", icon="fa-tag",
                            advanced=True, group="afficher", stales=()),
        "show_conf": dict(type="toggle", label="Afficher la confiance", icon="fa-percent",
                          advanced=True, group="afficher", stales=()),
    },
)

# ── Format et qualité de SORTIE — la brique COMMUNE (2026-10-28) ─────────────────────────────
# Un média est une image OU une vidéo : formats en groupes par nature (`format_option_groups`),
# qualité affichée seulement quand le fichier est réencodé — comme dans toutes les apps. Ils étaient
# déclarés ici à la main (union recopiée, qualité toujours affichée), et le volet les écrivait une
# TROISIÈME fois en HTML (8 formats sur 13, valeur figée : le choix retenu n'était jamais réaffiché).
# « Original » est le format du fichier DÉPOSÉ : le floutage l'écrit dans ce format, en un seul
# encodage, audio d'origine recopié (`detections.rewrite_media`, 2026-10-28, décision de Fabien —
# « je ne vois pas la différence avec les autres »). Le choix « Format du fichier source » qui
# existait ici est retiré : le floutage imposait le MP4, il fallait reconvertir pour retrouver
# le format déposé.
# Volet : `dom_id` `output_format` / `output_quality`, les ids que lit le dépôt (`upload.js`).
PARAMS += output_format_params(
    ("video", "image"), contexts=("item", "batch", "panel"), group="sortie",
    dom_id_format={"panel": "output_format"}, dom_id_quality={"panel": "output_quality"},
    advanced=True,
    format_extra=dict(help="« Original » : le format du fichier déposé."),
)


PARAMS_JSON = schema_to_dicts(PARAMS)
GROUPS_JSON = groups_to_dicts(GROUPS)


# ── Domaine DOCUMENT (2026-11-02) — son schéma, que le domaine nomme (`app_modes`, `params_schema`) ──
# Un document se lit, ses données personnelles se détectent (Presidio + détecteurs installés,
# `common/privacy`) et s'occultent dans le fichier même, sa forme gardée. Son seul réglage est
# l'étape commune « OCR des scans et des images » (`ocr_process`), que le fichier PROPOSE : un PDF
# sans couche texte la coche, avec la raison dite sous le réglage — le réglage du Translator, mot
# pour mot (`manifests/app_drafts/translator.json`).
from wama.common.services.ocr_process import OCR_LABEL  # noqa: E402

DOCUMENT_PARAMS = derive_from_model(
    Media,
    include=["ocr_scanned_pages"],
    overrides={
        "ocr_scanned_pages": dict(
            type="toggle", label=OCR_LABEL, icon="fa-file-image", section="settings",
            chip=True, chip_label="OCR", contexts=("item", "batch", "panel"),
            default_from={"port": "work_file", "property": "needs_ocr"},
            help="Lit par OCR les pages d'un PDF qui n'ont pas de texte (un scan) et le texte "
                 "dessiné dans ses images, pour y trouver les données personnelles et les occulter "
                 "à leur place. Coché d'office quand le document a des pages scannées — "
                 "décochable ; à cocher pour lire le texte de ses images.",
        ),
    },
)
DOCUMENT_PARAMS_JSON = schema_to_dicts(DOCUMENT_PARAMS)


# ── Réglages UTILISATEUR du volet — brique commune `user_settings` (2026-09-27) ─────────────
# Le volet EST la surface des défauts de l'utilisateur, et un média NAÎT avec eux (modèle
# événementiel, ROADMAP §23.2quater). Lire, garder, remettre à zéro : `user_settings.*_panel_*`.
# Remplace les tables `UserSettings` (défauts recopiés à la main du modèle `Media`) et
# `GlobalSettings` (défauts semés par une liste en dur) : un défaut ne vit plus qu'à UN endroit,
# la colonne de `Media` dont le schéma le dérive. Clé de stockage = le NOM du param.
from wama.anonymizer.models import default_classes2blur  # noqa: E402

# La clé de stockage est celle de TOUTES les apps, `<domaine>.<nom>` d'un réglage retenu
# (`param_schema.setting_key`, bascule du 2026-11-12) : rien à déclarer ici.

#: `classes2blur` est hors schéma (multi-sélection à cases, cf. en-tête) mais c'est un réglage
#: du volet comme les autres : même stockage, même naissance de l'élément.
CLASSES_SETTING = 'classes2blur'
USER_SETTINGS_EXTRA = {CLASSES_SETTING: default_classes2blur()}


def clean_classes(classes):
    """Une liste postée de classes à flouter, assainie (mêmes règles que la tâche)."""
    from wama.anonymizer.utils.media_utils import sane_classes
    return sane_classes(classes) if isinstance(classes, list) else default_classes2blur()


#: Tout ce que la brique commune doit savoir des réglages du volet de l'anonymizer.
PANEL_SETTINGS = dict(extra=USER_SETTINGS_EXTRA,
                      clean={CLASSES_SETTING: clean_classes})
