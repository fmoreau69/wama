"""
WAMA Imager - Mochi Backend

Video generation using Mochi-1 Preview via Hugging Face Diffusers.
High-quality text-to-video generation.

Models:
- Mochi-1 Preview: 10B parameters, 22GB VRAM with bf16 variant
"""

import gc
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, List

from django.conf import settings

from .base import ImageGenerationBackend, GenerationParams, GenerationResult

logger = logging.getLogger(__name__)


def _get_mochi_cache_dir() -> str:
    """Get cache directory for Mochi models."""
    try:
        from wama.imager.utils.model_config import MODEL_PATHS
        cache_dir = MODEL_PATHS.get('diffusion', {}).get('mochi')
        if cache_dir:
            return str(cache_dir)
    except ImportError:
        pass

    # Fallback path
    base_dir = Path(settings.BASE_DIR)
    models_dir = base_dir / "AI-models" / "models" / "diffusion" / "mochi"
    models_dir.mkdir(parents=True, exist_ok=True)
    return str(models_dir)


@dataclass
class MochiParams:
    """Parameters for Mochi generation."""
    prompt: str
    negative_prompt: Optional[str] = None
    model: str = "mochi-1-preview"
    width: int = 848
    height: int = 480
    num_frames: int = 84  # Up to 84 frames (~2.8 seconds at 30fps)
    num_inference_steps: int = 50
    guidance_scale: float = 4.5
    seed: Optional[int] = None
    fps: int = 30


# Supported models
SUPPORTED_MODELS = {
    "mochi-1-preview": {
        "name": "Mochi-1 Preview",
        "description": "Text-to-Video 480p - 22GB VRAM (bf16) - High quality",
        "hf_id": "genmo/mochi-1-preview",
        "type": "t2v",
        "vram": "22GB",
        "disk_size": "~18GB",
        "variant": "bf16",
    },
}


class MochiBackend(ImageGenerationBackend):
    """Mochi-1 backend for video generation."""

    name = "mochi"
    display_name = "Mochi-1"

    def __init__(self):
        super().__init__()
        self._pipe = None
        self._torch = None
        self._device = None
        self._loaded = False
        self._current_model = None
        self._cache_dir = _get_mochi_cache_dir()

    @classmethod
    def is_available(cls) -> bool:
        """Check if Mochi is available."""
        try:
            import torch
            from diffusers import MochiPipeline

            if not torch.cuda.is_available():
                logger.warning("[Mochi] CUDA not available")
                return False

            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            if vram_gb < 16:
                logger.warning(f"[Mochi] Insufficient VRAM: {vram_gb:.1f}GB < 16GB (22GB recommended)")
                return False

            logger.info(f"[Mochi] Available with {vram_gb:.1f}GB VRAM")
            return True

        except ImportError as e:
            logger.warning(f"[Mochi] Import error: {e}")
            return False
        except Exception as e:
            logger.warning(f"[Mochi] Availability check failed: {e}")
            return False

    def _get_device(self) -> str:
        """Get the best available device."""
        if self._torch is None:
            import torch
            self._torch = torch

        if self._torch.cuda.is_available():
            device_name = self._torch.cuda.get_device_name(0)
            props = self._torch.cuda.get_device_properties(0)
            vram_gb = props.total_memory / (1024 ** 3)
            logger.info(f"[Mochi] CUDA device: {device_name} ({vram_gb:.1f}GB)")
            return "cuda"
        else:
            logger.warning("[Mochi] No CUDA, using CPU (not supported)")
            return "cpu"

    def _get_vram_gb(self) -> float:
        """Get available VRAM in GB."""
        if self._torch and self._torch.cuda.is_available():
            return self._torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        return 0

    def load(self, model_name: str = "mochi-1-preview") -> bool:
        """Load a Mochi model."""
        try:
            import torch
            from diffusers import MochiPipeline

            self._torch = torch
            self._device = self._get_device()

            if model_name not in SUPPORTED_MODELS:
                logger.error(f"[Mochi] Unknown model: {model_name}")
                return False

            model_config = SUPPORTED_MODELS[model_name]
            model_id = model_config["hf_id"]
            variant = model_config.get("variant", "bf16")

            logger.info(f"[Mochi] ========================================")
            logger.info(f"[Mochi] Loading model: {model_name}")
            logger.info(f"[Mochi] HuggingFace ID: {model_id}")
            logger.info(f"[Mochi] Variant: {variant}")
            logger.info(f"[Mochi] Cache directory: {self._cache_dir}")
            logger.info(f"[Mochi] ========================================")

            # Unload previous model
            if self._pipe is not None:
                self.unload()

            vram_gb = self._get_vram_gb()
            logger.info(f"[Mochi] Detected VRAM: {vram_gb:.1f}GB")

            # Load pipeline with bf16 variant for lower VRAM usage
            logger.info("[Mochi] Loading pipeline with bf16 variant...")

            self._pipe = MochiPipeline.from_pretrained(
                model_id,
                variant=variant,
                torch_dtype=torch.bfloat16,
                cache_dir=self._cache_dir
            )

            logger.info("[Mochi] Pipeline loaded")

            # Enable memory optimizations
            logger.info("[Mochi] Enabling CPU offload for memory efficiency...")
            self._pipe.enable_model_cpu_offload()

            # Enable VAE tiling for lower VRAM
            try:
                self._pipe.enable_vae_tiling()
                logger.info("[Mochi] VAE tiling enabled")
            except Exception as e:
                logger.debug(f"[Mochi] VAE tiling not available: {e}")

            self._current_model = model_name
            self._loaded = True
            logger.info(f"[Mochi] Model {model_name} loaded successfully")

            return True

        except Exception as e:
            import traceback
            logger.error(f"[Mochi] Failed to load model: {e}")
            logger.error(f"[Mochi] Traceback:\n{traceback.format_exc()}")
            self._loaded = False
            return False

    def unload(self) -> None:
        """Unload the model from memory."""
        logger.info("[Mochi] Unloading model...")

        if self._pipe is not None:
            del self._pipe
            self._pipe = None

        self._loaded = False
        self._current_model = None

        gc.collect()
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

        logger.info("[Mochi] Model unloaded")

    def generate(
        self,
        params: MochiParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """Generate a video from parameters."""
        import torch
        from diffusers.utils import export_to_video

        if not self._loaded:
            model_to_load = params.model if params.model in SUPPORTED_MODELS else "mochi-1-preview"
            if not self.load(model_to_load):
                return GenerationResult(success=False, error="Failed to load Mochi model")

        # Check if we need to switch models
        if self._current_model != params.model and params.model in SUPPORTED_MODELS:
            logger.info(f"[Mochi] Switching model from {self._current_model} to {params.model}")
            if not self.load(params.model):
                return GenerationResult(success=False, error=f"Failed to load model {params.model}")

        try:
            # Set up generator for reproducibility
            seed_used = params.seed
            if seed_used is None:
                seed_used = torch.randint(0, 2**32, (1,)).item()
                logger.info(f"[Mochi] Generated random seed: {seed_used}")
            else:
                logger.info(f"[Mochi] Using provided seed: {seed_used}")

            generator = torch.Generator(device="cpu").manual_seed(seed_used)

            # Clear CUDA cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()

            # Clamp num_frames to max 84
            num_frames = min(params.num_frames, 84)

            logger.info(f"[Mochi] Generating video...")
            logger.info(f"[Mochi] Resolution: {params.width}x{params.height}")
            logger.info(f"[Mochi] Frames: {num_frames}")
            logger.info(f"[Mochi] Steps: {params.num_inference_steps}")

            # Progress callback wrapper
            def callback_on_step_end(pipe, step_index, timestep, callback_kwargs):
                if progress_callback:
                    progress = int((step_index + 1) / params.num_inference_steps * 100)
                    progress_callback(progress)
                return callback_kwargs

            # Generate with autocast for better memory efficiency
            with torch.autocast("cuda", torch.bfloat16, cache_enabled=False):
                output = self._pipe(
                    prompt=params.prompt,
                    negative_prompt=params.negative_prompt,
                    height=params.height,
                    width=params.width,
                    num_frames=num_frames,
                    num_inference_steps=params.num_inference_steps,
                    guidance_scale=params.guidance_scale,
                    generator=generator,
                    callback_on_step_end=callback_on_step_end,
                )

            # Get frames
            video_frames = output.frames[0]
            logger.info(f"[Mochi] Generated {len(video_frames)} frames")

            return GenerationResult(
                success=True,
                video_frames=video_frames,
                seed_used=seed_used
            )

        except Exception as e:
            import traceback
            error_msg = str(e)
            logger.error(f"[Mochi] Generation failed: {error_msg}")
            logger.error(f"[Mochi] Traceback:\n{traceback.format_exc()}")
            return GenerationResult(success=False, error=error_msg)

    def export_video(self, frames: List, output_path: str, fps: int = 30) -> bool:
        """Export frames to video file."""
        try:
            from diffusers.utils import export_to_video
            export_to_video(frames, output_path, fps=fps)
            logger.info(f"[Mochi] Exported video to {output_path}")
            return True
        except Exception as e:
            logger.error(f"[Mochi] Failed to export video: {e}")
            return False

    @classmethod
    def get_supported_models(cls) -> dict:
        """Get dictionary of supported models with descriptions."""
        return SUPPORTED_MODELS
