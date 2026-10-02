"""Orientation de MONTAGE d'une caméra embarquée, mesurée par le MOUVEMENT CONNU du véhicule.

Pourquoi : l'orientation d'une caméra latérale (son lacet dans le repère véhicule) est une valeur
SAISIE — et une erreur de quelques degrés fait tourner tous ses objets autour d'elle, donc les
place mal aux jonctions avec la caméra voisine (doublons, relais ratés). La rotation vue dans
l'image (`ego_rotation`) ne la mesure pas : sur une latérale, la translation vers l'avant défile EN
TRAVERS de la visée et se confond avec un lacet.

Méthode : entre deux images d'une même caméra, la trace (positions + cap) donne le mouvement du
véhicule. Exprimé dans le repère caméra — ce qui dépend du lacet ψ, du tangage φ de montage et de
la distorsion radiale k1 —, ce mouvement impose à chaque point du décor la contrainte ÉPIPOLAIRE
x₁ᵀ·E·x₀ = 0, E = [t]ₓ·R. Aucune profondeur n'intervient. On minimise la distance de Sampson
(pixels, tronquée : objets mobiles et appariements faux plafonnent) sur une grille (ψ, φ, k1), à
focale CONNUE. En ligne droite, la contrainte fixe le point de fuite du déplacement, donc
fx·tan ψ : c'est pourquoi la focale doit venir d'ailleurs.

⚠ **Ce que la méthode NE mesure PAS : la focale.** Mesuré le 2026-10-02 sur la caméra avant
(focale connue par deux mesures indépendantes, ~75,7°) : le coût décroît vers les champs larges
sans minimum net, et une rotation libre par paire ne converge pas non plus. Le lacet, lui, est
net (±5° montent le coût de 5-10 %) et la caméra avant retrouve −0,5° pour 0° attendu : c'est le
CONTRÔLE que l'appelant doit faire tourner avant de croire une latérale.

⚠ **Retard de la trace** : le cap GPS filtré retarde sur l'image (mesuré ~0,5 s). Un retard non
compensé tord la rotation imposée ; il est estimé d'abord, à géométrie a priori, puis fixé.

Fonction pure — ni OpenCV, ni image, ni Django : elle consomme des correspondances déjà établies.
"""
from __future__ import annotations

import math

import numpy as np

#: Grilles par défaut : lacet ±15° autour de l'a priori, tangage ±6°, distorsion radiale (1 terme,
#: redressement x·(1 + k1·r²) en coordonnées normalisées) et retard de la trace (s).
YAW_SPAN_DEG, YAW_STEP_DEG = 15.0, 1.0
PITCH_OFFSETS_DEG = (-6.0, -3.0, 0.0, 3.0, 6.0)
K1_VALUES = (0.0, 0.15, 0.3)
LAGS_S = (-0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0)
#: Distance de Sampson au-delà de laquelle un point ne compte plus (px) ; points gardés par paire.
TAU_PX = 1.5
MAX_POINTS_PER_PAIR = 150
#: Une paire où le véhicule a moins avancé ne contraint pas la direction de translation.
MIN_STEP_M = 0.25
#: Remontée du coût à ±5° du minimum en deçà de laquelle le lacet n'est pas jugé mesuré.
MIN_RISE_5DEG = 0.005


def _rot_vehicle_to_world(h):
    """(n,3,3) : colonnes droite, avant, haut du véhicule dans (est, nord, haut) ; cap horaire."""
    c, s = np.cos(h), np.sin(h)
    R = np.zeros((len(h), 3, 3))
    R[:, 0, 0], R[:, 0, 1] = c, s
    R[:, 1, 0], R[:, 1, 1] = -s, c
    R[:, 2, 2] = 1.0
    return R


def _rot_camera_to_vehicle(yaw_deg, pitch_deg):
    """Colonnes x (droite image), y (bas image), z (axe optique) de la caméra dans le repère
    véhicule ; lacet horaire depuis l'avant, tangage positif vers le BAS."""
    ps, ph = math.radians(yaw_deg), math.radians(pitch_deg)
    z = np.array([math.sin(ps) * math.cos(ph), math.cos(ps) * math.cos(ph), -math.sin(ph)])
    x = np.array([math.cos(ps), -math.sin(ps), 0.0])
    return np.stack([x, np.cross(z, x), z], axis=1)


class _Problem:
    """Données figées d'un ajustement : points, paires, trace."""

    def __init__(self, pairs, trajectory, image_size, focal_px, mount, max_points, min_step_m):
        T = np.asarray(trajectory, dtype=float)
        self.t, self.e, self.n = T[:, 0], T[:, 1], T[:, 2]
        self.h = np.unwrap(np.radians(T[:, 3]))
        self.W, self.H = float(image_size[0]), float(image_size[1])
        self.fx = float(focal_px)
        self.mount = np.array([float(mount[0]), float(mount[1]), 0.0])
        t0s, t1s, U0, U1, idx = [], [], [], [], []
        for t0, t1, m in pairs:
            m = np.asarray(m, dtype=float).reshape(-1, 4)
            if len(m) < 8:
                continue
            if len(m) > max_points:      # sous-échantillonnage DÉTERMINISTE (reproductible)
                m = m[np.linspace(0, len(m) - 1, max_points).astype(int)]
            e0, n0 = np.interp(t0, self.t, self.e), np.interp(t0, self.t, self.n)
            e1, n1 = np.interp(t1, self.t, self.e), np.interp(t1, self.t, self.n)
            if math.hypot(e1 - e0, n1 - n0) < min_step_m:
                continue
            k = len(t0s)
            t0s.append(float(t0)); t1s.append(float(t1))
            U0.append(m[:, :2]); U1.append(m[:, 2:]); idx.append(np.full(len(m), k))
        self.t0, self.t1 = np.array(t0s), np.array(t1s)
        self.U0 = np.concatenate(U0) if U0 else np.zeros((0, 2))
        self.U1 = np.concatenate(U1) if U1 else np.zeros((0, 2))
        self.idx = np.concatenate(idx) if idx else np.zeros(0, dtype=int)

    def _vehicle_states(self, lag):
        def at(ts):
            p = np.stack([np.interp(ts + lag, self.t, self.e), np.interp(ts + lag, self.t, self.n),
                          np.zeros(len(ts))], axis=1)
            return p, np.interp(ts + lag, self.t, self.h)
        return at(self.t0), at(self.t1)

    def cost(self, yaw_deg, pitch_deg, k1, lag, tau=TAU_PX, states=None):
        (p0, h0), (p1, h1) = states or self._vehicle_states(lag)
        Rvc = _rot_camera_to_vehicle(yaw_deg, pitch_deg)
        Rv0, Rv1 = _rot_vehicle_to_world(h0), _rot_vehicle_to_world(h1)
        Rw0, Rw1 = Rv0 @ Rvc, Rv1 @ Rvc
        c0, c1 = p0 + Rv0 @ self.mount, p1 + Rv1 @ self.mount
        R = np.einsum('nji,njk->nik', Rw1, Rw0)                 # Rw1ᵀ·Rw0
        t = np.einsum('nji,nj->ni', Rw1, c0 - c1)
        t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-12
        tx = np.zeros((len(t), 3, 3))
        tx[:, 0, 1], tx[:, 0, 2] = -t[:, 2], t[:, 1]
        tx[:, 1, 0], tx[:, 1, 2] = t[:, 2], -t[:, 0]
        tx[:, 2, 0], tx[:, 2, 1] = -t[:, 1], t[:, 0]
        E = (tx @ R)[self.idx]
        x0, x1 = self._normalized(self.U0, k1), self._normalized(self.U1, k1)
        Ex0 = np.einsum('nij,nj->ni', E, x0)
        Etx1 = np.einsum('nji,nj->ni', E, x1)
        num = np.einsum('ni,ni->n', x1, Ex0) ** 2
        den = Ex0[:, 0] ** 2 + Ex0[:, 1] ** 2 + Etx1[:, 0] ** 2 + Etx1[:, 1] ** 2
        d2 = num / np.maximum(den, 1e-18) * self.fx * self.fx      # Sampson², px²
        return float(np.mean(np.minimum(d2, tau * tau)))

    def _normalized(self, U, k1):
        a, b = (U[:, 0] - self.W / 2.0) / self.fx, (U[:, 1] - self.H / 2.0) / self.fx
        g = 1.0 + k1 * (a * a + b * b)
        return np.stack([a * g, b * g, np.ones(len(U))], axis=1)


def _parabola_min(xs, ys):
    """Sommet de la parabole par trois points équidistants ; le point central sinon."""
    (x0, x1, x2), (y0, y1, y2) = xs, ys
    den = y0 - 2 * y1 + y2
    if den <= 0:
        return x1
    return x1 + 0.5 * (x1 - x0) * (y0 - y2) / den


def fit_mount_yaw(pairs, trajectory, *, image_size, focal_px, mount=(0.0, 0.0), yaw0_deg=0.0,
                  pitch0_deg=15.0, yaw_span_deg=YAW_SPAN_DEG, yaw_step_deg=YAW_STEP_DEG,
                  pitch_offsets_deg=PITCH_OFFSETS_DEG, k1_values=K1_VALUES, lags_s=LAGS_S,
                  max_points_per_pair=MAX_POINTS_PER_PAIR, min_step_m=MIN_STEP_M):
    """Lacet de montage d'une caméra (°, horaire depuis l'avant du véhicule), focale CONNUE.

    `pairs` : `[(t0, t1, matches)]` — instants de la TRACE (s) des deux images et leurs
    correspondances `(x0, y0, x1, y1)` en pixels (points du DÉCOR ; les mobiles plafonnent).
    `trajectory` : `[(t, est_m, nord_m, cap_deg)]` triée — position du point de référence du
    véhicule (celui dont `mount` est l'écart, en (droite, avant) mètres) et son cap.
    `focal_px` : focale en pixels (pixels carrés), `image_size` : (largeur, hauteur).

    Rend None sans données, sinon un dict : `yaw_deg` (optimum, distorsion comprise),
    `yaw_pinhole_deg` (optimum sans distorsion — ce qu'une chaîne pinhole verrait), `pitch_deg`,
    `k1`, `lag_s`, `cost` et `cost_prior` (à l'a priori), `rise_5deg` (remontée du coût à ±5°),
    `at_bound` (optimum au bord de la grille), `measured` (lacet jugé mesuré), `profile`,
    `n_pairs`, `n_points`."""
    pb = _Problem(pairs, trajectory, image_size, focal_px, mount, max_points_per_pair, min_step_m)
    if len(pb.t0) < 20:
        return None
    # 1. retard de la trace, CONJOINTEMENT avec un lacet grossier (sans distorsion) — puis FIXÉ.
    #    Estimé au seul lacet a priori, il compensait l'erreur de cet a priori (mesuré sur scène
    #    synthétique : −0,25 s rendu pour 0,5 s vrai, a priori faux de 2,5°).
    coarse = np.arange(yaw0_deg - yaw_span_deg, yaw0_deg + yaw_span_deg + 1e-9, 2.5)
    lag_costs = []
    for lg in lags_s:
        ps = pb._vehicle_states(lg)
        lag_costs.append((min(pb.cost(float(y), pitch0_deg, 0.0, lg, states=ps) for y in coarse), lg))
    lag = min(lag_costs)[1]
    states = pb._vehicle_states(lag)
    cost_prior = pb.cost(yaw0_deg, pitch0_deg, 0.0, lag, states=states)
    # 2. grille (lacet × tangage × distorsion)
    yaws = np.arange(yaw0_deg - yaw_span_deg, yaw0_deg + yaw_span_deg + 1e-9, yaw_step_deg)
    grid = {}
    for k1 in k1_values:
        for dp in pitch_offsets_deg:
            for y in yaws:
                grid[(k1, dp, float(y))] = pb.cost(float(y), pitch0_deg + dp, k1, lag, states=states)
    k1b, dpb, yb = min(grid, key=grid.get)

    def refine(k1, dp, y):
        i = int(round((y - yaws[0]) / yaw_step_deg))
        if 0 < i < len(yaws) - 1:
            trio = [grid[(k1, dp, float(yaws[j]))] for j in (i - 1, i, i + 1)]
            return _parabola_min([float(yaws[i - 1]), float(yaws[i]), float(yaws[i + 1])], trio)
        return y
    yaw = refine(k1b, dpb, yb)
    k0 = min((key for key in grid if key[0] == 0.0), key=grid.get, default=None)
    yaw_pinhole = refine(*k0) if k0 else None
    best = grid[(k1b, dpb, yb)]
    near = [grid.get((k1b, dpb, float(y))) for y in (yb - 5 * yaw_step_deg, yb + 5 * yaw_step_deg)]
    near = [c for c in near if c is not None]
    rise = (sum(near) / len(near) - best) if near else 0.0
    at_bound = yb in (float(yaws[0]), float(yaws[-1])) or \
        dpb in (min(pitch_offsets_deg), max(pitch_offsets_deg))
    return {
        'yaw_deg': round(float(yaw), 2),
        'yaw_pinhole_deg': None if yaw_pinhole is None else round(float(yaw_pinhole), 2),
        'pitch_deg': round(pitch0_deg + dpb, 1), 'k1': k1b, 'lag_s': lag,
        'cost': round(best, 4), 'cost_prior': round(cost_prior, 4),
        'rise_5deg': round(rise, 4), 'at_bound': bool(at_bound),
        'measured': bool(not at_bound and rise >= MIN_RISE_5DEG),
        'profile': [(round(float(y), 1), round(grid[(k1b, dpb, float(y))], 4)) for y in yaws],
        'n_pairs': int(len(pb.t0)), 'n_points': int(len(pb.U0)),
    }


def known_motion_yaw(matches: 'TypedFrame', trajectory: 'TypedFrame', *, width=None, height=None,
                     focal_px=None, mount_right_m=0.0, mount_forward_m=0.0, yaw0_deg=0.0,
                     pitch0_deg=15.0) -> 'TypedFrame':
    """Wrapper FunctionSpec : correspondances (`t0, t1, x0, y0, x1, y1`) + trace (`time, e, n,
    heading`) → SCALAR (lacet), le reste du rapport dans `meta`."""
    import pandas as pd
    from wama.common.catalog.data_types import TypedFrame as _TF, DataType as _DT
    mdf = matches.df if hasattr(matches, 'df') else matches
    tdf = trajectory.df if hasattr(trajectory, 'df') else trajectory
    pairs = [(t0, t1, g[['x0', 'y0', 'x1', 'y1']].to_numpy())
             for (t0, t1), g in mdf.groupby(['t0', 't1'], sort=True)]
    traj = tdf[['time', 'e', 'n', 'heading']].sort_values('time').to_numpy()
    res = fit_mount_yaw(pairs, traj, image_size=(width, height), focal_px=focal_px,
                        mount=(mount_right_m, mount_forward_m), yaw0_deg=yaw0_deg,
                        pitch0_deg=pitch0_deg)
    if res is None:
        return _TF(pd.DataFrame([{'metric': 'mount_yaw_deg', 'value': None}]), _DT.SCALAR,
                   meta={'measured': False, 'reason': 'moins de 20 paires roulantes'})
    return _TF(pd.DataFrame([{'metric': 'mount_yaw_deg', 'value': res['yaw_deg']}]), _DT.SCALAR,
               meta=res)


# ── Manifeste ─────────────────────────────────────────────────────────────────────────
from wama.common.catalog.function_catalog import (  # noqa: E402
    FunctionCategory, FunctionSpec, ParamSpec, PortSpec, register)
from wama.common.catalog.data_types import DataType  # noqa: E402

SPEC = register(FunctionSpec(
    key='known_motion_yaw',
    name='Orientation de montage par mouvement connu',
    description="Mesure le lacet de montage d'une caméra embarquée (et son tangage, sa distorsion "
                "radiale) : le mouvement du véhicule tiré de la trace impose à chaque point du décor "
                "suivi entre deux images une contrainte épipolaire, sans profondeur. Focale CONNUE "
                "requise — la méthode ne la mesure pas. Contrôle conseillé : une caméra d'orientation "
                "connue doit retrouver son lacet.",
    category=FunctionCategory.ENRICHER,
    tags=['vision', 'geometry', 'calibration', 'ego-motion', 'gnss'],
    inputs=[
        PortSpec('matches', DataType.TABLE, required_fields=['t0', 't1', 'x0', 'y0', 'x1', 'y1'],
                 description="Correspondances de points du DÉCOR entre deux images, avec les "
                             "instants (temps de la trace) des deux images."),
        PortSpec('trajectory', DataType.TABLE, required_fields=['time', 'e', 'n', 'heading'],
                 description="Trace du point de référence du véhicule dans un repère local "
                             "métrique (est, nord) et son cap (° horaire depuis le nord)."),
    ],
    outputs=[PortSpec('mount_yaw', DataType.SCALAR, produced_fields=['metric', 'value'],
                      description="Lacet de montage (°, horaire depuis l'avant du véhicule) ; "
                                  "tangage, distorsion, retard de la trace, profil et verdict "
                                  "`measured` dans meta. ⚠ PAS de facette estimateur : `yaw` y "
                                  "désigne une rotation ENTRE deux instants (`ego_rotation`) ; une "
                                  "orientation de montage est une constante d'étalonnage, qu'aucune "
                                  "fusion de cap ne doit prendre pour une source.")],
    params=[
        ParamSpec('focal_px', 'float', None, 1.0, 10000.0, unit='px',
                  description='Focale en pixels (pixels carrés).'),
        ParamSpec('yaw0_deg', 'float', 0.0, -180.0, 180.0, unit='°',
                  description='Lacet a priori : centre de la recherche (±15°).'),
        ParamSpec('pitch0_deg', 'float', 15.0, -10.0, 45.0, unit='°',
                  description='Tangage a priori (positif vers le bas) : centre de la recherche (±6°).'),
    ],
    cost={'cpu_bound': True},
    projects=['ENA'],
    fn=known_motion_yaw,
))
