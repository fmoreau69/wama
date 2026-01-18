"""
SAM3 Model Manager - Handles model management and HuggingFace authentication
for SAM3 (Segment Anything Model 3) integration in WAMA Anonymizer.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional

from wama.settings import AI_MODELS_DIR

logger = logging.getLogger(__name__)

# SAM3 model cache directory (HuggingFace format in centralized AI-models)
SAM3_MODELS_DIR = str(AI_MODELS_DIR / "anonymizer" / "models--facebook--sam3")


def check_sam3_installed() -> bool:
    """
    Check if SAM3 package is installed.

    Returns:
        True if SAM3 is installed and importable
    """
    try:
        import sam3
        return True
    except ImportError:
        return False


def check_hf_auth() -> bool:
    """
    Check if HuggingFace authentication is configured.

    Returns:
        True if HuggingFace token is set
    """
    try:
        from huggingface_hub import HfFolder
        token = HfFolder.get_token()
        return token is not None and len(token) > 0
    except ImportError:
        logger.warning("huggingface_hub not installed")
        return False
    except Exception as e:
        logger.warning(f"Error checking HuggingFace auth: {e}")
        return False


def setup_hf_auth(token: str) -> bool:
    """
    Setup HuggingFace authentication by saving the token.

    Args:
        token: HuggingFace access token (starts with 'hf_')

    Returns:
        True if successful, False otherwise
    """
    if not token or not token.strip():
        logger.error("Empty token provided")
        return False

    token = token.strip()

    # Basic validation
    if not token.startswith('hf_'):
        logger.warning("Token does not start with 'hf_', might be invalid")

    try:
        from huggingface_hub import HfFolder
        HfFolder.save_token(token)
        logger.info("HuggingFace token saved successfully")
        return True
    except ImportError:
        logger.error("huggingface_hub not installed. Install with: pip install huggingface-hub")
        return False
    except Exception as e:
        logger.error(f"Failed to setup HuggingFace auth: {e}")
        return False


def check_sam3_models_cached() -> bool:
    """
    Check if SAM3 models are already cached locally.

    HuggingFace cache structure:
    models--facebook--sam3/
    ├── blobs/          # Contains actual model files
    ├── refs/           # Reference files
    └── snapshots/      # Model snapshots

    Returns:
        True if models appear to be cached locally
    """
    if not os.path.exists(SAM3_MODELS_DIR):
        return False

    # Check for HuggingFace cache structure
    blobs_dir = os.path.join(SAM3_MODELS_DIR, 'blobs')
    snapshots_dir = os.path.join(SAM3_MODELS_DIR, 'snapshots')

    # Models are cached if blobs directory exists and has files
    if os.path.exists(blobs_dir) and os.listdir(blobs_dir):
        return True

    # Or if snapshots directory exists and has content
    if os.path.exists(snapshots_dir) and os.listdir(snapshots_dir):
        return True

    return False


def get_sam3_status() -> Dict:
    """
    Get comprehensive SAM3 installation and configuration status.

    Returns:
        Dict containing:
        - installed: bool - whether SAM3 package is installed
        - hf_authenticated: bool - whether HuggingFace token is configured
        - models_cached: bool - whether models are already downloaded locally
        - models_dir: str - path to SAM3 models directory
        - models_dir_exists: bool - whether models directory exists
        - ready: bool - whether SAM3 is ready to use
        - version: str - SAM3 version if installed, None otherwise
        - error: str - error message if any
    """
    status = {
        'installed': False,
        'hf_authenticated': False,
        'models_cached': False,
        'models_dir': SAM3_MODELS_DIR,
        'models_dir_exists': os.path.exists(SAM3_MODELS_DIR),
        'ready': False,
        'version': None,
        'error': None,
    }

    # Check if SAM3 is installed
    try:
        import sam3
        status['installed'] = True
        status['version'] = getattr(sam3, '__version__', 'unknown')
    except ImportError as e:
        status['error'] = f"SAM3 not installed: {e}"
        return status

    # Check if models are already cached locally
    status['models_cached'] = check_sam3_models_cached()

    # Check HuggingFace authentication
    status['hf_authenticated'] = check_hf_auth()

    # Ready if:
    # - SAM3 is installed AND
    # - Either models are cached locally OR HF is authenticated (for download)
    if status['models_cached']:
        # Models already downloaded, no need for HF auth
        status['ready'] = True
        status['error'] = None
    elif status['hf_authenticated']:
        # Can download models with HF auth
        status['ready'] = True
        status['error'] = None
    else:
        # Need HF auth to download models
        status['ready'] = False
        status['error'] = "HuggingFace token required to download SAM3 models"

    return status


def validate_sam3_prompt(prompt: str) -> Tuple[bool, str]:
    """
    Validate a SAM3 text prompt.

    Args:
        prompt: Text prompt to validate

    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if prompt is valid
        - error_message: Empty string if valid, error description otherwise
    """
    # Check for empty prompt
    if not prompt or not prompt.strip():
        return False, "Le prompt ne peut pas etre vide"

    prompt = prompt.strip()

    # Check length limits
    if len(prompt) < 2:
        return False, "Le prompt doit contenir au moins 2 caracteres"

    if len(prompt) > 500:
        return False, "Le prompt ne peut pas depasser 500 caracteres"

    # Security: Check for potentially dangerous patterns
    dangerous_patterns = [
        '<script', 'javascript:', 'eval(', 'exec(',
        '__import__', 'subprocess', 'os.system',
        '{{', '{%',  # Template injection
    ]
    prompt_lower = prompt.lower()
    for pattern in dangerous_patterns:
        if pattern.lower() in prompt_lower:
            return False, "Le prompt contient des caracteres non autorises"

    return True, ""


def get_sam3_requirements() -> Dict:
    """
    Get SAM3 system requirements and installation instructions.

    Returns:
        Dict with requirements information
    """
    return {
        'python_version': '3.12+',
        'pytorch_version': '2.7+',
        'cuda_version': '12.6+',
        'packages': [
            'sam3>=1.0.0',
            'huggingface-hub>=0.20.0',
            'transformers>=4.36.0',
        ],
        'installation_steps': [
            '1. Creer un environnement conda: conda create -n sam3 python=3.12',
            '2. Activer l\'environnement: conda activate sam3',
            '3. Installer PyTorch: pip install torch==2.7.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126',
            '4. Installer SAM3: pip install sam3',
            '5. Configurer HuggingFace: hf auth login',
        ],
        'hf_model_repo': 'facebook/sam3',
        'hf_access_request_url': 'https://huggingface.co/facebook/sam3',
    }


def ensure_sam3_models_dir() -> str:
    """
    Ensure SAM3 models directory exists.

    Returns:
        Path to the models directory
    """
    Path(SAM3_MODELS_DIR).mkdir(parents=True, exist_ok=True)
    return SAM3_MODELS_DIR


def get_recommended_prompt_examples() -> list:
    """
    Get example prompts to help users understand SAM3 usage.

    Returns:
        List of example prompts with descriptions
    """
    return [
        {
            'prompt': 'all human faces',
            'description': 'Floute tous les visages humains dans l\'image/video',
        },
        {
            'prompt': 'license plates and car registration numbers',
            'description': 'Floute les plaques d\'immatriculation',
        },
        {
            'prompt': 'people in the background',
            'description': 'Floute les personnes en arriere-plan',
        },
        {
            'prompt': 'computer screens and monitors',
            'description': 'Floute les ecrans d\'ordinateur',
        },
        {
            'prompt': 'all text and written content',
            'description': 'Floute tout le texte visible',
        },
        {
            'prompt': 'brand logos and company names',
            'description': 'Floute les logos et noms de marques',
        },
        {
            'prompt': 'children and minors',
            'description': 'Floute les enfants et mineurs',
        },
        {
            'prompt': 'ID cards and documents',
            'description': 'Floute les cartes d\'identite et documents',
        },
    ]
