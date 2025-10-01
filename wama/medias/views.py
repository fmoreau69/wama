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

from django.http import FileResponse, HttpResponseBadRequest, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.db import close_old_connections
from django.core.cache import cache
from django.contrib.auth.models import User
from django.template import loader
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView

from .models import Media, GlobalSettings, UserSettings
from .forms import MediaSettingsForm, UserSettingsForm
from .tasks import process_single_media, process_user_media_batch, stop_process
from .utils.media_utils import get_input_media_path, get_output_media_path, get_blurred_media_path, get_unique_filename
from .utils.yolo_utils import get_model_path

from ..accounts.views import get_or_create_anonymous_user
from ..settings import MEDIA_ROOT, MEDIA_INPUT_ROOT, MEDIA_OUTPUT_ROOT


class UploadView(View):
    def get(self, request):
        return render(request, 'medias/upload/index.html', get_context(request))

    def post(self, request):
        user = request.user if request.user.is_authenticated else User.objects.filter(username="anonymous").first()
        UserSettings.objects.filter(user_id=user.id).update(media_added=1)

        try:
            media_file = request.FILES.get('file')

            # Case 1: text file containing paths or URLs
            if media_file and media_file.name.endswith(('.txt', '.csv', '.log')):
                lines = media_file.read().decode('utf-8').splitlines()
                added, failed = [], []

                for line in lines:
                    path = line.strip().replace('\\', '/')
                    if not path:
                        continue
                    try:
                        if is_url(path):
                            video_path = upload_media_from_url(path, MEDIA_INPUT_ROOT)
                        else:
                            if not os.path.isfile(path):
                                raise FileNotFoundError("Local path not found or inaccessible")
                            filename = os.path.basename(path)
                            unique_filename = get_unique_filename(MEDIA_INPUT_ROOT, filename)
                            dest_path = os.path.join(MEDIA_INPUT_ROOT, unique_filename)
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
            video_path = upload_from_url(request)
            media_result = process_media(video_path, user)
            if isinstance(media_result, dict) and media_result.get('is_valid'):
                return JsonResponse({'success': True, 'media': media_result})
            else:
                return JsonResponse({'success': False, 'error': media_result}, status=400)

        except ValueError as e:
            return JsonResponse({'is_valid': False, 'error': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'is_valid': False, 'error': f"Server error: {e}"}, status=500)


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
        media = Media.objects.create(file=f'input_media/{filename}', file_ext=ext, user=user)

        mime_type, _ = mimetypes.guess_type(video_path)
        if mime_type and mime_type.startswith("video/"):
            vid = cv2.VideoCapture(str(video_path))
            add_media_to_db(media, vid)
        else:
            add_media_to_db(media, video_path)

        return {
            'is_valid': True,
            'name': filename,
            'url': media.file.url,
            'file_ext': media.file_ext,
            'username': user.username,
            'fps': media.fps,
            'width': media.width,
            'height': media.height,
            'duration': media.duration_inMinSec,
        }
    except Exception as e:
        return str(e)


def upload_from_url(request):
    """Handle media from either an uploaded file or a form URL."""
    media_file = request.FILES.get('file')
    media_url = request.POST.get('media_url')
    output_path = MEDIA_INPUT_ROOT
    os.makedirs(output_path, exist_ok=True)

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


def upload_media_from_url(url, output_path):
    """Download a media file from a URL using yt_dlp or direct HTTP."""
    try:
        # YouTube and similar platforms
        if 'youtube.com' in url or 'youtu.be' in url:
            ydl_opts = {
                'format': 'mp4/best',
                'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                base_path = ydl.prepare_filename(info)

                filename = os.path.basename(base_path)
                unique_path = get_unique_filename(output_path, filename)
                if unique_path != filename:
                    new_path = os.path.join(output_path, unique_path)
                    os.rename(base_path, new_path)
                    return new_path
                return base_path

        # HTTP download
        response = requests.get(url, stream=True, timeout=15)
        response.raise_for_status()
        filename = os.path.basename(urlparse(url).path) or 'video.mp4'
        unique_filename = get_unique_filename(output_path, filename)
        save_path = os.path.join(output_path, unique_filename)

        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return save_path

    except Exception as e:
        raise ValueError(f"Download failed: {e}")


def add_media_to_db(media, vid_or_path):
    """Populate the Media model with metadata from a video or image."""
    if isinstance(vid_or_path, str):
        mime_type, _ = mimetypes.guess_type(vid_or_path)
        if mime_type and mime_type.startswith("image/"):
            try:
                with Image.open(vid_or_path) as img:
                    media.width, media.height = img.size
                media.fps = 1
                media.duration_inSec = 0
                media.duration_inMinSec = "0:00"
                media.properties = f"{media.width}x{media.height} (1fps)"
                media.media_type = "image"
                media.save()
                return
            except Exception as e:
                raise ValueError(f"Error opening image: {e}")

    # Video processing
    vid = vid_or_path
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
    def get(self, request):
        return render(request, 'medias/process/index.html', get_context(request))

    def post(self, request):
        try:
            user = request.user if request.user.is_authenticated else User.objects.filter(username="anonymous").first()
            # Lancer batch task qui va enchaîner toutes les tâches individuelles
            task = process_user_media_batch.delay(user.id)
            cache.set(f"user_task_{user.id}", task.id, timeout=3600)
            return JsonResponse({"task_id": task.id})
        except Exception as e:
            import traceback
            print("🚨 ERREUR upload:", e)
            traceback.print_exc()
            return JsonResponse({'is_valid': False, 'error': str(e)}, status=500)

    def display_console(self, request):
        if request.POST.get('url', 'medias:process.display_console'):
            command = "path/to/builder.pl --router " + 'hostname'
            pipe = sp.Popen(command.split(), stdout=sp.PIPE, stderr=sp.PIPE)
            console = pipe.stdout.read()
            return render(self.request, 'medias/process/index.html', {'console': console})
        return None


def get_process_progress(request):
    user_id = request.user.id or request.session.session_key
    if not user_id:
        request.session.save()
        user_id = request.session.session_key
    progress = int(cache.get(f"process_progress_{user_id}", 0))
    return JsonResponse({"progress": progress})


def task_status(request, task_id):
    res = AsyncResult(task_id)
    return JsonResponse({"status": res.status})


def download_media(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    media_id = request.POST.get('media_id')
    if not media_id:
        return HttpResponseBadRequest("Missing media_id.")

    media = get_object_or_404(Media, pk=media_id)

    # Generate blurred output file path
    media_path = get_blurred_media_path(media.file.name, media.file_ext)
    blurred_filename = os.path.basename(media_path)

    if not os.path.exists(media_path):
        # Return to a page with context (HTML)
        context = get_context(request)
        context['error'] = f"Processed file {blurred_filename} doesn't exist."
        return render(request, 'medias/process/index.html', context)

        # In JSON if called via JavaScript
        # return JsonResponse({'error': 'Blurred file not found.'}, status=404)

    # Serve le fichier
    try:
        response = FileResponse(open(media_path, "rb"), as_attachment=True, filename=os.path.basename(media_path))
        print(f"Téléchargement : {blurred_filename}")
        return response
    except Exception as e:
        return HttpResponseBadRequest(f"Erreur lors du téléchargement : {str(e)}")


# @login_required
def download_all_media(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    user = request.user

    # Recover processed user media
    medias = Media.objects.filter(user=user, processed=True)

    if not medias.exists():
        return HttpResponseBadRequest("No blurred files found.")

    # Create a ZIP archive in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for media in medias:
            file_path = get_blurred_media_path(media.file.name, media.file_ext)

            if os.path.exists(file_path):
                archive_name = os.path.basename(file_path)
                zip_file.write(str(file_path), arcname=archive_name)

    zip_buffer.seek(0)
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
        template = loader.get_template(f'medias/upload/{template_name}.html')
    except Exception as e:
        return JsonResponse({'error': f"Template introuvable : {e}"}, status=500)

    context = get_context(request)
    return JsonResponse({'render': template.render(context, request)})


def get_context(request):
    if request.user.is_authenticated:
        user = request.user
    else:
        user = User.objects.filter(username="anonymous").first()

    user_settings, _ = UserSettings.objects.get_or_create(user=user)
    user_settings_form = UserSettingsForm(instance=user_settings)

    global_settings = GlobalSettings.objects.all()
    medias = Media.objects.filter(user=user)

    media_settings_form = {}
    ms_values = {}

    for media in medias:
        media_settings_form[media.id] = MediaSettingsForm(instance=media)
        ms_values[media.id] = {}
        for setting in global_settings:
            ms_values[media.id][setting.name] = getattr(media, setting.name, None)

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
        gs_values[setting.name] = getattr(user_settings, setting.name, setting.default)

    class_list = Media.classes2blur.field.choices

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
        'range_width': 'col-sm-12',
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
                media.save(update_fields=['classes2blur'])
                context['value'] = current

            else:
                # générique : float, bool, int
                field = Media._meta.get_field(setting_name)
                internal_type = field.get_internal_type()

                if internal_type == 'BooleanField':
                    value = str(input_value).lower() in ['true', '1', 'on']
                elif internal_type in ['FloatField', 'DecimalField']:
                    value = float(input_value)
                else:
                    value = int(input_value)

                setattr(media, setting_name, value)
                media.save()
                context['value'] = getattr(media, setting_name)

            # Charger le GlobalSettings correspondant pour le titre/label
            context['setting'] = GlobalSettings.objects.get(name=setting_name)

        elif setting_type == 'user_setting':
            user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
            user_settings, _ = UserSettings.objects.get_or_create(user=user)

            field = UserSettings._meta.get_field(setting_name)
            internal_type = field.get_internal_type()

            if internal_type == 'BooleanField':
                value = str(input_value).lower() in ['true', '1', 'on']
            elif internal_type in ['FloatField', 'DecimalField']:
                value = float(input_value)
            else:
                value = int(input_value)

            setattr(user_settings, setting_name, value)
            user_settings.save()
            context['value'] = getattr(user_settings, setting_name)
            context['setting'] = GlobalSettings.objects.get(name=setting_name)

        elif setting_type == 'global_setting':
            global_setting, _ = GlobalSettings.objects.get_or_create(name=setting_name)

            global_setting.value = input_value
            global_setting.save()
            context['value'] = global_setting.value
            context['setting'] = global_setting

        else:
            return JsonResponse({'error': f'Unknown setting_type: {setting_type}'}, status=400)

        html = loader.render_to_string('medias/upload/setting_button.html', context, request=request)
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
        "Console": lambda: UserSettings.objects.filter(user_id=user.id).update(show_console=button_state),
    }

    for key, action in update_map.items():
        if key in button_id:
            action()
            return JsonResponse(data={})

    return HttpResponseBadRequest("Unknown button_id")



def clear_all_media(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    if user.user_settings.media_added:
        user_medias = Media.objects.filter(user=user)
        for media in user_medias:
            media.file.delete()
        user_medias.delete()
        UserSettings.objects.filter(user_id=user.id).update(media_added=0)
        UserSettings.objects.filter(user_id=user.id).update(show_gs=0)

    # Rafraîchir le template content
    context = get_context(request)
    template = loader.get_template('medias/upload/content.html')
    return JsonResponse({'render': template.render(context, request)})


def clear_media(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    media_id = request.POST.get('media_id')
    media = Media.objects.filter(pk=media_id).first()

    if media:
        Media.objects.filter(pk=media_id).update(MSValues_customised=0)
        media.file.delete()
        media.delete()

    has_media = Media.objects.filter(user=user).exists()
    UserSettings.objects.filter(user_id=user.id).update(media_added=int(has_media))

    context = get_context(request)
    template = loader.get_template('medias/upload/content.html')
    return JsonResponse({'render': template.render(context, request)})


def reset_media_settings(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    media_id = request.POST.get('media_id')
    if not media_id:
        return HttpResponseBadRequest("Missing media_id")

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

    # Rafraîchir dynamiquement le bloc HTML comme les autres vues
    context = get_context(request)
    template = loader.get_template('medias/upload/content.html')
    return JsonResponse({'render': template.render(context, request)})


@require_POST
def reset_user_settings(request):
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    init_user_settings(user)

    if user.username == 'anonymous':
        reset_global_settings_safe()

    UserSettings.objects.filter(user_id=user.id).update(GSValues_customised=0)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        context = get_context(request)
        html = render_to_string("medias/upload/global_settings.html", context=context, request=request)
        return JsonResponse({"render": html})
    else:
        return redirect(request.POST.get('next', '/'))


def init_user_settings(user):
    close_old_connections()  # assure que la connexion est du thread courant

    global_settings_list = GlobalSettings.objects.all()
    if not global_settings_list:
        return
    for setting in global_settings_list:
        field_name = setting.name.split('_')[0]
        if field_name in [f.name for f in UserSettings._meta.get_fields()]:
            UserSettings.objects.filter(user_id=user.id).update(**{field_name: setting.default})


def init_global_settings():
    if GlobalSettings.objects.exists():
        return  # Already initialized

    global_settings_list = [
        {'title': "Objects to blur", 'name': "classes2blur", 'default': ["face", "plate"], 'value': ["face", "plate"],
         'type': 'BOOL', 'label': 'WTB'},
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
    for setting_data in global_settings_list:
        setting = GlobalSettings(**setting_data)
        setting.save()

def ensure_global_settings():
    if not GlobalSettings.objects.exists():
        init_global_settings()

def reset_global_settings_safe():
    """Réinitialise les GlobalSettings sans provoquer d'erreur de thread."""
    close_old_connections()  # ferme toute connexion héritée d'un autre thread

    if GlobalSettings.objects.exists():
        GlobalSettings.objects.all().delete()
    init_global_settings()

class AboutView(TemplateView):
    template_name = 'medias/about/index.html'

class HelpView(TemplateView):
    template_name = 'medias/help/index.html'
