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

#: ⚑ parked_off_road — marge de doute autour du bord de chaussée IGN (m) : une médiane plus proche
#: du bord que cela n'est ni « sur la voie » ni « garée » (placement latéral ± 0,8 m, mesuré par
#: rangée le 2026-09-30). Dans le doute, pas garé : on ne fige jamais un véhicule qui peut partir.
OFF_ROAD_MARGIN_M = 0.5
#: Familles qui peuvent être GARÉES (jamais un piéton immobile sur un trottoir).
PARKABLE_FAMILIES = ('four_wheel', 'two_wheel')
#: Garde contre les MOBILES placés hors des voies par une erreur latérale : déplacement net /
#: longueur du chemin (`net_sur_chemin`, sans dimension, bimodal — mode ≈ 0,95 pour ce qui roule).
#: Mesuré le 2026-09-30 : retenus hors voies p50 0,17 mais p95 0,86 ; les vus < 4 s (signature des
#: mobiles) p50 0,81. Ce n'est PAS le critère réfuté au §D.3 bis (séparer étalés et retenus) :
#: seulement l'élimination des tracks qui AVANCENT franchement.
MAX_NET_OVER_PATH = 0.8
#: ⚑ parked_motion_guard — déplacement ROBUSTE (médiane du 1er tiers → médiane du dernier tiers du
#: track) au-delà duquel un « hors voies » n'est pas garé : il faut LES DEUX (≥ 5 m et ≥ 0,5 m/s).
#: Mesuré le 2026-10-01 sur 1547 « hors voies » : p50 6,7 m, p75 16,4 m, p90 36 m — dont G2759,
#: traversant l'intersection (25,6 m, 4,9 m/s), figé en garé. Seuil NON validé (aucune vérité
#: terrain ; un critère « revu à un autre tour » s'est révélé non discriminant, 90 % partout).
PARKED_MOVE_M = 5.0
PARKED_MOVE_MPS = 0.5

from .artifact_filter import is_giant_reflection as _giant_reflection

from .prediction_adapter import (make_local_frame, shuttle_trajectory, pinhole_ego,
                               ego_to_world, _shuttle_pose_at, CLASS_DIMS,
                               camera_geometry, ground_projector_for, ground_ego,
                               undistorted_x)


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


def off_road_gate(hs, votes, footprint, edge, margin_m=OFF_ROAD_MARGIN_M):
    """Porte de sortie d'un track sous ⚑ parked_off_road : 'pas_un_vehicule', 'sur_voie',
    'bord_de_voie' ou 'retenu'. Médiane (composante par composante, comme les ancres) des positions
    `hs` = [(fn, t, e, n, classe)] confrontée à l'emprise de chaussée `footprint` (même repère) :
    dedans à plus de `margin_m` du bord → sur la voie (arrêté ou roulant, JAMAIS garé) ; dehors à
    plus de `margin_m` → garé ; entre les deux → doute, pas garé."""
    from shapely.geometry import Point
    if dominant_family(votes) not in PARKABLE_FAMILIES:
        return 'pas_un_vehicule'
    es = sorted(h[2] for h in hs)
    ns = sorted(h[3] for h in hs)
    pt = Point(es[len(es) // 2], ns[len(ns) // 2])
    signed = (-1.0 if footprint.contains(pt) else 1.0) * edge.distance(pt)   # > 0 : hors chaussée
    if signed <= -margin_m:
        return 'sur_voie'
    if signed < margin_m:
        return 'bord_de_voie'
    return 'retenu'


def robust_displacement(hs):
    """(distance m, vitesse m/s) entre la position MÉDIANE du premier tiers et celle du dernier
    tiers d'un track `[(fn, t, e, n, classe)]` trié — le bruit de placement s'y moyenne, un vrai
    déplacement reste. Le rapport net/chemin (`MAX_NET_OVER_PATH`) ne le voit pas : le bruit
    allonge le chemin (G2759 : 25,6 m parcourus, net/chemin 0,27)."""
    n = len(hs)
    if n < 3:
        return 0.0, 0.0
    k = max(n // 3, 1)

    def med(part, i):
        v = sorted(h[i] for h in part)
        return v[len(v) // 2]
    a, b = hs[:k], hs[-k:]
    dist = math.hypot(med(b, 2) - med(a, 2), med(b, 3) - med(a, 3))
    dt = med(b, 1) - med(a, 1)
    return dist, (dist / dt if dt > 1e-6 else 0.0)


def track_descriptors(hs):
    """`[(fn, t, e, n, classe)]` TRIÉ → descripteurs d'un track global, pour la
    qualification « garé ».

    Quatre grandeurs, dont **trois ne servent pas encore au filtre** : elles sont mesurées
    pour le chantier de refonte (§D.3 — verdict Fabien 2026-09-09 : « un garé se remarque
    uniquement sur un ENSEMBLE d'images successives »), où la question est de savoir laquelle
    sépare un garé d'un mobile lent **sans exiger une précision de placement que la chaîne
    ne fournit pas** (pinhole ±20 %, soit plusieurs mètres à 20 m).

    - `spread_first` — distance max à la PREMIÈRE observation. ⚠ C'est ce que le filtre
      utilise depuis le 2026-07-17, et une première position bruitée fixe tout le verdict.
    - `spread_robuste` — **p90** des distances à la position MÉDIANE. ⚠ La 1ʳᵉ version prenait
      le MAX des distances à la médiane : un test l'a réfutée en naissant (une observation
      aberrante rendait `spread_first` = `spread_robuste` = 11,8 m). *La fragilité n'était pas
      dans le point de RÉFÉRENCE mais dans l'AGRÉGATEUR* — changer l'origine sans changer le
      max ne robustifie rien. C'est le quantile qui écarte l'aberration, pas la médiane.
    - `pas_median` — médiane de |Δposition| / Δt entre observations CONSÉCUTIVES : un garé
      jitte, un mobile avance régulièrement.
    - `net_sur_chemin` — |dernière − première| / longueur totale du chemin. **Sans dimension** :
      un garé jitte sur place (net ≈ 0, chemin long), un mobile avance (net ≈ chemin), et le
      rapport ne dépend PAS de l'échelle du bruit de placement — c'est ce qui en fait la
      candidate la plus directement opposée au verrou mesuré.
    """
    n = len(hs)
    out = {'n_obs': n, 'duree': (hs[-1][1] - hs[0][1]) if n >= 2 else 0.0,
           'spread_first': 0.0, 'spread_robuste': 0.0,
           'pas_median': 0.0, 'net_sur_chemin': 0.0}
    if n < 2:
        return out
    es = [h[2] for h in hs]
    ns = [h[3] for h in hs]
    e0, n0 = es[0], ns[0]
    out['spread_first'] = max(math.hypot(e - e0, n - n0) for e, n in zip(es, ns))
    em = sorted(es)[n // 2]
    nm = sorted(ns)[n // 2]
    dm = sorted(math.hypot(e - em, n - nm) for e, n in zip(es, ns))
    out['spread_robuste'] = dm[min(int(0.9 * (n - 1)), n - 1)]

    pas, chemin = [], 0.0
    for i in range(1, n):
        d = math.hypot(es[i] - es[i - 1], ns[i] - ns[i - 1])
        chemin += d
        dt = hs[i][1] - hs[i - 1][1]
        if dt > 1e-6:
            pas.append(d / dt)
    if pas:
        pas.sort()
        out['pas_median'] = pas[len(pas) // 2]
    net = math.hypot(es[-1] - e0, ns[-1] - n0)
    out['net_sur_chemin'] = (net / chemin) if chemin > 1e-6 else 0.0
    return out


def _quantiles(valeurs, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    """Quantiles d'une liste — l'agrégat qui tient dans `results_summary` (5210 tracks n'y
    tiennent pas, et une moyenne ne dirait pas si la distribution est BIMODALE)."""
    if not valeurs:
        return {}
    v = sorted(valeurs)
    return {f'p{int(q * 100)}': round(v[min(int(q * (len(v) - 1)), len(v) - 1)], 4)
            for q in qs}


def _histogramme(valeurs, vmax, nb=20):
    """Comptes par classe sur [0, vmax], dernière classe = débordement.

    ⚠ Des quantiles ne disent PAS si une distribution est bimodale — or c'est exactement la
    question posée aux grandeurs candidates (§D.3) : une bonne discriminante sépare la
    population en deux modes, une mauvaise rend un continuum. 20 entiers y répondent et
    tiennent dans `results_summary`.
    """
    h = [0] * nb
    if not valeurs or vmax <= 0:
        return h
    for v in valeurs:
        k = int(v / vmax * (nb - 1))
        h[min(max(k, 0), nb - 1)] += 1
    return h


#: Bornes d'histogramme par descripteur (la dernière classe absorbe au-delà).
_BORNES_HISTO = {'duree': 60.0, 'spread_first': 20.0, 'spread_robuste': 20.0,
                 'pas_median': 5.0, 'net_sur_chemin': 1.0}


#: Familles de classe : YOLO fait alterner car↔truck (même gabarit, même FAMILLE) mais un
#: deux-roues n'est jamais un quatre-roues — les relier est une association fausse (mesuré le
#: 2026-09-29 : motos vues à droite fondues dans une voiture vue à l'avant, gid 743/739).
CLASS_FAMILY = {'motorcycle': 'two_wheel', 'bicycle': 'two_wheel',
                'car': 'four_wheel', 'truck': 'four_wheel', 'bus': 'four_wheel',
                'person': 'person'}


def box_iou(a, b):
    """IoU de deux boîtes [x0, y0, x1, y1] (0 si l'une manque)."""
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


#: Au-delà de ce recouvrement, deux boîtes d'une même image sont UN objet détecté deux fois
#: (YOLO produit « truck » et « car » de même contour) : elles peuvent partager un gid.
DUPLICATE_BOX_IOU = 0.3


def claims_distinct_box(claimed_boxes, bbox):
    """⚑ same_camera_exclusion : ce gid porte-t-il déjà, dans cette image et cette caméra, une
    boîte d'un AUTRE objet (recouvrement < `DUPLICATE_BOX_IOU`) ? Deux boîtes distinctes d'une
    même image sont deux objets ; un doublon de détection, lui, reste le même objet."""
    return any(box_iou(b, bbox) < DUPLICATE_BOX_IOU for b in (claimed_boxes or []))


def dominant_family(votes, min_weight=2.0, min_share=0.7):
    """Famille DOMINANTE d'un track d'après ses votes de classe pondérés, ou None tant qu'elle
    n'est pas établie (poids total < `min_weight` ou part < `min_share`) — une image isolée mal
    classée ne suffit jamais à fermer une association."""
    by_family = defaultdict(float)
    for cls, w in (votes or {}).items():
        fam = CLASS_FAMILY.get(cls)
        if fam:
            by_family[fam] += w
    total = sum(by_family.values())
    if total < min_weight:
        return None
    fam, w = max(by_family.items(), key=lambda kv: kv[1])
    return fam if w / total >= min_share else None


def families_conflict(fam_a, fam_b):
    """Deux familles établies et différentes : l'association est refusée."""
    return fam_a is not None and fam_b is not None and fam_a != fam_b


def _mixed_family_gids(cls_votes, min_weight=3.0, minority_share=0.2):
    """Métrique A/B de ⚑ class_family_gate : nombre de tracks dont une AUTRE famille pèse plus
    de `minority_share` des votes (deux-roues et quatre-roues fondus dans un même gid)."""
    n = 0
    for votes in cls_votes.values():
        by_family = defaultdict(float)
        for cls, w in votes.items():
            if CLASS_FAMILY.get(cls):
                by_family[CLASS_FAMILY[cls]] += w
        total = sum(by_family.values())
        if total >= min_weight and len(by_family) > 1 and \
                sorted(by_family.values())[-2] / total > minority_share:
            n += 1
    return n


def reanchor_ghosts(ghost_links, smoothed, shuttle_at, *, use_smoothed=True, ego_length_m=4.75,
                  ego_width_m=2.11):
    """Repose les fantômes sur la trajectoire LISSÉE et retire ceux tombés dans l'emprise navette.

    `ghost_links` : [(frame, détection fantôme, gid, f0, f1, a, fn)] — le fantôme de l'image `fn`
    est à la fraction `a` du trou entre les observations réelles `f0` et `f1` ; `smoothed` :
    {(gid, fn): (e, n)} des observations RÉELLES lissées ; `shuttle_at(fn)` → (e, n, cap) de la
    navette (centre arrière). Modifie les détections en place ; rend (sauts au bord du trou en m,
    nombre retirés). Sans les deux points lissés, le fantôme garde l'interpolation brute."""
    jumps, removed = [], 0
    for fr, det, gid, f0, f1, a, fn in ghost_links:
        s0, s1 = smoothed.get((gid, f0)), smoothed.get((gid, f1))
        lat, lon = det['vehicle_xy']
        if use_smoothed and s0 and s1:
            we, wn = s0[0] + a * (s1[0] - s0[0]), s0[1] + a * (s1[1] - s0[1])
            se, sn, sh = shuttle_at(fn)
            lat, lon = world_to_vehicle(we, wn, se, sn, sh)
            det['world_en'] = [round(we, 2), round(wn, 2)]
            det['vehicle_xy'] = [round(lat, 3), round(lon, 3)]
            det['dist_euclid_m'] = round(math.hypot(lat, lon), 1)
        # saut d'affichage au bord du trou (métrique A/B de la bascule)
        for edge, sp in ((f0 + 1, s0), (f1 - 1, s1)):
            if fn == edge and sp:
                jumps.append(math.hypot(det['world_en'][0] - sp[0], det['world_en'][1] - sp[1]))
        # emprise : origine = centre arrière, la silhouette s'étend vers l'avant (cf. JS)
        if abs(lat) < ego_width_m / 2 + 0.2 and -0.5 < lon < ego_length_m - 0.1:
            fr.detections.remove(det)
            removed += 1
    return jumps, removed


#: Champs qu'ÉCRIT le tracking 360° sur une détection RÉELLE. Un calcul les réécrit tous : ce
#: qu'il ne réécrit pas ne doit pas lui survivre (`reset_tracker_fields`).
TRACKER_FIELDS = ('global_track_id', 'world_en', 'world_vel', 'stable_class', 'stable_class_margin',
                  'artifact', 'placement_source')


def reset_tracker_fields(detections, removed=None) -> int:
    """Retire des détections réelles les champs d'un calcul PRÉCÉDENT du tracking 360° ; rend le
    nombre de détections touchées. Les fantômes (`predicted`) ont leur propre purge.

    Mesuré le 2026-09-30 (session 4da52df3) : le tracker n'écrivait ces champs que là où il avait
    une valeur, sans jamais effacer l'ancienne. 293 153 détections de STATIONNÉS (99,8 %) gardaient
    un `world_en` d'un calcul antérieur — le lissage exclut les stationnés —, à 6 m en médiane de
    leur ancre fraîche (p90 27 m, max 838 m : un autre objet, les gids ayant été renumérotés), et
    17 737 détections marquées artefact portaient un `global_track_id` alors que le tracker les
    exclut de l'association : les Indicateurs, qui regroupent par gid, les fondaient dans le track
    de l'objet qui porte aujourd'hui ce numéro."""
    n = 0
    for d in detections or []:
        if d.get('predicted'):
            continue
        keys = [k for k in TRACKER_FIELDS if k in d]
        for k in keys:
            del d[k]
        if keys:
            n += 1
            if removed is not None:      # pour mesurer, en fin de calcul, ce qui n'est PAS réécrit
                removed.append((d, frozenset(keys)))
    return n


def stale_fields_report(removed) -> dict:
    """Ce que la purge a réellement retiré de PÉRIMÉ : les détections qui portaient un gid ou une
    position monde et que le calcul courant ne réécrit pas. Le nombre de détections purgées, lui,
    compte aussi celles réécrites à l'identique — il ne dit rien du périmé."""
    out = {'detections_reset': len(removed), 'dropped_gid': 0, 'dropped_world_en': 0}
    for d, keys in removed:
        if 'global_track_id' in keys and 'global_track_id' not in d:
            out['dropped_gid'] += 1
        if 'world_en' in keys and 'world_en' not in d:
            out['dropped_world_en'] += 1
    return out


def one_to_one_stitches(pairs, spans, overlap_tolerance_s=0.25):
    """Recollement UN POUR UN (⚑ stitch_one_to_one, 2026-10-03) : `pairs` = [(écart, début, fin)]
    candidats (début = tracklet qui commence, fin = tracklet qui finit avant lui, écart = distance
    normalisée à la position prédite), `spans` = {tracklet: (t_début, t_fin)}.

    Attribution au MEILLEUR AJUSTEMENT (couples triés par écart) : une fin ne se prolonge qu'une fois,
    un début ne prolonge qu'une fin, et jamais deux groupes dont des membres sont présents en même
    temps (au-delà de `overlap_tolerance_s`). Rend (liens [(début, fin)] acceptés dans l'ordre,
    nombre de refus pour présence simultanée)."""
    parent = {}

    def root(g):
        while g in parent:
            g = parent[g]
        return g
    members = {g: [s] for g, s in spans.items()}
    continued, stitched, links, refused = set(), set(), [], 0
    tol = overlap_tolerance_s
    for _ratio, start, end in sorted(pairs, key=lambda p: p[0]):
        if start in stitched or end in continued or root(start) == root(end):
            continue
        if any(a < d - tol and c + tol < b
               for a, b in members.get(root(end), ()) for c, d in members.get(root(start), ())):
            refused += 1
            continue
        members.setdefault(root(end), []).extend(members.pop(root(start), []))
        parent[root(start)] = root(end)
        continued.add(end)
        stitched.add(start)
        links.append((start, end))
    return links, refused


def annotate_global_tracks(session, fov_v_deg=60.0, gate_m=3.5, max_gap_s=2.5,
                           frame_range=None, spread_max_m=6.0, path_ratio_max=None):
    """
    Assigne un `global_track_id` à chaque détection (objets suivis) de toutes les caméras
    ANALYSÉES, associées en repère monde. Retourne le nombre de tracks globaux créés.
    """
    DF = apps.get_model('cam_analyzer', 'DetectionFrame')
    from .ego_pose import effective_gps_track   # ⚑ shuttle_filter : filtrée si ON, sinon brute
    gt = effective_gps_track(session)
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
    _family_gate = _feat.get('class_family_gate', True)
    _same_cam_excl = _feat.get('same_camera_exclusion', True)
    _center_place = _feat.get('vehicle_center_placement', False)
    _cut_inner = _feat.get('cut_box_inner_edge', False)
    from wama_data.functions.geometry.shapes import visible_face_to_center, cut_box_face_center

    def _vehicle_axis(det, pos, t, shuttle_heading):
        """Axe long d'un véhicule dans le repère NAVETTE (°, horaire) : la vitesse de son track s'il
        roule, sinon parallèle à la navette (garés le long de la voie)."""
        _lk = chain.get((pos, det.get('track_id'))) if det.get('track_id') is not None else None
        _tr = by_gid.get(_lk['gid']) if _lk and (t - _lk['t']) <= 4.0 else None
        if _tr is not None and math.hypot(_tr['ve'], _tr['vn']) > 1.5:
            return math.degrees(math.atan2(_tr['ve'], _tr['vn'])) - shuttle_heading
        return 0.0
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
    # ⚑ auto_ground_calib OU ⚑ depth_estimation (étape 2a / usage 4 §[E]) : projecteurs sol par
    # caméra depuis la calib persistée (angle estimé par homographie OU par profondeur). La calib
    # est produite en amont par store_ground_calib ; la SOURCE (homographie/profondeur) est
    # transparente ici — le tracker consomme le même champ. Vide si les deux bascules sont OFF
    # → placement pinhole inchangé.
    # SOURCE DE PLACEMENT par détection (gap G7 rendu VISIBLE, 2026-09-05) : le repli
    # `ground_ego → pinhole` était silencieux, donc un A/B ⚑ ON/OFF comparait du pinhole à un
    # MÉLANGE sol+pinhole sans le dire. Chaque détection reçoit `placement_source` ∈
    # {'ground:homographie', 'ground:depth', 'pinhole', 'pinhole_relaxed'} et les compteurs
    # remontent au rapport — un placement mixte se COMPTE au lieu de se supposer.
    _gc_src = {p: ((v or {}).get('source') or 'homographie')
               for p, v in (((session.config or {}).get('ground_calib')) or {}).items()
               if isinstance(v, dict)}
    _src_counts = defaultdict(int)
    _gproj = {}
    if _feat.get('auto_ground_calib', False) or _feat.get('depth_estimation', False):
        for pos in _geo:
            gp = ground_projector_for(session, pos, _geo[pos])
            if gp is not None:
                _gproj[pos] = gp
        if _gproj:
            logger.info('projection sol active (⚑ auto_ground_calib/depth_estimation) pour %s',
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
    # Un calcul part de ZÉRO : sans cette purge, tout ce qu'il ne réécrit pas (stationnés non
    # lissés, artefacts exclus, détections qui ne s'associent plus) gardait l'état d'un calcul
    # antérieur — autre pose navette, autres numéros de track.
    _reset = []
    for (_iw, _ih, frames) in per_cam.values():
        for f in frames.values():
            if reset_tracker_fields(f.detections, _reset):
                dirty.add(f)

    _continuity_obs = []   # (image, caméra, chaîne détecteur, gid, e, n) — métrique #3
    _chain_switch = defaultdict(int)
    _live_chain = {}   # (gid, caméra) -> (chaîne détecteur, dernier instant) — ⚑ birth_same_camera_guard
    _birth_guard = _feat.get('birth_same_camera_guard', True)
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
                _psrc = None
                if _gproj.get(pos) is not None:
                    # ⚑ auto_ground_calib : projection SOL du bas de bbox (angle estimé)
                    # avec fallback pinhole si hors de portée utile — jamais de trou.
                    ego = ground_ego(_gproj[pos], d.get('bbox'))
                    if ego is not None:
                        _psrc = 'ground:' + _gc_src.get(pos, 'homographie')
                if ego is None:
                    ego = pinhole_ego(d, iw, ih, fov_v_deg,
                                      fov_h_deg=_g['fov_h'], dist_scale=_g['dist_scale'], k1=_g['k1'])
                    if ego is not None:
                        _psrc = 'pinhole'
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
                    _ux = undistorted_x((bb[0] + bb[2]) / 2.0, bb[3], iw, ih, fx, _g['k1'])
                    ego = (dm * (_ux - iw / 2.0) / fx, dm)
                    # ⚑ cut_box_inner_edge (2026-10-03) : le centre d'une boîte coupée est celui de la
                    # partie VISIBLE. On part du bord INTÉRIEUR (non coupé) et on prolonge de la demi-
                    # étendue apparente du véhicule — passage de 519 s : la boîte coupée de l'avant
                    # plaçait la voiture à 8,7 m de la mesure de la latérale, qui la voyait entière.
                    _cut_l, _cut_r = bb[0] <= 8, bb[2] >= iw - 8
                    _dims = CLASS_DIMS.get(d.get('class_name'))
                    if _cut_inner and _dims and _cut_l != _cut_r:
                        _inner = bb[2] if _cut_l else bb[0]
                        _xi = undistorted_x(_inner, bb[3], iw, ih, fx, _g['k1'])
                        ego = cut_box_face_center(dm * (_xi - iw / 2.0) / fx, dm, -1 if _cut_l else 1,
                                                  _dims[0], _dims[1], _vehicle_axis(d, pos, t, sh) - _g['yaw'])
                    relaxed = True
                    _psrc = 'pinhole_relaxed'
                d['placement_source'] = _psrc
                _src_counts[_psrc] += 1
                # ⚑ vehicle_center_placement (2026-10-03) : le point mesuré est le bas-centre de la
                # boîte — le contact au sol de la FACE VUE, pas le centre du véhicule. Repoussé le
                # long de la ligne de visée jusqu'au centre (`visible_face_to_center`). Axe du
                # véhicule : la vitesse de son track s'il roule, sinon parallèle à la navette (garés
                # le long de la voie). Constat de Fabien, 511,8 s : garés étiquetés 4-5 m, dessinés à
                # moitié sur la voie, donc jamais reconnus garés (rejet « sur_voie »).
                if _center_place:
                    _dims = CLASS_DIMS.get(d.get('class_name'))
                    if _dims:
                        ego = visible_face_to_center(ego[0], ego[1], _dims[0], _dims[1],
                                                     _vehicle_axis(d, pos, t, sh) - _g['yaw'])
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
        # ⚑ same_camera_exclusion : les gids déjà pris DANS CETTE IMAGE par une détection de la
        # même caméra — deux boîtes d'une même image sont deux objets (la fusion de doublons
        # voulue plus haut est INTER-caméras). Mesuré le 2026-09-29 : trois voitures garées en
        # file vues à gauche, toutes G4712 (2,3 / 4,3 / 4,7 m).
        _claimed = defaultdict(dict)     # pos -> {gid: [bbox, ...]}
        # ⚑ chain_lock_priority (2026-10-01) : les chaînes DÉJÀ verrouillées réclament leur gid AVANT
        # que les chaînes nouvelles ne cherchent un plus-proche-voisin. Sans cet ordre, une chaîne
        # nouvelle traitée en premier pouvait prendre le gid d'un objet suivi, que sa propre chaîne
        # trouvait ensuite « pris par une autre boîte » : 1111 changements forcés de gid mesurés.
        if _feat.get('chain_lock_priority', True):
            def _locked_first(item):
                _d, _pos = item[1], item[4]
                _k = (_pos, _d.get('track_id')) if _d.get('track_id') is not None else None
                return 0 if (_k and _k in chain and (t - chain[_k]['t']) <= 4.0) else 1
            dets_here.sort(key=_locked_first)
        for f, d, e, n, pos, relaxed in dets_here:
            _tid = d.get('track_id')
            ck = (pos, _tid) if _tid is not None else None
            best = None
            _lock_note = None
            # ── VERROU DE CHAÎNE ── : un track YOLO par caméra est une chaîne
            # temporellement cohérente — une fois appariée à un gid, elle le GARDE.
            # L'association frame par frame faisait churner le gid sur un même track
            # (track avant #166 = 6 gids différents, audit dépassement 2026-07-17).
            # Le plus-proche-voisin ne sert plus qu'à apparier les chaînes NOUVELLES.
            if ck and ck in chain and (t - chain[ck]['t']) <= 4.0:
                best = by_gid.get(chain[ck]['gid'])
                if _same_cam_excl and best is not None and \
                        claims_distinct_box(_claimed[pos].get(best['id']), d.get('bbox')):
                    best = None          # le gid est déjà pris par un AUTRE objet de cette caméra
                    _lock_note = 'verrou_pris_par_autre_boite'
            elif ck and ck in chain:
                _lock_note = 'verrou_expire'
            if best is None:
                # NN — STRICT pour les mesures dégradées (ratio < 0.7, jamais de
                # création) : c'est le pont physique du dépassement — le véhicule qui
                # longe la navette est vu par la caméra latérale mais 100 % coupé au
                # bord ; il peut REJOINDRE un track existant, pas en fonder un.
                best_ratio = 0.7 if relaxed else 1.0
                _dfam = CLASS_FAMILY.get(d.get('class_name')) if _family_gate else None
                for tr in tracks:
                    dt = t - tr['last_t']
                    if dt < 0 or dt > max_gap_s:
                        continue
                    # ⚑ class_family_gate : une nouvelle chaîne d'un deux-roues ne rejoint pas un
                    # track établi de quatre-roues (et inversement)
                    if _dfam and families_conflict(_dfam, tr.get('fam')):
                        continue
                    if _same_cam_excl and claims_distinct_box(_claimed[pos].get(tr['id']), d.get('bbox')):
                        continue
                    # ⚑ birth_same_camera_guard (2026-10-01) : CETTE caméra voit déjà ce track par une
                    # AUTRE chaîne, vivante il y a moins de 0,5 s (une détection manquée ne la tue
                    # pas) — c'est un autre objet. L'exclusion ci-dessus ne voyait que l'image en cours :
                    # une chaîne née pendant une détection manquée du voisin s'y fondait, puis les deux
                    # chaînes se disputaient le gid (913 changements forcés mesurés).
                    # Une boîte qui RECOUVRE la dernière de l'autre chaîne n'est pas un autre objet :
                    # c'est le détecteur qui a changé de numéro pour le même véhicule — elle doit
                    # pouvoir reprendre son gid (sans quoi la garde fabriquait des pertes).
                    if _birth_guard:
                        _lv = _live_chain.get((tr['id'], pos))
                        if (_lv is not None and _lv[0] != ck and t - _lv[1] <= 0.5
                                and box_iou(_lv[2], d.get('bbox')) < DUPLICATE_BOX_IOU):
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
            _continuity_obs.append((fn, pos, _tid, best['id'], e, n, d.get('bbox')))
            # Diagnostic (2026-10-01) : une chaîne de détecteur qui CHANGE de gid, et pourquoi.
            if ck and ck in chain and chain[ck]['gid'] != best['id']:
                _chain_switch[_lock_note or 'autre'] += 1
            _claimed[pos].setdefault(best['id'], []).append(d.get('bbox'))
            if ck:
                chain[ck] = {'gid': best['id'], 't': t}   # verrou de chaîne (voir plus haut)
                _live_chain[(best['id'], pos)] = (ck, t, d.get('bbox'))
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
            if _family_gate:
                # famille dominante tenue À JOUR sur le track (lue en O(1) par l'association)
                best['fam'] = dominant_family(cls_votes[best['id']])
            dirty.add(f)

    # Métrique A/B de ⚑ same_camera_exclusion (avant recollement) : images×caméras où un même gid
    # porte deux boîtes réelles ou plus.
    _same_camera_shared = 0
    for (_iw, _ih, _frames) in per_cam.values():
        for _f in _frames.values():
            _by = defaultdict(list)
            for d in (_f.detections or []):
                if d.get('global_track_id') is not None and not d.get('predicted') and not d.get('artifact'):
                    _by[d['global_track_id']].append(d.get('bbox'))
            if any(len(bs) > 1 and any(box_iou(bs[0], b) < DUPLICATE_BOX_IOU for b in bs[1:])
                   for bs in _by.values()):
                _same_camera_shared += 1

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
    _fam_of = ({g: dominant_family(v, min_share=0.6) for g, v in cls_votes.items()}
               if _family_gate else {})
    _stitch_refused = 0
    # Diagnostic (2026-10-01) : pour chaque début de tracklet, POURQUOI il n'a pas été recollé — un
    # recollement qui écarte l'essentiel de ses candidats doit dire par quelle porte.
    _stitch_diag = defaultdict(int)
    # ⚑ stitch_one_to_one (2026-10-03) : le recollement n'avait AUCUNE contrainte d'appariement —
    # plusieurs débuts pouvaient prolonger la MÊME fin, et un début pouvait rejoindre un groupe dont un
    # autre membre était présent au même moment. De recollement en recollement, des groupes de
    # dizaines de véhicules se formaient (G2788 : 1584 observations sur 48 m, voitures, vélos et
    # motos, 20 chaînes à l'avant) — invisibles des doublons, qu'elles faisaient même baisser.
    # Mesuré par `tracking_continuity.switchbacks`. Une fin ne se prolonge qu'UNE fois, et jamais
    # vers un groupe déjà présent (tolérance 0,25 s).
    # L'attribution se fait au MEILLEUR AJUSTEMENT (couples triés par écart à la position prédite),
    # pas dans l'ordre d'apparition : sinon un mauvais candidat apparu le premier prenait la fin, et
    # le bon successeur était refusé (1342 refus mesurés en ordre d'apparition).
    _one_to_one = _feat.get('stitch_one_to_one', False)
    _span = {g: (min(h[1] for h in hist), max(h[1] for h in hist)) for g, hist in track_hist.items()}
    _pairs = []                                       # (écart, début, fin) candidats, ⚑ stitch_one_to_one
    for gid, t0, e0, n0 in _starts:
        best_g, best_ratio = None, 1.0
        _slow_in_gate = False
        _near = None
        _has_pair = False
        for og, fit in _endfit.items():
            if _root(og) == _root(gid):
                continue
            te, tw, ew, nw, ve, vn = fit
            gap = t0 - te
            if gap <= 0 or gap > stitch_gap_s:
                continue
            sp = math.hypot(ve, vn)
            dtp = t0 - tw                     # horizon de prédiction depuis le point sain
            pe = ew + ve * dtp
            pn = nw + vn * dtp
            ratio = math.hypot(e0 - pe, n0 - pn) / (gate_m + 1.5 * gap)
            if sp < 1.0 and gap > 2.0:
                _slow_in_gate = _slow_in_gate or ratio < 1.0
                continue
            _near = ratio if _near is None else min(_near, ratio)
            if ratio < best_ratio:
                # ⚑ class_family_gate — compté seulement quand le recollement aurait eu LIEU
                # (dans le gate) : c'est la métrique A/B, pas le nombre de paires examinées
                if _family_gate and families_conflict(_fam_of.get(gid), _fam_of.get(og)):
                    _stitch_refused += 1
                    continue
                if _one_to_one:
                    _pairs.append((ratio, gid, og))      # attribué plus bas, au meilleur ajustement
                    _has_pair = True
                    continue
                best_g, best_ratio = og, ratio
        if _has_pair:
            continue
        if best_g is not None:
            alias[_root(gid)] = _root(best_g)
            _stitch_diag['recolle'] += 1
        elif _near is not None and _near < 1.0:
            _stitch_diag['refuse_famille'] += 1
        elif _slow_in_gate:
            _stitch_diag['bloque_lent_trou_sup_2s'] += 1
        elif _near is not None and _near < 2.0:
            _stitch_diag['juste_hors_gate'] += 1
        else:
            _stitch_diag['aucun_candidat'] += 1

    if _one_to_one:
        _links, _overlap_refused = one_to_one_stitches(_pairs, _span)
        for gid, og in _links:
            alias[_root(gid)] = _root(og)
        _stitch_diag['recolle'] += len(_links)
        _stitch_diag['refuse_groupe_deja_present'] += _overlap_refused
        _stitch_diag['refuse_un_pour_un'] += len({g for _, g, _ in _pairs} - {g for g, _ in _links})

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

    # Descripteurs par track — extraits en fonction PURE le 2026-09-11 pour que le chantier
    # de refonte du filtre (§D.3, verdict Fabien : « à REFAIRE, pas à régler ») puisse MESURER
    # des grandeurs candidates sans rejouer un monkeypatch fragile sur une variable locale.
    # Le filtre ci-dessous n'utilise que ce qu'il utilisait déjà : comportement INCHANGÉ
    # (gardé par un test d'empreinte).
    #
    # Métrique robuste au bruit : ÉTALEMENT spatial de la position monde sur la vie du
    # track (un véhicule garé reste groupé ; un mobile s'étale le long de son trajet).
    # ⚠ Critère VITESSE-AWARE (2026-07-17) : l'étalement seul marquait « garés » des
    # véhicules ROULANTS trackés brièvement (10 km/h × 1,5 s = 4 m < 6 m). Un stationné
    # doit être vu ASSEZ LONGTEMPS (≥ 4 s) avec une vitesse moyenne quasi nulle
    # (étalement/durée < 0,7 m/s ≈ 2,5 km/h), en plus du plafond absolu d'étalement.
    # ⚠⚠ CE FILTRE NE DISAIT RIEN DE CE QU'IL REJETTE (instrumenté le 2026-09-09, demande de
    # Fabien : « regarder ce que fait le code plutôt que supposer »). Quatre conditions
    # s'enchaînaient en silence : on lisait « 55 garés » sans savoir si les 3800 autres étaient
    # mobiles, vus trop brièvement, ou trop étalés. Deux sessions d'analyse EXTERNE (sur les
    # positions PERSISTÉES, donc lissées) ont conclu faux avant qu'on ne compte ici, à la
    # source, sur les positions BRUTES que le filtre juge réellement.
    # Le compte part dans `results_summary['stationary_rejects']` et en console : un filtre qui
    # écarte 97 % de ses candidats doit DIRE par quelle porte.
    # ⚑ parked_off_road (Fabien, 2026-09-30) : un garé est HORS DES VOIES DE CIRCULATION — l'emprise
    # de chaussée IGN (`geo.road_zones`) — et un immobile SUR la chaussée (feu, file, carrefour)
    # peut repartir à tout instant : il n'est jamais garé. Critère LATÉRAL, l'axe où le placement
    # tient (± 0,8 m par rangée) ; les portes d'étalement en mètres, qui mesurent le bruit de
    # placement (§D.3 bis), ne sont plus consultées. Emprise indisponible (réseau IGN) → portes
    # historiques, et le rapport le dit (`stationary_rule`).
    _footprint = _edge = None
    _stationary_rule = 'etalement'
    if _feat.get('parked_off_road', False):
        try:
            from .lane_map_recalage import road_footprint
            _footprint = road_footprint(session, gt, to_local)
        except Exception:
            logger.warning('emprise de chaussée indisponible (⚑ parked_off_road)', exc_info=True)
        if _footprint is None or _footprint.is_empty:
            _footprint = None
            _stationary_rule = 'etalement (emprise IGN indisponible)'
        else:
            _edge = _footprint.boundary
            _stationary_rule = 'hors_voies'
    stationary_gids = []
    _rejets = {'moins_de_5_obs': 0, 'vu_moins_de_4s': 0, 'trop_etale': 0,
               'trop_rapide': 0, 'pres_intersection': 0, 'retenu': 0}
    if _footprint is not None:
        _rejets = {'moins_de_5_obs': 0, 'vu_moins_de_4s': 0, 'pas_un_vehicule': 0,
                   'sur_voie': 0, 'bord_de_voie': 0, 'avance': 0, 'pres_intersection': 0,
                   'en_mouvement': 0, 'retenu': 0}
    _candidats = []          # descripteurs des tracks qui ATTEIGNENT la décision
    # RÉFÉRENCE DE CALIBRATION SOL (2026-10-01) : les immobiles COMPACTS — portes d'étalement, de
    # vitesse et de carrefour —, évaluées QUELLE QUE SOIT la règle des garés. Deux rôles, deux
    # besoins : la qualification « garé » (⚑ parked_off_road) tolère le bruit de placement, la
    # calibration le MESURE. Mesuré le 2026-09-30/10-01 (rejeu, écritures neutralisées) : sur les
    # garés « hors voies » (1433-1694 objets, observés à 19 m) la calibration rendait un étalement de
    # 2,7 à 7,8 m et rejetait toutes les caméras — placement 100 % pinhole ; sur les compacts (115-155,
    # à 13 m) 0,64 à 1,45 m, toutes acceptées, quel que soit le placement de départ.
    calibration_reference = []

    def _compactness_gate(d, hs):
        spread = d['spread_first']
        # La porte d'ÉTALEMENT — elle écarte 45,4 % des candidats (mesuré 09/09).
        # `path_ratio_max` permet de lui substituer le rapport SANS DIMENSION (§D.3 bis).
        # ⚠⚠ DEUX AVERTISSEMENTS, tous deux mesurés le 11/09 et tous deux contre ma première
        # rédaction de ce commentaire :
        # 1. Ce n'est PAS « un seul facteur changé ». La porte SUIVANTE (`trop_rapide`) calcule
        #    `spread_first / durée` : la grandeur remplacée ici continue d'agir juste après —
        #    1216 des 1904 écartés par l'étalement sont simplement repris par la vitesse.
        #    **Remplacer une porte ne remplace pas une GRANDEUR tant qu'elle sert ailleurs
        #    dans la même cascade.**
        # 2. La candidate est RÉFUTÉE (§D.3 bis ③) : à distance égale à la navette (2,4 m
        #    contre 2,7 m), les retenus supplémentaires dispersent 4× plus. Cet argument reste
        #    ici parce qu'il est la COUTURE DE MESURE du chantier, pas parce qu'il serait la
        #    solution — le jour où la bonne grandeur sera trouvée, il lui cédera la place.
        if path_ratio_max is None:
            trop = spread >= spread_max_m
        else:
            trop = d['net_sur_chemin'] >= path_ratio_max
        if trop:
            return 'trop_etale'
        if (spread / d['duree']) >= 0.7:
            return 'trop_rapide'
        if _near_intersection(hs):
            return 'pres_intersection'
        return 'retenu'

    # Porte de sortie PAR TRACK (2026-10-03) : « pourquoi ce véhicule n'est-il pas garé ? » se
    # répondait par un compteur global — la question de Fabien à 511,8 s portait sur SIX voitures.
    _gate_by_gid = {}
    for gid, hist in track_hist.items():
        hs = sorted(hist)
        d = track_descriptors(hs)
        dur = d['duree']
        if d['n_obs'] < 5:
            _rejets['moins_de_5_obs'] += 1
            _gate_by_gid[gid] = 'moins_de_5_obs'
            continue
        _candidats.append(d)
        if dur < 4.0:
            _rejets['vu_moins_de_4s'] += 1
            d['porte'] = 'vu_moins_de_4s'
            _gate_by_gid[gid] = 'vu_moins_de_4s'
            continue
        compact = _compactness_gate(d, hs)
        if compact == 'retenu':
            calibration_reference.append(gid)
        if _footprint is not None:
            porte = off_road_gate(hs, cls_votes.get(gid), _footprint, _edge)
            if porte == 'retenu' and d['net_sur_chemin'] > MAX_NET_OVER_PATH:
                porte = 'avance'
            # Près d'une INTERSECTION : jamais garé — la règle d'ORIGINE du filtre (« voiture arrêtée
            # au carrefour = pertinente »), que la branche hors voies contournait depuis le
            # 2026-09-30 : un véhicule TRAVERSANT le carrefour (G2759) y était figé en garé.
            if porte == 'retenu' and _near_intersection(hs):
                porte = 'pres_intersection'
            if porte == 'retenu' and _feat.get('parked_motion_guard', True):
                _dist, _speed = robust_displacement(hs)
                if _dist >= PARKED_MOVE_M and _speed >= PARKED_MOVE_MPS:
                    porte = 'en_mouvement'
            _rejets[porte] += 1
            d['porte'] = porte
            _gate_by_gid[gid] = porte
            if porte == 'retenu':
                stationary_gids.append(gid)
            continue
        _rejets[compact] += 1
        d['porte'] = compact
        _gate_by_gid[gid] = compact
        if compact == 'retenu':
            stationary_gids.append(gid)
    _stat_set = set(stationary_gids)
    logger.info('[référence de calibration] %s immobiles compacts (garés retenus : %s, règle %s)',
                len(calibration_reference), len(stationary_gids), _stationary_rule)
    logger.info('[stationnés] %s', ' · '.join(f'{k}={v}' for k, v in _rejets.items()))

    # Distribution des grandeurs CANDIDATES sur la population qui atteint la décision
    # (≥ 5 observations). Des quantiles, pas une moyenne : la question posée au chantier
    # §D.3 est de savoir si une grandeur SÉPARE la population en deux modes — une moyenne
    # ne le dirait pas, et 5210 tracks ne tiennent pas dans `results_summary`.
    _stat_candidats = {'n': len(_candidats)}
    for _k, _vmax in _BORNES_HISTO.items():
        _vals = [c[_k] for c in _candidats]
        _stat_candidats[_k] = _quantiles(_vals)
        _stat_candidats[_k + '_histo'] = {'vmax': _vmax, 'bins': _histogramme(_vals, _vmax)}
    # CROISEMENT : que dit la grandeur candidate de ceux que le filtre ACTUEL écarte ?
    # Une distribution globale ne le dit pas — or c'est la question qui décide d'une refonte :
    # la nouvelle grandeur retiendrait-elle ce que l'ancienne rejette, ou les mêmes ?
    _par_porte = {}
    for _c in _candidats:
        _par_porte.setdefault(_c.get('porte', '?'), []).append(_c['net_sur_chemin'])
    _stat_candidats['net_sur_chemin_par_porte'] = {
        _p: dict(_quantiles(_v), n=len(_v)) for _p, _v in _par_porte.items()}
    logger.info('[stationnés/candidats] %s', _stat_candidats)

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
            # champ VERTICAL effectif (`camera_geometry`), cohérent avec le champ horizontal utilisé
            cands.extend(_ratio_heading_candidates(
                bb, iw_o, ih_o, _cls, _geo[pos], _geo[pos]['fov_v'], shh))
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
    ghost_links = []   # (frame, détection, gid, f0, f1, a, fn) — repris après le lissage
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
                    ghost_links.append((fr, fr.detections[-1], gid, f0, f1, a, fn))

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
    # (gid, fn) -> (vx, vy) m/s : vitesse LISSÉE du même filtre (2026-10-01) — le cap d'affichage
    # en dérive (`world_vel`) au lieu de la recalculer sur les quelques images vues par la page
    smoothed_vel = {}
    for gid, hist in track_hist.items():
        if gid in _stat_set or len(hist) < 5:
            continue
        try:
            out = smooth_track([(t, e, n) for (_fn, t, e, n, _c) in hist])
        except Exception:
            logger.debug('smooth_track failed gid=%s', gid, exc_info=True)
            continue
        by_t = {round(t, 4): (e, n, vx, vy) for t, e, n, vx, vy in out}
        for fn, t, _e, _n, _c in hist:
            v = by_t.get(round(t, 4))
            if v:
                smoothed[(gid, fn)] = (v[0], v[1])
                smoothed_vel[(gid, fn)] = (v[2], v[3])

    # ── Fantômes REPOSÉS sur la trajectoire LISSÉE (⚑ ghost_on_smoothed, 2026-09-29) ─────
    # Un fantôme interpolait entre les positions BRUTES encadrant le trou, alors que les
    # détections réelles s'affichent sur la trajectoire LISSÉE (`world_en`, bloc ci-dessus) :
    # chaque entrée/sortie de fantôme faisait SAUTER l'objet. Mesuré sur `4da52df3` : saut
    # p50 0,56 m / p90 2,25 m / p99 9,1 m contre un pas normal p50 0,12 m. On interpole entre
    # les deux points LISSÉS qui encadrent le trou. Et un fantôme dans l'EMPRISE de la navette
    # est physiquement impossible (le lien entre ses deux bouts est faux) : retiré.
    _prof = getattr(session, 'profile', None)
    _use_smooth = _feat.get('ghost_on_smoothed', True)
    ghost_jumps, ghosts_in_footprint = reanchor_ghosts(
        ghost_links, smoothed, lambda fn: _shuttle_pose_at(sh_traj, fn / fps * scale + off),
        use_smoothed=_use_smooth,
        ego_length_m=float(getattr(_prof, 'ego_length_m', None) or 4.75),
        ego_width_m=float(getattr(_prof, 'ego_width_m', None) or 2.11))
    if ghost_links:
        logger.info("[fantômes] %s posés (%s), %s retirés dans l'emprise navette · saut au bord p50 %s p90 %s",
                    len(ghost_links) - ghosts_in_footprint,
                    'trajectoire lissée' if _use_smooth else 'positions brutes', ghosts_in_footprint,
                    _quantiles(ghost_jumps, (0.5,)).get('p50'), _quantiles(ghost_jumps, (0.9,)).get('p90'))

    # ── Classe STABLE par track (vote majoritaire pondéré confiance) ────────────────
    # YOLO fait flapper la classe (car↔truck) d'une frame à l'autre sur le même
    # véhicule → gabarit vue de dessus qui saute. La classe d'un TRACK est la majorité
    # pondérée sur toute sa durée, écrite sur chaque détection (`stable_class`) —
    # l'affichage la préfère à la classe brute de la frame.
    stable_cls = {gid: max(v, key=v.get) for gid, v in cls_votes.items() if v}
    # MARGE du vote (2026-09-12) — le verdict seul cachait sa propre fragilité.
    # Mesuré avant de l'écrire : 40,4 % des gids changent de classe brute (45 701 bascules),
    # et le vote les tranche NETTEMENT dans 95 % des cas — mais les 5 % restants sont
    # départagés à quelques pourcents, sans que rien ne le dise. Un consommateur qui dessine
    # un gabarit « truck » ne peut pas savoir qu'il repose sur 51 contre 49.
    # ⭐ On DÉCLARE l'hésitation au lieu de changer la règle : l'alternative testée (pondérer
    # par l'aire de bbox) déplacerait 232 gids, mais rien ne dit qu'elle a raison faute de
    # vérité terrain — remplacer une pondération arbitraire par une autre n'est pas une
    # amélioration. Même idiome que la facette estimateur (§E) : une incertitude se déclare.
    stable_marge = {}
    for gid, v in cls_votes.items():
        if not v:
            continue
        o = sorted(v.values(), reverse=True)
        tot = sum(o)
        stable_marge[gid] = round((o[0] - (o[1] if len(o) > 1 else 0.0)) / tot, 3) if tot else 1.0
    _cls_fragiles = sum(1 for m in stable_marge.values() if m < 0.1)
    logger.info('[classe stable] %s gids · marge < 0,10 : %s · marge médiane %.3f',
                len(stable_cls), _cls_fragiles,
                sorted(stable_marge.values())[len(stable_marge) // 2] if stable_marge else 1.0)
    for f in dirty:
        for d in (f.detections or []):
            g = d.get('global_track_id')
            sc = stable_cls.get(g)
            if sc:
                d['stable_class'] = sc
                d['stable_class_margin'] = stable_marge.get(g, 1.0)
            w = smoothed.get((g, f.frame_number)) if g is not None else None
            if w:
                d['world_en'] = [round(w[0], 2), round(w[1], 2)]
                wv = smoothed_vel.get((g, f.frame_number))
                if wv:
                    d['world_vel'] = [round(wv[0], 2), round(wv[1], 2)]

    # Métrique #3 (2026-10-01) : ce que le suivi DUPLIQUE ou PERD, après recollement (gids racines).
    continuity = None
    try:
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        continuity = tracking_continuity(_continuity_obs, root=_root)
        continuity['stitch'] = dict(_stitch_diag)
        continuity['chain_switch'] = dict(_chain_switch)
        logger.info('[tracking 360°] continuité : %s', continuity)
    except Exception:
        logger.warning('tracking_continuity (contrôle qualité) échoué', exc_info=True)
    stale_reset = stale_fields_report(_reset)
    logger.info('[tracking 360°] état du calcul précédent : %s', stale_reset)

    # ── Contrôle qualité : cohérence caméra ↔ position monde (brique WAMA Data #2) ──
    # Sur les positions FRAÎCHES (mobiles lissés) : un objet placé derrière sa propre caméra est
    # impossible, et l'écart entre la profondeur affichée (étiquette) et celle de la position
    # dessinée se lit ici au lieu d'être découvert à l'écran.
    camera_check = None
    try:
        from wama_data.functions.geometry.placement_metrics import camera_consistency
        _obs = []
        for pos, (_iw, _ih, frames) in per_cam.items():
            _g = _geo[pos]
            _mx, _my = _g['mount']
            for fn, f in frames.items():
                ws = [d for d in (f.detections or []) if d.get('world_en') and not d.get('predicted')]
                if not ws:
                    continue
                se, sn, sh = _shuttle_pose_at(sh_traj, fn / fps * scale + off)
                for d in ws:
                    x, y = world_to_vehicle(d['world_en'][0], d['world_en'][1], se, sn, sh)
                    dm = d.get('distance_m')
                    _obs.append((pos, x, y, _g['yaw'], _mx, _my,
                                 dm * _g['dist_scale'] if isinstance(dm, (int, float)) else None))
        camera_check = camera_consistency(_obs)
        logger.info('[tracking 360°] cohérence caméra ↔ position : %s', camera_check)
    except Exception:
        logger.warning('camera_consistency (contrôle qualité) échoué', exc_info=True)

    # Par lots, et ATOMIQUE : un `save()` par frame (~300 000) prenait ~3 min, et un worker
    # arrêté au milieu laissait la base mi-ancienne mi-nouvelle (2026-09-29, arrêt de 21:18).
    DF.objects.bulk_update(list(dirty), ['detections'], batch_size=500)

    # ── Métrique A/B objective : cohérence de placement des stationnés ────────────
    # Un objet réellement immobile doit se réduire à UN point monde ; la dispersion
    # RMS de ses positions autour de leur barycentre est un proxy sans-vérité-terrain
    # de la qualité du placement (0 = idéal, plus bas = meilleur). Brique commune WAMA
    # Data réutilisable. Comparer ce chiffre entre deux configs (⚑ auto_ground_calib
    # ON vs OFF) = A/B objectif au lieu d'une inspection « à l'œil » (cf. feedback).
    # Les stationnés sont exclus du lissage (plus haut) : leurs positions par
    # observation ne vivent que dans `track_hist`, filtré ici par `_stat_set`.
    placement_spread = None
    try:
        from wama_data.functions.geometry.placement_metrics import track_position_spread
        # Sur la RÉFÉRENCE de calibration, pas sur les garés : cette métrique tranche la source
        # de calibration, et doit mesurer la même population qu'elle (cf. `calibration_reference`).
        _pos_by_stat = {gid: [(h[2], h[3]) for h in track_hist.get(gid, [])]
                        for gid in calibration_reference}
        placement_spread = track_position_spread(_pos_by_stat, min_obs=3)
    except Exception:
        logger.warning('placement_spread (métrique de cohérence) échouée', exc_info=True)

    return {'tracks': next_id - 1, 'stationary_gids': stationary_gids,
            'stationary_anchors': stationary_anchors,
            'calibration_reference_gids': calibration_reference,
            'placement_spread': placement_spread,
            'placement_sources': dict(_src_counts),
            'stationary_rejects': _rejets,
            'stationary_gate_by_gid': _gate_by_gid,
            'stationary_rule': _stationary_rule,
            'stationary_candidates': _stat_candidats,
            'stable_class_fragiles': _cls_fragiles,
            'stable_class_margin_median': (sorted(stable_marge.values())[len(stable_marge) // 2]
                                           if stable_marge else None),
            'mixed_family_gids': _mixed_family_gids(cls_votes),
            'same_camera_shared_gids': _same_camera_shared,
            'stitch_refused_by_family': _stitch_refused,
            'ghosts': len(ghost_links) - ghosts_in_footprint,
            'ghosts_in_footprint_removed': ghosts_in_footprint,
            'ghost_boundary_jump_m': _quantiles(ghost_jumps, (0.5, 0.9, 0.99)),
            'stale_fields_reset': stale_reset,
            'camera_consistency': camera_check,
            'continuity': continuity}
