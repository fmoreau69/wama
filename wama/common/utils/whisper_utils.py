"""
WAMA Common — faster-whisper transcription utility
Shared by wama.transcriber.backends.whisper_backend and wama.describer.utils.audio_describer.

Usage:
    from wama.common.utils.whisper_utils import transcribe_audio, WhisperResult

    result = transcribe_audio(audio_path)
    print(result.text, result.language, result.duration)
"""

import gc
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default model — large-v3 for best accuracy (≥16 GB VRAM available)
DEFAULT_MODEL       = 'large-v3'
COMPUTE_TYPE_CUDA   = 'float16'
COMPUTE_TYPE_CPU    = 'int8'


@dataclass
class WhisperSegment:
    start: float
    end: float
    text: str
    words: list = field(default_factory=list)


@dataclass
class WhisperResult:
    text: str
    language: str
    duration: float
    segments: List[WhisperSegment] = field(default_factory=list)


def _get_device_and_compute() -> tuple[str, str]:
    """Auto-detect device and matching compute type."""
    try:
        import torch
        if torch.cuda.is_available():
            return 'cuda', COMPUTE_TYPE_CUDA
    except ImportError:
        pass
    return 'cpu', COMPUTE_TYPE_CPU


def _get_whisper_cache() -> Optional[str]:
    """Return the centralized whisper model cache directory, or None."""
    try:
        from wama.describer.utils.model_config import get_model_path
        p = get_model_path('whisper')
        return str(p) if p else None
    except Exception:
        return os.environ.get('WHISPER_CACHE')


def transcribe_audio(
    audio_path: str,
    model_name: str = DEFAULT_MODEL,
    language: Optional[str] = None,
    device: str = 'auto',
    compute_type: Optional[str] = None,
    vad_filter: bool = True,
    word_timestamps: bool = True,
    beam_size: int = 5,
) -> WhisperResult:
    """
    Transcribe an audio file with faster-whisper.

    Args:
        audio_path:      Path to the audio / video file.
        model_name:      Whisper model size (default: 'large-v3').
        language:        ISO 639-1 code or None for auto-detection.
        device:          'auto' | 'cuda' | 'cpu'.
        compute_type:    'float16' | 'int8' | 'float32' (auto-selected if None).
        vad_filter:      Remove silence with Voice Activity Detection.
        word_timestamps: Include word-level timestamps in segments.
        beam_size:       Beam search width (higher = more accurate, slower).

    Returns:
        WhisperResult with .text, .language, .duration, .segments

    Raises:
        ImportError if faster_whisper is not installed.
        RuntimeError on transcription failure.
    """
    from faster_whisper import WhisperModel

    # Resolve device / compute type
    if device == 'auto':
        device, _ct = _get_device_and_compute()
        compute_type = compute_type or _ct
    else:
        compute_type = compute_type or (COMPUTE_TYPE_CUDA if device == 'cuda' else COMPUTE_TYPE_CPU)

    download_root = _get_whisper_cache()

    logger.info(f"[whisper_utils] Loading {model_name} on {device} ({compute_type})"
                f"{' → ' + download_root if download_root else ''}")

    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=download_root,
    )

    try:
        segments_gen, info = model.transcribe(
            audio_path,
            language=language or None,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
            beam_size=beam_size,
        )

        segments: List[WhisperSegment] = []
        text_parts: List[str] = []

        for seg in segments_gen:
            words = []
            if word_timestamps and seg.words:
                words = [
                    {'word': w.word, 'start': w.start, 'end': w.end, 'prob': w.probability}
                    for w in seg.words
                ]
            segments.append(WhisperSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                words=words,
            ))
            text_parts.append(seg.text.strip())

        full_text = ' '.join(text_parts).strip()
        logger.info(
            f"[whisper_utils] Done — {len(full_text)} chars, "
            f"{len(segments)} segments, lang={info.language}, "
            f"duration={info.duration:.1f}s"
        )
        return WhisperResult(
            text=full_text,
            language=info.language,
            duration=info.duration,
            segments=segments,
        )

    finally:
        # Always release the model to free VRAM
        del model
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
