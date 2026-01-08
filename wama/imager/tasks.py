"""
WAMA Imager - Celery Tasks

Image generation using pluggable backends.
Supports Diffusers (Python 3.12+) and ImaginAiry (legacy) with automatic fallback.
"""

from celery import shared_task
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
import os
import logging

from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def generate_image_task(self, generation_id):
    """
    Celery task to generate images using the available backend.

    Automatically selects the best available backend:
    1. Diffusers (recommended for Python 3.12+)
    2. ImaginAiry (legacy fallback)
    """
    from .models import ImageGeneration

    try:
        generation = ImageGeneration.objects.get(id=generation_id)
        generation.status = 'RUNNING'
        generation.progress = 0
        generation.save()

        user_id = generation.user.id
        push_console_line(user_id, f"[Imager] Starting generation #{generation_id}: {generation.prompt[:50]}...")
        logger.info(f"Starting image generation #{generation_id}")

        # Import backend system
        try:
            from .backends import get_backend, get_available_backends
            from .backends.base import GenerationParams
        except ImportError as e:
            error_msg = f"Backend system not available: {e}"
            logger.error(error_msg)
            generation.status = 'FAILURE'
            generation.error_message = error_msg
            generation.save()
            return {'error': error_msg}

        # Check available backends
        available = get_available_backends()
        push_console_line(user_id, f"[Imager] Available backends: {available}")
        logger.info(f"Available backends: {available}")

        # Get the best available backend
        backend = get_backend()
        if backend is None:
            error_msg = "No image generation backend available. Install 'diffusers' or 'imaginairy'."
            logger.error(error_msg)
            generation.status = 'FAILURE'
            generation.error_message = error_msg
            generation.save()
            push_console_line(user_id, f"[Imager] Error: {error_msg}")
            return {'error': error_msg}

        push_console_line(user_id, f"[Imager] Using backend: {backend.display_name}")
        logger.info(f"Using backend: {backend.name} ({backend.display_name})")

        # Create output directory
        output_dir = os.path.join(settings.MEDIA_ROOT, 'imager', 'output', 'image', str(generation.user.id))
        os.makedirs(output_dir, exist_ok=True)

        generation.progress = 10
        generation.save()
        cache.set(f"imager_progress_{generation_id}", 10, timeout=3600)
        push_console_line(user_id, f"[Imager] Loading model: {generation.model}")

        # Load the model
        if not backend.load(generation.model):
            error_msg = f"Failed to load model: {generation.model}"
            logger.error(error_msg)
            generation.status = 'FAILURE'
            generation.error_message = error_msg
            generation.save()
            push_console_line(user_id, f"[Imager] Error: {error_msg}")
            return {'error': error_msg}

        generation.progress = 20
        generation.save()
        cache.set(f"imager_progress_{generation_id}", 20, timeout=3600)

        # Log generation mode
        mode_desc = generation.generation_mode or 'txt2img'
        if mode_desc in ('img2img', 'style2img') and generation.reference_image:
            push_console_line(user_id, f"[Imager] {mode_desc}: Generating {generation.num_images} image(s) on {backend.device} (strength={generation.image_strength:.0%})...")
        else:
            push_console_line(user_id, f"[Imager] Generating {generation.num_images} image(s) on {backend.device}...")

        # Get reference image path if applicable
        reference_image_path = None
        if generation.reference_image:
            reference_image_path = generation.reference_image.path
            push_console_line(user_id, f"[Imager] Using reference image: {os.path.basename(reference_image_path)}")

        # Create generation parameters with multi-modal support
        params = GenerationParams(
            prompt=generation.prompt,
            negative_prompt=generation.negative_prompt,
            model=generation.model,
            width=generation.width,
            height=generation.height,
            steps=generation.steps,
            guidance_scale=generation.guidance_scale,
            seed=generation.seed,
            num_images=generation.num_images,
            upscale=generation.upscale,
            # Multi-modal parameters
            generation_mode=generation.generation_mode or 'txt2img',
            reference_image=reference_image_path,
            image_strength=generation.image_strength,
        )

        # Progress callback
        def progress_callback(progress: int):
            # Map 0-100 progress to 20-90 range
            mapped_progress = 20 + int(progress * 0.7)
            generation.progress = mapped_progress
            generation.save(update_fields=['progress'])
            cache.set(f"imager_progress_{generation_id}", mapped_progress, timeout=3600)

        # Generate images
        logger.info(f"Generating {generation.num_images} image(s) with model {generation.model}")
        result = backend.generate(params, progress_callback)

        if not result.success:
            error_msg = result.error or "Unknown generation error"
            logger.error(f"Generation failed: {error_msg}")
            generation.status = 'FAILURE'
            generation.error_message = error_msg
            generation.save()
            push_console_line(user_id, f"[Imager] Error: {error_msg}")
            return {'error': error_msg}

        generation.progress = 90
        generation.save()
        cache.set(f"imager_progress_{generation_id}", 90, timeout=3600)
        push_console_line(user_id, f"[Imager] Saving {len(result.images)} image(s)...")

        # Save generated images
        # Include model name in filename for easy identification
        model_short = generation.model.replace('-', '_').replace('/', '_')  # Clean model name
        generated_paths = []
        for i, img in enumerate(result.images):
            try:
                filename = f"gen_{generation.id}_{i+1}_{model_short}.png"
                output_path = os.path.join(output_dir, filename)
                img.save(output_path)
                generated_paths.append(output_path)
                logger.info(f"Saved image {i+1}/{len(result.images)}: {output_path}")
            except Exception as save_error:
                logger.error(f"Error saving image {i+1}: {save_error}")

        if not generated_paths:
            error_msg = "Failed to save any generated images"
            logger.error(error_msg)
            generation.status = 'FAILURE'
            generation.error_message = error_msg
            generation.save()
            push_console_line(user_id, f"[Imager] Error: {error_msg}")
            return {'error': error_msg}

        # Update generation with results
        try:
            generation.refresh_from_db()
            generation.generated_images = generated_paths
            generation.status = 'SUCCESS'
            generation.progress = 100
            generation.completed_at = timezone.now()

            # Store seed if available
            if result.seed_used is not None and generation.seed is None:
                # Store the used seed for reproducibility
                pass  # Could add a field to store this

            generation.save()
            cache.set(f"imager_progress_{generation_id}", 100, timeout=3600)
            push_console_line(
                user_id,
                f"[Imager] ✓ Generated {len(generated_paths)} image(s) for #{generation_id} "
                f"(seed: {result.seed_used})"
            )
        except ImageGeneration.DoesNotExist:
            logger.warning(f"Generation {generation_id} was deleted during processing")
            return {'error': 'Generation was deleted during processing'}

        logger.info(f"Successfully generated {len(generated_paths)} image(s) for generation #{generation_id}")

        return {
            'success': True,
            'generation_id': generation_id,
            'images': generated_paths,
            'seed': result.seed_used,
            'backend': backend.name
        }

    except Exception as e:
        logger.error(f"Error in generate_image_task for generation #{generation_id}: {str(e)}")

        try:
            generation = ImageGeneration.objects.get(id=generation_id)
            user_id = generation.user.id
            generation.status = 'FAILURE'
            generation.error_message = str(e)
            generation.completed_at = timezone.now()
            generation.save()
            cache.set(f"imager_progress_{generation_id}", 0, timeout=3600)
            push_console_line(user_id, f"[Imager] ✗ Generation #{generation_id} failed: {str(e)}")
        except Exception as save_error:
            logger.error(f"Failed to save error state: {str(save_error)}")

        return {'error': str(e)}


@shared_task(bind=True)
def generate_video_task(self, generation_id):
    """
    Celery task to generate videos using Wan 2.1/2.2.

    Supports:
    - txt2vid: Text-to-Video generation
    - img2vid: Image-to-Video generation
    """
    import time
    import traceback
    from .models import ImageGeneration

    task_start_time = time.time()

    try:
        generation = ImageGeneration.objects.get(id=generation_id)
        generation.status = 'RUNNING'
        generation.progress = 0
        generation.save()

        user_id = generation.user.id
        mode_label = "Text-to-Video" if generation.generation_mode == 'txt2vid' else "Image-to-Video"

        push_console_line(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        push_console_line(user_id, f"[Imager Video] Starting {mode_label} generation #{generation_id}")
        push_console_line(user_id, f"[Imager Video] Model: {generation.model}")
        push_console_line(user_id, f"[Imager Video] Prompt: {generation.prompt[:80]}{'...' if len(generation.prompt) > 80 else ''}")
        logger.info(f"Starting video generation #{generation_id} ({mode_label})")

        # Detect which backend to use based on model name
        model_name = generation.model
        is_hunyuan_model = model_name.startswith('hunyuan-')

        if is_hunyuan_model:
            # Use HunyuanVideo backend
            push_console_line(user_id, f"[Imager Video] Importing HunyuanVideo backend...")
            try:
                from .backends.hunyuan_video_backend import HunyuanVideoBackend, HunyuanVideoParams
                backend_class = HunyuanVideoBackend
                params_class = HunyuanVideoParams
                push_console_line(user_id, f"[Imager Video] ✓ HunyuanVideo backend imported")
            except ImportError as e:
                error_msg = f"HunyuanVideo backend not available: {e}"
                logger.error(error_msg)
                logger.error(traceback.format_exc())
                generation.status = 'FAILURE'
                generation.error_message = error_msg
                generation.save()
                push_console_line(user_id, f"[Imager Video] ✗ Error: {error_msg}")
                return {'error': error_msg}

            # Check availability
            push_console_line(user_id, f"[Imager Video] Checking HunyuanVideo availability...")
            if not HunyuanVideoBackend.is_available():
                error_msg = "HunyuanVideo backend not available. Need CUDA with 14GB+ VRAM."
                logger.error(error_msg)
                generation.status = 'FAILURE'
                generation.error_message = error_msg
                generation.save()
                push_console_line(user_id, f"[Imager Video] ✗ Error: {error_msg}")
                return {'error': error_msg}
            push_console_line(user_id, f"[Imager Video] ✓ HunyuanVideo backend available")
        else:
            # Use Wan video backend
            push_console_line(user_id, f"[Imager Video] Importing Wan backend...")
            try:
                from .backends.wan_video_backend import WanVideoBackend, VideoGenerationParams
                backend_class = WanVideoBackend
                params_class = VideoGenerationParams
                push_console_line(user_id, f"[Imager Video] ✓ Wan backend imported")
            except ImportError as e:
                error_msg = f"Wan video backend not available: {e}"
                logger.error(error_msg)
                logger.error(traceback.format_exc())
                generation.status = 'FAILURE'
                generation.error_message = error_msg
                generation.save()
                push_console_line(user_id, f"[Imager Video] ✗ Error: {error_msg}")
                return {'error': error_msg}

            # Check if Wan is available
            push_console_line(user_id, f"[Imager Video] Checking Wan availability (torch, diffusers)...")
            if not WanVideoBackend.is_available():
                error_msg = "Wan video backend not available. Please install diffusers with Wan support."
                logger.error(error_msg)
                generation.status = 'FAILURE'
                generation.error_message = error_msg
                generation.save()
                push_console_line(user_id, f"[Imager Video] ✗ Error: {error_msg}")
                push_console_line(user_id, f"[Imager Video] Install with: pip install diffusers transformers accelerate")
                return {'error': error_msg}
            push_console_line(user_id, f"[Imager Video] ✓ Wan backend available")

        # Create output directory
        output_dir = os.path.join(settings.MEDIA_ROOT, 'imager', 'output', 'video', str(generation.user.id))
        os.makedirs(output_dir, exist_ok=True)
        push_console_line(user_id, f"[Imager Video] Output dir: {output_dir}")

        generation.progress = 5
        generation.save()
        cache.set(f"imager_progress_{generation_id}", 5, timeout=7200)  # 2 hour timeout for videos

        # Initialize backend
        backend = backend_class()
        push_console_line(user_id, f"[Imager Video] Loading model: {generation.model}")
        push_console_line(user_id, f"[Imager Video] ⏳ This may take several minutes on first run (downloading ~5-10GB)...")

        model_load_start = time.time()

        # Load the model
        if not backend.load(generation.model):
            error_msg = f"Failed to load video model: {generation.model}"
            logger.error(error_msg)
            generation.status = 'FAILURE'
            generation.error_message = error_msg
            generation.save()
            push_console_line(user_id, f"[Imager Video] ✗ Error: {error_msg}")
            return {'error': error_msg}

        model_load_time = time.time() - model_load_start
        push_console_line(user_id, f"[Imager Video] ✓ Model loaded in {model_load_time:.1f}s")

        generation.progress = 20
        generation.save()
        cache.set(f"imager_progress_{generation_id}", 20, timeout=7200)

        # Get resolution from generation
        width, height = generation.get_video_resolution()

        # Calculate frames
        num_frames = generation.calculate_video_frames()
        estimated_duration = num_frames / generation.video_fps

        push_console_line(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        push_console_line(user_id, f"[Imager Video] Parameters:")
        push_console_line(user_id, f"[Imager Video]   Resolution: {width}x{height}")
        push_console_line(user_id, f"[Imager Video]   Frames: {num_frames} ({estimated_duration:.1f}s @ {generation.video_fps}fps)")
        push_console_line(user_id, f"[Imager Video]   Steps: {generation.steps}")
        push_console_line(user_id, f"[Imager Video]   Guidance: {generation.guidance_scale}")
        push_console_line(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Get reference image path if applicable
        reference_image_path = None
        if generation.reference_image and generation.generation_mode == 'img2vid':
            reference_image_path = generation.reference_image.path
            push_console_line(user_id, f"[Imager Video] Reference image: {os.path.basename(reference_image_path)}")

        # Create video generation parameters (different structure per backend)
        if is_hunyuan_model:
            params = params_class(
                prompt=generation.prompt,
                negative_prompt=generation.negative_prompt,
                model=generation.model,
                width=width,
                height=height,
                num_frames=num_frames,
                num_inference_steps=generation.steps,
                guidance_scale=generation.guidance_scale,
                seed=generation.seed,
                fps=generation.video_fps,
                reference_image=reference_image_path,
            )
        else:
            params = params_class(
                prompt=generation.prompt,
                negative_prompt=generation.negative_prompt,
                model=generation.model,
                width=width,
                height=height,
                num_frames=num_frames,
                fps=generation.video_fps,
                guidance_scale=generation.guidance_scale,
                num_inference_steps=generation.steps,
                seed=generation.seed,
                generation_mode=generation.generation_mode,
                reference_image=reference_image_path,
            )

        last_progress_log = 0

        # Progress callback with console updates
        def progress_callback(progress: int):
            nonlocal last_progress_log
            # Map 0-100 progress to 20-85 range (save 15% for export)
            mapped_progress = 20 + int(progress * 0.65)
            generation.progress = mapped_progress
            generation.save(update_fields=['progress'])
            cache.set(f"imager_progress_{generation_id}", mapped_progress, timeout=7200)

            # Log every 10%
            if progress >= last_progress_log + 10:
                elapsed = time.time() - generation_start
                push_console_line(user_id, f"[Imager Video] Generation: {progress}% (elapsed: {elapsed:.0f}s)")
                last_progress_log = progress

        # Generate video
        push_console_line(user_id, f"[Imager Video] ⏳ Starting video generation... This may take 5-30 minutes.")
        logger.info(f"Generating video with {num_frames} frames at {width}x{height}")

        generation_start = time.time()

        # Call the appropriate generation method based on backend
        if is_hunyuan_model:
            result = backend.generate(params, progress_callback)
            video_frames = result.video_frames
            seed_used = result.seed_used
        else:
            result = backend.generate_video(params, progress_callback)
            video_frames = result.video_frames
            seed_used = result.seed_used

        generation_time = time.time() - generation_start

        if not result.success:
            error_msg = result.error or "Unknown video generation error"
            logger.error(f"Video generation failed: {error_msg}")
            generation.status = 'FAILURE'
            generation.error_message = error_msg
            generation.save()
            push_console_line(user_id, f"[Imager Video] ✗ Generation failed: {error_msg}")
            return {'error': error_msg}

        push_console_line(user_id, f"[Imager Video] ✓ Generation complete in {generation_time:.1f}s")
        push_console_line(user_id, f"[Imager Video] Seed used: {seed_used}")

        generation.progress = 85
        generation.save()
        cache.set(f"imager_progress_{generation_id}", 85, timeout=7200)
        push_console_line(user_id, f"[Imager Video] Exporting {len(video_frames)} frames to MP4...")

        # Export video to MP4
        # Include model name in filename for easy identification
        model_short = generation.model.replace('-', '_')  # e.g., wan_t2v_1.3b
        video_filename = f"video_{generation.id}_{model_short}.mp4"
        video_path = os.path.join(output_dir, video_filename)

        export_start = time.time()
        if not backend.export_video(video_frames, video_path, fps=generation.video_fps):
            error_msg = "Failed to export video to MP4"
            logger.error(error_msg)
            generation.status = 'FAILURE'
            generation.error_message = error_msg
            generation.save()
            push_console_line(user_id, f"[Imager Video] ✗ Export failed: {error_msg}")
            return {'error': error_msg}

        export_time = time.time() - export_start
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024) if os.path.exists(video_path) else 0
        push_console_line(user_id, f"[Imager Video] ✓ Exported in {export_time:.1f}s ({file_size_mb:.1f} MB)")

        # Update generation with results
        try:
            generation.refresh_from_db()

            # Save video path relative to MEDIA_ROOT for FileField
            relative_video_path = os.path.relpath(video_path, settings.MEDIA_ROOT)
            generation.output_video.name = relative_video_path

            generation.status = 'SUCCESS'
            generation.progress = 100
            generation.completed_at = timezone.now()
            generation.save()

            cache.set(f"imager_progress_{generation_id}", 100, timeout=7200)

            total_time = time.time() - task_start_time
            push_console_line(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            push_console_line(user_id, f"[Imager Video] ✓ SUCCESS! Generation #{generation_id}")
            push_console_line(user_id, f"[Imager Video]   Duration: {generation.video_duration}s")
            push_console_line(user_id, f"[Imager Video]   Seed: {seed_used}")
            push_console_line(user_id, f"[Imager Video]   Total time: {total_time:.1f}s")
            push_console_line(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        except ImageGeneration.DoesNotExist:
            logger.warning(f"Generation {generation_id} was deleted during processing")
            return {'error': 'Generation was deleted during processing'}

        logger.info(f"Successfully generated video for generation #{generation_id}")

        return {
            'success': True,
            'generation_id': generation_id,
            'video_path': video_path,
            'seed': seed_used,
        }

    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(f"Error in generate_video_task for generation #{generation_id}: {str(e)}")
        logger.error(f"Traceback:\n{error_traceback}")

        try:
            generation = ImageGeneration.objects.get(id=generation_id)
            user_id = generation.user.id
            generation.status = 'FAILURE'
            generation.error_message = str(e)
            generation.completed_at = timezone.now()
            generation.save()
            cache.set(f"imager_progress_{generation_id}", 0, timeout=7200)
            push_console_line(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            push_console_line(user_id, f"[Imager Video] ✗ FAILED! Generation #{generation_id}")
            push_console_line(user_id, f"[Imager Video] Error: {str(e)}")
            push_console_line(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        except Exception as save_error:
            logger.error(f"Failed to save error state: {str(save_error)}")

        return {'error': str(e)}
