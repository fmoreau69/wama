"""INTERACTIONS NAVETTE ↔ VÉHICULES, UNE LIGNE PAR VÉHICULE : insertions aux intersections et dépassements.

Pourquoi (Fabien, 2026-10-29, reprise de la demande initiale) : les sorties de fichiers devaient porter un
tableau qui ne contient QUE les conflits aux intersections — une ligne par véhicule susceptible de s'insérer,
avec son identifiant (le `G…` de la vue de dessus), s'il s'insère avant ou après le passage de la navette,
dans la voie de la navette ou dans la voie opposée, t0 (premier mouvement), t1 (entrée dans la voie),
t2 (sortie de la voie), les distances à la navette à ces instants, la distance minimale, la vitesse
maximale, le TTC minimal et sa distance, le PET minimal, et le véhicule à l'arrière de la navette pendant
la traversée. L'export existant (`conflicts.csv`) avait une ligne par track de CAMÉRA et par étendue de voie
(les `G…` n'y étaient pas), sans t0/t1/t2 ni distances aux instants, ni véhicule arrière. Même demande pour
les dépassements, que le tracking 360° suit désormais bien.

Tout se lit dans le REPÈRE DE LA TRAJECTOIRE DE LA NAVETTE (`PathFrame`) : abscisse `s` le long de son
chemin, écart latéral `lat` (positif à DROITE). La navette roule au centre de sa voie : sa voie est
|lat| ≤ largeur/2, la voie opposée (circulation à droite) est à sa gauche, de −1,5 largeur à −0,5 largeur.
Un virage de la navette est suivi par le chemin, pas par un repère figé.

Fonctions pures : l'appelant donne la trajectoire de la navette (instant, e, n, cap — le CENTRE ARRIÈRE,
origine des montages caméra) et, par véhicule, ses observations (instant, e, n, ve, vn[, ttc, pet]) dans
le même repère et la même base de temps.
"""
from __future__ import annotations

import math

import numpy as np

from wama.common.catalog.data_types import DataType, TypedFrame
from ...core.calculation import rolling
from ..geometry.shapes import point_traj_to_shape
from ..kinematics.collision import collision_detection
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                                  FunctionCategory, register)

#: Longueur et largeur de la navette (m) — son centre est à mi-longueur DEVANT le point de référence
#: (centre arrière).
SHUTTLE_LENGTH_M = 5.5
SHUTTLE_WIDTH_M = 2.1
#: Largeur (m) par défaut d'un véhicule dont la classe n'est pas connue.
VEHICLE_WIDTH_M = 1.8
#: Largeur de voie (m) par défaut, quand la session n'en a pas mesuré.
LANE_WIDTH_M = 3.5
#: Longueur (m) par défaut d'un véhicule dont la classe n'est pas connue.
VEHICLE_LENGTH_M = 4.5
#: Au-dessus de cette vitesse (m/s) un véhicule roule ; en dessous de `STILL_MPS` il est à l'arrêt.
MOVE_MPS = 1.0
STILL_MPS = 0.5
#: Durées (s) qu'un arrêt puis un départ doivent tenir pour compter.
STILL_S = 1.0
MOVE_S = 0.5
#: Une zone (voie, bord) ne compte qu'après ce nombre d'observations successives.
MIN_RUN = 3
#: Angle (°) sous lequel un véhicule roule dans l'axe de la voie : son insertion est achevée.
ALIGN_DEG = 25.0
#: Distance (m) au-delà de laquelle un véhicule derrière la navette n'est pas « à l'arrière ».
REAR_RANGE_M = 50.0
#: Prolongement (m) du chemin de la navette à ses deux bouts, pour situer ce qui est vu au-delà.
PATH_EXTENSION_M = 80.0


class PathFrame:
    """Repère d'un chemin (polyligne e, n) : `project(e, n)` → (s, lat, tangente) ; `lat` positif à droite."""

    def __init__(self, points, extension_m=PATH_EXTENSION_M):
        pts = np.asarray(points, dtype=float)
        keep = [0]
        for i in range(1, len(pts)):
            if math.hypot(*(pts[i] - pts[keep[-1]])) >= 0.2:
                keep.append(i)
        pts = pts[keep]
        if len(pts) < 2:
            raise ValueError('chemin trop court')
        d0 = pts[1] - pts[0]
        d1 = pts[-1] - pts[-2]
        head = pts[0] - d0 / max(np.linalg.norm(d0), 1e-9) * extension_m
        tail = pts[-1] + d1 / max(np.linalg.norm(d1), 1e-9) * extension_m
        self.pts = np.vstack([head, pts, tail])
        seg = np.diff(self.pts, axis=0)
        self.len = np.linalg.norm(seg, axis=1)
        self.dir = seg / np.maximum(self.len[:, None], 1e-9)
        self.s0 = np.concatenate([[0.0], np.cumsum(self.len)[:-1]]) - extension_m

    def project(self, e, n):
        p = np.array([e, n], dtype=float)
        rel = p - self.pts[:-1]
        along = np.clip(np.einsum('ij,ij->i', rel, self.dir), 0.0, self.len)
        foot = self.pts[:-1] + self.dir * along[:, None]
        k = int(np.argmin(np.linalg.norm(foot - p, axis=1)))
        de, dn = p - self.pts[k]
        ue, un = self.dir[k]
        return float(self.s0[k] + along[k]), float(de * un - dn * ue), (float(ue), float(un))


class ShuttleTrack:
    """La navette : pose (centre arrière, cap) à tout instant, et — avec un chemin `path` — l'abscisse de
    son CENTRE sur ce chemin. Sans chemin (session entière, plusieurs tours : la projection sauterait
    d'un tour à l'autre), `relative` situe un point dans son repère INSTANTANÉ."""

    def __init__(self, rows, path: PathFrame | None = None, length_m=SHUTTLE_LENGTH_M,
                 width_m=SHUTTLE_WIDTH_M):
        arr = np.asarray(sorted(rows, key=lambda r: r[0]), dtype=float)
        self.t = arr[:, 0]
        self.e, self.n = arr[:, 1], arr[:, 2]
        self.h_unwrapped = np.degrees(np.unwrap(np.radians(arr[:, 3])))
        self.half = length_m / 2.0
        self.length, self.width = length_m, width_m
        self.path = path
        if path is not None:
            self.s_rear = np.array([path.project(e, n)[0] for e, n in zip(self.e, self.n)])
            # l'abscisse le long du chemin ne recule pas (le bruit de projection, si)
            self.s_rear = np.maximum.accumulate(self.s_rear)

    def position_at(self, t):
        """(e, n, cap °) du centre arrière à l'instant `t`."""
        return (float(np.interp(t, self.t, self.e)), float(np.interp(t, self.t, self.n)),
                float(np.interp(t, self.t, self.h_unwrapped)) % 360.0)

    def center(self, t):
        e, n, h = self.position_at(t)
        h = math.radians(h)
        return e + self.half * math.sin(h), n + self.half * math.cos(h)

    def relative(self, t, e, n):
        """(longitudinal depuis le CENTRE de la navette, latéral positif à droite, (ue, un) de son axe)."""
        se, sn, h = self.position_at(t)
        hr = math.radians(h)
        s, c = math.sin(hr), math.cos(hr)
        de, dn = e - se, n - sn
        return de * s + dn * c - self.half, de * c - dn * s, (s, c)

    def velocity(self, t, dt=0.5):
        """(ve, vn) m/s de la navette à l'instant `t`."""
        e0, n0, _ = self.position_at(t - dt)
        e1, n1, _ = self.position_at(t + dt)
        return (e1 - e0) / (2 * dt), (n1 - n0) / (2 * dt)

    def speed(self, t, dt=0.5):
        return math.hypot(*self.velocity(t, dt))

    def footprint_state(self, t):
        """(e, n, ve, vn, longueur, largeur) de son CENTRE, pour `observed_ttc` — à l'arrêt, une vitesse
        infime le long de son cap : l'empreinte s'oriente par la vitesse, et vers l'est sans elle."""
        e, n = self.center(t)
        ve, vn = self.velocity(t)
        if math.hypot(ve, vn) < 0.05:
            h = math.radians(self.position_at(t)[2])
            ve, vn = 1e-3 * math.sin(h), 1e-3 * math.cos(h)
        return e, n, ve, vn, self.length, self.width

    def s_center(self, t):
        return float(np.interp(t, self.t, self.s_rear)) + self.half

    def s_rear_at(self, t):
        return float(np.interp(t, self.t, self.s_rear))


    def time_at_center(self, s):
        """Instant où le centre de la navette passe l'abscisse `s` (None hors de la plage observée)."""
        sc = self.s_rear + self.half
        if s < sc[0] or s > sc[-1]:
            return None
        return float(np.interp(s, sc, self.t))


#: Marge (m) au-delà du bord de la chaussée avant de compter un véhicule « dehors » : le bruit latéral du
#: placement ne le fait pas sortir et rentrer.
EDGE_MARGIN_M = 0.5
#: Un véhicule qui roule dehors vient de côté si sa route fait au moins cet angle (°) avec la voie.
CROSS_DEG = 35.0
#: Écart latéral maximal (m, caisse à caisse) d'un dépassement : la voie voisine, pas une route parallèle.
OVERTAKE_LATERAL_MAX_M = 3.0
#: Fenêtre (s) des médianes glissantes qui ôtent le bruit des bouts de trace (vitesse, TTC) — ≈ 7
#: observations à 12 i/s : à 5, une vmax de 103 km/h restait (rejeu du 2026-10-29).
ROBUST_WINDOW_S = 0.6
#: Horizon (s) et pas (s) du TTC observé : au-delà, un TTC ne décrit plus un conflit (rejeu : 114 s pour
#: un véhicule à 27 m) ; le pas est celui de la passe Indicateurs.
TTC_HORIZON_S = 10.0
TTC_STEP_S = 0.2


def _zone(lat, lane_w, previous=None):
    """'shuttle', 'opposite', 'right', 'left' — dans la marge du bord de chaussée, la zone d'avant."""
    if abs(lat) <= lane_w / 2:
        return 'shuttle'
    if -1.5 * lane_w <= lat < -lane_w / 2:
        return 'opposite'
    if lat > lane_w / 2 + EDGE_MARGIN_M:
        return 'right'
    if lat < -1.5 * lane_w - EDGE_MARGIN_M:
        return 'left'
    return previous or ('shuttle' if lat > 0 else 'opposite')


def _robust(times, values):
    """Médiane glissante centrée sur `ROBUST_WINDOW_S` — la statistique glissante du monde Data
    (`core.calculation.rolling`), valeurs absentes écartées."""
    return rolling(times, values, ROBUST_WINDOW_S, 'median')


def _runs(zones, times, min_run=MIN_RUN):
    """Plages successives d'une même zone, les plages trop courtes fondues dans la précédente :
    [(zone, t_début, t_fin, i_début, i_fin)]."""
    runs = []
    i = 0
    while i < len(zones):
        j = i
        while j + 1 < len(zones) and zones[j + 1] == zones[i]:
            j += 1
        if runs and (j - i + 1) < min_run:
            z, t0, _t1, i0, _i1 = runs[-1]
            runs[-1] = (z, t0, times[j], i0, j)
        elif runs and runs[-1][0] == zones[i]:
            z, t0, _t1, i0, _i1 = runs[-1]
            runs[-1] = (z, t0, times[j], i0, j)
        else:
            runs.append((zones[i], times[i], times[j], i, j))
        i = j + 1
    return runs


def _first_movement(times, speeds, *, move=MOVE_MPS, still=STILL_MPS, still_s=STILL_S, move_s=MOVE_S):
    """(t0, départ après un arrêt ?, durée de l'arrêt) — t0 = premier instant où le véhicule roule
    (au-dessus de `move` pendant `move_s`) ; après un arrêt (sous `still` pendant `still_s`) c'est le
    départ ; sinon il roulait déjà à sa première observation. None s'il ne roule jamais."""
    still_since, last_still = None, None
    for i, (t, v) in enumerate(zip(times, speeds)):
        if v < still:
            still_since = t if still_since is None else still_since
            last_still = (still_since, t)
            continue
        still_since = None
        if v >= move:
            # le départ TIENT : pas de retour à l'arrêt pendant `move_s` (ou jusqu'à la fin observée)
            j = i
            while j + 1 < len(times) and speeds[j + 1] >= still and times[j] - t < move_s:
                j += 1
            if times[j] - t >= move_s or j == len(times) - 1:
                if last_still and last_still[1] - last_still[0] >= still_s:
                    return t, True, round(last_still[1] - last_still[0], 2)
                return t, False, 0.0
    return None, False, 0.0


def _round(v, k=2):
    return None if v is None else round(float(v), k)


def observed_ttc(t, first, second, *, horizon=TTC_HORIZON_S, step=TTC_STEP_S):
    """TTC OBSERVÉ à l'instant `t` : chacun prolongé à vitesse constante, en EMPREINTES rectangulaires
    orientées par la vitesse (`geometry.point_traj_to_shape`), et la collision cherchée par la brique de la
    passe Indicateurs (`kinematics.collision_detection`) — seuls les positions et vitesses diffèrent :
    observées et lissées ici, extrapolées du pinhole là-bas. `first` / `second` : (e, n, ve, vn, longueur,
    largeur). None sans contact dans l'horizon."""
    # Sortie EXACTE avant les empreintes (×6 de temps sinon, rejeu du 2026-10-29) : à vitesses constantes,
    # la distance des centres ne fait que croître s'ils s'éloignent déjà, et ne peut fondre de plus de
    # |vitesse relative| × horizon ; hors de la somme des demi-diagonales, aucun contact possible.
    dp = (second[0] - first[0], second[1] - first[1])
    dv = (second[2] - first[2], second[3] - first[3])
    reach = (math.hypot(first[4], first[5]) + math.hypot(second[4], second[5])) / 2
    gap = math.hypot(*dp)
    if gap > reach and (dp[0] * dv[0] + dp[1] * dv[1] >= 0 or gap - math.hypot(*dv) * horizon > reach):
        return None
    ks = np.arange(int(horizon / step) + 1) * step
    shapes = []
    for e, n, ve, vn, length, width in (first, second):
        traj = np.column_stack([t + ks, e + ve * ks, n + vn * ks])
        shapes.append(point_traj_to_shape(traj, length, width))
    return collision_detection(shapes[0], shapes[1], compute_pet=False)['ttc']


def _observed_pet(shuttle, pr, lane, length):
    """PET OBSERVÉ au point d'entrée du véhicule dans la voie de la navette : (pet, qui passe d'abord).
    Le véhicule occupe ce point de son entrée (t1) jusqu'à ce qu'il le libère (sortie latérale de la voie,
    ou son arrière au-delà du point) ; la navette, du passage de son avant à celui de son arrière.
    None si l'un des deux passages n'est pas observé."""
    t1, _t2, _how, i0 = lane
    s_entry = pr[i0][1]
    t_clear = None
    for p in pr[i0:]:
        if p[4] != 'shuttle' or p[1] - length / 2 > s_entry + 1.0:
            t_clear = p[0][0]
            break
    t_front = shuttle.time_at_center(s_entry - shuttle.half)
    t_rear = shuttle.time_at_center(s_entry + shuttle.half)
    if t_front is not None and t_clear is not None and t_clear <= t_front:
        return t_front - t_clear, 'vehicle_first'
    if t_rear is not None and t_rear <= t1:
        return t1 - t_rear, 'shuttle_first'
    if t_front is None or t_rear is None or t_clear is None:
        return None, None
    return 0.0, 'overlap'


def insertion_rows(window, shuttle: ShuttleTrack, vehicles, *, parked=(), lane_w=LANE_WIDTH_M,
                   lengths=None, widths=None, min_obs=5):
    """Une ligne par véhicule SUSCEPTIBLE DE S'INSÉRER dans la fenêtre `window` ({'name', 'idx',
    't_enter', 't_exit', 'center': (e, n), 'radius_m'}) : un véhicule non garé, vu au moins `min_obs`
    fois dans la fenêtre, hors de la chaussée (ni la voie de la navette ni l'opposée) dans le rayon de
    l'intersection — qu'il s'y insère ensuite (`inserted`) ou qu'il attende.
    `vehicles` : {id: [(t, e, n, ve, vn, cls, ttc, pet)…] triés}. `lengths` / `widths` : {classe: m}."""
    lengths, widths = lengths or {}, widths or {}
    parked = set(parked)
    t_a, t_b = window['t_enter'], window['t_exit']
    ce, cn = window['center']
    radius = float(window.get('radius_m') or 30.0)
    prepared = {}
    for gid, obs in vehicles.items():
        if gid in parked:
            continue
        inside = [o for o in obs if t_a <= o[0] <= t_b]
        if len(inside) < min_obs:
            continue
        pr, zone = [], None
        for o in inside:
            s, lat, tan = shuttle.path.project(o[1], o[2])
            zone = _zone(lat, lane_w, zone)
            pr.append((o, s, lat, tan, zone))
        prepared[gid] = pr
    rows = []
    for gid, pr in prepared.items():
        times = [p[0][0] for p in pr]
        zones = [p[4] for p in pr]
        near = [math.hypot(p[0][1] - ce, p[0][2] - cn) <= radius for p in pr]
        speeds = _robust(times, [math.hypot(p[0][3], p[0][4]) for p in pr])
        runs = _runs(zones, times)
        # « susceptible de s'insérer » : DEHORS près de l'intersection en venant de côté — à l'arrêt, ou
        # roulant en travers de la voie (le trafic de passage, légèrement hors voie à l'élargissement du
        # carrefour, roule dans l'axe : il n'en est pas)
        side_runs = [k for k, (z, _a, _b, i0, i1) in enumerate(runs)
                     if z in ('left', 'right') and any(near[i0:i1 + 1]) and _from_the_side(pr, speeds, i0, i1)]
        if not side_runs:
            continue
        cls = pr[0][0][5]
        lanes = {}
        for k in range(side_runs[0] + 1, len(runs)):
            z, ta, tb, i0, i1 = runs[k]
            if z in ('shuttle', 'opposite') and z not in lanes:
                t2, how = _lane_exit(runs, k, pr)
                lanes[z] = (ta, t2, how, i0)
        main = 'shuttle' if 'shuttle' in lanes else ('opposite' if 'opposite' in lanes else None)
        t0, from_stop, waited = _first_movement(times, speeds)
        if t0 is None and main is None:
            continue                          # ni départ ni insertion pendant la fenêtre : rien à qualifier

        def dist(t):
            if t is None:
                return None
            j = min(range(len(times)), key=lambda q: abs(times[q] - t))
            sc = shuttle.center(t)
            return math.hypot(pr[j][0][1] - sc[0], pr[j][0][2] - sc[1])

        d_all = [dist(t) for t in times]
        jmin = int(np.argmin(d_all))
        # TTC OBSERVÉ (trajectoires suivies, vitesses constantes, `observed_ttc`) : le minimum de sa médiane
        # glissante — le minimum brut attrape le bruit d'un bout de trace. Le TTC PRÉDIT de la passe
        # Indicateurs (`prediction_ttc`) reste en colonne à part, pour comparaison.
        size = (lengths.get(cls, VEHICLE_LENGTH_M), widths.get(cls, VEHICLE_WIDTH_M))
        obs_ttc = [observed_ttc(p[0][0], shuttle.footprint_state(p[0][0]), (*p[0][1:5], *size)) for p in pr]
        ttc = [(v, times[k], d_all[k]) for k, v in enumerate(_robust(times, obs_ttc)) if v is not None]
        ttc_pred = [v for v in _robust(times, [p[0][6] if p[0][6] is not None and p[0][6] > 0 else None
                                               for p in pr]) if v is not None]
        pet, pet_first = (_observed_pet(shuttle, pr, lanes['shuttle'], lengths.get(cls, VEHICLE_LENGTH_M))
                          if 'shuttle' in lanes else (None, None))
        row = {
            'intersection': window.get('name', ''), 'window_idx': window.get('idx'),
            'id': gid, 'class_name': cls, 'first_seen_s': _round(times[0]), 'last_seen_s': _round(times[-1]),
            'inserted': main is not None,
            'shuttle_lane': 'shuttle' in lanes, 'opposite_lane': 'opposite' in lanes,
            't0_s': _round(t0), 'started_from_stop': from_stop, 'waited_s': _round(waited),
            'd0_m': _round(dist(t0)), 'dmin_m': _round(d_all[jmin]), 'dmin_t_s': _round(times[jmin]),
            'vmax_kmh': _round(max(speeds) * 3.6, 1),
            'ttc_min_s': _round(min(ttc)[0]) if ttc else None,
            'ttc_min_t_s': _round(min(ttc)[1]) if ttc else None,
            'ttc_min_distance_m': _round(min(ttc)[2]) if ttc else None,
            'ttc_pred_min_s': _round(min(ttc_pred)) if ttc_pred else None,
            'pet_s': _round(pet), 'pet_first': pet_first,
        }
        for z, key in (('shuttle', 'shuttle_lane'), ('opposite', 'opposite_lane')):
            ta, t2, how, _i0 = lanes.get(z, (None, None, None, None))
            row[f't1_{key}_s'], row[f't2_{key}_s'], row[f't2_{key}_kind'] = _round(ta), _round(t2), how
        if main:
            t1, t2, how, i0 = lanes[main]
            s_entry = pr[i0][1]
            t_pass = shuttle.time_at_center(s_entry)
            row.update({
                'lane_t1_t2': main, 't1_s': _round(t1), 't2_s': _round(t2), 't2_kind': how,
                'd1_m': _round(dist(t1)), 'd2_m': _round(dist(t2)),
                # devant le centre de la navette quand il entre : il s'insère AVANT son passage
                'before_shuttle': s_entry > shuttle.s_center(t1),
                'after_shuttle': s_entry <= shuttle.s_center(t1),
                'gap_to_shuttle_at_t1_m': _round(s_entry - shuttle.s_center(t1)),
                'shuttle_at_entry_point_s': _round(t_pass),
                'shuttle_time_margin_s': _round(t_pass - t1) if t_pass is not None else None,
            })
        else:
            row.update({'lane_t1_t2': None, 't1_s': None, 't2_s': None, 't2_kind': None, 'd1_m': None,
                        'd2_m': None, 'before_shuttle': None, 'after_shuttle': None,
                        'gap_to_shuttle_at_t1_m': None, 'shuttle_at_entry_point_s': None,
                        'shuttle_time_margin_s': None})
        # le véhicule à l'arrière de la navette PENDANT la traversée (t1 → t2 dans la voie de la navette),
        # à défaut pendant la présence du véhicule dans la fenêtre
        if 'shuttle' in lanes and lanes['shuttle'][1] is not None:
            span = (lanes['shuttle'][0], lanes['shuttle'][1])
        else:
            span = (times[0], times[-1])
        row.update(rear_vehicle(shuttle, vehicles, span, exclude={gid} | parked, lane_w=lane_w,
                                lengths=lengths, widths=widths))
        row['rear_span'] = 'traversée' if 'shuttle' in lanes and lanes['shuttle'][1] is not None else 'présence'
        rows.append(row)
    rows.sort(key=lambda r: (r['first_seen_s'] or 0.0))
    return rows


def _from_the_side(pr, speeds, i0, i1):
    """La plage dehors [i0, i1] vient-elle de côté : un arrêt d'au moins `STILL_S`, ou au moins
    `MIN_RUN` observations roulant en travers de la voie (angle ≥ `CROSS_DEG`) ?"""
    still = [pr[i][0][0] for i in range(i0, i1 + 1) if speeds[i] is not None and speeds[i] < STILL_MPS]
    if still and still[-1] - still[0] >= STILL_S:
        return True
    crossing = 0
    for i in range(i0, i1 + 1):
        o, (ue, un) = pr[i][0], pr[i][3]
        v = math.hypot(o[3], o[4])
        if v < MOVE_MPS:
            continue
        cos = abs(o[3] * ue + o[4] * un) / v
        crossing += cos <= math.cos(math.radians(CROSS_DEG))
    return crossing >= MIN_RUN


def _lane_exit(runs, k, pr):
    """(t2, nature) de la plage de voie `runs[k]` : 'sortie' quand le véhicule la quitte ; sinon
    'alignement' au premier instant où il roule dans l'axe de la voie (insertion achevée) ; sinon
    'fin_observation'."""
    z, ta, tb, i0, i1 = runs[k]
    if k + 1 < len(runs):
        return runs[k + 1][1], 'sortie'
    for p in pr[i0:i1 + 1]:
        o, _s, _lat, (ue, un) = p[0], p[1], p[2], p[3]
        v = math.hypot(o[3], o[4])
        if v >= MOVE_MPS:
            cos = abs(o[3] * ue + o[4] * un) / v
            if cos >= math.cos(math.radians(ALIGN_DEG)):
                return o[0], 'alignement'
    return tb, 'fin_observation'


def rear_vehicle(shuttle: ShuttleTrack, vehicles, span, *, exclude=(), lane_w=LANE_WIDTH_M, lengths=None,
                 widths=None, rear_range_m=REAR_RANGE_M):
    """Le véhicule à l'ARRIÈRE de la navette (dans sa voie, derrière son pare-chocs arrière, à moins de
    `rear_range_m`) sur l'intervalle `span` : présence, écart minimal (pare-chocs à pare-chocs), TTC
    minimal (`observed_ttc`) et son écart, écart moyen."""
    lengths, widths = lengths or {}, widths or {}
    t_a, t_b = span
    best = {}                              # instant arrondi → (écart, ttc) du plus proche derrière
    for gid, obs in vehicles.items():
        if gid in exclude:
            continue
        for o in obs:
            if not (t_a <= o[0] <= t_b):
                continue
            s, lat, _tan = shuttle.path.project(o[1], o[2])
            if abs(lat) > lane_w / 2:
                continue
            length = lengths.get(o[5], VEHICLE_LENGTH_M)
            gap = shuttle.s_rear_at(o[0]) - s - length / 2
            if gap < -0.5 or gap > rear_range_m:
                continue
            ttc = observed_ttc(o[0], shuttle.footprint_state(o[0]),
                               (*o[1:5], length, widths.get(o[5], VEHICLE_WIDTH_M)))
            key = round(o[0], 1)
            if key not in best or gap < best[key][0]:
                best[key] = (max(gap, 0.0), ttc)
    if not best:
        return {'rear_present': False, 'rear_min_gap_m': None, 'rear_ttc_min_s': None,
                'rear_ttc_min_gap_m': None, 'rear_mean_gap_m': None}
    gaps = [g for g, _ in best.values()]
    ttcs = [(t, g) for g, t in best.values() if t is not None]
    return {'rear_present': True, 'rear_min_gap_m': _round(min(gaps)),
            'rear_ttc_min_s': _round(min(ttcs)[0]) if ttcs else None,
            'rear_ttc_min_gap_m': _round(min(ttcs)[1]) if ttcs else None,
            'rear_mean_gap_m': _round(sum(gaps) / len(gaps))}


def overtaking_rows(shuttle: ShuttleTrack, vehicles, *, parked=(), lane_w=LANE_WIDTH_M, lengths=None,
                    widths=None, min_obs=5, follow_mps=1.0):
    """Une ligne par DÉPASSEMENT : un véhicule non garé qui passe de derrière la navette à devant elle
    (il la double) ou de devant à derrière en roulant dans le même sens (la navette le double), à côté
    d'elle (hors de sa voie) au moment où il est à sa hauteur. Rabattement : il entre ensuite dans la
    voie de la navette devant elle — écart et TTC (la navette qui le rattrape) à ce moment.
    Repère INSTANTANÉ de la navette (`ShuttleTrack.relative`) : une session fait plusieurs tours."""
    lengths, widths = lengths or {}, widths or {}
    parked = set(parked)
    rows = []
    for gid, obs in vehicles.items():
        if gid in parked or len(obs) < min_obs:
            continue
        L = lengths.get(obs[0][5], VEHICLE_LENGTH_M)
        W = widths.get(obs[0][5], VEHICLE_WIDTH_M)
        rel = []                              # (t, rel_long, lat, v_along, o)
        for o in obs:
            lon, lat, (ue, un) = shuttle.relative(o[0], o[1], o[2])
            rel.append((o[0], lon, lat, o[3] * ue + o[4] * un, o))
        clear = shuttle.half + L / 2 + 1.0    # devant / derrière : plus de recouvrement
        for k in range(1, len(rel)):
            a, b = rel[k - 1], rel[k]
            if not (a[1] < 0 <= b[1] or a[1] >= 0 > b[1]):
                continue
            if b[0] - a[0] > 3.0:
                continue                      # un trou : pas une traversée observée
            if abs(b[2]) <= lane_w / 2 or b[3] < follow_mps:
                continue                      # dans la voie de la navette, ou ne roule pas dans son sens
            passes_shuttle = a[1] < 0
            before = [r for r in rel[:k] if (r[1] <= -clear if passes_shuttle else r[1] >= clear)]
            after = [r for r in rel[k:] if (r[1] >= clear if passes_shuttle else r[1] <= -clear)]
            if not before or not after:
                continue
            t_start, t_end = before[-1][0], after[0][0]
            # écart latéral entre les deux caisses quand ils se recouvrent
            alongside = [r for r in rel if t_start <= r[0] <= t_end and abs(r[1]) < shuttle.half + L / 2]
            lateral = (min(abs(r[2]) for r in alongside) - shuttle.width / 2 - W / 2) if alongside else None
            if lateral is None or lateral > OVERTAKE_LATERAL_MAX_M:
                continue                      # jamais à côté d'elle : une autre route, pas un dépassement
            sh_v = shuttle.speed(b[0])
            row = {
                'id': gid, 'class_name': obs[0][5],
                'direction': 'vehicle_overtakes_shuttle' if passes_shuttle else 'shuttle_overtakes_vehicle',
                'side': 'left' if b[2] < 0 else 'right',
                't_start_s': _round(t_start), 't_alongside_s': _round(b[0]), 't_end_s': _round(t_end),
                'duration_s': _round(t_end - t_start),
                'lateral_gap_min_m': _round(lateral),
                'relative_speed_kmh': _round((b[3] - sh_v) * 3.6, 1),
                'vehicle_speed_kmh': _round(b[3] * 3.6, 1), 'shuttle_speed_kmh': _round(sh_v * 3.6, 1),
                'vmax_kmh': _round(max(_robust([r[0] for r in rel],
                                               [math.hypot(r[4][3], r[4][4]) for r in rel])) * 3.6, 1),
                'cut_in': False, 'cut_in_t_s': None, 'cut_in_gap_m': None, 'cut_in_ttc_min_s': None,
            }
            if passes_shuttle:
                # rabattement : entré dans la voie de la navette, devant elle, après l'avoir doublée
                for r in rel:
                    if r[0] <= t_end or abs(r[2]) > lane_w / 2:
                        continue
                    gap = r[1] - shuttle.half - L / 2
                    if gap < -0.5:
                        continue
                    row.update({'cut_in': True, 'cut_in_t_s': _round(r[0]), 'cut_in_gap_m': _round(max(gap, 0.0))})
                    after_cut = [q for q in rel if r[0] <= q[0] <= r[0] + 5.0 and abs(q[2]) <= lane_w / 2]
                    ttcs = [v for v in _robust([q[0] for q in after_cut],
                                               [observed_ttc(q[0], shuttle.footprint_state(q[0]), (*q[4][1:5], L, W))
                                                for q in after_cut]) if v is not None]
                    row['cut_in_ttc_min_s'] = _round(min(ttcs)) if ttcs else None
                    break
            # TTC OBSERVÉ pendant le dépassement et les 5 s qui suivent (rabattement compris)
            span = [r for r in rel if t_start <= r[0] <= t_end + 5]
            ttc = [v for v in _robust([r[0] for r in span],
                                      [observed_ttc(r[0], shuttle.footprint_state(r[0]), (*r[4][1:5], L, W))
                                       for r in span]) if v is not None]
            row['ttc_min_s'] = _round(min(ttc)) if ttc else None
            rows.append(row)
            break                             # un dépassement par véhicule et par traversée observée
    rows.sort(key=lambda r: r['t_alongside_s'])
    return rows


# ── FunctionSpec : les deux tableaux depuis des tables d'observations ─────────────────────────
def _vehicles_from_frame(df):
    out = {}
    for gid, g in df.sort_values('t').groupby('id', sort=False):
        out[gid] = [(r.t, r.e, r.n, r.ve, r.vn, getattr(r, 'class_name', 'car'),
                     getattr(r, 'ttc', None), getattr(r, 'pet', None)) for r in g.itertuples(index=False)]
    return out


def vehicle_interaction_frames(shuttle: TypedFrame, observations: TypedFrame, *, lane_width_m=LANE_WIDTH_M):
    """Wrapper FunctionSpec : trajectoire navette (t, e, n, heading) + observations par véhicule → tableau
    des dépassements (les fenêtres d'intersection sont propres à l'app : `insertion_rows` s'appelle
    directement)."""
    import pandas as pd
    sh = shuttle.df[['t', 'e', 'n', 'heading']].to_numpy()
    rows = overtaking_rows(ShuttleTrack(sh), _vehicles_from_frame(observations.df), lane_w=lane_width_m)
    return TypedFrame(pd.DataFrame(rows), DataType.TABLE, meta={'overtakes': len(rows)})


SPEC = register(FunctionSpec(
    key='shuttle_overtakes',
    name='Dépassements de la navette',
    description="Une ligne par dépassement, dans le repère de la trajectoire de la navette : un véhicule qui "
                "passe de derrière elle à devant elle (ou l'inverse en roulant dans son sens), à côté de sa "
                "voie — côté, instants (début, à hauteur, fin), écart latéral minimal, vitesses, et "
                "rabattement dans sa voie devant elle (écart, TTC). Les insertions aux intersections "
                "(`insertion_rows`) suivent le même repère.",
    category=FunctionCategory.TRANSFORM,
    tags=['driving', 'interactions', 'overtaking', 'ttc'],
    inputs=[
        PortSpec('shuttle', DataType.TABLE, required_fields=['t', 'e', 'n', 'heading'],
                 description="Trajectoire de la navette (centre arrière), repère local en mètres."),
        PortSpec('observations', DataType.TABLE, required_fields=['id', 't', 'e', 'n', 've', 'vn'],
                 description="Observations des véhicules : identifiant, instant, position et vitesse monde."),
    ],
    outputs=[
        PortSpec('overtakes', DataType.TABLE,
                 produced_fields=['id', 'direction', 'side', 't_start_s', 't_alongside_s', 't_end_s',
                                  'lateral_gap_min_m', 'relative_speed_kmh', 'cut_in', 'cut_in_gap_m'],
                 description="Un dépassement par ligne."),
    ],
    params=[
        ParamSpec('lane_width_m', 'float', LANE_WIDTH_M, 2.5, 5.0, unit='m',
                  description="Largeur d'une voie."),
    ],
    cost={'cpu_bound': True},
    fn=vehicle_interaction_frames,
))
