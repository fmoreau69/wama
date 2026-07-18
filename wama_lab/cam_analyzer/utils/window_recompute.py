"""
Recompute AnalysisSession.intersection_windows from the current
profile.intersections + session.gps_track.

This is the lightweight, GPU-free pass that runs synchronously each time
the user edits the profile's intersections (radius, position) so the
mini-map and the YOLO/SAM3 gating stay aligned with the saved profile,
without forcing a full re-analysis.
"""
from __future__ import annotations

import logging
from math import atan2, cos, degrees, radians, sin

logger = logging.getLogger(__name__)


def recompute_intersection_windows(session, profile=None) -> list[dict]:
    """
    Compute the windows list and persist it on the session.

    Returns the list of windows (also stored on session.intersection_windows).
    Returns [] when prerequisites are missing (no GPS, no intersections,
    profile not in intersection_insertion mode, etc.) — the session field is
    cleared in that case so the mini-map/gating don't keep stale data.
    """
    profile = profile or session.profile

    if not profile or profile.report_type != 'intersection_insertion':
        if session.intersection_windows:
            session.intersection_windows = []
            session.save(update_fields=['intersection_windows'])
        return []

    if not session.gps_track or not profile.intersections:
        if session.intersection_windows:
            session.intersection_windows = []
            session.save(update_fields=['intersection_windows'])
        return []

    from .intersection_analyzer import IntersectionAnalyzer

    raw_windows = IntersectionAnalyzer(
        intersections=profile.intersections,
        gps_track=session.gps_track,
        fps=12.0,
        frame_height=250,
    ).find_intersection_windows()

    # ── Conversion temps GPS → temps VIDÉO ──────────────────────────────────────
    # La piste GPS a sa propre base de temps (ts), reliée à la vidéo par
    # t_gps = t_vidéo × gps_time_scale + gps_time_offset. TOUS les consommateurs
    # d'intersection_windows (gating YOLO/SAM3, conflits, timeline, panneau
    # passages, tracker) comparent en temps VIDÉO — servir des fenêtres en temps
    # GPS décalait les zones proportionnellement au temps (scale 0,961 sur ENA :
    # ~20 s à 8 min, ~5 min en fin de session → passages ratés, segments à côté
    # des zones, saut « aller au passage » avant le centre — constat 2026-07-18).
    _scale = float(session.gps_time_scale or 1.0) or 1.0
    _off = float(session.gps_time_offset or 0.0)

    def _to_video(ts):
        return (ts - _off) / _scale

    windows: list[dict] = []
    for w in raw_windows:
        bearing = None
        gp = w.get('gps_points') or []
        if gp:
            h = gp[0].get('heading') if isinstance(gp[0], dict) else None
            if h is not None:
                bearing = float(h)
            elif len(gp) >= 2:
                p0, p1 = gp[0], gp[min(2, len(gp) - 1)]
                lat1, lon1 = radians(p0['lat']), radians(p0['lon'])
                lat2, lon2 = radians(p1['lat']), radians(p1['lon'])
                dlon = lon2 - lon1
                x = sin(dlon) * cos(lat2)
                y = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
                bearing = (degrees(atan2(x, y)) + 360.0) % 360.0

        windows.append({
            'name': w['intersection'].get('name', ''),
            'lat': w['intersection'].get('lat'),
            'lon': w['intersection'].get('lon'),
            'radius_m': w['intersection'].get('radius_m'),
            't_enter': round(_to_video(w['t_enter']), 2),
            't_exit': round(_to_video(w['t_exit']), 2),
            't_closest': round(_to_video(w.get('t_closest', (w['t_enter'] + w['t_exit']) / 2)), 2),
            'min_distance_m': w.get('min_distance_m'),
            'bearing_deg': round(bearing, 1) if bearing is not None else None,
        })

    session.intersection_windows = windows
    session.save(update_fields=['intersection_windows'])

    # Register the pass so the UI's pipeline panel reflects it
    try:
        from .pass_tracking import mark_completed, mark_started
        mark_started(session, 'intersection_windows', profile)
        mark_completed(session, 'intersection_windows', output_summary={
            'count': len(windows),
            'names': sorted({w.get('name', '') for w in windows}),
        })
    except Exception:
        logger.debug('intersection_windows pass tracking failed', exc_info=True)

    return windows
