from django.db import models
from django.contrib.auth.models import User
from wama.common.utils.media_paths import UploadToUserPath, upload_to_user_input


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
    input_file = models.FileField(upload_to=UploadToUserPath('enhancer', 'input/media'))
    output_file = models.FileField(upload_to=UploadToUserPath('enhancer', 'output/media'), blank=True, null=True)

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

    # Source URL (used for batch imports — file not yet downloaded)
    source_url = models.CharField(max_length=2000, blank=True, default='')

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


class AudioEnhancement(models.Model):
    """
    Represents an audio speech enhancement task.
    Engines: Resemble Enhance (quality) | DeepFilterNet 3 (speed).
    """
    ENGINE_CHOICES = [
        ('resemble',      'Resemble Enhance (Recommandé — 44.1kHz)'),
        ('deepfilternet', 'DeepFilterNet 3 (Rapide — temps réel)'),
    ]
    MODE_CHOICES = [
        ('both',    'Débruitage + Amélioration (Recommandé)'),
        ('denoise', 'Débruitage seul (Rapide)'),
        ('enhance', 'Amélioration seule (Qualité)'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'En attente'),
        ('RUNNING', 'En cours'),
        ('SUCCESS', 'Terminé'),
        ('FAILURE', 'Échec'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='audio_enhancements')
    created_at = models.DateTimeField(auto_now_add=True)

    input_file = models.FileField(upload_to=UploadToUserPath('enhancer', 'input/audio'), blank=True, null=True)
    output_file = models.FileField(
        upload_to=UploadToUserPath('enhancer', 'output/audio'), blank=True, null=True
    )

    # Source URL (used for batch imports — file not yet downloaded)
    source_url = models.CharField(max_length=2000, blank=True, default='')

    file_size = models.BigIntegerField(default=0, help_text='Input file size in bytes')
    duration = models.FloatField(default=0, help_text='Duration in seconds')

    # Engine / processing settings
    engine = models.CharField(max_length=20, choices=ENGINE_CHOICES, default='resemble')
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='both')
    denoising_strength = models.FloatField(
        default=0.5, help_text='Denoising strength 0.0–1.0 (Resemble only)'
    )
    quality = models.IntegerField(
        default=64, help_text='NFE quality steps 32/64/128 (Resemble only)'
    )

    # Processing state
    task_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='PENDING')
    progress = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default='')
    processing_time = models.FloatField(default=0, help_text='Processing time in seconds')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Audio Enhancement'
        verbose_name_plural = 'Audio Enhancements'

    def __str__(self):
        return f"AudioEnhancement {self.id} ({self.user.username}) - {self.get_status_display()}"

    def get_input_filename(self):
        import os
        return os.path.basename(self.input_file.name) if self.input_file else ''

    def get_output_filename(self):
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


class BatchEnhancement(models.Model):
    """Groupe d'améliorations créé depuis un fichier batch."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='batch_enhancements')
    created_at = models.DateTimeField(auto_now_add=True)
    batch_file = models.FileField(
        upload_to=upload_to_user_input('enhancer'),
        blank=True, null=True,
    )
    total = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Batch d'améliorations"
        verbose_name_plural = "Batchs d'améliorations"
        ordering = ['-created_at']

    def __str__(self):
        return f"Batch #{self.id} — {self.user.username} ({self.total} items)"


class BatchEnhancementItem(models.Model):
    """Link between BatchEnhancement and Enhancement."""
    batch = models.ForeignKey(BatchEnhancement, on_delete=models.CASCADE, related_name='items')
    enhancement = models.OneToOneField(
        Enhancement, on_delete=models.CASCADE,
        related_name='batch_item', null=True, blank=True,
    )
    row_index = models.IntegerField(default=0)

    class Meta:
        ordering = ['row_index']


class BatchAudioEnhancement(models.Model):
    """Groupe d'améliorations audio créé depuis un fichier batch ou upload multiple."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='batch_audio_enhancements')
    created_at = models.DateTimeField(auto_now_add=True)
    batch_file = models.FileField(
        upload_to=upload_to_user_input('enhancer'),
        blank=True, null=True,
    )
    total = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Batch d'améliorations audio"
        verbose_name_plural = "Batchs d'améliorations audio"
        ordering = ['-created_at']

    def __str__(self):
        return f"Audio Batch #{self.id} — {self.user.username} ({self.total} items)"


class BatchAudioEnhancementItem(models.Model):
    """Link between BatchAudioEnhancement and AudioEnhancement."""
    batch = models.ForeignKey(BatchAudioEnhancement, on_delete=models.CASCADE, related_name='items')
    audio_enhancement = models.OneToOneField(
        AudioEnhancement, on_delete=models.CASCADE,
        related_name='batch_item', null=True, blank=True,
    )
    row_index = models.IntegerField(default=0)

    class Meta:
        ordering = ['row_index']
