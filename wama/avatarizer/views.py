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

from .models import AvatarJob
from wama.synthesizer.models import CustomVoice
from wama.accounts.views import get_or_create_anonymous_user

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

    return JsonResponse({
        'progress': prog,
        'status': job.status,
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

    for field_name in ['audio_input', 'avatar_upload', 'output_video']:
        f = getattr(job, field_name)
        if f:
            try:
                path = f.path
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    job.delete()
    return JsonResponse({'status': 'deleted'})


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
