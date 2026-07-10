"""
WAMA Common — Détection MIME robuste.

`mimetypes.guess_type()` (stdlib) échoue pour des extensions courantes sur certains systèmes
(constaté Windows : `.webp` → `(None, None)`, dépend de la base mime.types locale, pas un bug
Python en soi mais une base de données incomplète/absente). Extrait de `filemanager/views.py`
(qui avait déjà ce correctif local, jamais reporté ailleurs — doublon identifié 2026-07-10, la
preview de l'inspecteur commun utilisait `mimetypes.guess_type()` nu et ratait donc les webp).
Source UNIQUE désormais, consommée par filemanager ET par `preview_registry.create_simple_adapter`.
"""

import mimetypes

# Repli pour les extensions que `mimetypes.guess_type()` peut manquer selon la plateforme.
_EXT_MIME_FALLBACK = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.gif': 'image/gif',  '.webp': 'image/webp', '.bmp': 'image/bmp',
    '.tiff': 'image/tiff', '.tif': 'image/tiff', '.ico': 'image/x-icon',
    '.svg': 'image/svg+xml',
    '.mp4': 'video/mp4',   '.webm': 'video/webm', '.mov': 'video/quicktime',
    '.avi': 'video/x-msvideo', '.mkv': 'video/x-matroska', '.flv': 'video/x-flv',
    '.wmv': 'video/x-ms-wmv', '.m4v': 'video/mp4',
    '.mp3': 'audio/mpeg',  '.wav': 'audio/wav',   '.ogg': 'audio/ogg',
    '.flac': 'audio/flac', '.aac': 'audio/aac',   '.m4a': 'audio/mp4',
    '.opus': 'audio/opus', '.weba': 'audio/webm',
}


def guess_mime_type(path_or_name: str) -> str:
    """MIME type robuste pour un chemin/nom de fichier. '' si vraiment inconnu (jamais None)."""
    guessed, _ = mimetypes.guess_type(path_or_name)
    if guessed:
        return guessed
    from pathlib import Path
    ext = Path(path_or_name).suffix.lower()
    return _EXT_MIME_FALLBACK.get(ext, '')
