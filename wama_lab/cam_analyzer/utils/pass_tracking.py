"""
AnalysisPass helpers — register, complete, fail, and detect stale passes.

A pass is "stale" when its parameter snapshot no longer matches the
profile's current value of the watched parameters. When a pass becomes
stale, downstream passes (per the dependency graph) are also flipped to
stale so the UI shows the cascade clearly.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

# Watched profile parameters per pass — change → STALE.
# YOLO_DETECT does NOT watch target_classes / confidence (≥0.10) because
# inference stores all classes at conf=0.10; we filter at read time.
_WATCHED: dict[str, list[str]] = {
    'extraction': [],
    'intersection_windows': ['intersections'],
    'yolo_detect': ['model_path', 'iou_threshold', 'tracker'],
    'yolopv2_lanes': ['road_model_path'],
    'sam3_markings': ['sam3_markings_enabled', 'sam3_markings_prompts',
                      'sam3_as_road_fallback'],
    'lane_events': [],  # purely derivative of yolo_detect + yolopv2_lanes
    'temporal_segments': ['target_classes', 'confidence'],
    'distance': [],
    'conflicts': [],
}

# Dependency graph: if upstream is stale → downstream becomes stale.
_DEPENDS_ON: dict[str, list[str]] = {
    'extraction': [],
    'intersection_windows': ['extraction'],
    'yolo_detect': ['extraction'],
    'yolopv2_lanes': ['extraction'],
    'sam3_markings': ['extraction', 'intersection_windows'],
    'lane_events': ['yolo_detect', 'yolopv2_lanes'],
    'temporal_segments': ['yolo_detect', 'intersection_windows'],
    'distance': ['lane_events'],
    'conflicts': ['lane_events', 'distance'],
}


def _profile_snapshot(profile, watched_keys: list[str]) -> dict:
    """Capture the watched fields from the profile."""
    if profile is None:
        return {}
    return {k: getattr(profile, k, None) for k in watched_keys}


def mark_started(session, pass_type: str, profile=None) -> None:
    """Insert/update the pass row at status RUNNING and reset any prior error."""
    from wama_lab.cam_analyzer.models import AnalysisPass

    snapshot = _profile_snapshot(profile, _WATCHED.get(pass_type, []))
    obj, _ = AnalysisPass.objects.update_or_create(
        session=session,
        pass_type=pass_type,
        defaults={
            'status': AnalysisPass.Status.RUNNING,
            'parameters': snapshot,
            'started_at': timezone.now(),
            'completed_at': None,
            'duration_s': None,
            'error_message': '',
        },
    )
    return obj


def mark_completed(session, pass_type: str, *, output_summary: dict | None = None) -> None:
    from wama_lab.cam_analyzer.models import AnalysisPass

    try:
        obj = AnalysisPass.objects.get(session=session, pass_type=pass_type)
    except AnalysisPass.DoesNotExist:
        # mark_started may not have been called (e.g. legacy task path) —
        # create the row directly with whatever we have.
        obj = AnalysisPass(session=session, pass_type=pass_type)
        obj.started_at = timezone.now()
    now = timezone.now()
    obj.status = AnalysisPass.Status.COMPLETED
    obj.completed_at = now
    if obj.started_at:
        obj.duration_s = round((now - obj.started_at).total_seconds(), 2)
    if output_summary is not None:
        obj.output_summary = output_summary
    obj.error_message = ''
    obj.save()


def mark_failed(session, pass_type: str, error_message: str) -> None:
    from wama_lab.cam_analyzer.models import AnalysisPass

    AnalysisPass.objects.update_or_create(
        session=session,
        pass_type=pass_type,
        defaults={
            'status': AnalysisPass.Status.FAILED,
            'error_message': str(error_message)[:2000],
            'completed_at': timezone.now(),
        },
    )


def recompute_stale(session) -> int:
    """
    Recompute STALE flags for all passes of a session by comparing each
    pass's parameter snapshot to the profile's current values, then
    propagating staleness through the dependency graph.

    Returns the number of passes flipped (for logging).
    """
    from wama_lab.cam_analyzer.models import AnalysisPass

    profile = session.profile
    passes = list(AnalysisPass.objects.filter(session=session))
    by_type = {p.pass_type: p for p in passes}

    flipped = 0

    # First pass: direct snapshot mismatch on watched params.
    for p in passes:
        if p.status != AnalysisPass.Status.COMPLETED:
            continue
        watched = _WATCHED.get(p.pass_type, [])
        if not watched:
            continue
        current = _profile_snapshot(profile, watched)
        if current != (p.parameters or {}):
            p.status = AnalysisPass.Status.STALE
            p.save(update_fields=['status'])
            flipped += 1

    # Cascade: if upstream is STALE/FAILED/missing, downstream becomes stale.
    # Iterate until fixpoint (graph is small, max ~5 levels).
    changed = True
    while changed:
        changed = False
        for p in by_type.values():
            if p.status != AnalysisPass.Status.COMPLETED:
                continue
            for dep_type in _DEPENDS_ON.get(p.pass_type, []):
                dep = by_type.get(dep_type)
                if dep is None:
                    # Upstream never run → can't be sure downstream is fresh.
                    p.status = AnalysisPass.Status.STALE
                    p.save(update_fields=['status'])
                    flipped += 1
                    changed = True
                    break
                if dep.status in (AnalysisPass.Status.STALE,
                                   AnalysisPass.Status.FAILED):
                    p.status = AnalysisPass.Status.STALE
                    p.save(update_fields=['status'])
                    flipped += 1
                    changed = True
                    break
    return flipped


def get_passes_status(session) -> list[dict]:
    """Return a serialisable list of pass status dicts for the UI."""
    from wama_lab.cam_analyzer.models import AnalysisPass

    passes = AnalysisPass.objects.filter(session=session)
    by_type = {p.pass_type: p for p in passes}
    out = []
    # Order matters for UX (top-down through the pipeline)
    order = [
        AnalysisPass.PassType.EXTRACTION,
        AnalysisPass.PassType.INTERSECTION_WINDOWS,
        AnalysisPass.PassType.YOLO_DETECT,
        AnalysisPass.PassType.YOLOPV2_LANES,
        AnalysisPass.PassType.SAM3_MARKINGS,
        AnalysisPass.PassType.LANE_EVENTS,
        AnalysisPass.PassType.TEMPORAL_SEGMENTS,
        AnalysisPass.PassType.DISTANCE,
        AnalysisPass.PassType.CONFLICTS,
    ]
    for pt in order:
        p = by_type.get(pt.value)
        if p is None:
            out.append({
                'pass_type': pt.value,
                'label': pt.label,
                'status': 'never',
                'parameters': {},
                'output_summary': {},
                'completed_at': None,
                'duration_s': None,
                'error_message': '',
            })
        else:
            out.append({
                'pass_type': p.pass_type,
                'label': dict(AnalysisPass.PassType.choices).get(p.pass_type, p.pass_type),
                'status': p.status,
                'parameters': p.parameters or {},
                'output_summary': p.output_summary or {},
                'completed_at': p.completed_at.isoformat() if p.completed_at else None,
                'duration_s': p.duration_s,
                'error_message': p.error_message or '',
            })
    return out
