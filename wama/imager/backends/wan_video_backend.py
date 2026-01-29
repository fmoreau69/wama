"""
WAMA Imager - Wan Video Backend

Video generation using Wan 2.2 models via Hugging Face Diffusers.
Supports Text-to-Video and Image-to-Video generation.

Models are stored in AI-models/imager/wan/ for centralized management.
"""

import gc
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, List

from django.conf import settings

# IMPORTANT: Set HF_HUB_CACHE BEFORE importing diffusers/transformers
# This ensures models are downloaded to the correct location
def _setup_hf_cache():
    """Set up Hugging Face cache directory before any HF imports."""
    try:
        from wama.imager.utils.model_config import setup_hf_cache_for_wan
        return setup_hf_cache_for_wan()
    except ImportError:
        # Fallback to legacy path
        base_dir = Path(settings.BASE_DIR)
        models_dir = base_dir / "AI-models" / "imager" / "wan"
        models_dir.mkdir(parents=True, exist_ok=True)
        models_dir_str = str(models_dir)

        os.environ['HF_HUB_CACHE'] = models_dir_str
        os.environ['HF_HOME'] = models_dir_str
        os.environ['HUGGINGFACE_HUB_CACHE'] = models_dir_str

        return models_dir_str

# Call this at module load time (before any HF imports)
_WAN_MODELS_DIR = _setup_hf_cache()

from .base import ImageGenerationBackend, GenerationParams, GenerationResult

logger = logging.getLogger(__name__)

# Log the cache location at module load
logger.info(f"[Wan] Module loaded - HF cache directory: {_WAN_MODELS_DIR}")
logger.info(f"[Wan] Environment: HF_HUB_CACHE={os.environ.get('HF_HUB_CACHE', 'not set')}")


def get_wan_models_dir() -> str:
    """Get the directory for Wan video models.

    Returns the path as a string for compatibility with Hugging Face.
    Environment variables are set at module load time via _setup_hf_cache().
    """
    return _WAN_MODELS_DIR


@dataclass
class VideoGenerationParams:
    """Parameters for video generation."""
    prompt: str
    negative_prompt: Optional[str] = None
    model: str = "wan-ti2v-5b"
    width: int = 832
    height: int = 480
    num_frames: int = 81  # Should be 4k+1 (e.g., 81 = 4*20+1)
    fps: int = 16
    guidance_scale: float = 5.0
    num_inference_steps: int = 50
    seed: Optional[int] = None

    # Generation mode
    generation_mode: str = "txt2vid"  # txt2vid or img2vid
    reference_image: Optional[str] = None  # Path to reference image for img2vid


@dataclass
class VideoGenerationResult:
    """Result of video generation."""
    success: bool
    video_frames: List  # List of numpy arrays or PIL images
    video_path: Optional[str] = None  # Path to exported MP4
    seed_used: Optional[int] = None
    error: Optional[str] = None


class WanVideoBackend(ImageGenerationBackend):
    """
    Video generation backend using Wan 2.2 models.

    This backend supports:
    - Image-to-Video (img2vid) using Wan2.2-TI2V-5B
    - Text-to-Video (txt2vid) using Wan2.2-T2V-14B
    - Image-to-Video (img2vid) using Wan2.2-I2V-14B

    VRAM Requirements:
    - wan-ti2v-5b: ~24GB VRAM (supports both txt2vid and img2vid)
    - wan-t2v-14b: ~24GB VRAM (txt2vid only)
    - wan-i2v-14b: ~24GB VRAM (img2vid only)
    """

    name = "wan_video"
    display_name = "Wan Video (Hugging Face)"

    # Map model names to Hugging Face model IDs
    SUPPORTED_MODELS = {
        "wan-ti2v-5b": (
            "Wan 2.2 TI2V 5B (~8GB)",
            "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
        ),
        "wan-t2v-14b": (
            "Wan 2.2 T2V 14B (~24GB)",
            "Wan-AI/Wan2.2-T2V-A14B-Diffusers"
        ),
        "wan-i2v-14b": (
            "Wan 2.2 I2V 14B (~24GB)",
            "Wan-AI/Wan2.2-I2V-A14B-Diffusers"
        ),
    }

    # Resolution presets
    RESOLUTION_PRESETS = {
        "480p": (832, 480),
        "720p": (1280, 720),
    }

    # Default negative prompt for video generation
    DEFAULT_NEGATIVE_PROMPT = (
        "Bright tones, overexposed, static, blurred details, subtitles, "
        "style, works, paintings, images, static, overall gray, worst quality, "
        "low quality, JPEG compression residue, ugly, incomplete, extra fingers, "
        "poorly drawn hands, poorly drawn faces, deformed, disfigured, "
        "misshapen limbs, fused fingers, still picture, messy background, "
        "three legs, many people in the background, walking backwards"
    )

    def __init__(self):
        super().__init__()
        self._pipe_t2v = None
        self._pipe_i2v = None
        self._current_model = None
        self._torch = None
        self._vae = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if Wan video generation is available."""
        try:
            import torch
            import diffusers
            logger.debug(f"[Wan] Checking availability - torch: {torch.__version__}, diffusers: {diffusers.__version__}")
            from diffusers import WanPipeline
            logger.info("[Wan] Backend available - WanPipeline found")
            return True
        except ImportError as e:
            logger.warning(f"[Wan] Backend not available: {e}")
            return False

    def _get_device(self) -> str:
        """Determine the best device to use."""
        if self._torch is None:
            import torch
            self._torch = torch

        if self._torch.cuda.is_available():
            device_name = self._torch.cuda.get_device_name(0)
            logger.info(f"[Wan] CUDA device detected: {device_name}")
            return "cuda"
        elif hasattr(self._torch.backends, 'mps') and self._torch.backends.mps.is_available():
            logger.info("[Wan] MPS device detected (Apple Silicon)")
            return "mps"
        else:
            logger.warning("[Wan] No GPU detected, using CPU (very slow)")
            return "cpu"

    def _get_vram_gb(self) -> float:
        """Get available VRAM in GB."""
        if self._torch is None:
            import torch
            self._torch = torch

        if self._torch.cuda.is_available():
            props = self._torch.cuda.get_device_properties(0)
            total_vram = props.total_memory / (1024 ** 3)
            free_vram = (props.total_memory - self._torch.cuda.memory_allocated(0)) / (1024 ** 3)
            logger.info(f"[Wan] VRAM: {total_vram:.1f}GB total, {free_vram:.1f}GB free")
            return total_vram
        return 0

    def load(self, model_name: str = None) -> bool:
        """
        Load a Wan video generation model.

        Args:
            model_name: Model name (e.g., "wan-t2v-1.3b", "wan-ti2v-5b").

        Returns:
            True if loaded successfully.
        """
        if model_name is None:
            model_name = "wan-t2v-1.3b"

        logger.info(f"[Wan] Requested model: {model_name}")

        # Map to HuggingFace model ID
        model_id = self.map_model_name(model_name)
        logger.info(f"[Wan] Mapped to HuggingFace ID: {model_id}")

        # Check if already loaded
        if self._loaded and self._current_model == model_id:
            logger.info(f"[Wan] Model {model_id} already loaded, skipping")
            return True

        try:
            import torch
            logger.info(f"[Wan] PyTorch version: {torch.__version__}")
            logger.info(f"[Wan] CUDA available: {torch.cuda.is_available()}")

            from diffusers import AutoencoderKLWan, WanPipeline
            logger.info("[Wan] Diffusers imports successful")

            self._torch = torch
            self._device = self._get_device()

            # Get cache directory for models
            cache_dir = get_wan_models_dir()
            logger.info(f"[Wan] ========================================")
            logger.info(f"[Wan] Models cache directory: {cache_dir}")
            logger.info(f"[Wan] Directory exists: {os.path.exists(cache_dir)}")
            logger.info(f"[Wan] HF_HUB_CACHE env: {os.environ.get('HF_HUB_CACHE', 'not set')}")
            logger.info(f"[Wan] ========================================")
            logger.info(f"[Wan] Starting model load: {model_id} on {self._device}")

            # Unload previous model if any
            if self._pipe_t2v is not None:
                logger.info("[Wan] Unloading previous model...")
                self.unload()

            # Determine VAE dtype based on VRAM
            # float32 = better quality but 2x memory (needs 32GB+ for safety)
            # bfloat16 = good quality, half memory (recommended for 24GB GPUs)
            vram_gb = self._get_vram_gb()
            if vram_gb >= 32:
                vae_dtype = torch.float32
                logger.info("[Wan] Loading VAE in float32 (best quality, sufficient VRAM)")
            else:
                vae_dtype = torch.bfloat16
                logger.info(f"[Wan] Loading VAE in bfloat16 ({vram_gb:.0f}GB VRAM - saves memory)")

            logger.info("[Wan] Loading VAE (AutoencoderKLWan)...")
            self._vae = AutoencoderKLWan.from_pretrained(
                model_id,
                subfolder="vae",
                torch_dtype=vae_dtype,
                cache_dir=cache_dir
            )
            logger.info(f"[Wan] VAE loaded successfully (dtype={vae_dtype})")

            # Load T2V pipeline
            logger.info("[Wan] Loading T2V pipeline (WanPipeline)... This may take several minutes on first run.")
            self._pipe_t2v = WanPipeline.from_pretrained(
                model_id,
                vae=self._vae,
                torch_dtype=torch.bfloat16,
                cache_dir=cache_dir
            )
            logger.info("[Wan] T2V pipeline loaded")

            # Move to device or enable offloading based on VRAM
            # Video generation (especially VAE decode) needs significant memory
            logger.info(f"[Wan] Detected VRAM: {vram_gb:.1f}GB")

            # Clear CUDA cache before loading to maximize available memory
            if self._device == "cuda":
                torch.cuda.empty_cache()
                gc.collect()

            # Determine strategy based on VRAM:
            # - 48GB+: Full GPU (A100 80GB, etc.)
            # - 32-48GB: Model CPU offload (A100 40GB, etc.)
            # - 24-32GB: Sequential CPU offload (RTX 4090, 3090 - T5 encoder can OOM)
            # - <24GB: Sequential CPU offload required
            if self._device == "cuda" and vram_gb >= 48:
                logger.info(f"[Wan] High VRAM ({vram_gb:.1f}GB >= 48GB), using full GPU...")
                self._pipe_t2v = self._pipe_t2v.to(self._device)
                logger.info(f"[Wan] Pipeline moved to {self._device}")
            elif self._device == "cuda" and vram_gb >= 32:
                # For 32-48GB GPUs, use regular CPU offload
                logger.info(f"[Wan] VRAM ({vram_gb:.1f}GB) - using model CPU offload...")
                self._pipe_t2v.enable_model_cpu_offload()
                logger.info("[Wan] Model CPU offload enabled")
            elif self._device == "cuda":
                # For 24-32GB GPUs (RTX 4090, 3090), use SEQUENTIAL CPU offload
                # This is more aggressive - offloads at layer level, not component level
                # Required because T5 encoder alone is ~5GB and can OOM with regular offload
                logger.info(f"[Wan] VRAM ({vram_gb:.1f}GB < 32GB) - using sequential CPU offload...")
                logger.info("[Wan] Sequential offload moves individual layers to GPU as needed")
                logger.info("[Wan] This is slower but prevents OOM during T5 encoding")
                self._pipe_t2v.enable_sequential_cpu_offload()
                logger.info("[Wan] Sequential CPU offload enabled")
            else:
                logger.info(f"[Wan] Moving pipeline to {self._device}...")
                self._pipe_t2v = self._pipe_t2v.to(self._device)
                logger.info(f"[Wan] Pipeline moved to {self._device}")

            # Enable memory optimizations regardless of offload mode
            try:
                self._pipe_t2v.enable_vae_slicing()
                logger.info("[Wan] VAE slicing enabled (reduces memory during decode)")
            except Exception as e:
                logger.debug(f"[Wan] VAE slicing not available: {e}")

            try:
                self._pipe_t2v.enable_vae_tiling()
                logger.info("[Wan] VAE tiling enabled")
            except Exception as e:
                logger.debug(f"[Wan] VAE tiling not available: {e}")

            # Enable attention slicing to reduce memory during inference
            try:
                self._pipe_t2v.enable_attention_slicing("auto")
                logger.info("[Wan] Attention slicing enabled (reduces peak memory)")
            except Exception as e:
                logger.debug(f"[Wan] Attention slicing not available: {e}")

            self._current_model = model_id
            self._loaded = True
            logger.info(f"[Wan] ✓ Model {model_id} loaded successfully on {self._device}")

            return True

        except Exception as e:
            import traceback
            logger.error(f"[Wan] ✗ Failed to load model {model_id}: {e}")
            logger.error(f"[Wan] Traceback:\n{traceback.format_exc()}")
            self._loaded = False
            return False

    def _load_i2v_pipeline(self) -> bool:
        """Load Image-to-Video pipeline if needed."""
        if self._pipe_i2v is not None:
            logger.info("[Wan I2V] Pipeline already loaded, skipping")
            return True

        try:
            import torch
            from diffusers import WanImageToVideoPipeline

            # Use the correct I2V model
            model_id = "Wan-AI/Wan2.2-I2V-A14B-Diffusers"

            # Get cache directory for models
            cache_dir = get_wan_models_dir()
            logger.info(f"[Wan I2V] ========================================")
            logger.info(f"[Wan I2V] Models cache directory: {cache_dir}")
            logger.info(f"[Wan I2V] Directory exists: {os.path.exists(cache_dir)}")
            logger.info(f"[Wan I2V] HF_HUB_CACHE env: {os.environ.get('HF_HUB_CACHE', 'not set')}")
            logger.info(f"[Wan I2V] ========================================")
            logger.info(f"[Wan I2V] Starting I2V pipeline load from {model_id}")
            logger.info("[Wan I2V] This is a 14B parameter model, requires ~24GB+ VRAM")
            logger.info("[Wan I2V] First download may take 20-30 minutes (~25GB)")

            # Load pipeline directly (simpler approach, handles all components)
            logger.info("[Wan I2V] Loading WanImageToVideoPipeline... This may take several minutes.")
            self._pipe_i2v = WanImageToVideoPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.bfloat16,
                cache_dir=cache_dir
            )
            logger.info("[Wan I2V] Pipeline loaded")

            # Enable offloading for low VRAM (I2V 14B needs ~28GB in bfloat16)
            vram_gb = self._get_vram_gb()
            logger.info(f"[Wan I2V] Detected VRAM: {vram_gb:.1f}GB")

            # I2V 14B needs ~28GB VRAM (14B params * 2 bytes for bfloat16)
            # RTX 4090 (24GB) needs CPU offload, but RTX 3090 Ti / A100 can run fully
            if self._device == "cuda" and vram_gb >= 32:
                # Enough VRAM for full model
                logger.info(f"[Wan I2V] Sufficient VRAM ({vram_gb:.1f}GB >= 32GB), using full GPU...")
                self._pipe_i2v = self._pipe_i2v.to(self._device)
                try:
                    self._pipe_i2v.enable_vae_tiling()
                    logger.info("[Wan I2V] VAE tiling enabled")
                except Exception:
                    pass
                logger.info(f"[Wan I2V] Pipeline moved to {self._device}")
            elif self._device == "cuda" and vram_gb >= 20:
                # 20-32GB: Use model CPU offload (moves modules to GPU only when needed)
                logger.info(f"[Wan I2V] VRAM ({vram_gb:.1f}GB) - using smart CPU offload...")
                logger.info("[Wan I2V] Note: I2V 14B (~28GB) is larger than your VRAM")
                logger.info("[Wan I2V] Generation will be slower due to CPU<->GPU transfers")
                self._pipe_i2v.enable_model_cpu_offload()
                try:
                    self._pipe_i2v.enable_vae_tiling()
                    logger.info("[Wan I2V] VAE tiling enabled")
                except Exception:
                    pass
                logger.info("[Wan I2V] CPU offload enabled")
            elif self._device == "cuda":
                # <20GB: Use sequential CPU offload (more aggressive, slower but less VRAM)
                logger.info(f"[Wan I2V] Low VRAM ({vram_gb:.1f}GB < 20GB), using sequential CPU offload...")
                logger.warning("[Wan I2V] ⚠ I2V on low VRAM will be VERY slow. Consider using T2V instead.")
                self._pipe_i2v.enable_sequential_cpu_offload()
                logger.info("[Wan I2V] Sequential CPU offload enabled")
            else:
                logger.info(f"[Wan I2V] Moving pipeline to {self._device}...")
                self._pipe_i2v = self._pipe_i2v.to(self._device)
                logger.info(f"[Wan I2V] Pipeline moved to {self._device}")

            logger.info("[Wan I2V] ✓ I2V pipeline loaded successfully")
            return True

        except Exception as e:
            import traceback
            logger.error(f"[Wan I2V] ✗ Failed to load I2V pipeline: {e}")
            logger.error(f"[Wan I2V] Traceback:\n{traceback.format_exc()}")
            self._pipe_i2v = None
            return False

    def generate(
        self,
        params: GenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """
        Generate images/videos based on parameters.

        This method routes to video generation for txt2vid/img2vid modes.

        Args:
            params: Generation parameters.
            progress_callback: Optional progress callback (0-100).

        Returns:
            GenerationResult (contains video frames for video modes).
        """
        # For video modes, route to video generation
        if params.generation_mode in ('txt2vid', 'img2vid'):
            video_params = VideoGenerationParams(
                prompt=params.prompt,
                negative_prompt=params.negative_prompt,
                model=params.model,
                width=params.width,
                height=params.height,
                guidance_scale=params.guidance_scale,
                seed=params.seed,
                generation_mode=params.generation_mode,
                reference_image=params.reference_image,
            )
            video_result = self.generate_video(video_params, progress_callback)

            # Convert to GenerationResult for compatibility
            return GenerationResult(
                success=video_result.success,
                images=[],  # Videos don't have images
                seed_used=video_result.seed_used,
                error=video_result.error
            )

        # Fallback: this backend doesn't support image generation
        return GenerationResult(
            success=False,
            images=[],
            error="WanVideoBackend only supports video generation (txt2vid, img2vid)"
        )

    def generate_video(
        self,
        params: VideoGenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> VideoGenerationResult:
        """
        Generate video based on parameters.

        Args:
            params: Video generation parameters.
            progress_callback: Optional progress callback (0-100).

        Returns:
            VideoGenerationResult with video frames.
        """
        if not self._loaded:
            if not self.load(params.model):
                return VideoGenerationResult(
                    success=False,
                    video_frames=[],
                    error="Failed to load model"
                )

        # Route to appropriate generation method
        if params.generation_mode == 'img2vid' and params.reference_image:
            return self._generate_img2vid(params, progress_callback)
        else:
            return self._generate_txt2vid(params, progress_callback)

    def _generate_txt2vid(
        self,
        params: VideoGenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> VideoGenerationResult:
        """Generate video from text prompt."""
        try:
            import torch
            import time

            logger.info("[Wan T2V] Starting Text-to-Video generation")
            logger.info(f"[Wan T2V] Prompt: {params.prompt[:100]}{'...' if len(params.prompt) > 100 else ''}")
            logger.info(f"[Wan T2V] Resolution: {params.width}x{params.height}")
            logger.info(f"[Wan T2V] Frames: {params.num_frames}, Steps: {params.num_inference_steps}")
            logger.info(f"[Wan T2V] Guidance scale: {params.guidance_scale}")

            if self._pipe_t2v is None:
                logger.info("[Wan T2V] Pipeline not loaded, loading now...")
                if not self.load(params.model):
                    return VideoGenerationResult(
                        success=False,
                        video_frames=[],
                        error="T2V pipeline not loaded"
                    )

            # Setup generator for reproducibility
            seed_used = params.seed
            if seed_used is None:
                seed_used = torch.randint(0, 2**32, (1,)).item()
                logger.info(f"[Wan T2V] Generated random seed: {seed_used}")
            else:
                logger.info(f"[Wan T2V] Using provided seed: {seed_used}")

            generator = torch.Generator(device="cpu").manual_seed(seed_used)

            # Build prompts
            prompt = params.prompt
            negative_prompt = params.negative_prompt or self.DEFAULT_NEGATIVE_PROMPT
            logger.info(f"[Wan T2V] Negative prompt: {negative_prompt[:50]}...")

            start_time = time.time()
            last_log_time = start_time

            # Progress callback wrapper
            def step_callback(pipe, step_index, timestep, callback_kwargs):
                nonlocal last_log_time
                current_time = time.time()
                if progress_callback:
                    progress = int((step_index / params.num_inference_steps) * 100)
                    progress_callback(progress)
                # Log every 10 steps or every 30 seconds
                if step_index % 10 == 0 or (current_time - last_log_time) > 30:
                    elapsed = current_time - start_time
                    logger.info(f"[Wan T2V] Step {step_index}/{params.num_inference_steps} ({progress}%) - Elapsed: {elapsed:.1f}s")
                    last_log_time = current_time
                return callback_kwargs

            # Clear CUDA cache before generation to avoid fragmentation issues
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()
                free_mem = torch.cuda.memory_reserved(0) - torch.cuda.memory_allocated(0)
                logger.info(f"[Wan T2V] CUDA cache cleared. Free reserved: {free_mem / 1024**3:.1f}GB")

            # Generate video
            logger.info("[Wan T2V] Starting inference... This may take several minutes.")
            with torch.inference_mode():
                output = self._pipe_t2v(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    height=params.height,
                    width=params.width,
                    num_frames=params.num_frames,
                    num_inference_steps=params.num_inference_steps,
                    guidance_scale=params.guidance_scale,
                    generator=generator,
                    callback_on_step_end=step_callback,
                )

            video_frames = output.frames[0]  # Get first (and only) video

            total_time = time.time() - start_time
            logger.info(f"[Wan T2V] ✓ Generation complete in {total_time:.1f}s ({len(video_frames)} frames)")

            if progress_callback:
                progress_callback(100)

            return VideoGenerationResult(
                success=True,
                video_frames=video_frames,
                seed_used=seed_used
            )

        except Exception as e:
            import traceback
            logger.error(f"[Wan T2V] ✗ Generation failed: {e}")
            logger.error(f"[Wan T2V] Traceback:\n{traceback.format_exc()}")
            return VideoGenerationResult(
                success=False,
                video_frames=[],
                error=str(e)
            )

    def _generate_img2vid(
        self,
        params: VideoGenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> VideoGenerationResult:
        """Generate video from reference image."""
        try:
            import torch
            import numpy as np
            import time
            from PIL import Image

            logger.info("[Wan I2V] Starting Image-to-Video generation")
            logger.info(f"[Wan I2V] Reference image: {params.reference_image}")
            logger.info(f"[Wan I2V] Prompt: {params.prompt[:100]}{'...' if len(params.prompt) > 100 else ''}")
            logger.info(f"[Wan I2V] Target resolution: {params.width}x{params.height}")
            logger.info(f"[Wan I2V] Frames: {params.num_frames}, Steps: {params.num_inference_steps}")

            # Load I2V pipeline if needed
            if self._pipe_i2v is None:
                logger.info("[Wan I2V] Pipeline not loaded, loading now...")
                if not self._load_i2v_pipeline():
                    return VideoGenerationResult(
                        success=False,
                        video_frames=[],
                        error="I2V pipeline not available. Make sure diffusers is up to date: pip install git+https://github.com/huggingface/diffusers"
                    )

            # Load and prepare reference image
            if not params.reference_image or not os.path.exists(params.reference_image):
                logger.error(f"[Wan I2V] Reference image not found: {params.reference_image}")
                return VideoGenerationResult(
                    success=False,
                    video_frames=[],
                    error=f"Reference image not found: {params.reference_image}"
                )

            logger.info("[Wan I2V] Loading reference image...")
            image = Image.open(params.reference_image).convert("RGB")
            original_size = image.size
            logger.info(f"[Wan I2V] Original image size: {original_size[0]}x{original_size[1]}")

            # Calculate dimensions using pipeline's VAE scale factor
            # max_area based on target resolution
            max_area = params.width * params.height
            aspect_ratio = image.height / image.width

            # Get mod_value from pipeline if available, otherwise use default
            try:
                mod_value = self._pipe_i2v.vae_scale_factor_spatial * self._pipe_i2v.transformer.config.patch_size[1]
                logger.info(f"[Wan I2V] Using pipeline mod_value: {mod_value}")
            except Exception:
                mod_value = 16  # Default VAE scale factor
                logger.info(f"[Wan I2V] Using default mod_value: {mod_value}")

            height = round(np.sqrt(max_area * aspect_ratio)) // mod_value * mod_value
            width = round(np.sqrt(max_area / aspect_ratio)) // mod_value * mod_value
            image = image.resize((width, height), Image.LANCZOS)
            logger.info(f"[Wan I2V] Image resized to {width}x{height} (mod {mod_value} aligned)")

            # Setup generator
            seed_used = params.seed
            if seed_used is None:
                seed_used = torch.randint(0, 2**32, (1,)).item()
                logger.info(f"[Wan I2V] Generated random seed: {seed_used}")
            else:
                logger.info(f"[Wan I2V] Using provided seed: {seed_used}")

            generator = torch.Generator(device="cpu").manual_seed(seed_used)

            # Build prompts (prompt is optional for I2V)
            prompt = params.prompt if params.prompt else ""
            negative_prompt = params.negative_prompt or self.DEFAULT_NEGATIVE_PROMPT
            logger.info(f"[Wan I2V] Prompt: {prompt[:50] if prompt else '(none)'}...")
            logger.info(f"[Wan I2V] Negative prompt: {negative_prompt[:50]}...")

            # Use recommended guidance scale for I2V (3.5 is recommended)
            guidance_scale = params.guidance_scale if params.guidance_scale else 3.5
            logger.info(f"[Wan I2V] Guidance scale: {guidance_scale}")

            start_time = time.time()
            last_log_time = start_time

            # Progress callback wrapper
            def step_callback(pipe, step_index, timestep, callback_kwargs):
                nonlocal last_log_time
                current_time = time.time()
                if progress_callback:
                    progress = int((step_index / params.num_inference_steps) * 100)
                    progress_callback(progress)
                # Log every 10 steps or every 30 seconds
                if step_index % 10 == 0 or (current_time - last_log_time) > 30:
                    elapsed = current_time - start_time
                    logger.info(f"[Wan I2V] Step {step_index}/{params.num_inference_steps} ({progress}%) - Elapsed: {elapsed:.1f}s")
                    last_log_time = current_time
                return callback_kwargs

            # Generate video
            logger.info("[Wan I2V] Starting inference... This may take 10-30 minutes depending on your GPU.")
            with torch.inference_mode():
                output = self._pipe_i2v(
                    image=image,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    height=height,
                    width=width,
                    num_frames=params.num_frames,
                    num_inference_steps=params.num_inference_steps,
                    guidance_scale=guidance_scale,
                    generator=generator,
                    callback_on_step_end=step_callback,
                )

            video_frames = output.frames[0]

            total_time = time.time() - start_time
            logger.info(f"[Wan I2V] ✓ Generation complete in {total_time:.1f}s ({len(video_frames)} frames)")

            if progress_callback:
                progress_callback(100)

            return VideoGenerationResult(
                success=True,
                video_frames=video_frames,
                seed_used=seed_used
            )

        except Exception as e:
            import traceback
            logger.error(f"[Wan I2V] ✗ Generation failed: {e}")
            logger.error(f"[Wan I2V] Traceback:\n{traceback.format_exc()}")
            return VideoGenerationResult(
                success=False,
                video_frames=[],
                error=str(e)
            )

    def export_video(
        self,
        frames,
        output_path: str,
        fps: int = 16
    ) -> bool:
        """
        Export video frames to MP4 file.

        Args:
            frames: List of video frames (numpy arrays or PIL images).
            output_path: Path to save the MP4 file.
            fps: Frames per second.

        Returns:
            True if export successful.
        """
        try:
            import time
            from diffusers.utils import export_to_video

            logger.info(f"[Wan Export] Starting video export...")
            logger.info(f"[Wan Export] Frames: {len(frames)}, FPS: {fps}")
            logger.info(f"[Wan Export] Output path: {output_path}")

            # Ensure output directory exists
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[Wan Export] Output directory: {output_dir}")

            # Export to video
            start_time = time.time()
            export_to_video(frames, output_path, fps=fps)
            export_time = time.time() - start_time

            # Check file size
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
                logger.info(f"[Wan Export] ✓ Video exported in {export_time:.1f}s")
                logger.info(f"[Wan Export] File size: {file_size:.2f} MB")
            else:
                logger.warning(f"[Wan Export] Export completed but file not found at {output_path}")

            return True

        except Exception as e:
            import traceback
            logger.error(f"[Wan Export] ✗ Failed to export video: {e}")
            logger.error(f"[Wan Export] Traceback:\n{traceback.format_exc()}")
            return False

    def unload(self) -> None:
        """Unload all models from memory."""
        if self._pipe_t2v is not None:
            del self._pipe_t2v
            self._pipe_t2v = None

        if self._pipe_i2v is not None:
            del self._pipe_i2v
            self._pipe_i2v = None

        if self._vae is not None:
            del self._vae
            self._vae = None

        self._current_model = None
        self._loaded = False

        # Force garbage collection
        gc.collect()

        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

        logger.info("Wan video models unloaded from memory")

    @classmethod
    def calculate_num_frames(cls, duration_seconds: float, fps: int = 16) -> int:
        """
        Calculate number of frames for Wan (must be 4k+1).

        Args:
            duration_seconds: Desired video duration in seconds.
            fps: Frames per second.

        Returns:
            Number of frames (always 4k+1).
        """
        raw_frames = int(duration_seconds * fps)
        # Round to nearest 4k+1
        k = round((raw_frames - 1) / 4)
        return 4 * k + 1

    @classmethod
    def get_resolution(cls, preset: str) -> tuple:
        """
        Get resolution from preset name.

        Args:
            preset: Resolution preset ("480p" or "720p").

        Returns:
            (width, height) tuple.
        """
        return cls.RESOLUTION_PRESETS.get(preset, (832, 480))
