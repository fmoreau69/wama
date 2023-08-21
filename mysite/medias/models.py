from __future__ import unicode_literals
from django.db import models

from YOLOv8.ultralytics import YOLO
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
    model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "./YOLOv8/models/yolov8n.pt")
    title = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to='input_media/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    properties = models.CharField(max_length=255, blank=True)
    duration_inSec = models.CharField(max_length=255, blank=True)
    duration_inMinSec = models.CharField(max_length=255, blank=True)
    blur_progress = models.IntegerField(default=0, verbose_name='Blur progress', help_text="Blur progress")
    blur_ratio = models.FloatField(default=0.20, verbose_name='Blur ratio', help_text="")
    blur_size = models.FloatField(default=0.50, verbose_name='Blur size', help_text="")
    ROI_enlargement = models.FloatField(default=0.50, verbose_name='ROI enlargement', help_text="")
    Detection_threshold = models.FloatField(default=0.25, verbose_name='Detection threshold', help_text="")
    show = models.BooleanField(default=True, verbose_name='Show', help_text="Show visualization")
    show_boxes = models.BooleanField(default=True, verbose_name='Show boxes', help_text="Show boxes from detection")
    show_labels = models.BooleanField(default=True, verbose_name='Show labels', help_text="Show labels from detection")
    show_conf = models.BooleanField(default=True, verbose_name='Show conf', help_text="Show confidence from detection")
    classes2blur = models.CharField(max_length=14, null=True, verbose_name='Objects to blur',
                                    choices=(get_classes_name(model_path)), help_text="Choose objects you want to blur")


class Option(models.Model):
    title = models.CharField(max_length=255)
    name = models.CharField(max_length=255, null=True)
    last_modified = models.DateTimeField(auto_now_add=True)
    default = models.CharField(max_length=255, default="0", help_text="")
    value = models.CharField(max_length=255, default="0", help_text="")
    type = models.CharField(max_length=5, default="NULL", help_text="",
                            choices=(('BOOL', 'Boolean'), ('FLOAT', 'Float')))
    label = models.CharField(max_length=255, default="0", help_text="",
                             choices=(('WTB', 'What to blur ?'), ('HTB', 'How to blur ?'), ('WTS', 'What to show ?')))
    # attr_list = models.CharField(max_length=255, default="0", help_text="")

    def __init__(self, *args, **kwargs):
        super(Option, self).__init__( *args, **kwargs)

    def __str__(self):
        return f'{self.title} {self.value}'
