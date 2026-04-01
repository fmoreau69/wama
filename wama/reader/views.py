"""
Reader — OCR document views.
"""
import io
import os
import json
import logging
import zipfile
import datetime
import tempfile

from django.shortcuts import render, get_object_or_404
from django.views import View
from django.http import JsonResponse, FileResponse, HttpResponse, HttpResponseBadRequest
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.db import transaction

import re

from .models import ReadingItem, BatchReadingItem, BatchReadingItemLink
from .tasks import read_document_task, _count_pdf_pages, _extract_natural_text
from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.queue_duplication import safe_delete_file, duplicate_instance

logger = logging.getLogger(__name__)


def _compact_preview(text: str, max_chars: int = 400) -> str:
    """Strip markdown syntax and collapse whitespace for card compact preview."""
    if not text:
        return ''
    t = str(text)
    t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\*{1,3}|_{1,3}', '', t)
    t = re.sub(r'^\s*[-*+]\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\|', ' ', t)
    t = re.sub(r'`+', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:max_chars]


ACCEPTED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp', '.bmp'}


def _get_user(request):
    if request.user.is_authenticated:
        return request.user
    return get_or_create_anonymous_user()


def _item_to_dict(item: ReadingItem) -> dict:
    cached = cache.get(f'reader_progress_{item.id}')
    progress = cached.get('pct', item.progress) if cached else item.progress
    progress_msg = cached.get('msg', '') if cached else ''
    return {
        'id': item.id,
        'filename': item.filename,
        'backend': item.backend,
        'mode': item.mode,
        'output_format': item.output_format,
        'language': item.language,
        'status': item.status,
        'progress': progress,
        'progress_msg': progress_msg,
        'page_count': item.page_count,
        'result_preview': _compact_preview(item.result_text) if item.result_text else '',
        'has_result': bool(item.result_text),
        'has_raw_result': bool(item.raw_result),
        'used_backend': item.used_backend,
        'error_message': item.error_message,
        'analysis': item.analysis,
        'created_at': item.created_at.isoformat(),
    }


def _wrap_reading_in_batch(reading):
    """Wrap a standalone ReadingItem in a new BatchReadingItem-of-1."""
    batch = BatchReadingItem.objects.create(user=reading.user, total=1)
    BatchReadingItemLink.objects.create(batch=batch, reading=reading, row_index=0)
    return batch


def _auto_wrap_orphans(user):
    """Wrap any ReadingItem not yet in a batch into a batch-of-1 (called on page load)."""
    existing_ids = set(
        BatchReadingItemLink.objects.filter(batch__user=user)
        .values_list('reading_id', flat=True)
    )
    orphans = ReadingItem.objects.filter(user=user).exclude(id__in=existing_ids)
    for orphan in orphans:
        try:
            _wrap_reading_in_batch(orphan)
        except Exception:
            pass


class IndexView(View):
    def get(self, request):
        user = _get_user(request)

        # Lazily wrap any orphan readings into a batch-of-1
        _auto_wrap_orphans(user)

        # All batches with prefetched items+reading
        batches_qs = BatchReadingItem.objects.filter(user=user).prefetch_related(
            'items__reading'
        ).order_by('-id')

        batches_list = []
        for batch in batches_qs:
            items = list(batch.items.all())
            success_count = sum(1 for i in items if i.reading and i.reading.status == 'DONE')
            first_reading = next((i.reading for i in items if i.reading), None)
            batches_list.append({
                'obj': batch,
                'items': items,
                'success_count': success_count,
                'success_pct': int(success_count / batch.total * 100) if batch.total > 0 else 0,
                'has_success': success_count > 0,
                'first_backend': first_reading.backend if first_reading else '',
                'first_mode': first_reading.mode if first_reading else '',
                'first_language': first_reading.language if first_reading else '',
            })

        # Multi-item batches first, then single-item batches
        batches_list.sort(key=lambda b: 0 if b['obj'].total > 1 else 1)

        queue_count = sum(len(b['items']) for b in batches_list)

        return render(request, 'reader/index.html', {
            'batches_list': batches_list,
            'queue_count': queue_count,
            'backend_choices': ReadingItem.Backend.choices,
            'mode_choices': ReadingItem.Mode.choices,
            'format_choices': ReadingItem.OutputFormat.choices,
        })


@require_POST
def upload(request):
    """Upload one or more files to the reading queue."""
    user = _get_user(request)
    files = request.FILES.getlist('files')
    if not files:
        return JsonResponse({'error': 'Aucun fichier reçu'}, status=400)

    backend       = request.POST.get('backend', 'auto')
    mode          = request.POST.get('mode', 'auto')
    output_format = request.POST.get('output_format', 'txt')
    language      = request.POST.get('language', '')

    items_created = []
    created = []
    for f in files:
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in ACCEPTED_EXTENSIONS:
            continue  # skip unsupported types silently

        item = ReadingItem.objects.create(
            user=user,
            input_file=f,
            original_filename=f.name,
            backend=backend,
            mode=mode,
            output_format=output_format,
            language=language,
            status='PENDING',
        )

        # Count PDF pages immediately (quick, synchronous)
        if ext == '.pdf':
            try:
                n = _count_pdf_pages(item.input_file.path)
                if n:
                    item.page_count = n
                    item.save(update_fields=['page_count'])
            except Exception:
                pass

        items_created.append(item)
        created.append(_item_to_dict(item))

    if not items_created:
        return JsonResponse({'created': []})

    if len(items_created) > 1:
        # Multiple files → one multi-item batch
        batch = BatchReadingItem.objects.create(user=user, total=len(items_created))
        for i, item in enumerate(items_created):
            BatchReadingItemLink.objects.create(batch=batch, reading=item, row_index=i)
        return JsonResponse({'created': created, 'batch_id': batch.id, 'multi': True})
    else:
        _wrap_reading_in_batch(items_created[0])
        return JsonResponse({'created': created})


@require_POST
def start(request, pk: int):
    """Start OCR processing for a single item (anti-race-condition)."""
    user = _get_user(request)

    with transaction.atomic():
        item = get_object_or_404(
            ReadingItem.objects.select_for_update(), pk=pk, user=user
        )
        if item.status == 'RUNNING':
            return JsonResponse({'error': 'Déjà en cours'}, status=409)

        # Revoke any stale task
        if item.task_id:
            try:
                from celery import current_app
                current_app.control.revoke(item.task_id, terminate=False)
            except Exception:
                pass

        item.status = 'RUNNING'
        item.task_id = ''
        item.result_text = ''
        item.raw_result = ''
        item.error_message = ''
        item.progress = 0
        item.save()

    task = read_document_task.delay(item.id)
    item.task_id = task.id
    item.save(update_fields=['task_id'])

    return JsonResponse({'ok': True, 'task_id': task.id})


def progress(request, pk: int):
    """Poll the current processing status of an item."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))
    return JsonResponse(_item_to_dict(item))


def text_view(request, pk: int):
    """Return the full extracted text as JSON (used by the in-page full-text modal)."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))
    return JsonResponse({'text': _extract_natural_text(item.result_text) or '', 'filename': item.filename})


def download(request, pk: int):
    """Download the OCR result. Supported formats: txt (default), md, pdf, docx, json."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))

    fmt = request.GET.get('format', 'txt').lower()
    base = os.path.splitext(item.filename)[0]

    # JSON format — serve raw backend output
    if fmt == 'json':
        if not item.raw_result:
            return HttpResponseBadRequest('Pas de données JSON disponibles')
        buffer = io.BytesIO(item.raw_result.encode('utf-8'))
        buffer.seek(0)
        return FileResponse(
            buffer,
            as_attachment=True,
            filename=f"{base}_ocr_raw.json",
            content_type='application/json; charset=utf-8',
        )

    if not item.result_text:
        return HttpResponseBadRequest('Pas encore de résultat')

    if fmt == 'pdf':
        try:
            from wama.common.utils.document_export import generate_reader_pdf
            pdf_bytes = generate_reader_pdf(item)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{base}_ocr.pdf"'
            return response
        except ImportError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            logger.error(f"[Reader] PDF generation failed: {e}")
            return HttpResponseBadRequest(f'Erreur PDF : {e}')

    if fmt == 'docx':
        try:
            from wama.common.utils.document_export import generate_reader_docx
            docx_bytes = generate_reader_docx(item)
            response = HttpResponse(
                docx_bytes,
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            )
            response['Content-Disposition'] = f'attachment; filename="{base}_ocr.docx"'
            return response
        except ImportError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            logger.error(f"[Reader] DOCX generation failed: {e}")
            return HttpResponseBadRequest(f'Erreur DOCX : {e}')

    # txt / md (default)
    is_md = (fmt == 'md')
    ext = '.md' if is_md else '.txt'
    content_type = 'text/markdown' if is_md else 'text/plain'
    buffer = io.BytesIO(_extract_natural_text(item.result_text).encode('utf-8'))
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"{base}_ocr{ext}",
        content_type=f'{content_type}; charset=utf-8',
    )


@require_POST
def delete(request, pk: int):
    """Delete an item and its input file (if not shared). Also removes parent batch-of-1."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))
    # Capture parent batch before deletion
    parent_batch = None
    try:
        link = item.batch_item
        parent_batch = link.batch
    except Exception:
        pass
    safe_delete_file(item, 'input_file')
    cache.delete(f'reader_progress_{pk}')
    item.delete()
    # Clean up empty batch container (batch-of-1) after cascade
    if parent_batch and parent_batch.items.count() == 0:
        safe_delete_file(parent_batch, 'batch_file')
        parent_batch.delete()
    return JsonResponse({'deleted': pk})


@require_POST
def duplicate(request, pk: int):
    """Duplicate an item, sharing the input file but resetting all results."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))
    new_item = duplicate_instance(
        item,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'result_text': '',
            'used_backend': '',
            'error_message': '',
        },
    )
    return JsonResponse(_item_to_dict(new_item))


@require_POST
def start_all(request):
    """Start all PENDING items for the current user."""
    user = _get_user(request)
    items = ReadingItem.objects.filter(user=user, status='PENDING').order_by('-created_at')
    count = 0
    for item in items:
        try:
            task = read_document_task.delay(item.id)
            item.task_id = task.id
            item.status = 'RUNNING'
            item.save(update_fields=['task_id', 'status'])
            count += 1
        except Exception as e:
            logger.error(f"[Reader] start_all error on {item.id}: {e}")
    return JsonResponse({'started': count})



def download_all(request):
    """Download a ZIP of all completed OCR results for the current user."""
    from io import BytesIO
    user = _get_user(request)
    items = ReadingItem.objects.filter(user=user, status='DONE')
    if not items.exists():
        return JsonResponse({'error': 'Aucun résultat disponible'}, status=400)

    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            base = os.path.splitext(item.original_filename)[0] if '.' in (item.original_filename or '') else (item.original_filename or f'item_{item.id}')
            if item.result_text:
                ext = '.md' if item.output_format == 'markdown' else '.txt'
                zf.writestr(f'{base}_ocr{ext}', item.result_text.encode('utf-8'))
    buf.seek(0)
    response = HttpResponse(buf.read(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="reader_results.zip"'
    return response


@require_POST
def clear_all(request):
    """Delete all items and batches for the current user."""
    user = _get_user(request)
    items = ReadingItem.objects.filter(user=user)
    for item in items:
        safe_delete_file(item, 'input_file')
        cache.delete(f'reader_progress_{item.id}')
    items.delete()
    # Clean up orphan batch containers and their files
    batches = BatchReadingItem.objects.filter(user=user)
    for batch in batches:
        safe_delete_file(batch, 'batch_file')
    batches.delete()
    return JsonResponse({'ok': True})


@require_POST
def save_settings(request, pk: int):
    """Update per-item OCR settings (backend, mode, output_format, language)."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    allowed_backends = [c[0] for c in ReadingItem.Backend.choices]
    allowed_modes    = [c[0] for c in ReadingItem.Mode.choices]
    allowed_formats  = [c[0] for c in ReadingItem.OutputFormat.choices]

    if 'backend' in data and data['backend'] in allowed_backends:
        item.backend = data['backend']
    if 'mode' in data and data['mode'] in allowed_modes:
        item.mode = data['mode']
    if 'output_format' in data and data['output_format'] in allowed_formats:
        item.output_format = data['output_format']
    if 'language' in data:
        item.language = data['language'].strip()[:16]

    item.save(update_fields=['backend', 'mode', 'output_format', 'language'])
    return JsonResponse(_item_to_dict(item))


@require_POST
def analyze(request, pk: int):
    """Lance une analyse LLM (résumé + points clés) sur le texte OCR extrait."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))

    if not item.result_text:
        return JsonResponse({'error': 'Pas encore de texte extrait'}, status=400)

    from .tasks import analyze_document_task
    task = analyze_document_task.delay(item.id)
    return JsonResponse({'ok': True, 'task_id': task.id})


def batch_template(request):
    """Download a batch file template (.txt)."""
    template_content = (
        "# WAMA Reader - Batch Import\n"
        "# Format : une URL ou chemin de fichier par ligne\n"
        "# Les lignes commençant par # sont des commentaires.\n"
        "# Formats supportés : PDF, JPG, PNG, TIFF, WebP\n"
        "\n"
        "https://example.com/document.pdf\n"
        "/media/uploads/scan.jpg\n"
    )
    response = HttpResponse(template_content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_reader_template.txt"'
    return response


@require_POST
def batch_preview(request):
    """Parse a batch file (one URL/path per line) and return the list for preview."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    return batch_media_list_preview_response(request)


@require_POST
def batch_create(request):
    """
    Parse batch file (URLs/paths), create BatchReadingItem + ReadingItem entries.
    Files are not downloaded yet — download happens when each task starts.
    """
    from wama.common.utils.batch_parsers import parse_batch_file_from_request

    user = _get_user(request)
    backend = request.POST.get('backend', 'auto')
    mode = request.POST.get('mode', 'auto')
    output_format = request.POST.get('output_format', 'txt')
    language = request.POST.get('language', '')

    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    batch_file = request.FILES.get('batch_file')
    batch = BatchReadingItem.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        fname = url_or_path.split('/')[-1].split('\\')[-1] or url_or_path

        reading = ReadingItem.objects.create(
            user=user,
            source_url=url_or_path,
            original_filename=fname,
            backend=backend,
            mode=mode,
            output_format=output_format,
            language=language,
            status='PENDING',
        )
        BatchReadingItemLink.objects.create(batch=batch, reading=reading, row_index=i)
        created_ids.append(reading.id)

    return JsonResponse({
        'batch_id': batch.id,
        'reading_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


def batch_list(request):
    """List the current user's batches with status counts."""
    user = _get_user(request)
    batches = BatchReadingItem.objects.filter(user=user).prefetch_related('items__reading')

    data = []
    for batch in batches:
        counts = {'done': 0, 'running': 0, 'pending': 0, 'error': 0}
        for item in batch.items.all():
            if item.reading:
                k = item.reading.status.lower()
                counts[k] = counts.get(k, 0) + 1

        total = batch.total
        if total > 0 and counts['done'] == total:
            status = 'DONE'
        elif counts['running'] > 0:
            status = 'RUNNING'
        elif counts['pending'] == 0 and counts['running'] == 0 and counts['error'] > 0:
            status = 'ERROR'
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
def batch_start(request, pk):
    """Start all PENDING readings in a batch."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)

    started = []
    for item in batch.items.select_related('reading').all():
        r = item.reading
        if not r or r.status == 'RUNNING':
            continue
        r.status = 'RUNNING'
        r.progress = 0
        r.result_text = ''
        r.raw_result = ''
        r.error_message = ''
        r.save(update_fields=['status', 'progress', 'result_text', 'raw_result', 'error_message'])

        task = read_document_task.delay(r.id)
        r.task_id = task.id
        r.save(update_fields=['task_id'])
        started.append(r.id)

    return JsonResponse({'started': started, 'count': len(started)})


def batch_status(request, pk):
    """Return status of all items in a batch."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)

    counts = {'done': 0, 'running': 0, 'pending': 0, 'error': 0}
    items_data = []

    for item in batch.items.select_related('reading').all():
        r = item.reading
        if not r:
            continue
        key = r.status.lower()
        counts[key] = counts.get(key, 0) + 1
        cached = cache.get(f'reader_progress_{r.id}')
        p = cached.get('pct', r.progress) if cached else r.progress
        items_data.append({
            'id': r.id,
            'filename': r.filename,
            'status': r.status,
            'progress': p,
            'error': r.error_message if r.status == 'ERROR' else None,
        })

    total = batch.total
    if total > 0 and counts['done'] == total:
        status_str = 'DONE'
    elif counts['running'] > 0:
        status_str = 'RUNNING'
    elif counts['pending'] == 0 and counts['running'] == 0 and counts['error'] > 0:
        status_str = 'ERROR'
    else:
        status_str = 'PENDING'

    return JsonResponse({
        'batch_id': pk,
        'status': status_str,
        'total': total,
        'counts': counts,
        'items': items_data,
    })


def batch_download(request, pk):
    """Download a ZIP of all completed OCR results in a batch."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in batch.items.select_related('reading').order_by('row_index'):
            r = item.reading
            if r and r.status == 'DONE' and r.result_text:
                ext = '.md' if r.output_format == 'markdown' else '.txt'
                stem = os.path.splitext(r.filename)[0] if r.filename else f'item_{r.id}'
                archive.writestr(f'{stem}_ocr{ext}', r.result_text.encode('utf-8'))

    buffer.seek(0)
    zip_name = f"batch_reader_{pk}_{datetime.date.today()}.zip"
    return FileResponse(buffer, as_attachment=True, filename=zip_name)


@require_POST
def batch_delete(request, pk):
    """Delete an entire batch: cascade-delete readings, clean up files."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)

    readings_to_delete = []
    for item in batch.items.select_related('reading').all():
        r = item.reading
        if not r:
            continue
        if r.task_id:
            try:
                from celery.result import AsyncResult
                AsyncResult(r.task_id).revoke(terminate=False)
            except Exception:
                pass
        readings_to_delete.append(r)

    safe_delete_file(batch, 'batch_file')
    batch.delete()  # CASCADE deletes BatchReadingItemLinks (not ReadingItem)

    for r in readings_to_delete:
        safe_delete_file(r, 'input_file')
        cache.delete(f'reader_progress_{r.id}')
        r.delete()

    return JsonResponse({'success': True, 'batch_id': pk})


@require_POST
def batch_duplicate(request, pk):
    """Duplicate an entire batch (shares source files/URLs, results cleared)."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)

    new_batch = BatchReadingItem.objects.create(user=user, total=batch.total)
    for item in batch.items.select_related('reading').order_by('row_index'):
        r = item.reading
        if not r:
            continue
        new_r = duplicate_instance(r, reset_fields={
            'status': 'PENDING', 'progress': 0, 'task_id': '',
            'result_text': '', 'used_backend': '', 'error_message': '',
        })
        BatchReadingItemLink.objects.create(batch=new_batch, reading=new_r, row_index=item.row_index)

    return JsonResponse({'success': True, 'batch_id': new_batch.id})


@require_POST
def batch_update(request, pk):
    """Update backend/mode/language on all non-RUNNING items in a batch."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    backend = data.get('backend', '')
    mode = data.get('mode', '')
    language = data.get('language', '')

    updated = 0
    for item in batch.items.select_related('reading').all():
        r = item.reading
        if not r or r.status == 'RUNNING':
            continue
        r.backend = backend
        r.mode = mode
        r.language = language
        r.save(update_fields=['backend', 'mode', 'language'])
        updated += 1

    return JsonResponse({'success': True, 'updated': updated})


def console_content(request):
    user = _get_user(request)
    lines = get_console_lines(user.id)
    return JsonResponse({'lines': lines})


def global_progress(request):
    """Overall reading progress for all items of the current user."""
    user = _get_user(request)
    items = ReadingItem.objects.filter(user=user)
    total = items.count()
    if total == 0:
        return JsonResponse({'total': 0, 'done': 0, 'running': 0, 'pending': 0,
                             'error': 0, 'overall_progress': 0})
    done    = items.filter(status='DONE').count()
    running = items.filter(status='RUNNING').count()
    pending = items.filter(status='PENDING').count()
    error   = items.filter(status='ERROR').count()
    if done == total:
        overall_progress = 100
    else:
        total_progress = sum(i.progress for i in items)
        overall_progress = int(total_progress / total)
    return JsonResponse({
        'total': total,
        'done': done,
        'running': running,
        'pending': pending,
        'error': error,
        'overall_progress': overall_progress,
    })
