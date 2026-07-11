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
    local = np.array([[hl, -hw], [hl, hw], [-hl, hw], [-hl, -hw]])
    last_dir = np.array([1.0, 0.0])
    for i in range(n):
        v = (traj[i + 1, 1:3] - traj[i, 1:3]) if i < n - 1 else (traj[i, 1:3] - traj[i - 1, 1:3]) if i > 0 else np.zeros(2)
        speed = np.hypot(v[0], v[1])
        if speed >= min_speed:
            vx = v / speed
            last_dir = vx
        else:
            vx = last_dir           # objet ~immobile : garder la dernière orientation
        vy = np.array([vx[1], -vx[0]])   # perpendiculaire (convention Prédiction)
        pos = traj[i, 1:3]
        for k in range(4):
            world = pos + local[k, 0] * vx + local[k, 1] * vy
            out[i, 1 + 2 * k] = world[0]
            out[i, 2 + 2 * k] = world[1]
    return out
