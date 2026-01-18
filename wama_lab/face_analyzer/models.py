"""
Django models for Face Analyzer.
"""
from django.db import models
from django.conf import settings
import uuid
import os
from pathlib import Path


def get_unique_filename(directory: str, filename: str) -> str:
    """
    Generate a unique filename, keeping the original name if possible.
    Only adds UUID suffix if a file with the same name already exists.

    Args:
        directory: Full path to the target directory
        filename: Original filename

    Returns:
        Unique filename (original or with UUID suffix)
    """
    # Ensure directory exists
    Path(directory).mkdir(parents=True, exist_ok=True)

    # Check if file already exists
    target_path = os.path.join(directory, filename)
    if not os.path.exists(target_path):
        return filename

    # File exists, add UUID suffix
    name, ext = os.path.splitext(filename)
    unique_filename = f"{name}_{uuid.uuid4().hex[:8]}{ext}"
    return unique_filename


def analysis_upload_path(instance, filename):
    """
    Generate upload path for analysis input files.
    Structure: face_analyzer/<user_id>/input/<original_filename>

    Keeps the original filename unless it already exists,
    in which case a short UUID suffix is added.
    """
    user_id = instance.user.id if instance.user else 0

    # Build the directory path
    relative_dir = os.path.join('face_analyzer', str(user_id), 'input')
    full_dir = os.path.join(settings.MEDIA_ROOT, relative_dir)

    # Get unique filename
    unique_filename = get_unique_filename(full_dir, filename)

    return os.path.join(relative_dir, unique_filename)


def result_upload_path(instance, filename):
    """
    Generate upload path for analysis output files.
    Structure: face_analyzer/<user_id>/output/<original_filename>

    Keeps the original filename unless it already exists,
    in which case a short UUID suffix is added.
    """
    user_id = instance.user.id if instance.user else 0

    # Build the directory path
    relative_dir = os.path.join('face_analyzer', str(user_id), 'output')
    full_dir = os.path.join(settings.MEDIA_ROOT, relative_dir)

    # Get unique filename
    unique_filename = get_unique_filename(full_dir, filename)

    return os.path.join(relative_dir, unique_filename)


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
