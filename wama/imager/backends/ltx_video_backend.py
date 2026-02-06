"""
WAMA Imager - LTX-Video Backend

Video generation using LTX-Video via Hugging Face Diffusers.
Supports Text-to-Video and Image-to-Video generation.

Models:
- LTX-Video 2B distilled: Lightweight, ~8GB VRAM
- LTX-Video 0.9.8: Latest version with improved quality
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


def _get_ltx_cache_dir() -> str:
    """Get cache directory for LTX-Video models."""
    try:
        from wama.imager.utils.model_config import MODEL_PATHS
        cache_dir = MODEL_PATHS.get('diffusion', {}).get('ltx')
        if cache_dir:
            return str(cache_dir)
    except ImportError:
        pass

    # Fallback path
    base_dir = Path(settings.BASE_DIR)
    models_dir = base_dir / "AI-models" / "models" / "diffusion" / "ltx"
    models_dir.mkdir(parents=True, exist_ok=True)
    return str(models_dir)


@dataclass
class LTXVideoParams:
    """Parameters for LTX-Video generation."""
    prompt: str
    negative_prompt: Optional[str] = "worst quality, inconsistent motion, blurry, jittery, distorted"
    model: str = "ltx-video-2b"
    width: int = 704
    height: int = 480
    num_frames: int = 97  # Must be divisible by 8 + 1
    num_inference_steps: int = 30
    guidance_scale: float = 3.0
    seed: Optional[int] = None
    fps: int = 24
    reference_image: Optional[str] = None  # For I2V mode


# Supported models
SUPPORTED_MODELS = {
    "ltx-video-2b": {
        "name": "LTX-Video 2B",
        "description": "Text-to-Video - 8GB VRAM - Fast and efficient",
        "hf_id": "Lightricks/LTX-Video",
        "type": "t2v",
        "vram": "8GB",
        "disk_size": "~5GB",
    },
    "ltx-video-0.9.8": {
        "name": "LTX-Video 0.9.8",
        "description": "Text/Image-to-Video - Latest version - Higher quality",
        "hf_id": "Lightricks/LTX-Video-0.9.8-dev",
        "type": "t2v",
        "vram": "10GB",
        "disk_size": "~6GB",
    },
    "ltx-video-0.9.8-distilled": {
        "name": "LTX-Video 0.9.8 Distilled",
        "description": "Text-to-Video - Faster inference - Light VRAM",
        "hf_id": "Lightricks/LTX-Video-0.9.8-distilled",
        "type": "t2v",
        "vram": "6GB",
        "disk_size": "~4GB",
    },
}


class LTXVideoBackend(ImageGenerationBackend):
    """LTX-Video backend for video generation."""

    name = "ltx_video"
    display_name = "LTX-Video"

    def __init__(self):
        super().__init__()
        self._pipe = None
        self._torch = None
        self._device = None
        self._loaded = False
        self._current_model = None
        self._cache_dir = _get_ltx_cache_dir()

    @classmethod
    def is_available(cls) -> bool:
        """Check if LTX-Video is available."""
        try:
            import torch
            from diffusers import LTXPipeline

            if not torch.cuda.is_available():
                logger.warning("[LTX-Video] CUDA not available")
                return False

            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            if vram_gb < 6:
                logger.warning(f"[LTX-Video] Insufficient VRAM: {vram_gb:.1f}GB < 6GB")
                return False

            logger.info(f"[LTX-Video] Available with {vram_gb:.1f}GB VRAM")
            return True

        except ImportError as e:
            logger.warning(f"[LTX-Video] Import error: {e}")
            return False
        except Exception as e:
            logger.warning(f"[LTX-Video] Availability check failed: {e}")
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
            logger.info(f"[LTX-Video] CUDA device: {device_name} ({vram_gb:.1f}GB)")
            return "cuda"
        else:
            logger.warning("[LTX-Video] No CUDA, using CPU (very slow)")
            return "cpu"

    def _get_vram_gb(self) -> float:
        """Get available VRAM in GB."""
        if self._torch and self._torch.cuda.is_available():
            return self._torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        return 0

    def load(self, model_name: str = "ltx-video-2b") -> bool:
        """Load an LTX-Video model."""
        try:
            import torch
            from diffusers import LTXPipeline

            self._torch = torch
            self._device = self._get_device()

            if model_name not in SUPPORTED_MODELS:
                logger.error(f"[LTX-Video] Unknown model: {model_name}")
                return False

            model_config = SUPPORTED_MODELS[model_name]
            model_id = model_config["hf_id"]

            logger.info(f"[LTX-Video] ========================================")
            logger.info(f"[LTX-Video] Loading model: {model_name}")
            logger.info(f"[LTX-Video] HuggingFace ID: {model_id}")
            logger.info(f"[LTX-Video] Cache directory: {self._cache_dir}")
            logger.info(f"[LTX-Video] ========================================")

            # Unload previous model
            if self._pipe is not None:
                self.unload()

            # Load pipeline
            logger.info("[LTX-Video] Loading pipeline...")

            self._pipe = LTXPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.bfloat16,
                cache_dir=self._cache_dir
            )

            logger.info("[LTX-Video] Pipeline loaded")

            # Use centralized MemoryManager for optimal memory strategy
            try:
                from wama.model_manager.services.memory_manager import MemoryManager
                self._pipe = MemoryManager.apply_strategy_for_model(
                    pipeline=self._pipe,
                    model_type='ltx-video',
                    device=self._device,
                    headroom_gb=4.0
                )
            except ImportError:
                logger.warning("[LTX-Video] MemoryManager not available, using default CPU offload")
                self._pipe.enable_model_cpu_offload()

            # Enable VAE tiling
            try:
                self._pipe.vae.enable_tiling()
                logger.info("[LTX-Video] VAE tiling enabled")
            except Exception as e:
                logger.debug(f"[LTX-Video] VAE tiling not available: {e}")

            self._current_model = model_name
            self._loaded = True
            logger.info(f"[LTX-Video] Model {model_name} loaded successfully")

            return True

        except Exception as e:
            import traceback
            logger.error(f"[LTX-Video] Failed to load model: {e}")
            logger.error(f"[LTX-Video] Traceback:\n{traceback.format_exc()}")
            self._loaded = False
            return False

    def unload(self) -> None:
        """Unload the model from memory."""
        logger.info("[LTX-Video] Unloading model...")

        if self._pipe is not None:
            del self._pipe
            self._pipe = None

        self._loaded = False
        self._current_model = None

        gc.collect()
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

        logger.info("[LTX-Video] Model unloaded")

    def generate(
        self,
        params: LTXVideoParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """Generate a video from parameters."""
        import torch
        from diffusers.utils import export_to_video

        if not self._loaded:
            model_to_load = params.model if params.model in SUPPORTED_MODELS else "ltx-video-2b"
            if not self.load(model_to_load):
                return GenerationResult(success=False, error="Failed to load LTX-Video model")

        # Check if we need to switch models
        if self._current_model != params.model and params.model in SUPPORTED_MODELS:
            logger.info(f"[LTX-Video] Switching model from {self._current_model} to {params.model}")
            if not self.load(params.model):
                return GenerationResult(success=False, error=f"Failed to load model {params.model}")

        try:
            # Set up generator for reproducibility
            seed_used = params.seed
            if seed_used is None:
                seed_used = torch.randint(0, 2**32, (1,)).item()
                logger.info(f"[LTX-Video] Generated random seed: {seed_used}")
            else:
                logger.info(f"[LTX-Video] Using provided seed: {seed_used}")

            generator = torch.Generator(device="cpu").manual_seed(seed_used)

            # Clear CUDA cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()

            # Ensure dimensions are divisible by 32
            width = (params.width // 32) * 32
            height = (params.height // 32) * 32

            # Ensure frames are divisible by 8 + 1
            num_frames = ((params.num_frames - 1) // 8) * 8 + 1

            logger.info(f"[LTX-Video] Generating video...")
            logger.info(f"[LTX-Video] Resolution: {width}x{height}")
            logger.info(f"[LTX-Video] Frames: {num_frames}")
            logger.info(f"[LTX-Video] Steps: {params.num_inference_steps}")

            # Progress callback wrapper
            def callback_on_step_end(pipe, step_index, timestep, callback_kwargs):
                if progress_callback:
                    progress = int((step_index + 1) / params.num_inference_steps * 100)
                    progress_callback(progress)
                return callback_kwargs

            # Generate
            with torch.inference_mode():
                output = self._pipe(
                    prompt=params.prompt,
                    negative_prompt=params.negative_prompt,
                    width=width,
                    height=height,
                    num_frames=num_frames,
                    num_inference_steps=params.num_inference_steps,
                    guidance_scale=params.guidance_scale,
                    generator=generator,
                    callback_on_step_end=callback_on_step_end,
                )

            # Get frames
            video_frames = output.frames[0]
            logger.info(f"[LTX-Video] Generated {len(video_frames)} frames")

            return GenerationResult(
                success=True,
                video_frames=video_frames,
                seed_used=seed_used
            )

        except Exception as e:
            import traceback
            error_msg = str(e)
            logger.error(f"[LTX-Video] Generation failed: {error_msg}")
            logger.error(f"[LTX-Video] Traceback:\n{traceback.format_exc()}")
            return GenerationResult(success=False, error=error_msg)

    def export_video(self, frames: List, output_path: str, fps: int = 24) -> bool:
        """Export frames to video file."""
        try:
            from diffusers.utils import export_to_video
            export_to_video(frames, output_path, fps=fps)
            logger.info(f"[LTX-Video] Exported video to {output_path}")
            return True
        except Exception as e:
            logger.error(f"[LTX-Video] Failed to export video: {e}")
            return False

    @classmethod
    def get_supported_models(cls) -> dict:
        """Get dictionary of supported models with descriptions."""
        return SUPPORTED_MODELS
