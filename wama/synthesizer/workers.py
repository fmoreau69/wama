"""
WAMA Synthesizer - Celery Workers
Tâches de synthèse vocale avec TTS
"""

import os
import torch
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections
from django.core.files.base import ContentFile
import logging

from .models import VoiceSynthesis
from wama.medias.utils.console_utils import push_console_line
from .utils.text_extractor import extract_text_from_file
from .utils.audio_processor import process_audio_output

logger = logging.getLogger(__name__)

# Configuration
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Cache global pour les modèles TTS
_TTS_MODEL_CACHE = {}


def _get_tts_model(model_name='xtts_v2'):
    """
    Charge et met en cache un modèle TTS.

    Args:
        model_name: Nom du modèle à charger

    Returns:
        Instance du modèle TTS
    """
    try:
        from TTS.api import TTS
    except ImportError:
        raise RuntimeError("TTS library not installed. Install with: pip install TTS")

    if model_name not in _TTS_MODEL_CACHE:
        logger.info(f"Loading TTS model: {model_name} on {DEVICE}")

        # Mapping des noms de modèles
        model_mapping = {
            'xtts_v2': 'tts_models/multilingual/multi-dataset/xtts_v2',
            'vits': 'tts_models/en/vctk/vits',
            'tacotron2': 'tts_models/en/ljspeech/tacotron2-DDC',
            'speedy_speech': 'tts_models/en/ljspeech/speedy-speech',
        }

        full_model_name = model_mapping.get(model_name, model_name)
        _TTS_MODEL_CACHE[model_name] = TTS(full_model_name).to(DEVICE)
        logger.info(f"Model {model_name} loaded successfully")

    return _TTS_MODEL_CACHE[model_name]


def _set_progress(synthesis: VoiceSynthesis, value: int) -> None:
    """Met à jour la progression de la synthèse."""
    cache.set(f"synthesizer_progress_{synthesis.id}", value, timeout=3600)
    VoiceSynthesis.objects.filter(pk=synthesis.id).update(progress=value)


def _console(user_id: int, message: str) -> None:
    """Envoie un message dans la console de l'utilisateur."""
    try:
        push_console_line(user_id, f"[Synthesizer] {message}")
    except Exception:
        pass


@shared_task(bind=True)
def synthesize_voice(self, synthesis_id: int):
    """
    Tâche principale de synthèse vocale.

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

        # Étape 2: Chargement du modèle TTS
        _console(synthesis.user_id, f"Chargement du modèle {synthesis.tts_model}...")
        _set_progress(synthesis, 30)

        tts = _get_tts_model(synthesis.tts_model)
        _console(synthesis.user_id, f"Modèle chargé sur {DEVICE}")
        _set_progress(synthesis, 40)

        # Étape 3: Préparation des paramètres
        _console(synthesis.user_id, "Préparation de la synthèse...")
        _set_progress(synthesis, 50)

        # Créer le fichier de sortie temporaire
        output_dir = os.path.dirname(synthesis.text_file.path)
        temp_output = os.path.join(output_dir, f"synthesis_{synthesis.id}_temp.wav")

        # Paramètres de synthèse selon le modèle
        if synthesis.tts_model == 'xtts_v2':
            # XTTS v2 supporte le voice cloning
            _synthesize_xtts_v2(
                tts,
                synthesis,
                text_content,
                temp_output,
                _set_progress,
                _console
            )
        else:
            # Autres modèles
            _synthesize_standard(
                tts,
                synthesis,
                text_content,
                temp_output,
                _set_progress,
                _console
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
            audio_filename = f"voice_synthesis_{synthesis.id}.wav"
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

    except Exception as e:
        logger.error(f"Error in synthesize_voice task: {str(e)}", exc_info=True)
        synthesis.status = 'FAILURE'
        synthesis.error_message = str(e)
        synthesis.save(update_fields=['status', 'error_message'])
        _set_progress(synthesis, 0)
        _console(synthesis.user_id, f"Erreur synthèse #{synthesis.id}: {e}")

        return {'ok': False, 'error': str(e)}


def _synthesize_xtts_v2(tts, synthesis, text, output_path, progress_fn, console_fn):
    """
    Synthèse avec le modèle XTTS v2 (supporte voice cloning).
    """
    console_fn(synthesis.user_id, "Synthèse avec XTTS v2 (voice cloning)...")

    # Paramètres pour XTTS v2
    kwargs = {
        'text': text,
        'file_path': output_path,
        'language': synthesis.language,
    }

    # Voice cloning si un fichier de référence est fourni
    if synthesis.voice_reference:
        console_fn(synthesis.user_id, "Utilisation du clonage de voix...")
        kwargs['speaker_wav'] = synthesis.voice_reference.path

    # Diviser le texte en chunks pour les longs textes
    max_chars = 1000  # Limite de caractères par chunk
    if len(text) > max_chars:
        console_fn(synthesis.user_id, f"Texte long détecté, division en segments...")
        chunks = _split_text_into_chunks(text, max_chars)
        _synthesize_chunks(tts, chunks, output_path, kwargs, progress_fn, synthesis, 60, 75)
    else:
        progress_fn(synthesis, 60)
        tts.tts_to_file(**kwargs)
        progress_fn(synthesis, 75)


def _synthesize_standard(tts, synthesis, text, output_path, progress_fn, console_fn):
    """
    Synthèse avec les modèles standard (VITS, Tacotron2, etc.).
    """
    console_fn(synthesis.user_id, f"Synthèse avec {synthesis.tts_model}...")

    kwargs = {
        'text': text,
        'file_path': output_path,
    }

    # Diviser le texte si nécessaire
    max_chars = 800
    if len(text) > max_chars:
        console_fn(synthesis.user_id, f"Texte long détecté, division en segments...")
        chunks = _split_text_into_chunks(text, max_chars)
        _synthesize_chunks(tts, chunks, output_path, kwargs, progress_fn, synthesis, 60, 75)
    else:
        progress_fn(synthesis, 60)
        tts.tts_to_file(**kwargs)
        progress_fn(synthesis, 75)


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


def _synthesize_chunks(tts, chunks, output_path, base_kwargs, progress_fn, synthesis, start_progress, end_progress):
    """
    Synthétise plusieurs chunks et les concatène.
    """
    from pydub import AudioSegment

    chunk_files = []
    progress_range = end_progress - start_progress

    for i, chunk in enumerate(chunks):
        # Mise à jour de la progression
        progress = start_progress + int((i / len(chunks)) * progress_range)
        progress_fn(synthesis, progress)

        # Générer le chunk
        chunk_output = output_path.replace('.wav', f'_chunk_{i}.wav')
        kwargs = base_kwargs.copy()
        kwargs['text'] = chunk
        kwargs['file_path'] = chunk_output

        tts.tts_to_file(**kwargs)
        chunk_files.append(chunk_output)

    # Concaténer tous les chunks
    _console(synthesis.user_id, "Assemblage des segments audio...")
    combined = AudioSegment.empty()

    for chunk_file in chunk_files:
        audio = AudioSegment.from_wav(chunk_file)
        combined += audio
        # Ajouter une petite pause entre les chunks
        combined += AudioSegment.silent(duration=200)  # 200ms de silence

    # Exporter le résultat final
    combined.export(output_path, format='wav')

    # Nettoyer les fichiers temporaires
    for chunk_file in chunk_files:
        try:
            os.remove(chunk_file)
        except OSError:
            pass


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