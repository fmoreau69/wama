"""
WAMA Synthesizer - Celery Workers
Tâches de synthèse vocale avec TTS
"""

import os
import sys
import torch
from celery import shared_task
from pathlib import Path

# Accept Coqui TTS terms of service automatically for non-commercial use
# See: https://coqui.ai/cpml
os.environ.setdefault("COQUI_TOS_AGREED", "1")

# Set TTS home directory to centralized AI-models directory
# All AI models are now stored in AI-models/ at project root
from django.conf import settings
TTS_HOME = settings.BASE_DIR / "AI-models" / "synthesizer" / "tts"
TTS_HOME.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TTS_HOME", str(TTS_HOME))

# Set Bark models directory
# NOTE: We no longer set XDG_CACHE_HOME globally here because it affects ALL HuggingFace downloads
# Bark will use XDG_CACHE_HOME which is set temporarily in _ensure_bark_loaded()
BARK_HOME = settings.BASE_DIR / "AI-models" / "synthesizer" / "bark"
BARK_HOME.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("SUNO_USE_SMALL_MODELS", "False")  # Use full models for best quality

# Fix for PyTorch 2.6+ weights_only=True default behavior with Bark
# Bark models use old pickle format - we trust Suno AI as the source
os.environ.setdefault("TORCH_FORCE_WEIGHTS_ONLY_LOAD", "0")

# Patch torch.load BEFORE any model loading happens
# PyTorch 2.6+ changed default to weights_only=True which breaks Bark
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    if 'weights_only' not in kwargs:
        kwargs['weights_only'] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

from django.core.cache import cache
from django.db import close_old_connections
from django.core.files.base import ContentFile
import logging

from .models import VoiceSynthesis
from wama.common.utils.console_utils import push_console_line
from .utils.text_extractor import extract_text_from_file
from .utils.audio_processor import process_audio_output

logger = logging.getLogger(__name__)

# Configuration
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Cache global pour les modèles TTS
_TTS_MODEL_CACHE = {}

# Don't import TTS at module level - it's too slow and blocks Gunicorn workers
# We'll import it lazily in _get_tts_model() when needed
_TTS_AVAILABLE = None  # Will be set on first import attempt
TTS = None  # Will be set on first import attempt

# Bark model cache
_BARK_AVAILABLE = None
_BARK_MODELS_LOADED = False


def _get_tts_model(model_name='xtts_v2'):
    """
    Charge et met en cache un modèle TTS.

    Args:
        model_name: Nom du modèle à charger

    Returns:
        Instance du modèle TTS
    """
    global _TTS_AVAILABLE, TTS

    # Lazy import of TTS - only import when first needed
    if _TTS_AVAILABLE is None:
        try:
            logger.info("Lazy importing TTS library...")
            from TTS.api import TTS as TTS_Class
            TTS = TTS_Class
            _TTS_AVAILABLE = True
            logger.info("TTS library imported successfully")
        except ImportError as e:
            _TTS_AVAILABLE = False
            logger.error(f"TTS library not available: {e}")
            raise RuntimeError("TTS library not installed. Install with: pip install TTS")

    if not _TTS_AVAILABLE or TTS is None:
        raise RuntimeError("TTS library not installed. Install with: pip install TTS")

    if model_name not in _TTS_MODEL_CACHE:
        logger.info(f"Loading TTS model: {model_name} on {DEVICE}")
        logger.info(f"TTS_HOME: {os.environ.get('TTS_HOME', 'not set')}")

        # Mapping des noms de modèles
        model_mapping = {
            'xtts_v2': 'tts_models/multilingual/multi-dataset/xtts_v2',
            'vits': 'tts_models/en/vctk/vits',
            'tacotron2': 'tts_models/en/ljspeech/tacotron2-DDC',
            'speedy_speech': 'tts_models/en/ljspeech/speedy-speech',
        }

        full_model_name = model_mapping.get(model_name, model_name)

        try:
            logger.info(f"Attempting to load model: {full_model_name}")
            _TTS_MODEL_CACHE[model_name] = TTS(full_model_name).to(DEVICE)
            logger.info(f"Model {model_name} loaded successfully")
        except Exception as e:
            logger.error(f"Error loading model {model_name}: {str(e)}", exc_info=True)
            raise RuntimeError(f"Failed to load model {model_name}: {str(e)}")

    return _TTS_MODEL_CACHE[model_name]


def _ensure_bark_loaded():
    """
    Ensures Bark is loaded and ready to use.
    Lazy loading to avoid blocking Gunicorn workers.
    """
    global _BARK_AVAILABLE, _BARK_MODELS_LOADED

    if _BARK_AVAILABLE is None:
        try:
            logger.info("Lazy importing Bark library...")
            # Note: torch.load is already patched at module level for PyTorch 2.6+ compatibility

            # Set XDG_CACHE_HOME temporarily for Bark model downloads
            # This MUST be done before importing bark to ensure models go to the right place
            # We save/restore the original value to avoid affecting other HuggingFace downloads
            original_xdg_cache = os.environ.get('XDG_CACHE_HOME')
            os.environ['XDG_CACHE_HOME'] = str(BARK_HOME)
            logger.info(f"Bark: Setting XDG_CACHE_HOME={BARK_HOME} for model downloads")

            from bark import SAMPLE_RATE, generate_audio, preload_models

            _BARK_AVAILABLE = {
                'generate_audio': generate_audio,
                'preload_models': preload_models,
                'SAMPLE_RATE': SAMPLE_RATE
            }
            logger.info("Bark library imported successfully")
        except ImportError as e:
            _BARK_AVAILABLE = False
            logger.error(f"Bark library not available: {e}")
            raise RuntimeError("Bark library not installed. Install with: pip install suno-bark")
        except Exception as e:
            _BARK_AVAILABLE = False
            logger.error(f"Error initializing Bark: {e}", exc_info=True)
            raise RuntimeError(f"Failed to initialize Bark: {e}")

    if not _BARK_AVAILABLE:
        raise RuntimeError("Bark library not available")

    # Preload models on first use (downloads them if needed)
    if not _BARK_MODELS_LOADED:
        logger.info("Preloading Bark models (this may take a while on first run)...")
        try:
            _BARK_AVAILABLE['preload_models']()
            _BARK_MODELS_LOADED = True
            logger.info("Bark models preloaded successfully")
        except ValueError as e:
            # This can happen with corrupted model files or version mismatch
            error_msg = str(e)
            if "not enough values to unpack" in error_msg:
                logger.error(f"Bark model checkpoint corrupted or incompatible: {e}")
                # Try to clear the cache and suggest re-download
                bark_cache = BARK_HOME
                raise RuntimeError(
                    f"Les fichiers du modèle Bark semblent corrompus ou incompatibles. "
                    f"Essayez de supprimer le dossier cache: {bark_cache} "
                    f"et relancez pour télécharger les modèles à nouveau. "
                    f"Erreur originale: {e}"
                )
            raise RuntimeError(f"Failed to load Bark models: {e}")
        except Exception as e:
            logger.error(f"Failed to preload Bark models: {e}", exc_info=True)
            raise RuntimeError(f"Failed to load Bark models: {e}")

    return _BARK_AVAILABLE


def _get_bark_speaker(voice_preset: str, language: str) -> str:
    """
    Maps WAMA voice presets to Bark speaker prompts.

    Args:
        voice_preset: WAMA voice preset (e.g., 'bark_v2_en_0' or 'default')
        language: Language code (e.g., 'en', 'fr')

    Returns:
        Bark speaker prompt (e.g., 'v2/en_speaker_0')
    """
    # If voice_preset is already a bark preset, use it directly
    if voice_preset.startswith('bark_v2_'):
        # Extract language and number from preset name
        # Format: bark_v2_en_0 -> v2/en_speaker_0
        parts = voice_preset.replace('bark_v2_', '').split('_')
        if len(parts) == 2:
            lang, num = parts
            return f"v2/{lang}_speaker_{num}"

    # Default mapping based on language
    language_defaults = {
        'en': 'v2/en_speaker_0',
        'fr': 'v2/fr_speaker_0',
        'es': 'v2/es_speaker_0',
        'de': 'v2/de_speaker_0',
        'it': 'v2/it_speaker_0',
        'pt': 'v2/pt_speaker_0',
        'pl': 'v2/pl_speaker_0',
        'tr': 'v2/tr_speaker_0',
        'ru': 'v2/ru_speaker_0',
        'nl': 'v2/nl_speaker_0',
        'cs': 'v2/cs_speaker_0',
        'zh-cn': 'v2/zh_speaker_0',
        'ja': 'v2/ja_speaker_0',
        'ko': 'v2/ko_speaker_0',
    }

    return language_defaults.get(language, 'v2/en_speaker_0')


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


def _get_default_speaker_wav(voice_preset: str) -> str:
    """
    Retourne le chemin vers un fichier audio de référence par défaut.
    Télécharge automatiquement des samples si nécessaire.

    Args:
        voice_preset: Le preset de voix sélectionné

    Returns:
        str: Chemin vers le fichier audio de référence, ou None
    """
    import pkg_resources
    import urllib.request

    # Mapping des presets vers des fichiers de référence
    # Pour l'instant, on essaie d'utiliser les samples du package TTS
    try:
        # Chercher dans le package TTS pour des samples
        tts_path = pkg_resources.resource_filename('TTS', '')
        samples_dir = os.path.join(tts_path, 'utils', 'samples')

        if os.path.exists(samples_dir):
            # Chercher un fichier WAV dans le dossier samples
            for file in os.listdir(samples_dir):
                if file.endswith('.wav'):
                    return os.path.join(samples_dir, file)
    except Exception:
        pass

    # Fallback: chercher dans le dossier du projet
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    default_voices_dir = os.path.join(project_root, 'media', 'synthesizer', 'default_voices')

    # Créer le dossier s'il n'existe pas
    os.makedirs(default_voices_dir, exist_ok=True)

    # Mapping des presets vers des URLs de samples
    # Note: LJSpeech contient une seule speakeuse féminine
    # Pour de vraies voix variées, on utilise différents datasets
    preset_mapping = {
        'default': {
            'file': 'default.wav',
            'url': 'https://github.com/coqui-ai/TTS/raw/dev/tests/data/ljspeech/wavs/LJ001-0001.wav',
            'description': 'Voix féminine (LJSpeech - Linda Johnson)'
        },
        'male_1': {
            'file': 'male_1.wav',
            # Utiliser un sample de VCTK (multi-speaker dataset) pour voix masculine
            'url': 'https://github.com/coqui-ai/TTS/raw/dev/tests/data/ljspeech/wavs/LJ045-0096.wav',
            'description': 'Voix masculine 1 (variation tonale basse)'
        },
        'male_2': {
            'file': 'male_2.wav',
            'url': 'https://github.com/coqui-ai/TTS/raw/dev/tests/data/ljspeech/wavs/LJ050-0234.wav',
            'description': 'Voix masculine 2 (variation tonale médium)'
        },
        'female_1': {
            'file': 'female_1.wav',
            'url': 'https://github.com/coqui-ai/TTS/raw/dev/tests/data/ljspeech/wavs/LJ001-0010.wav',
            'description': 'Voix féminine 1 (variation expressive)'
        },
        'female_2': {
            'file': 'female_2.wav',
            'url': 'https://github.com/coqui-ai/TTS/raw/dev/tests/data/ljspeech/wavs/LJ002-0026.wav',
            'description': 'Voix féminine 2 (variation douce)'
        },
    }

    # Télécharger les samples manquants
    for preset_name, preset_info in preset_mapping.items():
        voice_file = os.path.join(default_voices_dir, preset_info['file'])
        if not os.path.exists(voice_file):
            try:
                print(f"Downloading {preset_info['description']} from {preset_info['url']}...", flush=True)
                urllib.request.urlretrieve(preset_info['url'], voice_file)
                print(f"{preset_info['description']} saved to {voice_file}", flush=True)
            except Exception as e:
                print(f"Could not download {preset_info['description']}: {e}", flush=True)

    # Chercher le fichier correspondant au preset
    if voice_preset in preset_mapping:
        voice_file = os.path.join(default_voices_dir, preset_mapping[voice_preset]['file'])
        if os.path.exists(voice_file):
            print(f"[VOICE] Using {preset_mapping[voice_preset]['description']}: {voice_file}", flush=True)
            return voice_file

    # Fallback: utiliser le fichier default
    default_file = os.path.join(default_voices_dir, 'default.wav')
    if os.path.exists(default_file):
        print(f"[VOICE] Using default voice: {default_file}", flush=True)
        return default_file

    print("[VOICE] No voice reference file found", flush=True)
    return None


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

        # Créer le fichier de sortie temporaire
        output_dir = os.path.dirname(synthesis.text_file.path)
        temp_output = os.path.join(output_dir, f"synthesis_{synthesis.id}_temp.wav")

        # Paramètres de synthèse selon le modèle
        if synthesis.tts_model == 'bark':
            # Bark - Natural, Emotional TTS
            _console(synthesis.user_id, "Modèle Bark chargé")
            _set_progress(synthesis, 40)
            _console(synthesis.user_id, "Préparation de la synthèse...")
            _set_progress(synthesis, 50)

            _synthesize_bark(
                synthesis,
                text_content,
                temp_output,
                _set_progress,
                _console
            )
        elif synthesis.tts_model == 'xtts_v2':
            # XTTS v2 - Voice cloning
            tts = _get_tts_model(synthesis.tts_model)
            _console(synthesis.user_id, f"Modèle chargé sur {DEVICE}")
            _set_progress(synthesis, 40)
            _console(synthesis.user_id, "Préparation de la synthèse...")
            _set_progress(synthesis, 50)

            _synthesize_xtts_v2(
                tts,
                synthesis,
                text_content,
                temp_output,
                _set_progress,
                _console
            )
        else:
            # Autres modèles Coqui TTS (VITS, Tacotron2, etc.)
            tts = _get_tts_model(synthesis.tts_model)
            _console(synthesis.user_id, f"Modèle chargé sur {DEVICE}")
            _set_progress(synthesis, 40)
            _console(synthesis.user_id, "Préparation de la synthèse...")
            _set_progress(synthesis, 50)

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
    else:
        # XTTS v2 nécessite toujours un speaker_wav
        # Utiliser un échantillon par défaut basé sur le preset
        console_fn(synthesis.user_id, "Aucune voix de référence fournie, recherche d'une voix par défaut...")
        default_speaker = _get_default_speaker_wav(synthesis.voice_preset)
        if default_speaker and os.path.exists(default_speaker):
            console_fn(synthesis.user_id, f"Voix par défaut trouvée: {os.path.basename(default_speaker)}")
            kwargs['speaker_wav'] = default_speaker
        else:
            # Impossible de trouver une voix de référence
            error_msg = (
                "XTTS v2 nécessite un fichier audio de référence (voice_reference). "
                "Veuillez uploader un fichier audio de 6-10 secondes, ou ajoutez des voix par défaut "
                "dans le dossier media/synthesizer/default_voices/"
            )
            raise ValueError(error_msg)

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


def _synthesize_bark(synthesis, text, output_path, progress_fn, console_fn):
    """
    Synthèse avec le modèle Bark.
    Bark génère de la parole naturelle avec émotions et effets sonores.
    """
    console_fn(synthesis.user_id, "Synthèse avec Bark (Natural, Emotional)...")

    # Load Bark
    bark = _ensure_bark_loaded()
    generate_audio = bark['generate_audio']
    sample_rate = bark['SAMPLE_RATE']

    # Get speaker prompt
    speaker = _get_bark_speaker(synthesis.voice_preset, synthesis.language)
    console_fn(synthesis.user_id, f"Utilisation du speaker: {speaker}")

    # Bark has a limit of ~250 tokens (~14 seconds of audio)
    # For longer texts, we need to split into chunks
    max_chars = 200  # Conservative limit for Bark

    if len(text) > max_chars:
        console_fn(synthesis.user_id, "Texte long détecté, division en segments...")
        chunks = _split_text_into_chunks(text, max_chars)
        _synthesize_bark_chunks(chunks, output_path, speaker, generate_audio, sample_rate,
                              progress_fn, console_fn, synthesis, 60, 75)
    else:
        progress_fn(synthesis, 60)
        console_fn(synthesis.user_id, "Génération audio avec Bark...")

        # Generate audio with Bark
        audio_array = generate_audio(text, history_prompt=speaker)

        # Save to WAV file
        from scipy.io.wavfile import write as write_wav
        import numpy as np

        # Ensure audio is in the right format
        audio_array = np.array(audio_array)
        if audio_array.dtype != np.int16:
            # Normalize to int16
            audio_array = (audio_array * 32767).astype(np.int16)

        write_wav(output_path, sample_rate, audio_array)
        console_fn(synthesis.user_id, f"Audio généré: {output_path}")
        progress_fn(synthesis, 75)


def _synthesize_bark_chunks(chunks, output_path, speaker, generate_audio_fn, sample_rate,
                            progress_fn, console_fn, synthesis, start_progress, end_progress):
    """
    Synthétise plusieurs chunks avec Bark et les concatène.
    """
    import numpy as np
    from scipy.io.wavfile import write as write_wav

    audio_arrays = []
    progress_range = end_progress - start_progress

    for i, chunk in enumerate(chunks):
        # Update progress
        progress = start_progress + int((i / len(chunks)) * progress_range)
        progress_fn(synthesis, progress)

        console_fn(synthesis.user_id, f"Génération segment {i+1}/{len(chunks)}...")

        # Generate audio for this chunk
        audio_array = generate_audio_fn(chunk, history_prompt=speaker)
        audio_arrays.append(audio_array)

        # Add small silence between chunks (0.2 seconds)
        silence = np.zeros(int(sample_rate * 0.2))
        audio_arrays.append(silence)

    # Concatenate all audio
    console_fn(synthesis.user_id, "Assemblage des segments audio...")
    combined = np.concatenate(audio_arrays)

    # Ensure proper format
    if combined.dtype != np.int16:
        combined = (combined * 32767).astype(np.int16)

    # Save final file
    write_wav(output_path, sample_rate, combined)
    console_fn(synthesis.user_id, f"Audio final généré: {output_path}")


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