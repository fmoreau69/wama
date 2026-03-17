from django.db import models
from django.contrib.auth.models import User

from wama.common.utils.media_paths import upload_to_user_input, upload_to_user_output


class ComposerGeneration(models.Model):
    """Single music/SFX generation job."""

    GENERATION_TYPE_CHOICES = [
        ('music', 'Musique'),
        ('sfx', 'Bruitage / SFX'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'En attente'),
        ('RUNNING', 'En cours'),
        ('SUCCESS', 'Succès'),
        ('FAILURE', 'Échec'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='composer_generations')

    # What to generate
    generation_type = models.CharField(max_length=10, choices=GENERATION_TYPE_CHOICES, default='music')
    prompt = models.TextField()
    duration = models.FloatField(default=10.0, help_text='Durée en secondes (max 30)')
    model = models.CharField(max_length=64, default='musicgen-small')

    # Optional melody reference (MusicGen Melody only)
    melody_reference = models.FileField(
        upload_to=upload_to_user_input('composer'),
        blank=True, null=True,
    )

    # Output
    audio_output = models.FileField(
        upload_to=upload_to_user_output('composer'),
        blank=True, null=True,
    )

    # Processing state
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='PENDING')
    progress = models.IntegerField(default=0)
    task_id = models.CharField(max_length=64, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

    exported_to_library = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_generation_type_display()}] {self.prompt[:40]} ({self.model})"

    @property
    def duration_display(self):
        return f"{int(self.duration)}s"

    def get_model_label(self):
        from wama.composer.utils.model_config import COMPOSER_MODELS
        return COMPOSER_MODELS.get(self.model, {}).get('description', self.model)

    @property
    def estimated_seconds(self) -> int:
        """Estimated generation time in seconds (warm GPU)."""
        from wama.composer.utils.model_config import estimate_seconds
        return estimate_seconds(self.model, self.duration)

    @property
    def estimated_display(self) -> str:
        s = self.estimated_seconds
        if s < 60:
            return f"~{s}s"
        return f"~{s // 60}min{s % 60:02d}s" if s % 60 else f"~{s // 60}min"


class ComposerBatch(models.Model):
    """Container grouping one or more ComposerGeneration jobs."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='composer_batches')
    batch_file = models.FileField(
        upload_to=upload_to_user_input('composer'),
        blank=True, null=True,
        help_text='Fichier batch importé (null pour génération individuelle)',
    )
    total = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Batch #{self.id} — {self.total} items ({self.user})"


class ComposerBatchItem(models.Model):
    """Junction between a ComposerBatch and a ComposerGeneration."""

    batch = models.ForeignKey(ComposerBatch, on_delete=models.CASCADE, related_name='items')
    generation = models.OneToOneField(
        ComposerGeneration, on_delete=models.CASCADE, related_name='batch_item'
    )
    output_filename = models.CharField(max_length=255, blank=True)
    row_index = models.IntegerField(default=0)

    class Meta:
        ordering = ['row_index']
