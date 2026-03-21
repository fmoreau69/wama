"""
WAMA Common — Application Registry

Single source of truth for all app specifications:
  - accepted input extensions (used by upload validation, FileManager send-to)
  - batch type and support
  - import capabilities (URL, YouTube)
  - output types
  - conventions conformity status

Usage:
    from wama.common.app_registry import APP_CATALOG, AUDIO_EXTENSIONS, IMAGE_EXTENSIONS
    from wama.common.app_registry import get_app_extensions_for_filemanager
"""

# ---------------------------------------------------------------------------
# Centralized extension constants
# ---------------------------------------------------------------------------

AUDIO_EXTENSIONS = ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus', '.wma')

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.heic', '.gif')

VIDEO_EXTENSIONS = ('.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv', '.mpg', '.qt', '.3gp')

DOCUMENT_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp', '.bmp')

TEXT_EXTENSIONS = ('.txt', '.md', '.csv', '.pdf', '.docx')  # batch file formats (= SUPPORTED_BATCH_EXTENSIONS)


# ---------------------------------------------------------------------------
# Convention conformity flags
# Meanings:
#   True  = implemented and conformant
#   False = missing / non-conformant (should be fixed)
#   None  = not applicable for this app
# ---------------------------------------------------------------------------

def _conv(settings=True, start=True, download=True, duplicate=True, delete=True,
          start_all=True, clear_all=True, download_all=True, drag_drop=True, batch=True):
    return {
        'settings_btn':   settings,
        'start_btn':      start,
        'download_btn':   download,
        'duplicate_btn':  duplicate,
        'delete_btn':     delete,
        'start_all':      start_all,
        'clear_all':      clear_all,
        'download_all':   download_all,
        'drag_drop':      drag_drop,
        'batch':          batch,
    }


# ---------------------------------------------------------------------------
# App Catalog
# ---------------------------------------------------------------------------

APP_CATALOG = {

    'anonymizer': {
        'label':       'Anonymizer',
        'icon':        'fas fa-user-secret',
        'color':       '#dc3545',
        'url_name':    'anonymizer:index',
        'description': 'Floutage automatique de visages et plaques sur images et vidéos.',
        'input_extensions': IMAGE_EXTENSIONS + VIDEO_EXTENSIONS,
        'input_types': ('image', 'video'),
        'batch_type':  None,   # not yet implemented
        'has_batch':   False,
        'has_url_import': True,
        'has_youtube': True,
        'output_types': ('image', 'video'),
        'conventions': _conv(
            settings=False,    # per-item settings modal missing
            duplicate=False,   # duplicate button missing
            drag_drop=False,   # drag & drop missing
            batch=False,       # no batch model
        ),
    },

    'composer': {
        'label':       'Composer',
        'icon':        'fas fa-music',
        'color':       '#198754',
        'url_name':    'composer:index',
        'description': 'Génération de musique et effets sonores par IA.',
        'input_extensions': TEXT_EXTENSIONS,
        'input_types': ('text',),
        'batch_type':  'pipe',   # Type B: filename|prompt|model|duration
        'has_batch':   True,
        'has_url_import': False,
        'has_youtube': False,
        'output_types': ('wav', 'mp3'),
        'conventions': _conv(
            start=None,  # auto-start on generate, no per-item start button needed
        ),
    },

    'describer': {
        'label':       'Describer',
        'icon':        'fas fa-search-plus',
        'color':       '#0dcaf0',
        'url_name':    'describer:index',
        'description': 'Description automatique d\'images, vidéos, fichiers audio et documents par LLM.',
        'input_extensions': IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + AUDIO_EXTENSIONS + TEXT_EXTENSIONS,
        'input_types': ('image', 'video', 'audio', 'text'),
        'batch_type':  'media_list',  # Type A: one URL/path per line
        'has_batch':   True,
        'has_url_import': True,
        'has_youtube': True,
        'output_types': ('txt',),
        'conventions': _conv(),  # fully conformant
    },

    'enhancer': {
        'label':       'Enhancer',
        'icon':        'fas fa-magic',
        'color':       '#6f42c1',
        'url_name':    'enhancer:index',
        'description': 'Upscaling IA d\'images/vidéos et amélioration audio (Resemble, DeepFilterNet).',
        'input_extensions': IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + AUDIO_EXTENSIONS,
        'input_types': ('image', 'video', 'audio'),
        'batch_type':  'media_list',
        'has_batch':   True,
        'has_url_import': True,
        'has_youtube': False,
        'output_types': ('image', 'video', 'audio'),
        'conventions': _conv(),  # fully conformant
    },

    'imager': {
        'label':       'Imager',
        'icon':        'fas fa-image',
        'color':       '#fd7e14',
        'url_name':    'imager:index',
        'description': 'Génération d\'images et vidéos par IA (Stable Diffusion, Hunyuan, Mochi…).',
        'input_extensions': TEXT_EXTENSIONS + IMAGE_EXTENSIONS,  # text prompt + image reference
        'input_types': ('text', 'image'),
        'batch_type':  None,   # to be redesigned
        'has_batch':   False,
        'has_url_import': False,
        'has_youtube': False,
        'output_types': ('image', 'video'),
        'conventions': _conv(
            settings=False,     # per-item modal missing
            duplicate=False,    # missing
            start_all=False,    # missing
            drag_drop=False,    # missing
            batch=False,        # to be redesigned
        ),
    },

    'reader': {
        'label':       'Reader (OCR)',
        'icon':        'fas fa-book-open',
        'color':       '#0dcaf0',
        'url_name':    'reader:index',
        'description': 'Extraction de texte par OCR (Tesseract, PaddleOCR, EasyOCR).',
        'input_extensions': DOCUMENT_EXTENSIONS,
        'input_types': ('document', 'image'),
        'batch_type':  'media_list',
        'has_batch':   True,
        'has_url_import': False,
        'has_youtube': False,
        'output_types': ('txt', 'markdown'),
        'conventions': _conv(),  # fully conformant
    },

    'synthesizer': {
        'label':       'Synthesizer',
        'icon':        'fas fa-microphone',
        'color':       '#0d6efd',
        'url_name':    'synthesizer:index',
        'description': 'Synthèse vocale TTS (XTTS, Higgs Audio, Kokoro…).',
        'input_extensions': TEXT_EXTENSIONS,
        'input_types': ('text',),
        'batch_type':  'pipe',   # Type B: filename|text|voice|speed
        'has_batch':   True,
        'has_url_import': False,
        'has_youtube': False,
        'output_types': ('mp3', 'wav'),
        'conventions': _conv(start=None),  # auto-start on upload, no manual start button
    },

    'transcriber': {
        'label':       'Transcriber',
        'icon':        'fas fa-file-alt',
        'color':       '#ffc107',
        'url_name':    'transcriber:index',
        'description': 'Transcription audio/vidéo en texte (Whisper).',
        'input_extensions': AUDIO_EXTENSIONS + VIDEO_EXTENSIONS,
        'input_types': ('audio', 'video'),
        'batch_type':  'media_list',
        'has_batch':   True,
        'has_url_import': True,
        'has_youtube': True,
        'output_types': ('txt', 'srt', 'vtt', 'json'),
        'conventions': _conv(),  # fully conformant
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_app_extensions_for_filemanager() -> dict:
    """
    Returns a dict suitable for FileManager JS APP_EXTENSIONS:
        { 'reader': ['pdf', 'jpg', ...], 'transcriber': [...], ... }

    Extensions are returned without leading dot, lowercased.
    """
    return {
        app_name: sorted({ext.lstrip('.') for ext in spec['input_extensions']})
        for app_name, spec in APP_CATALOG.items()
    }


def get_conformity_summary() -> dict:
    """
    Returns per-app conformity score:
        { 'reader': {'score': 10, 'total': 10, 'pct': 100, 'issues': []}, ... }
    """
    summary = {}
    for app_name, spec in APP_CATALOG.items():
        conv = spec.get('conventions', {})
        issues = []
        total = 0
        ok = 0
        for key, val in conv.items():
            if val is None:
                continue  # N/A
            total += 1
            if val:
                ok += 1
            else:
                issues.append(key)
        pct = int(ok / total * 100) if total > 0 else 100
        summary[app_name] = {
            'score': ok,
            'total': total,
            'pct':   pct,
            'issues': issues,
        }
    return summary
