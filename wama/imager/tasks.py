"""
WAMA Imager - Celery Tasks
Image generation using imaginAIry
"""

from celery import shared_task
from django.utils import timezone
from django.conf import settings
import os
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def generate_image_task(self, generation_id):
    """
    Celery task to generate images using imaginAIry
    """
    from .models import ImageGeneration

    try:
        generation = ImageGeneration.objects.get(id=generation_id)
        generation.status = 'RUNNING'
        generation.progress = 0
        generation.save()

        logger.info(f"Starting image generation #{generation_id}")

        # Import imaginAIry
        try:
            from imaginairy import imagine, ImaginePrompt, imagine_image_files
            from imaginairy.schema import ImagineResult
        except ImportError as e:
            error_msg = "imaginAIry library not installed. Install with: pip install imaginairy"
            logger.error(error_msg)
            generation.status = 'FAILURE'
            generation.error_message = error_msg
            generation.save()
            return {'error': error_msg}

        # Create output directory
        output_dir = os.path.join(settings.MEDIA_ROOT, 'imager', 'outputs', str(generation.user.id))
        os.makedirs(output_dir, exist_ok=True)

        # Prepare prompt for imaginAIry
        prompt_text = generation.prompt
        if generation.negative_prompt:
            prompt_text += f" [negative:{generation.negative_prompt}]"

        generation.progress = 10
        generation.save()

        # Create ImaginePrompt
        imagine_prompt = ImaginePrompt(
            prompt=prompt_text,
            model=generation.model,
            width=generation.width,
            height=generation.height,
            steps=generation.steps,
            guidance_scale=generation.guidance_scale,
            seed=generation.seed,
            upscale=generation.upscale,
        )

        generation.progress = 20
        generation.save()

        logger.info(f"Generating {generation.num_images} image(s) with model {generation.model}")

        # Generate images
        generated_paths = []

        for i in range(generation.num_images):
            try:
                # Update progress
                progress = 20 + int((i / generation.num_images) * 70)
                generation.progress = progress
                generation.save()

                # Generate image
                results = list(imagine([imagine_prompt]))

                if results and len(results) > 0:
                    result = results[0]

                    # Save image
                    filename = f"gen_{generation.id}_{i+1}.png"
                    output_path = os.path.join(output_dir, filename)

                    result.img.save(output_path)
                    generated_paths.append(output_path)

                    logger.info(f"Saved image {i+1}/{generation.num_images}: {output_path}")
                else:
                    logger.warning(f"No result returned for image {i+1}/{generation.num_images}")

            except Exception as img_error:
                logger.error(f"Error generating image {i+1}/{generation.num_images}: {str(img_error)}")
                if i == 0:
                    # If first image fails, mark as failure
                    raise img_error
                # Otherwise continue with other images

        generation.progress = 90
        generation.save()

        # Update generation with results
        generation.generated_images = generated_paths
        generation.status = 'SUCCESS'
        generation.progress = 100
        generation.completed_at = timezone.now()
        generation.save()

        logger.info(f"Successfully generated {len(generated_paths)} image(s) for generation #{generation_id}")

        return {
            'success': True,
            'generation_id': generation_id,
            'images': generated_paths
        }

    except Exception as e:
        logger.error(f"Error in generate_image_task for generation #{generation_id}: {str(e)}")

        try:
            generation = ImageGeneration.objects.get(id=generation_id)
            generation.status = 'FAILURE'
            generation.error_message = str(e)
            generation.completed_at = timezone.now()
            generation.save()
        except Exception as save_error:
            logger.error(f"Failed to save error state: {str(save_error)}")

        return {'error': str(e)}
