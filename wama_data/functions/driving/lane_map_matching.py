"""
Recalage LATÉRAL et de CAP de la navette par la voie vue (caméra) + l'axe routier (carte).

Idée (Fabien) : le GPS dérive LOCALEMENT de plusieurs mètres — mesuré le 2026-09-28 à
Roumanille-Poincaré : ≈ 2 m trop à droite, cap figé à −5,9° pendant un arrêt. Le recalage ortho
(2b) ne s'appuie qu'aux passages piétons ; la voie + la carte donnent une correction CONTINUE :

  position latérale VRAIE = centre de la voie de droite (attendu par la carte : largeur de
                            chaussée, nombre de voies, sens — BD TOPO)
                          + écart de la navette au centre de SA voie (lignes vues par la caméra)
  correction              = latéral vrai − latéral GPS (perpendiculaire à l'axe)
  cap                     = cap de l'axe − angle des lignes dans le repère caméra

Le LONGITUDINAL n'est pas touché (les lignes n'en disent rien) : il reste au GPS et au 2b.

Briques PURES (numpy/pandas, aucun Django) :
  • le rattachement CONTINU (Viterbi : distance + cap + continuité) est celui de
    `gps_map_match.match_track` — `map_match(method='continuous')` —, IMPORTÉ ici ;
  • `expected_lane_offset`   — centre de la voie de droite dans le sens de circulation ;
  • `lane_observation`       — lignes de voie projetées au sol (repère caméra) → écart au centre
                               de voie, largeur, cap relatif ;
  • `lateral_corrections`    — ancres (instants où tout est mesuré) → série interpolée ;
  • `lane_map_recalage`      — la composition sur `TypedFrame`, déclarée au catalogue.

Repères : local est/nord en mètres ; caps en degrés depuis le nord, sens horaire ; latéral
POSITIF = à DROITE du sens de circulation.
"""
from __future__ import annotations

import math

import numpy as np

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                                  FunctionCategory, register)

# Le rattachement routier et ses utilitaires vivent dans `gps_map_match` (le domicile du
# map-matching) : ce module les IMPORTE — les recopier en ferait une seconde implémentation.
from wama_data.functions.driving.gps_map_match import angle_diff, local_frame, match_track, road_segments


def expected_lane_offset(road, default_lane_width_m=3.0):
    """(écart du centre de la voie de DROITE à l'axe du tronçon, largeur de voie) — dans le sens
    de circulation, latéral positif à droite. L'axe BD TOPO est le milieu de la chaussée :
    centre de la voie la plus à droite = W/2 − l/2, l = W / nombre de voies. Tronçon à une voie
    (même à double sens) : 0. Largeur inconnue : `nombre de voies × default_lane_width_m`."""
    n = road.get('nb_voies')
    try:
        n = int(n) if n else None
    except (TypeError, ValueError):
        n = None
    sens = (road.get('sens') or '').lower()
    if not n:
        n = 2 if 'double' in sens else 1
    W = road.get('largeur')
    try:
        W = float(W) if W else None
    except (TypeError, ValueError):
        W = None
    if not W:
        W = n * default_lane_width_m
    lane_w = W / n
    return (W / 2.0 - lane_w / 2.0 if n > 1 else 0.0), lane_w


def _densify(pts, step_m):
    """Les arêtes d'un contour (fermé) ou d'une polyligne au sol, échantillonnées tous les `step_m`.
    Un masque de segmentation arrive en contour SIMPLIFIÉ (quelques sommets pour 20 m de sol) :
    sans cela, une ligne réelle n'a qu'un ou deux sommets dans la bande de lecture. Interpoler au
    sol est exact — une homographie envoie une droite de l'image sur une droite du sol. Une arête
    dont un bout est absent ou non fini (au-dessus de l'horizon) est sautée."""
    ok = [p is not None and math.isfinite(p[0]) and math.isfinite(p[1]) for p in pts]
    out = []
    n = len(pts)
    for i in range(n if n > 2 else n - 1):
        j = (i + 1) % n
        if not (ok[i] and ok[j]):
            continue
        (x0, y0), (x1, y1) = pts[i], pts[j]
        k = max(1, int(math.hypot(x1 - x0, y1 - y0) / step_m))
        out.extend((x0 + (x1 - x0) * t / k, y0 + (y1 - y0) * t / k) for t in range(k))
    if n == 1 and ok[0]:
        out.append(tuple(pts[0]))
    return out


def lane_observation(lines_xy, *, y_band=(5.0, 10.0), eval_y=0.0, width_range=(2.2, 4.8),
                     step_m=0.2, max_spread_m=0.5, max_slope_deg=25.0):
    """Lignes de voie projetées au sol, repère CAMÉRA (X à droite, Y devant, m) → la voie.

    Chaque ligne (contour de masque ou polyligne) est densifiée puis ajustée X = a + b·Y dans
    `y_band`. N'est une LIGNE DE VOIE que ce qui est mince (écart-type résiduel ≤ `max_spread_m`)
    et longitudinal (pente ≤ `max_slope_deg`) : une tache transversale — ligne d'arrêt, passage
    piéton, flèche — ne compte pas. On retient la plus proche à gauche et à droite de l'axe
    caméra ; leur écart doit tomber dans `width_range` (sinon c'est un bord opposé ou une ligne
    voisine : pas d'observation). Rend None ou {'offset_m' : écart de la CAMÉRA au centre de la
    voie, évalué à `eval_y` (+ = à droite du centre), 'width_m', 'rel_heading_deg' : cap caméra −
    direction de la voie (+ = tournée vers la droite), 'n_lines'}.
    """
    max_slope = math.tan(math.radians(max_slope_deg))
    fits = []
    for pts in lines_xy:
        P = np.asarray([p for p in _densify(list(pts), step_m) if y_band[0] <= p[1] <= y_band[1]],
                       dtype=np.float64)
        if len(P) < 3 or np.ptp(P[:, 1]) < 1.0:
            continue
        b, a = np.polyfit(P[:, 1], P[:, 0], 1)
        if abs(b) > max_slope or np.std(P[:, 0] - (a + b * P[:, 1])) > max_spread_m:
            continue
        fits.append((a + b * np.mean(y_band), a, b))
    left = [f for f in fits if f[0] < 0]
    right = [f for f in fits if f[0] > 0]
    if not left or not right:
        return None
    L = max(left, key=lambda f: f[0])
    R = min(right, key=lambda f: f[0])
    width = R[0] - L[0]
    if not (width_range[0] <= width <= width_range[1]):
        return None
    xl, xr = L[1] + L[2] * eval_y, R[1] + R[2] * eval_y
    theta = math.degrees(math.atan((L[2] + R[2]) / 2.0))
    return {'offset_m': -(xl + xr) / 2.0, 'width_m': width, 'rel_heading_deg': -theta,
            'n_lines': len(fits)}


def lateral_corrections(anchor_ts, anchor_lat, anchor_dh, query_ts, *, max_gap_s=20.0,
                        ramp_s=5.0, smooth_s=3.0):
    """Ancres (instants où la correction est MESURÉE) → correction latérale et de cap à `query_ts`.

    Lissage médian des ancres sur ±`smooth_s` (une ligne mal classée ne fait pas sauter la
    trace), interpolation linéaire entre deux ancres séparées de moins de `max_gap_s`, maintien
    puis rampe vers 0 sur `ramp_s` au-delà (on ne prolonge pas une correction loin de toute
    mesure). Rend (corr_lat[], corr_dh[], anchored[]) alignés sur `query_ts` — les deux séries sont
    traitées à l'identique : on y passe aussi bien (est, nord) que (latéral, cap)."""
    at = np.asarray(anchor_ts, dtype=np.float64)
    q = np.asarray(query_ts, dtype=np.float64)
    zeros = np.zeros(len(q))
    if len(at) == 0:
        return zeros, zeros, np.zeros(len(q), dtype=bool)
    order = np.argsort(at)
    at = at[order]
    al = np.asarray(anchor_lat, dtype=np.float64)[order]
    ah = np.asarray(anchor_dh, dtype=np.float64)[order]
    sl, sh = np.empty_like(al), np.empty_like(ah)
    for k, t in enumerate(at):
        m = np.abs(at - t) <= smooth_s
        sl[k] = np.median(al[m])
        sh[k] = np.median(ah[m])
    cl, ch, anc = np.zeros(len(q)), np.zeros(len(q)), np.zeros(len(q), dtype=bool)
    for i, t in enumerate(q):
        k = int(np.searchsorted(at, t))
        if 0 < k < len(at) and at[k] - at[k - 1] <= max_gap_s:
            u = (t - at[k - 1]) / max(at[k] - at[k - 1], 1e-9)
            cl[i] = sl[k - 1] * (1 - u) + sl[k] * u
            ch[i] = sh[k - 1] * (1 - u) + sh[k] * u
            anc[i] = True
            continue
        # hors de toute paire d'ancres proches : maintien de la plus proche, puis rampe
        j = 0 if k == 0 else (len(at) - 1 if k >= len(at) else (k - 1 if t - at[k - 1] <= at[k] - t else k))
        gap = abs(t - at[j])
        w = 1.0 if gap <= max_gap_s / 2.0 else max(0.0, 1.0 - (gap - max_gap_s / 2.0) / ramp_s)
        cl[i], ch[i] = sl[j] * w, sh[j] * w
        anc[i] = w > 0
    return cl, ch, anc


#: Natures BD TOPO où un véhicule routier ne roule pas — exclues du rattachement.
NOT_DRIVABLE = ('Sentier', 'Escalier', 'Piste cyclable', 'Chemin', 'Bac ou liaison maritime')


def _moving(ts, xy, *, half_window_s=1.0, min_speed_ms=1.0):
    """En mouvement = déplacement sur ±`half_window_s` au-dessus de `min_speed_ms`. Dérivé des
    POSITIONS, pas d'une vitesse fournie : un récepteur qui RÉPÈTE ses fixes (mesuré le 2026-09-28
    sur ENA : trois points par seconde dont deux identiques) donne une vitesse fixe-à-fixe nulle
    sur deux points sur trois, et le cap serait ignoré en pleine marche."""
    lo = np.searchsorted(ts, ts - half_window_s, side='left')
    hi = np.searchsorted(ts, ts + half_window_s, side='right') - 1
    dt = ts[hi] - ts[lo]
    d = np.hypot(xy[hi, 0] - xy[lo, 0], xy[hi, 1] - xy[lo, 1])
    return np.where(dt > 1e-6, d / np.maximum(dt, 1e-6), 0.0) > min_speed_ms


def lane_map_recalage(track: TypedFrame, road_map: TypedFrame, lanes: TypedFrame, *,
                      radius_m=25.0, max_heading_dev_deg=15.0, max_correction_m=15.0,
                      max_gap_s=20.0, lateral_scale=0.0, width_range=(2.2, 4.8),
                      min_scale_samples=20, max_overshoot_m=2.0,
                      excluded_types=NOT_DRIVABLE) -> TypedFrame:
    """Composition : trace (ts, lat, lon, heading, speed_kmh) + tronçons (`geometry` en (lat, lon),
    `nb_voies`, `largeur_m`, `sens`, `type` = nature BD TOPO) + observations de voie (ts, offset_m, rel_heading_deg,
    width_m optionnel) →
    la MÊME trace enrichie de `corr_de_m`, `corr_dn_m`, `corr_dh_deg`, `road_lateral_m`,
    `road_bearing_deg`, `lane_anchored`. Aucun point n'est retiré ; la correction n'est PAS
    appliquée (l'appelant choisit — patron « calculer, stocker, basculer »).

    Une observation devient ANCRE si la navette est rattachée à un tronçon, alignée sur sa voie
    (|cap relatif caméra ↔ voie| ≤ `max_heading_dev_deg`), si le cap GPS reste à moins de
    `max_heading_dev_deg` du cap déduit de l'axe (au-delà : tronçon faux) et si la correction reste
    sous `max_correction_m` (au-delà : un rattachement ou une ligne faux, pas un GPS). Le rapport
    (`meta['lane_map']['rejected']`) compte les observations écartées par porte.

    ÉCHELLE LATÉRALE : `lateral_scale` 0 = MESURÉE (médiane de largeur vue / largeur attendue
    par la carte, dès `min_scale_samples` observations), sinon celle déclarée ; l'écart et le
    cap relatif y sont ramenés, et la largeur ramenée doit tomber dans `width_range`."""
    df = track.df.copy()
    rm = road_map.df
    if df.empty or rm.empty:
        for c in ('corr_de_m', 'corr_dn_m', 'corr_dh_deg', 'road_lateral_m', 'road_bearing_deg'):
            df[c] = 0.0 if c.startswith('corr') else None
        df['lane_anchored'] = False
        return TypedFrame(df, DataType.GEO_TRACK, meta={**(track.meta or {}), 'lane_map': {'anchors': 0}})
    lat0, lon0 = float(df['lat'].mean()), float(df['lon'].mean())
    to_xy, _ = local_frame(lat0, lon0)
    # un véhicule ne roule ni sur un sentier ni dans un escalier : candidats au rattachement
    # mesurés le 2026-09-28 sur ENA (un « Sentier » à 3 m de la trace, un « Escalier » à 14 m)
    roads = [{'coords': [(p[1], p[0]) for p in r['geometry']],
              'nb_voies': r.get('nb_voies'), 'largeur': r.get('largeur_m'), 'sens': r.get('sens')}
             for r in rm.to_dict('records') if r.get('type') not in excluded_types]
    segs = road_segments(roads, to_xy)
    ts = df['ts'].to_numpy(dtype=np.float64)
    xy = np.array([to_xy(la, lo) for la, lo in zip(df['lat'], df['lon'])], dtype=np.float64)
    moving = _moving(ts, xy)
    pts = []
    for k, r in enumerate(df.itertuples(index=False)):
        h = getattr(r, 'heading', None)
        pts.append((xy[k, 0], xy[k, 1], None if h is None or h != h else float(h), bool(moving[k])))
    matches = match_track(pts, segs, radius_m=radius_m)

    lo = lanes.df.sort_values('ts') if not lanes.df.empty else lanes.df
    a_ts, a_lat, a_dh, a_de, a_dn = [], [], [], [], []
    # Par où sortent les observations qui ne deviennent pas ancres — un filtre qui écarte
    # l'essentiel de ses candidats doit dire par quelle porte.
    rejected = {'not_finite': 0, 'no_match': 0, 'beyond_road_end': 0, 'lane_width': 0, 'lane_heading': 0,
                'gps_heading': 0, 'correction_too_big': 0}
    cands = []
    has_width = 'width_m' in lo.columns
    for r in lo.itertuples(index=False):
        off, rel = float(r.offset_m), float(r.rel_heading_deg)
        width = float(r.width_m) if has_width else float('nan')
        if not (math.isfinite(off) and math.isfinite(rel)):
            rejected['not_finite'] += 1
            continue
        k = int(np.searchsorted(ts, r.ts))
        k = min(max(k, 0), len(ts) - 1)
        if k > 0 and abs(ts[k - 1] - r.ts) < abs(ts[k] - r.ts):
            k -= 1
        m = matches[k]
        if m is None or abs(ts[k] - r.ts) > 1.5:
            rejected['no_match'] += 1
            continue
        if m.get('overshoot_m', 0.0) > max_overshoot_m:   # au-delà du bout : pas un latéral
            rejected['beyond_road_end'] += 1
            continue
        centre, lane_w = expected_lane_offset(roads[m['road']])
        cands.append((float(r.ts), k, m, off, rel, width, centre, lane_w))

    # ÉCHELLE LATÉRALE de la projection : la largeur de voie VUE rapportée à celle qu'attend la
    # carte. Une focale horizontale fausse gonfle tous les X au sol du même facteur (mesuré le
    # 2026-09-28 sur la caméra avant ENA : ×1,5, voies « de 5 m ») ; écart au centre et cap
    # relatif s'en corrigent — l'écart exprimé en FRACTION de voie ne dépend plus de la focale.
    ratios = [c[5] / c[7] for c in cands if math.isfinite(c[5]) and c[7] > 0]
    if lateral_scale:
        scale, scale_source = float(lateral_scale), 'declared'
    elif len(ratios) >= min_scale_samples:
        scale, scale_source = float(np.median(ratios)), 'measured'
    else:
        scale, scale_source = 1.0, 'default'

    for t_obs, k, m, off, rel, width, centre, lane_w in cands:
        if math.isfinite(width) and not (width_range[0] <= width / scale <= width_range[1]):
            rejected['lane_width'] += 1             # un bord opposé ou une voie voisine
            continue
        off = off / scale
        rel = math.degrees(math.atan(math.tan(math.radians(rel)) / scale))
        if abs(rel) > max_heading_dev_deg:          # la navette n'est pas alignée sur sa voie
            rejected['lane_heading'] += 1
            continue
        corr = centre + off - m['lateral_m']
        cam_heading = (m['bearing_deg'] + rel) % 360.0
        h = pts[k][2]
        dh = angle_diff(cam_heading, h) if h is not None else 0.0
        # un cap GPS très loin de l'axe = rattaché au MAUVAIS tronçon (la transversale d'un
        # carrefour, à l'arrêt), pas un GPS à corriger de 70° — mesuré le 2026-09-28
        if abs(dh) > max_heading_dev_deg:
            rejected['gps_heading'] += 1
            continue
        if not abs(corr) <= max_correction_m:
            rejected['correction_too_big'] += 1
            continue
        # la correction se fige en VECTEUR (est, nord) sur l'axe de l'ANCRE : reprojetée sur l'axe
        # courant, elle tournait de 90° au carrefour dès que le point passait sur la transversale
        br = math.radians(m['bearing_deg'])         # vecteur « droite » du sens de circulation
        a_ts.append(t_obs); a_lat.append(corr); a_dh.append(dh)
        a_de.append(corr * math.cos(br)); a_dn.append(-corr * math.sin(br))
    _, ch, anc = lateral_corrections(a_ts, a_lat, a_dh, ts, max_gap_s=max_gap_s)
    ce, cn, _ = lateral_corrections(a_ts, a_de, a_dn, ts, max_gap_s=max_gap_s)

    df['corr_de_m'] = np.round(np.where(anc, ce, 0.0), 3)
    df['corr_dn_m'] = np.round(np.where(anc, cn, 0.0), 3)
    lat_road = [m['lateral_m'] if m else None for m in matches]
    bear = [m['bearing_deg'] if m else None for m in matches]
    df['corr_dh_deg'] = np.round(np.where(anc, ch, 0.0), 2)
    df['road_lateral_m'] = lat_road
    df['road_bearing_deg'] = bear
    df['lane_anchored'] = anc
    report = {'points': len(df), 'matched': int(sum(m is not None for m in matches)),
              'observations': len(lo), 'rejected': rejected,
              'lateral_scale': round(scale, 3), 'lateral_scale_source': scale_source,
              'lateral_scale_samples': len(ratios),
              'anchors': len(a_ts), 'anchored_share': round(float(np.mean(anc)), 3),
              'correction_median_m': round(float(np.median(np.abs(a_lat))), 2) if a_lat else None,
              'correction_p95_m': round(float(np.percentile(np.abs(a_lat), 95)), 2) if a_lat else None,
              'heading_correction_median_deg': round(float(np.median(np.abs(a_dh))), 2) if a_dh else None}
    return TypedFrame(df, DataType.GEO_TRACK, meta={**(track.meta or {}), 'lane_map': report})


SPEC = register(FunctionSpec(
    key='lane_map_recalage',
    name='Recalage latéral par voie + carte',
    description="Corrige la position LATÉRALE et le CAP d'une trace GPS de véhicule par la voie vue "
                "(lignes de voie projetées au sol) et l'axe routier de référence (largeur, nombre "
                "de voies, sens) : rattachement continu (Viterbi), centre attendu de la voie de "
                "droite, écart mesuré au centre de voie → correction, interpolée entre ancres. "
                "Le longitudinal n'est pas touché. N'APPLIQUE rien : la trace sort enrichie.",
    category=FunctionCategory.ENRICHER,
    tags=['geo', 'timeseries', 'requires-road-map', 'lanes'],
    inputs=[
        PortSpec('track', DataType.GEO_TRACK, required_fields=['ts', 'lat', 'lon'],
                 description='Trace du véhicule (heading et speed_kmh servent le rattachement).'),
        PortSpec('road_map', DataType.ROAD_MAP, required_fields=['geometry'],
                 description='Tronçons de référence ((lat, lon), nb_voies, largeur_m, sens, type '
                             '— les natures non roulables sont écartées).',
                 group='reference'),
        PortSpec('lanes', DataType.TABLE, required_fields=['ts', 'offset_m', 'rel_heading_deg'],
                 description="Observations de voie : écart au centre de voie et cap relatif, par "
                             "instant (même base de temps que la trace).", group='reference'),
    ],
    outputs=[
        PortSpec('track', DataType.GEO_TRACK,
                 produced_fields=['corr_de_m', 'corr_dn_m', 'corr_dh_deg', 'road_lateral_m',
                                  'road_bearing_deg', 'lane_anchored'],
                 description="La MÊME trace, enrichie de la correction (est, nord, cap) à appliquer "
                             "et du rattachement routier ; `lane_anchored` dit si la correction "
                             "s'appuie sur une mesure proche (sinon elle vaut 0).",
                 estimates='offset', uncertainty={'model': 'declared',
                                                  'note': 'σ à mesurer contre le recalage ortho 2b'},
                 derived_from=['road_map', 'segmentation', 'gps'], estimate_field='corr_de_m'),
    ],
    params=[
        ParamSpec('radius_m', 'float', 25.0, 5.0, 100.0, 'm', 'Rayon des tronçons candidats.'),
        ParamSpec('max_heading_dev_deg', 'float', 15.0, 1.0, 45.0, '°',
                  'Écart de cap max navette ↔ voie, et cap GPS ↔ axe, pour qu\'une observation '
                  'devienne ancre.'),
        ParamSpec('max_correction_m', 'float', 15.0, 0.5, 30.0, 'm',
                  'Correction latérale max acceptée (au-delà : rattachement ou ligne faux). '
                  "Mesuré en canyon urbain : dérive GPS locale jusqu'à 12 m."),
        ParamSpec('max_gap_s', 'float', 20.0, 1.0, 120.0, 's',
                  'Écart max entre deux ancres pour interpoler.'),
        ParamSpec('max_overshoot_m', 'float', 2.0, 0.0, 20.0, 'm',
                  "Au-delà du bout d'un tronçon de plus de tant, l'écart n'est pas latéral : pas d'ancre."),
        ParamSpec('lateral_scale', 'float', 0.0, 0.0, 5.0, '×',
                  'Échelle latérale de la projection (largeur vue / largeur réelle) ; 0 = mesurée '
                  'contre la carte.'),
    ],
    cost={'cpu_bound': True},
    projects=['ENA'],
    fn=lane_map_recalage,
))
