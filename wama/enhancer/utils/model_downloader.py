"""
Automatic model downloader for Enhancer app.

Downloads AI models from multiple sources:
1. QualityScaler GitHub releases (primary)
2. Hugging Face repository (fallback)
"""

import os
import sys
import requests
import logging
from pathlib import Path
from typing import List, Dict, Optional
from tqdm import tqdm

logger = logging.getLogger(__name__)

# Source 1: QualityScaler GitHub repository
GITHUB_REPO = "Djdefrag/QualityScaler"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Source 2: Hugging Face repository (fallback)
HUGGINGFACE_REPO = "svjack/AI-onnx"
HUGGINGFACE_BASE_URL = f"https://huggingface.co/{HUGGINGFACE_REPO}/resolve/main"

# Model filename mapping for different sources
# Some models have different names on Hugging Face
FILENAME_MAPPING = {
    'RealESR_Animex4_fp16.onnx': 'RealSRx4_Anime_fp16.onnx',  # Different name on HF
}

# Model files to download with their download URLs
# These URLs point to pre-built models from QualityScaler releases
MODEL_FILES = {
    'RealESR_Gx4_fp16.onnx': {
        'size': 22 * 1024 * 1024,  # ~22 MB
        'description': 'RealESR General x4 (Fast)',
        'priority': 1,  # High priority - recommended for starting
    },
    'RealESR_Animex4_fp16.onnx': {
        'size': 22 * 1024 * 1024,  # ~22 MB
        'description': 'RealESR Anime x4',
        'priority': 3,
    },
    'BSRGANx2_fp16.onnx': {
        'size': 4 * 1024 * 1024,  # ~4 MB
        'description': 'BSRGAN x2 (Quality)',
        'priority': 2,
    },
    'BSRGANx4_fp16.onnx': {
        'size': 4 * 1024 * 1024,  # ~4 MB
        'description': 'BSRGAN x4 (Quality)',
        'priority': 2,
    },
    'RealESRGANx4_fp16.onnx': {
        'size': 22 * 1024 * 1024,  # ~22 MB
        'description': 'RealESRGAN x4 (High Quality)',
        'priority': 3,
    },
    'IRCNN_Mx1_fp16.onnx': {
        'size': 30 * 1024 * 1024,  # ~30 MB
        'description': 'IRCNN Medium Denoise',
        'priority': 4,
    },
    'IRCNN_Lx1_fp16.onnx': {
        'size': 30 * 1024 * 1024,  # ~30 MB
        'description': 'IRCNN Large Denoise',
        'priority': 4,
    },
}


def get_models_directory() -> Path:
    """Get the AI-onnx models directory path."""
    from django.conf import settings
    base_dir = Path(settings.BASE_DIR)
    models_dir = base_dir / 'wama' / 'enhancer' / 'AI-onnx'
    return models_dir


def ensure_models_directory() -> Path:
    """Ensure the models directory exists."""
    models_dir = get_models_directory()
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def get_missing_models() -> List[str]:
    """Get list of missing model files."""
    models_dir = get_models_directory()
    missing = []

    for model_file in MODEL_FILES.keys():
        model_path = models_dir / model_file
        if not model_path.exists():
            missing.append(model_file)

    return missing


def get_available_models() -> List[str]:
    """Get list of available (downloaded) model files."""
    models_dir = get_models_directory()
    available = []

    for model_file in MODEL_FILES.keys():
        model_path = models_dir / model_file
        if model_path.exists():
            available.append(model_file)

    return available


def get_latest_release_info() -> Optional[Dict]:
    """Get latest release information from GitHub."""
    try:
        response = requests.get(GITHUB_API_URL, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to get release info: {e}")
        return None


def find_asset_url(release_info: Dict, filename: str) -> Optional[str]:
    """Find download URL for a specific asset in the release."""
    if not release_info or 'assets' not in release_info:
        return None

    # Try to find direct asset with this name
    for asset in release_info['assets']:
        if asset['name'] == filename:
            return asset['browser_download_url']

    # Try to find the main ZIP file containing all models
    for asset in release_info['assets']:
        if asset['name'].endswith('.zip') and 'QualityScaler' in asset['name']:
            return asset['browser_download_url']

    return None


def get_huggingface_url(model_file: str) -> str:
    """Get Hugging Face download URL for a model file."""
    # Check if model has a different name on Hugging Face
    hf_filename = FILENAME_MAPPING.get(model_file, model_file)
    return f"{HUGGINGFACE_BASE_URL}/{hf_filename}?download=true"


def download_file(url: str, destination: Path, description: str = "") -> bool:
    """Download a file from URL with progress bar."""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))

        # Create progress bar
        progress_bar = tqdm(
            total=total_size,
            unit='B',
            unit_scale=True,
            desc=description or destination.name
        )

        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    progress_bar.update(len(chunk))

        progress_bar.close()

        logger.info(f"Downloaded {destination.name} successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        if destination.exists():
            destination.unlink()  # Remove partial download
        return False


def download_model_from_huggingface(model_file: str) -> bool:
    """Download a single model directly from Hugging Face."""
    models_dir = ensure_models_directory()
    destination = models_dir / model_file

    url = get_huggingface_url(model_file)
    description = f"{model_file} (Hugging Face)"

    logger.info(f"Downloading {model_file} from Hugging Face...")
    return download_file(url, destination, description)


def download_and_extract_models(release_info: Dict, models_to_download: List[str]) -> Dict[str, bool]:
    """Download models from release ZIP file."""
    import tempfile
    import zipfile

    results = {}
    models_dir = ensure_models_directory()

    # Find the main release ZIP
    zip_asset = None
    for asset in release_info.get('assets', []):
        if asset['name'].endswith('.zip') and 'QualityScaler' in asset['name']:
            zip_asset = asset
            break

    if not zip_asset:
        logger.error("Could not find QualityScaler ZIP in release assets")
        return {model: False for model in models_to_download}

    # Download ZIP to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
        tmp_path = Path(tmp_file.name)

    try:
        logger.info(f"Downloading QualityScaler release: {zip_asset['name']}")
        if not download_file(zip_asset['browser_download_url'], tmp_path, "QualityScaler Release"):
            return {model: False for model in models_to_download}

        # Extract specific models from ZIP
        logger.info("Extracting AI models from archive...")
        with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
            for model_file in models_to_download:
                try:
                    # Try to find the file in the ZIP (may be in AI-onnx subdirectory)
                    found = False
                    for zip_info in zip_ref.namelist():
                        if zip_info.endswith(model_file):
                            # Extract to models directory
                            destination = models_dir / model_file
                            with zip_ref.open(zip_info) as source:
                                with open(destination, 'wb') as target:
                                    target.write(source.read())

                            logger.info(f"Extracted {model_file}")
                            results[model_file] = True
                            found = True
                            break

                    if not found:
                        logger.warning(f"Model {model_file} not found in archive")
                        results[model_file] = False

                except Exception as e:
                    logger.error(f"Failed to extract {model_file}: {e}")
                    results[model_file] = False

    finally:
        # Clean up temp file
        if tmp_path.exists():
            tmp_path.unlink()

    return results


def download_models(models: Optional[List[str]] = None, download_all: bool = False) -> Dict[str, bool]:
    """
    Download missing AI models with multi-source fallback.

    Download strategy:
    1. Try GitHub (QualityScaler releases) - downloads all models from ZIP
    2. If GitHub fails, try Hugging Face for each model individually

    Args:
        models: List of specific models to download. If None, downloads priority models.
        download_all: If True, download all missing models.

    Returns:
        Dictionary mapping model names to download success status.
    """
    ensure_models_directory()

    # Determine which models to download
    if download_all:
        to_download = get_missing_models()
    elif models:
        to_download = [m for m in models if m in get_missing_models()]
    else:
        # Download only priority 1 models (essential)
        missing = get_missing_models()
        to_download = [
            m for m in missing
            if MODEL_FILES.get(m, {}).get('priority', 99) == 1
        ]

    if not to_download:
        logger.info("All requested models are already downloaded")
        return {}

    logger.info(f"Models to download: {', '.join(to_download)}")
    results = {}

    # Try Method 1: GitHub (QualityScaler releases)
    logger.info("Attempting to download from GitHub (QualityScaler)...")
    release_info = get_latest_release_info()

    if release_info:
        logger.info(f"Using QualityScaler release: {release_info.get('tag_name', 'unknown')}")
        results = download_and_extract_models(release_info, to_download)
    else:
        logger.warning("Could not get release information from GitHub")
        results = {model: False for model in to_download}

    # Try Method 2: Hugging Face (fallback for failed downloads)
    failed_models = [model for model, success in results.items() if not success]

    if failed_models:
        logger.info(f"\nFalling back to Hugging Face for {len(failed_models)} model(s)...")
        logger.info("Source: https://huggingface.co/svjack/AI-onnx")

        for model_file in failed_models:
            logger.info(f"\nAttempting to download {model_file} from Hugging Face...")
            success = download_model_from_huggingface(model_file)
            results[model_file] = success

            if success:
                logger.info(f"✓ {model_file} downloaded successfully from Hugging Face")
            else:
                logger.error(f"✗ {model_file} failed to download from Hugging Face")

    # Summary
    successful = sum(1 for v in results.values() if v)
    failed = len(results) - successful

    logger.info(f"\n=== Download Results ===")
    logger.info(f"✓ Successfully downloaded: {successful}/{len(results)} model(s)")

    if failed > 0:
        logger.error(f"✗ Failed to download: {failed} model(s)")
        logger.info("\nYou can try again or download manually from:")
        logger.info("- https://github.com/Djdefrag/QualityScaler/releases")
        logger.info("- https://huggingface.co/svjack/AI-onnx/tree/main")

    return results


def check_and_download_essential_models() -> bool:
    """
    Check if essential models are present, download if missing.
    Called automatically when app starts.

    Returns:
        True if at least one model is available.
    """
    available = get_available_models()

    if available:
        logger.info(f"Found {len(available)} AI models: {', '.join(available)}")
        return True

    logger.warning("No AI models found. Attempting to download essential models...")

    try:
        results = download_models(download_all=False)
        successful = sum(1 for v in results.values() if v)

        if successful > 0:
            logger.info(f"Successfully downloaded {successful} essential model(s)")
            return True
        else:
            logger.error("Failed to download essential models. Please download manually.")
            return False

    except Exception as e:
        logger.error(f"Error during automatic model download: {e}")
        logger.info("Please download models manually from: https://github.com/Djdefrag/QualityScaler/releases")
        return False


def get_models_status() -> Dict:
    """Get status of all models (available, missing, sizes)."""
    models_dir = get_models_directory()
    status = {
        'models_dir': str(models_dir),
        'models_dir_exists': models_dir.exists(),
        'models': {}
    }

    for model_file, info in MODEL_FILES.items():
        model_path = models_dir / model_file
        status['models'][model_file] = {
            'available': model_path.exists(),
            'expected_size': info['size'],
            'actual_size': model_path.stat().st_size if model_path.exists() else 0,
            'description': info['description'],
            'priority': info['priority'],
        }

    available_count = sum(1 for m in status['models'].values() if m['available'])
    status['summary'] = {
        'total': len(MODEL_FILES),
        'available': available_count,
        'missing': len(MODEL_FILES) - available_count,
    }

    return status


if __name__ == '__main__':
    # Command-line usage
    import argparse

    parser = argparse.ArgumentParser(description='Download AI models for Enhancer app')
    parser.add_argument('--all', action='store_true', help='Download all models')
    parser.add_argument('--status', action='store_true', help='Show models status')
    parser.add_argument('--models', nargs='+', help='Specific models to download')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    if args.status:
        status = get_models_status()
        print("\n=== Models Status ===")
        print(f"Directory: {status['models_dir']}")
        print(f"Exists: {status['models_dir_exists']}")
        print(f"\nAvailable: {status['summary']['available']}/{status['summary']['total']}")
        print(f"Missing: {status['summary']['missing']}/{status['summary']['total']}")
        print("\nModels:")
        for model, info in status['models'].items():
            status_str = "✓" if info['available'] else "✗"
            print(f"  {status_str} {model} - {info['description']}")
    else:
        download_models(models=args.models, download_all=args.all)
