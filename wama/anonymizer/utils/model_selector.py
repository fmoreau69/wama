"""
Automatic Model Selection System
Selects the best models based on requested classes to blur.

This module can use either:
1. The centralized Model Manager database (preferred, faster)
2. Direct filesystem scanning (fallback)

The Model Manager integration provides:
- Faster model discovery (no need to load YOLO models)
- Centralized model catalog
- Consistent model information across all WAMA apps
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

# Flag to enable/disable Model Manager integration
USE_MODEL_MANAGER_DB = True


# Cache pour éviter de recharger les modèles à chaque fois
_MODEL_CLASSES_CACHE: Dict[str, Dict[str, str]] = {}

# Known classes for specialty ONNX models (when metadata extraction is not possible)
# Maps specialty directory name to expected classes
SPECIALTY_MODEL_CLASSES = {
    'faces': {'0': 'face'},
    'plates': {'0': 'plate'},
    'faces&plates': {'0': 'face', '1': 'plate'},
}

# Class name aliases for flexible matching between user requests and model classes
# Maps user-friendly names to all possible model class names
CLASS_ALIASES = {
    'plate': {'license_plate', 'license plate', 'licenseplate', 'plate', 'number_plate'},
    'license_plate': {'plate', 'license plate', 'licenseplate', 'number_plate'},
    'face': {'face', 'faces'},
}


def normalize_class_name(class_name: str) -> str:
    """Normalize a class name for consistent comparison."""
    return class_name.lower().replace(' ', '_').replace('-', '_')


def classes_match(requested: str, model_class: str) -> bool:
    """
    Check if a requested class matches a model class, considering aliases.

    Args:
        requested: The class name requested by the user
        model_class: The class name from the model

    Returns:
        True if they match (directly or via alias)
    """
    req_lower = normalize_class_name(requested)
    model_lower = normalize_class_name(model_class)

    # Direct match
    if req_lower == model_lower:
        return True

    # Check aliases
    req_aliases = CLASS_ALIASES.get(req_lower, {req_lower})
    model_aliases = CLASS_ALIASES.get(model_lower, {model_lower})

    # Match if model class is in requested aliases or vice versa
    return model_lower in req_aliases or req_lower in model_aliases


def get_model_classes(model_path: str) -> Dict[str, str]:
    """
    Extract class names from a YOLO model.

    Supports both PyTorch (.pt) and ONNX (.onnx) formats.
    For ONNX models in specialty directories (faces, plates), uses predefined class mapping.

    Args:
        model_path: Absolute path to the model file

    Returns:
        Dictionary mapping class IDs (str) to class names (lowercase)
        Example: {'0': 'person', '1': 'bicycle', ...}
    """
    # Check cache first
    if model_path in _MODEL_CLASSES_CACHE:
        return _MODEL_CLASSES_CACHE[model_path]

    model_path_lower = model_path.lower()
    is_onnx = model_path_lower.endswith('.onnx')

    # For ONNX models in specialty directories, use predefined classes
    if is_onnx:
        classes = _get_onnx_model_classes(model_path)
        if classes:
            _MODEL_CLASSES_CACHE[model_path] = classes
            logger.info(f"Loaded {len(classes)} classes from ONNX model {os.path.basename(model_path)}")
            return classes

    # For PyTorch models, use ultralytics YOLO to extract classes
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


def _get_onnx_model_classes(model_path: str) -> Dict[str, str]:
    """
    Get classes for an ONNX model.

    First tries to extract from ONNX metadata, then falls back to specialty directory mapping.

    Args:
        model_path: Path to ONNX model file

    Returns:
        Dictionary mapping class IDs to class names, or empty dict if not found
    """
    # Try to determine specialty from path
    path_parts = model_path.replace('\\', '/').split('/')

    # Look for specialty directory in path (e.g., detect/faces/, detect/plates/)
    for i, part in enumerate(path_parts):
        if part in SPECIALTY_MODEL_CLASSES:
            classes = SPECIALTY_MODEL_CLASSES[part]
            logger.info(f"[ModelSelector] ONNX model in '{part}' directory: using predefined classes {list(classes.values())}")
            return classes

    # Try to extract from ONNX metadata
    try:
        import onnxruntime as ort

        session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        metadata = session.get_modelmeta()

        # Some ONNX models store class names in custom metadata
        if metadata.custom_metadata_map:
            # Look for names/classes in metadata
            for key in ['names', 'classes', 'class_names']:
                if key in metadata.custom_metadata_map:
                    import json
                    try:
                        names_data = json.loads(metadata.custom_metadata_map[key])
                        if isinstance(names_data, dict):
                            return {str(k): v.lower() for k, v in names_data.items()}
                        elif isinstance(names_data, list):
                            return {str(i): v.lower() for i, v in enumerate(names_data)}
                    except json.JSONDecodeError:
                        pass

        logger.debug(f"[ModelSelector] No class metadata found in ONNX model: {os.path.basename(model_path)}")

    except ImportError:
        logger.debug("[ModelSelector] onnxruntime not available for ONNX metadata extraction")
    except Exception as e:
        logger.debug(f"[ModelSelector] Could not extract ONNX metadata: {e}")

    return {}


def _get_models_from_model_manager_db() -> Optional[Dict[str, Dict]]:
    """
    Get Anonymizer models from the centralized Model Manager database.

    This provides faster model discovery than scanning the filesystem,
    as the Model Manager caches model information including classes.

    Returns:
        Dictionary of models or None if Model Manager is unavailable
    """
    if not USE_MODEL_MANAGER_DB:
        return None

    try:
        from wama.model_manager.models import AIModel

        # Query only Anonymizer YOLO models
        db_models = AIModel.objects.filter(
            source='anonymizer',
            is_available=True,
            is_downloaded=True
        )

        if not db_models.exists():
            logger.debug("[ModelSelector] No models found in Model Manager DB, will use filesystem scan")
            return None

        models_info = {}

        for db_model in db_models:
            extra_info = db_model.extra_info or {}

            # Skip non-YOLO models (e.g., SAM3)
            if 'yolo' not in db_model.model_key.lower():
                continue

            model_path = extra_info.get('path') or db_model.local_path
            if not model_path:
                continue

            # Get model identifier in Anonymizer format
            model_id = extra_info.get('model_id')
            if not model_id:
                # Build from components
                yolo_type = extra_info.get('yolo_type', 'detect')
                specialty = extra_info.get('specialty')
                if specialty:
                    model_id = f"{yolo_type}/{specialty}/{db_model.name}"
                else:
                    model_id = f"{yolo_type}/{db_model.name}"

            # Get classes - try from DB first, then load if needed
            class_list = extra_info.get('class_list', [])

            if not class_list:
                # Classes not in DB, need to load them
                classes = get_model_classes(model_path)
                class_list = list(classes.values()) if classes else []
            else:
                # Build classes dict from list
                classes = {str(i): c for i, c in enumerate(class_list)}

            if not class_list:
                # Still no classes, skip this model
                continue

            models_info[model_id] = {
                'path': model_path,
                'type': extra_info.get('yolo_type', 'detect'),
                'specialty': extra_info.get('specialty'),
                'name': db_model.name,
                'classes': classes if classes else {str(i): c for i, c in enumerate(class_list)},
                'class_list': class_list,
                'official': False,  # Can be enhanced later
                'from_db': True,  # Flag to indicate source
            }

        if models_info:
            logger.info(f"[ModelSelector] Loaded {len(models_info)} models from Model Manager DB")
            return models_info

        return None

    except ImportError:
        logger.debug("[ModelSelector] Model Manager not available, using filesystem scan")
        return None
    except Exception as e:
        logger.warning(f"[ModelSelector] Error reading from Model Manager DB: {e}")
        return None


def _scan_installed_models_filesystem() -> Dict[str, Dict]:
    """
    Scan installed models directly from the filesystem.

    This is the fallback method when Model Manager DB is unavailable.
    It loads each model to extract class information.

    Returns:
        Dictionary mapping model identifier to model info with classes
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
                'from_db': False,
            }

    return models_info


def scan_installed_models() -> Dict[str, Dict]:
    """
    Scan all installed models and extract their available classes.

    Uses the centralized Model Manager database when available (faster),
    falls back to direct filesystem scanning if DB is unavailable.

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
    # Try Model Manager DB first (faster)
    models_info = _get_models_from_model_manager_db()

    if models_info is not None and len(models_info) > 0:
        return models_info

    # Fallback to filesystem scan
    logger.info("[ModelSelector] Using filesystem scan for model discovery")
    models_info = _scan_installed_models_filesystem()

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
            # Check if any model class matches the requested class (with alias support)
            for model_cls in model_classes:
                if classes_match(cls, model_cls):
                    class_to_models[cls].append(model_id)
                    break  # Found a match, no need to check other model classes

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
    # Use segmentation for precision levels at or above 50 (balanced and higher)
    return precision_level >= 50


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


# =============================================================================
# PARALLEL DETECTION - Multi-model selection with precision awareness
# =============================================================================

# Specialty classes that have dedicated detection models
SPECIALTY_CLASSES = {'face', 'plate', 'license plate', 'license_plate'}


def select_best_models_by_precision(classes_to_blur: List[str],
                                     precision_level: int = 50) -> Dict:
    """
    Select the best models considering precision level for parallel detection.

    This function determines which models are needed to cover all requested classes,
    potentially returning multiple models when specialty classes (face, plate) are
    mixed with COCO classes.

    For high precision (>=65), prefers segmentation models when available.
    Groups classes by model capability and returns multiple models if needed.

    Args:
        classes_to_blur: List of class names to detect (e.g., ['face', 'person', 'car'])
        precision_level: 0=Quick, 50=Balanced, 100=Precise

    Returns:
        {
            'models_to_use': [
                {'id': 'segment/yolo11m-seg.pt', 'path': '...', 'classes': ['person', 'car']},
                {'id': 'detect/faces/yolov9s-face.pt', 'path': '...', 'classes': ['face']},
            ],
            'unsupported_classes': [...],
            'coverage': 1.0,
        }
    """
    if not classes_to_blur:
        return {
            'models_to_use': [],
            'coverage': 0,
            'unsupported_classes': [],
        }

    # Determine preferences based on precision level
    model_size = get_model_size_from_precision(precision_level)
    prefer_segmentation = should_use_segmentation(precision_level)
    prefer_small = model_size in ['n', 's']

    # Scan available models
    installed_models = scan_installed_models()

    # Normalize classes to lowercase
    classes_lower = [c.lower() for c in classes_to_blur]

    # Separate specialty classes (face, plate) from COCO classes
    specialty_classes = [c for c in classes_lower if c in SPECIALTY_CLASSES]
    coco_classes = [c for c in classes_lower if c not in SPECIALTY_CLASSES]

    models_to_use = []
    covered_classes = set()

    # 1. Handle specialty classes with dedicated models
    for specialty in specialty_classes:
        model_id = _find_specialty_model(specialty, installed_models, model_size)
        if model_id:
            model_info = installed_models[model_id]
            models_to_use.append({
                'id': model_id,
                'path': model_info['path'],
                'name': model_info['name'],
                'type': model_info['type'],
                'classes': [specialty],
            })
            covered_classes.add(specialty)
        else:
            logger.warning(f"[ModelSelector] No specialty model found for: {specialty}")

    # 2. Handle COCO classes with general model
    remaining_coco = [c for c in coco_classes if c not in covered_classes]
    if remaining_coco:
        model_id = _find_coco_model(remaining_coco, installed_models,
                                     prefer_segmentation, model_size)
        if model_id:
            model_info = installed_models[model_id]
            supported = [c for c in remaining_coco if c in model_info['class_list']]
            if supported:
                models_to_use.append({
                    'id': model_id,
                    'path': model_info['path'],
                    'name': model_info['name'],
                    'type': model_info['type'],
                    'classes': supported,
                })
                covered_classes.update(supported)
        else:
            logger.warning(f"[ModelSelector] No COCO model found for: {remaining_coco}")

    # Calculate coverage
    unsupported = [c for c in classes_lower if c not in covered_classes]
    coverage = len(covered_classes) / len(classes_lower) if classes_lower else 0

    logger.info(f"[ModelSelector] Selected {len(models_to_use)} model(s) for {len(classes_lower)} classes "
                f"(coverage: {coverage:.0%}, precision: {precision_level})")

    return {
        'models_to_use': models_to_use,
        'unsupported_classes': unsupported,
        'coverage': coverage,
    }


def _find_specialty_model(specialty_class: str, installed: Dict,
                           model_size: str) -> Optional[str]:
    """
    Find the best specialty model for a given class (face, plate).

    Specialty models are stored in subdirectories like detect/faces/, detect/plates/.

    Args:
        specialty_class: The specialty class name ('face', 'plate')
        installed: Dict of installed models from scan_installed_models()
        model_size: Preferred model size ('n', 's', 'm', 'l', 'x')

    Returns:
        Model identifier or None if not found
    """
    # Map class names to specialty directories
    specialty_dirs = {
        'face': ['faces', 'faces&plates'],
        'plate': ['plates', 'faces&plates'],
        'license plate': ['plates', 'faces&plates'],
        'license_plate': ['plates', 'faces&plates'],
    }

    target_dirs = specialty_dirs.get(specialty_class, [])

    candidates = []

    for model_id, model_info in installed.items():
        # Check if this is a specialty model
        if not model_info.get('specialty'):
            continue

        specialty = model_info['specialty']

        # Check if this specialty matches what we need
        if specialty not in target_dirs:
            continue

        # Check if model supports the class (with alias support)
        model_supports_class = any(
            classes_match(specialty_class, model_cls)
            for model_cls in model_info['class_list']
        )
        if not model_supports_class:
            continue

        # Score this candidate
        score = 0

        # Prefer models matching the requested size
        model_name = model_info['name'].lower()
        if model_size in model_name:
            score += 5

        # Prefer larger models for higher precision
        if 'x' in model_name:
            score += 1
        elif 'l' in model_name:
            score += 2
        elif 'm' in model_name:
            score += 3
        elif 's' in model_name:
            score += 4
        elif 'n' in model_name:
            score += 5

        # Prefer models that specialize in just this class (faces/ over faces&plates/)
        if len(target_dirs) > 0 and specialty == target_dirs[0]:
            score += 2

        candidates.append((model_id, score))

    if candidates:
        # Sort by score (higher is better)
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    return None


def _find_coco_model(classes: List[str], installed: Dict,
                      prefer_seg: bool, model_size: str) -> Optional[str]:
    """
    Find the best model for COCO classes.

    Prefers segmentation models if prefer_seg is True and they're available.
    Prefers YOLO11 over YOLOv8.

    Args:
        classes: List of COCO class names to detect
        installed: Dict of installed models
        prefer_seg: Whether to prefer segmentation models
        model_size: Preferred model size ('n', 's', 'm', 'l', 'x')

    Returns:
        Model identifier or None if not found
    """
    candidates = []

    for model_id, model_info in installed.items():
        # Skip specialty models for COCO classes
        if model_info.get('specialty'):
            continue

        model_classes = model_info['class_list']

        # Check if model covers all requested classes (with alias support)
        all_covered = True
        for requested_cls in classes:
            if not any(classes_match(requested_cls, model_cls) for model_cls in model_classes):
                all_covered = False
                break
        if not all_covered:
            continue

        score = 0
        model_name = model_info['name'].lower()
        model_type = model_info['type']

        # Prefer segmentation if requested
        if prefer_seg:
            if model_type == 'segment':
                score += 20
            else:
                score += 0  # Detection model when segmentation preferred
        else:
            if model_type == 'detect':
                score += 10

        # Prefer models matching the requested size
        if model_size in model_name:
            score += 10

        # Prefer YOLO11 over YOLOv8
        if 'yolo11' in model_name:
            score += 5
        elif 'yolov8' in model_name:
            score += 3

        # Prefer official models
        if model_info.get('official'):
            score += 2

        candidates.append((model_id, score))

    if candidates:
        # Sort by score (higher is better)
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    return None
