"""
WAMA Describer - Models
AI-powered content description and summarization
"""

from django.db import models
from wama.common.models import ProcessingTimeMixin, ScopedVisibility, ScopedManager, JOB_STATUS_CHOICES
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator
from wama.common.utils.media_paths import upload_to_user_input, upload_to_user_output

User = get_user_model()


class Description(ProcessingTimeMixin, ScopedVisibility):
    # Partage F7 : lectures via visible_to()/visible_or_404, mutations par user.
    objects = ScopedManager()

    """Model for a description/summarization task."""

    # Ingest média déclaratif commun (common/utils/source_ingest.ensure_local_input) :
    # une URL dans source_url est téléchargée vers input_file dès la création. mode 'smart' =
    # page web → `.html` gardé / média → download ; `derive` pose la nature du fichier reçu.
    WAMA_INGEST = {
        'source': 'source_url', 'target': 'input_file', 'mode': 'smart',
        'name_field': 'filename', 'size_field': 'file_size',
        'derive': 'wama.describer.workers._derive_detected_type',
    }

    #: Vocabulaire COMMUN (wama.common.models) — plus de copie par app.
    STATUS_CHOICES = JOB_STATUS_CHOICES
    CONTENT_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('document', 'Document'),
        # 'text' et 'pdf' ont fusionné dans 'document' (2026-08-30, geste taxonomie) — gardés
        # en CHOICES pour que les lignes historiques restent affichables (lecture tolérante,
        # normalisation par content_analyzer.normalize_detected_type ; pas de migration : les
        # migrations sont gitignorées, le correctif vit dans le code).
        ('text', 'Texte'),
        ('pdf', 'PDF'),
        ('auto', 'Detection auto'),
    ]

    OUTPUT_STYLE_CHOICES = [
        ('summary', 'Resume court'),
        ('detailed', 'Description detaillee'),
        ('scientific', 'Synthese scientifique'),
        ('bullet_points', 'Points cles'),
    ]

    # Le compte-rendu de réunion est un TYPE DE RÉSUMÉ depuis le 2026-10-13 (il était un style de
    # description) — comme au transcriber ; migration 0016 pour les cards posées en « meeting ».
    SUMMARY_TYPE_CHOICES = [
        ('structured', 'Résumé structuré'),
        ('meeting', 'Compte-rendu de réunion'),
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
        blank=True,
        validators=[FileExtensionValidator(
            allowed_extensions=[
                'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp',
                'mp4', 'avi', 'mov', 'mkv', 'webm',
                'mp3', 'wav', 'flac', 'ogg', 'm4a',
                'txt', 'pdf', 'docx', 'md', 'csv'
            ]
        )]
    )
    # URL source for batch import (file downloaded at task start if input_file is empty)
    source_url = models.CharField(max_length=2000, blank=True)

    # Content type (detected or specified)
    content_type = models.CharField(
        max_length=20,
        choices=CONTENT_TYPE_CHOICES,
        default='auto'
    )
    detected_type = models.CharField(max_length=20, blank=True)

    # Processing options
    output_style = models.CharField(
        max_length=20,
        choices=OUTPUT_STYLE_CHOICES,
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

    # Le MODÈLE de chaque rôle du pipeline (2026-10-13, `function_specs.PIPELINE`) — clés de
    # catalogue, ou « auto » : transcription (audio, piste son d'une vidéo), vision (image,
    # images-clés d'une vidéo), langage (rédaction, résumé, cohérence). `db_default` : le code
    # en service avant le redémarrage insère sans ces colonnes (migration 0015).
    asr_model = models.CharField(max_length=200, blank=True, default='auto', db_default='auto',
                                 help_text="Clé de catalogue du modèle de transcription, ou « auto ».")
    vision_model = models.CharField(max_length=200, blank=True, default='auto', db_default='auto',
                                    help_text="Clé de catalogue du modèle de vision, ou « auto ».")
    llm_model = models.CharField(max_length=200, blank=True, default='auto', db_default='auto',
                                 help_text="Clé de catalogue du modèle de langage, ou « auto ».")
    # La TEMPÉRATURE de chacun des deux modèles qui tirent (2026-10-21, `temperature_param`) —
    # null = celle du modèle (rien n'est envoyé, il applique celle de son éditeur).
    vision_temperature = models.FloatField(null=True, blank=True,
                                           help_text="Température du modèle de vision ; vide = celle du modèle.")
    llm_temperature = models.FloatField(null=True, blank=True,
                                        help_text="Température du modèle de langage ; vide = celle du modèle.")
    # Curseur rapide/qualité du tirage « auto » — lu au LANCEMENT (`resolve_model_choice(item=…)`
    # → `quality_intent_of`). Null = le réglage d'app de l'utilisateur, sinon équilibré (50).
    quality_intent = models.IntegerField(null=True, blank=True,
                                         help_text="Curseur rapide/qualité 0-100 du tirage auto")

    # Sorties INTERMÉDIAIRES des process, gardées sur la card : un process relancé seul (▶ de la
    # bande) reprend celles de ses amonts au lieu de les refaire.
    transcript = models.TextField(blank=True, default='', db_default='')
    frame_captions = models.JSONField(blank=True, default=list,
                                      db_default=models.Value([], output_field=models.JSONField()))

    # Optional LLM summary (generated after description if requested)
    generate_summary = models.BooleanField(default=False)
    summary_type = models.CharField(max_length=16, choices=SUMMARY_TYPE_CHOICES,
                                    default='structured', db_default='structured')
    summary = models.TextField(blank=True)

    # Optional coherence check (score + notes + LLM-proposed correction)
    verify_coherence = models.BooleanField(default=False)
    coherence_score = models.IntegerField(null=True, blank=True)
    coherence_notes = models.TextField(blank=True)
    coherence_suggestion = models.TextField(blank=True)

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

    @property
    def gear_data(self):
        """data-* du bouton ⚙ (reflet de la card dans le volet inspecteur) — brique COMMUNE
        card_gear dérivée du schéma (remplace les 5 attributs écrits à la main, 18/08)."""
        from wama.common.utils.card_gear import gear_data
        from .params import PARAMS
        return gear_data(self, PARAMS)

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
            'document': 'fa-file-alt', 'text': 'fa-file-alt',
            'pdf': 'fa-file-pdf',
        }
        return icons.get(self.detected_type or self.content_type, 'fa-file')


from wama.common.models import QueueOrderMixin, BatchMixin


class BatchDescription(BatchMixin, QueueOrderMixin, ScopedVisibility):
    # ScopedVisibility AUSSI sur le batch : la file est bâtie à partir des batchs.
    objects = ScopedManager()

    """Groupe de descriptions créé depuis un fichier batch."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='batch_descriptions')
    created_at = models.DateTimeField(auto_now_add=True)
    batch_file = models.FileField(
        upload_to=upload_to_user_input('describer'),
        blank=True, null=True,
        help_text="Fichier batch source",
    )
    total = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Batch de descriptions"
        verbose_name_plural = "Batchs de descriptions"
        ordering = ['-created_at']

    def __str__(self):
        return f"Batch #{self.id} — {self.user.username} ({self.total} items)"


class BatchDescriptionItem(models.Model):
    """Item d'un batch de descriptions."""
    batch = models.ForeignKey(BatchDescription, on_delete=models.CASCADE, related_name='items')
    description = models.OneToOneField(
        Description, on_delete=models.CASCADE,
        related_name='batch_item', null=True, blank=True,
    )
    row_index = models.IntegerField(default=0)

    class Meta:
        ordering = ['row_index']

    def __str__(self):
        return f"BatchItem #{self.id} — batch {self.batch_id}"
