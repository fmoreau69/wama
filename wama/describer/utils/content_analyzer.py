"""
Content type detection utilities.
"""

import os
import mimetypes


def detect_content_type(file_path: str) -> str:
    """Detect content type from file path."""
    if not os.path.exists(file_path):
        return 'text'

    # Get extension
    ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''

    # Image extensions
    image_exts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'ico']
    if ext in image_exts:
        return 'image'

    # Video extensions
    video_exts = ['mp4', 'avi', 'mov', 'mkv', 'webm', 'flv', 'wmv', 'm4v']
    if ext in video_exts:
        return 'video'

    # Audio extensions
    audio_exts = ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac', 'wma']
    if ext in audio_exts:
        return 'audio'

    # PDF
    if ext == 'pdf':
        return 'pdf'

    # Text formats
    text_exts = ['txt', 'md', 'csv', 'json', 'xml', 'html', 'docx', 'doc', 'rtf']
    if ext in text_exts:
        return 'text'

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
            return 'pdf'
        elif mime_type.startswith('text/'):
            return 'text'

    # Default to text
    return 'text'


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
