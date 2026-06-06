"""
Audio Preprocessing Module for WAMA Transcriber
================================================
Prétraitement IA avant transcription Whisper.

Remplace l'ancien pipeline (pydub normalize + noisereduce / spectral-gating) qui
dégradait souvent l'ASR (artefacts « musical noise », perte d'énergie de parole).
On s'appuie désormais sur le débruitage IA **DeepFilterNet** de l'enhancer
(discriminatif, préserve la structure de parole → sûr pour l'ASR), suivi d'une
mise au format ASR minimale : 16 kHz mono + normalisation crête légère.

Pas de couche de correction supplémentaire : le sur-traitement nuit à l'ASR.
Modern Whisper étant robuste au bruit, ce prétraitement reste OPTIONNEL.

Le backend DeepFilterNet est un singleton partagé (keep_loaded) : aucun
rechargement entre fichiers d'un batch, et il cohabite avec l'ASR (Whisper) en
VRAM (<1 Go). Voir wama/enhancer/utils/audio_enhancer.get_deepfilternet_backend().
"""

import os
import logging

import numpy as np
import librosa
import soundfile as sf

logger = logging.getLogger(__name__)

_ASR_SR = 16000  # entrée native de Whisper


class AudioPreprocessor:
    """Prétraitement audio IA (DeepFilterNet) + mise au format ASR."""

    def __init__(self, target_sr=_ASR_SR, noise_reduction=0.5, stationary=False):
        # `noise_reduction` / `stationary` : conservés pour compat d'API. L'ancien
        # spectral-gating (noisereduce) est remplacé par le débruitage IA et ces
        # paramètres ne sont plus utilisés.
        self.target_sr = target_sr or _ASR_SR

    def preprocess(self, input_path, output_path=None):
        """Débruite (IA) puis met l'audio au format ASR. Retourne le chemin de sortie."""
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Le fichier {input_path} n'existe pas")

        if output_path is None:
            base = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(os.path.dirname(input_path), f"{base}_cleaned.wav")

        logger.info(f"Prétraitement audio (DeepFilterNet) : {input_path}")

        # 1) Débruitage IA via DeepFilterNet (singleton keep_loaded de l'enhancer)
        source = input_path
        tmp_denoised = None
        try:
            from wama.enhancer.utils.audio_enhancer import (
                get_deepfilternet_backend, DeepFilterNetBackend,
            )
            if DeepFilterNetBackend.is_available():
                tmp_denoised = output_path + ".dfn.wav"
                get_deepfilternet_backend().enhance(input_path, tmp_denoised)
                source = tmp_denoised
            else:
                logger.warning("[preprocess] DeepFilterNet indisponible — "
                               "mise au format ASR uniquement (pas de débruitage)")
        except Exception as e:
            logger.warning(f"[preprocess] Débruitage IA ignoré ({e}) — "
                           "mise au format ASR uniquement")
            source = input_path

        # 2) Mise au format ASR : 16 kHz mono + normalisation crête légère
        try:
            y, _ = librosa.load(source, sr=self.target_sr, mono=True)
            peak = float(np.max(np.abs(y))) if y.size else 0.0
            if peak > 0:
                y = y * (0.97 / peak)  # crête ~-0.26 dBFS, évite la saturation
            sf.write(output_path, y, self.target_sr, subtype='PCM_16')
        finally:
            if tmp_denoised and os.path.exists(tmp_denoised):
                try:
                    os.remove(tmp_denoised)
                except OSError:
                    pass

        logger.info(f"Prétraitement terminé : {output_path}")
        return output_path

    def preprocess_batch(self, input_files, output_dir=None, keep_originals=True):
        """Prétraite plusieurs fichiers. Retourne la liste des chemins traités."""
        processed = []
        for f in input_files:
            try:
                out = None
                if output_dir:
                    base = os.path.splitext(os.path.basename(f))[0]
                    out = os.path.join(output_dir, f"{base}_cleaned.wav")
                processed.append(self.preprocess(f, out))
            except Exception as e:
                logger.error(f"Erreur prétraitement {f} : {e}")
        return processed


def preprocess_audio_file(input_path, output_path=None, **kwargs):
    """Helper : prétraite rapidement un fichier audio."""
    return AudioPreprocessor(**kwargs).preprocess(input_path, output_path)
