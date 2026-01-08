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


class DiffusersBackend(ImageGenerationBackend):
    """
    Image generation backend using Hugging Face Diffusers.

    This is the recommended backend for Python 3.12+ as it doesn't
    have the compatibility issues that ImaginAiry has.
    """

    name = "diffusers"
    display_name = "Diffusers (Hugging Face)"

    # Map generic model names to Hugging Face model IDs
    # Format: (display_name, hf_model_id, description, vram_required)
    SUPPORTED_MODELS = {
        # HunyuanImage 2.1 - High quality 2K images (NEW)
        "hunyuan-image-2.1": {
            "name": "HunyuanImage 2.1",
            "hf_id": "hunyuanvideo-community/HunyuanImage-2.1-Diffusers",
            "description": "Génération 2K (2048px) - 24GB VRAM - Qualité exceptionnelle",
            "vram": "24GB",
            "pipeline": "hunyuan",
            "min_resolution": 2048,
        },

        # Stable Diffusion models
        "stable-diffusion-v1-5": {
            "name": "Stable Diffusion 1.5",
            "hf_id": "stable-diffusion-v1-5/stable-diffusion-v1-5",
            "description": "Modèle classique - 4GB VRAM - Rapide et polyvalent",
            "vram": "4GB",
            "pipeline": "sd",
        },
        "stable-diffusion-2-1": {
            "name": "Stable Diffusion 2.1",
            "hf_id": "stabilityai/stable-diffusion-2-1",
            "description": "Version améliorée - 6GB VRAM - Meilleure cohérence",
            "vram": "6GB",
            "pipeline": "sd",
        },
        "stable-diffusion-xl": {
            "name": "Stable Diffusion XL",
            "hf_id": "stabilityai/stable-diffusion-xl-base-1.0",
            "description": "Haute résolution - 10GB VRAM - Images détaillées",
            "vram": "10GB",
            "pipeline": "sdxl",
        },

        # Artistic models
        "openjourney-v4": {
            "name": "OpenJourney v4",
            "hf_id": "prompthero/openjourney-v4",
            "description": "Style Midjourney - 4GB VRAM - Art créatif",
            "vram": "4GB",
            "pipeline": "sd",
        },
        "dreamlike-art-2": {
            "name": "Dreamlike Art 2.0",
            "hf_id": "dreamlike-art/dreamlike-diffusion-1.0",
            "description": "Style artistique - 4GB VRAM - Images oniriques",
            "vram": "4GB",
            "pipeline": "sd",
        },
        "dreamshaper-8": {
            "name": "DreamShaper 8",
            "hf_id": "Lykon/DreamShaper",
            "description": "Polyvalent - 4GB VRAM - Excellent rapport qualité/vitesse",
            "vram": "4GB",
            "pipeline": "sd",
        },
        "deliberate-v2": {
            "name": "Deliberate v2",
            "hf_id": "XpucT/Deliberate",
            "description": "Réaliste/Artistique - 4GB VRAM - Très détaillé",
            "vram": "4GB",
            "pipeline": "sd",
        },

        # Realistic models
        "realistic-vision-v5": {
            "name": "Realistic Vision V5",
            "hf_id": "SG161222/Realistic_Vision_V5.1_noVAE",
            "description": "Photoréaliste - 4GB VRAM - Portraits et paysages",
            "vram": "4GB",
            "pipeline": "sd",
        },

        # Anime models
        "anything-v5": {
            "name": "Anything V5",
            "hf_id": "stablediffusionapi/anything-v5",
            "description": "Style anime - 4GB VRAM - Illustrations manga",
            "vram": "4GB",
            "pipeline": "sd",
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

        return StableDiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=dtype,
            use_safetensors=True,
            safety_checker=None,
        )

    def _load_sdxl_pipeline(self, model_id: str):
        """Load a Stable Diffusion XL pipeline."""
        from diffusers import StableDiffusionXLPipeline

        dtype = self._torch.float16 if self._device == "cuda" else self._torch.float32

        return StableDiffusionXLPipeline.from_pretrained(
            model_id,
            torch_dtype=dtype,
            use_safetensors=True,
            variant="fp16" if dtype == self._torch.float16 else None
        )

    def _load_hunyuan_pipeline(self, model_id: str):
        """Load a HunyuanImage 2.1 pipeline."""
        from diffusers import HunyuanImagePipeline

        logger.info("[Diffusers] Loading HunyuanImage 2.1 pipeline...")
        logger.info("[Diffusers] Note: This model only supports 2K resolution (2048x2048)")

        pipe = HunyuanImagePipeline.from_pretrained(
            model_id,
            torch_dtype=self._torch.bfloat16,
        )

        # Use CPU offload for memory efficiency (24GB required for 2K)
        logger.info("[Diffusers] Enabling CPU offload for HunyuanImage...")
        pipe.enable_model_cpu_offload()

        # Enable VAE tiling for large images
        try:
            pipe.vae.enable_tiling()
            logger.info("[Diffusers] VAE tiling enabled for HunyuanImage")
        except Exception as e:
            logger.debug(f"[Diffusers] VAE tiling not available: {e}")

        return pipe

    def load(self, model_name: str = None) -> bool:
        """
        Load a Stable Diffusion or Hunyuan model.

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

            # Unload previous model if any
            if self._pipe is not None:
                self.unload()

            # Load based on pipeline type
            if pipeline_type == "hunyuan":
                # HunyuanImage 2.1 pipeline
                self._pipe = self._load_hunyuan_pipeline(model_id)
            elif pipeline_type == "sdxl":
                # Stable Diffusion XL pipeline
                self._pipe = self._load_sdxl_pipeline(model_id)
            else:
                # Standard Stable Diffusion pipeline
                self._pipe = self._load_sd_pipeline(model_id)

            # Skip scheduler and device setup for Hunyuan (uses CPU offload)
            if pipeline_type != "hunyuan":
                # Use faster scheduler (with fallback if incompatible)
                try:
                    scheduler_config = dict(self._pipe.scheduler.config)
                    # Fix incompatible settings for some models
                    if scheduler_config.get('final_sigmas_type') == 'zero':
                        scheduler_config['final_sigmas_type'] = 'sigma_min'
                    self._pipe.scheduler = DPMSolverMultistepScheduler.from_config(scheduler_config)
                except Exception as scheduler_error:
                    logger.warning(f"Could not use DPMSolver scheduler, using default: {scheduler_error}")

                # Move to device
                logger.info(f"[Diffusers] Moving pipeline to {self._device}...")
                self._pipe = self._pipe.to(self._device)
                logger.info(f"[Diffusers] Pipeline moved to {self._device}")

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
        try:
            import torch
            from PIL import Image

            # Check if this is a HunyuanImage model
            model_info = self._get_model_info(params.model)
            is_hunyuan = model_info and model_info.get("pipeline") == "hunyuan"

            # For HunyuanImage with CPU offload, generator must be on CPU
            generator_device = "cpu" if is_hunyuan else self._device

            # Setup generator for reproducibility
            generator = None
            seed_used = params.seed
            if seed_used is not None:
                generator = torch.Generator(device=generator_device).manual_seed(seed_used)
            else:
                # Generate a random seed for reproducibility
                seed_used = torch.randint(0, 2**32, (1,)).item()
                generator = torch.Generator(device=generator_device).manual_seed(seed_used)

            # Build prompt
            prompt = params.prompt
            negative_prompt = params.negative_prompt or ""

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

                # Clear CUDA cache before generation
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    gc.collect()

                # Generate single image
                with torch.inference_mode():
                    if is_hunyuan:
                        # HunyuanImage has different parameters
                        # Force 2K resolution for HunyuanImage
                        width = max(params.width, 2048)
                        height = max(params.height, 2048)
                        logger.info(f"[Diffusers] HunyuanImage forcing 2K: {width}x{height}")

                        result = self._pipe(
                            prompt=prompt,
                            negative_prompt=negative_prompt if negative_prompt else None,
                            height=height,
                            width=width,
                            num_inference_steps=params.steps,
                            guidance_scale=params.guidance_scale,
                            generator=generator,
                            callback_on_step_end=step_callback,
                        )
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
            logger.error(f"Generation failed: {e}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            return GenerationResult(
                success=False,
                images=[],
                error=str(e)
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
            logger.error(f"Img2Img generation failed: {e}")
            return GenerationResult(
                success=False,
                images=[],
                error=str(e)
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
                self._pipe_img2img = StableDiffusionXLImg2ImgPipeline.from_pretrained(
                    model_id,
                    torch_dtype=dtype,
                    use_safetensors=True,
                    variant="fp16" if dtype == torch.float16 else None
                )
            else:
                self._pipe_img2img = StableDiffusionImg2ImgPipeline.from_pretrained(
                    model_id,
                    torch_dtype=dtype,
                    use_safetensors=True,
                    safety_checker=None,
                )

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
