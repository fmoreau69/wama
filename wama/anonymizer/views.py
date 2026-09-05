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

from django.http import FileResponse, Http404, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
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
from django.utils.decorators import method_decorator
from django.utils.encoding import iri_to_uri

from wama.accounts.permissions import app_access

from .models import Media, GlobalSettings, UserSettings, BatchAnonymizer, BatchAnonymizerItem
from wama.common.utils.queue_duplication import duplicate_instance, safe_delete_file
from .tasks import process_single_media, process_user_media_batch, stop_process
from .utils.media_utils import get_input_media_path, get_output_media_path, get_blurred_media_path, get_unique_filename
from .utils.yolo_utils import get_model_path, list_models_by_type
from .utils.sam3_manager import (
    get_sam3_status, setup_hf_auth, validate_sam3_prompt,
    get_sam3_requirements, get_recommended_prompt_examples
)

from ..accounts.views import get_or_create_anonymous_user
from ..settings import MEDIA_ROOT, MEDIA_INPUT_ROOT, MEDIA_OUTPUT_ROOT
from ..common.utils.console_utils import get_console_lines
from ..common.utils.video_utils import get_media_info
from ..common.utils.video_utils import upload_media_from_url
from ..common.utils.media_paths import get_app_media_path, ensure_app_media_dirs


@method_decorator(app_access('anonymizer'), name='dispatch')
class IndexView(View):
    """Page principale de Anonymizer."""

    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Réconcilie les tâches RUNNING orphelines (worker mort/crash) — brique COMMUNE,
        # preuve positive de mort uniquement (reference_orphan_task_reconcile).
        try:
            from wama.common.utils.process_control import reconcile_orphaned_running
            running = list(Media.objects.filter(user=user, status='RUNNING'))
            reconcile_orphaned_running(running, error_field='error_message')
        except Exception:
            pass

        context = get_context(request)
        context.update(_queue_context(request, user))
        return render(request, 'anonymizer/index.html', context)

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
                            # Confinement (05/09) : ce site lisait N'IMPORTE QUEL chemin serveur
                            # cité dans un .txt — le seul du parc sans garde, alors que le
                            # gabarit généré et le converter confinent à MEDIA_ROOT. Même règle
                            # partout : un chemin de lot se résout SOUS MEDIA_ROOT, ou est
                            # refusé (`MEDIA_STORAGE_TIERING §8.6` D3).
                            from wama.common.utils.media_paths import copy_into_app_input, resolve_under_media_root
                            abs_src, _ = resolve_under_media_root(path)   # OutsideMediaRoot / FileNotFoundError → failed[]
                            dest, _rel = copy_into_app_input(abs_src, 'anonymizer', user.id, 'input')
                            video_path = str(dest)
                        # Crée Media en DB
                        media = process_media(
                            video_path, user,
                            output_format=request.POST.get('output_format', 'original'),
                            output_quality=request.POST.get('output_quality', 'balanced'),
                        )
                        added.append(media)
                    except Exception as e:
                        failed.append((path, str(e)))

                return JsonResponse({'success': True, 'added': added, 'errors': failed})

            # Case 2: direct upload (file or URL)
            video_path = upload_from_url(request, user)
            media_result = process_media(
                video_path, user,
                output_format=request.POST.get('output_format', 'original'),
                output_quality=request.POST.get('output_quality', 'balanced'),
            )
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


def process_media(video_path, user, output_format='original', output_quality='balanced'):
    """Create a Media object from the given path and assign metadata."""
    try:
        filename = os.path.basename(video_path)
        ext = os.path.splitext(filename)[1]
        # Use user-specific path
        relative_path = f'anonymizer/{user.id}/input/{filename}'
        media = Media.objects.create(
            file=relative_path, file_ext=ext, user=user,
            output_format=output_format or 'original',
            output_quality=output_quality or 'balanced',
        )

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

            # Dedup: prise de verrou ATOMIQUE (cache.add = set-si-absent). L'ancien
            # get() puis set() laissait une fenêtre de course sur double-clic.
            batch_lock_key = f"anon_lock:batch:{user.id}"
            if not cache.add(batch_lock_key, True, timeout=7200):
                logger.info(f"[ProcessView] Batch already running for user {user.id}")
                return JsonResponse({"task_id": None, "error": "Un traitement est déjà en cours"}, status=409)

            # Get all user media (not just unprocessed)
            all_medias = Media.objects.filter(user=user).order_by('id')

            if not all_medias.exists():
                logger.warning(f"[ProcessView] No media found for user {user.username}")
                return JsonResponse({"task_id": None, "error": "No media to process"})

            # (verrou batch déjà posé atomiquement par cache.add ci-dessus)

            # Reset all media to allow reprocessing
            for media in all_medias:
                media.status = 'PENDING'
                media.blur_progress = 0
                media.save(update_fields=['status', 'blur_progress'])
                # Clear cache for this media
                cache.delete(f"media_progress_{media.id}")
                # Set individual media lock
                cache.set(f"anon_lock:media:{media.id}", True, timeout=7200)
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
    """Return metadata + absolute URL to play a media file in-place.
    Lecture → partage F7 (visible_or_404 : le sien, ou partagé unité/projet/public)."""
    from wama.common.utils.scoping import visible_or_404
    viewer = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    media = visible_or_404(Media, viewer, pk=media_id)

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
    all_lines = get_console_lines(user.id, limit=200)
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
        'unprocessed_medias': Media.objects.filter(user=user).exclude(status='SUCCESS').count(),
        'medias': []
    }

    for m in medias:
        result['medias'].append({
            'id': m.id,
            'title': m.title or f"Media {m.id}",
            'processed': m.processed,
            'status': m.status,
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
        viewer = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
        try:
            # Lecture → partage F7 (visible_to : le sien, ou partagé)
            media = Media.objects.visible_to(viewer).get(pk=int(media_id))
            cache_progress = cache.get(f"media_progress_{media.id}")
            db_progress = media.blur_progress or 0

            # Prefer cache, fallback to DB
            progress = int(cache_progress if cache_progress is not None else db_progress)

            payload = {
                "progress": max(0, min(100, progress)),
                "status": media.status,
                "error": media.error_message or '',
            }
            # ETA seedée (a-priori → EMA apprise par record_run en fin de tâche)
            if media.status in ('PENDING', 'RUNNING'):
                try:
                    from wama.model_manager.services.eta_estimator import estimate
                    from .tasks import anonymizer_eta_key_size
                    _k, _s, _u = anonymizer_eta_key_size(media)
                    payload['estimated_seconds'] = estimate(_k, size=_s, unit=_u, model_loaded=True)
                except Exception:
                    pass
            return JsonResponse(payload)
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


def download(request, pk: int):
    """Télécharge le média traité — route au FORMAT COMMUN `download/<pk>/` (2026-08-23).

    POURQUOI, ALORS QUE LE TÉLÉCHARGEMENT MARCHAIT. Comme pour la suppression, c'est la FORME
    qui divergeait : l'anonymizer était la seule app dont le ⬇ n'était pas un lien mais un
    `<form method="post">` postant `media_id`. La brique commune `_download_button.html` rend un
    `<a href>` — elle ne pouvait donc pas le servir.

    Ce que le formulaire coûtait à l'utilisateur, au-delà de l'homogénéité : un POST n'est pas
    une navigation. Pas de clic-droit « Enregistrer sous », pas d'ouverture dans un nouvel
    onglet, et un rechargement de page qui redemande la soumission. Un téléchargement est un GET.
    """
    from wama.common.utils.scoping import visible_or_404
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    return _servir_media_traite(request, visible_or_404(Media, user, pk=pk))


def download_media(request):
    """Ancienne forme (POST + `media_id`). Conservée le temps de vérifier qu'aucun appelant
    externe n'en dépend, et DÉLÈGUE au même travail — pas de second chemin. Cf. REMOVAL_LEDGER."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    media_id = request.POST.get('media_id')
    if not media_id:
        return HttpResponseBadRequest("Missing media_id.")

    # Lecture → partage F7 (le sien, ou partagé unité/projet/public)
    from wama.common.utils.scoping import visible_or_404
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    return _servir_media_traite(request, visible_or_404(Media, user, pk=media_id))


def _servir_media_traite(request, media):
    """Résout le fichier de sortie (le suffixe varie selon le backend) et le sert."""

    # Generate the canonical blurred output path; the actual file written
    # by the pipeline carries a suffix that varies by backend:
    #   YOLO :  {base}_blurred_{model_suffix}{ext}
    #   SAM3 :  {base}_blurred_sam3{ext}
    # We resolve to whichever matches by globbing the output directory.
    media_path = get_blurred_media_path(media.file.name, media.file_ext, media.user_id)
    blurred_filename = os.path.basename(media_path)
    print(f"[download_media] Looking for file: {media_path}")

    if not os.path.exists(media_path):
        # Fallback: glob for {base}_blurred*{ext} and pick the most recent.
        # The pipelines write _blurred_<suffix>.<ext> rather than just _blurred.<ext>.
        import glob as _glob
        out_dir = os.path.dirname(media_path)
        base = os.path.splitext(os.path.basename(media_path))[0]
        # Strip the trailing "_blurred" so we can match base_blurred*{ext}.
        if base.endswith('_blurred'):
            base = base[:-len('_blurred')]
        ext = os.path.splitext(media_path)[1]
        candidates = sorted(
            _glob.glob(os.path.join(out_dir, f"{base}_blurred*{ext}")),
            key=os.path.getmtime,
            reverse=True,
        )
        if candidates:
            media_path = candidates[0]
            blurred_filename = os.path.basename(media_path)
            print(f"[download_media] Resolved via glob: {media_path}")
        else:
            print(f"[download_media] ✗ File not found: {media_path}")
            context = get_context(request)
            context['error'] = f"Processed file {blurred_filename} doesn't exist."
            return render(request, 'anonymizer/index.html', context)

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
    processed_medias = all_medias.filter(status='SUCCESS')

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

    # Clear all dedup locks for this user
    cache.delete(f"anon_lock:batch:{user_id}")
    for m in Media.objects.filter(user_id=user_id):
        cache.delete(f"anon_lock:media:{m.id}")
        cache.delete(f"anon_task_owner:media:{m.id}")

    return JsonResponse({"status": "stopped"})


def card_html(request, pk):
    """Card média = partial serveur UNIQUE (source du markup, remplace le re-render
    de table legacy `refresh`). Lecture → partage F7 (visible_or_404)."""
    from wama.common.utils.scoping import visible_or_404
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    media = visible_or_404(Media, user, pk=pk)
    _decorate_card(media)
    item = BatchAnonymizerItem.objects.filter(media=media).select_related('batch').first()
    in_batch = bool(item and item.batch.total > 1)
    return render(request, 'anonymizer/_media_card.html',
                  {'elem': media, 'in_batch': in_batch, 'user': user})


def _reset_for_relaunch(media):
    """Remise à zéro d'un média AVANT relance (sous le verrou begin_processing)."""
    media.blur_progress = 0
    media.error_message = ''


@require_POST
@app_access('anonymizer')
def start(request, pk):
    """Lance/relance UN média (bouton de cycle ▶/↻) — anti-race par brique commune."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.process_control import begin_processing
    media, err = begin_processing(Media, pk, user=user, reset=_reset_for_relaunch)
    if err:
        return JsonResponse({'error': err}, status=404 if err == 'not_found' else 400)
    cache.delete(f"media_progress_{media.id}")
    task = process_single_media.delay(media.id, force_individual=True)
    media.task_id = task.id
    media.save(update_fields=['task_id'])
    return JsonResponse({'success': True, 'task_id': task.id, 'status': 'RUNNING'})


@require_POST
@app_access('anonymizer')
def stop(request, pk):
    """Arrête UN média (bouton de cycle ⏹) : revoke + libération des verrous."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    media = get_object_or_404(Media, pk=pk, user=user)
    if media.task_id:
        try:
            AsyncResult(media.task_id).revoke(terminate=False)
        except Exception:
            pass
    cache.delete(f"anon_lock:media:{media.id}")
    cache.delete(f"anon_task_owner:media:{media.id}")
    cache.delete(f"media_progress_{media.id}")
    if media.status == 'RUNNING':
        media.status = 'PENDING'
        media.blur_progress = 0
        media.save(update_fields=['status', 'blur_progress'])
    return JsonResponse({'success': True, 'status': media.status})


@require_POST
@app_access('anonymizer')
def batch_start(request, pk):
    """Lance/relance tous les médias d'UN batch (card mère) — même brique que start."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchAnonymizer, pk=pk, user=user)
    from wama.common.utils.process_control import begin_processing
    started = []
    for item in batch.items.select_related('media').order_by('row_index'):
        if not item.media:
            continue
        locked, err = begin_processing(Media, item.media.pk, user=user, reset=_reset_for_relaunch)
        if err:
            continue  # already_running / not_found
        cache.delete(f"media_progress_{locked.id}")
        task = process_single_media.delay(locked.id)
        locked.task_id = task.id
        locked.save(update_fields=['task_id'])
        started.append(locked.id)
    return JsonResponse({'success': True, 'started': started})


@require_POST
def batch_update(request, pk):
    """Réglages d'un BATCH : applique le payload schéma-driven à tous les items
    non-RUNNING (modale batch commune, contrat reader)."""
    import json as _json
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchAnonymizer, pk=pk, user=user)
    try:
        payload = _json.loads(request.body or '{}')
    except (ValueError, TypeError):
        payload = request.POST
    from wama.common.utils.param_schema import coerce_schema_values, schema_for_app
    valeurs = coerce_schema_values(schema_for_app('anonymizer'), payload)
    updated = 0
    for item in batch.items.select_related('media'):
        m = item.media
        if not m or m.status == 'RUNNING':
            continue
        for champ, valeur in valeurs.items():
            setattr(m, champ, valeur)
        m.MSValues_customised = True
        m.save()
        updated += 1
    return JsonResponse({'success': True, 'updated': updated})


def queue_count(request):
    """Returns the current queue count for AJAX updates."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    count = Media.objects.filter(user=user).count()
    return JsonResponse({'count': count})


@require_POST
@app_access('anonymizer')
def start_all(request):
    """« Tout lancer » (toolbar commune) — délègue au traitement global historique
    (ProcessView : verrou batch atomique cache.add + chaîne process_user_media_batch)."""
    return ProcessView().post(request)


def _anonymizer_nature(m):
    """Nature d'un média (image / vidéo / audio) — ce qui peut cohabiter dans un lot.

    DEUX consommateurs, une seule déclaration : le regroupement à l'import
    (`group_into_batches_by_nature`) et la fusion par drag&drop (`group_key`)."""
    return m.media_type or 'video'


def _group_medias_into_batches(user, medias, unwrap_singletons=None):
    """Crée UN batch PAR NATURE (image/vidéo/audio) — règle commune."""
    from wama.common.utils.batch_common import group_into_batches_by_nature
    group_into_batches_by_nature(
        medias,
        nature_of=_anonymizer_nature,
        create_batch=lambda nature, total: BatchAnonymizer.objects.create(user=user, total=total),
        link_item=lambda batch, m, idx: BatchAnonymizerItem.objects.create(
            batch=batch, media=m, row_index=idx),
        unwrap_singletons=unwrap_singletons,
    )


def consolidate_medias_into_batches(media_ids, user):
    """Regroupe des Media importés ENSEMBLE (même requête) par nature — helper PUBLIC
    exposé au filemanager (`api_import_to_app`), même découplage que le converter."""
    from wama.common.utils.batch_common import delete_singleton_batches, load_in_import_order
    items = load_in_import_order(Media, media_ids, user)
    if not items:
        return
    _group_medias_into_batches(
        user, items,
        unwrap_singletons=lambda ids: delete_singleton_batches(
            BatchAnonymizer, 'media', user, ids))


def _auto_wrap_orphans(user):
    """Range les Media pas encore en batch — brique COMMUNE, stratégie par défaut
    (chaque orphelin → batch-of-1). Le regroupement par nature ne se fait plus qu'à
    l'IMPORT GROUPÉ (consolidate_medias_into_batches) : indexé sur l'accumulation,
    il fusionnait des envois individuels espacés (constat Fabien 14/08)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(
        user, work_model=Media, batch_model=BatchAnonymizer,
        item_model=BatchAnonymizerItem, fk_name='media',
    )


def _decorate_card(media):
    """Attache les chips de card (générés du SCHÉMA, card_chips) à l'instance.
    Point d'attache UNIQUE : appelé par IndexView ET par card_html — sinon la card
    rendue par l'endpoint diverge de celle du chargement (leçon describer)."""
    from wama.common.utils.card_chips import chips_by_section
    from wama.anonymizer.params import PARAMS_JSON
    extra = []
    if not media.use_sam3 and media.classes2blur:
        extra.append({'label': ', '.join(media.classes2blur[:3])
                                + ('…' if len(media.classes2blur) > 3 else ''),
                      'icon': 'fa-eye-slash',
                      'title': 'Objets floutés : ' + ', '.join(media.classes2blur),
                      'section': 'settings'})
    media.chips = chips_by_section(media, PARAMS_JSON, extra=extra)
    return media


def _queue_context(request, user):
    """Contexte de FILE (toolbar + batches + schéma params) — briques communes."""
    import json as _json
    from wama.common.utils.batch_common import build_batches_list
    from wama.common.utils.queue_view import apply_queue_sort_filter
    from wama.anonymizer.params import GROUPS_JSON, PARAMS_JSON

    _auto_wrap_orphans(user)

    def _extra(batch, items, medias):
        from wama.common.utils.card_chips import common_chips_for_items
        from wama.anonymizer.params import PARAMS_JSON
        success_count = sum(1 for m in medias if m.status == 'SUCCESS')
        for m in medias:
            _decorate_card(m)
        return {
            'success_pct': int(success_count / batch.total * 100) if batch.total else 0,
            # ETA agrégée de la card mère (brique _batch_card.html) — CSV, pas liste
            'eta_ids': ','.join(str(m.id) for m in medias),
            # Réglages COMMUNS aux filles (slot meta_template, mécanisme du parc — porté
            # le 31/08 depuis le pilote transcriber, brique commune schéma-driven).
            'common_chips': common_chips_for_items(medias, PARAMS_JSON),
        }

    batches_list = build_batches_list(user, batch_model=BatchAnonymizer,
                                      work_attr='media', order_by='-created_at',
                                      extra=_extra)

    def _name(b):
        m = b['items'][0].media if b['obj'].total == 1 and b['items'] and b['items'][0].media else None
        return (m.get_filename() or '').lower() if m else ''

    batches_list, q_sort, q_filter = apply_queue_sort_filter(request, batches_list, name_of=_name)

    return {
        'batches_list': batches_list,
        'queue_count': sum(len(b['items']) for b in batches_list),
        'q_sort': q_sort,
        'q_filter': q_filter,
        # Schéma params (source unique modale item/batch + inspecteur). Voir params.py.
        'params_json': _json.dumps(PARAMS_JSON),
        # Groupes de la modale (sections calquées sur le volet droit). Voir params.py GROUPS.
        'groups_json': _json.dumps(GROUPS_JSON),
    }


# ── Manipulation directe de la file (fabrique COMMUNE, variante liaison) ─────────────
#
# L'anonymizer était la DERNIÈRE app hors fabrique (relevé du 2026-09-04 : 11 apps sur 12 avaient
# les routes, elle n'avait qu'un `consolidate`). Rien ne s'y opposait — elle a bien l'architecture
# batch unifiée (BatchAnonymizer + BatchAnonymizerItem + FK `media`) que la fabrique demande ;
# personne n'était simplement venu la brancher, faute d'UI qui l'exige.
#
# Son `consolidate` local est CONSERVÉ (la fabrique le permet explicitement) : il regroupe PAR
# NATURE, ce que le consolidate commun ne sait pas faire — même partage que describer et converter.
# `group_key` porte cette même règle jusqu'au geste de drag&drop : sans elle, glisser une vidéo
# dans un lot d'images produisait un lot mixte qu'aucun import n'aurait pu créer.
from wama.common.utils.queue_manipulation import make_queue_manipulation_views as _make_qm

_qm = _make_qm(
    work_model=Media, batch_model=BatchAnonymizer, item_model=BatchAnonymizerItem,
    fk_name='media',
    get_user=lambda r: r.user if r.user.is_authenticated else get_or_create_anonymous_user(),
    group_key=_anonymizer_nature,      # jumeau du `nature_of` de l'import
)
remove_from_batch = _qm['remove_from_batch']
reorder           = _qm['reorder']
reorder_queue     = _qm['reorder_queue']
merge             = _qm['merge']
move_to_batch     = _qm['move_to_batch']


def consolidate(request):
    """Regroupe plusieurs Media importés ensemble en UN batch-of-N."""
    import json as _json
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requis'}, status=405)
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    try:
        ids = _json.loads(request.body or '{}').get('ids', [])
    except (ValueError, TypeError):
        ids = request.POST.getlist('ids[]') or request.POST.getlist('ids')
    ids = [int(i) for i in ids if str(i).isdigit()]

    from wama.common.utils.batch_common import load_in_import_order
    items = load_in_import_order(Media, ids, user)
    if len(items) < 2:
        return JsonResponse({'consolidated': False})

    # Regroupement PAR NATURE (image / vidéo / audio) — même helper que l'import filemanager.
    consolidate_medias_into_batches(ids, user)
    return JsonResponse({'consolidated': True, 'count': len(items)})


def get_context(request):
    """Contexte du VOLET DROIT (réglages user legacy `setting-button`) — la file, elle,
    vient de `_queue_context` (briques communes). Les ModelForms et grilles `ms_values`/
    `range_widths` legacy sont mortes avec les partials upload/ (port 2026-08-03)."""
    if request.user.is_authenticated:
        user = request.user
    else:
        user = get_or_create_anonymous_user()

    user_settings, _ = UserSettings.objects.get_or_create(user=user)
    # Ensure sensible defaults for initial view (show_preview True)
    if user_settings.show_preview is None:
        user_settings.show_preview = True
        user_settings.save(update_fields=['show_preview'])

    global_settings = GlobalSettings.objects.all()

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
    gs_values['model_to_use'] = getattr(user_settings, 'model_to_use', '') or ''

    from .utils.yolo_utils import get_all_class_choices
    models_by_type = list_models_by_type()

    return {
        'user': user,
        'global_settings': global_settings,
        'gs_values': gs_values,
        'classes': get_all_class_choices(),
        'models_by_type': models_by_type,
        'model_help_meta': _model_help_meta(models_by_type),
        # Appariement entrée↔modèles (brique commune input_match) — JSON déjà sérialisé,
        # même contrat que model_help_meta (valeurs d'option `type/fichier` OU `fichier`).
        'input_match_meta': _input_match_meta(models_by_type),
        'input_labels': _input_labels(),
        # Couverture de classes PAR MODÈLE (brique d'alias model_coverage, JSON) → meta
        # WamaModelCaps : griser les checkboxes de classes hors modèle (jamais cachées).
        'class_coverage_meta': _class_coverage_meta(),
    }


def _class_coverage_meta():
    """{model_key: {covered_classes: [ids d'app]}} — l'appariement d'alias est fait CÔTÉ
    SERVEUR par la brique commune `classes_couvertes` (le vocabulaire du catalogue n'est pas
    celui des checkboxes ; leçon couvrir_classes : ne jamais re-apparier en JS)."""
    import json as _json
    try:
        from wama.common.services.model_coverage import classes_couvertes
        from wama.model_manager.models import AIModel
        from .utils.yolo_utils import get_all_class_choices
        voulues = [c[0] for c in get_all_class_choices()]
        meta = {}
        for m in AIModel.objects.filter(source='anonymizer', is_proposed=False):
            if (m.capabilities or {}).get('classes'):
                meta[m.model_key] = {'covered_classes': sorted(classes_couvertes(m, voulues))}
        return _json.dumps(meta)
    except Exception:
        return '{}'


def _input_match_meta(models_by_type):
    """Meta JSON brique COMMUNE re-clée sur les VALEURS D'OPTION du select (`type/fichier`,
    ou `fichier` seul pour le type root — même double clé que _model_help_meta) + pseudo-choix
    '' (« Auto (basé sur précision) », yolo seulement — sam3 vit derrière le radio de mode)."""
    import json as _json
    from wama.common.utils.input_match import auto_entry, input_match_meta
    base = input_match_meta('anonymizer', key=lambda mk: mk.rsplit(':', 1)[-1])
    if not base:
        return '{}'
    meta = {}
    for mtype, names in (models_by_type or {}).items():
        for name in names:
            entry = base.get(name)
            if entry:
                meta[f"{mtype}/{name}"] = entry
                meta.setdefault(name, entry)
    meta[''] = auto_entry({k: v for k, v in base.items() if k != 'sam3'} or base)
    return _json.dumps(meta)


def _input_labels():
    """Libellés d'INPUT_TYPES (JSON) — brique commune (extraction 2026-08-17)."""
    import json as _json
    from wama.common.utils.input_match import input_labels
    return _json.dumps(input_labels())


def _model_help_meta(models_by_type):
    """Meta JSON {valeur_option: {description, description_long, vram_gb}} pour WamaModelHelp
    (descriptif sous le select #user_setting_model_to_use), lue depuis le CATALOGUE `AIModel`
    (clés `anonymizer:yolo:<fichier>`). Les valeurs d'options du template sont `type/fichier`
    (ou `fichier` seul) → on mappe par nom de fichier. Fail-safe : '{}' si catalogue indispo."""
    import json as _json
    try:
        from wama.model_manager.models import AIModel
        by_fname = {}
        for m in AIModel.objects.filter(model_key__startswith='anonymizer:yolo:'):
            by_fname[m.model_key.rsplit(':', 1)[-1]] = {
                'description': m.description_short or '',
                'description_long': m.description or '',
                'vram_gb': m.vram_gb,
            }
        meta = {}
        for mtype, names in (models_by_type or {}).items():
            for name in names:
                info = by_fname.get(name)
                if info:
                    meta[f"{mtype}/{name}"] = info
                    meta.setdefault(name, info)
        return _json.dumps(meta)
    except Exception:
        return '{}'


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

    user_medias = list(Media.objects.filter(user=user))
    if user_medias:
        # Clear dedup locks
        cache.delete(f"anon_lock:batch:{user.id}")
        for media in user_medias:
            cache.delete(f"anon_lock:media:{media.id}")
            cache.delete(f"anon_task_owner:media:{media.id}")

            # Delete input file only if not shared with another item (safe for duplicates)
            safe_delete_file(media, 'file')

            # Delete output file (blurred media) - always unique per item
            try:
                output_path = get_blurred_media_path(media.file.name, media.file_ext, media.user_id)
                if os.path.exists(output_path):
                    os.remove(output_path)
            except Exception:
                pass

            media.delete()

        UserSettings.objects.filter(user_id=user.id).update(media_added=0, show_gs=0)

    return JsonResponse({'success': True})


@require_POST
def delete(request, pk: int):
    """Supprime UN média — route au format commun `delete/<pk>/` (2026-08-23).

    POURQUOI CETTE VUE EXISTE, ALORS QUE LA SUPPRESSION MARCHAIT DÉJÀ. Le bouton de
    l'anonymizer supprimait bien : il postait `media_id` en champ de formulaire vers
    `clear_media/`. Ce qui n'était pas conforme, c'est la FORME de la route — les neuf autres
    apps exposent `delete/<pk>/` et répondent `batch_changed`. Tant que l'anonymizer divergeait,
    la brique commune `queue-actions.js` ne pouvait pas le servir : elle poste un corps JSON
    vide vers `data-delete-url`, donc `media_id` serait arrivé VIDE — et une suppression sans
    cible est précisément ce qu'on ne veut pas laisser partir au hasard.

    Deux défauts de `clear_media` sont corrigés ici, et ils ne sont pas cosmétiques :
      1. **Aucun scope utilisateur** — `Media.objects.filter(pk=media_id)` acceptait l'id de
         N'IMPORTE QUEL utilisateur. Toutes les autres apps écrivent
         `get_object_or_404(Model, pk=pk, user=user)` ; l'anonymizer était le seul à ne pas le
         faire, sur des médias que l'app est faite pour anonymiser.
      2. **`batch_changed` absent de la réponse** — le JS devait deviner l'appartenance à un lot
         en inspectant le DOM. Le serveur sait ; il le dit désormais, comme partout ailleurs.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    media = get_object_or_404(Media, pk=pk, user=user)

    # Capturé AVANT la cascade : la suppression emporte le BatchAnonymizerItem.
    parent_batch = None
    try:
        parent_batch = media.batch_item.batch
    except Exception:
        pass

    _supprimer_media(media, user)
    # batch.total / suppression du lot vidé : gérés par le signal batch_sync.
    return JsonResponse({'success': True, 'deleted': pk,
                         'batch_changed': parent_batch is not None})


def _supprimer_media(media, user):
    """Travail de suppression proprement dit — partagé par `delete` et `clear_media`.

    Extrait le 2026-08-23 pour qu'il n'existe pas DEUX chemins de suppression : les verrous de
    déduplication, la remise à zéro de `MSValues_customised` et la bascule `show_gs` sont des
    effets de bord qu'on ne peut pas se permettre d'oublier d'un côté.
    """
    cache.delete(f"anon_lock:media:{media.pk}")
    cache.delete(f"anon_task_owner:media:{media.pk}")

    Media.objects.filter(pk=media.pk).update(MSValues_customised=0)
    safe_delete_file(media, 'file')
    media.delete()  # signal batch_sync : recale total / supprime le batch vidé

    has_media = Media.objects.filter(user=user).exists()
    UserSettings.objects.filter(user_id=user.id).update(media_added=int(has_media))
    if not has_media:
        # Hide global settings section when no media remains
        UserSettings.objects.filter(user_id=user.id).update(show_gs=0)


def clear_media(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    media_id = request.POST.get('media_id')
    media = Media.objects.filter(pk=media_id).first()

    if not media:
        return JsonResponse({'success': False, 'error': 'Media not found'}, status=404)

    try:
        # DÉLÈGUE au même travail que `delete` (2026-08-23) : un seul chemin de suppression,
        # sinon les effets de bord (verrous de dédup, MSValues_customised, bascule show_gs)
        # divergent au premier oubli. Cette vue n'a plus AUCUN consommateur dans le dépôt
        # depuis que la card passe par la brique commune — elle est conservée le temps de
        # vérifier qu'aucun appelant externe n'en dépend, puis à retirer (REMOVAL_LEDGER).
        _supprimer_media(media, user)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def reset_media_settings(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        media_id = request.POST.get('media_id')
        if not media_id:
            return JsonResponse({'success': False, 'error': 'Missing media_id'}, status=400)

        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
        media = get_object_or_404(Media, pk=media_id, user=user)
        global_settings_list = GlobalSettings.objects.all()

        # Champs éditables = le SCHÉMA (params.py), plus le ModelForm legacy.
        from wama.anonymizer.params import PARAMS_JSON
        schema_names = {f['name'] for f in PARAMS_JSON} | {'classes2blur'}
        updated_fields = {
            setting.name: setting.default
            for setting in global_settings_list
            if setting.name in schema_names
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
        # ⚠ `next` vient du CLIENT : validé avant redirection, comme dans `login_view`
        # (2026-08-31). C'est le JUMEAU que « une garde se pose avec ses jumeaux »
        # demandait de traiter dans le même geste : les deux seuls consommateurs de `next`
        # du dépôt sont cette vue et le login, et seul le second était gardé. Peu
        # atteignable (le test `is_ajax` capture déjà les POST de formulaire courants),
        # mais une garde ne se pose pas « là où c'est atteignable » — sinon elle se
        # redécouvre le jour où un appelant change de Content-Type.
        from django.utils.http import url_has_allowed_host_and_scheme
        cible = request.POST.get('next', '')
        if not url_has_allowed_host_and_scheme(cible, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
            cible = '/'
        return redirect(cible)



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
    """Valeurs COURANTES d'un média pour la modale paramètres — SCHÉMA-DRIVEN.

    Le payload est plat : `values[name]` pour chaque champ du schéma (params.py),
    + les deux cas à sémantique propre (classes2blur = liste à cocher ; modèles =
    options du select peuplées côté JS). Les listes sliders/booleans en dur ont
    disparu avec settings_modal.js (port 2026-08-03) : la modale est rendue par
    WamaParams.renderSettingsModal depuis le schéma."""
    try:
        from wama.common.utils.scoping import visible_or_404
        from wama.anonymizer.params import PARAMS_JSON
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
        media = visible_or_404(Media, user, pk=media_id)

        values = {}
        for field in PARAMS_JSON:
            v = getattr(media, field['name'], None)
            if v is not None:
                values[field['name']] = v
        values['model_to_use'] = media.model_to_use or ''
        values['sam3_prompt'] = media.sam3_prompt or ''

        from .utils.yolo_utils import get_all_class_choices, get_model_choices_grouped
        media_classes = media.classes2blur or []
        classes2blur_list = [
            {'value': code, 'label': label, 'checked': code in media_classes}
            for code, label in get_all_class_choices()
        ]
        model_choices = [
            {'value': value, 'label': label, 'group': group_label}
            for group_label, group_choices in get_model_choices_grouped()
            for value, label in group_choices
        ]

        return JsonResponse({
            'success': True,
            'values': values,
            'classes2blur': classes2blur_list,
            'model_choices': model_choices,
        })

    except Http404:
        raise
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }, status=500)


@require_POST
def save_media_settings(request):
    """Réglages d'un média depuis la modale — SCHÉMA-DRIVEN (typage/bornes = params.py).

    Les listes en dur slider_fields/bool_fields recopiaient les noms ET les types du
    schéma (redondance résorbée, ROADMAP §16.9 ②) : `coerce_schema_values` fait foi.
    Restent explicites les seuls cas à sémantique PROPRE : classes2blur (liste),
    sam3_prompt (validation + None), model_to_use ('' = retour à l'auto/global).
    """
    try:
        media_id = request.POST.get('media_id')
        if not media_id:
            return JsonResponse({'success': False, 'error': 'No media_id provided'}, status=400)

        # Scope par UTILISATEUR : l'ancien get(pk=…) laissait éditer le média d'autrui.
        media = Media.objects.get(pk=media_id, user=request.user)

        # Save classes2blur (checkboxes)
        classes2blur = request.POST.getlist('classes2blur')
        if classes2blur:
            media.classes2blur = classes2blur

        from wama.common.utils.param_schema import coerce_schema_values, schema_for_app
        valeurs = coerce_schema_values(schema_for_app('anonymizer'), request.POST)
        for cle in ('sam3_prompt', 'model_to_use', 'classes2blur'):
            valeurs.pop(cle, None)
        for champ, valeur in valeurs.items():
            setattr(media, champ, valeur)

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

        # « Enregistrer & relancer » (contrat composer) : restart=1 → relance sous verrou.
        if request.POST.get('restart', '0') == '1':
            from wama.common.utils.process_control import begin_processing
            locked, err = begin_processing(Media, media.pk, user=request.user,
                                           reset=_reset_for_relaunch)
            if err:
                return JsonResponse({'success': True, 'restarted': False, 'error': err})
            cache.delete(f"media_progress_{locked.id}")
            task = process_single_media.delay(locked.id, force_individual=True)
            locked.task_id = task.id
            locked.save(update_fields=['task_id'])
            return JsonResponse({'success': True, 'restarted': True,
                                 'status': 'RUNNING', 'task_id': task.id})

        return JsonResponse({
            'success': True,
            'restarted': False,
            'status': media.status,
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
        # Statut canonique depuis 2026-07-11 (audit §31) — l'ancien booléen `processed` = property dérivée
        success = medias.filter(status='SUCCESS').count()
        failure = medias.filter(status='FAILURE').count()
        running = medias.filter(status='RUNNING').count()
        pending = total - success - failure - running

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
            'failure': failure,
            'done': success,  # contrat wama-global-progress.js ({total, done, running, overall_progress})
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


@require_POST
def duplicate_media(request, media_id):
    """Duplicate a Media item sharing the same input file, resetting processing state."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    media = get_object_or_404(Media, pk=media_id, user=user)
    new_media = duplicate_instance(
        media,
        reset_fields={'status': 'PENDING', 'blur_progress': 0},
        clear_fields=[],
    )
    return JsonResponse({'duplicated': new_media.id})


def batch_duplicate(request, pk):
    """Duplique un batch et tous ses médias (entrées partagées, état remis à zéro)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requis'}, status=405)
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchAnonymizer, pk=pk, user=user)
    new_batch = BatchAnonymizer.objects.create(user=user, total=0)
    idx = 0
    for item in batch.items.select_related('media').order_by('row_index'):
        if not item.media:
            continue
        new_media = duplicate_instance(
            item.media, reset_fields={'status': 'PENDING', 'blur_progress': 0}, clear_fields=[])
        BatchAnonymizerItem.objects.create(batch=new_batch, media=new_media, row_index=idx)
        idx += 1
    new_batch.total = idx
    new_batch.save(update_fields=['total'])
    return JsonResponse({'duplicated': True, 'batch_id': new_batch.id})


def batch_download(request, pk):
    """ZIP de toutes les sorties traitées d'un batch. Lecture → partage F7."""
    import io
    import zipfile
    from wama.common.utils.scoping import visible_or_404
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = visible_or_404(BatchAnonymizer, user, pk=pk)
    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in batch.items.select_related('media'):
            m = item.media
            if not m or not m.processed:
                continue
            fp = get_blurred_media_path(m.file.name, m.file_ext, m.user_id)
            if os.path.exists(fp):
                zf.write(str(fp), arcname=os.path.basename(fp))
                added += 1
    if added == 0:
        return HttpResponseBadRequest("Aucune sortie disponible dans ce batch")
    buf.seek(0)
    return FileResponse(buf, as_attachment=True, filename=f'anonymizer_batch_{batch.id}.zip')


# =============================================================================
# Batch import (Type A: media_list — one URL/path per line)
# =============================================================================

def batch_template(request):
    """Download a batch file template (.txt)."""
    from django.http import HttpResponse
    content = (
        "# WAMA Anonymizer - Batch Import\n"
        "# Format : une URL ou chemin de fichier image/vidéo par ligne\n"
        "# Les lignes commençant par # sont des commentaires.\n\n"
        "https://example.com/photo.jpg\n"
        "https://example.com/video.mp4\n"
        "/media/uploads/photo.png\n"
    )
    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_anonymizer_template.txt"'
    return response


@require_POST
def batch_preview(request):
    """Parse a batch file and return the list for preview (no DB entries created)."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    return batch_media_list_preview_response(request)


@require_POST
def batch_create(request):
    """
    Parse batch file (URLs/paths), create BatchAnonymizer + Media entries.
    Files are not downloaded yet — download happens when the task starts.
    """
    from wama.common.utils.batch_parsers import parse_batch_file_from_request

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    # parse_batch_file_from_request a consommé FILES['batch_file'] : on le re-lit
    # pour l'archiver sur le batch (NameError avant 2026-08-03).
    batch_file = request.FILES.get('batch_file')
    if batch_file:
        batch_file.seek(0)
    batch = BatchAnonymizer.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        filename = url_or_path.split('/')[-1].split('\\')[-1] or f'item_{i+1}'
        m = Media.objects.create(
            user=user,
            title=filename,
            source_url=url_or_path,
            file='',
            file_ext='',
        )
        BatchAnonymizerItem.objects.create(batch=batch, media=m, row_index=i)
        created_ids.append(m.id)

    UserSettings.objects.filter(user_id=user.id).update(media_added=1)

    return JsonResponse({
        'batch_id': batch.id,
        'media_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


@require_POST
def batch_delete(request, pk):
    """Delete an entire batch and all its media items."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchAnonymizer, pk=pk, user=user)

    media_to_delete = []
    for item in batch.items.select_related('media').all():
        if item.media:
            media_to_delete.append(item.media)

    safe_delete_file(batch, 'batch_file')
    batch.delete()  # CASCADE deletes BatchAnonymizerItems

    for media in media_to_delete:
        cache.delete(f"anon_lock:media:{media.id}")
        cache.delete(f"anon_task_owner:media:{media.id}")
        try:
            output_path = get_blurred_media_path(media.file.name, media.file_ext, media.user_id)
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception:
            pass
        safe_delete_file(media, 'file')
        media.delete()

    return JsonResponse({'success': True, 'batch_id': pk})
