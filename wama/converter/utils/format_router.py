"""
WAMA Converter — Format Router

Source de vérité pour :
  - les types de médias supportés en entrée/sortie
  - les options cross-apps disponibles par type
  - CONVERTER_OUTPUT_FORMATS : dict importé par app_registry et les autres apps
    pour peupler leurs dropdowns de format de sortie
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Conversions supportées par type de média
# ---------------------------------------------------------------------------

SUPPORTED_CONVERSIONS = {
    'image': {
        'input':  ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif',
                   '.gif', '.heic', '.heif', '.avif'],
        'output': ['jpg', 'png', 'webp', 'tiff', 'bmp', 'gif', 'avif', 'pdf'],
        'label':  'Image',
    },
    'video': {
        'input':  ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.mpg',
                   '.mpeg', '.3gp', '.wmv', '.ts', '.m4v'],
        'output': ['mp4', 'webm', 'avi', 'mov', 'mkv', 'gif', 'mp3', 'wav', 'ogg'],  # wama:redondance-ok — capacités de SORTIE du converter (déclaration propre, pas une classification)
        'label':  'Vidéo',
    },
    'audio': {
        'input':  ['.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac',
                   '.opus', '.wma', '.aiff', '.aif'],
        'output': ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac', 'opus'],  # wama:redondance-ok — capacités de SORTIE du converter (déclaration propre, pas une classification)
        'label':  'Audio',
    },
    'document': {
        'input':  ['.pdf', '.docx', '.md', '.markdown', '.html', '.htm',
                   '.txt', '.rtf', '.odt', '.epub', '.fb2', '.tex', '.latex',
                   '.mobi', '.azw3', '.azw'],
        'output': ['pdf', 'docx', 'md', 'html', 'txt', 'rtf', 'odt',
                   'epub', 'fb2', 'mobi', 'azw3'],
        'label':  'Document',
    },
    'archive': {
        'input':  ['.zip', '.tar', '.gz', '.tgz', '.bz2', '.tbz2',
                   '.xz', '.txz', '.7z', '.rar'],
        'output': ['zip', 'tar', 'tar.gz', 'tar.bz2', 'tar.xz', '7z'],
        'label':  'Archive',
    },
}

# ---------------------------------------------------------------------------
# Dict importable par app_registry + autres apps pour leurs dropdowns de sortie
# Format : { 'image': ['jpg', 'png', ...], ... }
# ---------------------------------------------------------------------------

CONVERTER_OUTPUT_FORMATS = {
    media_type: spec['output']
    for media_type, spec in SUPPORTED_CONVERSIONS.items()
}

# ---------------------------------------------------------------------------
# Options cross-apps disponibles par type de média
# ---------------------------------------------------------------------------

CROSS_APP_OPTIONS = {
    'image': [
        {
            'id':      'upscale',
            'label':   'Upscaling IA (Real-ESRGAN)',
            'app':     'enhancer',
            'type':    'select',
            'choices': [('x2', '×2'), ('x4', '×4')],
        },
        {
            'id':    'denoise',
            'label': 'Débruitage IA (Real-ESRGAN)',
            'app':   'enhancer',
            'type':  'checkbox',
        },
    ],
    'video': [
        # DIFFÉRÉ (18/08, wiring v1) : upscale vidéo frame par frame — le mécanisme vit dans
        # enhancer/tasks.py::_enhance_video, couplé au modèle Enhancement ; l'extraire en
        # brique (converter = 2ᵉ consommateur) toucherait le during fraîchement câblé qui
        # attend la validation GPU. À réintroduire après extraction (ROADMAP §Converter P2).
        {
            'id':    'audio_enhance',
            'label': 'Enhancement audio (DeepFilterNet)',
            'app':   'enhancer',
            'type':  'checkbox',
        },
    ],
    'audio': [
        {
            'id':    'audio_enhance',
            'label': 'Enhancement audio (ResembleEnhance / DeepFilterNet)',
            'app':   'enhancer',
            'type':  'checkbox',
        },
    ],
}


def cross_app_option_ids() -> set:
    """Ids de toutes les options cross-app déclarées — SOURCE UNIQUE du split
    options ↔ cross_app_options (views.update_settings), du préremplissage (views.status)
    et du filtre d'application (utils/cross_app.py)."""
    return {opt['id'] for opts in CROSS_APP_OPTIONS.values() for opt in opts}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def detect_media_type(filename: str) -> str | None:
    """
    Détecte le type de média depuis l'extension du fichier.
    Retourne 'image', 'video', 'audio', ou None si non supporté.
    """
    ext = Path(filename).suffix.lower()
    for media_type, spec in SUPPORTED_CONVERSIONS.items():
        if ext in spec['input']:
            return media_type
    return None


def get_output_formats(media_type: str) -> list[str]:
    """Retourne la liste des formats de sortie disponibles pour un type de média."""
    return SUPPORTED_CONVERSIONS.get(media_type, {}).get('output', [])


# ---------------------------------------------------------------------------
# Le format de sortie AUTOMATIQUE — une règle, lue par toutes les voies (2026-10-18)
# ---------------------------------------------------------------------------
# Décision de Fabien : « ça doit être automatique, ça dépend simplement de l'entrée ». Le
# converter le faisait déjà, mais de QUATRE façons selon la voie : le dépôt prenait le premier
# format de la liste (JS), le repli du serveur le dernier format employé, « Envoyer vers » le
# dernier ou RIEN (card à régler), l'outil de l'assistant — donc le Studio — refusait un format
# absent, et l'import par lot créait des jobs sans format. La cascade est celle de tout réglage
# (`param_schema.applicable_defaults`) : défaut de la nature ← dernier format employé par
# l'utilisateur pour CETTE nature ← choix explicite.

def default_output_format(media_type: str) -> str:
    """Le défaut d'une nature : le premier format de sa liste (l'ordre de `SUPPORTED_CONVERSIONS`
    est la déclaration — jpg, mp4, mp3, pdf, zip), '' pour une nature inconnue."""
    formats = get_output_formats(media_type)
    return formats[0] if formats else ''


def _format_key(media_type: str) -> str:
    return f'last_format_{media_type}'


def last_output_format(user, media_type: str, app: str = 'converter') -> str:
    """Le DERNIER format de sortie employé par `user` pour cette nature (brique user_settings), ''
    s'il n'y en a pas ou s'il n'est plus offert pour elle. `app` : une jumelle passe le sien."""
    if user is None or not getattr(user, 'pk', None):
        return ''
    from wama.common.utils.user_settings import get_user_app_settings
    key = _format_key(media_type)
    value = (get_user_app_settings(user, app, {key: ''}).get(key) or '').lower()
    return value if value in get_output_formats(media_type) else ''


def output_format_for(user, media_type: str, requested: str = '', app: str = 'converter') -> str:
    """Le format de sortie d'un élément de cette nature : le choix EXPLICITE s'il est offert pour
    elle, sinon le dernier format employé, sinon le défaut de la nature. Lève `ValueError` sur un
    choix explicite qui n'est pas offert (jamais remplacé en silence par un autre)."""
    fmt = (requested or '').strip().lower()
    if fmt:
        if fmt not in get_output_formats(media_type):
            raise ValueError(f"Format de sortie '{fmt}' invalide pour {media_type or 'cette nature'}. "
                             f"Formats : {', '.join(get_output_formats(media_type)) or '—'}")
        return fmt
    return last_output_format(user, media_type, app) or default_output_format(media_type)


def remember_output_format(user, media_type: str, fmt: str, app: str = 'converter') -> None:
    """Retient un format CHOISI (jamais un format résolu automatiquement) comme le dernier employé
    pour cette nature — au dépôt d'une card comme sur un nœud du Studio (décision de Fabien)."""
    if not (user is not None and getattr(user, 'pk', None) and media_type and fmt):
        return
    from wama.common.utils.user_settings import save_user_app_settings
    save_user_app_settings(user, app, {_format_key(media_type): fmt})


def get_cross_app_options(media_type: str) -> list[dict]:
    """Retourne les options cross-apps disponibles pour un type de média."""
    return CROSS_APP_OPTIONS.get(media_type, [])


def build_output_filename(input_filename: str, output_format: str) -> str:
    """Construit le nom du fichier de sortie en remplaçant l'extension."""
    stem = Path(input_filename).stem
    return f"{stem}.{output_format.lower()}"
