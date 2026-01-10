"""
WAMA Imager - Views
Image generation using Diffusers with multi-modal support:
- txt2img: Text to image (standard)
- file2img: Batch from prompt file (txt/json/yaml)
- describe2img: Auto-prompt from reference image via BLIP
- style2img: Style transfer from reference image
- img2img: Image to image transformation
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.cache import cache
from django.utils import timezone
from django.conf import settings
from django.db.models import Q
import os
import json
import logging
from pathlib import Path

from .models import ImageGeneration, UserSettings
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)


def index(request):
    """Main page showing generation queue"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Get user's generations (exclude batch children from main list)
    generations = ImageGeneration.objects.filter(
        user=user,
        parent_generation__isnull=True  # Only show top-level generations
    ).order_by('-created_at')

    # Get or create user settings
    user_settings, _ = UserSettings.objects.get_or_create(user=user)

    # Get available models from backend system (fast method - no heavy imports)
    try:
        from .backends import get_models_choices_fast, get_models_with_info_fast, get_backend_info_fast

        # Use fast methods to avoid slow torch/diffusers imports during page load
        models_choices = get_models_choices_fast()
        models_info = get_models_with_info_fast()  # Full info with descriptions
        backend_info = get_backend_info_fast()

        backend_name = backend_info['backend_name']
        backend_available = backend_info['backend_available']
        available_backends = backend_info['available_backends']
    except ImportError:
        # Fallback to default models if backend system not available
        models_choices = [
            ('openjourney-v4', 'OpenJourney v4'),
            ('stable-diffusion-v1-5', 'Stable Diffusion 1.5'),
        ]
        models_info = [
            {'id': 'openjourney-v4', 'name': 'OpenJourney v4', 'description': 'Style Midjourney', 'vram': '4GB'},
            {'id': 'stable-diffusion-v1-5', 'name': 'Stable Diffusion 1.5', 'description': 'Modèle classique', 'vram': '4GB'},
        ]
        backend_name = "Unknown"
        backend_available = False
        available_backends = {}

    # Generation mode choices for UI - Images
    image_modes = [
        ('txt2img', 'Text to Image', 'fas fa-keyboard'),
        ('file2img', 'File (Batch)', 'fas fa-file-alt'),
        ('describe2img', 'Describe', 'fas fa-search-plus'),
        ('style2img', 'Style Transfer', 'fas fa-palette'),
        ('img2img', 'Img2Img', 'fas fa-exchange-alt'),
    ]

    # Generation mode choices for UI - Videos
    video_modes = [
        ('txt2vid', 'Text to Video', 'fas fa-keyboard'),
        ('img2vid', 'Image to Video', 'fas fa-image'),
    ]

    # Video model choices with descriptions
    video_models = [
        ('wan-t2v-1.3b', 'Wan T2V 1.3B'),
        ('wan-i2v-14b', 'Wan I2V 14B'),
        ('hunyuan-t2v-480p', 'HunyuanVideo T2V 480p'),
        ('hunyuan-t2v-720p', 'HunyuanVideo T2V 720p'),
        ('hunyuan-i2v-480p', 'HunyuanVideo I2V 480p'),
    ]
    video_models_info = [
        {'id': 'wan-t2v-1.3b', 'name': 'Wan T2V 1.3B', 'description': 'Text-to-Video - 8GB VRAM - Rapide et efficace', 'vram': '8GB', 'type': 't2v'},
        {'id': 'wan-i2v-14b', 'name': 'Wan I2V 14B', 'description': 'Image-to-Video - 24GB VRAM - Haute qualité', 'vram': '24GB', 'type': 'i2v'},
        {'id': 'hunyuan-t2v-480p', 'name': 'HunyuanVideo T2V 480p', 'description': 'Text-to-Video 480p - 14GB VRAM avec offload - Excellente qualité', 'vram': '14GB', 'type': 't2v'},
        {'id': 'hunyuan-t2v-720p', 'name': 'HunyuanVideo T2V 720p', 'description': 'Text-to-Video 720p - 24GB VRAM - Haute résolution', 'vram': '24GB', 'type': 't2v'},
        {'id': 'hunyuan-i2v-480p', 'name': 'HunyuanVideo I2V 480p', 'description': 'Image-to-Video 480p - 14GB VRAM avec offload - Animation d\'images', 'vram': '14GB', 'type': 'i2v'},
    ]

    # Separate image and video generations
    image_generations = generations.exclude(generation_mode__in=['txt2vid', 'img2vid'])
    video_generations = generations.filter(generation_mode__in=['txt2vid', 'img2vid'])

    context = {
        'generations': generations,
        'image_generations': image_generations,
        'video_generations': video_generations,
        'user_settings': user_settings,
        'models_choices': models_choices,
        'models_info': models_info,  # Model info with descriptions for tooltips
        'video_models': video_models,
        'video_models_info': video_models_info,  # Video model info with descriptions
        'backend_name': backend_name,
        'backend_available': backend_available,
        'available_backends': available_backends,
        'image_modes': image_modes,
        'video_modes': video_modes,
        'generation_modes': image_modes,  # Keep for backward compatibility
    }

    return render(request, 'imager/index.html', context)


@require_http_methods(["POST"])
def create_generation(request):
    """Create a new image generation task (routes to appropriate handler based on mode)"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # Get generation mode
        generation_mode = request.POST.get('generation_mode', 'txt2img')

        # Route to appropriate handler
        if generation_mode == 'file2img':
            return handle_file2img(request, user)
        elif generation_mode == 'describe2img':
            return handle_describe2img(request, user)
        elif generation_mode in ('style2img', 'img2img'):
            return handle_img2img(request, user, generation_mode)
        elif generation_mode == 'txt2vid':
            return handle_txt2vid(request, user)
        elif generation_mode == 'img2vid':
            return handle_img2vid(request, user)
        else:
            # Default: txt2img mode
            return handle_txt2img(request, user)

    except Exception as e:
        logger.error(f"Error creating generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def handle_txt2img(request, user):
    """Handle standard text-to-image generation"""
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
        generation_mode='txt2img',
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

    logger.info(f"Created txt2img generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'generation_id': generation.id,
        'message': 'Generation created successfully'
    })


def handle_file2img(request, user):
    """Handle batch generation from prompt file (txt/json/yaml)"""
    from .utils.prompt_parser import parse_prompt_file, validate_prompt_config

    prompt_file = request.FILES.get('prompt_file')
    if not prompt_file:
        return JsonResponse({'error': 'No prompt file provided'}, status=400)

    # Default parameters for batch
    model = request.POST.get('model', 'openjourney-v4')
    width = int(request.POST.get('width', 512))
    height = int(request.POST.get('height', 512))
    steps = int(request.POST.get('steps', 30))
    guidance_scale = float(request.POST.get('guidance_scale', 7.5))

    # Save file temporarily to parse it
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(prompt_file.name).suffix) as tmp:
        for chunk in prompt_file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        # Parse prompts from file
        prompts = parse_prompt_file(tmp_path)

        if not prompts:
            return JsonResponse({'error': 'No valid prompts found in file'}, status=400)

        # Create parent generation (container)
        parent = ImageGeneration.objects.create(
            user=user,
            generation_mode='file2img',
            prompt=f"Batch: {len(prompts)} prompts from {prompt_file.name}",
            model=model,
            width=width,
            height=height,
            steps=steps,
            guidance_scale=guidance_scale,
            status='SUCCESS',  # Parent is just a container
        )
        parent.prompt_file.save(prompt_file.name, prompt_file)

        # Create child generations for each prompt
        children_ids = []
        for prompt_data in prompts:
            validated = validate_prompt_config(prompt_data)

            child = ImageGeneration.objects.create(
                user=user,
                generation_mode='txt2img',
                parent_generation=parent,
                prompt=validated.get('prompt', ''),
                negative_prompt=validated.get('negative_prompt', ''),
                model=validated.get('model', model),
                width=validated.get('width', width),
                height=validated.get('height', height),
                steps=validated.get('steps', steps),
                guidance_scale=validated.get('guidance_scale', guidance_scale),
                seed=validated.get('seed'),
                num_images=validated.get('num_images', 1),
                status='PENDING'
            )
            children_ids.append(child.id)

        logger.info(f"Created batch generation #{parent.id} with {len(children_ids)} children for user {user.username}")

        return JsonResponse({
            'success': True,
            'parent_id': parent.id,
            'children_ids': children_ids,
            'count': len(children_ids),
            'message': f'Created {len(children_ids)} generation(s) from file'
        })

    finally:
        # Clean up temp file
        os.unlink(tmp_path)


def handle_describe2img(request, user):
    """Handle describe-to-image: auto-generate prompt from reference image using BLIP"""
    reference_image = request.FILES.get('reference_image')
    if not reference_image:
        return JsonResponse({'error': 'No reference image provided'}, status=400)

    model = request.POST.get('model', 'openjourney-v4')
    width = int(request.POST.get('width', 512))
    height = int(request.POST.get('height', 512))
    steps = int(request.POST.get('steps', 30))
    guidance_scale = float(request.POST.get('guidance_scale', 7.5))
    prompt_style = request.POST.get('prompt_style', 'detailed')

    # Create generation with placeholder prompt
    generation = ImageGeneration.objects.create(
        user=user,
        generation_mode='describe2img',
        prompt='[Generating prompt from image...]',
        model=model,
        width=width,
        height=height,
        steps=steps,
        guidance_scale=guidance_scale,
        status='PENDING'
    )
    generation.reference_image.save(reference_image.name, reference_image)

    # Generate auto-prompt from image
    try:
        from .utils.auto_prompt import generate_prompt_from_image

        auto_prompt = generate_prompt_from_image(
            generation.reference_image.path,
            style=prompt_style
        )

        generation.prompt = auto_prompt
        generation.auto_prompt = auto_prompt
        generation.save()

        logger.info(f"Created describe2img generation #{generation.id} with auto-prompt for user {user.username}")

        return JsonResponse({
            'success': True,
            'generation_id': generation.id,
            'auto_prompt': auto_prompt,
            'message': 'Generation created with auto-generated prompt'
        })

    except Exception as e:
        logger.error(f"Error generating auto-prompt: {e}")
        # Keep the generation but mark error
        generation.prompt = f"[Auto-prompt failed: {str(e)}]"
        generation.status = 'FAILURE'
        generation.error_message = str(e)
        generation.save()

        return JsonResponse({
            'error': f'Failed to generate prompt from image: {str(e)}',
            'generation_id': generation.id
        }, status=500)


def handle_img2img(request, user, mode):
    """Handle img2img and style2img: image-to-image transformation"""
    reference_image = request.FILES.get('reference_image')
    if not reference_image:
        return JsonResponse({'error': 'No reference image provided'}, status=400)

    prompt = request.POST.get('prompt', '').strip()
    negative_prompt = request.POST.get('negative_prompt', '').strip()
    model = request.POST.get('model', 'openjourney-v4')
    width = int(request.POST.get('width', 512))
    height = int(request.POST.get('height', 512))
    steps = int(request.POST.get('steps', 30))
    guidance_scale = float(request.POST.get('guidance_scale', 7.5))
    image_strength = float(request.POST.get('image_strength', 0.75))
    seed = request.POST.get('seed')
    if seed:
        seed = int(seed)
    else:
        seed = None
    num_images = int(request.POST.get('num_images', 1))

    # For style2img mode, if no prompt is provided, generate one
    if mode == 'style2img' and not prompt:
        prompt = "in the style of the reference image"

    # Create generation
    generation = ImageGeneration.objects.create(
        user=user,
        generation_mode=mode,
        prompt=prompt or '[No prompt - pure img2img]',
        negative_prompt=negative_prompt,
        model=model,
        width=width,
        height=height,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        num_images=num_images,
        image_strength=image_strength,
        status='PENDING'
    )
    generation.reference_image.save(reference_image.name, reference_image)

    logger.info(f"Created {mode} generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'generation_id': generation.id,
        'mode': mode,
        'message': f'{mode} generation created successfully'
    })


def handle_txt2vid(request, user):
    """Handle text-to-video generation"""
    prompt = request.POST.get('prompt', '').strip()
    if not prompt:
        return JsonResponse({'error': 'Prompt is required'}, status=400)

    negative_prompt = request.POST.get('negative_prompt', '').strip()
    model = request.POST.get('model', 'wan-t2v-1.3b')
    video_duration = float(request.POST.get('video_duration', 5.0))
    video_fps = int(request.POST.get('video_fps', 16))
    video_resolution = request.POST.get('video_resolution', '480p')
    steps = int(request.POST.get('steps', 50))
    guidance_scale = float(request.POST.get('guidance_scale', 5.0))
    seed = request.POST.get('seed')
    if seed:
        seed = int(seed)
    else:
        seed = None

    # Create generation object
    generation = ImageGeneration.objects.create(
        user=user,
        generation_mode='txt2vid',
        prompt=prompt,
        negative_prompt=negative_prompt,
        model=model,
        video_duration=video_duration,
        video_fps=video_fps,
        video_resolution=video_resolution,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        status='PENDING'
    )

    logger.info(f"Created txt2vid generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'generation_id': generation.id,
        'message': 'Video generation created successfully'
    })


def handle_img2vid(request, user):
    """Handle image-to-video generation"""
    reference_image = request.FILES.get('reference_image')
    if not reference_image:
        return JsonResponse({'error': 'Reference image is required'}, status=400)

    prompt = request.POST.get('prompt', '').strip()
    negative_prompt = request.POST.get('negative_prompt', '').strip()
    model = request.POST.get('model', 'wan-i2v-14b')
    video_duration = float(request.POST.get('video_duration', 5.0))
    video_fps = int(request.POST.get('video_fps', 16))
    video_resolution = request.POST.get('video_resolution', '480p')
    steps = int(request.POST.get('steps', 50))
    guidance_scale = float(request.POST.get('guidance_scale', 5.0))
    seed = request.POST.get('seed')
    if seed:
        seed = int(seed)
    else:
        seed = None

    # Create generation object
    generation = ImageGeneration.objects.create(
        user=user,
        generation_mode='img2vid',
        prompt=prompt or 'animate this image',
        negative_prompt=negative_prompt,
        model=model,
        video_duration=video_duration,
        video_fps=video_fps,
        video_resolution=video_resolution,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        status='PENDING'
    )
    generation.reference_image.save(reference_image.name, reference_image)

    logger.info(f"Created img2vid generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'generation_id': generation.id,
        'message': 'Image-to-video generation created successfully'
    })


@require_http_methods(["POST"])
def generate_auto_prompt(request):
    """Generate prompt from uploaded image using BLIP (AJAX endpoint)"""
    reference_image = request.FILES.get('reference_image')
    if not reference_image:
        return JsonResponse({'error': 'No image provided'}, status=400)

    prompt_style = request.POST.get('prompt_style', 'detailed')

    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(reference_image.name).suffix) as tmp:
        for chunk in reference_image.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        from .utils.auto_prompt import generate_prompt_from_image

        auto_prompt = generate_prompt_from_image(tmp_path, style=prompt_style)

        return JsonResponse({
            'success': True,
            'prompt': auto_prompt
        })

    except Exception as e:
        logger.error(f"Error generating auto-prompt: {e}")
        return JsonResponse({'error': str(e)}, status=500)

    finally:
        os.unlink(tmp_path)


def get_batch_children(request, parent_id):
    """Get children of a batch generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        parent = get_object_or_404(ImageGeneration, id=parent_id, user=user)
        children = ImageGeneration.objects.filter(parent_generation=parent).order_by('id')

        children_data = []
        for child in children:
            children_data.append({
                'id': child.id,
                'prompt': child.prompt[:100] + ('...' if len(child.prompt) > 100 else ''),
                'status': child.status,
                'progress': child.progress,
                'generated_images': child.generated_images,
            })

        return JsonResponse({
            'parent_id': parent.id,
            'count': children.count(),
            'children': children_data
        })

    except Exception as e:
        logger.error(f"Error getting batch children: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def start_batch(request, parent_id):
    """Start all pending children of a batch generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        parent = get_object_or_404(ImageGeneration, id=parent_id, user=user)
        children = ImageGeneration.objects.filter(
            parent_generation=parent,
            status='PENDING'
        )

        if not children.exists():
            return JsonResponse({'error': 'No pending children to start'}, status=400)

        from .tasks import generate_image_task

        started_count = 0
        for child in children:
            task = generate_image_task.delay(child.id)
            child.status = 'RUNNING'
            child.progress = 0
            child.save()
            started_count += 1

        logger.info(f"Started {started_count} batch children for parent #{parent_id}")

        return JsonResponse({
            'success': True,
            'started': started_count,
            'message': f'Started {started_count} generation(s)'
        })

    except Exception as e:
        logger.error(f"Error starting batch: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def start_generation(request, generation_id):
    """Start a specific generation task"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = get_object_or_404(ImageGeneration, id=generation_id, user=user)

        if generation.status == 'RUNNING':
            return JsonResponse({'error': 'Generation already running'}, status=400)

        # Reset progress and clear cache
        generation.progress = 0
        generation.save()
        cache.delete(f"imager_progress_{generation_id}")

        # Import tasks - use video task for video modes
        from .tasks import generate_image_task, generate_video_task

        # Start appropriate Celery task based on mode
        if generation.is_video_generation:
            task = generate_video_task.delay(generation.id)
        else:
            task = generate_image_task.delay(generation.id)

        # Update status
        generation.status = 'RUNNING'
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
def restart_generation(request, generation_id):
    """Restart a completed or failed generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = get_object_or_404(ImageGeneration, id=generation_id, user=user)

        if generation.status == 'RUNNING':
            return JsonResponse({'error': 'Generation is already running'}, status=400)

        # Reset status and progress
        generation.status = 'PENDING'
        generation.progress = 0
        generation.error_message = ""
        generation.save()

        # Clear progress cache to avoid showing old values
        cache.delete(f"imager_progress_{generation_id}")

        # Import tasks - use video task for video modes
        from .tasks import generate_image_task, generate_video_task

        # Start appropriate Celery task based on mode
        if generation.is_video_generation:
            task = generate_video_task.delay(generation.id)
        else:
            task = generate_image_task.delay(generation.id)

        # Update status
        generation.status = 'RUNNING'
        generation.save()

        logger.info(f"Restarted generation #{generation.id}, task_id: {task.id}")

        return JsonResponse({
            'success': True,
            'task_id': task.id,
            'message': 'Generation restarted'
        })

    except Exception as e:
        logger.error(f"Error restarting generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def start_all_generations(request):
    """Start all pending generations"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        pending = ImageGeneration.objects.filter(user=user, status='PENDING')

        if not pending.exists():
            return JsonResponse({'error': 'No pending generations'}, status=400)

        from .tasks import generate_image_task, generate_video_task

        started_count = 0
        for generation in pending:
            # Clear progress cache before starting
            cache.delete(f"imager_progress_{generation.id}")

            # Use appropriate task based on mode
            if generation.is_video_generation:
                task = generate_video_task.delay(generation.id)
            else:
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
        progress_value = cached_progress if cached_progress is not None else generation.progress

        data = {
            'id': generation.id,
            'status': generation.status,
            'progress': progress_value,
            'error_message': generation.error_message,
            'generated_images': generation.generated_images,
            'duration': generation.duration_display,
            'output_type': generation.output_type,
            'is_video': generation.is_video_generation,
        }

        # Include video URL if available
        if generation.output_video:
            data['output_video_url'] = generation.output_video.url

        return JsonResponse(data)

    except Exception as e:
        logger.error(f"Error getting progress: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def global_progress(request):
    """Get overall progress for all user generations (optimized single query)"""
    from django.db.models import Count, Case, When, IntegerField, Avg

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # Single aggregated query instead of 7+ separate queries
        stats = ImageGeneration.objects.filter(
            user=user,
            parent_generation__isnull=True  # Only top-level generations
        ).aggregate(
            total=Count('id'),
            pending=Count(Case(When(status='PENDING', then=1), output_field=IntegerField())),
            running=Count(Case(When(status='RUNNING', then=1), output_field=IntegerField())),
            success=Count(Case(When(status='SUCCESS', then=1), output_field=IntegerField())),
            failure=Count(Case(When(status='FAILURE', then=1), output_field=IntegerField())),
            avg_progress=Avg('progress'),
        )

        total = stats['total'] or 0
        overall_progress = int(stats['avg_progress'] or 0)

        return JsonResponse({
            'total': total,
            'pending': stats['pending'] or 0,
            'running': stats['running'] or 0,
            'success': stats['success'] or 0,
            'failure': stats['failure'] or 0,
            'overall_progress': overall_progress
        })

    except Exception as e:
        logger.error(f"Error getting global progress: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def download(request, generation_id):
    """Download generated images or video"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = get_object_or_404(ImageGeneration, id=generation_id, user=user)

        # Handle video download
        if generation.is_video_generation:
            if not generation.output_video:
                return HttpResponse("No video generated yet", status=404)

            video_path = generation.output_video.path
            if os.path.exists(video_path):
                return FileResponse(
                    open(video_path, 'rb'),
                    as_attachment=True,
                    filename=f"video_{generation.id}.mp4",
                    content_type='video/mp4'
                )
            return HttpResponse("Video file not found", status=404)

        # Handle image download
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
        logger.error(f"Error downloading: {str(e)}")
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

        # Delete video file if exists
        if generation.output_video:
            try:
                video_path = generation.output_video.path
                if os.path.exists(video_path):
                    os.remove(video_path)
            except Exception as e:
                logger.warning(f"Failed to delete video: {str(e)}")

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


def download_all(request):
    """Download all generated images as a zip file"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generations = ImageGeneration.objects.filter(user=user, status='SUCCESS')

        if not generations.exists():
            return HttpResponse("No completed generations to download", status=404)

        import zipfile
        from io import BytesIO

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for generation in generations:
                for image_path in generation.generated_images:
                    if os.path.exists(image_path):
                        # Create a subfolder per generation
                        folder_name = f"generation_{generation.id}"
                        arcname = f"{folder_name}/{os.path.basename(image_path)}"
                        zip_file.write(image_path, arcname)

        zip_buffer.seek(0)
        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="imager_all_images.zip"'
        return response

    except Exception as e:
        logger.error(f"Error downloading all images: {str(e)}")
        return HttpResponse(f"Error: {str(e)}", status=500)


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


def get_generation_settings(request, generation_id):
    """Get settings for a specific generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = get_object_or_404(ImageGeneration, id=generation_id, user=user)

        data = {
            'id': generation.id,
            'generation_mode': generation.generation_mode,
            'prompt': generation.prompt,
            'negative_prompt': generation.negative_prompt or '',
            'auto_prompt': generation.auto_prompt or '',
            'model': generation.model,
            'width': generation.width,
            'height': generation.height,
            'steps': generation.steps,
            'guidance_scale': generation.guidance_scale,
            'image_strength': generation.image_strength,
            'reference_image_url': generation.reference_image.url if generation.reference_image else None,
            'seed': generation.seed,
            'num_images': generation.num_images,
            'upscale': generation.upscale,
            'status': generation.status,
            # Video-specific fields
            'video_duration': generation.video_duration,
            'video_fps': generation.video_fps,
            'video_resolution': generation.video_resolution,
        }

        return JsonResponse(data)

    except Exception as e:
        logger.error(f"Error getting generation settings: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def save_generation_settings(request, generation_id):
    """Save settings for a specific generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = get_object_or_404(ImageGeneration, id=generation_id, user=user)

        # Don't allow editing while running
        if generation.status == 'RUNNING':
            return JsonResponse({'error': 'Cannot edit a running generation'}, status=400)

        # Update fields from POST data
        if 'prompt' in request.POST:
            prompt = request.POST.get('prompt', '').strip()
            if not prompt:
                return JsonResponse({'error': 'Prompt is required'}, status=400)
            generation.prompt = prompt

        if 'negative_prompt' in request.POST:
            generation.negative_prompt = request.POST.get('negative_prompt', '').strip()

        if 'model' in request.POST:
            generation.model = request.POST.get('model')

        if 'width' in request.POST:
            generation.width = int(request.POST.get('width', 512))

        if 'height' in request.POST:
            generation.height = int(request.POST.get('height', 512))

        if 'steps' in request.POST:
            generation.steps = int(request.POST.get('steps', 30))

        if 'guidance_scale' in request.POST:
            generation.guidance_scale = float(request.POST.get('guidance_scale', 7.5))

        if 'seed' in request.POST:
            seed = request.POST.get('seed')
            generation.seed = int(seed) if seed else None

        if 'num_images' in request.POST:
            generation.num_images = int(request.POST.get('num_images', 1))

        if 'upscale' in request.POST:
            generation.upscale = request.POST.get('upscale', 'false').lower() == 'true'

        if 'image_strength' in request.POST:
            generation.image_strength = float(request.POST.get('image_strength', 0.75))

        # Video-specific fields
        if 'video_duration' in request.POST:
            generation.video_duration = int(request.POST.get('video_duration', 5))

        if 'video_fps' in request.POST:
            generation.video_fps = int(request.POST.get('video_fps', 16))

        if 'video_resolution' in request.POST:
            generation.video_resolution = request.POST.get('video_resolution', '480p')

        generation.save()

        logger.info(f"Updated settings for generation #{generation.id}")

        return JsonResponse({
            'success': True,
            'message': 'Settings saved successfully'
        })

    except Exception as e:
        logger.error(f"Error saving generation settings: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def api_model_resolutions(request):
    """
    API endpoint to get recommended resolutions for a model.

    GET /imager/api/model-resolutions/?model=hunyuan-image-2.1

    Returns:
        {
            "model": "hunyuan-image-2.1",
            "config": {
                "min_size": 1024,
                "max_size": 2048,
                "default": "2048x2048",
                "vram_warning": "...",
            },
            "resolutions": [
                {"key": "2048x2048", "width": 2048, "height": 2048, "label": "...", "ratio": "1:1"},
                ...
            ]
        }
    """
    from .models import (
        get_model_resolution_config,
        get_recommended_resolutions,
        IMAGE_RESOLUTION_PRESETS
    )

    model_name = request.GET.get('model', 'stable-diffusion-v1-5')

    config = get_model_resolution_config(model_name)
    resolutions = get_recommended_resolutions(model_name)

    return JsonResponse({
        'model': model_name,
        'config': config,
        'resolutions': resolutions,
        'all_presets': IMAGE_RESOLUTION_PRESETS,
    })


@require_http_methods(["GET"])
def api_all_resolutions(request):
    """
    API endpoint to get all available resolution presets.

    GET /imager/api/resolutions/

    Returns all resolution presets grouped by ratio.
    """
    from .models import IMAGE_RESOLUTION_PRESETS

    # Group by ratio
    by_ratio = {}
    for key, preset in IMAGE_RESOLUTION_PRESETS.items():
        ratio = preset['ratio']
        if ratio not in by_ratio:
            by_ratio[ratio] = []
        by_ratio[ratio].append({'key': key, **preset})

    return JsonResponse({
        'presets': IMAGE_RESOLUTION_PRESETS,
        'by_ratio': by_ratio,
    })
