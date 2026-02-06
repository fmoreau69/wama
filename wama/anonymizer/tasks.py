import os
import logging
import threading
import time
from celery import shared_task, chord, group
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

# Parallel detection imports
from .parallel_detection import (
    needs_parallel_detection,
    launch_parallel_detection,
    store_detection_results,
    load_detection_results,
    merge_all_detections,
    cleanup_detection_cache,
)

logger = logging.getLogger(__name__)

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

        # ======================================================================
        # PARALLEL DETECTION: Check if multiple models are needed
        # ======================================================================
        # Determine user's specified model (if any)
        user_specified_model = (
            (ms_custom and media.model_to_use and media.model_to_use.strip()) or
            (hasattr(user_settings, 'model_to_use') and user_settings.model_to_use and user_settings.model_to_use.strip())
        )

        # Check if specialty classes (face, plate) are requested
        # These often require dedicated models even if user has a default COCO model
        specialty_classes_set = {'face', 'plate', 'license_plate', 'license plate'}
        specialty_classes_requested = any(
            c.lower() in specialty_classes_set for c in kwargs['classes2blur']
        )

        # Enable parallel detection check if:
        # - SAM3 is not being used AND
        # - Either no user model is specified OR specialty classes are requested
        #   (specialty classes need dedicated models, can't rely on user's COCO model)
        should_check_parallel = not use_sam3 and (not user_specified_model or specialty_classes_requested)

        # Debug: Log parallel detection decision
        logger.info(f"[ParallelCheck] use_sam3={use_sam3}, user_specified_model={user_specified_model}")
        logger.info(f"[ParallelCheck] specialty_classes_requested={specialty_classes_requested}, should_check_parallel={should_check_parallel}")
        logger.info(f"[ParallelCheck] classes2blur={kwargs['classes2blur']}, precision_level={precision_level}")
        push_console_line(user.id, f"[Parallel Check] SAM3={use_sam3}, user_model={user_specified_model}, specialty={specialty_classes_requested}")

        if should_check_parallel:
            parallel_info = needs_parallel_detection(kwargs['classes2blur'], precision_level)

            logger.info(f"[ParallelCheck] parallel_info: parallel={parallel_info.get('parallel')}, "
                        f"models={len(parallel_info.get('models', []))}, coverage={parallel_info.get('coverage')}")
            push_console_line(user.id, f"[Parallel Check] parallel={parallel_info.get('parallel')}, "
                              f"models={len(parallel_info.get('models', []))}")

            if parallel_info.get('unsupported_classes'):
                push_console_line(user.id, f"[Parallel Check] Unsupported classes: {parallel_info['unsupported_classes']}")

            if parallel_info['parallel'] and len(parallel_info['models']) > 1:
                # Multiple models needed - use parallel detection workflow
                push_console_line(user.id, f"[Parallel] Detected {len(parallel_info['models'])} models needed")
                for m in parallel_info['models']:
                    push_console_line(user.id, f"  - {m['id']}: {m['classes']}")

                # Add paths to kwargs for parallel tasks
                kwargs['source_dir'] = str(get_app_media_path('anonymizer', user.id, 'input'))
                kwargs['dest_dir'] = str(get_app_media_path('anonymizer', user.id, 'output'))
                kwargs['is_image'] = is_image

                # Reset progress
                set_media_progress(media.id, 0)
                push_console_line(user.id, f"[Parallel] Launching parallel detection for media {media.id}...")

                # Launch parallel detection workflow (chord: group of detections + merge callback)
                launch_parallel_detection(media.id, parallel_info['models'], kwargs)

                # Return immediately - the chord callback will handle completion
                return {"processing": "parallel", "media_id": media.id, "models": len(parallel_info['models'])}

        # ======================================================================
        # SINGLE MODEL PATH: Standard processing (existing flow)
        # ======================================================================
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


# ======================================================================
# PARALLEL DETECTION TASKS
# ======================================================================

@shared_task(bind=True)
def detect_with_model(self, media_id, model_id, model_path, classes_to_detect, **kwargs):
    """
    Detection-only task for sequential multi-model processing.

    Runs detection with a single model and stores results in cache.
    Tasks run sequentially (chained) to avoid GPU conflicts.

    Args:
        media_id: Media ID being processed
        model_id: Identifier of the model (e.g., 'detect/yolo11n.pt')
        model_path: Full path to the model file
        classes_to_detect: List of class names this model should detect
        **kwargs: Additional parameters including:
            - media_path: Path to the media file
            - detection_threshold: Confidence threshold
            - model_index: Index of this model in the sequence (0-based)
            - total_models: Total number of models being used

    Returns:
        dict with success status and detection count
    """
    from anonymizer.detection_only import DetectionOnlyProcessor

    close_old_connections()

    # Extract progress calculation parameters
    model_index = kwargs.pop('model_index', 0)
    total_models = kwargs.pop('total_models', 1)

    try:
        media = Media.objects.get(pk=media_id)
        user_id = media.user_id

        logger.info(f"[Sequential] detect_with_model started: media={media_id}, model={model_id} ({model_index + 1}/{total_models})")
        push_console_line(user_id, f"[Detection {model_index + 1}/{total_models}] {model_id}...")

        # Calculate progress: detection phase is 0-45%, blur phase is 45-100%
        # Each model gets an equal share of the detection phase
        detection_phase_pct = 45
        start_pct = int((model_index / total_models) * detection_phase_pct)
        end_pct = int(((model_index + 1) / total_models) * detection_phase_pct)

        # Update progress at start of this detection
        set_media_progress(media_id, start_pct)

        # Create detection processor
        processor = DetectionOnlyProcessor(model_path=model_path)

        # Run detection
        results = processor.detect_media(
            media_path=kwargs['media_path'],
            classes_to_detect=classes_to_detect,
            detection_threshold=kwargs.get('detection_threshold', 0.25),
            use_tracking=not kwargs.get('is_image', False),
        )

        # Store results in cache for later merging
        store_detection_results(media_id, model_id, results)

        # Count detections
        det_count = sum(len(dets) for dets in results.get('frame_detections', {}).values())
        logger.info(f"[Sequential] detect_with_model complete: model={model_id}, detections={det_count}")
        push_console_line(user_id, f"[Detection {model_index + 1}/{total_models}] {det_count} detections")

        # Update progress at end of this detection
        set_media_progress(media_id, end_pct)

        # Cleanup
        processor.unload()

        return {
            'success': True,
            'media_id': media_id,
            'model_id': model_id,
            'detection_count': det_count,
        }

    except Exception as e:
        logger.error(f"[Parallel] detect_with_model failed: model={model_id}, error={e}")
        try:
            push_console_line(media.user_id, f"[Parallel] Error in {model_id}: {e}")
        except:
            pass
        return {
            'success': False,
            'media_id': media_id,
            'model_id': model_id,
            'error': str(e),
        }


@shared_task(bind=True)
def merge_and_blur_detections(self, detection_results=None, media_id=None, **kwargs):
    """
    Merge detection results from sequential tasks and apply blurring.

    This task runs after all detection tasks complete. It retrieves cached
    detection results and merges them before applying blur.

    Supports two modes:
    1. Sequential chain mode: model_ids passed in kwargs, detection_results
       is the result from the last detection task
    2. Legacy chord mode: detection_results is a list of all task results

    Args:
        detection_results: Result from last detection task (chain) or list (chord)
        media_id: Media ID being processed
        **kwargs: Blur settings, paths, and model_ids (for chain mode)

    Returns:
        dict with success status and processing info
    """
    from anonymizer.merged_blur import MergedBlurProcessor

    close_old_connections()

    # Handle case where media_id is passed in kwargs (si() mode)
    if media_id is None:
        media_id = kwargs.get('media_id')
    if media_id is None:
        raise ValueError("media_id is required but was not provided")

    try:
        media = Media.objects.get(pk=media_id)
        user_id = media.user_id

        logger.info(f"[Merge] merge_and_blur_detections started: media={media_id}")

        # Get model IDs - check kwargs first (chain mode), then detection_results (chord mode)
        if 'model_ids' in kwargs and kwargs['model_ids']:
            # Chain mode: model_ids explicitly passed
            model_ids = kwargs['model_ids']
            logger.info(f"[Parallel] Using model_ids from kwargs: {model_ids}")
        elif isinstance(detection_results, list):
            # Chord mode: extract from detection results list
            model_ids = [r['model_id'] for r in detection_results if r.get('success')]
            failed_models = [r['model_id'] for r in detection_results if not r.get('success')]
            if failed_models:
                push_console_line(user_id, f"[Parallel] Warning: {len(failed_models)} model(s) failed")
                logger.warning(f"[Parallel] Failed models: {failed_models}")
        else:
            # Single result (shouldn't happen, but handle gracefully)
            model_ids = kwargs.get('model_ids', [])
            if not model_ids and isinstance(detection_results, dict) and detection_results.get('model_id'):
                model_ids = [detection_results['model_id']]

        if not model_ids:
            raise Exception("No model IDs available - cannot merge detections")

        push_console_line(user_id, f"[Parallel] Merging results from {len(model_ids)} model(s)...")

        # Merge all detections from cache
        merged = merge_all_detections(media_id, model_ids)

        total_detections = sum(len(dets) for dets in merged.get('frame_detections', {}).values())
        push_console_line(user_id, f"[Parallel] Total merged detections: {total_detections}")

        # Apply blurring with merged detections (45% -> 100%)
        push_console_line(user_id, f"[Blur] Applying blur to {total_detections} detections...")
        set_media_progress(media_id, 45)

        processor = MergedBlurProcessor(
            source_dir=kwargs.get('source_dir'),
            destination_dir=kwargs.get('dest_dir'),
        )

        processor.process_with_detections(
            media_path=kwargs['media_path'],
            merged_detections=merged,
            blur_ratio=kwargs.get('blur_ratio', 25),
            progressive_blur=kwargs.get('progressive_blur', 15),
            roi_enlargement=kwargs.get('roi_enlargement', 1.05),
            rounded_edges=kwargs.get('rounded_edges', 5),
        )

        # Clean up detection cache
        cleanup_detection_cache(media_id, model_ids)

        # Mark media as processed
        media.refresh_from_db()
        media.processed = True
        media.save(update_fields=['processed'])
        set_media_progress(media_id, 100)

        push_console_line(user_id, f"[Parallel] Complete! ✓ ({len(model_ids)} models, {total_detections} detections)")
        logger.info(f"[Parallel] merge_and_blur_detections complete: media={media_id}")

        return {
            'success': True,
            'media_id': media_id,
            'models_used': model_ids,
            'total_detections': total_detections,
        }

    except Exception as e:
        logger.error(f"[Parallel] merge_and_blur_detections failed: media={media_id}, error={e}")
        try:
            push_console_line(user_id, f"[Parallel] Merge error: {e}")
        except:
            pass
        return {
            'success': False,
            'media_id': media_id,
            'error': str(e),
        }
