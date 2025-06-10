import os
import re
import cv2
import yt_dlp
import mimetypes
import uuid
from tqdm import tqdm
# import urllib.request
import subprocess as sp

from django.core.files.storage import default_storage, FileSystemStorage
from django.http import FileResponse, JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.template import loader
from django.conf import settings
from django.views import View

from .forms import MediaForm, MediaSettingsForm, GlobalSettingsForm, UserSettingsForm
from .models import Media, GlobalSettings, UserSettings
from .tasks import start_process, stop_process
from ..settings import MEDIA_INPUT_ROOT
from ..accounts.views import add_user


class UploadView(View):

    def get(self, request):
        if len(GlobalSettings.objects.all()) == 0:
            init_global_settings()
        if not User.objects.filter(username='anonymous').exists():
            add_user('anonymous', 'Anonymous', 'User', 'anonymous@univ-eiffel.fr')
        return render(self.request, 'medias/upload/index.html', get_context(request))

    def post(self, request):
        user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
        UserSettings.objects.filter(user_id=user.id).update(media_added=1)

        try:
            video_path = upload_from_url(request)
            filename = os.path.basename(video_path)

            media = Media.objects.create(file=f'input_media/{filename}', file_ext=os.path.splitext(filename)[1])
            mime_type, _ = mimetypes.guess_type(video_path)
            if mime_type and mime_type.startswith("video/"):
                vid = cv2.VideoCapture(str(video_path))
                add_media_to_db(media, user, vid)
            else:
                add_media_to_db(media, user, video_path)

            return JsonResponse({
                'is_valid': True,
                'name': filename,
                'url': media.file.url,
                'file_ext': media.file_ext,
                'username': media.username,
                'fps': media.fps,
                'width': media.width,
                'height': media.height,
                'duration': media.duration_inMinSec,
            })

        except ValueError as e:
            return JsonResponse({'is_valid': False, 'error': str(e)}, status=400)

        except Exception as e:
            return JsonResponse({'is_valid': False, 'error': f"Erreur serveur : {e}"}, status=500)


def upload_from_url(request):
    media_file = request.FILES.get('file')
    media_url = request.POST.get('media_url')
    output_path = settings.MEDIA_INPUT_ROOT
    allowed_mime_types = [
        'video/mp4', 'video/x-msvideo', 'video/quicktime', 'video/x-matroska',
        'image/jpeg', 'image/png', 'image/jpg', 'image/bmp'
    ]

    if media_file:
        mime_type, _ = mimetypes.guess_type(media_file.name)
        if mime_type not in allowed_mime_types:
            raise ValueError(f"Type de fichier non supporté : {mime_type}")

        filename = get_unique_filename(output_path, media_file.name)
        save_path = os.path.join(output_path, filename)

        with open(save_path, 'wb+') as dest:
            for chunk in media_file.chunks():
                dest.write(chunk)
        return save_path

    elif media_url:
        ydl_opts = {
            'format': 'mp4/best',
            'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
            'quiet': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(media_url, download=True)
            base_path = ydl.prepare_filename(info)

            filename = os.path.basename(base_path)
            unique_path = get_unique_filename(output_path, filename)
            if unique_path != filename:
                new_path = os.path.join(output_path, unique_path)
                os.rename(base_path, new_path)
                return new_path
            return base_path

    raise ValueError("Aucun média fourni (fichier ou URL).")


def get_unique_filename(folder, filename):
    """Ajoute un suffixe UUID si le fichier existe déjà."""
    base, ext = os.path.splitext(filename)
    full_path = os.path.join(folder, filename)
    while os.path.exists(full_path):
        filename = f"{base}_{uuid.uuid4().hex[:6]}{ext}"
        full_path = os.path.join(folder, filename)
    return filename


def add_media_to_db(media, user, vid_or_path):
    media.username = user.username

    if isinstance(vid_or_path, str):
        mime_type, _ = mimetypes.guess_type(vid_or_path)
        if mime_type and mime_type.startswith("image/"):
            # Cas image
            from PIL import Image
            try:
                with Image.open(vid_or_path) as img:
                    media.width, media.height = img.size
                media.fps = 1
                media.duration_inSec = 0
                media.duration_inMinSec = "0:00"
                media.properties = f"{media.width}x{media.height} (1fps)"
                media.media_type = "image"
            except Exception as e:
                raise ValueError(f"Erreur lors de l'ouverture de l'image : {e}")
            media.save()
            return

    # Cas vidéo
    vid = vid_or_path
    fps = vid.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 25  # fallback

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
        return render(self.request, 'medias/process/index.html', get_context(request))

    def post(self, request):
        if request.POST.get('url', 'medias:process'):
            user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
            user_settings = UserSettings.objects.get(user_id=user.id)
            medias_list = Media.objects.all()
            for media in medias_list:
                if user.username in media.username:
                    ms_custom = media.MSValues_customised
                    length = media.duration_inSec * media.fps
                    with tqdm(total=length, desc="Blurring media", unit="frames", dynamic_ncols=True) as progress_bar:
                        kwargs = {
                            'model_path': media.model_path,  # 'anonymizer/models/yolov8n.pt',
                            'media_path': os.path.join('media', media.file.name),
                            'file_ext': media.file_ext,
                            'classes2blur': media.classes2blur if ms_custom else user_settings.classes2blur,  # ['face', 'plate']
                            'blur_ratio': media.blur_ratio if ms_custom else user_settings.blur_ratio,  # 20
                            'rounded_edges': media.rounded_edges if ms_custom else user_settings.rounded_edges,  # 5
                            'roi_enlargement': media.roi_enlargement if ms_custom else user_settings.roi_enlargement,  # 1.05
                            'detection_threshold': media.detection_threshold if ms_custom else user_settings.detection_threshold,  # 0.25
                            'show_preview': user_settings.show_preview,  # True
                            'show_boxes': user_settings.show_boxes,  # True
                            'show_labels': user_settings.show_labels,  # True
                            'show_conf': user_settings.show_conf,  # True
                        }
                        if any([classe in kwargs['classes2blur'] for classe in ['face', 'plate']]):
                            kwargs['model_path'] = 'anonymizer/models/yolov8m_faces&plates_720p.pt'
                        start_process(**kwargs)
                        progress_bar.update()
                        media.processed = True
                        media.save()
            return render(self.request, 'medias/process/index.html', get_context(request))
        return None

    def display_console(self, request):
        if request.POST.get('url', 'medias:process.display_console'):
            command = "path/to/builder.pl --router " + 'hostname'
            pipe = sp.Popen(command.split(), stdout=sp.PIPE, stderr=sp.PIPE)
            console = pipe.stdout.read()
            return render(self.request, 'medias/process/index.html', {'console': console})
        return None


def download_media(request):
    if request.method == 'POST':
        media = Media.objects.get(pk=request.POST['media_id'])
        media_name = media.file.name.replace('input', 'output')
        media_path = os.path.join(settings.MEDIA_ROOT, os.path.splitext(media_name)[0] + '_blurred' + media.file_ext)
        if os.path.exists(media_path):
            response = FileResponse(open(media_path, "rb"), as_attachment=True)
            print(f"Downloading: {media_name}")
            return response
        else:
            return render(request, 'medias/process/index.html', get_context(request))
    return None


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
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    user_settings = UserSettings.objects.get(user_id=user.id)
    user_settings_form = UserSettingsForm(instance=user)
    global_settings_list = GlobalSettings.objects.all()
    medias_list = Media.objects.all()
    media_settings_form = {}
    ms_values = {}
    for media in medias_list:
        if user.username in media.username:
            media_settings_form[media.id] = MediaSettingsForm(instance=media)
            ms_values[media.id] = dict()
            for setting in global_settings_list:
                ms_values[media.id][setting.name] = getattr(media, setting.name)
    gs_values = dict()
    for setting in global_settings_list:
        gs_values[setting.name] = getattr(user_settings, setting.name)
    class_list = Media.classes2blur.field.choices
    context = {'user': user, 'medias': medias_list, 'media_settings_form': media_settings_form,
               'global_settings': global_settings_list, 'user_settings_form': user_settings_form,
               'ms_values': ms_values, 'gs_values': gs_values, 'classes': class_list}
    return context


def update_settings(request):
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    if request.method == 'POST':
        input_id = request.POST.get('input_id')
        context_value = request.POST.get('input_value')
        setting_type = re.search(r'^\S*_setting', input_id).group()
        global_settings_list = GlobalSettings.objects.all()
        for setting in global_settings_list:
            if setting.name in input_id:
                context_id = {}
                range_width = ''
                field = {}
                class_list = UserSettings.classes2blur.field.choices
                template = loader.get_template('medias/upload/setting_button.html')
                if setting_type == 'media_setting':
                    context_id = re.search(r'\d+$', input_id).group()
                    range_width = 'col-sm-12'
                    if setting.name == 'classes2blur':
                        template = loader.get_template('widgets/CheckboxMultipleModal.html')
                        class_id = int(re.findall(r'\d+', input_id)[-2])
                        new_class = Media.classes2blur.field.choices[class_id][0]
                        classes2blur = Media.objects.get(pk=context_id).classes2blur
                        context_value = classes2blur[:-1] + ", '" + new_class + "']" if new_class not in classes2blur \
                            else classes2blur.replace(", '" + new_class + "'", '')
                        field = MediaSettingsForm(instance=Media.objects.get(pk=context_id))['classes2blur']
                    Media.objects.filter(pk=context_id).update(**{setting.name: context_value})
                    Media.objects.filter(pk=context_id).update(MSValues_customised=1)
                elif setting_type == 'global_setting':
                    context_id = user.id
                    range_width = 'col-sm-3'
                    if setting.name == 'classes2blur':
                        template = loader.get_template('widgets/CheckboxMultipleModal.html')
                        class_id = int(re.findall(r'\d+', input_id)[-1])
                        new_class = UserSettings.classes2blur.field.choices[class_id][0]
                        classes2blur = UserSettings.objects.get(user_id=context_id).classes2blur
                        context_value = classes2blur[:-1] + ", '" + new_class + "']" if new_class not in classes2blur \
                            else classes2blur.replace(", '" + new_class + "'", '')
                        user_settings_form = UserSettingsForm(instance=user)
                        field = user_settings_form['classes2blur']
                    if setting.name != 'classes2blur' and any(sub in context_value for sub in ['true', 'false']):
                        context_value = context_value.capitalize()
                    UserSettings.objects.filter(user_id=context_id).update(**{setting.name: context_value})
                    UserSettings.objects.filter(user_id=context_id).update(GSValues_customised=1)
                context = {'user': user, 'setting_type': setting_type, 'id': context_id, 'setting': setting,
                           'range_width': range_width, 'value': context_value, 'field': field, 'classes': class_list}
                response = {'render': template.render(context, request), }
                return JsonResponse(response)
            return None
        return None
    return None


def expand_area(request):
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    if request.method == 'POST':
        button_id = request.POST["button_id"]
        button_state = request.POST["button_state"]
        if "MediaSettings" in button_id:
            Media.objects.filter(pk=re.search(r'\d+$', button_id).group()).update(show_ms=button_state)
        elif "GlobalSettings" in button_id:
            UserSettings.objects.filter(user_id=user.id).update(show_gs=button_state)
        elif "Preview" in button_id:
            UserSettings.objects.filter(user_id=user.id).update(show_preview=button_state)
        elif "Console" in button_id:
            UserSettings.objects.filter(user_id=user.id).update(show_console=button_state)
        return JsonResponse(data={})
    return None


def clear_all_media(request):
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    if user.user_settings.media_added:
        for media in Media.objects.all():
            if user.username in media.username:
                media.file.delete()
                media.delete()
        UserSettings.objects.filter(user_id=user.id).update(**{'media_added': 0})
    return redirect(request.POST.get('next'))


def clear_media(request):
    if request.method == 'POST':
        user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
        if user.user_settings.media_added:
            media = Media.objects.get(pk=request.POST['media_id'])
            media.file.delete()
            media.delete()
            media_added = 0
            for media in Media.objects.all():
                if user.username in media.username:
                    media_added = 1
            UserSettings.objects.filter(user_id=user.id).update(**{'media_added': media_added})
            Media.objects.filter(pk=request.POST['media_id']).update(MSValues_customised=0)
    return redirect(request.POST.get('next'))


def reset_media_settings(request):
    if request.method == 'POST':
        media = Media.objects.get(pk=request.POST['media_id'])
        media_settings_form = MediaSettingsForm(media)
        global_settings_list = GlobalSettings.objects.all()
        for setting in global_settings_list:
            if setting.name in media_settings_form.fields:
                Media.objects.filter(pk=request.POST['media_id']).update(**{setting.name: setting.default})
        Media.objects.filter(pk=request.POST['media_id']).update(MSValues_customised=0)
        return redirect(request.POST.get('next'))
    return None


def reset_user_settings(request):
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    init_user_settings(user)
    if user.username == 'anonymous':
        for setting in GlobalSettings.objects.all():
            setting.delete()
        init_global_settings()
    UserSettings.objects.filter(user_id=user.id).update(GSValues_customised=0)
    return redirect(request.POST.get('next'))


def init_user_settings(user):
    global_settings_list = GlobalSettings.objects.all()
    for setting in global_settings_list:
        UserSettings.objects.filter(user_id=user.id).update(**{setting.name: setting.default})


def init_global_settings():
    global_settings_list = [
        {'title': "Objects to blur", 'name': "classes2blur", 'default': ['', 'face', 'plate'], 'value': ['', 'face', 'plate'],
         'type': 'BOOL', 'label': 'WTB'},
        {'title': "Blur ratio", 'name': "blur_ratio", 'default': "25", 'value': "25",
         'min': "0", 'max': "50", 'step': "1", 'type': 'FLOAT', 'label': 'HTB',
         'attr_list': {'min': '0', 'max': '50', 'step': '1'}},
        {'title': "Rounded edges", 'name': "rounded_edges", 'default': "5", 'value': "5",
         'min': "0", 'max': "50", 'step': "1", 'type': 'FLOAT', 'label': 'HTB',
         'attr_list': {'min': '0', 'max': '50', 'step': '1'}},
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
    for setting in global_settings_list:
        global_settings_form = GlobalSettingsForm(setting)
        global_settings_form.save()

class AboutView(View):
    def get(self, request):
        return render(self.request, 'medias/about/index.html')

class HelpView(View):
    def get(self, request):
        return render(self.request, 'medias/help/index.html')
