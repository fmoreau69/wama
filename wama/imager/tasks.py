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
        output_dir = os.path.join(settings.MEDIA_ROOT, 'imager', 'outputs', str(generation.user.id))
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
        push_console_line(user_id, f"[Imager] Generating {generation.num_images} image(s) on {backend.device}...")

        # Create generation parameters
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
        generated_paths = []
        for i, img in enumerate(result.images):
            try:
                filename = f"gen_{generation.id}_{i+1}.png"
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
