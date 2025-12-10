from django.db import models
from django.contrib.auth.models import User


class Enhancement(models.Model):
    """
    Represents an image or video enhancement task.
    """
    MEDIA_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'En attente'),
        ('RUNNING', 'En cours'),
        ('SUCCESS', 'Terminé'),
        ('FAILURE', 'Échec'),
    ]

    AI_MODEL_CHOICES = [
        ('RealESR_Gx4', 'RealESR-General x4 (Rapide)'),
        ('RealESR_Animex4', 'RealESR-Anime x4 (Anime)'),
        ('BSRGANx2', 'BSRGAN x2 (Qualité)'),
        ('BSRGANx4', 'BSRGAN x4 (Qualité)'),
        ('RealESRGANx4', 'RealESRGAN x4 (Haute qualité)'),
        ('IRCNN_Mx1', 'IRCNN-M x1 (Débruitage)'),
        ('IRCNN_Lx1', 'IRCNN-L x1 (Débruitage fort)'),
    ]

    # Basic info
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enhancements')
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPE_CHOICES, default='image')
    created_at = models.DateTimeField(auto_now_add=True)

    # Input/Output files
    input_file = models.FileField(upload_to='enhancer/input/')
    output_file = models.FileField(upload_to='enhancer/output/', blank=True, null=True)

    # Media properties
    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)
    duration = models.FloatField(default=0, help_text='Duration in seconds (for videos)')
    file_size = models.BigIntegerField(default=0, help_text='File size in bytes')

    # Processing settings
    ai_model = models.CharField(
        max_length=32,
        choices=AI_MODEL_CHOICES,
        default='RealESR_Gx4',
        help_text='AI model for upscaling'
    )
    upscale_factor = models.IntegerField(
        default=4,
        help_text='Upscaling factor (2x or 4x depending on model)'
    )
    denoise = models.BooleanField(
        default=False,
        help_text='Apply denoising before upscaling'
    )
    blend_factor = models.FloatField(
        default=0.0,
        help_text='Blend with original (0=full AI, 1=original)'
    )
    tile_size = models.IntegerField(
        default=0,
        help_text='Tile size for large images (0=auto)'
    )

    # Processing state
    task_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='PENDING')
    progress = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default='')

    # Results
    output_width = models.IntegerField(default=0)
    output_height = models.IntegerField(default=0)
    output_file_size = models.BigIntegerField(default=0)
    processing_time = models.FloatField(default=0, help_text='Processing time in seconds')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Enhancement'
        verbose_name_plural = 'Enhancements'

    def __str__(self):
        return f"Enhancement {self.id} ({self.user.username}) - {self.get_status_display()}"

    def get_input_filename(self):
        """Return the input filename without path."""
        import os
        return os.path.basename(self.input_file.name) if self.input_file else ''

    def get_output_filename(self):
        """Return the output filename without path."""
        import os
        return os.path.basename(self.output_file.name) if self.output_file else ''


class UserSettings(models.Model):
    """
    User-specific settings for the Enhancer app.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='enhancer_settings',
        related_query_name='enhancer_settings'
    )

    # Default settings
    default_ai_model = models.CharField(
        max_length=32,
        choices=Enhancement.AI_MODEL_CHOICES,
        default='RealESR_Gx4'
    )
    default_denoise = models.BooleanField(default=False)
    default_blend_factor = models.FloatField(default=0.0)

    # UI preferences
    show_advanced_settings = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'User Settings'
        verbose_name_plural = 'User Settings'

    def __str__(self):
        return f"Settings for {self.user.username}"
