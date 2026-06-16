"""
Décodage audio robuste pour WAMA (WSL où torchcodec/torchaudio est cassé).

Problème : dans `venv_linux`, `torchcodec` ne s'importe pas (mismatch ABI torch 2.9.1)
et `torchaudio.load` passe désormais par torchcodec → cassé lui aussi. `soundfile`
(libsndfile) décode WAV/FLAC/OGG mais **PAS** l'AAC/m4a/mp3. Résultat : tout code qui
compte sur torchaudio/torchcodec pour décoder un média compressé échoue.

Ce module fournit un décodage **multi-format** sans torchaudio/torchcodec, via une
chaîne de repli : soundfile → faster-whisper (PyAV) → ffmpeg (binaire). PyAV gère tout
ce que gère ffmpeg (m4a/mp3/aac/…) — c'est le même décodeur que faster-whisper utilise
déjà pour transcrire.

Voir `memory/reference_torchcodec_broken.md`. Dépendances : numpy (+ soundfile et/ou
faster-whisper et/ou ffmpeg selon le format). Pas de dépendance torch.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)


def decode_audio(path, target_sr: int = 16000, mono: bool = True):
    """
    Décode un fichier audio en (ndarray float32, sample_rate), robuste aux formats
    compressés (m4a/aac/mp3) là où soundfile et torchaudio échouent.

    Args:
        path:      Chemin du fichier audio.
        target_sr: Fréquence cible pour les replis PyAV/ffmpeg (soundfile conserve la
                   fréquence native du fichier).
        mono:      True → tableau 1-D mono ; False → (channels, time).

    Returns:
        (numpy.ndarray float32, sample_rate:int).
        - Branche soundfile : fréquence et canaux **natifs** (downmix mono si `mono`).
        - Branches PyAV/ffmpeg : ré-échantillonné à `target_sr`, mono.

    Raises:
        RuntimeError si aucun décodeur n'aboutit.
    """
    import numpy as np

    # 1) soundfile — sans FFmpeg, lit WAV/FLAC/OGG nativement (PAS l'AAC/m4a/mp3).
    try:
        import soundfile as sf
        data, sr = sf.read(path, dtype='float32', always_2d=True)  # (time, channels)
        arr = data.mean(axis=1) if mono else data.T                # mono 1-D ou (channels, time)
        return np.ascontiguousarray(arr), sr
    except Exception as e_sf:
        logger.debug(f"[audio_decode] soundfile failed: {e_sf}, trying faster-whisper")

    # 2) faster-whisper (PyAV) — gère m4a/mp3/aac, ré-échantillonne à target_sr, mono.
    try:
        from faster_whisper.audio import decode_audio as _fw_decode
        arr = _fw_decode(path, sampling_rate=target_sr)  # float32 mono (time,)
        if not mono:
            arr = arr[None, :]
        return np.ascontiguousarray(arr), target_sr
    except Exception as e_fw:
        logger.debug(f"[audio_decode] faster-whisper decode failed: {e_fw}, trying ffmpeg")

    # 3) ffmpeg (binaire) — dernier recours, décode en PCM float32 mono @ target_sr.
    try:
        proc = subprocess.run(
            ['ffmpeg', '-nostdin', '-threads', '0', '-i', str(path),
             '-f', 'f32le', '-ac', '1', '-ar', str(target_sr), '-'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
        )
        arr = np.frombuffer(proc.stdout, dtype=np.float32)
        if not mono:
            arr = arr[None, :]
        return np.ascontiguousarray(arr), target_sr
    except Exception as e_ff:
        logger.warning(f"[audio_decode] ffmpeg decode failed: {e_ff}")

    raise RuntimeError(f"[audio_decode] aucun décodeur n'a pu lire : {path}")


def decode_for_pyannote(path, target_sr: int = 16000):
    """
    Décode en dict `{'waveform': (channels, time) torch.Tensor, 'sample_rate': int}`
    attendu par les pipelines pyannote.audio — contourne le décodeur torchcodec interne.

    Raises:
        RuntimeError si le décodage échoue (l'appelant peut retomber sur le chemin brut).
    """
    import torch
    arr, sr = decode_audio(path, target_sr=target_sr, mono=False)
    waveform = torch.from_numpy(arr).float()
    if waveform.ndim == 1:
        waveform = waveform.unsqueeze(0)
    return {'waveform': waveform, 'sample_rate': sr}
