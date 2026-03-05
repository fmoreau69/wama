"""
WAMA Imager - Qwen Image 2 Backend

Qwen Image 2 & Qwen Image Edit (Alibaba Cloud)
- Qwen/Qwen-Image-2512     : 20B text-to-image diffusion (Apache 2.0, #1 open-source AI Arena)
- Qwen/Qwen-Image-Edit-2511: multi-image editing, up to 14 reference images

Both models are Diffusers pipelines (NOT transformers models):
  - t2i  : DiffusionPipeline.from_pretrained("Qwen/Qwen-Image-2512")
  - edit : QwenImageEditPlusPipeline.from_pretrained("Qwen/Qwen-Image-Edit-2511")

Key parameters:
  - true_cfg_scale=4.0  (Qwen-specific CFG, replaces standard guidance_scale)
  - num_inference_steps : 50 for t2i, 40 for edit

Requirements:
    pip install diffusers>=0.36.0 accelerate
    16 GB VRAM for qwen-image-2, 12 GB for qwen-image-edit

⚠️  HF_HUB_CACHE is set BEFORE diffusers import — see RÈGLE in model_config.py.
"""

import gc
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .base import GenerationResult, ImageGenerationBackend

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache directory (set before any HF import)
# ---------------------------------------------------------------------------

def _get_cache_dir() -> str:
    try:
        from wama.imager.utils.model_config import QWEN_IMAGE_DIR
        d = Path(QWEN_IMAGE_DIR)
        d.mkdir(parents=True, exist_ok=True)
        return str(d)
    except Exception:
        from django.conf import settings
        d = settings.AI_MODELS_DIR / "models" / "diffusion" / "qwen-image"
        Path(d).mkdir(parents=True, exist_ok=True)
        return str(d)


def _set_cache_env(cache_dir: str) -> None:
    """Set HF cache env vars before any HuggingFace library import."""
    os.environ['HF_HUB_CACHE'] = cache_dir
    os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir


# ---------------------------------------------------------------------------
# Supported models
# ---------------------------------------------------------------------------

SUPPORTED_MODELS = {
    "qwen-image-2": {
        "name": "Qwen Image 2",
        "hf_id": "Qwen/Qwen-Image-2512",
        "description": "Text-to-Image 2K — 16 GB VRAM — #1 open-source (AI Arena)",
        "type": "t2i",
        "vram": "16GB",
        "disk_size": "~40GB",
        "license": "apache-2.0",
        "default_steps": 50,
        "default_true_cfg": 4.0,
    },
    "qwen-image-edit": {
        "name": "Qwen Image Edit",
        "hf_id": "Qwen/Qwen-Image-Edit-2511",
        "description": "Image Editing 2K — 12 GB VRAM — multi-image, character consistency",
        "type": "edit",
        "vram": "12GB",
        "disk_size": "~25GB",
        "license": "apache-2.0",
        "default_steps": 40,
        "default_true_cfg": 4.0,
    },
}


# ---------------------------------------------------------------------------
# Params dataclass
# ---------------------------------------------------------------------------

@dataclass
class QwenImageParams:
    """Parameters for Qwen Image generation."""
    prompt: str
    negative_prompt: Optional[str] = None
    model: str = "qwen-image-2"
    width: int = 1024
    height: int = 1024
    steps: int = 50
    guidance_scale: float = 4.0   # maps to true_cfg_scale
    seed: Optional[int] = None
    num_images: int = 1
    # For edit mode: path(s) to reference image(s), comma-separated or list
    reference_image: Optional[str] = None


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

class QwenImageBackend(ImageGenerationBackend):
    """
    Image generation backend using Alibaba Qwen Image 2 / Qwen Image Edit.

    Both models are Diffusers pipelines:
      - qwen-image-2    → DiffusionPipeline
      - qwen-image-edit → QwenImageEditPlusPipeline
    """

    name = "qwen_image"
    display_name = "Qwen Image 2 (Alibaba)"

    def __init__(self):
        super().__init__()
        self._pipe = None
        self._loaded = False
        self._current_model = None
        self._cache_dir = _get_cache_dir()

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Check if diffusers + CUDA are available."""
        try:
            import torch
            import diffusers  # noqa: F401
            if not torch.cuda.is_available():
                logger.warning("[QwenImage] CUDA not available")
                return False
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            if vram_gb < 12:
                logger.warning(f"[QwenImage] Insufficient VRAM: {vram_gb:.1f}GB < 12GB")
                return False
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, model_name: str = "qwen-image-2") -> bool:
        """
        Load a Qwen Image diffusion pipeline.

        Args:
            model_name: 'qwen-image-2' (t2i) or 'qwen-image-edit' (i2i).

        Returns:
            True on success.
        """
        if model_name not in SUPPORTED_MODELS:
            logger.error(f"[QwenImage] Unknown model: {model_name}. "
                         f"Supported: {list(SUPPORTED_MODELS)}")
            return False

        if self._loaded and self._current_model == model_name:
            logger.info(f"[QwenImage] '{model_name}' already loaded — reusing")
            return True

        try:
            import torch

            # ── CRITICAL: set HF_HUB_CACHE BEFORE importing diffusers ────
            _set_cache_env(self._cache_dir)

            import diffusers

            if self._pipe is not None:
                self.unload()

            hf_id = SUPPORTED_MODELS[model_name]["hf_id"]
            model_type = SUPPORTED_MODELS[model_name]["type"]
            logger.info(f"[QwenImage] Loading '{model_name}' ({model_type}) from '{hf_id}'")
            logger.info(f"[QwenImage] Cache dir: {self._cache_dir}")

            # Free VRAM
            torch.cuda.empty_cache()
            gc.collect()

            load_kwargs = dict(
                torch_dtype=torch.bfloat16,
                cache_dir=self._cache_dir,
            )

            if model_type == "t2i":
                logger.info("[QwenImage] Loading QwenImagePipeline (t2i)…")
                self._pipe = diffusers.QwenImagePipeline.from_pretrained(
                    hf_id, **load_kwargs
                )

            else:  # edit
                logger.info("[QwenImage] Loading QwenImageEditPlusPipeline (edit)…")
                self._pipe = diffusers.QwenImageEditPlusPipeline.from_pretrained(
                    hf_id, **load_kwargs
                )

            # enable_model_cpu_offload: moves each component to GPU only when needed,
            # then back to CPU — essential for large models (20B+) that exceed VRAM.
            # Avoids "CUDA driver error: unknown error" from OOM on .to("cuda").
            self._pipe.enable_model_cpu_offload()
            logger.info("[QwenImage] CPU offload enabled (components loaded on-demand to GPU)")

            self._loaded = True
            self._current_model = model_name
            logger.info(f"[QwenImage] '{model_name}' loaded ✓")
            return True

        except Exception as e:
            logger.error(f"[QwenImage] Failed to load '{model_name}': {e}")
            import traceback
            logger.debug(traceback.format_exc())
            self._pipe = None
            self._loaded = False
            return False

    def unload(self) -> None:
        """Unload pipeline and free VRAM."""
        if self._pipe is not None:
            logger.info("[QwenImage] Unloading…")
            del self._pipe
            self._pipe = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
            except Exception:
                pass
            gc.collect()
            self._loaded = False
            self._current_model = None
            logger.info("[QwenImage] Unloaded")

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(
        self,
        params: QwenImageParams,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> GenerationResult:
        """
        Generate images with Qwen Image 2 or Qwen Image Edit.

        Args:
            params: QwenImageParams (or GenerationParams from base)
            progress_callback: Optional 0–100 progress reporter

        Returns:
            GenerationResult with PIL images.
        """
        import torch
        from PIL import Image

        model_name = getattr(params, 'model', 'qwen-image-2')

        if not self._loaded or self._current_model != model_name:
            if not self.load(model_name):
                return GenerationResult(
                    success=False,
                    error=f"Failed to load Qwen Image model: {model_name}",
                )

        try:
            if progress_callback:
                progress_callback(10)

            prompt          = params.prompt
            negative_prompt = getattr(params, 'negative_prompt', None) or " "
            width           = getattr(params, 'width',  1024)
            height          = getattr(params, 'height', 1024)
            steps           = getattr(params, 'steps',  SUPPORTED_MODELS[model_name]["default_steps"])
            true_cfg        = getattr(params, 'guidance_scale', SUPPORTED_MODELS[model_name]["default_true_cfg"])
            seed            = getattr(params, 'seed', None)
            num_images      = getattr(params, 'num_images', 1)
            reference_image = getattr(params, 'reference_image', None)

            logger.info(f"[QwenImage] Generating: '{prompt[:80]}' "
                        f"{width}x{height}, steps={steps}, true_cfg={true_cfg}")

            # Seed / generator — use CPU generator (compatible with cpu_offload)
            seed_used = seed
            if seed_used is None:
                seed_used = torch.randint(0, 2 ** 32, (1,)).item()
            generator = torch.Generator(device="cpu").manual_seed(seed_used)

            if progress_callback:
                progress_callback(20)

            model_type = SUPPORTED_MODELS[model_name]["type"]

            if model_type == "t2i":
                # ── Text-to-Image ──────────────────────────────────────────
                logger.info("[QwenImage] t2i generation…")
                output = self._pipe(
                    prompt=prompt,
                    width=width,
                    height=height,
                    num_inference_steps=steps,
                    true_cfg_scale=true_cfg,
                    generator=generator,
                    num_images_per_prompt=num_images,
                )

            else:
                # ── Image Editing ──────────────────────────────────────────
                if not reference_image:
                    return GenerationResult(
                        success=False,
                        error="qwen-image-edit requires at least one reference image",
                    )

                # Support comma-separated list of image paths
                ref_paths = [p.strip() for p in reference_image.split(",") if p.strip()]
                ref_images: List[Image.Image] = []
                for rp in ref_paths:
                    try:
                        ref_images.append(Image.open(rp).convert("RGB"))
                    except Exception as img_err:
                        logger.warning(f"[QwenImage] Could not open reference image '{rp}': {img_err}")

                if not ref_images:
                    return GenerationResult(
                        success=False,
                        error="qwen-image-edit: none of the reference images could be opened",
                    )

                logger.info(f"[QwenImage] edit generation with {len(ref_images)} reference image(s)…")
                output = self._pipe(
                    image=ref_images,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    num_inference_steps=steps,
                    true_cfg_scale=true_cfg,
                    guidance_scale=1.0,
                    generator=generator,
                    num_images_per_prompt=num_images,
                )

            if progress_callback:
                progress_callback(90)

            images: List[Image.Image] = output.images if hasattr(output, 'images') else []

            if not images:
                return GenerationResult(
                    success=False,
                    error="Qwen Image returned no images",
                )

            if progress_callback:
                progress_callback(100)

            logger.info(f"[QwenImage] Generated {len(images)} image(s) ✓ (seed={seed_used})")
            return GenerationResult(
                success=True,
                images=images,
                seed_used=seed_used,
            )

        except Exception as e:
            import traceback
            logger.error(f"[QwenImage] Generation failed: {e}")
            logger.debug(traceback.format_exc())
            return GenerationResult(success=False, error=str(e))
