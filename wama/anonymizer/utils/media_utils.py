import os
import uuid
from typing import Union
from wama.settings import MEDIA_ROOT
from wama.common.utils.media_paths import get_app_media_path, ensure_app_media_dirs


# `get_input_media_path` retiré le 2026-10-05 (REMOVAL_LEDGER R104) : il reconstruisait l'entrée
# en `anonymizer/input/<nom>` au lieu de lire le champ fichier, qui est un POINTEUR — une card
# désignée par l'assistant (fichier dans `temp/`) échouait. La tâche lit `media.file.path`.

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


def sane_classes(classes) -> list:
    """Les classes d'une liste `classes2blur` qui sont des NOMS : un ancien chemin de sauvegarde y
    a injecté le booléen sérialisé 'false' (médias 220/221/225, constat 2026-08-17). Une classe
    est un nom, jamais true/false/none/vide. Lu par la détection ET par la surface de correction
    (déplacé de `tasks._classes_saines` le 2026-10-10, second lecteur)."""
    return [c for c in (classes or [])
            if isinstance(c, str) and c.strip().lower() not in ('true', 'false', 'none', '')]
