import os
import re
import cv2
from pytube import *
from tqdm import tqdm
import urllib.request
import subprocess as sp

# from django.core.files.storage import FileSystemStorage
from django.shortcuts import render, redirect
from django.http import FileResponse, JsonResponse
from django.contrib.auth.models import User, AnonymousUser
# from django.contrib import messages
from django.template import loader
from django.conf import settings
from django.views import View

from .forms import MediaForm, MediaSettingsForm, GlobalSettingsForm, UserSettingsForm
from .models import Media, GlobalSettings, UserSettings
from .tasks import start_process, stop_process
from ..accounts.views import add_user


class UploadView(View):

    def get(self, request):
        global_settings_list = GlobalSettings.objects.all()
        if len(global_settings_list) == 0:
            init_global_settings()
        if not User.objects.filter(username='anonymous').exists():
            add_user('anonymous', 'Anonymous', 'User', 'anonymous@univ-eiffel.fr')
        user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
        user_settings_form = UserSettingsForm(instance=user)
        user_settings = UserSettings.objects.get(user_id=user.id)
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
        return render(self.request, 'medias/upload/index.html', context)

    def post(self, request):
        medias_form = MediaForm(self.request.POST, self.request.FILES)
        if medias_form.is_valid():
            media = medias_form.save()
            media.file_ext = os.path.splitext(media.file.name)[1]
            user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
            UserSettings.objects.filter(user_id=user.id).update(**{'media_added': 1})
            media.username = user.username
            vid = cv2.VideoCapture('./media/' + media.file.name)
            media.fps = vid.get(cv2.CAP_PROP_FPS)
            media.width = vid.get(cv2.CAP_PROP_FRAME_WIDTH)
            media.height = vid.get(cv2.CAP_PROP_FRAME_HEIGHT)
            media.properties = str(int(media.width)) + 'x' + str(int(media.height)) + ' (' + str(int(media.fps)) + 'fps)'
            media.duration_inSec = vid.get(cv2.CAP_PROP_FRAME_COUNT)/media.fps
            media.duration_inMinSec = str(int(media.duration_inSec / 60)) + ':' + str(media.duration_inSec % 60)
            media.save()
            media_data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url, 'file_ext': media.file_ext,
                          'username': media.username, 'fps': media.fps, 'width': media.width, 'height': media.height,
                          'duration': media.duration_inMinSec}
        else:
            media_data = {'is_valid': False}
        return JsonResponse(media_data)


class ProcessView(View):
    def get(self, request):
        global_settings_list = GlobalSettings.objects.all()
        user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
        user_settings_form = UserSettingsForm(instance=user)
        user_settings = UserSettings.objects.get(user_id=user.id)
        medias_list = Media.objects.all()
        media_settings_form = {}
        ms_values = {}
        for media in medias_list:
            if request.user.is_authenticated and request.user.username in media.username:
                media_settings_form[media.id] = MediaSettingsForm(instance=media)
                ms_values[media.id] = dict()
                for setting in global_settings_list:
                    ms_values[media.id][setting.name] = getattr(media, setting.name)
            elif media.username == 'Anonymous':
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
        return render(self.request, 'medias/process/index.html', context)

    def post(self, request):
        if request.POST.get('url', 'medias:process'):
            global_settings_list = GlobalSettings.objects.all()
            user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
            user_settings_form = UserSettingsForm(instance=user)
            user_settings = UserSettings.objects.get(user_id=user.id)
            medias_list = Media.objects.all()
            media_settings_form = {}
            ms_values = {}
            for media in medias_list:
                if request.user.is_authenticated and request.user.username in media.username:
                    media_settings_form[media.id] = MediaSettingsForm(instance=media)
                    ms_values[media.id] = dict()
                    for setting in global_settings_list:
                        ms_values[media.id][setting.name] = getattr(media, setting.name)
                    length = media.duration_inSec * media.fps
                    with tqdm(total=length, desc="Blurring media", unit="frames", dynamic_ncols=True) as progress_bar:
                        kwargs = {
                            'model_path': media.model_path,  # 'anonymizer/models/yolov8n.pt',
                            'media_path': os.path.join('media', media.file.name),
                            'media_ext': media.file_ext,
                            'classes2blur': media.classes2blur if media.MSValues_customised else user_settings.classes2blur,  # ['face', 'plate']
                            'blur_ratio': media.blur_ratio if media.MSValues_customised else user_settings.blur_ratio,  # 20
                            'rounded_edges': media.rounded_edges if media.MSValues_customised else user_settings.rounded_edges,  # 5
                            'roi_enlargement': media.roi_enlargement if media.MSValues_customised else user_settings.roi_enlargement,  # 1.05
                            'detection_threshold': media.detection_threshold if media.MSValues_customised else user_settings.detection_threshold,  # 0.25
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
            gs_values = dict()
            for setting in global_settings_list:
                gs_values[setting.name] = getattr(user_settings, setting.name)
            class_list = Media.classes2blur.field.choices
            context = {'user': user, 'medias': medias_list, 'media_settings_form': media_settings_form,
                       'global_settings': global_settings_list, 'user_settings_form': user_settings_form,
                       'ms_values': ms_values, 'gs_values': gs_values, 'classes': class_list}
            return render(self.request, 'medias/process/index.html', context)

    def display_console(self, request):
        if request.POST.get('url', 'medias:process.display_console'):
            command = "path/to/builder.pl --router " + 'hostname'
            pipe = sp.Popen(command.split(), stdout=sp.PIPE, stderr=sp.PIPE)
            console = pipe.stdout.read()
            return render(self.request, 'medias/process/index.html', {'console': console})


def download_media(request):
    if request.method == 'POST':
        media = Media.objects.get(pk=request.POST['media_id'])
        media_name = media.file.name.replace('input', 'output')
        media_path = os.path.join(settings.MEDIA_ROOT, os.path.splitext(media_name)[0] + '_blurred' + media.file_ext)
        if os.path.exists(media_path):
            response = FileResponse(open(media_path, "rb"), as_attachment=True)
            return response
        else:
            global_settings_list = GlobalSettings.objects.all()
            user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
            user_settings_form = UserSettingsForm(instance=user)
            user_settings = UserSettings.objects.get(user_id=user.id)
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
            return render(request, 'medias/process/index.html', context)


def stop(request):
    if request.POST.get('url', 'medias:stop_process'):
        stop_process()
    medias_list = Media.objects.all()
    media_settings_form = {}
    for media in medias_list:
        media_settings_form[media.id] = MediaSettingsForm(instance=media)
    medias_form = MediaForm
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    user_settings_form = UserSettingsForm(instance=user)
    context = {'user': user, 'medias': medias_list, 'medias_form': medias_form, 'media_settings_form': media_settings_form,
               'user_settings_form': user_settings_form}
    return render(request, 'medias/upload/index.html', context)


def refresh_content(request):
    global_settings_list = GlobalSettings.objects.all()
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    user_settings_form = UserSettingsForm(instance=user)
    user_settings = UserSettings.objects.get(user_id=user.id)
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
    template = loader.get_template('medias/upload/content.html')
    context = {'user': user, 'medias': medias_list, 'media_settings_form': media_settings_form,
               'global_settings': global_settings_list, 'user_settings_form': user_settings_form,
               'ms_values': ms_values, 'gs_values': gs_values, 'classes': class_list}
    response = {'render': template.render(context, request), }
    return JsonResponse(response)


def refresh_media_table(request):
    medias_list = Media.objects.all()
    global_settings_list = GlobalSettings.objects.all()
    media_settings_form = {}
    for media in medias_list:
        media_settings_form[media.id] = MediaSettingsForm(media)
    medias_form = MediaForm
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    user_settings_form = UserSettingsForm(instance=user)
    ms_values = dict()
    for setting in global_settings_list:
        ms_values[setting.name] = getattr(media, setting.name)
    template = loader.get_template('medias/upload/media_table.html')
    context = {'user': user, 'medias': medias_list, 'medias_form': medias_form, 'global_settings': global_settings_list,
               'media_settings_form': media_settings_form, 'user_settings_form': user_settings_form,
               'ms_values': ms_values}
    response = {'render': template.render(context, request), }
    return JsonResponse(response)


def refresh_media_settings(request):
    global_settings_list = GlobalSettings.objects.all()
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    user_settings_form = UserSettingsForm(instance=user)
    medias_list = Media.objects.all()
    media_settings_form = {}
    for media in medias_list:
        media_settings_form[media.id] = MediaSettingsForm(media)
    ms_values = dict()
    for setting in global_settings_list:
        ms_values[setting.name] = getattr(media, setting.name)
    template = loader.get_template('medias/upload/media_settings.html')
    context = {'user': user, 'medias': medias_list, 'media_settings_form': media_settings_form,
               'user_settings_form': user_settings_form, 'ms_values': ms_values}
    response = {'render': template.render(context, request), }
    return JsonResponse(response)


def refresh_global_settings(request):
    global_settings_list = GlobalSettings.objects.all()
    global_settings_form = GlobalSettingsForm()
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    user_settings_form = UserSettingsForm(instance=user)
    template = loader.get_template('medias/upload/global_settings.html')
    context = {'user': user, 'global_settings': global_settings_list, 'global_settings_form': global_settings_form,
               'user_settings_form': user_settings_form}
    response = {'render': template.render(context, request), }
    return JsonResponse(response)


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


def clear_database(request):
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


def reset_user_settings(request):
    user = request.user if request.user.is_authenticated else User.objects.get(username='anonymous')
    init_user_settings(user)
    if user.username == 'anonymous':
        for setting in GlobalSettings.objects.all():
            setting.delete()
        init_global_settings()
    UserSettings.objects.filter(user_id=request.user.id).update(GSValues_customised=0)
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


def upload_from_url(request):
    if request.method == 'POST':
        link = request.POST['link']
        video = YouTube(link)
        stream = video.streams.get_highest_resolution()
        vid = cv2.VideoCapture(stream.download())
        medias_form = MediaForm(request.POST, request.FILES)
        if medias_form.is_valid():
            media = medias_form.save()
            media.user_id = request.POST['user_id']
            media.fps = int(vid.get(cv2.CAP_PROP_FPS))
            media.width = vid.get(cv2.CAP_PROP_FRAME_WIDTH)
            media.height = vid.get(cv2.CAP_PROP_FRAME_HEIGHT)
            media.duration_inSec = vid.get(cv2.CAP_PROP_FRAME_COUNT)/media.fps
            media.duration_inMinSec = str(int(media.duration_inSec / 60)) + ':' + str(media.duration_inSec % 60)
            media.save()
            media_data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url, 'user_id': media.user_id,
                          'fps': media.fps, 'width': media.width, 'height': media.height,
                          'duration': media.duration_inMinSec}
        else:
            media_data = {'is_valid': False}
        return JsonResponse(media_data)

        # myfile = request.FILES['myfile']
        # fs = FileSystemStorage()
        # filename = fs.save(myfile.name, myfile)
        # uploaded_file_url = fs.url(filename)
        # return render(request, 'core/simple_upload.html', {
        #     'uploaded_file_url': uploaded_file_url
        # })
    # return render(request, 'core/simple_upload.html')
