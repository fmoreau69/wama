import os
import re
import io
import cv2
import yt_dlp
import zipfile
import mimetypes
import requests
from PIL import Image
from urllib.parse import urlparse
import subprocess as sp
from celery.result import AsyncResult

from django.http import FileResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import close_old_connections, transaction
from django.core.cache import cache
from django.contrib.auth.models import User
from django.template import loader
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView
from django.urls import reverse
from django.utils.encoding import iri_to_uri

from .models import Media, GlobalSettings, UserSettings
from .forms import MediaSettingsForm, UserSettingsForm
from .tasks import process_single_media, process_user_media_batch, stop_process
from .utils.media_utils import get_input_media_path, get_output_media_path, get_blurred_media_path, get_unique_filename
from .utils.yolo_utils import get_model_path, list_available_models, list_models_by_type
from .utils.sam3_manager import (
    get_sam3_status, setup_hf_auth, validate_sam3_prompt,
    get_sam3_requirements, get_recommended_prompt_examples
)

from ..accounts.views import get_or_create_anonymous_user
from ..settings import MEDIA_ROOT, MEDIA_INPUT_ROOT, MEDIA_OUTPUT_ROOT
from ..common.utils.console_utils import get_console_lines, get_celery_worker_logs
from ..common.utils.video_utils import get_media_info
from ..common.utils.video_utils import upload_media_from_url
from ..common.utils.media_paths import get_app_media_path, ensure_app_media_dirs


class IndexView(View):
    """Page principale de Anonymizer."""

    def get(self, request):
        return render(request, 'anonymizer/index.html', get_context(request))

    def post(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
        UserSettings.objects.filter(user_id=user.id).update(media_added=1)

        try:
            media_file = request.FILES.get('file')

            # Case 1: text file containing paths or URLs
            if media_file and media_file.name.endswith(('.txt', '.csv', '.log')):
                lines = media_file.read().decode('utf-8').splitlines()
                added, failed = [], []

                for line in lines:
                    path = windows_path_to_wsl(line)
                    if not path:
                        continue
                    try:
                        # Get user-specific input directory
                        user_input_dir = get_app_media_path('anonymizer', user.id, 'input')
                        user_input_dir.mkdir(parents=True, exist_ok=True)

                        if is_url(path):
                            video_path = upload_media_from_url(path, str(user_input_dir))
                        else:
                            if not os.path.isfile(path):
                                raise FileNotFoundError("Local path not found or inaccessible")
                            filename = os.path.basename(path)
                            unique_filename = get_unique_filename(str(user_input_dir), filename)
                            dest_path = os.path.join(str(user_input_dir), unique_filename)
                            with open(path, 'rb') as src, open(dest_path, 'wb') as dst:
                                dst.write(src.read())
                            video_path = dest_path
                        # Crée Media en DB
                        media = process_media(video_path, user)
                        added.append(media)
                    except Exception as e:
                        failed.append((path, str(e)))

                return JsonResponse({'success': True, 'added': added, 'errors': failed})

            # Case 2: direct upload (file or URL)
            video_path = upload_from_url(request, user)
            media_result = process_media(video_path, user)
            if isinstance(media_result, dict) and media_result.get('is_valid'):
                return JsonResponse({'success': True, 'media': media_result})
            else:
                return JsonResponse({'success': False, 'error': media_result}, status=400)

        except ValueError as e:
            return JsonResponse({'is_valid': False, 'error': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'is_valid': False, 'error': f"Server error: {e}"}, status=500)


def windows_path_to_wsl(path):
    r"""
    Convertit un chemin Windows D:\... en chemin WSL /mnt/d/...
    Ignore les URLs (http:// ou https://).
    """
    path = path.strip().replace('\\', '/')
    if path.lower().startswith(('http://', 'https://')):
        return path
    import re
    match = re.match(r'^([a-zA-Z]):/(.*)', path)
    if match:
        drive = match.group(1).lower()
        rest = match.group(2)
        return f"/mnt/{drive}/{rest}"
    return path


def is_url(path):
    """Check if the string is a valid URL."""
    try:
        result = urlparse(path)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def process_media(video_path, user):
    """Create a Media object from the given path and assign metadata."""
    try:
        filename = os.path.basename(video_path)
        ext = os.path.splitext(filename)[1]
        # Use user-specific path
        relative_path = f'anonymizer/{user.id}/input/{filename}'
        media = Media.objects.create(file=relative_path, file_ext=ext, user=user)

        mime_type, _ = mimetypes.guess_type(video_path)
        if mime_type and mime_type.startswith("video/"):
            vid = cv2.VideoCapture(str(video_path))
            add_media_to_db(media, vid)
        else:
            add_media_to_db(media, video_path)

        return {
            'is_valid': True,
            'id': media.id,
            'name': filename,
            'url': media.file.url,
            'preview_url': reverse('anonymizer:preview_media', args=[media.id]),
            'file_ext': media.file_ext,
            'username': user.username,
            'fps': media.fps,
            'width': media.width,
            'height': media.height,
            'duration': media.duration_inMinSec,
        }
    except Exception as e:
        return str(e)


def upload_from_url(request, user):
    """Handle media from either an uploaded file or a form URL."""
    media_file = request.FILES.get('file')
    media_url = request.POST.get('media_url')

    # Use user-specific input directory
    output_path = get_app_media_path('anonymizer', user.id, 'input')
    output_path.mkdir(parents=True, exist_ok=True)
    output_path = str(output_path)

    if media_file:
        return handle_uploaded_media_file(media_file, output_path)
    elif media_url:
        return upload_media_from_url(media_url, output_path)

    raise ValueError("No media file or URL provided.")


def handle_uploaded_media_file(media_file, output_path):
    """Save uploaded media file to disk with a unique name."""
    allowed_mime_types = [
        'video/mp4', 'video/x-msvideo', 'video/quicktime', 'video/x-matroska',
        'image/jpeg', 'image/png', 'image/jpg', 'image/bmp'
    ]
    mime_type, _ = mimetypes.guess_type(media_file.name)
    if mime_type not in allowed_mime_types:
        raise ValueError(f"Unsupported file type: {mime_type}")

    filename = get_unique_filename(output_path, media_file.name)
    save_path = os.path.join(output_path, filename)

    with open(save_path, 'wb+') as dest:
        for chunk in media_file.chunks():
            dest.write(chunk)

    return save_path


def add_media_to_db(media, vid_or_path):
    """Populate the Media model with metadata from a video or image using common utility."""
    if isinstance(vid_or_path, str):
        # It's a file path - use the common utility
        info = get_media_info(vid_or_path)
        media.width = info['width']
        media.height = info['height']
        media.fps = info['fps']
        media.duration_inSec = info['duration']
        media.duration_inMinSec = f"{int(info['duration'] // 60)}:{int(info['duration'] % 60):02d}"
        media.properties = info['properties']
        media.media_type = info['media_type']
        media.save()
    else:
        # It's already a VideoCapture object - process directly
        vid = vid_or_path
        if not vid.isOpened():
            raise ValueError("Could not open video file")

        fps = vid.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0:
            fps = 25  # Default fallback

        media.fps = fps
        media.width = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))
        media.height = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = vid.get(cv2.CAP_PROP_FRAME_COUNT)
        media.duration_inSec = total_frames / fps if fps > 0 else 0
        media.duration_inMinSec = f"{int(media.duration_inSec // 60)}:{int(media.duration_inSec % 60):02d}"
        media.properties = f"{media.width}x{media.height} ({media.fps:.2f}fps)"
        media.media_type = "video"
        media.save()


class ProcessView(View):
    """
    Endpoint pour lancer le traitement batch des médias.
    Le GET redirige vers la page principale.
    Le POST lance le traitement asynchrone via Celery.
    """
    def get(self, request):
        # Rediriger vers la page principale au lieu de rendre le template
        return redirect('anonymizer:index')

    def post(self, request):
        try:
            import logging
            logger = logging.getLogger('anonymizer.process')

            user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
            logger.info(f"[ProcessView] Starting process for user {user.id} ({user.username})")

            # Get all user media (not just unprocessed)
            all_medias = Media.objects.filter(user=user).order_by('id')

            if not all_medias.exists():
                logger.warning(f"[ProcessView] No media found for user {user.username}")
                return JsonResponse({"task_id": None, "error": "No media to process"})

            # Reset all media to allow reprocessing
            for media in all_medias:
                media.processed = False
                media.blur_progress = 0
                media.save(update_fields=['processed', 'blur_progress'])
                # Clear cache for this media
                cache.delete(f"media_progress_{media.id}")
                logger.info(f"[ProcessView] Reset media {media.id} for reprocessing")

            batch_medias = list(all_medias.values_list('id', flat=True))
            logger.info(f"[ProcessView] Found {len(batch_medias)} media(s) to process: {batch_medias}")

            cache.set(f"batch_media_ids_{user.id}", batch_medias, timeout=3600)

            # Lancer batch task qui va enchaîner toutes les tâches individuelles
            logger.info(f"[ProcessView] Calling process_user_media_batch.delay({user.id})")
            task = process_user_media_batch.delay(user.id)
            logger.info(f"[ProcessView] Task created: {task.id}")
            logger.info(f"[ProcessView] Task state immediately after creation: {task.state}")

            # Test Redis connection
            try:
                from celery import current_app
                logger.info(f"[ProcessView] Celery broker: {current_app.conf.broker_url}")
                logger.info(f"[ProcessView] Celery backend: {current_app.conf.result_backend}")
            except Exception as e:
                logger.error(f"[ProcessView] Error checking Celery config: {e}")

            cache.set(f"user_task_{user.id}", task.id, timeout=3600)
            return JsonResponse({"task_id": task.id})
        except Exception as e:
            import traceback
            logger = logging.getLogger('anonymizer.process')
            logger.error(f"[ProcessView] ERROR: {e}")
            logger.error(traceback.format_exc())
            print("🚨 ERREUR upload:", e)
            traceback.print_exc()
            return JsonResponse({'is_valid': False, 'error': str(e)}, status=500)

    def display_console(self, request):
        if request.POST.get('url', 'anonymizer:upload.display_console'):
            command = "path/to/builder.pl --router " + 'hostname'
            pipe = sp.Popen(command.split(), stdout=sp.PIPE, stderr=sp.PIPE)
            console = pipe.stdout.read()
            return render(self.request, 'anonymizer/index.html', {'console': console})
        return None


def preview_media(request, media_id):
    """Return metadata + absolute URL to play a media file in-place."""
    viewer = request.user if request.user.is_authenticated else User.objects.filter(username="anonymous").first()
    media = get_object_or_404(Media, pk=media_id)

    if media.user != viewer and not (request.user.is_authenticated and request.user.is_staff):
        return HttpResponseForbidden("You do not have access to this media.")

    media_url = request.build_absolute_uri(iri_to_uri(media.file.url))
    mime_type, _ = mimetypes.guess_type(media.file.path)

    return JsonResponse({
        "name": os.path.basename(media.file.name),
        "url": media_url,
        "mime_type": mime_type or "video/mp4",
        "duration": media.duration_inMinSec,
        "resolution": f"{media.width}x{media.height}" if media.width and media.height else "",
    })


def console_content(request):
    """Retourne un flux textuel des logs en cours pour affichage console (via Redis/Cache + logs Celery)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    console_lines = get_console_lines(user.id, limit=100)
    celery_lines = get_celery_worker_logs(limit=100)
    all_lines = (celery_lines + console_lines)[-200:]
    return JsonResponse({'output': all_lines})


def debug_media_status(request):
    """Debug view to check media status."""
    import logging
    logger = logging.getLogger('anonymizer.debug')

    # Session info
    session_info = {
        'session_key': request.session.session_key,
        'session_data': dict(request.session.items()) if hasattr(request.session, 'items') else {},
        'session_age': request.session.get_expiry_age() if hasattr(request.session, 'get_expiry_age') else None,
    }

    # User info
    user_info = {
        'is_authenticated': request.user.is_authenticated,
        'username': request.user.username if request.user.is_authenticated else 'AnonymousUser',
        'user_id': request.user.id if request.user.is_authenticated else None,
    }

    logger.info(f"[debug_media_status] Session: {session_info}")
    logger.info(f"[debug_media_status] User: {user_info}")

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    medias = Media.objects.filter(user=user).order_by('-id')[:10]

    result = {
        'session': session_info,
        'user_info': user_info,
        'effective_user': user.username,
        'effective_user_id': user.id,
        'total_medias': Media.objects.filter(user=user).count(),
        'unprocessed_medias': Media.objects.filter(user=user, processed=False).count(),
        'medias': []
    }

    for m in medias:
        result['medias'].append({
            'id': m.id,
            'title': m.title or f"Media {m.id}",
            'processed': m.processed,
            'blur_progress': m.blur_progress,
            'file': str(m.file),
            'user': m.user.username,
            'user_id': m.user.id,
        })

    return JsonResponse(result, json_dumps_params={'indent': 2})


def get_model_recommendations(request):
    """
    API endpoint pour obtenir les recommandations de modèles basées sur les classes à flouter.

    GET params:
        - classes: Liste des classes séparées par des virgules (ex: "person,car,face")
        - current_model: Modèle actuellement sélectionné (optionnel)

    Returns:
        JSON avec les recommandations de modèles
    """
    from wama.anonymizer.utils.model_selector import get_model_selection_info

    # Get parameters
    classes_str = request.GET.get('classes', '')
    current_model = request.GET.get('current_model', None)

    if not classes_str:
        return JsonResponse({
            'status': 'error',
            'message': 'Paramètre "classes" manquant'
        }, status=400)

    # Parse classes list
    classes_to_blur = [cls.strip() for cls in classes_str.split(',') if cls.strip()]

    if not classes_to_blur:
        return JsonResponse({
            'status': 'error',
            'message': 'Aucune classe fournie'
        }, status=400)

    # Get model selection info
    try:
        info = get_model_selection_info(classes_to_blur, current_model)
        return JsonResponse(info)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


def get_process_progress(request):
    """
    Retourne la progression globale (tous médias de l'utilisateur) ou individuelle (par media_id).
    - Si ?media_id=... est fourni: lit Media.blur_progress ou cache("media_progress_{id}")
    - Sinon: moyenne des progrès des médias en cours pour l'utilisateur
    """
    import logging
    logger = logging.getLogger('anonymizer.progress')

    media_id = request.GET.get('media_id')
    if media_id:
        try:
            media = Media.objects.get(pk=int(media_id))
            cache_progress = cache.get(f"media_progress_{media.id}")
            db_progress = media.blur_progress or 0

            # Prefer cache, fallback to DB
            progress = int(cache_progress if cache_progress is not None else db_progress)

            logger.info(f"[get_process_progress] media_id={media_id}, cache={cache_progress}, db={db_progress}, final={progress}, processed={media.processed}")

            return JsonResponse({"progress": max(0, min(100, progress))})
        except Media.DoesNotExist:
            logger.warning(f"[get_process_progress] Media {media_id} not found")
            return JsonResponse({"progress": 0})

    # Global progress for current user
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch_ids = cache.get(f"batch_media_ids_{user.id}")
    if batch_ids:
        medias = list(Media.objects.filter(id__in=batch_ids).order_by('id'))
    else:
        medias = list(Media.objects.filter(user=user).order_by('id'))

    if not medias:
        return JsonResponse({"progress": 0})

    values = []
    for m in medias:
        if m.processed:
            values.append(100)
        else:
            values.append(int(cache.get(f"media_progress_{m.id}", m.blur_progress or 0)))
    avg = sum(values) // len(values) if values else 0
    return JsonResponse({"progress": max(0, min(100, avg))})


def task_status(request, task_id):
    res = AsyncResult(task_id)
    return JsonResponse({"status": res.status})


def download_media(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    media_id = request.POST.get('media_id')
    print(f"[download_media] Received media_id: {media_id}")

    if not media_id:
        print("[download_media] ✗ Missing media_id")
        return HttpResponseBadRequest("Missing media_id.")

    media = get_object_or_404(Media, pk=media_id)
    print(f"[download_media] Media found: {media.file.name} (ext: {media.file_ext}, processed: {media.processed})")

    # Generate blurred output file path
    media_path = get_blurred_media_path(media.file.name, media.file_ext, media.user_id)
    blurred_filename = os.path.basename(media_path)
    print(f"[download_media] Looking for file: {media_path}")

    if not os.path.exists(media_path):
        print(f"[download_media] ✗ File not found: {media_path}")
        # Return to a page with context (HTML)
        context = get_context(request)
        context['error'] = f"Processed file {blurred_filename} doesn't exist."
        return render(request, 'anonymizer/index.html', context)

        # In JSON if called via JavaScript
        # return JsonResponse({'error': 'Blurred file not found.'}, status=404)

    # Serve le fichier
    try:
        response = FileResponse(open(media_path, "rb"), as_attachment=True, filename=os.path.basename(media_path))
        print(f"[download_media] ✓ Download started: {blurred_filename}")
        return response
    except Exception as e:
        print(f"[download_media] ✗ Error: {str(e)}")
        return HttpResponseBadRequest(f"Erreur lors du téléchargement : {str(e)}")


# @login_required
def download_all_media(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    print(f"[download_all_media] User: {user.username} (ID: {user.id})")

    # Check all user media first
    all_medias = Media.objects.filter(user=user)
    processed_medias = all_medias.filter(processed=True)

    print(f"[download_all_media] Total user media: {all_medias.count()}")
    print(f"[download_all_media] Processed media: {processed_medias.count()}")

    # Log each media status
    for media in all_medias:
        print(f"[download_all_media] Media ID {media.id}: {media.file.name} - processed={media.processed}")

    if not processed_medias.exists():
        error_msg = f"No processed media found. Total media: {all_medias.count()}, Processed: 0"
        print(f"[download_all_media] ERROR: {error_msg}")
        return HttpResponseBadRequest(error_msg)

    # Create a ZIP archive in memory
    zip_buffer = io.BytesIO()
    files_added = 0
    missing_files = []

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for media in processed_medias:
            file_path = get_blurred_media_path(media.file.name, media.file_ext, media.user_id)
            print(f"[download_all_media] Looking for: {file_path}")

            if os.path.exists(file_path):
                archive_name = os.path.basename(file_path)
                zip_file.write(str(file_path), arcname=archive_name)
                files_added += 1
                print(f"[download_all_media] ✓ Added to ZIP: {archive_name}")
            else:
                missing_files.append(os.path.basename(file_path))
                print(f"[download_all_media] ✗ File not found: {file_path}")

    print(f"[download_all_media] ZIP created with {files_added} files, {len(missing_files)} missing")

    if files_added == 0:
        error_msg = f"No files found on disk. Processed in DB: {processed_medias.count()}, Missing files: {', '.join(missing_files)}"
        print(f"[download_all_media] ERROR: {error_msg}")
        return HttpResponseBadRequest(error_msg)

    zip_buffer.seek(0)
    print(f"[download_all_media] ✓ Sending ZIP with {files_added} files")
    return FileResponse(zip_buffer, as_attachment=True, filename="blurred_media.zip")


def stop_process_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    user_id = request.user.id
    task_id = cache.get(f"user_task_{user_id}")
    if task_id:
        res = AsyncResult(task_id)
        res.revoke(terminate=True)
        cache.delete(f"user_task_{user_id}")
        cache.delete(f"process_progress_{user_id}")
        stop_process(user_id)  # set stop flag pour toutes les tasks individuelles

    return JsonResponse({"status": "stopped"})


def refresh(request):
    """
    Refreshes template according to the argument supplied: 'content', 'media_table', 'media_settings', 'global_settings'
    """
    template_name = request.GET.get('template_name')
    if not template_name:
        return JsonResponse({'error': "Paramètre 'template_name' manquant."}, status=400)

    try:
        template = loader.get_template(f'anonymizer/upload/{template_name}.html')
    except Exception as e:
        return JsonResponse({'error': f"Template introuvable : {e}"}, status=500)

    context = get_context(request)
    return JsonResponse({'render': template.render(context, request)})


def queue_count(request):
    """Returns the current queue count for AJAX updates."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    count = Media.objects.filter(user=user).count()
    return JsonResponse({'count': count})


def get_context(request):
    if request.user.is_authenticated:
        user = request.user
    else:
        user = get_or_create_anonymous_user()

    user_settings, _ = UserSettings.objects.get_or_create(user=user)
    # Ensure sensible defaults for initial view (show_preview True)
    if user_settings.show_preview is None:
        user_settings.show_preview = True
        user_settings.save(update_fields=['show_preview'])
    user_settings_form = UserSettingsForm(instance=user_settings)

    global_settings = GlobalSettings.objects.all()
    medias = Media.objects.filter(user=user).order_by('id')

    media_settings_form = {}
    ms_values = {}

    for media in medias:
        media_settings_form[media.id] = MediaSettingsForm(instance=media)
        ms_values[media.id] = {}
        for setting in global_settings:
            # Lecture directe depuis l'instance, JSONField gère la conversion
            ms_values[media.id][setting.name] = getattr(media, setting.name, setting.value)

    # range_widths par média et par setting (FLOAT → col-12)
    range_widths_media = {
        media.id: {
            setting.name: 'col-12' if setting.type == 'FLOAT' else ''
            for setting in global_settings
        }
        for media in medias
    }

    # range_widths global (FLOAT → col-3)
    range_widths_global = {
        setting.name: 'col-3' if setting.type == 'FLOAT' else ''
        for setting in global_settings
    }

    # valeurs par défaut pour les global_settings
    gs_values = {}
    for setting in global_settings:
        value = getattr(user_settings, setting.name, None)
        if value is None:
            # fallback on GlobalSettings.default
            value = setting.default
        gs_values[setting.name] = value

    # Add SAM3 settings (not in GlobalSettings but needed for the right panel)
    gs_values['use_sam3'] = getattr(user_settings, 'use_sam3', False)
    gs_values['sam3_prompt'] = getattr(user_settings, 'sam3_prompt', '') or ''

    # Get class choices from form field (which uses get_all_class_choices())
    class_list = user_settings_form.fields['classes2blur'].choices
    available_models = list_available_models()
    models_by_type = list_models_by_type()

    return {
        'user': user,
        'medias': medias,
        'media_settings_form': media_settings_form,
        'global_settings': global_settings,
        'user_settings_form': user_settings_form,
        'ms_values': ms_values,
        'gs_values': gs_values,
        'classes': class_list,
        'range_widths_media': range_widths_media,
        'range_widths_global': range_widths_global,
        'available_models': available_models,
        'models_by_type': models_by_type,
    }


def update_settings(request):
    if request.method != "POST":
        return JsonResponse({'error': 'Invalid request method'}, status=400)

    # Récupérer les champs du POST
    setting_type = request.POST.get("setting_type")
    setting_name = request.POST.get("setting_name")
    input_value = request.POST.get("input_value")
    media_id = request.POST.get("media_id")  # Peut être None pour global_setting

    if not setting_type or not setting_name or input_value is None:
        return JsonResponse({'error': 'Missing parameters'}, status=400)

    # Préparer le contexte pour le render du bouton
    context = {
        'setting_type': setting_type,
        'id': media_id or request.user.id,
        # Global and user settings should render compact sliders; media_setting is full width
        'range_width': 'col-sm-12' if setting_type == 'media_setting' else 'col-sm-3',
    }

    try:
        if setting_type == 'media_setting':
            if not media_id:
                return JsonResponse({'error': 'Missing media_id for media_setting'}, status=400)

            media = Media.objects.get(pk=int(media_id))

            if setting_name.startswith('classes2blur_'):
                # cas spécial checkbox dynamique pour une classe individuelle
                _, class_name = setting_name.split('_', 1)
                is_checked = str(input_value).lower() in ['true', '1', 'on']

                current = media.classes2blur or []
                if is_checked and class_name not in current:
                    current.append(class_name)
                elif not is_checked and class_name in current:
                    current.remove(class_name)

                media.classes2blur = current
                media.MSValues_customised = True
                media.save(update_fields=['classes2blur', 'MSValues_customised'])
                context['value'] = current
                # Pour classes2blur_, on cherche le GlobalSettings 'classes2blur'
                context['setting'] = GlobalSettings.objects.get(name='classes2blur')

            else:
                # générique : float, bool, int, text
                field = Media._meta.get_field(setting_name)
                internal_type = field.get_internal_type()

                if internal_type == 'BooleanField':
                    value = str(input_value).lower() in ['true', '1', 'on']
                elif internal_type in ['FloatField', 'DecimalField']:
                    value = float(input_value)
                elif internal_type in ['TextField', 'CharField']:
                    # For text fields like sam3_prompt
                    value = str(input_value) if input_value else None
                elif internal_type == 'IntegerField':
                    value = int(input_value)
                else:
                    # Fallback: try int, else keep as string
                    try:
                        value = int(input_value)
                    except (ValueError, TypeError):
                        value = str(input_value)

                setattr(media, setting_name, value)
                media.MSValues_customised = True
                media.save(update_fields=[setting_name, 'MSValues_customised'])
                context['value'] = getattr(media, setting_name)
                # Pour les autres settings, on cherche le GlobalSettings avec le nom exact
                try:
                    context['setting'] = GlobalSettings.objects.get(name=setting_name)
                except GlobalSettings.DoesNotExist:
                    context['setting'] = None

        elif setting_type == 'user_setting':
            user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
            user_settings, _ = UserSettings.objects.get_or_create(user=user)
            if setting_name.startswith('classes2blur_'):
                # Toggle for a single class in the user's classes2blur list
                _, class_name = setting_name.split('_', 1)
                is_checked = str(input_value).lower() in ['true', '1', 'on']

                current = user_settings.classes2blur or []
                if is_checked and class_name not in current:
                    current.append(class_name)
                elif not is_checked and class_name in current:
                    current.remove(class_name)

                user_settings.classes2blur = current
                user_settings.GSValues_customised = True
                user_settings.save(update_fields=['classes2blur', 'GSValues_customised'])
                context['value'] = current
                context['setting'] = GlobalSettings.objects.get(name='classes2blur')
            elif setting_name == 'model_to_use':
                # simple string select
                user_settings.model_to_use = str(input_value)
                user_settings.GSValues_customised = True
                user_settings.save(update_fields=['model_to_use', 'GSValues_customised'])
                context['value'] = user_settings.model_to_use
                context['setting'] = GlobalSettings.objects.filter(name='classes2blur').first()
            else:
                field = UserSettings._meta.get_field(setting_name)
                internal_type = field.get_internal_type()

                if internal_type == 'BooleanField':
                    value = str(input_value).lower() in ['true', '1', 'on']
                elif internal_type in ['FloatField', 'DecimalField']:
                    value = float(input_value)
                elif internal_type in ['TextField', 'CharField']:
                    # For text fields like sam3_prompt
                    value = str(input_value) if input_value else None
                elif internal_type == 'IntegerField':
                    value = int(input_value)
                else:
                    # Fallback: try int, else keep as string
                    try:
                        value = int(input_value)
                    except (ValueError, TypeError):
                        value = str(input_value)

                setattr(user_settings, setting_name, value)
                user_settings.GSValues_customised = True
                user_settings.save(update_fields=[setting_name, 'GSValues_customised'])
                context['value'] = getattr(user_settings, setting_name)
                # Try to get the global setting, but don't fail if it doesn't exist (like sam3_prompt)
                try:
                    context['setting'] = GlobalSettings.objects.get(name=setting_name)
                except GlobalSettings.DoesNotExist:
                    context['setting'] = None

        elif setting_type == 'global_setting':
            print(f"[DEBUG] update_settings: received global_setting {setting_name}={input_value}")
            try:
                global_setting = GlobalSettings.objects.get(name=setting_name)
            except GlobalSettings.DoesNotExist:
                print(f"[update_settings] ❌ Unknown global setting: {setting_name}")
                return JsonResponse({'error': f'Unknown global setting: {setting_name}'}, status=400)

            print(
                f"[update_settings] 🟡 Before save: {global_setting.name} = {input_value} (type={global_setting.type})")

            # Conversion typée
            if global_setting.type == 'BOOL':
                value = str(input_value).lower() in ['true', '1', 'on']
            elif global_setting.type == 'FLOAT':
                value = float(input_value)
            else:
                value = input_value

            global_setting.value = {"current": value}
            global_setting.save(update_fields=['value'])

            print(f"[update_settings] ✅ Saved: {global_setting.name} = {global_setting.value}")

            context['value'] = value
            context['setting'] = global_setting

        else:
            return JsonResponse({'error': f'Unknown setting_type: {setting_type}'}, status=400)

        html = loader.render_to_string('anonymizer/upload/setting_button.html', context, request=request)
        return JsonResponse({'render': html})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def expand_area(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    button_id = request.POST.get("button_id")
    button_state = request.POST.get("button_state")

    if not button_id or button_state is None:
        return HttpResponseBadRequest("Missing button_id or button_state")

    update_map = {
        "MediaSettings": lambda: Media.objects.filter(pk=re.search(r'\d+$', button_id).group()).update(show_ms=button_state),
        "GlobalSettings": lambda: UserSettings.objects.filter(user_id=user.id).update(show_gs=button_state),
        "Preview": lambda: UserSettings.objects.filter(user_id=user.id).update(show_preview=button_state),
        # "Console": lambda: UserSettings.objects.filter(user_id=user.id).update(show_console=button_state),
    }

    for key, action in update_map.items():
        if key in button_id:
            action()
            return JsonResponse(data={})

    return HttpResponseBadRequest("Unknown button_id")



def clear_all_media(request):
    """Delete all media files (input and output) for the current user."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    user_medias = Media.objects.filter(user=user)
    if user_medias.exists():
        for media in user_medias:
            # Delete input file
            if media.file:
                try:
                    media.file.delete(save=False)
                except Exception as e:
                    print(f"[clear_all_media] Error deleting input file: {e}")

            # Delete output file (blurred media) - derive path from input filename
            try:
                output_path = get_blurred_media_path(media.file.name, media.file_ext, media.user_id)
                if os.path.exists(output_path):
                    os.remove(output_path)
                    print(f"[clear_all_media] Deleted output file: {output_path}")
            except Exception as e:
                print(f"[clear_all_media] Error deleting output file: {e}")

        user_medias.delete()
        UserSettings.objects.filter(user_id=user.id).update(media_added=0, show_gs=0)

    return JsonResponse({'success': True})


def clear_media(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    media_id = request.POST.get('media_id')
    media = Media.objects.filter(pk=media_id).first()

    if not media:
        return JsonResponse({'success': False, 'error': 'Media not found'}, status=404)

    try:
        Media.objects.filter(pk=media_id).update(MSValues_customised=0)
        media.file.delete()
        media.delete()

        has_media = Media.objects.filter(user=user).exists()
        UserSettings.objects.filter(user_id=user.id).update(media_added=int(has_media))
        if not has_media:
            # Hide global settings section when no media remains
            UserSettings.objects.filter(user_id=user.id).update(show_gs=0)

        context = get_context(request)
        template = loader.get_template('anonymizer/upload/content.html')
        return JsonResponse({
            'success': True,
            'render': template.render(context, request)
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def reset_media_settings(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        media_id = request.POST.get('media_id')
        if not media_id:
            return JsonResponse({'success': False, 'error': 'Missing media_id'}, status=400)

        media = get_object_or_404(Media, pk=media_id)
        media_settings_form = MediaSettingsForm(instance=media)
        global_settings_list = GlobalSettings.objects.all()

        updated_fields = {
            setting.name: setting.default
            for setting in global_settings_list
            if setting.name in media_settings_form.fields
        }

        if updated_fields:
            Media.objects.filter(pk=media_id).update(**updated_fields, MSValues_customised=0)

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def check_all_processed(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    medias = Media.objects.filter(user=user)
    all_processed = medias.exists() and all(m.processed for m in medias)
    return JsonResponse({"all_processed": all_processed})


@require_POST
def reset_user_settings(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Réinitialisation des UserSettings aux valeurs par défaut de GlobalSettings
    init_user_settings(user)

    # Get the updated settings to return to the client
    user_settings, _ = UserSettings.objects.get_or_create(user=user)

    # Check if this is an AJAX/fetch request
    is_ajax = (
        request.headers.get("x-requested-with") == "XMLHttpRequest" or
        request.headers.get("Content-Type") == "application/json" or
        request.content_type == "application/x-www-form-urlencoded"
    )

    if is_ajax or request.headers.get("X-CSRFToken"):
        # Return JSON with the reset settings values
        settings_data = {
            'precision_level': user_settings.precision_level,
            'blur_ratio': user_settings.blur_ratio,
            'detection_threshold': user_settings.detection_threshold,
            'roi_enlargement': user_settings.roi_enlargement,
            'progressive_blur': user_settings.progressive_blur,
            'use_sam3': getattr(user_settings, 'use_sam3', False),
            'sam3_prompt': getattr(user_settings, 'sam3_prompt', '') or '',
            'classes2blur': user_settings.classes2blur or [],
            'interpolate_detections': user_settings.interpolate_detections,
            'use_segmentation': user_settings.use_segmentation,
            'model_to_use': getattr(user_settings, 'model_to_use', '') or '',
            'show_preview': getattr(user_settings, 'show_preview', True),
            'show_boxes': getattr(user_settings, 'show_boxes', True),
            'show_labels': getattr(user_settings, 'show_labels', True),
            'show_conf': getattr(user_settings, 'show_conf', True),
        }
        return JsonResponse({"success": True, "settings": settings_data})
    else:
        return redirect(request.POST.get('next', '/'))



def init_user_settings(user):
    """
    Réinitialise les UserSettings d'un utilisateur avec les valeurs par défaut des GlobalSettings.
    """
    close_old_connections()

    user_settings, _ = UserSettings.objects.get_or_create(user=user)
    global_settings_list = GlobalSettings.objects.all()

    for setting in global_settings_list:
        if setting.name in [f.name for f in UserSettings._meta.get_fields()]:
            setattr(user_settings, setting.name, setting.default)

    # Reset to model defaults (these may not be in GlobalSettings)
    user_settings.precision_level = 50
    user_settings.use_segmentation = False
    user_settings.show_preview = True
    user_settings.show_boxes = True
    user_settings.show_labels = True
    user_settings.show_conf = True

    # Réinitialise le flag custom
    user_settings.GSValues_customised = 0
    user_settings.save()


def init_global_settings():
    if GlobalSettings.objects.exists():
        return  # Already initialized

    settings_data = [
        {'title': "Objects to blur", 'name': "classes2blur", 'default': ["face"], 'value': ["face"],
         'type': 'BOOL', 'label': 'WTB'},
        {'title': "Processing precision", 'name': "precision_level", 'default': "50", 'value': "50",
         'min': "0", 'max': "100", 'step': "5", 'type': 'FLOAT', 'label': 'WTB',
         'attr_list': {'min': '0', 'max': '100', 'step': '5'}},
        {'title': "Blur ratio", 'name': "blur_ratio", 'default': "25", 'value': "25",
         'min': "1", 'max': "49", 'step': "2", 'type': 'FLOAT', 'label': 'HTB',
         'attr_list': {'min': '1', 'max': '49', 'step': '2'}},
        {'title': "ROI enlargement", 'name': "roi_enlargement", 'default': "1.05", 'value': "1.05",
         'min': "0.5", 'max': "1.5", 'step': "0.05", 'type': 'FLOAT', 'label': 'HTB',
         'attr_list': {'min': '0.5', 'max': '1.5', 'step': '0.05'}},
        {'title': "Progressive blur", 'name': "progressive_blur", 'default': "25", 'value': "25",
         'min': "3", 'max': "31", 'step': "2", 'type': 'FLOAT', 'label': 'HTB',
         'attr_list': {'min': '3', 'max': '31', 'step': '2'}},
        {'title': "Detection threshold", 'name': "detection_threshold", 'default': "0.25", 'value': "0.25",
         'min': "0", 'max': "1", 'step': "0.05", 'type': 'FLOAT', 'label': 'HTB',
         'attr_list': {'min': '0', 'max': '1', 'step': '0.05'}},
        {'title': "Show preview", 'name': "show_preview", 'default': True, 'value': True, 'type': 'BOOL', 'label': 'WTS'},
        {'title': "Show boxes", 'name': "show_boxes", 'default': True, 'value': True, 'type': 'BOOL', 'label': 'WTS'},
        {'title': "Show labels", 'name': "show_labels", 'default': True, 'value': True, 'type': 'BOOL', 'label': 'WTS'},
        {'title': "Show conf", 'name': "show_conf", 'default': True, 'value': True, 'type': 'BOOL', 'label': 'WTS'}
        ]
    for s in settings_data :
        GlobalSettings.objects.create(**s)

def ensure_global_settings():
    if not GlobalSettings.objects.exists():
        init_global_settings()

def reset_global_settings_safe():
    """Réinitialise tous les GlobalSettings proprement."""
    close_old_connections()
    with transaction.atomic():
        GlobalSettings.objects.all().delete()
        init_global_settings()


# ========================================
# Modern Modal-Based Settings Endpoints
# ========================================

def get_media_settings(request, media_id):
    """Get settings for a specific media to populate the settings modal."""
    try:
        media = Media.objects.get(pk=media_id)
        global_settings = GlobalSettings.objects.all()

        # Build settings data for the modal
        classes2blur_list = []
        sliders_list = []
        booleans_list = []

        # Use the same class list as global settings for consistency
        from .utils.yolo_utils import get_all_class_choices
        available_classes = get_all_class_choices()  # Returns [(code, label), ...]

        media_classes = media.classes2blur if media.classes2blur else []
        for cls_code, cls_label in available_classes:
            classes2blur_list.append({
                'value': cls_code,
                'label': cls_label,
                'checked': cls_code in media_classes
            })

        # Slider settings (FLOAT type)
        slider_configs = [
            {'name': 'blur_ratio', 'title': 'Blur Ratio', 'min': 1, 'max': 49, 'step': 2},
            {'name': 'roi_enlargement', 'title': 'ROI Enlargement', 'min': 0.5, 'max': 1.5, 'step': 0.05},
            {'name': 'progressive_blur', 'title': 'Progressive Blur', 'min': 3, 'max': 31, 'step': 2},
            {'name': 'detection_threshold', 'title': 'Detection Threshold', 'min': 0, 'max': 1, 'step': 0.05},
            {'name': 'precision_level', 'title': 'Precision Level', 'min': 0, 'max': 100, 'step': 5},
        ]

        for config in slider_configs:
            media_value = getattr(media, config['name'], None)
            if media_value is None:
                # Get default from global settings
                setting = global_settings.filter(name=config['name']).first()
                if setting:
                    default_val = setting.default
                    if isinstance(default_val, str):
                        media_value = float(default_val)
                    else:
                        media_value = float(default_val) if default_val else config['min']
                else:
                    media_value = config['min']

            sliders_list.append({
                'name': config['name'],
                'title': config['title'],
                'value': float(media_value),
                'min': config['min'],
                'max': config['max'],
                'step': config['step'],
                'description': ''
            })

        # Boolean settings
        bool_configs = [
            {'name': 'show_preview', 'title': 'Show Preview'},
            {'name': 'show_boxes', 'title': 'Show Boxes'},
            {'name': 'show_labels', 'title': 'Show Labels'},
            {'name': 'show_conf', 'title': 'Show Confidence'},
            {'name': 'interpolate_detections', 'title': 'Interpolate Detections'},
            {'name': 'use_segmentation', 'title': 'Use Segmentation'},
        ]

        for config in bool_configs:
            media_value = getattr(media, config['name'], False)
            booleans_list.append({
                'name': config['name'],
                'title': config['title'],
                'value': bool(media_value)
            })

        # SAM3 settings - status is loaded asynchronously by frontend to avoid slow modal opening
        sam3_data = {
            'use_sam3': media.use_sam3,
            'prompt': media.sam3_prompt or '',
            # Don't include status here - let frontend fetch it asynchronously when needed
            # 'status': get_sam3_status(),  # SLOW - removed for performance
            # 'examples': get_recommended_prompt_examples(),  # Also loaded async
        }

        # Model selection - get available models grouped by type
        from .utils.yolo_utils import get_model_choices_grouped
        model_choices_grouped = get_model_choices_grouped()

        # Flatten grouped choices for easier frontend handling
        model_choices = []
        for group_label, group_choices in model_choices_grouped:
            for value, label in group_choices:
                model_choices.append({
                    'value': value,
                    'label': label,
                    'group': group_label
                })

        # Get user's global model setting as default
        user_settings, _ = UserSettings.objects.get_or_create(user=media.user)
        global_model = getattr(user_settings, 'model_to_use', '') or ''

        model_data = {
            'current': media.model_to_use or '',  # Empty means use global/auto
            'global_default': global_model,
            'choices': model_choices,
        }

        return JsonResponse({
            'success': True,
            'classes2blur': classes2blur_list,
            'sliders': sliders_list,
            'booleans': booleans_list,
            'sam3': sam3_data,
            'model': model_data,
        })

    except Media.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Media not found'
        }, status=404)
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }, status=500)


@require_POST
def save_media_settings(request):
    """Save settings for a specific media from the modal."""
    try:
        media_id = request.POST.get('media_id')
        if not media_id:
            return JsonResponse({'success': False, 'error': 'No media_id provided'}, status=400)

        media = Media.objects.get(pk=media_id)

        # Save classes2blur (checkboxes)
        classes2blur = request.POST.getlist('classes2blur')
        if classes2blur:
            media.classes2blur = classes2blur

        # Save slider values
        slider_fields = ['blur_ratio', 'roi_enlargement', 'progressive_blur', 'detection_threshold', 'precision_level']
        for field in slider_fields:
            value = request.POST.get(field)
            if value is not None:
                if field in ['blur_ratio', 'progressive_blur', 'precision_level']:
                    setattr(media, field, int(float(value)))
                else:
                    setattr(media, field, float(value))

        # Save boolean values
        bool_fields = ['show_preview', 'show_boxes', 'show_labels', 'show_conf', 'interpolate_detections', 'use_segmentation']
        for field in bool_fields:
            value = request.POST.get(field)
            if value is not None:
                setattr(media, field, value.lower() == 'true')

        # Save SAM3 settings
        use_sam3 = request.POST.get('use_sam3')
        if use_sam3 is not None:
            media.use_sam3 = use_sam3.lower() == 'true'

        sam3_prompt = request.POST.get('sam3_prompt')
        if sam3_prompt is not None:
            prompt = sam3_prompt.strip()
            if prompt:
                # Validate prompt
                is_valid, error = validate_sam3_prompt(prompt)
                if not is_valid:
                    return JsonResponse({
                        'success': False,
                        'error': f'Invalid SAM3 prompt: {error}'
                    }, status=400)
            media.sam3_prompt = prompt if prompt else None

        # Save model selection
        model_to_use = request.POST.get('model_to_use')
        if model_to_use is not None:
            # Empty string means use global/auto-select
            media.model_to_use = model_to_use.strip() if model_to_use.strip() else None

        # Mark as customized
        media.MSValues_customised = True
        media.save()

        return JsonResponse({
            'success': True,
            'message': 'Settings saved successfully'
        })

    except Media.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Media not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_POST
def restart_media(request):
    """Restart processing for a specific media."""
    import logging
    logger = logging.getLogger('anonymizer.process')

    logger.info(f"[restart_media] Request received: {request.method}")
    logger.info(f"[restart_media] POST data: {request.POST}")

    try:
        media_id = request.POST.get('media_id')
        logger.info(f"[restart_media] media_id={media_id}")

        if not media_id:
            logger.warning("[restart_media] No media_id provided")
            return JsonResponse({'success': False, 'error': 'No media_id provided'}, status=400)

        media = Media.objects.get(pk=media_id)
        logger.info(f"[restart_media] Found media: {media.title} (id={media.id})")

        # Reset processing status
        media.processed = False
        media.blur_progress = 0
        media.save()
        logger.info(f"[restart_media] Reset media processing status")

        # Launch the processing task
        task = process_single_media.delay(media.id)
        logger.info(f"[restart_media] Launched task {task.id} for media {media.id}")

        return JsonResponse({
            'success': True,
            'message': 'Processing started',
            'task_id': task.id
        })

    except Media.DoesNotExist:
        logger.error(f"[restart_media] Media not found: {media_id}")
        return JsonResponse({
            'success': False,
            'error': 'Media not found'
        }, status=404)
    except Exception as e:
        logger.error(f"[restart_media] Error: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def global_progress(request):
    """Get overall progress for all user medias"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        medias = Media.objects.filter(user=user)

        if not medias.exists():
            return JsonResponse({
                'total': 0,
                'pending': 0,
                'running': 0,
                'success': 0,
                'failure': 0,
                'overall_progress': 0
            })

        total = medias.count()
        # Anonymizer uses 'processed' instead of 'status'
        pending = medias.filter(processed=False).count()
        success = medias.filter(processed=True).count()
        running = 0  # Anonymizer doesn't have explicit RUNNING status

        # Calculate overall progress using cache
        total_progress = 0
        for m in medias:
            progress = int(cache.get(f"media_progress_{m.id}", m.blur_progress or 0))
            total_progress += progress

        overall_progress = int(total_progress / total) if total > 0 else 0

        return JsonResponse({
            'total': total,
            'pending': pending,
            'running': running,
            'success': success,
            'failure': 0,  # Anonymizer doesn't track failures separately
            'overall_progress': overall_progress
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ----------------------------------------------------------------------
# SAM3 Endpoints
# ----------------------------------------------------------------------

def get_sam3_status_view(request):
    """Return SAM3 installation and configuration status."""
    status = get_sam3_status()
    status['requirements'] = get_sam3_requirements()
    status['examples'] = get_recommended_prompt_examples()
    return JsonResponse(status)


@require_POST
def configure_hf_token(request):
    """Configure HuggingFace token for SAM3 access."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    token = request.POST.get('hf_token', '').strip()
    if not token:
        return JsonResponse({'success': False, 'error': 'Token requis'}, status=400)

    if setup_hf_auth(token):
        # Mark user as having configured HF token
        user_settings, _ = UserSettings.objects.get_or_create(user=user)
        user_settings.hf_token_configured = True
        user_settings.save(update_fields=['hf_token_configured'])

        return JsonResponse({
            'success': True,
            'message': 'Token HuggingFace configure avec succes'
        })
    else:
        return JsonResponse({
            'success': False,
            'error': 'Echec de la configuration du token'
        }, status=500)


def validate_prompt_view(request):
    """Validate a SAM3 text prompt."""
    prompt = request.GET.get('prompt', '')
    is_valid, error = validate_sam3_prompt(prompt)
    return JsonResponse({
        'valid': is_valid,
        'error': error if not is_valid else None
    })


def get_sam3_examples(request):
    """Get recommended SAM3 prompt examples."""
    return JsonResponse({
        'examples': get_recommended_prompt_examples()
    })


class AboutView(TemplateView):
    template_name = 'anonymizer/about.html'

class HelpView(TemplateView):
    template_name = 'anonymizer/help.html'
