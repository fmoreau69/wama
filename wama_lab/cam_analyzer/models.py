"""
Django models for Cam Analyzer.
"""
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models


def get_unique_filename(directory: str, filename: str) -> str:
    """Generate a unique filename, adding UUID suffix only if needed."""
    Path(directory).mkdir(parents=True, exist_ok=True)
    target_path = os.path.join(directory, filename)
    if not os.path.exists(target_path):
        return filename
    name, ext = os.path.splitext(filename)
    return f"{name}_{uuid.uuid4().hex[:8]}{ext}"


def _default_analyzed_positions():
    """Default cameras analysed by YOLO when a profile doesn't specify."""
    return ['front', 'rear']


def cam_upload_path(instance, filename):
    """Upload path: cam_analyzer/<user_id>/input/<filename>"""
    user_id = instance.session.user.id if instance.session and instance.session.user else 0
    relative_dir = os.path.join('cam_analyzer', str(user_id), 'input')
    full_dir = os.path.join(settings.MEDIA_ROOT, relative_dir)
    unique_filename = get_unique_filename(full_dir, filename)
    return os.path.join(relative_dir, unique_filename)


class AnalysisProfile(models.Model):
    """Reusable analysis configuration (YOLO model, target classes, thresholds)."""

    TASK_CHOICES = [
        ('detect', 'Detection'),
        ('segment', 'Segmentation'),
    ]

    REPORT_TYPE_CHOICES = [
        ('proximity_overtaking', 'Proximité & Dépassements'),
        ('intersection_insertion', 'Insertions aux intersections'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cam_analysis_profiles'
    )
    name = models.CharField(max_length=100)
    intersections = models.JSONField(
        default=list,
        blank=True,
        help_text='List of {name, lat, lon, radius_m} dicts for intersection_insertion report',
    )
    road_model_path = models.CharField(
        max_length=500,
        blank=True,
        help_text='Optional YOLO segmentation model (.pt) for road/drivable-area detection',
    )
    report_type = models.CharField(
        max_length=30,
        choices=REPORT_TYPE_CHOICES,
        default='proximity_overtaking',
    )
    model_path = models.CharField(max_length=500)
    task_type = models.CharField(max_length=10, choices=TASK_CHOICES, default='detect')
    target_classes = models.JSONField(default=list)
    confidence = models.FloatField(default=0.25)
    iou_threshold = models.FloatField(default=0.45)
    tracker = models.CharField(max_length=50, default='botsort')
    # ── SAM3 road markings (Phase Avancée) ───────────────────────────────────
    sam3_markings_enabled = models.BooleanField(
        default=False,
        help_text='Enable SAM3 detection of road markings (stop lines, crossings) in intersection windows',
    )
    sam3_markings_prompts = models.JSONField(
        default=list,
        blank=True,
        help_text='List of {label, prompt} dicts for SAM3 road marking detection',
    )
    sam3_as_road_fallback = models.BooleanField(
        default=False,
        help_text='Use SAM3 to generate road_mask entries when road_model_path is absent',
    )
    restrict_to_intersection_windows = models.BooleanField(
        default=True,
        help_text='Skip YOLO inference outside intersection windows (intersection_insertion only)',
    )
    analyzed_positions = models.JSONField(
        default=_default_analyzed_positions,
        blank=True,
        help_text='Camera positions to run YOLO on (default: front+rear). Others are extracted as MP4 for visualisation only.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ['user', 'name']

    def __str__(self):
        return f"{self.name} ({self.task_type})"


class AnalysisSession(models.Model):
    """A multi-camera analysis session."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Brouillon'
        PENDING = 'pending', 'En attente'
        PROCESSING = 'processing', 'En cours'
        COMPLETED = 'completed', 'Terminé'
        FAILED = 'failed', 'Échec'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cam_analysis_sessions'
    )
    name = models.CharField(max_length=200, blank=True)
    profile = models.ForeignKey(
        AnalysisProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sessions'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT
    )
    source_type = models.CharField(
        max_length=10,
        default='video',
        help_text="'video' = individual camera files | 'rtmaps' = extracted from .rec",
    )
    gps_track = models.JSONField(
        default=list,
        blank=True,
        help_text='GPS telemetry: [{ts, lat, lon, speed_kmh, heading}, ...]',
    )
    intersection_windows = models.JSONField(
        default=list,
        blank=True,
        help_text='Pre-computed intersection traversals: [{name, lat, lon, radius_m, t_enter, t_exit, bearing_deg}, ...]',
    )
    config = models.JSONField(default=dict)
    results_summary = models.JSONField(default=dict, blank=True)
    progress = models.FloatField(default=0.0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Analysis Session'
        verbose_name_plural = 'Analysis Sessions'

    def __str__(self):
        return f"{self.name or 'Session'} ({self.id})"


class CameraView(models.Model):
    """A camera assigned to a position within a session."""

    class Position(models.TextChoices):
        FRONT = 'front', 'Avant'
        REAR = 'rear', 'Arrière'
        LEFT = 'left', 'Gauche'
        RIGHT = 'right', 'Droite'

    session = models.ForeignKey(
        AnalysisSession,
        on_delete=models.CASCADE,
        related_name='cameras'
    )
    position = models.CharField(max_length=10, choices=Position.choices)
    video_file = models.FileField(upload_to=cam_upload_path)
    label = models.CharField(max_length=100, blank=True)
    duration = models.FloatField(null=True, blank=True)
    fps = models.FloatField(null=True, blank=True)
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    time_offset = models.FloatField(default=0.0)

    class Meta:
        ordering = ['position']
        unique_together = ['session', 'position']

    def __str__(self):
        return f"{self.get_position_display()} - {self.label or os.path.basename(self.video_file.name)}"


class DetectionFrame(models.Model):
    """Frame-by-frame detection results (Phase 2)."""

    camera = models.ForeignKey(
        CameraView,
        on_delete=models.CASCADE,
        related_name='detections'
    )
    frame_number = models.IntegerField()
    timestamp = models.FloatField()
    detections = models.JSONField(default=list)
    processing_time_ms = models.FloatField(default=0.0)

    class Meta:
        ordering = ['camera', 'frame_number']
        unique_together = ['camera', 'frame_number']

    def __str__(self):
        return f"Frame {self.frame_number} - {self.camera}"


class TemporalSegment(models.Model):
    """Identified temporal segments (Phase 3)."""

    class SegmentType(models.TextChoices):
        CLOSE_FOLLOWING = 'close_following', 'Suivi rapproché'
        OVERTAKING = 'overtaking', 'Dépassement'
        CROSSING = 'crossing', 'Croisement'
        INTERSECTION_STOP = 'intersection_stop', 'Arrêt intersection'
        INSERTION_FRONT = 'insertion_front', 'Insertion devant navette'
        CUSTOM = 'custom', 'Personnalisé'

    session = models.ForeignKey(
        AnalysisSession,
        on_delete=models.CASCADE,
        related_name='segments'
    )
    segment_type = models.CharField(max_length=20, choices=SegmentType.choices)
    camera = models.ForeignKey(
        CameraView,
        null=True,
        on_delete=models.SET_NULL,
        related_name='segments'
    )
    start_time = models.FloatField()
    end_time = models.FloatField()
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"{self.get_segment_type_display()} [{self.start_time:.1f}s - {self.end_time:.1f}s]"
