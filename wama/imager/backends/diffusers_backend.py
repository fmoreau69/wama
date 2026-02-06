"""
WAMA Imager - Diffusers Backend

Image generation using Hugging Face Diffusers library.
Compatible with Python 3.12+.

This backend uses Stable Diffusion models from Hugging Face.
"""

import gc
import logging
from typing import Optional, Callable, List

from .base import ImageGenerationBackend, GenerationParams, GenerationResult

logger = logging.getLogger(__name__)

# Import centralized model configuration
try:
    from wama.imager.utils.model_config import (
        get_stable_diffusion_directory,
        get_flux_directory,
        get_logo_directory,
        LOGO_MODELS,
        is_lora_model,
        get_model_trigger_words,
    )
    _SD_CACHE_DIR = str(get_stable_diffusion_directory())
    _FLUX_CACHE_DIR = str(get_flux_directory())
    _LOGO_CACHE_DIR = str(get_logo_directory())
    logger.info(f"[Diffusers] Using cache directory: {_SD_CACHE_DIR}")
    logger.info(f"[Diffusers] FLUX cache directory: {_FLUX_CACHE_DIR}")
    logger.info(f"[Diffusers] Logo cache directory: {_LOGO_CACHE_DIR}")
except ImportError:
    _SD_CACHE_DIR = None
    _FLUX_CACHE_DIR = None
    _LOGO_CACHE_DIR = None
    LOGO_MODELS = {}
    logger.warning("[Diffusers] model_config not available, using default HF cache")

    def is_lora_model(model_name):
        return False

    def get_model_trigger_words(model_name):
        return []


class DiffusersBackend(ImageGenerationBackend):
    """
    Image generation backend using Hugging Face Diffusers.

    This is the recommended backend for Python 3.12+ as it doesn't
    have the compatibility issues that ImaginAiry has.
    """

    name = "diffusers"
    display_name = "Diffusers (Hugging Face)"

    # Map generic model names to Hugging Face model IDs
    # Format: dict with name, hf_id, description, vram, pipeline, min_resolution, max_resolution
    SUPPORTED_MODELS = {
        # HunyuanImage 2.1 - High quality images (supports 1024-2048)
        "hunyuan-image-2.1": {
            "name": "HunyuanImage 2.1",
            "hf_id": "hunyuanvideo-community/HunyuanImage-2.1-Diffusers",
            "description": "Haute qualité 1K-2K - 24GB VRAM - Support 16:9, 9:16, 21:9",
            "vram": "24GB",
            "pipeline": "hunyuan",
            "min_resolution": 1024,
            "max_resolution": 2048,
            "recommended_resolutions": ["2048x2048", "2048x1152", "1152x2048", "2048x880"],
        },

        # Stable Diffusion models
        "stable-diffusion-v1-5": {
            "name": "Stable Diffusion 1.5",
            "hf_id": "stable-diffusion-v1-5/stable-diffusion-v1-5",
            "description": "Modèle classique - 4GB VRAM - Rapide et polyvalent",
            "vram": "4GB",
            "pipeline": "sd",
            "min_resolution": 256,
            "max_resolution": 768,
            "recommended_resolutions": ["512x512", "768x768", "896x512", "512x896"],
        },
        "stable-diffusion-2-1": {
            "name": "Stable Diffusion 2.1",
            "hf_id": "stabilityai/stable-diffusion-2-1",
            "description": "Version améliorée - 6GB VRAM - Meilleure cohérence",
            "vram": "6GB",
            "pipeline": "sd",
            "min_resolution": 256,
            "max_resolution": 1024,
            "recommended_resolutions": ["768x768", "1024x1024", "896x512", "512x896"],
        },
        "stable-diffusion-xl": {
            "name": "Stable Diffusion XL",
            "hf_id": "stabilityai/stable-diffusion-xl-base-1.0",
            "description": "Haute résolution - 10GB VRAM - Images détaillées",
            "vram": "10GB",
            "pipeline": "sdxl",
            "min_resolution": 512,
            "max_resolution": 1536,
            "recommended_resolutions": ["1024x1024", "1344x768", "768x1344", "1920x1088"],
        },

        # Artistic models
        "openjourney-v4": {
            "name": "OpenJourney v4",
            "hf_id": "prompthero/openjourney-v4",
            "description": "Style Midjourney - 4GB VRAM - Art créatif",
            "vram": "4GB",
            "pipeline": "sd",
            "min_resolution": 256,
            "max_resolution": 768,
            "recommended_resolutions": ["512x512", "768x768", "896x512", "512x896"],
        },
        "dreamlike-art-2": {
            "name": "Dreamlike Art 2.0",
            "hf_id": "dreamlike-art/dreamlike-diffusion-1.0",
            "description": "Style artistique - 4GB VRAM - Images oniriques",
            "vram": "4GB",
            "pipeline": "sd",
            "min_resolution": 256,
            "max_resolution": 768,
            "recommended_resolutions": ["512x512", "768x768", "896x512", "512x896"],
        },
        "dreamshaper-8": {
            "name": "DreamShaper 8",
            "hf_id": "Lykon/DreamShaper",
            "description": "Polyvalent - 4GB VRAM - Excellent rapport qualité/vitesse",
            "vram": "4GB",
            "pipeline": "sd",
            "min_resolution": 256,
            "max_resolution": 768,
            "recommended_resolutions": ["512x512", "768x768", "896x512", "512x896"],
        },
        "deliberate-v2": {
            "name": "Deliberate v2",
            "hf_id": "stablediffusionapi/deliberate-v2",
            "description": "Réaliste/Artistique - 4GB VRAM - Très détaillé",
            "vram": "4GB",
            "pipeline": "sd",
            "min_resolution": 256,
            "max_resolution": 768,
            "recommended_resolutions": ["512x512", "768x768", "896x512", "512x896"],
        },

        # Realistic models
        "realistic-vision-v5": {
            "name": "Realistic Vision V5",
            "hf_id": "SG161222/Realistic_Vision_V5.1_noVAE",
            "description": "Photoréaliste - 4GB VRAM - Portraits et paysages",
            "vram": "4GB",
            "pipeline": "sd",
            "min_resolution": 256,
            "max_resolution": 768,
            "recommended_resolutions": ["512x512", "768x768", "896x512", "512x896"],
        },

        # Anime models
        "anything-v5": {
            "name": "Anything V5",
            "hf_id": "stablediffusionapi/anything-v5",
            "description": "Style anime - 4GB VRAM - Illustrations manga",
            "vram": "4GB",
            "pipeline": "sd",
            "min_resolution": 256,
            "max_resolution": 768,
            "recommended_resolutions": ["512x512", "768x768", "896x512", "512x896"],
        },

        # =================================================================
        # LOGO GENERATION MODELS
        # =================================================================

        # FLUX.1-dev + LoRA for Logo Design
        "flux-lora-logo-design": {
            "name": "FLUX Logo Design LoRA",
            "hf_id": "Shakker-Labs/FLUX.1-dev-LoRA-Logo-Design",
            "base_model": "black-forest-labs/FLUX.1-dev",
            "description": "Logo Design - 16GB VRAM - Excellent quality logos",
            "vram": "16GB",
            "pipeline": "flux",
            "model_type": "lora",
            "category": "logo",
            "trigger_words": ["wablogo", "logo", "Minimalist"],
            "lora_scale": 0.8,
            "min_resolution": 512,
            "max_resolution": 1024,
            "recommended_resolutions": ["1024x1024", "768x768", "1024x768", "768x1024"],
        },

        # LogoRedmond V2 - SDXL + LoRA
        "logo-redmond-v2": {
            "name": "LogoRedmond V2 (SDXL)",
            "hf_id": "artificialguybr/LogoRedmond-LogoLoraForSDXL-V2",
            "base_model": "stabilityai/stable-diffusion-xl-base-1.0",
            "description": "Logo Generation - 10GB VRAM - Commercial OK",
            "vram": "10GB",
            "pipeline": "sdxl",
            "model_type": "lora",
            "category": "logo",
            "trigger_words": ["LogoRedAF"],
            "lora_scale": 0.7,
            "min_resolution": 512,
            "max_resolution": 1024,
            "recommended_resolutions": ["1024x1024", "768x768", "1024x768", "768x1024"],
        },

        # Amazing Logos V2 - Full SD 1.5 fine-tune
        "amazing-logos-v2": {
            "name": "Amazing Logos V2",
            "hf_id": "iamkaikai/amazing-logos-v2",
            "description": "Logo Generation - 4GB VRAM - Commercial OK",
            "vram": "4GB",
            "pipeline": "sd",
            "model_type": "full_finetune",
            "category": "logo",
            "min_resolution": 256,
            "max_resolution": 768,
            "recommended_resolutions": ["512x512", "512x768", "768x512"],
        },
    }

    # Legacy support: map old format to new
    @classmethod
    def _get_model_info(cls, model_name: str) -> dict:
        """Get model info, supporting both old tuple and new dict formats."""
        model_info = cls.SUPPORTED_MODELS.get(model_name)
        if model_info is None:
            return None
        if isinstance(model_info, tuple):
            # Old format: (name, hf_id)
            return {"name": model_info[0], "hf_id": model_info[1], "pipeline": "sd"}
        return model_info

    def __init__(self):
        super().__init__()
        self._pipe = None
        self._pipe_img2img = None  # Separate pipeline for img2img
        self._current_model = None
        self._torch = None
        self._diffusers = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if diffusers library is installed."""
        try:
            import torch
            import diffusers
            from diffusers import StableDiffusionPipeline
            return True
        except ImportError:
            return False

    def _get_device(self) -> str:
        """Determine the best device to use."""
        if self._torch is None:
            import torch
            self._torch = torch

        if self._torch.cuda.is_available():
            device_name = self._torch.cuda.get_device_name(0)
            props = self._torch.cuda.get_device_properties(0)
            vram_gb = props.total_memory / (1024 ** 3)
            logger.info(f"[Diffusers] CUDA device detected: {device_name}")
            logger.info(f"[Diffusers] VRAM: {vram_gb:.1f}GB")
            return "cuda"
        elif hasattr(self._torch.backends, 'mps') and self._torch.backends.mps.is_available():
            logger.info("[Diffusers] MPS device detected (Apple Silicon)")
            return "mps"
        else:
            logger.warning("[Diffusers] No GPU detected, using CPU (slow)")
            return "cpu"

    def _load_sd_pipeline(self, model_id: str):
        """Load a standard Stable Diffusion pipeline."""
        from diffusers import StableDiffusionPipeline

        dtype = self._torch.float16 if self._device == "cuda" else self._torch.float32

        kwargs = {
            "torch_dtype": dtype,
            "use_safetensors": True,
            "safety_checker": None,
        }
        if _SD_CACHE_DIR:
            kwargs["cache_dir"] = _SD_CACHE_DIR
            logger.info(f"[Diffusers] Loading from cache: {_SD_CACHE_DIR}")

        return StableDiffusionPipeline.from_pretrained(model_id, **kwargs)

    def _load_sdxl_pipeline(self, model_id: str):
        """Load a Stable Diffusion XL pipeline."""
        from diffusers import StableDiffusionXLPipeline

        dtype = self._torch.float16 if self._device == "cuda" else self._torch.float32

        kwargs = {
            "torch_dtype": dtype,
            "use_safetensors": True,
            "variant": "fp16" if dtype == self._torch.float16 else None,
        }
        if _SD_CACHE_DIR:
            kwargs["cache_dir"] = _SD_CACHE_DIR
            logger.info(f"[Diffusers] Loading SDXL from cache: {_SD_CACHE_DIR}")

        return StableDiffusionXLPipeline.from_pretrained(model_id, **kwargs)

    def _load_flux_pipeline(self, model_info: dict):
        """
        Load a FLUX pipeline, optionally with LoRA.

        Args:
            model_info: Model configuration dictionary containing base_model, hf_id, etc.
        """
        import gc
        from diffusers import FluxPipeline

        base_model = model_info.get('base_model', 'black-forest-labs/FLUX.1-dev')
        lora_repo = model_info.get('hf_id')
        model_type = model_info.get('model_type', 'base')
        lora_scale = model_info.get('lora_scale', 0.8)

        logger.info(f"[Diffusers] Loading FLUX pipeline: {base_model}")

        # Aggressive CUDA cleanup before loading this heavy model
        if self._torch.cuda.is_available():
            logger.info("[Diffusers] Clearing CUDA memory before FLUX load...")
            self._torch.cuda.empty_cache()
            self._torch.cuda.synchronize()
            gc.collect()

        kwargs = {
            "torch_dtype": self._torch.bfloat16,
        }

        if _FLUX_CACHE_DIR:
            kwargs["cache_dir"] = _FLUX_CACHE_DIR
            logger.info(f"[Diffusers] Loading FLUX from cache: {_FLUX_CACHE_DIR}")

        # Load base FLUX pipeline
        pipe = FluxPipeline.from_pretrained(base_model, **kwargs)

        # Apply memory strategy FIRST (before LoRA) for faster LoRA fusion on GPU
        try:
            from wama.model_manager.services.memory_manager import MemoryManager
            pipe = MemoryManager.apply_strategy_for_model(
                pipeline=pipe,
                model_type='flux',
                device=self._device,
                headroom_gb=4.0  # Extra headroom for LoRA operations
            )
        except ImportError:
            logger.warning("[Diffusers] MemoryManager not available, using default GPU loading")
            pipe = pipe.to(self._device)

        # Load LoRA weights AFTER moving to GPU (much faster fusion)
        if model_type == 'lora' and lora_repo:
            logger.info(f"[Diffusers] Loading LoRA weights from: {lora_repo}")
            try:
                pipe.load_lora_weights(lora_repo)
                logger.info(f"[Diffusers] LoRA weights loaded, fusing with scale {lora_scale}")
                pipe.fuse_lora(lora_scale=lora_scale)
                logger.info("[Diffusers] LoRA fused successfully")
            except Exception as e:
                logger.warning(f"[Diffusers] Could not load LoRA weights: {e}")
                # Continue without LoRA

        return pipe

    def _load_sdxl_with_lora(self, model_info: dict):
        """
        Load SDXL pipeline with LoRA weights.

        Args:
            model_info: Model configuration dictionary containing base_model, hf_id, etc.
        """
        from diffusers import StableDiffusionXLPipeline

        base_model = model_info.get('base_model', 'stabilityai/stable-diffusion-xl-base-1.0')
        lora_repo = model_info.get('hf_id')
        lora_scale = model_info.get('lora_scale', 0.7)

        logger.info(f"[Diffusers] Loading SDXL with LoRA: {base_model}")
        logger.info(f"[Diffusers] LoRA source: {lora_repo}")

        dtype = self._torch.float16 if self._device == "cuda" else self._torch.float32

        kwargs = {
            "torch_dtype": dtype,
            "use_safetensors": True,
            "variant": "fp16" if dtype == self._torch.float16 else None,
        }
        if _SD_CACHE_DIR:
            kwargs["cache_dir"] = _SD_CACHE_DIR

        # Load base SDXL pipeline
        pipe = StableDiffusionXLPipeline.from_pretrained(base_model, **kwargs)

        # Load LoRA weights
        if lora_repo:
            logger.info(f"[Diffusers] Loading SDXL LoRA from: {lora_repo}")
            try:
                pipe.load_lora_weights(lora_repo)
                logger.info(f"[Diffusers] SDXL LoRA loaded, fusing with scale {lora_scale}")
                pipe.fuse_lora(lora_scale=lora_scale)
                logger.info("[Diffusers] SDXL LoRA fused successfully")
            except Exception as e:
                logger.warning(f"[Diffusers] Could not load SDXL LoRA: {e}")

        return pipe

    def _load_hunyuan_pipeline(self, model_id: str):
        """Load a HunyuanImage 2.1 pipeline."""
        import gc
        from diffusers import HunyuanImagePipeline

        logger.info("[Diffusers] Loading HunyuanImage 2.1 pipeline...")
        logger.info("[Diffusers] Note: This model only supports 2K resolution (2048x2048)")

        # Aggressive CUDA cleanup before loading this heavy model
        if self._torch.cuda.is_available():
            logger.info("[Diffusers] Clearing CUDA memory before HunyuanImage load...")
            self._torch.cuda.empty_cache()
            self._torch.cuda.synchronize()
            gc.collect()
            # Reset CUDA context by initializing device
            try:
                self._torch.cuda.init()
                logger.info(f"[Diffusers] CUDA initialized, device: {self._torch.cuda.get_device_name(0)}")
            except Exception as e:
                logger.warning(f"[Diffusers] CUDA init warning: {e}")

        kwargs = {
            "torch_dtype": self._torch.bfloat16,
        }
        # HunyuanImage uses its own cache directory
        try:
            from wama.imager.utils.model_config import get_hunyuan_directory
            kwargs["cache_dir"] = str(get_hunyuan_directory())
            logger.info(f"[Diffusers] Loading HunyuanImage from cache: {kwargs['cache_dir']}")
        except ImportError:
            pass

        pipe = HunyuanImagePipeline.from_pretrained(model_id, **kwargs)

        # Use centralized MemoryManager to determine and apply optimal strategy
        try:
            from wama.model_manager.services.memory_manager import MemoryManager
            pipe = MemoryManager.apply_strategy_for_model(
                pipeline=pipe,
                model_type='hunyuan-image',
                device=self._device,
                headroom_gb=4.0  # HunyuanImage needs more headroom for 2K images
            )
        except ImportError:
            # Fallback if MemoryManager not available
            logger.warning("[Diffusers] MemoryManager not available, using sequential offload")
            try:
                pipe.enable_sequential_cpu_offload()
            except Exception:
                pipe = pipe.to(self._device)

        # Enable VAE tiling for large images
        try:
            pipe.vae.enable_tiling()
            logger.info("[Diffusers] VAE tiling enabled for HunyuanImage")
        except Exception as e:
            logger.debug(f"[Diffusers] VAE tiling not available: {e}")

        # Enable attention slicing for memory efficiency
        try:
            pipe.enable_attention_slicing("max")
            logger.info("[Diffusers] Attention slicing enabled for HunyuanImage")
        except Exception as e:
            logger.debug(f"[Diffusers] Attention slicing not available: {e}")

        return pipe

    def load(self, model_name: str = None) -> bool:
        """
        Load a Stable Diffusion, FLUX, or Hunyuan model.

        Supports:
        - Standard SD/SDXL models
        - FLUX models with optional LoRA
        - SDXL with LoRA (e.g., logo models)
        - HunyuanImage models

        Args:
            model_name: Model name (will be mapped to HuggingFace model ID).

        Returns:
            True if loaded successfully.
        """
        if model_name is None:
            model_name = "stable-diffusion-v1-5"

        # Get model info
        model_info = self._get_model_info(model_name)
        if model_info is None:
            # Fallback: use model_name as HuggingFace ID
            model_info = {"name": model_name, "hf_id": model_name, "pipeline": "sd"}

        model_id = model_info["hf_id"]
        pipeline_type = model_info.get("pipeline", "sd")
        model_type = model_info.get("model_type", "base")  # base, lora, full_finetune

        # Check if already loaded
        if self._loaded and self._current_model == model_id:
            logger.info(f"Model {model_id} already loaded")
            return True

        try:
            import torch
            from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler

            self._torch = torch
            self._device = self._get_device()

            logger.info(f"[Diffusers] Loading model: {model_info.get('name', model_name)}")
            logger.info(f"[Diffusers] HuggingFace ID: {model_id}")
            logger.info(f"[Diffusers] Pipeline type: {pipeline_type}")
            logger.info(f"[Diffusers] Model type: {model_type}")

            # Store model info for prompt preprocessing
            self._current_model_info = model_info

            # Unload previous model if any
            if self._pipe is not None:
                self.unload()

            # Load based on pipeline type
            if pipeline_type == "flux":
                # FLUX pipeline (with optional LoRA)
                self._pipe = self._load_flux_pipeline(model_info)
            elif pipeline_type == "hunyuan":
                # HunyuanImage 2.1 pipeline
                self._pipe = self._load_hunyuan_pipeline(model_id)
            elif pipeline_type == "sdxl":
                # SDXL pipeline - check if it uses LoRA
                if model_type == "lora":
                    self._pipe = self._load_sdxl_with_lora(model_info)
                else:
                    self._pipe = self._load_sdxl_pipeline(model_id)
            else:
                # Standard Stable Diffusion pipeline
                self._pipe = self._load_sd_pipeline(model_id)

            # Skip scheduler and device setup for models using CPU offload (handled in their loaders)
            if pipeline_type not in ("hunyuan", "flux"):
                # Use faster scheduler (with fallback if incompatible)
                try:
                    scheduler_config = dict(self._pipe.scheduler.config)
                    # Fix incompatible settings for some models
                    if scheduler_config.get('final_sigmas_type') == 'zero':
                        scheduler_config['final_sigmas_type'] = 'sigma_min'
                    self._pipe.scheduler = DPMSolverMultistepScheduler.from_config(scheduler_config)
                except Exception as scheduler_error:
                    logger.warning(f"Could not use DPMSolver scheduler, using default: {scheduler_error}")

                # Use centralized MemoryManager for optimal memory strategy
                model_type_key = 'sdxl' if pipeline_type == 'sdxl' else 'sd15'
                try:
                    from wama.model_manager.services.memory_manager import MemoryManager
                    self._pipe = MemoryManager.apply_strategy_for_model(
                        pipeline=self._pipe,
                        model_type=model_type_key,
                        device=self._device,
                        headroom_gb=2.0
                    )
                except ImportError:
                    # Fallback if MemoryManager not available
                    logger.warning("[Diffusers] MemoryManager not available, using direct GPU loading")
                    self._pipe = self._pipe.to(self._device)

                # Enable memory optimizations
                if self._device == "cuda":
                    try:
                        self._pipe.enable_attention_slicing()
                        logger.info("[Diffusers] Attention slicing enabled")
                    except Exception:
                        pass

                    # Try to enable xformers for better memory efficiency
                    try:
                        self._pipe.enable_xformers_memory_efficient_attention()
                        logger.info("[Diffusers] xformers memory efficient attention enabled")
                    except Exception as e:
                        logger.debug(f"[Diffusers] xformers not available: {e}")

                    # Log VRAM usage after loading
                    try:
                        allocated = self._torch.cuda.memory_allocated(0) / (1024 ** 3)
                        reserved = self._torch.cuda.memory_reserved(0) / (1024 ** 3)
                        logger.info(f"[Diffusers] GPU memory: {allocated:.1f}GB allocated, {reserved:.1f}GB reserved")
                    except Exception:
                        pass

            self._current_model = model_id
            self._loaded = True
            logger.info(f"[Diffusers] ✓ Model {model_id} loaded successfully on {self._device}")

            return True

        except Exception as e:
            logger.error(f"Failed to load model {model_id}: {e}")
            self._loaded = False
            return False

    def generate(
        self,
        params: GenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """
        Generate images using the loaded model.

        Supports txt2img and img2img modes based on params.generation_mode.

        Args:
            params: Generation parameters.
            progress_callback: Optional progress callback (0-100).

        Returns:
            GenerationResult with generated images.
        """
        logger.info(f"[Diffusers] >>> generate() called with model={params.model}, mode={params.generation_mode}")
        logger.info(f"[Diffusers]     prompt='{params.prompt[:80]}...', size={params.width}x{params.height}, steps={params.steps}")

        if not self._loaded or self._pipe is None:
            if not self.load(params.model):
                return GenerationResult(
                    success=False,
                    images=[],
                    error="Failed to load model"
                )

        # Check if we need to switch models
        expected_model = self.map_model_name(params.model)
        if self._current_model != expected_model:
            if not self.load(params.model):
                return GenerationResult(
                    success=False,
                    images=[],
                    error=f"Failed to load model {params.model}"
                )

        # Route to appropriate generation method based on mode
        if params.generation_mode in ('img2img', 'style2img') and params.reference_image:
            return self._generate_img2img(params, progress_callback)
        else:
            return self._generate_txt2img(params, progress_callback)

    def _generate_txt2img(
        self,
        params: GenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """Generate images from text prompt (standard txt2img)."""
        logger.info(f"[Diffusers] >>> _generate_txt2img() started")

        try:
            import torch
            from PIL import Image

            # Log GPU state at generation start
            if torch.cuda.is_available():
                try:
                    allocated = torch.cuda.memory_allocated(0) / (1024 ** 3)
                    reserved = torch.cuda.memory_reserved(0) / (1024 ** 3)
                    logger.info(f"[Diffusers] GPU at generation start: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved")
                except Exception:
                    pass

            # Check model pipeline type
            model_info = self._get_model_info(params.model)
            is_hunyuan = model_info and model_info.get("pipeline") == "hunyuan"
            is_flux = model_info and model_info.get("pipeline") == "flux"
            is_logo = model_info and model_info.get("category") == "logo"

            # For models with CPU offload, generator must be on CPU
            generator_device = "cpu" if (is_hunyuan or is_flux) else self._device

            # Setup generator for reproducibility
            generator = None
            seed_used = params.seed
            if seed_used is not None:
                generator = torch.Generator(device=generator_device).manual_seed(seed_used)
            else:
                # Generate a random seed for reproducibility
                seed_used = torch.randint(0, 2**32, (1,)).item()
                generator = torch.Generator(device=generator_device).manual_seed(seed_used)

            # Build prompt - prepend trigger words for LoRA models
            prompt = params.prompt
            negative_prompt = params.negative_prompt or ""

            # Prepend trigger words for logo/LoRA models
            if model_info:
                trigger_words = model_info.get('trigger_words', [])
                if trigger_words:
                    # Check if trigger words are already in prompt (case-insensitive)
                    prompt_lower = prompt.lower()
                    words_to_add = [w for w in trigger_words if w.lower() not in prompt_lower]
                    if words_to_add:
                        trigger_prefix = ', '.join(words_to_add)
                        prompt = f"{trigger_prefix}, {prompt}"
                        logger.info(f"[Diffusers] Added trigger words: {trigger_prefix}")

            generated_images: List[Image.Image] = []

            # Progress tracking
            def step_callback(pipe, step_index, timestep, callback_kwargs):
                if progress_callback:
                    # Calculate progress based on current image and step
                    total_steps = params.steps * params.num_images
                    current_step = len(generated_images) * params.steps + step_index
                    progress = int((current_step / total_steps) * 100)
                    progress_callback(progress)
                return callback_kwargs

            # Generate images
            for i in range(params.num_images):
                logger.info(f"Generating image {i+1}/{params.num_images}")

                if progress_callback:
                    base_progress = int((i / params.num_images) * 100)
                    progress_callback(base_progress)

                # Aggressive CUDA cache clearing before generation
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    gc.collect()
                    # Log available memory
                    free_mem = torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated(0)
                    logger.info(f"[Diffusers] GPU memory available: {free_mem / 1024**3:.1f}GB")

                # Generate single image
                with torch.inference_mode():
                    if is_hunyuan:
                        # HunyuanImage - use requested resolution but ensure minimum 1024
                        # Recommended: 2048x2048, 2048x1152 (16:9), 1152x2048 (9:16)
                        width = params.width
                        height = params.height

                        # Ensure minimum size (1024 recommended for quality)
                        min_size = model_info.get("min_resolution", 1024)
                        if width < min_size:
                            logger.warning(f"[Diffusers] Width {width} below minimum {min_size}, adjusting")
                            width = min_size
                        if height < min_size:
                            logger.warning(f"[Diffusers] Height {height} below minimum {min_size}, adjusting")
                            height = min_size

                        # Ensure dimensions are multiples of 8 (required by diffusion models)
                        width = (width // 8) * 8
                        height = (height // 8) * 8

                        logger.info(f"[Diffusers] HunyuanImage generation parameters:")
                        logger.info(f"[Diffusers]   Resolution: {width}x{height}")
                        logger.info(f"[Diffusers]   Steps: {params.steps}")
                        logger.info(f"[Diffusers]   Guidance: {params.guidance_scale}")
                        logger.info(f"[Diffusers]   Seed: {seed_used}")
                        logger.info(f"[Diffusers]   Prompt: {prompt[:100]}...")

                        try:
                            # HunyuanImage uses distilled_guidance_scale instead of guidance_scale
                            result = self._pipe(
                                prompt=prompt,
                                negative_prompt=negative_prompt if negative_prompt else None,
                                height=height,
                                width=width,
                                num_inference_steps=params.steps,
                                distilled_guidance_scale=params.guidance_scale,
                                generator=generator,
                                callback_on_step_end=step_callback,
                            )
                            logger.info(f"[Diffusers] HunyuanImage generation complete, result type: {type(result)}")
                        except Exception as gen_error:
                            import traceback
                            logger.error(f"[Diffusers] HunyuanImage pipeline error: {type(gen_error).__name__}: {gen_error}")
                            logger.error(f"[Diffusers] Pipeline traceback:\n{traceback.format_exc()}")
                            raise
                    elif is_flux:
                        # FLUX generation - different parameters than SD/SDXL
                        width = params.width
                        height = params.height

                        # Ensure minimum size (512 recommended for FLUX)
                        min_size = model_info.get("min_resolution", 512)
                        max_size = model_info.get("max_resolution", 1024)
                        if width < min_size:
                            logger.warning(f"[Diffusers] Width {width} below minimum {min_size}, adjusting")
                            width = min_size
                        if height < min_size:
                            logger.warning(f"[Diffusers] Height {height} below minimum {min_size}, adjusting")
                            height = min_size
                        if width > max_size:
                            logger.warning(f"[Diffusers] Width {width} above maximum {max_size}, adjusting")
                            width = max_size
                        if height > max_size:
                            logger.warning(f"[Diffusers] Height {height} above maximum {max_size}, adjusting")
                            height = max_size

                        # Ensure dimensions are multiples of 8
                        width = (width // 8) * 8
                        height = (height // 8) * 8

                        logger.info(f"[Diffusers] FLUX generation parameters:")
                        logger.info(f"[Diffusers]   Resolution: {width}x{height}")
                        logger.info(f"[Diffusers]   Steps: {params.steps}")
                        logger.info(f"[Diffusers]   Guidance: {params.guidance_scale}")
                        logger.info(f"[Diffusers]   Seed: {seed_used}")
                        logger.info(f"[Diffusers]   Prompt: {prompt[:100]}...")

                        try:
                            # FLUX uses guidance_scale (not distilled_guidance_scale)
                            # FLUX does NOT support negative_prompt natively
                            result = self._pipe(
                                prompt=prompt,
                                height=height,
                                width=width,
                                num_inference_steps=params.steps,
                                guidance_scale=params.guidance_scale,
                                generator=generator,
                                callback_on_step_end=step_callback,
                            )
                            logger.info(f"[Diffusers] FLUX generation complete, result type: {type(result)}")
                        except Exception as gen_error:
                            import traceback
                            logger.error(f"[Diffusers] FLUX pipeline error: {type(gen_error).__name__}: {gen_error}")
                            logger.error(f"[Diffusers] Pipeline traceback:\n{traceback.format_exc()}")
                            raise
                    else:
                        # Standard SD/SDXL generation
                        result = self._pipe(
                            prompt=prompt,
                            negative_prompt=negative_prompt if negative_prompt else None,
                            width=params.width,
                            height=params.height,
                            num_inference_steps=params.steps,
                            guidance_scale=params.guidance_scale,
                            generator=generator,
                            num_images_per_prompt=1,
                            callback_on_step_end=step_callback,
                        )

                if result.images:
                    img = result.images[0]

                    # Apply upscaling if requested
                    if params.upscale:
                        img = self._upscale_image(img)

                    generated_images.append(img)

                # Create new generator with incremented seed for next image
                if params.num_images > 1:
                    generator = torch.Generator(device=generator_device).manual_seed(seed_used + i + 1)

            if progress_callback:
                progress_callback(100)

            return GenerationResult(
                success=True,
                images=generated_images,
                seed_used=seed_used
            )

        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {str(e)}"
            error_traceback = traceback.format_exc()
            logger.error(f"[Diffusers] Generation failed: {error_msg}")
            logger.error(f"[Diffusers] Full traceback:\n{error_traceback}")
            return GenerationResult(
                success=False,
                images=[],
                error=error_msg
            )

    def _generate_img2img(
        self,
        params: GenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """Generate images from reference image (img2img/style transfer)."""
        try:
            import torch
            from PIL import Image

            logger.info(f"Img2Img generation with reference: {params.reference_image}")

            # Load img2img pipeline if needed
            if self._pipe_img2img is None:
                self._load_img2img_pipeline()

            if self._pipe_img2img is None:
                return GenerationResult(
                    success=False,
                    images=[],
                    error="Failed to load img2img pipeline"
                )

            # Load and prepare reference image
            init_image = Image.open(params.reference_image).convert("RGB")
            init_image = init_image.resize((params.width, params.height), Image.LANCZOS)
            logger.info(f"Reference image resized to {params.width}x{params.height}")

            # Setup generator for reproducibility
            seed_used = params.seed
            if seed_used is None:
                seed_used = torch.randint(0, 2**32, (1,)).item()
            generator = torch.Generator(device=self._device).manual_seed(seed_used)

            # Build prompt
            prompt = params.prompt
            negative_prompt = params.negative_prompt or ""

            # Calculate strength (diffusers uses inverse of our image_strength)
            # Our image_strength: 0=ignore image, 1=copy exactly
            # Diffusers strength: 0=copy exactly, 1=ignore image
            strength = 1.0 - params.image_strength

            # Clamp strength to valid range (0.0-1.0)
            strength = max(0.0, min(1.0, strength))

            generated_images: List[Image.Image] = []

            # Progress tracking
            def step_callback(pipe, step_index, timestep, callback_kwargs):
                if progress_callback:
                    total_steps = int(params.steps * strength) * params.num_images
                    current_step = len(generated_images) * int(params.steps * strength) + step_index
                    if total_steps > 0:
                        progress = int((current_step / total_steps) * 100)
                        progress_callback(progress)
                return callback_kwargs

            # Generate images
            for i in range(params.num_images):
                logger.info(f"Generating img2img {i+1}/{params.num_images} (strength={strength:.2f})")

                if progress_callback:
                    base_progress = int((i / params.num_images) * 100)
                    progress_callback(base_progress)

                # Generate single image
                with torch.inference_mode():
                    result = self._pipe_img2img(
                        prompt=prompt,
                        negative_prompt=negative_prompt if negative_prompt else None,
                        image=init_image,
                        strength=strength,
                        num_inference_steps=params.steps,
                        guidance_scale=params.guidance_scale,
                        generator=generator,
                        num_images_per_prompt=1,
                        callback_on_step_end=step_callback,
                    )

                if result.images:
                    img = result.images[0]

                    # Apply upscaling if requested
                    if params.upscale:
                        img = self._upscale_image(img)

                    generated_images.append(img)

                # Create new generator with incremented seed for next image
                if params.num_images > 1:
                    generator = torch.Generator(device=self._device).manual_seed(seed_used + i + 1)

            if progress_callback:
                progress_callback(100)

            return GenerationResult(
                success=True,
                images=generated_images,
                seed_used=seed_used
            )

        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {str(e)}"
            error_traceback = traceback.format_exc()
            logger.error(f"[Diffusers] Img2Img generation failed: {error_msg}")
            logger.error(f"[Diffusers] Full traceback:\n{error_traceback}")
            return GenerationResult(
                success=False,
                images=[],
                error=error_msg
            )

    def _load_img2img_pipeline(self) -> bool:
        """Load the img2img pipeline based on current model."""
        try:
            import torch
            from diffusers import StableDiffusionImg2ImgPipeline, DPMSolverMultistepScheduler

            model_id = self._current_model
            is_xl = "xl" in model_id.lower()

            logger.info(f"Loading img2img pipeline for {model_id}...")

            # Determine dtype based on device
            if self._device == "cuda":
                dtype = torch.float16
            else:
                dtype = torch.float32

            if is_xl:
                from diffusers import StableDiffusionXLImg2ImgPipeline
                kwargs = {
                    "torch_dtype": dtype,
                    "use_safetensors": True,
                    "variant": "fp16" if dtype == torch.float16 else None,
                }
                if _SD_CACHE_DIR:
                    kwargs["cache_dir"] = _SD_CACHE_DIR
                self._pipe_img2img = StableDiffusionXLImg2ImgPipeline.from_pretrained(model_id, **kwargs)
            else:
                kwargs = {
                    "torch_dtype": dtype,
                    "use_safetensors": True,
                    "safety_checker": None,
                }
                if _SD_CACHE_DIR:
                    kwargs["cache_dir"] = _SD_CACHE_DIR
                self._pipe_img2img = StableDiffusionImg2ImgPipeline.from_pretrained(model_id, **kwargs)

            # Use faster scheduler
            try:
                scheduler_config = dict(self._pipe_img2img.scheduler.config)
                if scheduler_config.get('final_sigmas_type') == 'zero':
                    scheduler_config['final_sigmas_type'] = 'sigma_min'
                self._pipe_img2img.scheduler = DPMSolverMultistepScheduler.from_config(scheduler_config)
            except Exception as scheduler_error:
                logger.warning(f"Could not use DPMSolver scheduler for img2img: {scheduler_error}")

            # Move to device
            self._pipe_img2img = self._pipe_img2img.to(self._device)

            # Enable memory optimizations
            if self._device == "cuda":
                try:
                    self._pipe_img2img.enable_attention_slicing()
                except Exception:
                    pass
                try:
                    self._pipe_img2img.enable_xformers_memory_efficient_attention()
                except Exception:
                    pass

            logger.info("Img2Img pipeline loaded successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to load img2img pipeline: {e}")
            self._pipe_img2img = None
            return False

    def _upscale_image(self, image, scale: int = 2):
        """
        Upscale an image using a simple method.

        For better results, consider using Real-ESRGAN or similar.
        """
        from PIL import Image

        new_size = (image.width * scale, image.height * scale)
        return image.resize(new_size, Image.LANCZOS)

    def unload(self) -> None:
        """Unload the model from memory."""
        if self._pipe is not None:
            del self._pipe
            self._pipe = None

        self._current_model = None
        self._loaded = False

        # Force garbage collection
        gc.collect()

        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

        logger.info("Model unloaded from memory")
