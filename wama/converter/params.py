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

ITEM = ("item",)
ITEM_BATCH = ("item", "batch")   # rendu aussi dans la modale de BATCH (application en masse)

PARAMS = [
    # Porteur (invisible) : pilote les show_if + le resolver de formats. Non sauvegardé (type fixe du job).
    Param(name="media_type", type="hidden", contexts=ITEM),

    Param(name="output_format", type="select", label="Format de sortie", icon="fa-file-export",
          options_source="formats", contexts=ITEM_BATCH,
          chip=True, help_fallback=_FORMAT_HELP),

    # Préréglage de qualité GLOBAL (ffmpeg/pillow) — consommé par batch_update
    # (quality_preset) ; déclaré au schéma depuis le port batch (03/08) : un champ
    # consommé mais non déclaré y était invisible (leçon converter).
    Param(name="quality_preset", type="select", label="Qualité (préréglage)", icon="fa-gem",
          contexts=("batch",),
          choices=[("", "— inchangé —"), ("web", "Web (léger)"),
                   ("balanced", "Équilibré"), ("max", "Maximum")]),

    # ── Image ───────────────────────────────────────────────────────────────
    Param(name="quality", type="range", label="Qualité", icon="fa-gauge",
          min=1, max=100, step=1, default=85, show_if=IMG, contexts=ITEM,
          help="Qualité d'encodage de l'image (1–100)."),
    Param(name="resize_w", type="number", label="Largeur (px)", icon="fa-arrows-left-right",
          min=0, show_if=IMG, contexts=ITEM, help="0 = inchangé."),
    Param(name="resize_h", type="number", label="Hauteur (px)", icon="fa-arrows-up-down",
          min=0, show_if=IMG, contexts=ITEM, help="0 = inchangé."),

    # ── Transformations (image OU vidéo) ──────────────────────────────────────
    Param(name="rotation", type="select", label="Rotation", icon="fa-rotate", show_if=IMG_VID, contexts=ITEM,
          choices=[("0", "Aucune"), ("90", "90° horaire"), ("180", "180°"), ("270", "90° anti-horaire")]),
    Param(name="flip_h", type="toggle", label="Miroir horizontal", icon="fa-left-right",
          show_if=IMG_VID, contexts=ITEM),
    Param(name="flip_v", type="toggle", label="Miroir vertical", icon="fa-up-down",
          show_if=IMG_VID, contexts=ITEM),

    # ── Vidéo ─────────────────────────────────────────────────────────────────
    Param(name="video_quality", type="number", label="Qualité vidéo (CRF)", icon="fa-film",
          min=0, max=51, show_if=VID, contexts=ITEM,
          help="0 = sans perte, 23 = défaut, 51 = pire qualité."),
    Param(name="fps", type="number", label="Images/s (FPS)", icon="fa-video",
          min=1, max=120, show_if=VID, contexts=ITEM, help="Vide = inchangé."),
    # Sortie GIF uniquement (video_backend._to_gif). Déclarés ici parce que le SCHÉMA est la
    # source : ils étaient consommés par le backend et acceptés par la vue, mais invisibles de
    # l'UI comme de l'API — la vue en gardait une liste en dur.
    Param(name="gif_fps", type="number", label="FPS du GIF", icon="fa-images",
          min=1, max=50, default=12, show_if=VID, contexts=ITEM,
          help="Sortie GIF uniquement."),
    Param(name="gif_width", type="number", label="Largeur du GIF (px)", icon="fa-arrows-left-right",
          min=64, max=1920, default=480, show_if=VID, contexts=ITEM,
          help="Sortie GIF uniquement — hauteur calculée pour garder les proportions."),

    # ── Audio ─────────────────────────────────────────────────────────────────
    Param(name="audio_bitrate", type="select", label="Débit audio", icon="fa-music", show_if=AUD, contexts=ITEM,
          choices=[("", "Auto"), ("128k", "128 kbps"), ("192k", "192 kbps"),
                   ("256k", "256 kbps"), ("320k", "320 kbps")]),
    Param(name="sample_rate", type="select", label="Fréquence d'échantillonnage", icon="fa-wave-square",
          show_if=AUD, contexts=ITEM,
          choices=[("", "Inchangée"), ("22050", "22 050 Hz"), ("44100", "44 100 Hz"),
                   ("48000", "48 000 Hz")]),
    Param(name="channels", type="select", label="Canaux", icon="fa-headphones",
          show_if=AUD, contexts=ITEM,
          choices=[("", "Inchangés"), ("1", "Mono"), ("2", "Stéréo")]),
    Param(name="normalize", type="toggle", label="Normaliser le volume", icon="fa-wave-square",
          show_if=AUD, contexts=ITEM),
]

PARAMS_JSON = schema_to_dicts(PARAMS)
