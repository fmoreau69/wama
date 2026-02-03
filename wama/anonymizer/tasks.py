import os
import threading
import time
from celery import shared_task
from django.db import close_old_connections
from django.core.cache import cache
from django.contrib.auth import get_user_model
from .models import Media, UserSettings
from anonymizer import anonymize
from .utils.media_utils import get_input_media_path
from .utils.yolo_utils import get_model_path
from wama.common.utils.media_paths import get_app_media_path
from .utils.sam3_manager import check_sam3_installed, validate_sam3_prompt
from wama.common.utils.console_utils import push_console_line

# ----------------------------------------------------------------------
# Tâche principale pour traiter un média
# ----------------------------------------------------------------------
@shared_task(bind=True)
def process_single_media(self, media_id):
    """
    Traite un média unique en DB, en respectant les settings utilisateur.
    """

    close_old_connections()

    try:
        media = Media.objects.get(pk=media_id)
        user = media.user
        user_settings, _ = UserSettings.objects.get_or_create(user=user)
        ms_custom = media.MSValues_customised

        # Get precision level and use_segmentation from media or user settings
        precision_level = media.precision_level if ms_custom else user_settings.precision_level
        use_segmentation = media.use_segmentation if ms_custom else user_settings.use_segmentation

        # Get SAM3 settings from media or user settings
        use_sam3 = media.use_sam3 if ms_custom else user_settings.use_sam3
        sam3_prompt = media.sam3_prompt if ms_custom else user_settings.sam3_prompt

        # Debug: Log SAM3 settings retrieval
        print(f"[process_single_media] DEBUG: ms_custom={ms_custom}")
        print(f"[process_single_media] DEBUG: media.use_sam3={media.use_sam3}, user_settings.use_sam3={user_settings.use_sam3}")
        print(f"[process_single_media] DEBUG: media.sam3_prompt='{media.sam3_prompt}', user_settings.sam3_prompt='{user_settings.sam3_prompt}'")
        print(f"[process_single_media] DEBUG: Final use_sam3={use_sam3}, sam3_prompt='{sam3_prompt}'")
        push_console_line(user.id, f"[DEBUG] SAM3 settings: use_sam3={use_sam3}, prompt='{sam3_prompt[:30] if sam3_prompt else ''}'")

        # Determine if this is an image (interpolation doesn't apply to images)
        image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tiff', '.tif']
        is_image = media.file_ext and media.file_ext.lower() in image_extensions

        # Get interpolation setting (disabled for images)
        interpolate_detections = False if is_image else (
            media.interpolate_detections if ms_custom else user_settings.interpolate_detections
        )

        kwargs = {
            'media_path': get_input_media_path(media.file.name, user.id),
            'file_ext': media.file_ext,
            'classes2blur': media.classes2blur if ms_custom else user_settings.classes2blur,
            'blur_ratio': media.blur_ratio if ms_custom else user_settings.blur_ratio,
            'roi_enlargement': media.roi_enlargement if ms_custom else user_settings.roi_enlargement,
            'progressive_blur': media.progressive_blur if ms_custom else user_settings.progressive_blur,
            'detection_threshold': media.detection_threshold if ms_custom else user_settings.detection_threshold,
            'interpolate_detections': interpolate_detections,
            'max_interpolation_frames': media.max_interpolation_frames if ms_custom else user_settings.max_interpolation_frames,
            'show_preview': user_settings.show_preview,
            'show_boxes': user_settings.show_boxes,
            'show_labels': user_settings.show_labels,
            'show_conf': user_settings.show_conf,
            'precision_level': precision_level,
            'use_segmentation': use_segmentation,
            # SAM3 parameters
            'use_sam3': use_sam3,
            'sam3_prompt': sam3_prompt,
            'user_id': user.id,  # For console logging
        }

        # Model selection: prefer media-specific model, then user's global model, otherwise auto-select
        try:
            from .utils.yolo_utils import get_model_path as _gmp
            from .utils.model_selector import select_model_by_precision

            # Priority: 1) Media-specific model, 2) User's global model, 3) Auto-select
            model_to_use = None

            # Check if media has a specific model set (only if customised)
            if ms_custom and media.model_to_use and media.model_to_use.strip():
                model_to_use = media.model_to_use.strip()
                push_console_line(user.id, f"Using media-specific model: {model_to_use}")
            # Otherwise check user's global setting
            elif hasattr(user_settings, 'model_to_use') and user_settings.model_to_use and user_settings.model_to_use.strip():
                model_to_use = user_settings.model_to_use.strip()
                push_console_line(user.id, f"Using user's global model: {model_to_use}")

            if model_to_use:
                kwargs['model_path'] = _gmp(model_to_use)
            else:
                # Auto-select model based on precision level and classes
                selected_model = select_model_by_precision(
                    classes_to_blur=kwargs['classes2blur'],
                    precision_level=precision_level
                )

                if selected_model:
                    kwargs['model_path'] = _gmp(selected_model)
                    push_console_line(user.id, f"Auto-selected model (precision {precision_level}): {selected_model}")
                # Fallback to custom face/plate model if needed
                elif any(c in kwargs['classes2blur'] for c in ['face', 'plate']):
                    kwargs['model_path'] = _gmp("yolov8m_faces&plates_720p.pt")
                    push_console_line(user.id, f"Using custom face/plate model")
        except Exception as e:
            push_console_line(user.id, f"Warning: Model selection failed ({e}), using default")
            pass

        # Vérifie si un stop a été demandé
        if cache.get(f"stop_process_{user.id}", False):
            cache.delete(f"stop_process_{user.id}")
            return {"stopped": media.id}

        # Reset progress at start
        set_media_progress(media.id, 0)
        push_console_line(user.id, f"Start processing media {media.id} ...")

        # Load model (early progress)
        try:
            cache.set(f"media_stage_{media.id}", "loading_model", timeout=3600)
            set_media_progress(media.id, 5)
            push_console_line(user.id, f"Loading model for media {media.id} ...")
        except Exception:
            pass

        # Run process with simulated progress
        set_media_progress(media.id, 10)
        push_console_line(user.id, f"Running anonymization for media {media.id} ...")

        # Estimate processing time based on media type and size (rough estimate)
        # Video: ~60 seconds, Image: ~10 seconds
        # Adjust based on actual experience
        is_video = media.file_ext.lower() in ['mp4', 'avi', 'mov', 'mkv', 'webm']
        estimated_duration = 60 if is_video else 10

        # Start progress simulation in background thread (10% -> 90%)
        stop_flag = f"stop_progress_sim_{media.id}"
        cache.delete(stop_flag)  # Ensure it's clear
        progress_thread = threading.Thread(
            target=simulate_progress,
            args=(media.id, 10, 90, estimated_duration, stop_flag),
            daemon=True
        )
        progress_thread.start()

        try:
            # Run the actual processing
            start_process(**kwargs)
        finally:
            # Stop the progress simulation
            cache.set(stop_flag, True, timeout=10)
            progress_thread.join(timeout=2)  # Wait max 2 seconds for thread to finish

        # Marque le média comme traité
        try:
            media.refresh_from_db()
            media.processed = True
            media.save(update_fields=["processed"])
            set_media_progress(media.id, 100)
            push_console_line(user.id, f"Finished media {media.id} ✔")
        except media.__class__.DoesNotExist:
            push_console_line(user.id, f"Warning: Media {media.id} was deleted during processing")
            return {"error": "Media was deleted", "media_id": media_id}

        return {"processed": media.id}

    except Exception as e:
        print(f"Erreur sur media {media_id}: {e}")
        push_console_line(user.id, f"Error on media {media_id}: {e}")
        # mark as failed state (keep last known progress)
        return {"error": str(e), "media_id": media_id}


# ----------------------------------------------------------------------
# Fonction pour lancer le traitement du média
# ----------------------------------------------------------------------
def start_process(**kwargs):
    """
    Route processing to SAM3 or YOLO based on settings.

    If use_sam3=True and sam3_prompt is provided, uses SAM3 for segmentation.
    Otherwise, uses the standard YOLO-based Anonymize class.
    """
    media_path = kwargs.get('media_path', 'unknown')
    use_sam3 = kwargs.get('use_sam3', False)
    sam3_prompt = kwargs.get('sam3_prompt', '')
    user_id = kwargs.get('user_id')

    # Debug: Log SAM3 routing decision
    print(f"[start_process] DEBUG: use_sam3={use_sam3} (type={type(use_sam3)})")
    print(f"[start_process] DEBUG: sam3_prompt='{sam3_prompt}' (type={type(sam3_prompt)})")
    print(f"[start_process] DEBUG: Condition check: use_sam3={bool(use_sam3)}, sam3_prompt={bool(sam3_prompt)}, strip={bool(sam3_prompt and sam3_prompt.strip())}")
    if user_id:
        push_console_line(user_id, f"[DEBUG] use_sam3={use_sam3}, sam3_prompt='{sam3_prompt[:30] if sam3_prompt else ''}'...")

    # Route to SAM3 if enabled and prompt provided
    if use_sam3 and sam3_prompt and sam3_prompt.strip():
        print(f"[SAM3] Process started for media: {media_path} ...")

        # Validate SAM3 is available
        if not check_sam3_installed():
            error_msg = "SAM3 not installed. Falling back to YOLO."
            print(f"Warning: {error_msg}")
            if user_id:
                push_console_line(user_id, f"Warning: {error_msg}")
            # Fall through to YOLO
        else:
            # Validate prompt
            is_valid, error = validate_sam3_prompt(sam3_prompt)
            if not is_valid:
                error_msg = f"Invalid SAM3 prompt: {error}. Falling back to YOLO."
                print(f"Warning: {error_msg}")
                if user_id:
                    push_console_line(user_id, f"Warning: {error_msg}")
                # Fall through to YOLO
            else:
                # Use SAM3 processor
                try:
                    from anonymizer.sam3_processor import SAM3Processor

                    if user_id:
                        push_console_line(user_id, f"Using SAM3 with prompt: {sam3_prompt[:50]}...")

                    # Get user-specific paths for SAM3
                    source_dir = get_app_media_path('anonymizer', user_id, 'input') if user_id else None
                    dest_dir = get_app_media_path('anonymizer', user_id, 'output') if user_id else None

                    processor = SAM3Processor(source_dir=source_dir, destination_dir=dest_dir)
                    processor.load_model('auto')
                    processor.process(**kwargs)

                    if user_id:
                        push_console_line(user_id, f"SAM3 processing complete")
                    return
                except ImportError as e:
                    error_msg = f"SAM3 import error: {e}. Falling back to YOLO."
                    print(f"Warning: {error_msg}")
                    if user_id:
                        push_console_line(user_id, f"Warning: {error_msg}")
                except Exception as e:
                    error_msg = f"SAM3 processing error: {e}. Falling back to YOLO."
                    print(f"Warning: {error_msg}")
                    if user_id:
                        push_console_line(user_id, f"Warning: {error_msg}")

    # Default: Use YOLO-based Anonymize
    print(f"[YOLO] Process started for media: {media_path} ...")
    if user_id:
        push_console_line(user_id, f"Using YOLO with classes: {kwargs.get('classes2blur', [])}")

    # Get user-specific paths for YOLO
    source_dir = get_app_media_path('anonymizer', user_id, 'input') if user_id else None
    dest_dir = get_app_media_path('anonymizer', user_id, 'output') if user_id else None

    model = anonymize.Anonymize(source_dir=source_dir, destination_dir=dest_dir)
    anonymize.Anonymize.load_model(model, **kwargs)
    anonymize.Anonymize.process(model, **kwargs)


# ----------------------------------------------------------------------
# Arrêt d'un traitement utilisateur
# ----------------------------------------------------------------------
def stop_process(user_id):
    """
    Demande l'arrêt d'un traitement utilisateur en cours.
    Le flag sera vérifié dans la boucle de process_single_media.
    """
    cache.set(f"stop_process_{user_id}", True, timeout=60)
    print(f"Process stop demandé pour user {user_id}")


# ----------------------------------------------------------------------
# Tâche pour traiter tous les médias d'un utilisateur (file batch)
# ----------------------------------------------------------------------
@shared_task(bind=True)
def process_user_media_batch(self, user_id):
    """
    Enfile tous les médias non traités d'un utilisateur dans des tâches individuelles.
    """
    import logging
    logger = logging.getLogger('celery')

    logger.info(f"[process_user_media_batch] Starting batch process for user_id={user_id}")

    close_old_connections()

    User = get_user_model()
    user = User.objects.get(pk=user_id)
    logger.info(f"[process_user_media_batch] User: {user.username}")

    medias_list = Media.objects.filter(user=user, processed=False)
    logger.info(f"[process_user_media_batch] Found {medias_list.count()} unprocessed media(s)")

    if not medias_list.exists():
        logger.warning(f"[process_user_media_batch] No media to process for user {user.username}")
        return {"processed": 0}

    task_ids = []
    for media in medias_list:
        # Chaque média est traité dans sa propre tâche Celery
        logger.info(f"[process_user_media_batch] Launching task for media {media.id} ({media.title})")
        task = process_single_media.delay(media.id)
        task_ids.append(task.id)
        logger.info(f"[process_user_media_batch] Task {task.id} launched for media {media.id}")

    logger.info(f"[process_user_media_batch] Total tasks launched: {len(task_ids)}")
    return {"queued_tasks": task_ids, "total": medias_list.count()}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def set_media_progress(media_id: int, percent: int) -> None:
    """Persist media progress in cache and DB (clamped 0..100)."""
    try:
        pct = max(0, min(100, int(percent)))
        cache.set(f"media_progress_{media_id}", pct, timeout=3600)
        Media.objects.filter(pk=media_id).update(blur_progress=pct)
    except Exception:
        # best effort only
        pass


def simulate_progress(media_id: int, start_pct: int, end_pct: int, duration_seconds: int, stop_flag_key: str):
    """
    Simule une progression graduelle de start_pct à end_pct sur duration_seconds.
    S'arrête si le flag stop_flag_key est détecté dans le cache.
    """
    if duration_seconds <= 0 or start_pct >= end_pct:
        return

    steps = min(duration_seconds, end_pct - start_pct)  # Max 1 step per second
    interval = duration_seconds / steps
    increment = (end_pct - start_pct) / steps

    current = start_pct
    for _ in range(steps):
        if cache.get(stop_flag_key, False):
            break
        time.sleep(interval)
        current += increment
        set_media_progress(media_id, int(current))
