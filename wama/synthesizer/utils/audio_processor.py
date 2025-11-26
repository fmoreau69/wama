"""
WAMA Synthesizer - Utilities
Traitement audio
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def process_audio_output(
        input_path: str,
        speed: float = 1.0,
        pitch: float = 1.0,
        output_path: Optional[str] = None
) -> str:
    """
    Traite le fichier audio de sortie (ajustement vitesse, pitch).

    Args:
        input_path: Chemin du fichier audio d'entrée
        speed: Facteur de vitesse (1.0 = normal)
        pitch: Facteur de hauteur (1.0 = normal)
        output_path: Chemin de sortie (optionnel)

    Returns:
        str: Chemin du fichier traité
    """
    try:
        from pydub import AudioSegment
        from pydub.effects import speedup
    except ImportError:
        raise RuntimeError("pydub not installed. Install with: pip install pydub")

    # Si pas de transformation, retourner l'original
    if speed == 1.0 and pitch == 1.0:
        return input_path

    # Charger l'audio
    audio = AudioSegment.from_wav(input_path)

    # Ajuster la vitesse
    if speed != 1.0:
        audio = _change_speed(audio, speed)

    # Ajuster le pitch
    if pitch != 1.0:
        audio = _change_pitch(audio, pitch)

    # Générer le chemin de sortie
    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_processed{ext}"

    # Exporter
    audio.export(output_path, format='wav')

    return output_path


def _change_speed(audio: 'AudioSegment', speed: float) -> 'AudioSegment':
    """
    Change la vitesse d'un audio sans changer le pitch.

    Args:
        audio: AudioSegment à modifier
        speed: Facteur de vitesse

    Returns:
        AudioSegment modifié
    """
    # Méthode simple: changer le frame rate
    if speed > 1.0:
        # Accélérer
        return audio._spawn(
            audio.raw_data,
            overrides={'frame_rate': int(audio.frame_rate * speed)}
        ).set_frame_rate(audio.frame_rate)
    elif speed < 1.0:
        # Ralentir
        return audio._spawn(
            audio.raw_data,
            overrides={'frame_rate': int(audio.frame_rate * speed)}
        ).set_frame_rate(audio.frame_rate)

    return audio


def _change_pitch(audio: 'AudioSegment', pitch: float) -> 'AudioSegment':
    """
    Change le pitch d'un audio.

    Args:
        audio: AudioSegment à modifier
        pitch: Facteur de pitch

    Returns:
        AudioSegment modifié
    """
    # Calculer le nombre de semitones
    import math
    semitones = 12 * math.log2(pitch)

    # Méthode: changer le frame rate et résampler
    new_sample_rate = int(audio.frame_rate * pitch)

    return audio._spawn(
        audio.raw_data,
        overrides={'frame_rate': new_sample_rate}
    ).set_frame_rate(audio.frame_rate)


def get_audio_duration(file_path: str) -> float:
    """
    Récupère la durée d'un fichier audio en secondes.

    Args:
        file_path: Chemin du fichier audio

    Returns:
        float: Durée en secondes
    """
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(file_path)
        return len(audio) / 1000.0  # Convertir ms en secondes
    except Exception as e:
        logger.warning(f"Could not get audio duration: {e}")
        return 0.0


def convert_audio_format(
        input_path: str,
        output_path: str,
        format: str = 'mp3',
        bitrate: str = '192k'
) -> str:
    """
    Convertit un fichier audio vers un autre format.

    Args:
        input_path: Chemin du fichier d'entrée
        output_path: Chemin du fichier de sortie
        format: Format de sortie (mp3, wav, ogg, etc.)
        bitrate: Bitrate pour la compression (ex: '192k')

    Returns:
        str: Chemin du fichier converti
    """
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(input_path)
        audio.export(
            output_path,
            format=format,
            bitrate=bitrate
        )

        return output_path

    except Exception as e:
        logger.error(f"Error converting audio: {e}")
        raise


def normalize_audio(input_path: str, output_path: Optional[str] = None) -> str:
    """
    Normalise le volume d'un fichier audio.

    Args:
        input_path: Chemin du fichier d'entrée
        output_path: Chemin de sortie (optionnel)

    Returns:
        str: Chemin du fichier normalisé
    """
    try:
        from pydub import AudioSegment
        from pydub.effects import normalize

        audio = AudioSegment.from_file(input_path)
        normalized = normalize(audio)

        if not output_path:
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_normalized{ext}"

        normalized.export(output_path, format='wav')
        return output_path

    except Exception as e:
        logger.error(f"Error normalizing audio: {e}")
        raise


# ============= TEXT PREPROCESSING =============

def clean_text_for_tts(text: str) -> str:
    """
    Nettoie et prépare un texte pour la synthèse vocale.

    Args:
        text: Texte brut

    Returns:
        str: Texte nettoyé
    """
    import re

    # Supprimer les URLs
    text = re.sub(r'http[s]?://\S+', '', text)

    # Supprimer les emails
    text = re.sub(r'\S+@\S+', '', text)

    # Normaliser les espaces multiples
    text = re.sub(r'\s+', ' ', text)

    # Supprimer les caractères de contrôle
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')

    # Normaliser les sauts de ligne multiples
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def estimate_reading_time(text: str, wpm: int = 150) -> float:
    """
    Estime le temps de lecture d'un texte.

    Args:
        text: Texte à évaluer
        wpm: Mots par minute (words per minute)

    Returns:
        float: Temps estimé en secondes
    """
    word_count = len(text.split())
    minutes = word_count / wpm
    return minutes * 60


def split_text_by_sentences(text: str, max_length: int = 1000) -> list:
    """
    Divise un texte en morceaux respectant les limites de phrases.

    Args:
        text: Texte à diviser
        max_length: Longueur maximale de chaque morceau

    Returns:
        list: Liste de morceaux de texte
    """
    import re

    # Diviser en phrases
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_length:
            current_chunk += sentence + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks