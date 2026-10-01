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
    #    Via le résolveur commun (ffmpeg WSL2 peu fiable → override FFMPEG_BINARY possible,
    #    y compris un ffmpeg.exe Windows ; adapt_path adapte alors le chemin /mnt → C:\).
    try:
        from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe, adapt_path_for_ffmpeg
        _ff = get_ffmpeg_exe()
        proc = subprocess.run(
            [_ff, '-nostdin', '-threads', '0', '-i', adapt_path_for_ffmpeg(str(path), _ff),
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


def resample(samples, rate: int, target_sr: int):
    """Échantillons mono → float32 à `target_sr` (polyphase, scipy) ; inchangés s'ils y sont."""
    from math import gcd

    import numpy as np
    samples = np.asarray(samples, dtype=np.float32)
    if int(rate) == int(target_sr):
        return samples
    from scipy.signal import resample_poly
    g = gcd(int(target_sr), int(rate))
    return resample_poly(samples, int(target_sr) // g, int(rate) // g).astype(np.float32)


def decode_audio_at(path, target_sr: int = 16000):
    """(mono float32 à `target_sr` GARANTI, `target_sr`) — ce qu'attend un modèle de parole.

    `decode_audio` laisse un WAV/FLAC à sa fréquence NATIVE (branche soundfile). Trois
    consommateurs rééchantillonnaient chacun à leur façon (NeMo, Qwen3-ASR, le banc
    `asr_eval_corpus`), et deux backends neufs l'ont oublié le 2026-10-01 : Kyutai a « entendu »
    un 16 kHz pris pour du 24 kHz, accéléré de moitié. Ce geste-là est unique, ici."""
    arr, sr = decode_audio(path, target_sr=target_sr, mono=True)
    return resample(arr, sr, target_sr), int(target_sr)


def transcode_to_wav(path, out_path, target_sr: int = 16000):
    """
    Réécrit un média en WAV PCM 16 bits mono à `target_sr`, via ffmpeg — rend `out_path`.

    Pour ce qui exige un FICHIER lisible partout (soundfile, un fournisseur distant qui
    n'accepte que wav/mp3) là où `decode_audio` rend un tableau en mémoire. 16 kHz mono est ce
    qu'un modèle de parole consomme de toute façon : rien de ce qu'il entend n'est perdu.
    `target_sr=None` garde la fréquence D'ORIGINE — ce que veut un fichier RANGÉ (une voix de
    clonage en médiathèque : le moteur qui la lira rééchantillonne à SON besoin, pas au nôtre).

    Raises:
        subprocess.CalledProcessError si ffmpeg échoue.
    """
    from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe, adapt_path_for_ffmpeg
    _ff = get_ffmpeg_exe()
    rate = ['-ar', str(target_sr)] if target_sr else []
    subprocess.run(
        [_ff, '-nostdin', '-y', '-i', adapt_path_for_ffmpeg(str(path), _ff),
         '-ac', '1', *rate, '-c:a', 'pcm_s16le',
         adapt_path_for_ffmpeg(str(out_path), _ff)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )
    return str(out_path)


def probe_duration_seconds(path):
    """
    Durée d'un média en secondes via ffprobe — SANS décoder (coût négligeable).

    Renvoie float, ou None si la sonde échoue (l'appelant peut alors estimer la durée
    autrement, ex. via le dernier segment ASR). Réutilisable par toute app.
    """
    try:
        from wama.common.utils.ffmpeg_utils import get_ffprobe_exe, adapt_path_for_ffmpeg
        exe = get_ffprobe_exe()
        out = subprocess.run(
            [exe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', adapt_path_for_ffmpeg(str(path), exe)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, text=True,
        )
        return float(out.stdout.strip())
    except Exception as e:
        logger.debug(f"[audio_decode] probe_duration_seconds failed: {e}")
        return None


def decode_window(path, target_sr: int = 16000, start_s: float = 0.0,
                  duration_s=None, mono: bool = True):
    """
    Décode UNE FENÊTRE [start_s, start_s+duration_s] d'un média en (ndarray float32, sr),
    via ffmpeg (seek en entrée `-ss` avant `-i` = rapide sur gros fichiers).

    Permet de traiter un long média **sans jamais le charger entièrement en mémoire**
    (RAM bornée à ~une fenêtre) — indispensable là où le décodage complet d'un 2h+
    fait exploser la RAM (torchcodec cassé → pas de décodage streamé natif). Réutilisable
    par toute app (diarisation par tranches, prévisualisation, extraction de segment…).

    Args:
        start_s:     début de la fenêtre (s). duration_s: durée (s) ou None (jusqu'à la fin).
        mono:        True → 1-D mono ; False → (1, time).
    """
    import numpy as np
    from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe, adapt_path_for_ffmpeg
    _ff = get_ffmpeg_exe()
    cmd = [_ff, '-nostdin', '-threads', '0']
    if start_s and start_s > 0:
        cmd += ['-ss', f'{float(start_s):.3f}']            # seek RAPIDE (avant -i)
    cmd += ['-i', adapt_path_for_ffmpeg(str(path), _ff)]
    if duration_s is not None:
        cmd += ['-t', f'{float(duration_s):.3f}']
    cmd += ['-f', 'f32le', '-ac', '1', '-ar', str(target_sr), '-']
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)
    arr = np.frombuffer(proc.stdout, dtype=np.float32)
    if not mono:
        arr = arr[None, :]
    return np.ascontiguousarray(arr), target_sr


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
