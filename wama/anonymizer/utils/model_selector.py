"""
Automatic Model Selection System
Selects the best models based on requested classes to blur.
"""

import os
import logging
from typing import List, Dict, Set, Tuple, Optional
from ultralytics import YOLO
from .model_manager import (
    get_installed_models,
    list_downloadable_models,
    OFFICIAL_MODELS,
    MODELS_ROOT,
)
from .yolo_utils import get_model_path

logger = logging.getLogger(__name__)


# Cache pour éviter de recharger les modèles à chaque fois
_MODEL_CLASSES_CACHE: Dict[str, Dict[str, str]] = {}


def get_model_classes(model_path: str) -> Dict[str, str]:
    """
    Extract class names from a YOLO model.

    Args:
        model_path: Absolute path to the model file

    Returns:
        Dictionary mapping class IDs (str) to class names (lowercase)
        Example: {'0': 'person', '1': 'bicycle', ...}
    """
    # Check cache first
    if model_path in _MODEL_CLASSES_CACHE:
        return _MODEL_CLASSES_CACHE[model_path]

    try:
        model = YOLO(model_path)
        # Get class names from model
        names_dict = model.model.names  # {0: 'person', 1: 'bicycle', ...}

        # Convert to lowercase and string keys for consistency
        classes = {str(k): v.lower() for k, v in names_dict.items()}

        # Cache the result
        _MODEL_CLASSES_CACHE[model_path] = classes

        logger.info(f"Loaded {len(classes)} classes from {os.path.basename(model_path)}")
        return classes

    except Exception as e:
        logger.error(f"Failed to load model {model_path}: {e}")
        return {}


def scan_installed_models() -> Dict[str, Dict]:
    """
    Scan all installed models and extract their available classes.

    Returns:
        Dictionary mapping model identifier to model info with classes
        Example:
        {
            'detect/yolov8n.pt': {
                'path': '/path/to/model',
                'type': 'detect',
                'specialty': None,
                'name': 'yolov8n.pt',
                'classes': {'0': 'person', '1': 'bicycle', ...},
                'class_list': ['person', 'bicycle', ...]
            },
            'detect/faces/yolov9s-face-lindevs.pt': {
                'path': '/path/to/model',
                'type': 'detect',
                'specialty': 'faces',
                'name': 'yolov9s-face-lindevs.pt',
                ...
            }
        }
    """
    installed = get_installed_models()
    models_info = {}

    for category_key, models_list in installed.items():
        for model_info in models_list:
            model_name = model_info['name']
            model_path = model_info['path']
            base_type = model_info.get('type', category_key)
            specialty = model_info.get('specialty')

            # Get classes from this model
            classes = get_model_classes(model_path)

            if not classes:
                continue

            # Create model identifier with full path including specialty
            if category_key == 'root':
                model_id = model_name
            elif specialty:
                model_id = f"{base_type}/{specialty}/{model_name}"
            else:
                model_id = f"{base_type}/{model_name}"

            models_info[model_id] = {
                'path': model_path,
                'type': base_type,
                'specialty': specialty,
                'name': model_name,
                'classes': classes,
                'class_list': list(classes.values()),
                'official': model_info.get('official', False),
            }

    return models_info


def find_models_for_classes(classes_to_blur: List[str],
                            installed_models: Optional[Dict] = None) -> Dict[str, List[str]]:
    """
    Find which installed models support the requested classes.

    Args:
        classes_to_blur: List of class names to detect (e.g., ['person', 'car', 'face'])
        installed_models: Optional pre-scanned models dict

    Returns:
        Dictionary mapping class name to list of model IDs that support it
        Example: {'person': ['detect/yolov8n.pt', 'detect/yolo11s.pt'], 'car': [...]}
    """
    if installed_models is None:
        installed_models = scan_installed_models()

    # Normalize input classes to lowercase
    classes_to_blur = [c.lower() for c in classes_to_blur]

    # Map each class to models that support it
    class_to_models = {cls: [] for cls in classes_to_blur}

    for model_id, model_info in installed_models.items():
        model_classes = model_info['class_list']

        for cls in classes_to_blur:
            if cls in model_classes:
                class_to_models[cls].append(model_id)

    return class_to_models


def select_best_models(classes_to_blur: List[str],
                       prefer_official: bool = True,
                       prefer_small: bool = True) -> Dict:
    """
    Automatically select the best models to use for the requested classes.

    Args:
        classes_to_blur: List of class names to detect
        prefer_official: Prefer official models over custom ones
        prefer_small: Prefer smaller models (nano/small) for speed

    Returns:
        Dictionary with selection results:
        {
            'models_to_use': [{'id': 'detect/yolo11n.pt', 'classes': ['person', 'car']}],
            'unsupported_classes': ['face'],
            'recommendations': [{'model': 'detect/yolo11n.pt', 'reason': '...'}],
            'coverage': 0.66  # Percentage of classes covered
        }
    """
    # Scan installed models
    installed_models = scan_installed_models()

    # Find which models support which classes
    class_to_models = find_models_for_classes(classes_to_blur, installed_models)

    # Identify unsupported classes
    unsupported_classes = [cls for cls, models in class_to_models.items() if not models]

    # Group classes by models
    # Find the minimum set of models that covers all supported classes
    models_to_use = []
    covered_classes = set()
    remaining_classes = set(cls for cls in classes_to_blur if cls not in unsupported_classes)

    # Strategy: For each uncovered class, pick the model that covers the most remaining classes
    while remaining_classes:
        best_model = None
        best_coverage = 0
        best_classes = set()

        # Check each model to see how many remaining classes it covers
        for model_id, model_info in installed_models.items():
            model_classes = set(model_info['class_list'])
            covered = remaining_classes & model_classes

            if len(covered) > best_coverage:
                best_coverage = len(covered)
                best_model = model_id
                best_classes = covered
            elif len(covered) == best_coverage and best_model:
                # Tie-breaker: prefer official, then smaller models
                if prefer_official and model_info['official'] and not installed_models[best_model]['official']:
                    best_model = model_id
                    best_classes = covered
                elif prefer_small and 'n' in model_info['name'] and 'n' not in best_model:
                    best_model = model_id
                    best_classes = covered

        if best_model:
            models_to_use.append({
                'id': best_model,
                'path': installed_models[best_model]['path'],
                'name': installed_models[best_model]['name'],
                'type': installed_models[best_model]['type'],
                'specialty': installed_models[best_model].get('specialty'),
                'classes': sorted(list(best_classes)),
            })
            covered_classes.update(best_classes)
            remaining_classes -= best_classes
        else:
            # No model found for remaining classes
            break

    # Calculate coverage
    total_classes = len(classes_to_blur)
    covered_count = len(covered_classes)
    coverage = covered_count / total_classes if total_classes > 0 else 0

    # Generate recommendations for unsupported classes
    recommendations = []
    if unsupported_classes:
        recommendations = get_download_recommendations(unsupported_classes)

    return {
        'models_to_use': models_to_use,
        'unsupported_classes': unsupported_classes,
        'recommendations': recommendations,
        'coverage': coverage,
        'total_classes': total_classes,
        'covered_classes': covered_count,
    }


def get_download_recommendations(classes_needed: List[str]) -> List[Dict]:
    """
    Recommend official models to download for unsupported classes.

    Args:
        classes_needed: List of class names not supported by installed models

    Returns:
        List of model recommendations with reasons
    """
    recommendations = []

    # Standard COCO classes are available in all detection models
    coco_classes = [
        'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck',
        'boat', 'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench',
        'bird', 'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra',
        'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
        'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove',
        'skateboard', 'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup',
        'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich', 'orange',
        'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
        'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse',
        'remote', 'keyboard', 'cell phone', 'microwave', 'oven', 'toaster', 'sink',
        'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier',
        'toothbrush'
    ]

    # Check if any needed classes are in COCO
    coco_needed = [cls for cls in classes_needed if cls.lower() in coco_classes]

    if coco_needed:
        recommendations.append({
            'model_type': 'detect',
            'model_name': 'yolo11n.pt',
            'reason': f'YOLO11 Nano détecte les classes COCO standard: {", ".join(coco_needed[:5])}{"..." if len(coco_needed) > 5 else ""}',
            'classes_covered': coco_needed,
            'download_command': 'python manage.py manage_models download detect yolo11n.pt',
        })

    # Special cases for common anonymization needs
    face_plate_classes = [cls for cls in classes_needed if cls.lower() in ['face', 'plate', 'license plate']]
    if face_plate_classes:
        recommendations.append({
            'model_type': 'custom',
            'model_name': 'yolov8n_faces&plates',
            'reason': f'Modèle spécialisé pour la détection de visages et plaques d\'immatriculation',
            'classes_covered': face_plate_classes,
            'download_command': 'Téléchargement manuel requis - modèle personnalisé',
        })

    # If no specific recommendations, suggest a general detection model
    if not recommendations:
        recommendations.append({
            'model_type': 'detect',
            'model_name': 'yolo11n.pt',
            'reason': 'Modèle de détection général recommandé (80 classes COCO)',
            'classes_covered': classes_needed,
            'download_command': 'python manage.py manage_models download detect yolo11n.pt',
        })

    return recommendations


def get_model_size_from_precision(precision_level: int) -> str:
    """
    Determine model size based on precision level (0-100).

    Args:
        precision_level: 0=Quick, 50=Balanced, 100=Precise

    Returns:
        Model size suffix: 'n', 's', 'm', 'l', or 'x'
    """
    if precision_level <= 20:
        return 'n'  # Nano - fastest
    elif precision_level <= 40:
        return 's'  # Small
    elif precision_level <= 60:
        return 'm'  # Medium
    elif precision_level <= 80:
        return 'l'  # Large
    else:
        return 'x'  # XLarge - most accurate


def should_use_segmentation(precision_level: int) -> bool:
    """
    Determine if segmentation should be used based on precision level.

    Args:
        precision_level: 0=Quick, 50=Balanced, 100=Precise

    Returns:
        True if segmentation should be used
    """
    # Use segmentation for precision levels above 65
    return precision_level >= 65


def select_model_by_precision(classes_to_blur: List[str],
                               precision_level: int = 50,
                               prefer_yolo11: bool = True) -> Optional[str]:
    """
    Automatically select the best model based on precision level and classes to blur.

    Args:
        classes_to_blur: List of class names to detect
        precision_level: 0=Quick, 50=Balanced, 100=Precise
        prefer_yolo11: Prefer YOLO11 models over YOLOv8

    Returns:
        Model identifier (e.g., 'detect/yolo11m.pt') or None if not found
    """
    if not classes_to_blur:
        return None

    # Determine model size from precision level
    size = get_model_size_from_precision(precision_level)

    # Determine if segmentation should be used
    use_seg = should_use_segmentation(precision_level)

    # Determine model type based on classes
    model_type = 'segment' if use_seg else 'detect'

    # Get installed models
    installed = scan_installed_models()

    # Build candidate model names
    version_prefix = 'yolo11' if prefer_yolo11 else 'yolov8'
    suffix = '-seg' if use_seg else ''

    # Try to find the exact model
    candidate_name = f"{version_prefix}{size}{suffix}.pt"
    candidate_id = f"{model_type}/{candidate_name}"

    # Check if candidate exists
    if candidate_id in installed:
        # Verify it supports the requested classes
        model_classes = set(installed[candidate_id]['class_list'])
        requested_classes = set(cls.lower() for cls in classes_to_blur)

        if requested_classes.issubset(model_classes):
            return candidate_id

    # Fallback: try YOLOv8 if YOLO11 not found
    if prefer_yolo11:
        fallback_name = f"yolov8{size}{suffix}.pt"
        fallback_id = f"{model_type}/{fallback_name}"

        if fallback_id in installed:
            model_classes = set(installed[fallback_id]['class_list'])
            requested_classes = set(cls.lower() for cls in classes_to_blur)

            if requested_classes.issubset(model_classes):
                return fallback_id

    # If still not found, fall back to standard selection
    selection = select_best_models(classes_to_blur, prefer_official=True, prefer_small=(size in ['n', 's']))

    if selection['models_to_use']:
        return selection['models_to_use'][0]['id']

    return None


def get_model_selection_info(classes_to_blur: List[str],
                              current_model: Optional[str] = None,
                              precision_level: int = 50,
                              auto_select_by_precision: bool = False) -> Dict:
    """
    Get complete information about model selection for the given classes.
    This is the main function to call from views.

    Args:
        classes_to_blur: List of class names to detect
        current_model: Currently selected model (if any)
        precision_level: 0=Quick, 50=Balanced, 100=Precise
        auto_select_by_precision: Use precision-based auto selection

    Returns:
        Complete selection information for the UI
    """
    if not classes_to_blur:
        return {
            'status': 'no_classes',
            'message': 'Aucune classe sélectionnée',
            'use_current': bool(current_model),
            'current_model': current_model,
        }

    # If auto-select by precision is enabled
    if auto_select_by_precision:
        selected_model = select_model_by_precision(classes_to_blur, precision_level)
        if selected_model:
            return {
                'status': 'auto_precision',
                'message': f'Modèle sélectionné automatiquement (niveau {precision_level})',
                'use_current': False,
                'selected_model': selected_model,
                'precision_level': precision_level,
                'model_size': get_model_size_from_precision(precision_level),
                'use_segmentation': should_use_segmentation(precision_level),
            }

    # If user has selected a model, check if it supports all classes
    if current_model:
        installed = scan_installed_models()
        if current_model in installed:
            model_classes = set(installed[current_model]['class_list'])
            requested_classes = set(cls.lower() for cls in classes_to_blur)

            if requested_classes.issubset(model_classes):
                return {
                    'status': 'manual_ok',
                    'message': 'Le modèle sélectionné supporte toutes les classes demandées',
                    'use_current': True,
                    'current_model': current_model,
                    'supported_classes': list(requested_classes),
                }
            else:
                unsupported = requested_classes - model_classes
                return {
                    'status': 'manual_incomplete',
                    'message': f'Le modèle sélectionné ne supporte pas: {", ".join(unsupported)}',
                    'use_current': True,
                    'current_model': current_model,
                    'unsupported_classes': list(unsupported),
                    'suggestion': 'Laissez le champ vide pour une sélection automatique',
                }

    # Automatic selection
    selection = select_best_models(classes_to_blur)

    if selection['coverage'] == 1.0:
        return {
            'status': 'auto_complete',
            'message': f'{len(selection["models_to_use"])} modèle(s) sélectionné(s) automatiquement',
            'use_current': False,
            'models': selection['models_to_use'],
            'coverage': selection['coverage'],
        }
    elif selection['coverage'] > 0:
        return {
            'status': 'auto_partial',
            'message': f'Couverture partielle: {selection["covered_classes"]}/{selection["total_classes"]} classes',
            'use_current': False,
            'models': selection['models_to_use'],
            'coverage': selection['coverage'],
            'unsupported_classes': selection['unsupported_classes'],
            'recommendations': selection['recommendations'],
        }
    else:
        return {
            'status': 'no_models',
            'message': 'Aucun modèle installé ne supporte ces classes',
            'use_current': False,
            'unsupported_classes': selection['unsupported_classes'],
            'recommendations': selection['recommendations'],
        }
