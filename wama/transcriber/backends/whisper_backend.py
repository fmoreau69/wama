"""
Whisper Backend for Transcriber — powered by faster-whisper.

Uses CTranslate2 (float16 on GPU, int8 on CPU) for significantly faster
inference than the original openai-whisper while keeping the same accuracy.

Default model: large-v3 (best accuracy, ≈10 GB VRAM).
"""

import gc
import logging
from typing import Optional

from .base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)

DEFAULT_WHISPER_MODEL = 'large-v3'


class WhisperBackend(SpeechToTextBackend):
    """
    Speech-to-text backend using faster-whisper (CTranslate2).

    Supports large-v3 (default), large-v3-turbo, medium, small, base, tiny.
    Diarization is handled externally by pyannote_diarizer (see workers.py).
    """

    name = "whisper"
    display_name = "Whisper (faster-whisper)"

    supports_diarization = False   # pyannote post-processing in workers.py
    supports_timestamps  = True
    supports_hotwords    = False
    supports_streaming   = False

    min_vram_gb         = 2
    recommended_vram_gb = 10

    MODEL_VRAM = {
        'tiny':             1,
        'base':             1,
        'small':            2,
        'medium':           5,
        'large':            10,
        'large-v2':         10,
        'large-v3':         10,
        'large-v3-turbo':   6,
        'distil-large-v3':  4,
    }

    def __init__(self):
        super().__init__()
        self._model  = None
        self._device = None
        self._compute_type = None

    # ------------------------------------------------------------------
    # Class-level helpers
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Check whether faster_whisper is installed."""
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def _get_device_and_compute(self) -> tuple[str, str]:
        """Auto-select device and matching CTranslate2 compute type."""
        try:
            import torch
            if torch.cuda.is_available():
                return 'cuda', 'float16'
            if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                # faster-whisper does not support MPS natively → CPU
                return 'cpu', 'int8'
        except ImportError:
            pass
        return 'cpu', 'int8'

    def _get_download_root(self) -> Optional[str]:
        """Return the centralized Whisper model cache, or None."""
        try:
            from ..utils.model_config import get_whisper_download_root
            return str(get_whisper_download_root())
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, model_name: str = None) -> bool:
        """
        Load a faster-whisper model.

        Args:
            model_name: Model size identifier (default: 'large-v3').

        Returns:
            True if loaded successfully.
        """
        if model_name is None:
            model_name = DEFAULT_WHISPER_MODEL

        # Already loaded with the same model — reuse
        if self._loaded and self._current_model == model_name:
            logger.info(f"[Whisper] {model_name} already loaded — reusing")
            return True

        try:
            from faster_whisper import WhisperModel

            # Unload previous model if any
            if self._model is not None:
                self.unload()

            self._device, self._compute_type = self._get_device_and_compute()
            download_root = self._get_download_root()

            logger.info(
                f"[Whisper] Loading '{model_name}' on {self._device} "
                f"({self._compute_type})"
                + (f" → {download_root}" if download_root else "")
            )

            self._model = WhisperModel(
                model_name,
                device=self._device,
                compute_type=self._compute_type,
                download_root=download_root,
            )

            self._loaded        = True
            self._current_model = model_name
            logger.info(f"[Whisper] '{model_name}' loaded ✓")
            return True

        except Exception as e:
            logger.error(f"[Whisper] Failed to load '{model_name}': {e}")
            self._loaded = False
            return False

    def unload(self) -> None:
        """Unload model and free VRAM."""
        if self._model is not None:
            logger.info("[Whisper] Unloading model…")
            del self._model
            self._model = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            gc.collect()
            self._loaded        = False
            self._current_model = None
            logger.info("[Whisper] Model unloaded")

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def transcribe(
        self,
        audio_path: str,
        language: str = None,
        hotwords: str = None,         # accepted but ignored (not supported)
        **kwargs,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file with faster-whisper.

        Supported kwargs:
            enable_timestamps (bool, default True)
            vad_filter        (bool, default True)
            beam_size         (int,  default 5)
            temperature       (float)

        Returns:
            TranscriptionResult — segments have empty speaker_id (filled by
            pyannote post-processing in workers.py if diarization is enabled).
        """
        if not self._loaded or self._model is None:
            if not self.load():
                return TranscriptionResult(
                    success=False, text='',
                    error="Failed to load Whisper model",
                )

        try:
            logger.info(f"[Whisper] Transcribing: {audio_path}")

            transcribe_opts: dict = {
                'language':        language or None,
                'vad_filter':      kwargs.get('vad_filter', True),
                'word_timestamps': kwargs.get('enable_timestamps', True),
                'beam_size':       int(kwargs.get('beam_size', 5)),
            }
            if 'temperature' in kwargs:
                transcribe_opts['temperature'] = float(kwargs['temperature'])

            segments_gen, info = self._model.transcribe(audio_path, **transcribe_opts)

            segments:    list[TranscriptionSegment] = []
            text_parts:  list[str]                  = []

            for seg in segments_gen:
                confidence = getattr(seg, 'avg_logprob', None)
                segments.append(TranscriptionSegment(
                    speaker_id = '',          # filled by pyannote later
                    start_time = seg.start,
                    end_time   = seg.end,
                    text       = seg.text.strip(),
                    confidence = confidence,
                ))
                text_parts.append(seg.text.strip())

            full_text = ' '.join(text_parts).strip()
            logger.info(
                f"[Whisper] Done — {len(full_text)} chars, "
                f"{len(segments)} segments, lang={info.language}"
            )

            return TranscriptionResult(
                success  = True,
                text     = full_text,
                language = info.language,
                segments = segments,
            )

        except Exception as e:
            logger.error(f"[Whisper] Transcription failed: {e}")
            return TranscriptionResult(success=False, text='', error=str(e))
