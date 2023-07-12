import time
import pandas as pd

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views import View

from .forms import MediaForm
from .models import Media  # , Option


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


class OptionsView(View):
    def get(self, request):
        medias_list = Media.objects.all()
        return render(self.request, 'medias/options/index.html', {'medias': medias_list})

    def post(self, request):
        time.sleep(1)  # You don't need this line. This is just to delay the process, so you can see the progress bar
        form = MediaForm(self.request.POST, self.request.FILES)
        if form.is_valid():
            media = form.save()
            data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url}
        else:
            data = {'is_valid': False}
        return JsonResponse(data)

    def get_context_data(self, **kwargs):
        context = super(OptionsView, self).get_context_data(**kwargs)
        context['options'] = ["blur faces", "blur plates", "blur people", "blur cars", "conf", "boxes", "show_labels",
                              "show_conf", "show"]
        context['value'] = [True, True, False, False, 0.0, False, False, False, True]
        return context


class ProcessView(View):
    def get(self, request):
        medias_list = Media.objects.all()
        return render(self.request, 'medias/process/index.html', {'medias': medias_list})

    def post(self, request):
        time.sleep(
            1)  # You don't need this line. This is just to delay the process so you can see the progress bar testing locally.
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
