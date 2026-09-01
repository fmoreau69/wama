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
from .model_config import get_model_info  # noqa: F401 — consommé par le backend BLIP et l'app

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
        from wama.common.utils.ollama_host import ollama_base
        host = ollama_base()
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
        from wama.common.utils.ollama_host import ollama_base
        host = ollama_base()

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
    Priority: gemma4:12b > gemma4:e4b (12b validé bon describer FR, 256K ; e4b = repli
    plus léger + audio). Liste confrontée au RÉEL à l'appel (fallthrough sur les modèles
    présents) — nettoyée le 2026-08-12 des entrées jamais installées (qwen3-vl:8b,
    moondream…) : un candidat futur passe par la prospection, pas par du vocabulaire
    mort ici. Correctif de fond = capacité `vision` au catalogue (cf. llm_utils).
    """
    available = _get_available_ollama_models()
    priority = ['gemma4:12b', 'gemma4:e4b']
    for model in priority:
        # Match prefix (Ollama can append :latest)
        for avail in available:
            if avail == model or avail.startswith(model + ':'):
                return avail
    return None


# Le chargement/déchargement BLIP vit dans `describer/backends/blip_backend.py`
# (contrat commun BaseModelBackend, 2026-08-17) — l'ancien cache de module
# `_blip_processor/_blip_model` + `get_blip_model()` est REMPLACÉ, pas doublé.


# Prompts vision localisés — graine de l'orchestration de traduction (ROADMAP §10.B) :
# si le modèle vision est multilingue, on le prompte DIRECTEMENT dans la langue de sortie
# (évite la chaîne « caption EN → reformatage FR » en aval). Sinon EN.
_VISION_PROMPTS = {  # wama:redondance-ok — prompts vision par style (info nouvelle ; styles manquants → fallback)
    'detailed':      {'en': "Describe this image in detail.",
                      'fr': "Décris cette image en détail."},
    'scientific':    {'en': "Provide a scientific analysis of this image.",
                      'fr': "Fournis une analyse scientifique de cette image."},
    'bullet_points': {'en': "List the key elements visible in this image.",
                      'fr': "Liste les éléments clés visibles dans cette image."},
    'brief':         {'en': "Briefly describe this image.",
                      'fr': "Décris brièvement cette image."},
}


def _is_multilingual_vision(model: Optional[str]) -> bool:
    """Modèles vision Ollama multilingues (décrivent directement en langue cible)."""
    m = (model or '').lower()
    return m.startswith('gemma4') or 'qwen' in m  # moondream = anglophone


def _vision_prompt(output_style: str, output_language: str, model: Optional[str]) -> str:
    """Prompt vision dans output_language si le modèle est multilingue, sinon EN (reformaté en aval)."""
    spec = _VISION_PROMPTS.get(output_style, _VISION_PROMPTS['brief'])
    lang = output_language if (_is_multilingual_vision(model) and output_language in spec) else 'en'
    return spec[lang]


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
    output_style = description.output_style
    output_language = description.output_language
    max_length = description.max_length

    # Meeting format not applicable to images — silently use detailed
    if output_style == 'meeting':
        output_style = 'detailed'

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

        # --- Pick the vision model first: its language ability decides the prompt language ---
        # Graine §10.B : prompter direct dans la langue de sortie si le modèle est multilingue
        # (gemma4/qwen), au lieu de la chaîne « caption EN → reformatage FR » en aval.
        ollama_model = _best_ollama_vision_model()
        moondream_prompt = _vision_prompt(output_style, output_language, ollama_model)
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

            from wama.describer.backends import get_blip
            blip = get_blip()
            blip.load()

            set_progress(description, 50)
            console(user_id, "Génération de la description (BLIP)…")
            set_partial(description, "Analyse BLIP…")

            # Amorce de conditionnement — POLITIQUE de style (le backend est neutre)
            if output_style == 'detailed':
                blip_text = "a photograph of"
            elif output_style == 'scientific':
                blip_text = "this image shows"
            else:
                blip_text = None

            max_new_tokens = min(200 if output_style in ('detailed', 'scientific') else 100, max_length)
            caption = blip.process(image=image, prefix=blip_text,
                                   max_new_tokens=max_new_tokens,
                                   num_beams=5, repetition_penalty=1.2)
            console(user_id, "Description générée avec BLIP ✓")
            set_progress(description, 70)
            set_partial(description, caption)

        # Post-process based on format
        result = format_image_result(caption, output_style, output_language)

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


def format_image_result(caption: str, output_style: str, language: str) -> str:
    """Format the caption based on output format."""
    caption = caption.strip()

    # Capitalize first letter
    if caption and caption[0].islower():
        caption = caption[0].upper() + caption[1:]

    # Add period if missing
    if caption and not caption.endswith('.'):
        caption += '.'

    if output_style == 'bullet_points':
        # Convert to bullet points
        sentences = caption.replace('. ', '.\n').split('\n')
        return '\n'.join(f"- {s.strip()}" for s in sentences if s.strip())

    elif output_style == 'scientific':
        return f"Image Analysis:\n\n{caption}\n\nNote: This description was generated automatically using computer vision."

    elif output_style == 'summary':
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
