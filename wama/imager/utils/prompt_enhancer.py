"""
WAMA Imager - Prompt Enhancer via Ollama

Wraps wama.common.utils.llm_utils.ollama_chat() to enrich image/video prompts.
Zero VRAM overhead — runs entirely in the Ollama process.

Model configured via settings.OLLAMA_PROMPT_ENHANCE_MODEL (default: gemma3).
"""

import logging
from django.conf import settings

logger = logging.getLogger(__name__)

_ENHANCE_MODEL_SETTING = getattr(settings, 'OLLAMA_PROMPT_ENHANCE_MODEL', 'gemma3')


def _resolve_model_name() -> str:
    """
    Resolve the configured model name to the exact name known by Ollama.

    If the setting is 'gemma3' but Ollama has 'gemma3:4b', returns 'gemma3:4b'.
    Falls back to the raw setting if Ollama is unreachable.
    """
    import httpx
    host = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
    try:
        r = httpx.get(f'{host}/api/tags', timeout=3.0, trust_env=False)
        models = [m['name'] for m in r.json().get('models', [])]
        # Exact match first
        if _ENHANCE_MODEL_SETTING in models:
            return _ENHANCE_MODEL_SETTING
        # Prefix match: 'gemma3' matches 'gemma3:4b', 'gemma3:12b', etc.
        for m in models:
            if m.startswith(_ENHANCE_MODEL_SETTING + ':') or m.startswith(_ENHANCE_MODEL_SETTING + '-'):
                logger.info(f'[PromptEnhancer] Resolved model "{_ENHANCE_MODEL_SETTING}" → "{m}"')
                return m
    except Exception:
        pass
    return _ENHANCE_MODEL_SETTING


ENHANCE_MODEL = _resolve_model_name()

_SYSTEM_IMAGE = (
    "You are an expert AI image generation prompt engineer. "
    "Transform the user's simple prompt into a detailed, high-quality prompt for image generation models "
    "(Stable Diffusion, Flux, Hunyuan, etc.).\n\n"
    "Rules:\n"
    "- Add specific visual details: lighting, composition, atmosphere, art style\n"
    "- Preserve the user's exact subject and intent — do not invent new subjects\n"
    "- Keep the result concise (40-120 words), comma-separated descriptors\n"
    "- Output the enhanced prompt ONLY — no explanations, no preamble\n\n"
    "Example:\n"
    "User: a researcher in a lab\n"
    "Output: a middle-aged researcher in a white lab coat standing at a stainless steel bench, "
    "modern laboratory with sophisticated equipment, bright fluorescent overhead lighting, "
    "sharp shadows, sterile professional environment, photorealistic, high detail"
)

_SYSTEM_VIDEO = (
    "You are an expert AI video generation prompt engineer. "
    "Transform the user's simple prompt into a detailed, cinematic prompt for video generation models "
    "(LTX-Video, CogVideoX, Mochi, etc.).\n\n"
    "Rules:\n"
    "- Describe motion and camera movement explicitly (slow pan, tracking shot, dolly in, etc.)\n"
    "- Add temporal and dynamic details: lighting evolution, movement direction, scene dynamics\n"
    "- Preserve the user's exact subject and intent\n"
    "- Keep it concise (40-120 words), comma-separated descriptors\n"
    "- Output the enhanced prompt ONLY — no explanations\n\n"
    "Example:\n"
    "User: a car on a road\n"
    "Output: a sleek modern sports car driving along a coastal highway at sunset, "
    "camera tracking smoothly from the side, warm golden light reflecting off the metallic body, "
    "gentle ocean waves visible in the background, cinematic motion blur, photorealistic"
)


def enhance_prompt(prompt: str, mode: str = 'image') -> str:
    """
    Enhance a user prompt using the configured Ollama model.

    Args:
        prompt: Original user prompt
        mode:   'image' or 'video' — selects the system prompt

    Returns:
        Enhanced prompt string

    Raises:
        RuntimeError: if Ollama is unreachable or returns an error
    """
    from wama.common.utils.llm_utils import ollama_chat

    system = _SYSTEM_VIDEO if mode == 'video' else _SYSTEM_IMAGE

    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': prompt},
    ]

    model = _resolve_model_name()
    text, error = ollama_chat(messages, model=model)

    if error:
        raise RuntimeError(error)
    if not text:
        raise RuntimeError('Réponse vide de Ollama')

    # Strip leading/trailing noise (model sometimes adds "Output:" prefix)
    for prefix in ('Output:', 'Enhanced:', 'Result:'):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()

    logger.info(f'[PromptEnhancer] "{prompt[:40]}" → "{text[:60]}"')
    return text


def is_enhance_available() -> bool:
    """Check if Ollama is running and the enhance model is loaded."""
    import httpx
    host = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
    try:
        r = httpx.get(f'{host}/api/tags', timeout=3.0, trust_env=False)
        models = [m['name'] for m in r.json().get('models', [])]
        return any(ENHANCE_MODEL in m for m in models)
    except Exception:
        return False
