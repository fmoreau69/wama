"""
SAM3 Model Manager — état et prompts de SAM3 (Segment Anything Model 3) dans l'anonymizer.

⚠ Le JETON HuggingFace ne se gère plus ici (2026-09-27, décision de Fabien). `setup_hf_auth`
l'écrivait dans le dossier personnel (`HfFolder.save_token`) — ce que le socle a retiré partout
ailleurs le 07/09 — et `check_hf_auth` faisait dire « Config HF requise » à tout utilisateur,
alors qu'un SAM3 installé se charge par chemin local, SANS jeton (`sam3_processor`,
`load_from_HF=False`). Le jeton ne sert qu'au TÉLÉCHARGEMENT : il se pose au profil (règle
commune des clés, source `huggingface`) et c'est celui de la personne qui installe.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional

from wama.settings import AI_MODELS_DIR

logger = logging.getLogger(__name__)

# Dépôt HuggingFace d'ORIGINE des poids SAM3 — source unique : consommé par
# get_sam3_requirements() ET par la découverte (model_registry → ModelInfo.hf_id →
# provenance/licences).
SAM3_HF_REPO = 'facebook/sam3'

# Import centralized model configuration
try:
    from .model_config import get_sam3_dir
    MODEL_CONFIG_AVAILABLE = True
    SAM3_MODELS_DIR = str(get_sam3_dir())
except ImportError:
    MODEL_CONFIG_AVAILABLE = False
    # Fallback to legacy path
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
    """État de SAM3 pour la pastille et le catalogue.

    PRÊT = le paquet `sam3` est importable ET les poids sont sur le disque : c'est tout ce que
    le chargement demande. Sinon, la pastille dit quoi faire — installer le modèle depuis le
    gestionnaire de modèles, avec SON jeton HuggingFace posé au profil (`profile_url`) : le
    dépôt est « sur approbation » chez Meta (`gated`, lu au catalogue), l'accès se demande sur
    `access_url` avec le même compte.

    Clés : installed, models_cached, ready, gated, version, error, models_dir,
    models_dir_exists, profile_url, access_url.
    """
    status = {
        'installed': False,
        # DISQUE d'abord, AVANT le retour anticipé « paquet absent » : les poids sont une
        # propriété du disque, pas du venv. Le retour anticipé rendait models_cached=False
        # depuis venv_win (sam3 installé côté venv_linux seulement) → faux positif
        # verify_models « catalogue dit téléchargé, disque non » (constaté 2026-08-12).
        'models_cached': check_sam3_models_cached(),
        'models_dir': SAM3_MODELS_DIR,
        'models_dir_exists': os.path.exists(SAM3_MODELS_DIR),
        'ready': False,
        'version': None,
        'error': None,
        'gated': '',
        'access_url': f'https://huggingface.co/{SAM3_HF_REPO}',
        'profile_url': '',
    }
    try:
        from django.urls import reverse
        status['profile_url'] = reverse('accounts:profile')
    except Exception:
        pass
    try:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key='anonymizer:sam3').values('gated').first()
        status['gated'] = (row or {}).get('gated') or ''
    except Exception:
        pass

    try:
        import sam3
        status['installed'] = True
        status['version'] = getattr(sam3, '__version__', 'unknown')
    except ImportError as e:
        status['error'] = f"SAM3 not installed: {e}"
        return status

    status['ready'] = bool(status['models_cached'])
    if not status['ready']:
        status['error'] = ("Poids SAM3 absents — à installer depuis le gestionnaire de modèles, "
                           "avec votre jeton HuggingFace posé au profil.")
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
            "5. Poser son jeton HuggingFace au profil (Clés d'API), puis installer le modèle "
            "depuis le gestionnaire de modèles",
        ],
        'hf_model_repo': SAM3_HF_REPO,
        'hf_access_request_url': f'https://huggingface.co/{SAM3_HF_REPO}',
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
