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

    # La LISTE des moteurs ne vit plus ici depuis la route F4b ⑤ (2026-10-07) : elle vient du
    # catalogue, par tâche (`utils/model_config.OCR_SPEC`) — l'énumération `Backend` figeait
    # trois moteurs, dont un doublon de la ligne Ollama de GLM-OCR.

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
    # Clé de CATALOGUE du moteur OCR (`reader:olmocr`, `ollama:glm-ocr:latest`) ou « auto » —
    # migration 0012 ; un identifiant d'avant est normalisé par `save`.
    backend       = models.CharField(max_length=128, default='auto')
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
    # Le modèle qui a RÉELLEMENT servi : sa clé de catalogue (2026-10-07 — la card en affiche le
    # libellé par `card_chips`), ou `fitz_direct` quand le texte natif du PDF a suffi.
    used_backend  = models.CharField(max_length=128, blank=True, default='')
    error_message = models.TextField(blank=True, default='')

    # LLM analysis — process OPTIONNEL `analyze` du pipeline (2026-10-13 ; il était « à la
    # demande », par une tâche à part que rien dans l'interface n'appelait).
    analysis      = models.TextField(blank=True, default='',
                                     help_text='Résumé/analyse LLM du texte extrait')

    # Le PIPELINE (2026-10-13, `function_specs.PIPELINE`) : les interrupteurs des deux process
    # optionnels et le modèle de langage qu'ils emploient (« auto » = le comportement d'avant).
    # `db_default` : le code en service avant le redémarrage insère sans ces colonnes (0013).
    format_markdown = models.BooleanField(default=True, db_default=True,
                                          help_text='Mise en forme Markdown du texte lu (LLM)')
    generate_analysis = models.BooleanField(default=False, db_default=False,
                                            help_text='Analyse LLM du texte lu (résumé, points clés)')
    llm_model     = models.CharField(max_length=200, blank=True, default='auto', db_default='auto',
                                     help_text="Clé de catalogue du modèle de langage, ou « auto ».")
    # Sa TEMPÉRATURE (2026-10-21, `temperature_param`) — null = celle du modèle.
    llm_temperature = models.FloatField(null=True, blank=True,
                                        help_text="Température du modèle de langage ; vide = celle du modèle.")
    # Sa GRAINE et son TOP P (2026-10-22, `seed_param` / `top_p_param`) — null = un tirage neuf,
    # celui du modèle.
    llm_seed = models.IntegerField(null=True, blank=True,
                                   help_text="Graine du modèle de langage ; vide = un tirage neuf.")
    llm_top_p = models.FloatField(null=True, blank=True,
                                  help_text="Top P du modèle de langage ; vide = celui du modèle.")

    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"ReadingItem {self.id} ({self.filename})"

    def save(self, *args, **kwargs):
        # Moteur = CLÉ DE CATALOGUE (route F4b ⑤, 2026-10-07), normalisée au point de passage de
        # tous les écrivains (volet, modales, lots, assistant, duplication) : un identifiant nu
        # (`olmocr`) est lu dans l'espace du reader, un identifiant RETIRÉ (`glm-ocr`) sous la
        # source qui sert désormais son modèle.
        from wama.common.utils.model_keys import catalog_key
        from wama.reader.utils.model_config import RETIRED_IDS
        value = (self.backend or '').strip()
        self.backend = catalog_key(RETIRED_IDS.get(value, value), 'reader')
        super().save(*args, **kwargs)

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


from wama.common.models import QueueOrderMixin, BatchMixin


class BatchReadingItem(BatchMixin, QueueOrderMixin, ScopedVisibility):
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
