from __future__ import unicode_literals

from django.db import models


class Media(models.Model):
    title = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to='input_media/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    duration = models.IntegerField(default="0")
    progress = models.IntegerField(default="0")


class Option(models.Model):
    title = models.CharField(max_length=255)
    last_modified = models.DateTimeField(auto_now_add=True)
    default = models.CharField(max_length=255, default="0", help_text="")
    value = models.CharField(max_length=255, default="0", help_text="")
    type = models.CharField(max_length=5, default="NULL", choices=(('BOOL', 'Boolean'), ('FLOAT', 'Float')), help_text="")
    # attr_list = models.CharField(max_length=255, default="0", help_text="")

    def __init__(self, *args, **kwargs):
        super(Option, self).__init__( *args, **kwargs)

    def __str__(self):
        return f'{self.title} {self.value}'
