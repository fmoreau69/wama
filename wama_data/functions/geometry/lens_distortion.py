"""Distorsion radiale d'une caméra par les LIGNES DROITES du décor — méthode « fil à plomb », sans mire.

Pourquoi : une caméra embarquée n'a pas de grille de calibration, et la distorsion de son objectif est
SAISIE (ou ignorée). Or une arête droite du monde (bordure, marquage, façade, poteau) est droite dans une
image SANS distorsion : la courbure qu'y laissent les contours mesure la distorsion, par cette caméra
seule — ni autre caméra, ni identité de suivi, ni mouvement connu.

Modèle : celui du placement (`ground_projection.undistort_radial_inverse`, modèle radial INVERSE) —
x_redressé = x_observé · (1 + k·r²), coordonnées normalisées par la focale, k > 0 = barillet. Mesurer avec
un autre modèle que celui qui l'applique ferait une valeur juste… pour un autre calcul.

⚠ **L'écart à la droite se mesure DANS L'IMAGE OBSERVÉE** (2026-10-06, deux biais rencontrés avant) :
  · en pixels de l'image REDRESSÉE, il croît avec k (redresser agrandit) → la mesure tire vers la borne
    basse ;
  · rapporté à la longueur du contour, il décroît avec k (redresser étire davantage les contours
    excentrés) → vers la borne haute.
  Le bruit d'observation est en pixels de l'image prise : on redresse, on ajuste une droite, on projette
  chaque point sur elle, puis on RE-DÉFORME ce pied et l'on mesure l'écart en pixels réels.

Seuls les contours qu'UN k au moins rend droits comptent (les autres sont courbes dans le monde), et
seuls ceux qui sont LOIN du centre renseignent (au centre, la distorsion est nulle quel que soit k).
Mesuré sur ENA_CASA (800 images par caméra, 2026-10-06, moindres carrés) : avant 0,69, gauche 0,53 — la
mesure « une voiture garée ne bouge pas » du 2026-10-03 disait 0,5, critère indépendant —, droite 0,62
(0,7 le 03/10), arrière 0,55. Les premières versions de la méthode rendaient 0,3-0,5 partout : biaisées
vers le bas (cf. `straightness_residual_px`, `plumb_line_distortion`).

Fonction pure — ni OpenCV, ni image, ni Django : elle consomme des contours déjà extraits.
"""
from __future__ import annotations

import math

import numpy as np

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                                  FunctionCategory, register)

#: Distorsions candidates (modèle radial inverse) : du coussinet léger au barillet fort.
K_GRID = tuple(round(k, 2) for k in np.arange(-0.6, 1.61, 0.1))
#: Un contour est une DROITE du monde si un k au moins le redresse à moins de cet écart (px, RMS).
MAX_STRAIGHT_RESIDUAL_PX = 0.6
#: Rayon normalisé (r² = x² + y², x = (u − cx)/fx) au-delà duquel un contour renseigne la distorsion.
MIN_RADIUS = 0.45
#: Contours excentrés minimum pour un verdict.
MIN_CHAINS = 30
#: Le minimum est NET si le profil remonte d'au moins cette part aux deux bords de la grille.
MIN_RISE = 0.1


def undistort_points(pts, k, fx, fy, cx, cy):
    """Pixels observés (n, 2) → coordonnées normalisées REDRESSÉES (modèle radial inverse)."""
    x, y = (pts[:, 0] - cx) / fx, (pts[:, 1] - cy) / fy
    g = 1.0 + k * (x * x + y * y)
    return x * g, y * g


def redistort(xu, yu, k, iterations=20):
    """Inverse du modèle radial inverse, par point fixe : x_observé = x_redressé / (1 + k·r_observé²)."""
    xd, yd = np.array(xu, dtype=float), np.array(yu, dtype=float)
    for _ in range(iterations):
        g = 1.0 + k * (xd * xd + yd * yd)
        xd, yd = xu / g, yu / g
    return xd, yd


def straightness_residual_px(pts, k, fx, fy, cx, cy, samples=200):
    """Écart RMS (px de l'image OBSERVÉE) d'un contour à la droite que k lui donne une fois redressé : la
    droite ajustée dans l'image redressée est RE-DÉFORMÉE en courbe (échantillonnée), et chaque point est
    mesuré à cette courbe. ⚠ Re-déformer seulement le pied de la perpendiculaire tirée dans l'image
    redressée ne donne PAS le point le plus proche dans l'image observée : la mesure sous-estimait k, d'autant
    plus qu'il est fort (0,8 rendu 0,4-0,5 sur une scène simulée, 2026-10-06)."""
    pts = np.asarray(pts, dtype=float)
    obs = np.stack([(pts[:, 0] - cx) / fx * fx, (pts[:, 1] - cy) / fy * fy], 1)   # px, centrés
    u, v = undistort_points(pts, k, fx, fy, cx, cy)
    m = np.array([u.mean(), v.mean()])
    P = np.stack([u, v], 1) - m
    d = np.linalg.svd(P, full_matrices=False)[2][0]
    s = P @ d
    span = s.max() - s.min()
    t = np.linspace(s.min() - 0.1 * span, s.max() + 0.1 * span, samples)
    line = m + np.outer(t, d)
    xd, yd = redistort(line[:, 0], line[:, 1], k)
    curve = np.stack([xd * fx, yd * fy], 1)
    # distance au POLYGONE (segments), pas aux échantillons : à 200 échantillons sur ~100 px, l'écart
    # plancher aux sommets valait 0,17 px — de quoi noyer la courbure qu'on cherche
    a, b = curve[:-1], curve[1:]
    ab = b - a
    ap = obs[:, None, :] - a[None, :, :]
    tt = np.clip((ap * ab[None]).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-12)[None], 0.0, 1.0)
    proj = a[None] + tt[..., None] * ab[None]
    dist = np.sqrt(((obs[:, None, :] - proj) ** 2).sum(-1)).min(axis=1)
    return float(np.sqrt(np.mean(dist ** 2)))


def plumb_line_distortion(chains, fx, fy, cx, cy, *, ks=K_GRID, max_residual_px=MAX_STRAIGHT_RESIDUAL_PX,
                          min_radius=MIN_RADIUS, min_chains=MIN_CHAINS, min_rise=MIN_RISE):
    """Distorsion d'une caméra par ses contours droits — MOINDRES CARRÉS : le k qui minimise la somme des
    carrés des écarts (px de l'image observée) des contours droits et excentrés, affiné sous le pas de la
    grille par une parabole. ⚠ La médiane des écarts RELATIFS (1ʳᵉ version) avait un profil trop plat vers
    les fortes distorsions : 0,6 rendu 0,7-0,8 sur une scène simulée ; les moindres carrés rendent 0,60-0,65.

    `chains` : itérable de tableaux (n, 2) de pixels (u, v), un par contour. Rend {'k', 'clear', 'n_chains',
    'n_central', 'n_far', 'profile', 'flat_range'} — `n_central` : contours écartés car centraux, `n_far` :
    contours excentrés qu'un k redresse — `profile` : somme des carrés RELATIVE au minimum par
    k ; `flat_range` : les k à 2 % du minimum (la largeur de ce plateau est l'incertitude) ; `clear` : assez
    de contours, minimum intérieur à la grille, remontée nette d'un côté et sensible de l'autre. None si aucun
    contour exploitable."""
    ks = np.asarray(ks, dtype=float)
    far, n_chains, n_central = [], 0, 0
    for c in chains:
        p = np.asarray(c, dtype=float)
        if p.ndim != 2 or len(p) < 3:
            continue
        n_chains += 1
        # un contour CENTRAL ne renseigne pas la distorsion : écarté AVANT le calcul (≈ 70 % du coût)
        if math.hypot((p[:, 0].mean() - cx) / fx, (p[:, 1].mean() - cy) / fy) <= min_radius:
            n_central += 1
            continue
        r = np.array([straightness_residual_px(p, k, fx, fy, cx, cy) for k in ks])
        if r.min() >= max_residual_px or r.min() <= 0:
            continue
        far.append(r)
    if not far:
        return None
    sse = (np.stack(far) ** 2).sum(axis=0)
    i = int(sse.argmin())
    k_best = float(ks[i])
    if 0 < i < len(ks) - 1:
        y0, y1, y2 = sse[i - 1], sse[i], sse[i + 1]
        den = y0 - 2.0 * y1 + y2
        if den > 0:
            k_best += 0.5 * (ks[i + 1] - ks[i]) * (y0 - y2) / den
    prof = sse / sse[i]
    flat = [float(k) for k, v in zip(ks, prof) if v <= 1.02]
    rises = sorted((prof[0], prof[-1]))
    # « remontée des deux côtés » suffit : un minimum AU BORD de la grille y vaut 1,00 et ne la passe pas
    # (une condition « minimum intérieur » à côté était redondante — invisible à la mutation, 2026-10-06)
    clear = bool(len(far) >= min_chains and rises[1] >= 1 + min_rise and rises[0] >= 1.02)
    return {'k': round(k_best, 2), 'clear': clear, 'n_chains': n_chains, 'n_central': n_central,
            'n_far': len(far), 'flat_range': [min(flat), max(flat)],
            'profile': [[round(float(k), 2), round(float(v), 3)] for k, v in zip(ks, prof)]}


def plumb_line_frame(contours: TypedFrame, *, fx_px=300.0, fy_px=300.0, width=384, height=248) -> TypedFrame:
    """Wrapper FunctionSpec : une ligne par point de contour (`chain`, `u`, `v`) → une ligne de verdict."""
    import pandas as pd
    df = contours.df
    chains = [g[['u', 'v']].to_numpy(dtype=float) for _, g in df.groupby('chain')]
    res = plumb_line_distortion(chains, fx_px, fy_px, width / 2.0, height / 2.0) or {}
    return TypedFrame(pd.DataFrame([{k: res.get(k) for k in ('k', 'clear', 'n_chains', 'n_central', 'n_far')}]),
                      DataType.SCALAR, meta={'profile': res.get('profile'), 'flat_range': res.get('flat_range')})


SPEC = register(FunctionSpec(
    key='plumb_line_distortion',
    name='Distorsion par les lignes droites',
    description="Mesure la distorsion radiale d'une caméra SANS MIRE : une arête droite du monde est droite "
                "dans une image sans distorsion. Les contours qu'une distorsion redresse, loin du centre, la "
                "désignent ; l'écart à la droite est pris dans l'image OBSERVÉE (sans biais d'échelle). Même "
                "modèle que la projection (radial inverse, k > 0 = barillet).",
    category=FunctionCategory.INDICATOR,
    tags=['geometry', 'calibration', 'lens', 'no-ground-truth', 'single-camera'],
    inputs=[
        PortSpec('contours', DataType.TABLE, required_fields=['chain', 'u', 'v'],
                 description="Points de contours d'images d'une caméra (pixels), groupés par contour."),
    ],
    outputs=[
        PortSpec('distortion', DataType.SCALAR, produced_fields=['k', 'clear', 'n_chains', 'n_central', 'n_far'],
                 description="Distorsion radiale k et verdict (minimum net, assez de contours)."),
    ],
    params=[
        ParamSpec('fx_px', 'float', 300.0, 10.0, 10000.0, unit='px', description='Focale horizontale.'),
        ParamSpec('fy_px', 'float', 300.0, 10.0, 10000.0, unit='px', description='Focale verticale.'),
        ParamSpec('width', 'int', 384, 16, 16384, unit='px', description="Largeur de l'image."),
        ParamSpec('height', 'int', 248, 16, 16384, unit='px', description="Hauteur de l'image."),
    ],
    cost={'cpu_bound': True},
    fn=plumb_line_frame,
))
