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


def _is_app_owned(file_field, user_id) -> bool:
    """True only if the file lives inside the Converter's OWN media tree
    (``converter/<user_id>/…``).

    Règle WAMA : supprimer une tâche ne supprime les fichiers QUE s'ils sont
    dans le dossier média de l'application. Les fichiers seulement *référencés*
    ailleurs appartiennent à l'utilisateur et ne doivent jamais être supprimés :
      - "Envoyer vers Converter" (file d'attente) : input = source Filemanager
        (référencée, pas copiée) → NON supprimable ; output dans converter/<u>/output → supprimable.
      - "Conversion rapide" (in-place) : input ET output dans des dossiers
        utilisateur → NON supprimables.
      - Upload direct dans la page Converter : input ET output dans
        converter/<u>/… → supprimables.
    """
    if not file_field:
        return False
    name = (getattr(file_field, 'name', '') or '').replace('\\', '/')
    return name.startswith(f'converter/{user_id}/')


def _wrap_job_in_batch(job):
    """Wrap a standalone job in a ConversionBatch-of-1 (même nature)."""
    from .models import ConversionBatch
    batch = ConversionBatch.objects.create(user=job.user, media_type=job.media_type, total=1)
    job.batch = batch
    job.batch_row_index = 0
    job.save(update_fields=['batch', 'batch_row_index'])
    return batch


def _auto_wrap_orphans(user):
    """Wrap any non-ephemeral queue job without a batch into a batch-of-1
    (lazy, à l'ouverture de la page — comme reader/synthesizer)."""
    for job in ConversionJob.objects.filter(user=user, ephemeral=False, batch__isnull=True):
        try:
            _wrap_job_in_batch(job)
        except Exception:
            pass


def consolidate_jobs_into_batches(job_ids, user):
    """Regroupe des jobs par NATURE → un ConversionBatch par nature.

    Les jobs importés sont des orphelins (pas de batch-of-1 préalable), donc on
    crée directement les batchs-of-N. Réglages de sortie communs par batch →
    on ne mélange jamais les natures. Retourne la liste des batchs créés.
    """
    from collections import OrderedDict
    from .models import ConversionBatch
    from wama.common.utils.batch_common import consolidate_into_batch

    jobs = list(ConversionJob.objects.filter(id__in=job_ids, user=user, ephemeral=False))
    by_nature = OrderedDict()
    for j in jobs:
        by_nature.setdefault(j.media_type, []).append(j)

    batches = []
    for nature, group in by_nature.items():
        def _create(total, _n=nature):
            return ConversionBatch.objects.create(user=user, media_type=_n, total=total)

        def _link(batch, job, idx):
            job.batch = batch
            job.batch_row_index = idx
            job.save(update_fields=['batch', 'batch_row_index'])

        b = consolidate_into_batch(group, create_batch=_create, link_item=_link)
        if b:
            batches.append(b)
    return batches


class IndexView(View):
    def get(self, request):
        import json
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
        # Tout job de file appartient à un batch (batch-of-1 si fichier seul) —
        # wrap paresseux des éventuels orphelins (ex. upload direct).
        _auto_wrap_orphans(user)
        # Ephemeral jobs (quick-convert) are never shown in the queue.
        jobs     = (ConversionJob.objects.filter(user=user, ephemeral=False)
                    .select_related('batch').order_by('-created_at'))
        profiles = ConversionProfile.objects.filter(user=user)

        # Group jobs by batch for the queue UI (batch-of-1 → carte simple,
        # batch-of-N → groupe). Ordre : par batch le plus récent.
        from collections import OrderedDict
        _nature_labels = {'image': 'Images', 'video': 'Vidéos', 'audio': 'Audio',
                          'document': 'Documents', 'archive': 'Archives'}
        grouped = OrderedDict()
        for job in jobs:
            key = job.batch_id or f'loose-{job.id}'
            grouped.setdefault(key, []).append(job)
        batches_list = []
        for items in grouped.values():
            items_sorted = sorted(items, key=lambda j: j.batch_row_index)
            batch = items[0].batch
            total = batch.total if batch else len(items_sorted)
            done = sum(1 for j in items_sorted if j.status == 'DONE')
            batches_list.append({
                'obj': batch,
                'items': items_sorted,
                'is_group': bool(batch) and total > 1,
                'media_label': _nature_labels.get(batch.media_type if batch else '', ''),
                'done_count': done,
            })

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
            'batches_list':         batches_list,
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
                'sample_rate', 'channels',
                'rotation', 'flip_h', 'flip_v']:
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

        # Clear previous output (only if it lives in the Converter's media tree)
        if job.output_file and _is_app_owned(job.output_file, job.user_id):
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
        'status':          job.status,
        'progress':        pct,
        'error_message':   job.error_message,
        'output_ready':    bool(job.status == 'DONE' and job.output_file),
        'output_filename': job.output_filename,
        'input_filename':  job.input_filename,
        'media_type':      job.media_type,
        'output_format':   job.output_format,
        'options':         job.options or {},
    })


@login_required
def global_progress(request):
    """Progression globale de la file (toujours affichée côté UI).

    Renvoie {total, done, running, overall_progress} pour le composant commun
    common/_global_progress.html + wama-global-progress.js.
    Les jobs éphémères (quick-convert in-place) sont exclus de la file.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    jobs = list(ConversionJob.objects.filter(user=user, ephemeral=False)
                .values('id', 'status', 'progress'))

    total = len(jobs)
    done = sum(1 for j in jobs if j['status'] == 'DONE')
    running = sum(1 for j in jobs if j['status'] == 'RUNNING')

    if total:
        acc = 0
        for j in jobs:
            if j['status'] == 'DONE':
                acc += 100
            elif j['status'] == 'RUNNING':
                acc += cache.get(f"converter_progress_{j['id']}", j['progress'] or 0)
            else:
                acc += j['progress'] or 0
        overall = int(acc / total)
    else:
        overall = 0

    return JsonResponse({
        'total': total,
        'done': done,
        'running': running,
        'overall_progress': overall,
    })


@login_required
@require_POST
def update_job(request, pk):
    """Update a job's output_format and options (only when not RUNNING)."""
    import json as _json

    job = get_object_or_404(ConversionJob, pk=pk, user=request.user)
    if job.status == 'RUNNING':
        return JsonResponse({'error': 'Impossible de modifier une conversion en cours'}, status=400)

    output_fmt = (request.POST.get('output_format') or '').strip().lower()
    if output_fmt:
        if output_fmt not in get_output_formats(job.media_type):
            return JsonResponse({'error': f"Format de sortie non supporté : {output_fmt}"}, status=400)
        job.output_format = output_fmt

    # Options can come as a JSON blob (preferred) or as individual POST keys.
    options_json = request.POST.get('options_json')
    if options_json:
        try:
            new_opts = _json.loads(options_json)
            if not isinstance(new_opts, dict):
                raise ValueError("options_json must be an object")
            job.options = new_opts
        except (ValueError, _json.JSONDecodeError) as exc:
            return JsonResponse({'error': f"options_json invalide : {exc}"}, status=400)

    job.save(update_fields=['output_format', 'options'])
    return JsonResponse({'success': True, 'output_format': job.output_format, 'options': job.options})


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
    """Delete a ConversionJob and its files.

    For in-place/ephemeral quick-convert jobs the files belong to the user
    (Filemanager) — only the DB row is removed, the files are kept.
    """
    job = get_object_or_404(ConversionJob, pk=pk, user=request.user)

    # Output : supprimé seulement s'il est dans le dossier média du Converter
    if job.output_file and _is_app_owned(job.output_file, job.user_id):
        try:
            Path(job.output_file.path).unlink(missing_ok=True)
        except Exception:
            pass
    # Input : idem — jamais les fichiers utilisateur seulement référencés
    if _is_app_owned(job.input_file, job.user_id):
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
        if job.output_file and _is_app_owned(job.output_file, job.user_id):
            try:
                Path(job.output_file.path).unlink(missing_ok=True)
            except Exception:
                pass
        if _is_app_owned(job.input_file, job.user_id):
            safe_delete_file(job, 'input_file')
    jobs.delete()
    return JsonResponse({'success': True})


# ────────────────────────────────────────────────────────────────────────────
# Batch import — consolidation multi-fichiers + fichier batch d'URLs
# ────────────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def consolidate(request):
    """Regroupe des jobs (créés par upload multi-fichiers) en batchs par nature.

    Appelé par le front après avoir uploadé plusieurs fichiers d'un coup :
    chaque /upload/ crée un job orphelin, puis on consolide ici → 1 batch/nature.
    """
    import json as _json
    try:
        ids = _json.loads(request.body or '{}').get('job_ids', [])
    except Exception:
        ids = request.POST.getlist('job_ids')
    ids = [int(i) for i in ids if str(i).isdigit()]
    batches = consolidate_jobs_into_batches(ids, request.user)
    return JsonResponse({'success': True, 'batches': len(batches)})


@login_required
@require_POST
def batch_preview(request):
    """Aperçu d'un fichier batch d'URLs/chemins (détection style synthesizer)."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response

    def _enrich(item):
        mt = detect_media_type(item.get('filename', ''))
        item['detected_type'] = mt or 'inconnu'

    return batch_media_list_preview_response(request, item_enricher=_enrich)


@login_required
@require_POST
def batch_create(request):
    """Crée des jobs depuis un fichier batch d'URLs/chemins.

    Téléchargement eager : URL distante → upload_media_from_url ; chemin local
    (sous MEDIA_ROOT) → copie. Chaque source → un ConversionJob PENDING (format
    réglé ensuite via les réglages du batch). Consolidation par nature.
    Les lignes en échec sont ignorées et reportées dans `warnings`.
    """
    import os as _os
    from django.conf import settings
    from wama.common.utils.batch_parsers import parse_batch_file_from_request
    from wama.common.utils.media_paths import get_app_media_path, copy_into_app_input

    user = request.user
    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    media_root = Path(settings.MEDIA_ROOT).resolve()
    dest_dir = get_app_media_path('converter', user.id, 'input')
    dest_dir.mkdir(parents=True, exist_ok=True)

    job_ids = []
    for item in items:
        src = (item.get('path') or '').strip()
        if not src:
            continue
        try:
            if src.startswith(('http://', 'https://')):
                from wama.common.utils.video_utils import upload_media_from_url
                before = set(_os.listdir(dest_dir))
                upload_media_from_url(src, str(dest_dir))
                new = sorted(set(_os.listdir(dest_dir)) - before)
                if not new:
                    warnings.append(f'Échec téléchargement : {src}')
                    continue
                fname = new[0]
                dpath = dest_dir / fname
                rel = f'converter/{user.id}/input/{fname}'
            else:
                cand = Path(src)
                abs_src = (cand if cand.is_absolute() else (media_root / src)).resolve()
                if not str(abs_src).startswith(str(media_root)) or not abs_src.exists():
                    warnings.append(f'Introuvable : {src}')
                    continue
                dpath, rel = copy_into_app_input(abs_src, 'converter', user.id, 'input')
                fname = dpath.name

            media_type = detect_media_type(fname)
            if media_type is None:
                warnings.append(f'Type non supporté : {fname}')
                continue

            job = ConversionJob.objects.create(
                user=user, input_filename=fname, media_type=media_type,
                output_format='', status='PENDING',
            )
            job.input_file.name = rel
            job.save(update_fields=['input_file'])
            job_ids.append(job.id)
        except Exception as e:
            warnings.append(f'{src} : {e}')

    batches = consolidate_jobs_into_batches(job_ids, user)
    return JsonResponse({
        'success': True,
        'count': len(job_ids),
        'batches': len(batches),
        'warnings': warnings,
    })


# ────────────────────────────────────────────────────────────────────────────
# Batch actions (groupe) — démarrer / régler / supprimer
# ────────────────────────────────────────────────────────────────────────────

def _delete_job_files(job):
    """Supprime input/output d'un job s'ils appartiennent au Converter."""
    if job.output_file and _is_app_owned(job.output_file, job.user_id):
        try:
            Path(job.output_file.path).unlink(missing_ok=True)
        except Exception:
            pass
    if _is_app_owned(job.input_file, job.user_id):
        safe_delete_file(job, 'input_file')


@login_required
@require_POST
def batch_start(request, pk):
    """Démarre tous les jobs PENDING d'un batch."""
    from .models import ConversionBatch
    from .tasks import convert_media_task
    batch = get_object_or_404(ConversionBatch, pk=pk, user=request.user)
    started = []
    for job in batch.items.filter(status='PENDING'):
        if not job.output_format:
            continue  # format non défini → on saute (réglé via batch settings)
        with transaction.atomic():
            j = ConversionJob.objects.select_for_update().get(pk=job.pk)
            if j.status == 'RUNNING':
                continue
            j.status = 'RUNNING'
            j.save(update_fields=['status'])
        task = convert_media_task.delay(job.id)
        job.task_id = task.id
        job.save(update_fields=['task_id'])
        started.append(job.id)
    return JsonResponse({'success': True, 'started': started})


@login_required
@require_POST
def batch_update(request, pk):
    """Applique format/qualité communs à tous les jobs non-RUNNING d'un batch."""
    from .models import ConversionBatch
    batch = get_object_or_404(ConversionBatch, pk=pk, user=request.user)
    out_fmt = (request.POST.get('output_format') or '').strip().lower()
    preset  = (request.POST.get('output_quality') or request.POST.get('quality_preset') or '').strip().lower()

    if out_fmt and out_fmt not in get_output_formats(batch.media_type):
        return JsonResponse({'error': f"Format invalide pour {batch.media_type} : {out_fmt}"}, status=400)

    updated = 0
    for job in batch.items.exclude(status='RUNNING'):
        fields = []
        if out_fmt:
            job.output_format = out_fmt; fields.append('output_format')
        if preset:
            job.quality_preset = preset; fields.append('quality_preset')
        if fields:
            job.save(update_fields=fields); updated += 1
    return JsonResponse({'success': True, 'updated': updated,
                         'output_format': out_fmt, 'media_type': batch.media_type})


@login_required
@require_POST
def batch_delete(request, pk):
    """Supprime un batch : révoque les tâches, nettoie les fichiers app-owned,
    puis supprime les jobs + le batch."""
    from .models import ConversionBatch
    batch = get_object_or_404(ConversionBatch, pk=pk, user=request.user)
    for job in batch.items.all():
        if job.task_id:
            try:
                from celery import current_app
                current_app.control.revoke(job.task_id, terminate=False)
            except Exception:
                pass
        _delete_job_files(job)
    # CASCADE supprime les jobs liés à la suppression du batch
    batch.delete()
    return JsonResponse({'success': True})


# ────────────────────────────────────────────────────────────────────────────
# Conversion profiles — save / list / delete
# ────────────────────────────────────────────────────────────────────────────

@login_required
def profile_list(request):
    """Return user's profiles, optionally filtered by media_type."""
    media_type = request.GET.get('media_type', '').strip()
    qs = ConversionProfile.objects.filter(user=request.user)
    if media_type:
        qs = qs.filter(media_type=media_type)
    return JsonResponse({
        'profiles': [
            {
                'id':            p.id,
                'name':          p.name,
                'description':   p.description,
                'media_type':    p.media_type,
                'output_format': p.output_format,
                'options':       p.options or {},
            }
            for p in qs
        ],
    })


@login_required
@require_POST
def profile_save(request):
    """Create or update a profile by name (per user)."""
    import json as _json

    name          = (request.POST.get('name') or '').strip()
    description   = (request.POST.get('description') or '').strip()
    media_type    = (request.POST.get('media_type') or '').strip()
    output_format = (request.POST.get('output_format') or '').strip().lower()
    options_json  = request.POST.get('options_json') or '{}'

    if not name:
        return JsonResponse({'error': 'Nom du profil requis'}, status=400)
    if media_type not in SUPPORTED_CONVERSIONS:
        return JsonResponse({'error': f"Type de média invalide : {media_type}"}, status=400)
    if output_format not in get_output_formats(media_type):
        return JsonResponse({'error': f"Format de sortie invalide : {output_format}"}, status=400)

    try:
        options = _json.loads(options_json)
        if not isinstance(options, dict):
            raise ValueError("options must be an object")
    except (ValueError, _json.JSONDecodeError) as exc:
        return JsonResponse({'error': f"options_json invalide : {exc}"}, status=400)

    profile, created = ConversionProfile.objects.update_or_create(
        user=request.user,
        name=name,
        defaults={
            'description':   description,
            'media_type':    media_type,
            'output_format': output_format,
            'options':       options,
        },
    )
    return JsonResponse({
        'success':       True,
        'created':       created,
        'id':            profile.id,
        'name':          profile.name,
        'media_type':    profile.media_type,
        'output_format': profile.output_format,
        'options':       profile.options or {},
    })


@login_required
@require_POST
def profile_delete(request, pk):
    """Delete a profile."""
    profile = get_object_or_404(ConversionProfile, pk=pk, user=request.user)
    profile.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def cancel(request, pk):
    """Cancel a running conversion (revoke the Celery task).

    Ephemeral quick-convert jobs are deleted outright; queue jobs are reset to
    PENDING so they can be restarted. The atomic-output design guarantees no
    partial file is left next to the source on a killed in-place conversion.
    """
    job = get_object_or_404(ConversionJob, pk=pk, user=request.user)
    if job.task_id:
        try:
            from celery import current_app
            current_app.control.revoke(job.task_id, terminate=True, signal='SIGTERM')
        except Exception:
            pass
    if job.ephemeral:
        job.delete()
    else:
        job.status = 'PENDING'
        job.task_id = ''
        job.progress = 0
        job.save(update_fields=['status', 'task_id', 'progress'])
    return JsonResponse({'success': True})


@login_required
@require_POST
def dismiss(request, pk):
    """Delete an ephemeral quick-convert job row WITHOUT touching files.

    Called by the Filemanager once the in-place result has been delivered.
    The output file lives in the user's media tree, so we must never delete it
    here — only the tracking row is removed. Refuses non-ephemeral jobs.
    """
    job = get_object_or_404(ConversionJob, pk=pk, user=request.user, ephemeral=True)
    job.delete()  # FileField files are NOT deleted by .delete(); row only
    return JsonResponse({'success': True})


@login_required
@require_POST
def quick_convert(request):
    """
    Convert / enqueue from a server file path — called from the Filemanager.

    "Conversion rapide" (on-the-fly) : crée un job ÉPHÉMÈRE, écrit le résultat
    À CÔTÉ de la source (in-place), démarre tout de suite, n'apparaît JAMAIS
    dans la file, et la ligne est supprimée (dismiss) après livraison — le
    fichier reste. output_format requis ; quality_preset (web/balanced/max).

    NB : "Envoyer vers Converter" (mode file d'attente) passe désormais par le
    flux d'import STANDARD (filemanager api_import_to_app → import_to_converter),
    qui COPIE le fichier dans converter/<user>/input comme toutes les apps.

    POST params:
        file_path      : chemin absolu ou relatif à MEDIA_ROOT du fichier source
        output_format  : format cible (requis)
        quality_preset : 'web' | 'balanced' | 'max' (défaut 'balanced')
    """
    from .tasks import convert_media_task
    from .utils.quality_presets import DEFAULT_PRESET, PRESET_CHOICES

    file_path_str = request.POST.get('file_path', '').strip()
    output_fmt    = (request.POST.get('output_format', '') or '').strip().lower()
    preset        = (request.POST.get('quality_preset', '') or '').strip().lower()
    if preset not in PRESET_CHOICES:
        preset = DEFAULT_PRESET

    if not file_path_str:
        return JsonResponse({'error': 'Chemin de fichier manquant'}, status=400)
    if not output_fmt:
        return JsonResponse({'error': 'Format de sortie manquant'}, status=400)

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
        rel_path = abs_path.relative_to(media_root)
    except ValueError:
        return JsonResponse({'error': 'Chemin de fichier invalide'}, status=400)

    if not abs_path.exists():
        return JsonResponse({'error': 'Fichier source introuvable'}, status=404)

    media_type = detect_media_type(abs_path.name)
    if media_type is None:
        return JsonResponse({'error': f"Type de fichier non supporté : {abs_path.suffix}"}, status=400)

    if output_fmt not in get_output_formats(media_type):
        return JsonResponse({'error': f"Format de sortie non supporté : {output_fmt}"}, status=400)

    # ── Quick convert : ephemeral + in-place + preset ─────────────────────────
    dest_dir = str(rel_path.parent).replace('\\', '/')  # source folder, relative to MEDIA_ROOT
    job = ConversionJob.objects.create(
        user=request.user,
        input_file=str(rel_path),
        input_filename=abs_path.name,
        media_type=media_type,
        output_format=output_fmt,
        ephemeral=True,
        dest_dir=dest_dir,
        quality_preset=preset,
        status='RUNNING',
    )
    task = convert_media_task.delay(job.id)
    job.task_id = task.id
    job.save(update_fields=['task_id'])
    return JsonResponse({'success': True, 'job_id': job.id, 'task_id': task.id})
