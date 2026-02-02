"""
WAMA Imager - CogVideoX Backend

Video generation using CogVideoX via Hugging Face Diffusers.
Supports Text-to-Video and Image-to-Video generation.

Models:
- CogVideoX-2b: Lightweight, 4GB VRAM with optimizations
- CogVideoX-5b: Higher quality, 5GB VRAM with optimizations
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


def _get_cogvideox_cache_dir() -> str:
    """Get cache directory for CogVideoX models."""
    try:
        from wama.imager.utils.model_config import MODEL_PATHS
        cache_dir = MODEL_PATHS.get('diffusion', {}).get('cogvideox')
        if cache_dir:
            return str(cache_dir)
    except ImportError:
        pass

    # Fallback path
    base_dir = Path(settings.BASE_DIR)
    models_dir = base_dir / "AI-models" / "models" / "diffusion" / "cogvideox"
    models_dir.mkdir(parents=True, exist_ok=True)
    return str(models_dir)


@dataclass
class CogVideoXParams:
    """Parameters for CogVideoX generation."""
    prompt: str
    negative_prompt: Optional[str] = None
    model: str = "cogvideox-2b"
    width: int = 720
    height: int = 480
    num_frames: int = 49  # Fixed for CogVideoX (6 seconds at 8fps)
    num_inference_steps: int = 50
    guidance_scale: float = 6.0
    seed: Optional[int] = None
    fps: int = 8
    reference_image: Optional[str] = None  # For I2V mode


# Supported models
SUPPORTED_MODELS = {
    "cogvideox-2b": {
        "name": "CogVideoX 2B",
        "description": "Text-to-Video - 4GB VRAM - Fast and efficient",
        "hf_id": "THUDM/CogVideoX-2b",
        "type": "t2v",
        "vram": "4GB",
        "precision": "fp16",
        "disk_size": "~6GB",
    },
    "cogvideox-5b": {
        "name": "CogVideoX 5B",
        "description": "Text-to-Video - 5GB VRAM - Higher quality",
        "hf_id": "THUDM/CogVideoX-5b",
        "type": "t2v",
        "vram": "5GB",
        "precision": "bf16",
        "disk_size": "~12GB",
    },
    "cogvideox-5b-i2v": {
        "name": "CogVideoX 5B I2V",
        "description": "Image-to-Video - 5GB VRAM - Animate images",
        "hf_id": "THUDM/CogVideoX-5b-I2V",
        "type": "i2v",
        "vram": "5GB",
        "precision": "bf16",
        "disk_size": "~12GB",
    },
}


class CogVideoXBackend(ImageGenerationBackend):
    """CogVideoX backend for video generation."""

    name = "cogvideox"
    display_name = "CogVideoX"

    def __init__(self):
        super().__init__()
        self._pipe = None
        self._torch = None
        self._device = None
        self._loaded = False
        self._current_model = None
        self._cache_dir = _get_cogvideox_cache_dir()

    @classmethod
    def is_available(cls) -> bool:
        """Check if CogVideoX is available."""
        try:
            import torch
            from diffusers import CogVideoXPipeline

            if not torch.cuda.is_available():
                logger.warning("[CogVideoX] CUDA not available")
                return False

            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            if vram_gb < 4:
                logger.warning(f"[CogVideoX] Insufficient VRAM: {vram_gb:.1f}GB < 4GB")
                return False

            logger.info(f"[CogVideoX] Available with {vram_gb:.1f}GB VRAM")
            return True

        except ImportError as e:
            logger.warning(f"[CogVideoX] Import error: {e}")
            return False
        except Exception as e:
            logger.warning(f"[CogVideoX] Availability check failed: {e}")
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
            logger.info(f"[CogVideoX] CUDA device: {device_name} ({vram_gb:.1f}GB)")
            return "cuda"
        else:
            logger.warning("[CogVideoX] No CUDA, using CPU (very slow)")
            return "cpu"

    def _get_vram_gb(self) -> float:
        """Get available VRAM in GB."""
        if self._torch and self._torch.cuda.is_available():
            return self._torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        return 0

    def load(self, model_name: str = "cogvideox-2b") -> bool:
        """Load a CogVideoX model."""
        try:
            import torch
            from diffusers import CogVideoXPipeline, CogVideoXImageToVideoPipeline

            self._torch = torch
            self._device = self._get_device()

            if model_name not in SUPPORTED_MODELS:
                logger.error(f"[CogVideoX] Unknown model: {model_name}")
                return False

            model_config = SUPPORTED_MODELS[model_name]
            model_id = model_config["hf_id"]
            model_type = model_config["type"]
            precision = model_config["precision"]

            logger.info(f"[CogVideoX] ========================================")
            logger.info(f"[CogVideoX] Loading model: {model_name}")
            logger.info(f"[CogVideoX] HuggingFace ID: {model_id}")
            logger.info(f"[CogVideoX] Cache directory: {self._cache_dir}")
            logger.info(f"[CogVideoX] ========================================")

            # Unload previous model
            if self._pipe is not None:
                self.unload()

            # Determine torch dtype based on precision
            if precision == "bf16":
                torch_dtype = torch.bfloat16
            else:
                torch_dtype = torch.float16

            # Load appropriate pipeline
            logger.info("[CogVideoX] Loading pipeline...")

            if model_type == "i2v":
                self._pipe = CogVideoXImageToVideoPipeline.from_pretrained(
                    model_id,
                    torch_dtype=torch_dtype,
                    cache_dir=self._cache_dir
                )
            else:
                self._pipe = CogVideoXPipeline.from_pretrained(
                    model_id,
                    torch_dtype=torch_dtype,
                    cache_dir=self._cache_dir
                )

            logger.info("[CogVideoX] Pipeline loaded")

            # Enable memory optimizations
            logger.info("[CogVideoX] Enabling memory optimizations...")
            self._pipe.enable_model_cpu_offload()

            # Enable VAE optimizations
            try:
                self._pipe.vae.enable_tiling()
                self._pipe.vae.enable_slicing()
                logger.info("[CogVideoX] VAE tiling and slicing enabled")
            except Exception as e:
                logger.debug(f"[CogVideoX] VAE optimizations not available: {e}")

            self._current_model = model_name
            self._loaded = True
            logger.info(f"[CogVideoX] Model {model_name} loaded successfully")

            return True

        except Exception as e:
            import traceback
            logger.error(f"[CogVideoX] Failed to load model: {e}")
            logger.error(f"[CogVideoX] Traceback:\n{traceback.format_exc()}")
            self._loaded = False
            return False

    def unload(self) -> None:
        """Unload the model from memory."""
        logger.info("[CogVideoX] Unloading model...")

        if self._pipe is not None:
            del self._pipe
            self._pipe = None

        self._loaded = False
        self._current_model = None

        gc.collect()
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

        logger.info("[CogVideoX] Model unloaded")

    def generate(
        self,
        params: CogVideoXParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """Generate a video from parameters."""
        import torch
        from diffusers.utils import export_to_video

        if not self._loaded:
            model_to_load = params.model if params.model in SUPPORTED_MODELS else "cogvideox-2b"
            if not self.load(model_to_load):
                return GenerationResult(success=False, error="Failed to load CogVideoX model")

        # Check if we need to switch models
        if self._current_model != params.model and params.model in SUPPORTED_MODELS:
            logger.info(f"[CogVideoX] Switching model from {self._current_model} to {params.model}")
            if not self.load(params.model):
                return GenerationResult(success=False, error=f"Failed to load model {params.model}")

        model_config = SUPPORTED_MODELS.get(params.model, SUPPORTED_MODELS["cogvideox-2b"])

        try:
            # Set up generator for reproducibility
            seed_used = params.seed
            if seed_used is None:
                seed_used = torch.randint(0, 2**32, (1,)).item()
                logger.info(f"[CogVideoX] Generated random seed: {seed_used}")
            else:
                logger.info(f"[CogVideoX] Using provided seed: {seed_used}")

            generator = torch.Generator(device="cuda").manual_seed(seed_used)

            # Clear CUDA cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()

            logger.info(f"[CogVideoX] Generating video...")
            logger.info(f"[CogVideoX] Resolution: {params.width}x{params.height}")
            logger.info(f"[CogVideoX] Frames: {params.num_frames}")
            logger.info(f"[CogVideoX] Steps: {params.num_inference_steps}")

            # Progress callback wrapper
            def callback_on_step_end(pipe, step_index, timestep, callback_kwargs):
                if progress_callback:
                    progress = int((step_index + 1) / params.num_inference_steps * 100)
                    progress_callback(progress)
                return callback_kwargs

            # Generate
            with torch.inference_mode():
                if model_config["type"] == "i2v" and params.reference_image:
                    # Image-to-Video
                    from PIL import Image
                    image = Image.open(params.reference_image).convert("RGB")
                    # Resize to match expected dimensions
                    image = image.resize((params.width, params.height))

                    output = self._pipe(
                        prompt=params.prompt,
                        image=image,
                        num_videos_per_prompt=1,
                        num_frames=params.num_frames,
                        num_inference_steps=params.num_inference_steps,
                        guidance_scale=params.guidance_scale,
                        generator=generator,
                        callback_on_step_end=callback_on_step_end,
                    )
                else:
                    # Text-to-Video
                    output = self._pipe(
                        prompt=params.prompt,
                        num_videos_per_prompt=1,
                        num_frames=params.num_frames,
                        num_inference_steps=params.num_inference_steps,
                        guidance_scale=params.guidance_scale,
                        generator=generator,
                        callback_on_step_end=callback_on_step_end,
                    )

            # Get frames
            video_frames = output.frames[0]
            logger.info(f"[CogVideoX] Generated {len(video_frames)} frames")

            return GenerationResult(
                success=True,
                video_frames=video_frames,
                seed_used=seed_used
            )

        except Exception as e:
            import traceback
            error_msg = str(e)
            logger.error(f"[CogVideoX] Generation failed: {error_msg}")
            logger.error(f"[CogVideoX] Traceback:\n{traceback.format_exc()}")
            return GenerationResult(success=False, error=error_msg)

    def export_video(self, frames: List, output_path: str, fps: int = 8) -> bool:
        """Export frames to video file."""
        try:
            from diffusers.utils import export_to_video
            export_to_video(frames, output_path, fps=fps)
            logger.info(f"[CogVideoX] Exported video to {output_path}")
            return True
        except Exception as e:
            logger.error(f"[CogVideoX] Failed to export video: {e}")
            return False

    @classmethod
    def get_supported_models(cls) -> dict:
        """Get dictionary of supported models with descriptions."""
        return SUPPORTED_MODELS
