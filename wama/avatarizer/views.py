"""
WAMA Avatarizer - Views
Interface de génération d'avatars animés
"""

import os
import logging
import tempfile
from pathlib import Path

from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.http import JsonResponse, FileResponse, Http404
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError

from .models import AvatarJob, BatchAvatarJob, BatchAvatarJobItem
from wama.synthesizer.models import CustomVoice
from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.queue_duplication import duplicate_instance, safe_delete_file
from wama.common.utils.batch_common import group_into_batches_by_nature

logger = logging.getLogger(__name__)

# Lazy import of the Celery task (avoids importing heavy libs at Gunicorn startup)
_generate_avatar = None


def _ensure_workers_imported():
    global _generate_avatar
    if _generate_avatar is None:
        from .workers import generate_avatar as ga
        _generate_avatar = ga


def _get_user(request):
    if request.user.is_authenticated:
        return request.user
    return get_or_create_anonymous_user()


def _gallery_images():
    """Return list of filenames in the shared avatar gallery directory."""
    gallery_dir = Path(settings.MEDIA_ROOT) / 'avatarizer' / 'gallery'
    gallery_dir.mkdir(parents=True, exist_ok=True)
    valid_exts = {'.jpg', '.jpeg', '.png', '.webp'}
    return [
        f.name for f in sorted(gallery_dir.iterdir())
        if f.is_file() and f.suffix.lower() in valid_exts
    ]


class IndexView(View):
    """Page principale de l'Avatarizer."""

    def get(self, request):
        user = _get_user(request)
        jobs = AvatarJob.objects.filter(user=user).order_by('-id')
        gallery = _gallery_images()

        custom_voices = CustomVoice.objects.filter(user=user)

        context = {
            'jobs': jobs,
            'batches_list': _get_batches_list(user),
            'gallery_images': gallery,
            'tts_models': AvatarJob.TTS_MODEL_CHOICES,
            'languages': AvatarJob.LANGUAGE_CHOICES,
            'custom_voices': custom_voices,
            'quality_mode_choices': AvatarJob.QUALITY_MODE_CHOICES,
            'media_url': settings.MEDIA_URL,
        }
        return render(request, 'avatarizer/index.html', context)


def create(request):
    """POST : Crée un AvatarJob avec les paramètres fournis."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requis'}, status=405)

    user = _get_user(request)
    mode = request.POST.get('mode', 'pipeline')
    job = AvatarJob(user=user, mode=mode)

    # --- Pipeline : champs TTS ---
    if mode == 'pipeline':
        text_content = request.POST.get('text_content', '').strip()
        if not text_content:
            return JsonResponse({'error': 'Le texte est obligatoire en mode Pipeline.'}, status=400)
        job.text_content = text_content
        job.tts_model = request.POST.get('tts_model', 'xtts_v2')
        job.language = request.POST.get('language', 'fr')
        job.voice_preset = request.POST.get('voice_preset', 'default')

    # --- Standalone : fichier audio ---
    if mode == 'standalone':
        audio_file = request.FILES.get('audio_input')
        if not audio_file:
            return JsonResponse({'error': 'Un fichier audio est obligatoire en mode Standalone.'}, status=400)
        validator = FileExtensionValidator(allowed_extensions=['wav', 'mp3', 'ogg', 'flac'])
        try:
            validator(audio_file)
        except ValidationError as e:
            return JsonResponse({'error': str(e)}, status=400)
        job.audio_input = audio_file

    # --- Source de l'avatar ---
    avatar_source = request.POST.get('avatar_source', 'gallery')
    job.avatar_source = avatar_source

    if avatar_source == 'gallery':
        avatar_name = request.POST.get('avatar_gallery_name', '')
        if not avatar_name:
            return JsonResponse({'error': 'Sélectionnez un avatar dans la galerie.'}, status=400)
        job.avatar_gallery_name = avatar_name
    else:
        avatar_file = request.FILES.get('avatar_upload')
        if not avatar_file:
            return JsonResponse({'error': "Importez une image avatar."}, status=400)
        validator = FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp'])
        try:
            validator(avatar_file)
        except ValidationError as e:
            return JsonResponse({'error': str(e)}, status=400)
        job.avatar_upload = avatar_file

    # --- Paramètres pipeline MuseTalk ---
    quality_mode = request.POST.get('quality_mode', 'fast')
    job.quality_mode = quality_mode if quality_mode in ('fast', 'quality') else 'fast'
    job.use_enhancer = request.POST.get('use_enhancer', 'false') == 'true'
    try:
        job.bbox_shift = max(-10, min(10, int(request.POST.get('bbox_shift', 0))))
    except (ValueError, TypeError):
        job.bbox_shift = 0

    job.save()
    return JsonResponse({'job_id': job.id, 'status': 'created'})


def stop(request, pk):
    """
    Stoppe la génération en cours (révoque la tâche Celery) → job relançable (bouton de cycle ↻).
    Brique commune : wama.common.utils.process_control.stop_instance.
    """
    user = _get_user(request)
    job = get_object_or_404(AvatarJob, pk=pk, user=user)
    if job.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({'id': job.id, 'status': job.status})
    from wama.common.utils.process_control import stop_instance
    new_status = stop_instance(job, error_field='error_message')
    return JsonResponse({'id': job.id, 'status': new_status})


def start(request, pk):
    """GET : Lance la génération d'un AvatarJob via Celery (queue gpu)."""
    user = _get_user(request)
    job = get_object_or_404(AvatarJob, pk=pk, user=user)

    if job.status == 'RUNNING':
        return JsonResponse({'error': 'Job déjà en cours.'}, status=400)

    _ensure_workers_imported()
    task = _generate_avatar.delay(job.id)

    job.status = 'PENDING'
    job.task_id = task.id
    job.progress = 0
    job.error_message = ''
    job.save(update_fields=['status', 'task_id', 'progress', 'error_message'])

    return JsonResponse({'task_id': task.id, 'status': 'started'})


def progress(request, pk):
    """GET : Retourne l'état de progression d'un AvatarJob."""
    user = _get_user(request)
    job = get_object_or_404(AvatarJob, pk=pk, user=user)

    cached_progress = cache.get(f"avatarizer_progress_{job.id}")
    prog = cached_progress if cached_progress is not None else job.progress

    video_url = None
    if job.status == 'SUCCESS' and job.output_video:
        video_url = settings.MEDIA_URL + job.output_video.name

    avatar_name = job.avatar_gallery_name if job.avatar_source == 'gallery' else 'Photo importée'

    estimated_seconds = 0.0
    if job.status in ('PENDING', 'RUNNING'):
        try:
            from wama.model_manager.services.eta_estimator import estimate
            # durée connue (run précédent) sinon ~ texte/15 (≈ débit parole) en mode pipeline
            _size = float(job.duration_seconds or 0)
            if not _size and job.mode == 'pipeline' and job.text_content:
                _size = len(job.text_content) / 15.0
            estimated_seconds = estimate(f'avatarizer:{job.quality_mode}',
                                         size=_size, unit='video_sec', model_loaded=True)
        except Exception:
            pass

    return JsonResponse({
        'progress': prog,
        'status': job.status,
        'estimated_seconds': estimated_seconds,
        'video_url': video_url,
        'error': job.error_message,
        'mode': job.mode,
        'avatar_name': avatar_name,
        'tts_model': job.get_tts_model_display(),
        'language': job.language,
        'voice_preset': job.voice_preset,
        'quality_mode': job.quality_mode,
        'quality_mode_label': job.get_quality_mode_display(),
        'bbox_shift': job.bbox_shift,
        'use_enhancer': job.use_enhancer,
        'text_preview': (job.text_content or '')[:80],
    })


def global_progress(request):
    """Progression globale de la file (toujours affichée côté UI).

    Renvoie {total, done, running, overall_progress} pour le composant commun
    common/_global_progress.html + wama-global-progress.js.
    """
    user = _get_user(request)
    jobs = list(AvatarJob.objects.filter(user=user).values('id', 'status', 'progress'))

    total = len(jobs)
    done = sum(1 for j in jobs if j['status'] == 'SUCCESS')
    running = sum(1 for j in jobs if j['status'] == 'RUNNING')

    if total:
        acc = 0
        for j in jobs:
            if j['status'] == 'SUCCESS':
                acc += 100
            elif j['status'] == 'RUNNING':
                cached = cache.get(f"avatarizer_progress_{j['id']}")
                acc += cached if cached is not None else (j['progress'] or 0)
            else:
                acc += j['progress'] or 0
        overall = int(acc / total)
    else:
        overall = 0

    return JsonResponse({
        'total': total,
        'done': done,
        'running': running,
        'failed': sum(1 for j in jobs if j['status'] == 'FAILURE'),
        'overall_progress': overall,
    })


@require_POST
def update_options(request, pk):
    """POST : Met à jour les paramètres d'un AvatarJob (avant relance)."""
    user = _get_user(request)
    job = get_object_or_404(AvatarJob, pk=pk, user=user)

    if job.status == 'RUNNING':
        return JsonResponse({'error': 'Impossible de modifier un job en cours.'}, status=400)

    # TTS (pipeline seulement)
    if job.mode == 'pipeline':
        tts_model = request.POST.get('tts_model')
        if tts_model:
            job.tts_model = tts_model
        language = request.POST.get('language')
        if language:
            job.language = language
        voice_preset = request.POST.get('voice_preset')
        if voice_preset:
            job.voice_preset = voice_preset

    # MuseTalk params
    quality_mode = request.POST.get('quality_mode')
    if quality_mode in ('fast', 'quality'):
        job.quality_mode = quality_mode

    job.use_enhancer = request.POST.get('use_enhancer', 'false') == 'true'

    try:
        job.bbox_shift = max(-10, min(10, int(request.POST.get('bbox_shift', job.bbox_shift))))
    except (ValueError, TypeError):
        pass

    job.save(update_fields=['tts_model', 'language', 'voice_preset', 'quality_mode', 'use_enhancer', 'bbox_shift'])
    return JsonResponse({'status': 'updated'})


@require_POST
def delete(request, pk):
    """POST : Supprime un AvatarJob et ses fichiers associés."""
    user = _get_user(request)
    job = get_object_or_404(AvatarJob, pk=pk, user=user)

    # Le membre était-il dans un batch ? (flag UI ; total/cleanup = signal batch_sync)
    from .models import BatchAvatarJobItem
    from wama.common.utils.batch_utils import find_member_batch
    parent_batch = find_member_batch(BatchAvatarJobItem, job=job)

    for field_name in ['audio_input', 'avatar_upload', 'output_video']:
        f = getattr(job, field_name)
        if f:
            try:
                path = f.path
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    job.delete()  # signal batch_sync : recale total / supprime le batch vidé
    return JsonResponse({'status': 'deleted', 'batch_changed': parent_batch is not None})


@require_POST
def duplicate(request, pk):
    """POST : Duplique un AvatarJob (entrées partagées, sortie vidée).

    Si le job appartient à un lot, la copie rejoint le MÊME lot (élément frère).
    """
    user = _get_user(request)
    job = get_object_or_404(AvatarJob, pk=pk, user=user)

    copy = duplicate_instance(
        job,
        reset_fields={'status': 'PENDING', 'progress': 0, 'task_id': '', 'error_message': ''},
        clear_fields=['output_video'],
    )

    orig_item = BatchAvatarJobItem.objects.filter(job=job).select_related('batch').first()
    if orig_item:
        from django.db.models import Max
        batch = orig_item.batch
        idx = (batch.items.aggregate(m=Max('row_index'))['m'] or 0) + 1
        BatchAvatarJobItem.objects.create(batch=batch, job=copy, row_index=idx)
        batch.total = batch.items.count()
        batch.save(update_fields=['total'])
    else:
        _wrap_job_in_batch(copy)

    return JsonResponse({'status': 'duplicated', 'job_id': copy.id})


def download(request, pk):
    """GET : Télécharge la vidéo avatar générée."""
    user = _get_user(request)
    job = get_object_or_404(AvatarJob, pk=pk, user=user)

    if job.status != 'SUCCESS' or not job.output_video:
        raise Http404("Vidéo non disponible.")

    try:
        response = FileResponse(
            open(job.output_video.path, 'rb'),
            content_type='video/mp4',
        )
        filename = os.path.basename(job.output_video.name)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except FileNotFoundError:
        raise Http404("Fichier vidéo introuvable.")


@require_POST
def extract_text(request):
    """
    POST : Extrait le texte d'un fichier (TXT, PDF, DOCX, CSV, MD).

    Accepte soit :
      - 'file'       : fichier uploadé (multipart, depuis l'explorateur Windows)
      - 'media_path' : chemin relatif depuis MEDIA_ROOT (fichier déjà sur le serveur / filemanager)
    """
    ALLOWED_EXTS = {'txt', 'md', 'pdf', 'docx', 'csv'}

    try:
        from wama.synthesizer.utils.text_extractor import extract_text_from_file
    except ImportError as e:
        return JsonResponse({'error': f'Module text_extractor indisponible : {e}'}, status=500)

    try:
        media_path = request.POST.get('media_path', '').strip()

        if media_path:
            # Fichier déjà sur le serveur (depuis filemanager)
            target = (Path(settings.MEDIA_ROOT) / media_path).resolve()
            media_root = Path(settings.MEDIA_ROOT).resolve()
            if not str(target).startswith(str(media_root)):
                return JsonResponse({'error': 'Chemin non autorisé.'}, status=403)
            if not target.exists():
                return JsonResponse({'error': 'Fichier introuvable.'}, status=404)
            ext = target.suffix.lstrip('.').lower()
            if ext not in ALLOWED_EXTS:
                return JsonResponse({'error': f'Format non supporté : .{ext}'}, status=400)
            text = extract_text_from_file(str(target))

        else:
            # Upload direct (depuis l'explorateur Windows)
            upload = request.FILES.get('file')
            if not upload:
                return JsonResponse({'error': 'Aucun fichier fourni.'}, status=400)
            ext = upload.name.rsplit('.', 1)[-1].lower() if '.' in upload.name else ''
            if ext not in ALLOWED_EXTS:
                return JsonResponse({'error': f'Format non supporté : .{ext}'}, status=400)

            with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False) as tmp:
                for chunk in upload.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            try:
                text = extract_text_from_file(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return JsonResponse({'text': text})

    except Exception as e:
        logger.error(f'[avatarizer] extract_text error: {e}', exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


def gallery_list(request):
    """GET : Retourne la liste des avatars disponibles dans la galerie partagée."""
    images = _gallery_images()
    gallery_url = settings.MEDIA_URL + 'avatarizer/gallery/'
    return JsonResponse({
        'images': [{'name': name, 'url': gallery_url + name} for name in images]
    })


# ---------------------------------------------------------------------------
# Batch — import par fichier (format à balises unifié) + groupes
# ---------------------------------------------------------------------------

def _avatar_nature(job: AvatarJob) -> str:
    """Nature d'un job = son mode (pipeline / standalone)."""
    return job.mode or 'pipeline'


def _wrap_job_in_batch(job: AvatarJob) -> BatchAvatarJob:
    """Enveloppe un job autonome dans un lot-de-1."""
    batch = BatchAvatarJob.objects.create(user=job.user, total=1)
    BatchAvatarJobItem.objects.create(batch=batch, job=job, row_index=0)
    return batch


def _auto_wrap_orphans(user) -> None:
    """Enveloppe paresseusement les jobs sans lot dans des lots-de-1."""
    orphans = AvatarJob.objects.filter(user=user, batch_item__isnull=True).order_by('id')
    for job in orphans:
        _wrap_job_in_batch(job)


def _get_batches_list(user):
    """Liste de dicts {obj, items, total, done_count, has_success} pour le template."""
    _auto_wrap_orphans(user)
    batches = BatchAvatarJob.objects.filter(user=user).prefetch_related('items__job').order_by('-created_at')
    result = []
    for batch in batches:
        items = [it.job for it in batch.items.select_related('job').order_by('row_index') if it.job]
        done = sum(1 for j in items if j.status == 'SUCCESS')
        has_success = any(j.status == 'SUCCESS' and j.output_video for j in items)
        result.append({
            'obj': batch,
            'items': items,
            'total': len(items),
            'done_count': done,
            'has_success': has_success,
        })
    # lots multi-éléments en premier
    result.sort(key=lambda b: 0 if b['total'] > 1 else 1)
    return result


def batch_template(request):
    """GET : Modèle de fichier batch (format à balises unifié)."""
    from django.http import HttpResponse
    lines = [
        "# WAMA Avatarizer — fichier batch (format à balises)",
        "# Pipeline (texte → TTS → avatar) :",
        '#   -p "texte à dire" -r nom_avatar.png [--voice default] [--language fr] [--tts xtts_v2] [--quality fast] [-o sortie.mp4]',
        "# Standalone (audio déjà prêt) :",
        '#   -i chemin/audio.wav -r nom_avatar.png [--quality quality]',
        "# -r = nom d'un avatar de la galerie partagée. Une ligne = un job.",
        "",
        '-p "Bonjour et bienvenue sur WAMA." -r avatar1.png --voice default --language fr',
        '-p "Ceci est une seconde vidéo." -r avatar1.png --language fr --quality quality',
    ]
    resp = HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="batch_avatarizer_template.txt"'
    return resp


def _parse_avatar_batch_from_request(request):
    """Parse le batch_file uploadé (format à balises) → (rows, warnings)."""
    from wama.common.utils.batch_parsers import (
        extract_batch_file_text, is_structured_batch_text, parse_unified_batch,
    )
    SUPPORTED = ('txt', 'md', 'csv', 'pdf', 'docx')
    batch_file = request.FILES.get('batch_file')
    if not batch_file:
        raise ValueError('Aucun fichier fourni')
    ext = os.path.splitext(batch_file.name)[1][1:].lower()
    if ext not in SUPPORTED:
        raise ValueError(f'Format non supporté : .{ext}')

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
            for chunk in batch_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        text = extract_batch_file_text(tmp_path)
        if not is_structured_batch_text(text):
            raise ValueError(
                'Format attendu : CSV à en-têtes ou balises (-p/-i/-r…). Voir le modèle.'
            )
        items, warnings = parse_unified_batch(tmp_path)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    rows, extra = [], []
    for it in items:
        row = _unified_item_to_avatar_row(it)
        if row.get('error'):
            extra.append(f"Ligne {it.get('line_num')} : {row['error']}, ignorée")
            continue
        rows.append(row)
    if not rows:
        extra.append('Aucune ligne valide')
    return rows, warnings + extra


def _unified_item_to_avatar_row(it: dict) -> dict:
    """Mappe un item unifié → champs AvatarJob. {'error': msg} si invalide."""
    opts = it.get('options') or {}
    reference = it.get('reference')
    if not reference:
        return {'error': 'avatar de référence (-r) manquant'}

    prompt = it.get('prompt')
    audio = it.get('input')
    if prompt:
        mode = 'pipeline'
    elif audio:
        mode = 'standalone'
    else:
        return {'error': 'ni texte (-p) ni audio (-i) fourni'}

    quality = opts.get('quality', 'fast')
    quality = quality if quality in ('fast', 'quality') else 'fast'
    try:
        bbox = max(-10, min(10, int(opts.get('bbox', 0))))
    except (ValueError, TypeError):
        bbox = 0

    return {
        'mode': mode,
        'text_content': prompt or '',
        'audio_path': audio or '',
        'avatar_gallery_name': reference,
        'tts_model': opts.get('tts') or opts.get('model') or 'xtts_v2',
        'language': opts.get('language', 'fr'),
        'voice_preset': opts.get('voice', 'default'),
        'quality_mode': quality,
        'use_enhancer': str(opts.get('enhancer', '')).lower() in ('1', 'true', 'yes'),
        'bbox_shift': bbox,
        'output': it.get('output', ''),
        'line_num': it.get('line_num'),
    }


@require_POST
def batch_preview(request):
    """POST : Aperçu d'un fichier batch (sans création)."""
    try:
        rows, warnings = _parse_avatar_batch_from_request(request)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    preview = [
        {
            'mode': r['mode'],
            'avatar': r['avatar_gallery_name'],
            'text': (r['text_content'] or r['audio_path'])[:60],
            'language': r['language'],
        }
        for r in rows
    ]
    return JsonResponse({'items': preview, 'warnings': warnings, 'count': len(rows)})


@require_POST
def batch_create(request):
    """POST : Crée N AvatarJob depuis un fichier batch, groupés par nature (mode)."""
    user = _get_user(request)
    try:
        rows, warnings = _parse_avatar_batch_from_request(request)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    media_root = Path(settings.MEDIA_ROOT).resolve()

    def _make_job(row):
        job = AvatarJob(
            user=user,
            mode=row['mode'],
            text_content=row['text_content'],
            tts_model=row['tts_model'],
            language=row['language'],
            voice_preset=row['voice_preset'],
            avatar_source='gallery',
            avatar_gallery_name=row['avatar_gallery_name'],
            quality_mode=row['quality_mode'],
            use_enhancer=row['use_enhancer'],
            bbox_shift=row['bbox_shift'],
        )
        # Standalone : rattacher l'audio s'il résout sous MEDIA_ROOT (partage, pas de copie)
        if row['mode'] == 'standalone' and row['audio_path']:
            try:
                target = (media_root / row['audio_path']).resolve()
                if str(target).startswith(str(media_root)) and target.exists():
                    job.audio_input.name = os.path.relpath(str(target), str(media_root)).replace('\\', '/')
            except Exception:
                pass
        job.save()
        return job

    jobs = [_make_job(r) for r in rows]

    batches = group_into_batches_by_nature(
        jobs,
        nature_of=_avatar_nature,
        create_batch=lambda nature, total: BatchAvatarJob.objects.create(user=user, total=total),
        link_item=lambda batch, job, idx: BatchAvatarJobItem.objects.create(
            batch=batch, job=job, row_index=idx),
    )

    return JsonResponse({
        'status': 'created',
        'jobs': len(jobs),
        'batches': len(batches),
        'warnings': warnings,
    })


@require_POST
def consolidate(request):
    """POST : Regroupe les jobs autonomes en lots par nature (mode)."""
    user = _get_user(request)
    # défait les lots-de-1 existants puis regroupe par nature
    singles = list(BatchAvatarJob.objects.filter(user=user, total=1))
    job_ids = []
    for b in singles:
        job_ids += [it.job_id for it in b.items.all() if it.job_id]
    jobs = list(AvatarJob.objects.filter(id__in=job_ids).order_by('id')) if job_ids else \
        list(AvatarJob.objects.filter(user=user, batch_item__isnull=True).order_by('id'))

    if not jobs:
        return JsonResponse({'status': 'noop', 'batches': 0})

    def _unwrap(ids):
        BatchAvatarJobItem.objects.filter(job_id__in=ids).delete()
        BatchAvatarJob.objects.filter(user=user, total=1, items__isnull=True).delete()

    batches = group_into_batches_by_nature(
        jobs,
        nature_of=_avatar_nature,
        create_batch=lambda nature, total: BatchAvatarJob.objects.create(user=user, total=total),
        link_item=lambda batch, job, idx: BatchAvatarJobItem.objects.create(
            batch=batch, job=job, row_index=idx),
        unwrap_singletons=_unwrap,
    )
    # purge des lots devenus vides
    BatchAvatarJob.objects.filter(user=user, items__isnull=True).delete()
    return JsonResponse({'status': 'ok', 'batches': len(batches)})


@require_POST
def batch_start(request, pk):
    """POST : Lance tous les jobs non terminés d'un lot."""
    user = _get_user(request)
    batch = get_object_or_404(BatchAvatarJob, pk=pk, user=user)
    _ensure_workers_imported()

    started = 0
    for it in batch.items.select_related('job').order_by('row_index'):
        job = it.job
        if not job or job.status == 'RUNNING':
            continue
        task = _generate_avatar.delay(job.id)
        job.status = 'PENDING'
        job.task_id = task.id
        job.progress = 0
        job.error_message = ''
        job.save(update_fields=['status', 'task_id', 'progress', 'error_message'])
        started += 1
    return JsonResponse({'status': 'started', 'count': started})


@require_POST
def batch_duplicate(request, pk):
    """POST : Duplique un lot et tous ses jobs (entrées partagées, sorties vidées)."""
    user = _get_user(request)
    batch = get_object_or_404(BatchAvatarJob, pk=pk, user=user)

    new_batch = BatchAvatarJob.objects.create(user=user, total=batch.total)
    for it in batch.items.select_related('job').order_by('row_index'):
        if not it.job:
            continue
        copy = duplicate_instance(
            it.job,
            reset_fields={'status': 'PENDING', 'progress': 0, 'task_id': '', 'error_message': ''},
            clear_fields=['output_video'],
        )
        BatchAvatarJobItem.objects.create(batch=new_batch, job=copy, row_index=it.row_index)
    new_batch.total = new_batch.items.count()
    new_batch.save(update_fields=['total'])
    return JsonResponse({'status': 'duplicated', 'batch_id': new_batch.id})


def batch_download(request, pk):
    """GET : ZIP de toutes les vidéos générées d'un lot (mono-format MP4)."""
    import io
    import zipfile
    from django.http import HttpResponse
    user = _get_user(request)
    batch = get_object_or_404(BatchAvatarJob, pk=pk, user=user)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for it in batch.items.select_related('job').order_by('row_index'):
            job = it.job
            if job and job.status == 'SUCCESS' and job.output_video:
                try:
                    archive.write(job.output_video.path, os.path.basename(job.output_video.name))
                except Exception:
                    continue
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="batch_avatarizer_{pk}.zip"'
    return response


@require_POST
def batch_delete(request, pk):
    """POST : Supprime un lot, ses jobs et leurs fichiers."""
    user = _get_user(request)
    batch = get_object_or_404(BatchAvatarJob, pk=pk, user=user)

    jobs = [it.job for it in batch.items.select_related('job').all() if it.job]
    for job in jobs:
        if job.task_id:
            try:
                from celery.result import AsyncResult
                AsyncResult(job.task_id).revoke(terminate=False)
            except Exception:
                pass
    safe_delete_file(batch, 'batch_file')
    batch.delete()  # CASCADE supprime les liens
    for job in jobs:
        for fld in ('audio_input', 'avatar_upload', 'output_video'):
            safe_delete_file(job, fld)
        cache.delete(f"avatarizer_progress_{job.id}")
        job.delete()
    return JsonResponse({'status': 'deleted', 'batch_id': pk})
