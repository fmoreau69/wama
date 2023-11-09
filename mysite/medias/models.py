from __future__ import unicode_literals
from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse
from django.template.defaulttags import register
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver

from mysite.settings import BASE_DIR
from ultralytics import YOLO
import os


def get_classes_name(model_path):
    model = YOLO(model_path)
    classes = (('face', 'Faces'), ('plate', 'Plates'),)
    classes_values = model.model.names.values()
    for class_value in classes_values:
        classes = classes + ((class_value, class_value[0].upper() + class_value[1:] +
                              ('s' if not class_value.endswith('s') else '')),)
    return classes


class Media(models.Model):
    model_path = os.path.join(BASE_DIR, "anonymizer/models/yolov8n.pt")
    title = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to='input_media/')
    file_ext = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    username = models.CharField(max_length=255, default='Anonymous')
    processed = models.BooleanField(default=False, verbose_name='Process status')
    show_ms = models.BooleanField(default=False, verbose_name='Show media settings')
    MSValues_customised = models.BooleanField(default=False, verbose_name='Media settings customised')
    fps = models.IntegerField(default=0, verbose_name="Media's frames per second")
    width = models.IntegerField(default=0, verbose_name="Media's width in pixels")
    height = models.IntegerField(default=0, verbose_name="Media's height in pixels")
    duration_inSec = models.FloatField(default=0.0, verbose_name="Media's duration")
    duration_inMinSec = models.CharField(max_length=255, blank=True)
    blur_progress = models.IntegerField(default=0, verbose_name='Blur progress', help_text="Blur progress")
    blur_ratio = models.IntegerField(default=20, verbose_name='Blur ratio', help_text="")
    rounded_edges = models.IntegerField(default=5, verbose_name='Rounded edges', help_text="")
    roi_enlargement = models.FloatField(default=1.05, verbose_name='ROI enlargement', help_text="")
    detection_threshold = models.FloatField(default=0.25, verbose_name='Detection threshold', help_text="")
    show_preview = models.BooleanField(default=True, verbose_name='Show preview', help_text="Shows a blurring preview")
    show_boxes = models.BooleanField(default=True, verbose_name='Show boxes', help_text="Show boxes from detection")
    show_labels = models.BooleanField(default=True, verbose_name='Show labels', help_text="Show labels from detection")
    show_conf = models.BooleanField(default=True, verbose_name='Show conf', help_text="Show confidence from detection")
    classes2blur = models.CharField(max_length=255, default=['', 'face', 'plate'], verbose_name='Objects to blur',
                                    choices=(get_classes_name(model_path)), help_text="Choose objects you want to blur")

    def __init__(self, *args, **kwargs):
        super(Media, self).__init__(*args, **kwargs)

    def __int__(self):
        return int(self.pk)

    # def get_absolute_url(self):
    #     return reverse('medias:download_media', args=[str(self.pk)])

    def get_field_value(self, field):
        media_settings = Media.objects.get(pk=self.pk)
        setting = media_settings.get_field(field)
        return setting.value


class GlobalSettings(models.Model):
    title = models.CharField(max_length=255)
    name = models.CharField(max_length=255, null=True)
    last_modified = models.DateTimeField(auto_now_add=True)
    default = models.CharField(max_length=255, default="0", help_text="")
    value = models.CharField(max_length=255, default="0", help_text="")
    min = models.CharField(max_length=255, default="NULL", blank=True, help_text="")
    max = models.CharField(max_length=255, default="NULL", blank=True, help_text="")
    step = models.CharField(max_length=255, default="NULL", blank=True, help_text="")
    type = models.CharField(max_length=5, default="NULL", help_text="",
                            choices=(('BOOL', 'Boolean'), ('FLOAT', 'Float')))
    label = models.CharField(max_length=255, default="0", help_text="",
                             choices=(('WTB', 'What to blur ?'), ('HTB', 'How to blur ?'), ('WTS', 'What to show ?')))
    attr_list = models.CharField(max_length=255, default="NULL", blank=True, help_text="")

    def __init__(self, *args, **kwargs):
        super(GlobalSettings, self).__init__(*args, **kwargs)

    def __str__(self):
        return f'{self.title} {self.value}'


class UserSettings(models.Model):
    model_path = os.path.join(BASE_DIR, "anonymizer/models/yolov8n.pt")
    user = models.OneToOneField(User,
                                verbose_name=_('member'),
                                on_delete=models.CASCADE,
                                related_name='user_settings',
                                related_query_name='user_settings')
    media_added = models.BooleanField(default=False, verbose_name='Media added')
    show_gs = models.BooleanField(default=False, verbose_name='Show global settings')
    show_console = models.BooleanField(default=False, verbose_name='Show media settings')
    GSValues_customised = models.BooleanField(default=False, verbose_name='Global settings customised')
    blur_ratio = models.IntegerField(default=20, verbose_name='Blur ratio', help_text="")
    rounded_edges = models.IntegerField(default=5, verbose_name='Rounded edges', help_text="")
    roi_enlargement = models.FloatField(default=1.05, verbose_name='ROI enlargement', help_text="")
    detection_threshold = models.FloatField(default=0.25, verbose_name='Detection threshold', help_text="")
    show_preview = models.BooleanField(default=True, verbose_name='Show preview', help_text="Shows a blurring preview")
    show_boxes = models.BooleanField(default=True, verbose_name='Show boxes', help_text="Show boxes from detection")
    show_labels = models.BooleanField(default=True, verbose_name='Show labels', help_text="Show labels from detection")
    show_conf = models.BooleanField(default=True, verbose_name='Show conf', help_text="Show confidence from detection")
    classes2blur = models.CharField(max_length=255, default=['', 'face', 'plate'], verbose_name='Objects to blur',
                                    choices=(get_classes_name(model_path)), help_text="Choose objects you want to blur")

    def __init__(self, *args, **kwargs):
        super(UserSettings, self).__init__(*args, **kwargs)

    def __int__(self):
        return int(self.pk)

    def get_field_value(self, field):
        user_settings = UserSettings.objects.get(user_id=self.user)
        setting = user_settings.get_field(field)
        return setting.value


@register.filter
def get_value(dictionary, key):
    return dictionary.get(key)


@register.filter(name='split')
def split(value, key):
    """
    Returns the value turned into a list.
    """
    return value.split(key)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserSettings.objects.create(user=instance)
