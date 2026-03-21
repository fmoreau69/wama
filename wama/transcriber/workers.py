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


def _console(user_id: int, message: str, level: str = None) -> None:
    """Send message to user's console."""
    try:
        if level is None:
            msg_lower = message.lower()
            if any(w in msg_lower for w in ['error', 'failed', '\u2717', 'erreur']):
                level = 'error'
            elif any(w in msg_lower for w in ['warning', 'attention']):
                level = 'warning'
            elif any(w in msg_lower for w in ['[debug]', '[parallel']):
                level = 'debug'
            else:
                level = 'info'
        push_console_line(user_id, message, level=level, app='transcriber')
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


def _get_output_stem(transcript: Transcript, backend_name: str) -> str:
    """Build the output filename stem: {input_stem}_{backend}."""
    input_stem = os.path.splitext(os.path.basename(transcript.audio.name))[0]
    return f"{input_stem}_{backend_name}" if backend_name else input_stem


def _get_output_dir(transcript: Transcript) -> str:
    """Get (and create) the output directory for a transcript."""
    from wama.common.utils.media_paths import get_app_media_path
    output_dir = get_app_media_path('transcriber', transcript.user_id, 'output')
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir)


def _build_txt_content(transcript: Transcript) -> str:
    """
    Build enriched TXT content:
      - Full transcription text
      - Diarization table (if segments exist)
      - LLM summary / meeting notes (if generated)
      - Coherence report (if verified)
    """
    parts: list[str] = []

    # ── 1. Transcription ──────────────────────────────────────────────────
    parts.append("=" * 60)
    parts.append("TRANSCRIPTION")
    parts.append("=" * 60)
    parts.append(transcript.text or '')
    parts.append('')

    # ── 2. Diarisation ────────────────────────────────────────────────────
    segments = TranscriptSegment.objects.filter(transcript=transcript).order_by('order')
    if segments.exists() and any(s.speaker_id for s in segments):
        parts.append("=" * 60)
        parts.append("DIARISATION — LOCUTEURS")
        parts.append("=" * 60)
        for seg in segments:
            speaker = seg.speaker_id or 'Inconnu'
            time_range = seg.format_time_range()
            parts.append(f"[{speaker}]  {time_range}")
            parts.append(f"  {seg.text}")
            parts.append('')

    # ── 3. Résumé LLM ────────────────────────────────────────────────────
    if transcript.summary:
        parts.append("=" * 60)
        label = "COMPTE-RENDU DE RÉUNION" if transcript.summary_type == 'meeting' else "RÉSUMÉ"
        parts.append(label)
        parts.append("=" * 60)
        parts.append(transcript.summary)
        if transcript.key_points:
            parts.append('')
            parts.append("Points clés :")
            for kp in transcript.key_points:
                parts.append(f"  • {kp}")
        if transcript.action_items:
            parts.append('')
            parts.append("Actions :")
            for ai in transcript.action_items:
                parts.append(f"  • {ai}")
        parts.append('')

    # ── 4. Vérification de cohérence ──────────────────────────────────────
    if transcript.coherence_score is not None:
        parts.append("=" * 60)
        parts.append("VÉRIFICATION DE COHÉRENCE")
        parts.append("=" * 60)
        parts.append(f"Score : {transcript.coherence_score}/100")
        if transcript.coherence_notes:
            parts.append('')
            parts.append("Problèmes détectés :")
            for note in transcript.coherence_notes.splitlines():
                if note.strip():
                    parts.append(f"  • {note.strip()}")
        if (transcript.coherence_suggestion
                and transcript.coherence_suggestion.strip() != transcript.text.strip()):
            parts.append('')
            parts.append("Version corrigée proposée :")
            parts.append("-" * 40)
            parts.append(transcript.coherence_suggestion)
        parts.append('')

    return '\n'.join(parts)


def _save_output_files(transcript: Transcript, backend_name: str) -> None:
    """Save SRT (after diarization) and enriched TXT (after all steps) to output folder."""
    try:
        output_dir = _get_output_dir(transcript)
        stem = _get_output_stem(transcript, backend_name)

        # ── SRT (diarization-aware) ────────────────────────────────────────
        segments = TranscriptSegment.objects.filter(transcript=transcript).order_by('order')
        if segments.exists():
            srt_content = ''
            for i, seg in enumerate(segments, 1):
                srt_content += seg.to_srt_entry(i)
        elif transcript.text:
            srt_content = f"1\n00:00:00,000 --> 00:00:00,000\n{transcript.text}\n\n"
        else:
            srt_content = ''

        if srt_content:
            srt_path = os.path.join(output_dir, f"{stem}.srt")
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

        # ── TXT (enriched — called AFTER summary + coherence) ─────────────
        txt_path = os.path.join(output_dir, f"{stem}.txt")
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(_build_txt_content(transcript))

        _console(transcript.user_id, f"Fichiers de sortie sauvegardés: {stem}.txt / .srt")
    except Exception as e:
        _console(transcript.user_id, f"Avertissement: sauvegarde fichiers de sortie échouée ({e})")


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

        _set_progress(t, 75)

        # Step 4b: Pyannote diarization (Whisper + Qwen3-ASR — VibeVoice has its own)
        if backend.name in ('whisper', 'qwen_asr') and t.enable_diarization and result.segments:
            try:
                from .backends.pyannote_diarizer import is_available as pyannote_ok, diarize
                if pyannote_ok():
                    _console(t.user_id, "Diarisation des locuteurs (pyannote)…")
                    _set_partial_text(t.id, "🔎 Identification des locuteurs…\n")
                    result.segments = diarize(cleaned_path, result.segments)
                    _console(t.user_id, "Diarisation terminée ✓")
                else:
                    _console(t.user_id, "pyannote non disponible, diarisation ignorée", level='warning')
            except Exception as dia_err:
                _console(t.user_id, f"Avertissement: diarisation échouée ({dia_err})", level='warning')

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
        _set_progress(t, 90)
        t.save(update_fields=['text', 'language', 'used_backend', 'status', 'segments_json'])

        # Step 6: Save output files (TXT + SRT) to output folder
        _save_output_files(t, backend.name)
        _set_progress(t, 95)

        # Unload the ASR model NOW — before LLM steps — to free GPU VRAM for Ollama
        try:
            backend.unload()
        except Exception:
            pass

        # Step 7: Optional LLM summary (structured or meeting compte-rendu)
        if t.generate_summary and t.text:
            try:
                _set_partial_text(t.id, t.text + "\n\n⏳ Génération du résumé en cours…")
                from wama.common.utils.llm_utils import (
                    generate_structured_summary, generate_meeting_summary,
                )
                lang = t.language or 'fr'

                if t.summary_type == 'meeting':
                    _console(t.user_id, "Génération du compte-rendu de réunion (Ollama)…")
                    # Collect identified speakers from diarized segments if available
                    speakers = list(
                        TranscriptSegment.objects.filter(transcript=t)
                        .exclude(speaker_id='')
                        .values_list('speaker_id', flat=True)
                        .distinct()
                    )
                    t.summary = generate_meeting_summary(t.text, language=lang, speakers=speakers or None)
                    t.key_points = []
                    t.action_items = []
                else:
                    _console(t.user_id, "Génération du résumé LLM (Ollama)…")
                    summary_data = generate_structured_summary(
                        t.text, content_hint='transcription', language=lang,
                    )
                    t.summary = summary_data['summary']
                    t.key_points = summary_data['key_points']
                    t.action_items = summary_data['action_items']

                t.save(update_fields=['summary', 'key_points', 'action_items'])
                _console(t.user_id, "Résumé LLM généré ✓")
            except Exception as llm_err:
                _console(t.user_id, f"Avertissement: résumé LLM échoué ({llm_err})", level='warning')

        # Step 8: Optional coherence verification
        if t.verify_coherence and t.text:
            try:
                _console(t.user_id, "Vérification de cohérence (Ollama)…")
                from wama.common.utils.llm_utils import verify_text_coherence
                coherence = verify_text_coherence(t.text, 'transcription', t.language or 'fr')
                t.coherence_score = coherence['score']
                t.coherence_notes = '\n'.join(coherence['notes'])
                t.coherence_suggestion = coherence['suggestion']
                t.save(update_fields=['coherence_score', 'coherence_notes', 'coherence_suggestion'])
                _console(t.user_id, f"Cohérence vérifiée — score: {coherence['score']}/100 ✓")
            except Exception as coh_err:
                _console(t.user_id, f"Avertissement: vérification cohérence échouée ({coh_err})", level='warning')

        _set_progress(t, 100)
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

    # Delegate to main task (Celery injects self automatically for bind=True)
    return transcribe(transcript_id)


@shared_task(bind=True, name='wama.transcriber.enrich_transcript')
def enrich_transcript(self, transcript_id: int, summary_type: str = 'structured'):
    """
    On-demand LLM enrichment of an already-transcribed item.

    Runs generate_structured_summary or generate_meeting_summary on the
    existing transcript text and saves the result without re-running STT.
    """
    close_old_connections()

    try:
        t = Transcript.objects.select_related('user').get(pk=transcript_id)
    except Transcript.DoesNotExist:
        return {'ok': False, 'error': f'Transcript {transcript_id} introuvable'}

    if not t.text:
        return {'ok': False, 'error': 'Pas de texte transcrit'}

    user_id = t.user_id
    lang = t.language or 'fr'

    try:
        push_console_line(user_id, f"[Transcriber] Enrichissement LLM — type: {summary_type}…", app='transcriber')
        from wama.common.utils.llm_utils import (
            generate_structured_summary, generate_meeting_summary,
        )

        if summary_type == 'meeting':
            speakers = list(
                TranscriptSegment.objects.filter(transcript=t)
                .exclude(speaker_id='')
                .values_list('speaker_id', flat=True)
                .distinct()
            )
            t.summary = generate_meeting_summary(t.text, language=lang, speakers=speakers or None)
            t.key_points = []
            t.action_items = []
        else:
            summary_data = generate_structured_summary(
                t.text, content_hint='transcription', language=lang,
            )
            t.summary = summary_data['summary']
            t.key_points = summary_data['key_points']
            t.action_items = summary_data['action_items']

        t.save(update_fields=['summary', 'key_points', 'action_items'])
        push_console_line(user_id, f"[Transcriber] Enrichissement terminé ✓", app='transcriber')
        return {'ok': True}

    except Exception as exc:
        push_console_line(user_id, f"[Transcriber] Enrichissement échoué : {exc}", app='transcriber', level='error')
        return {'ok': False, 'error': str(exc)}
