"""
Celery tasks for Face Analyzer video processing.
"""
import os
import logging
from celery import shared_task
from django.db import close_old_connections
from django.core.cache import cache
from django.utils import timezone

from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)


def convert_numpy_types(obj):
    """
    Recursively convert numpy types to native Python types for JSON serialization.
    """
    import numpy as np

    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_numpy_types(item) for item in obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    else:
        return obj


def _console(user_id: int, message: str) -> None:
    """Send message to WAMA console."""
    try:
        push_console_line(user_id, f"[Face Analyzer] {message}")
        logger.info(message)
    except Exception as e:
        logger.warning(f"Failed to push console line: {e}")


def set_session_progress(session_id: str, percent: float, status_message: str = None) -> None:
    """Update session progress in cache and DB."""
    try:
        from .models import AnalysisSession
        pct = max(0.0, min(100.0, float(percent)))
        cache.set(f"face_analyzer_progress_{session_id}", pct, timeout=3600)
        if status_message:
            cache.set(f"face_analyzer_status_{session_id}", status_message, timeout=3600)
        AnalysisSession.objects.filter(pk=session_id).update(progress=pct)
    except Exception as e:
        logger.warning(f"Failed to set progress: {e}")


@shared_task(bind=True)
def process_video_task(self, session_id: str):
    """
    Celery task to process a video for face analysis.

    Args:
        session_id: UUID of the AnalysisSession to process
    """
    import cv2
    import numpy as np

    close_old_connections()

    try:
        from .models import AnalysisSession, AnalysisFrame
        from .pipeline import FaceAnalysisPipeline, PipelineConfig, AnalysisMode
        from .rppg import RPPGMethod
        from django.conf import settings

        session = AnalysisSession.objects.get(pk=session_id)
        user_id = session.user_id

        _console(user_id, f"Starting video processing task for session: {session_id}")

        # Check if stop was requested
        if cache.get(f"stop_face_analyzer_{user_id}", False):
            cache.delete(f"stop_face_analyzer_{user_id}")
            session.status = AnalysisSession.Status.FAILED
            session.error_message = "Processing cancelled by user"
            session.save()
            _console(user_id, "Processing cancelled by user")
            return {"cancelled": str(session_id)}

        # Verify input file exists
        if not session.input_file:
            raise ValueError("No input file associated with session")

        input_path = session.input_file.path
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")

        _console(user_id, f"Input video: {os.path.basename(input_path)}")
        _console(user_id, f"File size: {os.path.getsize(input_path) / (1024*1024):.1f} MB")

        # Configure pipeline
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

        # Initialize pipeline
        set_session_progress(session_id, 5, "Initializing pipeline...")
        pipeline = FaceAnalysisPipeline(config)
        _console(user_id, "Pipeline initialized")

        # Generate output path
        output_filename = f"{session_id}_output.mp4"
        output_dir = os.path.join(settings.MEDIA_ROOT, 'face_analyzer', 'output')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        last_progress = 0

        def progress_callback(progress):
            nonlocal last_progress
            # Scale progress: 10% -> 90% for video processing
            scaled_progress = 10 + (progress * 80)
            set_session_progress(session_id, scaled_progress)

            current_pct = int(progress * 100)
            if current_pct >= last_progress + 10:
                _console(user_id, f"Processing progress: {current_pct}%")
                last_progress = current_pct

            # Check for cancellation
            if cache.get(f"stop_face_analyzer_{user_id}", False):
                raise InterruptedError("Processing cancelled by user")

        # Process video
        set_session_progress(session_id, 10, "Processing video frames...")
        _console(user_id, "Starting video analysis...")

        results = pipeline.process_video(input_path, output_path, progress_callback)
        _console(user_id, f"Video analysis complete: {len(results)} frames processed")

        # Save results to database
        set_session_progress(session_id, 92, "Saving results to database...")
        _console(user_id, "Saving frame results to database...")

        # Batch create frames for better performance
        frames_to_create = []
        for i, result in enumerate(results):
            # Convert numpy types to native Python types for JSON serialization
            frames_to_create.append(AnalysisFrame(
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
            ))

        # Bulk create in batches of 500
        batch_size = 500
        for i in range(0, len(frames_to_create), batch_size):
            AnalysisFrame.objects.bulk_create(frames_to_create[i:i+batch_size])

        # Calculate summary statistics
        set_session_progress(session_id, 96, "Calculating summary statistics...")
        _console(user_id, "Calculating summary statistics...")
        session.results_summary = convert_numpy_types(_calculate_summary(results))

        # Finalize session
        session.output_file.name = f'face_analyzer/output/{output_filename}'
        session.status = AnalysisSession.Status.COMPLETED
        session.completed_at = timezone.now()
        session.progress = 100
        session.save()

        pipeline.close()
        set_session_progress(session_id, 100, "Complete")
        _console(user_id, f"Session completed successfully!")

        return {"processed": str(session_id), "frames": len(results)}

    except InterruptedError as e:
        logger.warning(f"Processing interrupted for session {session_id}: {e}")
        try:
            session = AnalysisSession.objects.get(pk=session_id)
            session.status = AnalysisSession.Status.FAILED
            session.error_message = str(e)
            session.save()
            _console(session.user_id, f"Processing cancelled")
        except Exception:
            pass
        return {"cancelled": str(session_id)}

    except Exception as e:
        logger.error(f"Error processing video for session {session_id}: {e}", exc_info=True)
        try:
            session = AnalysisSession.objects.get(pk=session_id)
            _console(session.user_id, f"ERROR: {str(e)}")
            session.status = AnalysisSession.Status.FAILED
            session.error_message = str(e)
            session.save()
        except Exception:
            pass
        return {"error": str(e), "session_id": str(session_id)}


def _calculate_summary(results):
    """Calculate summary statistics from analysis results."""
    import numpy as np

    summary = {
        'total_frames': len(results),
        'frames_with_face': sum(1 for r in results if r.face_detected),
    }

    # Heart rate statistics
    hr_values = [r.rppg.heart_rate for r in results if r.rppg and r.rppg.heart_rate]
    if hr_values:
        summary['heart_rate'] = {
            'mean': float(np.mean(hr_values)),
            'min': float(np.min(hr_values)),
            'max': float(np.max(hr_values)),
            'std': float(np.std(hr_values))
        }

    # Respiratory rate
    rr_values = [r.respiration.respiratory_rate for r in results if r.respiration and r.respiration.respiratory_rate]
    if rr_values:
        summary['respiratory_rate'] = {
            'mean': float(np.mean(rr_values)),
            'min': float(np.min(rr_values)),
            'max': float(np.max(rr_values))
        }

    # Dominant emotions distribution
    emotion_counts = {}
    for r in results:
        if r.emotions and r.emotions.dominant_emotion:
            emotion = r.emotions.dominant_emotion
            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
    if emotion_counts:
        total = sum(emotion_counts.values())
        summary['emotion_distribution'] = {
            k: round(v / total * 100, 1) for k, v in emotion_counts.items()
        }

    # Blink statistics
    blink_rates = [r.eye_tracking.blink.blink_rate for r in results if r.eye_tracking and r.eye_tracking.blink]
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


def stop_face_analyzer(user_id: int) -> None:
    """
    Request stop for face analyzer processing.
    The flag will be checked during video processing.
    """
    cache.set(f"stop_face_analyzer_{user_id}", True, timeout=60)
    logger.info(f"Face analyzer stop requested for user {user_id}")
