"""
WAMA Describer - Views
AI-powered content description and summarization
"""

import os
import json
import logging
import mimetypes
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.generic import TemplateView
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.conf import settings

from .models import Description
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)


def get_user(request):
    """Get authenticated user or anonymous user."""
    if request.user.is_authenticated:
        return request.user
    return get_or_create_anonymous_user()


class IndexView(TemplateView):
    """Main page with file queue."""
    template_name = 'describer/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = get_user(self.request)

        # Get all descriptions for this user
        descriptions = Description.objects.filter(user=user)

        context['descriptions'] = descriptions
        context['output_format_choices'] = Description.OUTPUT_FORMAT_CHOICES
        context['language_choices'] = Description.LANGUAGE_CHOICES
        context['pending_count'] = descriptions.filter(status='PENDING').count()
        context['running_count'] = descriptions.filter(status='RUNNING').count()
        context['success_count'] = descriptions.filter(status='SUCCESS').count()
        context['failure_count'] = descriptions.filter(status='FAILURE').count()

        return context


@require_POST
def upload(request):
    """Handle file upload."""
    user = get_user(request)

    if 'file' not in request.FILES:
        return JsonResponse({'error': 'No file provided'}, status=400)

    uploaded_file = request.FILES['file']
    filename = uploaded_file.name

    # Detect content type from extension
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    detected_type = detect_type_from_extension(ext)

    # Get options from request
    output_format = request.POST.get('output_format', 'detailed')
    output_language = request.POST.get('output_language', 'fr')
    max_length = int(request.POST.get('max_length', 500))

    # Create description record
    description = Description.objects.create(
        user=user,
        input_file=uploaded_file,
        filename=filename,
        file_size=uploaded_file.size,
        detected_type=detected_type,
        output_format=output_format,
        output_language=output_language,
        max_length=max_length,
    )

    # Get file properties
    properties = get_file_properties(description)
    description.properties = properties
    description.save()

    return JsonResponse({
        'id': description.id,
        'filename': description.filename,
        'file_size': description.format_file_size(),
        'detected_type': description.detected_type,
        'type_icon': description.get_type_icon(),
        'output_format': description.output_format,
        'output_language': description.output_language,
        'max_length': description.max_length,
        'status': description.status,
        'properties': description.properties,
    })


def detect_type_from_extension(ext):
    """Detect content type from file extension."""
    image_exts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
    video_exts = ['mp4', 'avi', 'mov', 'mkv', 'webm']
    audio_exts = ['mp3', 'wav', 'flac', 'ogg', 'm4a']
    text_exts = ['txt', 'md', 'csv', 'docx']
    pdf_exts = ['pdf']

    if ext in image_exts:
        return 'image'
    elif ext in video_exts:
        return 'video'
    elif ext in audio_exts:
        return 'audio'
    elif ext in pdf_exts:
        return 'pdf'
    elif ext in text_exts:
        return 'text'
    return 'text'  # Default to text


def get_file_properties(description):
    """Get file properties string."""
    ext = description.filename.rsplit('.', 1)[-1].lower() if '.' in description.filename else ''
    size = description.format_file_size()

    if description.detected_type == 'image':
        try:
            from PIL import Image
            with Image.open(description.input_file.path) as img:
                return f"{img.width}x{img.height} - {size}"
        except:
            pass
    elif description.detected_type in ('video', 'audio'):
        try:
            import subprocess
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', description.input_file.path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                duration = float(result.stdout.strip())
                description.duration_seconds = duration
                mins = int(duration // 60)
                secs = int(duration % 60)
                description.duration_display = f"{mins}:{secs:02d}"
                return f"{description.duration_display} - {size}"
        except:
            pass

    return f"{ext.upper()} - {size}"


@require_POST
def start(request, pk):
    """Start processing a description."""
    user = get_user(request)
    description = get_object_or_404(Description, pk=pk, user=user)

    if description.status == 'RUNNING':
        return JsonResponse({'error': 'Already running'}, status=400)

    # Import and launch Celery task
    from .workers import describe_content

    description.status = 'RUNNING'
    description.progress = 0
    description.error_message = ''
    description.save()

    task = describe_content.delay(description.id)
    description.task_id = task.id
    description.save()

    return JsonResponse({
        'id': description.id,
        'task_id': task.id,
        'status': 'RUNNING',
    })


@require_GET
def progress(request, pk):
    """Get processing progress."""
    user = get_user(request)
    description = get_object_or_404(Description, pk=pk, user=user)

    # Get progress from cache or model
    cache_key = f"describer_progress_{description.id}"
    progress = cache.get(cache_key, description.progress)

    # Get partial result if available
    partial_key = f"describer_partial_{description.id}"
    partial_text = cache.get(partial_key, '')

    response = {
        'id': description.id,
        'progress': progress,
        'status': description.status,
        'partial_text': partial_text,
    }

    if description.status == 'SUCCESS':
        response['result_text'] = description.result_text
        if description.result_file:
            response['result_url'] = description.result_file.url

    if description.status == 'FAILURE':
        response['error'] = description.error_message

    return JsonResponse(response)


@require_GET
def download(request, pk):
    """Download result file."""
    user = get_user(request)
    description = get_object_or_404(Description, pk=pk, user=user)

    if description.status != 'SUCCESS':
        return JsonResponse({'error': 'No result available'}, status=400)

    # If result file exists, return it
    if description.result_file and os.path.exists(description.result_file.path):
        return FileResponse(
            open(description.result_file.path, 'rb'),
            as_attachment=True,
            filename=description.result_file.name.split('/')[-1]
        )

    # Otherwise, create a text file from result_text
    if description.result_text:
        base_name = description.filename.rsplit('.', 1)[0] if '.' in description.filename else description.filename
        content = description.result_text.encode('utf-8')
        response = HttpResponse(content, content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{base_name}_description.txt"'
        return response

    return JsonResponse({'error': 'No result available'}, status=400)


@require_POST
def delete(request, pk):
    """Delete a description."""
    user = get_user(request)
    description = get_object_or_404(Description, pk=pk, user=user)

    # Delete files
    if description.input_file and os.path.exists(description.input_file.path):
        try:
            os.remove(description.input_file.path)
        except OSError:
            pass

    if description.result_file and os.path.exists(description.result_file.path):
        try:
            os.remove(description.result_file.path)
        except OSError:
            pass

    description.delete()

    return JsonResponse({'deleted': True, 'id': pk})


@require_GET
def preview(request, pk):
    """Get file preview."""
    user = get_user(request)
    description = get_object_or_404(Description, pk=pk, user=user)

    response = {
        'id': description.id,
        'filename': description.filename,
        'detected_type': description.detected_type,
    }

    if description.input_file:
        response['input_url'] = description.input_file.url

    if description.result_text:
        response['result_text'] = description.result_text[:2000]  # Limit preview

    return JsonResponse(response)


@require_POST
def start_all(request):
    """Start all pending descriptions."""
    user = get_user(request)
    pending = Description.objects.filter(user=user, status='PENDING')

    from .workers import describe_content

    started = []
    for description in pending:
        description.status = 'RUNNING'
        description.progress = 0
        description.save()

        task = describe_content.delay(description.id)
        description.task_id = task.id
        description.save()

        started.append(description.id)

    return JsonResponse({'started': started, 'count': len(started)})


@require_POST
def clear_all(request):
    """Delete all descriptions."""
    user = get_user(request)
    descriptions = Description.objects.filter(user=user)

    count = descriptions.count()

    for desc in descriptions:
        if desc.input_file and os.path.exists(desc.input_file.path):
            try:
                os.remove(desc.input_file.path)
            except OSError:
                pass
        if desc.result_file and os.path.exists(desc.result_file.path):
            try:
                os.remove(desc.result_file.path)
            except OSError:
                pass

    descriptions.delete()

    return JsonResponse({'deleted': count})


@require_GET
def download_all(request):
    """Download all results as ZIP."""
    user = get_user(request)
    descriptions = Description.objects.filter(user=user, status='SUCCESS')

    if not descriptions.exists():
        return JsonResponse({'error': 'No results available'}, status=400)

    # Create ZIP in memory
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as zf:
        for desc in descriptions:
            base_name = desc.filename.rsplit('.', 1)[0] if '.' in desc.filename else desc.filename

            if desc.result_file and os.path.exists(desc.result_file.path):
                zf.write(desc.result_file.path, f"{base_name}_description.txt")
            elif desc.result_text:
                zf.writestr(f"{base_name}_description.txt", desc.result_text.encode('utf-8'))

    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="descriptions.zip"'
    return response


@require_GET
def console_content(request):
    """Get console output for live display."""
    user = get_user(request)
    cache_key = f"describer_console_{user.id}"
    lines = cache.get(cache_key, [])
    return JsonResponse({'lines': lines})


@require_GET
def global_progress(request):
    """Get global progress stats."""
    user = get_user(request)
    descriptions = Description.objects.filter(user=user)

    total = descriptions.count()
    pending = descriptions.filter(status='PENDING').count()
    running = descriptions.filter(status='RUNNING').count()
    success = descriptions.filter(status='SUCCESS').count()
    failure = descriptions.filter(status='FAILURE').count()

    # Calculate overall progress
    if total == 0:
        overall = 0
    else:
        # Each completed = 100%, running = current progress
        running_progress = 0
        for desc in descriptions.filter(status='RUNNING'):
            cache_key = f"describer_progress_{desc.id}"
            running_progress += cache.get(cache_key, desc.progress)

        overall = int(((success * 100) + running_progress) / total)

    return JsonResponse({
        'total': total,
        'pending': pending,
        'running': running,
        'success': success,
        'failure': failure,
        'overall_progress': overall,
    })


@require_POST
def update_options(request, pk):
    """Update description options."""
    user = get_user(request)
    description = get_object_or_404(Description, pk=pk, user=user)

    if description.status == 'RUNNING':
        return JsonResponse({'error': 'Cannot update while running'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST

    if 'output_format' in data:
        description.output_format = data['output_format']
    if 'output_language' in data:
        description.output_language = data['output_language']
    if 'max_length' in data:
        description.max_length = int(data['max_length'])

    description.save()

    return JsonResponse({
        'id': description.id,
        'output_format': description.output_format,
        'output_language': description.output_language,
        'max_length': description.max_length,
    })
