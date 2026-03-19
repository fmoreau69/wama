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
    Stub — Détection d'insertions aux intersections.
    Sera implémentée en Phase 2 de ce rapport :
    - Véhicules à l'arrêt aux intersections (droite/gauche) quand la navette approche
    - Détection si le véhicule s'insère devant la navette (même voie ou voie opposée)
      ou attend que la navette soit passée
    """
    return []


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

                # Track max proximity
                for det in detections:
                    if det['proximity'] > cam_max_proximity:
                        cam_max_proximity = det['proximity']
                    # Count by class
                    cls_name = det['class_name']
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
