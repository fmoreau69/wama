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

    import os
    import torch

    # ── CRITICAL: set HF_HUB_CACHE BEFORE importing pyannote/huggingface_hub ──
    # This routes all sub-downloads (weights, configs) to speech/diarization/
    # instead of the global AI-models/cache/huggingface/ fallback.
    try:
        from pathlib import Path
        from django.conf import settings as _s
        _dia_dir = _s.MODEL_PATHS.get('speech', {}).get(
            'diarization',
            _s.AI_MODELS_DIR / "models" / "speech" / "diarization"
        )
        Path(_dia_dir).mkdir(parents=True, exist_ok=True)
        _cache = str(_dia_dir)
        os.environ['HF_HUB_CACHE'] = _cache
        os.environ['HUGGINGFACE_HUB_CACHE'] = _cache
        logger.info(f"[pyannote] Cache → {_cache}")
    except Exception:
        pass

    from pyannote.audio import Pipeline

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
    Load audio into the {'waveform': tensor, 'sample_rate': int} dict expected by
    pyannote, bypassing its torchcodec/FFmpeg decoder (cassé dans ce venv).

    Délègue au helper commun `common/utils/audio_decode.decode_for_pyannote`
    (chaîne robuste soundfile → faster-whisper/PyAV → ffmpeg, gère m4a/mp3/aac).
    En cas d'échec total, on renvoie le chemin brut (dernier recours pyannote).
    """
    try:
        from wama.common.utils.audio_decode import decode_for_pyannote
        return decode_for_pyannote(audio_path, target_sr=16000)
    except Exception as e:
        logger.warning(f"[pyannote] decode failed ({e}), passing raw path")
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

        # Compat pyannote 3.x (Annotation, .itertracks) ↔ 4.x (DiarizeOutput :
        # l'Annotation est dans .speaker_diarization / .diarization).
        annotation = diarization
        if not hasattr(annotation, 'itertracks'):
            annotation = (getattr(diarization, 'speaker_diarization', None)
                          or getattr(diarization, 'diarization', None)
                          or annotation)

        # Extract (start, end, speaker) turns from pyannote output
        dia_turns: List[tuple] = [
            (turn.start, turn.end, speaker)
            for turn, _, speaker in annotation.itertracks(yield_label=True)
        ]
        logger.info(f"[pyannote] {len(dia_turns)} diarization turns found")

        # Assign speaker to each Whisper segment by maximum time overlap
        unassigned = 0
        for seg in segments:
            best_speaker = ""
            best_overlap = 0.0
            for d_start, d_end, speaker in dia_turns:
                overlap = min(seg.end_time, d_end) - max(seg.start_time, d_start)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = speaker
            # Aucun recouvrement (mot isolé dans un trou entre deux tours) → on rattache au
            # locuteur du tour le PLUS PROCHE, plutôt que de laisser un segment sans locuteur
            # (sinon il apparaît « non identifié » et fausse le compte des intervenants).
            if not best_speaker:
                mid = (seg.start_time + seg.end_time) / 2.0
                nearest, ndist = "", float('inf')
                for d_start, d_end, speaker in dia_turns:
                    dist = (d_start - mid) if mid < d_start else (mid - d_end if mid > d_end else 0.0)
                    if dist < ndist:
                        ndist, nearest = dist, speaker
                best_speaker = nearest
                unassigned += 1
            seg.speaker_id = best_speaker

        logger.info(f"[pyannote] Speaker IDs assigned ✓ ({unassigned} segment(s) rattaché(s) au plus proche)")
        return segments

    except Exception as e:
        logger.error(f"[pyannote] Diarization failed — returning original segments: {e}")
        return segments
