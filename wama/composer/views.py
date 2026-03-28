"""
Composer Views — Music and SFX generation.
"""

import json
import logging
import os

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_POST, require_GET

from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.queue_duplication import safe_delete_file, duplicate_instance
from .models import ComposerBatch, ComposerBatchItem, ComposerGeneration
from .utils.model_config import COMPOSER_MODELS, MUSIC_MODELS, SFX_MODELS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrap_generation_in_batch(generation: ComposerGeneration) -> ComposerBatch:
    """Wrap a standalone ComposerGeneration in a new ComposerBatch-of-1."""
    stem = os.path.splitext(generation.prompt[:30].replace(' ', '_'))[0]
    output_filename = f"{stem}_{generation.id}.wav"
    batch = ComposerBatch.objects.create(user=generation.user, total=1)
    ComposerBatchItem.objects.create(
        batch=batch,
        generation=generation,
        output_filename=output_filename,
        row_index=0,
    )
    return batch


def _auto_wrap_orphans(user):
    """Lazily wrap any ComposerGeneration not yet in a batch on page load."""
    existing_ids = set(
        ComposerBatchItem.objects.filter(batch__user=user)
        .values_list('generation_id', flat=True)
    )
    orphans = ComposerGeneration.objects.filter(user=user).exclude(id__in=existing_ids)
    for orphan in orphans:
        try:
            _wrap_generation_in_batch(orphan)
        except Exception:
            pass


def _get_batches_list(user):
    """Return list of dicts with batch info for the template."""
    _auto_wrap_orphans(user)

    batches = ComposerBatch.objects.filter(user=user).prefetch_related(
        'items__generation'
    ).order_by('-created_at')

    result = []
    for batch in batches:
        items = list(batch.items.select_related('generation').order_by('row_index'))
        result.append({'obj': batch, 'items': items})
    return result


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

@method_decorator(login_required, name='dispatch')
class IndexView(View):
    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        batches_list = _get_batches_list(user)
        queue_count = sum(
            1 for b in batches_list
            for item in b['items']
            if item.generation and item.generation.status in ('PENDING', 'RUNNING')
        )

        return render(request, 'composer/index.html', {
            'batches_list': batches_list,
            'queue_count': queue_count,
            'music_models': MUSIC_MODELS,
            'sfx_models': SFX_MODELS,
            'all_models': COMPOSER_MODELS,
        })


# ---------------------------------------------------------------------------
# Generate single item
# ---------------------------------------------------------------------------

@login_required
@require_POST
def generate(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    prompt = request.POST.get('prompt', '').strip()
    if not prompt:
        return JsonResponse({'error': 'Prompt requis'}, status=400)

    model_id = request.POST.get('model', 'musicgen-small')
    if model_id not in COMPOSER_MODELS:
        return JsonResponse({'error': 'Modèle invalide'}, status=400)

    try:
        duration = float(request.POST.get('duration', 10))
        duration = max(10.0, min(300.0, duration))
    except (ValueError, TypeError):
        duration = 10.0

    generation_type = COMPOSER_MODELS[model_id]['type']

    gen = ComposerGeneration.objects.create(
        user=user,
        generation_type=generation_type,
        prompt=prompt,
        model=model_id,
        duration=duration,
    )

    # Melody reference (musicgen-melody only)
    if model_id == 'musicgen-melody' and 'melody_reference' in request.FILES:
        gen.melody_reference = request.FILES['melody_reference']
        gen.save(update_fields=['melody_reference'])

    # Wrap in batch-of-1
    _wrap_generation_in_batch(gen)

    # Launch Celery task
    from .tasks import compose_task
    task = compose_task.apply_async(args=(gen.id,))
    gen.task_id = task.id
    gen.save(update_fields=['task_id'])

    return JsonResponse({
        'id': gen.id,
        'status': gen.status,
        'model': gen.model,
        'model_label': gen.get_model_label(),
        'generation_type': gen.generation_type,
        'prompt': gen.prompt,
        'duration': gen.duration,
    })


# ---------------------------------------------------------------------------
# Import batch file
# ---------------------------------------------------------------------------

@login_required
@require_POST
def import_batch(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    if 'batch_file' not in request.FILES:
        return JsonResponse({'error': 'Aucun fichier batch fourni'}, status=400)

    batch_file = request.FILES['batch_file']

    # Default params for items without explicit model/duration
    default_model = request.POST.get('default_model', 'musicgen-small')
    if default_model not in COMPOSER_MODELS:
        default_model = 'musicgen-small'
    try:
        default_duration = float(request.POST.get('default_duration', 10))
        default_duration = max(10.0, min(300.0, default_duration))
    except (ValueError, TypeError):
        default_duration = 10.0

    # Save batch file temporarily to parse it
    from django.conf import settings
    import uuid
    import shutil
    tmp_dir = os.path.join(settings.MEDIA_ROOT, 'composer', str(user.id), 'batch_imports')
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"batch_{uuid.uuid4().hex[:8]}_{batch_file.name}")
    with open(tmp_path, 'wb') as f:
        for chunk in batch_file.chunks():
            f.write(chunk)

    try:
        from .utils.batch_parser import parse_batch_file
        tasks, warnings = parse_batch_file(tmp_path, default_model, default_duration)
    except Exception as exc:
        os.remove(tmp_path)
        return JsonResponse({'error': str(exc)}, status=400)

    if not tasks:
        os.remove(tmp_path)
        return JsonResponse({
            'error': 'Aucune tâche valide dans le fichier batch',
            'warnings': warnings,
        }, status=400)

    # Create batch container
    batch = ComposerBatch.objects.create(user=user, total=len(tasks))
    # Save the batch file on the batch object
    rel_path = os.path.relpath(tmp_path, settings.MEDIA_ROOT)
    batch.batch_file = rel_path
    batch.save(update_fields=['batch_file'])

    # Create generations and items
    created_ids = []
    from .tasks import compose_task
    for task_data in tasks:
        gen = ComposerGeneration.objects.create(
            user=user,
            generation_type=task_data['generation_type'],
            prompt=task_data['prompt'],
            model=task_data['model'],
            duration=task_data['duration'],
        )
        ComposerBatchItem.objects.create(
            batch=batch,
            generation=gen,
            output_filename=task_data['output_filename'],
            row_index=task_data['line_num'],
        )
        celery_task = compose_task.apply_async(args=(gen.id,))
        gen.task_id = celery_task.id
        gen.save(update_fields=['task_id'])
        created_ids.append(gen.id)

    return JsonResponse({
        'batch_id': batch.id,
        'total': batch.total,
        'created': created_ids,
        'warnings': warnings,
    })


# ---------------------------------------------------------------------------
# Update individual settings
# ---------------------------------------------------------------------------

@login_required
@require_POST
def update_settings(request, pk):
    """Update model and/or duration on an existing generation, then re-run."""
    gen = get_object_or_404(ComposerGeneration, id=pk, user=request.user)

    if gen.status == 'RUNNING':
        return JsonResponse({'error': 'Impossible de modifier une génération en cours'}, status=400)

    model_id = request.POST.get('model', gen.model)
    if model_id not in COMPOSER_MODELS:
        return JsonResponse({'error': 'Modèle invalide'}, status=400)

    try:
        duration = float(request.POST.get('duration', gen.duration))
        duration = max(10.0, min(300.0, duration))
    except (ValueError, TypeError):
        duration = gen.duration

    # Update generation type based on new model
    generation_type = COMPOSER_MODELS[model_id]['type']

    # Clear previous output
    if gen.audio_output:
        try:
            gen.audio_output.delete(save=False)
        except Exception:
            pass

    gen.model = model_id
    gen.duration = duration
    gen.generation_type = generation_type
    gen.status = 'PENDING'
    gen.progress = 0
    gen.audio_output = None
    gen.error_message = None
    gen.exported_to_library = False
    gen.save()

    # Re-launch task
    from .tasks import compose_task
    task = compose_task.apply_async(args=(gen.id,))
    gen.task_id = task.id
    gen.save(update_fields=['task_id'])

    return JsonResponse({'success': True, 'status': 'PENDING'})


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

@login_required
@require_GET
def progress(request, pk):
    gen = get_object_or_404(ComposerGeneration, id=pk, user=request.user)
    cached = cache.get(f'composer_progress_{pk}')
    pct = cached if cached is not None else gen.progress

    data = {
        'status': gen.status,
        'progress': pct,
        'error': gen.error_message,
    }
    if gen.status == 'SUCCESS' and gen.audio_output:
        from django.urls import reverse
        data['download_url'] = reverse('composer:download', args=[gen.id])
        data['audio_url'] = gen.audio_output.url
        data['exported'] = gen.exported_to_library

    return JsonResponse(data)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

@login_required
def download(request, pk):
    gen = get_object_or_404(ComposerGeneration, id=pk, user=request.user)
    if not gen.audio_output:
        return JsonResponse({'error': 'Aucun fichier disponible'}, status=404)

    filename = os.path.basename(gen.audio_output.name)
    response = FileResponse(gen.audio_output.open('rb'), content_type='audio/wav')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@login_required
@require_POST
def delete(request, pk):
    gen = get_object_or_404(ComposerGeneration, id=pk, user=request.user)

    # Capture parent batch before cascade
    parent_batch = None
    try:
        parent_batch = gen.batch_item.batch
    except Exception:
        pass

    # Delete output unconditionally
    if gen.audio_output:
        try:
            gen.audio_output.delete(save=False)
        except Exception:
            pass

    # Melody reference: check refs before deleting
    if gen.melody_reference:
        safe_delete_file(gen, 'melody_reference')

    gen.delete()

    # Clean up empty parent batch
    if parent_batch:
        try:
            if not parent_batch.items.exists():
                if parent_batch.batch_file:
                    try:
                        parent_batch.batch_file.delete(save=False)
                    except Exception:
                        pass
                parent_batch.delete()
        except Exception:
            pass

    return JsonResponse({'success': True})


# ---------------------------------------------------------------------------
# Batch delete
# ---------------------------------------------------------------------------

@login_required
@require_POST
def batch_delete(request, pk):
    batch = get_object_or_404(ComposerBatch, id=pk, user=request.user)

    for item in batch.items.select_related('generation'):
        gen = item.generation
        if gen.audio_output:
            try:
                gen.audio_output.delete(save=False)
            except Exception:
                pass
        if gen.melody_reference:
            safe_delete_file(gen, 'melody_reference')

    if batch.batch_file:
        try:
            batch.batch_file.delete(save=False)
        except Exception:
            pass

    batch.delete()  # cascades to items and generations
    return JsonResponse({'success': True})


# ---------------------------------------------------------------------------
# Export to media library
# ---------------------------------------------------------------------------

@login_required
@require_POST
def export_to_library(request, pk):
    gen = get_object_or_404(ComposerGeneration, id=pk, user=request.user)

    if not gen.audio_output:
        return JsonResponse({'error': 'Aucun fichier à exporter'}, status=400)
    if gen.exported_to_library:
        return JsonResponse({'error': 'Déjà exporté'}, status=400)

    try:
        from wama.media_library.models import UserAsset
        import shutil
        from django.conf import settings

        src = os.path.join(settings.MEDIA_ROOT, gen.audio_output.name)
        filename = os.path.basename(src)
        dest_dir = os.path.join(settings.MEDIA_ROOT, 'media_library', str(gen.user_id), 'audio')
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, filename)
        shutil.copy2(src, dest)
        rel_dest = os.path.relpath(dest, settings.MEDIA_ROOT)

        asset_type = 'music' if gen.generation_type == 'music' else 'sfx'
        UserAsset.objects.create(
            user=gen.user,
            asset_type=asset_type,
            name=filename,
            file=rel_dest,
            tags=','.join([gen.model, 'ia-généré', gen.generation_type]),
        )

        gen.exported_to_library = True
        gen.save(update_fields=['exported_to_library'])
        return JsonResponse({'success': True})

    except Exception as exc:
        logger.exception(f"[Composer] Export failed: {exc}")
        return JsonResponse({'error': str(exc)}, status=500)


# ---------------------------------------------------------------------------
# Duplicate & Download All
# ---------------------------------------------------------------------------

@login_required
@require_POST
def duplicate(request, pk):
    """Duplicate a single generation sharing the source, resetting the result."""
    gen = get_object_or_404(ComposerGeneration, id=pk, user=request.user)
    try:
        output_filename = gen.batch_item.output_filename
    except ComposerBatchItem.DoesNotExist:
        output_filename = ''

    new_gen = duplicate_instance(
        gen,
        reset_fields={
            'status': 'PENDING', 'progress': 0,
            'task_id': None, 'error_message': '',
            'exported_to_library': False,
        },
        clear_fields=['audio_output'],
    )
    _wrap_generation_in_batch(new_gen)
    return JsonResponse({'success': True, 'id': new_gen.id})


@login_required
@require_POST
def batch_duplicate(request, pk):
    """Duplicate a batch with all its items, sharing source files."""
    batch = get_object_or_404(ComposerBatch, id=pk, user=request.user)

    new_batch = ComposerBatch(user=request.user, total=batch.total)
    if batch.batch_file and batch.batch_file.name:
        new_batch.batch_file = batch.batch_file.name
    new_batch.save()

    for item in batch.items.select_related('generation').order_by('row_index'):
        gen = item.generation
        if not gen:
            continue
        new_gen = duplicate_instance(
            gen,
            reset_fields={
                'status': 'PENDING', 'progress': 0,
                'task_id': None, 'error_message': '',
                'exported_to_library': False,
            },
            clear_fields=['audio_output'],
        )
        ComposerBatchItem.objects.create(
            batch=new_batch,
            generation=new_gen,
            output_filename=item.output_filename,
            row_index=item.row_index,
        )

    return JsonResponse({'success': True, 'id': new_batch.id})


@login_required
def download_all(request):
    """Download all completed audio outputs as a ZIP archive."""
    import io as _io
    import zipfile
    from django.http import HttpResponse

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gens = (ComposerGeneration.objects
            .filter(user=user, status='SUCCESS')
            .exclude(audio_output=''))

    if not gens.exists():
        return JsonResponse({'error': 'Aucun fichier disponible'}, status=404)

    buffer = _io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for gen in gens:
            if not gen.audio_output:
                continue
            try:
                zf.write(gen.audio_output.path, os.path.basename(gen.audio_output.name))
            except Exception:
                pass

    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="composer_audio.zip"'
    return response


# ---------------------------------------------------------------------------
# Start all / Clear all
# ---------------------------------------------------------------------------

@login_required
@require_POST
def start_all(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from .tasks import compose_task

    gens = ComposerGeneration.objects.filter(user=user, status__in=('PENDING', 'FAILURE'))
    count = 0
    for gen in gens:
        gen.status = 'PENDING'
        gen.progress = 0
        gen.save(update_fields=['status', 'progress'])
        task = compose_task.apply_async(args=(gen.id,))
        gen.task_id = task.id
        gen.save(update_fields=['task_id'])
        count += 1

    return JsonResponse({'launched': count})


@login_required
@require_POST
def clear_all(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    gens = ComposerGeneration.objects.filter(user=user).exclude(status='RUNNING')
    for gen in gens:
        if gen.audio_output:
            try:
                gen.audio_output.delete(save=False)
            except Exception:
                pass
        if gen.melody_reference:
            safe_delete_file(gen, 'melody_reference')

    gens.delete()
    ComposerBatch.objects.filter(user=user).delete()
    return JsonResponse({'success': True})


# ---------------------------------------------------------------------------
# Console & global progress
# ---------------------------------------------------------------------------

@login_required
def console_content(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    lines = get_console_lines(user.id, app='composer')
    return JsonResponse({'lines': lines})


@login_required
def global_progress(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gens = ComposerGeneration.objects.filter(user=user, status__in=('PENDING', 'RUNNING'))

    items = []
    for gen in gens:
        cached = cache.get(f'composer_progress_{gen.id}')
        pct = cached if cached is not None else gen.progress
        items.append({'id': gen.id, 'status': gen.status, 'progress': pct})

    return JsonResponse({'items': items})
