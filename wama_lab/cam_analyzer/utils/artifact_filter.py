"""
Détecteur d'ARTEFACTS collés à l'image (reflets de vitrage, salissures) — chantier 1
du plan anti-faux-positifs (discuté/validé 2026-07-19).

Principe CINÉMATIQUE (aucune analyse d'image) : un reflet sur le vitrage de la navette
est collé aux coordonnées IMAGE — sa bbox ne bouge quasiment pas pendant des secondes
ALORS QUE LA NAVETTE AVANCE. Aucun objet réel ne fait ça : un objet du monde défile
dans l'image quand l'observateur se déplace. Critère :

    track par-caméra dont le centre bbox dérive < `max_px_drift` (RMS) pendant
    ≥ `min_dur_s`, alors que la navette s'est déplacée ≥ `min_shuttle_move_m`
    sur l'intervalle → ARTEFACT.

Consommation : `annotate_global_tracks` marque `artifact: true` sur les détections de
ces tracks (jamais supprimées — bascule ⚑ `artifact_filter` pour les masquer à
l'affichage et les exclure du tracking). Statistique pure sur les détections
existantes → rétroactif sur toutes les sessions.
"""
import logging
import math

logger = logging.getLogger(__name__)


def _shuttle_positions(session):
    """[(t_vidéo, e, n)] depuis la piste GPS (conversion temps GPS → vidéo)."""
    gt = session.gps_track or []
    if len(gt) < 2:
        return []
    from .prediction_adapter import make_local_frame
    to_local = make_local_frame(gt)
    scale = float(session.gps_time_scale or 1.0) or 1.0
    off = float(session.gps_time_offset or 0.0)
    out = []
    for p in gt:
        try:
            e, n = to_local(p['lat'], p['lon'])
            out.append(((float(p['ts']) - off) / scale, e, n))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def is_giant_reflection(det, iw, ih, area_frac=0.5, max_conf=0.55):
    """Reflet « fantôme géant » (vitrage) : bbox couvrant > area_frac de l'image AVEC
    confiance < max_conf. Un vrai véhicule aussi gros serait détecté avec forte
    confiance. Complément géométrique du critère cinématique (bbox fixe) pour les
    reflets fragmentés qui bougent trop pour être « statiques en image »."""
    if det.get('type') in ('sam3_marking', 'road_mask'):
        return False
    conf = det.get('confidence')
    bb = det.get('bbox')
    if conf is None or conf >= max_conf or not (isinstance(bb, (list, tuple)) and len(bb) >= 4):
        return False
    if not iw or not ih:
        return False
    frac = ((bb[2] - bb[0]) * (bb[3] - bb[1])) / float(iw * ih)
    return frac > area_frac


def detect_static_artifacts(session, min_dur_s=10.0, max_px_drift=4.0,
                            min_shuttle_move_m=8.0, min_obs=20):
    """Retourne {(position, track_id), ...} des tracks par-caméra jugés artefacts."""
    from ..models import DetectionFrame
    sh = _shuttle_positions(session)
    if not sh:
        return set()
    sh_t = [p[0] for p in sh]
    import bisect

    def _shuttle_at(t):
        i = min(max(bisect.bisect_left(sh_t, t), 1), len(sh) - 1)
        return sh[i][1], sh[i][2]

    artifacts = set()
    stats = []
    for cam in session.cameras.all():
        obs = {}   # tid -> [(t, bcx, bcy)]
        qs = (DetectionFrame.objects.filter(camera=cam)
              .order_by('frame_number').only('detections', 'timestamp'))
        for df in qs.iterator(chunk_size=1000):
            for d in (df.detections or []):
                tid = d.get('track_id')
                bb = d.get('bbox')
                if tid is None or not (isinstance(bb, (list, tuple)) and len(bb) >= 4):
                    continue
                obs.setdefault(tid, []).append(
                    (df.timestamp, (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0))
        for tid, pts in obs.items():
            if len(pts) < min_obs:
                continue
            t0, t1 = pts[0][0], pts[-1][0]
            if (t1 - t0) < min_dur_s:
                continue
            mx = sum(p[1] for p in pts) / len(pts)
            my = sum(p[2] for p in pts) / len(pts)
            rms = math.sqrt(sum((p[1] - mx) ** 2 + (p[2] - my) ** 2 for p in pts) / len(pts))
            if rms > max_px_drift:
                continue
            e0, n0 = _shuttle_at(t0)
            e1, n1 = _shuttle_at(t1)
            if math.hypot(e1 - e0, n1 - n0) < min_shuttle_move_m:
                continue   # navette quasi immobile : un vrai objet statique est aussi figé
            artifacts.add((cam.position, tid))
            stats.append((cam.position, tid, round(t0, 1), round(t1 - t0, 1), round(rms, 1)))
    if stats:
        logger.info("artefacts image-statiques : %d tracks — %s",
                    len(stats), stats[:10])
    return artifacts
