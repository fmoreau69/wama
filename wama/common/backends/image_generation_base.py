"""
WAMA Imager - Base Backend Interface

Abstract base class for image generation backends.
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Callable
from PIL import Image
import logging

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)


def enable_vae_memory_savings(pipe, label: str = "VAE") -> list:
    """Réduit le pic du DÉCODAGE VAE d'un pipeline diffusers — en ESPACE et en TEMPS. Rend la
    liste des économies réellement posées.

    UNE brique pour les backends image et vidéo (2026-09-24), après deux défauts du même geste
    écrit à la main dans chaque backend :
      • `pipe.enable_vae_tiling()` n'existe que sur les pipelines d'IMAGE : sur Wan et Mochi
        l'appel levait en silence, et le décodage non tuilé de FastWan a pris 69 min ;
      • LTX tuilait bien en ESPACE, mais pas en TEMPS : `use_framewise_decoding` vaut False par
        défaut chez `AutoencoderKLLTXVideo`, et `enable_tiling()` ne le pose pas — les 233 images
        de la génération #275 ont été décodées d'un bloc (24,6 Gio demandés, OOM à 85 %).
    On agit donc sur le VAE LUI-MÊME, et le découpage temporel est posé partout où le VAE le
    connaît (LTX, Mochi, HunyuanVideo, Cosmos…). Un échec se DIT (warning), jamais en debug.
    """
    vae = getattr(pipe, 'vae', None)
    done = []
    if vae is None:
        return done
    for method, name in (('enable_slicing', 'slicing'), ('enable_tiling', 'tiling')):
        try:
            if hasattr(vae, method):
                getattr(vae, method)()
                done.append(name)
        except Exception as exc:
            logger.warning(f"[{label}] {method} indisponible : {exc}")
    for attr in ('use_framewise_decoding', 'use_framewise_encoding'):
        if hasattr(vae, attr):
            setattr(vae, attr, True)
            done.append(attr.replace('use_', ''))
    if 'tiling' not in done:
        logger.warning(f"[{label}] décodage VAE NON tuilé — pic mémoire élevé attendu")
    else:
        logger.info(f"[{label}] économies VAE : {', '.join(done)}")
    return done


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


class ImageGenerationBackend(BaseModelBackend):
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

    def process(self, **kwargs):
        """Point d'entrée métier générique (contrat commun BaseModelBackend) → délègue à generate()."""
        return self.generate(**kwargs)

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
            model_info = self.SUPPORTED_MODELS[model_name]
            # Support both old tuple format (name, model_id) and new dict format
            if isinstance(model_info, dict):
                return model_info.get("hf_id", model_name)
            elif isinstance(model_info, (tuple, list)) and len(model_info) >= 2:
                return model_info[1]
            else:
                return model_name

        # Default fallback
        logger.warning(f"Model '{model_name}' not found, using default")
        if self.SUPPORTED_MODELS:
            first_key = list(self.SUPPORTED_MODELS.keys())[0]
            model_info = self.SUPPORTED_MODELS[first_key]
            if isinstance(model_info, dict):
                return model_info.get("hf_id", first_key)
            elif isinstance(model_info, (tuple, list)) and len(model_info) >= 2:
                return model_info[1]

        return model_name

    @property
    def is_loaded(self) -> bool:
        """Check if a model is currently loaded."""
        return self._loaded

    @property
    def device(self) -> str:
        """Get the device being used (cpu, cuda, etc.)."""
        return self._device or "cpu"
