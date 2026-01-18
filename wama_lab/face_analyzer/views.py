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
from wama.common.utils.console_utils import push_console_line, get_console_lines

logger = logging.getLogger(__name__)


def _console(user_id: int, message: str) -> None:
    """Send message to WAMA console."""
    try:
        push_console_line(user_id, f"[Face Analyzer] {message}")
        logger.info(message)
    except Exception as e:
        logger.warning(f"Failed to push console line: {e}")

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
    user_id = request.user.id
    _console(user_id, f"Creating new session for user: {request.user.username}")
    logger.info(f"Creating new session for user: {request.user.username}")
    logger.debug(f"POST data: {dict(request.POST)}")
    logger.debug(f"FILES: {list(request.FILES.keys())}")

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
        _console(user_id, f"Session created: {session.id}")
        logger.info(f"Session created: {session.id}")

        # Handle file upload for video mode
        if mode == 'video' and 'video_file' in request.FILES:
            video_file = request.FILES['video_file']
            session.input_file = video_file
            session.save()
            _console(user_id, f"Video uploaded: {video_file.name} ({video_file.size} bytes)")
            _console(user_id, f"Saved to: {session.input_file.path}")
            logger.info(f"Video file uploaded: {video_file.name} ({video_file.size} bytes)")
            logger.info(f"Video saved to: {session.input_file.path}")
        elif mode == 'video':
            _console(user_id, "WARNING: No video file found in request!")
            logger.warning(f"No video_file in request.FILES. Available keys: {list(request.FILES.keys())}")

        return JsonResponse({
            'success': True,
            'session_id': str(session.id)
        })

    except Exception as e:
        logger.error(f"Error creating session: {e}", exc_info=True)
        _console(user_id, f"ERROR creating session: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def start_analysis(request, session_id):
    """Start analysis for a session."""
    from .tasks import process_video_task

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id
    _console(user_id, f"Starting analysis for session: {session_id}")
    logger.info(f"Starting analysis for session: {session_id}")

    if session.status == AnalysisSession.Status.PROCESSING:
        _console(user_id, "Analysis already in progress")
        return JsonResponse({
            'success': False,
            'error': 'Analysis already in progress'
        })

    try:
        session.status = AnalysisSession.Status.PROCESSING
        session.started_at = timezone.now()
        session.save()

        # Check if input file exists
        if session.mode == 'video':
            if session.input_file:
                _console(user_id, f"Input file: {session.input_file.path}")
                logger.info(f"Input file path: {session.input_file.path}")
                if os.path.exists(session.input_file.path):
                    _console(user_id, f"File exists, size: {os.path.getsize(session.input_file.path)} bytes")
                else:
                    _console(user_id, "ERROR: Input file does not exist on disk!")
                    logger.error(f"Input file does not exist: {session.input_file.path}")
                    return JsonResponse({
                        'success': False,
                        'error': 'Input file not found on disk'
                    }, status=400)
            else:
                _console(user_id, "ERROR: No input file associated with session!")
                logger.error("No input file for video session")
                return JsonResponse({
                    'success': False,
                    'error': 'No input file uploaded'
                }, status=400)

        # Start Celery task for video processing
        if session.mode == 'video' and session.input_file:
            _console(user_id, "Launching async video processing task...")
            task = process_video_task.delay(str(session.id))
            _console(user_id, f"Task queued: {task.id}")
            logger.info(f"Celery task {task.id} queued for session {session_id}")

        return JsonResponse({
            'success': True,
            'message': 'Analysis started',
            'task_id': task.id if session.mode == 'video' else None
        })

    except Exception as e:
        logger.error(f"Error starting analysis: {e}", exc_info=True)
        _console(user_id, f"ERROR: {e}")
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

    user_id = session.user_id
    _console(user_id, f"Starting video processing for session: {session.id}")

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
        modules_enabled = []
        if config.enable_rppg:
            modules_enabled.append("rPPG")
        if config.enable_eye_tracking:
            modules_enabled.append("Eye Tracking")
        if config.enable_emotions:
            modules_enabled.append("Emotions")
        if config.enable_respiration:
            modules_enabled.append("Respiration")
        _console(user_id, f"Modules enabled: {', '.join(modules_enabled)}")

        pipeline = FaceAnalysisPipeline(config)
        _console(user_id, "Pipeline initialized")

        input_path = session.input_file.path
        _console(user_id, f"Input video: {os.path.basename(input_path)}")

        # Generate output path (per-user directory, based on input filename)
        user_folder_id = session.user.id if session.user else 0
        input_basename = os.path.basename(input_path)
        input_name, input_ext = os.path.splitext(input_basename)
        output_filename = f"{input_name}_output.mp4"

        output_dir = os.path.join(settings.MEDIA_ROOT, 'face_analyzer', str(user_folder_id), 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Check if output file exists, add UUID if needed
        output_path = os.path.join(output_dir, output_filename)
        if os.path.exists(output_path):
            import uuid
            output_filename = f"{input_name}_output_{uuid.uuid4().hex[:8]}.mp4"
            output_path = os.path.join(output_dir, output_filename)

        last_progress = 0

        def progress_callback(progress):
            nonlocal last_progress
            session.progress = progress * 100
            session.save(update_fields=['progress'])
            current_pct = int(progress * 100)
            if current_pct >= last_progress + 10:
                _console(user_id, f"Processing progress: {current_pct}%")
                last_progress = current_pct

        _console(user_id, "Starting video analysis...")
        results = pipeline.process_video(input_path, output_path, progress_callback)
        _console(user_id, f"Video analysis complete: {len(results)} frames processed")

        # Save results
        from .tasks import convert_numpy_types
        _console(user_id, "Saving frame results to database...")
        for i, result in enumerate(results):
            AnalysisFrame.objects.create(
                session=session,
                frame_number=i,
                timestamp=float(result.timestamp) if result.timestamp else 0.0,
                face_detected=bool(result.face_detected),
                head_pose=convert_numpy_types(result.head_pose) if result.head_pose else None,
                rppg_data=convert_numpy_types(result.rppg.to_dict()) if result.rppg else None,
                eye_tracking_data=convert_numpy_types(result.eye_tracking.to_dict()) if result.eye_tracking else None,
                emotion_data=convert_numpy_types(result.emotions.to_dict()) if result.emotions else None,
                respiration_data=convert_numpy_types(result.respiration.to_dict()) if result.respiration else None,
                processing_time_ms=float(result.processing_time_ms) if result.processing_time_ms else 0.0
            )

        # Calculate summary statistics
        _console(user_id, "Calculating summary statistics...")
        session.results_summary = convert_numpy_types(_calculate_summary(results))
        session.output_file.name = f'face_analyzer/{user_folder_id}/output/{output_filename}'
        session.status = AnalysisSession.Status.COMPLETED
        session.completed_at = timezone.now()
        session.progress = 100
        session.save()

        pipeline.close()
        _console(user_id, f"✓ Session completed successfully!")

    except Exception as e:
        logger.error(f"Error processing video for session {session.id}: {e}", exc_info=True)
        _console(user_id, f"✗ Error: {str(e)}")
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
    from django.core.cache import cache

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    # Get real-time progress from cache if processing
    progress = session.progress
    status_message = None
    if session.status == AnalysisSession.Status.PROCESSING:
        cached_progress = cache.get(f"face_analyzer_progress_{session_id}")
        if cached_progress is not None:
            progress = cached_progress
        status_message = cache.get(f"face_analyzer_status_{session_id}")

    return JsonResponse({
        'id': str(session.id),
        'status': session.status,
        'progress': progress,
        'status_message': status_message,
        'error_message': session.error_message,
        'results_summary': session.results_summary,
        'output_url': session.output_file.url if session.output_file else None,
        'input_file': session.input_file.url if session.input_file else None
    })


@login_required
@require_http_methods(["POST"])
def cancel_analysis(request, session_id):
    """Cancel a running analysis."""
    from .tasks import stop_face_analyzer

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    if session.status != AnalysisSession.Status.PROCESSING:
        return JsonResponse({
            'success': False,
            'error': 'No analysis in progress'
        })

    _console(user_id, f"Cancellation requested for session: {session_id}")
    stop_face_analyzer(user_id)

    return JsonResponse({
        'success': True,
        'message': 'Cancellation requested'
    })


@login_required
@require_http_methods(["GET"])
def get_frame_data(request, session_id):
    """Get frame data for a session (for chart visualization)."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    # Get all frames (or paginated if needed)
    start_frame = int(request.GET.get('start', 0))
    end_frame = int(request.GET.get('end', 10000))  # Increased default limit

    frames_queryset = AnalysisFrame.objects.filter(
        session=session,
        frame_number__gte=start_frame,
        frame_number__lt=end_frame
    ).order_by('frame_number')

    total_frames = frames_queryset.count()
    # Only log once per request to avoid spam
    logger.debug(f"Loading {total_frames} frames for session {session_id}")

    # Transform frames to match frontend expected format
    transformed_frames = []
    frames_with_rppg = 0
    frames_with_hrv = 0
    frames_with_respiration = 0
    
    for frame in frames_queryset:
        frame_data = {
            'frame_number': frame.frame_number,
            'timestamp': float(frame.timestamp),
            'face_detected': frame.face_detected,
        }

        # Transform rppg_data to rppg
        if frame.rppg_data:
            rppg = frame.rppg_data.copy()
            frames_with_rppg += 1
            
            # Ensure heart_rate is available
            if 'heart_rate' not in rppg and 'hr' in rppg:
                rppg['heart_rate'] = rppg['hr']
            
            # HRV structure: hrv is already a dict with rmssd, sdnn, etc. from HRVMetrics.to_dict()
            # Check if hrv exists and has rmssd
            if 'hrv' in rppg:
                if isinstance(rppg['hrv'], dict) and 'rmssd' in rppg['hrv']:
                    frames_with_hrv += 1
                # hrv is already in correct format from HRVMetrics.to_dict()
            elif 'rmssd' in rppg:
                # If rmssd is at top level, wrap it in hrv
                rppg['hrv'] = {'rmssd': rppg['rmssd']}
                frames_with_hrv += 1
            
            frame_data['rppg'] = rppg
        else:
            frame_data['rppg'] = None

        # Transform emotion_data to emotions
        if frame.emotion_data:
            emotions = frame.emotion_data.copy()

            # Flatten nested emotions structure (from EmotionResult.to_dict())
            # The structure is: { 'emotions': {...}, 'dominant_emotion': ..., ... }
            # We need to flatten 'emotions' dict to top level for chart access
            if 'emotions' in emotions and isinstance(emotions['emotions'], dict):
                nested_emotions = emotions.pop('emotions')
                for key, value in nested_emotions.items():
                    emotions[key.lower()] = value

            # Ensure dominant is available
            if 'dominant' not in emotions and 'dominant_emotion' in emotions:
                emotions['dominant'] = emotions['dominant_emotion']

            # Normalize remaining emotion keys to lowercase
            normalized_emotions = {}
            for key, value in emotions.items():
                if key not in ['dominant', 'dominant_emotion', 'age', 'gender', 'confidence', 'valence', 'arousal', 'timestamp', 'gender_confidence']:
                    if isinstance(value, (int, float)):
                        normalized_emotions[key.lower()] = value
            emotions.update(normalized_emotions)
            frame_data['emotions'] = emotions
        else:
            frame_data['emotions'] = None

        # Transform eye_tracking_data to eye_tracking
        if frame.eye_tracking_data:
            eye_tracking = frame.eye_tracking_data.copy()
            # Ensure perclos is available
            if 'perclos' not in eye_tracking:
                eye_tracking['perclos'] = eye_tracking.get('perclos_value', 0)
            # Ensure blink_detected is available (BlinkResult.to_dict() uses 'is_blinking')
            if 'blink_detected' not in eye_tracking:
                eye_tracking['blink_detected'] = eye_tracking.get('blink', {}).get('is_blinking', False)
            frame_data['eye_tracking'] = eye_tracking
        else:
            frame_data['eye_tracking'] = None

        # Transform respiration_data to respiration
        if frame.respiration_data:
            respiration = frame.respiration_data.copy()
            frames_with_respiration += 1
            
            # Ensure rate is available (from RespirationResult.to_dict(), it's 'respiratory_rate')
            if 'rate' not in respiration and 'respiratory_rate' in respiration:
                respiration['rate'] = respiration['respiratory_rate']
            
            frame_data['respiration'] = respiration
        else:
            frame_data['respiration'] = None

        # Add face_bbox from head_pose if available
        if frame.head_pose and 'bbox' in frame.head_pose:
            frame_data['face_bbox'] = frame.head_pose['bbox']
        elif frame.head_pose and 'face_bbox' in frame.head_pose:
            frame_data['face_bbox'] = frame.head_pose['face_bbox']

        transformed_frames.append(frame_data)

    # Count frames with emotions
    frames_with_emotions = sum(1 for f in transformed_frames if f.get('emotions'))

    # Only log to console once, use debug for repeated calls
    if frames_with_rppg > 0 or frames_with_respiration > 0 or frames_with_emotions > 0:
        _console(user_id, f"Data: {frames_with_rppg} rPPG, {frames_with_hrv} HRV, {frames_with_emotions} emotions, {frames_with_respiration} respiration")

    # Debug: log sample frame data structure
    if transformed_frames:
        sample = transformed_frames[len(transformed_frames) // 2]  # Middle frame
        if sample.get('emotions'):
            logger.info(f"Sample emotions data: {list(sample['emotions'].keys())}")
        if sample.get('rppg') and sample['rppg'].get('hrv'):
            logger.info(f"Sample HRV data: {sample['rppg']['hrv']}")

    logger.debug(f"Data transformation: {frames_with_rppg} frames with rPPG, {frames_with_hrv} with HRV, {frames_with_emotions} with emotions, {frames_with_respiration} with respiration")

    # Transform summary from results_summary
    summary = {}
    if session.results_summary:
        summary_data = session.results_summary
        logger.debug(f"Summary data keys: {list(summary_data.keys())}")
        
        # Map summary fields to frontend expected format
        if 'heart_rate' in summary_data:
            hr_stats = summary_data['heart_rate']
            summary['avg_heart_rate'] = hr_stats.get('mean', 0)
        elif 'avg_heart_rate' in summary_data:
            summary['avg_heart_rate'] = summary_data['avg_heart_rate']

        # HRV: Calculate from frames if not in summary
        if 'hrv' in summary_data:
            hrv_stats = summary_data['hrv']
            if isinstance(hrv_stats, dict):
                summary['avg_hrv'] = hrv_stats.get('mean', 0)
            else:
                summary['avg_hrv'] = hrv_stats
        elif 'avg_hrv' in summary_data:
            summary['avg_hrv'] = summary_data['avg_hrv']
        else:
            # Calculate HRV average from frames
            hrv_values = []
            for frame_data in transformed_frames:
                if frame_data.get('rppg') and frame_data['rppg'].get('hrv'):
                    rmssd = frame_data['rppg']['hrv'].get('rmssd')
                    if rmssd is not None:
                        hrv_values.append(rmssd)
            if hrv_values:
                import numpy as np
                summary['avg_hrv'] = float(np.mean(hrv_values))
                # Only log once
                logger.debug(f"Calculated avg HRV from {len(hrv_values)} frames: {summary['avg_hrv']:.1f}")

        if 'respiratory_rate' in summary_data:
            rr_stats = summary_data['respiratory_rate']
            summary['avg_respiration'] = rr_stats.get('mean', 0)
        elif 'avg_respiration' in summary_data:
            summary['avg_respiration'] = summary_data['avg_respiration']
        else:
            # Calculate respiration average from frames
            rr_values = []
            for frame_data in transformed_frames:
                if frame_data.get('respiration'):
                    rate = frame_data['respiration'].get('rate') or frame_data['respiration'].get('respiratory_rate')
                    if rate is not None:
                        rr_values.append(rate)
            if rr_values:
                import numpy as np
                summary['avg_respiration'] = float(np.mean(rr_values))
                # Only log once
                logger.debug(f"Calculated avg respiration from {len(rr_values)} frames: {summary['avg_respiration']:.1f}")

        # Get dominant emotion from distribution
        if 'emotion_distribution' in summary_data:
            emotion_dist = summary_data['emotion_distribution']
            if emotion_dist:
                summary['dominant_emotion'] = max(emotion_dist.items(), key=lambda x: x[1])[0]
        elif 'dominant_emotion' in summary_data:
            summary['dominant_emotion'] = summary_data['dominant_emotion']

    logger.debug(f"Returning {len(transformed_frames)} frames and summary: {summary}")
    # Only log to console once per unique request
    if not hasattr(request, '_face_analyzer_logged'):
        _console(user_id, f"Returning {len(transformed_frames)} frames for visualization")
        request._face_analyzer_logged = True

    return JsonResponse({
        'frames': transformed_frames,
        'summary': summary
    })


@login_required
@require_http_methods(["POST", "DELETE"])
def delete_session(request, session_id):
    """Delete an analysis session."""
    logger.info(f"Deleting session {session_id} for user {request.user.username}")
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    # Delete associated files
    if session.input_file:
        logger.debug(f"Deleting input file: {session.input_file.path}")
        session.input_file.delete()
    if session.output_file:
        logger.debug(f"Deleting output file: {session.output_file.path}")
        session.output_file.delete()

    session.delete()
    logger.info(f"Session {session_id} deleted successfully")

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

@login_required
@require_http_methods(["GET"])
def console_content(request):
    """Get console output for the current user."""
    user = request.user
    console_lines = get_console_lines(user.id, limit=100)
    
    return JsonResponse({
        'output': console_lines
    })


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
