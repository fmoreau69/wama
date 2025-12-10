"""
Celery tasks for Enhancer app.
"""

import os
import time
import logging
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections

from .models import Enhancement
from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)


def _set_progress(enhancement_id: int, percent: int) -> None:
    """Set enhancement progress in cache and database."""
    try:
        pct = max(0, min(100, int(percent)))
        cache.set(f"enhancer_progress_{enhancement_id}", pct, timeout=3600)
        Enhancement.objects.filter(pk=enhancement_id).update(progress=pct)
    except Exception:
        pass


def _console(user_id: int, message: str) -> None:
    """Push console message to user."""
    try:
        push_console_line(user_id, f"[Enhancer] {message}")
    except Exception:
        pass


@shared_task(bind=True)
def enhance_media(self, enhancement_id: int):
    """
    Celery task to enhance image or video.

    Args:
        enhancement_id: ID of the Enhancement object
    """
    logger.info(f"========================================")
    logger.info(f"WORKER: enhance_media START")
    logger.info(f"Enhancement ID: {enhancement_id}")
    logger.info(f"Task ID: {self.request.id}")
    logger.info(f"========================================")

    close_old_connections()

    try:
        enhancement = Enhancement.objects.get(pk=enhancement_id)
        logger.info(f"Enhancement loaded: {enhancement.id}")
        logger.info(f"  - User: {enhancement.user.username} (ID: {enhancement.user_id})")
        logger.info(f"  - Media type: {enhancement.media_type}")
        logger.info(f"  - AI model: {enhancement.ai_model}")
        logger.info(f"  - Input file: {enhancement.input_file.path if enhancement.input_file else 'None'}")
        logger.info(f"  - Denoise: {enhancement.denoise}")
        logger.info(f"  - Blend factor: {enhancement.blend_factor}")
    except Enhancement.DoesNotExist:
        logger.error(f"Enhancement {enhancement_id} not found in database!")
        return {'ok': False, 'error': 'Enhancement not found'}

    user_id = enhancement.user_id
    logger.info(f"Sending console message to user {user_id}")
    _console(user_id, f"Starting enhancement #{enhancement_id}")
    _set_progress(enhancement_id, 5)
    logger.info("Progress set to 5%")

    start_time = time.time()

    try:
        logger.info(f"Determining processing path for media_type: {enhancement.media_type}")

        if enhancement.media_type == 'image':
            logger.info("Calling _enhance_image()")
            result = _enhance_image(enhancement, user_id)
        elif enhancement.media_type == 'video':
            logger.info("Calling _enhance_video()")
            result = _enhance_video(enhancement, user_id)
        else:
            logger.error(f"Unsupported media type: {enhancement.media_type}")
            raise ValueError(f"Unsupported media type: {enhancement.media_type}")

        logger.info(f"Enhancement processing result: {result}")

        if result['ok']:
            processing_time = time.time() - start_time
            logger.info(f"Enhancement SUCCESS in {processing_time:.2f}s")
            enhancement.status = 'SUCCESS'
            enhancement.processing_time = processing_time
            enhancement.save(update_fields=['status', 'processing_time'])
            _set_progress(enhancement_id, 100)
            _console(user_id, f"Enhancement #{enhancement_id} completed ✓")
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Enhancement processing returned error: {error_msg}")
            raise Exception(error_msg)

        logger.info(f"========================================")
        logger.info(f"WORKER: enhance_media END (SUCCESS)")
        logger.info(f"========================================")
        return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"========================================")
        logger.error(f"WORKER: enhance_media END (FAILURE)")
        logger.error(f"Error: {error_msg}")
        logger.error(f"========================================", exc_info=True)

        enhancement.status = 'FAILURE'
        enhancement.error_message = error_msg
        enhancement.save(update_fields=['status', 'error_message'])
        _set_progress(enhancement_id, 0)
        _console(user_id, f"Enhancement #{enhancement_id} failed: {error_msg}")
        return {'ok': False, 'error': error_msg}


def _enhance_image(enhancement: Enhancement, user_id: int) -> dict:
    """
    Enhance a single image.

    Args:
        enhancement: Enhancement object
        user_id: User ID for console messages

    Returns:
        Result dictionary
    """
    logger.info("--- _enhance_image START ---")

    from .utils.ai_upscaler import upscale_image_file
    import os
    from django.core.files.base import ContentFile

    input_filename = enhancement.get_input_filename()
    logger.info(f"Image filename: {input_filename}")

    _console(user_id, f"Processing image: {input_filename}")
    _set_progress(enhancement.id, 10)
    logger.info("Console message sent, progress set to 10%")

    input_path = enhancement.input_file.path
    logger.info(f"Input file path: {input_path}")
    logger.info(f"Input file exists: {os.path.exists(input_path)}")

    base_name, ext = os.path.splitext(os.path.basename(input_path))
    output_filename = f"{base_name}_enhanced{ext}"
    logger.info(f"Output filename will be: {output_filename}")

    # Create temporary output path
    output_dir = os.path.dirname(input_path).replace('input', 'output')
    logger.info(f"Creating output directory: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)
    logger.info(f"Output path: {output_path}")

    try:
        # Progress callback
        def progress_cb(pct):
            # Map 0-100 to 10-90
            mapped = 10 + int(pct * 0.8)
            _set_progress(enhancement.id, mapped)

        # Upscale image
        logger.info(f"Starting upscale with model: {enhancement.ai_model}")
        logger.info(f"  - Denoise: {enhancement.denoise}")
        logger.info(f"  - Blend factor: {enhancement.blend_factor}")

        width, height = upscale_image_file(
            input_path=input_path,
            output_path=output_path,
            model_name=enhancement.ai_model,
            denoise=enhancement.denoise,
            blend_factor=enhancement.blend_factor,
            progress_callback=progress_cb,
        )

        logger.info(f"Upscaling completed: {width}x{height}")

        # Save output file to model
        logger.info("Saving output file to database...")
        with open(output_path, 'rb') as f:
            enhancement.output_file.save(output_filename, ContentFile(f.read()), save=False)

        # Update dimensions
        file_size = os.path.getsize(output_path)
        logger.info(f"Output file size: {file_size} bytes")

        enhancement.output_width = width
        enhancement.output_height = height
        enhancement.output_file_size = file_size
        enhancement.save(update_fields=['output_file', 'output_width', 'output_height', 'output_file_size'])
        logger.info("Database updated with output file info")

        _set_progress(enhancement.id, 95)

        # Clean up temp file
        try:
            os.remove(output_path)
            logger.info(f"Temporary file removed: {output_path}")
        except Exception as cleanup_err:
            logger.warning(f"Could not remove temp file: {cleanup_err}")

        logger.info("--- _enhance_image END (SUCCESS) ---")
        return {'ok': True, 'output_width': width, 'output_height': height}

    except Exception as e:
        logger.error(f"--- _enhance_image END (FAILURE) ---")
        logger.error(f"Error during image enhancement: {e}", exc_info=True)

        # Clean up on error
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass
        raise


def _enhance_video(enhancement: Enhancement, user_id: int) -> dict:
    """
    Enhance a video (frame by frame).

    Args:
        enhancement: Enhancement object
        user_id: User ID for console messages

    Returns:
        Result dictionary
    """
    import subprocess
    import tempfile
    import shutil
    from .utils.ai_upscaler import AIUpscaler
    import cv2
    from django.core.files.base import ContentFile

    _console(user_id, f"Processing video: {enhancement.get_input_filename()}")
    _set_progress(enhancement.id, 5)

    input_path = enhancement.input_file.path
    base_name, ext = os.path.splitext(os.path.basename(input_path))
    output_filename = f"{base_name}_enhanced{ext}"

    # Create temporary directories
    temp_dir = tempfile.mkdtemp(prefix='enhancer_')
    frames_dir = os.path.join(temp_dir, 'frames')
    enhanced_dir = os.path.join(temp_dir, 'enhanced')
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(enhanced_dir, exist_ok=True)

    try:
        # Step 1: Extract frames with ffmpeg (10%)
        _console(user_id, "Extracting frames...")
        _set_progress(enhancement.id, 10)

        frame_pattern = os.path.join(frames_dir, 'frame_%05d.png')
        subprocess.run([
            'ffmpeg',
            '-i', input_path,
            '-qscale:v', '1',
            frame_pattern
        ], check=True, capture_output=True)

        # Count frames
        frame_files = sorted([f for f in os.listdir(frames_dir) if f.endswith('.png')])
        total_frames = len(frame_files)
        _console(user_id, f"Extracted {total_frames} frames")

        # Step 2: Upscale frames (10-80%)
        _console(user_id, f"Upscaling frames with {enhancement.ai_model}...")

        upscaler = AIUpscaler(
            model_name=enhancement.ai_model,
            tile_size=enhancement.tile_size if enhancement.tile_size > 0 else 512
        )

        output_width = 0
        output_height = 0

        for i, frame_file in enumerate(frame_files):
            # Update progress
            progress = 10 + int((i / total_frames) * 70)
            _set_progress(enhancement.id, progress)

            # Read frame
            frame_path = os.path.join(frames_dir, frame_file)
            frame = cv2.imread(frame_path)

            # Upscale
            enhanced_frame = upscaler.upscale_image(
                frame,
                blend_factor=enhancement.blend_factor
            )

            # Save enhanced frame
            enhanced_path = os.path.join(enhanced_dir, frame_file)
            cv2.imwrite(enhanced_path, enhanced_frame)

            # Store dimensions from first frame
            if i == 0:
                output_height, output_width = enhanced_frame.shape[:2]

        upscaler.close()
        _console(user_id, f"Upscaled all frames")

        # Step 3: Encode video (80-95%)
        _console(user_id, "Encoding video...")
        _set_progress(enhancement.id, 80)

        output_dir = os.path.dirname(input_path).replace('input', 'output')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        enhanced_pattern = os.path.join(enhanced_dir, 'frame_%05d.png')

        # Get original video FPS
        probe_result = subprocess.run([
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            input_path
        ], capture_output=True, text=True)

        fps = eval(probe_result.stdout.strip()) if probe_result.stdout.strip() else 30

        # Encode video
        subprocess.run([
            'ffmpeg',
            '-framerate', str(fps),
            '-i', enhanced_pattern,
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '18',
            '-pix_fmt', 'yuv420p',
            output_path
        ], check=True, capture_output=True)

        _set_progress(enhancement.id, 95)

        # Save output file to model
        with open(output_path, 'rb') as f:
            enhancement.output_file.save(output_filename, ContentFile(f.read()), save=False)

        # Update dimensions
        enhancement.output_width = output_width
        enhancement.output_height = output_height
        enhancement.output_file_size = os.path.getsize(output_path)
        enhancement.save(update_fields=['output_file', 'output_width', 'output_height', 'output_file_size'])

        _console(user_id, f"Video encoding complete")

        # Clean up
        shutil.rmtree(temp_dir)
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass

        return {'ok': True, 'output_width': output_width, 'output_height': output_height, 'frames': total_frames}

    except Exception as e:
        # Clean up on error
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
