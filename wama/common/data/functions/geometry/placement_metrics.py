"""
Métriques de COHÉRENCE de placement monde — brique commune WAMA Data (capability-first).

But : mesurer OBJECTIVEMENT la qualité d'un placement d'objets dans un repère monde, SANS
vérité terrain, pour trancher un A/B (ex. bascule ⚑ ON vs OFF) sur des chiffres plutôt qu'« à
l'œil ». Métrique-driven, réutilisable par tout pipeline qui pose des objets dans un repère
(cam_analyzer = premier consommateur). Voir memory `feedback-ab-objective-metric`.

Métrique #1 — **étalement monde des stationnés** (implémentée ici) :
  un objet réellement immobile doit se réduire à UN SEUL point monde ; la dispersion RMS de
  ses positions autour de leur barycentre = proxy direct de la qualité du placement (0 = idéal).
  Plus bas = meilleur. C'est aussi l'objectif que minimise `homography_estimator` — ici on
  l'expose comme MÉTRIQUE (comparable entre configs), pas comme cible d'optimisation.

À venir (mêmes entrées, non implémentées — pas de stub inerte) :
  #2 désaccord inter-sources (homography ⟷ pinhole ⟷ ortho, via `distance_source`) ;
  #3 discontinuité au hand-off inter-caméras (saut de position à la transition de track).

Pur (numpy) : le cœur `track_position_spread` ne dépend ni de Django ni de pandas et se teste
hors serveur. Le wrapper `placement_spread` (FunctionSpec) l'adapte à un `TypedFrame`.
"""
from __future__ import annotations

import numpy as np

from ...data_types import DataType, TypedFrame
from ...function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                  FunctionCategory, register)


def track_position_spread(positions_by_track, *, min_obs=3):
    """Cœur PUR de la métrique #1 (aucune dépendance Django/pandas).

    positions_by_track : {track_id: [(x, y), ...]} — positions monde (mêmes unités, ex. m)
        d'objets supposés immobiles, groupées par identité de track.
    min_obs : nombre minimal d'observations pour qu'un track compte (bruit sinon).

    Retourne {'per_track': {tid: {n, cx, cy, rms_m}}, 'aggregate': {n_tracks, rms_median_m,
    rms_mean_m, rms_p90_m}}. Le RMS d'un track = racine de la moyenne des carrés des distances
    au barycentre (dispersion radiale). L'agrégat résume la distribution des RMS sur les tracks.
    """
    per_track = {}
    rms_values = []
    for tid, pts in (positions_by_track or {}).items():
        arr = np.asarray(pts, dtype=float)
        if arr.ndim != 2 or arr.shape[0] < min_obs or arr.shape[1] < 2:
            continue
        arr = arr[:, :2]
        # ignore les points non finis (NaN/inf) sans casser le calcul
        arr = arr[np.isfinite(arr).all(axis=1)]
        if arr.shape[0] < min_obs:
            continue
        centroid = arr.mean(axis=0)
        radial = np.linalg.norm(arr - centroid, axis=1)
        rms = float(np.sqrt(np.mean(radial ** 2)))
        per_track[tid] = {'n': int(arr.shape[0]),
                          'cx': float(centroid[0]), 'cy': float(centroid[1]),
                          'rms_m': round(rms, 4)}
        rms_values.append(rms)

    if rms_values:
        rms_arr = np.asarray(rms_values, dtype=float)
        aggregate = {
            'n_tracks': int(rms_arr.size),
            'rms_median_m': round(float(np.median(rms_arr)), 4),
            'rms_mean_m': round(float(np.mean(rms_arr)), 4),
            'rms_p90_m': round(float(np.percentile(rms_arr, 90)), 4),
        }
    else:
        aggregate = {'n_tracks': 0, 'rms_median_m': None,
                     'rms_mean_m': None, 'rms_p90_m': None}
    return {'per_track': per_track, 'aggregate': aggregate}


def _positions_by_track_from_df(df, id_field, coord_field, x_field, y_field):
    """Extrait {track_id: [(x, y)…]} d'un DataFrame de détections. Accepte soit un champ
    coordonnée unique portant [x, y] (`coord_field`, ex. cam_analyzer `world_en`), soit deux
    colonnes séparées (`x_field`, `y_field`)."""
    from collections import defaultdict
    out = defaultdict(list)
    if id_field not in df.columns:
        return out
    use_coord = coord_field and coord_field in df.columns
    if not use_coord and not (x_field in df.columns and y_field in df.columns):
        return out
    for _, row in df.iterrows():
        tid = row[id_field]
        if tid is None:
            continue
        if use_coord:
            v = row[coord_field]
            if not (isinstance(v, (list, tuple)) and len(v) >= 2):
                continue
            out[tid].append((v[0], v[1]))
        else:
            out[tid].append((row[x_field], row[y_field]))
    return out


def placement_spread(detections: TypedFrame, *, id_field='global_track_id',
                     coord_field='world_en', x_field='world_e', y_field='world_n',
                     min_obs=3) -> TypedFrame:
    """Wrapper FunctionSpec de la métrique #1 : lit un `TypedFrame` de détections monde,
    groupe par `id_field`, calcule l'étalement RMS. Sortie SCALAR = RMS médian (l'indicateur
    A/B) ; le détail par track + l'agrégat complet sont dans `meta` (diagnostic). INDICATOR.

    Note d'usage A/B (cam_analyzer) : ne comparer que des placements de MÊME source, ou séparer
    par `distance_source`, sinon le fallback pinhole silencieux (gap G7) fausse la comparaison.
    """
    import pandas as pd
    df = detections.df
    pbt = _positions_by_track_from_df(df, id_field, coord_field, x_field, y_field)
    res = track_position_spread(pbt, min_obs=min_obs)
    agg = res['aggregate']
    out = pd.DataFrame([{'metric': 'placement_spread_rms_m', 'value': agg['rms_median_m']}])
    return TypedFrame(out, DataType.SCALAR,
                      meta={'aggregate': agg, 'per_track': res['per_track'],
                            'lower_is_better': True})


SPEC = register(FunctionSpec(
    key='placement_spread',
    name='Étalement des stationnés',
    description="Mesure la cohérence d'un placement monde : dispersion RMS des positions des "
                "objets immobiles autour de leur barycentre (0 = idéal). Métrique A/B objective, "
                "sans vérité terrain — plus bas = meilleur.",
    category=FunctionCategory.INDICATOR,
    tags=['geometry', 'placement-quality', 'ab-metric', 'no-ground-truth'],
    inputs=[
        PortSpec('detections', DataType.DETECTIONS,
                 required_fields=['global_track_id', 'world_en'],
                 description='Détections placées en monde, avec identité de track et position.'),
    ],
    outputs=[
        PortSpec('rms', DataType.SCALAR, produced_fields=['metric', 'value'],
                 description='RMS médian d\'étalement (m) ; détail par track dans meta.'),
    ],
    params=[
        ParamSpec('min_obs', 'int', 3, 1, 100,
                  description='Observations minimales pour qu\'un track soit compté.'),
    ],
    cost={'cpu_bound': True},
    fn=placement_spread,
))
