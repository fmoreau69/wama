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

import datetime
from .models import (Enhancement, UserSettings, AudioEnhancement,
                     BatchEnhancement, BatchEnhancementItem,
                     BatchAudioEnhancement, BatchAudioEnhancementItem)
from ..accounts.views import get_or_create_anonymous_user
from ..common.utils.console_utils import get_console_lines
from ..common.utils.video_utils import upload_media_from_url, get_media_info
from ..common.utils.queue_duplication import safe_delete_file, duplicate_instance

logger = logging.getLogger(__name__)


def _wrap_enhancement_in_batch(enhancement):
    """Wrap a standalone Enhancement in a new BatchEnhancement-of-1."""
    batch = BatchEnhancement.objects.create(user=enhancement.user, total=1)
    BatchEnhancementItem.objects.create(batch=batch, enhancement=enhancement, row_index=0)
    return batch


def _auto_wrap_orphans(user):
    """Wrap any Enhancement not yet in a batch into a batch-of-1 (called on page load)."""
    existing_ids = set(
        BatchEnhancementItem.objects.filter(batch__user=user)
        .values_list('enhancement_id', flat=True)
    )
    orphans = Enhancement.objects.filter(user=user).exclude(id__in=existing_ids)
    for orphan in orphans:
        try:
            _wrap_enhancement_in_batch(orphan)
        except Exception:
            pass


def _wrap_audio_in_batch(audio_enhancement):
    """Wrap a standalone AudioEnhancement in a new BatchAudioEnhancement-of-1."""
    batch = BatchAudioEnhancement.objects.create(user=audio_enhancement.user, total=1)
    BatchAudioEnhancementItem.objects.create(batch=batch, audio_enhancement=audio_enhancement, row_index=0)
    return batch


def _auto_wrap_audio_orphans(user):
    """Wrap any AudioEnhancement not yet in a batch into a batch-of-1 (called on page load)."""
    existing_ids = set(
        BatchAudioEnhancementItem.objects.filter(batch__user=user)
        .values_list('audio_enhancement_id', flat=True)
    )
    orphans = AudioEnhancement.objects.filter(user=user).exclude(id__in=existing_ids)
    for orphan in orphans:
        try:
            _wrap_audio_in_batch(orphan)
        except Exception:
            pass


class IndexView(View):
    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Lazily wrap any orphan enhancements into batches-of-1
        _auto_wrap_orphans(user)
        _auto_wrap_audio_orphans(user)

        # Build batches_list for image/video tab
        batches_qs = BatchEnhancement.objects.filter(user=user).prefetch_related(
            'items__enhancement'
        ).order_by('-id')

        batches_list = []
        for batch in batches_qs:
            items = list(batch.items.all())
            success_count = sum(
                1 for i in items if i.enhancement and i.enhancement.status == 'SUCCESS'
            )
            batches_list.append({
                'obj': batch,
                'items': items,
                'success_count': success_count,
                'success_pct': int(success_count / batch.total * 100) if batch.total > 0 else 0,
                'has_success': success_count > 0,
            })

        # Build audio_batches_list for audio tab
        audio_batches_qs = BatchAudioEnhancement.objects.filter(user=user).prefetch_related(
            'items__audio_enhancement'
        ).order_by('-id')

        audio_batches_list = []
        for batch in audio_batches_qs:
            items = list(batch.items.all())
            success_count = sum(
                1 for i in items if i.audio_enhancement and i.audio_enhancement.status == 'SUCCESS'
            )
            audio_batches_list.append({
                'obj': batch,
                'items': items,
                'success_count': success_count,
                'success_pct': int(success_count / batch.total * 100) if batch.total > 0 else 0,
                'has_success': success_count > 0,
            })

        batches_list.sort(key=lambda b: 0 if b['obj'].total > 1 else 1)
        audio_batches_list.sort(key=lambda b: 0 if b['obj'].total > 1 else 1)

        # Get or create user settings
        user_settings, _ = UserSettings.objects.get_or_create(user=user)

        return render(request, 'enhancer/index.html', {
            'batches_list': batches_list,
            'audio_batches_list': audio_batches_list,
            'user_settings': user_settings,
            'ai_models': Enhancement.AI_MODEL_CHOICES,
        })


@require_POST
def upload(request):
    """Upload and analyze image/video file, or download from URL."""
    print("=== ENHANCER UPLOAD CALLED ===")  # DEBUG
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

            # Wrap in batch-of-1
            try:
                _wrap_enhancement_in_batch(enhancement)
            except Exception:
                pass

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

    # Wrap in batch-of-1
    try:
        _wrap_enhancement_in_batch(enhancement)
    except Exception:
        pass

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
    """Analyze media file to extract dimensions and metadata using common utility."""
    file_path = enhancement.input_file.path
    logger.info(f"[_analyze_media] Starting analysis for: {file_path}")

    try:
        info = get_media_info(file_path)
        logger.info(f"[_analyze_media] get_media_info returned: {info}")
        enhancement.width = info['width']
        enhancement.height = info['height']
        enhancement.duration = info['duration']
        enhancement.file_size = info['file_size']
        enhancement.save(update_fields=['width', 'height', 'duration', 'file_size'])
        logger.info(f"[_analyze_media] Saved: {enhancement.width}x{enhancement.height}")
    except Exception as e:
        logger.error(f"[_analyze_media] FAILED for {file_path}: {e}", exc_info=True)


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

    # Input file may be shared with a duplicate — only delete if no other row references it
    safe_delete_file(enhancement, 'input_file')

    # Output file is unique to this enhancement — delete unconditionally
    if enhancement.output_file:
        try:
            enhancement.output_file.delete(save=False)
        except Exception:
            pass

    enhancement.delete()
    cache.delete(f"enhancer_progress_{pk}")

    return JsonResponse({'deleted': pk})


@require_POST
def duplicate(request, pk: int):
    """Duplicate an Enhancement sharing the same input_file, resetting results."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancement = get_object_or_404(Enhancement, pk=pk, user=user)
    new_e = duplicate_instance(
        enhancement,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'error_message': '',
            'output_width': 0,
            'output_height': 0,
            'output_file_size': 0,
            'processing_time': 0,
        },
        clear_fields=['output_file'],
    )
    # Wrap duplicate in its own batch-of-1
    try:
        _wrap_enhancement_in_batch(new_e)
    except Exception:
        pass
    return JsonResponse({'duplicated': new_e.id})


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


# ===========================================================================
# Batch Enhancement Views (image/video only)
# ===========================================================================

def batch_template(request):
    """Download a batch file template (.txt)."""
    from django.http import HttpResponse
    content = (
        "# WAMA Enhancer - Batch Import\n"
        "# Format : une URL ou chemin de fichier image/vidéo par ligne\n"
        "# Les lignes commençant par # sont des commentaires.\n\n"
        "https://example.com/image.jpg\n"
        "https://example.com/video.mp4\n"
        "/media/uploads/photo.png\n"
    )
    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_enhancer_template.txt"'
    return response


@require_POST
def batch_preview(request):
    """Parse a batch file (one URL/path per line) and return the list for preview."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    from wama.common.app_registry import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

    _img = set(IMAGE_EXTENSIONS)
    _vid = set(VIDEO_EXTENSIONS)

    def _enrich(item):
        ext_item = '.' + item['filename'].rsplit('.', 1)[-1].lower() if '.' in item['filename'] else ''
        if ext_item in _img:
            item['detected_type'] = 'image'
        elif ext_item in _vid:
            item['detected_type'] = 'video'
        else:
            item['detected_type'] = 'media'

    return batch_media_list_preview_response(request, item_enricher=_enrich)


@require_POST
def batch_create(request):
    """Parse batch file (URLs/paths), create BatchEnhancement + Enhancement entries."""
    from wama.common.utils.batch_parsers import parse_batch_file_from_request
    from wama.common.app_registry import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    ai_model = request.POST.get('ai_model', 'RealESR_Gx4')
    denoise_val = request.POST.get('denoise', 'false')
    denoise = denoise_val.lower() in ('1', 'true', 'on')
    try:
        blend_factor = float(request.POST.get('blend_factor', '0'))
    except (ValueError, TypeError):
        blend_factor = 0.0

    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.heic'}
    video_extensions = {'.mp4', '.webm', '.mkv', '.flv', '.gif', '.avi', '.mov', '.mpg', '.qt', '.3gp'}

    batch_file.seek(0)
    batch = BatchEnhancement.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        fname = url_or_path.split('/')[-1].split('\\')[-1] or url_or_path
        ext_item = '.' + fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
        if ext_item in image_extensions:
            media_type = 'image'
        elif ext_item in video_extensions:
            media_type = 'video'
        else:
            media_type = 'image'  # default

        enhancement = Enhancement.objects.create(
            user=user,
            source_url=url_or_path,
            media_type=media_type,
            ai_model=ai_model,
            denoise=denoise,
            blend_factor=blend_factor,
        )
        BatchEnhancementItem.objects.create(batch=batch, enhancement=enhancement, row_index=i)
        created_ids.append(enhancement.id)

    return JsonResponse({
        'batch_id': batch.id,
        'enhancement_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


def batch_list(request):
    """List current user's batches with status counts."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batches = BatchEnhancement.objects.filter(user=user).prefetch_related('items__enhancement')

    data = []
    for batch in batches:
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        for item in batch.items.all():
            if item.enhancement:
                k = item.enhancement.status.lower()
                counts[k] = counts.get(k, 0) + 1

        total = batch.total
        if total > 0 and counts['success'] == total:
            status = 'SUCCESS'
        elif counts['running'] > 0:
            status = 'RUNNING'
        elif counts['pending'] == 0 and counts['running'] == 0 and counts['failure'] > 0:
            status = 'FAILURE'
        else:
            status = 'PENDING'

        data.append({
            'id': batch.id,
            'created_at': batch.created_at.strftime('%d/%m/%Y %H:%M'),
            'total': total,
            'status': status,
            'counts': counts,
        })

    return JsonResponse({'batches': data})


@require_POST
def batch_start(request, pk: int):
    """Start all PENDING enhancements in a batch."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchEnhancement, pk=pk, user=user)

    from .tasks import enhance_media

    started = []
    for item in batch.items.select_related('enhancement').all():
        e = item.enhancement
        if not e or e.status == 'RUNNING':
            continue
        e.status = 'RUNNING'
        e.progress = 0
        e.error_message = ''
        e.save(update_fields=['status', 'progress', 'error_message'])
        cache.set(f"enhancer_progress_{e.id}", 0, timeout=3600)

        task = enhance_media.delay(e.id)
        e.task_id = task.id
        e.status = 'RUNNING'
        e.save(update_fields=['task_id', 'status'])
        started.append(e.id)

    return JsonResponse({'started': started, 'count': len(started)})


def batch_status(request, pk: int):
    """Return status of all items in a batch."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchEnhancement, pk=pk, user=user)

    counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
    items_data = []

    for item in batch.items.select_related('enhancement').all():
        e = item.enhancement
        if not e:
            continue
        key = e.status.lower()
        counts[key] = counts.get(key, 0) + 1
        p = int(cache.get(f"enhancer_progress_{e.id}", e.progress or 0))
        items_data.append({
            'id': e.id,
            'filename': e.get_input_filename() or e.source_url,
            'status': e.status,
            'progress': p,
            'error': e.error_message if e.status == 'FAILURE' else None,
        })

    total = batch.total
    if total > 0 and counts['success'] == total:
        status_str = 'SUCCESS'
    elif counts['running'] > 0:
        status_str = 'RUNNING'
    elif counts['pending'] == 0 and counts['running'] == 0 and counts['failure'] > 0:
        status_str = 'FAILURE'
    else:
        status_str = 'PENDING'

    return JsonResponse({
        'batch_id': pk,
        'status': status_str,
        'total': total,
        'counts': counts,
        'items': items_data,
    })


def batch_download(request, pk: int):
    """Download a ZIP of all completed enhanced files in a batch."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchEnhancement, pk=pk, user=user)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in batch.items.select_related('enhancement').order_by('row_index'):
            e = item.enhancement
            if e and e.status == 'SUCCESS' and e.output_file:
                try:
                    fname = e.get_output_filename()
                    with e.output_file.open('rb') as f:
                        archive.writestr(fname, f.read())
                except Exception:
                    pass

    buffer.seek(0)
    zip_name = f"batch_enhancer_{pk}_{datetime.date.today()}.zip"
    return FileResponse(buffer, as_attachment=True, filename=zip_name)


@require_POST
def batch_delete(request, pk: int):
    """Delete an entire batch: cascade-delete enhancements, clean up files."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchEnhancement, pk=pk, user=user)

    enhancements_to_delete = []
    for item in batch.items.select_related('enhancement').all():
        e = item.enhancement
        if not e:
            continue
        if e.task_id:
            try:
                from celery.result import AsyncResult
                AsyncResult(e.task_id).revoke(terminate=False)
            except Exception:
                pass
        enhancements_to_delete.append(e)

    safe_delete_file(batch, 'batch_file')
    batch.delete()  # CASCADE deletes BatchEnhancementItems (not Enhancement)

    for e in enhancements_to_delete:
        safe_delete_file(e, 'input_file')
        if e.output_file:
            try:
                e.output_file.delete(save=False)
            except Exception:
                pass
        cache.delete(f"enhancer_progress_{e.id}")
        e.delete()

    return JsonResponse({'success': True, 'batch_id': pk})


@require_POST
def batch_duplicate(request, pk: int):
    """Duplicate an entire batch (shares source files, results cleared)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchEnhancement, pk=pk, user=user)

    new_batch = BatchEnhancement.objects.create(user=user, total=batch.total)
    for item in batch.items.select_related('enhancement').order_by('row_index'):
        e = item.enhancement
        if not e:
            continue
        new_e = duplicate_instance(e, reset_fields={
            'status': 'PENDING', 'progress': 0, 'task_id': '',
            'error_message': '', 'output_width': 0, 'output_height': 0,
            'output_file_size': 0, 'processing_time': 0,
        }, clear_fields=['output_file'])
        BatchEnhancementItem.objects.create(batch=new_batch, enhancement=new_e, row_index=item.row_index)

    return JsonResponse({'success': True, 'batch_id': new_batch.id})


# ===========================================================================
# Audio Enhancement Views
# ===========================================================================

_AUDIO_EXTENSIONS = ['.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus', '.wma']


@require_POST
def audio_upload(request):
    """Upload an audio file for speech enhancement, or register from file_path."""
    import json as _json
    from pathlib import Path as _Path
    from django.conf import settings as _settings
    from django.core.files import File as _File

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # --- Option A: file_path from filemanager (server-side path) ---
    file_path = None
    try:
        body = _json.loads(request.body)
        file_path = body.get('file_path', '').strip()
    except Exception:
        pass

    if file_path:
        src = (_Path(_settings.MEDIA_ROOT) / file_path).resolve()
        media_root = _Path(_settings.MEDIA_ROOT).resolve()
        if not str(src).startswith(str(media_root)) or not src.exists():
            return JsonResponse({'error': 'Fichier introuvable ou accès refusé'}, status=400)
        if src.suffix.lower() not in _AUDIO_EXTENSIONS:
            return JsonResponse({'error': f'Format audio non supporté : {src.suffix}'}, status=400)

        try:
            with open(str(src), 'rb') as f:
                django_file = _File(f, name=src.name)
                ae = AudioEnhancement.objects.create(
                    user=user,
                    input_file=django_file,
                    file_size=src.stat().st_size,
                )
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

        _wrap_audio_in_batch(ae)
        return JsonResponse({
            'id': ae.id,
            'input_filename': ae.get_input_filename(),
            'file_size': ae.file_size,
            'duration': ae.duration,
            'status': ae.status,
        })

    # --- Option B: regular file upload ---
    file = request.FILES.get('file')
    if not file:
        return HttpResponseBadRequest('No file provided')

    ext = os.path.splitext(file.name)[1].lower()
    if ext not in _AUDIO_EXTENSIONS:
        return JsonResponse({'error': f'Format audio non supporté : {ext}'}, status=400)

    try:
        ae = AudioEnhancement.objects.create(
            user=user,
            input_file=file,
            file_size=file.size,
        )
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    # Attempt to get duration via ffprobe
    try:
        from ..common.utils.video_utils import get_media_info
        info = get_media_info(ae.input_file.path)
        ae.duration = info.get('duration', 0)
        ae.file_size = info.get('file_size', ae.file_size)
        ae.save(update_fields=['duration', 'file_size'])
    except Exception:
        pass

    _wrap_audio_in_batch(ae)
    return JsonResponse({
        'id': ae.id,
        'input_filename': ae.get_input_filename(),
        'file_size': ae.file_size,
        'duration': ae.duration,
        'status': ae.status,
    })


@require_POST
def audio_start(request, pk: int):
    """Start audio enhancement processing."""
    import json as _json

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    ae = get_object_or_404(AudioEnhancement, pk=pk, user=user)

    try:
        data = _json.loads(request.body) if request.body else {}
    except Exception:
        data = {}

    ae.engine = data.get('engine', ae.engine)
    ae.mode = data.get('mode', ae.mode)
    ae.denoising_strength = float(data.get('denoising_strength', ae.denoising_strength))
    ae.quality = int(data.get('quality', ae.quality))
    ae.save(update_fields=['engine', 'mode', 'denoising_strength', 'quality'])

    from .tasks import enhance_audio

    try:
        task = enhance_audio.delay(pk)
        ae.task_id = task.id
        ae.status = 'RUNNING'
        ae.save(update_fields=['task_id', 'status'])
        return JsonResponse({'task_id': task.id, 'status': 'RUNNING'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def audio_progress(request, pk: int):
    """Get audio enhancement progress."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    ae = get_object_or_404(AudioEnhancement, pk=pk, user=user)
    progress = int(cache.get(f"audio_enhancer_progress_{pk}", ae.progress or 0))
    return JsonResponse({
        'progress': progress,
        'status': ae.status,
        'error_message': ae.error_message,
    })


def audio_download(request, pk: int):
    """Download enhanced audio file."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    ae = get_object_or_404(AudioEnhancement, pk=pk, user=user)

    if not ae.output_file:
        return HttpResponseBadRequest('No output file available')

    from django.core.files.storage import default_storage
    if not default_storage.exists(ae.output_file.name):
        return HttpResponseBadRequest('Output file not found in storage')

    return FileResponse(
        ae.output_file.open('rb'),
        as_attachment=True,
        filename=ae.get_output_filename(),
    )


@require_POST
def audio_delete(request, pk: int):
    """Delete audio enhancement and clean up parent batch-of-1 if empty."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    ae = get_object_or_404(AudioEnhancement, pk=pk, user=user)

    # Capture parent batch before deletion
    parent_batch = None
    try:
        parent_batch = ae.batch_item.batch
    except Exception:
        pass

    # Input may be shared with a duplicate — only delete if no other row references it
    safe_delete_file(ae, 'input_file')

    # Output is unique — delete unconditionally
    if ae.output_file:
        try:
            ae.output_file.delete(save=False)
        except Exception:
            pass

    ae.delete()
    cache.delete(f"audio_enhancer_progress_{pk}")

    # Clean up empty batch container (batch-of-1) after cascade
    if parent_batch and parent_batch.items.count() == 0:
        safe_delete_file(parent_batch, 'batch_file')
        parent_batch.delete()

    return JsonResponse({'deleted': pk})


@require_POST
def audio_duplicate(request, pk: int):
    """Duplicate an AudioEnhancement sharing the same input_file, resetting results."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    ae = get_object_or_404(AudioEnhancement, pk=pk, user=user)
    new_ae = duplicate_instance(
        ae,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'error_message': '',
            'processing_time': 0,
        },
        clear_fields=['output_file'],
    )
    return JsonResponse({'duplicated': new_ae.id})


@require_POST
def audio_start_all(request):
    """Start all pending audio enhancements."""
    import json as _json

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        data = _json.loads(request.body) if request.body else {}
    except Exception:
        data = {}

    global_engine = data.get('engine')
    global_mode = data.get('mode')
    global_strength = data.get('denoising_strength')
    global_quality = data.get('quality')

    from .tasks import enhance_audio

    pending = AudioEnhancement.objects.filter(user=user).exclude(status='RUNNING')
    started, errors = [], []

    for ae in pending:
        try:
            update_fields = []
            if global_engine:
                ae.engine = global_engine
                update_fields.append('engine')
            if global_mode:
                ae.mode = global_mode
                update_fields.append('mode')
            if global_strength is not None:
                ae.denoising_strength = float(global_strength)
                update_fields.append('denoising_strength')
            if global_quality is not None:
                ae.quality = int(global_quality)
                update_fields.append('quality')
            if update_fields:
                ae.save(update_fields=update_fields)

            task = enhance_audio.delay(ae.id)
            ae.task_id = task.id
            ae.status = 'RUNNING'
            ae.save(update_fields=['task_id', 'status'])
            started.append(ae.id)
        except Exception as e:
            errors.append({'id': ae.id, 'error': str(e)})

    return JsonResponse({'started_ids': started, 'count': len(started), 'errors': errors})


@require_POST
def audio_clear_all(request):
    """Clear all audio enhancements and batch containers."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    aes = AudioEnhancement.objects.filter(user=user)
    cleared = []
    for ae in aes:
        cleared.append(ae.id)
        safe_delete_file(ae, 'input_file')
        if ae.output_file:
            try:
                ae.output_file.delete(save=False)
            except Exception:
                pass
        cache.delete(f"audio_enhancer_progress_{ae.id}")
    aes.delete()
    # Clean up orphan batch containers and their files
    batches = BatchAudioEnhancement.objects.filter(user=user)
    for batch in batches:
        safe_delete_file(batch, 'batch_file')
    batches.delete()
    return JsonResponse({'cleared_ids': cleared, 'count': len(cleared)})


def audio_download_all(request):
    """Download all enhanced audio files as ZIP."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    aes = AudioEnhancement.objects.filter(user=user, status='SUCCESS').exclude(output_file='')

    if not aes.exists():
        return HttpResponseBadRequest('No enhanced audio files available')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for ae in aes:
            if ae.output_file:
                try:
                    with ae.output_file.open('rb') as f:
                        archive.writestr(ae.get_output_filename(), f.read())
                except Exception:
                    pass

    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename="enhanced_audio_files.zip")


def audio_global_progress(request):
    """Get overall audio enhancement progress."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    aes = AudioEnhancement.objects.filter(user=user)

    if not aes.exists():
        return JsonResponse({'total': 0, 'pending': 0, 'running': 0, 'success': 0, 'failure': 0, 'overall_progress': 0})

    total = aes.count()
    total_progress = sum(int(cache.get(f"audio_enhancer_progress_{ae.id}", ae.progress or 0)) for ae in aes)

    return JsonResponse({
        'total': total,
        'pending': aes.filter(status='PENDING').count(),
        'running': aes.filter(status='RUNNING').count(),
        'success': aes.filter(status='SUCCESS').count(),
        'failure': aes.filter(status='FAILURE').count(),
        'overall_progress': int(total_progress / total) if total > 0 else 0,
    })


# ===========================================================================
# Audio Batch Views
# ===========================================================================

def audio_batch_template(request):
    """Download a batch file template for audio enhancement."""
    content = (
        "# WAMA Enhancer — Batch Audio Import\n"
        "# Format : une URL ou chemin de fichier audio par ligne\n"
        "# Les lignes commençant par # sont des commentaires.\n"
        "# Formats supportés : MP3, WAV, FLAC, OGG, M4A, AAC, OPUS, WMA\n"
        "\n"
        "https://example.com/audio.mp3\n"
        "/media/uploads/voice.wav\n"
    )
    from django.http import HttpResponse
    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_audio_enhancer_template.txt"'
    return response


@require_POST
def audio_batch_preview(request):
    """Parse a batch file (one audio URL/path per line) and return the list for preview."""
    import tempfile as _tempfile
    batch_file = request.FILES.get('batch_file')
    if not batch_file:
        return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)

    ext = os.path.splitext(batch_file.name)[1][1:].lower()
    from wama.common.utils.batch_parsers import parse_media_list_batch, SUPPORTED_BATCH_EXTENSIONS
    if ext not in SUPPORTED_BATCH_EXTENSIONS:
        return JsonResponse({'error': f'Format non supporté : {ext}'}, status=400)

    tmp_path = None
    try:
        with _tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
            for chunk in batch_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        items, warnings = parse_media_list_batch(tmp_path)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    for item in items:
        path = item['path']
        item['filename'] = path.split('/')[-1].split('\\')[-1] or path

    return JsonResponse({'items': items, 'warnings': warnings, 'count': len(items)})


@require_POST
def audio_batch_create(request):
    """Parse batch file, create BatchAudioEnhancement + AudioEnhancement entries."""
    import tempfile as _tempfile
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch_file = request.FILES.get('batch_file')
    if not batch_file:
        return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)

    ext = os.path.splitext(batch_file.name)[1][1:].lower()
    from wama.common.utils.batch_parsers import parse_media_list_batch, SUPPORTED_BATCH_EXTENSIONS
    if ext not in SUPPORTED_BATCH_EXTENSIONS:
        return JsonResponse({'error': f'Format non supporté : {ext}'}, status=400)

    tmp_path = None
    try:
        with _tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
            for chunk in batch_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        items, warnings = parse_media_list_batch(tmp_path)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    batch_file.seek(0)
    batch = BatchAudioEnhancement.objects.create(user=user, total=len(items), batch_file=batch_file)

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        ae = AudioEnhancement.objects.create(user=user, source_url=url_or_path)
        BatchAudioEnhancementItem.objects.create(batch=batch, audio_enhancement=ae, row_index=i)
        created_ids.append(ae.id)

    return JsonResponse({'batch_id': batch.id, 'audio_ids': created_ids, 'total': len(items), 'warnings': warnings})


@require_POST
def audio_batch_start(request, pk):
    """Start all PENDING audio enhancements in a batch."""
    import json as _json
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchAudioEnhancement, pk=pk, user=user)

    try:
        data = _json.loads(request.body) if request.body else {}
    except Exception:
        data = {}

    from .tasks import enhance_audio
    started = []
    for item in batch.items.select_related('audio_enhancement').all():
        ae = item.audio_enhancement
        if not ae or ae.status == 'RUNNING':
            continue
        if data.get('engine'):
            ae.engine = data['engine']
        if data.get('mode'):
            ae.mode = data['mode']
        if data.get('denoising_strength') is not None:
            ae.denoising_strength = float(data['denoising_strength'])
        if data.get('quality') is not None:
            ae.quality = int(data['quality'])
        ae.status = 'RUNNING'
        ae.progress = 0
        ae.error_message = ''
        ae.save()
        task = enhance_audio.delay(ae.id)
        ae.task_id = task.id
        ae.save(update_fields=['task_id'])
        started.append(ae.id)

    return JsonResponse({'started': started, 'count': len(started)})


def audio_batch_status(request, pk):
    """Return status of all items in an audio batch."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchAudioEnhancement, pk=pk, user=user)

    counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
    items_data = []

    for item in batch.items.select_related('audio_enhancement').all():
        ae = item.audio_enhancement
        if not ae:
            continue
        key = ae.status.lower()
        counts[key] = counts.get(key, 0) + 1
        progress = int(cache.get(f"audio_enhancer_progress_{ae.id}", ae.progress or 0))
        items_data.append({
            'id': ae.id,
            'filename': ae.get_input_filename() or ae.source_url,
            'status': ae.status,
            'progress': progress,
            'error': ae.error_message if ae.status == 'FAILURE' else None,
        })

    total = batch.total
    if total > 0 and counts['success'] == total:
        status_str = 'SUCCESS'
    elif counts['running'] > 0:
        status_str = 'RUNNING'
    elif counts['pending'] == 0 and counts['running'] == 0 and counts['failure'] > 0:
        status_str = 'FAILURE'
    else:
        status_str = 'PENDING'

    return JsonResponse({'batch_id': pk, 'status': status_str, 'total': total, 'counts': counts, 'items': items_data})


def audio_batch_download(request, pk):
    """Download a ZIP of all completed audio enhancements in a batch."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchAudioEnhancement, pk=pk, user=user)

    import datetime as _dt
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in batch.items.select_related('audio_enhancement').order_by('row_index'):
            ae = item.audio_enhancement
            if ae and ae.status == 'SUCCESS' and ae.output_file:
                try:
                    with ae.output_file.open('rb') as f:
                        archive.writestr(ae.get_output_filename(), f.read())
                except Exception:
                    pass

    buffer.seek(0)
    zip_name = f"audio_batch_{pk}_{_dt.date.today()}.zip"
    return FileResponse(buffer, as_attachment=True, filename=zip_name)


@require_POST
def audio_batch_delete(request, pk):
    """Delete an entire audio batch and all its enhancements."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchAudioEnhancement, pk=pk, user=user)

    aes_to_delete = []
    for item in batch.items.select_related('audio_enhancement').all():
        ae = item.audio_enhancement
        if not ae:
            continue
        if ae.task_id:
            try:
                from celery.result import AsyncResult
                AsyncResult(ae.task_id).revoke(terminate=False)
            except Exception:
                pass
        aes_to_delete.append(ae)

    safe_delete_file(batch, 'batch_file')
    batch.delete()

    for ae in aes_to_delete:
        safe_delete_file(ae, 'input_file')
        if ae.output_file:
            try:
                ae.output_file.delete(save=False)
            except Exception:
                pass
        cache.delete(f"audio_enhancer_progress_{ae.id}")
        ae.delete()

    return JsonResponse({'success': True, 'batch_id': pk})


@require_POST
def audio_batch_duplicate(request, pk):
    """Duplicate an entire audio batch (shares source files, results cleared)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchAudioEnhancement, pk=pk, user=user)

    new_batch = BatchAudioEnhancement.objects.create(user=user, total=batch.total)
    for item in batch.items.select_related('audio_enhancement').order_by('row_index'):
        ae = item.audio_enhancement
        if not ae:
            continue
        new_ae = duplicate_instance(ae, reset_fields={
            'status': 'PENDING', 'progress': 0, 'task_id': '',
            'error_message': '', 'processing_time': 0,
        }, clear_fields=['output_file'])
        BatchAudioEnhancementItem.objects.create(batch=new_batch, audio_enhancement=new_ae, row_index=item.row_index)

    return JsonResponse({'success': True, 'batch_id': new_batch.id})


def console_content(request):
    """
    Retourne le contenu de la console (logs Celery + cache).
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Récupère les logs depuis le cache et Celery
    all_lines = get_console_lines(user.id, limit=200)
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
