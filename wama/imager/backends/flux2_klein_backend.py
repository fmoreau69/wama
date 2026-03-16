"""
WAMA Imager - FLUX.2 [klein] 4B Backend

Text-to-Image generation using FLUX.2 [klein] 4B via HuggingFace Diffusers.
Apache 2.0 licensed. Ultra-fast distilled model: 4 steps, <1s per image, ~13GB VRAM.

Model: black-forest-labs/FLUX.2-klein-4B
Pipeline: Flux2KleinPipeline (diffusers >= 0.37)

Supports:
- Text-to-Image (T2I): prompt → image
- Image-conditioned generation: prompt + reference image → image
"""

import gc
import logging
import os
from pathlib import Path
from typing import Optional, Callable, List

from django.conf import settings

from .base import ImageGenerationBackend, GenerationParams, GenerationResult

logger = logging.getLogger(__name__)


def _get_flux2_klein_cache_dir() -> str:
    """Get cache directory for FLUX.2 Klein models."""
    try:
        from wama.imager.utils.model_config import FLUX2_KLEIN_DIR
        return str(FLUX2_KLEIN_DIR)
    except ImportError:
        pass
    base_dir = Path(settings.BASE_DIR)
    models_dir = base_dir / "AI-models" / "models" / "diffusion" / "flux2-klein"
    models_dir.mkdir(parents=True, exist_ok=True)
    return str(models_dir)


# Module-level pipeline cache — avoids reloading 13GB weights on every task.
_PIPELINE_CACHE: dict = {}  # {model_name: pipeline}

SUPPORTED_MODELS = {
    "flux2-klein-4b": {
        "name": "FLUX.2 Klein 4B",
        "hf_id": "black-forest-labs/FLUX.2-klein-4B",
        "description": "Ultra-rapide (<1s), 4 steps distillé, 13GB VRAM, Apache 2.0",
        "vram": "13GB",
        "default_guidance_scale": 1.0,
        "default_steps": 4,
    },
}


class Flux2KleinBackend(ImageGenerationBackend):
    """
    Image generation backend using FLUX.2 [klein] 4B.

    Ultra-fast distilled model: 4 inference steps, sub-second generation.
    Supports T2I and image-conditioned generation via Flux2KleinPipeline.
    """

    name = "flux2_klein"
    display_name = "FLUX.2 Klein 4B"

    def __init__(self):
        super().__init__()
        self._pipe = None
        self._current_model = None
        self._torch = None

    @classmethod
    def is_available(cls) -> bool:
        try:
            import torch
            if not torch.cuda.is_available():
                return False
            from diffusers import Flux2KleinPipeline  # noqa
            return True
        except ImportError:
            return False

    def _get_device(self) -> str:
        if self._torch is None:
            import torch
            self._torch = torch
        return "cuda" if self._torch.cuda.is_available() else "cpu"

    def load(self, model_name: str) -> bool:
        """Load the FLUX.2 Klein pipeline. Uses module-level cache."""
        global _PIPELINE_CACHE

        if model_name not in SUPPORTED_MODELS:
            logger.error(f"[Flux2Klein] Unknown model: {model_name}")
            return False

        # Return cached pipeline
        if model_name in _PIPELINE_CACHE:
            logger.info(f"[Flux2Klein] Using cached pipeline for {model_name}")
            self._pipe = _PIPELINE_CACHE[model_name]
            self._current_model = model_name
            self._device = self._get_device()
            return True

        # ── CRITIQUE : env vars avant tout import HF ─────────────────────────
        cache_dir = _get_flux2_klein_cache_dir()
        os.environ['HF_HUB_CACHE'] = cache_dir
        os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir
        # ─────────────────────────────────────────────────────────────────────

        import torch
        from diffusers import Flux2KleinPipeline

        self._torch = torch
        self._device = self._get_device()

        model_info = SUPPORTED_MODELS[model_name]
        hf_id = model_info["hf_id"]

        logger.info(f"[Flux2Klein] Loading {hf_id} → {cache_dir}")

        # Evict previous cached model to free VRAM
        if _PIPELINE_CACHE:
            old_name = next(iter(_PIPELINE_CACHE))
            logger.info(f"[Flux2Klein] Evicting cached model: {old_name}")
            old_pipe = _PIPELINE_CACHE.pop(old_name)
            del old_pipe
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        try:
            pipe = Flux2KleinPipeline.from_pretrained(
                hf_id,
                torch_dtype=torch.bfloat16,
                cache_dir=cache_dir,
            )
            pipe.enable_model_cpu_offload()
            logger.info(f"[Flux2Klein] Pipeline loaded, cpu_offload enabled")

            _PIPELINE_CACHE[model_name] = pipe
            self._pipe = pipe
            self._current_model = model_name
            return True

        except Exception as e:
            logger.error(f"[Flux2Klein] Failed to load {model_name}: {e}")
            return False

    def unload(self) -> None:
        """Unload the pipeline and free VRAM."""
        global _PIPELINE_CACHE
        if self._current_model and self._current_model in _PIPELINE_CACHE:
            _PIPELINE_CACHE.pop(self._current_model)
        self._pipe = None
        self._current_model = None
        gc.collect()
        if self._torch and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

    def generate(
        self,
        params: GenerationParams,
        progress_callback: Optional[Callable] = None,
    ) -> GenerationResult:
        """Generate images using FLUX.2 Klein."""
        if self._pipe is None:
            return GenerationResult(success=False, error="Pipeline not loaded")

        model_info = SUPPORTED_MODELS.get(self._current_model, {})
        guidance_scale = float(params.guidance_scale or model_info.get("default_guidance_scale", 1.0))
        num_steps = int(params.num_inference_steps or model_info.get("default_steps", 4))
        width = int(params.width or 1024)
        height = int(params.height or 1024)
        num_images = int(params.num_images or 1)

        # Seed
        generator = None
        if params.seed is not None:
            generator = self._torch.Generator(device="cpu").manual_seed(int(params.seed))

        # Reference image for image-conditioned generation
        reference_image = None
        if params.reference_image:
            try:
                from PIL import Image
                reference_image = Image.open(params.reference_image).convert("RGB").resize((width, height))
                logger.info(f"[Flux2Klein] Image-conditioned mode, ref: {params.reference_image}")
            except Exception as e:
                logger.warning(f"[Flux2Klein] Could not load reference image: {e}")

        call_kwargs = dict(
            prompt=params.prompt,
            height=height,
            width=width,
            num_inference_steps=num_steps,
            guidance_scale=guidance_scale,
            num_images_per_prompt=num_images,
            generator=generator,
        )
        if reference_image is not None:
            call_kwargs["image"] = reference_image

        logger.info(
            f"[Flux2Klein] Generating: steps={num_steps}, guidance={guidance_scale}, "
            f"{width}x{height}, n={num_images}, seed={params.seed}"
        )

        try:
            result = self._pipe(**call_kwargs)
            images: List = result.images
            logger.info(f"[Flux2Klein] Generated {len(images)} image(s)")
            return GenerationResult(success=True, images=images)

        except Exception as e:
            logger.error(f"[Flux2Klein] Generation error: {e}")
            return GenerationResult(success=False, error=str(e))
