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
import math
import os
from bisect import bisect_left
from typing import Optional


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
