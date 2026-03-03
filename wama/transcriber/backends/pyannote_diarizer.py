"""
pyannote.audio Speaker Diarizer for Transcriber

Post-processes Whisper segments to assign a speaker_id to each segment by
computing the maximum time-overlap between each Whisper segment and the
pyannote diarization turns.

Requires:
    pip install pyannote.audio>=3.3.1

The pyannote/speaker-diarization-3.1 model is gated on HuggingFace.
Provide an access token via settings.HUGGINGFACE_TOKEN or the hf_token arg.
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Module-level pipeline cache — reloaded only when the process restarts
_pipeline = None


def is_available() -> bool:
    """Return True if pyannote.audio is installed."""
    try:
        import pyannote.audio  # noqa: F401
        return True
    except ImportError:
        return False


def _load_pipeline(hf_token: Optional[str] = None):
    """Load (or return cached) pyannote speaker-diarization pipeline."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    from pyannote.audio import Pipeline
    import torch

    # Resolve HuggingFace token from argument or Django settings
    token = hf_token
    if not token:
        try:
            from django.conf import settings
            token = getattr(settings, 'HUGGINGFACE_TOKEN', None)
        except Exception:
            pass

    logger.info("[pyannote] Loading speaker-diarization-3.1 pipeline…")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=token,
    )

    if torch.cuda.is_available():
        pipeline = pipeline.to(torch.device("cuda"))
        logger.info("[pyannote] Pipeline moved to CUDA")

    _pipeline = pipeline
    logger.info("[pyannote] Pipeline loaded ✓")
    return _pipeline


def _preload_audio(audio_path: str) -> dict:
    """
    Load audio file into a {'waveform': tensor, 'sample_rate': int} dict.

    This bypasses pyannote's built-in torchcodec/FFmpeg audio decoder, which
    requires specific shared libraries that may not be available.  We use
    soundfile (bundled with faster-whisper / openai-whisper) or torchaudio
    as a fallback.
    """
    import torch

    # Primary: soundfile — no FFmpeg required, reads WAV/FLAC/OGG natively
    try:
        import soundfile as sf
        import numpy as np
        data, sr = sf.read(audio_path, dtype='float32', always_2d=True)
        # soundfile → (time, channels); pyannote expects (channels, time)
        waveform = torch.from_numpy(data.T)
        return {'waveform': waveform, 'sample_rate': sr}
    except Exception as e_sf:
        logger.debug(f"[pyannote] soundfile preload failed: {e_sf}, trying torchaudio")

    # Fallback: torchaudio
    try:
        import torchaudio
        waveform, sr = torchaudio.load(audio_path)
        return {'waveform': waveform, 'sample_rate': sr}
    except Exception as e_ta:
        logger.warning(f"[pyannote] torchaudio preload failed: {e_ta}, passing raw path")

    # Last resort: let pyannote try to load the path directly
    return audio_path  # type: ignore[return-value]


def diarize(
    audio_path: str,
    segments: list,
    num_speakers: Optional[int] = None,
    hf_token: Optional[str] = None,
) -> list:
    """
    Run speaker diarization and assign speaker_id to each segment.

    Args:
        audio_path:   Path to the audio file.
        segments:     List of TranscriptionSegment (speaker_id='') from Whisper.
        num_speakers: Optional number of speakers hint.
        hf_token:     HuggingFace access token for the gated pyannote model.

    Returns:
        Same list with speaker_id populated.
        Falls back gracefully (empty speaker_id) on any failure.
    """
    if not segments:
        return segments

    try:
        pipeline = _load_pipeline(hf_token)

        diarize_kwargs: dict = {}
        if num_speakers:
            diarize_kwargs["num_speakers"] = num_speakers

        # Pre-load audio as tensor to avoid torchcodec/FFmpeg dependency in pyannote
        audio_input = _preload_audio(audio_path)

        logger.info(f"[pyannote] Diarizing: {audio_path}")
        diarization = pipeline(audio_input, **diarize_kwargs)

        # Extract (start, end, speaker) turns from pyannote output
        dia_turns: List[tuple] = [
            (turn.start, turn.end, speaker)
            for turn, _, speaker in diarization.itertracks(yield_label=True)
        ]
        logger.info(f"[pyannote] {len(dia_turns)} diarization turns found")

        # Assign speaker to each Whisper segment by maximum time overlap
        for seg in segments:
            best_speaker = ""
            best_overlap = 0.0
            for d_start, d_end, speaker in dia_turns:
                overlap = min(seg.end_time, d_end) - max(seg.start_time, d_start)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = speaker
            seg.speaker_id = best_speaker

        logger.info("[pyannote] Speaker IDs assigned ✓")
        return segments

    except Exception as e:
        logger.error(f"[pyannote] Diarization failed — returning original segments: {e}")
        return segments
