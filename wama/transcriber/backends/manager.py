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

    # Priority order for auto-selection (first available wins).
    # Whisper d'abord : meilleure qualité FR, plus léger (~10 GB vs 16 GB pour
    # VibeVoice), et la diarisation est assurée par pyannote (backend-agnostique).
    # VibeVoice reste sélectionnable explicitement (diarisation native). qwen_asr
    # en dernier : is_available()=True dès transformers installé, mais nécessite
    # un téléchargement explicite + son intérêt (context biasing) est opt-in.
    BACKEND_PRIORITY = [
        'whisper',     # Défaut fiable : faster-whisper large-v3 + pyannote
        'vibevoice',   # Option : diarisation native (16 GB VRAM)
        'qwen_asr',    # Option : context biasing (hotwords), une fois le modèle dispo
    ]

    _backends: Dict[str, Type[SpeechToTextBackend]] = {}
    _instances: Dict[str, SpeechToTextBackend] = {}
    _availability_cache: Dict[str, bool] = {}
    # True si un check a échoué sur EXCEPTION (vs False propre) → cache « incomplet »,
    # à ré-évaluer au prochain appel. Couvre les indispos transitoires au démarrage
    # (ex. course d'imports accelerate qui casse VibeVoice le temps que ça se stabilise).
    _availability_incomplete: bool = False
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

        try:
            from .qwen_asr_backend import QwenASRBackend
            self._backends['qwen_asr'] = QwenASRBackend
            logger.debug("[TranscriberManager] Registered: qwen_asr")
        except ImportError as e:
            logger.warning(f"[TranscriberManager] Could not import QwenASRBackend: {e}")

        logger.info(f"[TranscriberManager] Registered backends: {list(self._backends.keys())}")

    def check_availability(self, force: bool = False) -> Dict[str, bool]:
        """
        Check which backends are available.

        Args:
            force: If True, recheck even if cached.

        Returns:
            Dict mapping backend name to availability status.
        """
        # Cache réutilisé seulement s'il est COMPLET (aucun check n'a planté sur exception).
        if not force and self._availability_cache and not self._availability_incomplete:
            return self._availability_cache.copy()

        self._availability_cache = {}
        self._availability_incomplete = False
        for name, backend_class in self._backends.items():
            try:
                available = backend_class.is_available()
                self._availability_cache[name] = available
                status = "available" if available else "not available"
                logger.info(f"[TranscriberManager] {name}: {status}")
            except Exception as e:
                # Échec sur exception (≠ False propre) : probablement transitoire
                # (course d'imports au démarrage). On ne verrouille PAS ce négatif →
                # le cache est marqué incomplet pour forcer une ré-évaluation ensuite.
                self._availability_cache[name] = False
                self._availability_incomplete = True
                logger.warning(f"[TranscriberManager] Error checking {name}: {e} (sera re-testé)")

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
            # L'utilisateur a demandé CE moteur explicitement : avant de replier,
            # forcer un re-test (l'indispo peut être une race d'import transitoire au
            # démarrage, déjà résorbée au moment où la tâche tourne).
            logger.info(f"[TranscriberManager] {name} marqué indisponible — re-test forcé")
            availability = self.check_availability(force=True)
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
            "Install faster-whisper (pip install faster-whisper) "
            "or transformers+soundfile for Qwen3-ASR."
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
                'description': getattr(backend_class, 'description', ''),
                'description_long': getattr(backend_class, 'description_long', ''),
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
