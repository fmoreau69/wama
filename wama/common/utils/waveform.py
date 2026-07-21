"""Pics de forme d'onde pré-calculés côté serveur (« waveform par parties »).

Centralise dans `common/` le mécanisme CONÇU mais reporté par la correction Transcriber
(`TRANSCRIBER_CORRECTION.md` §5ter) : le SERVEUR downsample l'audio en N pics d'amplitude → le
client dessine l'onde SANS décoder tout le PCM en mémoire. Bénéficie :
- aux **fichiers longs** (le player commun échoue à décoder en mémoire → aujourd'hui repli timeline
  sans amplitude ; avec des pics serveur, l'onde reste dessinable) ;
- au **streaming « pendant »** (chantier 2) : le worker émet des pics par fenêtre au fil de la
  génération (`publish_partial_peaks`), le front les ajoute → onde qui se construit (effet « Suno »).

Contrat : `compute_peaks` ne lève JAMAIS (retourne `[]` si illisible) — le client garde son repli.
"""


def compute_peaks(source, buckets=800):
    """N pics d'amplitude normalisés [0..1] (max |amplitude| par tranche).

    `source` : chemin de fichier audio OU tableau/liste PCM (mono ou stéréo ; numpy accepté).
    `buckets` : nombre de pics voulus (résolution horizontale de l'onde).
    Retourne `[]` si l'audio est illisible ou vide (le client a un repli timeline — jamais d'erreur).
    """
    try:
        import numpy as np
    except Exception:
        return []

    if isinstance(source, (str, bytes)) or hasattr(source, '__fspath__'):
        try:
            import soundfile as sf
            data, _sr = sf.read(str(source), dtype='float32', always_2d=False)
        except Exception:
            return []
    else:
        data = source

    try:
        arr = np.asarray(data, dtype='float32')
        if arr.ndim > 1:                      # stéréo/multi → mono
            arr = arr.mean(axis=1)
        n = int(arr.shape[0])
        if n == 0 or buckets <= 0:
            return []
        buckets = min(int(buckets), n)
        idx = np.linspace(0, n, buckets + 1, dtype=int)
        peaks = [float(np.abs(arr[idx[i]:idx[i + 1]]).max()) if idx[i + 1] > idx[i] else 0.0
                 for i in range(buckets)]
        m = max(peaks) or 1.0
        return [round(p / m, 4) for p in peaks]
    except Exception:
        return []
