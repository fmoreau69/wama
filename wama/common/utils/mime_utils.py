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

# Fichiers TEXTE lisibles tels quels — ces types PRIMENT sur la stdlib, comme le 3D : le
# visualiseur ne montre en texte que `text/…` (`media-preview.js`). L'aperçu du filemanager les
# forçait à `text/plain` localement ; il passe par la fabrique commune depuis le 2026-10-12 — la
# règle vit ici. Les bases de la stdlib DIVERGENT d'une plateforme à l'autre (mesuré le
# 2026-10-12) : venv_win ne connaît ni `.md`, ni `.yaml`, ni `.abc` ; venv_linux connaît `.yaml`
# en `application/yaml` — un « connu » qui n'est pas lu comme du texte (relevé par l'instance de
# portage, test rouge sous WSL seulement). En simple repli, le même fichier s'ouvrait en texte
# sous Windows et en téléchargement sous Linux, où tourne le service.
_EXT_MIME_TEXT = {
    '.log': 'text/plain', '.ini': 'text/plain', '.cfg': 'text/plain',
    '.md': 'text/markdown', '.yaml': 'text/yaml', '.yml': 'text/yaml',
    # Partition ABC (une face du composer, 2026-10-12).
    '.abc': 'text/vnd.abc',
}

# Objets 3D (ROADMAP §17ter) — la stdlib n'en connaît AUCUN (mesuré 13/09 : `.obj` rend même
# `application/octet-stream`, un « connu » qui ne dit rien). Ces types PRIMENT donc sur la
# stdlib : c'est `model/…` que `media-preview.js` reconnaît pour ouvrir la visionneuse.
_EXT_MIME_3D = {
    '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json', '.obj': 'model/obj',
    '.stl': 'model/stl', '.ply': 'model/ply', '.fbx': 'model/fbx',
    '.usd': 'model/vnd.usd', '.usdz': 'model/vnd.usdz+zip', '.dae': 'model/vnd.collada+xml',
}


def guess_mime_type(path_or_name: str) -> str:
    """MIME type robuste pour un chemin/nom de fichier. '' si vraiment inconnu (jamais None)."""
    from pathlib import Path
    ext = Path(path_or_name).suffix.lower()
    if ext in _EXT_MIME_3D:
        return _EXT_MIME_3D[ext]
    if ext in _EXT_MIME_TEXT:
        return _EXT_MIME_TEXT[ext]
    guessed, _ = mimetypes.guess_type(path_or_name)
    if guessed:
        return guessed
    return _EXT_MIME_FALLBACK.get(ext, '')
