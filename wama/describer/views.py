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
from wama.common.utils.queue_duplication import duplicate_instance
from ..accounts.views import get_or_create_anonymous_user
from ..common.utils.video_utils import upload_media_from_url


def _fetch_html_as_text(url: str, temp_dir: str) -> str:
    """
    Fetch a web page and save its readable text content as a .txt file.
    Uses BeautifulSoup + lxml to strip markup and extract meaningful content.
    Returns the path to the saved .txt file.
    """
    import re
    import requests
    from urllib.parse import urlparse
    from bs4 import BeautifulSoup

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/122 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'lxml')

    title_tag = soup.find('title')
    title_text = title_tag.get_text(strip=True) if title_tag else ''

    for tag in soup(['script', 'style', 'nav', 'footer', 'aside',
                     'noscript', 'meta', 'link', 'button', 'svg', 'form',
                     'iframe', 'template', 'header']):
        tag.decompose()

    main = (
        soup.find('main') or
        soup.find('article') or
        soup.find(id='readme') or
        soup.find(class_='markdown-body') or
        soup.find(attrs={'role': 'main'}) or
        soup.find(id='content') or
        soup.find(class_='content') or
        soup.body or
        soup
    )

    text = main.get_text(separator='\n', strip=True)
    text = re.sub(r'\n{3,}', '\n\n', text)
    if title_text:
        text = f"# {title_text}\n\n{text}"

    # Build a clean filename from the URL path
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p]
    base = '_'.join(path_parts[-2:]) if len(path_parts) >= 2 else (path_parts[-1] if path_parts else 'page')
    base = re.sub(r'[^\w\-]', '_', base)[:60] or 'page'
    save_path = os.path.join(temp_dir, f"{base}.txt")

    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(text)

    return save_path

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
    """Handle file upload or URL download."""
    user = get_user(request)

    # Check for URL upload first
    media_url = request.POST.get('media_url', '').strip()
    uploaded_file = request.FILES.get('file')

    if not uploaded_file and not media_url:
        return JsonResponse({'error': 'No file or URL provided'}, status=400)

    # Handle URL download
    if media_url and not uploaded_file:
        try:
            import tempfile
            from django.core.files import File

            logger.info(f"[Describer] Downloading media from URL: {media_url}")

            # Download to temp directory
            # For plain HTML pages, extract readable text instead of saving raw markup.
            # Media platform URLs (YouTube, Vimeo, …) serve text/html on HEAD but
            # must go through upload_media_from_url (yt_dlp), so we skip the check for them.
            temp_dir = tempfile.mkdtemp()
            _MEDIA_PLATFORM_DOMAINS = (
                'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com',
                'twitch.tv', 'soundcloud.com', 'bandcamp.com', 'mixcloud.com',
            )
            _is_media_platform = any(d in media_url for d in _MEDIA_PLATFORM_DOMAINS)

            # Also skip check if URL ends with a media file extension
            _MEDIA_EXTS = ('.mp4', '.webm', '.mkv', '.avi', '.mov',
                           '.mp3', '.wav', '.flac', '.ogg', '.m4a',
                           '.jpg', '.jpeg', '.png', '.gif', '.webp')
            _has_media_ext = media_url.lower().split('?')[0].endswith(_MEDIA_EXTS)

            _is_html_page = False
            if not _is_media_platform and not _has_media_ext:
                try:
                    import requests as _req
                    _head = _req.head(media_url, timeout=10, allow_redirects=True,
                                      headers={'User-Agent': 'Mozilla/5.0'})
                    _ct = _head.headers.get('Content-Type', '')
                    _is_html_page = 'text/html' in _ct
                except Exception:
                    pass

            if _is_html_page:
                logger.info(f"[Describer] HTML page detected — extracting text content")
                downloaded_path = _fetch_html_as_text(media_url, temp_dir)
            else:
                downloaded_path = upload_media_from_url(media_url, temp_dir)
                # Post-download: if the file has no extension or an HTML extension,
                # sniff the content and extract text if it looks like HTML.
                _dl_name = os.path.basename(downloaded_path)
                _dl_ext = _dl_name.rsplit('.', 1)[-1].lower() if '.' in _dl_name else ''
                if not _dl_ext or _dl_ext in ('html', 'htm'):
                    try:
                        with open(downloaded_path, 'rb') as _fh:
                            _sample = _fh.read(2048).lower()
                        if b'<html' in _sample or b'<!doctype' in _sample:
                            logger.info(f"[Describer] Downloaded file looks like HTML — extracting text")
                            with open(downloaded_path, 'r', encoding='utf-8', errors='replace') as _fh:
                                _html = _fh.read()
                            from .utils.text_describer import _html_to_readable_text
                            _text = _html_to_readable_text(_html)
                            import re as _re
                            from urllib.parse import urlparse as _urlparse
                            _parts = [p for p in _urlparse(media_url).path.split('/') if p]
                            _base = '_'.join(_parts[-2:]) if len(_parts) >= 2 else (_parts[-1] if _parts else 'page')
                            _base = _re.sub(r'[^\w\-]', '_', _base)[:60] or 'page'
                            _new_path = os.path.join(temp_dir, f"{_base}.txt")
                            with open(_new_path, 'w', encoding='utf-8') as _fh:
                                _fh.write(_text)
                            os.remove(downloaded_path)
                            downloaded_path = _new_path
                        elif not _dl_ext:
                            # Unknown binary/text without extension — add .txt
                            _new_path = downloaded_path + '.txt'
                            os.rename(downloaded_path, _new_path)
                            downloaded_path = _new_path
                    except Exception as _ex:
                        logger.warning(f"[Describer] Post-download sniff failed: {_ex}")
            filename = os.path.basename(downloaded_path)

            logger.info(f"[Describer] Downloaded to: {downloaded_path}")

            # Create the model with the downloaded file
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            detected_type = detect_type_from_extension(ext)

            # Get options from request
            output_format = request.POST.get('output_format', 'detailed')
            output_language = request.POST.get('output_language', 'fr')
            max_length = int(request.POST.get('max_length', 500))

            # Create description with the downloaded file
            with open(downloaded_path, 'rb') as f:
                django_file = File(f, name=filename)
                file_size = os.path.getsize(downloaded_path)

                description = Description.objects.create(
                    user=user,
                    input_file=django_file,
                    filename=filename,
                    file_size=file_size,
                    detected_type=detected_type,
                    output_format=output_format,
                    output_language=output_language,
                    max_length=max_length,
                )

            # Cleanup temp file
            try:
                os.remove(downloaded_path)
                os.rmdir(temp_dir)
            except OSError:
                pass

            # Get file properties
            properties = get_file_properties(description)
            description.properties = properties
            description.save()

            logger.info(f"[Describer] Created Description ID: {description.id}")

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

        except Exception as e:
            logger.error(f"[Describer] URL download failed: {e}")
            return JsonResponse({'error': f'Download failed: {str(e)}'}, status=400)

    # Handle regular file upload
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
        response['summary'] = description.summary or ''
        response['coherence_score'] = description.coherence_score
        response['coherence_notes'] = description.coherence_notes or ''
        response['coherence_suggestion'] = description.coherence_suggestion or ''

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
def duplicate(request, pk):
    """Duplicate a Description sharing the same input file, resetting results."""
    user = get_user(request)
    description = get_object_or_404(Description, pk=pk, user=user)
    new_desc = duplicate_instance(
        description,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'result_text': '',
            'properties': '',
            'error_message': '',
        },
        clear_fields=['result_file'],
    )
    return JsonResponse({'duplicated': new_desc.id})


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
    if 'generate_summary' in data:
        description.generate_summary = bool(data['generate_summary'])
    if 'verify_coherence' in data:
        description.verify_coherence = bool(data['verify_coherence'])

    description.save()

    return JsonResponse({
        'id': description.id,
        'output_format': description.output_format,
        'output_language': description.output_language,
        'max_length': description.max_length,
        'generate_summary': description.generate_summary,
        'verify_coherence': description.verify_coherence,
    })
