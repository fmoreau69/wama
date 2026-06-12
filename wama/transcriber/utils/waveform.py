"""
WAMA — Calcul de l'enveloppe (peaks) de forme d'onde, côté serveur.

Calculé UNE fois par fichier (asynchrone, voir workers.compute_waveform_peaks),
stocké en JSON. Le client rend ensuite uniquement la fenêtre visible au niveau de
zoom courant (rendu fenêtré). Voir TRANSCRIBER_CORRECTION.md.
"""
import os
import json
import shutil
import platform
import subprocess
import logging

logger = logging.getLogger(__name__)

# Résolution : ~50 buckets/seconde suffit pour un rendu fenêtré lisible une fois zoomé.
BUCKETS_PER_SECOND = 50
MAX_BUCKETS = 300_000          # garde-fou (≈ 100 min à 50/s)
DECODE_SR = 8000               # Hz, mono — l'enveloppe n'a pas besoin de la pleine bande


def _get_ffmpeg_path():
    """Résout le binaire ffmpeg (mirroir de _get_ffprobe_path de views.py)."""
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
    ]
    if platform.system().lower().startswith('linux'):
        candidates += [
            "/mnt/c/ffmpeg/bin/ffmpeg.exe",
            "/mnt/c/Program Files/ffmpeg/bin/ffmpeg.exe",
        ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def peaks_path(transcript):
    """Chemin du fichier JSON de peaks pour ce transcript."""
    from wama.common.utils.media_paths import get_app_media_path
    out = get_app_media_path('transcriber', transcript.user_id, 'output')
    return out / f"{transcript.id}.peaks.json"


def compute_peaks(audio_path, buckets_per_second=BUCKETS_PER_SECOND):
    """Décode l'audio (ffmpeg → PCM mono s16le) et calcule l'enveloppe max-abs par bucket.

    Retourne (peaks_uint8_list, duration_seconds) ou (None, 0) si indisponible.
    """
    import numpy as np
    ffmpeg = _get_ffmpeg_path()
    if not ffmpeg:
        logger.warning("[waveform] ffmpeg introuvable")
        return None, 0
    try:
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(audio_path),
             "-ac", "1", "-ar", str(DECODE_SR), "-f", "s16le", "-"],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.warning(f"[waveform] ffmpeg a échoué : {e.stderr[:300] if e.stderr else e}")
        return None, 0

    raw = np.frombuffer(proc.stdout, dtype=np.int16)
    n = raw.size
    if n == 0:
        return [], 0.0
    duration = n / float(DECODE_SR)
    buckets = max(1, min(MAX_BUCKETS, int(duration * buckets_per_second)))
    spb = max(1, n // buckets)               # samples par bucket
    usable = spb * buckets
    env = np.abs(raw[:usable].astype(np.float32)).reshape(buckets, spb).max(axis=1)
    peak = float(env.max()) or 1.0
    out = np.clip((env / peak) * 255.0, 0, 255).astype(np.uint8)
    return out.tolist(), duration


def write_peaks(transcript, peaks, duration):
    """Écrit le JSON de peaks sur disque."""
    path = peaks_path(transcript)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({"v": 1, "duration": duration, "bps": BUCKETS_PER_SECOND, "peaks": peaks}, f)
    return path


def read_peaks(transcript):
    """Lit le JSON de peaks (ou None si absent/illisible)."""
    path = peaks_path(transcript)
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
