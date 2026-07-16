"""
Phase 4 — distance / vitesse / TTC par détection.

Modèle pinhole simple, sans calibration externe : on assume un FoV
vertical par caméra et une hauteur réelle par classe d'objet.

  distance_m = (real_height_m * focal_y_px) / bbox_height_px
  focal_y_px = frame_height / (2 * tan(fov_v / 2))

── Vitesse / TTC : filtrage AVANT dérivation ─────────────────────────
La distance pinhole est cohérente en niveau mais bruitée frame-à-frame :
`distance ∝ 1 / bbox_height`, donc un jitter de 1 px sur la bbox d'un
objet lointain déplace la distance de plusieurs mètres. Dériver cette
distance par différence entre deux frames consécutives amplifie ce bruit
en vitesses aberrantes (des centaines de km/h), et le TTic en hérite.

On corrige SANS toucher aux distances affichées :
  1. lissage EMA de la distance, en INTERNE seulement (`distance_m`
     persistée reste la mesure pinhole brute, jugée cohérente) ;
  2. clamp des sauts bruts physiquement impossibles (ID-switch, glitch
     de bbox) avant lissage ;
  3. vitesse = pente d'une régression moindres-carrés sur une courte
     fenêtre temporelle (≈0,6 s) au lieu d'une différence à 2 points →
     débruite la dérivée ;
  4. rejet des vitesses relatives hors plage plausible (usager de la
     route vs navette lente) : on préfère `None` à une valeur fausse.

Le signe de la vitesse indique l'approche (+) ou l'éloignement (-) ;
TTC = distance / vitesse_relative quand l'objet approche, sinon None.

Quand la navette possède une vitesse GPS, on retranche pour obtenir la
vitesse absolue de l'objet (utile pour les conflits Phase 5).
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional

# Hauteur réelle moyenne (mètres) par classe COCO/BDD utile au shuttle
CLASS_REAL_HEIGHT_M = {
    'person': 1.7, 'pedestrian': 1.7,
    'bicycle': 1.4, 'motorcycle': 1.4, 'motor': 1.4,
    'car': 1.5, 'voiture': 1.5,
    'bus': 3.2, 'truck': 3.0, 'camion': 3.0,
    'rider': 1.7,
}

# FoV vertical par caméra (degrés) — VALEURS RÉELLES du rig ENA (audit 2026-07-16,
# schéma claude/ENA_Installation + specs AXIS) : avant/arrière AXIS F4005-E 110°H/61°V,
# latérales AXIS F1015 vari-focale ~55°H → ~31°V (table constructeur 97-52°H ↔ 53-30°V).
# ⚠ Les anciennes valeurs (60/60/90/90) sous-estimaient les distances latérales ×3,6 ;
# les sessions annotées avec elles sont corrigées à l'affichage via LEGACY_FOV_V +
# config['fov_v_used'] (prediction_adapter.camera_geometry).
DEFAULT_FOV_V_DEG = {
    'front': 61.0, 'rear': 61.0, 'left': 31.0, 'right': 31.0,
}

# ── Paramètres du filtrage vitesse/TTC ────────────────────────────────
# Lissage EMA de la distance (interne). alpha bas = plus lisse / plus de
# latence ; 0.35 amortit le jitter sans traîner sur les vraies variations.
_EMA_ALPHA = 0.35
# Fenêtre glissante de régression pour estimer la pente d/dt (secondes).
_SPEED_WINDOW_S = 0.6
# Baseline temporelle minimale avant d'émettre une vitesse (secondes) :
# sous ce seuil la pente est trop bruitée pour être fiable.
_MIN_SPEED_BASELINE_S = 0.25
# Profondeur d'historique par track (bornée : ~fenêtre × fps max utile).
_MAX_HISTORY = 20
# Vitesse relative plausible d'un usager de la route vis-à-vis d'une
# navette lente (km/h). Au-delà = glitch de mesure → on rejette (None).
_MAX_REL_SPEED_KMH = 130.0
# Vitesse d'approche minimale (m/s) pour calculer un TTC (évite les TTC
# géants issus d'un quasi-arrêt bruité).
_MIN_APPROACH_MPS = 0.5


def _linreg_slope(points: list) -> float:
    """Pente moindres-carrés de distance(t) sur `points` = [(t, d), …].

    Retourne d(distance)/dt en m/s (positif = objet qui s'éloigne).
    """
    n = len(points)
    t0 = points[0][0]
    xs = [t - t0 for t, _ in points]
    ys = [d for _, d in points]
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 1e-9:
        return 0.0
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return num / den


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
    Derives a debounced relative speed + TTC per track_id from the noisy
    pinhole distance signal. Reset between cameras (track_id collisions
    between cameras would otherwise pollute each other's history).

    Per track we keep a short history of EMA-smoothed (timestamp,
    distance) samples and fit a least-squares slope over the last
    `_SPEED_WINDOW_S`. Smoothing + windowed regression is what tames the
    frame-to-frame differentiation noise; the raw distance is NOT altered
    here — only the internal copy used to derive the speed.
    """
    def __init__(self):
        # track_id -> last EMA-smoothed distance (m)
        self._smooth: dict[int, float] = {}
        # track_id -> deque[(timestamp, smoothed_distance)]
        self._hist: dict[int, deque] = {}

    def update(self, track_id, timestamp: float, distance_m: float) -> dict:
        """
        Returns {'relative_speed_kmh': float|None, 'ttc_s': float|None}.
        relative_speed_kmh : positive = approaching (distance shrinking).
        Values are None until enough baseline is accumulated, or when the
        estimate is physically implausible (rejected rather than emitted).
        """
        prev_s = self._smooth.get(track_id)
        hist = self._hist.get(track_id)

        if prev_s is None or hist is None or not hist:
            # First sample for this track: seed, nothing to differentiate.
            d_s = distance_m
        else:
            dt = timestamp - hist[-1][0]
            d_in = distance_m
            if dt > 1e-3:
                # Clamp implausible single-step jumps (ID-switch / bbox
                # glitch) before they pollute the EMA and the regression.
                max_step = (_MAX_REL_SPEED_KMH / 3.6) * dt + 0.5  # m (+0.5 floor)
                delta = distance_m - prev_s
                if abs(delta) > max_step:
                    d_in = prev_s + math.copysign(max_step, delta)
            d_s = _EMA_ALPHA * d_in + (1.0 - _EMA_ALPHA) * prev_s

        self._smooth[track_id] = d_s
        if hist is None:
            hist = self._hist[track_id] = deque(maxlen=_MAX_HISTORY)
        hist.append((timestamp, d_s))

        rel_speed_kmh = None
        ttc_s = None

        # Regression window: recent samples within _SPEED_WINDOW_S.
        window = [(t, d) for (t, d) in hist if timestamp - t <= _SPEED_WINDOW_S]
        if len(window) >= 2:
            span = window[-1][0] - window[0][0]
            if span >= _MIN_SPEED_BASELINE_S:
                slope = _linreg_slope(window)   # d(distance)/dt, m/s
                v_mps = -slope                  # positive = approaching
                v_kmh = v_mps * 3.6
                if abs(v_kmh) <= _MAX_REL_SPEED_KMH:
                    rel_speed_kmh = round(v_kmh, 1)
                    if v_mps > _MIN_APPROACH_MPS and d_s > 0:
                        ttc_s = round(d_s / v_mps, 2)

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
