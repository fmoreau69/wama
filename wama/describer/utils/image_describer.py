"""
Image description via Ollama vision models with BLIP local fallback.

Vision model cascade (in order of preference):
  1. qwen3-vl:8b  — best quality (8B, 256K ctx, VQA + OCR + reasoning)
  2. moondream    — lightweight fallback (1.8B)
  3. BLIP         — local HuggingFace model (no Ollama required)

The cascade auto-detects which Ollama models are available.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Import model configuration
from .model_config import get_model_info

# Global model cache
_blip_processor = None
_blip_model = None

# Cached list of available Ollama models (refreshed per worker process start)
_ollama_available_models: Optional[set] = None


# ---------------------------------------------------------------------------
# Ollama vision helpers
# ---------------------------------------------------------------------------

def _get_available_ollama_models() -> set:
    """Return the set of model names currently pulled in Ollama."""
    global _ollama_available_models
    if _ollama_available_models is not None:
        return _ollama_available_models
    try:
        import httpx
        from django.conf import settings
        host = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            resp = client.get(f"{host}/api/tags")
        if resp.status_code == 200:
            models = {m['name'] for m in resp.json().get('models', [])}
            _ollama_available_models = models
            return models
    except Exception as e:
        logger.debug(f"[image_describer] Ollama unavailable: {e}")
    _ollama_available_models = set()
    return set()


def _describe_with_ollama_vision(model: str, image_path: str, prompt: str) -> Optional[str]:
    """
    Describe an image using any Ollama vision model.
    Uses /api/generate with base64-encoded image.
    Returns description string, or None if unavailable.
    """
    try:
        import base64
        import httpx
        from django.conf import settings
        host = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')

        with open(image_path, 'rb') as fh:
            b64_image = base64.b64encode(fh.read()).decode('utf-8')

        # qwen3-vl uses /api/chat with role:user + image content parts
        # moondream uses /api/generate with top-level images[]
        # We normalise by trying /api/chat first (works for both in recent Ollama),
        # then fallback to /api/generate for older moondream tags.
        payload_chat = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [b64_image],
            }],
            "stream": False,
            "options": {"num_predict": 1024},
        }

        with httpx.Client(timeout=180.0, trust_env=False) as client:
            resp = client.post(f"{host}/api/chat", json=payload_chat)

        if resp.status_code == 200:
            text = resp.json().get("message", {}).get("content", "").strip()
            if text:
                return text

        # Fallback: /api/generate (older Ollama or moondream)
        payload_gen = {
            "model": model,
            "prompt": prompt,
            "images": [b64_image],
            "stream": False,
            "options": {"num_predict": 1024},
        }
        with httpx.Client(timeout=180.0, trust_env=False) as client:
            resp2 = client.post(f"{host}/api/generate", json=payload_gen)

        if resp2.status_code == 200:
            text = resp2.json().get("response", "").strip()
            return text or None

        logger.debug(f"[image_describer] {model} HTTP {resp2.status_code}")
        return None

    except Exception as e:
        logger.debug(f"[image_describer] {model} unavailable: {e}")
        return None


def _best_ollama_vision_model() -> Optional[str]:
    """
    Return the best available Ollama vision model name, or None.
    Priority: qwen3-vl:8b > qwen3-vl > moondream2 > moondream
    """
    available = _get_available_ollama_models()
    priority = ['qwen3-vl:8b', 'qwen3-vl', 'moondream2', 'moondream']
    for model in priority:
        # Match prefix (Ollama can append :latest)
        for avail in available:
            if avail == model or avail.startswith(model + ':'):
                return avail
    return None


def get_blip_model():
    """Load and cache BLIP model."""
    global _blip_processor, _blip_model

    if _blip_processor is None or _blip_model is None:
        logger.info("Loading BLIP model...")

        try:
            import os
            import torch
            from wama.model_manager.services.memory_manager import MemoryManager, MemoryStrategy

            # Get model info from centralized config
            model_info = get_model_info('blip')
            model_name = model_info['model_id']
            cache_dir = str(model_info['local_dir'])

            # ── CRITIQUE : set HF cache BEFORE importing transformers ──────────
            os.environ['HF_HUB_CACHE'] = cache_dir
            os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir
            # ──────────────────────────────────────────────────────────────────

            from transformers import BlipProcessor, BlipForConditionalGeneration

            # Determine VRAM strategy using MemoryManager (~1.8 GB for BLIP)
            strategy = MemoryManager.get_memory_strategy(1.8)
            device = "cpu" if strategy == MemoryStrategy.CPU_ONLY else (
                "cuda" if torch.cuda.is_available() else "cpu"
            )
            logger.info(f"Loading {model_name} — strategy: {strategy.value}, device: {device}")

            _blip_processor = BlipProcessor.from_pretrained(model_name, cache_dir=cache_dir, use_fast=True)
            _blip_model = BlipForConditionalGeneration.from_pretrained(model_name, cache_dir=cache_dir)
            _blip_model = _blip_model.to(device)
            logger.info(f"BLIP model loaded on {device.upper()}")

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

    # Meeting format not applicable to images — silently use detailed
    if output_format == 'meeting':
        output_format = 'detailed'

    console(user_id, "Chargement de l'image…")
    set_progress(description, 20)

    try:
        from PIL import Image
        import torch

        # Load image
        image = Image.open(file_path).convert('RGB')
        console(user_id, f"Taille image: {image.width}x{image.height}")

        set_progress(description, 30)
        set_partial(description, "Analyse de l'image…")

        # Build prompt according to requested format
        if output_format == 'detailed':
            moondream_prompt = "Describe this image in detail."
        elif output_format == 'scientific':
            moondream_prompt = "Provide a scientific analysis of this image."
        elif output_format == 'bullet_points':
            moondream_prompt = "List the key elements visible in this image."
        else:
            moondream_prompt = "Briefly describe this image."

        # --- Try best available Ollama vision model ---
        ollama_model = _best_ollama_vision_model()
        caption = None
        if ollama_model:
            console(user_id, f"Essai {ollama_model} (Ollama)…")
            caption = _describe_with_ollama_vision(ollama_model, file_path, moondream_prompt)
            if caption:
                console(user_id, f"Description générée avec {ollama_model} ✓")
                set_progress(description, 70)
                set_partial(description, caption)

        if not caption:
            # --- Fallback: BLIP ---
            msg = "Aucun modèle Ollama vision disponible" if not ollama_model else f"{ollama_model} indisponible"
            console(user_id, f"{msg}, utilisation de BLIP…")
            set_partial(description, "Chargement du modèle BLIP…")

            processor, model = get_blip_model()

            set_progress(description, 50)
            console(user_id, "Génération de la description (BLIP)…")
            set_partial(description, "Analyse BLIP…")

            device = str(next(model.parameters()).device)

            # Conditional captioning prefix
            if output_format == 'detailed':
                blip_text = "a photograph of"
            elif output_format == 'scientific':
                blip_text = "this image shows"
            else:
                blip_text = None

            if blip_text:
                inputs = processor(image, blip_text, return_tensors="pt").to(device)
            else:
                inputs = processor(image, return_tensors="pt").to(device)

            max_new_tokens = min(200 if output_format in ('detailed', 'scientific') else 100, max_length)
            out = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                num_beams=5,
                repetition_penalty=1.2,
            )
            caption = processor.decode(out[0], skip_special_tokens=True)
            console(user_id, "Description générée avec BLIP ✓")
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
