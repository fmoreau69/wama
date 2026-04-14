"""
WAMA Converter — Views

Endpoints:
  GET  /converter/                  IndexView (queue)
  POST /converter/upload/           upload (create ConversionJob)
  POST /converter/<pk>/start/       start conversion task
  GET  /converter/<pk>/status/      job status JSON
  GET  /converter/<pk>/download/    download output file
  POST /converter/<pk>/delete/      delete job
  POST /converter/<pk>/duplicate/   duplicate job
  POST /converter/start-all/        start all PENDING jobs
  POST /converter/clear-all/        clear all jobs
  POST /converter/quick/            quick conversion (from filemanager / other apps)
"""

import logging
from pathlib import Path

from django.shortcuts import render, get_object_or_404
from django.views import View
from django.http import JsonResponse, FileResponse, Http404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str
from django.core.cache import cache
from django.db import transaction

from .models import ConversionJob, ConversionProfile
from .utils.format_router import detect_media_type, get_output_formats, SUPPORTED_CONVERSIONS
from ..accounts.views import get_or_create_anonymous_user
from ..common.utils.queue_duplication import safe_delete_file, duplicate_instance

logger = logging.getLogger(__name__)


class IndexView(View):
    def get(self, request):
        import json
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
        jobs     = ConversionJob.objects.filter(user=user).order_by('-created_at')
        profiles = ConversionProfile.objects.filter(user=user)

        # Build JS-safe dict: { image: { input: ['.jpg',…], output: ['jpg',…] }, … }
        formats_for_js = {
            media_type: {
                'input':  spec['input'],
                'output': spec['output'],
            }
            for media_type, spec in SUPPORTED_CONVERSIONS.items()
        }

        return render(request, 'converter/index.html', {
            'jobs':                 jobs,
            'profiles':             profiles,
            'supported_formats':    SUPPORTED_CONVERSIONS,
            'supported_formats_json': json.dumps(formats_for_js),
        })


@login_required
@require_POST
def upload(request):
    """Accept a file upload and create a ConversionJob (PENDING)."""
    user        = request.user
    file_obj    = request.FILES.get('file')
    output_fmt  = request.POST.get('output_format', '').strip().lower()

    if not file_obj:
        return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
    if not output_fmt:
        return JsonResponse({'error': 'Format de sortie manquant'}, status=400)

    media_type = detect_media_type(file_obj.name)
    if media_type is None:
        return JsonResponse({'error': f"Format d'entrée non supporté : {file_obj.name}"}, status=400)

    allowed_formats = get_output_formats(media_type)
    if output_fmt not in allowed_formats:
        return JsonResponse({'error': f"Format de sortie non supporté pour {media_type} : {output_fmt}"}, status=400)

    # Parse extra options from POST
    options = {}
    for key in ['quality', 'resize_w', 'resize_h', 'fps', 'video_quality',
                'audio_bitrate', 'gif_fps', 'gif_width', 'normalize',
                'sample_rate', 'channels']:
        if request.POST.get(key):
            val = request.POST[key]
            # Cast booleans
            if val.lower() in ('true', '1'):
                options[key] = True
            elif val.lower() in ('false', '0'):
                options[key] = False
            else:
                try:
                    options[key] = int(val)
                except ValueError:
                    options[key] = val

    job = ConversionJob.objects.create(
        user=user,
        input_file=file_obj,
        input_filename=file_obj.name,
        media_type=media_type,
        output_format=output_fmt,
        options=options,
        status='PENDING',
    )

    return JsonResponse({
        'success':    True,
        'job_id':     job.id,
        'media_type': media_type,
        'filename':   file_obj.name,
        'output_fmt': output_fmt,
    })


@login_required
@require_POST
def start(request, pk):
    """Start (or restart) a ConversionJob."""
    from .tasks import convert_media_task

    with transaction.atomic():
        job = get_object_or_404(
            ConversionJob.objects.select_for_update(), pk=pk, user=request.user
        )
        if job.status == 'RUNNING':
            return JsonResponse({'error': 'Conversion déjà en cours'}, status=400)

        # Revoke previous task if any
        if job.task_id:
            try:
                from celery import current_app
                current_app.control.revoke(job.task_id, terminate=False)
            except Exception:
                pass

        # Clear previous output
        if job.output_file:
            safe_delete_file(job, 'output_file')
            job.output_file = None

        job.status        = 'RUNNING'
        job.task_id       = ''
        job.error_message = ''
        job.progress      = 0
        job.save()

    task    = convert_media_task.delay(job.id)
    job.task_id = task.id
    job.save(update_fields=['task_id'])

    return JsonResponse({'success': True, 'task_id': task.id})


@login_required
def status(request, pk):
    """Return job status JSON."""
    job = get_object_or_404(ConversionJob, pk=pk, user=request.user)
    pct = cache.get(f"converter_progress_{job.id}", job.progress)
    return JsonResponse({
        'status':        job.status,
        'progress':      pct,
        'error_message': job.error_message,
        'output_ready':  bool(job.status == 'DONE' and job.output_file),
        'output_filename': job.output_filename,
    })


@login_required
def download(request, pk):
    """Serve the converted output file."""
    job = get_object_or_404(ConversionJob, pk=pk, user=request.user)
    if not job.output_file:
        raise Http404("Fichier de sortie indisponible")

    try:
        file_path = job.output_file.path
    except Exception:
        raise Http404("Fichier introuvable")

    if not Path(file_path).exists():
        raise Http404("Fichier introuvable sur le disque")

    response = FileResponse(
        open(file_path, 'rb'),
        as_attachment=True,
        filename=smart_str(job.output_filename),
    )
    return response


@login_required
@require_POST
def delete(request, pk):
    """Delete a ConversionJob and its files."""
    job = get_object_or_404(ConversionJob, pk=pk, user=request.user)

    # Output file: unconditional delete
    if job.output_file:
        try:
            Path(job.output_file.path).unlink(missing_ok=True)
        except Exception:
            pass

    # Input file: safe delete (may be shared if duplicated)
    safe_delete_file(job, 'input_file')

    job.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def duplicate(request, pk):
    """Duplicate a ConversionJob (shared input file, no output)."""
    job = get_object_or_404(ConversionJob, pk=pk, user=request.user)
    new_job = duplicate_instance(
        instance=job,
        reset_fields={
            'status':        'PENDING',
            'progress':      0,
            'task_id':       '',
            'error_message': '',
        },
        clear_fields=['output_file'],
    )
    return JsonResponse({'success': True, 'job_id': new_job.id})


@login_required
@require_POST
def start_all(request):
    """Start all PENDING jobs for the current user."""
    from .tasks import convert_media_task

    jobs = ConversionJob.objects.filter(user=request.user, status='PENDING')
    started = []
    for job in jobs:
        try:
            with transaction.atomic():
                job_locked = ConversionJob.objects.select_for_update().get(pk=job.pk, status='PENDING')
                job_locked.status = 'RUNNING'
                job_locked.save()
            task = convert_media_task.delay(job.id)
            job.task_id = task.id
            job.save(update_fields=['task_id'])
            started.append(job.id)
        except ConversionJob.DoesNotExist:
            pass
        except Exception as e:
            logger.exception(f"start_all error for job #{job.id}: {e}")

    return JsonResponse({'success': True, 'started': started})


@login_required
@require_POST
def clear_all(request):
    """Delete all jobs for the current user."""
    jobs = ConversionJob.objects.filter(user=request.user)
    for job in jobs:
        if job.output_file:
            try:
                Path(job.output_file.path).unlink(missing_ok=True)
            except Exception:
                pass
        safe_delete_file(job, 'input_file')
    jobs.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def quick_convert(request):
    """
    Quick conversion endpoint — called from Filemanager or other apps.

    POST params:
        file_path   : absolute server path of the source file
        output_format : target format key (e.g. 'mp4', 'webp')

    Returns immediately with job_id; client polls /converter/<id>/status/.
    The job stays in the converter queue after completion.
    """
    from .tasks import convert_media_task

    file_path_str = request.POST.get('file_path', '').strip()
    output_fmt    = request.POST.get('output_format', '').strip().lower()

    if not file_path_str or not output_fmt:
        return JsonResponse({'error': 'Paramètres manquants'}, status=400)

    from django.conf import settings
    media_root = Path(settings.MEDIA_ROOT).resolve()

    # Accept both absolute paths and MEDIA_ROOT-relative paths (e.g. from FileManager)
    candidate = Path(file_path_str)
    if candidate.is_absolute():
        abs_path = candidate.resolve()
    else:
        # Relative path — treat as relative to MEDIA_ROOT
        abs_path = (media_root / file_path_str).resolve()

    # Security: must stay inside MEDIA_ROOT
    try:
        abs_path.relative_to(media_root)
    except ValueError:
        return JsonResponse({'error': 'Chemin de fichier invalide'}, status=400)

    if not abs_path.exists():
        return JsonResponse({'error': 'Fichier source introuvable'}, status=404)

    media_type = detect_media_type(abs_path.name)
    if media_type is None:
        return JsonResponse({'error': f"Type de fichier non supporté : {abs_path.suffix}"}, status=400)

    if output_fmt not in get_output_formats(media_type):
        return JsonResponse({'error': f"Format de sortie non supporté : {output_fmt}"}, status=400)

    # Create job with a reference to the existing file path (relative to MEDIA_ROOT)
    rel_path = abs_path.relative_to(media_root)

    job = ConversionJob.objects.create(
        user=request.user,
        input_file=str(rel_path),
        input_filename=abs_path.name,
        media_type=media_type,
        output_format=output_fmt,
        status='RUNNING',
    )
    task    = convert_media_task.delay(job.id)
    job.task_id = task.id
    job.save(update_fields=['task_id'])

    return JsonResponse({'success': True, 'job_id': job.id, 'task_id': task.id})
