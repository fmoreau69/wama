from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections
from django.conf import settings

from .models import Transcript

try:
    import whisper  # optional dependency; small/medium models as needed
except Exception:  # pragma: no cover
    whisper = None


@shared_task(bind=True)
def transcribe(self, transcript_id: int):
    close_old_connections()
    t = Transcript.objects.get(pk=transcript_id)
    # Mark start
    cache.set(f"transcriber_progress_{t.id}", 5, timeout=3600)

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
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            cache.set(f"transcriber_progress_{t.id}", 90, timeout=3600)
            with open(out_txt, 'r', encoding='utf-8', errors='ignore') as f:
                t.text = f.read()
            t.status = 'SUCCESS'
            cache.set(f"transcriber_progress_{t.id}", 100, timeout=3600)
            t.save(update_fields=['text', 'status'])
            return { 'ok': True, 'engine': 'speech_to_text_transcriptor' }
        except Exception:
            # 2) fallback whisper
            if whisper is None:
                raise RuntimeError('No STT engine available (install whisper or speech_to_text_transcriptor)')
            model = whisper.load_model('base')
            cache.set(f"transcriber_progress_{t.id}", 20, timeout=3600)
            result = model.transcribe(t.audio.path)
            t.text = result.get('text', '')
            t.language = result.get('language', '')
            t.status = 'SUCCESS'
            cache.set(f"transcriber_progress_{t.id}", 100, timeout=3600)
            t.save(update_fields=['text', 'language', 'status'])
            return { 'ok': True, 'engine': 'whisper' }
    except Exception as e:
        t.status = 'FAILURE'
        t.save(update_fields=['status'])
        cache.set(f"transcriber_progress_{t.id}", 0, timeout=3600)
        return { 'ok': False, 'error': str(e) }
