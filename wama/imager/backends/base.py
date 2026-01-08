"""
WAMA Imager - Base Backend Interface

Abstract base class for image generation backends.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Callable
from PIL import Image
import logging

logger = logging.getLogger(__name__)


@dataclass
class GenerationParams:
    """Parameters for image generation."""
    prompt: str
    negative_prompt: Optional[str] = None
    model: str = "stable-diffusion-v1-5"
    width: int = 512
    height: int = 512
    steps: int = 30
    guidance_scale: float = 7.5
    seed: Optional[int] = None
    num_images: int = 1
    upscale: bool = False

    # Multi-modal generation parameters
    generation_mode: str = "txt2img"  # txt2img, img2img, style2img, describe2img
    reference_image: Optional[str] = None  # Path to reference image
    image_strength: float = 0.75  # Influence of reference image (0=ignore, 1=copy)


@dataclass
class GenerationResult:
    """Result of image/video generation."""
    success: bool
    images: List[Image.Image] = None
    seed_used: Optional[int] = None
    error: Optional[str] = None
    video_frames: Optional[List] = None  # For video generation

    def __post_init__(self):
        if self.images is None:
            self.images = []


class ImageGenerationBackend(ABC):
    """
    Abstract base class for image generation backends.

    All backends must implement this interface to be compatible
    with the WAMA Imager system.
    """

    # Backend identification
    name: str = "base"
    display_name: str = "Base Backend"

    # Supported models mapping: internal_name -> (display_name, model_id)
    SUPPORTED_MODELS: dict = {}

    def __init__(self):
        self._loaded = False
        self._device = None

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """
        Check if this backend is available (dependencies installed).

        Returns:
            True if the backend can be used, False otherwise.
        """
        pass

    @abstractmethod
    def load(self, model_name: str = None) -> bool:
        """
        Load the model into memory.

        Args:
            model_name: Name of the model to load.

        Returns:
            True if loaded successfully, False otherwise.
        """
        pass

    @abstractmethod
    def generate(
        self,
        params: GenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """
        Generate images based on the given parameters.

        Args:
            params: Generation parameters.
            progress_callback: Optional callback for progress updates (0-100).

        Returns:
            GenerationResult with generated images or error.
        """
        pass

    @abstractmethod
    def unload(self) -> None:
        """Unload the model from memory."""
        pass

    def get_supported_models(self) -> dict:
        """
        Get the list of supported models for this backend.

        Returns:
            Dictionary mapping internal names to (display_name, model_id) tuples.
        """
        return self.SUPPORTED_MODELS

    def map_model_name(self, model_name: str) -> str:
        """
        Map a generic model name to this backend's specific model identifier.

        Args:
            model_name: Generic model name (e.g., "openjourney-v4")

        Returns:
            Backend-specific model identifier.
        """
        if model_name in self.SUPPORTED_MODELS:
            return self.SUPPORTED_MODELS[model_name][1]

        # Default fallback
        logger.warning(f"Model '{model_name}' not found, using default")
        if self.SUPPORTED_MODELS:
            first_key = list(self.SUPPORTED_MODELS.keys())[0]
            return self.SUPPORTED_MODELS[first_key][1]

        return model_name

    @property
    def is_loaded(self) -> bool:
        """Check if a model is currently loaded."""
        return self._loaded

    @property
    def device(self) -> str:
        """Get the device being used (cpu, cuda, etc.)."""
        return self._device or "cpu"
