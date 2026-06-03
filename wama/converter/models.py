from django.db import models
from django.contrib.auth.models import User
from wama.common.utils.media_paths import UploadToUserPath


class ConversionProfile(models.Model):
    """Profil de conversion sauvegardable — reproduire des réglages entre sessions."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversion_profiles')
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    media_type = models.CharField(max_length=20)   # 'image', 'video', 'audio'
    output_format = models.CharField(max_length=20)
    options = models.JSONField(default=dict)        # format-specific options
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.output_format})"


class ConversionBatch(models.Model):
    """Groupe de conversions partageant la même nature (image/vidéo/audio/…).

    Créé soit par import multi-fichiers (1 batch par nature), soit par fichier
    batch d'URLs/chemins. Les réglages de sortie (format/qualité) sont communs
    à tous les jobs du batch — d'où le regroupement par nature.
    """
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversion_batches')
    created_at  = models.DateTimeField(auto_now_add=True)
    batch_file  = models.FileField(upload_to=UploadToUserPath('converter', 'input'),
                                   blank=True, null=True)
    media_type  = models.CharField(max_length=20, blank=True)  # nature commune
    total       = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"ConversionBatch #{self.id} — {self.media_type} ({self.total})"


class ConversionJob(models.Model):
    STATUS_CHOICES = [
        ('PENDING',  'En attente'),
        ('RUNNING',  'En cours'),
        ('DONE',     'Terminé'),
        ('ERROR',    'Erreur'),
    ]

    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversion_jobs')
    input_file    = models.FileField(upload_to=UploadToUserPath('converter', 'input'))
    input_filename = models.CharField(max_length=255)
    media_type    = models.CharField(max_length=20, blank=True)  # 'image', 'video', 'audio'

    output_file   = models.FileField(upload_to=UploadToUserPath('converter', 'output'),
                                     null=True, blank=True)
    output_format = models.CharField(max_length=20, blank=True)  # 'mp4', 'webp', …
    options       = models.JSONField(default=dict)               # resize, quality, fps, …

    # Cross-app options (applied after main conversion)
    cross_app_options = models.JSONField(default=dict)  # e.g. {"upscale": "x2", "audio_enhance": true}

    profile       = models.ForeignKey(ConversionProfile, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='jobs')

    # Regroupement batch (multi-fichiers même nature, ou fichier batch d'urls).
    # Tout job de file appartient à un batch (batch-of-1 pour un fichier seul).
    batch           = models.ForeignKey(ConversionBatch, null=True, blank=True,
                                        on_delete=models.CASCADE, related_name='items')
    batch_row_index = models.IntegerField(default=0)

    # Quick-convert (Filemanager) — ephemeral jobs never shown in the queue,
    # output written next to the source, row dismissed after delivery.
    ephemeral     = models.BooleanField(default=False)
    # MEDIA_ROOT-relative directory where the output must be written.
    # Empty → default converter/output/<user>/. Set for in-place quick convert.
    dest_dir      = models.CharField(max_length=500, blank=True)
    # Quality preset: '', 'web', 'balanced', 'max'.
    quality_preset = models.CharField(max_length=20, blank=True)

    status        = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    task_id       = models.CharField(max_length=100, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    progress      = models.IntegerField(default=0)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.input_filename} → {self.output_format} [{self.status}]"

    @property
    def output_filename(self):
        if self.output_file:
            from pathlib import Path
            return Path(self.output_file.name).name
        return ''
