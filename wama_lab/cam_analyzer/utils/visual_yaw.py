"""Rotation VUE de la navette — seconde source de cap, indépendante du GPS (passe `visual_yaw`,
appliquée sous ⚑ visual_heading par le filtre navette).

Le cap de la navette ne venait que du GPS ; sous 1 m/s il est TENU faute de mieux, et c'est là
qu'il se trompe (manœuvres, virages lents). La caméra avant voit la rotation : `geometry.
ego_rotation` la mesure paire d'images par paire d'images. Mesuré le 2026-09-30 sur les 115
segments où le filtre tient le cap (protocole `CHAINE §D.4 ⑥`) : cap de sortie 4,3° médiane /
16,9° p90 contre 4,7° / 30,5° en le tenant, et 13,9° contre 30,2° sur les vrais virages.

Deux conditions, toutes deux MESURÉES comme indispensables :
  * la focale MESURÉE (passe `camera_intrinsics`) — avec celle de la fiche, les rotations vues
    valent ×1,87 la réalité : la passe refuse de tourner sans elle ;
  * seulement quand la navette ROULE : arrêtée, le décor ne bouge plus dans l'image et seuls les
    autres usagers y bougent — jusqu'à 90° de fausse rotation sur un arrêt de 3 min. Un véhicule
    non holonome ne tourne pas sans avancer.

Stocké : `results_summary['visual_yaw'] = {'fx_px', 'step', 'rows': [[t_gps, yaw_deg], …],
'gps_latency': {…}}` — une ligne par paire ANALYSÉE (les paires à l'arrêt valent 0 par construction
et ne sont pas écrites). `yaw_cumulative()` en fait la source `yaw_cum` du filtre ;
`measure_gps_latency()` en tire le retard du GPS sur la vidéo (⚑ gps_latency, 2026-10-13).
"""
import logging
from bisect import bisect_right

import numpy as np

logger = logging.getLogger(__name__)

#: Une image sur STEP (12 i/s → 6 i/s) : une rotation se mesure sans base, et 1/6 s entre deux
#: images garde le déplacement des points dans la fenêtre du suivi même en virage serré.
STEP = 2
#: Vitesse lissée sous laquelle la navette est ARRÊTÉE (même seuil que le filtre).
MIN_MOVE_MPS = 0.3
#: Au-delà de ce résidu médian, la paire ne décrit plus une rotation (objets mobiles, flou).
MAX_RESIDUAL_PX = 2.0


def compute_visual_yaw(session, position='front'):
    """Mesure la rotation vue sur toute la vidéo de `position`, aux instants où la navette roule.
    Rend `(data, report)` ; `data` est None si la mesure n'est pas possible (report['skipped'])."""
    import cv2
    from wama_data.functions.geometry.ego_rotation import estimate_ego_rotation
    from .camera_intrinsics import _pair_matches
    rs = session.results_summary or {}
    fx = ((rs.get('camera_intrinsics') or {}).get(position) or {}).get('fx_px')
    if not fx:
        return None, {'skipped': "focale non mesurée : lancer d'abord la passe « Champ des caméras »"}
    rows = [r for r in ((rs.get('shuttle_filter') or {}).get('track') or []) if r.get('ts') is not None]
    if not rows:
        return None, {'skipped': 'filtre navette absent (vitesse lissée inconnue)'}
    rows.sort(key=lambda r: r['ts'])
    ts = np.array([r['ts'] for r in rows], dtype=float)
    v = np.array([(r.get('speed_f_kmh') or 0.0) / 3.6 for r in rows], dtype=float)
    cam = session.cameras.filter(position=position).first()
    if cam is None or not getattr(cam, 'video_file', None):
        return None, {'skipped': 'pas de vidéo'}
    cap = cv2.VideoCapture(cam.video_file.path)
    if not cap.isOpened():
        return None, {'skipped': 'vidéo illisible'}
    fps = cam.fps or 12.0
    # synchro SANS la latence du GPS (⚑ gps_latency) : ces lignes servent à la MESURER
    scale = float(session.gps_time_scale or 1.0) or 1.0
    off = float(session.gps_time_offset or 0.0)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out, lost, analysed, fn, prev = [], 0, 0, -1, None
    while True:
        ok = cap.grab()
        if not ok:
            break
        fn += 1
        if fn % STEP:
            continue
        tg = fn / fps * scale + off
        moving = float(np.interp(tg, ts, v)) >= MIN_MOVE_MPS
        if not moving:
            prev = None                       # à l'arrêt : rien à mesurer, la chaîne repart après
            continue
        ok, im = cap.retrieve()
        if not ok:
            prev = None
            continue
        cur = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        if prev is not None:
            analysed += 1
            r = estimate_ego_rotation(_pair_matches(prev, cur), fx, (W / 2.0, H / 2.0))
            if r is None or r['residual_px'] > MAX_RESIDUAL_PX:
                lost += 1
            else:
                out.append([round(tg, 3), round(r['yaw_deg'], 4)])
        prev = cur
    cap.release()
    report = {'position': position, 'fx_px': fx, 'step': STEP, 'pairs': analysed, 'lost': lost,
              'lost_share': round(lost / analysed, 3) if analysed else None,
              'rotation_total_abs_deg': round(sum(abs(r[1]) for r in out), 1)}
    if not out:
        report['skipped'] = 'aucune paire exploitable'
        return None, report
    return {'fx_px': fx, 'step': STEP, 'position': position, 'rows': out}, report


#: Retard du GPS au-delà duquel la mesure est rejetée plutôt qu'appliquée (s).
MAX_GPS_LATENCY_S = 2.0
#: Corrélation minimale au retard retenu pour juger la mesure applicable.
MIN_LATENCY_R = 0.5
#: Seuls les virages renseignent sur un cap : vitesse de lacet GPS minimale (°/s) et vitesse (m/s).
TURN_RATE_DEG_S = 2.0
MOVING_MPS = 1.0


def measure_gps_latency(session, data=None):
    """Retard du GPS sur la VIDÉO (s), mesuré par la rotation : vitesse de lacet VUE par la caméra
    avant (lignes de cette passe) contre vitesse de lacet du cap GPS (fixes, différence centrée), en
    virage. > 0 : le GPS décrit l'instant que la vidéo montrait `latency_s` plus tôt — la navette est
    dessinée en ARRIÈRE de sa position, de vitesse × retard.

    Mesuré le 2026-10-13 sur ENA_CASA : +0,55 s par cette méthode (stable du seuil de virage 0 à
    4 °/s), +0,35 à +0,45 s par l'accéléromètre du .rec (latérale : GPS +0,10 s, vidéo −0,25 s, avant
    reprise du milieu de paire) et +0,30 s par la dérivée de la vitesse Doppler — trois références,
    même sens. Les lignes sont horodatées à la FIN de leur paire d'images : le milieu est repris ici.
    Rend {'latency_s', 'r', 'r_at_zero', 'samples', 'method', 'applicable'} ou None."""
    import math
    from wama_data.functions.kinematics.signal_lag import estimate_lag
    from .ego_pose import gps_fixes
    data = data if data is not None else ((session.results_summary or {}).get('visual_yaw') or {})
    rows = data.get('rows') or []
    fixes = [p for p in gps_fixes(session) if p.get('ts') is not None and p.get('lat') is not None]
    if len(rows) < 100 or len(fixes) < 100:
        return None
    cam = session.cameras.filter(position=data.get('position') or 'front').first()
    fps = (getattr(cam, 'fps', None) or 12.0)
    scale = float(session.gps_time_scale or 1.0) or 1.0
    step_s = (data.get('step') or STEP) / fps * scale
    vt = np.array([r[0] for r in rows], float) - step_s / 2.0
    vrate = np.array([r[1] for r in rows], float) / step_s

    t = np.array([p['ts'] for p in fixes], float)
    lat0 = math.radians(fixes[0]['lat'])
    x = np.array([p['lon'] for p in fixes], float) * 111320.0 * math.cos(lat0)
    y = np.array([p['lat'] for p in fixes], float) * 111320.0
    hd = np.degrees(np.unwrap(np.arctan2(x[2:] - x[:-2], y[2:] - y[:-2])))
    tc = t[1:-1]
    gspeed = np.hypot(x[2:] - x[:-2], y[2:] - y[:-2]) / np.maximum(t[2:] - t[:-2], 1e-6)
    grate = np.gradient(hd, tc)

    # même bande passante des deux côtés : le GPS est à ~1 Hz, la rotation vue est lissée sur 1 s
    grid = np.arange(max(vt[0], tc[0]), min(vt[-1], tc[-1]), 0.05)
    if len(grid) < 400:
        return None
    k = 20
    kern = np.ones(k) / k
    # lacet × vitesse (une accélération latérale) : l'erreur de POSITION d'un retard vaut vitesse ×
    # retard, la mesure doit peser les virages comme la position les subit. Sans cette pondération, les
    # virages lents (où le cap GPS est le plus traînant) tirent la mesure vers 0,75 s sur ENA_CASA.
    v = np.interp(grid, tc, gspeed)
    rate_gps = np.convolve(np.interp(grid, tc, grate), kern, mode='same')
    vis = np.convolve(np.interp(grid, vt, vrate), kern, mode='same') * v
    gps = rate_gps * v

    def turning(g):
        return (np.abs(np.interp(g, grid, rate_gps)) > TURN_RATE_DEG_S) & (np.interp(g, grid, v) > MOVING_MPS)

    res = estimate_lag(grid, vis, grid, gps, mask=turning)
    if res is None:
        return None
    applicable = abs(res['lag_s']) <= MAX_GPS_LATENCY_S and res['r'] >= MIN_LATENCY_R
    return {'latency_s': res['lag_s'], 'r': res['r'], 'r_at_zero': res['r_at_zero'],
            'samples': res['samples'], 'method': 'lacet × vitesse, vu contre GPS (virages)',
            'applicable': bool(applicable)}


def yaw_cumulative(session):
    """`callable(t_gps) -> deg` : rotation vue CUMULÉE (source `yaw_cum` du filtre navette), ou None.

    Les lignes sont horodatées par la synchro vidéo SANS la latence du GPS (c'est elle qu'elles
    mesurent) : sous ⚑ gps_latency, elles sont décalées de cette latence pour rejoindre le temps de
    la trace."""
    data = (session.results_summary or {}).get('visual_yaw') or {}
    rows = data.get('rows') or []
    if not rows:
        return None
    from .prediction_adapter import gps_latency_s
    lat = gps_latency_s(session)
    t = [r[0] + lat for r in rows]
    cum = list(np.cumsum([r[1] for r in rows]))

    def at(tg):
        k = bisect_right(t, tg)
        return float(cum[k - 1]) if k else 0.0
    return at
