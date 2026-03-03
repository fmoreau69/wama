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

    # Get specific backend
    backend = get_backend('qwen_asr')  # or 'whisper', 'vibevoice'

    # Transcribe
    result = backend.transcribe('/path/to/audio.mp3', hotwords='WAMA, transcription')
"""

from .base import (
    SpeechToTextBackend,
    TranscriptionResult,
    TranscriptionSegment,
)

from .manager import (
    TranscriberBackendManager,
    get_backend,
    get_available_backends,
    get_backends_info,
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
    'get_backends_info',
]
