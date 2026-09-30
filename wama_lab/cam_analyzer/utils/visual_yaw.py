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

Stocké : `results_summary['visual_yaw'] = {'fx_px', 'step', 'rows': [[t_gps, yaw_deg], …]}` —
une ligne par paire ANALYSÉE (les paires à l'arrêt valent 0 par construction et ne sont pas
écrites). `yaw_cumulative()` en fait la source `yaw_cum` du filtre.
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


def yaw_cumulative(session):
    """`callable(t_gps) -> deg` : rotation vue CUMULÉE (source `yaw_cum` du filtre navette), ou None."""
    data = (session.results_summary or {}).get('visual_yaw') or {}
    rows = data.get('rows') or []
    if not rows:
        return None
    t = [r[0] for r in rows]
    cum = list(np.cumsum([r[1] for r in rows]))

    def at(tg):
        k = bisect_right(t, tg)
        return float(cum[k - 1]) if k else 0.0
    return at
