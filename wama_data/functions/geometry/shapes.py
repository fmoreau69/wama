"""
Géométrie Prédiction : collision de rectangles orientés (SAT) + conversion d'une
trajectoire ponctuelle en trajectoire de rectangles orientés (empreinte au sol).

Portage fidèle de RectIntersectUsingSATPrediction.m et TrajConvPointToShapePrediction.m.
Autonome (numpy pur).
"""
import numpy as np


def rect_intersect_sat(rect1, rect2):
    """
    Collision entre 2 rectangles orientés via le théorème des axes séparateurs (SAT).

    rect1, rect2 : (4, 2) — les 4 coins (ordre horaire ou anti-horaire).
    Retourne True s'ils s'intersectent (ou se touchent).
    """
    r1 = np.asarray(rect1, dtype=float)
    r2 = np.asarray(rect2, dtype=float)
    # On teste les normales des arêtes des DEUX rectangles comme axes candidats.
    for r in (r1, r2):
        for i in range(4):
            edge = r[(i + 1) % 4] - r[i]
            axis = np.array([-edge[1], edge[0]])   # normale à l'arête
            norm = np.hypot(axis[0], axis[1])
            if norm < 1e-12:
                continue
            axis /= norm
            p1 = r1 @ axis
            p2 = r2 @ axis
            # Axe séparateur si les projections ne se recouvrent pas.
            if p1.max() < p2.min() or p2.max() < p1.min():
                return False
    return True


def _sat_separated(own, other, axes, valid):
    """(N,M,4) : l'axe i de `own[a]` sépare-t-il `own[a]` de `other[b]` ?"""
    p_own = np.einsum('acd,aid->aic', own, axes)              # (N,4,4) : axe i, coin c
    p_oth = np.einsum('bcd,aid->abic', other, axes)           # (N,M,4,4)
    lo_own, hi_own = p_own.min(-1)[:, None], p_own.max(-1)[:, None]
    sep = (hi_own < p_oth.min(-1)) | (p_oth.max(-1) < lo_own)
    return sep & valid[:, None, :]


def _sat_axes(rects):
    edges = np.roll(rects, -1, axis=1) - rects                # arête i = coin i+1 − coin i
    axes = np.stack([-edges[..., 1], edges[..., 0]], axis=-1)  # normale à l'arête
    norm = np.hypot(axes[..., 0], axes[..., 1])
    valid = norm >= 1e-12                                     # arête dégénérée : pas un axe
    return axes / np.where(valid, norm, 1.0)[..., None], valid


def rect_intersect_sat_matrix(rects1, rects2):
    """`rect_intersect_sat` pour TOUTES les paires d'un coup : (N,4,2) × (M,4,2) → bool (N,M).

    Mêmes axes (normales des arêtes des deux rectangles), mêmes projections, même critère
    de recouvrement — seul l'ordre de parcours change, donc pas le verdict. Existe parce que
    la collision TTC/PET appelait la version scalaire ~340 fois par instant évalué : 75 % de
    la passe Indicateurs du cam_analyzer (profil du 2026-09-29)."""
    r1 = np.asarray(rects1, dtype=float).reshape(-1, 4, 2)
    r2 = np.asarray(rects2, dtype=float).reshape(-1, 4, 2)
    ax1, ok1 = _sat_axes(r1)
    ax2, ok2 = _sat_axes(r2)
    sep1 = _sat_separated(r1, r2, ax1, ok1).any(-1)                        # (N,M)
    sep2 = _sat_separated(r2, r1, ax2, ok2).any(-1).T                      # (M,N) → (N,M)
    return ~(sep1 | sep2)


def point_traj_to_shape(traj, length_m, width_m, min_speed=1e-6):
    """
    Trajectoire ponctuelle → trajectoire de rectangles orientés (empreinte).

    traj      : (N, 3) — colonnes [timecode, X, Y].
    length_m  : longueur de l'objet (avant→arrière).
    width_m   : largeur de l'objet (gauche→droite).
    Orientation = direction de la vitesse instantanée (comme Prédiction).

    Retourne : (N, 9) — [timecode, x1,y1, x2,y2, x3,y3, x4,y4] (4 coins/instant).
    """
    traj = np.asarray(traj, dtype=float)
    n = len(traj)
    out = np.zeros((n, 9))
    out[:, 0] = traj[:, 0]
    hl, hw = length_m / 2.0, width_m / 2.0
    # Coins locaux : avant-droit, avant-gauche, arrière-gauche, arrière-droit.
    if n == 0:
        return out
    local = np.array([[hl, -hw], [hl, hw], [-hl, hw], [-hl, -hw]])
    # Vitesse instantanée : différence AVANT, sauf au dernier point (différence arrière).
    pos = traj[:, 1:3]
    v = np.zeros((n, 2))
    if n > 1:
        v[:-1] = pos[1:] - pos[:-1]
        v[-1] = pos[-1] - pos[-2]
    speed = np.hypot(v[:, 0], v[:, 1])
    moving = speed >= min_speed
    dirs = np.vstack([[1.0, 0.0], v / np.where(moving, speed, 1.0)[:, None]])
    # Objet ~immobile : garder la dernière orientation valide (indice 0 = [1, 0] initial).
    src = np.maximum.accumulate(np.where(moving, np.arange(1, n + 1), 0))
    vx = dirs[src]
    vy = np.stack([vx[:, 1], -vx[:, 0]], axis=1)   # perpendiculaire (convention Prédiction)
    for k in range(4):
        world = pos + local[k, 0] * vx + local[k, 1] * vy
        out[:, 1 + 2 * k] = world[:, 0]
        out[:, 2 + 2 * k] = world[:, 1]
    return out
