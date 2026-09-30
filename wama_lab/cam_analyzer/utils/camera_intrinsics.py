"""Champ de vue MESURÉ des caméras avant/arrière — rotation visuelle contre cap GPS
(passe `camera_intrinsics`, appliqué sous ⚑ measured_camera_fov).

Pourquoi : le champ horizontal des caméras est une valeur de FICHE TECHNIQUE (`CAMERA_FOV_H`,
AXIS F4005-E : 110°). Deux mesures indépendantes l'ont contredit le 2026-09-30 sur la caméra
avant : l'échelle latérale du recalage voie + carte (largeurs de voie vues / IGN) valait ×1,862,
et la rotation visuelle (`geometry.ego_rotation`) sur un demi-tour valait −380° contre −191° au
GPS — les deux disent une focale ~1,9× plus longue, soit ~75° au lieu de 110° (la vidéo 384×248
est vraisemblablement un recadrage du capteur). Une focale fausse fausse tout ce qui passe par
la caméra : latéral des objets, largeur des voies vues, cap par ratio de boîte, projection sol.

Méthode — patron « calculer, stocker, basculer » :
  1. fenêtres de VIRAGE franc en roulant, tirées de la trace (le cap GPS n'est fiable qu'en
     mouvement ; à l'arrêt il est TENU, `ego_rotation.yaw_disagreement`) ;
  2. par paire d'images consécutives : points suivis (Lucas-Kanade, contrôle aller-retour),
     points collés au vitrage écartés, rotation par `estimate_ego_rotation` AVEC LA FOCALE
     SUPPOSÉE ;
  3. rotation cumulée vue contre rotation GPS par fenêtre → `focal_scale_from_rotation` → focale
     réelle → champs horizontal ET vertical (pixels CARRÉS supposés — dit dans le rapport).
Seules avant et arrière : leur translation est dans l'axe optique, ce que le modèle sépare de la
rotation ; une caméra LATÉRALE translate en travers de sa visée, et ce décalage horizontal se
confond avec un lacet.

Consommé par `prediction_adapter.camera_geometry` (et son miroir JS) quand ⚑ measured_camera_fov
est ON. ⚠ Basculer change la géométrie de TOUTE la chaîne : la calibration sol (tangage estimé
avec l'ancienne focale), le recalage voie + carte, le tracking et les marquages sont à rejouer.
"""
import logging
import math

import numpy as np

logger = logging.getLogger(__name__)

#: Caméras mesurables par cette méthode (translation dans l'axe optique).
MEASURABLE = ('front', 'rear')
#: Fenêtres de virage : durée (s GPS), rotation minimale, vitesse moyenne et minimale (m/s), nombre
#: maximal. Réglées sur mesure le 2026-09-30 : des fenêtres COURTES et SÉLECTIVES (14 s, ≥ 30°)
#: ne retenaient que le MÊME virage à chaque tour — mêmes erreurs GPS, fenêtres non indépendantes —
#: et gonflaient le facteur (×2,19, le cap GPS retardant sur l'image en fin de fenêtre) ; des
#: fenêtres de 30 s accumulaient la dérive visuelle (×1,64, dispersion doublée). 20 s, ≥ 20°, 30
#: virages aux LIEUX VARIÉS (gauche et droite) : ×1,87 avant, ×1,95 arrière, en accord avec
#: l'échelle latérale du recalage voie + carte (×1,862). Une recherche de retard du cap GPS a été
#: essayée et RETIRÉE : son optimum sautait de 0 à 1,5 s selon les fenêtres, sans rien stabiliser.
WINDOW_S, TURN_MIN_DEG, MIN_MEAN_SPEED, MIN_SPEED = 20.0, 20.0, 2.0, 0.5
MAX_WINDOWS = 30
#: Une paire dont la rotation n'est pas exploitable (résidu > 2 px, trop peu de points) ne compte
#: pas ; au-delà de cette part de paires perdues, la fenêtre entière est écartée (sa rotation
#: cumulée serait tronquée, donc biaisée vers zéro).
MAX_LOST_SHARE = 0.1


def turn_windows(sh_traj, *, window_s=WINDOW_S, turn_min_deg=TURN_MIN_DEG,
                 min_mean_speed=MIN_MEAN_SPEED, min_speed=MIN_SPEED, max_windows=MAX_WINDOWS):
    """Fenêtres [t0, t1] (temps GPS) de virage franc en roulant : rotation cumulée du cap ≥
    `turn_min_deg`, vitesse moyenne ≥ `min_mean_speed` et jamais sous `min_speed` (cap tenu).
    Les plus fortes d'abord, sans recouvrement. `sh_traj` : [(t, e, n, cap)] trié."""
    T = np.asarray(sh_traj, dtype=float)
    if len(T) < 10:
        return []
    t, e, n, h = T[:, 0], T[:, 1], T[:, 2], T[:, 3]
    dh = (np.diff(h) + 180.0) % 360.0 - 180.0
    cum_h = np.concatenate([[0.0], np.cumsum(dh)])
    cands = []
    for i in range(len(t)):
        j = int(np.searchsorted(t, t[i] + window_s))
        if j >= len(t):
            break
        dt = np.diff(t[i:j + 1])
        ds = np.hypot(np.diff(e[i:j + 1]), np.diff(n[i:j + 1]))
        if len(dt) == 0 or dt.sum() <= 0:
            continue
        v = ds / np.maximum(dt, 1e-3)
        turn = cum_h[j] - cum_h[i]
        if abs(turn) >= turn_min_deg and ds.sum() / dt.sum() >= min_mean_speed and v.min() >= min_speed:
            cands.append((abs(turn), t[i], t[j], turn))
    out = []
    for _, t0, t1, turn in sorted(cands, reverse=True):
        if all(t1 <= a or t0 >= b for a, b, _ in out):
            out.append((t0, t1, turn))
        if len(out) >= max_windows:
            break
    return sorted(out)


def _pair_matches(ga, gb):
    """Correspondances (x0, y0, x1, y1) du DÉCOR entre deux images en niveaux de gris."""
    import cv2
    p0 = cv2.goodFeaturesToTrack(ga, maxCorners=800, qualityLevel=0.005, minDistance=5)
    if p0 is None:
        return []
    p1, st, _ = cv2.calcOpticalFlowPyrLK(ga, gb, p0, None, winSize=(21, 21), maxLevel=3)
    pb, st2, _ = cv2.calcOpticalFlowPyrLK(gb, ga, p1, None, winSize=(21, 21), maxLevel=3)
    ok = (st.ravel() == 1) & (st2.ravel() == 1) & (np.linalg.norm(p0 - pb, axis=2).ravel() < 1.0)
    # immobiles dans l'image = collés au vitrage (reflets, capot) : ils violent le modèle
    ok &= np.linalg.norm(p1 - p0, axis=2).ravel() >= 0.5
    return [(a[0], a[1], b[0], b[1]) for a, b in zip(p0[ok].reshape(-1, 2), p1[ok].reshape(-1, 2))]


def measure_camera(session, position, windows, fov_h_declared, fps, to_frame):
    """Rotation vue (focale SUPPOSÉE) contre rotation GPS, par fenêtre → focale réelle."""
    import cv2
    from wama_data.functions.geometry.ego_rotation import (estimate_ego_rotation,
                                                           focal_scale_from_rotation)
    cam = session.cameras.filter(position=position).first()
    if cam is None or not getattr(cam, 'video_file', None):
        return {'skipped': 'pas de vidéo'}
    cap = cv2.VideoCapture(cam.video_file.path)
    if not cap.isOpened():
        return {'skipped': 'vidéo illisible'}
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fx_decl = (W / 2.0) / math.tan(math.radians(fov_h_declared) / 2.0)
    pairs, per_window = [], []
    for t0, t1, turn in windows:
        f0, f1 = to_frame(t0), to_frame(t1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
        ok, prev = cap.read()
        if not ok:
            continue
        prev = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
        vis, expa, lost, total = 0.0, 0.0, 0, 0
        for _ in range(f0 + 1, f1 + 1):
            ok, cur = cap.read()
            if not ok:
                break
            cur = cv2.cvtColor(cur, cv2.COLOR_BGR2GRAY)
            total += 1
            r = estimate_ego_rotation(_pair_matches(prev, cur), fx_decl, (W / 2.0, H / 2.0))
            if r is None or r['residual_px'] > 2.0:
                lost += 1
            else:
                vis += r['yaw_deg']
                expa += r['expansion']
            prev = cur
        kept = total > 0 and lost / total <= MAX_LOST_SHARE
        # `expansion` cumulée : diagnostic du point de fuite (un point de fuite décalé du centre
        # ajoute un faux lacet proportionnel au trajet ; mesuré petit le 2026-09-30, ~10 px)
        per_window.append({'t0': round(float(t0), 1), 't1': round(float(t1), 1),
                           'gps_deg': round(float(turn), 1), 'visual_deg': round(vis, 1),
                           'expansion': round(expa, 4), 'pairs': total, 'lost': lost, 'kept': kept})
        if kept:
            pairs.append((vis, float(turn)))
    cap.release()
    fit = focal_scale_from_rotation(pairs)
    out = {'fov_h_declared': fov_h_declared, 'fx_declared_px': round(fx_decl, 1), 'image': [W, H],
           'windows': per_window}
    if not fit:
        out['skipped'] = 'moins de 2 fenêtres de virage exploitables'
        return out
    fx = fx_decl * fit['scale']
    out.update(fit)
    out.update({'fx_px': round(fx, 1),
                'fov_h': round(math.degrees(2 * math.atan((W / 2.0) / fx)), 1),
                # pixels CARRÉS supposés : la rotation ne mesure que l'axe horizontal
                'fov_v': round(math.degrees(2 * math.atan((H / 2.0) / fx)), 1),
                'fov_v_assumption': 'pixels carrés'})
    return out


def measure_camera_intrinsics(session):
    """Mesure et rend `{position: {...}}` pour les caméras avant/arrière, plus le recoupement par
    l'échelle latérale du recalage voie + carte (caméra avant) quand il existe."""
    from .ego_pose import effective_gps_track
    from .prediction_adapter import (make_local_frame, shuttle_trajectory, antenna_offset,
                                     CAMERA_FOV_H)
    gt = effective_gps_track(session)
    to_local = make_local_frame(gt)
    sh = shuttle_trajectory(gt, to_local, antenna=antenna_offset(session))
    windows = turn_windows(sh)
    scale = float(session.gps_time_scale or 1.0) or 1.0
    off = float(session.gps_time_offset or 0.0)
    fov_over = (session.config or {}).get('camera_fov') or {}
    out = {'turn_windows': len(windows)}
    for pos in MEASURABLE:
        cam = session.cameras.filter(position=pos).first()
        if cam is None:
            continue
        fps = cam.fps or 12.0
        declared = float((fov_over.get(pos) or {}).get('h', CAMERA_FOV_H[pos]))
        out[pos] = measure_camera(session, pos, windows, declared, fps,
                                  lambda tg, fps=fps: int(round((tg - off) / scale * fps)))
    lane = (((session.results_summary or {}).get('lane_map_recalage') or {}).get('report') or {})
    ls = lane.get('lateral_scale')
    if ls and lane.get('lateral_scale_source') == 'measured' and 'front' in out:
        d = out['front'].get('fov_h_declared') or CAMERA_FOV_H['front']
        out['front']['lane_scale_cross_check'] = {
            'lateral_scale': ls,
            'fov_h': round(math.degrees(2 * math.atan(math.tan(math.radians(d) / 2) / ls)), 1)}
    return out


def measured_fov(session, position):
    """(fov_h, fov_v) MESURÉS d'une caméra, ou None — lu par `camera_geometry`."""
    m = (((session.results_summary or {}).get('camera_intrinsics') or {}).get(position) or {})
    if m.get('fov_h') and m.get('fov_v'):
        return float(m['fov_h']), float(m['fov_v'])
    return None
