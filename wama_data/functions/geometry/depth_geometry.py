"""
Géométrie de la PROFONDEUR monoculaire — briques PURES (numpy seul), réutilisables.

Cœur de calcul de l'amélioration « profondeur » de cam_analyzer (§[E]), extrait ICI (tronc
commun WAMA Data) plutôt que dans `cam_analyzer/utils/` : rien de couplé à Django / à une
session / au modèle. L'app charge Depth Pro, décode les frames et écrit en base ; elle
DÉLÈGUE à ces fonctions tout le calcul géométrique (déprojection → nuage → plan RANSAC →
pitch/hauteur ; profondeur au contact-sol d'une bbox). Deux capabilities visibles au
catalogue (`/model-manager/functions/`, Studio) s'y auto-déclarent en fin de module.

Repère caméra : X-droite, Y-BAS, Z-avant (mètres). La normale-sol unitaire est orientée
vers le HAUT, donc `ny < 0`. Le signe du pitch (piqué caméra, >0 = vers le bas) suit
`atan2(nz, -ny)` — convention à confirmer au 1er run GPU (la métrique `placement_spread`
en console le révèle : un signe faux fait exploser l'étalement monde).

Aucune dépendance app : un module de `common/` qui importerait cam_analyzer serait une
inversion de dépendance (cf. skill cam-analyzer §3).
"""
from __future__ import annotations

import math

import numpy as np

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                 FunctionCategory, register)


# ── Primitives PURES (numpy) ──────────────────────────────────────────────────

def deproject_depth(depth_m, focal_px, mask=None, *, cx=None, cy=None,
                    z_min=1.5, z_max=60.0, max_points=4000):
    """Nuage de points 3D (N,3) en repère caméra depuis une carte de profondeur métrique.

    `depth_m` : raster HxW en mètres. `focal_px` : focale en pixels (repli ~0.8·W en amont).
    `mask` : booléen HxW restreignant les pixels retenus (ex. zone roulable) ; None = tout.
    Filtre la plage utile [z_min, z_max] et sous-échantillonne à `max_points` pour le budget.
    Retourne un tableau float32 (N,3) [x, y, z], éventuellement vide (0,3)."""
    depth_m = np.asarray(depth_m, dtype=np.float32)
    h, w = depth_m.shape[:2]
    if cx is None:
        cx = w / 2.0
    if cy is None:
        cy = h / 2.0
    f = float(focal_px) if focal_px else (0.8 * w)
    if f <= 1e-6:
        return np.empty((0, 3), dtype=np.float32)

    if mask is not None:
        vs, us = np.nonzero(np.asarray(mask, dtype=bool))
    else:
        vs, us = np.mgrid[0:h, 0:w].reshape(2, -1)
    if len(us) == 0:
        return np.empty((0, 3), dtype=np.float32)
    if max_points and len(us) > max_points:
        sel = np.linspace(0, len(us) - 1, int(max_points)).astype(int)
        us, vs = us[sel], vs[sel]

    z = depth_m[vs, us].astype(np.float32)
    valid = (z > z_min) & (z < z_max) & np.isfinite(z)
    if not valid.any():
        return np.empty((0, 3), dtype=np.float32)
    us, vs, z = us[valid], vs[valid], z[valid]
    x = (us - cx) * z / f
    y = (vs - cy) * z / f
    return np.stack([x, y, z], axis=1).astype(np.float32)


def fit_plane_ransac(points, *, iters=250, thresh=0.10, min_inliers=100, seed=20260805):
    """Ajuste un plan par RANSAC sur un nuage (N,3), puis raffine (SVD sur inliers).

    Retourne (normal (3,), offset, n_inliers, rms_m) avec la normale UNITAIRE orientée vers
    le haut (repère caméra : haut = -Y, donc `normal[1] <= 0`) et le plan `n·p + offset = 0`.
    None si le nuage est trop petit ou aucun plan ne réunit `min_inliers`."""
    pts = np.asarray(points, dtype=np.float32)
    n_pts = len(pts)
    if n_pts < 3:
        return None
    rng = np.random.default_rng(seed)
    best_c, best_n, best_d = 0, None, 0.0
    for _ in range(int(iters)):
        idx = rng.choice(n_pts, size=3, replace=False)
        p0, p1, p2 = pts[idx[0]], pts[idx[1]], pts[idx[2]]
        n = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(n)
        if nn < 1e-6:
            continue
        n = n / nn
        d = -float(n.dot(p0))
        dist = np.abs(pts.dot(n) + d)
        c = int((dist < thresh).sum())
        if c > best_c:
            best_c, best_n, best_d = c, n, d
    if best_n is None or best_c < min_inliers:
        return None
    # Raffinement moindres carrés sur les inliers (SVD sur nuage centré).
    dist = np.abs(pts.dot(best_n) + best_d)
    inl = pts[dist < thresh]
    if len(inl) >= 3:
        c0 = inl.mean(axis=0)
        _, _, vt = np.linalg.svd(inl - c0)
        best_n = vt[-1] / np.linalg.norm(vt[-1])
        best_d = -float(best_n.dot(c0))
        dist = np.abs(inl.dot(best_n) + best_d)
    # Orienter la normale vers le HAUT (en repère caméra, le haut est -Y).
    if best_n[1] > 0:
        best_n, best_d = -best_n, -best_d
    rms_m = float(np.sqrt(np.mean(dist ** 2))) if len(inl) else None
    return best_n, best_d, best_c, rms_m


def plane_pitch_height(normal, offset):
    """(pitch_deg, height_m) depuis un plan-sol (normale vers le haut, `n·p + offset = 0`).
    Pitch (piqué caméra, >0 = vers le bas) = atan2(nz, -ny) ; hauteur caméra = |offset|."""
    n = np.asarray(normal, dtype=np.float64)
    pitch_deg = math.degrees(math.atan2(float(n[2]), -float(n[1])))
    height_m = abs(float(offset))
    return pitch_deg, height_m


def ground_plane_from_depth(depth_m, drivable_mask, focal_px, *, cx=None, cy=None,
                            z_min=1.5, z_max=60.0, max_points=4000,
                            ransac_thresh=0.10, min_inliers=100):
    """Cœur PUR usage 4 : (pitch_deg, height_m) du plan de sol depuis UNE carte de profondeur
    restreinte à la zone roulable. Compose déprojection → RANSAC → pitch/hauteur.

    Retourne un dict {pitch_deg, height_m, n_inliers, n_points, rms_m} ou None (nuage/plan
    insuffisant). N'APPLIQUE AUCUN garde-fou physique (plage rig) : l'appelant décide de
    retenir ou de replier — la géométrie pure reste agnostique du véhicule."""
    pts = deproject_depth(depth_m, focal_px, mask=drivable_mask, cx=cx, cy=cy,
                          z_min=z_min, z_max=z_max, max_points=max_points)
    if len(pts) < min_inliers:
        return None
    fit = fit_plane_ransac(pts, thresh=ransac_thresh, min_inliers=min_inliers)
    if fit is None:
        return None
    normal, offset, n_inl, rms_m = fit
    pitch_deg, height_m = plane_pitch_height(normal, offset)
    return {'pitch_deg': round(pitch_deg, 2), 'height_m': round(height_m, 3),
            'n_inliers': int(n_inl), 'n_points': int(len(pts)),
            'rms_m': round(rms_m, 3) if rms_m is not None else None}


def contact_depth(depth_m, bbox, *, half=3, d_min=0.3, d_max=120.0):
    """Cœur PUR usages 3+1 : profondeur métrique au point de CONTACT SOL d'une bbox (centre du
    bord bas), médiane d'un petit patch (±`half` px) pour la robustesse. None si aucun
    échantillon plausible dans [d_min, d_max]."""
    depth_m = np.asarray(depth_m, dtype=np.float32)
    h, w = depth_m.shape[:2]
    x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    u = int(round((x1 + x2) / 2.0))
    v = int(round(y2))
    u = min(max(u, 0), w - 1)
    v = min(max(v, 0), h - 1)
    u0, u1 = max(0, u - half), min(w, u + half + 1)
    v0, v1 = max(0, v - half), min(h, v + half + 1)
    patch = depth_m[v0:v1, u0:u1]
    vals = patch[np.isfinite(patch) & (patch > d_min) & (patch < d_max)]
    if vals.size < 2:
        return None
    return float(np.median(vals))


# ── Capabilities catalogue (auto-déclarées) ───────────────────────────────────

SPEC_GROUND = register(FunctionSpec(
    key='depth_ground_plane',
    name='Plan de sol par profondeur',
    description="Estime le pitch/hauteur caméra en ajustant (RANSAC) un plan sur le nuage de "
                "points déprojeté depuis une carte de profondeur métrique restreinte à la zone "
                "roulable. Brique PURE : la géométrie ne connaît ni le rig ni la session ; les "
                "garde-fous physiques et le repli homographie restent à l'appelant.",
    category=FunctionCategory.INDICATOR,
    tags=['geometry', 'depth', 'monocular', 'needs-calibration'],
    inputs=[
        PortSpec('depth', DataType.DEPTH_MAP,
                 description='Carte de profondeur métrique HxW (mètres) + focale (px).'),
        PortSpec('drivable', DataType.DEPTH_MAP, optional=True,
                 description='Masque booléen HxW de la zone roulable (sinon tout le raster).'),
    ],
    outputs=[
        PortSpec('ground_plane', DataType.SCALAR,
                 produced_fields=['pitch_deg', 'height_m', 'n_inliers', 'rms_m']),
    ],
    params=[
        ParamSpec('z_min', 'float', 1.5, 0.1, 20.0, 'm', 'Profondeur min retenue (route utile).'),
        ParamSpec('z_max', 'float', 60.0, 5.0, 200.0, 'm', 'Profondeur max retenue.'),
        ParamSpec('ransac_thresh', 'float', 0.10, 0.01, 1.0, 'm', 'Seuil inlier au plan.'),
        ParamSpec('min_inliers', 'int', 100, 3, 100000, '', 'Inliers minimum pour valider le plan.'),
    ],
    cost={'cpu_bound': True},
    projects=['ENA'],
    fn=ground_plane_from_depth,
))

SPEC_CONTACT = register(FunctionSpec(
    key='depth_contact_distance',
    name='Distance au contact-sol (profondeur)',
    description="Profondeur métrique au point de contact-sol d'une bbox (médiane d'un patch au "
                "centre du bord bas) : 3ᵉ source de distance indépendante du pinhole et de "
                "l'homographie. Brique PURE réutilisable par tout cross-check de distance.",
    category=FunctionCategory.INDICATOR,
    tags=['geometry', 'depth', 'monocular', 'distance'],
    inputs=[
        PortSpec('depth', DataType.DEPTH_MAP,
                 description='Carte de profondeur métrique HxW (mètres).'),
        PortSpec('detections', DataType.DETECTIONS, required_fields=['bbox'],
                 description='Objets dont on mesure la distance au contact-sol.'),
    ],
    outputs=[
        PortSpec('detections', DataType.DETECTIONS, produced_fields=['depth_distance_m']),
    ],
    params=[
        ParamSpec('half', 'int', 3, 0, 32, 'px', 'Demi-taille du patch médian.'),
        ParamSpec('d_min', 'float', 0.3, 0.0, 10.0, 'm', 'Profondeur plausible min.'),
        ParamSpec('d_max', 'float', 120.0, 5.0, 300.0, 'm', 'Profondeur plausible max.'),
    ],
    cost={'cpu_bound': True},
    projects=['ENA'],
    fn=contact_depth,
))
