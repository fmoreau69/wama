"""
Arithmétique d'intervalles 1D — brique GÉNÉRIQUE (listes de [début, fin], début ≤ fin).

Premier consommateur : le registre de couverture d'analyse du cam_analyzer
(quelles plages temporelles d'une vidéo ont été analysées). Conçu générique :
toute app manipulant des plages (temps, frames, offsets) peut l'utiliser.

Convention : les intervalles sont des paires [a, b] en unités quelconques mais
homogènes ; les listes retournées sont triées, disjointes et fusionnées.
"""


def merge_intervals(intervals, tol=0.0):
    """Union d'intervalles : trie, fusionne chevauchements et quasi-contigus (écart ≤ tol)."""
    ivs = sorted([float(a), float(b)] for a, b in intervals if b >= a)
    if not ivs:
        return []
    out = [ivs[0]]
    for a, b in ivs[1:]:
        if a <= out[-1][1] + tol:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def subtract_intervals(base, holes, min_len=0.0):
    """`base` − `holes` : les portions de `base` non couvertes par `holes`.
    Écarte les fragments plus courts que `min_len` (poussière d'arrondi)."""
    base = merge_intervals(base)
    holes = merge_intervals(holes)
    out = []
    for a, b in base:
        cur = a
        for ha, hb in holes:
            if hb <= cur or ha >= b:
                continue
            if ha > cur:
                out.append([cur, min(ha, b)])
            cur = max(cur, hb)
            if cur >= b:
                break
        if cur < b:
            out.append([cur, b])
    return [[a, b] for a, b in out if (b - a) >= min_len]


def total_length(intervals):
    """Longueur cumulée d'une liste d'intervalles (après fusion)."""
    return sum(b - a for a, b in merge_intervals(intervals))


def coverage_ratio(covered, scope):
    """Fraction de `scope` couverte par `covered` (0..1) ; 1.0 si scope vide."""
    scope_len = total_length(scope)
    if scope_len <= 0:
        return 1.0
    missing = total_length(subtract_intervals(scope, covered))
    return max(0.0, min(1.0, 1.0 - missing / scope_len))
