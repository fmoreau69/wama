import cv2

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.template import loader
from django.views import View

from .forms import MediaForm, OptionForm
from .models import Media, Option


class UploadView(View):
    def get(self, request):
        if len(Option.objects.all()) == 0:
            set_options()
        medias_list = Media.objects.all()
        option_list = Option.objects.all()
        return render(self.request, 'medias/upload/index.html', {'medias': medias_list, 'options': option_list})

    def post(self, request):
        print(self.request.POST)
        media_form = MediaForm(self.request.POST, self.request.FILES)
        if media_form.is_valid():
            media = media_form.save()
            vid = cv2.VideoCapture('./media/' + media.file.name)
            media.fps = vid.get(cv2.CAP_PROP_FPS)
            media.width = vid.get(cv2.CAP_PROP_FRAME_WIDTH)
            media.height = vid.get(cv2.CAP_PROP_FRAME_HEIGHT)
            media.properties = str(int(media.width)) + 'x' + str(int(media.height)) + ' (' + str(int(media.fps)) + 'fps)'
            media.duration_inSec = vid.get(cv2.CAP_PROP_FRAME_COUNT)/media.fps
            media.duration_inMinSec = str(int(media.duration_inSec / 60)) + ':' + str(media.duration_inSec % 60)
            media.save()
            media_data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url,
                          'properties': media.properties, 'duration': media.duration_inMinSec}
        else:
            media_data = {'is_valid': False}
        # option_form = OptionForm(self.request.POST, self.request.FILES)
        # option = option_form.save()
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

    def launch_process(self, request):
        msg = ''
        for media in Media.objects.all():
            msg = ('process launched for media :' + media)
            # execute_from_command_line()
        return redirect(request.POST.get('next')), msg

    def launch_process_with_options(self, request):
        msg = ''
        for media in Media.objects.all():
            msg = ('process launched for media :' + media)
            # execute_from_command_line()
        return redirect(request.POST.get('next')), msg


class ProcessView(View):
    def get(self, request):
        medias_list = Media.objects.all()
        return render(self.request, 'medias/process/index.html', {'medias': medias_list})

    def post(self, request):
        form = MediaForm(self.request.POST, self.request.FILES)
        if form.is_valid():
            media = form.save()
            data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url}
        else:
            data = {'is_valid': False}
        return JsonResponse(data)


def refresh_table(request):
    medias_list = Media.objects.all()
    template = loader.get_template('medias/upload/media_table.html')
    response = {'render': template.render({'medias': medias_list}, request), }
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
        {'title': "Blur faces", 'name': "blur_faces", 'default': 1, 'value': 1, 'type': 'BOOL', 'label': 'WTB'},
        {'title': "Blur plates", 'name': "blur_plates", 'default': 1, 'value': 1, 'type': 'BOOL', 'label': 'WTB'},
        {'title': "Blur people", 'name': "blur_people", 'default': 0, 'value': 0, 'type': 'BOOL', 'label': 'WTB'},
        {'title': "Blur cars", 'name': "blur_cars", 'default': 0, 'value': 0, 'type': 'BOOL', 'label': 'WTB'},
        {'title': "Blur ratio", 'name': "blur_ratio", 'default': 0.2, 'value': 0.2, 'type': 'FLOAT', 'label': 'HTB'},  # , 'attr_list': {{'minimum': '0'}, {'maximum': '100'}}
        {'title': "Blur size", 'name': "blur_size", 'default': 0.5, 'value': 0.5, 'type': 'FLOAT', 'label': 'HTB'},  # , 'attr_list': {{'minimum': '1'}, {'maximum': '10'}}
        {'title': "ROI enlargement", 'name': "ROI_enlargement", 'default': 0.5, 'value': 0.5, 'type': 'FLOAT', 'label': 'HTB'},  # 'attr_list': {{'minimum': '1'}, {'maximum': '10'}}},
        {'title': "Detection threshold", 'name': "detection_threshold", 'default': 0.25, 'value': 0.25, 'type': 'FLOAT', 'label': 'HTB'},  # 'attr_list': {{'minimum': '0'}, {'maximum': '1'}}},
        {'title': "Show", 'name': "show", 'default': 1, 'value': 1, 'type': 'BOOL', 'label': 'WTS'},
        {'title': "Show boxes", 'name': "show_boxes", 'default': 0, 'value': 0, 'type': 'BOOL', 'label': 'WTS'},
        {'title': "Show labels", 'name': "show_labels", 'default': 0, 'value': 0, 'type': 'BOOL', 'label': 'WTS'},
        {'title': "Show conf", 'name': "show_conf", 'default': 0, 'value': 0, 'type': 'BOOL', 'label': 'WTS'}
        ]
    for option in options_list:
        form = OptionForm(option)
        form.save()
