from django.db import models
from django.contrib.auth.models import User
from wama.common.utils.media_paths import upload_to_user_input


class ReadingItem(models.Model):

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'En attente'
        RUNNING = 'RUNNING', 'En cours'
        DONE    = 'DONE',    'Terminé'
        ERROR   = 'ERROR',   'Erreur'

    class Backend(models.TextChoices):
        AUTO    = 'auto',    'Auto (meilleur disponible)'
        OLMOCR  = 'olmocr',  'olmOCR-2 7B'
        DOCTR   = 'doctr',   'docTR (CPU-friendly)'

    class Mode(models.TextChoices):
        AUTO        = 'auto',        'Auto'
        PRINTED     = 'printed',     'Imprimé / Typographié'
        HANDWRITTEN = 'handwritten', 'Manuscrit'

    class OutputFormat(models.TextChoices):
        TXT      = 'txt',      'Texte brut (.txt)'
        MARKDOWN = 'markdown', 'Markdown (.md)'

    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reading_items')
    input_file    = models.FileField(upload_to=upload_to_user_input('reader'), blank=True, null=True)
    original_filename = models.CharField(max_length=255, blank=True, default='')
    source_url    = models.CharField(max_length=2000, blank=True, default='',
                                     help_text='URL ou chemin à télécharger si input_file est vide')

    # Options
    backend       = models.CharField(max_length=16, choices=Backend.choices, default=Backend.AUTO)
    mode          = models.CharField(max_length=16, choices=Mode.choices, default=Mode.AUTO)
    output_format = models.CharField(max_length=16, choices=OutputFormat.choices, default=OutputFormat.TXT)
    language      = models.CharField(max_length=16, blank=True, default='',
                                     help_text='Code langue (fr, en…) ou vide pour auto-détection')

    # Processing state
    task_id       = models.CharField(max_length=255, blank=True, default='')
    status        = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    progress      = models.IntegerField(default=0)
    page_count    = models.IntegerField(default=0, help_text='Nombre de pages (PDF)')

    # Result
    result_text   = models.TextField(blank=True, default='')
    used_backend  = models.CharField(max_length=32, blank=True, default='')
    error_message = models.TextField(blank=True, default='')

    # LLM analysis (on-demand)
    analysis      = models.TextField(blank=True, default='',
                                     help_text='Résumé/analyse LLM du texte extrait')

    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"ReadingItem {self.id} ({self.filename})"

    @property
    def filename(self):
        if self.original_filename:
            return self.original_filename
        import os
        if self.input_file:
            return os.path.basename(self.input_file.name)
        if self.source_url:
            return self.source_url.split('/')[-1].split('\\')[-1] or self.source_url
        return ''


class BatchReadingItem(models.Model):
    """Groupe de lectures OCR créé depuis un fichier batch."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='batch_readings')
    created_at = models.DateTimeField(auto_now_add=True)
    batch_file = models.FileField(
        upload_to=upload_to_user_input('reader'),
        blank=True, null=True,
    )
    total = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Batch de lectures"
        verbose_name_plural = "Batchs de lectures"
        ordering = ['-created_at']

    def __str__(self):
        return f"Batch #{self.id} — {self.user.username} ({self.total} items)"


class BatchReadingItemLink(models.Model):
    """Lien entre BatchReadingItem et ReadingItem."""
    batch = models.ForeignKey(BatchReadingItem, on_delete=models.CASCADE, related_name='items')
    reading = models.OneToOneField(
        ReadingItem, on_delete=models.CASCADE,
        related_name='batch_item', null=True, blank=True,
    )
    row_index = models.IntegerField(default=0)

    class Meta:
        ordering = ['row_index']
