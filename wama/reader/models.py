from django.db import models
from wama.common.models import (ProcessingTimeMixin, ScopedVisibility, ScopedManager,
                                JOB_STATUS_CHOICES, JOB_PENDING)
from django.contrib.auth.models import User
from wama.common.utils.media_paths import upload_to_user_input


class ReadingItem(ProcessingTimeMixin, ScopedVisibility):
    # Partage F7 : lectures via visible_to()/visible_or_404, mutations par user.
    objects = ScopedManager()


    #: Vocabulaire COMMUN (wama.common.models) — plus de copie par app.
    #: ⚠ Le reader déclarait les mêmes valeurs sous une AUTRE FORME (`models.TextChoices`).
    #: Elle avait échappé au portage des 12 autres, qui cherchait `STATUS_CHOICES = [...]` :
    #: une même information sous deux formes se retrouve à un seul endroit sur deux, et c'est
    #: celui qu'on oublie qui dérive. Un seul usage externe existait (`default=`), d'où un
    #: portage sans risque.
    STATUS_CHOICES = JOB_STATUS_CHOICES

    class Backend(models.TextChoices):
        AUTO    = 'auto',    'Auto (meilleur disponible)'
        OLMOCR  = 'olmocr',  'olmOCR-2 7B'
        DOCTR   = 'doctr',   'docTR (CPU-friendly)'
        GLM_OCR = 'glm-ocr', 'GLM-OCR 0.9B (Ollama, léger)'

    class Mode(models.TextChoices):
        AUTO        = 'auto',        'Auto'
        PRINTED     = 'printed',     'Imprimé / Typographié'
        HANDWRITTEN = 'handwritten', 'Manuscrit'

    class OutputFormat(models.TextChoices):
        TXT      = 'txt',      'Texte brut (.txt)'
        MARKDOWN = 'markdown', 'Markdown (.md)'

    # Ingest déclaratif commun (source_ingest.ensure_local_input) : résout source_url
    # → input_file local en tête de tâche (avant : source_url était persisté mais JAMAIS
    # téléchargé — items d'un batch d'URLs sans entrée, bug identifié 2026-07-25).
    WAMA_INGEST = {
        'source': 'source_url', 'target': 'input_file', 'mode': 'smart',
        'name_field': 'original_filename',
    }

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
    # max_length 16 -> 24 : `AWAITING_RESOURCES` fait 18 caracteres (Django l'a refuse net,
    # fields.E009 -- le framework a attrape ce que j'aurais pu manquer).
    status        = models.CharField(max_length=24, choices=STATUS_CHOICES, default=JOB_PENDING)
    progress      = models.IntegerField(default=0)
    page_count    = models.IntegerField(default=0, help_text='Nombre de pages (PDF)')

    # Result
    result_text   = models.TextField(blank=True, default='',
                                     help_text='Texte extrait nettoyé (natural_text si JSON)')
    raw_result    = models.TextField(blank=True, default='',
                                     help_text='Sortie brute du backend (JSON olmOCR, texte docTR…)')
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
    def gear_data(self):
        """data-* du bouton ⚙ (reflet dans le volet inspecteur) — brique COMMUNE card_gear
        dérivée du schéma (le hand-written n'émettait QUE data-language sur 4 params, 18/08)."""
        from wama.common.utils.card_gear import gear_data
        from .params import PARAMS
        return gear_data(self, PARAMS)

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


from wama.common.models import BatchMixin


class BatchReadingItem(BatchMixin, ScopedVisibility):
    # ScopedVisibility AUSSI sur le batch : la file est bâtie à partir des batchs.
    objects = ScopedManager()

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
