from ultralytics import YOLO
from wama.settings import BASE_DIR
import os
import logging
from typing import List, Dict, Tuple, Optional
from .model_manager import (
    auto_download_model,
    get_installed_models,
    MODELS_ROOT,
)

# Types de modèles disponibles
MODEL_TYPES = ['detect', 'segment', 'classify', 'pose', 'obb']

# Supported model file extensions
MODEL_EXTENSIONS = ['.pt', '.onnx']

logger = logging.getLogger(__name__)


#: Anciennes valeurs de `model_to_use` qui ne sont pas un fichier YOLO.
_LEGACY_IDS = {'sam3_vit_h': 'sam3'}


def catalogue_id_for(value) -> str:
    """L'identifiant du CATALOGUE (sans la source) d'une valeur de `model_to_use`, ou '' si elle
    est vide / « auto » / introuvable. Accepte l'identifiant lui-même (`yolo:x.pt`, `sam3`) et
    les chemins d'avant le 2026-09-27 (`detect/faces/x.pt`, `x.pt`) : le fichier est unique au
    catalogue (`anonymizer:yolo:<fichier>`)."""
    from wama.common.utils.auto_model import is_auto
    from wama.model_manager.models import AIModel
    if is_auto(value):
        return ''
    value = _LEGACY_IDS.get(str(value).strip(), str(value).strip())
    if AIModel.objects.filter(model_key=f'anonymizer:{value}').exists():
        return value
    legacy = 'yolo:' + value.replace('\\', '/').rsplit('/', 1)[-1]
    return legacy if AIModel.objects.filter(model_key=f'anonymizer:{legacy}').exists() else ''


def model_path_for(value):
    """Chemin disque du modèle choisi pour un élément, ou None en automatique. Le catalogue
    porte le chemin (`local_path`) ; une valeur qu'il ne connaît pas retombe sur la recherche
    historique par nom de fichier (`get_model_path`)."""
    from wama.common.utils.auto_model import is_auto
    from wama.model_manager.models import AIModel
    if is_auto(value):
        return None
    key = catalogue_id_for(value)
    m = AIModel.objects.filter(model_key=f'anonymizer:{key}').first() if key else None
    if m and m.local_path:
        return m.local_path
    return get_model_path(str(value).strip())


def get_model_path(filename: str, auto_download: bool = True) -> str:
    """
    Retourne le chemin absolu d'un modèle YOLO.
    Supporte les formats PyTorch (.pt) et ONNX (.onnx).

    Recherche dans l'ordre:
    1. Chemin direct si path contient des séparateurs (type/specialty/model.pt)
    2. Si type/model.pt n'existe pas, recherche dans les sous-dossiers de type/
    3. Racine MODELS_ROOT
    4. Sous-dossiers par type (detect/, segment/, etc.)
    5. Sous-dossiers spécialisés (detect/faces/, detect/faces&plates/, etc.)

    Args:
        filename: Nom du fichier modèle. Formats acceptés:
            - 'model.pt' ou 'model.onnx' (recherche dans tous les dossiers)
            - 'detect/model.pt' (recherche dans le type detect et ses sous-dossiers)
            - 'detect/faces/model.pt' (chemin exact avec spécialité)

    Returns:
        Chemin absolu vers le fichier modèle
    """
    def is_model_file(path: str) -> bool:
        """Check if path is a valid model file."""
        return os.path.isfile(path) and any(path.endswith(ext) for ext in MODEL_EXTENSIONS)

    # Si le chemin contient déjà un séparateur, utiliser directement
    if '/' in filename or '\\' in filename:
        path = os.path.join(MODELS_ROOT, filename.replace('/', os.sep))
        if is_model_file(path):
            return path

        # Si le chemin est type/model.pt (un seul séparateur) et n'existe pas,
        # rechercher dans les sous-dossiers de type/
        parts = filename.replace('\\', '/').split('/')
        if len(parts) == 2:
            model_type, model_name = parts
            type_dir = os.path.join(MODELS_ROOT, model_type)
            if os.path.isdir(type_dir):
                # Rechercher dans les sous-dossiers spécialisés
                for subdir in os.listdir(type_dir):
                    subdir_path = os.path.join(type_dir, subdir)
                    if os.path.isdir(subdir_path):
                        specialty_path = os.path.join(subdir_path, model_name)
                        if is_model_file(specialty_path):
                            logger.info(f"Model found in specialty folder: {subdir}/{model_name}")
                            return specialty_path

        # Try auto-download if enabled (only for official models, .pt only)
        if auto_download and filename.endswith('.pt'):
            downloaded_path = auto_download_model(filename)
            if downloaded_path:
                return downloaded_path
        return path

    # Rechercher d'abord dans la racine (compatibilité ascendante)
    root_path = os.path.join(MODELS_ROOT, filename)
    if is_model_file(root_path):
        return root_path

    # Rechercher dans les sous-dossiers par type
    for model_type in MODEL_TYPES:
        type_dir = os.path.join(MODELS_ROOT, model_type)

        # Vérifier directement dans le dossier type
        type_path = os.path.join(type_dir, filename)
        if is_model_file(type_path):
            return type_path

        # Rechercher dans les sous-dossiers spécialisés (faces/, faces&plates/, etc.)
        if os.path.isdir(type_dir):
            for subdir in os.listdir(type_dir):
                subdir_path = os.path.join(type_dir, subdir)
                if os.path.isdir(subdir_path):
                    specialty_path = os.path.join(subdir_path, filename)
                    if is_model_file(specialty_path):
                        return specialty_path

    # Si non trouvé et auto_download activé, essayer de télécharger (PT only)
    if auto_download and filename.endswith('.pt'):
        logger.info(f"Model {filename} not found locally, attempting auto-download...")
        downloaded_path = auto_download_model(filename)
        if downloaded_path:
            return downloaded_path

    # Si non trouvé, retourner le chemin racine (pour compatibilité)
    logger.warning(f"Model {filename} not found and could not be downloaded")
    return root_path

def get_yolo_class_choices(model_filename: str = "yolov8n.pt"):
    """
    Charge un modèle YOLO et retourne la liste des classes disponibles.
    """
    model_path = get_model_path(model_filename)

    try:
        model = YOLO(model_path)
        names_dict = model.model.names  # {0: 'person', 1: 'car', ...}
        return [(str(k), v.capitalize()) for k, v in names_dict.items()]
    except Exception as e:
        logging.warning(f"[YOLO] Could not load model at {model_path}: {e}")
        # Valeurs par défaut si le modèle ne se charge pas
        return [('0', 'Face'), ('1', 'Plate')]

def get_all_class_choices():
    yolo_choices = get_yolo_class_choices()

    fixed_classes = [("face", "Face"), ("plate", "Plate")]
    all_classes = fixed_classes + [
        (lbl, lbl) for _, lbl in yolo_choices if lbl.lower() not in ['face', 'plate']
    ]
    return all_classes


def list_available_models() -> List[str]:
    """
    List model files available in AI-models/anonymizer/models--ultralytics--yolo directory.
    Returns filenames from root directory only (for backward compatibility).
    """
    if not os.path.isdir(MODELS_ROOT):
        return []
    return sorted([
        f for f in os.listdir(MODELS_ROOT)
        if os.path.isfile(os.path.join(MODELS_ROOT, f)) and f.endswith('.pt') and not f.startswith('.')
    ])


# `list_models_by_type` et `get_model_choices_grouped` RETIRÉES le 2026-09-27 : les menus de
# modèle de l'anonymizer (volet et modale) viennent du CATALOGUE (source `catalog`, bornée par le
# mode, groupée par tâche) — ces listes par DOSSIER n'avaient plus d'appelant (REMOVAL_LEDGER R76).
