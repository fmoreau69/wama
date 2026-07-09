"""
Phase 3b — projection sol par homographie (socle géométrique).

Voir CAM_ANALYZER_DISTANCE_DESIGN.md. Idée : le **point-sol** d'un objet
(centre-bas de sa bbox, supposé au contact du sol) est projeté par une
homographie `H` (image → plan-sol, mètres, repère navette) en une position
`(X, Y)` :

  X = écart latéral (droite +)      → dist_lateral_m
  Y = distance longitudinale (avant +) → dist_longitudinal_m
  ‖(X, Y)‖                          → dist_euclid_m

`H` provient, par ordre de priorité (couche de fusion en 3c) :
  1. une matrice `homography` fournie directement dans la calibration ;
  2. un calcul analytique plan-sol depuis intrinsèques (fx,fy,cx,cy) +
     extrinsèques (hauteur, pitch[, yaw, roll]) — cf. `build_homography` ;
  3. sinon `None` → l'appelant retombe sur le pinhole (`distance_speed`).

Ce module ne DÉCIDE pas de la source : il construit/applique `H` et expose
la distance pinhole en repli. La stratégie de confrontation lignes⟷pinhole
vit dans la couche de fusion (à venir, `homography_estimator.py`).

Dépend de numpy uniquement (testable hors Django).
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np


# ── Géométrie de base ─────────────────────────────────────────────────

def foot_point(bbox) -> tuple[float, float]:
    """Point-sol d'une bbox [x1, y1, x2, y2] : centre horizontal, bord bas."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, float(max(y1, y2)))


def _K(fx: float, fy: float, cx: float, cy: float) -> np.ndarray:
    return np.array([[fx, 0.0, cx],
                     [0.0, fy, cy],
                     [0.0, 0.0, 1.0]], dtype=float)


def _rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)


def _rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)


def _rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)


def build_homography(calib: dict, image_size: Optional[tuple] = None) -> Optional[np.ndarray]:
    """
    Construit `H` (image → sol, 3×3) depuis la calibration d'une caméra.

    Repère monde (navette) : X droite, Y avant, Z haut ; caméra à la hauteur
    `height_m`, axe optique incliné vers le bas de `pitch_deg`.

    Retourne `None` si les paramètres sont insuffisants (→ fallback pinhole).
    """
    if not calib:
        return None

    # (1) Homographie fournie directement.
    Hdirect = calib.get('homography')
    if Hdirect is not None:
        H = np.asarray(Hdirect, dtype=float)
        if H.shape == (3, 3):
            return H
        return None

    # (2) Analytique depuis intrinsèques + extrinsèques.
    fx = calib.get('fx_px')
    fy = calib.get('fy_px')
    cx = calib.get('cx_px')
    cy = calib.get('cy_px')

    # Intrinsèques dérivables d'un FoV si focale absente et image connue.
    if (fx is None or fy is None) and image_size is not None:
        w, h = image_size
        fov_h = calib.get('fov_h_deg')
        fov_v = calib.get('fov_v_deg')
        if fx is None and fov_h:
            fx = (w / 2.0) / math.tan(math.radians(fov_h) / 2.0)
        if fy is None and fov_v:
            fy = (h / 2.0) / math.tan(math.radians(fov_v) / 2.0)
        if fx is not None and fy is None:
            fy = fx
        if fy is not None and fx is None:
            fx = fy
        if cx is None:
            cx = w / 2.0
        if cy is None:
            cy = h / 2.0

    height_m = calib.get('height_m')
    pitch_deg = calib.get('pitch_deg')
    if None in (fx, fy, cx, cy, height_m, pitch_deg):
        return None

    # Rotation monde→caméra. Base (pitch=0) : Z_cam=+Y_monde (avant),
    # X_cam=+X_monde (droite), Y_cam=-Z_monde (bas).
    R0 = np.array([[1, 0, 0],
                   [0, 0, -1],
                   [0, 1, 0]], dtype=float)
    # pitch = bascule de l'axe optique vers le bas (autour de X_cam).
    R = _rot_x(math.radians(pitch_deg)) @ R0
    if calib.get('yaw_deg'):
        R = _rot_y(math.radians(calib['yaw_deg'])) @ R
    if calib.get('roll_deg'):
        R = _rot_z(math.radians(calib['roll_deg'])) @ R

    K = _K(fx, fy, cx, cy)
    # Point sol (X, Y, 0), caméra en (0,0,h) → P - C = (X, Y, -h).
    # pixel ~ K R [[1,0,0],[0,1,0],[0,0,-h]] (X,Y,1)^T  =  H_g2i (X,Y,1)^T
    G = np.array([[1, 0, 0],
                  [0, 1, 0],
                  [0, 0, -height_m]], dtype=float)
    H_g2i = K @ R @ G
    try:
        H = np.linalg.inv(H_g2i)
    except np.linalg.LinAlgError:
        return None
    return H


def _undistort_pixel(u: float, v: float, calib: dict) -> tuple[float, float]:
    """
    Redresse un pixel distordu (modèle radial-tangentiel Brown-Conrady).

    Identité si aucun coefficient. Le fisheye fort (lens_type='fisheye')
    nécessite un modèle équidistant dédié — non implémenté ici : on renvoie
    le pixel tel quel et l'appelant doit baisser la confiance (TODO 3c).
    ENA_CASA (quasi-rectiligne) ne requiert pas d'undistorsion.
    """
    dist = calib.get('distortion')
    fx, fy = calib.get('fx_px'), calib.get('fy_px')
    cx, cy = calib.get('cx_px'), calib.get('cy_px')
    if not dist or None in (fx, fy, cx, cy):
        return u, v
    k1, k2, p1, p2, k3 = (list(dist) + [0, 0, 0, 0, 0])[:5]
    # pixel → normalisé
    x = (u - cx) / fx
    y = (v - cy) / fy
    # inversion itérative de la distorsion
    xu, yu = x, y
    for _ in range(5):
        r2 = xu * xu + yu * yu
        radial = 1 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
        dx = 2 * p1 * xu * yu + p2 * (r2 + 2 * xu * xu)
        dy = p1 * (r2 + 2 * yu * yu) + 2 * p2 * xu * yu
        xu = (x - dx) / radial
        yu = (y - dy) / radial
    return xu * fx + cx, yu * fy + cy


class GroundProjector:
    """
    Applique une homographie caméra pour convertir des bbox en positions sol.
    Instancié par (calibration de la caméra, taille image). Sans `H` calculable,
    `distances_for_bbox` renvoie None → l'appelant utilise le pinhole.
    """

    def __init__(self, calib: Optional[dict], image_size: Optional[tuple] = None):
        self.calib = calib or {}
        self.image_size = image_size
        self.H = build_homography(self.calib, image_size)

    @property
    def available(self) -> bool:
        return self.H is not None

    def project(self, u: float, v: float) -> Optional[tuple[float, float]]:
        """Pixel (u, v) → (X, Y) au sol (m), ou None si non projetable."""
        if self.H is None:
            return None
        if self.calib.get('distortion'):
            u, v = _undistort_pixel(u, v, self.calib)
        p = self.H @ np.array([u, v, 1.0])
        w = p[2]
        if abs(w) < 1e-9:
            return None            # point à l'horizon → distance ~infinie
        X, Y = p[0] / w, p[1] / w
        # Un objet au sol devant la caméra a Y > 0 ; Y <= 0 = au-dessus de
        # l'horizon ou derrière → non fiable.
        if Y <= 0:
            return None
        return float(X), float(Y)

    def distances_for_bbox(self, bbox) -> Optional[dict]:
        u, v = foot_point(bbox)
        xy = self.project(u, v)
        if xy is None:
            return None
        X, Y = xy
        return {
            'ground_xy': [round(X, 3), round(Y, 3)],
            'dist_lateral_m': round(X, 2),
            'dist_longitudinal_m': round(Y, 2),
            'dist_euclid_m': round(math.hypot(X, Y), 2),
            'distance_source': 'homography',
        }
