"""
Transcriber Celery Workers

Background tasks for audio transcription using pluggable backends.
"""

import os
import torch
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections

from .models import Transcript, TranscriptSegment
from wama.common.utils.console_utils import push_console_line

# Import backend system
try:
    from .backends import get_backend, get_available_backends, TranscriptionResult
    BACKENDS_AVAILABLE = True
except ImportError:
    BACKENDS_AVAILABLE = False

# Import audio preprocessor
try:
    from .utils.audio_preprocessor import AudioPreprocessor
except Exception:
    AudioPreprocessor = None

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def _set_progress(transcript: Transcript, value: int, *, force: bool = False) -> None:
    """Update transcript progress in cache and database."""
    key = f"transcriber_progress_{transcript.id}"
    current = cache.get(key)
    if current is None:
        current = Transcript.objects.filter(pk=transcript.id).values_list('progress', flat=True).first()
    if not force and current is not None and value < current and value != 0:
        value = int(current)
    cache.set(key, value, timeout=3600)
    Transcript.objects.filter(pk=transcript.id).update(progress=value)


def _console(user_id: int, message: str) -> None:
    """Send message to user's console."""
    try:
        push_console_line(user_id, f"[Transcriber] {message}")
    except Exception:
        pass


def _set_partial_text(transcript_id: int, text: str) -> None:
    """Store partial transcription text in cache for live display."""
    key = f"transcriber_partial_text_{transcript_id}"
    cache.set(key, text, timeout=3600)


def _preprocess_audio(transcript: Transcript, audio_path: str) -> str:
    """
    Preprocess audio file for better transcription quality.

    Args:
        transcript: Transcript instance
        audio_path: Path to original audio file

    Returns:
        Path to preprocessed audio file (or original if preprocessing fails)
    """
    if AudioPreprocessor is None:
        return audio_path

    try:
        _console(transcript.user_id, "Prétraitement audio en cours...")
        _set_progress(transcript, 10)

        preprocessor = AudioPreprocessor(
            target_sr=16000,
            noise_reduction=0.5,
            stationary=False
        )

        base_name = os.path.splitext(audio_path)[0]
        cleaned_path = f"{base_name}_cleaned.wav"
        result_path = preprocessor.preprocess(audio_path, cleaned_path)

        _console(transcript.user_id, "Prétraitement terminé ✓")
        _set_progress(transcript, 15)

        return result_path

    except Exception as e:
        _console(transcript.user_id, f"Avertissement: prétraitement échoué ({e}), utilisation du fichier original")
        return audio_path


def _save_segments(transcript: Transcript, result: 'TranscriptionResult') -> int:
    """
    Save transcription segments to database.

    Args:
        transcript: Transcript instance
        result: TranscriptionResult with segments

    Returns:
        Number of segments saved
    """
    if not result.segments:
        return 0

    # Delete existing segments
    TranscriptSegment.objects.filter(transcript=transcript).delete()

    # Create new segments
    segments_to_create = []
    for i, seg in enumerate(result.segments):
        segments_to_create.append(TranscriptSegment(
            transcript=transcript,
            speaker_id=seg.speaker_id,
            start_time=seg.start_time,
            end_time=seg.end_time,
            text=seg.text,
            confidence=seg.confidence,
            order=i
        ))

    TranscriptSegment.objects.bulk_create(segments_to_create)

    # Also save segments as JSON backup
    transcript.segments_json = [s.to_dict() for s in result.segments]
    transcript.save(update_fields=['segments_json'])

    return len(segments_to_create)


@shared_task(bind=True)
def transcribe(self, transcript_id: int):
    """
    Main transcription task with preprocessing and backend selection.

    Uses the backend system to select the best available engine.
    Supports VibeVoice (diarization) and Whisper backends.
    """
    close_old_connections()
    t = Transcript.objects.get(pk=transcript_id)
    _set_progress(t, 5, force=True)
    _console(t.user_id, f"Transcription {t.id} démarrée.")

    _set_partial_text(t.id, "🎙️ Transcription en cours...\n")

    audio_path = t.audio.path
    cleaned_path = None

    try:
        # Step 1: Preprocessing (if enabled)
        if t.preprocess_audio:
            _set_partial_text(t.id, "🔧 Prétraitement audio...\n")
            cleaned_path = _preprocess_audio(t, audio_path)
        else:
            cleaned_path = audio_path

        # Step 2: Get backend
        if not BACKENDS_AVAILABLE:
            raise RuntimeError("Backend system not available")

        backend_name = t.backend if t.backend and t.backend != 'auto' else None
        backend = get_backend(backend_name)

        _console(t.user_id, f"Utilisation de {backend.display_name}...")
        _set_progress(t, 20)
        _set_partial_text(t.id, f"📥 Chargement de {backend.display_name}...\n\n")

        # Step 3: Load model
        if not backend.load():
            raise RuntimeError(f"Failed to load {backend.display_name}")

        _console(t.user_id, f"{backend.display_name} chargé sur {DEVICE}")
        _set_progress(t, 30)
        _set_partial_text(t.id, "🎯 Transcription en cours...\n\nCela peut prendre quelques instants selon la durée de l'audio.\n")

        # Step 4: Transcribe
        _console(t.user_id, "Transcription en cours...")

        # Build kwargs for transcription
        transcribe_kwargs = {}
        if t.hotwords:
            transcribe_kwargs['hotwords'] = t.hotwords
        if t.temperature > 0:
            transcribe_kwargs['temperature'] = t.temperature
            transcribe_kwargs['do_sample'] = True
        if t.max_tokens != 32768:
            transcribe_kwargs['max_tokens'] = t.max_tokens

        result: TranscriptionResult = backend.transcribe(
            audio_path=cleaned_path,
            **transcribe_kwargs
        )

        if not result.success:
            raise RuntimeError(result.error or "Transcription failed")

        _set_progress(t, 80)

        # Step 5: Save results
        t.text = result.text
        t.language = result.language
        t.used_backend = backend.name
        t.status = 'SUCCESS'

        # Save segments if available (diarization)
        num_segments = _save_segments(t, result)
        if num_segments > 0:
            _console(t.user_id, f"{num_segments} segments avec diarisation sauvegardés")

        _set_partial_text(t.id, t.text)
        _set_progress(t, 100)
        t.save(update_fields=['text', 'language', 'used_backend', 'status', 'segments_json'])

        _console(t.user_id, f"Transcription {t.id} terminée ({backend.display_name}) ✓")

        # Unload model to free memory
        try:
            backend.unload()
        except Exception:
            pass

        return {
            'ok': True,
            'engine': backend.name,
            'preprocessed': t.preprocess_audio,
            'segments': num_segments,
            'language': result.language
        }

    except Exception as e:
        import traceback
        error_msg = str(e)
        _console(t.user_id, f"Erreur transcription {t.id}: {error_msg}")
        print(f"[Transcriber] Error: {traceback.format_exc()}")

        t.status = 'FAILURE'
        t.save(update_fields=['status'])
        _set_progress(t, 0, force=True)
        _set_partial_text(t.id, f"❌ Erreur lors de la transcription:\n\n{error_msg}")

        return {'ok': False, 'error': error_msg}

    finally:
        # Cleanup: remove preprocessed temporary file
        if cleaned_path and cleaned_path != audio_path and os.path.exists(cleaned_path):
            try:
                os.remove(cleaned_path)
                _console(t.user_id, "Fichier temporaire nettoyé")
            except OSError as e:
                _console(t.user_id, f"Avertissement: impossible de supprimer {cleaned_path}: {e}")


@shared_task(bind=True)
def transcribe_without_preprocessing(self, transcript_id: int):
    """
    Transcription task without audio preprocessing.

    Delegates to the main transcribe task after disabling preprocessing.
    """
    close_old_connections()

    # Update transcript to disable preprocessing
    Transcript.objects.filter(pk=transcript_id).update(preprocess_audio=False)

    # Delegate to main task
    return transcribe(self, transcript_id)
