"""Retard d'un signal horodaté sur un autre, par corrélation.

Deux capteurs qui observent le même phénomène sur la même horloge — le cap tiré du GPS et la
rotation vue par une caméra, une vitesse et une accélération dérivée — devraient varier ensemble.
S'ils sont décalés, c'est qu'un des deux arrive en retard (latence du récepteur, mise en tampon) :
le décalage qui maximise leur corrélation le mesure.

Fonction pure — ni Django, ni métier : deux séries (temps, valeur) et une grille de retards.
Exception §7bis comme `rts_smoother` : un noyau de calcul, sans FunctionSpec.
"""
from __future__ import annotations

import numpy as np

#: Grille par défaut : ±3 s par pas de 0,05 s.
LAGS_S = tuple(round(x, 2) for x in np.arange(-3.0, 3.0001, 0.05))


def estimate_lag(ref_t, ref_x, sig_t, sig_x, *, lags_s=LAGS_S, grid_step_s=0.05, mask=None,
                 min_samples=200):
    """Retard de `sig` sur `ref`, en secondes : `sig(t) ≈ ref(t − lag)`, donc lag > 0 = `sig` arrive APRÈS.

    Les deux séries sont rééchantillonnées sur une grille commune (`grid_step_s`) ; `mask(grid)` (booléens)
    restreint les instants comptés — par exemple aux virages, seuls à porter de l'information sur un cap.
    Rend {'lag_s', 'r', 'r_at_zero', 'samples'} ou None si les données ne suffisent pas.
    """
    rt, rx = np.asarray(ref_t, float), np.asarray(ref_x, float)
    st, sx = np.asarray(sig_t, float), np.asarray(sig_x, float)
    if len(rt) < 2 or len(st) < 2:
        return None
    span = max(abs(min(lags_s)), abs(max(lags_s)))
    lo, hi = max(rt[0], st[0]) + span, min(rt[-1], st[-1]) - span
    if hi <= lo:
        return None
    grid = np.arange(lo, hi, grid_step_s)
    sig = np.interp(grid, st, sx)
    keep = np.ones(len(grid), bool) if mask is None else np.asarray(mask(grid), bool)
    keep &= np.isfinite(sig)
    if keep.sum() < min_samples:
        return None
    best, at_zero = None, None
    for lag in lags_s:
        ref = np.interp(grid - lag, rt, rx)
        m = keep & np.isfinite(ref)
        if m.sum() < min_samples or np.std(ref[m]) == 0 or np.std(sig[m]) == 0:
            continue
        r = float(np.corrcoef(ref[m], sig[m])[0, 1])
        if abs(lag) < 1e-9:
            at_zero = r
        if best is None or r > best[0]:
            best = (r, float(lag))
    if best is None:
        return None
    return {'lag_s': round(best[1], 2), 'r': round(best[0], 3),
            'r_at_zero': None if at_zero is None else round(at_zero, 3), 'samples': int(keep.sum())}
