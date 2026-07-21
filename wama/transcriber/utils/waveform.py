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
    """DÉLÈGUE à la brique ffmpeg_utils (audit 2026-07-06 : la copie locale n'avait ni test
    fonctionnel WSL2, ni fallback imageio, ni escape hatch FFMPEG_BINARY)."""
    from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe
    return get_ffmpeg_exe()


def peaks_path(transcript):
    """Chemin du fichier JSON de peaks pour ce transcript."""
    from wama.common.utils.media_paths import get_app_media_path
    out = get_app_media_path('transcriber', transcript.user_id, 'output')
    return out / f"{transcript.id}.peaks.json"


def compute_peaks(audio_path, buckets_per_second=BUCKETS_PER_SECOND):
    """Pics d'onde (uint8, densite) — DELEGUE au calcul UNIQUE commun
    `common.utils.waveform.compute_peaks` (mode ffmpeg/uint8/densite). Sortie identique a
    l'historique (verifie octet pour octet). Le cache/worker/endpoint transcriber restent ici.
    Ne plus dupliquer le calcul : la source unique est common/utils/waveform.py."""
    from wama.common.utils.waveform import compute_peaks as _common_compute_peaks
    return _common_compute_peaks(
        audio_path, backend='ffmpeg', buckets_per_second=buckets_per_second,
        dtype='uint8', with_duration=True)


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
