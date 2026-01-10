"""
Django views for Face Analyzer.
"""
import json
import logging
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.conf import settings
import os

from .models import AnalysisSession, AnalysisFrame
from .pipeline import FaceAnalysisPipeline, PipelineConfig, AnalysisMode
from .rppg import RPPGMethod

logger = logging.getLogger(__name__)

# Configure logging format if not already configured
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


@login_required
def index(request):
    """Main Face Analyzer page."""
    logger.info(f"Face Analyzer index accessed by user: {request.user.username}")
    sessions = AnalysisSession.objects.filter(user=request.user)[:10]

    context = {
        'sessions': sessions,
        'analysis_modes': AnalysisSession.AnalysisMode.choices,
    }

    return render(request, 'face_analyzer/index.html', context)


@login_required
@require_http_methods(["GET"])
def realtime_view(request):
    """Real-time webcam analysis view."""
    logger.info(f"Realtime view accessed by user: {request.user.username}")
    # Get chart configurations
    pipeline = FaceAnalysisPipeline()
    chart_configs = pipeline.get_chart_configs()
    logger.debug(f"Chart configs loaded: {len(chart_configs)} charts")

    context = {
        'chart_configs': json.dumps(chart_configs),
        'mode': 'realtime'
    }

    return render(request, 'face_analyzer/realtime.html', context)


@login_required
@require_http_methods(["GET"])
def video_view(request, session_id=None):
    """Video analysis view."""
    session = None
    if session_id:
        session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    # Get chart configurations
    pipeline = FaceAnalysisPipeline()
    chart_configs = pipeline.get_chart_configs()

    context = {
        'session': session,
        'chart_configs': json.dumps(chart_configs),
        'mode': 'video'
    }

    return render(request, 'face_analyzer/video.html', context)


@login_required
@require_http_methods(["POST"])
def create_session(request):
    """Create a new analysis session."""
    logger.info(f"Creating new session for user: {request.user.username}")
    try:
        mode = request.POST.get('mode', 'video')
        config = {
            'enable_rppg': request.POST.get('enable_rppg', 'true') == 'true',
            'enable_eye_tracking': request.POST.get('enable_eye_tracking', 'true') == 'true',
            'enable_emotions': request.POST.get('enable_emotions', 'true') == 'true',
            'enable_respiration': request.POST.get('enable_respiration', 'true') == 'true',
            'rppg_method': request.POST.get('rppg_method', 'chrom'),
        }
        logger.debug(f"Session config: mode={mode}, config={config}")

        session = AnalysisSession.objects.create(
            user=request.user,
            mode=mode,
            config=config,
            status=AnalysisSession.Status.PENDING
        )
        logger.info(f"Session created: {session.id}")

        # Handle file upload for video mode
        if mode == 'video' and 'video_file' in request.FILES:
            video_file = request.FILES['video_file']
            session.input_file = video_file
            session.save()
            logger.info(f"Video file uploaded: {video_file.name} ({video_file.size} bytes)")

        return JsonResponse({
            'success': True,
            'session_id': str(session.id)
        })

    except Exception as e:
        logger.error(f"Error creating session: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def start_analysis(request, session_id):
    """Start analysis for a session."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    if session.status == AnalysisSession.Status.PROCESSING:
        return JsonResponse({
            'success': False,
            'error': 'Analysis already in progress'
        })

    try:
        session.status = AnalysisSession.Status.PROCESSING
        session.started_at = timezone.now()
        session.save()

        # TODO: Start Celery task for video processing
        # For now, return success and process synchronously for small files
        if session.mode == 'video' and session.input_file:
            # This should be a Celery task for production
            _process_video_sync(session)

        return JsonResponse({
            'success': True,
            'message': 'Analysis started'
        })

    except Exception as e:
        session.status = AnalysisSession.Status.FAILED
        session.error_message = str(e)
        session.save()

        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def _process_video_sync(session: AnalysisSession):
    """Process video synchronously (for development/small files)."""
    import cv2

    logger.info(f"Starting video processing for session: {session.id}")

    try:
        config = PipelineConfig(
            enable_rppg=session.config.get('enable_rppg', True),
            enable_eye_tracking=session.config.get('enable_eye_tracking', True),
            enable_emotions=session.config.get('enable_emotions', True),
            enable_respiration=session.config.get('enable_respiration', True),
            rppg_method=RPPGMethod(session.config.get('rppg_method', 'chrom')),
            mode=AnalysisMode.POSTPROCESS,
            enable_overlay=True
        )
        logger.debug(f"Pipeline config: rPPG={config.enable_rppg}, Eyes={config.enable_eye_tracking}, "
                     f"Emotions={config.enable_emotions}, Respiration={config.enable_respiration}")

        pipeline = FaceAnalysisPipeline(config)
        logger.info("Pipeline initialized")

        input_path = session.input_file.path
        logger.info(f"Input video: {input_path}")

        # Generate output path
        output_filename = f"{session.id}_output.mp4"
        output_dir = os.path.join(settings.MEDIA_ROOT, 'face_analyzer', 'results')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)
        logger.info(f"Output video: {output_path}")

        def progress_callback(progress):
            session.progress = progress * 100
            session.save(update_fields=['progress'])
            if int(progress * 100) % 10 == 0:
                logger.info(f"Processing progress: {progress * 100:.0f}%")

        logger.info("Starting video analysis...")
        results = pipeline.process_video(input_path, output_path, progress_callback)
        logger.info(f"Video analysis complete: {len(results)} frames processed")

        # Save results
        logger.info("Saving frame results to database...")
        for i, result in enumerate(results):
            AnalysisFrame.objects.create(
                session=session,
                frame_number=i,
                timestamp=result.timestamp,
                face_detected=result.face_detected,
                head_pose=result.head_pose,
                rppg_data=result.rppg.to_dict() if result.rppg else None,
                eye_tracking_data=result.eye_tracking.to_dict() if result.eye_tracking else None,
                emotion_data=result.emotions.to_dict() if result.emotions else None,
                respiration_data=result.respiration.to_dict() if result.respiration else None,
                processing_time_ms=result.processing_time_ms
            )

        # Calculate summary statistics
        logger.info("Calculating summary statistics...")
        session.results_summary = _calculate_summary(results)
        session.output_file.name = f'face_analyzer/results/{output_filename}'
        session.status = AnalysisSession.Status.COMPLETED
        session.completed_at = timezone.now()
        session.progress = 100
        session.save()

        pipeline.close()
        logger.info(f"Session {session.id} completed successfully")

    except Exception as e:
        logger.error(f"Error processing video for session {session.id}: {e}", exc_info=True)
        session.status = AnalysisSession.Status.FAILED
        session.error_message = str(e)
        session.save()
        raise


def _calculate_summary(results):
    """Calculate summary statistics from analysis results."""
    import numpy as np

    summary = {
        'total_frames': len(results),
        'frames_with_face': sum(1 for r in results if r.face_detected),
    }

    # Heart rate statistics
    hr_values = [r.rppg.heart_rate for r in results if r.rppg]
    if hr_values:
        summary['heart_rate'] = {
            'mean': float(np.mean(hr_values)),
            'min': float(np.min(hr_values)),
            'max': float(np.max(hr_values)),
            'std': float(np.std(hr_values))
        }

    # Respiratory rate
    rr_values = [r.respiration.respiratory_rate for r in results if r.respiration]
    if rr_values:
        summary['respiratory_rate'] = {
            'mean': float(np.mean(rr_values)),
            'min': float(np.min(rr_values)),
            'max': float(np.max(rr_values))
        }

    # Dominant emotions distribution
    emotion_counts = {}
    for r in results:
        if r.emotions:
            emotion = r.emotions.dominant_emotion
            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
    if emotion_counts:
        total = sum(emotion_counts.values())
        summary['emotion_distribution'] = {
            k: round(v / total * 100, 1) for k, v in emotion_counts.items()
        }

    # Blink statistics
    blink_rates = [r.eye_tracking.blink.blink_rate for r in results if r.eye_tracking]
    if blink_rates:
        summary['blink_rate'] = {
            'mean': float(np.mean(blink_rates))
        }

    # Demographics (DeepFace)
    ages = [r.emotions.age for r in results if r.emotions and r.emotions.age is not None]
    if ages:
        summary['age'] = {
            'mean': float(np.mean(ages)),
            'min': int(np.min(ages)),
            'max': int(np.max(ages)),
            'median': int(np.median(ages))
        }

    genders = [r.emotions.gender for r in results if r.emotions and r.emotions.gender is not None]
    if genders:
        from collections import Counter
        gender_counts = Counter(genders)
        total_gender = sum(gender_counts.values())
        summary['gender'] = {
            'dominant': gender_counts.most_common(1)[0][0],
            'distribution': {k: round(v / total_gender * 100, 1) for k, v in gender_counts.items()}
        }

    return summary


@login_required
@require_http_methods(["GET"])
def get_session_status(request, session_id):
    """Get session status and progress."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    return JsonResponse({
        'id': str(session.id),
        'status': session.status,
        'progress': session.progress,
        'error_message': session.error_message,
        'results_summary': session.results_summary,
        'output_url': session.output_file.url if session.output_file else None
    })


@login_required
@require_http_methods(["GET"])
def get_frame_data(request, session_id):
    """Get frame data for a session (for chart visualization)."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    start_frame = int(request.GET.get('start', 0))
    end_frame = int(request.GET.get('end', 1000))

    frames = AnalysisFrame.objects.filter(
        session=session,
        frame_number__gte=start_frame,
        frame_number__lt=end_frame
    ).values(
        'frame_number', 'timestamp', 'face_detected',
        'head_pose', 'rppg_data', 'eye_tracking_data',
        'emotion_data', 'respiration_data'
    )

    return JsonResponse({
        'frames': list(frames)
    })


@login_required
@require_http_methods(["DELETE"])
def delete_session(request, session_id):
    """Delete an analysis session."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    # Delete associated files
    if session.input_file:
        session.input_file.delete()
    if session.output_file:
        session.output_file.delete()

    session.delete()

    return JsonResponse({'success': True})


@login_required
@require_http_methods(["GET"])
def list_sessions(request):
    """List all sessions for current user."""
    sessions = AnalysisSession.objects.filter(user=request.user).values(
        'id', 'mode', 'status', 'created_at', 'progress', 'results_summary'
    )

    return JsonResponse({
        'sessions': list(sessions)
    })


# Real-time analysis API endpoints

@require_http_methods(["POST"])
def process_frame_realtime(request):
    """
    Process a single frame for real-time analysis.
    Expects base64 encoded image data.
    """
    # Check authentication and return JSON error if not authenticated
    if not request.user.is_authenticated:
        logger.warning("Unauthenticated request to process_frame_realtime")
        return JsonResponse({'error': 'Authentication required'}, status=401)

    import base64
    import numpy as np
    import cv2
    import time

    start_time = time.perf_counter()

    try:
        data = json.loads(request.body)
        image_data = data.get('image')
        timestamp = data.get('timestamp', 0)
        modules = data.get('modules', {})

        if not image_data:
            logger.warning("Realtime frame request with no image data")
            return JsonResponse({'error': 'No image data'}, status=400)

        # Decode base64 image
        if ',' in image_data:
            image_data = image_data.split(',')[1]

        image_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            logger.warning("Failed to decode image data")
            return JsonResponse({'error': 'Invalid image'}, status=400)

        logger.debug(f"Frame received: {frame.shape}, timestamp={timestamp}")

        # Get emotion settings
        emotion_backend = data.get('emotion_backend', 'deepface')
        enable_age_gender = data.get('enable_age_gender', True)

        # Configure pipeline based on requested modules
        config = PipelineConfig(
            mode=AnalysisMode.REALTIME,
            enable_rppg=modules.get('rppg', True),
            enable_eye_tracking=modules.get('eyes', True),
            enable_emotions=modules.get('emotions', True),
            enable_respiration=modules.get('respiration', True),
            emotion_backend=emotion_backend,
            enable_age_gender=enable_age_gender
        )
        logger.debug(f"Pipeline config: emotion_backend={emotion_backend}, age_gender={enable_age_gender}")
        pipeline = FaceAnalysisPipeline(config)

        result = pipeline.process_frame(frame, timestamp)
        pipeline.close()

        # Encode overlay frame if available
        overlay_base64 = None
        if result.frame_with_overlay is not None:
            _, buffer = cv2.imencode('.jpg', result.frame_with_overlay, [cv2.IMWRITE_JPEG_QUALITY, 80])
            overlay_base64 = base64.b64encode(buffer).decode('utf-8')

        total_time = (time.perf_counter() - start_time) * 1000
        logger.debug(f"Frame processed: face_detected={result.face_detected}, "
                     f"processing_time={result.processing_time_ms:.1f}ms, total_time={total_time:.1f}ms")

        return JsonResponse({
            'success': True,
            'face_detected': result.face_detected,
            'data': result.to_dict(),
            'overlay': overlay_base64
        })

    except Exception as e:
        logger.error(f"Error processing realtime frame: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
