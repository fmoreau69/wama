"""
Content type detection utilities.
"""

import os
import mimetypes

# ── Jeux d'extensions du describer : domicile UNIQUE de l'app ────────────────────
# Trois classifications coexistaient (ici, detect_type_from_extension des views et
# _DESCRIBER_*_EXTS) avec des jeux DIVERGENTS en silence : heic accepté à l'upload
# mais inconnu du routage, wma audio ici et texte là. Un seul jeu, trois usages ;
# chaque fonction garde son VOCABULAIRE de retour (image/video/audio/document —
# 'text' et 'pdf' ont FUSIONNÉ dans 'document' le 2026-08-30, arbitrage taxonomie :
# les deux routaient déjà vers le même describe_text ; les valeurs historiques en
# base se normalisent À LA LECTURE (LEGACY_DETECTED_TYPE_ALIASES ci-dessous — même
# doctrine que data_types.LEGACY_TYPE_ALIASES : les migrations sont gitignorées,
# une migration de données n'atteindrait jamais une autre installation).
DESCRIBER_IMG_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff', 'tif',
                      'heic', 'avif', 'ico'}
DESCRIBER_VID_EXTS = {'mp4', 'webm', 'mkv', 'avi', 'mov', 'flv', 'mpg', 'mpeg',
                      'm4v', '3gp', 'wmv'}
DESCRIBER_AUD_EXTS = {'mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac', 'opus', 'wma'}  # wama:redondance-ok — domicile unique des jeux d'extensions du describer
DESCRIBER_DOC_EXTS = {'txt', 'md', 'csv', 'docx', 'doc', 'pdf', 'rtf', 'odt'}
DESCRIBER_TEXT_LIKE_EXTS = {'json', 'xml', 'html'}   # texte brut lisible, hors documents

# Valeurs HISTORIQUES de `detected_type` en base → vocabulaire courant. Normaliser à la
# lecture, en UN point de passage par consommateur qui DÉCIDE (workers + groupement de lot).
LEGACY_DETECTED_TYPE_ALIASES = {'text': 'document', 'pdf': 'document'}


def normalize_detected_type(value):
    return LEGACY_DETECTED_TYPE_ALIASES.get(value, value)


def detect_content_type(file_path: str) -> str:
    """Detect content type from file path."""
    if not os.path.exists(file_path):
        return 'document'

    # Get extension
    ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''

    if ext in DESCRIBER_IMG_EXTS:
        return 'image'

    if ext in DESCRIBER_VID_EXTS:
        return 'video'

    if ext in DESCRIBER_AUD_EXTS:
        return 'audio'

    if ext in DESCRIBER_DOC_EXTS or ext in DESCRIBER_TEXT_LIKE_EXTS:
        return 'document'

    # Try mimetype detection
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        if mime_type.startswith('image/'):
            return 'image'
        elif mime_type.startswith('video/'):
            return 'video'
        elif mime_type.startswith('audio/'):
            return 'audio'
        elif mime_type == 'application/pdf':
            return 'document'
        elif mime_type.startswith('text/'):
            return 'document'

    # Default: document
    return 'document'


def get_file_info(file_path: str) -> dict:
    """Get basic file information."""
    info = {
        'path': file_path,
        'exists': os.path.exists(file_path),
        'size': 0,
        'extension': '',
    }

    if info['exists']:
        info['size'] = os.path.getsize(file_path)
        if '.' in file_path:
            info['extension'] = file_path.rsplit('.', 1)[-1].lower()

    return info
