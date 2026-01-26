"""
WAMA Describer - Models
AI-powered content description and summarization
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator
from wama.common.utils.media_paths import upload_to_user_input, upload_to_user_output

User = get_user_model()


class Description(models.Model):
    """Model for a description/summarization task."""

    STATUS_CHOICES = [
        ('PENDING', 'En attente'),
        ('RUNNING', 'En cours'),
        ('SUCCESS', 'Termine'),
        ('FAILURE', 'Echec'),
    ]

    CONTENT_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('text', 'Texte'),
        ('pdf', 'PDF'),
        ('auto', 'Detection auto'),
    ]

    OUTPUT_FORMAT_CHOICES = [
        ('summary', 'Resume court'),
        ('detailed', 'Description detaillee'),
        ('scientific', 'Synthese scientifique'),
        ('bullet_points', 'Points cles'),
    ]

    LANGUAGE_CHOICES = [
        ('fr', 'Francais'),
        ('en', 'English'),
        ('auto', 'Langue source'),
    ]

    # Identity
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='descriptions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Source file
    input_file = models.FileField(
        upload_to=upload_to_user_input('describer'),
        validators=[FileExtensionValidator(
            allowed_extensions=[
                'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp',
                'mp4', 'avi', 'mov', 'mkv', 'webm',
                'mp3', 'wav', 'flac', 'ogg', 'm4a',
                'txt', 'pdf', 'docx', 'md', 'csv'
            ]
        )]
    )

    # Content type (detected or specified)
    content_type = models.CharField(
        max_length=20,
        choices=CONTENT_TYPE_CHOICES,
        default='auto'
    )
    detected_type = models.CharField(max_length=20, blank=True)

    # Processing options
    output_format = models.CharField(
        max_length=20,
        choices=OUTPUT_FORMAT_CHOICES,
        default='detailed'
    )
    output_language = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default='fr'
    )
    max_length = models.IntegerField(
        default=500,
        help_text="Maximum length of summary in words"
    )

    # Result
    result_text = models.TextField(blank=True)
    result_file = models.FileField(
        upload_to=upload_to_user_output('describer'),
        blank=True,
        null=True
    )

    # Source file metadata
    filename = models.CharField(max_length=255, blank=True)
    file_size = models.BigIntegerField(default=0)
    duration_seconds = models.FloatField(default=0.0)
    duration_display = models.CharField(max_length=20, blank=True)
    properties = models.CharField(max_length=200, blank=True)

    # Task state
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    progress = models.IntegerField(default=0)
    task_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        verbose_name = "Description"
        verbose_name_plural = "Descriptions"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Description #{self.id} - {self.filename} - {self.status}"

    @property
    def input_filename(self):
        """Return the input file name."""
        if self.input_file:
            return self.input_file.name.split('/')[-1]
        return self.filename or "N/A"

    @property
    def output_filename(self):
        """Return the output file name."""
        if self.result_file:
            return self.result_file.name.split('/')[-1]
        return "N/A"

    def format_file_size(self):
        """Format file size for display."""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"

    def get_type_icon(self):
        """Return FontAwesome icon class for content type."""
        icons = {
            'image': 'fa-image',
            'video': 'fa-video',
            'audio': 'fa-music',
            'text': 'fa-file-alt',
            'pdf': 'fa-file-pdf',
        }
        return icons.get(self.detected_type or self.content_type, 'fa-file')
