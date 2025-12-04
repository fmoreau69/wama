import os
import torch
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections

from .models import Transcript
from wama.anonymizer.utils.console_utils import push_console_line

try:
    from .utils.audio_preprocessor import AudioPreprocessor
except Exception:  # pragma: no cover
    AudioPreprocessor = None  # type: ignore

try:
    import whisper  # optional dependency; small/medium models as needed
except Exception:  # pragma: no cover
    whisper = None

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def _set_progress(transcript: Transcript, value: int, *, force: bool = False) -> None:
    key = f"transcriber_progress_{transcript.id}"
    current = cache.get(key)
    if current is None:
        current = Transcript.objects.filter(pk=transcript.id).values_list('progress', flat=True).first()
    if not force and current is not None and value < current and value != 0:
        value = int(current)
    cache.set(key, value, timeout=3600)
    Transcript.objects.filter(pk=transcript.id).update(progress=value)


def _console(user_id: int, message: str) -> None:
    try:
        push_console_line(user_id, f"[Transcriber] {message}")
    except Exception:
        pass


def _preprocess_audio(transcript: Transcript, audio_path: str) -> str:
    """
    Prétraite le fichier audio pour améliorer la qualité de transcription.

    Args:
        transcript: Instance du Transcript
        audio_path: Chemin du fichier audio original

    Returns:
        str: Chemin du fichier audio prétraité (ou original si échec)
    """
    if AudioPreprocessor is None:
        return audio_path

    try:
        _console(transcript.user_id, f"Prétraitement audio en cours...")
        _set_progress(transcript, 10)

        # Initialiser le preprocessor
        preprocessor = AudioPreprocessor(
            target_sr=16000,
            noise_reduction=0.5,  # Niveau modéré par défaut
            stationary=False  # Adapté à la parole
        )

        # Générer le chemin du fichier nettoyé
        base_name = os.path.splitext(audio_path)[0]
        cleaned_path = f"{base_name}_cleaned.wav"

        # Prétraiter l'audio
        result_path = preprocessor.preprocess(audio_path, cleaned_path)

        _console(transcript.user_id, f"Prétraitement terminé ✓")
        _set_progress(transcript, 15)

        return result_path

    except Exception as e:
        _console(transcript.user_id, f"Avertissement: prétraitement échoué ({e}), utilisation du fichier original")
        return audio_path


@shared_task(bind=True)
def transcribe(self, transcript_id: int):
    """
    Tâche Celery pour transcrire un fichier audio.
    Intègre le prétraitement audio avant la transcription.
    """
    close_old_connections()
    t = Transcript.objects.get(pk=transcript_id)
    _set_progress(t, 5, force=True)
    _console(t.user_id, f"Transcription {t.id} démarrée.")

    audio_path = t.audio.path
    cleaned_path = None

    try:
        # Étape 1: Prétraitement audio
        cleaned_path = _preprocess_audio(t, audio_path)

        # Étape 2: Transcription
        # Choice backend: try speech_to_text_transcriptor CLI if present; otherwise fallback to whisper

        # 1) Tentative avec speech_to_text_transcriptor CLI
        try:
            import subprocess
            out_dir = os.path.dirname(audio_path)
            out_txt = os.path.join(out_dir, f"transcript_{t.id}.txt")

            cmd = [
                'python', '-m', 'speech_to_text_transcriptor.cli',
                '--audio', cleaned_path,  # Utiliser le fichier prétraité
                '--output', out_txt,
            ]

            _console(t.user_id, f"Utilisation du moteur CLI sur {os.path.basename(cleaned_path)}")
            _set_progress(t, 20)

            subprocess.run(cmd, check=True, capture_output=True, text=True)
            _set_progress(t, 90)

            with open(out_txt, 'r', encoding='utf-8', errors='ignore') as f:
                t.text = f.read()

            t.status = 'SUCCESS'
            _set_progress(t, 100)
            t.save(update_fields=['text', 'status'])
            _console(t.user_id, f"Transcription {t.id} terminée (CLI) ✓")

            return {'ok': True, 'engine': 'speech_to_text_transcriptor', 'preprocessed': True}

        except Exception as cli_error:
            # 2) Fallback vers Whisper
            if whisper is None:
                raise RuntimeError('No STT engine available (install whisper or speech_to_text_transcriptor)')

            _console(t.user_id, f"Moteur Whisper (base) en cours...")
            _set_progress(t, 20)

            # Charger le modèle Whisper
            model = whisper.load_model('base', device=DEVICE)
            _console(t.user_id, f"Modèle Whisper chargé sur {DEVICE}")
            _set_progress(t, 30)

            # Transcrire le fichier prétraité
            _console(t.user_id, f"Transcription en cours...")
            result = model.transcribe(cleaned_path)

            t.text = result.get('text', '')
            t.language = result.get('language', '')
            t.status = 'SUCCESS'
            _set_progress(t, 100)
            t.save(update_fields=['text', 'language', 'status'])

            _console(t.user_id, f"Transcription {t.id} terminée (Whisper) ✓")

            return {'ok': True, 'engine': 'whisper', 'preprocessed': True}

    except Exception as e:
        t.status = 'FAILURE'
        t.save(update_fields=['status'])
        _set_progress(t, 0, force=True)
        _console(t.user_id, f"Erreur transcription {t.id}: {e}")
        return {'ok': False, 'error': str(e)}

    finally:
        # Nettoyage: supprimer le fichier audio prétraité temporaire
        if cleaned_path and cleaned_path != audio_path and os.path.exists(cleaned_path):
            try:
                os.remove(cleaned_path)
                _console(t.user_id, f"Fichier temporaire nettoyé")
            except OSError as e:
                _console(t.user_id, f"Avertissement: impossible de supprimer {cleaned_path}: {e}")


@shared_task(bind=True)
def transcribe_without_preprocessing(self, transcript_id: int):
    """
    Tâche alternative sans prétraitement audio (pour comparaison).
    """
    close_old_connections()
    t = Transcript.objects.get(pk=transcript_id)
    _set_progress(t, 5, force=True)
    _console(t.user_id, f"Transcription {t.id} démarrée (sans prétraitement).")

    try:
        audio_path = t.audio.path

        # Tentative avec speech_to_text_transcriptor CLI
        try:
            import subprocess
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
            return {'ok': True, 'engine': 'speech_to_text_transcriptor', 'preprocessed': False}
        except Exception:
            # Fallback whisper
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
            return {'ok': True, 'engine': 'whisper', 'preprocessed': False}
    except Exception as e:
        t.status = 'FAILURE'
        t.save(update_fields=['status'])
        _set_progress(t, 0, force=True)
        _console(t.user_id, f"Erreur transcription {t.id}: {e}")
        return {'ok': False, 'error': str(e)}