"""
WAMA Imager - HunyuanVideo Backend

Video generation using HunyuanVideo 1.5 via Hugging Face Diffusers.
Supports Text-to-Video and Image-to-Video generation.

Models are stored in AI-models/imager/hunyuan/ for centralized management.
"""

import gc
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, List

from django.conf import settings

# IMPORTANT: Set HF_HUB_CACHE BEFORE importing diffusers/transformers
def _setup_hf_cache():
    """Set up Hugging Face cache directory before any HF imports."""
    base_dir = Path(settings.BASE_DIR)
    models_dir = base_dir / "AI-models" / "imager" / "hunyuan"
    models_dir.mkdir(parents=True, exist_ok=True)
    models_dir_str = str(models_dir)

    os.environ['HF_HUB_CACHE'] = models_dir_str
    os.environ['HF_HOME'] = models_dir_str
    os.environ['HUGGINGFACE_HUB_CACHE'] = models_dir_str

    return models_dir_str

_HUNYUAN_MODELS_DIR = _setup_hf_cache()

from .base import ImageGenerationBackend, GenerationParams, GenerationResult

logger = logging.getLogger(__name__)

logger.info(f"[HunyuanVideo] Module loaded - HF cache directory: {_HUNYUAN_MODELS_DIR}")


def get_hunyuan_models_dir() -> str:
    """Get the directory for Hunyuan video models."""
    return _HUNYUAN_MODELS_DIR


@dataclass
class HunyuanVideoParams:
    """Parameters for HunyuanVideo generation."""
    prompt: str
    negative_prompt: Optional[str] = None
    model: str = "hunyuan-t2v-480p"
    width: int = 848
    height: int = 480
    num_frames: int = 121  # ~5 seconds at 24fps
    num_inference_steps: int = 50
    guidance_scale: float = 6.0
    flow_shift: float = 5.0
    seed: Optional[int] = None
    fps: int = 24
    reference_image: Optional[str] = None  # For I2V mode


# Supported models with descriptions and HuggingFace IDs
SUPPORTED_MODELS = {
    "hunyuan-t2v-480p": {
        "name": "HunyuanVideo 1.5 T2V 480p",
        "description": "Text-to-Video 480p - 14GB VRAM avec offload",
        "hf_id": "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v",
        "type": "t2v",
        "resolution": "480p",
        "vram": "14GB",
        "cfg_scale": 6.0,
        "flow_shift": 5.0,
    },
    "hunyuan-t2v-720p": {
        "name": "HunyuanVideo 1.5 T2V 720p",
        "description": "Text-to-Video 720p - 24GB VRAM recommandé",
        "hf_id": "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-720p_t2v",
        "type": "t2v",
        "resolution": "720p",
        "vram": "24GB",
        "cfg_scale": 6.0,
        "flow_shift": 9.0,
    },
    "hunyuan-i2v-480p": {
        "name": "HunyuanVideo 1.5 I2V 480p",
        "description": "Image-to-Video 480p - 14GB VRAM avec offload",
        "hf_id": "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_i2v",
        "type": "i2v",
        "resolution": "480p",
        "vram": "14GB",
        "cfg_scale": 6.0,
        "flow_shift": 5.0,
    },
}

# Resolution presets
RESOLUTION_PRESETS = {
    "480p": {
        "16:9": (848, 480),
        "9:16": (480, 848),
        "4:3": (624, 480),
        "3:4": (480, 624),
        "1:1": (544, 544),
    },
    "720p": {
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "4:3": (960, 720),
        "3:4": (720, 960),
        "1:1": (720, 720),
    },
}


class HunyuanVideoBackend(ImageGenerationBackend):
    """HunyuanVideo 1.5 backend for video generation."""

    name = "hunyuan_video"
    display_name = "HunyuanVideo 1.5"

    def __init__(self):
        super().__init__()
        self._pipe = None
        self._torch = None
        self._device = None
        self._loaded = False
        self._current_model = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if HunyuanVideo is available."""
        try:
            import torch
            from diffusers import HunyuanVideo15Pipeline

            if not torch.cuda.is_available():
                logger.warning("[HunyuanVideo] CUDA not available")
                return False

            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            if vram_gb < 14:
                logger.warning(f"[HunyuanVideo] Insufficient VRAM: {vram_gb:.1f}GB < 14GB")
                return False

            logger.info(f"[HunyuanVideo] Available with {vram_gb:.1f}GB VRAM")
            return True

        except ImportError as e:
            logger.warning(f"[HunyuanVideo] Import error: {e}")
            return False
        except Exception as e:
            logger.warning(f"[HunyuanVideo] Availability check failed: {e}")
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
            logger.info(f"[HunyuanVideo] CUDA device: {device_name} ({vram_gb:.1f}GB)")
            return "cuda"
        else:
            logger.warning("[HunyuanVideo] No CUDA, using CPU (very slow)")
            return "cpu"

    def _get_vram_gb(self) -> float:
        """Get available VRAM in GB."""
        if self._torch and self._torch.cuda.is_available():
            return self._torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        return 0

    def load(self, model_name: str = "hunyuan-t2v-480p") -> bool:
        """Load a HunyuanVideo model."""
        try:
            import torch
            from diffusers import HunyuanVideo15Pipeline

            self._torch = torch
            self._device = self._get_device()

            if model_name not in SUPPORTED_MODELS:
                logger.error(f"[HunyuanVideo] Unknown model: {model_name}")
                return False

            model_config = SUPPORTED_MODELS[model_name]
            model_id = model_config["hf_id"]
            cache_dir = get_hunyuan_models_dir()

            logger.info(f"[HunyuanVideo] ========================================")
            logger.info(f"[HunyuanVideo] Loading model: {model_name}")
            logger.info(f"[HunyuanVideo] HuggingFace ID: {model_id}")
            logger.info(f"[HunyuanVideo] Cache directory: {cache_dir}")
            logger.info(f"[HunyuanVideo] ========================================")

            # Unload previous model
            if self._pipe is not None:
                self.unload()

            vram_gb = self._get_vram_gb()
            logger.info(f"[HunyuanVideo] Detected VRAM: {vram_gb:.1f}GB")

            # Load pipeline
            logger.info("[HunyuanVideo] Loading pipeline... This may take several minutes on first run.")
            self._pipe = HunyuanVideo15Pipeline.from_pretrained(
                model_id,
                torch_dtype=torch.bfloat16,
                cache_dir=cache_dir
            )
            logger.info("[HunyuanVideo] Pipeline loaded")

            # Enable memory optimizations
            logger.info("[HunyuanVideo] Enabling CPU offload for memory efficiency...")
            self._pipe.enable_model_cpu_offload()

            # Enable VAE tiling
            try:
                self._pipe.vae.enable_tiling()
                logger.info("[HunyuanVideo] VAE tiling enabled")
            except Exception as e:
                logger.debug(f"[HunyuanVideo] VAE tiling not available: {e}")

            self._current_model = model_name
            self._loaded = True
            logger.info(f"[HunyuanVideo] Model {model_name} loaded successfully")

            return True

        except Exception as e:
            import traceback
            logger.error(f"[HunyuanVideo] Failed to load model: {e}")
            logger.error(f"[HunyuanVideo] Traceback:\n{traceback.format_exc()}")
            self._loaded = False
            return False

    def unload(self) -> None:
        """Unload the model from memory."""
        logger.info("[HunyuanVideo] Unloading model...")

        if self._pipe is not None:
            del self._pipe
            self._pipe = None

        self._loaded = False
        self._current_model = None

        gc.collect()
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

        logger.info("[HunyuanVideo] Model unloaded")

    def generate(
        self,
        params: HunyuanVideoParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """Generate a video from parameters."""
        import torch
        from diffusers.utils import export_to_video
        import tempfile

        if not self._loaded:
            model_to_load = params.model if params.model in SUPPORTED_MODELS else "hunyuan-t2v-480p"
            if not self.load(model_to_load):
                return GenerationResult(success=False, error="Failed to load HunyuanVideo model")

        # Check if we need to switch models
        if self._current_model != params.model and params.model in SUPPORTED_MODELS:
            logger.info(f"[HunyuanVideo] Switching model from {self._current_model} to {params.model}")
            if not self.load(params.model):
                return GenerationResult(success=False, error=f"Failed to load model {params.model}")

        model_config = SUPPORTED_MODELS.get(params.model, SUPPORTED_MODELS["hunyuan-t2v-480p"])

        try:
            # Set up generator for reproducibility
            # With CPU offload, generator must be on CPU
            seed_used = params.seed
            if seed_used is None:
                seed_used = torch.randint(0, 2**32, (1,)).item()
                logger.info(f"[HunyuanVideo] Generated random seed: {seed_used}")
            else:
                logger.info(f"[HunyuanVideo] Using provided seed: {seed_used}")

            generator = torch.Generator(device="cpu").manual_seed(seed_used)

            # Clear CUDA cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()

            logger.info(f"[HunyuanVideo] Generating video...")
            logger.info(f"[HunyuanVideo] Resolution: {params.width}x{params.height}")
            logger.info(f"[HunyuanVideo] Frames: {params.num_frames}")
            logger.info(f"[HunyuanVideo] Steps: {params.num_inference_steps}")

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
                    output = self._pipe(
                        prompt=params.prompt,
                        image=image,
                        negative_prompt=params.negative_prompt or "",
                        height=params.height,
                        width=params.width,
                        num_frames=params.num_frames,
                        num_inference_steps=params.num_inference_steps,
                        guidance_scale=model_config["cfg_scale"],
                        generator=generator,
                        callback_on_step_end=callback_on_step_end,
                    )
                else:
                    # Text-to-Video
                    output = self._pipe(
                        prompt=params.prompt,
                        negative_prompt=params.negative_prompt or "",
                        height=params.height,
                        width=params.width,
                        num_frames=params.num_frames,
                        num_inference_steps=params.num_inference_steps,
                        guidance_scale=model_config["cfg_scale"],
                        generator=generator,
                        callback_on_step_end=callback_on_step_end,
                    )

            # Get frames
            video_frames = output.frames[0]
            logger.info(f"[HunyuanVideo] Generated {len(video_frames)} frames")

            return GenerationResult(
                success=True,
                video_frames=video_frames,
                seed_used=seed_used
            )

        except Exception as e:
            import traceback
            error_msg = str(e)
            logger.error(f"[HunyuanVideo] Generation failed: {error_msg}")
            logger.error(f"[HunyuanVideo] Traceback:\n{traceback.format_exc()}")
            return GenerationResult(success=False, error=error_msg)

    def export_video(self, frames: List, output_path: str, fps: int = 24) -> bool:
        """Export frames to video file."""
        try:
            from diffusers.utils import export_to_video
            export_to_video(frames, output_path, fps=fps)
            logger.info(f"[HunyuanVideo] Exported video to {output_path}")
            return True
        except Exception as e:
            logger.error(f"[HunyuanVideo] Failed to export video: {e}")
            return False

    @classmethod
    def get_supported_models(cls) -> dict:
        """Get dictionary of supported models with descriptions."""
        return SUPPORTED_MODELS

    @classmethod
    def get_resolution(cls, preset: str, aspect_ratio: str = "16:9") -> tuple:
        """Get resolution from preset and aspect ratio."""
        if preset in RESOLUTION_PRESETS:
            ratios = RESOLUTION_PRESETS[preset]
            return ratios.get(aspect_ratio, ratios["16:9"])
        return (848, 480)
