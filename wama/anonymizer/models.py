from __future__ import unicode_literals
from django.db import models
from django.contrib.auth.models import User
from django.template.defaulttags import register
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver

from wama.settings import BASE_DIR, AI_MODELS_DIR
from wama.common.utils.media_paths import upload_to_user_input
import os

# Model path - now points to centralized AI-models directory
MODEL_PATH = os.path.join(AI_MODELS_DIR, "anonymizer", "models--ultralytics--yolo", "detect", "yolo11s.pt")

# Optional: utility for splitting templates
@register.filter(name='split')
def split(value, key):
    return value.split(key)

@register.filter
def get_value(dictionary, key):
    return dictionary.get(key)

def default_classes2blur():
    return ["face"]


class Media(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="media")
    title = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to=upload_to_user_input('anonymizer'))
    file_ext = models.CharField(max_length=255)
    media_type = models.CharField(max_length=10, choices=[('video', 'Vidéo'), ('image', 'Image'), ('audio', 'Audio'),], default='video')
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
    interpolate_detections = models.BooleanField(default=True, verbose_name='Interpolate missing detections')
    max_interpolation_frames = models.IntegerField(default=15, verbose_name='Max frames to interpolate (capped at 0.5s)')

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

    precision_level = models.IntegerField(
        default=50,
        verbose_name='Processing precision level',
        help_text='0=Quick (fast), 50=Balanced, 100=Precise (slow but accurate)'
    )

    use_segmentation = models.BooleanField(
        default=True,
        verbose_name='Use segmentation models',
        help_text='Automatically determined by precision level'
    )

    # SAM3 (Segment Anything Model 3) fields
    use_sam3 = models.BooleanField(
        default=False,
        verbose_name='Use SAM3 for segmentation',
        help_text='When True, uses SAM3 text prompt instead of YOLO classes'
    )
    sam3_prompt = models.TextField(
        blank=True,
        null=True,
        verbose_name='SAM3 Text Prompt',
        help_text='Text prompt for SAM3 segmentation (e.g., "blur all faces and license plates")'
    )

    model_to_use = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='YOLO model to use',
        help_text='Specific YOLO model for this media (empty = use global setting or auto-select)'
    )

    def __str__(self):
        return self.title or f"Media {self.pk}"

    def get_field_value(self, field):
        return getattr(self, field, None)


class GlobalSettings(models.Model):
    title = models.CharField(max_length=255)
    name = models.CharField(max_length=255, null=True)
    last_modified = models.DateTimeField(auto_now_add=True)
    default = models.JSONField(default=dict)
    value = models.JSONField(default=dict)
    type = models.CharField(max_length=5, choices=[('BOOL', 'Boolean'), ('FLOAT', 'Float')], default="FLOAT")
    label = models.CharField(max_length=255, choices=[('WTB', 'What to blur ?'), ('HTB', 'How to blur ?'), ('WTS', 'What to show ?'),], default='HTB')
    attr_list = models.JSONField(default=dict, blank=True, null=True)
    min = models.CharField(max_length=255, default="", blank=True)
    max = models.CharField(max_length=255, default="", blank=True)
    step = models.CharField(max_length=255, default="", blank=True)

    def __str__(self):
        val = self.value.get("current") if isinstance(self.value, dict) else self.value
        return f"{self.title} ({val})"


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
    interpolate_detections = models.BooleanField(default=True, verbose_name='Interpolate missing detections')
    max_interpolation_frames = models.IntegerField(default=15, verbose_name='Max frames to interpolate (capped at 0.5s)')

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

    model_to_use = models.CharField(
        max_length=255,
        default='detect/yolov8n.pt',
        help_text='YOLO model path (e.g., detect/yolo11n.pt or detect/faces/yolov9s-face-lindevs.pt)'
    )

    precision_level = models.IntegerField(
        default=50,
        verbose_name='Processing precision level',
        help_text='0=Quick (fast), 50=Balanced, 100=Precise (slow but accurate)'
    )

    use_segmentation = models.BooleanField(
        default=True,
        verbose_name='Use segmentation models',
        help_text='Automatically determined by precision level'
    )

    # SAM3 (Segment Anything Model 3) fields
    use_sam3 = models.BooleanField(
        default=False,
        verbose_name='Use SAM3 by default',
        help_text='When True, uses SAM3 text prompt instead of YOLO classes by default'
    )
    sam3_prompt = models.TextField(
        blank=True,
        null=True,
        verbose_name='Default SAM3 Text Prompt',
        help_text='Default text prompt for SAM3 segmentation'
    )
    hf_token_configured = models.BooleanField(
        default=False,
        verbose_name='HuggingFace token configured',
        help_text='Whether user has configured HuggingFace access token for SAM3'
    )

    def __str__(self):
        username = getattr(self.user, 'username', 'Unknown User')
        return f"UserSettings for {username}"

    def get_field_value(self, field):
        return getattr(self, field, None)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created and instance and instance.pk:
        UserSettings.objects.get_or_create(user=instance)
