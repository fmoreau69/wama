"""
Image description using BLIP model.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Global model cache
_blip_processor = None
_blip_model = None


def get_blip_model():
    """Load and cache BLIP model."""
    global _blip_processor, _blip_model

    if _blip_processor is None or _blip_model is None:
        logger.info("Loading BLIP model...")

        try:
            from transformers import BlipProcessor, BlipForConditionalGeneration
            import torch

            model_name = "Salesforce/blip-image-captioning-large"

            _blip_processor = BlipProcessor.from_pretrained(model_name)
            _blip_model = BlipForConditionalGeneration.from_pretrained(model_name)

            # Move to GPU if available
            if torch.cuda.is_available():
                _blip_model = _blip_model.to("cuda")
                logger.info("BLIP model loaded on GPU")
            else:
                logger.info("BLIP model loaded on CPU")

        except ImportError as e:
            logger.error(f"Failed to import transformers: {e}")
            raise ImportError(
                "transformers library not installed. "
                "Run: pip install transformers torch pillow"
            )

    return _blip_processor, _blip_model


def describe_image(description, set_progress, set_partial, console):
    """
    Describe an image using BLIP model.

    Args:
        description: Description model instance
        set_progress: Function to update progress
        set_partial: Function to set partial result
        console: Function to log to console

    Returns:
        str: Image description text
    """
    user_id = description.user_id
    file_path = description.input_file.path
    output_format = description.output_format
    output_language = description.output_language
    max_length = description.max_length

    console(user_id, "Loading image...")
    set_progress(description, 20)

    try:
        from PIL import Image
        import torch

        # Load image
        image = Image.open(file_path).convert('RGB')
        console(user_id, f"Image size: {image.width}x{image.height}")

        set_progress(description, 30)
        set_partial(description, "Loading AI model...")

        # Load model
        processor, model = get_blip_model()

        set_progress(description, 50)
        console(user_id, "Generating description...")
        set_partial(description, "Analyzing image...")

        # Generate caption
        device = "cuda" if torch.cuda.is_available() else "cpu"

        # Conditional captioning for more detailed descriptions
        if output_format == 'detailed':
            text = "a photograph of"
        elif output_format == 'scientific':
            text = "this image shows"
        else:
            text = None

        if text:
            inputs = processor(image, text, return_tensors="pt").to(device)
        else:
            inputs = processor(image, return_tensors="pt").to(device)

        # Generate with parameters based on format
        max_new_tokens = min(100, max_length)
        if output_format in ('detailed', 'scientific'):
            max_new_tokens = min(200, max_length)

        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            num_beams=5,
            repetition_penalty=1.2,
        )

        caption = processor.decode(out[0], skip_special_tokens=True)

        set_progress(description, 70)
        set_partial(description, caption)

        # Post-process based on format
        result = format_image_result(caption, output_format, output_language)

        set_progress(description, 85)
        console(user_id, "Description generated successfully")

        # Translate if needed
        if output_language == 'fr':
            result = translate_to_french(result, console, user_id)
            set_progress(description, 90)

        return result

    except Exception as e:
        logger.exception(f"Error describing image: {e}")
        raise


def format_image_result(caption: str, output_format: str, language: str) -> str:
    """Format the caption based on output format."""
    caption = caption.strip()

    # Capitalize first letter
    if caption and caption[0].islower():
        caption = caption[0].upper() + caption[1:]

    # Add period if missing
    if caption and not caption.endswith('.'):
        caption += '.'

    if output_format == 'bullet_points':
        # Convert to bullet points
        sentences = caption.replace('. ', '.\n').split('\n')
        return '\n'.join(f"- {s.strip()}" for s in sentences if s.strip())

    elif output_format == 'scientific':
        return f"Image Analysis:\n\n{caption}\n\nNote: This description was generated automatically using computer vision."

    elif output_format == 'summary':
        # Keep it short
        if len(caption) > 200:
            caption = caption[:197] + '...'
        return caption

    else:  # detailed
        return caption


def translate_to_french(text: str, console, user_id: int) -> str:
    """Translate text to French using deep-translator."""
    try:
        from deep_translator import GoogleTranslator

        console(user_id, "Translating to French...")
        translator = GoogleTranslator(source='en', target='fr')

        # Split long text if needed
        if len(text) > 4500:
            chunks = [text[i:i+4500] for i in range(0, len(text), 4500)]
            translated = [translator.translate(chunk) for chunk in chunks]
            return ''.join(translated)

        return translator.translate(text)

    except ImportError:
        logger.warning("deep-translator not installed, skipping translation")
        return text
    except Exception as e:
        logger.warning(f"Translation failed: {e}")
        return text
