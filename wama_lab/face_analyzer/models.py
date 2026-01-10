"""
Django models for Face Analyzer.
"""
from django.db import models
from django.conf import settings
import uuid
import os


def analysis_upload_path(instance, filename):
    """Generate upload path for analysis files."""
    ext = filename.split('.')[-1]
    new_filename = f"{uuid.uuid4().hex}.{ext}"
    return os.path.join('face_analyzer', 'uploads', new_filename)


def result_upload_path(instance, filename):
    """Generate upload path for result files."""
    ext = filename.split('.')[-1]
    new_filename = f"{uuid.uuid4().hex}.{ext}"
    return os.path.join('face_analyzer', 'results', new_filename)


class AnalysisSession(models.Model):
    """A face analysis session (real-time or video processing)."""

    class AnalysisMode(models.TextChoices):
        REALTIME = 'realtime', 'Real-time (Webcam)'
        VIDEO = 'video', 'Video File'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='face_analysis_sessions'
    )

    mode = models.CharField(
        max_length=20,
        choices=AnalysisMode.choices,
        default=AnalysisMode.VIDEO
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    # Input file (for video mode)
    input_file = models.FileField(
        upload_to=analysis_upload_path,
        null=True,
        blank=True
    )

    # Output file with overlay
    output_file = models.FileField(
        upload_to=result_upload_path,
        null=True,
        blank=True
    )

    # Analysis configuration
    config = models.JSONField(default=dict)

    # Analysis results (summary)
    results_summary = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Progress
    progress = models.FloatField(default=0.0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Analysis Session'
        verbose_name_plural = 'Analysis Sessions'

    def __str__(self):
        return f"Analysis {self.id} ({self.mode})"


class AnalysisFrame(models.Model):
    """Frame-by-frame analysis results."""

    session = models.ForeignKey(
        AnalysisSession,
        on_delete=models.CASCADE,
        related_name='frames'
    )

    frame_number = models.IntegerField()
    timestamp = models.FloatField()  # Seconds

    # Detection status
    face_detected = models.BooleanField(default=False)

    # Analysis data (JSON)
    head_pose = models.JSONField(null=True, blank=True)
    rppg_data = models.JSONField(null=True, blank=True)
    eye_tracking_data = models.JSONField(null=True, blank=True)
    emotion_data = models.JSONField(null=True, blank=True)
    respiration_data = models.JSONField(null=True, blank=True)

    # Processing time
    processing_time_ms = models.FloatField(default=0.0)

    class Meta:
        ordering = ['session', 'frame_number']
        unique_together = ['session', 'frame_number']

    def __str__(self):
        return f"Frame {self.frame_number} of {self.session.id}"
