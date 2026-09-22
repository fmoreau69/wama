"""
WAMA Synthesizer - Audio Processor (version simplifiée)
Traitement des fichiers audio
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
    except ImportError:
        logger.warning("pydub not installed, skipping audio processing")
        return input_path

    # Si pas de transformation, retourner l'original
    if speed == 1.0 and pitch == 1.0:
        return input_path

    try:
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

    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        return input_path  # Retourner l'original en cas d'erreur


def _change_speed(audio, speed: float):
    """
    Change la vitesse d'un audio sans changer le pitch.

    Args:
        audio: AudioSegment à modifier
        speed: Facteur de vitesse

    Returns:
        AudioSegment modifié
    """
    if speed == 1.0:
        return audio

    # Méthode simple: changer le frame rate
    return audio._spawn(
        audio.raw_data,
        overrides={'frame_rate': int(audio.frame_rate * speed)}
    ).set_frame_rate(audio.frame_rate)


def _change_pitch(audio, pitch: float):
    """
    Change le pitch d'un audio.

    Args:
        audio: AudioSegment à modifier
        pitch: Facteur de pitch

    Returns:
        AudioSegment modifié
    """
    if pitch == 1.0:
        return audio

    # Méthode: changer le frame rate et résampler
    new_sample_rate = int(audio.frame_rate * pitch)

    return audio._spawn(
        audio.raw_data,
        overrides={'frame_rate': new_sample_rate}
    ).set_frame_rate(audio.frame_rate)
