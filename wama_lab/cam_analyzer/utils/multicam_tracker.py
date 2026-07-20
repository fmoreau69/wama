"""
Tracker global multi-caméra (repère monde) pour cam_analyzer.

Associe les détections de TOUTES les caméras analysées (avant/arrière/gauche/droite) en
tracks GLOBAUX persistants : un objet garde un seul `global_track_id` en passant d'une
caméra à l'autre (hand-off) → plus de disparition/réapparition au bord du champ, et les
doublons (même objet vu par 2 caméras) partagent l'ID.

Post-traitement (pas de re-détection). Vérifie les caméras réellement analysées.
Association = plus-proche-voisin en repère monde avec gating + prédiction de position.
"""
import logging
import math
from collections import defaultdict

from django.apps import apps

logger = logging.getLogger(__name__)

from .artifact_filter import is_giant_reflection as _giant_reflection

from .prediction_adapter import (make_local_frame, shuttle_trajectory, pinhole_ego,
                               ego_to_world, _shuttle_pose_at, CLASS_DIMS,
                               camera_geometry, ground_projector_for, ground_ego)


def world_to_vehicle(world_e, world_n, shuttle_e, shuttle_n, heading_deg):
    """Position monde → repère véhicule (inverse d'ego_to_world) : (latéral, longitudinal)."""
    de, dn = world_e - shuttle_e, world_n - shuttle_n
    h = math.radians(heading_deg)
    s, c = math.sin(h), math.cos(h)
    lateral = de * c - dn * s
    longitudinal = de * s + dn * c
    return lateral, longitudinal

# Orientation de montage de chaque caméra (deg, sens horaire depuis l'avant véhicule).
CAMERA_YAW = {'front': 0.0, 'right': 75.0, 'rear': 180.0, 'left': -75.0}   # défauts rig ENA (±75° latérales)


def _ratio_heading_candidates(bb, iw, ih, cls, geo, fov_v_deg, sh_heading):
    """Cap MONDE (mod 180°) d'un véhicule depuis le ratio largeur/hauteur de sa bbox —
    portage serveur du calcul JS (étendue apparente E = L·|sinθ| + W·|cosθ|, indépendante
    de la distance car celle-ci vient de la hauteur bbox). Retourne les 2 candidats."""
    from .distance_speed import CLASS_REAL_HEIGHT_M
    dims = CLASS_DIMS.get(cls)
    H = CLASS_REAL_HEIGHT_M.get(cls)
    if not dims or not H:
        return []
    L, W = dims[0], dims[1]
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    if bh < 12 or bw < 4:
        return []
    fy = ih / (2.0 * math.tan(math.radians(fov_v_deg) / 2.0))
    fx = iw / (2.0 * math.tan(math.radians(geo['fov_h']) / 2.0))
    E = max(W, min(math.hypot(L, W), H * (fy / fx) * (bw / bh)))
    disc = max(0.0, L * L + W * W - E * E)
    sq = math.sqrt(disc)
    los = sh_heading + geo['yaw'] + math.degrees(
        math.atan2((bb[0] + bb[2]) / 2.0 - iw / 2.0, fx))
    out = []
    for sg in (1.0, -1.0):
        s = (L * E + sg * W * sq) / (L * L + W * W)
        if -1e-9 <= s <= 1 + 1e-9:
            th = math.degrees(math.asin(min(1.0, max(0.0, s))))
            out.append((los + th) % 180.0)
            out.append((los - th) % 180.0)
    return out


def _axial_consensus(cands):
    """Axe dominant (deg, mod 180°) d'un nuage de candidats : pic d'histogramme 5°
    (lissé sur 3 bins, circulaire) puis moyenne AXIALE (angle doublé) à ±15° du pic.
    La vraie orientation est stable à travers les gisements ; le candidat fantôme du
    ratio bouge avec la ligne de visée → le pic isole la vérité."""
    if not cands:
        return None
    bins = [0] * 36
    for a in cands:
        bins[int(a % 180.0 // 5)] += 1
    best = max(range(36), key=lambda i: bins[(i - 1) % 36] + bins[i] + bins[(i + 1) % 36])
    center = best * 5 + 2.5
    sx = sy = 0.0
    for a in cands:
        dv = ((a - center) % 180.0 + 90.0) % 180.0 - 90.0
        if abs(dv) <= 15.0:
            r = math.radians((center + dv) * 2.0)
            sx += math.cos(r)
            sy += math.sin(r)
    if sx == 0 and sy == 0:
        return None
    return (math.degrees(math.atan2(sy, sx)) / 2.0) % 180.0


def _cam_to_vehicle(lateral, longitudinal, yaw_deg):
    """Position dans le repère caméra → repère VÉHICULE commun (via l'orientation caméra)."""
    t = math.radians(yaw_deg)
    s, c = math.sin(t), math.cos(t)
    return (longitudinal * s + lateral * c, longitudinal * c - lateral * s)


def annotate_global_tracks(session, fov_v_deg=60.0, gate_m=3.5, max_gap_s=2.5,
                           frame_range=None, spread_max_m=6.0):
    """
    Assigne un `global_track_id` à chaque détection (objets suivis) de toutes les caméras
    ANALYSÉES, associées en repère monde. Retourne le nombre de tracks globaux créés.
    """
    DF = apps.get_model('cam_analyzer', 'DetectionFrame')
    gt = session.gps_track or []
    if len(gt) < 5:
        return 0
    to_local = make_local_frame(gt)
    from .prediction_adapter import antenna_offset
    sh_traj = shuttle_trajectory(gt, to_local, antenna=antenna_offset(session))
    if len(sh_traj) < 5:
        return 0

    # ── Caméras réellement analysées (position connue + détections présentes) ──
    cams = []
    for c in session.cameras.all():
        if c.position in CAMERA_YAW and DF.objects.filter(camera=c).exists():
            cams.append(c)
    if not cams:
        return 0

    fps = cams[0].fps or 12.0
    scale = session.gps_time_scale or 1.0
    off = session.gps_time_offset or 0.0
    _geo = camera_geometry(session)  # yaw/FOV/montage réels par caméra (rig + session)
    from .features import effective as _features_effective
    _feat = _features_effective(session)
    # ── Artefacts collés à l'image (reflets de vitrage) — chantier 1, 2026-07-19 ──
    # Détectés par cinématique pure AVANT l'association : bbox quasi immobile pendant
    # que la navette avance = pas un objet du monde. Marqués (jamais supprimés) et
    # exclus du tracking quand la bascule ⚑ artifact_filter est active.
    _artifact_tids = set()
    if _feat.get('artifact_filter', True):
        try:
            from .artifact_filter import detect_static_artifacts
            _artifact_tids = detect_static_artifacts(session)
        except Exception:
            logger.warning('detect_static_artifacts failed (non-blocking)', exc_info=True)
    _head_obs = defaultdict(list)   # gid -> [(pos, t, bbox)] pour le cap serveur des ancrés
    _cam_dims = {c.position: (c.width or 384, c.height or 248) for c in cams}
    # ⚑ auto_ground_calib (étape 2a) : projecteurs sol par caméra depuis la calib
    # persistée (angle estimé). Vide si la bascule est OFF → placement pinhole inchangé.
    _gproj = {}
    if _feat.get('auto_ground_calib', False):
        for pos in _geo:
            gp = ground_projector_for(session, pos, _geo[pos])
            if gp is not None:
                _gproj[pos] = gp
        if _gproj:
            logger.info('auto_ground_calib actif : projection sol pour %s',
                        sorted(_gproj.keys()))

    per_cam = {}
    for c in cams:
        iw = getattr(c, 'width', None) or 384
        ih = getattr(c, 'height', None) or 248
        _q = DF.objects.filter(camera=c)
        if frame_range:
            _q = _q.filter(frame_number__gte=frame_range[0], frame_number__lte=frame_range[1])
        frames = {f.frame_number: f for f in _q.only('frame_number', 'detections')}
        per_cam[c.position] = (iw, ih, frames)

    all_fns = sorted({fn for (_, _, frames) in per_cam.values() for fn in frames})
    tracks = []        # {id, e, n, ve, vn, last_t}
    track_hist = defaultdict(list)   # gid -> [(fn, t, world_e, world_n, class)]
    cls_votes = defaultdict(lambda: defaultdict(float))   # gid -> {classe: Σ confiance}
    chain = {}    # (pos, track_id) -> {'gid', 't'} : verrou de chaîne par caméra
    by_gid = {}   # gid -> track : accès direct pour le verrou de chaîne
    next_id = 1
    dirty = set()

    for fn in all_fns:
        t = fn / fps * scale + off
        se, sn, sh = _shuttle_pose_at(sh_traj, t)
        # Détections de cette frame (toutes caméras) en position monde.
        dets_here = []
        for pos, (iw, ih, frames) in per_cam.items():
            f = frames.get(fn)
            if not f:
                continue
            for d in (f.detections or []):
                if d.get('class_name') not in CLASS_DIMS:
                    continue
                # Accepte les détections suivies (track_id) ET les objets SEGMENTÉS sans
                # track_id (le tracker global les suit par position monde). Exclut les
                # fantômes (predicted) qui n'ont ni track_id ni source segmentation.
                if d.get('track_id') is None and d.get('source') != 'segmentation':
                    continue
                if ((pos, d.get('track_id')) in _artifact_tids
                        or (_feat.get('artifact_filter', True)
                            and _giant_reflection(d, iw, ih))):
                    d['artifact'] = True   # marqué, jamais supprimé (bascule ⚑ à l'affichage)
                    dirty.add(f)
                    continue               # exclu de l'association (pas un objet du monde)
                _g = _geo[pos]
                ego = None
                if _gproj.get(pos) is not None:
                    # ⚑ auto_ground_calib : projection SOL du bas de bbox (angle estimé)
                    # avec fallback pinhole si hors de portée utile — jamais de trou.
                    ego = ground_ego(_gproj[pos], d.get('bbox'))
                if ego is None:
                    ego = pinhole_ego(d, iw, ih, fov_v_deg,
                                      fov_h_deg=_g['fov_h'], dist_scale=_g['dist_scale'])
                relaxed = False
                if ego is None:
                    # Mesure DÉGRADÉE (bbox coupée au bord) : autorisée UNIQUEMENT pour
                    # PROLONGER une chaîne déjà appariée — jamais pour créer un track.
                    # Cas dépassement (audit 2026-07-17, G432) : le véhicule qui longe la
                    # navette est coupé au bord sur ~100 % des frames de la caméra
                    # latérale → il disparaissait du tracker pendant toute la phase de
                    # dépassement et ressortait avec un nouveau gid. Le latéral est
                    # biaisé (centre bbox tronqué) mais borné — suffisant pour maintenir
                    # la continuité.
                    tid = d.get('track_id')
                    dm = d.get('distance_m')
                    bb = d.get('bbox')
                    if (tid is None or dm is None
                            or not (isinstance(bb, (list, tuple)) and len(bb) >= 4)):
                        continue
                    dm = dm * _g['dist_scale']
                    fx = iw / (2.0 * math.tan(math.radians(_g['fov_h']) / 2.0))
                    ego = (dm * ((bb[0] + bb[2]) / 2.0 - iw / 2.0) / fx, dm)
                    relaxed = True
                xv, yv = _cam_to_vehicle(ego[0], ego[1], _g['yaw'])
                xv, yv = xv + _g['mount'][0], yv + _g['mount'][1]
                e, n = ego_to_world(se, sn, sh, xv, yv)
                dets_here.append((f, d, e, n, pos, relaxed))

        # Association plus-proche-voisin (gating + prédiction). On autorise plusieurs
        # détections → même track (fusion des doublons vus par 2 caméras).
        # Gate CROISSANT avec le trou (2026-07-17) : à la COUTURE inter-caméras, le
        # véhicule est coupé au bord (exclu par le garde-fou pinhole) pendant ~1-2 s →
        # le gate fixe + gap 1 s cassait la continuité (perte du G entre avant et
        # latérale, constat #537/G313). On tolère un trou plus long, avec une exigence
        # de proximité qui se relâche avec l'incertitude (~1,5 m/s de dérive).
        for f, d, e, n, pos, relaxed in dets_here:
            _tid = d.get('track_id')
            ck = (pos, _tid) if _tid is not None else None
            best = None
            # ── VERROU DE CHAÎNE ── : un track YOLO par caméra est une chaîne
            # temporellement cohérente — une fois appariée à un gid, elle le GARDE.
            # L'association frame par frame faisait churner le gid sur un même track
            # (track avant #166 = 6 gids différents, audit dépassement 2026-07-17).
            # Le plus-proche-voisin ne sert plus qu'à apparier les chaînes NOUVELLES.
            if ck and ck in chain and (t - chain[ck]['t']) <= 4.0:
                best = by_gid.get(chain[ck]['gid'])
            if best is None:
                # NN — STRICT pour les mesures dégradées (ratio < 0.7, jamais de
                # création) : c'est le pont physique du dépassement — le véhicule qui
                # longe la navette est vu par la caméra latérale mais 100 % coupé au
                # bord ; il peut REJOINDRE un track existant, pas en fonder un.
                best_ratio = 0.7 if relaxed else 1.0
                for tr in tracks:
                    dt = t - tr['last_t']
                    if dt < 0 or dt > max_gap_s:
                        continue
                    pe = tr['e'] + tr['ve'] * dt
                    pn = tr['n'] + tr['vn'] * dt
                    ratio = math.hypot(e - pe, n - pn) / (gate_m + 1.5 * dt)
                    if ratio < best_ratio:
                        best, best_ratio = tr, ratio
                if best is None and relaxed:
                    continue   # dégradée sans correspondance → ignorée
            if best is None:
                best = {'id': next_id, 'e': e, 'n': n, 've': 0.0, 'vn': 0.0, 'last_t': t}
                tracks.append(best)
                by_gid[next_id] = best
                next_id += 1
            else:
                dt = t - best['last_t']
                if dt > 1e-3:
                    # Vitesse LISSÉE (EMA α=0.3) + rejet des mesures aberrantes. Le delta
                    # instantané brut ((e−e₀)/dt, dt≈1/12 s) transformait ~25 cm de bruit
                    # de position (pinhole ±20 % + cap ego GPS) en ~3 m/s de vitesse
                    # fantôme : le gate prédictif (e+ve·dt) partait n'importe où → hand-off
                    # cassé, et les véhicules garés « roulaient » à 1-3 km/h.
                    # Audit vue de dessus 2026-07-16.
                    rve = (e - best['e']) / dt
                    rvn = (n - best['n']) / dt
                    if math.hypot(rve, rvn) > 15.0:   # >54 km/h en urbain = jitter
                        rve = rvn = 0.0
                    best['ve'] = 0.7 * best['ve'] + 0.3 * rve
                    best['vn'] = 0.7 * best['vn'] + 0.3 * rvn
                    best['e'], best['n'], best['last_t'] = e, n, t
            d['global_track_id'] = best['id']
            if ck:
                chain[ck] = {'gid': best['id'], 't': t}   # verrou de chaîne (voir plus haut)
            _bb = d.get('bbox')
            if (not relaxed and isinstance(_bb, (list, tuple)) and len(_bb) >= 4
                    and _bb[0] > 8 and _bb[2] < _cam_dims.get(pos, (384, 248))[0] - 8):
                # Observation pour le CAP serveur des ancrés (bbox non coupée seulement —
                # une bbox tronquée fausse l'étendue apparente, donc le ratio).
                _head_obs[best['id']].append((pos, t, (float(_bb[0]), float(_bb[1]),
                                                       float(_bb[2]), float(_bb[3]))))
            track_hist[best['id']].append((fn, t, e, n, d.get('class_name', 'car')))
            # Vote de classe pondéré par la confiance : YOLO fait flapper car↔truck
            # d'une frame à l'autre sur le même véhicule → la classe STABLE d'un track
            # est la majorité pondérée sur toute sa durée (écrite en 2e passe).
            cls_votes[best['id']][d.get('class_name', 'car')] += float(d.get('confidence') or 0.5)
            dirty.add(f)

    # ── RECOLLEMENT DE TRACKLETS (stitching) ─────────────────────────────────────
    # Cas dépassement (audit 2026-07-17, G432) : le véhicule qui double traverse la
    # zone AVEUGLE arrière↔latérale (aucun recouvrement caméras) et ses détections
    # latérales sont coupées au bord → le tracklet arrière et le tracklet avant
    # restaient deux gids distincts. On recolle les tracklets dont la CINÉMATIQUE
    # s'aligne : B commence peu après la fin de A, à la position PRÉDITE par la
    # vitesse de fin de A (gate croissant avec le trou, comme l'association).
    # Grâce au verrou de chaîne, les tracklets sont propres → le recollement par
    # extrémités est fiable. Les tracks lents (< 1 m/s) ne pontent que 2 s max
    # (deux garés voisins ne doivent JAMAIS fusionner).
    stitch_gap_s = 6.0
    alias = {}

    def _root(g):
        while g in alias:
            g = alias[g]
        return g

    # État de FIN robuste par tracklet : ajustement linéaire (t → e, n) sur la queue
    # SAINE de l'historique — fenêtre 2,5 s finissant 0,5 s AVANT la vraie fin. Les
    # toutes dernières mesures d'un track qui sort du champ (bbox tronquée, portée
    # < 3 m) sont les plus corrompues : prédire depuis le dernier état brut faisait
    # systématiquement rater le pont du dépassement (constat G252→G256, données 4da52).
    _endfit = {}
    for gid, hist in track_hist.items():
        hs = sorted(hist, key=lambda h: h[1])
        te = hs[-1][1]
        win = [h for h in hs if te - 2.5 <= h[1] <= te - 0.5] or hs[-4:]
        tr = by_gid.get(gid)
        if len(win) >= 3:
            tm = sum(h[1] for h in win) / len(win)
            em = sum(h[2] for h in win) / len(win)
            nm = sum(h[3] for h in win) / len(win)
            den = sum((h[1] - tm) ** 2 for h in win)
            if den > 1e-6:
                ve = sum((h[1] - tm) * (h[2] - em) for h in win) / den
                vn = sum((h[1] - tm) * (h[3] - nm) for h in win) / den
                _endfit[gid] = (te, win[-1][1], win[-1][2], win[-1][3], ve, vn)
                continue
        if tr is not None:
            _endfit[gid] = (te, tr['last_t'], tr['e'], tr['n'], tr['ve'], tr['vn'])

    _starts = []
    for gid, hist in track_hist.items():
        hs = min(hist, key=lambda h: h[1])
        _starts.append((gid, hs[1], hs[2], hs[3]))
    _starts.sort(key=lambda s: s[1])
    for gid, t0, e0, n0 in _starts:
        best_g, best_ratio = None, 1.0
        for og, fit in _endfit.items():
            if _root(og) == _root(gid):
                continue
            te, tw, ew, nw, ve, vn = fit
            gap = t0 - te
            if gap <= 0 or gap > stitch_gap_s:
                continue
            sp = math.hypot(ve, vn)
            if sp < 1.0 and gap > 2.0:
                continue
            dtp = t0 - tw                     # horizon de prédiction depuis le point sain
            pe = ew + ve * dtp
            pn = nw + vn * dtp
            ratio = math.hypot(e0 - pe, n0 - pn) / (gate_m + 1.5 * gap)
            if ratio < best_ratio:
                best_g, best_ratio = og, ratio
        if best_g is not None:
            alias[_root(gid)] = _root(best_g)

    if alias:
        # Remap gid → racine PARTOUT : historiques, votes de classe, détections annotées
        # (les fantômes/stationnés/classe stable calculés ensuite héritent de la fusion).
        _mh = defaultdict(list)
        for gid, h in track_hist.items():
            _mh[_root(gid)].extend(h)
        track_hist = _mh
        _mv = defaultdict(lambda: defaultdict(float))
        for gid, votes in cls_votes.items():
            for c, w in votes.items():
                _mv[_root(gid)][c] += w
        cls_votes = _mv
        for f in dirty:
            for d in (f.detections or []):
                g = d.get('global_track_id')
                if g is not None and _root(g) != g:
                    d['global_track_id'] = _root(g)

    # ── Détection des véhicules STATIONNÉS (garés) ──────────────────────────────
    # Track à vitesse max ~nulle sur toute sa vie = garé, SAUF s'il passe près d'une
    # intersection (voiture arrêtée au carrefour = pertinente, on la garde).
    windows = session.intersection_windows or []
    win_local = []
    for w in windows:
        if w.get('lat') is not None and w.get('lon') is not None:
            we, wn = to_local(w['lat'], w['lon'])
            win_local.append((we, wn, w.get('radius_m', 30.0)))

    def _near_intersection(hs):
        for (_, _, e, n, _) in hs:
            for we, wn, wr in win_local:
                if math.hypot(e - we, n - wn) <= wr:
                    return True
        return False

    # Métrique robuste au bruit : ÉTALEMENT spatial de la position monde sur la vie du
    # track (un véhicule garé reste groupé ; un mobile s'étale le long de son trajet).
    # ⚠ Critère VITESSE-AWARE (2026-07-17) : l'étalement seul marquait « garés » des
    # véhicules ROULANTS trackés brièvement (10 km/h × 1,5 s = 4 m < 6 m). Un stationné
    # doit être vu ASSEZ LONGTEMPS (≥ 4 s) avec une vitesse moyenne quasi nulle
    # (étalement/durée < 0,7 m/s ≈ 2,5 km/h), en plus du plafond absolu d'étalement.
    stationary_gids = []
    for gid, hist in track_hist.items():
        hs = sorted(hist)
        dur = (hs[-1][1] - hs[0][1]) if len(hs) >= 2 else 0.0
        if len(hs) < 5 or dur < 4.0:
            continue
        e0, n0 = hs[0][2], hs[0][3]
        spread = max(math.hypot(e - e0, n - n0) for (_, _, e, n, _) in hs)
        if (spread < spread_max_m and (spread / dur) < 0.7
                and not _near_intersection(hs)):
            stationary_gids.append(gid)
    _stat_set = set(stationary_gids)

    # ── Ancres MONDE des stationnés ─────────────────────────────────────────────
    # Un stationné est STATIQUE par définition : sa position monde est unique. La
    # reconstruire PAR FRAME le faisait « bouger/tourner » hors de l'axe caméra
    # (erreur de focale × gisement : quand la navette passe devant, le gisement
    # balaie → la position reconstruite décrit un arc ; dans l'axe l'erreur
    # latérale est ~nulle — diagnostic utilisateur 2026-07-18). Ancre = MÉDIANE
    # de toutes les observations du track (robuste aux mesures aberrantes),
    # servie en lat/lon à l'affichage qui dessine le garé à position FIXE.
    lat0, lon0 = gt[0]['lat'], gt[0]['lon']
    _m_lat = 111320.0
    _m_lon = 111320.0 * math.cos(math.radians(lat0))
    # Phase 1 : position (médiane) + CAP SERVEUR (chantier 2, 2026-07-19) — consensus
    # axial du ratio-bbox sur TOUTES les observations du track (la navette balaie des
    # gisements variés en passant devant un garé : très informatif, et bien plus stable
    # que l'EMA par frame au rendu). Phase 2 : prior CLUSTER (chantier 3) — les garés
    # voisins (< 15 m) partagent souvent leur axe (rangée/épi) : mélange axial pondéré
    # (soi ×2, voisins ×1), débrayable (⚑ heading_cluster).
    _anchor_tmp = {}
    for gid in stationary_gids:
        hs = track_hist.get(gid) or []
        if not hs:
            continue
        es = sorted(h[2] for h in hs)
        ns = sorted(h[3] for h in hs)
        me, mn = es[len(es) // 2], ns[len(ns) // 2]
        cands = []
        _v = cls_votes.get(gid)
        _cls = max(_v, key=_v.get) if _v else 'car'
        for pos, tt, bb in (_head_obs.get(gid) or [])[:400]:
            iw_o, ih_o = _cam_dims.get(pos, (384, 248))
            _, _, shh = _shuttle_pose_at(sh_traj, tt)
            from .prediction_adapter import CAMERA_FOV_V as _FOVV_REAL
            cands.extend(_ratio_heading_candidates(
                bb, iw_o, ih_o, _cls, _geo[pos], _FOVV_REAL.get(pos, 61.0), shh))
        _anchor_tmp[gid] = (me, mn, _axial_consensus(cands))

    if _feat.get('heading_cluster', True):
        _blended = {}
        for gid, (me, mn, hd) in _anchor_tmp.items():
            neigh = [ohd for og, (oe, on, ohd) in _anchor_tmp.items()
                     if og != gid and ohd is not None
                     and math.hypot(oe - me, on - mn) <= 15.0]
            if hd is not None and len(neigh) >= 2:
                sx = 2.0 * math.cos(math.radians(hd * 2))
                sy = 2.0 * math.sin(math.radians(hd * 2))
                for oh in neigh:
                    sx += math.cos(math.radians(oh * 2))
                    sy += math.sin(math.radians(oh * 2))
                _blended[gid] = (math.degrees(math.atan2(sy, sx)) / 2.0) % 180.0
        for gid, hd in _blended.items():
            me, mn, _ = _anchor_tmp[gid]
            _anchor_tmp[gid] = (me, mn, hd)

    stationary_anchors = {}
    for gid, (me, mn, hd) in _anchor_tmp.items():
        stationary_anchors[gid] = [round(lat0 + mn / _m_lat, 7),
                                   round(lon0 + me / _m_lon, 7),
                                   round(hd, 1) if hd is not None else None]

    # ── Comblement des trous de détection au hand-off (empreintes prédites) ──────
    # Pour chaque track, on interpole en repère MONDE entre avant/après le trou, puis on
    # convertit en repère véhicule et on insère une détection "fantôme" (predicted) dans
    # la frame front manquante. Bornes : trou ≤ max_gap_frames.
    front_frames = per_cam.get('front', (None, None, {}))[2]
    max_gap_frames = int(6.0 * fps)   # aligné stitching : INTERPOLATION entre 2 mesures réelles   # ~1,2 s max
    ghosts = 0
    if front_frames:
        # Retirer les anciens fantômes (idempotence si on recalcule).
        for fr in front_frames.values():
            if fr.detections and any(d.get('predicted') for d in fr.detections):
                fr.detections = [d for d in fr.detections if not d.get('predicted')]
                dirty.add(fr)
        for gid, hist in track_hist.items():
            if gid in _stat_set:
                continue   # trajectoire d'un STATIONNÉ = rien à reconstituer
            hist.sort()
            # positions monde uniques par frame (moyenne si doublons)
            byfn = {}
            for fn, t, e, n, cls in hist:
                pe, pn, k = byfn.get(fn, (0.0, 0.0, 0))
                byfn[fn] = (pe + e, pn + n, k + 1)
            fns_h = sorted(byfn)
            # Classe MAJORITAIRE du track (pondérée confiance), pas celle de la 1re frame
            # — un fantôme doit hériter de la classe stable (gabarit cohérent).
            _v = cls_votes.get(gid)
            cls = max(_v, key=_v.get) if _v else hist[0][4]
            for i in range(1, len(fns_h)):
                f0, f1 = fns_h[i - 1], fns_h[i]
                gap = f1 - f0
                if gap <= 1 or gap - 1 > max_gap_frames:
                    continue
                e0, n0 = byfn[f0][0] / byfn[f0][2], byfn[f0][1] / byfn[f0][2]
                e1, n1 = byfn[f1][0] / byfn[f1][2], byfn[f1][1] / byfn[f1][2]
                for fn in range(f0 + 1, f1):
                    fr = front_frames.get(fn)
                    if not fr:
                        continue
                    a = (fn - f0) / gap
                    we, wn = e0 + a * (e1 - e0), n0 + a * (n1 - n0)   # interpolation monde
                    t = fn / fps * scale + off
                    se, sn, sh = _shuttle_pose_at(sh_traj, t)
                    lat, lon = world_to_vehicle(we, wn, se, sn, sh)
                    # lon <= 0 accepté (2026-07-17) : la trajectoire doit être
                    # reconstituée AUSSI derrière/à côté de la navette (dépassement).
                    if fr.detections is None:
                        fr.detections = []
                    fr.detections.append({
                        'type': 'ghost', 'predicted': True, 'global_track_id': gid,
                        'class_name': cls, 'vehicle_xy': [round(lat, 3), round(lon, 3)],
                        # Position MONDE interpolée : même canal de consommation que les
                        # détections réelles lissées (world_en) — affichage uniforme.
                        'world_en': [round(we, 2), round(wn, 2)],
                        # Distance GÉOMÉTRIQUE dérivée de la position interpolée (repère
                        # véhicule, origine antenne) : donne au fantôme un tooltip chiffré
                        # et une couleur par distance (au lieu du cyan « aucune mesure »).
                        'dist_euclid_m': round(math.hypot(lat, lon), 1),
                    })
                    dirty.add(fr)
                    ghosts += 1

    # ── Trajectoires LISSÉES des mobiles (Kalman + RTS, 2026-07-19) ─────────────────
    # Agrège TOUTES les observations monde d'un même gid (toutes caméras, toute la
    # manœuvre) et les lisse par Kalman avant + RTS arrière — le lissage utilise le
    # futur ET le passé de chaque point (pas de retard de phase). La position lissée
    # est écrite sur chaque détection (`world_en`, repère monde) : l'affichage la
    # CONSOMME au lieu de re-reconstruire par frame/caméra — plus de sauts au
    # changement de caméra ni de disparitions dues aux gardes par-frame.
    # Stationnés exclus (les ancres font mieux).
    from .trajectory_smoother import smooth_track
    smoothed = {}   # (gid, fn) -> (e, n)
    for gid, hist in track_hist.items():
        if gid in _stat_set or len(hist) < 5:
            continue
        try:
            out = smooth_track([(t, e, n) for (_fn, t, e, n, _c) in hist])
        except Exception:
            logger.debug('smooth_track failed gid=%s', gid, exc_info=True)
            continue
        by_t = {round(t, 4): (e, n) for t, e, n, _vx, _vy in out}
        for fn, t, _e, _n, _c in hist:
            v = by_t.get(round(t, 4))
            if v:
                smoothed[(gid, fn)] = v

    # ── Classe STABLE par track (vote majoritaire pondéré confiance) ────────────────
    # YOLO fait flapper la classe (car↔truck) d'une frame à l'autre sur le même
    # véhicule → gabarit vue de dessus qui saute. La classe d'un TRACK est la majorité
    # pondérée sur toute sa durée, écrite sur chaque détection (`stable_class`) —
    # l'affichage la préfère à la classe brute de la frame.
    stable_cls = {gid: max(v, key=v.get) for gid, v in cls_votes.items() if v}
    for f in dirty:
        for d in (f.detections or []):
            g = d.get('global_track_id')
            sc = stable_cls.get(g)
            if sc:
                d['stable_class'] = sc
            w = smoothed.get((g, f.frame_number)) if g is not None else None
            if w:
                d['world_en'] = [round(w[0], 2), round(w[1], 2)]

    for f in dirty:
        f.save(update_fields=['detections'])
    return {'tracks': next_id - 1, 'stationary_gids': stationary_gids,
            'stationary_anchors': stationary_anchors}
