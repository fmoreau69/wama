"""
Django views for Cam Analyzer.
"""
import csv
import io
import json
import logging
import os

import mimetypes
import re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from django.core.cache import cache

from .models import AnalysisSession, AnalysisProfile, CameraView, DetectionFrame, TemporalSegment
from .models import get_unique_filename
from wama.common.utils.console_utils import push_console_line, get_console_lines

logger = logging.getLogger(__name__)


def _console(user_id: int, message: str) -> None:
    """Send message to WAMA console."""
    try:
        push_console_line(user_id, f"[Cam Analyzer] {message}")
        logger.info(message)
    except Exception as e:
        logger.warning(f"Failed to push console line: {e}")


def _get_available_models():
    """List available YOLO models from AI-models directory."""
    models_dir = os.path.join(settings.BASE_DIR, 'AI-models', 'models', 'vision', 'yolo')
    available = []

    for task_dir in ['detect', 'segment']:
        task_path = os.path.join(models_dir, task_dir)
        if not os.path.isdir(task_path):
            continue
        for root, dirs, files in os.walk(task_path):
            for f in files:
                if f.endswith('.pt'):
                    rel_path = os.path.relpath(os.path.join(root, f), settings.BASE_DIR)
                    available.append({
                        'name': f,
                        'path': rel_path.replace('\\', '/'),
                        'task': task_dir,
                    })

    available.sort(key=lambda x: (x['task'], x['name']))
    return available


def _extract_video_metadata(file_path):
    """Extract video metadata (duration, fps, resolution) using cv2."""
    try:
        import cv2
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            return {}
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = frame_count / fps if fps > 0 else 0
        cap.release()
        return {
            'duration': round(duration, 2),
            'fps': round(fps, 2),
            'width': width,
            'height': height,
        }
    except Exception as e:
        logger.warning(f"Failed to extract video metadata: {e}")
        return {}


def _ensure_h264(file_path):
    """
    Ensure a video is browser-compatible (H.264/H.265).
    If the codec is not playable (MJPG, mp4v, etc.), re-encode to H.264.
    When the input is .avi (typical OpenCV/MJPG fallback), the output is
    promoted to .mp4 — the original .avi is removed.

    Returns:
        - False if no conversion was needed or if it failed
        - The final file path (str) if a conversion occurred (may differ
          from the input path when extension was promoted)
    """
    import subprocess

    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name',
             '-of', 'csv=p=0', file_path],
            capture_output=True, text=True, timeout=10,
        )
        codec = result.stdout.strip().lower()

        if codec in ('h264', 'hevc', 'vp8', 'vp9', 'av1'):
            return False  # Already browser-compatible

        # Promote .avi to .mp4 since we're re-encoding anyway — avoids the
        # codec/container mismatch where the file claims .avi but holds H.264.
        base, ext = os.path.splitext(file_path)
        target_path = base + '.mp4' if ext.lower() == '.avi' else file_path

        logger.info(f"Video codec '{codec}' not browser-compatible, re-encoding to H.264: {file_path} → {target_path}")

        tmp_path = target_path + '.h264.tmp.mp4'
        proc = subprocess.run(
            ['ffmpeg', '-i', file_path,
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
             '-pix_fmt', 'yuv420p', '-c:a', 'copy',
             '-movflags', '+faststart',
             tmp_path, '-y'],
            capture_output=True, text=True, timeout=1800,
        )

        if proc.returncode != 0:
            logger.error(f"ffmpeg re-encode failed: {proc.stderr[-500:]}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return False

        os.replace(tmp_path, target_path)

        # If the extension changed, drop the legacy file.
        if target_path != file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as rm_err:
                logger.warning(f"Could not remove original {file_path}: {rm_err}")

        logger.info(f"Re-encoded to H.264: {target_path}")
        return target_path

    except FileNotFoundError:
        logger.warning("ffprobe/ffmpeg not found, skipping codec check")
        return False
    except Exception as e:
        logger.warning(f"Codec check failed: {e}")
        return False


# COCO classes relevant for road analysis
COCO_ROAD_CLASSES = {
    0: 'person',
    1: 'bicycle',
    2: 'car',
    3: 'motorcycle',
    5: 'bus',
    7: 'truck',
    9: 'traffic light',
    11: 'stop sign',
    13: 'bench',
    15: 'cat',
    16: 'dog',
}


# =============================================================================
# Video streaming with Range request support (for seeking)
# =============================================================================

@login_required
@require_http_methods(["GET"])
def stream_video(request, camera_id):
    """Stream a camera video with HTTP Range support for seeking."""
    camera = get_object_or_404(CameraView, id=camera_id, session__user=request.user)
    if not camera.video_file:
        return HttpResponse(status=404)

    file_path = camera.video_file.path
    if not os.path.isfile(file_path):
        return HttpResponse(status=404)

    file_size = os.path.getsize(file_path)
    content_type = mimetypes.guess_type(file_path)[0] or 'video/mp4'

    range_header = request.META.get('HTTP_RANGE', '')
    range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)

    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1

        def file_iterator():
            with open(file_path, 'rb') as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk_size = min(8192, remaining)
                    data = f.read(chunk_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        response = StreamingHttpResponse(file_iterator(), status=206, content_type=content_type)
        response['Content-Length'] = length
        response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
    else:
        response = FileResponse(open(file_path, 'rb'), content_type=content_type)
        response['Content-Length'] = file_size

    response['Accept-Ranges'] = 'bytes'
    return response


# =============================================================================
# Main view
# =============================================================================

@login_required
def index(request):
    """Main Cam Analyzer page."""
    sessions = AnalysisSession.objects.filter(user=request.user)[:20]
    profiles = AnalysisProfile.objects.filter(user=request.user)
    available_models = _get_available_models()

    context = {
        'sessions': sessions,
        'profiles': profiles,
        'available_models': json.dumps(available_models),
        'coco_classes': json.dumps(COCO_ROAD_CLASSES),
    }

    return render(request, 'cam_analyzer/index.html', context)


# =============================================================================
# Sessions API
# =============================================================================

@login_required
@require_http_methods(["GET"])
def list_sessions(request):
    """List all sessions for current user."""
    sessions = AnalysisSession.objects.filter(user=request.user)

    data = []
    for s in sessions:
        cameras = []
        for c in s.cameras.all():
            cameras.append({
                'id': c.id,
                'position': c.position,
                'label': c.label,
                'video_url': f'/lab/cam-analyzer/api/cameras/{c.id}/stream/' if c.video_file else None,
                'duration': c.duration,
                'fps': c.fps,
                'width': c.width,
                'height': c.height,
                'time_offset': c.time_offset,
            })
        data.append({
            'id': str(s.id),
            'name': s.name,
            'status': s.status,
            'camera_count': len(cameras),
            'cameras': cameras,
            'profile_id': s.profile_id,
            'created_at': s.created_at.isoformat(),
            'progress': s.progress,
        })

    return JsonResponse({'sessions': data})


@login_required
@require_http_methods(["POST"])
def create_session(request):
    """Create a new analysis session."""
    user_id = request.user.id
    name = request.POST.get('name', '').strip()
    profile_id = request.POST.get('profile_id')

    try:
        profile = None
        if profile_id:
            profile = AnalysisProfile.objects.filter(pk=profile_id, user=request.user).first()

        session = AnalysisSession.objects.create(
            user=request.user,
            name=name or f"Session {AnalysisSession.objects.filter(user=request.user).count() + 1}",
            profile=profile,
            status=AnalysisSession.Status.DRAFT,
        )
        _console(user_id, f"Session créée : {session.name}")

        return JsonResponse({
            'success': True,
            'session_id': str(session.id),
            'name': session.name,
        })

    except Exception as e:
        logger.error(f"Error creating session: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def get_session(request, session_id):
    """Get full session details."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    cameras = []
    for c in session.cameras.all():
        cameras.append({
            'id': c.id,
            'position': c.position,
            'label': c.label,
            'video_url': f'/lab/cam-analyzer/api/cameras/{c.id}/stream/' if c.video_file else None,
            'filename': os.path.basename(c.video_file.name) if c.video_file else '',
            'duration': c.duration,
            'fps': c.fps,
            'width': c.width,
            'height': c.height,
            'time_offset': c.time_offset,
        })

    # Downsample gps_track for the mini-map. With 24k points across 2h20 of
    # driving, 1500 samples = 1 point per ~5.5s ≈ 46m at 30 km/h, which
    # under-samples sharp turns. 3000 points (~22m gap) tracks corners
    # cleanly while keeping the JSON payload around 250 KB.
    gps_full = session.gps_track or []
    if len(gps_full) > 3000:
        step = max(1, len(gps_full) // 3000)
        gps_sampled = [
            {'ts': p.get('ts'), 'lat': p.get('lat'), 'lon': p.get('lon')}
            for p in gps_full[::step]
        ]
    else:
        gps_sampled = [
            {'ts': p.get('ts'), 'lat': p.get('lat'), 'lon': p.get('lon')}
            for p in gps_full
        ]

    return JsonResponse({
        'id': str(session.id),
        'name': session.name,
        'status': session.status,
        'profile_id': session.profile_id,
        'config': session.config,
        'cameras': cameras,
        'progress': session.progress,
        'results_summary': session.results_summary,
        'intersection_windows': session.intersection_windows,
        'gps_track': gps_sampled,
        'created_at': session.created_at.isoformat(),
        'error_message': session.error_message,
    })


@login_required
@require_http_methods(["POST"])
def update_session(request, session_id):
    """Update session name or profile."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    name = request.POST.get('name')
    profile_id = request.POST.get('profile_id')

    if name is not None:
        session.name = name.strip()
    if profile_id is not None:
        if profile_id:
            session.profile = AnalysisProfile.objects.filter(pk=profile_id, user=request.user).first()
        else:
            session.profile = None

    session.save()
    return JsonResponse({'success': True})


@login_required
@require_http_methods(["POST", "DELETE"])
def delete_session(request, session_id):
    """Delete an analysis session and its files."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    # Delete camera video files
    for camera in session.cameras.all():
        if camera.video_file:
            try:
                camera.video_file.delete()
            except Exception as e:
                logger.warning(f"Failed to delete camera file: {e}")

    session.delete()
    _console(user_id, f"Session supprimée : {session.name}")

    return JsonResponse({'success': True})


# =============================================================================
# Camera management
# =============================================================================

@login_required
@require_http_methods(["POST"])
def upload_camera(request, session_id):
    """Upload a video file and assign it to a camera position."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    position = request.POST.get('position')
    video_file = request.FILES.get('video_file')

    if not position or position not in dict(CameraView.Position.choices):
        return JsonResponse({'success': False, 'error': 'Position invalide'}, status=400)

    if not video_file:
        return JsonResponse({'success': False, 'error': 'Aucun fichier vidéo'}, status=400)

    try:
        # Delete existing camera at this position if any
        existing = session.cameras.filter(position=position).first()
        if existing:
            if existing.video_file:
                existing.video_file.delete()
            existing.delete()

        # Create new camera view
        camera = CameraView.objects.create(
            session=session,
            position=position,
            video_file=video_file,
            label=os.path.splitext(video_file.name)[0],
        )

        # Re-encode to H.264 if needed (MPEG-4 Part 2 etc. not playable in browser)
        converted = _ensure_h264(camera.video_file.path)
        if converted:
            _console(user_id, f"  Vidéo ré-encodée en H.264 pour compatibilité navigateur")
            # If the extension was promoted (e.g. .avi → .mp4), update the DB pointer
            if isinstance(converted, str) and converted != camera.video_file.path:
                new_rel = os.path.relpath(converted, settings.MEDIA_ROOT).replace('\\', '/')
                camera.video_file.name = new_rel
                camera.save(update_fields=['video_file'])

        # Extract metadata
        meta = _extract_video_metadata(camera.video_file.path)
        if meta:
            camera.duration = meta.get('duration')
            camera.fps = meta.get('fps')
            camera.width = meta.get('width')
            camera.height = meta.get('height')
            camera.save()

        _console(user_id, f"Caméra {camera.get_position_display()} : {video_file.name}")

        return JsonResponse({
            'success': True,
            'camera': {
                'id': camera.id,
                'position': camera.position,
                'label': camera.label,
                'video_url': f'/lab/cam-analyzer/api/cameras/{camera.id}/stream/',
                'filename': video_file.name,
                'duration': camera.duration,
                'fps': camera.fps,
                'width': camera.width,
                'height': camera.height,
                'time_offset': camera.time_offset,
            }
        })

    except Exception as e:
        logger.error(f"Error uploading camera: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST", "DELETE"])
def delete_camera(request, camera_id):
    """Delete a camera from a session."""
    camera = get_object_or_404(CameraView, pk=camera_id, session__user=request.user)

    if camera.video_file:
        try:
            camera.video_file.delete()
        except Exception:
            pass

    camera.delete()
    return JsonResponse({'success': True})


@login_required
@require_http_methods(["POST"])
def update_camera_position(request, camera_id):
    """Update a camera's position (drag & drop reassignment)."""
    camera = get_object_or_404(CameraView, pk=camera_id, session__user=request.user)

    data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
    new_position = data.get('position')

    if not new_position or new_position not in dict(CameraView.Position.choices):
        return JsonResponse({'success': False, 'error': 'Position invalide'}, status=400)

    # Swap if target position is occupied
    existing = CameraView.objects.filter(session=camera.session, position=new_position).first()
    if existing and existing.pk != camera.pk:
        old_position = camera.position
        existing.position = old_position
        existing.save()

    camera.position = new_position
    camera.save()

    return JsonResponse({'success': True})


# =============================================================================
# Analysis
# =============================================================================

@login_required
@require_http_methods(["POST"])
def start_analysis(request, session_id):
    """Start YOLO detection analysis for a session."""
    from .tasks import process_session_task

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    if session.cameras.count() == 0:
        return JsonResponse({'success': False, 'error': 'Aucune caméra assignée'}, status=400)

    if not session.profile:
        return JsonResponse({'success': False, 'error': 'Aucun profil d\'analyse sélectionné'}, status=400)

    if session.status in (AnalysisSession.Status.PROCESSING, AnalysisSession.Status.PENDING):
        return JsonResponse({'success': False, 'error': 'Analyse déjà en cours ou en attente'}, status=400)

    # Clear previous detection results if re-running
    DetectionFrame.objects.filter(camera__session=session).delete()

    session.status = AnalysisSession.Status.PENDING
    session.progress = 0.0
    session.error_message = ''
    session.results_summary = {}
    session.save()

    task = process_session_task.delay(str(session_id))
    cache.set(f"cam_analyzer_task_{session_id}", task.id, timeout=86400)
    _console(user_id, f"Analyse lancée pour la session : {session.name}")

    return JsonResponse({
        'success': True,
        'task_id': task.id,
    })


@login_required
@require_http_methods(["POST"])
def cancel_analysis(request, session_id):
    """Cancel a running analysis."""
    from .tasks import stop_cam_analyzer

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    if session.status not in (AnalysisSession.Status.PROCESSING, AnalysisSession.Status.PENDING):
        return JsonResponse({'success': False, 'error': 'Aucune analyse en cours'})

    _console(user_id, f"Annulation demandée pour la session : {session.name}")

    # Set cache flag (cooperative cancellation, checked every 100 frames)
    stop_cam_analyzer(user_id)

    # Force-revoke the running task — sends SIGTERM if YOLO is stuck
    task_id = cache.get(f"cam_analyzer_task_{session_id}")
    if task_id:
        try:
            from celery import current_app
            current_app.control.revoke(task_id, terminate=True, signal='SIGTERM')
            _console(user_id, f"Révocation forcée du task {task_id[:8]}...")
        except Exception as e:
            logger.warning(f"Failed to revoke task {task_id}: {e}")
        cache.delete(f"cam_analyzer_task_{session_id}")

    # For PENDING sessions, immediately mark as failed
    if session.status == AnalysisSession.Status.PENDING:
        session.status = AnalysisSession.Status.FAILED
        session.error_message = "Annulé par l'utilisateur"
        session.progress = 0
        session.save()
        return JsonResponse({'success': True, 'message': 'Analyse annulée', 'immediate': True})

    # For PROCESSING sessions: mark as failed since revoke was sent
    session.status = AnalysisSession.Status.FAILED
    session.error_message = "Annulé par l'utilisateur"
    session.save(update_fields=['status', 'error_message'])

    return JsonResponse({'success': True, 'message': 'Annulation envoyée'})


@login_required
@require_http_methods(["GET"])
def get_session_status(request, session_id):
    """Get session status and progress."""
    from django.core.cache import cache

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    # Detect lost tasks: PENDING for > 300s without extraction activity = task dropped
    if session.status == AnalysisSession.Status.PENDING and session.updated_at:
        elapsed = (timezone.now() - session.updated_at).total_seconds()
        # Also check RTMaps extraction cache — if active, the task is running
        extract_active = bool(cache.get(f"cam_analyzer_extract_{session_id}"))
        if elapsed > 300 and not extract_active:
            session.status = AnalysisSession.Status.FAILED
            session.error_message = (
                "La tâche n'a pas été prise en charge par le worker. "
                "Vérifiez que le worker GPU Celery est démarré et relancez l'analyse."
            )
            session.save()

    # Get real-time progress from cache if processing/pending
    progress = session.progress
    status_message = None
    if session.status in (AnalysisSession.Status.PROCESSING, AnalysisSession.Status.PENDING):
        cached_progress = cache.get(f"cam_analyzer_progress_{session_id}")
        if cached_progress is not None:
            progress = cached_progress
        status_message = cache.get(f"cam_analyzer_status_{session_id}")

    return JsonResponse({
        'id': str(session.id),
        'status': session.status,
        'progress': progress,
        'status_message': status_message,
        'error_message': session.error_message,
        'results_summary': session.results_summary,
        'intersection_windows': session.intersection_windows,
    })


@login_required
@require_http_methods(["GET"])
def get_detections(request, session_id, camera_id):
    """Get detection frames for a camera (for canvas overlay)."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    camera = get_object_or_404(CameraView, pk=camera_id, session=session)

    start_frame = int(request.GET.get('start', 0))
    end_frame = int(request.GET.get('end', 100000))

    frames = DetectionFrame.objects.filter(
        camera=camera,
        frame_number__gte=start_frame,
        frame_number__lt=end_frame,
    ).order_by('frame_number').values('frame_number', 'timestamp', 'detections')

    return JsonResponse({
        'camera_id': camera_id,
        'position': camera.position,
        'fps': camera.fps,
        'width': camera.width,
        'height': camera.height,
        'frames': list(frames),
    })


# =============================================================================
# Profiles
# =============================================================================

@login_required
@require_http_methods(["GET"])
def list_profiles(request):
    """List analysis profiles."""
    profiles = AnalysisProfile.objects.filter(user=request.user)

    data = [{
        'id': p.id,
        'name': p.name,
        'report_type': p.report_type,
        'intersections': p.intersections,
        'road_model_path': p.road_model_path,
        'sam3_markings_enabled': p.sam3_markings_enabled,
        'sam3_markings_prompts': p.sam3_markings_prompts,
        'sam3_as_road_fallback': p.sam3_as_road_fallback,
        'restrict_to_intersection_windows': p.restrict_to_intersection_windows,
        'analyzed_positions': p.analyzed_positions or ['front', 'rear'],
        'model_path': p.model_path,
        'task_type': p.task_type,
        'target_classes': p.target_classes,
        'confidence': p.confidence,
        'iou_threshold': p.iou_threshold,
        'tracker': p.tracker,
    } for p in profiles]

    return JsonResponse({'profiles': data})


@login_required
@require_http_methods(["POST"])
def save_profile(request):
    """Create or update an analysis profile."""
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST

        profile_id = data.get('id')
        name = data.get('name', '').strip()
        report_type = data.get('report_type', 'proximity_overtaking')
        intersections = data.get('intersections', [])
        road_model_path = data.get('road_model_path', '').strip()
        sam3_markings_enabled = bool(data.get('sam3_markings_enabled', False))
        sam3_markings_prompts = data.get('sam3_markings_prompts', [])
        sam3_as_road_fallback = bool(data.get('sam3_as_road_fallback', False))
        # Master switch: if SAM3 markings is off, force the fallback off too —
        # otherwise its checkbox stays hidden but its value persists, silently
        # triggering SAM3 loading on the next analysis.
        if not sam3_markings_enabled:
            sam3_as_road_fallback = False
        restrict_to_intersection_windows = bool(data.get('restrict_to_intersection_windows', True))
        # Validate analyzed_positions against allowed positions; fall back to
        # front+rear if the payload is missing or empty.
        valid_positions = ['front', 'rear', 'left', 'right']
        analyzed_positions = data.get('analyzed_positions') or []
        if isinstance(analyzed_positions, str):
            analyzed_positions = json.loads(analyzed_positions)
        analyzed_positions = [p for p in analyzed_positions if p in valid_positions]
        if not analyzed_positions:
            analyzed_positions = ['front', 'rear']
        model_path = data.get('model_path', '')
        task_type = data.get('task_type', 'detect')
        target_classes = data.get('target_classes', [])
        confidence = float(data.get('confidence', 0.25))
        iou_threshold = float(data.get('iou_threshold', 0.45))
        tracker = data.get('tracker', 'botsort')

        if not name:
            return JsonResponse({'success': False, 'error': 'Nom requis'}, status=400)
        if not model_path:
            return JsonResponse({'success': False, 'error': 'Modèle requis'}, status=400)

        valid_report_types = [r[0] for r in AnalysisProfile.REPORT_TYPE_CHOICES]
        if report_type not in valid_report_types:
            report_type = 'proximity_overtaking'

        if isinstance(target_classes, str):
            target_classes = json.loads(target_classes)
        if isinstance(intersections, str):
            intersections = json.loads(intersections)
        if isinstance(sam3_markings_prompts, str):
            sam3_markings_prompts = json.loads(sam3_markings_prompts)

        if profile_id:
            profile = get_object_or_404(AnalysisProfile, pk=profile_id, user=request.user)
            profile.name = name
            profile.report_type = report_type
            profile.intersections = intersections
            profile.road_model_path = road_model_path
            profile.sam3_markings_enabled = sam3_markings_enabled
            profile.sam3_markings_prompts = sam3_markings_prompts
            profile.sam3_as_road_fallback = sam3_as_road_fallback
            profile.restrict_to_intersection_windows = restrict_to_intersection_windows
            profile.analyzed_positions = analyzed_positions
            profile.model_path = model_path
            profile.task_type = task_type
            profile.target_classes = target_classes
            profile.confidence = confidence
            profile.iou_threshold = iou_threshold
            profile.tracker = tracker
            profile.save()
        else:
            profile = AnalysisProfile.objects.create(
                user=request.user,
                name=name,
                report_type=report_type,
                intersections=intersections,
                road_model_path=road_model_path,
                sam3_markings_enabled=sam3_markings_enabled,
                sam3_markings_prompts=sam3_markings_prompts,
                sam3_as_road_fallback=sam3_as_road_fallback,
                restrict_to_intersection_windows=restrict_to_intersection_windows,
                analyzed_positions=analyzed_positions,
                model_path=model_path,
                task_type=task_type,
                target_classes=target_classes,
                confidence=confidence,
                iou_threshold=iou_threshold,
                tracker=tracker,
            )

        return JsonResponse({
            'success': True,
            'profile': {
                'id': profile.id,
                'name': profile.name,
                'report_type': profile.report_type,
                'intersections': profile.intersections,
                'road_model_path': profile.road_model_path,
                'sam3_markings_enabled': profile.sam3_markings_enabled,
                'sam3_markings_prompts': profile.sam3_markings_prompts,
                'sam3_as_road_fallback': profile.sam3_as_road_fallback,
                'restrict_to_intersection_windows': profile.restrict_to_intersection_windows,
                'analyzed_positions': profile.analyzed_positions or ['front', 'rear'],
                'model_path': profile.model_path,
                'task_type': profile.task_type,
                'target_classes': profile.target_classes,
                'confidence': profile.confidence,
                'iou_threshold': profile.iou_threshold,
                'tracker': profile.tracker,
            }
        })

    except Exception as e:
        logger.error(f"Error saving profile: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST", "DELETE"])
def delete_profile(request, profile_id):
    """Delete an analysis profile."""
    profile = get_object_or_404(AnalysisProfile, pk=profile_id, user=request.user)
    profile.delete()
    return JsonResponse({'success': True})


# =============================================================================
# Console
# =============================================================================

@login_required
@require_http_methods(["POST"])
def upload_rtmaps(request, session_id):
    """
    Upload a RTMaps .rec file (+ optional API CSV) and launch extraction.
    The extraction task will parse the .rec, crop the quadrature video into
    front/rear views, extract GPS data, and finally trigger the YOLO analysis.
    """
    from .tasks import extract_rtmaps_task

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    rec_file = request.FILES.get('rec_file')
    csv_file = request.FILES.get('csv_file')

    if not rec_file:
        return JsonResponse({'success': False, 'error': 'Fichier .rec manquant'}, status=400)

    if not session.profile:
        return JsonResponse({'success': False, 'error': "Aucun profil d'analyse sélectionné"}, status=400)

    # Block if YOLO analysis is already running
    if session.status in (AnalysisSession.Status.PROCESSING, AnalysisSession.Status.PENDING):
        return JsonResponse(
            {'success': False, 'error': "Une analyse est déjà en cours sur cette session. Annulez-la avant de lancer l'extraction RTMaps."},
            status=400,
        )

    # Save uploaded files (under input/rtmaps/ to keep all source data under input/)
    rtmaps_dir = os.path.join(settings.MEDIA_ROOT, 'cam_analyzer', str(user_id), 'input', 'rtmaps')
    os.makedirs(rtmaps_dir, exist_ok=True)

    rec_filename = get_unique_filename(rtmaps_dir, rec_file.name)
    rec_path = os.path.join(rtmaps_dir, rec_filename)
    with open(rec_path, 'wb') as f:
        for chunk in rec_file.chunks():
            f.write(chunk)

    csv_path = None
    if csv_file:
        csv_filename = get_unique_filename(rtmaps_dir, csv_file.name)
        csv_path = os.path.join(rtmaps_dir, csv_filename)
        with open(csv_path, 'wb') as f:
            for chunk in csv_file.chunks():
                f.write(chunk)

    # Reset session state
    session.status = AnalysisSession.Status.PENDING
    session.progress = 0.0
    session.error_message = ''
    session.results_summary = {}
    session.save(update_fields=['status', 'progress', 'error_message', 'results_summary'])

    task = extract_rtmaps_task.delay(str(session_id), rec_path, csv_path)
    _console(user_id, f"Extraction RTMaps lancée : {rec_file.name}")

    return JsonResponse({'success': True, 'task_id': task.id})


@login_required
@require_http_methods(["POST"])
def upload_quadrature_avi(request, session_id):
    """
    Import a pre-exported RTMaps quadrature AVI (800×500) + optional GPS CSV.
    Launches extract_rtmaps_task in AVI mode (skips binary .rec extraction).
    """
    from .tasks import extract_rtmaps_task

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    avi_file = request.FILES.get('avi_file')
    gps_csv_file = request.FILES.get('gps_csv_file')

    if not avi_file:
        return JsonResponse({'success': False, 'error': 'Fichier AVI manquant'}, status=400)

    if not session.profile:
        return JsonResponse({'success': False, 'error': "Aucun profil d'analyse sélectionné"}, status=400)

    if session.status in (AnalysisSession.Status.PROCESSING, AnalysisSession.Status.PENDING):
        return JsonResponse(
            {'success': False, 'error': "Une analyse est déjà en cours. Annulez-la d'abord."},
            status=400,
        )

    rtmaps_dir = os.path.join(settings.MEDIA_ROOT, 'cam_analyzer', str(user_id), 'input', 'rtmaps')
    os.makedirs(rtmaps_dir, exist_ok=True)

    avi_filename = get_unique_filename(rtmaps_dir, avi_file.name)
    avi_path = os.path.join(rtmaps_dir, avi_filename)
    with open(avi_path, 'wb') as f:
        for chunk in avi_file.chunks():
            f.write(chunk)

    gps_csv_path = None
    if gps_csv_file:
        csv_filename = get_unique_filename(rtmaps_dir, gps_csv_file.name)
        gps_csv_path = os.path.join(rtmaps_dir, csv_filename)
        with open(gps_csv_path, 'wb') as f:
            for chunk in gps_csv_file.chunks():
                f.write(chunk)

    session.status = AnalysisSession.Status.PENDING
    session.progress = 0.0
    session.error_message = ''
    session.results_summary = {}
    session.save(update_fields=['status', 'progress', 'error_message', 'results_summary'])

    task = extract_rtmaps_task.delay(
        str(session_id),
        rec_path=None,
        csv_path=gps_csv_path,
        quad_avi_path=avi_path,
    )
    _console(user_id, f"Import quadrature AVI lancé : {avi_file.name}")

    return JsonResponse({'success': True, 'task_id': task.id})


@login_required
@require_http_methods(["GET"])
def rtmaps_status(request, session_id):
    """Return extraction progress for a RTMaps session."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    cached = cache.get(f"cam_analyzer_extract_{session_id}") or {}
    return JsonResponse({
        'session_status': session.status,
        'progress': cached.get('progress', 0),
        'status_message': cached.get('status', ''),
    })


@login_required
@require_http_methods(["GET"])
def console_content(request):
    """Get console output for the current user."""
    console_lines = get_console_lines(request.user.id, limit=100)
    return JsonResponse({'output': console_lines})


# =============================================================================
# Export & Analytics (Phase 3)
# =============================================================================

@login_required
@require_http_methods(["GET"])
def export_detections_csv(request, session_id):
    """Export all detections as CSV."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['camera', 'frame', 'timestamp', 'class_name', 'class_id',
                     'confidence', 'track_id', 'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2', 'proximity'])

    for camera in session.cameras.all():
        for df in DetectionFrame.objects.filter(camera=camera).order_by('frame_number'):
            for det in df.detections:
                bbox = det.get('bbox', [0, 0, 0, 0])
                writer.writerow([
                    camera.position, df.frame_number, df.timestamp,
                    det.get('class_name', ''), det.get('class_id', ''),
                    det.get('confidence', ''), det.get('track_id', ''),
                    *bbox, det.get('proximity', '')
                ])

    return FileResponse(
        io.BytesIO(buffer.getvalue().encode('utf-8')),
        as_attachment=True,
        filename=f"{session.name or 'session'}_detections.csv",
        content_type='text/csv; charset=utf-8',
    )


@login_required
@require_http_methods(["GET"])
def export_session_json(request, session_id):
    """Export full session data as JSON."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    cameras_data = []
    for c in session.cameras.all():
        cameras_data.append({
            'position': c.position,
            'label': c.label,
            'duration': c.duration,
            'fps': c.fps,
            'width': c.width,
            'height': c.height,
        })

    profile_data = None
    if session.profile:
        p = session.profile
        profile_data = {
            'name': p.name,
            'model_path': p.model_path,
            'task_type': p.task_type,
            'target_classes': p.target_classes,
            'confidence': p.confidence,
            'iou_threshold': p.iou_threshold,
            'tracker': p.tracker,
        }

    segments_data = []
    for seg in TemporalSegment.objects.filter(session=session):
        segments_data.append({
            'type': seg.segment_type,
            'type_display': seg.get_segment_type_display(),
            'camera': seg.camera.position if seg.camera else None,
            'start_time': seg.start_time,
            'end_time': seg.end_time,
            'duration': round(seg.end_time - seg.start_time, 2),
            'metadata': seg.metadata,
        })

    data = {
        'session': {
            'id': str(session.id),
            'name': session.name,
            'status': session.status,
            'created_at': session.created_at.isoformat(),
            'completed_at': session.completed_at.isoformat() if session.completed_at else None,
        },
        'profile': profile_data,
        'cameras': cameras_data,
        'results_summary': session.results_summary,
        'segments': segments_data,
    }

    content = json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')
    return FileResponse(
        io.BytesIO(content),
        as_attachment=True,
        filename=f"{session.name or 'session'}_report.json",
        content_type='application/json; charset=utf-8',
    )


@login_required
@require_http_methods(["GET"])
def export_segments_csv(request, session_id):
    """Export temporal segments as CSV."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['type', 'type_display', 'camera', 'start_time', 'end_time', 'duration', 'metadata'])

    for seg in TemporalSegment.objects.filter(session=session):
        writer.writerow([
            seg.segment_type,
            seg.get_segment_type_display(),
            seg.camera.position if seg.camera else '',
            seg.start_time,
            seg.end_time,
            round(seg.end_time - seg.start_time, 2),
            json.dumps(seg.metadata, ensure_ascii=False),
        ])

    return FileResponse(
        io.BytesIO(buffer.getvalue().encode('utf-8')),
        as_attachment=True,
        filename=f"{session.name or 'session'}_segments.csv",
        content_type='text/csv; charset=utf-8',
    )


@login_required
@require_http_methods(["GET"])
def get_segments(request, session_id):
    """Get temporal segments for a session."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    segments = []
    for seg in TemporalSegment.objects.filter(session=session).select_related('camera'):
        segments.append({
            'id': seg.id,
            'type': seg.segment_type,
            'type_display': seg.get_segment_type_display(),
            'camera_position': seg.camera.position if seg.camera else None,
            'start_time': seg.start_time,
            'end_time': seg.end_time,
            'duration': round(seg.end_time - seg.start_time, 2),
            'metadata': seg.metadata,
        })

    return JsonResponse({'segments': segments})


@login_required
@require_http_methods(["GET"])
def get_analytics_data(request, session_id):
    """Get pre-computed analytics data for Chart.js visualization."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    # Build proximity timeline: 1-second bins per camera
    proximity_timeline = {'timestamps': [], 'series': {}}
    cameras = list(session.cameras.all())

    if cameras:
        # Find max duration across cameras
        max_duration = 0
        for cam in cameras:
            if cam.duration and cam.duration > max_duration:
                max_duration = cam.duration

        if max_duration > 0:
            bin_size = 1.0
            num_bins = int(max_duration / bin_size) + 1
            proximity_timeline['timestamps'] = [round(i * bin_size, 1) for i in range(num_bins)]

            for cam in cameras:
                series = [0.0] * num_bins
                frames = DetectionFrame.objects.filter(camera=cam).order_by('frame_number')

                for frame in frames:
                    bin_idx = int(frame.timestamp / bin_size)
                    if 0 <= bin_idx < num_bins:
                        max_prox = max(
                            (d.get('proximity', 0) for d in frame.detections),
                            default=0
                        )
                        if max_prox > series[bin_idx]:
                            series[bin_idx] = round(max_prox, 3)

                proximity_timeline['series'][cam.position] = series

    # Class distribution from results_summary
    class_distribution = session.results_summary.get('by_class', {})

    # Segments count
    segments_count = TemporalSegment.objects.filter(session=session).count()

    return JsonResponse({
        'proximity_timeline': proximity_timeline,
        'class_distribution': class_distribution,
        'segments_count': segments_count,
    })
