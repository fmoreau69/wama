from django.db import models
from django.contrib.auth.models import User


class Transcript(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transcripts')
    audio = models.FileField(upload_to='transcriber/input/')
    created_at = models.DateTimeField(auto_now_add=True)

    # Options
    preprocess_audio = models.BooleanField(default=False)

    # Processing state
    task_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=32, default='PENDING')  # PENDING/RUNNING/SUCCESS/FAILURE
    progress = models.IntegerField(default=0)
    properties = models.CharField(max_length=128, blank=True, default='')
    duration_seconds = models.FloatField(default=0)
    duration_display = models.CharField(max_length=16, blank=True, default='')

    # Result
    language = models.CharField(max_length=16, blank=True, default='')
    text = models.TextField(blank=True, default='')

    def __str__(self):
        return f"Transcript {self.id} ({self.user.username})"
