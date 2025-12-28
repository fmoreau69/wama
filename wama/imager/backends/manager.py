"""
WAMA Imager - Backend Manager

Manages available image generation backends and provides automatic fallback.
"""

import logging
from typing import Optional, Dict, Type, List, Tuple

from .base import ImageGenerationBackend

logger = logging.getLogger(__name__)


class BackendManager:
    """
    Manager for image generation backends.

    Handles backend registration, availability checking, and automatic
    fallback to alternative backends.
    """

    # Backend priority order (first available will be used)
    BACKEND_PRIORITY = [
        'diffusers',      # Recommended for Python 3.12+
        'imaginairy',     # Legacy fallback
    ]

    def __init__(self):
        self._backends: Dict[str, Type[ImageGenerationBackend]] = {}
        self._instances: Dict[str, ImageGenerationBackend] = {}
        self._availability_cache: Dict[str, bool] = {}  # Cache availability results
        self._default_backend: Optional[str] = None
        self._register_builtin_backends()

    def _register_builtin_backends(self):
        """Register built-in backends."""
        # Import backends
        try:
            from .diffusers_backend import DiffusersBackend
            self._backends['diffusers'] = DiffusersBackend
            logger.debug("Registered DiffusersBackend")
        except ImportError as e:
            logger.warning(f"Could not register DiffusersBackend: {e}")

        try:
            from .imaginairy_backend import ImaginAiryBackend
            self._backends['imaginairy'] = ImaginAiryBackend
            logger.debug("Registered ImaginAiryBackend")
        except ImportError as e:
            logger.warning(f"Could not register ImaginAiryBackend: {e}")

    def register_backend(
        self,
        name: str,
        backend_class: Type[ImageGenerationBackend]
    ) -> None:
        """
        Register a custom backend.

        Args:
            name: Unique name for the backend.
            backend_class: Backend class (must inherit from ImageGenerationBackend).
        """
        if not issubclass(backend_class, ImageGenerationBackend):
            raise ValueError(
                f"Backend class must inherit from ImageGenerationBackend"
            )

        self._backends[name] = backend_class
        logger.info(f"Registered custom backend: {name}")

    def get_available_backends(self, use_cache: bool = True) -> Dict[str, bool]:
        """
        Get all registered backends and their availability status.

        Args:
            use_cache: If True, use cached results for faster response.

        Returns:
            Dictionary mapping backend names to availability status.
        """
        result = {}
        for name, backend_class in self._backends.items():
            # Use cached result if available and caching is enabled
            if use_cache and name in self._availability_cache:
                result[name] = self._availability_cache[name]
                continue

            try:
                is_available = backend_class.is_available()
                self._availability_cache[name] = is_available
                result[name] = is_available
            except Exception as e:
                logger.warning(f"Error checking availability of {name}: {e}")
                self._availability_cache[name] = False
                result[name] = False

        return result

    def get_best_backend(self) -> Optional[str]:
        """
        Get the best available backend based on priority.

        Returns:
            Name of the best available backend, or None if none available.
        """
        available = self.get_available_backends()

        for backend_name in self.BACKEND_PRIORITY:
            if available.get(backend_name, False):
                return backend_name

        # Check any other registered backends
        for name, is_available in available.items():
            if is_available:
                return name

        return None

    def get_backend(
        self,
        name: Optional[str] = None,
        allow_fallback: bool = True
    ) -> Optional[ImageGenerationBackend]:
        """
        Get a backend instance.

        Args:
            name: Backend name. If None, uses best available.
            allow_fallback: If True, falls back to other backends if requested
                          one is not available.

        Returns:
            Backend instance, or None if no suitable backend found.
        """
        # Determine which backend to use
        if name is None:
            name = self.get_best_backend()
            if name is None:
                logger.error("No image generation backend available")
                return None

        # Check if backend is registered
        if name not in self._backends:
            if allow_fallback:
                logger.warning(
                    f"Backend '{name}' not registered, trying fallback"
                )
                name = self.get_best_backend()
                if name is None:
                    return None
            else:
                logger.error(f"Backend '{name}' not registered")
                return None

        # Check if backend is available
        backend_class = self._backends[name]
        if not backend_class.is_available():
            if allow_fallback:
                logger.warning(
                    f"Backend '{name}' not available, trying fallback"
                )
                name = self.get_best_backend()
                if name is None:
                    return None
                backend_class = self._backends[name]
            else:
                logger.error(f"Backend '{name}' not available")
                return None

        # Return cached instance or create new one
        if name not in self._instances:
            logger.info(f"Creating new instance of backend: {name}")
            self._instances[name] = backend_class()

        return self._instances[name]

    def get_all_supported_models(self) -> Dict[str, Dict]:
        """
        Get all models supported across all available backends.

        Returns:
            Dictionary mapping model names to info dict with display_name
            and supported_backends.
        """
        models = {}
        available = self.get_available_backends()

        for backend_name, is_available in available.items():
            if not is_available:
                continue

            backend_class = self._backends[backend_name]
            for model_name, (display_name, _) in backend_class.SUPPORTED_MODELS.items():
                if model_name not in models:
                    models[model_name] = {
                        'display_name': display_name,
                        'backends': []
                    }
                models[model_name]['backends'].append(backend_name)

        return models

    def get_models_choices_fast(self) -> List[tuple]:
        """
        Get models list quickly without checking availability.
        Uses the first registered backend's models (typically diffusers).
        Good for UI display during page load.

        Returns:
            List of (model_name, display_name) tuples.
        """
        # Use diffusers models by default (most comprehensive list)
        for backend_name in self.BACKEND_PRIORITY:
            if backend_name in self._backends:
                backend_class = self._backends[backend_name]
                return [
                    (name, info[0])
                    for name, info in backend_class.SUPPORTED_MODELS.items()
                ]

        # Fallback to any registered backend
        for backend_class in self._backends.values():
            return [
                (name, info[0])
                for name, info in backend_class.SUPPORTED_MODELS.items()
            ]

        return []

    def get_backend_info_fast(self) -> Dict:
        """
        Get backend info quickly without heavy imports.
        Uses cached availability if available.

        Returns:
            Dict with backend_name, backend_available, and available_backends.
        """
        # Check if we have cached availability
        if self._availability_cache:
            available_backends = self._availability_cache.copy()
        else:
            # Return unknown status without checking (will be checked on first use)
            available_backends = {name: None for name in self._backends.keys()}

        # Determine best backend from cache or priority
        backend_name = "Unknown"
        backend_available = False

        for name in self.BACKEND_PRIORITY:
            if name in self._availability_cache:
                if self._availability_cache[name]:
                    backend_name = self._backends[name].display_name if name in self._backends else name
                    backend_available = True
                    break
            elif name in self._backends:
                # Not checked yet, assume available (will be verified on first use)
                backend_name = self._backends[name].display_name
                backend_available = True
                break

        return {
            'backend_name': backend_name,
            'backend_available': backend_available,
            'available_backends': available_backends,
        }

    def cleanup(self):
        """Unload all backend instances."""
        for name, instance in self._instances.items():
            try:
                instance.unload()
                logger.info(f"Unloaded backend: {name}")
            except Exception as e:
                logger.warning(f"Error unloading backend {name}: {e}")

        self._instances.clear()


# Global manager instance
_manager: Optional[BackendManager] = None


def get_manager() -> BackendManager:
    """Get the global backend manager instance."""
    global _manager
    if _manager is None:
        _manager = BackendManager()
    return _manager


def get_backend(
    name: Optional[str] = None,
    allow_fallback: bool = True
) -> Optional[ImageGenerationBackend]:
    """
    Convenience function to get a backend instance.

    Args:
        name: Backend name. If None, uses best available.
        allow_fallback: If True, falls back to other backends.

    Returns:
        Backend instance, or None if not available.
    """
    return get_manager().get_backend(name, allow_fallback)


def get_available_backends() -> Dict[str, bool]:
    """
    Convenience function to get available backends.

    Returns:
        Dictionary mapping backend names to availability.
    """
    return get_manager().get_available_backends()


def get_models_choices_fast() -> List[Tuple[str, str]]:
    """
    Get models list quickly without heavy imports.
    Use this for page load to avoid slow torch/diffusers imports.

    Returns:
        List of (model_name, display_name) tuples.
    """
    return get_manager().get_models_choices_fast()


def get_backend_info_fast() -> Dict:
    """
    Get backend info quickly without heavy imports.

    Returns:
        Dict with backend_name, backend_available, and available_backends.
    """
    return get_manager().get_backend_info_fast()
