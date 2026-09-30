"""
Transcriber Backends Package

Provides pluggable speech-to-text backends for the Transcriber application.

Available backends:
- whisper:   faster-whisper (CTranslate2) — fast, reliable, many model sizes
- qwen_asr:  Qwen3-ASR (Alibaba) — context biasing, 52 languages, low VRAM
- vibevoice: Microsoft VibeVoice ASR 7B — native diarization + timestamps (16 GB VRAM, install from GitHub)

Usage:
    from wama.transcriber.backends import get_backend, get_available_backends

    # Get best available backend
    backend = get_backend()

    # Get the backend of a catalogue model (or an old engine name: 'whisper', 'qwen_asr'…)
    backend = get_backend('transcriber:qwen3-asr-1.7b')

    # Transcribe
    result = backend.transcribe('/path/to/audio.mp3', hotwords='WAMA, transcription')
"""

from wama.common.backends.speech_to_text_base import (
    SpeechToTextBackend,
    TranscriptionResult,
    TranscriptionSegment,
)

from .manager import (
    TranscriberBackendManager,
    get_backend,
    get_available_backends,
)

__all__ = [
    # Base classes
    'SpeechToTextBackend',
    'TranscriptionResult',
    'TranscriptionSegment',
    # Manager
    'TranscriberBackendManager',
    'get_backend',
    'get_available_backends',
]
