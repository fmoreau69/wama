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

# ── PICS FINS d'un média, servis à toute page (2026-10-21, ROUTE §F3b) ─────────────────────────
# La ligne « pics : à rendre COMMUN (stockage + service) » de la matrice de parité : ils vivaient
# au transcriber (un fichier par transcription, un champ d'état, une tâche, une route). Ils suivent
# désormais le chemin de la COPIE DE LECTURE (`video_compat`, 2026-10-06) : un fichier DÉRIVÉ au
# dossier caché de l'utilisateur, à jour tant qu'il est plus récent que l'original, fabriqué par une
# tâche commune CPU une fois par version du fichier, balayé quand l'original part. L'état « en
# cours » et « échec » se lit d'une marque de cache par version (chemin, taille, date).
DENSE_SUFFIX = '.peaks.json'
#: Une version mise en file ne l'est plus pendant 30 jours ; un échec se dit pendant une heure,
#: puis la page suivante retente (la règle de l'éditeur : un échec se retente à l'ouverture).
DENSE_QUEUED_TTL = 30 * 86400
DENSE_FAILED_TTL = 3600


def _dense():
    """Le fait dérivé « pics fins » — son cycle (fichier à jour, une tâche par version, « en file »
    et « échec » lus d'une marque de cache) est celui de TOUT fait dérivé d'un média
    (`derived_json`, 2026-11-25) : il était écrit ici, pour l'onde seule."""
    from .derived_json import DerivedJson
    return DerivedJson('dense_peaks', DENSE_SUFFIX, 'wama.common.tasks:make_dense_peaks_task',
                       required='peaks', queued_ttl=DENSE_QUEUED_TTL, failed_ttl=DENSE_FAILED_TTL)


def dense_peaks_rel(rel):
    """Le chemin (relatif à MEDIA_ROOT) des pics fins d'un média — pure."""
    return _dense().rel(rel)


def dense_peaks(rel, *, schedule=True, retry_failed=False):
    """L'état des pics fins d'un média (chemin relatif d'un champ fichier) : `{'status': 'ready',
    'peaks', 'duration'}`, ou `{'status': 'pending' | 'failed' | 'none'}`. `schedule` met le calcul
    en file s'il n'y est pas ; `retry_failed` le relance après un échec (une page qui s'OUVRE, pas
    une page qui interroge). Ne lève jamais."""
    state = _dense().state(rel, schedule=schedule, retry_failed=retry_failed)
    if state['status'] != 'ready':
        return state
    data = state['data']
    return {'status': 'ready', 'peaks': data['peaks'], 'duration': data.get('duration') or 0}


def schedule_dense_peaks(rel):
    """Met en file le calcul des pics fins d'un média, UNE fois par version du fichier. Rend True
    si une tâche part. Ne lève jamais : une page ne casse pas pour une onde."""
    return _dense().schedule(rel)


def hold_dense_peaks(rel):
    """Marque la version d'un média « en file » SANS rien lancer : un témoin de scénario s'ouvre
    sur une onde « en cours », comme une page dont la tâche n'a pas encore tourné."""
    _dense().hold(rel)


def make_dense_peaks(rel):
    """Calcule et range les pics fins d'un média (ffmpeg, densité de l'éditeur, `uint8`) —
    idempotent. Rend True s'ils sont prêts. Un échec se marque (`dense_peaks` le dit)."""
    from .derived_json import absolute, version_of
    dense = _dense()
    if dense.fresh(rel):
        return True
    if version_of(rel) is None:
        return False
    peaks, duration = compute_peaks(absolute(rel), backend='ffmpeg',
                                    buckets_per_second=BUCKETS_PER_SECOND, dtype='uint8',
                                    with_duration=True)
    return dense.store(rel, {'v': 1, 'duration': duration, 'bps': BUCKETS_PER_SECOND,
                             'peaks': peaks} if peaks else None)


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
