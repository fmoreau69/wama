"""
WAMA Avatarizer - Models
Génération de vidéos d'avatars animés synchronisés avec l'audio.
Pipeline : MuseTalk (lip sync) + CodeFormer (amélioration faciale optionnelle)
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator
from wama.common.utils.media_paths import UploadToUserPath
from wama.common.tts.constants import TTS_MODEL_CHOICES, LANGUAGE_CHOICES, VOICE_PRESET_CHOICES

User = get_user_model()


class AvatarJob(models.Model):
    """Représente une tâche de génération d'avatar animé (pipeline MuseTalk)."""

    STATUS_CHOICES = [
        ('PENDING', 'En attente'),
        ('RUNNING', 'En cours'),
        ('SUCCESS', 'Terminé'),
        ('FAILURE', 'Échec'),
    ]

    MODE_CHOICES = [
        ('pipeline', 'Pipeline (texte → TTS → avatar)'),
        ('standalone', 'Standalone (audio uploadé)'),
    ]

    AVATAR_SOURCE_CHOICES = [
        ('gallery', 'Galerie partagée'),
        ('upload', 'Image uploadée'),
    ]

    QUALITY_MODE_CHOICES = [
        ('fast', 'Rapide (MuseTalk seul)'),
        ('quality', 'Qualité (MuseTalk + CodeFormer)'),
    ]

    # Choix TTS partagés — source : wama.common.tts.constants
    TTS_MODEL_CHOICES    = TTS_MODEL_CHOICES
    LANGUAGE_CHOICES     = LANGUAGE_CHOICES
    VOICE_PRESET_CHOICES = VOICE_PRESET_CHOICES

    # Informations de base
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='avatar_jobs')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Workflow
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='pipeline')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    progress = models.IntegerField(default=0)
    task_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)

    # Pipeline : inputs TTS
    text_content = models.TextField(blank=True, help_text="Texte à synthétiser (mode Pipeline)")
    tts_model = models.CharField(
        max_length=50, choices=TTS_MODEL_CHOICES, default='xtts_v2',
    )
    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='fr')
    voice_preset = models.CharField(max_length=50, choices=VOICE_PRESET_CHOICES, default='default')

    # Standalone : audio uploadé
    audio_input = models.FileField(
        upload_to=UploadToUserPath('avatarizer', 'input'),
        blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=['wav', 'mp3', 'ogg', 'flac'])],
    )

    # Image avatar
    avatar_source = models.CharField(max_length=20, choices=AVATAR_SOURCE_CHOICES, default='gallery')
    avatar_gallery_name = models.CharField(max_length=255, blank=True)
    avatar_upload = models.FileField(
        upload_to=UploadToUserPath('avatarizer', 'input'),
        blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp'])],
    )

    # Paramètres pipeline MuseTalk
    quality_mode = models.CharField(
        max_length=20, choices=QUALITY_MODE_CHOICES, default='fast',
        help_text="Rapide (MuseTalk) ou Qualité (MuseTalk + CodeFormer)"
    )
    use_enhancer = models.BooleanField(
        default=False,
        help_text="Amélioration faciale CodeFormer (mode Qualité uniquement)"
    )
    bbox_shift = models.IntegerField(
        default=0,
        help_text="Décalage détection visage (-10 à +10, 0 = auto)"
    )

    # Résultat
    output_video = models.FileField(
        upload_to=UploadToUserPath('avatarizer', 'output'),
        blank=True, null=True,
    )
    duration_seconds = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = "Job d'avatar"
        verbose_name_plural = "Jobs d'avatars"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"AvatarJob #{self.id} - {self.user.username} - {self.get_mode_display()} - {self.status}"

    @property
    def video_filename(self):
        if self.output_video:
            return self.output_video.name.split('/')[-1]
        return "N/A"
