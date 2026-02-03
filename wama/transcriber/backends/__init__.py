"""
Transcriber Backends Package

Provides pluggable speech-to-text backends for the Transcriber application.

Available backends:
- whisper: OpenAI Whisper (fast, good accuracy)
- vibevoice: Microsoft VibeVoice ASR (diarization, timestamps, hotwords)

Usage:
    from wama.transcriber.backends import get_backend, get_available_backends

    # Get best available backend
    backend = get_backend()

    # Get specific backend
    backend = get_backend('whisper')

    # Transcribe
    result = backend.transcribe('/path/to/audio.mp3')
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
