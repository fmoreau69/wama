"""
WAMA Synthesizer - Celery Workers
Tâches de synthèse vocale avec TTS

All TTS generation is delegated to the TTS microservice (tts_service.py)
running on TTS_SERVICE_URL (default: http://localhost:8001).
"""

import os
import re
import unicodedata
import logging
import tempfile
import requests
from celery import shared_task
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.core.files.base import ContentFile

from .models import VoiceSynthesis
from wama.common.utils.console_utils import push_console_line
from .utils.text_extractor import extract_text_from_file
from .utils.audio_processor import process_audio_output

logger = logging.getLogger(__name__)

# TTS microservice URL
TTS_SERVICE_URL = getattr(settings, 'TTS_SERVICE_URL', 'http://localhost:8001')

# Request timeout for TTS service (seconds).
# 600s allows for long texts (75+ words) even under RAM pressure.
# The reduced max_tokens formula prevents runaway generation for short texts.
TTS_TIMEOUT = 600

# Raised when the TTS service responds 503 "loading" — triggers a Celery retry
class TTSServiceLoadingError(Exception):
    pass


def _tts_via_service(text, model, language='fr', voice_preset='default',
                     speaker_wav=None, multi_speaker=False,
                     scene_description='', options=None):
    """
    Call the TTS microservice to generate audio.

    Args:
        text: Text to synthesize
        model: Model name (xtts_v2, bark, higgs_audio, etc.)
        language: Language code
        voice_preset: Voice preset name
        speaker_wav: Path to speaker reference WAV (for voice cloning)
        multi_speaker: Enable multi-speaker mode (Higgs)
        scene_description: Scene description for multi-speaker (Higgs)
        options: Additional options dict

    Returns:
        str: Path to temporary WAV file with generated audio

    Raises:
        RuntimeError: If the TTS service is unavailable or returns an error
    """
    payload = {
        'text': text,
        'model': model,
        'language': language,
        'voice_preset': voice_preset,
        'speaker_wav': speaker_wav,
        'multi_speaker': multi_speaker,
        'scene_description': scene_description,
        'options': options or {},
    }

    try:
        resp = requests.post(
            f"{TTS_SERVICE_URL}/tts",
            json=payload,
            timeout=(5, TTS_TIMEOUT),  # (connect_timeout, read_timeout)
        )
        resp.raise_for_status()
    except requests.ConnectionError:
        raise RuntimeError(
            f"TTS service unavailable at {TTS_SERVICE_URL}. "
            "Start it with: python -m uvicorn tts_service:app --port 8001"
        )
    except requests.Timeout:
        raise RuntimeError(f"TTS service timed out after {TTS_TIMEOUT}s")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 503:
            try:
                # FastAPI wraps detail: {"detail": {"status": "loading", ...}}
                body = e.response.json()
                detail_obj = body.get("detail", {}) if isinstance(body, dict) else {}
                if isinstance(detail_obj, dict) and detail_obj.get("status") == "loading":
                    raise TTSServiceLoadingError(detail_obj.get("message", "TTS service is still loading"))
            except TTSServiceLoadingError:
                raise
            except Exception:
                pass
        detail = ""
        try:
            detail_raw = e.response.json().get("detail") or ""
            detail = str(detail_raw)
        except Exception:
            detail = e.response.text[:200] if e.response else ""
        raise RuntimeError(f"TTS service error: {detail or str(e)}")

    # Save WAV bytes to a temp file
    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    tmp.write(resp.content)
    tmp.close()
    return tmp.name


def _get_default_speaker_wav(voice_preset: str) -> str:
    """
    Retourne le chemin vers un fichier audio de référence par défaut.
    Délègue à voice_utils.resolve_voice_preset() pour la résolution.
    Si aucun fichier trouvé pour le preset, télécharge les samples LJSpeech en fallback.

    Args:
        voice_preset: Le preset de voix sélectionné

    Returns:
        str: Chemin vers le fichier audio de référence, ou None
    """
    import urllib.request
    from wama.synthesizer.utils.voice_utils import resolve_voice_preset, get_voice_refs_dir

    # 1. Essayer la résolution directe (nouveau format ou héritage)
    resolved = resolve_voice_preset(voice_preset)
    if resolved:
        return resolved

    # 2. Fallback : essayer les samples du package TTS (Coqui)
    try:
        import pkg_resources
        tts_path = pkg_resources.resource_filename('TTS', '')
        samples_dir = os.path.join(tts_path, 'utils', 'samples')
        if os.path.exists(samples_dir):
            for file in os.listdir(samples_dir):
                if file.endswith('.wav'):
                    return os.path.join(samples_dir, file)
    except Exception:
        pass

    # 3. Fallback final : télécharger un sample LJSpeech minimal
    refs_dir = get_voice_refs_dir()
    refs_dir.mkdir(parents=True, exist_ok=True)
    default_file = refs_dir / 'default.wav'

    if not default_file.exists():
        _LJ_BASE = 'https://github.com/idiap/coqui-ai-TTS/raw/main/tests/data/ljspeech/wavs'
        try:
            logger.info("Downloading fallback voice sample (LJSpeech)...")
            urllib.request.urlretrieve(f'{_LJ_BASE}/LJ001-0001.wav', str(default_file))
            logger.info(f"Fallback voice saved to {default_file}")
        except Exception as e:
            logger.warning(f"Could not download fallback voice: {e}")

    if default_file.exists():
        return str(default_file)

    return None


@shared_task(name='wama.synthesizer.download_voice_refs', ignore_result=False)
def download_voice_refs_task(force: bool = False):
    """
    Tâche Celery : télécharge les fichiers de voix de référence manquants
    selon VOICE_DOWNLOAD_CATALOG défini dans voice_utils.py.
    """
    from wama.synthesizer.utils.voice_utils import download_missing_voice_refs
    results = download_missing_voice_refs(force=force)
    n_ok   = sum(1 for s in results.values() if s == 'downloaded')
    n_fail = sum(1 for s in results.values() if s == 'failed')
    logger.info(f"[download_voice_refs_task] {n_ok} téléchargées, {n_fail} échec(s)")
    return {'downloaded': n_ok, 'failed': n_fail, 'details': results}


def _set_progress(synthesis: VoiceSynthesis, value: int) -> None:
    """Met à jour la progression de la synthèse."""
    cache.set(f"synthesizer_progress_{synthesis.id}", value, timeout=3600)
    VoiceSynthesis.objects.filter(pk=synthesis.id).update(progress=value)


def _console(user_id: int, message: str, level: str = None) -> None:
    """Envoie un message dans la console de l'utilisateur."""
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
        push_console_line(user_id, message, level=level, app='synthesizer')
    except Exception:
        pass


def _split_text_into_chunks(text, max_chars):
    """
    Divise un texte en chunks de taille maximale.
    Essaie de couper aux limites de phrases.
    """
    import re

    # Diviser en phrases
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_chars:
            current_chunk += sentence + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


@shared_task(bind=True, max_retries=60, default_retry_delay=10)
def synthesize_voice(self, synthesis_id: int):
    """
    Tâche principale de synthèse vocale.
    Delegates audio generation to the TTS microservice.

    Args:
        synthesis_id: ID de l'objet VoiceSynthesis

    Returns:
        dict: Résultat de la synthèse
    """
    close_old_connections()

    try:
        synthesis = VoiceSynthesis.objects.get(pk=synthesis_id)
    except VoiceSynthesis.DoesNotExist:
        logger.error(f"VoiceSynthesis {synthesis_id} not found")
        return {'ok': False, 'error': 'Synthesis not found'}

    _set_progress(synthesis, 5)
    _console(synthesis.user_id, f"Synthèse vocale #{synthesis.id} démarrée")

    try:
        # Étape 1: Extraction du texte
        _console(synthesis.user_id, "Extraction du texte du fichier...")
        _set_progress(synthesis, 10)

        text_content = extract_text_from_file(synthesis.text_file.path)

        if not text_content or len(text_content.strip()) == 0:
            raise ValueError("Le fichier ne contient pas de texte valide")

        synthesis.text_content = text_content
        synthesis.update_metadata()

        _console(synthesis.user_id, f"Texte extrait: {synthesis.word_count} mots")
        _set_progress(synthesis, 20)

        # Étape 2: Génération audio via le service TTS
        _console(synthesis.user_id, f"Envoi au service TTS (modèle: {synthesis.tts_model})...")
        _set_progress(synthesis, 30)

        # Créer le fichier de sortie temporaire
        output_dir = os.path.dirname(synthesis.text_file.path)
        temp_output = os.path.join(output_dir, f"synthesis_{synthesis.id}_temp.wav")

        # Resolve speaker_wav for voice cloning models
        speaker_wav = None
        if synthesis.voice_reference:
            speaker_wav = synthesis.voice_reference.path
        elif synthesis.voice_preset.startswith('ua_'):
            try:
                from wama.media_library.models import UserAsset
                ua = UserAsset.objects.get(pk=int(synthesis.voice_preset[3:]))
                speaker_wav = ua.file.path
            except (ValueError, UserAsset.DoesNotExist):
                speaker_wav = _get_default_speaker_wav('default')
        elif synthesis.voice_preset.startswith('cv_'):
            # Compat legacy : chercher dans CustomVoice encore présent
            try:
                from .models import CustomVoice
                cv = CustomVoice.objects.get(pk=int(synthesis.voice_preset[3:]))
                speaker_wav = cv.audio.path
            except (ValueError, CustomVoice.DoesNotExist):
                speaker_wav = _get_default_speaker_wav('default')
        elif synthesis.tts_model == 'xtts_v2':
            speaker_wav = _get_default_speaker_wav(synthesis.voice_preset)

        # Generate audio via TTS service (with chunking for long texts)
        _synthesize_via_service(
            synthesis, text_content, temp_output,
            speaker_wav, _set_progress, _console,
        )

        _set_progress(synthesis, 80)

        # Étape 4: Post-traitement audio (ajustement vitesse, pitch)
        _console(synthesis.user_id, "Post-traitement audio...")
        _set_progress(synthesis, 85)

        final_output = process_audio_output(
            temp_output,
            speed=synthesis.speed,
            pitch=synthesis.pitch
        )

        # Étape 5: Sauvegarde du résultat
        _console(synthesis.user_id, "Sauvegarde du fichier audio...")
        _set_progress(synthesis, 90)

        with open(final_output, 'rb') as f:
            # Build output filename from input name + model name (sanitize special chars)
            raw_name = os.path.splitext(os.path.basename(synthesis.text_file.name))[0]
            # Normalize unicode (é → e, etc.) then keep only safe chars
            normalized = unicodedata.normalize('NFKD', raw_name).encode('ascii', 'ignore').decode('ascii')
            input_name = re.sub(r'[^\w\-]', '_', normalized).strip('_') or 'synthesis'
            audio_filename = f"{input_name}_{synthesis.tts_model}.wav"
            synthesis.audio_output.save(audio_filename, ContentFile(f.read()))

        # Mettre à jour les propriétés audio
        _update_audio_properties(synthesis)

        # Nettoyage des fichiers temporaires
        for temp_file in [temp_output, final_output]:
            if os.path.exists(temp_file) and temp_file != synthesis.audio_output.path:
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

        # Finalisation
        synthesis.status = 'SUCCESS'
        synthesis.save(update_fields=['status', 'audio_output'])
        _set_progress(synthesis, 100)

        _console(synthesis.user_id, f"Synthèse #{synthesis.id} terminée ✓")

        return {
            'ok': True,
            'synthesis_id': synthesis.id,
            'audio_url': synthesis.audio_output.url,
            'duration': synthesis.duration_display,
            'word_count': synthesis.word_count,
        }

    except TTSServiceLoadingError as e:
        # TTS service is still starting — release the GPU worker and retry later.
        retry_num = self.request.retries + 1
        wait_msg = f"Service TTS en chargement, nouvelle tentative dans 10s ({retry_num}/60)..."
        logger.info(f"synthesize_voice #{synthesis_id}: {wait_msg}")
        synthesis.error_message = wait_msg
        synthesis.save(update_fields=['error_message'])
        _console(synthesis.user_id, wait_msg, level='warning')
        try:
            raise self.retry(exc=e, countdown=10)
        except self.MaxRetriesExceededError:
            # 60 retries × 10s = 10 minutes without TTS service → give up
            synthesis.status = 'FAILURE'
            synthesis.error_message = "Service TTS non disponible après 10 minutes d'attente (60 tentatives)"
            synthesis.save(update_fields=['status', 'error_message'])
            _set_progress(synthesis, 0)
            _console(synthesis.user_id, "Erreur: service TTS non disponible après 10 minutes", level='error')
            return {'ok': False, 'error': str(e)}

    except Exception as e:
        logger.error(f"Error in synthesize_voice task: {str(e)}", exc_info=True)
        synthesis.status = 'FAILURE'
        synthesis.error_message = str(e)
        synthesis.save(update_fields=['status', 'error_message'])
        _set_progress(synthesis, 0)
        _console(synthesis.user_id, f"Erreur synthèse #{synthesis.id}: {e}")

        return {'ok': False, 'error': str(e)}


def _synthesize_via_service(synthesis, text, output_path, speaker_wav,
                            progress_fn, console_fn):
    """
    Generate audio by calling the TTS microservice.
    Handles text chunking and concatenation for long texts.
    """
    from pydub import AudioSegment

    model = synthesis.tts_model
    language = synthesis.language
    voice_preset = synthesis.voice_preset
    multi_speaker = getattr(synthesis, 'multi_speaker', False)
    scene_description = getattr(synthesis, 'scene_description', '')

    # Determine chunk size based on model
    chunk_limits = {
        'bark': 200,
        'kokoro': 400,   # EspeakG2P (FR/ES/IT/PT) truncates long texts — keep short
        'higgs_audio': 500,
        'xtts_v2': 1000,
    }
    max_chars = chunk_limits.get(model, 800)

    # Split text into chunks if needed
    if len(text) > max_chars:
        console_fn(synthesis.user_id, f"Texte long détecté, division en segments...")
        chunks = _split_text_into_chunks(text, max_chars)
    else:
        chunks = [text]

    console_fn(synthesis.user_id, f"Génération audio: {len(chunks)} segment(s) via service TTS...")
    progress_fn(synthesis, 40)

    chunk_files = []
    progress_start = 40
    progress_end = 75
    progress_range = progress_end - progress_start

    for i, chunk in enumerate(chunks):
        progress = progress_start + int((i / len(chunks)) * progress_range)
        progress_fn(synthesis, progress)
        console_fn(synthesis.user_id, f"Génération segment {i+1}/{len(chunks)}...")

        # Call the TTS service
        wav_path = _tts_via_service(
            text=chunk,
            model=model,
            language=language,
            voice_preset=voice_preset,
            speaker_wav=speaker_wav,
            multi_speaker=multi_speaker,
            scene_description=scene_description if i == 0 else '',
        )
        chunk_files.append(wav_path)

    progress_fn(synthesis, 75)

    # Concatenate chunks
    if len(chunk_files) == 1:
        # Single chunk: just move the file
        import shutil
        shutil.move(chunk_files[0], output_path)
    else:
        console_fn(synthesis.user_id, "Assemblage des segments audio...")
        combined = AudioSegment.empty()
        for chunk_file in chunk_files:
            audio = AudioSegment.from_wav(chunk_file)
            combined += audio
            combined += AudioSegment.silent(duration=200)  # 200ms silence between chunks

        combined.export(output_path, format='wav')

        # Cleanup temp chunk files
        for chunk_file in chunk_files:
            try:
                os.remove(chunk_file)
            except OSError:
                pass

    console_fn(synthesis.user_id, f"Audio généré: {output_path}")


def _update_audio_properties(synthesis):
    """
    Met à jour les propriétés du fichier audio généré.
    """
    import subprocess
    import json
    import shutil

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=duration,codec_name,sample_rate,channels",
                "-of", "json",
                synthesis.audio_output.path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]

        duration = float(stream.get("duration") or 0)
        sample_rate = stream.get("sample_rate")
        codec = stream.get("codec_name")
        channels = int(stream.get("channels") or 0)

        # Format des propriétés
        props_parts = []
        if codec:
            props_parts.append(codec.upper())
        if sample_rate:
            props_parts.append(f"{int(sample_rate) / 1000:.1f} kHz")
        if channels == 1:
            props_parts.append("mono")
        elif channels == 2:
            props_parts.append("stéréo")

        synthesis.properties = " • ".join(props_parts)
        synthesis.duration_seconds = duration
        synthesis.duration_display = synthesis.format_duration(duration)
        synthesis.save(update_fields=['properties', 'duration_seconds', 'duration_display'])

    except Exception as e:
        logger.warning(f"Could not extract audio properties: {e}")


@shared_task
def cleanup_old_syntheses(days=7):
    """
    Tâche de nettoyage périodique des anciennes synthèses.

    Args:
        days: Nombre de jours après lesquels supprimer
    """
    from datetime import timedelta
    from django.utils import timezone

    cutoff_date = timezone.now() - timedelta(days=days)
    old_syntheses = VoiceSynthesis.objects.filter(created_at__lt=cutoff_date)

    count = 0
    for synthesis in old_syntheses:
        # Supprimer les fichiers
        if synthesis.text_file:
            synthesis.text_file.delete(save=False)
        if synthesis.audio_output:
            synthesis.audio_output.delete(save=False)
        if synthesis.voice_reference:
            synthesis.voice_reference.delete(save=False)

        synthesis.delete()
        count += 1

    logger.info(f"Cleaned up {count} old syntheses")
    return {'cleaned': count}
