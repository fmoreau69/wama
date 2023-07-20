import time

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views import View

from .forms import MediaForm, OptionForm
from .models import Media, Option


class UploadView(View):
    def get(self, request):
        medias_list = Media.objects.all()
        return render(self.request, 'medias/upload/index.html', {'medias': medias_list})

    def post(self, request):
        time.sleep(1)  # You don't need this line. This is just to delay the process, so you can see the progress bar
        form = MediaForm(self.request.POST, self.request.FILES)
        if form.is_valid():
            media = form.save()
            data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url}
        else:
            data = {'is_valid': False}
        return JsonResponse(data)

    def launch_process(self, request):
        msg = ''
        for media in Media.objects.all():
            msg = ('process launched for media :' + media)
        return redirect(request.POST.get('next')), msg


class OptionsView(View):
    def get(self, request):
        if len(Option.objects.all()) == 0:
            set_options()
        medias_list = Media.objects.all()
        option_list = Option.objects.all()
        return render(self.request, 'medias/options/index.html', {'medias': medias_list, 'options': option_list})

    def post(self, request):
        form = MediaForm(self.request.POST, self.request.FILES)
        if form.is_valid():
            media = form.save()
            data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url}
        else:
            data = {'is_valid': False}
        return JsonResponse(data)

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
        {'title': "Blur faces", 'default': 1, 'value': 1, 'type': 'BOOL'},
        {'title': "Blur plates", 'default': 1, 'value': 1, 'type': 'BOOL'},
        {'title': "Blur people", 'default': 0, 'value': 0, 'type': 'BOOL'},
        {'title': "Blur cars", 'default': 0, 'value': 0, 'type': 'BOOL'},
        {'title': "Blur size", 'default': 0, 'value': 0, 'type': 'FLOAT'},  # , 'attr_list': {{'minimum': '1'}, {'maximum': '10'}}
        {'title': "ROI enlargement", 'default': 0, 'value': 0, 'type': 'FLOAT'},  # 'attr_list': {{'minimum': '1'}, {'maximum': '10'}}},
        {'title': "Detection threshold", 'default': 0, 'value': 0, 'type': 'FLOAT'},  # 'attr_list': {{'minimum': '0'}, {'maximum': '1'}}},
        {'title': "Show", 'default': 1, 'value': 1, 'type': 'BOOL'},
        {'title': "Show boxes", 'default': 0, 'value': 0, 'type': 'BOOL'},
        {'title': "Show labels", 'default': 0, 'value': 0, 'type': 'BOOL'},
        {'title': "Show conf", 'default': 0, 'value': 0, 'type': 'BOOL'}
        ]
    for option in options_list:
        form = OptionForm(option)
        form.save()
