"""
Phase 3e — ego-pose de la navette (position, cap, vitesse) pour la carte.

Sources hiérarchisées (cf. CAM_ANALYZER_DISTANCE_DESIGN.md §1quater) :
  1. **API navette** (orientation/speed/driving_direction) — prioritaire SI présente
     (donne le cap même à l'arrêt). Absente du jeu ENA_CASA.
  2. **GPS + accéléromètre** (fallback ENA_CASA). Cap = cap GPS (course) en mouvement,
     tenu au dernier connu à l'arrêt (aucun gyroscope logué).

Parsing propre = les **CSV par canal** de `RecFile_Data/` (`sample_ts_µs;valeur`, `;`) —
plus fiable que le `.rec` monolithique. Horodatage = microsecondes depuis le début de
session ; on le convertit en secondes (aligné avec les timestamps vidéo).

Pur (math + stdlib), testable hors Django, sans dépendance lourde.
"""
from __future__ import annotations

import glob
import logging
import math
import os
from bisect import bisect_left
from typing import Optional

logger = logging.getLogger(__name__)


# ── Parsing des CSV par canal ─────────────────────────────────────────

def _read_scalar_csv(path: str) -> list[tuple[float, float]]:
    """`sample_ts_µs;valeur` → [(ts_s, valeur), ...] triés par ts."""
    out = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(';')
            if len(parts) < 2:
                continue
            try:
                ts = float(parts[0]) / 1e6
                val = float(parts[1])
            except ValueError:
                continue
            out.append((ts, val))
    out.sort(key=lambda p: p[0])
    return out


def _find_channel(rec_dir: str, suffix: str) -> Optional[str]:
    """Trouve `…_<suffix>.csv` dans un dossier RecFile_Data."""
    hits = glob.glob(os.path.join(rec_dir, f'*_{suffix}.csv'))
    return hits[0] if hits else None


def parse_accel(rec_dir: str) -> list[dict]:
    """
    Fusionne les 3 CSV Accel_Sensor X/Y/Z (mêmes sample_ts) → [{ts, ax, ay, az}] (g).
    Les axes partagent l'horodatage d'échantillon ; on aligne par ts arrondi.
    """
    axes = {}
    for ax_name, suffix in (('ax', 'Accel_Sensor_X_axis'),
                            ('ay', 'Accel_Sensor_Y_axis'),
                            ('az', 'Accel_Sensor_Z_axis')):
        path = _find_channel(rec_dir, suffix)
        axes[ax_name] = dict((round(ts, 6), v) for ts, v in _read_scalar_csv(path)) if path else {}
    all_ts = sorted(set().union(*[set(d.keys()) for d in axes.values()]))
    out = []
    for ts in all_ts:
        out.append({
            'ts': ts,
            'ax': axes['ax'].get(ts),
            'ay': axes['ay'].get(ts),
            'az': axes['az'].get(ts),
        })
    return out


def parse_gps_position(rec_dir: str) -> list[dict]:
    """`…_oPosition.csv` (`ts;lat;lon[;alt;…]`) → [{ts, lat, lon}] trié."""
    path = _find_channel(rec_dir, 'GPS_NMEA0183_3_oPosition')
    if not path:
        return []
    out = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            parts = line.strip().split(';')
            if len(parts) < 3:
                continue
            try:
                out.append({'ts': float(parts[0]) / 1e6,
                            'lat': float(parts[1]),
                            'lon': float(parts[2])})
            except ValueError:
                continue
    out.sort(key=lambda p: p['ts'])
    return out


# ── Cap & vitesse depuis le GPS ───────────────────────────────────────

_EARTH_R = 6_371_000.0


def _bearing(lat1, lon1, lat2, lon2) -> float:
    """Cap initial (deg, 0=Nord, sens horaire) du segment 1→2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def annotate_gps_heading_speed(gps: list[dict], min_move_m: float = 0.30) -> list[dict]:
    """
    Ajoute `speed_kmh` et `heading` (deg) à chaque point GPS.

    Cap indéfini à l'arrêt (déplacement < `min_move_m`) → **tenu au dernier connu**
    (aucun gyroscope). Vitesse = distance/temps entre fixes.
    """
    last_heading = None
    for i, pt in enumerate(gps):
        if i == 0:
            pt['speed_kmh'] = 0.0
            pt['heading'] = None
            continue
        prev = gps[i - 1]
        dt = pt['ts'] - prev['ts']
        d = _haversine_m(prev['lat'], prev['lon'], pt['lat'], pt['lon'])
        pt['speed_kmh'] = (d / dt * 3.6) if dt > 1e-6 else 0.0
        if d >= min_move_m:
            last_heading = _bearing(prev['lat'], prev['lon'], pt['lat'], pt['lon'])
        pt['heading'] = last_heading      # tenu au dernier connu à l'arrêt
    return gps


class EgoPose:
    """
    Trajectoire ego interrogeable par timestamp. Priorité aux données API navette
    (`api_track` : [{ts, lat, lon, heading, speed_kmh, driving_direction}]) si
    fournies (cap fiable même à l'arrêt), sinon GPS annoté + accel.
    """

    def __init__(self, gps: Optional[list] = None, accel: Optional[list] = None,
                 api_track: Optional[list] = None):
        self.accel = accel or []
        if api_track:
            self.track = sorted(api_track, key=lambda p: p['ts'])
            self.source = 'shuttle_api'
        else:
            self.track = annotate_gps_heading_speed(gps or [])
            self.source = 'gps'
        self._ts = [p['ts'] for p in self.track]

    @classmethod
    def from_recfile_dir(cls, rec_dir: str) -> 'EgoPose':
        return cls(gps=parse_gps_position(rec_dir), accel=parse_accel(rec_dir))

    def at(self, ts: float) -> Optional[dict]:
        """Pose la plus proche du timestamp `ts` (s)."""
        if not self.track:
            return None
        i = bisect_left(self._ts, ts)
        if i == 0:
            return self.track[0]
        if i >= len(self.track):
            return self.track[-1]
        before, after = self.track[i - 1], self.track[i]
        return before if (ts - before['ts']) <= (after['ts'] - ts) else after


# ── Filtre de trajectoire navette (⚑ shuttle_filter, 2026-09-05) ─────────────────────
# Patron « calculer, stocker, basculer sans recalculer » : le filtre est un CALCUL (CPU,
# rejouable) qui écrit `results_summary['shuttle_filter']` ; la bascule ne fait que choisir,
# à la lecture, entre la trace brute et la trace filtrée — côté serveur via
# `effective_gps_track`, côté JS via `_applyShuttleFilter` au même point d'ingestion unique.

# ── Accéléromètre : convention d'axes du rig ──────────────────────────
# MESURÉ le 2026-09-10 sur la session P97 (`CAM_ANALYZER_CHAINE §D.4 ①`), par TROIS
# discriminants indépendants réclamant chacun un axe DIFFÉRENT — c'est la contre-épreuve :
#   `ax` longitudinal (r=+0,57 avec dv/dt Doppler, ~0 avec v·ω) → AXE AVANT, signe +
#   `ay` latéral      (r=−0,44 avec v·ω, ~0 avec dv/dt)
#   `az` vertical     (moyenne +0,938 g = la gravité)
# Rien ne déclarait cette correspondance : les CSV nomment les VOIES DU CAPTEUR (X/Y/Z), pas
# le repère du véhicule, et `parse_accel` ne fait que renommer des suffixes de fichiers.
# ⚠ Ces constantes valent pour LE RIG de ces enregistrements. Un autre montage les invalide —
# le jour où un 2ᵉ rig entre, elles se déclarent par profil, pas ici (elles ne sont pas une
# propriété du code mais de l'installation physique).
IMU_FORWARD_AXIS = 'ax'
IMU_FORWARD_SIGN = 1.0
#: g pour convertir l'accéléromètre (exprimé en g dans les CSV) en m/s².
_G = 9.80665
#: Fenêtre de moyenne glissante (échantillons à 10 Hz) : ~0,5 s, l'ordre de grandeur de
#: l'intervalle entre deux fixes GPS — on donne au filtre une accélération de la MÊME bande
#: passante que ce qu'il propage, pas la vibration de caisse à 10 Hz.
_LISSAGE_ECH = 5


def longitudinal_accel_series(session):
    """`session.imu_track` → `(callable(t) -> a en m/s², infos)` ou `(None, raison)`.

    Le biais est estimé À L'ARRÊT, pas sur toute la trace : un accéléromètre monté avec
    ~1° d'assiette lit en permanence g·sin(assiette) sur son axe avant, et c'est exactement
    ce qu'on mesure quand le véhicule NE BOUGE PAS. La navette étant à l'arrêt 77 % du temps
    (mesuré, `§D.4 ⑤`), l'estimation est abondante — et elle vaut mieux qu'une moyenne
    globale, qui absorberait aussi les accélérations réelles.
    """
    imu = session.imu_track or []
    if len(imu) < 10:
        return None, 'aucun échantillon IMU'
    ts, va = [], []
    for p in imu:
        v = p.get(IMU_FORWARD_AXIS)
        if p.get('ts') is None or v is None:
            continue
        ts.append(float(p['ts']))
        va.append(IMU_FORWARD_SIGN * float(v) * _G)
    if len(ts) < 10:
        return None, f'axe {IMU_FORWARD_AXIS} absent des échantillons'

    # Moyenne glissante centrée (bande passante alignée sur le pas de propagation).
    n, demi = len(va), _LISSAGE_ECH // 2
    cum = [0.0]
    for v in va:
        cum.append(cum[-1] + v)
    lisse = []
    for i in range(n):
        a, b = max(0, i - demi), min(n, i + demi + 1)
        lisse.append((cum[b] - cum[a]) / (b - a))

    # Biais à l'arrêt : médiane de l'accélération lue là où la vitesse GPS est quasi nulle.
    arret = []
    gt = [p for p in (session.gps_track or [])
          if p.get('ts') is not None and p.get('speed_kmh') is not None]
    if gt:
        gt.sort(key=lambda p: p['ts'])
        g_ts = [float(p['ts']) for p in gt]
        for i, t in enumerate(ts):
            k = min(bisect_left(g_ts, t), len(gt) - 1)
            if float(gt[k]['speed_kmh']) < 1.8:        # < 0,5 m/s
                arret.append(lisse[i])
    source = 'arrêt'
    if len(arret) < 50:
        arret, source = list(lisse), 'trace entière (arrêts trop rares)'
    arret.sort()
    biais = arret[len(arret) // 2]

    def _at(t):
        k = bisect_left(ts, t)
        if k <= 0:
            return lisse[0] - biais
        if k >= len(ts):
            return lisse[-1] - biais
        t0, t1 = ts[k - 1], ts[k]
        if t1 <= t0:
            return lisse[k] - biais
        w = (t - t0) / (t1 - t0)
        return (lisse[k - 1] * (1 - w) + lisse[k] * w) - biais

    return _at, {'n': len(ts), 'bias_ms2': round(biais, 4), 'bias_source': source,
                 'axis': IMU_FORWARD_AXIS, 'sign': IMU_FORWARD_SIGN}


def compute_shuttle_filter(session):
    """Filtre `session.gps_track` (brique pure `driving.ego_trajectory_filter`) et PERSISTE
    le résultat dans `results_summary['shuttle_filter'] = {'track': [...], 'report': {...}}`.

    `track` ne porte que les champs filtrés + `ts` (la trace brute reste `gps_track`, seule
    source de vérité) ; `report` = l'A/B chiffré (déplacement RMS brut→filtré, écart de cap
    médian, part de cap tenu). Retourne le rapport.
    """
    from wama_data.functions.driving.ego_trajectory_filter import filter_gps_points
    gt = session.gps_track or []
    accel, infos = None, None
    try:
        from .features import enabled
        if enabled(session, 'imu_command'):
            accel, infos = longitudinal_accel_series(session)
            if accel is None:
                logger.info('[shuttle_filter] ⚑ imu_command ON mais inutilisable : %s', infos)
    except Exception:
        logger.debug('commande IMU indisponible (non bloquant)', exc_info=True)
        accel = None
    enriched, report = filter_gps_points(gt, accel_long=accel)
    if accel is not None and isinstance(infos, dict):
        report['imu'] = infos
        logger.info('[shuttle_filter] ⚑ imu_command ON · axe %s%s · biais %+.3f m/s² (%s) · '
                    'déplacement médian %s m (p95 %s) · Δvitesse médiane %s km/h',
                    '+' if infos['sign'] > 0 else '-', infos['axis'], infos['bias_ms2'],
                    infos['bias_source'], report.get('command_shift_median_m'),
                    report.get('command_shift_p95_m'),
                    report.get('command_speed_delta_median_kmh'))
    track = [{'ts': p.get('ts'), 'lat_f': p['lat_f'], 'lon_f': p['lon_f'],
              'heading_f': p.get('heading_f'), 'speed_f_kmh': p.get('speed_f_kmh'),
              'heading_f_held': bool(p.get('heading_f_held'))}
             for p in enriched if p.get('lat_f') is not None]
    rs = session.results_summary or {}
    rs['shuttle_filter'] = {'track': track, 'report': report}
    session.results_summary = rs
    session.save(update_fields=['results_summary'])
    return report


def effective_gps_track(session):
    """Trace navette EFFECTIVE pour le POSITIONNEMENT — point d'accès UNIQUE côté serveur.

    ⚑ `shuttle_filter` ON et calcul présent → trace dont `lat`/`lon`/`heading` sont les valeurs
    FILTRÉES (les brutes restent en `*_raw`, et `heading_held` dit si le cap est tenu — ce
    qu'un consommateur comme `yaw_disagreement` doit savoir). Sinon → `gps_track` tel quel.
    La bascule est relue à CHAQUE appel : OFF ⇒ brut même si un calcul traîne en base, sinon
    l'A/B mentirait (même règle que `_applyOrthoCorrection`).

    Consommateurs = ceux qui POSITIONNENT (tracker, prédiction, calibration sol, marquages,
    branches, artefacts). Les fenêtres d'intersection et la couverture restent sur le brut :
    elles délimitent l'ANALYSE, pas une position — les filtrer invaliderait la couverture.
    """
    gt = session.gps_track or []
    try:
        from .features import enabled
        if not enabled(session, 'shuttle_filter'):
            return gt
    except Exception:
        return gt
    rows = ((session.results_summary or {}).get('shuttle_filter') or {}).get('track') or []
    if not rows:
        return gt
    by_ts = {round(float(r['ts']), 4): r for r in rows if r.get('ts') is not None}
    out = []
    for p in gt:
        f = by_ts.get(round(float(p['ts']), 4)) if p.get('ts') is not None else None
        if not f or f.get('lat_f') is None:
            out.append(p)
            continue
        q = dict(p)
        q['lat_raw'], q['lon_raw'], q['heading_raw'] = p.get('lat'), p.get('lon'), p.get('heading')
        q['lat'], q['lon'] = f['lat_f'], f['lon_f']
        if f.get('heading_f') is not None:
            q['heading'] = f['heading_f']
        q['heading_held'] = bool(f.get('heading_f_held'))
        out.append(q)
    return out
