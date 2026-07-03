"""
Composer Views — Music and SFX generation.
"""

import json
import logging
import os

from django.core.cache import cache
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
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
        has_success = any(
            it.generation and it.generation.status == 'SUCCESS' and it.generation.audio_output
            for it in items
        )
        result.append({'obj': batch, 'items': items, 'has_success': has_success})
    result.sort(key=lambda b: 0 if b['obj'].total > 1 else 1)
    return result


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

class IndexView(View):
    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        batches_list = _get_batches_list(user)
        queue_count = sum(
            1 for b in batches_list
            for item in b['items']
            if item.generation and item.generation.status in ('PENDING', 'RUNNING')
        )

        import json
        from .params import PARAMS_JSON as _COMPOSER_PARAMS_JSON
        return render(request, 'composer/index.html', {
            'batches_list': batches_list,
            'queue_count': queue_count,
            'music_models': MUSIC_MODELS,
            'sfx_models': SFX_MODELS,
            'all_models': COMPOSER_MODELS,
            'params_json': json.dumps(_COMPOSER_PARAMS_JSON),
            # Appariement card↔modèles (WamaInputMatch) : besoins d'entrées par modèle depuis le
            # CATALOGUE + libellés d'INPUT_TYPES. Cf. INPUT_MODEL_MATCHING.md.
            'input_match_meta': json.dumps(_input_match_meta()),
            'input_labels': json.dumps(_input_labels()),
        })


# ---------------------------------------------------------------------------
# Generate single item
# ---------------------------------------------------------------------------

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
        duration = max(10.0, min(600.0, duration))
    except (ValueError, TypeError):
        duration = 10.0

    generation_type = COMPOSER_MODELS[model_id]['type']

    gen = ComposerGeneration.objects.create(
        user=user,
        generation_type=generation_type,
        prompt=prompt,
        model=model_id,
        duration=duration,
        output_format=request.POST.get('output_format', 'original'),
        output_quality=request.POST.get('output_quality', 'balanced'),
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
        default_duration = max(10.0, min(600.0, default_duration))
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
        tasks, warnings = parse_batch_file(
            tmp_path, default_model, default_duration, source_name=batch_file.name,
        )
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

@require_POST
def start(request, pk):
    """Relance la génération d'une composition (bouton de cycle ▶/↻) sans changer les réglages."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gen = get_object_or_404(ComposerGeneration, id=pk, user=user)
    if gen.status == 'RUNNING':
        return JsonResponse({'error': 'Déjà en cours'}, status=400)
    if gen.task_id:
        try:
            from celery import current_app
            current_app.control.revoke(gen.task_id, terminate=False)
        except Exception:
            pass
    gen.status = 'PENDING'
    gen.progress = 0
    gen.audio_output = None
    gen.error_message = None
    gen.save(update_fields=['status', 'progress', 'audio_output', 'error_message'])
    from .tasks import compose_task
    task = compose_task.apply_async(args=(gen.id,))
    gen.task_id = task.id
    gen.save(update_fields=['task_id'])
    return JsonResponse({'id': gen.id, 'status': 'RUNNING'})


def stop(request, pk):
    """
    Stoppe la génération en cours (révoque la tâche Celery) → composition relançable (bouton ↻).
    Brique commune : wama.common.utils.process_control.stop_instance.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gen = get_object_or_404(ComposerGeneration, id=pk, user=user)
    if gen.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({'id': gen.id, 'status': gen.status})
    from wama.common.utils.process_control import stop_instance
    new_status = stop_instance(gen, error_field='error_message')
    return JsonResponse({'id': gen.id, 'status': new_status})


def _input_match_meta():
    """{model_id: {inputs_required, inputs_optional}} depuis le CATALOGUE — fail-safe {}."""
    try:
        from wama.model_manager.models import AIModel
        meta = {}
        for m in AIModel.objects.filter(source='composer', is_proposed=False):
            caps = m.capabilities or {}
            meta[m.model_key.split(':', 1)[-1]] = {
                'inputs_required': caps.get('inputs_required', []),
                'inputs_optional': caps.get('inputs_optional', []),
            }
        return meta
    except Exception:
        return {}


def _input_labels():
    """{input_id: libellé} depuis INPUT_TYPES (source déclarée commune) — fail-safe {}."""
    try:
        from wama.common.utils.app_modes import INPUT_TYPES
        return {k: v.get('label', k) for k, v in INPUT_TYPES.items()}
    except Exception:
        return {}


def update_settings(request, pk):
    """Update model and/or duration on an existing generation, then re-run."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gen = get_object_or_404(ComposerGeneration, id=pk, user=user)

    if gen.status == 'RUNNING':
        return JsonResponse({'error': 'Impossible de modifier une génération en cours'}, status=400)

    model_id = request.POST.get('model', gen.model)
    if model_id not in COMPOSER_MODELS:
        return JsonResponse({'error': 'Modèle invalide'}, status=400)

    try:
        duration = float(request.POST.get('duration', gen.duration))
        duration = max(10.0, min(600.0, duration))
    except (ValueError, TypeError):
        duration = gen.duration

    # Update generation type based on new model
    generation_type = COMPOSER_MODELS[model_id]['type']

    gen.model = model_id
    gen.duration = duration
    gen.generation_type = generation_type
    # Prompt éditable (modale complète P1) — on ne l'écrase pas s'il est vide.
    prompt = request.POST.get('prompt')
    if prompt is not None and prompt.strip():
        gen.prompt = prompt.strip()
    # Format/qualité de sortie (early-binding, per-item) si fournis
    if request.POST.get('output_format'):
        gen.output_format = request.POST['output_format']
    if request.POST.get('output_quality'):
        gen.output_quality = request.POST['output_quality']

    # Pied de modale CONFORME : « Enregistrer » (restart=0) sauve SANS purger la sortie ni
    # relancer ; « Enregistrer et relancer » (restart=1, défaut historique) purge + re-run.
    restart = request.POST.get('restart', '1') == '1'
    if not restart:
        gen.save()
        return JsonResponse({'success': True, 'status': gen.status, 'restarted': False})

    # Clear previous output
    if gen.audio_output:
        try:
            gen.audio_output.delete(save=False)
        except Exception:
            pass
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

    return JsonResponse({'success': True, 'status': 'PENDING', 'restarted': True})


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

@require_GET
def progress(request, pk):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gen = get_object_or_404(ComposerGeneration, id=pk, user=user)
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

def download(request, pk):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gen = get_object_or_404(ComposerGeneration, id=pk, user=user)
    if not gen.audio_output:
        return JsonResponse({'error': 'Aucun fichier disponible'}, status=404)

    filename = os.path.basename(gen.audio_output.name)
    response = FileResponse(gen.audio_output.open('rb'), content_type='audio/wav')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@require_POST
def delete(request, pk):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gen = get_object_or_404(ComposerGeneration, id=pk, user=user)

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

    # batch.total / suppression du batch vidé (+ fichier batch) : gérés par le signal batch_sync.
    return JsonResponse({'success': True, 'batch_changed': parent_batch is not None})


# ---------------------------------------------------------------------------
# Batch delete
# ---------------------------------------------------------------------------

@require_POST
def batch_delete(request, pk):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(ComposerBatch, id=pk, user=user)

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

@require_POST
def export_to_library(request, pk):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gen = get_object_or_404(ComposerGeneration, id=pk, user=user)

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

        asset_type = 'audio_music' if gen.generation_type == 'music' else 'audio_sfx'
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

@require_POST
def duplicate(request, pk):
    """Duplicate a single generation sharing the source, resetting the result."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gen = get_object_or_404(ComposerGeneration, id=pk, user=user)
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
    # Dupliquer DANS le même batch que l'original (élément frère).
    orig_item = ComposerBatchItem.objects.filter(generation=gen).select_related('batch').first()
    if orig_item:
        from django.db.models import Max
        batch = orig_item.batch
        next_idx = (batch.items.aggregate(m=Max('row_index'))['m'] or 0) + 1
        ComposerBatchItem.objects.create(
            batch=batch, generation=new_gen, output_filename=output_filename, row_index=next_idx)
        batch.total = batch.items.count()
        batch.save(update_fields=['total'])
    else:
        _wrap_generation_in_batch(new_gen)
    return JsonResponse({'success': True, 'id': new_gen.id})


@require_POST
def batch_update(request, pk):
    """Applique les paramètres (modèle, durée) à TOUS les items non-RUNNING du batch.

    Réutilise la même modale que les réglages individuels (mode batch côté JS).
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(ComposerBatch, id=pk, user=user)
    model = request.POST.get('model')
    duration = request.POST.get('duration')
    output_format = request.POST.get('output_format')
    output_quality = request.POST.get('output_quality')
    updated = 0
    for item in batch.items.select_related('generation'):
        g = item.generation
        if not g or g.status == 'RUNNING':
            continue
        if model and model in COMPOSER_MODELS:
            g.model = model
            g.generation_type = COMPOSER_MODELS[model]['type']
        if duration:
            try:
                g.duration = max(10.0, min(600.0, float(duration)))
            except (ValueError, TypeError):
                pass
        if output_format:
            g.output_format = output_format
        if output_quality:
            g.output_quality = output_quality
        g.save()
        updated += 1
    return JsonResponse({'success': True, 'updated': updated})


@require_POST
def batch_duplicate(request, pk):
    """Duplicate a batch with all its items, sharing source files."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(ComposerBatch, id=pk, user=user)

    new_batch = ComposerBatch(user=user, total=batch.total)
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


def batch_download(request, pk):
    """Download a ZIP of all completed audio outputs in a batch (mono-format WAV).

    Simple-button variant of the batch ZIP convention (WAMA_APP_CONVENTIONS §9.10).
    """
    import io as _io
    import zipfile
    from django.http import HttpResponse

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(ComposerBatch, id=pk, user=user)

    buffer = _io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in batch.items.select_related('generation').order_by('row_index'):
            gen = item.generation
            if gen and gen.status == 'SUCCESS' and gen.audio_output:
                try:
                    arcname = item.output_filename or os.path.basename(gen.audio_output.name)
                    zf.write(gen.audio_output.path, arcname)
                except Exception:
                    continue

    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="batch_composer_{pk}.zip"'
    return response


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

def console_content(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    lines = get_console_lines(user.id, app='composer')
    return JsonResponse({'lines': lines})


def global_progress(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gens = ComposerGeneration.objects.filter(user=user, status__in=('PENDING', 'RUNNING'))

    items = []
    for gen in gens:
        cached = cache.get(f'composer_progress_{gen.id}')
        pct = cached if cached is not None else gen.progress
        items.append({'id': gen.id, 'status': gen.status, 'progress': pct})

    return JsonResponse({'items': items})
