"""
YOLO Model Manager - Automatic download and management of YOLO models
Based on https://github.com/ultralytics/assets/releases

Model directory structure:
AI-models/anonymizer/models--ultralytics--yolo/
├── classify/           # Classification models
├── detect/             # Detection models
│   ├── faces/          # Face-specific detection
│   ├── faces&plates/   # Face + Plate detection
│   └── *.pt            # Generic detection models
├── obb/                # Oriented Bounding Box
├── pose/               # Pose estimation
└── segment/            # Segmentation models
"""

import os
import logging
import requests
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from wama.settings import BASE_DIR

logger = logging.getLogger(__name__)

# Dossier racine des modèles YOLO (nouvelle organisation centralisée)
MODELS_ROOT = os.path.join(BASE_DIR, "AI-models", "anonymizer", "models--ultralytics--yolo")

# Définition des modèles YOLO officiels disponibles
# Format: {model_type: {model_name: (version, url_pattern)}}
OFFICIAL_MODELS = {
    'detect': {
        # YOLOv8 Detection
        'yolov8n.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt'),
        'yolov8s.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s.pt'),
        'yolov8m.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m.pt'),
        'yolov8l.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8l.pt'),
        'yolov8x.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8x.pt'),

        # YOLO11 Detection (latest)
        'yolo11n.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt'),
        'yolo11s.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt'),
        'yolo11m.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11m.pt'),
        'yolo11l.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11l.pt'),
        'yolo11x.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x.pt'),
    },

    'segment': {
        # YOLOv8 Segmentation
        'yolov8n-seg.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-seg.pt'),
        'yolov8s-seg.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s-seg.pt'),
        'yolov8m-seg.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m-seg.pt'),
        'yolov8l-seg.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8l-seg.pt'),
        'yolov8x-seg.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8x-seg.pt'),

        # YOLO11 Segmentation
        'yolo11n-seg.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-seg.pt'),
        'yolo11s-seg.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s-seg.pt'),
        'yolo11m-seg.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11m-seg.pt'),
        'yolo11l-seg.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11l-seg.pt'),
        'yolo11x-seg.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x-seg.pt'),
    },

    'pose': {
        # YOLOv8 Pose Estimation
        'yolov8n-pose.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-pose.pt'),
        'yolov8s-pose.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s-pose.pt'),
        'yolov8m-pose.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m-pose.pt'),
        'yolov8l-pose.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8l-pose.pt'),
        'yolov8x-pose.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8x-pose.pt'),

        # YOLO11 Pose Estimation
        'yolo11n-pose.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-pose.pt'),
        'yolo11s-pose.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s-pose.pt'),
        'yolo11m-pose.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11m-pose.pt'),
        'yolo11l-pose.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11l-pose.pt'),
        'yolo11x-pose.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x-pose.pt'),
    },

    'classify': {
        # YOLOv8 Classification
        'yolov8n-cls.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-cls.pt'),
        'yolov8s-cls.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s-cls.pt'),
        'yolov8m-cls.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m-cls.pt'),
        'yolov8l-cls.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8l-cls.pt'),
        'yolov8x-cls.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8x-cls.pt'),

        # YOLO11 Classification
        'yolo11n-cls.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-cls.pt'),
        'yolo11s-cls.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s-cls.pt'),
        'yolo11m-cls.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11m-cls.pt'),
        'yolo11l-cls.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11l-cls.pt'),
        'yolo11x-cls.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x-cls.pt'),
    },

    'obb': {
        # YOLOv8 Oriented Bounding Box
        'yolov8n-obb.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-obb.pt'),
        'yolov8s-obb.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s-obb.pt'),
        'yolov8m-obb.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m-obb.pt'),
        'yolov8l-obb.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8l-obb.pt'),
        'yolov8x-obb.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8x-obb.pt'),

        # YOLO11 Oriented Bounding Box
        'yolo11n-obb.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-obb.pt'),
        'yolo11s-obb.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s-obb.pt'),
        'yolo11m-obb.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11m-obb.pt'),
        'yolo11l-obb.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11l-obb.pt'),
        'yolo11x-obb.pt': ('v8.3.0', 'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x-obb.pt'),
    },
}


def ensure_model_directories():
    """Create model directories if they don't exist."""
    Path(MODELS_ROOT).mkdir(parents=True, exist_ok=True)

    for model_type in OFFICIAL_MODELS.keys():
        type_dir = Path(MODELS_ROOT) / model_type
        type_dir.mkdir(exist_ok=True)


def download_model(model_type: str, model_name: str, force: bool = False) -> bool:
    """
    Download a specific YOLO model.

    Args:
        model_type: Type of model (detect, segment, pose, classify, obb)
        model_name: Name of the model file (e.g., 'yolo11n.pt')
        force: If True, re-download even if file exists

    Returns:
        True if download successful, False otherwise
    """
    if model_type not in OFFICIAL_MODELS:
        logger.error(f"Unknown model type: {model_type}")
        return False

    if model_name not in OFFICIAL_MODELS[model_type]:
        logger.error(f"Unknown model: {model_name} for type {model_type}")
        return False

    ensure_model_directories()

    # Get download URL
    version, url = OFFICIAL_MODELS[model_type][model_name]

    # Target path
    target_path = Path(MODELS_ROOT) / model_type / model_name

    # Check if already exists
    if target_path.exists() and not force:
        logger.info(f"Model already exists: {target_path}")
        return True

    logger.info(f"Downloading {model_name} from {url}...")

    try:
        # Download with progress
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        block_size = 8192
        downloaded = 0

        with open(target_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        logger.info(f"Progress: {progress:.1f}%")

        logger.info(f"Successfully downloaded {model_name} to {target_path}")
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download {model_name}: {e}")
        if target_path.exists():
            target_path.unlink()  # Remove partial download
        return False


def download_default_models() -> Dict[str, bool]:
    """
    Download a set of default models for common use cases.

    Returns:
        Dictionary mapping model names to success status
    """
    default_models = [
        ('detect', 'yolo11n.pt'),
        ('detect', 'yolo11s.pt'),
        ('segment', 'yolo11n-seg.pt'),
        ('pose', 'yolo11n-pose.pt'),
    ]

    results = {}
    for model_type, model_name in default_models:
        success = download_model(model_type, model_name)
        results[f"{model_type}/{model_name}"] = success

    return results


def list_downloadable_models() -> Dict[str, List[str]]:
    """
    List all models available for download.

    Returns:
        Dictionary mapping model type to list of model names
    """
    return {
        model_type: list(models.keys())
        for model_type, models in OFFICIAL_MODELS.items()
    }


def get_model_info(model_type: str, model_name: str) -> Optional[Dict]:
    """
    Get information about a specific model.

    Returns:
        Dictionary with version, url, exists status, or None if not found
    """
    if model_type not in OFFICIAL_MODELS:
        return None

    if model_name not in OFFICIAL_MODELS[model_type]:
        return None

    version, url = OFFICIAL_MODELS[model_type][model_name]
    target_path = Path(MODELS_ROOT) / model_type / model_name

    return {
        'type': model_type,
        'name': model_name,
        'version': version,
        'url': url,
        'exists': target_path.exists(),
        'path': str(target_path),
        'size': target_path.stat().st_size if target_path.exists() else 0,
    }


def auto_download_model(model_identifier: str) -> Optional[str]:
    """
    Automatically download a model if it doesn't exist and return its path.

    Args:
        model_identifier: Either 'model.pt' or 'type/model.pt'

    Returns:
        Path to the model file, or None if download failed
    """
    # Parse model identifier
    if '/' in model_identifier:
        model_type, model_name = model_identifier.split('/', 1)
    else:
        # Try to infer type from name
        model_name = model_identifier
        model_type = infer_model_type(model_name)
        if not model_type:
            logger.error(f"Cannot infer model type for: {model_name}")
            return None

    # Check if it exists
    target_path = Path(MODELS_ROOT) / model_type / model_name

    # If exists, return path
    if target_path.exists():
        return str(target_path)

    # If it's an official model, try to download
    if model_type in OFFICIAL_MODELS and model_name in OFFICIAL_MODELS[model_type]:
        logger.info(f"Model not found, attempting to download: {model_type}/{model_name}")
        if download_model(model_type, model_name):
            return str(target_path)

    logger.warning(f"Model not available: {model_identifier}")
    return None


def infer_model_type(model_name: str) -> Optional[str]:
    """
    Infer model type from model name.

    Args:
        model_name: Name of the model file

    Returns:
        Model type string or None
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

    return None


def get_installed_models() -> Dict[str, List[Dict]]:
    """
    Get list of all installed models with their info.
    Handles nested directory structure: mode/specialty/model.pt
    Supports both PyTorch (.pt) and ONNX (.onnx) formats.

    Models are sorted by file size (ascending) to respect the n, s, m, l, x order
    (nano < small < medium < large < extra-large).

    Returns:
        Dictionary mapping model type (or type/specialty) to list of model info dicts
    """
    installed = {}

    # Supported model extensions
    MODEL_EXTENSIONS = ['*.pt', '*.onnx']

    ensure_model_directories()

    def get_model_format(filename: str) -> str:
        """Return model format based on extension."""
        if filename.endswith('.onnx'):
            return 'onnx'
        return 'pytorch'

    def scan_directory_for_models(directory: Path) -> List[Dict]:
        """Scan a directory for model files (.pt and .onnx)."""
        models = []
        for ext in MODEL_EXTENSIONS:
            for model_file in directory.glob(ext):
                if model_file.is_file():
                    models.append(model_file)
        return models

    # Scan all model types defined in OFFICIAL_MODELS
    for model_type in OFFICIAL_MODELS.keys():
        type_dir = Path(MODELS_ROOT) / model_type
        if not type_dir.exists():
            continue

        # Get models directly in the type directory
        models = []
        for model_file in scan_directory_for_models(type_dir):
            model_info = {
                'name': model_file.name,
                'type': model_type,
                'specialty': None,
                'path': str(model_file),
                'size': model_file.stat().st_size,
                'format': get_model_format(model_file.name),
                'official': model_file.name in OFFICIAL_MODELS.get(model_type, {}),
            }
            models.append(model_info)

        if models:
            # Sort by file size (ascending) - smaller models first (n, s, m, l, x)
            installed[model_type] = sorted(models, key=lambda x: x['size'])

        # Check for specialty subdirectories (e.g., detect/faces/, detect/faces&plates/)
        for subdir in type_dir.iterdir():
            if subdir.is_dir():
                specialty = subdir.name
                specialty_key = f"{model_type}/{specialty}"
                specialty_models = []

                for model_file in scan_directory_for_models(subdir):
                    model_info = {
                        'name': model_file.name,
                        'type': model_type,
                        'specialty': specialty,
                        'path': str(model_file),
                        'size': model_file.stat().st_size,
                        'format': get_model_format(model_file.name),
                        'official': False,  # Specialty models are custom
                    }
                    specialty_models.append(model_info)

                if specialty_models:
                    # Sort by file size (ascending) - smaller models first
                    installed[specialty_key] = sorted(specialty_models, key=lambda x: x['size'])

    # Also check root directory for legacy models
    root_models = []
    for model_file in scan_directory_for_models(Path(MODELS_ROOT)):
        root_models.append({
            'name': model_file.name,
            'type': 'root',
            'specialty': None,
            'path': str(model_file),
            'size': model_file.stat().st_size,
            'format': get_model_format(model_file.name),
            'official': False,
        })

    if root_models:
        # Sort by file size (ascending)
        installed['root'] = sorted(root_models, key=lambda x: x['size'])

    return installed
