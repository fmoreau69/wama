import os
import uuid
from typing import Union
from wama.settings import MEDIA_ROOT
from wama.common.utils.media_paths import get_app_media_path, ensure_app_media_dirs


def get_input_media_path(filename: str, user_id: Union[int, str] = None) -> str:
    """
    Retourne le chemin absolu d'une vidéo téléchargée (input_media).

    Args:
        filename: Filename or relative path
        user_id: User ID (required for user-specific paths)
    """
    if user_id is not None:
        input_dir = get_app_media_path('anonymizer', user_id, 'input')
        return str(input_dir / os.path.basename(filename))
    # Fallback for legacy paths
    return os.path.join(MEDIA_ROOT, filename)


def get_output_media_path(filename: str, user_id: Union[int, str] = None) -> str:
    """
    Retourne le chemin absolu d'une vidéo générée (output_media).

    Args:
        filename: Filename
        user_id: User ID (required for user-specific paths)
    """
    if user_id is not None:
        output_dir = get_app_media_path('anonymizer', user_id, 'output')
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir / os.path.basename(filename))
    # Fallback for legacy paths (backwards compatibility)
    from wama.settings import MEDIA_OUTPUT_ROOT
    return os.path.join(MEDIA_OUTPUT_ROOT, os.path.basename(filename))


def get_blurred_media_path(filename: str, file_ext: str, user_id: Union[int, str] = None) -> str:
    """
    Retourne le chemin absolu pour une version 'blurred' du fichier média.
    Exemple : input.mp4 → input_blurred.mp4
    Note: For videos, always returns .mp4 regardless of intermediate format

    Args:
        filename: Original filename
        file_ext: File extension
        user_id: User ID (required for user-specific paths)
    """
    # Extract just the filename without path
    base_filename = os.path.basename(filename)
    base = os.path.splitext(base_filename)[0]

    # For videos, always use .mp4 as final output (after FFmpeg re-encoding)
    # Images keep their original extension
    if file_ext.lower() in ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv']:
        file_ext = '.mp4'

    blurred_filename = f"{base}_blurred{file_ext}"

    if user_id is not None:
        output_dir = get_app_media_path('anonymizer', user_id, 'output')
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir / blurred_filename)

    # Fallback for legacy paths
    from wama.settings import MEDIA_OUTPUT_ROOT
    return os.path.join(MEDIA_OUTPUT_ROOT, blurred_filename)


def get_unique_filename(folder: str, filename: str) -> str:
    """
    Retourne un nom de fichier unique dans un dossier donné.
    Si 'file.mp4' existe déjà, génère 'file_<uuid>.mp4'.
    """
    base, ext = os.path.splitext(filename)
    candidate = filename
    full_path = os.path.join(folder, candidate)

    while os.path.exists(full_path):
        candidate = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
        full_path = os.path.join(folder, candidate)

    return candidate
