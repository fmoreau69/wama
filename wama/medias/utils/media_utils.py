import os, uuid
from wama.settings import MEDIA_ROOT, MEDIA_INPUT_ROOT, MEDIA_OUTPUT_ROOT


def get_input_media_path(filename: str) -> str:
    """
    Retourne le chemin absolu d'une vidéo téléchargée (input_media).
    """
    return os.path.join(MEDIA_ROOT, filename)


def get_output_media_path(filename: str) -> str:
    """
    Retourne le chemin absolu d'une vidéo générée (output_media).
    """
    return os.path.join(MEDIA_OUTPUT_ROOT, os.path.basename(filename))


def get_blurred_media_path(filename: str, file_ext: str) -> str:
    """
    Retourne le chemin absolu pour une version 'blurred' du fichier média.
    Exemple : input.mp4 → input_blurred.mp4
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    blurred_filename = f"{base}_blurred{file_ext}"
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
        candidate = f"{base}_{uuid.uuid4().hex[:6]}{ext}"
        full_path = os.path.join(folder, candidate)

    return candidate
