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


# Module-level pipeline cache — persists across Celery tasks within the same worker process.
# Without this, each task reloads from_pretrained() and WSL2 re-swaps 23 GB to page file.
# Keyed by model_name (e.g. 'flux-lora-logo-design'). Only keeps the last loaded model.
_PIPELINE_CACHE: dict = {}  # {model_name: pipeline}


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
        "deliberate-v6": {
            "name": "Deliberate v6",
            "hf_id": "XpucT/Deliberate",
            "single_file": "Deliberate_v6.safetensors",
            "description": "Réaliste/Artistique - 4GB VRAM - Très détaillé, tokens: mj, cinematic",
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

        # Shakker-Labs FLUX Logo Design LoRA — #1 open-source logo model (2025-2026)
        # Replaces obsolete logo-redmond-v2 (SDXL 2023) and amazing-logos-v2 (SD1.5 2023).
        # guidance_scale: 3.5 (FLUX rectified flow — NOT 7.5–20 like SD)
        # steps: 24 recommended
        "flux-lora-logo-design": {
            "name": "FLUX Logo Design LoRA",
            "hf_id": "Shakker-Labs/FLUX.1-dev-LoRA-Logo-Design",
            "base_model": "black-forest-labs/FLUX.1-dev",
            # Max 768 px: at 1024×1024 the transformer (23 GB) + attention activations
            # (4096 tokens) exceed the 24 GB VRAM budget causing a silent CUDA OOM.
            # 768×768 (2304 tokens) is well within budget and still high-quality.
            "description": "Logo Design LoRA — #1 open-source, logos professionnels, max 768px (16GB VRAM)",
            "vram": "16GB",
            "pipeline": "flux",
            "model_type": "lora",
            "category": "logo",
            "trigger_words": ["wablogo", "logo", "Minimalist"],
            "lora_scale": 0.8,
            "default_guidance_scale": 3.5,
            "default_steps": 24,
            "min_resolution": 512,
            "max_resolution": 768,
            "recommended_resolutions": ["768x768", "768x512", "512x768"],
        },

        # =================================================================
        # FLUX.2 KLEIN (Black Forest Labs) — Apache 2.0
        # Routed to flux2_klein_backend at generation time — listed here
        # so they appear in the UI model selector.
        # =================================================================

        "flux2-klein-4b": {
            "name": "FLUX.2 Klein 4B",
            "hf_id": "black-forest-labs/FLUX.2-klein-4B",
            "description": "Ultra-rapide (<1s/image) - 13GB VRAM - 4 steps distillé - Apache 2.0",
            "vram": "13GB",
            "pipeline": "flux2_klein",
            "min_resolution": 512,
            "max_resolution": 2048,
            "recommended_resolutions": ["1024x1024", "1344x768", "768x1344", "1920x1088"],
        },

        # =================================================================
        # QWEN IMAGE MODELS (Alibaba Cloud)
        # Routed to qwen_image_backend at generation time — listed here
        # so they appear in the UI model selector.
        # =================================================================

        "qwen-image-2": {
            "name": "Qwen Image 2 (20B)",
            "hf_id": "Qwen/Qwen-Image-2512",
            "description": "#1 open-source (AI Arena) - 16GB VRAM - 2K natif, text rendering",
            "vram": "16GB",
            "pipeline": "qwen_image",
            "min_resolution": 512,
            "max_resolution": 2048,
            "recommended_resolutions": ["1024x1024", "2048x2048", "2048x1152", "1152x2048"],
        },
        "qwen-image-edit": {
            "name": "Qwen Image Edit",
            "hf_id": "Qwen/Qwen-Image-Edit-2511",
            "description": "Image editing - 12GB VRAM - multi-image, character consistency, 2K",
            "vram": "12GB",
            "pipeline": "qwen_image",
            "min_resolution": 512,
            "max_resolution": 2048,
            "recommended_resolutions": ["1024x1024", "2048x2048", "2048x1152", "1152x2048"],
        },
    }

    # Backward-compatibility aliases for renamed models
    _MODEL_ALIASES = {
        "deliberate-v2": "deliberate-v6",
    }

    @classmethod
    def _get_model_info(cls, model_name: str) -> dict:
        """Get model info, supporting both old tuple and new dict formats."""
        # Check aliases for renamed models
        resolved_name = cls._MODEL_ALIASES.get(model_name, model_name)
        if resolved_name != model_name:
            logger.info(f"[Diffusers] Model alias: {model_name} -> {resolved_name}")

        model_info = cls.SUPPORTED_MODELS.get(resolved_name)
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

    def _load_sd_pipeline(self, model_id: str, model_info: dict = None):
        """Load a standard Stable Diffusion pipeline."""
        from diffusers import StableDiffusionPipeline
        from wama.model_manager.services.memory_manager import MemoryManager

        dtype = self._torch.float16 if self._device == "cuda" else self._torch.float32

        # Single-file loading (e.g., XpucT/Deliberate with single safetensors)
        single_file = model_info.get("single_file") if model_info else None
        if single_file:
            logger.info(f"[Diffusers] Loading single-file model: {model_id}/{single_file}")
            kwargs = {
                "torch_dtype": dtype,
                "safety_checker": None,
            }
            return MemoryManager.load_single_file_pipeline(
                StableDiffusionPipeline, model_id, single_file,
                cache_dir=_SD_CACHE_DIR, **kwargs
            )

        # Standard diffusers-format loading
        kwargs = {
            "torch_dtype": dtype,
            "use_safetensors": True,
            "safety_checker": None,
        }
        if _SD_CACHE_DIR:
            kwargs["cache_dir"] = _SD_CACHE_DIR
            logger.info(f"[Diffusers] Loading from cache: {_SD_CACHE_DIR}")

        return MemoryManager.load_pipeline(StableDiffusionPipeline, model_id, **kwargs)

    def _load_sdxl_pipeline(self, model_id: str):
        """Load a Stable Diffusion XL pipeline."""
        from diffusers import StableDiffusionXLPipeline
        from wama.model_manager.services.memory_manager import MemoryManager

        dtype = self._torch.float16 if self._device == "cuda" else self._torch.float32

        kwargs = {
            "torch_dtype": dtype,
            "use_safetensors": True,
            "variant": "fp16" if dtype == self._torch.float16 else None,
        }
        if _SD_CACHE_DIR:
            kwargs["cache_dir"] = _SD_CACHE_DIR
            logger.info(f"[Diffusers] Loading SDXL from cache: {_SD_CACHE_DIR}")

        return MemoryManager.load_pipeline(StableDiffusionXLPipeline, model_id, **kwargs)

    def _get_vram_gb(self) -> float:
        """Get total GPU VRAM in GB."""
        if self._torch and self._torch.cuda.is_available():
            return self._torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        return 0.0

    def _get_flux_strategy(self) -> dict:
        """
        Determine best FLUX loading strategy based on available RAM and VRAM.

        FLUX transformer sizes:
          bfloat16 : 23 GB  → stays on CPU, MODEL_OFFLOAD to GPU per step (slow if RAM swaps)
          8-bit    : 11.5 GB → loaded directly to GPU, T5 (9.5 GB) on CPU via offload hooks
          4-bit    : 5.75 GB → loaded directly to GPU, T5 on CPU

        With 32 GB RAM / WSL2 ~16 GB: bfloat16 causes swap → 13 min/step.
        8-bit on GPU eliminates the swap issue entirely.
        """
        vram_gb = self._get_vram_gb()

        # Check bitsandbytes availability
        bnb_available = False
        try:
            import bitsandbytes  # noqa
            bnb_available = True
        except ImportError:
            pass

        # Check available system RAM
        free_ram_gb = 0.0
        try:
            import psutil
            free_ram_gb = psutil.virtual_memory().available / (1024 ** 3)
        except ImportError:
            # psutil unavailable: assume low RAM → prefer quantization if possible
            free_ram_gb = 0.0

        logger.info(
            f"[Diffusers] FLUX resource check: free_ram={free_ram_gb:.1f}GB, "
            f"vram={vram_gb:.0f}GB, bitsandbytes={bnb_available}"
        )

        # Strategy 1 — bfloat16 + MODEL_OFFLOAD
        # Requires ~27 GB free RAM so the transformer stays in physical RAM without swapping.
        if free_ram_gb >= 27:
            logger.info("[Diffusers] Strategy: bfloat16 + MODEL_OFFLOAD (RAM sufficient)")
            return {'quantization': None, 'label': 'bfloat16+offload'}

        # Strategy 2 — 8-bit transformer on GPU
        # Transformer: 11.5 GB on GPU. T5 (9.5 GB) stays on CPU via offload hooks.
        # Peak VRAM during encoding: 11.5 + 9.5 + 0.5 ≈ 21.5 GB → fits in 24 GB.
        if bnb_available and vram_gb >= 22:
            logger.info("[Diffusers] Strategy: 8-bit transformer on GPU (low RAM detected)")
            return {'quantization': '8bit', 'label': '8bit+gpu'}

        # Strategy 3 — 4-bit transformer on GPU
        # Transformer: 5.75 GB. T5 on CPU. Peak VRAM ≈ 15.75 GB.
        if bnb_available and vram_gb >= 16:
            logger.info("[Diffusers] Strategy: 4-bit transformer on GPU (very low RAM)")
            return {'quantization': '4bit', 'label': '4bit+gpu'}

        # Fallback — bfloat16 + MODEL_OFFLOAD (may be slow if RAM is insufficient)
        logger.warning(
            "[Diffusers] Strategy: bfloat16 + MODEL_OFFLOAD (fallback — "
            "bitsandbytes unavailable or VRAM too low). May be slow due to swap."
        )
        return {'quantization': None, 'label': 'bfloat16+offload(fallback)'}

    def _load_flux_quantized(self, base_model: str, quant_bits: str, cache_dir: str):
        """
        Load FLUX with quantized transformer directly onto GPU via bitsandbytes.
        Eliminates CPU↔GPU transfers per denoising step and avoids WSL2 RAM swap.

        After loading, text encoders (T5 9.5 GB, CLIP 0.5 GB) are offloaded to CPU
        via enable_model_cpu_offload() hooks — they fit in WSL2 RAM without swapping.
        """
        from diffusers import FluxPipeline, FluxTransformer2DModel, BitsAndBytesConfig

        if quant_bits == '8bit':
            bnb_config = BitsAndBytesConfig(load_in_8bit=True)
            logger.info("[Diffusers] Loading FLUX transformer in 8-bit (~11.5 GB VRAM)...")
        else:  # 4bit
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=self._torch.bfloat16,
            )
            logger.info("[Diffusers] Loading FLUX transformer in 4-bit (~5.75 GB VRAM)...")

        kwargs = {}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir

        # Load quantized transformer — lands directly on GPU (bitsandbytes requirement)
        transformer = FluxTransformer2DModel.from_pretrained(
            base_model,
            subfolder="transformer",
            quantization_config=bnb_config,
            torch_dtype=self._torch.bfloat16,
            **kwargs,
        )
        alloc = self._torch.cuda.memory_allocated(0) / 1024 ** 3
        logger.info(f"[Diffusers] Transformer loaded: {alloc:.1f}GB GPU allocated")

        # Load full pipeline with the pre-quantized transformer;
        # remaining components (T5, CLIP, VAE, scheduler) stay in bfloat16 on CPU.
        logger.info("[Diffusers] Loading pipeline components (bfloat16)...")
        pipe = FluxPipeline.from_pretrained(
            base_model,
            transformer=transformer,
            torch_dtype=self._torch.bfloat16,
            **kwargs,
        )

        return pipe

    def _apply_flux_lora(self, pipe, lora_repo: str, lora_scale: float):
        """Load LoRA weights onto a FLUX pipeline (works with both bfloat16 and quantized)."""
        import os as _os
        lora_cache = _LOGO_CACHE_DIR or _FLUX_CACHE_DIR
        if lora_cache:
            _os.environ['HF_HUB_CACHE'] = lora_cache
            _os.environ['HUGGINGFACE_HUB_CACHE'] = lora_cache
        pipe.load_lora_weights(lora_repo, adapter_name="lora_adapter", cache_dir=lora_cache)
        pipe.set_adapters(["lora_adapter"], adapter_weights=[lora_scale])
        logger.info(f"[Diffusers] LoRA loaded with scale {lora_scale}")

    def _load_flux_pipeline(self, model_info: dict):
        """
        Load a FLUX pipeline with dynamic strategy selection based on available RAM/VRAM.

        Strategies (auto-selected):
          bfloat16+offload : 23 GB in RAM + MODEL_OFFLOAD  (requires ~27 GB free RAM)
          8bit+gpu         : 11.5 GB transformer on GPU, T5 on CPU via offload hooks
          4bit+gpu         :  5.75 GB transformer on GPU, T5 on CPU via offload hooks
        """
        import gc
        from diffusers import FluxPipeline

        base_model = model_info.get('base_model', 'black-forest-labs/FLUX.1-dev')
        lora_repo = model_info.get('hf_id')
        model_type = model_info.get('model_type', 'base')
        lora_scale = model_info.get('lora_scale', 0.8)

        logger.info(f"[Diffusers] Loading FLUX pipeline: {base_model}")

        # CUDA cleanup before loading
        if self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
            self._torch.cuda.synchronize()
            gc.collect()

        strategy = self._get_flux_strategy()

        if strategy['quantization'] in ('8bit', '4bit'):
            # ── Quantized path: transformer goes directly to GPU ──────────────
            pipe = self._load_flux_quantized(base_model, strategy['quantization'], _FLUX_CACHE_DIR)

            # Load LoRA on quantized pipeline (adapter weights are bfloat16, compatible)
            if model_type == 'lora' and lora_repo:
                logger.info(f"[Diffusers] Loading LoRA on quantized pipeline: {lora_repo}")
                try:
                    self._apply_flux_lora(pipe, lora_repo, lora_scale)
                except Exception as e:
                    logger.warning(f"[Diffusers] LoRA on quantized model failed: {e}")

            # Offload text encoders to CPU via hooks (transformer stays on GPU — quantized).
            # T5 (9.5 GB) + CLIP (0.5 GB) fit in WSL2 RAM without swapping.
            logger.info("[Diffusers] Applying CPU offload for text encoders...")
            try:
                pipe.enable_model_cpu_offload()
                logger.info("[Diffusers] CPU offload hooks applied (text encoders → CPU)")
            except Exception as e:
                logger.warning(f"[Diffusers] enable_model_cpu_offload failed: {e}. Pipeline stays as-is.")

        else:
            # ── bfloat16 path: full model on CPU, MODEL_OFFLOAD to GPU ────────
            kwargs = {"torch_dtype": self._torch.bfloat16}
            if _FLUX_CACHE_DIR:
                kwargs["cache_dir"] = _FLUX_CACHE_DIR
                logger.info(f"[Diffusers] Loading FLUX bfloat16 from: {_FLUX_CACHE_DIR}")

            pipe = FluxPipeline.from_pretrained(base_model, **kwargs)

            # Load LoRA before applying memory strategy (model still on CPU)
            if model_type == 'lora' and lora_repo:
                logger.info(f"[Diffusers] Loading LoRA (bfloat16 path): {lora_repo}")
                try:
                    self._apply_flux_lora(pipe, lora_repo, lora_scale)
                except Exception as e:
                    logger.warning(f"[Diffusers] Could not load LoRA: {e}")

            # Apply MODEL_OFFLOAD via MemoryManager
            try:
                from wama.model_manager.services.memory_manager import MemoryManager
                pipe = MemoryManager.apply_strategy_for_model(
                    pipeline=pipe, model_type='flux',
                    device=self._device, headroom_gb=4.0
                )
            except ImportError:
                logger.warning("[Diffusers] MemoryManager not available, using direct GPU loading")
                pipe = pipe.to(self._device)

        # VAE optimizations (apply regardless of strategy)
        try:
            pipe.vae.enable_slicing()
            logger.info("[Diffusers] VAE slicing enabled")
        except Exception:
            pass
        try:
            pipe.vae.enable_tiling()
            logger.info("[Diffusers] VAE tiling enabled")
        except Exception:
            pass

        alloc = self._torch.cuda.memory_allocated(0) / 1024 ** 3
        resrv = self._torch.cuda.memory_reserved(0) / 1024 ** 3
        logger.info(f"[Diffusers] FLUX ready [{strategy['label']}] — GPU: {alloc:.1f}GB alloc / {resrv:.1f}GB reserved")

        return pipe

    def _load_sdxl_with_lora(self, model_info: dict):
        """
        Load SDXL pipeline with LoRA weights.

        Args:
            model_info: Model configuration dictionary containing base_model, hf_id, etc.
        """
        from diffusers import StableDiffusionXLPipeline
        from wama.model_manager.services.memory_manager import MemoryManager

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
        pipe = MemoryManager.load_pipeline(StableDiffusionXLPipeline, base_model, **kwargs)

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

        # Check if already loaded on this instance
        if self._loaded and self._current_model == model_id:
            logger.info(f"Model {model_id} already loaded")
            return True

        # Check module-level cache (survives across Celery tasks in same worker process).
        # Avoids re-reading 23 GB from /mnt/d/ and re-swapping through WSL2 page file.
        global _PIPELINE_CACHE
        if model_name in _PIPELINE_CACHE:
            logger.info(f"[Diffusers] Cache hit for '{model_name}' — reusing pipeline (skipping from_pretrained)")
            self._pipe = _PIPELINE_CACHE[model_name]
            self._current_model = model_id
            self._current_model_info = model_info
            self._loaded = True
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
                self._pipe = self._load_sd_pipeline(model_id, model_info)

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

            # Evict any other cached model to avoid holding multiple large models in RAM,
            # then store this pipeline for reuse across future Celery tasks.
            for old_name in list(_PIPELINE_CACHE.keys()):
                if old_name != model_name:
                    logger.info(f"[Diffusers] Evicting '{old_name}' from pipeline cache to free RAM")
                    del _PIPELINE_CACHE[old_name]
                    gc.collect()
            _PIPELINE_CACHE[model_name] = self._pipe
            logger.info(f"[Diffusers] Pipeline '{model_name}' stored in module cache for next task")

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

            # FLUX: generate images ONE AT A TIME.
            # Batch mode (num_images_per_prompt > 1) causes WSL2 crashes: after 30
            # denoising steps the 23 GB transformer may still occupy GPU when VAE
            # decode starts; clearing cache between calls is the safest fix.
            if is_flux:
                width = params.width
                height = params.height
                min_size = model_info.get("min_resolution", 512) if model_info else 512
                max_size = model_info.get("max_resolution", 1024) if model_info else 1024
                width  = max(min_size, min(max_size, (width  // 8) * 8))
                height = max(min_size, min(max_size, (height // 8) * 8))

                logger.info(f"[Diffusers] FLUX generation: {params.num_images} image(s) one-at-a-time, {width}x{height}, steps={params.steps}")
                logger.info(f"[Diffusers]   Guidance: {params.guidance_scale}, Seed base: {seed_used}")
                logger.info(f"[Diffusers]   Prompt: {prompt[:100]}...")

                for img_idx in range(params.num_images):
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()
                        gc.collect()
                        free_mem = torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated(0)
                        logger.info(f"[Diffusers] GPU memory before image {img_idx+1}: {free_mem / 1024**3:.1f}GB free")

                    # Sequential seeds for reproducibility across images
                    img_generator = torch.Generator(device=generator_device).manual_seed(seed_used + img_idx)

                    # Progress: map this image's steps into the overall 0-95% range
                    def flux_step_callback(pipe, step_index, timestep, callback_kwargs, _idx=img_idx):
                        if progress_callback:
                            img_progress = (_idx * params.steps + step_index) / (params.num_images * params.steps)
                            progress_callback(int(img_progress * 95))
                        return callback_kwargs

                    logger.info(f"[Diffusers] Generating image {img_idx+1}/{params.num_images}")
                    try:
                        with torch.inference_mode():
                            result = self._pipe(
                                prompt=prompt,
                                height=height,
                                width=width,
                                num_inference_steps=params.steps,
                                guidance_scale=params.guidance_scale,
                                num_images_per_prompt=1,
                                generator=img_generator,
                                callback_on_step_end=flux_step_callback,
                            )
                        img = result.images[0]

                        if torch.cuda.is_available():
                            alloc = torch.cuda.memory_allocated(0) / 1024**3
                            resrv = torch.cuda.memory_reserved(0) / 1024**3
                            logger.info(f"[Diffusers] After image {img_idx+1}: allocated={alloc:.2f}GB reserved={resrv:.2f}GB")

                        if params.upscale:
                            img = self._upscale_image(img)
                        generated_images.append(img)
                        logger.info(f"[Diffusers] Image {img_idx+1}/{params.num_images} complete ({img.size[0]}x{img.size[1]})")
                    except Exception as gen_error:
                        import traceback
                        logger.error(f"[Diffusers] FLUX error on image {img_idx+1}: {type(gen_error).__name__}: {gen_error}")
                        logger.error(f"[Diffusers] Traceback:\n{traceback.format_exc()}")
                        raise

                if progress_callback:
                    progress_callback(100)

                return GenerationResult(success=True, images=generated_images, seed_used=seed_used)

            # Non-FLUX: generate images one at a time (SD / SDXL / HunyuanImage)
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

            from wama.model_manager.services.memory_manager import MemoryManager

            if is_xl:
                from diffusers import StableDiffusionXLImg2ImgPipeline
                kwargs = {
                    "torch_dtype": dtype,
                    "use_safetensors": True,
                    "variant": "fp16" if dtype == torch.float16 else None,
                }
                if _SD_CACHE_DIR:
                    kwargs["cache_dir"] = _SD_CACHE_DIR
                self._pipe_img2img = MemoryManager.load_pipeline(StableDiffusionXLImg2ImgPipeline, model_id, **kwargs)
            else:
                kwargs = {
                    "torch_dtype": dtype,
                    "use_safetensors": True,
                    "safety_checker": None,
                }
                if _SD_CACHE_DIR:
                    kwargs["cache_dir"] = _SD_CACHE_DIR
                self._pipe_img2img = MemoryManager.load_pipeline(StableDiffusionImg2ImgPipeline, model_id, **kwargs)

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
