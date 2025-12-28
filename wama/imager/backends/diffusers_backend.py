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
    SUPPORTED_MODELS = {
        # Stable Diffusion models
        "stable-diffusion-v1-5": (
            "Stable Diffusion 1.5",
            "stable-diffusion-v1-5/stable-diffusion-v1-5"
        ),
        "stable-diffusion-2-1": (
            "Stable Diffusion 2.1",
            "stabilityai/stable-diffusion-2-1"
        ),
        "stable-diffusion-xl": (
            "Stable Diffusion XL",
            "stabilityai/stable-diffusion-xl-base-1.0"
        ),

        # Artistic models
        "openjourney-v4": (
            "OpenJourney v4",
            "prompthero/openjourney-v4"
        ),
        "dreamlike-art-2": (
            "Dreamlike Art 2.0",
            "dreamlike-art/dreamlike-diffusion-1.0"
        ),
        "dreamshaper-8": (
            "DreamShaper 8",
            "Lykon/DreamShaper"
        ),
        "deliberate-v2": (
            "Deliberate v2",
            "XpucT/Deliberate"
        ),

        # Realistic models
        "realistic-vision-v5": (
            "Realistic Vision V5",
            "SG161222/Realistic_Vision_V5.1_noVAE"
        ),

        # Anime models
        "anything-v5": (
            "Anything V5",
            "stablediffusionapi/anything-v5"
        ),
    }

    def __init__(self):
        super().__init__()
        self._pipe = None
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
            return "cuda"
        elif hasattr(self._torch.backends, 'mps') and self._torch.backends.mps.is_available():
            return "mps"
        else:
            return "cpu"

    def load(self, model_name: str = None) -> bool:
        """
        Load a Stable Diffusion model.

        Args:
            model_name: Model name (will be mapped to HuggingFace model ID).

        Returns:
            True if loaded successfully.
        """
        if model_name is None:
            model_name = "stable-diffusion-v1-5"

        # Map to HuggingFace model ID
        model_id = self.map_model_name(model_name)

        # Check if already loaded
        if self._loaded and self._current_model == model_id:
            logger.info(f"Model {model_id} already loaded")
            return True

        try:
            import torch
            from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler

            self._torch = torch
            self._device = self._get_device()

            logger.info(f"Loading model {model_id} on {self._device}...")

            # Unload previous model if any
            if self._pipe is not None:
                self.unload()

            # Determine dtype based on device
            if self._device == "cuda":
                dtype = torch.float16
            else:
                dtype = torch.float32

            # Check if it's an XL model
            is_xl = "xl" in model_id.lower()

            if is_xl:
                from diffusers import StableDiffusionXLPipeline
                self._pipe = StableDiffusionXLPipeline.from_pretrained(
                    model_id,
                    torch_dtype=dtype,
                    use_safetensors=True,
                    variant="fp16" if dtype == torch.float16 else None
                )
            else:
                self._pipe = StableDiffusionPipeline.from_pretrained(
                    model_id,
                    torch_dtype=dtype,
                    use_safetensors=True,
                    safety_checker=None,  # Disable NSFW filter for faster processing
                )

            # Use faster scheduler
            self._pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                self._pipe.scheduler.config
            )

            # Move to device
            self._pipe = self._pipe.to(self._device)

            # Enable memory optimizations
            if self._device == "cuda":
                try:
                    self._pipe.enable_attention_slicing()
                except Exception:
                    pass

                # Try to enable xformers for better memory efficiency
                try:
                    self._pipe.enable_xformers_memory_efficient_attention()
                    logger.info("xformers memory efficient attention enabled")
                except Exception:
                    pass

            self._current_model = model_id
            self._loaded = True
            logger.info(f"Model {model_id} loaded successfully on {self._device}")

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

        try:
            import torch
            from PIL import Image

            # Setup generator for reproducibility
            generator = None
            seed_used = params.seed
            if seed_used is not None:
                generator = torch.Generator(device=self._device).manual_seed(seed_used)
            else:
                # Generate a random seed for reproducibility
                seed_used = torch.randint(0, 2**32, (1,)).item()
                generator = torch.Generator(device=self._device).manual_seed(seed_used)

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

                # Generate single image
                with torch.inference_mode():
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
                    generator = torch.Generator(device=self._device).manual_seed(seed_used + i + 1)

            if progress_callback:
                progress_callback(100)

            return GenerationResult(
                success=True,
                images=generated_images,
                seed_used=seed_used
            )

        except Exception as e:
            logger.error(f"Generation failed: {e}")
            return GenerationResult(
                success=False,
                images=[],
                error=str(e)
            )

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
