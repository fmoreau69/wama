import os
import re
import cv2
from pytube import *
from tqdm import tqdm
import urllib.request
import subprocess as sp

from django.core.files.storage import FileSystemStorage
from django.shortcuts import render, redirect
from django.http import FileResponse, JsonResponse
from django.contrib import messages
from django.template import loader
from django.conf import settings
from django.views import View

from .forms import MediaForm, MediaSettingsForm, GlobalSettingsForm, UserSettingsForm
from .models import Media, GlobalSettings, UserSettings
from .tasks import start_process, stop_process


class UploadView(View):

    def get(self, request):
        global_settings_list = GlobalSettings.objects.all()
        if len(global_settings_list) == 0:
            init_global_settings()
        user_settings_form = UserSettingsForm(instance=request.user) if request.user.is_authenticated \
            else UserSettingsForm()
        user_settings = UserSettings.objects.get(user_id=request.user.id) if request.user.is_authenticated \
            else {}
        medias_list = Media.objects.all()
        media_settings_form = {}
        for media in medias_list:
            media_settings_form[media.id] = MediaSettingsForm(instance=media)
        ms_values = dict()
        gs_values = dict()
        for setting in global_settings_list:
            ms_values[setting.name] = getattr(media, setting.name)
            gs_values[setting.name] = getattr(user_settings, setting.name)
        context = {'medias': medias_list, 'media_settings_form': media_settings_form,
                   'global_settings': global_settings_list, 'user_settings_form': user_settings_form,
                   'ms_values': ms_values, 'gs_values': gs_values}
        return render(self.request, 'medias/upload/index.html', context)

    def post(self, request):
        # print(self.request.FILES)
        medias_form = MediaForm(self.request.POST, self.request.FILES)
        # print(medias_form)
        if medias_form.is_valid():
            media = medias_form.save()
            media.username = self.request.user.username
            vid = cv2.VideoCapture('./media/' + media.file.name)
            media.fps = vid.get(cv2.CAP_PROP_FPS)
            media.width = vid.get(cv2.CAP_PROP_FRAME_WIDTH)
            media.height = vid.get(cv2.CAP_PROP_FRAME_HEIGHT)
            media.properties = str(int(media.width)) + 'x' + str(int(media.height)) + ' (' + str(int(media.fps)) + 'fps)'
            media.duration_inSec = vid.get(cv2.CAP_PROP_FRAME_COUNT)/media.fps
            media.duration_inMinSec = str(int(media.duration_inSec / 60)) + ':' + str(media.duration_inSec % 60)
            media.save()
            media_data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url, 'username': media.username,
                          'fps': media.fps, 'width': media.width, 'height': media.height,
                          'duration': media.duration_inMinSec}
            if self.request.user.is_authenticated:
                UserSettings.objects.filter(user_id=request.user.id).update(**{'media_added': 1})
        else:
            media_data = {'is_valid': False}
        return JsonResponse(media_data)


class ProcessView(View):
    def get(self, request):
        medias_list = Media.objects.all()
        media_settings_form = {}
        for media in medias_list:
            media_settings_form[media.id] = MediaSettingsForm(instance=media)
        medias_form = MediaForm(self.request.POST, self.request.FILES)
        context = {'medias': medias_list, 'medias_form': medias_form, 'media_settings_form': media_settings_form}
        return render(self.request, 'medias/process/index.html', context)

    def post(self, request):
        if request.POST.get('url', 'medias:process'):
            medias_list = Media.objects.all()
            for media in medias_list:
                length = media.duration_inSec * media.fps
                with tqdm(total=length, desc="Blurring media", unit="frames", dynamic_ncols=True) as progress_bar:
                    kwargs = {
                        'model_path': media.model_path,  # 'anonymizer/models/yolov8n.pt',
                        'media_path': os.path.join('media', media.file.name),
                        'classes2blur': media.classes2blur,  # ['face', 'plate']
                        'blur_ratio': media.blur_ratio,  # 20
                        'rounded_edges': media.rounded_edges,  # 5
                        'roi_enlargement': media.roi_enlargement,  # 1.05
                        'detection_threshold': media.detection_threshold,  # 0.25
                        'show_preview': media.show_preview,  # True
                        'show_boxes': media.show_boxes,  # True
                        'show_labels': media.show_labels,  # True
                        'show_conf': media.show_conf,  # True
                    }
                    if any([classe in kwargs['classes2blur'] for classe in ['face', 'plate']]):
                        kwargs['model_path'] = 'anonymizer/models/yolov8m_faces&plates_720p.pt'
                    start_process(**kwargs)
                    progress_bar.update()
                    media.processed = True
                    media.save()
            media_settings_form = {}
            for media in medias_list:
                media_settings_form[media.id] = MediaSettingsForm(instance=media)
            medias_form = MediaForm(self.request.POST, self.request.FILES)
            context = {'medias': medias_list, 'medias_form': medias_form, 'media_settings_form': media_settings_form}
            return render(self.request, 'medias/process/index.html', context)

    def display_console(self, request):
        if request.POST.get('url', 'medias:process.display_console'):
            command = "path/to/builder.pl --router " + 'hostname'
            pipe = sp.Popen(command.split(), stdout=sp.PIPE, stderr=sp.PIPE)
            console = pipe.stdout.read()
            return render(self.request, 'medias/process/index.html', {'console': console})


def download_media(request, pk):
    if request.method == 'POST' and request.user.is_authenticated:
        media = Media.objects.get(pk=pk)
        file_name = media.file.name.replace('input', 'output')
        file_path = os.path.join(settings.MEDIA_ROOT, file_name[:-4] + '_blurred.avi')
        if os.path.exists(file_path):
            with open(file_path, 'rb') as file:
                print(file_path)
                response = FileResponse(file)
                response['Content-Disposition'] = f'attachment; filename="{file_name}"'
                return response
        else:
            medias_list = Media.objects.all()
            global_settings_list = GlobalSettings.objects.all()
            context = {'medias': medias_list, 'global_settings': global_settings_list}
            return render(request, 'medias/process/index.html', context)


def stop(request):
    if request.POST.get('url', 'medias:stop_process'):
        stop_process()
    medias_list = Media.objects.all()
    media_settings_form = {}
    for media in medias_list:
        media_settings_form[media.id] = MediaSettingsForm(instance=media)
    medias_form = MediaForm
    user_settings_form = UserSettingsForm(instance=request.user) if request.user.is_authenticated \
        else UserSettingsForm()
    context = {'medias': medias_list, 'medias_form': medias_form, 'media_settings_form': media_settings_form,
               'user_settings_form': user_settings_form}
    return render(request, 'medias/upload/index.html', context)


def refresh_content(request):
    global_settings_list = GlobalSettings.objects.all()
    user_settings_form = UserSettingsForm(instance=request.user) if request.user.is_authenticated \
        else UserSettingsForm()
    user_settings = UserSettings.objects.get(user_id=request.user.id) if request.user.is_authenticated \
        else {}
    medias_list = Media.objects.all()
    media_settings_form = {}
    for media in medias_list:
        media_settings_form[media.id] = MediaSettingsForm(instance=media)
    medias_form = MediaForm
    ms_values = dict()
    gs_values = dict()
    for setting in global_settings_list:
        ms_values[setting.name] = getattr(media, setting.name)
        gs_values[setting.name] = getattr(user_settings, setting.name)
    template = loader.get_template('medias/upload/content.html')
    context = {'medias': medias_list, 'medias_form': medias_form, 'media_settings_form': media_settings_form,
               'global_settings': global_settings_list, 'user_settings_form': user_settings_form,
               'ms_values': ms_values, 'gs_values': gs_values}
    response = {'render': template.render(context, request), }
    return JsonResponse(response)


def refresh_media_table(request):
    medias_list = Media.objects.all()
    global_settings_list = GlobalSettings.objects.all()
    media_settings_form = {}
    for media in medias_list:
        media_settings_form[media.id] = MediaSettingsForm(media)
    medias_form = MediaForm
    user_settings_form = UserSettingsForm(instance=request.user) if request.user.is_authenticated \
        else UserSettingsForm()
    ms_values = dict()
    for setting in global_settings_list:
        ms_values[setting.name] = getattr(media, setting.name)
    template = loader.get_template('medias/upload/media_table.html')
    context = {'medias': medias_list, 'medias_form': medias_form, 'global_settings': global_settings_list,
               'media_settings_form': media_settings_form, 'user_settings_form': user_settings_form,
               'ms_values': ms_values}
    response = {'render': template.render(context, request), }
    return JsonResponse(response)


def refresh_media_settings(request):
    global_settings_list = GlobalSettings.objects.all()
    user_settings_form = UserSettingsForm(instance=request.user) if request.user.is_authenticated \
        else UserSettingsForm()
    medias_list = Media.objects.all()
    media_settings_form = {}
    for media in medias_list:
        media_settings_form[media.id] = MediaSettingsForm(media)
    ms_values = dict()
    for setting in global_settings_list:
        ms_values[setting.name] = getattr(media, setting.name)
    template = loader.get_template('medias/upload/media_settings.html')
    context = {'medias': medias_list, 'media_settings_form': media_settings_form,
               'user_settings_form': user_settings_form, 'ms_values': ms_values}
    response = {'render': template.render(context, request), }
    return JsonResponse(response)


def refresh_global_settings(request):
    global_settings_list = GlobalSettings.objects.all()
    global_settings_form = GlobalSettingsForm()
    user_settings_form = UserSettingsForm(instance=request.user) if request.user.is_authenticated \
        else UserSettingsForm()
    template = loader.get_template('medias/upload/global_settings.html')
    context = {'global_settings': global_settings_list, 'global_settings_form': global_settings_form,
               'user_settings_form': user_settings_form}
    response = {'render': template.render(context, request), }
    return JsonResponse(response)


def update_settings(request):
    if request.method == 'POST':
        input_id = request.POST.get('input_id')
        context_value = request.POST.get('input_value')
        setting_type = re.search(r'^\S*_setting', input_id).group()
        global_settings_list = GlobalSettings.objects.all()
        for setting in global_settings_list:
            if setting.name in input_id:
                context_id = {}
                range_width = ''
                if setting_type == 'media_setting':
                    context_id = re.search(r'\d+', input_id).group()
                    range_width = 'col-sm-12'
                    Media.objects.filter(pk=context_id).update(**{setting.name: context_value})
                elif setting_type == 'global_setting':
                    context_id = request.user.id
                    range_width = 'col-sm-3'
                    if any(sub in context_value for sub in ['true', 'false']):
                        context_value = context_value.capitalize()
                    UserSettings.objects.filter(user_id=context_id).update(**{setting.name: context_value})
                context = {'setting_type': setting_type, 'id': context_id, 'setting': setting,
                           'range_width': range_width, 'value': context_value}
                template = loader.get_template('medias/upload/setting_button.html')
                response = {'render': template.render(context, request), }
                return JsonResponse(response)


def expand_area(request):
    if request.method == 'POST' and request.user.is_authenticated:
        button_id = request.POST["button_id"]
        button_state = request.POST["button_state"]
        if "MediaSettings" in button_id:
            Media.objects.filter(pk=re.search(r'\d+', button_id).group()).update(show_settings=button_state)
        elif "GlobalSettings" in button_id:
            UserSettings.objects.filter(user_id=request.user.id).update(show_gs=button_state)
        elif "Console" in button_id:
            UserSettings.objects.filter(user_id=request.user.id).update(show_console=button_state)
        return JsonResponse(data={})


def clear_database(request):
    if request.user.is_authenticated and request.user.user_settings.media_added:
        for media in Media.objects.all():
            if request.user.username in media.username:
                media.file.delete()
                media.delete()
        UserSettings.objects.filter(user_id=request.user.id).update(**{'media_added': 0})
    return redirect(request.POST.get('next'))


def clear_media(request):
    if request.method == 'POST':
        if request.user.is_authenticated and request.user.user_settings.media_added:
            media = Media.objects.get(pk=request.POST['media_id'])
            media.file.delete()
            media.delete()
            media_added = 0
            for media in Media.objects.all():
                if request.user.username in media.username:
                    media_added = 1
            UserSettings.objects.filter(user_id=request.user.id).update(**{'media_added': media_added})
    return redirect(request.POST.get('next'))


def reset_media_settings(request):
    if request.method == 'POST':
        media = Media.objects.get(pk=request.POST['media_id'])
        media_settings_form = MediaSettingsForm(media)
        global_settings_list = GlobalSettings.objects.all()
        for setting in global_settings_list:
            if setting.name in media_settings_form.fields:
                print(str(setting.name) + ' = ' + str(setting.default))
                Media.objects.filter(pk=request.POST['media_id']).update(**{setting.name: setting.default})
        return redirect(request.POST.get('next'))


def reset_user_settings(request):
    if request.user.is_authenticated:
        init_user_settings(request)
    else:
        for setting in GlobalSettings.objects.all():
            setting.delete()
        init_global_settings()
    return redirect(request.POST.get('next'))


def init_user_settings(request):
    global_settings_list = GlobalSettings.objects.all()
    for setting in global_settings_list:
        UserSettings.objects.filter(user_id=request.user.id).update(**{setting.name: setting.default})


def init_global_settings():
    global_settings_list = [
        {'title': "Objects to blur", 'name': "classes2blur", 'default': ['face', 'plate'], 'value': ['face', 'plate'],
         'type': 'BOOL', 'label': 'WTB'},
        {'title': "Blur ratio", 'name': "blur_ratio", 'default': "20", 'value': "20",
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
