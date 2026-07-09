"""
Phase 3c — calibration légère de l'homographie sol (sans mesure terrain).

L'homographie plan-sol dépend des intrinsèques (fx, fy, cx, cy — dérivables du
FoV et de la résolution) et de deux extrinsèques dominantes : la **hauteur** de
la caméra et son **pitch** (inclinaison vers le bas). Sans relevé de chantier, on
fixe la hauteur (estimée : toit navette ≈ 2,5 m) et on **résout le pitch** à
partir d'UNE référence sol connue :

  « le pixel (u, v) correspond à un point du sol situé à Y mètres devant »

La référence peut venir : (a) d'un clic UI sur un point sol à distance estimée,
(b) d'un marquage de dimension connue (largeur de voie / passage piéton), (c)
d'une valeur eyeballée. Y(pitch) est monotone (à pixel fixe sous l'horizon,
plus le pitch augmente, plus le rayon plonge → point plus proche) → bissection.

Voir CAM_ANALYZER_DISTANCE_DESIGN.md §3c. Pur (stdlib + ground_projection).
"""
from __future__ import annotations

import math
from typing import Optional

from .ground_projection import GroundProjector


def solve_homography_dlt(image_pts, ground_pts):
    """
    Homographie image→sol depuis N≥4 correspondances, par DLT (SVD).

    C'est la calibration la PLUS robuste et **sans hypothèse** hauteur/pitch/FoV :
    4 points d'un objet-sol normé (coins d'un passage piéton, d'une case…) dont on
    connaît les coordonnées-sol réelles (X, Y en mètres, repère navette) suffisent.

    `image_pts` = [(u, v), …] (pixels) ; `ground_pts` = [(X, Y), …] (mètres).
    Retourne H (3×3 numpy) telle que [X, Y, 1]ᵀ ~ H · [u, v, 1]ᵀ, ou None si dégénéré.
    """
    import numpy as np
    if len(image_pts) != len(ground_pts) or len(image_pts) < 4:
        return None
    A = []
    for (u, v), (X, Y) in zip(image_pts, ground_pts):
        A.append([-u, -v, -1, 0, 0, 0, u * X, v * X, X])
        A.append([0, 0, 0, -u, -v, -1, u * Y, v * Y, Y])
    A = np.asarray(A, dtype=float)
    try:
        _, _, Vt = np.linalg.svd(A)
    except np.linalg.LinAlgError:
        return None
    H = Vt[-1].reshape(3, 3)
    if abs(H[2, 2]) < 1e-12:
        return None
    return H / H[2, 2]


def quad_from_polygon(polygon):
    """4 coins d'un polygone ~rectangulaire (passage piéton), en pur numpy.

    Coins par extrema de (x+y)/(x−y) — robuste pour un quad grossièrement
    rectangulaire, sans dépendre d'OpenCV. Retourne [TL, TR, BR, BL] (ordre non
    garanti « navette » — passer par `order_quad_corners` ensuite).
    """
    import numpy as np
    p = np.asarray(polygon, dtype=float)
    if p.ndim != 2 or p.shape[0] < 4:
        return None
    s = p[:, 0] + p[:, 1]
    d = p[:, 0] - p[:, 1]
    tl = p[int(np.argmin(s))]
    br = p[int(np.argmax(s))]
    bl = p[int(np.argmin(d))]
    tr = p[int(np.argmax(d))]
    return [tuple(tl), tuple(tr), tuple(br), tuple(bl)]


def order_quad_corners(pts):
    """Ordonne 4 coins image en [proche-G, proche-D, loin-D, loin-G].

    Convention image : proche = bas (v grand), loin = haut (v petit).
    """
    pts = list(pts)
    if len(pts) != 4:
        return None
    by_v = sorted(pts, key=lambda p: p[1])       # v croissant : haut d'abord
    far = sorted(by_v[:2], key=lambda p: p[0])    # loin-G, loin-D
    near = sorted(by_v[2:], key=lambda p: p[0])   # proche-G, proche-D
    return [near[0], near[1], far[1], far[0]]     # nG, nD, lD, lG


def evaluate_homography(H, image_pts, ground_pts) -> dict:
    """Erreur de reprojection (RMS, max, en m) + validité géométrique."""
    import numpy as np
    Hm = np.asarray(H, dtype=float)
    errs = []
    for (u, v), (X, Y) in zip(image_pts, ground_pts):
        q = Hm @ np.array([u, v, 1.0])
        if abs(q[2]) < 1e-9:
            return {'valid': False, 'rms_error_m': float('inf'), 'max_error_m': float('inf')}
        errs.append(math.hypot(q[0] / q[2] - X, q[1] / q[2] - Y))
    rms = math.sqrt(sum(e * e for e in errs) / len(errs))
    valid = all(Y > 0 for _, Y in ground_pts)      # tous les points-sol devant
    return {'valid': valid, 'rms_error_m': round(rms, 4), 'max_error_m': round(max(errs), 4)}


def homography_from_quad(image_corners, width_m: float, length_m: float,
                         near_distance_m: float = 0.0, lateral_offset_m: float = 0.0,
                         reorder: bool = True) -> Optional[dict]:
    """
    Homographie depuis les 4 coins d'un passage (image) + ses dimensions réelles.

    Cœur PARTAGÉ auto (SAM3 : polygone → `quad_from_polygon` → ici) et manuel
    (clics ordonnés → `reorder=False`). Retourne {H, ground_points, image_corners,
    rms_error_m, max_error_m, valid} ou None.
    """
    corners = order_quad_corners(image_corners) if reorder else list(image_corners)
    if corners is None or len(corners) != 4:
        return None
    W, L, X0, Y0 = width_m, length_m, lateral_offset_m, near_distance_m
    ground = [
        [-W / 2 + X0, Y0], [W / 2 + X0, Y0],
        [W / 2 + X0, Y0 + L], [-W / 2 + X0, Y0 + L],
    ]
    H = solve_homography_dlt([(float(u), float(v)) for u, v in corners], ground)
    if H is None:
        return None
    ev = evaluate_homography(H, corners, ground)
    return {'H': H.tolist(), 'ground_points': ground,
            'image_corners': [[float(u), float(v)] for u, v in corners], **ev}


def intrinsics_from_fov(width: int, height: int,
                        hfov_deg: float, vfov_deg: Optional[float] = None) -> dict:
    """Intrinsèques pinhole depuis le FoV horizontal (et vertical si fourni)."""
    fx = (width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    fy = ((height / 2.0) / math.tan(math.radians(vfov_deg) / 2.0)) if vfov_deg else fx
    return {'fx_px': fx, 'fy_px': fy, 'cx_px': width / 2.0, 'cy_px': height / 2.0}


def _longitudinal_at(u: float, v: float, intr: dict, height_m: float,
                     pitch_deg: float) -> Optional[float]:
    calib = dict(intr, height_m=height_m, pitch_deg=pitch_deg)
    proj = GroundProjector(calib)
    xy = proj.project(u, v)
    return xy[1] if xy else None   # Y = distance longitudinale


def solve_pitch_from_reference(u: float, v: float, target_Y_m: float,
                               intr: dict, height_m: float,
                               pitch_lo: float = 0.5, pitch_hi: float = 60.0,
                               tol_m: float = 0.02, iters: int = 60) -> Optional[float]:
    """
    Résout le pitch (deg) tel que le pixel (u, v) tombe à `target_Y_m` devant.

    Bissection : Y décroît quand le pitch croît. Retourne None si la référence
    n'est pas atteignable dans [pitch_lo, pitch_hi] (point mal choisi / au-dessus
    de l'horizon sur toute la plage).
    """
    def Y(p):
        return _longitudinal_at(u, v, intr, height_m, p)

    lo, hi = pitch_lo, pitch_hi
    # Au pitch fort, le pixel doit être sous l'horizon (Y défini) ; sinon insoluble.
    if Y(hi) is None:
        return None
    # Aux petits pitchs le pixel peut être AU-DESSUS de l'horizon (Y indéfini) :
    # on remonte `lo` jusqu'à la frontière horizon (plus petit pitch où Y existe).
    if Y(lo) is None:
        a, b = lo, hi
        for _ in range(iters):
            m = (a + b) / 2
            if Y(m) is None:
                a = m
            else:
                b = m
        lo = b
    y_lo, y_hi = Y(lo), Y(hi)          # Y(lo) grand (près horizon) → Y(hi) petit
    if y_lo is None:
        return None
    if not (y_hi - tol_m <= target_Y_m <= y_lo + tol_m):
        return None                    # cible hors de la plage atteignable
    for _ in range(iters):
        mid = (lo + hi) / 2
        y = Y(mid)
        if y is None:                  # garde-fou : pitch trop faible
            lo = mid
            continue
        if abs(y - target_Y_m) <= tol_m:
            return round(mid, 3)
        # Y décroît avec le pitch : Y trop grand → augmenter le pitch
        if y > target_Y_m:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 3)


def build_calibration(width: int, height: int, hfov_deg: float, height_m: float,
                      ref_u: float, ref_v: float, ref_distance_m: float,
                      vfov_deg: Optional[float] = None) -> Optional[dict]:
    """
    Construit un dict de calibration prêt pour le profil (`camera_calibration[pos]`)
    depuis : résolution, FoV, hauteur estimée, et UNE référence sol (pixel + distance).
    Retourne None si le pitch n'est pas résoluble.
    """
    intr = intrinsics_from_fov(width, height, hfov_deg, vfov_deg)
    pitch = solve_pitch_from_reference(ref_u, ref_v, ref_distance_m, intr, height_m)
    if pitch is None:
        return None
    return dict(intr, height_m=height_m, pitch_deg=pitch,
                hfov_deg=hfov_deg, lens_type='rectilinear')
