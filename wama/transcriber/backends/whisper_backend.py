"""
Whisper Backend for Transcriber

OpenAI Whisper-based speech-to-text backend.
"""

import gc
import logging
from typing import Optional

from .base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)


class WhisperBackend(SpeechToTextBackend):
    """
    Speech-to-text backend using OpenAI Whisper.

    Supports multiple model sizes from tiny to large-v3.
    """

    name = "whisper"
    display_name = "Whisper (OpenAI)"

    supports_diarization = False
    supports_timestamps = True  # Whisper provides word-level timestamps
    supports_hotwords = False
    supports_streaming = False

    min_vram_gb = 2
    recommended_vram_gb = 4

    # Model size to VRAM mapping
    MODEL_VRAM = {
        'tiny': 1,
        'base': 1,
        'small': 2,
        'medium': 5,
        'large': 10,
        'large-v2': 10,
        'large-v3': 10,
    }

    def __init__(self):
        super().__init__()
        self._model = None
        self._torch = None
        self._whisper = None
        self._device = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if whisper is installed."""
        try:
            import whisper
            import torch
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
        Load a Whisper model.

        Args:
            model_name: Model size ('tiny', 'base', 'small', 'medium', 'large', 'large-v3').
                       Defaults to 'base'.

        Returns:
            True if loaded successfully.
        """
        if model_name is None:
            model_name = 'base'

        # Check if already loaded with same model
        if self._loaded and self._current_model == model_name:
            logger.info(f"[Whisper] Model {model_name} already loaded")
            return True

        try:
            import whisper
            import torch

            self._whisper = whisper
            self._torch = torch
            self._device = self._get_device()

            # Unload previous model if any
            if self._model is not None:
                self.unload()

            logger.info(f"[Whisper] Loading model '{model_name}' on {self._device}...")

            # Try to use centralized cache
            try:
                from ..utils.model_config import load_whisper_model
                self._model = load_whisper_model(model_name, device=self._device)
            except ImportError:
                # Fallback to default whisper loading
                self._model = whisper.load_model(model_name, device=self._device)

            self._loaded = True
            self._current_model = model_name
            logger.info(f"[Whisper] Model '{model_name}' loaded successfully on {self._device}")

            return True

        except Exception as e:
            logger.error(f"[Whisper] Failed to load model: {e}")
            self._loaded = False
            return False

    def transcribe(
        self,
        audio_path: str,
        language: str = None,
        hotwords: str = None,
        **kwargs
    ) -> TranscriptionResult:
        """
        Transcribe audio using Whisper.

        Args:
            audio_path: Path to audio file.
            language: Optional language code. If None, auto-detect.
            hotwords: Not supported by Whisper (ignored).
            **kwargs: Additional parameters passed to whisper.transcribe().

        Returns:
            TranscriptionResult with text and segments.
        """
        if not self._loaded or self._model is None:
            if not self.load():
                return TranscriptionResult(
                    success=False,
                    text='',
                    error="Failed to load Whisper model"
                )

        try:
            logger.info(f"[Whisper] Transcribing: {audio_path}")

            # Build transcribe options
            transcribe_options = {
                'verbose': False,
            }

            # Add language if specified
            if language:
                transcribe_options['language'] = language

            # Add any extra options from kwargs
            for key in ['temperature', 'initial_prompt', 'word_timestamps', 'fp16']:
                if key in kwargs:
                    transcribe_options[key] = kwargs[key]

            # Enable word timestamps for segment extraction
            if kwargs.get('enable_timestamps', True):
                transcribe_options['word_timestamps'] = True

            # Transcribe
            result = self._model.transcribe(audio_path, **transcribe_options)

            # Extract full text
            full_text = result.get('text', '').strip()
            detected_language = result.get('language', '')

            # Extract segments with timestamps
            segments = []
            for seg in result.get('segments', []):
                segments.append(TranscriptionSegment(
                    speaker_id='',  # Whisper doesn't do diarization
                    start_time=seg.get('start', 0),
                    end_time=seg.get('end', 0),
                    text=seg.get('text', '').strip(),
                    confidence=None  # Whisper doesn't provide segment confidence
                ))

            logger.info(f"[Whisper] Transcription complete: {len(full_text)} chars, {len(segments)} segments")

            return TranscriptionResult(
                success=True,
                text=full_text,
                language=detected_language,
                segments=segments
            )

        except Exception as e:
            logger.error(f"[Whisper] Transcription failed: {e}")
            return TranscriptionResult(
                success=False,
                text='',
                error=str(e)
            )

    def unload(self) -> None:
        """Unload model from memory."""
        if self._model is not None:
            logger.info("[Whisper] Unloading model...")
            del self._model
            self._model = None

            # Clear CUDA cache
            if self._torch is not None and self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()

            gc.collect()

            self._loaded = False
            self._current_model = None
            logger.info("[Whisper] Model unloaded")
