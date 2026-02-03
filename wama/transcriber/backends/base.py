"""
Transcriber Backend Base Classes

Abstract base class for speech-to-text backends.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionSegment:
    """A segment of transcription with speaker and timing info."""
    speaker_id: str
    start_time: float  # seconds
    end_time: float    # seconds
    text: str
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'speaker_id': self.speaker_id,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'text': self.text,
            'confidence': self.confidence,
        }


@dataclass
class TranscriptionResult:
    """Result from a transcription operation."""
    success: bool
    text: str
    language: str = ''
    segments: List[TranscriptionSegment] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'success': self.success,
            'text': self.text,
            'language': self.language,
            'segments': [s.to_dict() for s in self.segments],
            'error': self.error,
        }


class SpeechToTextBackend(ABC):
    """
    Abstract base class for speech-to-text backends.

    All transcription backends must inherit from this class and implement
    the required methods.
    """

    # Class-level attributes to be overridden by subclasses
    name: str = "base"
    display_name: str = "Base Backend"

    # Feature flags
    supports_diarization: bool = False
    supports_timestamps: bool = False
    supports_hotwords: bool = False
    supports_streaming: bool = False

    # Resource requirements
    min_vram_gb: float = 0
    recommended_vram_gb: float = 0

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """
        Check if this backend's dependencies are installed and available.

        Returns:
            True if the backend can be used, False otherwise.
        """
        pass

    @abstractmethod
    def load(self, model_name: str = None) -> bool:
        """
        Load the transcription model into memory.

        Args:
            model_name: Optional model identifier. If None, use default.

        Returns:
            True if loaded successfully, False otherwise.
        """
        pass

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: str = None,
        hotwords: str = None,
        **kwargs
    ) -> TranscriptionResult:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to the audio file.
            language: Optional language code (e.g., 'en', 'fr'). Auto-detect if None.
            hotwords: Optional comma-separated list of domain-specific terms.
            **kwargs: Additional backend-specific parameters.

        Returns:
            TranscriptionResult with text and optional segments.
        """
        pass

    @abstractmethod
    def unload(self) -> None:
        """
        Unload the model from memory to free resources.
        """
        pass

    @property
    def is_loaded(self) -> bool:
        """Check if a model is currently loaded."""
        return self._loaded

    def get_info(self) -> dict:
        """Get backend information."""
        return {
            'name': self.name,
            'display_name': self.display_name,
            'available': self.is_available(),
            'loaded': self.is_loaded,
            'current_model': self._current_model,
            'supports_diarization': self.supports_diarization,
            'supports_timestamps': self.supports_timestamps,
            'supports_hotwords': self.supports_hotwords,
            'supports_streaming': self.supports_streaming,
            'min_vram_gb': self.min_vram_gb,
            'recommended_vram_gb': self.recommended_vram_gb,
        }
