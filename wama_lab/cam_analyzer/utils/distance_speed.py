"""
Phase 4 — distance / vitesse / TTC par détection.

Modèle pinhole simple, sans calibration externe : on assume un FoV
vertical par caméra et une hauteur réelle par classe d'objet.

  distance_m = (real_height_m * focal_y_px) / bbox_height_px
  focal_y_px = frame_height / (2 * tan(fov_v / 2))

Pour la vitesse : on garde le dernier frame de chaque track_id et on
calcule Δdistance / Δt. Le signe indique l'approche (-) ou l'éloignement
(+) ; TTC = -distance / vitesse_relative quand vitesse < 0, sinon None.

Quand la navette possède une vitesse GPS, on retranche pour obtenir la
vitesse absolue de l'objet (utile pour les conflits Phase 5).
"""
from __future__ import annotations

import math
from typing import Optional

# Hauteur réelle moyenne (mètres) par classe COCO/BDD utile au shuttle
CLASS_REAL_HEIGHT_M = {
    'person': 1.7, 'pedestrian': 1.7,
    'bicycle': 1.4, 'motorcycle': 1.4, 'motor': 1.4,
    'car': 1.5, 'voiture': 1.5,
    'bus': 3.2, 'truck': 3.0, 'camion': 3.0,
    'rider': 1.7,
}

# FoV vertical par caméra (degrés). Approximations Navya — à raffiner.
DEFAULT_FOV_V_DEG = {
    'front': 60.0, 'rear': 60.0, 'left': 90.0, 'right': 90.0,
}


def pinhole_distance(
    bbox: list,
    class_name: str,
    frame_height: int,
    fov_v_deg: float = 60.0,
) -> Optional[float]:
    """Estimate distance to object foot via pinhole + reference height."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4 or frame_height <= 0:
        return None
    bbox_h = bbox[3] - bbox[1]
    if bbox_h <= 1:
        return None
    h_real = CLASS_REAL_HEIGHT_M.get((class_name or '').lower())
    if not h_real:
        return None
    fov_rad = math.radians(fov_v_deg)
    focal_y = frame_height / (2.0 * math.tan(fov_rad / 2.0))
    return round((h_real * focal_y) / bbox_h, 2)


class TrackKinematics:
    """
    Maintains last-known (timestamp, distance) per track_id to derive
    relative speed and TTC. Reset between cameras.
    """
    def __init__(self):
        self._prev: dict[int, tuple[float, float]] = {}

    def update(self, track_id, timestamp: float, distance_m: float) -> dict:
        """
        Returns {'relative_speed_kmh': float|None, 'ttc_s': float|None}.
        relative_speed_kmh : positive = approaching (distance shrinking).
        """
        prev = self._prev.get(track_id)
        rel_speed_kmh = None
        ttc_s = None
        if prev is not None:
            t0, d0 = prev
            dt = timestamp - t0
            if dt > 0.05:  # ignore sub-50ms ticks (jitter)
                v_mps = (d0 - distance_m) / dt  # positive when approaching
                rel_speed_kmh = round(v_mps * 3.6, 1)
                if v_mps > 0.5 and distance_m > 0:
                    ttc_s = round(distance_m / v_mps, 2)
        self._prev[track_id] = (timestamp, distance_m)
        return {
            'relative_speed_kmh': rel_speed_kmh,
            'ttc_s': ttc_s,
        }


def annotate_detections_with_distance(
    detections: list,
    frame_height: int,
    fov_v_deg: float,
    timestamp: float,
    kinematics: TrackKinematics,
) -> None:
    """Mutate detections in place, adding distance_m / rel_speed / ttc_s."""
    for det in detections:
        bbox = det.get('bbox')
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        d = pinhole_distance(bbox, det.get('class_name', ''), frame_height, fov_v_deg)
        if d is None:
            continue
        det['distance_m'] = d
        track_id = det.get('track_id')
        if track_id is not None:
            k = kinematics.update(track_id, timestamp, d)
            if k['relative_speed_kmh'] is not None:
                det['relative_speed_kmh'] = k['relative_speed_kmh']
            if k['ttc_s'] is not None:
                det['ttc_s'] = k['ttc_s']
