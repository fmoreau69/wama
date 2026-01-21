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


def list_models_by_type() -> Dict[str, List[str]]:
    """
    List all available models organized by type.
    Uses model_manager to get comprehensive model information.

    Returns:
        Dictionary mapping model type to list of model filenames
        Example: {'detect': ['yolov8n.pt', ...], 'segment': ['yolov8n-seg.pt']}
    """
    # Get installed models from model_manager
    installed = get_installed_models()

    # Convert to simple dict of lists
    models_by_type = {}
    for model_type, models_list in installed.items():
        models_by_type[model_type] = [m['name'] for m in models_list]

    return models_by_type


def get_model_choices_grouped() -> List[Tuple[str, List[Tuple[str, str]]]]:
    """
    Get model choices grouped by type and specialty for use in Django forms.
    Supports nested structure: mode/specialty/model.pt
    Supports both PyTorch (.pt) and ONNX (.onnx) formats.

    Returns:
        List of tuples (group_name, [(value, label), ...])
        Example: [
            ('Detection', [('detect/yolov8n.pt', 'yolov8n.pt (5.4 MB)'), ...]),
            ('Detection - Faces', [('detect/faces/model.pt', 'model.pt (12.3 MB)'), ...]),
        ]
    """
    # Get installed models from model_manager (now includes specialty and format info)
    installed = get_installed_models()
    grouped_choices = []

    type_labels = {
        'root': 'Legacy (Root Directory)',
        'detect': 'Detection',
        'segment': 'Segmentation',
        'classify': 'Classification',
        'pose': 'Pose Estimation',
        'obb': 'Oriented Bounding Box'
    }

    specialty_labels = {
        'faces': 'Faces',
        'faces&plates': 'Faces & Plates',
        'plates': 'Plates',
    }

    # Sort keys to ensure consistent ordering (base types first, then specialties)
    sorted_keys = sorted(installed.keys(), key=lambda k: (
        0 if k == 'root' else 1,  # root first
        k.count('/'),  # then by depth (base types before specialties)
        k  # then alphabetically
    ))

    for key in sorted_keys:
        models_list = installed[key]
        if not models_list:
            continue

        # Determine group label
        if '/' in key and key.count('/') == 1:
            # It's a specialty (e.g., 'detect/faces')
            model_type, specialty = key.split('/')
            base_label = type_labels.get(model_type, model_type.capitalize())
            specialty_label = specialty_labels.get(specialty, specialty.replace('&', ' & ').title())
            group_label = f"{base_label} - {specialty_label}"
        else:
            # It's a base type
            group_label = type_labels.get(key, key.capitalize())

        group_choices = []
        for model_info in models_list:
            model_name = model_info['name']
            model_type = model_info['type']
            specialty = model_info.get('specialty')
            model_format = model_info.get('format', 'pytorch')

            # Build the value path
            if key == 'root':
                value = model_name
            elif specialty:
                value = f"{model_type}/{specialty}/{model_name}"
            else:
                value = f"{model_type}/{model_name}"

            # Build label with size and format info
            size_mb = model_info.get('size', 0) / (1024 * 1024)
            parts = [model_name]

            # Add format badge for ONNX models
            if model_format == 'onnx':
                parts.append('[ONNX]')

            # Add size info
            if size_mb > 0:
                parts.append(f"({size_mb:.1f} MB)")

            label = ' '.join(parts)
            group_choices.append((value, label))

        grouped_choices.append((group_label, group_choices))

    return grouped_choices
