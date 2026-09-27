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


# `get_output_media_path` et `get_blurred_media_path` retirés le 2026-09-27 (REMOVAL_LEDGER
# R77) : la sortie floutée est le champ fichier `Media.output_file`, posé par la tâche avec le
# chemin que le moteur a ÉCRIT. Les recalculer depuis le nom de l'ENTRÉE faisait partager une
# sortie à des cards dupliquées.


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
