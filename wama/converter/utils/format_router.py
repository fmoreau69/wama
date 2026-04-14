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
        'output': ['mp4', 'webm', 'avi', 'mov', 'mkv', 'gif', 'mp3', 'wav', 'ogg'],
        'label':  'Vidéo',
    },
    'audio': {
        'input':  ['.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac',
                   '.opus', '.wma', '.aiff', '.aif'],
        'output': ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac', 'opus'],
        'label':  'Audio',
    },
    # 'document' : P2 — nécessite pypandoc + pandoc binaire
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
        {
            'id':      'upscale',
            'label':   'Upscaling IA frame par frame (Real-ESRGAN)',
            'app':     'enhancer',
            'type':    'select',
            'choices': [('x2', '×2'), ('x4', '×4')],
        },
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


def get_cross_app_options(media_type: str) -> list[dict]:
    """Retourne les options cross-apps disponibles pour un type de média."""
    return CROSS_APP_OPTIONS.get(media_type, [])


def build_output_filename(input_filename: str, output_format: str) -> str:
    """Construit le nom du fichier de sortie en remplaçant l'extension."""
    stem = Path(input_filename).stem
    return f"{stem}.{output_format.lower()}"
