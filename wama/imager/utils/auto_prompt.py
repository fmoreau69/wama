"""
Auto-prompt generation from reference images.
Uses BLIP model from Describer module for image captioning.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_prompt_from_image(image_path: str, style: str = 'detailed') -> str:
    """
    Generate a prompt from a reference image using BLIP.

    Uses the BLIP model from wama.describer to analyze the image
    and generate a descriptive prompt suitable for image generation.

    Args:
        image_path: Path to the reference image
        style: Prompt style - 'detailed', 'simple', or 'artistic'

    Returns:
        Generated prompt string
    """
    logger.info(f"Generating prompt from image: {image_path}")

    try:
        from wama.describer.utils.image_describer import get_blip_model
        from PIL import Image
        import torch

        # Load the image
        image = Image.open(image_path).convert('RGB')
        logger.info(f"Image loaded: {image.width}x{image.height}")

        # Load BLIP model (cached)
        processor, model = get_blip_model()
        device = "cuda" if torch.cuda.is_available() else "cpu"

        # Choose conditioning text based on style
        if style == 'artistic':
            conditioning_text = "an artistic painting of"
        elif style == 'simple':
            conditioning_text = None  # Unconditional
        else:  # detailed
            conditioning_text = "a detailed photograph of"

        # Prepare inputs
        if conditioning_text:
            inputs = processor(image, conditioning_text, return_tensors="pt").to(device)
        else:
            inputs = processor(image, return_tensors="pt").to(device)

        # Generate caption
        out = model.generate(
            **inputs,
            max_new_tokens=150,
            num_beams=5,
            repetition_penalty=1.2,
            length_penalty=1.0,
        )

        caption = processor.decode(out[0], skip_special_tokens=True)
        logger.info(f"Raw caption: {caption}")

        # Format as prompt
        prompt = format_as_prompt(caption, style)
        logger.info(f"Generated prompt: {prompt}")

        return prompt

    except ImportError as e:
        logger.error(f"Failed to import Describer module: {e}")
        raise ImportError(
            "Describer module is required for auto-prompt generation. "
            "Ensure wama.describer is properly installed."
        )
    except Exception as e:
        logger.exception(f"Error generating prompt from image: {e}")
        raise


def format_as_prompt(caption: str, style: str = 'detailed') -> str:
    """
    Format a raw caption into a prompt optimized for image generation.

    Args:
        caption: Raw caption from BLIP
        style: Prompt style for formatting

    Returns:
        Formatted prompt string
    """
    # Remove common prefixes from conditioned captions
    prefixes_to_remove = [
        'a detailed photograph of',
        'an artistic painting of',
        'a photograph of',
        'a picture of',
        'an image of',
        'this image shows',
        'the image shows',
    ]

    prompt = caption.strip()
    prompt_lower = prompt.lower()

    for prefix in prefixes_to_remove:
        if prompt_lower.startswith(prefix):
            prompt = prompt[len(prefix):].strip()
            break

    # Capitalize first letter
    if prompt and prompt[0].islower():
        prompt = prompt[0].upper() + prompt[1:]

    # Add style-specific enhancements
    if style == 'artistic':
        # Add artistic modifiers
        if not any(word in prompt.lower() for word in ['painting', 'art', 'artistic']):
            prompt = f"{prompt}, artistic style"

    elif style == 'detailed':
        # Add quality modifiers for better generation
        quality_terms = ['highly detailed', '4k', 'professional']
        if not any(term in prompt.lower() for term in quality_terms):
            prompt = f"{prompt}, highly detailed, professional quality"

    return prompt


def enhance_prompt_for_generation(prompt: str, style_hints: list = None) -> str:
    """
    Enhance a prompt with additional modifiers for better generation.

    Args:
        prompt: Base prompt
        style_hints: Optional list of style modifiers to add

    Returns:
        Enhanced prompt
    """
    enhanced = prompt.strip()

    # Default quality modifiers
    default_modifiers = [
        "high quality",
        "detailed",
    ]

    # Add style hints if provided
    if style_hints:
        for hint in style_hints:
            if hint.lower() not in enhanced.lower():
                enhanced = f"{enhanced}, {hint}"

    # Add default modifiers if not present
    for modifier in default_modifiers:
        if modifier.lower() not in enhanced.lower():
            enhanced = f"{enhanced}, {modifier}"

    return enhanced


def extract_style_from_image(image_path: str) -> dict:
    """
    Analyze an image to extract style characteristics.

    This can be used for style transfer to understand what
    style elements to preserve.

    Args:
        image_path: Path to the style reference image

    Returns:
        Dict with style characteristics
    """
    try:
        from PIL import Image
        import colorsys

        image = Image.open(image_path).convert('RGB')

        # Analyze dominant colors
        image_small = image.resize((50, 50))
        pixels = list(image_small.getdata())

        # Calculate average color
        avg_r = sum(p[0] for p in pixels) // len(pixels)
        avg_g = sum(p[1] for p in pixels) // len(pixels)
        avg_b = sum(p[2] for p in pixels) // len(pixels)

        # Convert to HSV for better analysis
        h, s, v = colorsys.rgb_to_hsv(avg_r / 255, avg_g / 255, avg_b / 255)

        # Determine color temperature
        if h < 0.1 or h > 0.9:
            temperature = "warm"
        elif 0.5 < h < 0.7:
            temperature = "cool"
        else:
            temperature = "neutral"

        # Determine saturation level
        if s < 0.2:
            saturation = "desaturated"
        elif s > 0.7:
            saturation = "vibrant"
        else:
            saturation = "moderate"

        # Determine brightness
        if v < 0.3:
            brightness = "dark"
        elif v > 0.7:
            brightness = "bright"
        else:
            brightness = "medium"

        return {
            'temperature': temperature,
            'saturation': saturation,
            'brightness': brightness,
            'dominant_hue': h,
            'avg_color': (avg_r, avg_g, avg_b),
        }

    except Exception as e:
        logger.warning(f"Could not analyze image style: {e}")
        return {}


def generate_style_prompt(style_info: dict) -> str:
    """
    Generate style modifiers from analyzed style info.

    Args:
        style_info: Dict from extract_style_from_image

    Returns:
        Style modifier string
    """
    modifiers = []

    if style_info.get('temperature') == 'warm':
        modifiers.append("warm tones")
    elif style_info.get('temperature') == 'cool':
        modifiers.append("cool tones")

    if style_info.get('saturation') == 'vibrant':
        modifiers.append("vibrant colors")
    elif style_info.get('saturation') == 'desaturated':
        modifiers.append("muted colors")

    if style_info.get('brightness') == 'dark':
        modifiers.append("dark atmosphere")
    elif style_info.get('brightness') == 'bright':
        modifiers.append("bright lighting")

    return ", ".join(modifiers) if modifiers else ""
