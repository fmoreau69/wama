"""Trajectoires JUMELLES : deux identifiants de suivi qui décrivent le même objet en mouvement.

Pourquoi (Fabien, 2026-10-06) : *« pour les doublons, le meilleur levier est la comparaison de trajectoires
proches — ce que j'observe, ce sont des fantômes incohérents »*. Un même véhicule vu par deux caméras
(recouvrement avant ↔ latérale, au bord des images) peut recevoir deux identifiants qui roulent côte à côte :
le suivi l'affiche deux fois, et comble les trous de chacun par des fantômes qui ne se rejoignent pas.
C'est exactement ce que compte la métrique de continuité (`placement_metrics.tracking_continuity`, « paires
proches entre caméras ») : on passe ici de la MESURE au GESTE.

Règles (fonction pure) — deux identifiants sont jumeaux si :
  · ils restent proches (< `close_m`) pendant au moins `min_frames` images, à une distance MÉDIANE inférieure
    à `max_median_m` (deux voies voisines sont à ≈ 3,5 m ; un véhicule suivi de près, à plus de 5 m) ;
  · une même caméra ne les a JAMAIS vus ensemble comme deux boîtes distinctes d'une image ;
  · ils BOUGENT, dans le même sens (écart de direction < `max_heading_deg` sur la fenêtre commune) — deux
    immobiles relèvent de la pose longue (`static_fusion`), un immobile et un mobile ne sont pas un objet ;
  · la fusion est jugée contre TOUS les membres du groupe déjà formé (aucun enchaînement de proche en proche).
"""
from __future__ import annotations

import math
from collections import defaultdict

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                                  FunctionCategory, register)
from wama_data.functions.geometry.shapes import box_iou

CLOSE_M = 4.0
MIN_FRAMES = 12
MAX_MEDIAN_M = 2.0
#: En deçà de ce déplacement sur la fenêtre commune (m), un identifiant ne « bouge » pas.
MIN_MOVE_M = 2.0
MAX_HEADING_DEG = 30.0


def trajectory_twins(observations, *, close_m=CLOSE_M, min_frames=MIN_FRAMES, max_median_m=MAX_MEDIAN_M,
                     min_move_m=MIN_MOVE_M, max_heading_deg=MAX_HEADING_DEG, distinct_iou=0.3):
    """`observations` : itérable de (image, caméra, identifiant, x, y[, boîte]) — positions monde (m).
    Rend ({identifiant: racine} des absorbés, {'candidats', 'immobiles', 'sens_differents', 'trop_loin',
    'conflits', 'fusions'})."""
    by_frame = defaultdict(list)
    for ob in observations:
        fr, cam, g, x, y = ob[:5]
        by_frame[fr].append((g, cam, float(x), float(y), ob[5] if len(ob) > 5 else None))
    close = defaultdict(list)          # (a, b) -> [(image, distance, xa, ya, xb, yb)]
    conflict = set()
    for fr, rows in by_frame.items():
        for i in range(len(rows)):
            gi, ci, xi, yi, bi = rows[i]
            for j in range(i + 1, len(rows)):
                gj, cj, xj, yj, bj = rows[j]
                if gi == gj:
                    continue
                a, b = (rows[i], rows[j]) if str(gi) < str(gj) else (rows[j], rows[i])
                key = (a[0], b[0])
                if ci == cj and bi is not None and bj is not None and box_iou(bi, bj) < distinct_iou:
                    conflict.add(frozenset(key))
                    continue
                d = math.hypot(xi - xj, yi - yj)
                if d < close_m:
                    close[key].append((fr, d, a[2], a[3], b[2], b[3]))
    stats = defaultdict(int)
    pairs = []
    for key, rows in close.items():
        if len(rows) < min_frames:
            continue
        stats['candidats'] += 1
        if frozenset(key) in conflict:
            stats['conflits'] += 1
            continue
        rows.sort()
        ds = sorted(r[1] for r in rows)
        if ds[len(ds) // 2] > max_median_m:
            stats['trop_loin'] += 1
            continue
        first, last = rows[0], rows[-1]
        va = (last[2] - first[2], last[3] - first[3])
        vb = (last[4] - first[4], last[5] - first[5])
        la, lb = math.hypot(*va), math.hypot(*vb)
        if la < min_move_m or lb < min_move_m:
            stats['immobiles'] += 1
            continue
        ang = math.degrees(math.acos(max(-1.0, min(1.0, (va[0] * vb[0] + va[1] * vb[1]) / (la * lb)))))
        if ang > max_heading_deg:
            stats['sens_differents'] += 1
            continue
        pairs.append((len(rows), key))
    # fusion, des paires les plus longuement proches aux moins : jugée contre TOUS les membres du groupe
    group_of, members, out = {}, {}, {}
    for _n, (a, b) in sorted(pairs, key=lambda p: (-p[0], str(p[1]))):
        ra, rb = group_of.get(a, a), group_of.get(b, b)
        if ra == rb:
            continue
        ma, mb = members.get(ra, [ra]), members.get(rb, [rb])
        if any(frozenset((x, y)) in conflict for x in ma for y in mb):
            stats['conflits'] += 1
            continue
        if any((min(x, y, key=str), max(x, y, key=str)) not in close for x in ma for y in mb if x != y):
            continue                     # un membre n'a JAMAIS été proche d'un membre de l'autre groupe
        root, other = (ra, rb) if len(ma) >= len(mb) else (rb, ra)
        merged = members.pop(root, [root]) + members.pop(other, [other])
        members[root] = merged
        for m in merged:
            group_of[m] = root
            if m != root:
                out[m] = root
        stats['fusions'] += 1
    return out, dict(stats)


def trajectory_twins_frame(observations: TypedFrame, *, max_median_m=MAX_MEDIAN_M) -> TypedFrame:
    """Wrapper FunctionSpec : une ligne par observation (`frame`, `camera`, `track_id`, `x`, `y`) →
    (identifiant absorbé, racine)."""
    import pandas as pd
    df = observations.df
    res, stats = trajectory_twins(zip(df['frame'], df['camera'], df['track_id'], df['x'], df['y']),
                                  max_median_m=max_median_m)
    return TypedFrame(pd.DataFrame([{'track_id': k, 'root': v} for k, v in res.items()],
                                   columns=['track_id', 'root']), DataType.TABLE, meta=stats)


SPEC = register(FunctionSpec(
    key='trajectory_twins',
    name='Trajectoires jumelles',
    description="Trouve les identifiants de suivi qui décrivent le MÊME objet en mouvement : restés proches "
                "(médiane < 2 m) au moins 12 images, jamais vus ensemble comme deux boîtes d'une même image, et "
                "roulant dans le même sens. Jugée contre tout le groupe (aucun enchaînement). Le geste de la "
                "métrique « paires proches entre caméras » (doublons).",
    category=FunctionCategory.TRANSFORM,
    tags=['tracking', 'duplicates', 'multi-camera', 'fusion'],
    inputs=[
        PortSpec('observations', DataType.TABLE, required_fields=['frame', 'camera', 'track_id', 'x', 'y'],
                 description="Une ligne par observation : image, caméra, identifiant de suivi, position (m)."),
    ],
    outputs=[
        PortSpec('twins', DataType.TABLE, produced_fields=['track_id', 'root'],
                 description="Identifiants absorbés et leur racine ; le bilan par porte est dans meta."),
    ],
    params=[
        ParamSpec('max_median_m', 'float', MAX_MEDIAN_M, 0.2, 10.0, unit='m',
                  description="Distance médiane maximale entre deux jumeaux pendant leur fenêtre commune."),
    ],
    cost={'cpu_bound': True},
    fn=trajectory_twins_frame,
))
