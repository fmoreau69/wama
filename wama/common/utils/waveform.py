"""Forme d'onde : calcul UNIQUE et centralisé des pics d'amplitude (« waveform par parties »).

Source unique pour TOUTE l'app WAMA (unifie l'ex-`transcriber/utils/waveform.py` et l'ancien doublon
`common`). Un seul `compute_peaks`, paramétrable :

- **backend** : `ffmpeg` (décode n'importe quel format, fichiers longs — mode éditeur/transcriber)
  · `soundfile` (rapide, wav/flac) · `array` (PCM déjà en mémoire — streaming « pendant ») · `auto`.
- **résolution** : `buckets_per_second` (densité fixe → N variable selon la durée, mode éditeur) OU
  `buckets` (N absolu, mode aperçu à largeur fixe).
- **dtype** : `uint8` (0–255, compact — format de transport/cache CANONIQUE) OU `float` (0–1).
- **with_duration** : retourne `(peaks, duration_s)`.

Le transcriber délègue ici (mode `ffmpeg`, `buckets_per_second=50`, `uint8`) — sortie identique à
son implémentation historique. La preview/streaming l'appelle en mode `array`/`buckets` `uint8`.
Contrat : ne lève JAMAIS (retourne `[]`/`(None|[], 0)`) — le client garde son repli.
"""

BUCKETS_PER_SECOND = 50          # densité éditeur (transcriber historique)
MAX_BUCKETS = 300_000            # garde-fou (~100 min à 50/s)
DECODE_SR = 8000                 # l'enveloppe n'a pas besoin de la pleine bande


def _decode_ffmpeg(audio_path):
    """(int16 mono @ DECODE_SR, sr) via ffmpeg, ou (None, 0). Même commande que l'historique."""
    import subprocess
    try:
        import numpy as np
        from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe
        ffmpeg = get_ffmpeg_exe()
        if not ffmpeg:
            return None, 0
        proc = subprocess.run(
            [str(ffmpeg), "-v", "error", "-i", str(audio_path),
             "-ac", "1", "-ar", str(DECODE_SR), "-f", "s16le", "-"],
            capture_output=True, check=True,
        )
        return np.frombuffer(proc.stdout, dtype=np.int16), DECODE_SR
    except Exception:
        return None, 0


def _decode_soundfile(audio_path):
    """(float32 mono, sr) via soundfile, ou (None, 0)."""
    try:
        import numpy as np
        import soundfile as sf
        data, sr = sf.read(str(audio_path), dtype='float32', always_2d=False)
        arr = np.asarray(data, dtype='float32')
        if arr.ndim > 1:
            arr = arr.mean(axis=1)
        return arr, int(sr)
    except Exception:
        return None, 0


def compute_peaks(source, buckets=800, *, buckets_per_second=None, sr=None,
                  backend='auto', dtype='float', with_duration=False):
    """Pics d'amplitude d'un audio. Voir le docstring de module pour les modes.

    `source` : chemin de fichier OU tableau/liste PCM (mono/stéréo ; numpy accepté).
    `buckets` : N absolu (mode aperçu). `buckets_per_second` : densité (mode éditeur ; prioritaire).
    `sr` : requis pour la durée en mode `array` (sinon durée = 0).
    Retourne une liste de pics, ou `(peaks, duration)` si `with_duration`.
    """
    def _ret(peaks, duration):
        return (peaks, duration) if with_duration else peaks

    try:
        import numpy as np
    except Exception:
        return _ret([], 0.0)

    # ── 1) échantillons + sr ────────────────────────────────────────────────
    is_path = isinstance(source, (str, bytes)) or hasattr(source, '__fspath__')
    if is_path:
        raw, s_sr = (None, 0)
        if backend in ('ffmpeg', 'auto'):
            raw, s_sr = _decode_ffmpeg(source)
        if raw is None and backend in ('soundfile', 'auto'):
            raw, s_sr = _decode_soundfile(source)
        if raw is None:
            return _ret(None, 0)                 # indisponible (contrat historique transcriber)
    else:
        raw = np.asarray(source)
        if raw.ndim > 1:
            raw = raw.mean(axis=1)
        s_sr = int(sr or 0)

    n = int(raw.size)
    if n == 0:
        return _ret([], 0.0)

    # ── 2) durée + nombre de buckets ────────────────────────────────────────
    duration = (n / float(s_sr)) if s_sr else 0.0
    if buckets_per_second:
        nb = max(1, min(MAX_BUCKETS, int(duration * buckets_per_second))) if duration else \
             max(1, min(MAX_BUCKETS, int(buckets)))
    else:
        nb = max(1, min(int(buckets), n))

    # ── 3) enveloppe max-abs par bucket (reshape tronqué : identique à l'historique) ──
    try:
        spb = max(1, n // nb)
        usable = spb * nb
        env = np.abs(raw[:usable].astype(np.float32)).reshape(nb, spb).max(axis=1)
        peak = float(env.max()) or 1.0
        if dtype == 'uint8':
            out = np.clip((env / peak) * 255.0, 0, 255).astype(np.uint8).tolist()
        else:
            out = [round(float(v), 4) for v in (env / peak)]
        return _ret(out, duration)
    except Exception:
        return _ret([], duration)
