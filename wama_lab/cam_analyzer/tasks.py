"""
Celery tasks for Cam Analyzer.
YOLO detection + tracking pipeline on multi-camera video sessions.
"""
import gc
import logging
import os
import time

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
    cache.set(f"stop_cam_analyzer_{user_id}", True, timeout=600)


def _is_cancelled(user_id: int) -> bool:
    """Check if cancellation was requested."""
    return bool(cache.get(f"stop_cam_analyzer_{user_id}", False))


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
            segments.append(TemporalSegment(
                session=session,
                camera=camera,
                segment_type=r['type'],    # 'insertion_front' | 'intersection_stop'
                start_time=r['start'],
                end_time=r['end'],
                metadata=r['metadata'],
            ))

    logger.info(f"[intersection] {len(segments)} segments detected across {len(windows)} windows")
    return segments


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
def process_session_task(self, session_id: str):
    """
    Process a cam analyzer session:
    - Load YOLO model from profile
    - Run tracking on each camera's video
    - Store DetectionFrame records
    - Generate annotated output videos
    - Compute results_summary
    """
    close_old_connections()

    from .models import AnalysisSession, DetectionFrame

    model = None
    start_time = time.time()

    try:
        session = AnalysisSession.objects.select_related('profile').get(pk=session_id)
        user_id = session.user_id
        profile = session.profile

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
        cameras = list(session.cameras.all().order_by('position'))
        num_cameras = len(cameras)

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

        # ── Pre-compute intersection windows (for SAM3 temporal gating) ─────────
        _sam3_windows = []
        if (profile.report_type == 'intersection_insertion'
                and getattr(profile, 'sam3_markings_enabled', False)
                and session.gps_track
                and profile.intersections):
            from .utils.intersection_analyzer import IntersectionAnalyzer as _IA
            _sam3_windows = _IA(
                intersections=profile.intersections,
                gps_track=session.gps_track,
                fps=12.0,        # approximate — refined per-camera inside the loop
                frame_height=250,
            ).find_intersection_windows()
            _console(user_id, f"SAM3: {len(_sam3_windows)} fenêtre(s) d'intersection pré-calculée(s)")

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

            set_session_progress(session_id, cam_progress_start,
                                 f"Analyse caméra {position} ({cam_idx + 1}/{num_cameras})...")

            # ─── Road segmenter (intersection_insertion + front only) ─────────
            road_segmenter = None
            if (profile.report_type == 'intersection_insertion'
                    and position == 'front'
                    and getattr(profile, 'road_model_path', '')):
                road_model_path = profile.road_model_path
                if not os.path.isabs(road_model_path):
                    road_model_path = os.path.join(settings.BASE_DIR, road_model_path)
                if os.path.exists(road_model_path):
                    from .utils.road_segmenter import RoadSegmenter
                    road_segmenter = RoadSegmenter(road_model_path, device=device)
                    road_segmenter.load()
                    _console(user_id, f"  Segmenteur routier chargé: {os.path.basename(road_model_path)}")
                else:
                    _console(user_id, f"  AVERTISSEMENT: road_model_path introuvable: {road_model_path}")

            # ─── SAM3 road markings analyzer (Phase Avancée) ──────────────────
            sam3_analyzer = None
            _use_sam3_fallback = (
                getattr(profile, 'sam3_as_road_fallback', False) and road_segmenter is None
            )
            if (position == 'front'
                    and profile.report_type == 'intersection_insertion'
                    and (_sam3_windows or _use_sam3_fallback)
                    and (getattr(profile, 'sam3_markings_enabled', False) or _use_sam3_fallback)):
                raw_prompts = getattr(profile, 'sam3_markings_prompts', []) or []
                if raw_prompts or _use_sam3_fallback:
                    try:
                        from .utils.sam3_road_analyzer import SAM3RoadAnalyzer
                        sam3_analyzer = SAM3RoadAnalyzer(
                            marking_prompts=raw_prompts or None,
                            road_fallback=_use_sam3_fallback,
                        )
                        sam3_analyzer.load()
                        _console(user_id,
                                 f"  SAM3 chargé — {len(raw_prompts)} prompt(s) marquages"
                                 + (" + fallback route" if _use_sam3_fallback else ""))
                    except Exception as _e:
                        _console(user_id, f"  AVERTISSEMENT SAM3: {_e}")
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
            track_kwargs = {
                'source': video_path,
                'device': device,
                'imgsz': ((max(width, height) + 31) // 32) * 32,
                'conf': profile.confidence,
                'iou': profile.iou_threshold,
                'classes': target_indices if target_indices else None,
                'verbose': False,
                'stream': True,
            }

            if profile.task_type == 'segment':
                track_kwargs['task'] = 'segment'
                track_kwargs['retina_masks'] = True

            try:
                preds = model.track(**track_kwargs)
            except Exception as e:
                _console(user_id, f"  ERREUR tracking: {e}")
                if vid_writer:
                    vid_writer.release()
                continue

            # Iterate over predictions
            frames_to_create = []
            cam_detections_count = 0
            cam_max_proximity = 0.0
            last_progress_frame = 0

            for frame_idx, pred in enumerate(preds):
                # Cancellation check every 100 frames
                if frame_idx % 100 == 0 and _is_cancelled(user_id):
                    raise InterruptedError("Annulé par l'utilisateur")

                # Extract detections
                detections = _extract_detections(pred, height)
                timestamp = frame_idx / fps

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

                # Report progress every 50 frames
                if frame_idx - last_progress_frame >= 50 and total_frames > 0:
                    cam_frac = frame_idx / total_frames
                    pct = cam_progress_start + cam_frac * (cam_progress_end - cam_progress_start)
                    set_session_progress(session_id, pct)
                    last_progress_frame = frame_idx

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
            num_segments = detect_temporal_segments(session)
            summary['segments_detected'] = num_segments
            _console(user_id, f"{num_segments} segments temporels détectés")
        except Exception as e:
            logger.warning(f"Segment detection failed: {e}")
            summary['segments_detected'] = 0

        # =====================================================================
        # Finalize
        # =====================================================================
        elapsed = time.time() - start_time
        summary['processing_time_seconds'] = round(elapsed, 1)
        summary['max_proximity'] = round(summary['max_proximity'], 3)

        session.results_summary = summary
        session.status = AnalysisSession.Status.COMPLETED
        session.completed_at = timezone.now()
        session.progress = 100.0
        session.save()

        set_session_progress(session_id, 100, "Terminé")

        _console(user_id, f"Analyse terminée en {elapsed:.0f}s — "
                          f"{summary['detections_total']} détections sur {summary['cameras_processed']} caméras")

        # Cleanup
        _unload_model(model)

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
            _console(session.user_id, f"ERREUR: {e}")
        except Exception:
            pass
        return {'error': str(e), 'session_id': session_id}


# =============================================================================
# RTMaps Extraction Task
# =============================================================================

@shared_task(bind=True)
def extract_rtmaps_task(self, session_id: str, rec_path: str, csv_path: str = None):
    """
    Extract camera views and GPS data from a RTMaps .rec file.

    Steps:
    1. Parse .rec -> GPS track + video frame timestamps
    2. Extract quadrature video frames from .rec binary data into a temporary AVI
    3. Crop quadrature AVI into front.mp4 and rear.mp4
    4. Create CameraView records for front + rear
    5. Save GPS track to session.gps_track
    6. Launch process_session_task
    """
    close_old_connections()

    from .models import AnalysisSession, CameraView
    from .utils.rtmaps_parser import RTMapsParser, merge_with_api_csv
    from .utils.quadrature_video import export_quadrature_view, LAYOUT_NAVYA

    EXTRACT_CACHE_KEY = f"cam_analyzer_extract_{session_id}"

    def _set_progress(pct, msg=None):
        cache.set(EXTRACT_CACHE_KEY, {'progress': pct, 'status': msg or ''}, timeout=3600)

    try:
        session = AnalysisSession.objects.get(pk=session_id)
        user_id = session.user_id
        _console(user_id, "Extraction RTMaps démarrée...")
        _set_progress(2, "Lecture du fichier .rec...")

        # ── 1. Parse GPS + metadata ──────────────────────────────────────
        parser = RTMapsParser()
        parsed = parser.parse(rec_path)

        _set_progress(15, "GPS extrait, fusion CSV...")

        # ── 2. Merge with API CSV ────────────────────────────────────────
        gps_track = merge_with_api_csv(parsed['gps'], csv_path)

        if not gps_track:
            _console(user_id, "AVERTISSEMENT: aucune donnée GPS extraite")
        else:
            _console(user_id, f"GPS: {len(gps_track)} points extraits")

        _set_progress(20, "Extraction de la vidéo quadrature...")

        # ── 3. Build quadrature video from RTMaps binary H264 frames ────
        # The .rec file contains raw H264 NAL units in the video stream.
        # Extract them into a single AVI file using frame-by-frame writing.
        output_dir = os.path.join(settings.MEDIA_ROOT, 'cam_analyzer', str(user_id), 'rtmaps')
        os.makedirs(output_dir, exist_ok=True)

        import re as _re
        session_slug = _re.sub(r'[^a-zA-Z0-9_-]', '_', session.name or str(session_id)[:8])
        quad_path = os.path.join(output_dir, f"{session_slug}_quad.avi")

        _extract_h264_frames_to_avi(rec_path, quad_path, user_id)

        if not os.path.exists(quad_path):
            raise RuntimeError(f"Quadrature video extraction failed: {quad_path}")

        _set_progress(60, "Crop des vues avant / arrière...")

        # ── 4. Crop front + rear views ───────────────────────────────────
        front_path = os.path.join(output_dir, f"{session_slug}_front.avi")
        rear_path = os.path.join(output_dir, f"{session_slug}_rear.avi")

        front_meta = export_quadrature_view(quad_path, front_path, 'front', LAYOUT_NAVYA)
        _set_progress(75, "Vue avant extraite, traitement arrière...")

        rear_meta = export_quadrature_view(quad_path, rear_path, 'rear', LAYOUT_NAVYA)
        _set_progress(85, "Vues extraites, création des caméras...")

        # ── 5. Create CameraView records ─────────────────────────────────
        # Remove existing cameras for this session (re-extraction)
        for existing in session.cameras.all():
            if existing.video_file:
                try:
                    existing.video_file.delete(save=False)
                except Exception:
                    pass
        session.cameras.all().delete()

        for pos, meta, fpath in [('front', front_meta, front_path), ('rear', rear_meta, rear_path)]:
            if 'error' in meta:
                _console(user_id, f"AVERTISSEMENT: vue {pos} non disponible: {meta['error']}")
                continue
            # Store path relative to MEDIA_ROOT
            rel_path = os.path.relpath(fpath, settings.MEDIA_ROOT).replace('\\', '/')
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

        # ── 6. Save GPS track + source type ─────────────────────────────
        session.gps_track = gps_track
        session.source_type = 'rtmaps'
        session.save(update_fields=['gps_track', 'source_type'])

        _set_progress(95, "Lancement de l'analyse YOLO...")
        _console(user_id, "Extraction RTMaps terminée — lancement de l'analyse")

        # ── 7. Launch YOLO analysis ──────────────────────────────────────
        process_session_task.delay(str(session_id))

        _set_progress(100, "Extraction terminée")
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
