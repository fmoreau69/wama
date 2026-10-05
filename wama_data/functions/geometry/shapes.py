"""
Géométrie Prédiction : collision de rectangles orientés (SAT) + conversion d'une
trajectoire ponctuelle en trajectoire de rectangles orientés (empreinte au sol).

Portage fidèle de RectIntersectUsingSATPrediction.m et TrajConvPointToShapePrediction.m.
Autonome (numpy pur).
"""
import numpy as np


def box_iou(a, b) -> float:
    """Recouvrement de deux boîtes alignées [x0, y0, x1, y1], de 0 à 1 (0 si l'une manque).

    Domicile unique depuis le 2026-10-05 : trois copies identiques vivaient au cam_analyzer
    (`multicam_tracker.box_iou`), au monde Data (`placement_metrics._iou`) et à l'anonymizer
    (`common/utils/detections.iou`)."""
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


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


def visible_face_to_center(x, y, length_m, width_m, axis_deg):
    """Centre d'un véhicule depuis le point mesuré sur sa FACE VISIBLE.

    Une caméra place un objet par le bas-centre de sa boîte : le point de contact au sol de la
    face qu'elle VOIT, pas le centre du véhicule — un véhicule vu de profil est placé une
    demi-largeur trop près, vu de dos une demi-longueur. (x, y) : ce point dans un repère dont
    l'ORIGINE est la caméra (x à droite, y en avant, mètres) ; `axis_deg` : axe long du véhicule
    dans ce repère (horaire depuis +y, le sens n'importe pas). Le centre est repoussé le long de
    la ligne de visée de la distance centre → bord du rectangle dans cette direction. Rend (x, y)."""
    import math
    r = math.hypot(x, y)
    if r < 1e-6:
        return x, y
    ux, uy = x / r, y / r
    phi = math.atan2(ux, uy) - math.radians(axis_deg)        # visée par rapport à l'axe long
    c, s = abs(math.cos(phi)), abs(math.sin(phi))
    hl, hw = length_m / 2.0, width_m / 2.0
    t = min(hl / c if c > 1e-9 else float('inf'), hw / s if s > 1e-9 else float('inf'))
    return x + ux * t, y + uy * t


def cut_box_face_center(inner_x, depth, side, length_m, width_m, axis_deg):
    """Milieu de la face VUE d'un véhicule dont la boîte est COUPÉE par un bord de l'image.

    Le centre d'une boîte coupée est celui de la partie VISIBLE : trop vers l'intérieur de l'image (à
    519 s, un véhicule coupé au bord gauche de l'avant était placé à 8,7 m de la mesure de la latérale
    qui le voyait entier). Le bord INTÉRIEUR, lui, n'est pas coupé : la face s'étend au-delà, de son
    étendue apparente E = L·|sin α| + W·|cos α| (α : angle entre la ligne de visée et l'axe du véhicule).
    (inner_x, depth) : point du bord intérieur dans le repère caméra (x à droite, y en avant, m) ; `side`
    = −1 si la boîte est coupée à GAUCHE (le véhicule se prolonge vers les x négatifs), +1 à droite ;
    `axis_deg` : axe long du véhicule dans ce repère. Rend (x, y) du milieu de la face vue."""
    import math
    phi = math.atan2(inner_x, depth)
    a = phi - math.radians(axis_deg)
    half = (length_m * abs(math.sin(a)) + width_m * abs(math.cos(a))) / 2.0
    return inner_x + side * half * math.cos(phi), depth - side * half * math.sin(phi)
