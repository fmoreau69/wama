"""
Transcriber Backend Manager

Manages transcription backend registration, availability checking, and selection.
"""

import logging
from typing import Dict, List, Optional, Type

from .base import SpeechToTextBackend

logger = logging.getLogger(__name__)


class TranscriberBackendManager:
    """
    Manager for transcription backends.

    Handles backend registration, availability checking, and priority-based selection.
    """

    # Priority order for auto-selection (first available wins)
    BACKEND_PRIORITY = [
        'vibevoice',  # Best quality with diarization
        'whisper',    # Good fallback
    ]

    _backends: Dict[str, Type[SpeechToTextBackend]] = {}
    _instances: Dict[str, SpeechToTextBackend] = {}
    _availability_cache: Dict[str, bool] = {}
    _instance: Optional['TranscriberBackendManager'] = None

    @classmethod
    def get_instance(cls) -> 'TranscriberBackendManager':
        """Get singleton instance of the manager."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._register_backends()
        return cls._instance

    def _register_backends(self) -> None:
        """Register all available backends."""
        # Import backends
        try:
            from .whisper_backend import WhisperBackend
            self._backends['whisper'] = WhisperBackend
            logger.debug("[TranscriberManager] Registered: whisper")
        except ImportError as e:
            logger.warning(f"[TranscriberManager] Could not import WhisperBackend: {e}")

        try:
            from .vibevoice_backend import VibeVoiceBackend
            self._backends['vibevoice'] = VibeVoiceBackend
            logger.debug("[TranscriberManager] Registered: vibevoice")
        except ImportError as e:
            logger.warning(f"[TranscriberManager] Could not import VibeVoiceBackend: {e}")

        logger.info(f"[TranscriberManager] Registered backends: {list(self._backends.keys())}")

    def check_availability(self, force: bool = False) -> Dict[str, bool]:
        """
        Check which backends are available.

        Args:
            force: If True, recheck even if cached.

        Returns:
            Dict mapping backend name to availability status.
        """
        if not force and self._availability_cache:
            return self._availability_cache.copy()

        self._availability_cache = {}
        for name, backend_class in self._backends.items():
            try:
                available = backend_class.is_available()
                self._availability_cache[name] = available
                status = "available" if available else "not available"
                logger.info(f"[TranscriberManager] {name}: {status}")
            except Exception as e:
                self._availability_cache[name] = False
                logger.warning(f"[TranscriberManager] Error checking {name}: {e}")

        return self._availability_cache.copy()

    def get_available_backends(self) -> List[str]:
        """
        Get list of available backend names.

        Returns:
            List of available backend names.
        """
        availability = self.check_availability()
        return [name for name, available in availability.items() if available]

    def get_backend(self, name: str = None) -> SpeechToTextBackend:
        """
        Get a backend instance.

        Args:
            name: Backend name. If None or 'auto', select best available.

        Returns:
            Backend instance.

        Raises:
            RuntimeError: If no backend is available.
        """
        # Auto-select if no name provided
        if name is None or name == 'auto':
            return self._get_best_backend()

        # Check if requested backend exists and is available
        if name not in self._backends:
            logger.warning(f"[TranscriberManager] Unknown backend: {name}")
            return self._get_best_backend()

        availability = self.check_availability()
        if not availability.get(name, False):
            logger.warning(f"[TranscriberManager] Backend not available: {name}")
            return self._get_best_backend()

        # Return cached instance or create new one
        if name not in self._instances:
            self._instances[name] = self._backends[name]()
        return self._instances[name]

    def _get_best_backend(self) -> SpeechToTextBackend:
        """
        Get the best available backend based on priority.

        Returns:
            Best available backend instance.

        Raises:
            RuntimeError: If no backend is available.
        """
        availability = self.check_availability()

        for backend_name in self.BACKEND_PRIORITY:
            if backend_name in self._backends and availability.get(backend_name, False):
                if backend_name not in self._instances:
                    self._instances[backend_name] = self._backends[backend_name]()
                logger.info(f"[TranscriberManager] Auto-selected: {backend_name}")
                return self._instances[backend_name]

        # Try any available backend not in priority list
        for name, available in availability.items():
            if available:
                if name not in self._instances:
                    self._instances[name] = self._backends[name]()
                logger.info(f"[TranscriberManager] Fallback to: {name}")
                return self._instances[name]

        raise RuntimeError(
            "No transcription backend available. "
            "Install whisper (pip install openai-whisper) or vibevoice."
        )

    def get_backends_info(self) -> List[Dict]:
        """
        Get information about all registered backends.

        Returns:
            List of backend info dicts.
        """
        availability = self.check_availability()
        result = []

        for name, backend_class in self._backends.items():
            info = {
                'name': name,
                'display_name': backend_class.display_name,
                'available': availability.get(name, False),
                'supports_diarization': backend_class.supports_diarization,
                'supports_timestamps': backend_class.supports_timestamps,
                'supports_hotwords': backend_class.supports_hotwords,
                'min_vram_gb': backend_class.min_vram_gb,
                'recommended_vram_gb': backend_class.recommended_vram_gb,
            }
            result.append(info)

        return result

    def unload_all(self) -> None:
        """Unload all loaded backend instances."""
        for name, instance in self._instances.items():
            try:
                if instance.is_loaded:
                    instance.unload()
                    logger.info(f"[TranscriberManager] Unloaded: {name}")
            except Exception as e:
                logger.warning(f"[TranscriberManager] Error unloading {name}: {e}")

        self._instances.clear()


# Module-level convenience functions

def get_backend(name: str = None) -> SpeechToTextBackend:
    """
    Get a transcription backend instance.

    Args:
        name: Backend name ('whisper', 'vibevoice', 'auto', or None).

    Returns:
        Backend instance.
    """
    return TranscriberBackendManager.get_instance().get_backend(name)


def get_available_backends() -> List[str]:
    """
    Get list of available backend names.

    Returns:
        List of available backend names.
    """
    return TranscriberBackendManager.get_instance().get_available_backends()


def get_backends_info() -> List[Dict]:
    """
    Get information about all backends.

    Returns:
        List of backend info dicts.
    """
    return TranscriberBackendManager.get_instance().get_backends_info()
