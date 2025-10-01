from __future__ import unicode_literals
from django.db import models
from django.contrib.auth.models import User
from django.template.defaulttags import register
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver

from wama.settings import BASE_DIR
import os

# Model path
MODEL_PATH = os.path.join(BASE_DIR, "anonymizer", "models", "yolov8n.pt")

# Optional: utility for splitting templates
@register.filter(name='split')
def split(value, key):
    return value.split(key)

@register.filter
def get_value(dictionary, key):
    return dictionary.get(key)

def default_classes2blur():
    return ["face", "plate"]


class Media(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="media")
    title = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to='input_media/')
    file_ext = models.CharField(max_length=255)

    MEDIA_TYPES = [
        ('video', 'Vidéo'),
        ('image', 'Image'),
        ('audio', 'Audio'),
    ]
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPES, default='video')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    processed = models.BooleanField(default=False, verbose_name='Process status')
    show_ms = models.BooleanField(default=False, verbose_name='Show media settings')
    MSValues_customised = models.BooleanField(default=False, verbose_name='Media settings customised')

    fps = models.IntegerField(default=0)
    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)
    duration_inSec = models.FloatField(default=0.0)
    duration_inMinSec = models.CharField(max_length=255, blank=True)

    blur_progress = models.IntegerField(default=0)
    blur_ratio = models.IntegerField(default=25)
    rounded_edges = models.IntegerField(default=5)
    roi_enlargement = models.FloatField(default=1.05)
    progressive_blur = models.IntegerField(default=25)
    detection_threshold = models.FloatField(default=0.25)

    show_preview = models.BooleanField(default=True)
    show_boxes = models.BooleanField(default=True)
    show_labels = models.BooleanField(default=True)
    show_conf = models.BooleanField(default=True)

    classes2blur = models.JSONField(
        default=default_classes2blur,
        blank=True,
        verbose_name='Objects to blur',
        help_text="List of objects to blur"
    )

    def __str__(self):
        return self.title or f"Media {self.pk}"

    def get_field_value(self, field):
        return getattr(self, field, None)


class GlobalSettings(models.Model):
    title = models.CharField(max_length=255)
    name = models.CharField(max_length=255, null=True)
    last_modified = models.DateTimeField(auto_now_add=True)
    default = models.CharField(max_length=255, default="0")
    value = models.CharField(max_length=255, default="0")
    min = models.CharField(max_length=255, default="", blank=True)
    max = models.CharField(max_length=255, default="", blank=True)
    step = models.CharField(max_length=255, default="", blank=True)

    TYPE_CHOICES = [('BOOL', 'Boolean'), ('FLOAT', 'Float')]
    type = models.CharField(max_length=5, choices=TYPE_CHOICES, default="FLOAT")

    LABEL_CHOICES = [
        ('WTB', 'What to blur ?'),
        ('HTB', 'How to blur ?'),
        ('WTS', 'What to show ?'),
    ]
    label = models.CharField(max_length=255, choices=LABEL_CHOICES, default='HTB')
    attr_list = models.CharField(max_length=255, default="", blank=True)

    def __str__(self):
        return f'{self.title} ({self.value})'


class UserSettings(models.Model):
    user = models.OneToOneField(
        User,
        verbose_name=_('member'),
        on_delete=models.CASCADE,
        related_name='user_settings',
        related_query_name='user_settings'
    )

    media_added = models.BooleanField(default=False, verbose_name='Media added')
    show_gs = models.BooleanField(default=False, verbose_name='Show global settings')
    show_console = models.BooleanField(default=False, verbose_name='Show media settings')
    GSValues_customised = models.BooleanField(default=False, verbose_name='Global settings customised')

    blur_ratio = models.IntegerField(default=25)
    roi_enlargement = models.FloatField(default=1.05)
    progressive_blur = models.IntegerField(default=25)
    detection_threshold = models.FloatField(default=0.25)

    show_preview = models.BooleanField(default=True)
    show_boxes = models.BooleanField(default=True)
    show_labels = models.BooleanField(default=True)
    show_conf = models.BooleanField(default=True)

    classes2blur = models.JSONField(
        default=default_classes2blur,
        blank=True,
        verbose_name='Objects to blur',
        help_text="List of objects to blur"
    )

    def __str__(self):
        username = getattr(self.user, 'username', 'Unknown User')
        return f"UserSettings for {username}"

    def get_field_value(self, field):
        return getattr(self, field, None)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserSettings.objects.create(user=instance)
