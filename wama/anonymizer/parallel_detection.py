"""
Multi-Model Detection Module for WAMA Anonymizer.

Orchestrates detection across multiple models for classes that require
different specialized models (e.g., faces from a face-specific model +
COCO classes from a general YOLO model).

Note: Due to GPU memory conflicts when multiple PyTorch models try to use
CUDA simultaneously, detection tasks run SEQUENTIALLY (not in parallel).
This prevents "CUDA driver error" issues while still supporting multi-model
detection workflows. Results are cached between tasks and merged before blurring.
"""

import hashlib
import json
import logging
import base64
import numpy as np

from celery import chord, group, chain
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Cache timeout for detection results (1 hour)
DETECTION_CACHE_TIMEOUT = 3600


def get_cache_key(media_id: int, model_id: str) -> str:
    """
    Generate cache key for detection results.

    Args:
        media_id: ID of the media being processed
        model_id: Model identifier (e.g., 'detect/yolo11n.pt')

    Returns:
        Cache key string
    """
    model_hash = hashlib.md5(model_id.encode()).hexdigest()[:8]
    return f"anon_detection_{media_id}_{model_hash}"


def needs_parallel_detection(classes_to_blur: list, precision_level: int) -> dict:
    """
    Determine if parallel detection is needed.

    Analyzes the requested classes and determines if multiple models are
    required to cover all classes (e.g., face model + COCO model).

    Args:
        classes_to_blur: List of class names to detect
        precision_level: 0-100 precision level (affects model selection)

    Returns:
        dict with:
        - 'parallel': bool - True if multiple models needed
        - 'models': list of model info dicts with classes to detect
        - 'coverage': float - percentage of classes covered
        - 'unsupported': list of classes with no available model
    """
    if not classes_to_blur:
        return {
            'parallel': False,
            'models': [],
            'coverage': 0,
            'unsupported': [],
        }

    from .utils.model_selector import select_best_models_by_precision

    selection = select_best_models_by_precision(
        classes_to_blur=classes_to_blur,
        precision_level=precision_level
    )

    return {
        'parallel': len(selection['models_to_use']) > 1,
        'models': selection['models_to_use'],
        'coverage': selection['coverage'],
        'unsupported': selection.get('unsupported_classes', []),
    }


def launch_parallel_detection(media_id: int, models_info: list, kwargs: dict):
    """
    Launch multi-model detection tasks using Celery.

    Due to GPU memory conflicts when multiple PyTorch models try to use
    CUDA simultaneously, we run detection tasks SEQUENTIALLY (not in parallel).
    Only the final merge+blur step runs after all detections complete.

    This approach is more reliable than true parallel execution which causes
    "CUDA driver error: unknown error" when multiple models compete for GPU.

    Args:
        media_id: Media ID to process
        models_info: List of model info dicts (from needs_parallel_detection)
        kwargs: Processing kwargs (paths, thresholds, etc.)

    Returns:
        AsyncResult of the workflow
    """
    from .tasks import detect_with_model, merge_and_blur_detections

    # Create detection tasks for each model
    detection_tasks = []
    model_ids_for_merge = []
    total_models = len(models_info)

    for idx, model_info in enumerate(models_info):
        # Use si() (immutable signature) so the task ignores the result of the previous task
        # This is necessary because chain() passes the previous result as the first argument
        task = detect_with_model.si(
            media_id=media_id,
            model_id=model_info['id'],
            model_path=model_info['path'],
            classes_to_detect=model_info['classes'],
            model_index=idx,           # For progress calculation
            total_models=total_models,  # For progress calculation
            **kwargs
        )
        detection_tasks.append(task)
        model_ids_for_merge.append(model_info['id'])

    # Run detections SEQUENTIALLY to avoid GPU conflicts, then merge
    # Each detection task stores results in cache, merge task retrieves them
    #
    # We use chain instead of chord(group()) because:
    # - GPU can only handle one model at a time reliably
    # - Sequential execution prevents CUDA errors
    # - Total time is similar (GPU is the bottleneck anyway)

    # Build sequential chain: detect1 | detect2 | ... | merge
    # The merge task needs to collect results from all models
    # Use si() for merge task too since we pass model_ids in kwargs, not via chain result
    workflow_tasks = detection_tasks + [
        merge_and_blur_detections.si(media_id=media_id, model_ids=model_ids_for_merge, **kwargs)
    ]

    workflow = chain(*workflow_tasks)

    logger.info(f"[Parallel] Launching {len(detection_tasks)} detection tasks SEQUENTIALLY for media {media_id}")
    logger.info(f"[Parallel] Models: {model_ids_for_merge}")

    return workflow.apply_async()


def store_detection_results(media_id: int, model_id: str, results: dict):
    """
    Store detection results in cache.

    Serializes numpy arrays and stores results in Redis cache for
    later retrieval by the merge task.

    Args:
        media_id: Media ID
        model_id: Model identifier
        results: Detection results dict
    """
    key = get_cache_key(media_id, model_id)

    # Debug: Count masks before serialization
    mask_count = 0
    for frame_dets in results.get('frame_detections', {}).values():
        for det in frame_dets:
            if det.get('mask') is not None:
                mask_count += 1

    serialized = _serialize_detections(results)

    # Debug: Count masks after serialization
    serialized_mask_count = 0
    for frame_dets in serialized.get('frame_detections', {}).values():
        for det in frame_dets:
            if det.get('has_mask'):
                serialized_mask_count += 1

    logger.info(f"[Cache] Storing {model_id}: {mask_count} masks before, {serialized_mask_count} after serialization")

    cache.set(key, json.dumps(serialized), timeout=DETECTION_CACHE_TIMEOUT)
    logger.debug(f"[Parallel] Stored detection results: {key}")


def load_detection_results(media_id: int, model_id: str) -> dict:
    """
    Load detection results from cache.

    Args:
        media_id: Media ID
        model_id: Model identifier

    Returns:
        Detection results dict or empty dict if not found
    """
    key = get_cache_key(media_id, model_id)
    data = cache.get(key)
    if data:
        result = _deserialize_detections(json.loads(data))

        # Debug: Count masks after deserialization
        mask_count = 0
        total_count = 0
        for frame_dets in result.get('frame_detections', {}).values():
            for det in frame_dets:
                total_count += 1
                if det.get('mask') is not None:
                    mask_count += 1

        logger.info(f"[Cache] Loaded {model_id}: {total_count} detections, {mask_count} with masks")
        return result

    logger.warning(f"[Parallel] Detection results not found: {key}")
    return {}


def merge_all_detections(media_id: int, model_ids: list) -> dict:
    """
    Merge detection results from all models.

    Combines detections from multiple models into a single result structure.
    Detections are merged per-frame, with source model tracked.

    Note: Currently keeps all detections without deduplication. Overlapping
    detections from different models will both be blurred (which is fine).
    Future enhancement could add IoU-based deduplication if needed.

    Args:
        media_id: Media ID
        model_ids: List of model identifiers to merge

    Returns:
        Merged detection result dict
    """
    merged = {
        'media_id': media_id,
        'models_used': model_ids,
        'frame_detections': {},
        'total_frames': 0,
    }

    for model_id in model_ids:
        results = load_detection_results(media_id, model_id)
        if not results:
            logger.warning(f"[Parallel] No results found for model: {model_id}")
            continue

        merged['total_frames'] = max(
            merged['total_frames'],
            results.get('total_frames', 0)
        )

        for frame_idx, detections in results.get('frame_detections', {}).items():
            # Convert string keys to int if needed
            frame_key = int(frame_idx) if isinstance(frame_idx, str) else frame_idx

            if frame_key not in merged['frame_detections']:
                merged['frame_detections'][frame_key] = []

            for det in detections:
                det['source_model'] = model_id
                merged['frame_detections'][frame_key].append(det)

    total_dets = sum(len(dets) for dets in merged['frame_detections'].values())
    logger.info(f"[Parallel] Merged {total_dets} detections from {len(model_ids)} models")

    return merged


def cleanup_detection_cache(media_id: int, model_ids: list):
    """
    Clean up cached detection results after processing.

    Args:
        media_id: Media ID
        model_ids: List of model identifiers to clean up
    """
    for model_id in model_ids:
        key = get_cache_key(media_id, model_id)
        cache.delete(key)
    logger.debug(f"[Parallel] Cleaned up cache for media {media_id}")


def _serialize_detections(results: dict) -> dict:
    """
    Serialize numpy arrays to JSON-compatible format.

    Masks are compressed using base64 encoding to reduce cache storage.

    Args:
        results: Detection results with potential numpy arrays

    Returns:
        JSON-serializable dict
    """
    serialized = results.copy()

    if 'frame_detections' in serialized:
        new_frame_dets = {}
        for frame_idx, dets in serialized['frame_detections'].items():
            new_dets = []
            for det in dets:
                new_det = det.copy()

                # Serialize mask
                if 'mask' in new_det and new_det['mask'] is not None:
                    if isinstance(new_det['mask'], np.ndarray):
                        # Store mask shape and compressed data
                        mask = new_det['mask']
                        new_det['mask_shape'] = mask.shape
                        new_det['mask_dtype'] = str(mask.dtype)
                        # Compress with base64
                        new_det['mask'] = base64.b64encode(mask.tobytes()).decode('ascii')
                        new_det['has_mask'] = True
                    else:
                        new_det['has_mask'] = False
                else:
                    new_det['has_mask'] = False
                    new_det['mask'] = None

                # Serialize bbox if numpy
                if 'bbox' in new_det and isinstance(new_det['bbox'], np.ndarray):
                    new_det['bbox'] = new_det['bbox'].tolist()

                new_dets.append(new_det)
            new_frame_dets[str(frame_idx)] = new_dets
        serialized['frame_detections'] = new_frame_dets

    return serialized


def _deserialize_detections(data: dict) -> dict:
    """
    Deserialize JSON data back to detection format.

    Reconstructs numpy arrays from base64-encoded mask data.

    Args:
        data: JSON-deserialized dict

    Returns:
        Detection results with numpy arrays restored
    """
    if 'frame_detections' in data:
        new_frame_dets = {}
        for frame_idx, dets in data['frame_detections'].items():
            new_dets = []
            for det in dets:
                new_det = det.copy()

                # Deserialize mask
                if det.get('has_mask') and det.get('mask'):
                    try:
                        mask_bytes = base64.b64decode(det['mask'])
                        dtype = np.dtype(det.get('mask_dtype', 'uint8'))
                        shape = tuple(det['mask_shape'])
                        new_det['mask'] = np.frombuffer(mask_bytes, dtype=dtype).reshape(shape)
                    except Exception as e:
                        logger.warning(f"Failed to deserialize mask: {e}")
                        new_det['mask'] = None
                else:
                    new_det['mask'] = None

                # Clean up serialization metadata
                new_det.pop('has_mask', None)
                new_det.pop('mask_shape', None)
                new_det.pop('mask_dtype', None)

                new_dets.append(new_det)
            new_frame_dets[int(frame_idx)] = new_dets
        data['frame_detections'] = new_frame_dets

    return data
