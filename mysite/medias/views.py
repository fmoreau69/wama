import os
import cv2
import subprocess as sp

from django.core.files.storage import FileSystemStorage
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.template import loader
from django.views import View
from pytube import *
from tqdm import tqdm

from .forms import MediaForm, OptionForm, GlobalSettingsForm
from .models import Media, Option
from .tasks import start_process, stop_process


class UploadView(View):
    def get(self, request):
        if len(Option.objects.all()) == 0:
            set_options()
        medias_list = Media.objects.all()
        options_list = Option.objects.all()
        options_form = {}
        for line in medias_list:
            options_form[line.id] = OptionForm(instance=line)
        medias_form = MediaForm
        context = {'medias': medias_list, 'medias_form': medias_form, 'options': options_list,
                   'options_form': options_form}
        return render(self.request, 'medias/upload/index.html', context)

    def post(self, request):
        print(self.request.POST)
        medias_form = MediaForm(self.request.POST, self.request.FILES)
        if medias_form.is_valid():
            media = medias_form.save()
            vid = cv2.VideoCapture('./media/' + media.file.name)
            media.fps = vid.get(cv2.CAP_PROP_FPS)
            media.width = vid.get(cv2.CAP_PROP_FRAME_WIDTH)
            media.height = vid.get(cv2.CAP_PROP_FRAME_HEIGHT)
            media.properties = str(int(media.width)) + 'x' + str(int(media.height)) + ' (' + str(int(media.fps)) + 'fps)'
            media.duration_inSec = vid.get(cv2.CAP_PROP_FRAME_COUNT)/media.fps
            media.duration_inMinSec = str(int(media.duration_inSec / 60)) + ':' + str(media.duration_inSec % 60)
            media.save()
            media_data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url, 'fps': media.fps,
                          'width': media.width, 'height': media.height, 'duration': media.duration_inMinSec}
        else:
            media_data = {'is_valid': False}
        # options_form = GlobalSettingsForm(self.request.POST, self.request.FILES)
        # option = options_form.save()
        # option.save()
        # option_data = {'is_valid': True, 'title': option.title, 'value': option.value}
        return JsonResponse(media_data)  # , option_data

    def update_options(self, request):
        if self.request.POST:
            val = {}
            for opt in Option.objects.all():
                if opt.name not in self.request.POST.keys():
                    val[opt.name] = 0
                else:
                    val[opt.name] = self.request.POST[opt.name]
            print(val)


class ProcessView(View):
    def get(self, request):
        medias_list = Media.objects.all()
        options_form = {}
        for line in medias_list:
            options_form[line.id] = OptionForm(instance=line)
        medias_form = MediaForm(self.request.POST, self.request.FILES)
        context = {"medias": medias_list, 'medias_form': medias_form, 'options_form': options_form}
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
        options_form = {}
        for media in medias_list:
            options_form[media.id] = OptionForm(instance=media)
        medias_form = MediaForm(self.request.POST, self.request.FILES)
        context = {'medias': medias_list, 'medias_form': medias_form, 'options_form': options_form}
        return render(self.request, 'medias/process/index.html', context)

    def display_console(self, request):
        if request.POST.get('url', 'medias:process.display_console'):
            command = "path/to/builder.pl --router " + 'hostname'
            pipe = sp.Popen(command.split(), stdout=sp.PIPE, stderr=sp.PIPE)
            console = pipe.stdout.read()
            return render(self.request, 'medias/process/index.html', {'console': console})


# class ProcessView(ListView):
#     template_name = 'medias/process/index.html'
#     queryset = Media.objects.all()
#     context_object_name = "medias"


def stop(request):
    if request.POST.get('url', 'medias:stop_process'):
        stop_process()
    medias_list = Media.objects.all()
    options_form = {}
    for line in medias_list:
        options_form[line.id] = OptionForm(instance=line)
    medias_form = MediaForm
    context = {'medias': medias_list, 'medias_form': medias_form, 'options_form': options_form}
    return render(request, 'medias/upload/index.html', context)


def refresh_content(request):
    medias_list = Media.objects.all()
    options_form = {}
    for line in medias_list:
        options_form[line.id] = OptionForm(line)
    template = loader.get_template('medias/upload/content.html')
    response = {'render': template.render({'medias': medias_list, "options_form": options_form}, request), }
    return JsonResponse(response), redirect(request.POST.get('next'))


def refresh_table(request):
    medias_list = Media.objects.all()
    options_form = {}
    for line in medias_list:
        options_form[line.id] = OptionForm(line)
    template = loader.get_template('medias/upload/media_table.html')
    response = {'render': template.render({'media': medias_list, "options_form": options_form}, request), }
    return JsonResponse(response)


def refresh_options(request):
    options_list = Option.objects.all()
    template = loader.get_template('medias/upload/global_settings.html')
    response = {'render': template.render({'options': options_list}, request), }
    return JsonResponse(response)


def clear_database(request):
    for media in Media.objects.all():
        media.file.delete()
        media.delete()
    return redirect(request.POST.get('next'))


def reset_options(request):
    for option in Option.objects.all():
        option.delete()
    set_options()
    return redirect(request.POST.get('next'))


def set_options():
    options_list = [
        {'title': "Faces", 'name': "blur_faces", 'default': True, 'value': True, 'type': 'BOOL', 'label': 'WTB'},
        {'title': "Plates", 'name': "blur_plates", 'default': True, 'value': True, 'type': 'BOOL', 'label': 'WTB'},
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
    for option in options_list:
        form = GlobalSettingsForm(option)
        form.save()


def upload_from_url(request):
    if request.method == 'POST':
        link = request.POST['link']
        video = YouTube(link)
        stream = video.streams.get_highest_resolution()
        vid = cv2.VideoCapture(stream.download())
        medias_form = MediaForm(request.POST, request.FILES)
        if medias_form.is_valid():
            media = medias_form.save()
            media.fps = int(vid.get(cv2.CAP_PROP_FPS))
            media.width = vid.get(cv2.CAP_PROP_FRAME_WIDTH)
            media.height = vid.get(cv2.CAP_PROP_FRAME_HEIGHT)
            media.duration_inSec = vid.get(cv2.CAP_PROP_FRAME_COUNT)/media.fps
            media.duration_inMinSec = str(int(media.duration_inSec / 60)) + ':' + str(media.duration_inSec % 60)
            media.save()
            media_data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url, 'fps': media.fps,
                          'width': media.width, 'height': media.height, 'duration': media.duration_inMinSec}
        else:
            media_data = {'is_valid': False}
        return JsonResponse(media_data)  # , option_data

        # myfile = request.FILES['myfile']
        # fs = FileSystemStorage()
        # filename = fs.save(myfile.name, myfile)
        # uploaded_file_url = fs.url(filename)
        # return render(request, 'core/simple_upload.html', {
        #     'uploaded_file_url': uploaded_file_url
        # })
    # return render(request, 'core/simple_upload.html')
