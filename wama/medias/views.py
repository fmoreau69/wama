import os
import io
import re
import cv2
import yt_dlp
import zipfile
import mimetypes
import uuid
import requests
from PIL import Image
from tqdm import tqdm
from urllib.parse import urlparse
import subprocess as sp

# from django.core.files.storage import default_storage, FileSystemStorage
from django.http import FileResponse, JsonResponse, HttpResponseBadRequest, HttpResponseNotAllowed  # , Http404
from django.shortcuts import render, redirect, get_object_or_404
# from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
# from django.contrib import messages
from django.template import loader
from django.conf import settings
from django.views import View
from django.views.generic import TemplateView

from .forms import MediaSettingsForm, GlobalSettingsForm, UserSettingsForm  # , MediaForm
from .models import Media, GlobalSettings, UserSettings
from .tasks import start_process, stop_process
# from ..settings import MEDIA_INPUT_ROOT
from ..accounts.views import add_user, get_or_create_anonymous_user


class UploadView(View):

    def get(self, request):
        # Ensure default settings and anonymous user exist
        if not GlobalSettings.objects.exists():
            init_global_settings()
        get_or_create_anonymous_user()
        return render(request, 'medias/upload/index.html', get_context(request))

    def post(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
        UserSettings.objects.filter(user_id=user.id).update(media_added=1)

        try:
            media_file = request.FILES.get('file')

            # Case 1: text file containing paths or URLs
            if media_file and media_file.name.endswith(('.txt', '.csv', '.log')):
                lines = media_file.read().decode('utf-8').splitlines()
                added, failed, results = [], [], []

                for line in lines:
                    path = line.strip().replace('\\', '/')  # Normalize Windows-style paths
                    if not path:
                        continue
                    try:
                        if is_url(path):
                            # Remote URL: download it
                            video_path = download_media_from_url(path, settings.MEDIA_INPUT_ROOT)
                        else:
                            # Local path: validate and copy into MEDIA_INPUT_ROOT
                            if not os.path.isfile(path):
                                raise FileNotFoundError("Local path not found or inaccessible")

                            filename = os.path.basename(path)
                            unique_filename = get_unique_filename(settings.MEDIA_INPUT_ROOT, filename)
                            dest_path = os.path.join(settings.MEDIA_INPUT_ROOT, unique_filename)

                            with open(path, 'rb') as src, open(dest_path, 'wb') as dst:
                                dst.write(src.read())

                            video_path = dest_path

                        added.append(video_path)
                    except Exception as e:
                        failed.append((path, str(e)))

                # Process all valid media files
                for video_path in added:
                    try:
                        result = process_media(video_path, user)
                        if isinstance(result, dict):
                            results.append(result)
                        else:
                            failed.append((video_path, str(result)))
                    except Exception as e:
                        failed.append((video_path, str(e)))

                return JsonResponse({'results': results, 'errors': failed})

            # Case 2: direct upload (file or URL from form)
            video_path = upload_from_url(request)
            result = process_media(video_path, user)
            return JsonResponse(result)

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
            add_media_to_db(media, user, vid)
        else:
            add_media_to_db(media, user, video_path)

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
    output_path = settings.MEDIA_INPUT_ROOT
    os.makedirs(output_path, exist_ok=True)

    if media_file:
        return handle_uploaded_media_file(media_file, output_path)
    elif media_url:
        return download_media_from_url(media_url, output_path)

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


def download_media_from_url(url, output_path):
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


def get_unique_filename(folder, filename):
    """Return a unique filename if the file already exists."""
    base, ext = os.path.splitext(filename)
    full_path = os.path.join(folder, filename)
    while os.path.exists(full_path):
        filename = f"{base}_{uuid.uuid4().hex[:6]}{ext}"
        full_path = os.path.join(folder, filename)
    return filename


def add_media_to_db(media, user, vid_or_path):
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
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # S'assurer que les UserSettings existent pour cet utilisateur
        user_settings, _ = UserSettings.objects.get_or_create(user=user)
        user_settings.media_added = True
        user_settings.save()

        medias_list = Media.objects.filter(user=user)

        for media in medias_list:
            ms_custom = media.MSValues_customised
            length = media.duration_inSec * media.fps

            kwargs = {
                'media_path': os.path.join('media', media.file.name),
                'file_ext': media.file_ext,
                'classes2blur': media.classes2blur if ms_custom else user_settings.classes2blur,
                'blur_ratio': media.blur_ratio if ms_custom else user_settings.blur_ratio,
                'rounded_edges': media.rounded_edges if ms_custom else user_settings.rounded_edges,
                'progressive_blur': media.progressive_blur if ms_custom else user_settings.progressive_blur,
                'roi_enlargement': media.roi_enlargement if ms_custom else user_settings.roi_enlargement,
                'detection_threshold': media.detection_threshold if ms_custom else user_settings.detection_threshold,
                'show_preview': user_settings.show_preview,
                'show_boxes': user_settings.show_boxes,
                'show_labels': user_settings.show_labels,
                'show_conf': user_settings.show_conf,
            }

            # Si floutage de visages ou plaques, utiliser modèle spécifique
            if any(c in kwargs['classes2blur'] for c in ['face', 'plate']):
                kwargs['model_path'] = 'anonymizer/models/yolov8m_faces&plates_720p.pt'

            start_process(**kwargs)

            media.processed = True
            media.save()

        return render(request, 'medias/process/index.html', get_context(request))


    def display_console(self, request):
        if request.POST.get('url', 'medias:process.display_console'):
            command = "path/to/builder.pl --router " + 'hostname'
            pipe = sp.Popen(command.split(), stdout=sp.PIPE, stderr=sp.PIPE)
            console = pipe.stdout.read()
            return render(self.request, 'medias/process/index.html', {'console': console})
        return None


def download_media(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    media_id = request.POST.get('media_id')
    if not media_id:
        return HttpResponseBadRequest("Missing media_id.")

    media = get_object_or_404(Media, pk=media_id)

    # Generate blurred output file path
    output_name = media.file.name.replace('input', 'output')
    blurred_filename = os.path.splitext(output_name)[0] + '_blurred' + media.file_ext
    media_path = os.path.join(settings.MEDIA_ROOT, blurred_filename)

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
            # Build blurred file path
            media_name = media.file.name.replace('input', 'output')
            blurred_filename = os.path.splitext(media_name)[0] + '_blurred' + media.file_ext
            file_path = os.path.join(settings.MEDIA_ROOT, blurred_filename)

            if os.path.exists(file_path):
                archive_name = os.path.basename(file_path)
                zip_file.write(str(file_path), arcname=archive_name)

    zip_buffer.seek(0)
    return FileResponse(zip_buffer, as_attachment=True, filename="blurred_media.zip")


def stop(request):
    if request.POST.get('url', 'medias:stop_process'):
        stop_process()
    return render(request, 'medias/upload/index.html', get_context(request))


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
    return JsonResponse({'html': template.render(context, request)})


def get_context(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    user_settings = UserSettings.objects.get(user=user)
    user_settings_form = UserSettingsForm(instance=user_settings)
    global_settings_list = GlobalSettings.objects.all()
    medias_list = Media.objects.filter(user=user)

    media_settings_form = {}
    ms_values = {}

    for media in medias_list:
        media_settings_form[media.id] = MediaSettingsForm(instance=media)
        ms_values[media.id] = {}
        for setting in global_settings_list:
            ms_values[media.id][setting.name] = getattr(media, setting.name)

    gs_values = dict()
    for setting in global_settings_list:
        gs_values[setting.name] = getattr(user_settings, setting.name)
    class_list = Media.classes2blur.field.choices

    context = {
        'user': user,
        'medias': medias_list,
        'media_settings_form': media_settings_form,
        'global_settings': global_settings_list,
        'user_settings_form': user_settings_form,
        'ms_values': ms_values,
        'gs_values': gs_values,
        'classes': class_list,
    }

    return context


def update_settings(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    input_id = request.POST.get('input_id')
    context_value = request.POST.get('input_value')

    if not input_id:
        return HttpResponseBadRequest("Missing input_id")

    match = re.search(r'^\S*_setting', input_id)
    if not match:
        return HttpResponseBadRequest("Invalid input_id format")

    setting_type = match.group()
    global_settings_list = GlobalSettings.objects.all()

    for setting in global_settings_list:
        if setting.name not in input_id:
            continue

        context_id = None
        range_width = ''
        field = {}
        class_list = UserSettings.classes2blur.field.choices
        template = loader.get_template('medias/upload/setting_button.html')

        if setting_type == 'media_setting':
            context_id = re.search(r'\d+$', input_id).group()
            range_width = 'col-sm-12'
            media = Media.objects.filter(pk=context_id).first()
            if not media:
                return HttpResponseBadRequest("Invalid media ID")
            if setting.name == 'classes2blur':
                template = loader.get_template('widgets/CheckboxMultipleModal.html')
                class_id = int(re.findall(r'\d+', input_id)[-2])
                classes_str = media.classes2blur or ""
                classes_list = [cls.strip() for cls in classes_str.split(',') if cls.strip()]

                new_class = Media.classes2blur.field.choices[class_id][0]

                if new_class in classes_list:
                    classes_list.remove(new_class)
                else:
                    classes_list.append(new_class)

                context_value = ','.join(classes_list)

                media.classes2blur = context_value
                field = MediaSettingsForm(instance=media)['classes2blur']
            Media.objects.filter(pk=context_id).update(**{setting.name: context_value}, MSValues_customised=1)

        elif setting_type == 'global_setting':
            context_id = user.id
            range_width = 'col-sm-3'
            user_settings = UserSettings.objects.get(user_id=context_id)
            if setting.name == 'classes2blur':
                template = loader.get_template('widgets/CheckboxMultipleModal.html')
                class_id = int(re.findall(r'\d+', input_id)[-1])
                new_class = UserSettings.classes2blur.field.choices[class_id][0]
                classes2blur = user_settings.classes2blur
                context_value = (
                    classes2blur[:-1] + ", '" + new_class + "']"
                    if new_class not in classes2blur
                    else classes2blur.replace(", '" + new_class + "'", '')
                )
                field = UserSettingsForm(instance=user_settings)['classes2blur']
            elif any(val in context_value for val in ['true', 'false']):
                context_value = context_value.capitalize()
            UserSettings.objects.filter(user_id=context_id).update(**{setting.name: context_value}, GSValues_customised=1)

        context = {
            'user': user,
            'setting_type': setting_type,
            'id': context_id,
            'setting': setting,
            'range_width': range_width,
            'value': context_value,
            'field': field,
            'classes': class_list
        }
        return JsonResponse({'render': template.render(context, request)})

    return HttpResponseBadRequest("Setting not found in input_id")


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

    return redirect(request.POST.get('next', '/'))


def clear_media(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    media_id = request.POST.get('media_id')
    media = Media.objects.filter(pk=media_id).first()

    if media:
        media.file.delete()
        media.delete()
        Media.objects.filter(pk=media_id).update(MSValues_customised=0)

    has_media = Media.objects.filter(user=user).exists()
    UserSettings.objects.filter(user_id=user.id).update(media_added=int(has_media))

    return redirect(request.POST.get('next', '/'))


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

    return redirect(request.POST.get('next', '/'))



def reset_user_settings(request):
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    init_user_settings(user)

    if user.username == 'anonymous':
        if GlobalSettings.objects.exists():
            GlobalSettings.objects.all().delete()
        init_global_settings()

    UserSettings.objects.filter(user_id=user.id).update(GSValues_customised=0)
    return redirect(request.POST.get('next', '/'))


def init_user_settings(user):
    if GlobalSettings.objects.exists():
        return  # Already initialized

    global_settings_list = GlobalSettings.objects.all()
    for setting in global_settings_list:
        UserSettings.objects.filter(user_id=user.id).update(**{setting.name: setting.default})


def init_global_settings():
    if GlobalSettings.objects.exists():
        return  # Already initialized

    global_settings_list = [
        {'title': "Objects to blur", 'name': "classes2blur", 'default': "face,plate", 'value': "face,plate",
         'type': 'BOOL', 'label': 'WTB'},
        {'title': "Blur ratio", 'name': "blur_ratio", 'default': "25", 'value': "25",
         'min': "1", 'max': "49", 'step': "2", 'type': 'FLOAT', 'label': 'HTB',
         'attr_list': {'min': '1', 'max': '49', 'step': '2'}},
        {'title': "Rounded edges", 'name': "rounded_edges", 'default': "5", 'value': "5",
         'min': "0", 'max': "50", 'step': "1", 'type': 'FLOAT', 'label': 'HTB',
         'attr_list': {'min': '0', 'max': '50', 'step': '1'}},
        {'title': "Progressive blur", 'name': "progressive_blur", 'default': "25", 'value': "25",
         'min': "3", 'max': "31", 'step': "2", 'type': 'FLOAT', 'label': 'HTB',
         'attr_list': {'min': '3', 'max': '31', 'step': '2'}},
        {'title': "ROI enlargement", 'name': "roi_enlargement", 'default': "1.05", 'value': "1.05",
         'min': "0.5", 'max': "1.5", 'step': "0.05", 'type': 'FLOAT', 'label': 'HTB',
         'attr_list': {'min': '0.5', 'max': '1.5', 'step': '0.05'}},
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


class AboutView(TemplateView):
    template_name = 'medias/about/index.html'

class HelpView(TemplateView):
    template_name = 'medias/help/index.html'
