import os
import io
import zipfile
import logging
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str
from django.core.cache import cache
from PIL import Image

from .models import Enhancement, UserSettings
from ..accounts.views import get_or_create_anonymous_user
from ..common.utils.console_utils import get_console_lines, get_celery_worker_logs
from ..common.utils.video_utils import upload_media_from_url

logger = logging.getLogger(__name__)


class IndexView(View):
    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
        enhancements = Enhancement.objects.filter(user=user).order_by('-id')

        # Get or create user settings
        user_settings, _ = UserSettings.objects.get_or_create(user=user)

        return render(request, 'enhancer/index.html', {
            'enhancements': enhancements,
            'user_settings': user_settings,
            'ai_models': Enhancement.AI_MODEL_CHOICES,
        })


@require_POST
def upload(request):
    """Upload and analyze image/video file, or download from URL."""
    logger.info("=== UPLOAD START ===")

    # Check for URL upload first
    media_url = request.POST.get('media_url', '').strip()
    file = request.FILES.get('file')

    if not file and not media_url:
        logger.error("Upload failed: No file or URL provided")
        return HttpResponseBadRequest('Missing file or URL')

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    logger.info(f"Upload by user: {user.username} (ID: {user.id})")

    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.heic']
    video_extensions = ['.mp4', '.webm', '.mkv', '.flv', '.gif', '.avi', '.mov', '.mpg', '.qt', '.3gp']

    # Handle URL download
    if media_url and not file:
        try:
            import tempfile
            from django.core.files import File

            logger.info(f"[Enhancer] Downloading media from URL: {media_url}")

            # Download to temp directory
            temp_dir = tempfile.mkdtemp()
            downloaded_path = upload_media_from_url(media_url, temp_dir)
            filename = os.path.basename(downloaded_path)

            logger.info(f"[Enhancer] Downloaded to: {downloaded_path}")

            # Detect media type
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext in image_extensions:
                media_type = 'image'
            elif file_ext in video_extensions:
                media_type = 'video'
            else:
                logger.error(f"Unsupported format: {file_ext}")
                # Cleanup
                try:
                    os.remove(downloaded_path)
                    os.rmdir(temp_dir)
                except OSError:
                    pass
                return JsonResponse({'error': 'Format non supporté'}, status=400)

            logger.info(f"Detected media type: {media_type}")

            # Get user settings for defaults
            user_settings, _ = UserSettings.objects.get_or_create(user=user)
            logger.info(f"User settings: model={user_settings.default_ai_model}, denoise={user_settings.default_denoise}, blend={user_settings.default_blend_factor}")

            # Create enhancement with the downloaded file
            with open(downloaded_path, 'rb') as f:
                django_file = File(f, name=filename)

                enhancement = Enhancement.objects.create(
                    user=user,
                    media_type=media_type,
                    input_file=django_file,
                    ai_model=user_settings.default_ai_model,
                    denoise=user_settings.default_denoise,
                    blend_factor=user_settings.default_blend_factor,
                )

            # Cleanup temp file
            try:
                os.remove(downloaded_path)
                os.rmdir(temp_dir)
            except OSError:
                pass

            logger.info(f"Created Enhancement ID: {enhancement.id}")

            # Analyze file
            try:
                _analyze_media(enhancement)
                logger.info(f"Media analyzed: {enhancement.width}x{enhancement.height}")
            except Exception as e:
                logger.warning(f"Could not analyze media: {e}")

            return JsonResponse({
                'id': enhancement.id,
                'media_type': enhancement.media_type,
                'input_url': enhancement.input_file.url,
                'input_filename': enhancement.get_input_filename(),
                'width': enhancement.width,
                'height': enhancement.height,
                'file_size': enhancement.file_size,
                'status': enhancement.status,
            })

        except Exception as e:
            logger.error(f"[Enhancer] URL download failed: {e}")
            return JsonResponse({'error': f'Download failed: {str(e)}'}, status=400)

    # Handle regular file upload
    # Detect media type
    file_ext = os.path.splitext(file.name)[1].lower()
    logger.info(f"File: {file.name} (extension: {file_ext}, size: {file.size} bytes)")

    if file_ext in image_extensions:
        media_type = 'image'
    elif file_ext in video_extensions:
        media_type = 'video'
    else:
        logger.error(f"Unsupported format: {file_ext}")
        return JsonResponse({'error': 'Format non supporté'}, status=400)

    logger.info(f"Detected media type: {media_type}")

    # Get user settings for defaults
    user_settings, _ = UserSettings.objects.get_or_create(user=user)
    logger.info(f"User settings: model={user_settings.default_ai_model}, denoise={user_settings.default_denoise}, blend={user_settings.default_blend_factor}")

    # Create enhancement record
    enhancement = Enhancement.objects.create(
        user=user,
        media_type=media_type,
        input_file=file,
        ai_model=user_settings.default_ai_model,
        denoise=user_settings.default_denoise,
        blend_factor=user_settings.default_blend_factor,
    )
    logger.info(f"Created Enhancement ID: {enhancement.id}")

    # Analyze file
    try:
        _analyze_media(enhancement)
        logger.info(f"Media analyzed: {enhancement.width}x{enhancement.height}")
    except Exception as e:
        logger.warning(f"Could not analyze media: {e}")

    return JsonResponse({
        'id': enhancement.id,
        'media_type': enhancement.media_type,
        'input_url': enhancement.input_file.url,
        'input_filename': enhancement.get_input_filename(),
        'width': enhancement.width,
        'height': enhancement.height,
        'file_size': enhancement.file_size,
        'status': enhancement.status,
    })


def _analyze_media(enhancement: Enhancement):
    """Analyze media file to extract dimensions and metadata."""
    file_path = enhancement.input_file.path
    enhancement.file_size = os.path.getsize(file_path)

    if enhancement.media_type == 'image':
        try:
            with Image.open(file_path) as img:
                enhancement.width, enhancement.height = img.size
        except Exception as e:
            logger.warning(f"Could not analyze image: {e}")

    elif enhancement.media_type == 'video':
        # Try ffprobe first
        try:
            import subprocess
            import json

            result = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=width,height,duration',
                    '-of', 'json',
                    file_path,
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                stream = (data.get('streams') or [{}])[0]
                enhancement.width = int(stream.get('width', 0))
                enhancement.height = int(stream.get('height', 0))
                enhancement.duration = float(stream.get('duration', 0))
            else:
                raise Exception(f"ffprobe failed: {result.stderr}")

        except Exception as e:
            logger.warning(f"ffprobe failed, trying OpenCV: {e}")
            # Fallback to OpenCV
            try:
                import cv2
                vid = cv2.VideoCapture(file_path)
                if vid.isOpened():
                    enhancement.width = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))
                    enhancement.height = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = vid.get(cv2.CAP_PROP_FPS) or 25
                    total_frames = vid.get(cv2.CAP_PROP_FRAME_COUNT)
                    enhancement.duration = total_frames / fps if fps > 0 else 0
                    vid.release()
                else:
                    logger.warning(f"OpenCV could not open video: {file_path}")
            except Exception as cv_error:
                logger.warning(f"OpenCV fallback failed: {cv_error}")

    enhancement.save(update_fields=['width', 'height', 'duration', 'file_size'])


@require_POST
def start(request, pk: int):
    """Start enhancement processing."""
    logger.info(f"=== START ENHANCEMENT {pk} ===")

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    logger.info(f"User: {user.username} (ID: {user.id})")

    enhancement = get_object_or_404(Enhancement, pk=pk, user=user)
    logger.info(f"Enhancement found: ID={enhancement.id}, media_type={enhancement.media_type}, current_status={enhancement.status}")

    # Get settings from request (support both JSON and form-data)
    try:
        import json
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, ValueError):
        data = request.POST

    ai_model = data.get('ai_model', enhancement.ai_model)
    denoise_value = data.get('denoise', enhancement.denoise)
    if isinstance(denoise_value, str):
        denoise = denoise_value.lower() in ('1', 'true', 'on')
    else:
        denoise = bool(denoise_value)
    blend_factor = float(data.get('blend_factor', enhancement.blend_factor))

    logger.info(f"Settings: model={ai_model}, denoise={denoise}, blend_factor={blend_factor}")

    # Update enhancement with new settings
    enhancement.ai_model = ai_model
    enhancement.denoise = denoise
    enhancement.blend_factor = blend_factor
    enhancement.save(update_fields=['ai_model', 'denoise', 'blend_factor'])
    logger.info("Enhancement settings updated")

    # Start Celery task
    from .tasks import enhance_media

    try:
        logger.info("Calling enhance_media.delay()...")
        task = enhance_media.delay(pk)
        logger.info(f"Task created: task_id={task.id}")

        enhancement.task_id = task.id
        enhancement.status = 'RUNNING'
        enhancement.save(update_fields=['task_id', 'status'])
        logger.info(f"Enhancement {pk} status updated to RUNNING")

        return JsonResponse({
            'task_id': task.id,
            'status': 'RUNNING',
        })
    except Exception as e:
        logger.error(f"Failed to start task for Enhancement {pk}: {e}", exc_info=True)
        return JsonResponse({
            'error': str(e),
            'message': 'Failed to start task. Is Celery running?',
        }, status=500)


def progress(request, pk: int):
    """Get enhancement progress."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancement = get_object_or_404(Enhancement, pk=pk, user=user)

    # Get progress from cache
    progress = int(cache.get(f"enhancer_progress_{pk}", enhancement.progress or 0))

    return JsonResponse({
        'progress': progress,
        'status': enhancement.status,
        'error_message': enhancement.error_message,
    })


def download(request, pk: int):
    """Download enhanced file."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancement = get_object_or_404(Enhancement, pk=pk, user=user)

    logger.info(f"Download request for enhancement {pk}")
    logger.info(f"  - output_file field: {enhancement.output_file}")
    logger.info(f"  - output_file.name: {enhancement.output_file.name if enhancement.output_file else 'None'}")

    if not enhancement.output_file:
        logger.error(f"No output file available for enhancement {pk}")
        return HttpResponseBadRequest('No output file available')

    # Check if file exists in storage
    from django.core.files.storage import default_storage
    if not default_storage.exists(enhancement.output_file.name):
        logger.error(f"Output file does not exist in storage: {enhancement.output_file.name}")
        return HttpResponseBadRequest(f'Output file not found in storage: {enhancement.output_file.name}')

    logger.info(f"Opening file for download: {enhancement.output_file.name}")
    try:
        return FileResponse(
            enhancement.output_file.open('rb'),
            as_attachment=True,
            filename=enhancement.get_output_filename()
        )
    except Exception as e:
        logger.error(f"Error opening file for download: {e}", exc_info=True)
        return HttpResponseBadRequest(f'Error opening file: {e}')


@require_POST
def delete(request, pk: int):
    """Delete enhancement."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancement = get_object_or_404(Enhancement, pk=pk, user=user)

    # Delete files
    if enhancement.input_file:
        try:
            enhancement.input_file.delete(save=False)
        except:
            pass

    if enhancement.output_file:
        try:
            enhancement.output_file.delete(save=False)
        except:
            pass

    enhancement.delete()
    cache.delete(f"enhancer_progress_{pk}")

    return JsonResponse({'deleted': pk})


@require_POST
def start_all(request):
    """Start all enhancements (including reprocessing completed ones)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancements = Enhancement.objects.filter(user=user)

    # Get global settings from request (support both JSON and form-data)
    try:
        import json
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, ValueError):
        data = request.POST

    # Extract global settings if provided
    global_ai_model = data.get('ai_model')
    global_denoise = data.get('denoise')
    global_blend_factor = data.get('blend_factor')

    logger.info(f"start_all with global settings: model={global_ai_model}, denoise={global_denoise}, blend={global_blend_factor}")

    from .tasks import enhance_media

    started = []
    errors = []

    for enhancement in enhancements:
        # Skip only currently running enhancements
        if enhancement.status == 'RUNNING':
            continue

        try:
            # Apply global settings if provided
            if global_ai_model:
                enhancement.ai_model = global_ai_model
            if global_denoise is not None:
                if isinstance(global_denoise, str):
                    enhancement.denoise = global_denoise.lower() in ('1', 'true', 'on')
                else:
                    enhancement.denoise = bool(global_denoise)
            if global_blend_factor is not None:
                enhancement.blend_factor = float(global_blend_factor)

            enhancement.save(update_fields=['ai_model', 'denoise', 'blend_factor'])

            task = enhance_media.delay(enhancement.id)
            enhancement.task_id = task.id
            enhancement.status = 'RUNNING'
            enhancement.save(update_fields=['task_id', 'status'])
            started.append(enhancement.id)
        except Exception as e:
            errors.append({'id': enhancement.id, 'error': str(e)})

    return JsonResponse({
        'started_ids': started,
        'count': len(started),
        'errors': errors,
    })


@require_POST
def clear_all(request):
    """Clear all enhancements."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancements = Enhancement.objects.filter(user=user)

    cleared = []
    for enhancement in enhancements:
        cleared.append(enhancement.id)
        if enhancement.input_file:
            try:
                enhancement.input_file.delete(save=False)
            except:
                pass
        if enhancement.output_file:
            try:
                enhancement.output_file.delete(save=False)
            except:
                pass
        cache.delete(f"enhancer_progress_{enhancement.id}")

    enhancements.delete()

    return JsonResponse({'cleared_ids': cleared, 'count': len(cleared)})


def download_all(request):
    """Download all enhanced files as ZIP."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancements = Enhancement.objects.filter(user=user, status='SUCCESS').exclude(output_file='')

    if not enhancements.exists():
        return HttpResponseBadRequest('No enhanced files available')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for enhancement in enhancements:
            if enhancement.output_file:
                try:
                    filename = enhancement.get_output_filename()
                    with enhancement.output_file.open('rb') as f:
                        archive.writestr(filename, f.read())
                except:
                    pass

    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename="enhanced_files.zip")


@require_POST
def update_settings(request, pk: int):
    """Update enhancement settings."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancement = get_object_or_404(Enhancement, pk=pk, user=user)

    if enhancement.status == 'RUNNING':
        return JsonResponse({'error': 'Cannot update running enhancement'}, status=400)

    # Update settings
    ai_model = request.POST.get('ai_model')
    if ai_model:
        enhancement.ai_model = ai_model

    denoise = request.POST.get('denoise')
    if denoise is not None:
        enhancement.denoise = denoise.lower() in ('1', 'true', 'on')

    blend_factor = request.POST.get('blend_factor')
    if blend_factor is not None:
        enhancement.blend_factor = float(blend_factor)

    enhancement.save()

    return JsonResponse({
        'id': enhancement.id,
        'ai_model': enhancement.ai_model,
        'denoise': enhancement.denoise,
        'blend_factor': enhancement.blend_factor,
    })


def console_content(request):
    """
    Retourne le contenu de la console (logs Celery + cache).
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Récupère les logs depuis le cache et Celery
    console_lines = get_console_lines(user.id, limit=100)
    celery_lines = get_celery_worker_logs(limit=100)
    all_lines = (celery_lines + console_lines)[-200:]

    return JsonResponse({'output': all_lines})


def global_progress(request):
    """Get overall progress for all user enhancements"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        enhancements = Enhancement.objects.filter(user=user)

        if not enhancements.exists():
            return JsonResponse({
                'total': 0,
                'pending': 0,
                'running': 0,
                'success': 0,
                'failure': 0,
                'overall_progress': 0
            })

        total = enhancements.count()
        pending = enhancements.filter(status='PENDING').count()
        running = enhancements.filter(status='RUNNING').count()
        success = enhancements.filter(status='SUCCESS').count()
        failure = enhancements.filter(status='FAILURE').count()

        # Calculate overall progress using cache
        total_progress = 0
        for e in enhancements:
            progress = int(cache.get(f"enhancer_progress_{e.id}", e.progress or 0))
            total_progress += progress

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
        logger.error(f"Error in global_progress: {e}")
        return JsonResponse({'error': str(e)}, status=500)
