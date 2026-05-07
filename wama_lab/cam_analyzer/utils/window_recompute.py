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
            't_enter': round(w['t_enter'], 2),
            't_exit': round(w['t_exit'], 2),
            't_closest': round(w.get('t_closest', (w['t_enter'] + w['t_exit']) / 2), 2),
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
