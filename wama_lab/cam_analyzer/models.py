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
    """Caméras analysées par YOLO (détection d'objets) par défaut. Les 4 vues sont
    traitées → fondation du tracking 360° (trajectoires continues d'une vue à
    l'autre). NB : yolopv2/road_segmenter/SAM3 restent front-only (calibration =
    Phase C ; côtés à calibrer via marquages de voie, cf. Roadmap)."""
    return ['front', 'rear', 'left', 'right']


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
    # ── Géométrie & calibration (Phase 3b — distance homographique) ──────────
    # Voir CAM_ANALYZER_DISTANCE_DESIGN.md. Toutes les valeurs sont des a priori
    # surchargeables par l'utilisateur (idéalement mesurées, sinon normes FR /
    # constructeur). L'homographie estimée depuis les lignes absorbe intrinsèques
    # + extrinsèques : ces champs servent d'a priori, de bornes et de fallback.
    geometry_enabled = models.BooleanField(
        default=False,
        help_text="Projeter les objets sur le plan-sol via homographie (distance/vitesse "
                  "géométriques). Off ou homographie non calculable → fallback pinhole (historique).",
    )
    yolopv2_all_views = models.BooleanField(
        default=False,
        help_text="Faire tourner yolopv2 (voies/route) sur les 4 vues (pour la calibration "
                  "360° des côtés) plutôt que sur la vue avant seule. OFF par défaut = analyse "
                  "plus légère/stable (yolopv2 front-only) ; ON = ~4× plus de segmentation.",
    )
    camera_calibration = models.JSONField(
        default=dict,
        blank=True,
        help_text="Calibration par position (tous champs optionnels) : {front:{lens_type,"
                  "fx_px,fy_px,cx_px,cy_px,distortion:[...],fov_h_deg,fov_v_deg,height_m,"
                  "pitch_deg,yaw_deg,roll_deg,mount_x_m,mount_y_m,homography:[[...]]}, ...}. "
                  "Manquants → estimés en ligne depuis les lignes, sinon pinhole.",
    )
    # Références sol métriques (normes FR par défaut)
    lane_width_m = models.FloatField(
        default=3.5,
        help_text="Largeur de voie (m) : échelle latérale de l'homographie ET corridor de "
                  "filtrage des véhicules stationnés.",
    )
    dash_mark_length_m = models.FloatField(
        default=3.0, help_text="Longueur d'un trait de ligne discontinue (m, T1 FR = 3).",
    )
    dash_gap_length_m = models.FloatField(
        default=9.0, help_text="Longueur d'un interstice de ligne discontinue (m, T1 FR = 9).",
    )
    crossing_band_width_m = models.FloatField(
        default=0.5, help_text="Largeur d'une bande de passage piéton (m, FR ≈ 0.5).",
    )
    crossing_gap_width_m = models.FloatField(
        default=0.5, help_text="Largeur entre bandes de passage piéton (m, FR ≈ 0.5).",
    )
    # Dimensions de la navette ego (placement en vue de dessus) — Navya Autonom par défaut
    ego_length_m = models.FloatField(default=4.75, help_text="Longueur navette ego (m).")
    ego_width_m = models.FloatField(default=2.11, help_text="Largeur navette ego (m).")
    ego_height_m = models.FloatField(default=2.65, help_text="Hauteur navette ego (m).")
    ego_cam_to_bumper_m = models.FloatField(
        null=True, blank=True,
        help_text="Distance approx. entre le bas du champ vidéo et le pare-choc (m), pour "
                  "caler l'origine des distances en vue de dessus. Approximation tolérée.",
    )
    # Fusion inertielle (accéléromètre RTMaps) pour l'ego-pose
    use_imu = models.BooleanField(
        default=True,
        help_text="Fusionner l'accélérométrie (si dispo) avec le GPS pour lisser trajectoire "
                  "et vitesse propre. Pas de cap (aucun gyroscope dans le flux).",
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
        PAUSED = 'paused', 'En pause (annulé, données partielles)'

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
    gps_time_offset = models.FloatField(
        default=0.0,
        help_text="Décalage (secondes) à ajouter au temps VIDÉO pour retrouver le ts GPS "
                  "correspondant. Recalage manuel de la synchro GPS↔vidéo (appliqué à "
                  "l'affichage, sans ré-analyse). >0 = le GPS est en avance sur la vidéo.",
    )
    gps_time_scale = models.FloatField(
        default=1.0,
        help_text="Facteur d'échelle temps VIDÉO→temps réel : ts_gps = temps_vidéo*scale "
                  "+ offset. Corrige un fps AVI erroné (ex. AVI à 12fps mais capture réelle "
                  "12,5fps → scale≈0,96) → sinon la désync GRANDIT avec le temps. Calculé "
                  "auto depuis le .rec (video_timestamps).",
    )
    lane_width_m = models.FloatField(
        default=0.0,
        help_text="Largeur de voie (m) estimée AUTO depuis les marquages yolopv2 projetés "
                  "au sol (médiane de l'écartement latéral). 0 = non estimée (défaut UI 3,5m). "
                  "Sert de 1ère passe pour le gabarit de la vue de dessus ; slider = affinage.",
    )
    imu_track = models.JSONField(
        default=list,
        blank=True,
        help_text='Accéléromètre navette (RTMaps) : [{ts, ax, ay, az}, ...] en g. '
                  'Aucun gyroscope disponible dans le flux.',
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
    # Calibration sol PAR CAMÉRA (donc par session : les CameraView sont créées par
    # session). Remplace `AnalysisProfile.camera_calibration` (profil réutilisé entre
    # sessions → la calibration fuyait et devenait fausse au moindre décrochage caméra).
    # Format = entrée calib : {homography, source, rms_error_m, crossing:{width_m,length_m}}.
    ground_homography = models.JSONField(null=True, blank=True, default=None)

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


class AnalysisPass(models.Model):
    """
    Per-session record of every distinct processing step (extraction, YOLO,
    YOLOPv2, SAM3, lane events, distance, conflicts...). Lets the UI show
    which passes are done, missing, or stale (= profile parameter has
    changed since the pass was run), and lets the orchestrator decide what
    to re-run incrementally.

    Granularity: ONE row per (session, pass_type). Per-camera / per-class
    detail goes into output_summary JSON.
    """

    class PassType(models.TextChoices):
        EXTRACTION = 'extraction', 'Extraction RTMaps'
        INTERSECTION_WINDOWS = 'intersection_windows', "Fenêtres d'intersection"
        YOLO_DETECT = 'yolo_detect', 'Détection YOLO'
        YOLOPV2_LANES = 'yolopv2_lanes', 'Drivable + lanes (YOLOPv2)'
        SAM3_MARKINGS = 'sam3_markings', 'Marquages SAM3'
        LANE_EVENTS = 'lane_events', 'Évènements de voie'
        TEMPORAL_SEGMENTS = 'temporal_segments', 'Segments temporels'
        DISTANCE = 'distance', 'Distance / vitesse / TTC'
        GLOBAL_TRACKING = 'global_tracking', 'Tracking 360° (gids + trajectoires)'
        CONFLICTS = 'conflicts', 'Conflits'

    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        RUNNING = 'running', 'En cours'
        COMPLETED = 'completed', 'Terminé'
        FAILED = 'failed', 'Échec'
        STALE = 'stale', 'Périmé (profil modifié)'

    session = models.ForeignKey(
        AnalysisSession,
        on_delete=models.CASCADE,
        related_name='passes',
    )
    # Proposition A — Per-camera granularity for YOLO/YOLOPv2/SAM3 passes.
    # Null for session-wide passes (intersection_windows, temporal_segments,
    # conflicts, extraction) which apply to the whole session.
    camera = models.ForeignKey(
        CameraView,
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='passes',
    )
    pass_type = models.CharField(max_length=30, choices=PassType.choices)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    # Snapshot of the watched profile parameters at the moment the pass ran.
    # Used to compute STALE by comparison with the current profile.
    parameters = models.JSONField(default=dict, blank=True)
    # Free-form summary: by_camera, by_class, counts, etc.
    output_summary = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_s = models.FloatField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['session', 'pass_type', 'camera']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'pass_type', 'camera'],
                name='unique_pass_per_session_type_camera',
            ),
        ]
        indexes = [models.Index(fields=['session', 'status'])]

    def __str__(self):
        cam_str = f" [{self.camera.position}]" if self.camera_id else ""
        return f"{self.get_pass_type_display()}{cam_str} [{self.status}] — {self.session_id}"


class LaneEvent(models.Model):
    """
    Time span during which a tracked object stays in a single lane on a
    given camera. Emitted by the lane-events computer that scans
    DetectionFrames in chronological order and fires one event per
    (track_id, lane_id) span.

    intersection_window_idx links the event back to
    AnalysisSession.intersection_windows[idx] when it falls inside one
    (otherwise -1, meaning "outside any intersection").
    """

    camera = models.ForeignKey(
        CameraView,
        on_delete=models.CASCADE,
        related_name='lane_events',
    )
    track_id = models.IntegerField()
    lane_id = models.IntegerField(
        help_text='Lane index from left, computed from YOLOPv2 lane lines',
    )
    in_shuttle_lane = models.BooleanField(default=False)
    t_enter = models.FloatField()
    t_exit = models.FloatField()
    intersection_window_idx = models.IntegerField(
        default=-1,
        help_text='Index in AnalysisSession.intersection_windows, -1 if outside',
    )
    class_name = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['camera', 't_enter']
        indexes = [
            models.Index(fields=['camera', 'track_id']),
            models.Index(fields=['camera', 'in_shuttle_lane']),
        ]

    def __str__(self):
        marker = '🚌' if self.in_shuttle_lane else ''
        return (f"{marker} track {self.track_id} lane {self.lane_id} "
                f"[{self.t_enter:.1f}–{self.t_exit:.1f}s]")


class ConflictEvent(models.Model):
    """
    Phase 5 — conflit (ou risque) entre la navette et un objet tracké
    pendant une fenêtre d'intersection.

    Conflit = objet en voie navette ET (TTC < seuil OU min_distance < seuil)
    pendant la fenêtre. Le signe de delta_t_s indique :
      delta_t_s > 0  → navette passe AVANT l'objet
      delta_t_s < 0  → l'objet est passé AVANT la navette
      |delta_t_s|    → marge temporelle (plus c'est petit, plus c'est critique)
    """

    class ConflictType(models.TextChoices):
        APPROACHING_FRONT = 'approaching_front', 'Approche frontale'
        SAME_LANE_AHEAD = 'same_lane_ahead', 'Devant en voie navette'
        CROSSING = 'crossing', 'Trajectoire transverse'

    session = models.ForeignKey(
        AnalysisSession, on_delete=models.CASCADE, related_name='conflicts'
    )
    camera = models.ForeignKey(
        CameraView, on_delete=models.CASCADE, related_name='conflicts'
    )
    track_id = models.IntegerField()
    class_name = models.CharField(max_length=50, blank=True)
    intersection_window_idx = models.IntegerField(default=-1)
    conflict_type = models.CharField(
        max_length=20, choices=ConflictType.choices,
        default=ConflictType.SAME_LANE_AHEAD,
    )
    navette_passed_first = models.BooleanField(null=True, blank=True)
    delta_t_s = models.FloatField(null=True, blank=True)
    min_distance_m = models.FloatField(null=True, blank=True)
    min_ttc_s = models.FloatField(null=True, blank=True)
    t_start = models.FloatField()
    t_end = models.FloatField()
    severity = models.CharField(max_length=10, default='info',
                                 help_text='info / warn / critical')

    class Meta:
        ordering = ['session', 't_start']
        indexes = [models.Index(fields=['session', 'severity'])]

    def __str__(self):
        return (f"⚠ {self.get_conflict_type_display()} track {self.track_id} "
                f"[{self.t_start:.1f}s] {self.severity}")


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
