from ultralytics import YOLO
from wama.settings import BASE_DIR
import os
import logging
from typing import List, Dict, Tuple

# Dossier des modèles
MODELS_ROOT = os.path.join(BASE_DIR, "anonymizer", "models")

# Types de modèles disponibles
MODEL_TYPES = ['detect', 'segment', 'classify', 'pose', 'obb']

def get_model_path(filename: str) -> str:
    """
    Retourne le chemin absolu d'un modèle YOLO.
    Recherche d'abord dans la racine, puis dans les sous-dossiers par type.

    Args:
        filename: Nom du fichier modèle (ex: 'yolov8n.pt' ou 'detect/yolov8n.pt')

    Returns:
        Chemin absolu vers le fichier modèle
    """
    # Si le chemin contient déjà un séparateur, utiliser directement
    if '/' in filename or '\\' in filename:
        return os.path.join(MODELS_ROOT, filename)

    # Rechercher d'abord dans la racine (compatibilité ascendante)
    root_path = os.path.join(MODELS_ROOT, filename)
    if os.path.isfile(root_path):
        return root_path

    # Rechercher dans les sous-dossiers
    for model_type in MODEL_TYPES:
        type_path = os.path.join(MODELS_ROOT, model_type, filename)
        if os.path.isfile(type_path):
            return type_path

    # Si non trouvé, retourner le chemin racine (pour compatibilité)
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
    List model files available in anonymizer/models directory.
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

    Returns:
        Dictionary mapping model type to list of model filenames
        Example: {'detect': ['yolov8n.pt', ...], 'segment': ['yolov8n-seg.pt']}
    """
    models_by_type = {}

    if not os.path.isdir(MODELS_ROOT):
        return models_by_type

    # List models in root directory (legacy/uncategorized)
    root_models = [
        f for f in os.listdir(MODELS_ROOT)
        if os.path.isfile(os.path.join(MODELS_ROOT, f)) and f.endswith('.pt') and not f.startswith('.')
    ]
    if root_models:
        models_by_type['root'] = sorted(root_models)

    # List models in subdirectories
    for model_type in MODEL_TYPES:
        type_dir = os.path.join(MODELS_ROOT, model_type)
        if os.path.isdir(type_dir):
            type_models = [
                f for f in os.listdir(type_dir)
                if os.path.isfile(os.path.join(type_dir, f)) and f.endswith('.pt') and not f.startswith('.')
            ]
            if type_models:
                models_by_type[model_type] = sorted(type_models)

    return models_by_type


def get_model_choices_grouped() -> List[Tuple[str, List[Tuple[str, str]]]]:
    """
    Get model choices grouped by type for use in Django forms.

    Returns:
        List of tuples (group_name, [(value, label), ...])
        Example: [('Detection', [('detect/yolov8n.pt', 'yolov8n.pt'), ...])]
    """
    models_by_type = list_models_by_type()
    grouped_choices = []

    type_labels = {
        'root': 'Legacy (Root Directory)',
        'detect': 'Detection',
        'segment': 'Segmentation',
        'classify': 'Classification',
        'pose': 'Pose Estimation',
        'obb': 'Oriented Bounding Box'
    }

    for model_type, models in sorted(models_by_type.items()):
        if not models:
            continue

        group_label = type_labels.get(model_type, model_type.capitalize())
        group_choices = []

        for model_name in models:
            # For root models, use filename only (backward compatibility)
            if model_type == 'root':
                value = model_name
            else:
                # For categorized models, use type/filename format
                value = f"{model_type}/{model_name}"

            label = model_name
            group_choices.append((value, label))

        grouped_choices.append((group_label, group_choices))

    return grouped_choices
