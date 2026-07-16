"""
Celery tasks for Cam Analyzer.
YOLO detection + tracking pipeline on multi-camera video sessions.
"""
import gc
import logging
import os
import time
from typing import Optional

import cv2
import torch
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone
from ultralytics import YOLO

from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)

# Classes COCO pouvant réellement interagir avec la navette à une intersection
# (s'insérer / attendre). Sert à écarter les faux positifs COCO (airplane,
# bird, boat…) du périmètre « véhicules d'intérêt ». Voir
# CAM_ANALYZER_DISTANCE_DESIGN.md §2.9.
ROAD_USER_CLASSES = {'person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck'}


# =============================================================================
# Helpers
# =============================================================================

def _console(user_id: int, message: str) -> None:
    """Send message to WAMA console."""
    try:
        push_console_line(user_id, f"[Cam Analyzer] {message}")
        logger.info(message)
    except Exception as e:
        logger.warning(f"Failed to push console line: {e}")


def set_session_progress(session_id: str, percent: float, status_message: str = None) -> None:
    """Update session progress in cache and DB."""
    from .models import AnalysisSession
    pct = max(0.0, min(100.0, float(percent)))
    cache.set(f"cam_analyzer_progress_{session_id}", pct, timeout=3600)
    if status_message:
        cache.set(f"cam_analyzer_status_{session_id}", status_message, timeout=3600)
    AnalysisSession.objects.filter(pk=session_id).update(progress=pct)


def stop_cam_analyzer(user_id: int) -> None:
    """Set cancellation flag for a user's running analysis."""
    # TTL long (= visibility_timeout Redis) : le flag doit SURVIVRE à la fenêtre de
    # re-livraison d'une tâche crashée, sinon une tâche SAM3 re-livrée après annulation
    # ne le verrait plus expiré et se relancerait. Toute vraie relance vide le flag
    # (run_passes/start_sam3), donc il ne bloque jamais un lancement légitime.
    cache.set(f"stop_cam_analyzer_{user_id}", True, timeout=21600)


def _is_cancelled(user_id: int) -> bool:
    """Check if cancellation was requested.

    Résiste à une panne Redis transitoire (ex. redémarrage du serveur pendant
    une tâche longue) : un blip ne doit pas tuer la tâche → on suppose « non
    annulé » plutôt que de propager la ConnectionError.
    """
    try:
        return bool(cache.get(f"stop_cam_analyzer_{user_id}", False))
    except Exception:
        return False


def _extract_detections(prediction, frame_height: int) -> list:
    """
    Extract detections from a YOLO Results object.
    Returns list of dicts with bbox, class info, track_id, proximity.
    """
    detections = []
    if not prediction.boxes or len(prediction.boxes) == 0:
        return detections

    for i, box in enumerate(prediction.boxes):
        bbox = box.xyxy[0].cpu().numpy().tolist()
        class_id = int(box.cls)
        class_name = prediction.names.get(class_id, str(class_id))
        confidence = float(box.conf)
        track_id = int(box.id) if hasattr(box, 'id') and box.id is not None else None

        # Proximity: ratio of bbox height to frame height
        bbox_height = bbox[3] - bbox[1]
        proximity = min(1.0, bbox_height / frame_height) if frame_height > 0 else 0.0

        detections.append({
            'class_id': class_id,
            'class_name': class_name,
            'confidence': round(confidence, 3),
            'bbox': [round(v, 1) for v in bbox],
            'track_id': track_id,
            'proximity': round(proximity, 3),
        })

    return detections


def _unload_model(model):
    """Release YOLO model and free GPU memory."""
    try:
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
    except Exception:
        pass


# =============================================================================
# Temporal Segment Detection (Phase 3)
# =============================================================================

def _merge_segments(segments, merge_gap: float = 1.0):
    """Merge segments that are closer than merge_gap seconds."""
    if len(segments) < 2:
        return segments

    merged = [segments[0]]
    for seg in segments[1:]:
        prev = merged[-1]
        if seg.start_time - prev.end_time <= merge_gap:
            # Merge: extend end_time, combine metadata
            prev.end_time = seg.end_time
            pm = prev.metadata
            sm = seg.metadata
            pm['max_proximity'] = max(pm.get('max_proximity', 0), sm.get('max_proximity', 0))
            # Weighted average proximity
            prev_dur = prev.end_time - prev.start_time
            seg_dur = seg.end_time - seg.start_time
            if prev_dur + seg_dur > 0:
                pm['avg_proximity'] = round(
                    (pm.get('avg_proximity', 0) * prev_dur + sm.get('avg_proximity', 0) * seg_dur)
                    / (prev_dur + seg_dur), 3)
        else:
            merged.append(seg)
    return merged


def _detect_close_following(session, camera, frames,
                            proximity_threshold=0.4, min_duration=2.0, merge_gap=1.0):
    """
    Detect close-following segments: sustained high proximity on a camera.
    Primarily relevant for rear camera but applied to all.
    """
    from .models import TemporalSegment

    segments = []
    current_start = None
    current_max_prox = 0.0
    prox_sum = 0.0
    prox_count = 0
    dominant_classes = {}

    for frame in frames:
        max_prox = max((d.get('proximity', 0) for d in frame.detections), default=0)

        if max_prox >= proximity_threshold:
            if current_start is None:
                current_start = frame.timestamp
            current_max_prox = max(current_max_prox, max_prox)
            prox_sum += max_prox
            prox_count += 1
            for d in frame.detections:
                if d.get('proximity', 0) >= proximity_threshold:
                    cls = d.get('class_name', 'unknown')
                    dominant_classes[cls] = dominant_classes.get(cls, 0) + 1
        else:
            if current_start is not None:
                duration = frame.timestamp - current_start
                if duration >= min_duration:
                    segments.append(TemporalSegment(
                        session=session, camera=camera,
                        segment_type='close_following',
                        start_time=round(current_start, 2),
                        end_time=round(frame.timestamp, 2),
                        metadata={
                            'max_proximity': round(current_max_prox, 3),
                            'avg_proximity': round(prox_sum / prox_count, 3) if prox_count else 0,
                            'dominant_class': max(dominant_classes, key=dominant_classes.get) if dominant_classes else '',
                        }
                    ))
            current_start = None
            current_max_prox = 0.0
            prox_sum = 0.0
            prox_count = 0
            dominant_classes = {}

    # Handle segment still open at end of video
    if current_start is not None and frames:
        last_ts = frames[len(frames) - 1].timestamp if hasattr(frames, '__getitem__') else current_start
        duration = last_ts - current_start
        if duration >= min_duration:
            segments.append(TemporalSegment(
                session=session, camera=camera,
                segment_type='close_following',
                start_time=round(current_start, 2),
                end_time=round(last_ts, 2),
                metadata={
                    'max_proximity': round(current_max_prox, 3),
                    'avg_proximity': round(prox_sum / prox_count, 3) if prox_count else 0,
                    'dominant_class': max(dominant_classes, key=dominant_classes.get) if dominant_classes else '',
                }
            ))

    return _merge_segments(segments, merge_gap)


def _detect_overtaking(session, camera, frames,
                       min_duration=1.0, min_proximity=0.15):
    """
    Detect overtaking segments: a tracked object traverses horizontally
    across left or right cameras.
    """
    from .models import TemporalSegment

    if camera.position not in ('left', 'right'):
        return []

    frame_width = camera.width or 1920

    # Track horizontal positions by track_id
    tracks = {}  # track_id -> [(timestamp, x_center, class_name, proximity)]
    for frame in frames:
        for d in frame.detections:
            tid = d.get('track_id')
            if tid is None:
                continue
            bbox = d.get('bbox', [0, 0, 0, 0])
            x_center = (bbox[0] + bbox[2]) / 2.0
            tracks.setdefault(tid, []).append((
                frame.timestamp,
                x_center,
                d.get('class_name', 'unknown'),
                d.get('proximity', 0),
            ))

    segments = []
    for tid, points in tracks.items():
        if len(points) < 2:
            continue

        duration = points[-1][0] - points[0][0]
        if duration < min_duration:
            continue

        max_prox = max(p[3] for p in points)
        if max_prox < min_proximity:
            continue

        # Check horizontal traversal: x-center range > 50% of frame width
        x_values = [p[1] for p in points]
        x_range = max(x_values) - min(x_values)
        if x_range < frame_width * 0.5:
            continue

        # Determine direction
        x_start = points[0][1]
        x_end = points[-1][1]
        direction = 'left_to_right' if x_end > x_start else 'right_to_left'

        # Most common class
        class_counts = {}
        for p in points:
            class_counts[p[2]] = class_counts.get(p[2], 0) + 1
        dominant_class = max(class_counts, key=class_counts.get)

        segments.append(TemporalSegment(
            session=session, camera=camera,
            segment_type='overtaking',
            start_time=round(points[0][0], 2),
            end_time=round(points[-1][0], 2),
            metadata={
                'track_id': tid,
                'direction': direction,
                'class_name': dominant_class,
                'max_proximity': round(max_prox, 3),
            }
        ))

    return segments


def _detect_crossing(session, camera, frames,
                     min_lateral_ratio=0.3, min_duration=0.5, max_duration=10.0):
    """
    Detect crossing segments: pedestrians/cyclists traversing laterally
    in front camera view.
    """
    from .models import TemporalSegment

    if camera.position != 'front':
        return []

    crossing_classes = {'person', 'bicycle', 'pedestrian'}
    frame_width = camera.width or 1920

    # Track lateral positions by track_id
    tracks = {}  # track_id -> [(timestamp, x_center, class_name)]
    for frame in frames:
        for d in frame.detections:
            cls = d.get('class_name', '').lower()
            if cls not in crossing_classes:
                continue
            tid = d.get('track_id')
            if tid is None:
                continue
            bbox = d.get('bbox', [0, 0, 0, 0])
            x_center = (bbox[0] + bbox[2]) / 2.0
            tracks.setdefault(tid, []).append((
                frame.timestamp, x_center, d.get('class_name', 'unknown')
            ))

    segments = []
    for tid, points in tracks.items():
        if len(points) < 2:
            continue

        duration = points[-1][0] - points[0][0]
        if duration < min_duration or duration > max_duration:
            continue

        # Check lateral traversal
        x_values = [p[1] for p in points]
        x_range = max(x_values) - min(x_values)
        if x_range < frame_width * min_lateral_ratio:
            continue

        segments.append(TemporalSegment(
            session=session, camera=camera,
            segment_type='crossing',
            start_time=round(points[0][0], 2),
            end_time=round(points[-1][0], 2),
            metadata={
                'track_id': tid,
                'class_name': points[0][2],
            }
        ))

    return segments


def _detect_intersection_insertion(session, camera, frames):
    """
    Detect vehicle insertions at intersections in front of the shuttle.

    Uses IntersectionAnalyzer with:
    - profile.intersections : known GPS coordinates of intersections
    - session.gps_track     : shuttle GPS telemetry (extracted from RTMaps or API CSV)
    - camera.position       : only 'front' camera is analyzed
    """
    if camera.position != 'front':
        return []

    from .models import TemporalSegment

    profile = session.profile
    if not profile:
        return []

    intersections = profile.intersections or []
    gps_track = session.gps_track or []

    if not intersections:
        logger.info("[intersection] No intersections configured in profile, skipping")
        return []

    if not gps_track:
        logger.info("[intersection] No GPS track in session, skipping")
        return []

    from .utils.intersection_analyzer import IntersectionAnalyzer

    analyzer = IntersectionAnalyzer(
        intersections=intersections,
        gps_track=gps_track,
        fps=camera.fps or 12.0,
        frame_height=camera.height or 250,
    )

    windows = analyzer.find_intersection_windows()
    if not windows:
        logger.info("[intersection] No intersection windows in GPS track")
        return []

    segments = []
    for window in windows:
        t_in = window['t_enter']
        t_out = window['t_exit']
        window_frames = [f for f in frames if t_in <= f.timestamp <= t_out]

        if not window_frames:
            continue

        results = analyzer.analyze_window(window, window_frames)
        for r in results:
            # ── Pertinence : véhicule d'intérêt aux intersections ────────
            # Ne sont « d'intérêt » que les usagers de la route qui INTERAGISSENT
            # avec la navette (s'insèrent devant / attendent son passage). Les
            # 'turn' (traversée/virage sans interaction) et les faux positifs
            # COCO (airplane/bird…) sont tagués of_interest=False → masqués par
            # défaut dans le rapport (source du « trop de lignes »). Tag non
            # destructif : rien n'est supprimé, le frontend peut tout afficher.
            meta = dict(r.get('metadata') or {})
            event_type = meta.get('event_type')
            vclass = (meta.get('vehicle_class') or '').lower()
            meta['of_interest'] = bool(
                event_type in ('insertion', 'wait')
                and vclass in ROAD_USER_CLASSES
            )
            segments.append(TemporalSegment(
                session=session,
                camera=camera,
                segment_type=r['type'],    # 'insertion_front' | 'intersection_stop'
                start_time=r['start'],
                end_time=r['end'],
                metadata=meta,
            ))

    _n_interest = sum(1 for s in segments if s.metadata.get('of_interest'))
    logger.info(f"[intersection] {len(segments)} segments detected across {len(windows)} windows "
                f"({_n_interest} of interest)")
    return segments


def _compute_lane_events(camera, intersection_windows):
    """
    Phase 3 — scan a camera's DetectionFrame rows in chronological order and
    emit one LaneEvent per (track_id, lane_id) contiguous span.

    Reads detections that were tagged with `lane_id` + `in_shuttle_lane`
    during the YOLO loop (Phase 2). Untagged detections (no track_id, no
    lane_id, or class is sam3_marking/road_mask) are skipped.
    """
    from .models import DetectionFrame, LaneEvent

    LaneEvent.objects.filter(camera=camera).delete()

    # active[track_id] = {lane_id, in_shuttle_lane, t_enter, last_t, class_name}
    active: dict = {}
    events: list = []

    def _close(track_id: int, cur: dict):
        events.append(LaneEvent(
            camera=camera,
            track_id=track_id,
            lane_id=cur['lane_id'],
            in_shuttle_lane=cur['in_shuttle_lane'],
            t_enter=cur['t_enter'],
            t_exit=cur['last_t'],
            class_name=cur['class_name'],
            intersection_window_idx=_window_idx_for(
                (cur['t_enter'] + cur['last_t']) / 2.0, intersection_windows
            ),
        ))

    for frame in DetectionFrame.objects.filter(camera=camera).only(
        'frame_number', 'timestamp', 'detections'
    ).order_by('frame_number').iterator(chunk_size=2000):
        ts = frame.timestamp
        for det in (frame.detections or []):
            track_id = det.get('track_id')
            lane_id = det.get('lane_id')
            if track_id is None or lane_id is None or lane_id < 0:
                continue
            in_lane = bool(det.get('in_shuttle_lane', False))
            cls_name = det.get('class_name', '')

            cur = active.get(track_id)
            if cur is None:
                active[track_id] = {
                    'lane_id': lane_id,
                    'in_shuttle_lane': in_lane,
                    't_enter': ts,
                    'last_t': ts,
                    'class_name': cls_name,
                }
                continue
            if cur['lane_id'] != lane_id:
                _close(track_id, cur)
                active[track_id] = {
                    'lane_id': lane_id,
                    'in_shuttle_lane': in_lane,
                    't_enter': ts,
                    'last_t': ts,
                    'class_name': cls_name,
                }
            else:
                cur['last_t'] = ts

    for track_id, cur in active.items():
        _close(track_id, cur)

    if events:
        LaneEvent.objects.bulk_create(events, batch_size=500)
    return len(events)


def _gps_speed_at(timestamp: float, gps_track: list) -> Optional[float]:
    """Return the shuttle's speed (km/h) at a given timestamp via nearest GPS sample."""
    if not gps_track:
        return None
    # Binary search would be cleaner; the track is small so linear is fine.
    best = min(gps_track, key=lambda g: abs(g.get('ts', 0) - timestamp))
    return best.get('speed_kmh')


def _compute_conflict_events(session, intersection_windows):
    """
    Phase 5 — for each LaneEvent in the shuttle lane that overlaps an
    intersection window, scan the corresponding DetectionFrames to compute:
      - min_distance_m / min_ttc_s during the span
      - delta_t_s : signed time-of-arrival difference between shuttle and
        object at the intersection centre (positive = shuttle first)
      - conflict_type heuristic
      - severity {'info' | 'warn' | 'critical'} from min_ttc_s + min_dist
    """
    from .models import ConflictEvent, DetectionFrame, LaneEvent

    ConflictEvent.objects.filter(session=session).delete()

    lane_events = LaneEvent.objects.filter(
        camera__session=session, in_shuttle_lane=True
    ).select_related('camera')
    if not lane_events.exists():
        return 0

    gps_track = session.gps_track or []
    conflicts = []

    for le in lane_events:
        # Only build a conflict for spans intersecting an intersection window
        if le.intersection_window_idx < 0:
            continue
        win = intersection_windows[le.intersection_window_idx] \
            if le.intersection_window_idx < len(intersection_windows) else None
        if not win:
            continue

        # Collect kinematics for this track over the lane-event span
        frames = DetectionFrame.objects.filter(
            camera=le.camera,
            timestamp__gte=le.t_enter,
            timestamp__lte=le.t_exit,
        ).only('timestamp', 'detections').order_by('frame_number')

        min_dist = None
        min_ttc = None
        last_dist = None
        last_speed_kmh = None
        for f in frames.iterator(chunk_size=500):
            for d in (f.detections or []):
                if d.get('track_id') != le.track_id:
                    continue
                dm = d.get('distance_m')
                if dm is not None:
                    if min_dist is None or dm < min_dist:
                        min_dist = dm
                    last_dist = dm
                ttc = d.get('ttc_s')
                if ttc is not None and (min_ttc is None or ttc < min_ttc):
                    min_ttc = ttc
                rs = d.get('relative_speed_kmh')
                if rs is not None:
                    last_speed_kmh = rs

        if min_dist is None and min_ttc is None:
            continue

        # delta_t : shuttle's t_closest minus the object's estimated arrival
        # at the intersection centre. Positive means shuttle arrives first.
        delta_t = None
        navette_first = None
        t_closest = win.get('t_closest', (win.get('t_enter', 0) + win.get('t_exit', 0)) / 2)
        if last_dist is not None and last_speed_kmh is not None and last_speed_kmh > 0.5:
            # last_speed_kmh > 0 means object approaching (closing distance)
            v_mps = last_speed_kmh / 3.6
            t_obj_arrival = le.t_exit + (last_dist / v_mps) if v_mps > 0 else None
            if t_obj_arrival is not None:
                delta_t = round(t_closest - t_obj_arrival, 2)
                navette_first = delta_t < 0  # shuttle arrives at t_closest BEFORE object

        # Severity heuristic
        severity = 'info'
        if min_ttc is not None and min_ttc < 3:
            severity = 'critical'
        elif (min_ttc is not None and min_ttc < 6) or (min_dist is not None and min_dist < 5):
            severity = 'warn'

        # Conflict type heuristic
        ctype = ConflictEvent.ConflictType.SAME_LANE_AHEAD
        if last_speed_kmh is not None and last_speed_kmh > 5:
            ctype = ConflictEvent.ConflictType.APPROACHING_FRONT

        conflicts.append(ConflictEvent(
            session=session,
            camera=le.camera,
            track_id=le.track_id,
            class_name=le.class_name,
            intersection_window_idx=le.intersection_window_idx,
            conflict_type=ctype,
            navette_passed_first=navette_first,
            delta_t_s=delta_t,
            min_distance_m=round(min_dist, 2) if min_dist is not None else None,
            min_ttc_s=round(min_ttc, 2) if min_ttc is not None else None,
            t_start=le.t_enter,
            t_end=le.t_exit,
            severity=severity,
        ))

    if conflicts:
        ConflictEvent.objects.bulk_create(conflicts, batch_size=500)
    return len(conflicts)


def _window_idx_for(t: float, intersection_windows: list) -> int:
    for idx, w in enumerate(intersection_windows or []):
        if w.get('t_enter', 0) <= t <= w.get('t_exit', 0):
            return idx
    return -1


def detect_temporal_segments(session):
    """Detect all temporal segments from DetectionFrame data.

    The segment detection logic branches on the profile's report_type:
    - 'proximity_overtaking' : suivi rapproché, dépassements, croisements (existant)
    - 'intersection_insertion' : insertions aux intersections devant la navette
    """
    from .models import TemporalSegment, DetectionFrame

    TemporalSegment.objects.filter(session=session).delete()

    profile = session.profile
    report_type = profile.report_type if profile else 'proximity_overtaking'

    segments = []
    for camera in session.cameras.all():
        frames = list(DetectionFrame.objects.filter(camera=camera).order_by('frame_number'))
        if not frames:
            continue

        if report_type == 'proximity_overtaking':
            segments += _detect_close_following(session, camera, frames)
            segments += _detect_overtaking(session, camera, frames)
            segments += _detect_crossing(session, camera, frames)
        elif report_type == 'intersection_insertion':
            segments += _detect_intersection_insertion(session, camera, frames)

    if segments:
        TemporalSegment.objects.bulk_create(segments)
    return len(segments)


# =============================================================================
# Main Celery Task
# =============================================================================

@shared_task(bind=True)
def process_session_task(self, session_id: str, force_rerun: bool = False,
                         chain_sam3: bool = True, positions: list = None):
    """
    Process a cam analyzer session:
    - Load YOLO model from profile
    - Run tracking on each camera's video
    - Store DetectionFrame records
    - Generate annotated output videos
    - Compute results_summary

    Args:
        session_id: AnalysisSession.id (UUID string)
        force_rerun: When True, existing DetectionFrames for each camera are
            wiped and re-computed. When False (default), cameras that already
            have DetectionFrames are skipped (Proposition B — skip-if-done).
    """
    close_old_connections()

    from .models import AnalysisSession, DetectionFrame

    model = None
    start_time = time.time()

    try:
        session = AnalysisSession.objects.select_related('profile').get(pk=session_id)
        user_id = session.user_id
        profile = session.profile

        # Idempotency guard: if Redis redelivered the task after success
        # (visibility_timeout < runtime), bail out instead of re-running and
        # tripping the (camera, frame_number) UNIQUE constraint.
        if session.status == AnalysisSession.Status.COMPLETED:
            logger.info(
                f"[cam_analyzer] Session {session_id} already COMPLETED — "
                f"skipping redelivered task"
            )
            return {'already_completed': str(session_id)}

        if not profile:
            raise ValueError("Aucun profil d'analyse assigné à la session")

        _console(user_id, f"Démarrage de l'analyse : {session.name}")

        # Check cancellation
        if _is_cancelled(user_id):
            cache.delete(f"stop_cam_analyzer_{user_id}")
            session.status = AnalysisSession.Status.FAILED
            session.error_message = "Annulé par l'utilisateur"
            session.save()
            return {'cancelled': session_id}

        # Update status
        session.status = AnalysisSession.Status.PROCESSING
        session.started_at = timezone.now()
        session.save(update_fields=['status', 'started_at'])

        # Cleanup derived events from a previous run (LaneEvent / ConflictEvent).
        # DetectionFrames are deleted per-camera further down. We do this at the
        # session level to invalidate stale event rows that pointed to about-to-
        # be-deleted DetectionFrames.
        from .models import LaneEvent, ConflictEvent
        _le_count = LaneEvent.objects.filter(camera__session=session).count()
        _ce_count = ConflictEvent.objects.filter(session=session).count()
        if _le_count or _ce_count:
            LaneEvent.objects.filter(camera__session=session).delete()
            ConflictEvent.objects.filter(session=session).delete()
            _console(session.user_id,
                     f"Nettoyage : {_le_count} LaneEvent et {_ce_count} ConflictEvent "
                     f"d'un run précédent supprimés")

        # Pipeline tracking — pass_tracking helpers. Per-camera passes
        # (yolo_detect, yolopv2_lanes) are registered INSIDE the camera
        # loop (Proposition A). Session-wide passes (intersection_windows,
        # temporal_segments, conflicts) are registered around their own
        # computers below.
        from .utils.pass_tracking import (
            mark_started, mark_completed, mark_failed,
        )
        _has_yolopv2 = (
            profile.report_type == 'intersection_insertion'
            and profile.road_model_path
            and 'yolopv2' in os.path.basename(profile.road_model_path).lower()
        )
        # SAM3 markings run as a SEPARATE chained Celery task at the end of
        # this one, NOT inline in the YOLO loop. Avoids loading YOLO +
        # YOLOPv2 + SAM3 in VRAM simultaneously (TDR/BSOD on RTX 4090 24GB).
        # The SAM3 pass is registered by analyze_sam3_only_task itself.
        _sam3_enabled = bool(getattr(profile, 'sam3_markings_enabled', False))

        set_session_progress(session_id, 2, "Chargement du modèle...")

        # =====================================================================
        # Load YOLO model
        # =====================================================================
        model_path = profile.model_path
        if not os.path.isabs(model_path):
            model_path = os.path.join(settings.BASE_DIR, model_path)

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Modèle introuvable : {model_path}")

        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        _console(user_id, f"Chargement modèle : {os.path.basename(model_path)} ({device})")

        model = YOLO(model_path)
        class_names = {i: name.lower() for i, name in model.names.items()}

        # Resolve target class indices
        target_classes = profile.target_classes or []
        if target_classes and isinstance(target_classes[0], int):
            target_indices = target_classes
        else:
            # String class names → indices
            target_lower = [str(c).lower() for c in target_classes]
            target_indices = [i for i, name in class_names.items() if name in target_lower]

        _console(user_id, f"Classes cibles : {[class_names.get(i, i) for i in target_indices]}")

        set_session_progress(session_id, 5, "Modèle chargé")

        # =====================================================================
        # Process each camera
        # =====================================================================
        # Filter to the profile's analysed positions; lateral views can be
        # extracted purely for visualisation without paying the YOLO cost.
        analyzed_positions = list(getattr(profile, 'analyzed_positions', []) or [])
        if not analyzed_positions:
            analyzed_positions = ['front', 'rear']
        # Restriction optionnelle : relance CIBLÉE (ex. yolopv2 sur front seule) → ne
        # traiter qu'un sous-ensemble, sans relancer les autres vues (left/right…).
        if positions:
            analyzed_positions = [p for p in analyzed_positions if p in positions]

        all_cameras = list(session.cameras.all().order_by('position'))
        cameras = [c for c in all_cameras if c.position in analyzed_positions]
        skipped_positions = sorted(set(c.position for c in all_cameras) - set(analyzed_positions))
        num_cameras = len(cameras)

        if skipped_positions:
            _console(
                user_id,
                f"Vues en lecture seule (non analysées) : {', '.join(skipped_positions)}"
            )

        if num_cameras == 0:
            raise ValueError("Aucune caméra dans la session")

        summary = {
            'total_frames': 0,
            'cameras_processed': 0,
            'detections_total': 0,
            'by_class': {},
            'by_camera': {},
            'annotated_videos': {},
            'max_proximity': 0.0,
        }

        # ── Pre-compute intersection windows (for YOLO + SAM3 temporal gating) ──
        # Used by:
        #   - YOLO main loop (skip frames outside windows when restrict_to_intersection_windows)
        #   - SAM3 road markings (always gated to windows)
        # Persisted on session.intersection_windows for the frontend timeline.
        from .utils.window_recompute import recompute_intersection_windows
        _intersection_windows = recompute_intersection_windows(session, profile)
        _restrict_to_windows = False
        if _intersection_windows:
            _restrict_to_windows = bool(getattr(profile, 'restrict_to_intersection_windows', True))
            _console(
                user_id,
                f"Intersections : {len(_intersection_windows)} fenêtre(s) pré-calculée(s)"
                + (" — analyse restreinte aux fenêtres" if _restrict_to_windows else "")
            )

        # SAM3 reuses the same windows when enabled
        _sam3_windows = _intersection_windows if getattr(profile, 'sam3_markings_enabled', False) else []

        for cam_idx, camera in enumerate(cameras):
            if _is_cancelled(user_id):
                raise InterruptedError("Annulé par l'utilisateur")

            cam_progress_start = 5 + (cam_idx / num_cameras) * 85
            cam_progress_end = 5 + ((cam_idx + 1) / num_cameras) * 85

            position = camera.position
            video_path = camera.video_file.path

            _console(user_id, f"Caméra {camera.get_position_display()} ({cam_idx + 1}/{num_cameras})")

            if not os.path.exists(video_path):
                _console(user_id, f"ERREUR: Fichier vidéo introuvable : {video_path}")
                continue

            # Get video metadata
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                _console(user_id, f"ERREUR: Impossible d'ouvrir la vidéo")
                continue

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

            _console(user_id, f"  {total_frames} frames, {fps:.1f} fps, {width}x{height}")

            # Proposition B — Skip-if-done check per camera.
            # When the camera already has DetectionFrames from a previous run,
            # skip it (preserves partial analyses across cancel/restart cycles).
            # force_rerun=True wipes existing data and re-computes.
            _prev_count = DetectionFrame.objects.filter(camera=camera).count()
            if _prev_count and not force_rerun:
                _console(user_id,
                         f"  Caméra {position} déjà analysée ({_prev_count} DetectionFrames). "
                         f"Skip — utiliser 'Tout relancer' pour forcer une nouvelle passe.")
                summary['cameras_processed'] += 1  # counted as done for the summary
                summary['by_camera'][position] = summary['by_camera'].get(position, {})
                summary['by_camera'][position]['frames_existing'] = _prev_count
                continue
            elif _prev_count and force_rerun:
                DetectionFrame.objects.filter(camera=camera).delete()
                _console(user_id,
                         f"  Force rerun : {_prev_count} DetectionFrame d'un run précédent supprimée(s)")

            # Proposition A — per-camera pass tracking. YOLO and YOLOPv2 are
            # registered against this specific camera so the UI can show
            # "front: ✅ / rear: ⏵ in progress".
            mark_started(session, 'yolo_detect', profile, camera=camera)
            if _has_yolopv2:
                mark_started(session, 'yolopv2_lanes', profile, camera=camera)

            set_session_progress(session_id, cam_progress_start,
                                 f"Analyse caméra {position} ({cam_idx + 1}/{num_cameras})...")

            # ─── Road segmenter (intersection_insertion + front only) ─────────
            # Log explicitly which branch we take, including the "skipped"
            # cases — otherwise it's invisible from the worker output why no
            # road_mask is being produced.
            road_segmenter = None
            _road_path_raw = getattr(profile, 'road_model_path', '') or ''
            # (b) Portée yolopv2 : vue avant seule par défaut (léger/stable) ; les 4 vues
            # seulement si profile.yolopv2_all_views (Phase C 360° : voies latérales pour
            # calibrer les côtés). L'aval (événements de voie/insertion) reste front-only.
            _yolopv2_here = (position == 'front') or getattr(profile, 'yolopv2_all_views', False)
            if not _yolopv2_here:
                pass  # yolopv2 désactivé sur cette vue (front-only)
            elif profile.report_type != 'intersection_insertion':
                _console(user_id, "  road_segmenter ignoré (report_type != intersection_insertion)")
            elif not _road_path_raw:
                _console(user_id, "  road_segmenter ignoré (road_model_path vide dans le profil)")
            else:
                road_model_path = _road_path_raw
                if not os.path.isabs(road_model_path):
                    road_model_path = os.path.join(settings.BASE_DIR, road_model_path)
                if os.path.exists(road_model_path):
                    # Dispatch on filename: yolopv2.pt is a TorchScript multi-task
                    # model, not an ultralytics checkpoint — needs its own loader.
                    fname = os.path.basename(road_model_path).lower()
                    if 'yolopv2' in fname:
                        try:
                            from .utils.yolopv2_segmenter import YOLOPv2RoadSegmenter
                            road_segmenter = YOLOPv2RoadSegmenter(road_model_path, device=device)
                            road_segmenter.load()
                            _console(user_id, f"  Segmenteur YOLOPv2 chargé: {os.path.basename(road_model_path)}")
                        except Exception as _yp_err:
                            _console(user_id, f"  ERREUR chargement YOLOPv2: {_yp_err}")
                            road_segmenter = None
                    else:
                        try:
                            from .utils.road_segmenter import RoadSegmenter
                            road_segmenter = RoadSegmenter(road_model_path, device=device)
                            road_segmenter.load()
                            _console(user_id, f"  Segmenteur routier (ultralytics) chargé: {os.path.basename(road_model_path)}")
                        except Exception as _rs_err:
                            _console(user_id, f"  ERREUR chargement RoadSegmenter: {_rs_err}")
                            road_segmenter = None
                else:
                    _console(user_id,
                             f"  AVERTISSEMENT: road_model_path introuvable sur disque: {road_model_path}")

            # SAM3 is intentionally NOT loaded here — see comment at the start
            # of process_session_task. It runs as a chained task after YOLO +
            # YOLOPv2 have unloaded, so VRAM is fresh when SAM3's ~8GB model
            # loads.
            sam3_analyzer = None

            # Setup annotated video writer
            output_dir = os.path.join(settings.MEDIA_ROOT, 'cam_analyzer', str(user_id), 'output')
            os.makedirs(output_dir, exist_ok=True)

            session_name = session.name.replace(' ', '_')[:30] if session.name else str(session_id)[:8]
            output_filename = f"{session_name}_{position}_annotated.avi"
            output_path = os.path.join(output_dir, output_filename)

            vid_writer = cv2.VideoWriter(
                output_path,
                cv2.VideoWriter_fourcc(*'MJPG'),
                fps,
                (width, height),
                True
            )

            if not vid_writer.isOpened():
                _console(user_id, f"  AVERTISSEMENT: Impossible de créer la vidéo annotée")
                vid_writer = None

            # =================================================================
            # Run YOLO tracking
            # =================================================================
            # Inférence à conf=0.10 fixe (storage exhaustif), filtrage par
            # profile.confidence + target_classes au read time. Permet
            # d'ajouter des classes / monter le seuil sans re-run YOLO.
            # Voir ROADMAP §9.2.bis (décision A, 2026-05-07).
            _STORAGE_CONF = 0.10
            _imgsz = ((max(width, height) + 31) // 32) * 32
            _track_base = {
                'device': device,
                'imgsz': _imgsz,
                'conf': _STORAGE_CONF,
                'iou': profile.iou_threshold,
                'classes': None,  # store all classes; filter at read time
                'verbose': False,
            }
            if profile.task_type == 'segment':
                _track_base['task'] = 'segment'
                _track_base['retina_masks'] = True

            # ── Window-restricted iteration vs full-video streaming ───────
            # When restrict_to_windows is on, we seek cv2.VideoCapture to
            # each window's f_start and run model.track() on single frames
            # with persist=True. This skips inference entirely on the ~80%
            # of frames outside any intersection window (the legacy path
            # ran inference on 100k frames and skipped only post-processing
            # — wasting most of the GPU time).
            #
            # Tracker behaviour : persist=False on the FIRST frame of each
            # window resets BoTSORT, so track_ids are window-local. This is
            # correct semantically — no object survives between two
            # intersections separated by minutes, and lane/conflict events
            # are per-window anyway.
            _use_window_iter = bool(_restrict_to_windows and _intersection_windows)

            # Convert windows → (f_start, f_end) ranges and merge any that
            # overlap or are adjacent (within 1 frame). Two windows on the
            # same road may overlap when they're closer than 2× the radius;
            # without merging, the same frame would be yielded twice and the
            # downstream DetectionFrame bulk_create would hit the
            # (camera, frame_number) unique constraint.
            def _merge_ranges(ranges):
                if not ranges:
                    return []
                ranges = sorted(ranges)
                merged = [list(ranges[0])]
                for s, e in ranges[1:]:
                    if s <= merged[-1][1] + 1:  # overlap or adjacent
                        merged[-1][1] = max(merged[-1][1], e)
                    else:
                        merged.append([s, e])
                return [tuple(r) for r in merged]

            _frame_ranges = []
            if _use_window_iter:
                _raw_ranges = []
                for w in _intersection_windows:
                    fs = max(0, int(w['t_enter'] * fps))
                    fe = min(total_frames - 1, int(w['t_exit'] * fps))
                    if fs <= fe:
                        _raw_ranges.append((fs, fe))
                _frame_ranges = _merge_ranges(_raw_ranges)
                _total_processing_frames = sum(fe - fs + 1 for fs, fe in _frame_ranges)
                _merged_note = (
                    f" (fusionnées en {len(_frame_ranges)} segments contigus)"
                    if len(_frame_ranges) != len(_raw_ranges) else ""
                )
                _console(user_id,
                         f"  Tracking YOLO démarré — mode fenêtres ({len(_intersection_windows)} "
                         f"fenêtres{_merged_note}, ~{_total_processing_frames} frames à analyser "
                         f"sur {total_frames} total → skip ~"
                         f"{(1 - _total_processing_frames / max(total_frames,1)) * 100:.0f}%)")
            else:
                _total_processing_frames = total_frames
                _console(user_id,
                         f"  Tracking YOLO démarré — mode complet ({total_frames} frames)")

            # Periodic console heartbeat so the user sees real progress in the
            # worker log (set_session_progress only updates the UI bar).
            _console_pct_step = 10  # log every 10% of processed frames
            _last_console_pct = 0

            def _yield_predictions():
                """Yields (frame_idx, pred) pairs to process.

                Restrict mode (path F — batched via ffmpeg mini-clips) :
                    for each merged (f_start, f_end) range, ffmpeg extracts a
                    frame-accurate sub-clip; model.track(stream=True) processes
                    the clip in its native batched pipeline (typically 5-10×
                    faster than per-frame inference). BoTSORT auto-resets
                    between segments via persist=False.

                Restrict mode fallback (no ffmpeg) :
                    per-frame inference with cv2.VideoCapture seek (legacy).

                Full mode :
                    ultralytics streaming over the whole video, no gating.
                """
                if _use_window_iter:
                    import shutil as _sh
                    import subprocess as _sp
                    import tempfile as _tf
                    _ff = _sh.which('ffmpeg')

                    if _ff is not None:
                        # ── Path F : ffmpeg mini-clip extraction + streaming ──
                        _tmp_dir = _tf.mkdtemp(prefix=f"wama_cam{camera.id}_seg_")
                        try:
                            for _seg_idx, (f_start, f_end) in enumerate(_frame_ranges):
                                _t_start_s = f_start / fps
                                _duration_s = (f_end - f_start + 1) / fps
                                _tmp_clip = os.path.join(_tmp_dir, f"seg_{_seg_idx:03d}.mp4")

                                # Extract a frame-accurate sub-clip. Re-encoding
                                # with libx264 -crf 18 is ~visually lossless and
                                # gives us exact frame counts (unlike -c copy
                                # which snaps to keyframes).
                                _proc = _sp.run([
                                    _ff, '-y', '-loglevel', 'error',
                                    '-ss', f"{_t_start_s:.6f}",
                                    '-i', video_path,
                                    '-t', f"{_duration_s:.6f}",
                                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                                    '-pix_fmt', 'yuv420p', '-an',
                                    _tmp_clip,
                                ], capture_output=True, text=True, timeout=600)

                                if _proc.returncode != 0 or not os.path.exists(_tmp_clip):
                                    logger.warning(
                                        f"[ffmpeg-seg] segment {_seg_idx} extraction failed: "
                                        f"{(_proc.stderr or '')[-200:]}"
                                    )
                                    continue

                                # Stream-track the mini-clip in native mode.
                                # persist=False resets BoTSORT for each new
                                # segment (track_ids are window-local).
                                kwargs = dict(_track_base)
                                kwargs['source'] = _tmp_clip
                                kwargs['stream'] = True
                                kwargs['persist'] = False

                                try:
                                    for _sub_idx, _pred in enumerate(model.track(**kwargs)):
                                        _abs_fidx = f_start + _sub_idx
                                        if _abs_fidx > f_end:
                                            break  # safety guard
                                        yield _abs_fidx, _pred
                                except Exception as _trk_e:
                                    logger.warning(
                                        f"[track-seg] segment {_seg_idx} failed: {_trk_e}"
                                    )
                                finally:
                                    try:
                                        os.remove(_tmp_clip)
                                    except OSError:
                                        pass
                        finally:
                            try:
                                _sh.rmtree(_tmp_dir, ignore_errors=True)
                            except Exception:
                                pass
                        return

                    # ── Fallback : per-frame inference via cv2.VideoCapture ──
                    _console(user_id, "  AVERTISSEMENT: ffmpeg indisponible, fallback per-frame inference (lent)")
                    cap_iter = cv2.VideoCapture(video_path)
                    if not cap_iter.isOpened():
                        _console(user_id, f"  ERREUR: cannot open video for window iteration")
                        return
                    try:
                        for f_start, f_end in _frame_ranges:
                            cap_iter.set(cv2.CAP_PROP_POS_FRAMES, f_start)
                            persist = False  # reset BoTSORT for new segment
                            for fidx in range(f_start, f_end + 1):
                                ok, fbgr = cap_iter.read()
                                if not ok:
                                    break
                                kwargs = dict(_track_base)
                                kwargs['source'] = fbgr
                                kwargs['persist'] = persist
                                try:
                                    results = model.track(**kwargs)
                                except Exception as _trk_e:
                                    logger.warning(f"[track] frame {fidx} failed: {_trk_e}")
                                    continue
                                if results:
                                    yield fidx, results[0]
                                persist = True
                    finally:
                        cap_iter.release()
                else:
                    kwargs = dict(_track_base)
                    kwargs['source'] = video_path
                    kwargs['stream'] = True
                    try:
                        preds_full = model.track(**kwargs)
                    except Exception as _e:
                        _console(user_id, f"  ERREUR tracking: {_e}")
                        return
                    for fidx, pred_full in enumerate(preds_full):
                        yield fidx, pred_full

            # Iterate over predictions
            frames_to_create = []
            cam_detections_count = 0
            cam_max_proximity = 0.0
            last_progress_frame = 0
            _processed_frames = 0  # for progress in window-restricted mode

            # Kinematics tracker reset per-camera so track_id collisions
            # between cameras don't pollute each other's distance history.
            from .utils.distance_speed import TrackKinematics
            _kinematics = TrackKinematics()

            # Trace le FOV V utilisé pour l'annotation des distances de CETTE caméra →
            # camera_geometry() peut corriger les sessions annotées avec un ancien FOV
            # (dist_scale devient 1.0 quand fov_v_used == FOV réel du rig). Les sessions
            # SANS cette clé sont supposées annotées avec les anciens défauts (LEGACY_FOV_V).
            try:
                from .utils.distance_speed import DEFAULT_FOV_V_DEG as _FOVV
                _cfg = session.config or {}
                _cfg.setdefault('fov_v_used', {})[position] = _FOVV.get(position, 60.0)
                session.config = _cfg
                session.save(update_fields=['config'])
            except Exception:
                logger.debug('fov_v_used save failed (non-blocking)', exc_info=True)

            # Projecteur sol (homographie) — actif UNIQUEMENT si CETTE caméra a une
            # calibration (camera.ground_homography, par session) ET
            # profile.geometry_enabled. Sinon None → seules les distances pinhole
            # (distance_m) sont conservées (fallback non destructif).
            # Voir CAM_ANALYZER_DISTANCE_DESIGN.md §3 + Roadmap Phase 0.
            _ground_projector = None
            try:
                _profile = session.profile
                if _profile and getattr(_profile, 'geometry_enabled', False):
                    from .utils.ground_projection import GroundProjector
                    _cal = getattr(camera, 'ground_homography', None)
                    if _cal and camera.width and camera.height:
                        _gpj = GroundProjector(_cal, (camera.width, camera.height))
                        _ground_projector = _gpj if _gpj.available else None
                        if _ground_projector:
                            _console(user_id, f"  [{position}] homographie sol active")
            except Exception:
                logger.debug('ground projector init failed (non-blocking)', exc_info=True)

            for frame_idx, pred in _yield_predictions():
                # Cancellation check every 100 processed frames
                if _processed_frames % 100 == 0 and _is_cancelled(user_id):
                    raise InterruptedError("Annulé par l'utilisateur")

                timestamp = frame_idx / fps
                _processed_frames += 1

                # In full-video mode, keep the legacy out-of-window short-circuit
                # so the annotated video stays length-aligned with the source.
                # In window-restricted mode (_use_window_iter), every yielded
                # frame is in-window by construction — this block is bypassed.
                if not _use_window_iter and _restrict_to_windows and _intersection_windows:
                    _in_intersection = any(
                        w['t_enter'] <= timestamp <= w['t_exit']
                        for w in _intersection_windows
                    )
                    if not _in_intersection:
                        if vid_writer and pred.orig_img is not None:
                            try:
                                vid_writer.write(pred.orig_img)
                            except Exception:
                                pass
                        if frame_idx - last_progress_frame >= 50 and total_frames > 0:
                            cam_frac = frame_idx / total_frames
                            pct = cam_progress_start + cam_frac * (cam_progress_end - cam_progress_start)
                            set_session_progress(session_id, pct)
                            last_progress_frame = frame_idx
                        continue

                # Extract detections (in-window only)
                detections = _extract_detections(pred, height)

                # Append road mask regions (only front camera, intersection_insertion profile)
                if road_segmenter is not None and pred.orig_img is not None:
                    road_regions = road_segmenter.segment_frame(pred.orig_img)
                    detections.extend(road_regions)

                # SAM3 road markings — gated to intersection windows (or road fallback)
                if sam3_analyzer is not None and pred.orig_img is not None:
                    _in_window = any(
                        w['t_enter'] <= timestamp <= w['t_exit'] for w in _sam3_windows
                    )
                    if _in_window or _use_sam3_fallback:
                        try:
                            markings = sam3_analyzer.analyze_frame(pred.orig_img)
                            detections.extend(markings)
                        except Exception as _sam3_err:
                            logger.debug(f"[SAM3] frame {frame_idx}: {_sam3_err}")

                # ── Lane attribution (Phase 2) ───────────────────────────────
                # Only when YOLOPv2 produced lane polygons AND we're on the
                # front camera (lateral views see lanes obliquely — geometry
                # would be unreliable). Cheap: just point-in-polygon per bbox.
                if (position == 'front'
                        and detections
                        and any(d.get('class_name') == 'lane (yolopv2)' for d in detections)):
                    from .utils.lane_partition import (
                        annotate_detections_with_lane,
                        find_shuttle_lane,
                    )
                    lane_polys = [
                        d['polygon'] for d in detections
                        if d.get('type') == 'road_mask'
                        and d.get('class_name') == 'lane (yolopv2)'
                        and isinstance(d.get('polygon'), list)
                    ]
                    if lane_polys:
                        shuttle_lane = find_shuttle_lane(lane_polys, width, height)
                        annotate_detections_with_lane(detections, lane_polys, shuttle_lane)

                # ── Distance / vitesse / TTC (Phase 4) ───────────────────────
                # Pinhole simple : on suppose un FoV vertical par caméra et
                # on pioche la hauteur réelle dans CLASS_REAL_HEIGHT_M selon
                # la classe. Vitesse relative dérivée du Δdistance entre
                # frames consécutives du même track_id. Valeurs persistées
                # par détection : distance_m, relative_speed_kmh, ttc_s.
                from .utils.distance_speed import (
                    annotate_detections_with_distance,
                    DEFAULT_FOV_V_DEG,
                )
                fov_v = DEFAULT_FOV_V_DEG.get(position, 60.0)
                annotate_detections_with_distance(
                    detections, height, fov_v, timestamp, _kinematics
                )

                # Distances GÉOMÉTRIQUES par homographie (si disponible) : point-sol
                # de la bbox → (X, Y) au sol → dist_longitudinal/lateral/euclid +
                # ground_xy + distance_source='homography'. Complète (ne remplace pas)
                # les champs pinhole ; les masques et marquages sont exclus.
                if _ground_projector is not None:
                    for det in detections:
                        if det.get('type') in ('road_mask', 'sam3_marking'):
                            continue
                        bbox = det.get('bbox')
                        if not (isinstance(bbox, (list, tuple)) and len(bbox) >= 4):
                            continue
                        g = _ground_projector.distances_for_bbox(bbox)
                        if g:
                            det.update(g)

                # Track max proximity — skip non-vehicle entries (road_mask, sam3_marking…)
                for det in detections:
                    prox = det.get('proximity', 0.0)
                    if prox and prox > cam_max_proximity:
                        cam_max_proximity = prox
                    cls_name = det.get('class_name', '')
                    if cls_name:
                        summary['by_class'][cls_name] = summary['by_class'].get(cls_name, 0) + 1

                cam_detections_count += len(detections)

                frames_to_create.append(DetectionFrame(
                    camera=camera,
                    frame_number=frame_idx,
                    timestamp=round(timestamp, 4),
                    detections=detections,
                ))

                # Write annotated frame
                if vid_writer:
                    try:
                        annotated = pred.plot()
                        vid_writer.write(annotated)
                    except Exception:
                        pass

                # Report progress every 50 processed frames. cam_frac is the
                # fraction of TO-PROCESS frames done — accurate in both
                # window-restricted and full modes.
                if _processed_frames - last_progress_frame >= 50 and _total_processing_frames > 0:
                    cam_frac = _processed_frames / _total_processing_frames
                    pct = cam_progress_start + cam_frac * (cam_progress_end - cam_progress_start)
                    set_session_progress(session_id, pct)
                    last_progress_frame = _processed_frames

                    # Console heartbeat every N% of frames so the worker log
                    # shows real progress for long sessions (UI bar isn't
                    # visible from the Celery log).
                    cam_pct = int(cam_frac * 100)
                    if cam_pct - _last_console_pct >= _console_pct_step:
                        _console(user_id,
                                 f"    {position}: {cam_pct}% — {_processed_frames}/{_total_processing_frames} "
                                 f"frames traitées, {cam_detections_count} détections")
                        _last_console_pct = cam_pct

                # Bulk save every 500 frames
                if len(frames_to_create) >= 500:
                    DetectionFrame.objects.bulk_create(frames_to_create)
                    frames_to_create = []

            # Save remaining frames
            if frames_to_create:
                DetectionFrame.objects.bulk_create(frames_to_create)

            # Release video writer
            has_annotated_video = False
            if vid_writer:
                vid_writer.release()
                has_annotated_video = True

            # Per-camera YOLO pass completed (Proposition A)
            try:
                mark_completed(session, 'yolo_detect', camera=camera, output_summary={
                    'frames': total_frames,
                    'detections': cam_detections_count,
                    'max_proximity': round(cam_max_proximity, 3),
                    'storage_conf': _STORAGE_CONF,
                })
                if _has_yolopv2:
                    mark_completed(session, 'yolopv2_lanes', camera=camera, output_summary={
                        'model_path': profile.road_model_path,
                    })
            except Exception as _mp:
                logger.warning(f"mark_completed (per-cam) failed: {_mp}")

            # ── Lane events (Phase 3) ─────────────────────────────────────
            # Only the front camera produces lane_id (cf. YOLO loop), so it's
            # the only one we scan. Cheap O(N_frames × N_detections).
            if position == 'front':
                try:
                    mark_started(session, 'lane_events', profile)
                    n_events = _compute_lane_events(camera, _intersection_windows)
                    if n_events:
                        _console(user_id, f"  {n_events} évènement(s) de voie calculés")
                    mark_completed(session, 'lane_events', output_summary={
                        'events_count': n_events,
                    })
                except Exception as _le:
                    logger.warning(f"_compute_lane_events failed: {_le}")
                    mark_failed(session, 'lane_events', str(_le))

            # Release road segmenter (if any) after this camera is done
            if road_segmenter is not None:
                road_segmenter.unload()
                road_segmenter = None

            # Release SAM3 analyzer (if any) after this camera is done
            if sam3_analyzer is not None:
                sam3_analyzer.unload()
                sam3_analyzer = None

            # Update summary
            summary['total_frames'] += total_frames
            summary['cameras_processed'] += 1
            summary['detections_total'] += cam_detections_count
            summary['by_camera'][position] = {
                'frames': total_frames,
                'detections': cam_detections_count,
                'max_proximity': round(cam_max_proximity, 3),
            }
            if cam_max_proximity > summary['max_proximity']:
                summary['max_proximity'] = cam_max_proximity

            # Store annotated video path
            if has_annotated_video and os.path.exists(output_path):
                relative_path = f'cam_analyzer/{user_id}/output/{output_filename}'
                summary['annotated_videos'][position] = relative_path

            _console(user_id, f"  {cam_detections_count} détections, proximité max: {cam_max_proximity:.2f}")

            set_session_progress(session_id, cam_progress_end,
                                 f"Caméra {position} terminée")

        # =====================================================================
        # Temporal Segment Detection (Phase 3)
        # =====================================================================
        if _is_cancelled(user_id):
            raise InterruptedError("Annulé par l'utilisateur")

        set_session_progress(session_id, 92, "Détection des segments temporels...")
        try:
            mark_started(session, 'temporal_segments', profile)
            num_segments = detect_temporal_segments(session)
            summary['segments_detected'] = num_segments
            _console(user_id, f"{num_segments} segments temporels détectés")
            mark_completed(session, 'temporal_segments', output_summary={
                'count': num_segments,
                'target_classes': list(profile.target_classes or []),
                'confidence': profile.confidence,
            })
        except Exception as e:
            logger.warning(f"Segment detection failed: {e}")
            summary['segments_detected'] = 0
            mark_failed(session, 'temporal_segments', str(e))

        # =====================================================================
        # Phase 4 — Distance / vitesse / TTC : déjà calculés inline pendant la
        # boucle YOLO (par détection, persistés dans DetectionFrame.detections).
        # On enregistre juste le pass pour la traçabilité.
        # =====================================================================
        try:
            mark_completed(session, 'distance', output_summary={
                'method': 'pinhole + class height + Δdistance/Δt',
                'fov_v_deg': {k: v for k, v in {
                    'front': 60.0, 'rear': 60.0, 'left': 90.0, 'right': 90.0,
                }.items()},
            })
        except Exception as _de:
            logger.warning(f"distance pass mark failed: {_de}")

        # =====================================================================
        # Phase 5 — Conflits navette ↔ objets en voie navette
        # =====================================================================
        if _is_cancelled(user_id):
            raise InterruptedError("Annulé par l'utilisateur")
        set_session_progress(session_id, 96, "Calcul des conflits...")
        try:
            mark_started(session, 'conflicts', profile)
            num_conflicts = _compute_conflict_events(session, _intersection_windows)
            summary['conflicts_detected'] = num_conflicts
            _console(user_id, f"{num_conflicts} conflit(s) détecté(s)")
            mark_completed(session, 'conflicts', output_summary={
                'count': num_conflicts,
                'method': 'shuttle-lane × intersection-window × TTC',
            })
        except Exception as e:
            logger.warning(f"Conflict detection failed: {e}")
            summary['conflicts_detected'] = 0
            mark_failed(session, 'conflicts', str(e))

        # =====================================================================
        # Finalize
        # =====================================================================
        elapsed = time.time() - start_time
        summary['processing_time_seconds'] = round(elapsed, 1)
        summary['max_proximity'] = round(summary['max_proximity'], 3)

        session.results_summary = summary

        # Largeur de voie AUTO (marquages yolopv2 projetés au sol) → défaut du gabarit
        # de la vue de dessus. Nécessite la calibration (homographie) faite pendant
        # l'analyse. Best-effort (n'impacte pas le résultat si absente).
        try:
            from .utils.lane_estimator import estimate_lane_width
            _front_cam = session.cameras.filter(position='front').first()
            if _front_cam and getattr(_front_cam, 'ground_homography', None):
                _lw = estimate_lane_width(_front_cam)
                if _lw:
                    session.lane_width_m = _lw
        except Exception:
            logger.debug('lane width estimation failed (non-blocking)', exc_info=True)

        # Per-camera passes were marked COMPLETED inside the camera loop
        # (Proposition A). Nothing else to mark here for YOLO/YOLOPv2.
        # SAM3 (if enabled) is delegated to the chained analyze_sam3_only_task.

        # Free YOLO VRAM BEFORE handing off to SAM3 — critical to avoid the
        # double-model spike that triggered TDR/BSOD on the user's 4090.
        _unload_model(model)
        model = None

        if _sam3_enabled and chain_sam3:
            # Keep the session in PROCESSING so the frontend polling stays
            # alive and reflects the SAM3 phase. analyze_sam3_only_task will
            # flip status to COMPLETED at the end.
            session.progress = 95.0
            session.save(update_fields=['progress'])
            set_session_progress(session_id, 95, "Marquages SAM3 (post-pass)…")
            _console(user_id,
                     f"YOLO/YOLOPv2 terminé en {elapsed:.0f}s — "
                     f"{summary['detections_total']} détections. "
                     f"Lancement SAM3 en post-pass (VRAM fraîche).")
            from .tasks import analyze_sam3_only_task
            _sam3_task = analyze_sam3_only_task.delay(str(session.id))
            # Tracker l'ID de la tâche SAM3 CHAÎNÉE (nouveau task_id) pour que
            # cancel_analysis puisse la révoquer — sinon le cache pointait sur
            # process_session_task et l'annulation ne touchait jamais SAM3.
            try:
                from django.core.cache import cache as _cache
                _cache.set(f"cam_analyzer_task_{session_id}", _sam3_task.id, timeout=None)
            except Exception:
                pass
            return {'processed': session_id, 'sam3_queued': True}

        # No SAM3 — close the session right here.
        session.status = AnalysisSession.Status.COMPLETED
        session.completed_at = timezone.now()
        session.progress = 100.0
        session.save()

        set_session_progress(session_id, 100, "Terminé")
        _console(user_id, f"Analyse terminée en {elapsed:.0f}s — "
                          f"{summary['detections_total']} détections sur {summary['cameras_processed']} caméras")

        return {'processed': session_id}

    except InterruptedError as e:
        if model:
            _unload_model(model)
        try:
            session = AnalysisSession.objects.get(pk=session_id)
            session.status = AnalysisSession.Status.FAILED
            session.error_message = str(e)
            session.save()
            cache.delete(f"stop_cam_analyzer_{session.user_id}")
            _console(session.user_id, f"Analyse annulée")
        except Exception:
            pass
        return {'cancelled': session_id}

    except Exception as e:
        if model:
            _unload_model(model)
        logger.error(f"Error processing session {session_id}: {e}", exc_info=True)
        try:
            session = AnalysisSession.objects.get(pk=session_id)
            session.status = AnalysisSession.Status.FAILED
            session.error_message = str(e)
            session.save()
            try:
                from .utils.pass_tracking import mark_failed
                # SAM3 is in its own chained task — don't mark it failed here.
                for pt in ('yolo_detect', 'yolopv2_lanes',
                           'lane_events', 'temporal_segments'):
                    mark_failed(session, pt, str(e))
            except Exception:
                pass
            _console(session.user_id, f"ERREUR: {e}")
        except Exception:
            pass
        return {'error': str(e), 'session_id': session_id}


# =============================================================================
# Pass C — SAM3 markings only (re-uses extracted MP4 + existing windows)
# =============================================================================

# =============================================================================
# Decoupled computer tasks (Proposition D)
# Each computer is a standalone Celery task that operates on already-persisted
# DetectionFrames. Lets the user re-run lane events / temporal segments /
# conflicts independently of YOLO, e.g. after changing target_classes or
# confidence without paying the YOLO cost again.
# =============================================================================

def _check_data_available(session, required_camera_positions: list) -> tuple[bool, str]:
    """Return (can_run, error_msg). Required cameras need ≥1 DetectionFrame."""
    from .models import DetectionFrame
    missing = []
    for pos in required_camera_positions:
        cam = session.cameras.filter(position=pos).first()
        if cam is None:
            missing.append(f"{pos} (caméra absente)")
            continue
        if not DetectionFrame.objects.filter(camera=cam).exists():
            missing.append(f"{pos} (aucune détection — lancer YOLO d'abord)")
    if missing:
        return False, f"Données manquantes : {', '.join(missing)}"
    return True, ''


@shared_task(bind=True)
def compute_lane_events_task(self, session_id: str):
    """Run lane events computer on the front camera's existing DetectionFrames.
    Pre-requisite : YOLO must have run on the front camera AND lane_id must
    be set on its detections (which happens when YOLOPv2 ran in the same pass)."""
    close_old_connections()
    from .models import AnalysisSession
    from .utils.pass_tracking import mark_started, mark_completed, mark_failed

    try:
        session = AnalysisSession.objects.select_related('profile').get(pk=session_id)
        ok, err = _check_data_available(session, ['front'])
        if not ok:
            mark_failed(session, 'lane_events', err)
            return {'error': err, 'session_id': session_id}

        front = session.cameras.filter(position='front').first()
        _console(session.user_id, f"Recalcul lane_events (camera front)")
        mark_started(session, 'lane_events', session.profile)
        n_events = _compute_lane_events(front, session.intersection_windows or [])
        mark_completed(session, 'lane_events', output_summary={'events_count': n_events})
        _console(session.user_id, f"  lane_events : {n_events} évènements")
        return {'session_id': session_id, 'events_count': n_events}
    except Exception as e:
        logger.error(f"compute_lane_events_task failed: {e}", exc_info=True)
        try:
            mark_failed(AnalysisSession.objects.get(pk=session_id), 'lane_events', str(e))
        except Exception:
            pass
        return {'error': str(e), 'session_id': session_id}


@shared_task(bind=True)
def compute_temporal_segments_task(self, session_id: str):
    """Run temporal segment detection on existing DetectionFrames. Filters by
    profile.target_classes + confidence at read time."""
    close_old_connections()
    from .models import AnalysisSession
    from .utils.pass_tracking import mark_started, mark_completed, mark_failed

    try:
        session = AnalysisSession.objects.select_related('profile').get(pk=session_id)
        ok, err = _check_data_available(session, [])  # any camera is fine
        if not ok:
            mark_failed(session, 'temporal_segments', err)
            return {'error': err, 'session_id': session_id}

        _console(session.user_id, f"Recalcul temporal_segments")
        mark_started(session, 'temporal_segments', session.profile)
        n_segments = detect_temporal_segments(session)
        mark_completed(session, 'temporal_segments', output_summary={
            'count': n_segments,
            'target_classes': list(session.profile.target_classes or []),
            'confidence': session.profile.confidence,
        })
        _console(session.user_id, f"  temporal_segments : {n_segments} segments")
        return {'session_id': session_id, 'count': n_segments}
    except Exception as e:
        logger.error(f"compute_temporal_segments_task failed: {e}", exc_info=True)
        try:
            mark_failed(AnalysisSession.objects.get(pk=session_id), 'temporal_segments', str(e))
        except Exception:
            pass
        return {'error': str(e), 'session_id': session_id}


@shared_task(bind=True)
def compute_conflict_events_task(self, session_id: str):
    """Run conflict events computer on existing LaneEvents + DetectionFrames.
    Pre-requisite : LaneEvents must exist (front camera analysed)."""
    close_old_connections()
    from .models import AnalysisSession, LaneEvent
    from .utils.pass_tracking import mark_started, mark_completed, mark_failed

    try:
        session = AnalysisSession.objects.select_related('profile').get(pk=session_id)
        if not LaneEvent.objects.filter(camera__session=session).exists():
            err = "Aucun LaneEvent — lancer lane_events d'abord"
            mark_failed(session, 'conflicts', err)
            return {'error': err, 'session_id': session_id}

        _console(session.user_id, f"Recalcul conflict_events")
        mark_started(session, 'conflicts', session.profile)
        n_conflicts = _compute_conflict_events(session, session.intersection_windows or [])
        mark_completed(session, 'conflicts', output_summary={'count': n_conflicts})
        _console(session.user_id, f"  conflicts : {n_conflicts} conflit(s) détecté(s)")
        return {'session_id': session_id, 'count': n_conflicts}
    except Exception as e:
        logger.error(f"compute_conflict_events_task failed: {e}", exc_info=True)
        try:
            mark_failed(AnalysisSession.objects.get(pk=session_id), 'conflicts', str(e))
        except Exception:
            pass
        return {'error': str(e), 'session_id': session_id}


# Dimensions par défaut d'un passage piéton (m) si le profil n'en fournit pas.
# Normes FR indicatives ; surchargeables par une calibration manuelle précise.
CROSSING_DEFAULT_WIDTH_M = 4.0    # largeur en travers de la route (axe X)
CROSSING_DEFAULT_LENGTH_M = 2.5   # profondeur le long de la route (axe Y)

# Cadence d'inférence SAM3 dans les fenêtres. Un marquage est STATIQUE → inutile
# d'analyser à 12 fps : ~2 fps suffit largement pour détecter/calibrer, et divise
# la charge GPU (durée + risque de crash système) d'un ordre de grandeur.
SAM3_TARGET_FPS = 2.0


def _polygon_area(poly) -> float:
    """Aire d'un polygone image (shoelace) — sert à préférer le passage le mieux segmenté."""
    n = len(poly)
    a = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _calibrate_from_crossing_polygons(session, camera, polygons, user_id,
                                      source='sam3_crossing_auto'):
    """
    Cœur PARTAGÉ (auto-scan DB + test 1-image) : depuis une liste de polygones de
    passage piéton (coords image), choisit le **mieux segmenté** (aire max) parmi
    ceux valides + à distance-échantillon plausible, enregistre l'homographie sol
    au profil (+ `geometry_enabled`) et retourne le meilleur `res` (ou None).

    N'effectue PAS la ré-annotation des distances : c'est au caller de le faire
    (l'auto-scan la fait déjà en aval). Voir CAM_ANALYZER_DISTANCE_DESIGN.md §3c.
    """
    profile = session.profile
    if not profile or not camera.width or not camera.height:
        return None
    import numpy as np
    from .utils.calibration import quad_from_polygon, homography_from_quad
    W = getattr(profile, 'crossing_total_width_m', None) or CROSSING_DEFAULT_WIDTH_M
    L = getattr(profile, 'crossing_total_length_m', None) or CROSSING_DEFAULT_LENGTH_M
    best, best_area = None, -1.0
    for poly in polygons:
        if not poly or len(poly) < 4:
            continue
        quad = quad_from_polygon(poly)
        if not quad:
            continue
        # 1) H dans le repère « passage à l'origine » (Y0=0).
        res0 = homography_from_quad(quad, W, L)
        if not res0:
            continue
        # 2) La distance du passage à la navette est INDÉTERMINÉE depuis l'image
        #    seule. Or décaler Y0 est une PURE translation du repère sol (T_k∘H).
        #    On ancre donc le repère pour que le bas-centre de l'image (sol le
        #    plus proche devant) tombe à ~`near_ground` (offset bas-de-vue→sol).
        H0 = np.asarray(res0['H'])
        pb = H0 @ np.array([camera.width / 2.0, camera.height - 1.0, 1.0])
        if abs(pb[2]) < 1e-9:
            continue
        yb0 = pb[1] / pb[2]
        near_ground = getattr(profile, 'ego_cam_to_bumper_m', None) or 2.0
        res = homography_from_quad(quad, W, L, near_distance_m=near_ground - yb0)
        if not res or not res.get('valid'):
            continue
        # Sanity finale : bas-centre plausible (devant, < 60 m).
        H = np.asarray(res['H'])
        p = H @ np.array([camera.width / 2.0, camera.height - 1.0, 1.0])
        if abs(p[2]) < 1e-9 or not (0.1 < p[1] / p[2] < 60.0):
            continue
        area = _polygon_area(poly)
        if area > best_area:
            best, best_area = res, area
    if best is None:
        return None
    # Stockage PAR CAMÉRA (par session) — plus sur le profil partagé (fin de la fuite).
    camera.ground_homography = {
        'homography': best['H'], 'source': source,
        'rms_error_m': best['rms_error_m'],
        'crossing': {'width_m': W, 'length_m': L},
    }
    camera.save(update_fields=['ground_homography'])
    if not profile.geometry_enabled:
        profile.geometry_enabled = True
        profile.save(update_fields=['geometry_enabled'])
    _console(user_id, f"Calibration [{camera.position}] depuis passage piéton "
                      f"(aire {int(best_area)} px², RMS {best['rms_error_m']} m, {source})")
    return best


def _auto_calibrate_from_crossings(session, camera, user_id):
    """
    Auto-calibration de l'homographie sol depuis les passages piétons SAM3 déjà
    enregistrés en base (scan complet). Collecte les polygones `sam3_marking`
    'crossing' de la caméra → cœur partagé `_calibrate_from_crossing_polygons`.
    """
    from .models import DetectionFrame
    polys = []
    qs = DetectionFrame.objects.filter(camera=camera).only('detections')
    for df in qs.iterator():
        for d in (df.detections or []):
            if d.get('type') == 'sam3_marking' and 'cross' in (d.get('label') or '').lower():
                poly = d.get('polygon')
                if poly and len(poly) >= 4:
                    polys.append(poly)
    return _calibrate_from_crossing_polygons(session, camera, polys, user_id)


def _reannotate_ground_distances(camera, calib_entry):
    """
    Ré-annote les distances géométriques (dist_long/lat/euclid + ground_xy) sur les
    détections déjà stockées d'une caméra, via l'homographie calibrée — SANS relancer
    YOLO. Retourne le nombre de frames modifiées.
    """
    from .models import DetectionFrame
    from .utils.ground_projection import GroundProjector
    proj = GroundProjector(calib_entry, (camera.width, camera.height))
    if not proj.available:
        return 0
    n = 0
    for df in DetectionFrame.objects.filter(camera=camera).only('detections').iterator():
        dets = df.detections or []
        changed = False
        for det in dets:
            if det.get('type') in ('road_mask', 'sam3_marking'):
                continue
            bbox = det.get('bbox')
            if not (isinstance(bbox, (list, tuple)) and len(bbox) >= 4):
                continue
            g = proj.distances_for_bbox(bbox)
            if g:
                det.update(g)
                changed = True
        if changed:
            df.detections = dets
            df.save(update_fields=['detections'])
            n += 1
    return n


def _free_memory_before_sam3(user_id=None):
    """Nettoyage VRAM/RAM avant SAM3 (gros modèle, sujet aux crashes GPU) : décharge le
    modèle yolopv2 gardé en cache (keep_loaded, hors model_manager) + cleanup agressif du
    model_manager (modèles idle, GPU cache, GC ×3). Non bloquant."""
    try:
        from .utils.yolopv2_segmenter import clear_model_cache
        clear_model_cache()
    except Exception:
        logger.debug('clear yolopv2 cache failed', exc_info=True)
    try:
        from wama.model_manager.services import get_memory_cleaner
        get_memory_cleaner().aggressive_cleanup()
    except Exception:
        logger.debug('aggressive_cleanup failed', exc_info=True)
    try:
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    if user_id:
        try:
            _console(user_id, "VRAM/RAM nettoyées avant SAM3 (modèles déchargés)")
        except Exception:
            pass


@shared_task(bind=True)
def annotate_prediction_task(self, session_id: str):
    """Calcule les indicateurs Prédiction (TTC/PET par trajectoire) pour la session et les
    stocke sur les détections (prediction_ttc/pet). Ré-annotation, pas de re-détection."""
    from .models import AnalysisSession
    from .utils.prediction_adapter import annotate_prediction_indicators
    from .utils.multicam_tracker import annotate_global_tracks
    session = AnalysisSession.objects.get(pk=session_id)
    # 1) Tracks globaux multi-caméra (rapide) → continuité 360° + hand-off.
    _gt = annotate_global_tracks(session)
    ng = _gt['tracks']
    stat = _gt.get('stationary_gids', [])
    rs = session.results_summary or {}
    rs['stationary_global_tracks'] = stat
    session.results_summary = rs
    session.save(update_fields=['results_summary'])
    _console(session.user_id, f"Tracking multi-caméra : {ng} tracks globaux (hand-off), "
                              f"{len(stat)} véhicules stationnés détectés.")
    # 2) Prédiction TTC/PET par trajectoire.
    n = annotate_prediction_indicators(session)
    _console(session.user_id, f"Prédiction : {n} détections annotées (TTC/PET par trajectoire).")
    return {'session': session_id, 'global_tracks': ng, 'annotated': n}


@shared_task(bind=True)
def sam3_test_frame_task(self, session_id: str, position: str, frame_number: int,
                         min_confidence: float = 0.0, calibrate: bool = False):
    """
    Diagnostic : lance SAM3 sur UNE frame choisie et met en cache TOUS les masks
    (polygones + scores, seuil `min_confidence`, 0 = tout) → permet de vérifier si
    SAM3 accroche un passage clairement visible et de régler le seuil, SANS lancer
    un scan complet (charge GPU minime). Résultat en cache `sam3_test_<session>`.

    Si `calibrate=True` : utilise en plus le meilleur passage détecté sur cette
    frame pour calibrer l'homographie sol (cœur partagé avec l'auto-scan) puis
    ré-annote les distances sol — la chaîne « une frame → vue de dessus ».
    """
    import cv2
    from django.core.cache import cache
    from .models import AnalysisSession
    key = f"sam3_test_{session_id}"
    sam3 = None
    try:
        session = AnalysisSession.objects.select_related('profile').get(pk=session_id)
        cam = session.cameras.filter(position=position).first()
        if not cam or not getattr(cam, 'video_file', None):
            cache.set(key, {'status': 'error', 'error': 'Caméra/vidéo introuvable'}, 600)
            return
        capd = cv2.VideoCapture(cam.video_file.path)
        capd.set(cv2.CAP_PROP_POS_FRAMES, int(frame_number))
        ok, frame = capd.read()
        capd.release()
        if not ok:
            cache.set(key, {'status': 'error', 'error': 'Frame introuvable'}, 600)
            return
        prompts = list(getattr(session.profile, 'sam3_markings_prompts', []) or [])
        from .utils.sam3_road_analyzer import SAM3RoadAnalyzer
        _free_memory_before_sam3(session.user_id)   # libérer la VRAM avant SAM3
        sam3 = SAM3RoadAnalyzer(marking_prompts=prompts or None)
        sam3.load()
        markings = sam3.analyze_frame(frame, min_confidence=float(min_confidence))
        out = [{'label': m.get('label'), 'confidence': m.get('confidence'),
                'polygon': m.get('polygon'), 'bbox': m.get('bbox')}
               for m in markings if m.get('type') == 'sam3_marking']

        calib_info = None
        if calibrate:
            cross_polys = [m['polygon'] for m in out
                           if m.get('polygon') and 'cross' in (m.get('label') or '').lower()]
            if not cross_polys:
                calib_info = {'ok': False, 'error': 'Aucun passage piéton détecté sur cette frame'}
            else:
                best = _calibrate_from_crossing_polygons(
                    session, cam, cross_polys, session.user_id, source='sam3_crossing_test')
                if best:
                    try:
                        _reannotate_ground_distances(cam, cam.ground_homography)
                    except Exception:
                        logger.debug('reannotate after test calib failed', exc_info=True)
                    calib_info = {'ok': True, 'position': cam.position,
                                  'rms_error_m': best['rms_error_m']}
                else:
                    calib_info = {'ok': False,
                                  'error': 'Passage détecté mais non exploitable (géométrie invalide)'}

        cache.set(key, {'status': 'done', 'frame_number': int(frame_number),
                        'width': cam.width, 'height': cam.height,
                        'prompts': [p.get('prompt') for p in prompts],
                        'markings': out, 'count': len(out),
                        'calibration': calib_info}, 600)
    except Exception as e:
        logger.error(f"sam3_test_frame failed: {e}", exc_info=True)
        cache.set(key, {'status': 'error', 'error': str(e)}, 600)
    finally:
        if sam3 is not None:
            try:
                sam3.unload()
            except Exception:
                pass


@shared_task(bind=True)
def analyze_sam3_only_task(self, session_id: str):
    """
    Re-run SAM3 road-marking detection on the front camera without touching
    the YOLO results.

    Inputs (must already exist on the session):
      - front CameraView with an extracted .mp4
      - session.intersection_windows (recompute Pass A first if stale)
      - profile.sam3_markings_enabled = True (master switch)

    Behaviour:
      - For each frame inside any intersection window, run SAM3.
      - For the matching DetectionFrame (created by the previous YOLO pass):
          drop entries with type in {'sam3_marking', 'road_mask'}, append fresh
          SAM3 entries.
      - If no DetectionFrame exists for that frame_idx (user toggled
        restrict_to_intersection_windows OFF after a YOLO pass that ran with
        it ON, etc.), create one with the SAM3 entries only.
      - YOLO entries are never read or written.
    """
    close_old_connections()

    from .models import AnalysisSession, DetectionFrame
    sam3 = None
    _previous_status = None
    try:
        session = AnalysisSession.objects.select_related('profile').get(pk=session_id)
        user_id = session.user_id
        profile = session.profile

        # Garde d'idempotence : si l'analyse a été ANNULÉE (flag persistant), sortir
        # AVANT de charger SAM3. Sinon une tâche RE-LIVRÉE par Redis (crash worker →
        # visibility_timeout 6h) relançait SAM3 en boucle après annulation/redémarrage
        # — d'où « SAM3 se relance à chaque redémarrage » et « cancel sans effet ».
        # (La relance vide le flag via run_passes, donc une vraie relance repart bien.)
        if _is_cancelled(user_id):
            _console(user_id, "SAM3 : annulation détectée au démarrage — tâche ignorée (pas de relance).")
            return {'status': 'cancelled', 'reason': 'cancel_flag'}

        if not profile or not getattr(profile, 'sam3_markings_enabled', False):
            raise ValueError("SAM3 désactivé sur le profil")

        # Park the previous status (typically COMPLETED from the YOLO pass) and
        # flip to PROCESSING so the frontend polling keeps tracking progress
        # instead of stopping on the first tick. Restored to COMPLETED at the
        # end so the UI reloads the freshly-patched detections.
        _previous_status = session.status
        session.status = AnalysisSession.Status.PROCESSING
        session.progress = 0.0
        session.save(update_fields=['status', 'progress'])

        windows = session.intersection_windows or []
        raw_prompts = list(getattr(profile, 'sam3_markings_prompts', []) or [])

        # Enrichissement par le PIPELINE COMMUN (skill `cam_analyzer-transport`) :
        # traduit + met en forme « concept » anglophone attendu par SAM3, au lieu
        # de passer le prompt brut (fin de la particularité cam_analyzer). Fallback
        # = prompt d'origine si le LLM local est injoignable. Voir PROMPT_PIPELINE.md.
        try:
            from wama.common.utils.prompt_enrichment import enrich_on_demand
            _enriched = []
            for _pd in raw_prompts:
                _base = (_pd.get('prompt') or '').strip()
                if not _base:
                    continue
                try:
                    _concept = enrich_on_demand(_base, app='cam_analyzer', domain='transport')
                except Exception:
                    _concept = _base   # LLM injoignable → on garde le prompt tel quel
                _enriched.append({**_pd, 'prompt': _concept})
            if _enriched:
                raw_prompts = _enriched
        except Exception:
            logger.debug('SAM3 prompt enrichment skipped (non-blocking)', exc_info=True)
        # The "road fallback" is meant to make SAM3 generate the drivable area
        # mask when no other road segmenter is wired in. When the profile has
        # a road_model_path (YOLOPv2 or equivalent), that backend already
        # produces road_mask entries during the YOLO pass — running SAM3
        # globally would double-up and waste hours of GPU time. We disable
        # the fallback in that case, matching the historical inline behaviour
        # in process_session_task. SAM3 then runs ONLY inside the
        # intersection windows.
        fallback_requested = bool(getattr(profile, 'sam3_as_road_fallback', False))
        has_external_road_segmenter = bool(getattr(profile, 'road_model_path', ''))
        use_fallback = fallback_requested and not has_external_road_segmenter

        if not (raw_prompts or use_fallback):
            raise ValueError("Aucun prompt SAM3 configuré")
        if not windows and not use_fallback:
            raise ValueError("Aucune fenêtre d'intersection — recalcule d'abord (Pass A)")

        front = session.cameras.filter(position='front').first()
        if not front:
            raise ValueError("Caméra avant introuvable")
        video_path = front.video_file.path
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Vidéo avant introuvable : {video_path}")

        _console(user_id, f"SAM3 seul : {session.name}")
        from .utils.pass_tracking import mark_started, mark_completed, mark_failed
        mark_started(session, 'sam3_markings', profile, camera=front)
        set_session_progress(session_id, 1, "Chargement SAM3...")

        from .utils.sam3_road_analyzer import SAM3RoadAnalyzer
        _free_memory_before_sam3(user_id)   # libérer la VRAM avant SAM3 (anti-crash)
        sam3 = SAM3RoadAnalyzer(
            marking_prompts=raw_prompts or None,
            road_fallback=use_fallback,
        )
        sam3.load()
        # Log des prompts RÉELLEMENT utilisés (vérifier langue/forme : SAM3 attend
        # des descriptions nominales EN, ex. "pedestrian crossing zebra stripes").
        _prompts_str = " | ".join(
            f"{p.get('label', '?')}=«{p.get('prompt', '')}»" for p in raw_prompts
        ) or "(aucun)"
        _console(user_id, f"Prompts SAM3 : {_prompts_str}")
        logger.info("[SAM3] prompts utilisés : %s", [p.get('prompt') for p in raw_prompts])
        if use_fallback:
            scope_label = (
                f"  SAM3 chargé — {len(raw_prompts)} prompt(s) marquages "
                f"+ fallback route (aucun road_model_path) → "
                f"inférence sur TOUTES les frames"
            )
        elif fallback_requested and has_external_road_segmenter:
            scope_label = (
                f"  SAM3 chargé — {len(raw_prompts)} prompt(s) marquages "
                f"— fallback route IGNORÉ (road_model_path={os.path.basename(profile.road_model_path)} "
                f"fournit déjà le road_mask). SAM3 limité aux {len(windows)} fenêtre(s) d'intersection"
            )
        else:
            scope_label = (
                f"  SAM3 chargé — {len(raw_prompts)} prompt(s) marquages, "
                f"limité aux {len(windows)} fenêtre(s) d'intersection"
            )
        _console(user_id, scope_label)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Impossible d'ouvrir la vidéo : {video_path}")
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        # Pre-fetch existing DetectionFrames for this camera, indexed by frame_number,
        # so we can patch in place without N round-trips to the DB.
        existing = {
            df.frame_number: df
            for df in DetectionFrame.objects.filter(camera=front).only(
                'id', 'frame_number', 'detections'
            )
        }

        new_frames = []
        updated = 0
        created = 0
        scanned = 0
        last_progress_frame = 0

        # Sous-échantillonnage : 1 frame sur `sam3_stride` (≈ SAM3_TARGET_FPS).
        sam3_stride = max(1, int(round(fps / SAM3_TARGET_FPS)))
        _console(user_id, f"SAM3 ~{SAM3_TARGET_FPS:g} fps (1 frame/{sam3_stride}) dans les fenêtres")

        frame_idx = -1
        while True:
            ok = cap.grab()          # avance SANS décoder → skip peu coûteux hors zone
            if not ok:
                break
            frame_idx += 1
            timestamp = frame_idx / fps

            if frame_idx % 200 == 0 and _is_cancelled(user_id):
                cap.release()
                raise InterruptedError("Annulé par l'utilisateur")

            in_window = use_fallback or any(
                w['t_enter'] <= timestamp <= w['t_exit'] for w in windows
            )
            # Hors fenêtre OU entre deux échantillons → ni décodage ni SAM3.
            if not in_window or (frame_idx % sam3_stride) != 0:
                continue

            ok2, frame_bgr = cap.retrieve()   # décodage UNIQUEMENT ici
            if not ok2:
                continue

            scanned += 1
            try:
                markings = sam3.analyze_frame(frame_bgr)
            except Exception as exc:
                logger.debug(f"[SAM3-only] frame {frame_idx}: {exc}")
                markings = []

            df = existing.get(frame_idx)
            if df is not None:
                # On ne remplace `road_mask` (segmentation YOLOPv2) QUE si SAM3 sert
                # de fallback route ; sinon on préserve la route et on ne remplace
                # que les anciens marquages SAM3. (Bug : SAM3 écrasait la route même
                # sans rien trouver → segmentation routière qui disparaissait.)
                drop_types = ('sam3_marking', 'road_mask') if use_fallback else ('sam3_marking',)
                kept = [
                    d for d in (df.detections or [])
                    if d.get('type') not in drop_types
                ]
                df.detections = kept + markings
                df.save(update_fields=['detections'])
                updated += 1
            else:
                new_frames.append(DetectionFrame(
                    camera=front,
                    frame_number=frame_idx,
                    timestamp=round(timestamp, 4),
                    detections=markings,
                ))
                created += 1
                if len(new_frames) >= 500:
                    DetectionFrame.objects.bulk_create(new_frames)
                    new_frames = []

            # Libère périodiquement la VRAM (évite l'accumulation → crash) +
            # log de progression dans celery-gpu.log (aucun log intermédiaire avant).
            if scanned % 50 == 0:
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:
                    pass
                logger.info(f"[SAM3] {frame_idx}/{total_frames} balayées, "
                            f"{scanned} analysées ({updated} maj, {created} créées)")

            if frame_idx - last_progress_frame >= 50 and total_frames > 0:
                pct = 1 + (frame_idx / total_frames) * 98
                set_session_progress(session_id, pct, f"SAM3 frame {frame_idx}/{total_frames}")
                last_progress_frame = frame_idx

        cap.release()
        if new_frames:
            DetectionFrame.objects.bulk_create(new_frames)

        # Mark COMPLETED so the polling loop on the frontend triggers
        # loadAllDetections() and the freshly-patched SAM3 entries become
        # visible in the canvas overlay.
        session.status = AnalysisSession.Status.COMPLETED
        session.progress = 100.0
        session.completed_at = timezone.now()
        session.save(update_fields=['status', 'progress', 'completed_at'])

        mark_completed(session, 'sam3_markings', camera=front, output_summary={
            'scanned': scanned, 'updated': updated, 'created': created,
            'prompts': [p.get('label', '') for p in (profile.sam3_markings_prompts or [])],
            'fallback': bool(getattr(profile, 'sam3_as_road_fallback', False)),
        })

        # ── Auto-calibration homographie depuis les passages piétons détectés ──
        # Si un passage exploitable est trouvé : calibre H (cœur partagé) puis
        # ré-annote les distances géométriques SANS relancer YOLO. Best-effort,
        # non bloquant (le fallback pinhole reste si ça échoue).
        try:
            cal = _auto_calibrate_from_crossings(session, front, user_id)
            if cal:
                n = _reannotate_ground_distances(front, {'homography': cal['H']})
                _console(user_id, f"Distances géométriques ré-annotées sur {n} frame(s) [{front.position}]")
        except Exception:
            logger.debug('auto-calibration from SAM3 failed (non-blocking)', exc_info=True)

        set_session_progress(session_id, 100, "SAM3 terminé")
        _console(user_id,
                 f"SAM3 terminé — {scanned} frame(s) analysée(s), "
                 f"{updated} mises à jour, {created} créée(s)")

        return {
            'session_id': session_id,
            'sam3_only': True,
            'scanned': scanned,
            'updated': updated,
            'created': created,
        }

    except InterruptedError as e:
        try:
            session = AnalysisSession.objects.get(pk=session_id)
            # Restore previous status so we don't leave the session stuck in
            # PROCESSING after a cancel.
            if _previous_status is not None:
                session.status = _previous_status
                session.save(update_fields=['status'])
            cache.delete(f"stop_cam_analyzer_{session.user_id}")
            # Ne pas laisser la passe SAM3 bloquée en 'running' après annulation.
            from .models import AnalysisPass
            AnalysisPass.objects.filter(session=session, pass_type='sam3_markings',
                                        status='running').update(status='failed')
            _console(session.user_id, "SAM3 annulé")
        except Exception:
            pass
        return {'cancelled': session_id}

    except Exception as e:
        logger.error(f"SAM3-only failed for session {session_id}: {e}", exc_info=True)
        try:
            session = AnalysisSession.objects.get(pk=session_id)
            if _previous_status is not None:
                session.status = _previous_status
                session.save(update_fields=['status'])
            # Ne pas laisser la passe SAM3 bloquée en 'running' après un crash.
            from .models import AnalysisPass
            AnalysisPass.objects.filter(session=session, pass_type='sam3_markings',
                                        status='running').update(status='failed')
            _console(session.user_id, f"ERREUR SAM3: {e}")
        except Exception:
            pass
        return {'error': str(e), 'session_id': session_id}

    finally:
        if sam3 is not None:
            try:
                sam3.unload()
            except Exception:
                pass


# =============================================================================
# RTMaps Extraction Task
# =============================================================================

@shared_task(bind=True)
def extract_rtmaps_task(self, session_id: str, rec_path: str = None, csv_path: str = None,
                        quad_avi_path: str = None):
    """
    Extract camera views and GPS data.

    Two modes:
    - rec_path provided: parse binary RTMaps .rec → extract H264 → crop views
    - quad_avi_path provided: AVI already extracted by RTMaps Player → crop views directly

    Steps:
    1. GPS: parse from .rec (NMEA) or csv_path (RTMaps oPosition / Navya API CSV)
    2. [rec_path only] Extract H264 frames from .rec binary → quadrature AVI
    3. Crop quadrature AVI → front.avi + rear.avi
    4. Create CameraView records
    5. Save GPS track to session.gps_track
    6. Launch process_session_task
    """
    close_old_connections()

    from .models import AnalysisSession, CameraView
    from .utils.rtmaps_parser import RTMapsParser, merge_with_api_csv
    from .utils.quadrature_video import (
        export_quadrature_view,
        LAYOUT_NAVYA,
        detect_quadrature_layout,
    )

    EXTRACT_CACHE_KEY = f"cam_analyzer_extract_{session_id}"

    def _set_progress(pct, msg=None):
        cache.set(EXTRACT_CACHE_KEY, {'progress': pct, 'status': msg or ''}, timeout=3600)

    try:
        session = AnalysisSession.objects.get(pk=session_id)
        user_id = session.user_id

        # Extracted views go alongside the input quadrature file under input/rtmaps/
        output_dir = os.path.join(settings.MEDIA_ROOT, 'cam_analyzer', str(user_id), 'input', 'rtmaps')
        os.makedirs(output_dir, exist_ok=True)

        import re as _re
        session_slug = _re.sub(r'[^a-zA-Z0-9_-]', '_', session.name or str(session_id)[:8])

        if quad_avi_path:
            # ── Mode AVI pré-exporté ─────────────────────────────────────
            _console(user_id, f"Import quadrature AVI : {os.path.basename(quad_avi_path)}")
            _set_progress(5, "Lecture du GPS...")

            # GPS from CSV only (no .rec parsing)
            gps_track = merge_with_api_csv([], csv_path)
            if not gps_track:
                _console(user_id, "AVERTISSEMENT: aucun GPS fourni — analyse intersection sans GPS")
            else:
                _console(user_id, f"GPS: {len(gps_track)} points (CSV RTMaps)")

            _set_progress(20, "Découpage des vues quadrature...")
            quad_path = quad_avi_path

        else:
            # ── Mode .rec binaire ────────────────────────────────────────
            _console(user_id, "Extraction RTMaps démarrée...")
            _set_progress(2, "Lecture du fichier .rec...")

            # ── 1. Parse GPS + metadata from .rec ────────────────────────
            parser = RTMapsParser()
            parsed = parser.parse(rec_path)
            _set_progress(15, "GPS extrait, fusion CSV...")

            gps_track = merge_with_api_csv(parsed['gps'], csv_path)
            if not gps_track:
                _console(user_id, "AVERTISSEMENT: aucune donnée GPS extraite")
            else:
                _console(user_id, f"GPS: {len(gps_track)} points extraits")

            _set_progress(20, "Extraction de la vidéo quadrature...")

            # ── 2. Extract H264 from .rec binary ─────────────────────────
            quad_path = os.path.join(output_dir, f"{session_slug}_quad.avi")
            _extract_h264_frames_to_avi(rec_path, quad_path, user_id)
            if not os.path.exists(quad_path):
                raise RuntimeError(f"Quadrature video extraction failed: {quad_path}")

        # ── Cleanup any prior CameraView records BEFORE extraction ───────
        # Previous extractions used the same deterministic output paths
        # ({slug}_front.mp4, {slug}_rear.mp4). If we did this AFTER extraction,
        # FileField.delete() would wipe the freshly-written files. Doing it
        # first makes re-extraction idempotent.
        for existing in session.cameras.all():
            if existing.video_file:
                try:
                    existing.video_file.delete(save=False)
                except Exception:
                    pass
        session.cameras.all().delete()

        _set_progress(60, "Crop des 4 vues...")

        # ── 4. Crop all 4 views from the quadrature ──────────────────────
        # Primary path : ffmpeg `-vf crop` × 4 in parallel, libx264 CRF 18.
        # Per-view fallback : OpenCV decoder → ffmpeg stdin pipe (path A).
        # Last-resort fallback : legacy OpenCV writer + _ensure_h264.
        layout = detect_quadrature_layout(quad_path) or LAYOUT_NAVYA
        if layout is LAYOUT_NAVYA:
            _console(user_id, "  Layout quadrature : par défaut (LAYOUT_NAVYA)")
        else:
            sizes = ', '.join(
                f"{p} {layout[p][2]-layout[p][0]}×{layout[p][3]-layout[p][1]}"
                for p in ('front', 'rear', 'left', 'right')
            )
            _console(user_id, f"  Layout quadrature auto-détecté : {sizes}")

        view_specs = [
            ('front', 65), ('rear', 73), ('left', 80), ('right', 87),
        ]
        view_pct = {p: pct for p, pct in view_specs}
        view_metas: dict = {}

        try:
            from .utils.quadrature_video import export_quadrature_views_parallel
            _set_progress(62, "Crop ffmpeg parallèle des 4 vues...")

            def _ffmpeg_progress_cb(pos, status):
                pct = view_pct.get(pos, 80)
                label_map = {
                    'ok': f"Vue {pos} prête",
                    'ok_via_pipe': f"Vue {pos} prête (via pipe)",
                    'failed_will_retry': f"Vue {pos} : retry via pipe…",
                    'failed': f"Vue {pos} échouée",
                }
                _set_progress(pct, label_map.get(status, f"Vue {pos}: {status}"))

            view_metas = export_quadrature_views_parallel(
                quad_path, layout, output_dir, session_slug,
                crf=18, progress_callback=_ffmpeg_progress_cb,
            )
            n_pipe = sum(1 for m in view_metas.values() if m.get('fallback_used') == 'pipe')
            if n_pipe:
                _console(user_id, f"  {n_pipe} vue(s) extraites via pipe OpenCV→ffmpeg (fallback)")
        except Exception as e:
            # Last-resort fallback when ffmpeg isn't available at all : legacy
            # OpenCV writer (MJPG/avc1) + _ensure_h264 re-encode.
            logger.warning(f"[RTMaps] parallel ffmpeg extraction unavailable ({e}), legacy path")
            _console(user_id, f"  AVERTISSEMENT: extraction ffmpeg indisponible ({e}), fallback legacy")
            from wama.common.utils.video_compat import ensure_h264
            view_metas = {}
            for pos, pct in view_specs:
                dst = os.path.join(output_dir, f"{session_slug}_{pos}.mp4")
                try:
                    meta = export_quadrature_view(quad_path, dst, pos, layout)
                    actual_path = meta.get('path')
                    if actual_path and os.path.exists(actual_path):
                        try:
                            converted = ensure_h264(actual_path)
                            if isinstance(converted, str):
                                meta['path'] = converted
                        except Exception as ee:
                            logger.warning(f"[RTMaps] ensure_h264 failed: {ee}")
                    view_metas[pos] = meta
                    _set_progress(pct, f"Vue {pos} prête (legacy)")
                except Exception as ee:
                    logger.error(f"[RTMaps] legacy extract failed for '{pos}': {ee}")
                    view_metas[pos] = {'error': str(ee)}
                    _set_progress(pct, f"Extraction {pos} échouée: {ee}")

        # ── 5. Create CameraView records ─────────────────────────────────
        for pos, meta in view_metas.items():
            if 'error' in meta:
                _console(user_id, f"AVERTISSEMENT: vue {pos} non disponible: {meta['error']}")
                continue
            actual_fpath = meta.get('path')
            if not actual_fpath:
                continue
            rel_path = os.path.relpath(actual_fpath, settings.MEDIA_ROOT).replace('\\', '/')
            cam = CameraView(
                session=session,
                position=pos,
                label=f"RTMaps {pos}",
            )
            cam.video_file.name = rel_path
            cam.fps = meta.get('fps')
            cam.width = meta.get('width')
            cam.height = meta.get('height')
            cam.duration = meta.get('duration')
            cam.save()
            _console(user_id, f"Caméra {pos} : {meta.get('frame_count', 0)} frames, {meta.get('duration', 0):.1f}s")

        # ── 6. Parse IMU (accéléromètre) depuis les CSV par canal ────────
        # Les fichiers Accel_Sensor_{X,Y,Z}_axis.csv sont dans le même dossier
        # RecFile_Data que le .rec / la CSV API. Best-effort : l'absence d'IMU
        # ne bloque pas l'extraction (ego-pose retombe sur le GPS seul).
        imu_track = []
        try:
            from .utils.ego_pose import parse_accel
            _rec_dir = os.path.dirname(rec_path or csv_path or '')
            if _rec_dir and os.path.isdir(_rec_dir):
                imu_track = parse_accel(_rec_dir)
                if imu_track:
                    _console(user_id, f"IMU : {len(imu_track)} échantillons accéléromètre")
        except Exception:
            logger.debug('IMU parsing failed (non-blocking)', exc_info=True)

        # ── 7. Save GPS + IMU tracks + source type + reset status ────────
        # Annoter cap + vitesse depuis les positions (sinon heading/speed restent à 0
        # dans le track stocké → vue de dessus mal orientée). C'est la même fonction
        # que celle utilisée par EgoPose, mais appliquée AU TRACK PERSISTÉ.
        try:
            from .utils.ego_pose import annotate_gps_heading_speed
            gps_track = annotate_gps_heading_speed(gps_track)
        except Exception:
            logger.debug('annotate GPS heading/speed failed (non-blocking)', exc_info=True)
        session.gps_track = gps_track
        session.imu_track = imu_track
        session.source_type = 'rtmaps'
        # Reset to DRAFT so user can review videos before launching analysis manually
        session.status = AnalysisSession.Status.DRAFT
        session.progress = 0.0
        session.save(update_fields=['gps_track', 'imu_track', 'source_type', 'status', 'progress'])

        # Synchro GPS↔vidéo AUTO depuis le .rec (parser commun) : scale corrige un fps AVI
        # erroné (désync qui grandit) + offset = décalage de départ. Best-effort.
        try:
            import glob as _glob
            _sync_rec = rec_path if (rec_path and os.path.exists(rec_path)) else None
            if not _sync_rec:
                _cands = [r for r in _glob.glob(os.path.join(os.path.dirname(csv_path or ''), '*.rec'))
                          if 'LogConsole' not in os.path.basename(r)]
                _sync_rec = _cands[0] if _cands else None
            if _sync_rec:
                from wama.common.rtmaps.rec_parser import parse_rec
                _p = parse_rec(_sync_rec)
                _vt = _p.get('video_timestamps') or []
                _gp = _p.get('gps') or []
                _fps = getattr(session.cameras.first(), 'fps', None) or 12.0
                if len(_vt) >= 100 and len(_gp) >= 10:
                    session.gps_time_scale = round(_fps * (_vt[-1] - _vt[0]) / (len(_vt) - 1), 5)
                    session.gps_time_offset = round(_vt[0] - _gp[0]['ts'], 4)
                    session.save(update_fields=['gps_time_scale', 'gps_time_offset'])
                    _console(user_id, f"Synchro GPS auto (.rec) : scale={session.gps_time_scale} "
                                      f"offset={session.gps_time_offset}s")
        except Exception:
            logger.debug('GPS sync from .rec failed (non-blocking)', exc_info=True)

        _set_progress(100, "Extraction terminée — prêt pour analyse")
        try:
            from .utils.pass_tracking import mark_completed as _mc
            _mc(session, 'extraction', output_summary={
                'views': sorted(view_metas.keys()),
                'sizes': {k: f"{v.get('width','?')}x{v.get('height','?')}"
                          for k, v in view_metas.items()},
            })
        except Exception:
            logger.debug('extraction pass tracking failed', exc_info=True)
        _console(user_id, "Extraction terminée. Vérifiez les vues puis cliquez sur 'Analyser'.")
        return {'extracted': session_id}

    except Exception as e:
        logger.error(f"RTMaps extraction failed for session {session_id}: {e}", exc_info=True)
        try:
            session = AnalysisSession.objects.get(pk=session_id)
            session.status = AnalysisSession.Status.FAILED
            session.error_message = f"Extraction RTMaps échouée: {e}"
            session.save(update_fields=['status', 'error_message'])
            _console(session.user_id, f"ERREUR extraction RTMaps: {e}")
        except Exception:
            pass
        cache.set(
            f"cam_analyzer_extract_{session_id}",
            {'progress': 0, 'status': f'Erreur: {e}'},
            timeout=3600,
        )
        return {'error': str(e), 'session_id': session_id}


def _extract_h264_frames_to_avi(rec_path: str, output_avi: str, user_id: int) -> None:
    """
    Extract H264 video frames from RTMaps .rec binary stream and write them
    to an AVI file.

    RTMaps stores each video frame as a binary blob in the record line after '='.
    For H264 streams, the blob starts with a NAL unit header (0x00 0x00 0x00 0x01).

    Approach: scan rec file for lines matching the h264 stream, decode each
    frame using cv2.imdecode on the raw JPEG-encoded data embedded in NAL units,
    OR use ffmpeg to remux directly from the rec file if available.
    """
    import subprocess
    import re

    # Strategy 1: Try ffmpeg direct remux (fastest, most reliable)
    # RTMaps .rec files may be playable directly by ffmpeg as raw H264
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', rec_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and 'h264' in result.stdout.lower():
            proc = subprocess.run(
                ['ffmpeg', '-i', rec_path, '-c:v', 'copy', output_avi, '-y'],
                capture_output=True, text=True, timeout=600,
            )
            if proc.returncode == 0 and os.path.exists(output_avi):
                logger.info(f"[RTMaps] ffmpeg direct remux succeeded: {output_avi}")
                return
    except Exception as e:
        logger.debug(f"[RTMaps] ffmpeg direct remux not available: {e}")

    # Strategy 2: Parse .rec lines, extract JPEG signatures frame-by-frame
    # RTMaps sometimes encodes video frames as Motion JPEG or JPEG-in-H264
    logger.info(f"[RTMaps] Parsing .rec for video frames: {rec_path}")

    VIDEO_STREAM_RE = re.compile(r'h264_stream', re.IGNORECASE)
    LINE_RE = re.compile(r'^(\d+:\d+\.\d+)\s*/\s*([^#]+)#(\d+)@(\d+)=(.*)$', re.DOTALL)

    frames = []
    timestamps = []

    with open(rec_path, 'r', encoding='utf-8', errors='replace') as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            m = LINE_RE.match(line)
            if not m:
                continue
            _, stream_name, _, ts_str, value = m.groups()
            if not VIDEO_STREAM_RE.search(stream_name):
                continue

            # Attempt to decode as JPEG
            import numpy as np
            import cv2 as _cv2
            raw_bytes = value.encode('latin-1', errors='replace')
            jpeg_start = raw_bytes.find(b'\xff\xd8')
            if jpeg_start != -1:
                arr = np.frombuffer(raw_bytes[jpeg_start:], dtype=np.uint8)
                img = _cv2.imdecode(arr, _cv2.IMREAD_COLOR)
                if img is not None:
                    frames.append(img)
                    timestamps.append(int(ts_str))

    if not frames:
        logger.warning(f"[RTMaps] No video frames extracted from {rec_path}")
        raise RuntimeError(
            "Impossible d'extraire les frames vidéo du fichier .rec. "
            "Vérifiez que le fichier contient un stream H264/MJPEG."
        )

    # Compute FPS from timestamp differences
    import numpy as np
    fps = 12.0
    if len(timestamps) > 1:
        diffs = np.diff(timestamps)
        median_dt = float(np.median(diffs))
        if median_dt > 0:
            fps = round(1e9 / median_dt, 2)

    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
    writer = cv2.VideoWriter(output_avi, fourcc, fps, (w, h))
    for frame in frames:
        writer.write(frame)
    writer.release()

    logger.info(f"[RTMaps] Wrote {len(frames)} frames @ {fps} fps -> {output_avi}")
