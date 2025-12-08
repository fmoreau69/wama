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
    Note: For videos, always returns .mp4 regardless of intermediate format
    """
    # Extract just the filename without path
    base_filename = os.path.basename(filename)
    base = os.path.splitext(base_filename)[0]

    print(f"[get_blurred_media_path] Input filename: {filename}")
    print(f"[get_blurred_media_path] Base filename: {base_filename}")
    print(f"[get_blurred_media_path] Base (no ext): {base}")
    print(f"[get_blurred_media_path] File ext: {file_ext}")

    # For videos, always use .mp4 as final output (after FFmpeg re-encoding)
    # Images keep their original extension
    if file_ext.lower() in ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv']:
        file_ext = '.mp4'
        print(f"[get_blurred_media_path] Video detected, using .mp4")

    blurred_filename = f"{base}_blurred{file_ext}"
    full_path = os.path.join(MEDIA_OUTPUT_ROOT, blurred_filename)

    print(f"[get_blurred_media_path] Blurred filename: {blurred_filename}")
    print(f"[get_blurred_media_path] Full path: {full_path}")
    print(f"[get_blurred_media_path] File exists: {os.path.exists(full_path)}")

    return full_path


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
