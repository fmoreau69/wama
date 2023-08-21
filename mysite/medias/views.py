import cv2

from django.core.files.storage import FileSystemStorage
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.template import loader
from django.views import View

from .forms import MediaForm, OptionForm, GlobalSettingsForm
from .models import Media, Option
from .tasks import process_anonymization


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
        return render(self.request, 'medias/upload/index.html',
                      {'medias': medias_list, 'options': options_list, 'medias_form': medias_form,
                       'options_form': options_form})

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
            media_data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url,
                          'properties': media.properties, 'duration': media.duration_inMinSec}
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
        # if request.POST.get('process'):
        #     process_anonymization()
        medias_list = Media.objects.all()
        options_form = {}
        for line in medias_list:
            options_form[line.id] = OptionForm(instance=line)
        medias_form = MediaForm
        return render(self.request, 'medias/process/index.html',
                      {"medias": medias_list, 'medias_form': medias_form, 'options_form': options_form})

    def post(self, request):
        if request.POST.get('process'):
            process_anonymization()
        medias_form = MediaForm(self.request.POST, self.request.FILES)
        medias_list = Media.objects.all()
        context = {'medias_list': medias_list, 'medias_form': medias_form}
        if medias_form.is_valid():
            media = medias_form.save()
            data = {'is_valid': True, 'name': media.file.name, 'url': media.file.url}
        else:
            data = {'is_valid': False}
        return render(self.request, 'medias/process/index.html', context)

    def launch_process(self, request):
        if request.POST.get('process'):
            process_anonymization()
            # msg = ''
            # for media in Media.objects.all():
            #     msg = ('process launched for media :' + media)
            return redirect(request.POST.get('next'))

# class ProcessView(ListView):
#     template_name = 'medias/process/index.html'
#     queryset = Media.objects.all()
#     context_object_name = "medias"


def refresh_content(request):
    medias_list = Media.objects.all()
    template = loader.get_template('medias/upload/content.html')
    response = {'render': template.render({'medias': medias_list}, request), }
    return JsonResponse(response)


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
        {'title': "Faces", 'name': "blur_faces", 'default': 1, 'value': 1, 'type': 'BOOL', 'label': 'WTB'},
        {'title': "Plates", 'name': "blur_plates", 'default': 1, 'value': 1, 'type': 'BOOL', 'label': 'WTB'},
        {'title': "Blur ratio", 'name': "blur_ratio", 'default': "0.20", 'value': "0.20", 'type': 'FLOAT', 'label': 'HTB'},  # , 'attr_list': {{'minimum': '0'}, {'maximum': '100'}}
        {'title': "Blur size", 'name': "blur_size", 'default': "0.50", 'value': "0.50", 'type': 'FLOAT', 'label': 'HTB'},  # , 'attr_list': {{'minimum': '1'}, {'maximum': '10'}}
        {'title': "ROI enlargement", 'name': "ROI_enlargement", 'default': "0.50", 'value': "0.50", 'type': 'FLOAT', 'label': 'HTB'},  # 'attr_list': {{'minimum': '1'}, {'maximum': '10'}}},
        {'title': "Detection threshold", 'name': "detection_threshold", 'default': "0.25", 'value': "0.25", 'type': 'FLOAT', 'label': 'HTB'},  # 'attr_list': {{'minimum': '0'}, {'maximum': '1'}}},
        {'title': "Show", 'name': "show", 'default': 1, 'value': 1, 'type': 'BOOL', 'label': 'WTS'},
        {'title': "Show boxes", 'name': "show_boxes", 'default': 0, 'value': 0, 'type': 'BOOL', 'label': 'WTS'},
        {'title': "Show labels", 'name': "show_labels", 'default': 0, 'value': 0, 'type': 'BOOL', 'label': 'WTS'},
        {'title': "Show conf", 'name': "show_conf", 'default': 0, 'value': 0, 'type': 'BOOL', 'label': 'WTS'}
        ]
    for option in options_list:
        form = GlobalSettingsForm(option)
        form.save()


def upload_from_url(request):
    if request.method == 'POST' and request.FILES['myfile']:
        myfile = request.FILES['myfile']
        fs = FileSystemStorage()
        filename = fs.save(myfile.name, myfile)
        uploaded_file_url = fs.url(filename)
        return render(request, 'core/simple_upload.html', {
            'uploaded_file_url': uploaded_file_url
        })
    return render(request, 'core/simple_upload.html')
