"""
Anonymizer Model Configuration

Centralized configuration for all models used by the Anonymizer application.
Uses the centralized AI-models directory structure from settings.py.

Model structure:
    vision/
    ├── yolo/                    # YOLO models (Ultralytics)
    │   ├── classify/            # Classification models
    │   ├── detect/              # Detection models
    │   │   ├── faces/           # Face-specific detection
    │   │   ├── faces&plates/    # Face + Plate detection
    │   │   └── plates/          # License plate detection
    │   ├── obb/                 # Oriented Bounding Box
    │   ├── pose/                # Pose estimation
    │   └── segment/             # Segmentation models
    └── sam/                     # SAM models (Meta)
        └── sam3/                # SAM3 HuggingFace cache
"""

import os
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# =============================================================================
# MODEL PATHS CONFIGURATION
# =============================================================================

# Get centralized paths from settings
MODEL_PATHS = getattr(settings, 'MODEL_PATHS', {})

# Vision models root
VISION_ROOT = MODEL_PATHS.get('vision', {}).get('root',
    settings.AI_MODELS_DIR / "models" / "vision")

# YOLO models directory (all types: detect, segment, pose, classify, obb)
YOLO_ROOT = MODEL_PATHS.get('vision', {}).get('yolo',
    settings.AI_MODELS_DIR / "models" / "vision" / "yolo")

# SAM models directory
SAM_ROOT = MODEL_PATHS.get('vision', {}).get('sam',
    settings.AI_MODELS_DIR / "models" / "vision" / "sam")

# SAM3 specific directory (HuggingFace cache structure)
SAM3_DIR = SAM_ROOT / "sam3"

# Ensure directories exist
for dir_path in [VISION_ROOT, YOLO_ROOT, SAM_ROOT, SAM3_DIR]:
    Path(dir_path).mkdir(parents=True, exist_ok=True)

# =============================================================================
# YOLO MODEL TYPES
# =============================================================================

# YOLO model types and their subdirectories
YOLO_TYPES = {
    'detect': {
        'description': 'Object detection',
        'suffix': '',
        'specialties': ['faces', 'faces&plates', 'plates'],
    },
    'segment': {
        'description': 'Instance segmentation',
        'suffix': '-seg',
        'specialties': [],
    },
    'pose': {
        'description': 'Pose estimation',
        'suffix': '-pose',
        'specialties': [],
    },
    'classify': {
        'description': 'Image classification',
        'suffix': '-cls',
        'specialties': [],
    },
    'obb': {
        'description': 'Oriented bounding box',
        'suffix': '-obb',
        'specialties': [],
    },
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_yolo_root() -> Path:
    """Get the YOLO models root directory."""
    return Path(YOLO_ROOT)


def get_yolo_type_dir(model_type: str) -> Path:
    """
    Get the directory for a specific YOLO model type.

    Args:
        model_type: One of 'detect', 'segment', 'pose', 'classify', 'obb'

    Returns:
        Path to the model type directory
    """
    if model_type not in YOLO_TYPES:
        raise ValueError(f"Unknown YOLO type: {model_type}. Available: {list(YOLO_TYPES.keys())}")

    type_dir = get_yolo_root() / model_type
    type_dir.mkdir(parents=True, exist_ok=True)
    return type_dir


def get_yolo_specialty_dir(model_type: str, specialty: str) -> Path:
    """
    Get the directory for a YOLO specialty model.

    Args:
        model_type: e.g., 'detect'
        specialty: e.g., 'faces', 'faces&plates', 'plates'

    Returns:
        Path to the specialty directory
    """
    type_dir = get_yolo_type_dir(model_type)
    specialty_dir = type_dir / specialty
    specialty_dir.mkdir(parents=True, exist_ok=True)
    return specialty_dir


def get_sam_root() -> Path:
    """Get the SAM models root directory."""
    return Path(SAM_ROOT)


def get_sam3_dir() -> Path:
    """Get the SAM3 models directory (HuggingFace cache)."""
    return Path(SAM3_DIR)


def ensure_yolo_directories():
    """Create all YOLO model directories."""
    for model_type, config in YOLO_TYPES.items():
        type_dir = get_yolo_type_dir(model_type)
        for specialty in config.get('specialties', []):
            (type_dir / specialty).mkdir(parents=True, exist_ok=True)


def infer_model_type(model_name: str) -> str:
    """
    Infer YOLO model type from model name.

    Args:
        model_name: Name of the model file (e.g., 'yolo11n-seg.pt')

    Returns:
        Model type string ('detect', 'segment', 'pose', 'classify', 'obb')
    """
    if '-seg' in model_name:
        return 'segment'
    elif '-pose' in model_name:
        return 'pose'
    elif '-cls' in model_name:
        return 'classify'
    elif '-obb' in model_name:
        return 'obb'
    elif any(x in model_name for x in ['yolov', 'yolo1']):
        return 'detect'

    return 'detect'  # Default


def get_model_path(model_type: str, model_name: str, specialty: str = None) -> Path:
    """
    Get the full path for a YOLO model.

    Args:
        model_type: One of 'detect', 'segment', 'pose', 'classify', 'obb'
        model_name: Model filename (e.g., 'yolo11n.pt')
        specialty: Optional specialty subdirectory (e.g., 'faces')

    Returns:
        Full path to the model file
    """
    if specialty:
        base_dir = get_yolo_specialty_dir(model_type, specialty)
    else:
        base_dir = get_yolo_type_dir(model_type)

    return base_dir / model_name


def list_available_yolo_models() -> dict:
    """
    List all available YOLO models with their info.

    Returns:
        Dictionary with model info grouped by type
    """
    result = {}
    yolo_root = get_yolo_root()

    for model_type in YOLO_TYPES.keys():
        type_dir = yolo_root / model_type
        if not type_dir.exists():
            continue

        models = []

        # Get models directly in the type directory
        for model_file in type_dir.glob('*.pt'):
            models.append({
                'name': model_file.name,
                'type': model_type,
                'specialty': None,
                'path': str(model_file),
                'size': model_file.stat().st_size,
            })

        for model_file in type_dir.glob('*.onnx'):
            models.append({
                'name': model_file.name,
                'type': model_type,
                'specialty': None,
                'path': str(model_file),
                'size': model_file.stat().st_size,
                'format': 'onnx',
            })

        # Check specialty subdirectories
        for subdir in type_dir.iterdir():
            if subdir.is_dir():
                specialty = subdir.name
                for model_file in subdir.glob('*.pt'):
                    models.append({
                        'name': model_file.name,
                        'type': model_type,
                        'specialty': specialty,
                        'path': str(model_file),
                        'size': model_file.stat().st_size,
                    })

                for model_file in subdir.glob('*.onnx'):
                    models.append({
                        'name': model_file.name,
                        'type': model_type,
                        'specialty': specialty,
                        'path': str(model_file),
                        'size': model_file.stat().st_size,
                        'format': 'onnx',
                    })

        if models:
            result[model_type] = sorted(models, key=lambda x: x['size'])

    return result


# =============================================================================
# LEGACY COMPATIBILITY
# =============================================================================

# For backward compatibility with existing code
def get_legacy_yolo_root() -> Path:
    """Get the legacy YOLO models root (for migration)."""
    return settings.AI_MODELS_DIR / "anonymizer" / "models--ultralytics--yolo"


def get_legacy_sam3_dir() -> Path:
    """Get the legacy SAM3 models directory (for migration)."""
    return settings.AI_MODELS_DIR / "anonymizer" / "models--facebook--sam3"
