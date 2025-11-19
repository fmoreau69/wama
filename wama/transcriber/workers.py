import torch
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections

from .models import Transcript
from wama.medias.utils.console_utils import push_console_line

try:
    import whisper  # optional dependency; small/medium models as needed
except Exception:  # pragma: no cover
    whisper = None

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def _set_progress(transcript: Transcript, value: int) -> None:
    cache.set(f"transcriber_progress_{transcript.id}", value, timeout=3600)
    Transcript.objects.filter(pk=transcript.id).update(progress=value)


def _console(user_id: int, message: str) -> None:
    try:
        push_console_line(user_id, f"[Transcriber] {message}")
    except Exception:
        pass


@shared_task(bind=True)
def transcribe(self, transcript_id: int):
    close_old_connections()
    t = Transcript.objects.get(pk=transcript_id)
    _set_progress(t, 5)
    _console(t.user_id, f"Transcription {t.id} démarrée.")

    try:
        # Choose backend: try speech_to_text_transcriptor CLI if present; otherwise fallback to whisper
        # 1) speech_to_text_transcriptor
        try:
            import subprocess, os
            audio_path = t.audio.path
            out_dir = os.path.dirname(audio_path)
            out_txt = os.path.join(out_dir, f"transcript_{t.id}.txt")
            cmd = [
                'python', '-m', 'speech_to_text_transcriptor.cli',
                '--audio', audio_path,
                '--output', out_txt,
            ]
            _console(t.user_id, f"Utilisation du moteur CLI sur {os.path.basename(audio_path)}")
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            _set_progress(t, 90)
            with open(out_txt, 'r', encoding='utf-8', errors='ignore') as f:
                t.text = f.read()
            t.status = 'SUCCESS'
            _set_progress(t, 100)
            t.save(update_fields=['text', 'status'])
            _console(t.user_id, f"Transcription {t.id} terminée (CLI).")
            return { 'ok': True, 'engine': 'speech_to_text_transcriptor' }
        except Exception:
            # 2) fallback whisper
            if whisper is None:
                raise RuntimeError('No STT engine available (install whisper or speech_to_text_transcriptor)')
            model = whisper.load_model('base', device=DEVICE)
            _console(t.user_id, f"Moteur Whisper (base) en cours...")
            _set_progress(t, 20)
            result = model.transcribe(t.audio.path)
            t.text = result.get('text', '')
            t.language = result.get('language', '')
            t.status = 'SUCCESS'
            _set_progress(t, 100)
            t.save(update_fields=['text', 'language', 'status'])
            _console(t.user_id, f"Transcription {t.id} terminée (Whisper).")
            return { 'ok': True, 'engine': 'whisper' }
    except Exception as e:
        t.status = 'FAILURE'
        t.save(update_fields=['status'])
        _set_progress(t, 0)
        _console(t.user_id, f"Erreur transcription {t.id}: {e}")
        return { 'ok': False, 'error': str(e) }
