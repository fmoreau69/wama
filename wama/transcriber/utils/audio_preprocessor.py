"""
Audio Preprocessing Module for WAMA Transcriber
Améliore la qualité audio avant transcription Whisper
"""

import os
import tempfile
import numpy as np
import librosa
import noisereduce as nr
from pydub import AudioSegment, effects
from scipy.io.wavfile import write
import logging

logger = logging.getLogger(__name__)


class AudioPreprocessor:
    """
    Classe pour prétraiter les fichiers audio avant transcription.
    Améliore la qualité en normalisant, réduisant le bruit et ajustant le volume.
    """

    def __init__(self, target_sr=16000, noise_reduction=0.5, stationary=False):
        """
        Initialise le préprocesseur audio.

        Args:
            target_sr (int): Fréquence d'échantillonnage cible (16000 Hz recommandé pour Whisper)
            noise_reduction (float): Niveau de réduction de bruit (0.0-1.0, 0.5 recommandé)
            stationary (bool): Si True, adapté aux bruits constants; False pour la parole
        """
        self.target_sr = target_sr
        self.noise_reduction = noise_reduction
        self.stationary = stationary

    def preprocess(self, input_path, output_path=None):
        """
        Prétraite un fichier audio pour améliorer la qualité de transcription.

        Args:
            input_path (str): Chemin du fichier audio d'entrée
            output_path (str, optional): Chemin du fichier de sortie.
                                        Si None, crée un fichier temporaire.

        Returns:
            str: Chemin du fichier audio prétraité

        Raises:
            FileNotFoundError: Si le fichier d'entrée n'existe pas
            Exception: En cas d'erreur lors du traitement
        """
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Le fichier {input_path} n'existe pas")

        logger.info(f"Début du prétraitement audio: {input_path}")

        try:
            # Générer un nom de fichier de sortie si nécessaire
            if output_path is None:
                output_dir = os.path.dirname(input_path)
                base_name = os.path.splitext(os.path.basename(input_path))[0]
                output_path = os.path.join(output_dir, f"{base_name}_cleaned.wav")

            # Étape 1: Normalisation avec Pydub
            logger.debug("Étape 1: Chargement et normalisation avec Pydub")
            temp_wav = self._normalize_with_pydub(input_path)

            # Étape 2: Réduction de bruit avec librosa et noisereduce
            logger.debug("Étape 2: Réduction de bruit")
            cleaned_audio = self._reduce_noise(temp_wav)

            # Étape 3: Sauvegarde du fichier final
            logger.debug("Étape 3: Sauvegarde du fichier nettoyé")
            self._save_audio(cleaned_audio, output_path)

            # Nettoyage du fichier temporaire
            if os.path.exists(temp_wav):
                os.remove(temp_wav)

            logger.info(f"Prétraitement terminé: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Erreur lors du prétraitement: {str(e)}")
            raise

    def _normalize_with_pydub(self, input_path):
        """
        Normalise l'audio avec Pydub (conversion mono, fréquence, volume).

        Args:
            input_path (str): Chemin du fichier audio

        Returns:
            str: Chemin du fichier temporaire normalisé
        """
        try:
            # Charger l'audio avec Pydub (supporte MP3, WAV, M4A, etc.)
            audio = AudioSegment.from_file(input_path)

            # Convertir en mono et ajuster la fréquence d'échantillonnage
            audio = audio.set_channels(1).set_frame_rate(self.target_sr)

            # Normaliser le volume (laisse 2.5dB de marge pour éviter la saturation)
            audio = effects.normalize(audio, headroom=2.5)

            # Sauvegarder dans un fichier temporaire
            temp_fd, temp_path = tempfile.mkstemp(suffix='.wav')
            os.close(temp_fd)
            audio.export(temp_path, format="wav")

            return temp_path

        except Exception as e:
            logger.error(f"Erreur lors de la normalisation Pydub: {str(e)}")
            raise

    def _reduce_noise(self, audio_path):
        """
        Réduit le bruit de l'audio en utilisant librosa et noisereduce.

        Args:
            audio_path (str): Chemin du fichier audio à traiter

        Returns:
            np.ndarray: Audio nettoyé sous forme de tableau numpy
        """
        try:
            # Charger l'audio avec librosa
            y, sr = librosa.load(audio_path, sr=self.target_sr)

            # Normaliser l'amplitude
            if np.max(np.abs(y)) > 0:
                y = y / np.max(np.abs(y))

            # Appliquer la réduction de bruit
            y_denoised = nr.reduce_noise(
                y=y,
                sr=sr,
                prop_decrease=self.noise_reduction,
                stationary=self.stationary
            )

            # Réamplification douce post-filtrage
            gain = 0.95 if np.max(np.abs(y_denoised)) > 0 else 1.0
            y_final = y_denoised * gain

            return y_final

        except Exception as e:
            logger.error(f"Erreur lors de la réduction de bruit: {str(e)}")
            raise

    def _save_audio(self, audio_data, output_path):
        """
        Sauvegarde les données audio dans un fichier WAV.

        Args:
            audio_data (np.ndarray): Données audio normalisées (valeurs entre -1 et 1)
            output_path (str): Chemin du fichier de sortie
        """
        try:
            # Convertir en int16 pour le format WAV
            audio_int16 = (audio_data * 32767).astype(np.int16)

            # Sauvegarder le fichier
            write(output_path, self.target_sr, audio_int16)

        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde: {str(e)}")
            raise

    def preprocess_batch(self, input_files, output_dir=None, keep_originals=True):
        """
        Prétraite plusieurs fichiers audio en batch.

        Args:
            input_files (list): Liste des chemins des fichiers à traiter
            output_dir (str, optional): Répertoire de sortie. Si None, utilise le même que l'entrée
            keep_originals (bool): Si True, garde les fichiers originaux

        Returns:
            list: Liste des chemins des fichiers prétraités
        """
        processed_files = []

        for input_file in input_files:
            try:
                if output_dir:
                    base_name = os.path.splitext(os.path.basename(input_file))[0]
                    output_path = os.path.join(output_dir, f"{base_name}_cleaned.wav")
                else:
                    output_path = None

                cleaned_file = self.preprocess(input_file, output_path)
                processed_files.append(cleaned_file)

            except Exception as e:
                logger.error(f"Erreur lors du traitement de {input_file}: {str(e)}")
                continue

        return processed_files


# Fonction utilitaire pour une utilisation rapide
def preprocess_audio_file(input_path, output_path=None, **kwargs):
    """
    Fonction helper pour prétraiter rapidement un fichier audio.

    Args:
        input_path (str): Chemin du fichier audio d'entrée
        output_path (str, optional): Chemin du fichier de sortie
        **kwargs: Arguments supplémentaires pour AudioPreprocessor

    Returns:
        str: Chemin du fichier audio prétraité
    """
    preprocessor = AudioPreprocessor(**kwargs)
    return preprocessor.preprocess(input_path, output_path)