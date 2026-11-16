"""RECOMPOSER un morceau depuis ses pistes séparées (2026-11-16, demande de Fabien : « refusionner les
stems pour recréer un audio complet ou partiel — par exemple en retirant seulement la batterie »).

Fabien le craignait : séparer puis fusionner DÉGRADE le son — chaque piste porte les défauts de la
séparation. La règle d'ici ne fusionne donc pas les pistes gardées : elle part de l'ORIGINAL et lui
RETIRE ce qu'on baisse,

        mélange = original + Σ (gain − 1) · piste

— tout à 1, c'est l'original exact, sans aucune perte ; une piste à 0 est retranchée, et seuls les
défauts de CETTE piste touchent le reste. La même formule servira le mixage en temps réel (gains
continus, dans la page).

Les pistes d'une séparation sont calées à l'échantillon sur leur original : lues à la même
fréquence (`audio_decode.decode_stereo`), elles se superposent sans décalage. Un mélange qui
dépasserait la pleine échelle est ramené dessous (jamais écrêté).

    mix(original, stems, gains, rate) -> ((2, n) float32, rate)
    write_wav(path, samples, rate)
"""
from __future__ import annotations


def mix(original: str, stems: dict, gains: dict, rate: int = 44100):
    """L'original (chemin) recomposé : chaque piste `stems[clé]` (chemin) pondérée par `gains[clé]`
    (1 = telle quelle, 0 = retirée ; une clé sans gain reste à 1)."""
    import numpy as np
    from .audio_decode import decode_stereo
    base, rate = decode_stereo(original, rate)
    out = base.copy()
    for key, gain in (gains or {}).items():
        path = (stems or {}).get(key)
        if not path or float(gain) == 1.0:
            continue
        part, _ = decode_stereo(path, rate)
        n = min(out.shape[1], part.shape[1])
        out[:, :n] += (float(gain) - 1.0) * part[:, :n]
    peak = float(np.abs(out).max()) if out.size else 0.0
    if peak > 1.0:
        out /= peak
    return out, rate


def write_wav(path, samples, rate: int) -> None:
    import soundfile as sf
    sf.write(str(path), samples.T, rate, subtype='PCM_16')
