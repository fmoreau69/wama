"""
Model Format Policy Configuration

Centralized configuration for model format preferences across WAMA applications.
Defines which format should be used for each type of model and use case.

Policy:
- Model weights (storage) → safetensors
- AI Pipeline (Diffusers) → PyTorch / safetensors
- Micro-services (vision/audio) → ONNX
- Embeddings → ONNX or native
- Cache → safetensors
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum


class ModelFormat(Enum):
    """Supported model formats."""
    PT = 'pt'
    PTH = 'pth'
    SAFETENSORS = 'safetensors'
    ONNX = 'onnx'
    BIN = 'bin'
    GGUF = 'gguf'
    CKPT = 'ckpt'
    UNKNOWN = 'unknown'


class RuntimeType(Enum):
    """Model runtime environments."""
    PYTORCH = 'pytorch'
    ONNXRUNTIME = 'onnxruntime'
    OLLAMA = 'ollama'
    NATIVE = 'native'


@dataclass
class FormatPolicyConfig:
    """Configuration for a model category's format policy."""
    preferred_format: str
    runtime: str
    auto_convert: bool
    keep_original: bool
    convertible_to: List[str]
    description: str = ''


# Main format policy configuration
FORMAT_POLICY: Dict[str, FormatPolicyConfig] = {
    # Diffusion models (Imager: SD, Wan, Hunyuan)
    'diffusion': FormatPolicyConfig(
        preferred_format='safetensors',
        runtime='pytorch',
        auto_convert=True,
        keep_original=False,
        convertible_to=['safetensors', 'onnx'],
        description='Image/Video generation models (Stable Diffusion, Wan, Hunyuan)',
    ),

    # Vision models (Anonymizer: YOLO, SAM)
    'vision': FormatPolicyConfig(
        preferred_format='onnx',
        runtime='onnxruntime',
        auto_convert=False,  # YOLO requires specific export
        keep_original=True,
        convertible_to=['onnx'],
        description='Object detection and segmentation models (YOLO, SAM)',
    ),

    # Speech models (Whisper, TTS)
    'speech': FormatPolicyConfig(
        preferred_format='onnx',
        runtime='onnxruntime',
        auto_convert=False,
        keep_original=True,
        convertible_to=['onnx', 'safetensors'],
        description='Speech recognition and synthesis models (Whisper, Coqui, Bark)',
    ),

    # Upscaling models (Enhancer)
    'upscaling': FormatPolicyConfig(
        preferred_format='onnx',
        runtime='onnxruntime',
        auto_convert=False,
        keep_original=False,
        convertible_to=['onnx'],
        description='Image upscaling and enhancement models (RealESRGAN, BSRGAN)',
    ),

    # Vision-Language models (BLIP, BART)
    'vlm': FormatPolicyConfig(
        preferred_format='safetensors',
        runtime='pytorch',
        auto_convert=True,
        keep_original=False,
        convertible_to=['safetensors'],
        description='Vision-Language models (BLIP, BART)',
    ),

    # Summarization models
    'summarization': FormatPolicyConfig(
        preferred_format='safetensors',
        runtime='pytorch',
        auto_convert=True,
        keep_original=False,
        convertible_to=['safetensors'],
        description='Text summarization models (BART)',
    ),

    # LLM models (Ollama)
    'llm': FormatPolicyConfig(
        preferred_format='gguf',
        runtime='ollama',
        auto_convert=False,  # Managed by Ollama
        keep_original=True,
        convertible_to=[],
        description='Large Language Models (managed by Ollama)',
    ),

    # Embedding models
    'embedding': FormatPolicyConfig(
        preferred_format='onnx',
        runtime='onnxruntime',
        auto_convert=False,
        keep_original=True,
        convertible_to=['onnx', 'safetensors'],
        description='Text and image embedding models',
    ),
}

# Map ModelType enum values to policy categories
MODEL_TYPE_TO_CATEGORY = {
    'VISION': 'vision',
    'DIFFUSION': 'diffusion',
    'SPEECH': 'speech',
    'VLM': 'vlm',
    'LLM': 'llm',
    'SUMMARIZATION': 'summarization',
    'UPSCALING': 'upscaling',
}

# Map source to default category
SOURCE_TO_CATEGORY = {
    'imager': 'diffusion',
    'anonymizer': 'vision',
    'enhancer': 'upscaling',
    'describer': 'vlm',  # Default, can be speech for whisper
    'transcriber': 'speech',
    'synthesizer': 'speech',
    'ollama': 'llm',
}


def get_preferred_format(category: str) -> str:
    """
    Get the preferred format for a model category.

    Args:
        category: Model category (e.g., 'vision', 'diffusion', 'speech')

    Returns:
        Preferred format string (e.g., 'safetensors', 'onnx')
    """
    policy = FORMAT_POLICY.get(category.lower())
    if policy:
        return policy.preferred_format
    return 'safetensors'  # Default


def get_policy(category: str) -> Optional[FormatPolicyConfig]:
    """
    Get the full policy configuration for a category.

    Args:
        category: Model category

    Returns:
        FormatPolicyConfig or None if not found
    """
    return FORMAT_POLICY.get(category.lower())


def get_category_for_model_type(model_type: str) -> str:
    """
    Map a ModelType enum value to a policy category.

    Args:
        model_type: ModelType value (e.g., 'VISION', 'DIFFUSION')

    Returns:
        Category string for FORMAT_POLICY lookup
    """
    return MODEL_TYPE_TO_CATEGORY.get(model_type.upper(), 'diffusion')


def get_category_for_source(source: str) -> str:
    """
    Map a model source to a policy category.

    Args:
        source: Source string (e.g., 'imager', 'anonymizer')

    Returns:
        Category string for FORMAT_POLICY lookup
    """
    return SOURCE_TO_CATEGORY.get(source.lower(), 'diffusion')


def should_auto_convert(category: str) -> bool:
    """
    Check if models of this category should be auto-converted on download.

    Args:
        category: Model category

    Returns:
        True if auto-conversion is enabled for this category
    """
    policy = FORMAT_POLICY.get(category.lower())
    return policy.auto_convert if policy else False


def get_convertible_formats(category: str) -> List[str]:
    """
    Get the list of formats a category can be converted to.

    Args:
        category: Model category

    Returns:
        List of target format strings
    """
    policy = FORMAT_POLICY.get(category.lower())
    return policy.convertible_to if policy else []


def is_format_preferred(current_format: str, category: str) -> bool:
    """
    Check if the current format matches the preferred format for the category.

    Args:
        current_format: Current format (e.g., 'pt', 'safetensors')
        category: Model category

    Returns:
        True if current format is the preferred one
    """
    preferred = get_preferred_format(category)
    return current_format.lower() == preferred.lower()


def get_conversion_suggestion(current_format: str, category: str) -> Optional[str]:
    """
    Get a suggestion for format conversion if applicable.

    Args:
        current_format: Current format of the model
        category: Model category

    Returns:
        Suggested target format or None if no conversion needed/possible
    """
    if is_format_preferred(current_format, category):
        return None

    policy = FORMAT_POLICY.get(category.lower())
    if not policy:
        return None

    if policy.preferred_format in policy.convertible_to:
        return policy.preferred_format

    return None


def get_format_stats_template() -> Dict[str, int]:
    """
    Get a template dictionary for format statistics.

    Returns:
        Dict with all format types initialized to 0
    """
    return {
        'pt': 0,
        'pth': 0,
        'safetensors': 0,
        'onnx': 0,
        'bin': 0,
        'gguf': 0,
        'ckpt': 0,
        'unknown': 0,
    }


def get_all_categories() -> List[str]:
    """
    Get all defined policy categories.

    Returns:
        List of category names
    """
    return list(FORMAT_POLICY.keys())


def get_policy_summary() -> Dict[str, Dict]:
    """
    Get a summary of all policies for display.

    Returns:
        Dict mapping category to policy summary
    """
    summary = {}
    for category, policy in FORMAT_POLICY.items():
        summary[category] = {
            'preferred_format': policy.preferred_format,
            'runtime': policy.runtime,
            'auto_convert': policy.auto_convert,
            'description': policy.description,
        }
    return summary
