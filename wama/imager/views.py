"""
WAMA Imager - Views
Image generation using imaginAIry
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.utils import timezone
from django.db.models import Q
import os
import json
import logging

from .models import ImageGeneration, UserSettings
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)


def index(request):
    """Main page showing generation queue"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Get user's generations
    generations = ImageGeneration.objects.filter(user=user).order_by('-created_at')

    # Get or create user settings
    user_settings, _ = UserSettings.objects.get_or_create(user=user)

    # Available models
    models_choices = [
        ('openjourney-v4', 'OpenJourney v4'),
        ('dreamlike-art-2', 'Dreamlike Art 2.0'),
        ('sd-2.1', 'Stable Diffusion 2.1'),
        ('sd-1.5', 'Stable Diffusion 1.5'),
    ]

    context = {
        'generations': generations,
        'user_settings': user_settings,
        'models_choices': models_choices,
    }

    return render(request, 'imager/index.html', context)


@require_http_methods(["POST"])
def create_generation(request):
    """Create a new image generation task"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # Get parameters from request
        prompt = request.POST.get('prompt', '').strip()
        if not prompt:
            return JsonResponse({'error': 'Prompt is required'}, status=400)

        negative_prompt = request.POST.get('negative_prompt', '').strip()
        model = request.POST.get('model', 'openjourney-v4')
        width = int(request.POST.get('width', 512))
        height = int(request.POST.get('height', 512))
        steps = int(request.POST.get('steps', 30))
        guidance_scale = float(request.POST.get('guidance_scale', 7.5))
        seed = request.POST.get('seed')
        if seed:
            seed = int(seed)
        else:
            seed = None
        num_images = int(request.POST.get('num_images', 1))
        upscale = request.POST.get('upscale', 'false').lower() == 'true'

        # Create generation object
        generation = ImageGeneration.objects.create(
            user=user,
            prompt=prompt,
            negative_prompt=negative_prompt,
            model=model,
            width=width,
            height=height,
            steps=steps,
            guidance_scale=guidance_scale,
            seed=seed,
            num_images=num_images,
            upscale=upscale,
            status='PENDING'
        )

        logger.info(f"Created generation #{generation.id} for user {user.username}")

        return JsonResponse({
            'success': True,
            'generation_id': generation.id,
            'message': 'Generation created successfully'
        })

    except Exception as e:
        logger.error(f"Error creating generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def start_generation(request, generation_id):
    """Start a specific generation task"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = get_object_or_404(ImageGeneration, id=generation_id, user=user)

        if generation.status == 'RUNNING':
            return JsonResponse({'error': 'Generation already running'}, status=400)

        # Import here to avoid circular imports
        from .tasks import generate_image_task

        # Start Celery task
        task = generate_image_task.delay(generation.id)

        # Update status
        generation.status = 'RUNNING'
        generation.progress = 0
        generation.save()

        logger.info(f"Started generation #{generation.id}, task_id: {task.id}")

        return JsonResponse({
            'success': True,
            'task_id': task.id,
            'message': 'Generation started'
        })

    except Exception as e:
        logger.error(f"Error starting generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def start_all_generations(request):
    """Start all pending generations"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        pending = ImageGeneration.objects.filter(user=user, status='PENDING')

        if not pending.exists():
            return JsonResponse({'error': 'No pending generations'}, status=400)

        from .tasks import generate_image_task

        started_count = 0
        for generation in pending:
            task = generate_image_task.delay(generation.id)
            generation.status = 'RUNNING'
            generation.progress = 0
            generation.save()
            started_count += 1
            logger.info(f"Started generation #{generation.id}, task_id: {task.id}")

        return JsonResponse({
            'success': True,
            'started': started_count,
            'message': f'Started {started_count} generation(s)'
        })

    except Exception as e:
        logger.error(f"Error starting all generations: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def progress(request, generation_id):
    """Get progress for a specific generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = get_object_or_404(ImageGeneration, id=generation_id, user=user)

        # Get progress from cache (more real-time) or fallback to DB
        cached_progress = cache.get(f"imager_progress_{generation_id}")
        progress = cached_progress if cached_progress is not None else generation.progress

        data = {
            'id': generation.id,
            'status': generation.status,
            'progress': progress,
            'error_message': generation.error_message,
            'generated_images': generation.generated_images,
            'duration': generation.duration_display,
        }

        return JsonResponse(data)

    except Exception as e:
        logger.error(f"Error getting progress: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def global_progress(request):
    """Get overall progress for all user generations"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generations = ImageGeneration.objects.filter(user=user)

        if not generations.exists():
            return JsonResponse({
                'total': 0,
                'pending': 0,
                'running': 0,
                'success': 0,
                'failure': 0,
                'overall_progress': 0
            })

        total = generations.count()
        pending = generations.filter(status='PENDING').count()
        running = generations.filter(status='RUNNING').count()
        success = generations.filter(status='SUCCESS').count()
        failure = generations.filter(status='FAILURE').count()

        # Calculate overall progress
        total_progress = sum(g.progress for g in generations)
        overall_progress = int(total_progress / total) if total > 0 else 0

        return JsonResponse({
            'total': total,
            'pending': pending,
            'running': running,
            'success': success,
            'failure': failure,
            'overall_progress': overall_progress
        })

    except Exception as e:
        logger.error(f"Error getting global progress: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def download(request, generation_id):
    """Download generated images as a zip file"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = get_object_or_404(ImageGeneration, id=generation_id, user=user)

        if not generation.generated_images:
            return HttpResponse("No images generated yet", status=404)

        # If single image, return it directly
        if len(generation.generated_images) == 1:
            image_path = generation.generated_images[0]
            if os.path.exists(image_path):
                return FileResponse(open(image_path, 'rb'),
                                  as_attachment=True,
                                  filename=os.path.basename(image_path))

        # Multiple images - create zip
        import zipfile
        from io import BytesIO

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for image_path in generation.generated_images:
                if os.path.exists(image_path):
                    zip_file.write(image_path, os.path.basename(image_path))

        zip_buffer.seek(0)
        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="generation_{generation.id}.zip"'
        return response

    except Exception as e:
        logger.error(f"Error downloading images: {str(e)}")
        return HttpResponse(f"Error: {str(e)}", status=500)


@require_http_methods(["POST"])
def delete_generation(request, generation_id):
    """Delete a specific generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = get_object_or_404(ImageGeneration, id=generation_id, user=user)

        # Delete generated images from filesystem
        for image_path in generation.generated_images:
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception as e:
                    logger.warning(f"Failed to delete image {image_path}: {str(e)}")

        generation.delete()
        logger.info(f"Deleted generation #{generation_id}")

        return JsonResponse({'success': True, 'message': 'Generation deleted'})

    except Exception as e:
        logger.error(f"Error deleting generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def clear_all(request):
    """Clear all generations for the user"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generations = ImageGeneration.objects.filter(user=user)

        # Delete all generated images
        for generation in generations:
            for image_path in generation.generated_images:
                if os.path.exists(image_path):
                    try:
                        os.remove(image_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete image {image_path}: {str(e)}")

        count = generations.count()
        generations.delete()
        logger.info(f"Cleared {count} generations for user {user.username}")

        return JsonResponse({'success': True, 'deleted': count})

    except Exception as e:
        logger.error(f"Error clearing all generations: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def console(request):
    """Console page for monitoring logs"""
    return render(request, 'imager/console.html')


def console_content(request):
    """Return console logs as JSON"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # Get recent generations with their logs
        generations = ImageGeneration.objects.filter(user=user).order_by('-updated_at')[:10]

        logs = []
        for gen in generations:
            status_icon = {
                'PENDING': '⏳',
                'RUNNING': '🔄',
                'SUCCESS': '✅',
                'FAILURE': '❌',
            }.get(gen.status, '❓')

            log_line = f"{status_icon} [Gen #{gen.id}] {gen.status} - {gen.progress}% - {gen.prompt[:50]}..."
            logs.append(log_line)

            if gen.error_message:
                logs.append(f"   ❌ Error: {gen.error_message}")

        return JsonResponse({'output': logs})

    except Exception as e:
        logger.error(f"Error getting console content: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def about(request):
    """About page"""
    return render(request, 'imager/about.html')


def help_page(request):
    """Help page"""
    return render(request, 'imager/help.html')


@require_http_methods(["POST"])
def update_settings(request):
    """Update user settings"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        user_settings, _ = UserSettings.objects.get_or_create(user=user)

        # Update settings from POST data
        if 'default_model' in request.POST:
            user_settings.default_model = request.POST['default_model']
        if 'default_width' in request.POST:
            user_settings.default_width = int(request.POST['default_width'])
        if 'default_height' in request.POST:
            user_settings.default_height = int(request.POST['default_height'])
        if 'default_steps' in request.POST:
            user_settings.default_steps = int(request.POST['default_steps'])
        if 'default_guidance_scale' in request.POST:
            user_settings.default_guidance_scale = float(request.POST['default_guidance_scale'])

        user_settings.save()

        return JsonResponse({'success': True, 'message': 'Settings updated'})

    except Exception as e:
        logger.error(f"Error updating settings: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
