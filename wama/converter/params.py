"""
Schéma de paramètres Converter — SOURCE UNIQUE de la modale « Réglages » per-job.

Les réglages de conversion vivent dans `Conversion.options` (JSON) + `output_format` ; ils ne sont pas
des champs de modèle individuels → on les déclare en `Param` explicites (pas de derive_from_model).

Champs CONDITIONNÉS par le type de média via `show_if` par valeur (nouvelle capacité WamaParams) :
le `media_type` du job est rendu en champ caché `media_type` ; les sections image/vidéo/audio
s'affichent selon sa valeur. Le select `output_format` est dynamique (`options_source="formats"` →
résolu côté JS depuis `FORMATS[media_type].output`).

Rendu par `WamaParams.render(body, PARAMS_JSON, {context:'item', values, optionsResolver})` dans
converter.js (remplace l'ancien buildModalFormHTML/readModalForm). Lu par `WamaParams.read(body)`.
"""
from wama.common.utils.param_schema import Param, schema_to_dicts

# ── Descriptif moteur (brique wama-model-help via WamaParams : chip + help_fallback) ──
# Construit depuis SUPPORTED_CONVERSIONS — source unique des formats (format_router).
# En cas de format multi-famille (pdf, gif, mp3…), le texte de la 1re famille gagne.
from .utils.format_router import SUPPORTED_CONVERSIONS

# Exporté vers le front (views.index → CONVERTER_APP.engineHelp) : la modale remplace le
# help_fallback PAR FORMAT (ambigu pour les formats multi-famille — mp3/wav/ogg sortent
# aussi de la famille vidéo, gif de l'image…) par le texte du TYPE du job.
_ENGINE_BY_TYPE = {
    'image':    "Moteur : Pillow — qualité, redimensionnement, rotations/miroirs.",
    'video':    "Moteur : FFmpeg — CRF, FPS, rotations ; extraction audio possible.",
    'audio':    "Moteur : FFmpeg — débit, normalisation du volume.",
    'document': "Moteur : Pandoc (PDF→DOCX via pdf2docx) ; ebooks via Calibre.",
    'archive':  "Moteur : zipfile / tarfile / py7zr.",
}
_FORMAT_HELP = {}
for _mt, _spec in SUPPORTED_CONVERSIONS.items():
    for _fmt in _spec.get('output', []):
        _FORMAT_HELP.setdefault(_fmt, _ENGINE_BY_TYPE.get(_mt, ''))

# Conditions de visibilité par valeur du champ caché media_type.
IMG = {"field": "media_type", "equals": "image"}
VID = {"field": "media_type", "equals": "video"}
AUD = {"field": "media_type", "equals": "audio"}
IMG_VID = {"field": "media_type", "in": ["image", "video"]}

# 'panel' ajouté (18/08, demande Fabien) : l'inspecteur du volet droit REFLÈTE les params
# de la modale pour la card sélectionnée (host #converterPanelParams, WamaParams context=panel,
# valeurs appliquées depuis les data-* du gear par WamaInspector.initFromSchema — pattern describer).
ITEM = ("item", "panel")
ITEM_BATCH = ("item", "batch", "panel")   # + modale de BATCH (application en masse)

PARAMS = [
    # Porteur (invisible) : pilote les show_if + le resolver de formats. Non sauvegardé (type fixe du job).
    # Porteur AUSSI en modale de LOT (02/09, demande Fabien) : le regroupement par nature
    # (brique commune group_into_batches_by_nature, vérifié en dépôt mixte → un batch par
    # nature) garantit un lot HOMOGÈNE — sa nature peut donc piloter les show_if de la
    # modale de lot, exactement comme en modale d'item.
    Param(name="media_type", type="hidden", contexts=ITEM_BATCH),

    Param(name="output_format", type="select", label="Format de sortie", icon="fa-file-export",
          options_source="formats", contexts=ITEM_BATCH,
          chip=True, section="output", help_fallback=_FORMAT_HELP),

    # Préréglage de qualité GLOBAL (ffmpeg/pillow) — consommé par batch_update
    # (quality_preset) ; déclaré au schéma depuis le port batch (03/08) : un champ
    # consommé mais non déclaré y était invisible (leçon converter).
    Param(name="quality_preset", type="select", label="Qualité (préréglage)", icon="fa-gem",
          chip=True,
          contexts=("batch",),
          # « — par défaut — » et non « — inchangé — » (Fabien, 02/09) : le vide de CE champ
          # signifie « aucun préréglage → les défauts du schéma s'appliquent », pas « garder
          # tel quel ». « inchangé » reste juste pour output_format (garder le format SOURCE) ;
          # « auto » est réservé au tirage résolu au lancement (options_auto, brique du 02/09).
          choices=[("", "— par défaut —"), ("web", "Web (léger)"),
                   ("balanced", "Équilibré"), ("max", "Maximum")]),

    # ── Image ───────────────────────────────────────────────────────────────
    # Réglages de la NATURE en modale de LOT aussi (ITEM_BATCH, 02/09, demande Fabien) : le
    # lot étant homogène par nature, ses réglages auxiliaires s'appliquent en masse. Seuls
    # restent à l'ITEM : `quality` (range à défaut VISIBLE — en masse il s'écraserait sur
    # les filles sans intention ; le préréglage de qualité couvre le besoin de masse) et les
    # cross-app GPU (garde v1, cf. _cross_app_params). Un save de lot ne poste que le POSÉ.
    # chip=True sur les réglages LISIBLES d'un coup d'œil (31/08, constat Fabien : la section
    # RÉGLAGES des cards restait vide — seul le format était chippé, en section SORTIE).
    # Convention des pilotes (reader/transcriber : moteur, mode, langue, toggles à chip_label) ;
    # les nombres ambigus (resize, CRF, fps) restent hors chips — un « 23 » nu ne dit rien.
    Param(name="quality", type="range", label="Qualité", icon="fa-gauge",
          min=1, max=100, step=1, default=85, show_if=IMG, contexts=ITEM, chip=True,
          help="Qualité d'encodage de l'image (1–100)."),
    Param(name="resize_w", type="number", label="Largeur (px)", icon="fa-arrows-left-right",
          min=0, show_if=IMG, contexts=ITEM_BATCH, help="0 = inchangé."),
    Param(name="resize_h", type="number", label="Hauteur (px)", icon="fa-arrows-up-down",
          min=0, show_if=IMG, contexts=ITEM_BATCH, help="0 = inchangé."),

    # ── Transformations (image OU vidéo) ──────────────────────────────────────
    # Neutre = "" (et plus "0") : un chip ne se rend que pour une valeur POSÉE — avec "0",
    # « Aucune » se chippait sur toute card passée par la modale. Les backends tolèrent ""
    # (`int(options.get('rotation', 0) or 0)`, image_backend:122 / video_backend:167).
    Param(name="rotation", type="select", label="Rotation", icon="fa-rotate", show_if=IMG_VID,
          contexts=ITEM_BATCH, chip=True,
          choices=[("", "Aucune"), ("90", "90° horaire"), ("180", "180°"), ("270", "90° anti-horaire")]),
    Param(name="flip_h", type="toggle", label="Miroir horizontal", icon="fa-left-right",
          show_if=IMG_VID, contexts=ITEM_BATCH, chip=True, chip_label="Miroir H"),
    Param(name="flip_v", type="toggle", label="Miroir vertical", icon="fa-up-down",
          show_if=IMG_VID, contexts=ITEM_BATCH, chip=True, chip_label="Miroir V"),

    # ── Vidéo ─────────────────────────────────────────────────────────────────
    Param(name="video_quality", type="number", label="Qualité vidéo (CRF)", icon="fa-film",
          min=0, max=51, show_if=VID, contexts=ITEM_BATCH,
          help="0 = sans perte, 23 = défaut, 51 = pire qualité."),
    Param(name="fps", type="number", label="Images/s (FPS)", icon="fa-video",
          min=1, max=120, show_if=VID, contexts=ITEM_BATCH, help="Vide = inchangé."),
    # Sortie GIF uniquement (video_backend._to_gif). Déclarés ici parce que le SCHÉMA est la
    # source : ils étaient consommés par le backend et acceptés par la vue, mais invisibles de
    # l'UI comme de l'API — la vue en gardait une liste en dur.
    Param(name="gif_fps", type="number", label="FPS du GIF", icon="fa-images",
          min=1, max=50, default=12, show_if=VID, contexts=ITEM_BATCH,
          help="Sortie GIF uniquement."),
    Param(name="gif_width", type="number", label="Largeur du GIF (px)", icon="fa-arrows-left-right",
          min=64, max=1920, default=480, show_if=VID, contexts=ITEM_BATCH,
          help="Sortie GIF uniquement — hauteur calculée pour garder les proportions."),

    # ── Audio ─────────────────────────────────────────────────────────────────
    Param(name="audio_bitrate", type="select", label="Débit audio", icon="fa-music", show_if=AUD,
          contexts=ITEM_BATCH, chip=True,
          choices=[("", "Auto"), ("128k", "128 kbps"), ("192k", "192 kbps"),
                   ("256k", "256 kbps"), ("320k", "320 kbps")]),
    Param(name="sample_rate", type="select", label="Fréquence d'échantillonnage", icon="fa-wave-square",
          show_if=AUD, contexts=ITEM_BATCH, chip=True,
          choices=[("", "Inchangée"), ("22050", "22 050 Hz"), ("44100", "44 100 Hz"),
                   ("48000", "48 000 Hz")]),
    Param(name="channels", type="select", label="Canaux", icon="fa-headphones",
          show_if=AUD, contexts=ITEM_BATCH, chip=True,
          choices=[("", "Inchangés"), ("1", "Mono"), ("2", "Stéréo")]),
    Param(name="normalize", type="toggle", label="Normaliser le volume", icon="fa-wave-square",
          show_if=AUD, contexts=ITEM_BATCH, chip=True, chip_label="Normalisation"),
]


# ── Post-traitement cross-app (enhancer inline, wiring 18/08) ────────────────────────────
# DÉRIVÉ du catalogue CROSS_APP_OPTIONS (format_router = source unique — ajouter une option
# là-bas suffit, le schéma suit). Un id présent pour plusieurs media_types donne UN Param
# avec show_if in=[...]. contexts=ITEM v1 (post-traitement GPU : pas d'application batch en
# masse). Valeurs stockées dans ConversionJob.cross_app_options (split dans views.update_job),
# appliquées par utils/cross_app.py après la conversion.
from .utils.format_router import CROSS_APP_OPTIONS

def _cross_app_params():
    by_id = {}
    for _mt, _opts in CROSS_APP_OPTIONS.items():
        for _o in _opts:
            entry = by_id.setdefault(_o['id'], {'opt': _o, 'types': []})
            entry['types'].append(_mt)
    out = []
    for _oid, entry in by_id.items():
        o, types = entry['opt'], entry['types']
        show = ({"field": "media_type", "equals": types[0]} if len(types) == 1
                else {"field": "media_type", "in": types})
        _help = f"Post-traitement IA via l'app {o['app']} — appliqué après la conversion (charge un modèle GPU)."
        # chip=True (31/08) : un post-traitement IA demandé est l'info la plus utile de la
        # card. Toggle → chip_label court (le libellé complet, « Débruitage IA (Real-ESRGAN) »,
        # déborde d'une piste — il reste au title).
        if o['type'] == 'select':
            out.append(Param(name=_oid, type="select", label=o['label'],
                             icon="fa-wand-magic-sparkles", show_if=show, contexts=ITEM,
                             chip=True,
                             choices=[("", "Aucun")] + list(o['choices']), help=_help))
        else:  # checkbox → toggle
            out.append(Param(name=_oid, type="toggle", label=o['label'],
                             icon="fa-wand-magic-sparkles", show_if=show, contexts=ITEM,
                             chip=True, chip_label=o['label'].split(' (')[0],
                             help=_help))
    return out

PARAMS += _cross_app_params()

PARAMS_JSON = schema_to_dicts(PARAMS)
