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

Métrique #2 — **cohérence caméra ↔ position monde** (`camera_consistency`, 2026-09-30) :
  deux contrôles qu'aucune vérité terrain n'est nécessaire à trancher, par caméra —
  · part des objets placés DERRIÈRE leur propre caméra (physiquement impossible : 0 = idéal) ;
  · désaccord entre la profondeur que la caméra affiche (`distance_m`, l'étiquette) et celle de la
    position monde le long de l'axe de cette caméra — la position dessinée et l'étiquette peuvent
    venir de sources différentes (sol/profondeur vs pinhole), et un écart s'y lit.
  Né d'un diagnostic : un véhicule étiqueté 32,8 m était dessiné à 43 m de sa caméra.

Métrique #3 — **continuité de suivi** (`tracking_continuity`, 2026-10-01) : un suivi multi-caméras
  peut DUPLIQUER un objet (deux identifiants pour un véhicule vu par deux caméras) ou le PERDRE
  (une trajectoire d'une même caméra éclatée sur plusieurs identifiants). Trois compteurs, sans
  vérité terrain :
  · chaînes de détecteur ÉCLATÉES — une trajectoire d'une caméra (même identifiant de détecteur)
    portée par plus d'un identifiant global ;
  · paires PROCHES ENTRE CAMÉRAS — deux identifiants simultanés, restés proches au moins
    `min_frames` images, que AUCUNE caméra n'a vus ensemble (doublons probables) ;
  · paires proches VUES ENSEMBLE par une même caméra — deux objets prouvés distincts (deux boîtes
    d'une même image) : la référence de ce que « proche » veut dire pour de vrais voisins ;
  · RELAIS RATÉS — un identifiant quitte une caméra et, dans `relay_frames` images, un AUTRE naît au
    même endroit de l'image (boîtes qui se recouvrent) : le même objet a perdu son identifiant. C'est
    la perte qu'un compteur de chaînes ne voit pas quand le détecteur, lui aussi, change de numéro.

Métrique #4 — **biais de DISTANCE par portée** (`range_bias_curve`, 2026-10-05) : une méthode de
  mesure de distance (projection sol, hauteur de boîte…) est-elle juste LOIN comme PRÈS ? Arbitre
  sans vérité terrain : un objet IMMOBILE ne bouge pas. Sa position fixe est prise sur ses
  observations PROCHES (où la méthode de référence est précise) ; pour chaque observation, la
  distance VRAIE est celle de la caméra (pose du moment) à ce point fixe ; le rapport mesuré / vrai,
  par tranche de distance vraie, est la courbe de biais. Universelle : toute caméra, toute méthode,
  calculée automatiquement à chaque passage — rien à saisir pour une nouvelle vue. Née d'une mesure
  du cam_analyzer : la projection sol de l'arrière donnait 0,60 à 30-40 m, la hauteur de boîte non.
  `correct_range` applique une courbe (repli : pas de correction là où elle ne sait rien).

Pur (numpy) : le cœur `track_position_spread` ne dépend ni de Django ni de pandas et se teste
hors serveur. Le wrapper `placement_spread` (FunctionSpec) l'adapte à un `TypedFrame`.
"""
from __future__ import annotations

import numpy as np

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
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


def camera_consistency(observations, *, min_obs=20):
    """Cœur PUR de la métrique #2 (aucune dépendance Django/pandas).

    observations : itérable de (camera, x, y, yaw_deg, mount_x, mount_y, depth_m) — position de
        l'objet en repère VÉHICULE (x droite, y avant, m), orientation de la caméra (degrés, sens
        horaire depuis l'avant), point de montage de la caméra dans le même repère, et profondeur
        que la caméra annonce le long de son axe (None si inconnue).
    min_obs : observations minimales pour qu'une caméra soit résumée.

    Rend {camera: {n, behind_share, depth_n, depth_rel_err_median, depth_rel_err_p90}} :
    `behind_share` = part des objets dont la projection sur l'axe de la caméra est ≤ 0 (derrière
    elle) ; `depth_rel_err` = |profondeur de la position − profondeur annoncée| / annoncée.
    """
    from collections import defaultdict
    by_cam = defaultdict(lambda: {'n': 0, 'behind': 0, 'err': []})
    for cam, x, y, yaw, mx, my, depth in observations:
        h = np.radians(yaw)
        axial = (x - mx) * np.sin(h) + (y - my) * np.cos(h)
        if not np.isfinite(axial):
            continue
        acc = by_cam[cam]
        acc['n'] += 1
        acc['behind'] += axial <= 0
        if depth is not None and np.isfinite(depth) and depth > 0:
            acc['err'].append(abs(axial - depth) / depth)
    out = {}
    for cam, acc in sorted(by_cam.items()):
        if acc['n'] < min_obs:
            continue
        err = np.asarray(acc['err'], dtype=float)
        out[cam] = {'n': acc['n'],
                    'behind_share': round(acc['behind'] / acc['n'], 4),
                    'depth_n': int(err.size),
                    'depth_rel_err_median': round(float(np.median(err)), 4) if err.size else None,
                    'depth_rel_err_p90': round(float(np.percentile(err, 90)), 4) if err.size else None}
    return out


def tracking_continuity(observations, *, root=None, close_m=4.0, min_frames=12, chain_gap_frames=48,
                        relay_frames=6, relay_iou=0.3, switchback_frames=60):
    """Cœur PUR de la métrique #3 (aucune dépendance Django/pandas).

    observations : itérable de (frame, camera, chain_id, track_id, x, y[, bbox]) — `chain_id`
        identifie la trajectoire du détecteur DANS sa caméra (None si inconnue), `track_id`
        l'identifiant global, (x, y) la position monde (m), `bbox` [x0, y0, x1, y1] facultative
        (sans elle, les relais ratés ne sont pas comptés).
    root : fonction track_id → identifiant final (fusions faites après coup) ; identité par défaut.
    chain_gap_frames : un trou plus long COUPE la chaîne — un détecteur relancé (analyse par fenêtres)
        RÉUTILISE ses numéros pour d'autres objets ; sans cette coupure, ces réutilisations comptaient
        comme des éclatements (63 % mesurés à tort le 2026-10-01).

    switchback_frames : FAUSSES FUSIONS (2026-10-03) — un objet ne suit, dans une caméra, qu'UNE
        chaîne de détecteur à la fois. Un identifiant qui REVIENT à une chaîne déjà quittée (A → B → A
        en moins de `switchback_frames`) alors que la boîte de B est SÉPARÉE de celle de A (recouvrement
        < `relay_iou` : pas un doublon de détecteur sur le même objet) porte au moins deux objets.
        Les éclatements et les doublons ne le voyaient pas — une fusion abusive les fait même BAISSER.

    Rend {'chains', 'chain_splits', 'tracks', 'cross_camera_close_pairs', 'same_camera_close_pairs',
    'relay_breaks', 'switchbacks', 'tracks_mixing_objects'}.
    """
    from collections import defaultdict
    r = root or (lambda g: g)
    raw_chains = defaultdict(list)
    by_frame = defaultdict(list)
    tracks = set()
    first_last = {}                     # (caméra, gid) -> [1re image, boîte, dernière image, boîte]
    per_track_cam = defaultdict(list)   # (caméra, gid) -> [(image, chaîne, boîte)] — fausses fusions
    for ob in observations:
        fr, cam, chain_id, g, x, y = ob[:6]
        box = ob[6] if len(ob) > 6 else None
        g = r(g)
        tracks.add(g)
        if chain_id is not None and box is not None:
            per_track_cam[(cam, g)].append((fr, chain_id, box))
        if box is not None:
            fl = first_last.get((cam, g))
            if fl is None:
                first_last[(cam, g)] = [fr, box, fr, box]
            else:
                if fr < fl[0]:
                    fl[0], fl[1] = fr, box
                if fr > fl[2]:
                    fl[2], fl[3] = fr, box
        if chain_id is not None:
            raw_chains[(cam, chain_id)].append((fr, g))
        by_frame[fr].append((g, cam, x, y))
    chains = defaultdict(set)
    for key, seq in raw_chains.items():
        seq.sort(key=lambda s: s[0])
        part, last = 0, None
        for fr, g in seq:
            if last is not None and fr - last > chain_gap_frames:
                part += 1
            chains[(key, part)].add(g)
            last = fr
    close = defaultdict(int)
    together = set()
    for rows in by_frame.values():
        n = len(rows)
        for i in range(n):
            gi, ci, xi, yi = rows[i]
            for j in range(i + 1, n):
                gj, cj, xj, yj = rows[j]
                if gi == gj:
                    continue
                key = (gi, gj) if gi < gj else (gj, gi)
                if ci == cj:
                    together.add(key)
                if (xi - xj) ** 2 + (yi - yj) ** 2 < close_m * close_m:
                    close[key] += 1
    persistent = [k for k, c in close.items() if c >= min_frames]
    # relais ratés : par caméra, une fin et un début d'identifiants DIFFÉRENTS, proches dans le temps
    # et au même endroit de l'image
    relay_breaks = 0
    by_cam = defaultdict(list)
    for (cam, g), (f0, b0, f1, b1) in first_last.items():
        by_cam[cam].append((g, f0, b0, f1, b1))
    for rows in by_cam.values():
        starts = sorted(rows, key=lambda r: r[1])
        import bisect
        keys = [s[1] for s in starts]
        for g, _f0, _b0, f1, b1 in rows:
            i = bisect.bisect_right(keys, f1)
            while i < len(starts) and starts[i][1] - f1 <= relay_frames:
                g2, _sf, sb = starts[i][0], starts[i][1], starts[i][2]
                if g2 != g and _iou(b1, sb) >= relay_iou:
                    relay_breaks += 1
                    break
                i += 1
    # fausses fusions : retour à une chaîne quittée, la chaîne intermédiaire étant un AUTRE objet
    switchbacks, mixing = 0, set()
    for (cam, g), seq in per_track_cam.items():
        seq.sort(key=lambda s: s[0])
        last = {}                        # chaîne -> (dernière image, dernière boîte)
        prev = None
        for fr, ch, box in seq:
            if (prev is not None and ch != prev and ch in last
                    and fr - last[ch][0] <= switchback_frames
                    and _iou(last[prev][1], last[ch][1]) < relay_iou):
                switchbacks += 1
                mixing.add(g)
            last[ch] = (fr, box)
            prev = ch
    return {'chains': len(chains),
            'chain_splits': sum(1 for s in chains.values() if len(s) > 1),
            'tracks': len(tracks),
            'cross_camera_close_pairs': sum(1 for k in persistent if k not in together),
            'same_camera_close_pairs': sum(1 for k in persistent if k in together),
            'relay_breaks': relay_breaks,
            'switchbacks': switchbacks,
            'tracks_mixing_objects': len(mixing)}


#: Tranches de distance VRAIE (m) de la courbe de biais — les mêmes pour toute caméra.
RANGE_BINS = ((4.0, 10.0), (10.0, 15.0), (15.0, 20.0), (20.0, 25.0), (25.0, 30.0), (30.0, 40.0))
#: Observations minimales pour qu'une tranche porte un rapport (sinon : rien de su, pas de correction).
RANGE_MIN_OBS = 150


def static_range_ratios(observations, *, near=(4.0, 10.0), min_near=3):
    """Rapports distance mesurée / distance VRAIE pour des objets IMMOBILES — cœur pur de la métrique #4.

    `observations` : itérable de (objet, cam_e, cam_n, ref_e, ref_n, ref_range, ranges) —
      `cam_e/cam_n` la position monde de la caméra à cet instant ; `ref_e/ref_n/ref_range` la position
      monde et la distance donnée par la méthode de RÉFÉRENCE (ou None) ; `ranges` = {méthode: distance
      mesurée ou None}.
    Le point fixe d'un objet est la médiane de ses positions de référence prises PRÈS (`near`, au moins
    `min_near`) ; les objets sans assez d'observations proches sont ignorés.
    Rend ({méthode: [(distance vraie, rapport), …]}, nombre d'objets retenus)."""
    from collections import defaultdict
    by_obj = defaultdict(list)
    for ob in observations:
        by_obj[ob[0]].append(ob)
    out = defaultdict(list)
    used = 0
    for obs in by_obj.values():
        near_pts = [(o[3], o[4]) for o in obs
                    if o[5] is not None and near[0] <= o[5] <= near[1] and o[3] is not None]
        if len(near_pts) < min_near:
            continue
        ae = float(np.median([p[0] for p in near_pts]))
        an = float(np.median([p[1] for p in near_pts]))
        used += 1
        for _obj, ce, cn, _re, _rn, _rr, ranges in obs:
            r_true = float(np.hypot(ae - ce, an - cn))
            if r_true <= 0:
                continue
            for method, r in (ranges or {}).items():
                if r is not None:
                    out[method].append((r_true, float(r) / r_true))
    return dict(out), used


def range_bias_curve(pairs, *, bins=RANGE_BINS, min_obs=RANGE_MIN_OBS):
    """Courbe de biais d'une méthode : par tranche de distance vraie, la médiane du rapport mesuré /
    vrai et sa dispersion (p25-p75). `pairs` = [(distance vraie, rapport)]. Une tranche qui a moins de
    `min_obs` observations n'a pas de rapport (None) : on n'y sait rien, on n'y corrigera rien.
    Rend [{'lo', 'hi', 'n', 'ratio', 'p25', 'p75'}, …]."""
    out = []
    for lo, hi in bins:
        vals = [q for r, q in pairs if lo <= r < hi]
        row = {'lo': lo, 'hi': hi, 'n': len(vals), 'ratio': None, 'p25': None, 'p75': None}
        if len(vals) >= min_obs:
            row.update(ratio=round(float(np.median(vals)), 3), p25=round(float(np.percentile(vals, 25)), 3),
                       p75=round(float(np.percentile(vals, 75)), 3))
        out.append(row)
    return out


def correct_range(r_measured, curve):
    """Distance corrigée par une courbe de biais (`range_bias_curve`) : r_mesurée / rapport, le rapport
    étant interpolé sur la distance MESURÉE (centre de chaque tranche ramené en distance mesurée).
    En deçà de la 1ʳᵉ tranche connue : sa valeur ; au-delà de la dernière : la dernière (pas
    d'extrapolation inventée). Courbe vide ou inexploitable : la distance telle quelle."""
    pts = sorted(((r['lo'] + r['hi']) / 2.0 * r['ratio'], r['ratio'])
                 for r in (curve or []) if r.get('ratio'))
    if not pts or r_measured is None:
        return r_measured
    if r_measured <= pts[0][0]:
        ratio = pts[0][1]
    elif r_measured >= pts[-1][0]:
        ratio = pts[-1][1]
    else:
        ratio = pts[0][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= r_measured <= x1:
                ratio = y0 + (y1 - y0) * (r_measured - x0) / (x1 - x0) if x1 > x0 else y0
                break
    return r_measured / ratio if ratio > 0 else r_measured


def range_curve_is_usable(curve, *, ratio_bounds=(0.4, 2.0), min_bins=2):
    """Une courbe ne s'applique que si elle est PLAUSIBLE : au moins `min_bins` tranches mesurées,
    rapports dans des bornes physiques, et la distance corrigée CROISSANTE avec la distance mesurée
    (sinon deux objets échangeraient leur ordre de profondeur). Rend (bool, raison).

    `min_bins` (2026-10-05) : une courbe d'UNE tranche n'est qu'un facteur d'échelle tiré de peu
    d'objets — mesuré sur la latérale droite (59 garés, tranche 4-10 m seule) : 0,83 à un calcul, 0,96
    au suivant ; la correction tirée du premier SUR-corrigeait le second (1,15)."""
    known = [r for r in (curve or []) if r.get('ratio')]
    if len(known) < min_bins:
        return False, f'moins de {min_bins} tranches mesurées'
    if any(not ratio_bounds[0] <= r['ratio'] <= ratio_bounds[1] for r in known):
        return False, 'rapport hors bornes physiques'
    grid = [1.0 + 0.5 * i for i in range(100)]
    corrected = [correct_range(r, curve) for r in grid]
    if any(b <= a for a, b in zip(corrected, corrected[1:])):
        return False, 'distance corrigée non croissante'
    return True, 'ok'


def _iou(a, b):
    """Recouvrement de deux boîtes [x0, y0, x1, y1] (0 si l'une manque) — DÉLÈGUE au domicile unique
    `shapes.box_iou` depuis le 2026-10-05 (trois copies identiques vivaient ici, au cam_analyzer et à
    l'anonymizer). Le nom reste : la métrique de continuité et ses tests l'appellent."""
    from .shapes import box_iou
    return box_iou(a, b)


def tracking_continuity_frame(observations: TypedFrame, *, frame_field='frame', camera_field='camera',
                              chain_field='chain_id', track_field='track_id', x_field='x', y_field='y',
                              close_m=4.0, min_frames=12) -> TypedFrame:
    """Wrapper FunctionSpec de la métrique #3 : une ligne de compteurs (plus bas = meilleur pour les
    éclatements et les paires entre caméras ; les paires d'une même caméra sont la référence)."""
    import pandas as pd
    df = observations.df
    rows = [(r[frame_field], r[camera_field], r[chain_field] if chain_field in df.columns else None,
             r[track_field], float(r[x_field]), float(r[y_field])) for _, r in df.iterrows()]
    res = tracking_continuity(rows, close_m=close_m, min_frames=min_frames)
    return TypedFrame(pd.DataFrame([res]), DataType.TABLE, meta={'lower_is_better': True})


TRACKING_CONTINUITY_SPEC = register(FunctionSpec(
    key='tracking_continuity',
    name='Continuité de suivi multi-caméras',
    description="Compte, sans vérité terrain, ce qu'un suivi multi-caméras DUPLIQUE ou PERD : "
                "trajectoires de détecteur éclatées sur plusieurs identifiants, paires d'identifiants "
                "restés proches qu'aucune caméra n'a vus ensemble (doublons probables), et en "
                "référence les paires proches qu'une même caméra a vues ensemble (vrais voisins).",
    category=FunctionCategory.INDICATOR,
    tags=['tracking', 'multi-camera', 'ab-metric', 'no-ground-truth'],
    inputs=[
        PortSpec('observations', DataType.DETECTIONS,
                 required_fields=['frame', 'camera', 'track_id', 'x', 'y'],
                 description="Une ligne par détection suivie : image, caméra, identifiant de la "
                             "trajectoire du détecteur (`chain_id`, facultatif), identifiant global "
                             "et position monde."),
    ],
    outputs=[
        PortSpec('counts', DataType.TABLE,
                 produced_fields=['chains', 'chain_splits', 'tracks', 'cross_camera_close_pairs',
                                  'same_camera_close_pairs', 'relay_breaks', 'switchbacks',
                                  'tracks_mixing_objects'],
                 description='Une ligne de compteurs ; éclatements et paires entre caméras : plus '
                             'bas = meilleur.'),
    ],
    params=[
        ParamSpec('close_m', 'float', 4.0, 0.5, 20.0, unit='m',
                  description='Distance en deçà de laquelle deux identifiants sont « proches ».'),
        ParamSpec('min_frames', 'int', 12, 1, 1000,
                  description='Images proches requises pour compter une paire.'),
    ],
    cost={'cpu_bound': True},
    fn=tracking_continuity_frame,
))


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


def camera_consistency_frame(detections: TypedFrame, *, camera_field='camera', x_field='veh_x',
                             y_field='veh_y', yaw_field='cam_yaw', mount_x_field='mount_x',
                             mount_y_field='mount_y', depth_field='distance_m',
                             min_obs=20) -> TypedFrame:
    """Wrapper FunctionSpec de la métrique #2 : une ligne par caméra (part derrière la caméra,
    écart de profondeur médian et p90). INDICATOR, plus bas = meilleur."""
    import pandas as pd
    df = detections.df
    rows = []
    for _, r in df.iterrows():
        d = r[depth_field] if depth_field in df.columns else None
        rows.append((r[camera_field], float(r[x_field]), float(r[y_field]), float(r[yaw_field]),
                     float(r[mount_x_field]), float(r[mount_y_field]),
                     float(d) if d is not None and d == d else None))
    res = camera_consistency(rows, min_obs=min_obs)
    out = pd.DataFrame([{'camera': c, **v} for c, v in res.items()])
    return TypedFrame(out, DataType.TABLE, meta={'lower_is_better': True})


CAMERA_CONSISTENCY_SPEC = register(FunctionSpec(
    key='camera_consistency',
    name='Cohérence caméra ↔ position',
    description="Contrôle, par caméra et sans vérité terrain, qu'un placement monde est cohérent "
                "avec ce que la caméra voit : part des objets placés DERRIÈRE leur caméra "
                "(impossible, 0 = idéal) et écart relatif entre la profondeur annoncée par la caméra "
                "et celle de la position le long de son axe.",
    category=FunctionCategory.INDICATOR,
    tags=['geometry', 'placement-quality', 'ab-metric', 'no-ground-truth'],
    inputs=[
        PortSpec('detections', DataType.DETECTIONS,
                 required_fields=['camera', 'veh_x', 'veh_y', 'cam_yaw', 'mount_x', 'mount_y'],
                 description='Détections en repère véhicule, avec orientation et montage de la '
                             'caméra qui les a vues (profondeur `distance_m` facultative).'),
    ],
    outputs=[
        PortSpec('per_camera', DataType.TABLE,
                 produced_fields=['camera', 'n', 'behind_share', 'depth_rel_err_median',
                                  'depth_rel_err_p90'],
                 description='Une ligne par caméra ; plus bas = meilleur.'),
    ],
    params=[
        ParamSpec('min_obs', 'int', 20, 1, 100000,
                  description='Observations minimales pour qu\'une caméra soit résumée.'),
    ],
    cost={'cpu_bound': True},
    fn=camera_consistency_frame,
))


def range_bias_frame(observations: TypedFrame, *, object_field='object', min_obs=RANGE_MIN_OBS) -> TypedFrame:
    """Wrapper FunctionSpec de la métrique #4 : une ligne par (méthode, tranche). Les colonnes
    `range_<méthode>` du tableau d'entrée sont les distances mesurées par chaque méthode."""
    import pandas as pd
    df = observations.df
    methods = [c[len('range_'):] for c in df.columns if c.startswith('range_')]

    def _v(x):
        return None if x is None or x != x else float(x)
    rows = [(r[object_field], float(r['cam_e']), float(r['cam_n']), _v(r.get('ref_e')), _v(r.get('ref_n')),
             _v(r.get('ref_range')), {m: _v(r[f'range_{m}']) for m in methods}) for _, r in df.iterrows()]
    ratios, used = static_range_ratios(rows)
    out = [{'method': m, **b} for m, pairs in ratios.items() for b in range_bias_curve(pairs, min_obs=min_obs)]
    return TypedFrame(pd.DataFrame(out), DataType.TABLE, meta={'objects': used})


RANGE_BIAS_SPEC = register(FunctionSpec(
    key='range_bias_curve',
    name='Biais de distance par portée',
    description="Mesure, sans vérité terrain, si une méthode de mesure de distance est juste LOIN comme "
                "PRÈS : un objet immobile ne bouge pas — sa position fixe est prise sur ses observations "
                "proches, et le rapport distance mesurée / distance vraie (caméra → ce point) est donné "
                "par tranche de distance. Universelle (toute caméra, toute méthode) ; la courbe sert "
                "aussi à CORRIGER la méthode (`correct_range`).",
    category=FunctionCategory.INDICATOR,
    tags=['geometry', 'placement-quality', 'calibration', 'no-ground-truth'],
    inputs=[
        PortSpec('observations', DataType.TABLE,
                 required_fields=['object', 'cam_e', 'cam_n', 'ref_e', 'ref_n', 'ref_range'],
                 description="Une ligne par observation d'un objet immobile : position monde de la "
                             "caméra, position et distance de la méthode de référence, et une colonne "
                             "`range_<méthode>` par méthode à juger."),
    ],
    outputs=[
        PortSpec('curve', DataType.TABLE,
                 produced_fields=['method', 'lo', 'hi', 'n', 'ratio', 'p25', 'p75'],
                 description='Une ligne par méthode et tranche : 1 = juste, < 1 = distances comprimées.'),
    ],
    params=[
        ParamSpec('min_obs', 'int', RANGE_MIN_OBS, 10, 100000,
                  description="Observations minimales pour qu'une tranche porte un rapport."),
    ],
    cost={'cpu_bound': True},
    fn=range_bias_frame,
))


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
