"""
WAMA Imager - ImaginAiry Backend

Image generation using the imaginAIry library.
This is the legacy backend for compatibility with older Python versions.

Note: ImaginAiry may not be compatible with Python 3.12+.
Use the Diffusers backend for Python 3.12+ compatibility.
"""

import gc
import logging
from typing import Optional, Callable, List

from .base import ImageGenerationBackend, GenerationParams, GenerationResult

logger = logging.getLogger(__name__)


class ImaginAiryBackend(ImageGenerationBackend):
    """
    Image generation backend using imaginAIry library.

    This backend wraps the imaginAIry library for image generation.
    It's kept for backwards compatibility with older setups.
    """

    name = "imaginairy"
    display_name = "imaginAIry (Legacy)"

    # ImaginAiry model names
    SUPPORTED_MODELS = {
        "openjourney-v4": (
            "OpenJourney v4",
            "openjourney-v4"
        ),
        "dreamlike-art-2": (
            "Dreamlike Art 2.0",
            "dreamlike-art-2.0"
        ),
        "stable-diffusion-2-1": (
            "Stable Diffusion 2.1",
            "SD-2.1"
        ),
        "stable-diffusion-v1-5": (
            "Stable Diffusion 1.5",
            "SD-1.5"
        ),
    }

    def __init__(self):
        super().__init__()
        self._imagine = None
        self._ImaginePrompt = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if imaginAIry library is installed and compatible."""
        try:
            from imaginairy import imagine, ImaginePrompt
            return True
        except ImportError:
            return False
        except Exception as e:
            # Catch compatibility errors (e.g., Python version issues)
            logger.warning(f"imaginAIry not compatible: {e}")
            return False

    def load(self, model_name: str = None) -> bool:
        """
        Load imaginAIry (lazy import).

        Args:
            model_name: Model name (used during generation).

        Returns:
            True if loaded successfully.
        """
        try:
            from imaginairy import imagine, ImaginePrompt

            self._imagine = imagine
            self._ImaginePrompt = ImaginePrompt
            self._loaded = True

            # Try to detect device
            try:
                import torch
                if torch.cuda.is_available():
                    self._device = "cuda"
                else:
                    self._device = "cpu"
            except ImportError:
                self._device = "cpu"

            logger.info(f"imaginAIry loaded successfully (device: {self._device})")
            return True

        except ImportError as e:
            logger.error(f"Failed to import imaginAIry: {e}")
            self._loaded = False
            return False
        except Exception as e:
            logger.error(f"Failed to load imaginAIry: {e}")
            self._loaded = False
            return False

    def generate(
        self,
        params: GenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """
        Generate images using imaginAIry.

        Args:
            params: Generation parameters.
            progress_callback: Optional progress callback (0-100).

        Returns:
            GenerationResult with generated images.
        """
        if not self._loaded:
            if not self.load(params.model):
                return GenerationResult(
                    success=False,
                    images=[],
                    error="Failed to load imaginAIry"
                )

        try:
            from PIL import Image

            # Build prompt text
            prompt_text = params.prompt
            if params.negative_prompt:
                prompt_text += f" [negative:{params.negative_prompt}]"

            # Map model name
            model_id = self.map_model_name(params.model)

            # Create ImaginePrompt
            imagine_prompt = self._ImaginePrompt(
                prompt=prompt_text,
                model=model_id,
                width=params.width,
                height=params.height,
                steps=params.steps,
                prompt_strength=params.guidance_scale,
                seed=params.seed,
                upscale=params.upscale,
            )

            generated_images: List[Image.Image] = []
            seed_used = params.seed

            for i in range(params.num_images):
                if progress_callback:
                    progress = int((i / params.num_images) * 100)
                    progress_callback(progress)

                logger.info(f"Generating image {i+1}/{params.num_images} with imaginAIry")

                # Generate image
                results = list(self._imagine([imagine_prompt]))

                if results and len(results) > 0:
                    result = results[0]

                    # Get the generated image
                    if hasattr(result, 'img') and result.img:
                        generated_images.append(result.img.copy())

                        # Get seed if available
                        if seed_used is None and hasattr(result, 'seed'):
                            seed_used = result.seed
                    else:
                        logger.warning(f"No image in result for image {i+1}")

            if progress_callback:
                progress_callback(100)

            if not generated_images:
                return GenerationResult(
                    success=False,
                    images=[],
                    error="No images were generated"
                )

            return GenerationResult(
                success=True,
                images=generated_images,
                seed_used=seed_used
            )

        except Exception as e:
            logger.error(f"imaginAIry generation failed: {e}")
            return GenerationResult(
                success=False,
                images=[],
                error=str(e)
            )

    def unload(self) -> None:
        """Unload imaginAIry from memory."""
        self._imagine = None
        self._ImaginePrompt = None
        self._loaded = False

        # Force garbage collection
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        logger.info("imaginAIry unloaded from memory")
