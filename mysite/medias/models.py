from __future__ import unicode_literals

from django.db import models


class Media(models.Model):
    title = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to='input_media/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    properties = models.CharField(max_length=255, blank=True)
    duration_inSec = models.CharField(max_length=255, blank=True)
    duration_inMinSec = models.CharField(max_length=255, blank=True)
    progress = models.IntegerField(default=0)
    blur_faces = models.BooleanField(default=True, verbose_name='Blur faces', help_text="")
    blur_plates = models.BooleanField(default=True, verbose_name='Blur plates', help_text="")
    blur_people = models.BooleanField(default=True, verbose_name='Blur people', help_text="")
    blur_cars = models.BooleanField(default=True, verbose_name='Blur cars', help_text="")
    blur_ratio = models.FloatField(default=0.2, verbose_name='Blur ratio', help_text="")
    blur_size = models.FloatField(default=0.5, verbose_name='Blur size', help_text="")
    ROI_enlargement = models.FloatField(default=0.5, verbose_name='ROI enlargement', help_text="")
    Detection_threshold = models.FloatField(default=0.25, verbose_name='Detection threshold', help_text="")
    show = models.BooleanField(default=True, verbose_name='Show', help_text="")
    show_boxes = models.BooleanField(default=True, verbose_name='Show boxes', help_text="")
    show_labels = models.BooleanField(default=True, verbose_name='Show labels', help_text="")
    show_conf = models.BooleanField(default=True, verbose_name='Show conf', help_text="")


class Option(models.Model):
    title = models.CharField(max_length=255)
    name = models.CharField(max_length=255, null=True)
    last_modified = models.DateTimeField(auto_now_add=True)
    default = models.CharField(max_length=255, default="0", help_text="")
    value = models.CharField(max_length=255, default="0", help_text="")
    type = models.CharField(max_length=5, default="NULL", help_text="",
                            choices=(('BOOL', 'Boolean'), ('FLOAT', 'Float')))
    label = models.CharField(max_length=255, default="0", help_text="",
                             choices=(('WTB', 'What to blur?'), ('HTB', 'How to blur?'), ('WTS', 'What to show?')))
    # attr_list = models.CharField(max_length=255, default="0", help_text="")

    def __init__(self, *args, **kwargs):
        super(Option, self).__init__( *args, **kwargs)

    def __str__(self):
        return f'{self.title} {self.value}'
