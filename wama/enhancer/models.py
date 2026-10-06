from django.db import models
from django.contrib.auth.models import User
from wama.common.models import (JOB_STATUS_CHOICES, NativeOutputsMixin, ProcessingTimeMixin,
                                ScopedManager, ScopedVisibility)
from wama.common.utils.media_paths import UploadToUserPath, upload_to_user_input


class Enhancement(ProcessingTimeMixin, NativeOutputsMixin, ScopedVisibility):
    """
    Represents an image or video enhancement task.

    Partageable (PROFILES_PERMISSIONS §7) : privée par défaut, partage possible à l'unité, à un
    projet ou publiquement. **Lecture seule par construction** — les chemins de LECTURE (liste,
    progression, téléchargement, batchs) passent par `visible_to(user)`, tout ce qui mute reste
    sur le propriétaire. Enhancer est porté en premier car c'est l'app la plus mature de la
    grille mesurée (89,6 % au 31/07).
    """

    objects = ScopedManager()
    # Ingest URL déclaratif — consommé par la brique commune
    # common/utils/source_ingest.ensure_local_input() au démarrage de la tâche.
    WAMA_INGEST = {
        'source': 'source_url',
        'target': 'input_file',
        'mode': 'media',
    }

    MEDIA_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
    ]

    #: Vocabulaire COMMUN (wama.common.models) — plus de copie par app.
    STATUS_CHOICES = JOB_STATUS_CHOICES
    # La LISTE des modèles ne vit plus ici depuis la route F4b étape ⑤ (2026-10-06) : elle vient
    # du catalogue, par tâche (`utils/auto_model.MEDIA_SPEC`) — l'ancienne liste en dur rendait
    # inchoisissable tout agrandisseur installé depuis le model manager.

    # Basic info
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enhancements')
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPE_CHOICES, default='image')
    created_at = models.DateTimeField(auto_now_add=True)

    # Input/Output files
    input_file = models.FileField(upload_to=UploadToUserPath('enhancer', 'input/media'))
    output_file = models.FileField(upload_to=UploadToUserPath('enhancer', 'output/media'), blank=True, null=True)

    # Format de sortie (conversion inline via Converter) — 'original' = pas de conversion
    output_format = models.CharField(max_length=20, default='original')
    output_quality = models.CharField(max_length=20, default='balanced')

    # Media properties
    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)
    duration = models.FloatField(default=0, help_text='Duration in seconds (for videos)')
    file_size = models.BigIntegerField(default=0, help_text='File size in bytes')

    # Processing settings
    # Clé de CATALOGUE du modèle (`enhancer:BSRGANx4`, `huggingface:org/depot`) ou « auto ».
    # 128 : `huggingface:onnx-community/swin2SR-realworld-sr-x4-64-bsrgan-psnr-ONNX` fait 71.
    ai_model = models.CharField(
        max_length=128,
        default='auto',
        help_text="Clé de catalogue du modèle d'agrandissement, ou « auto » (tirage au lancement)"
    )
    upscale_factor = models.IntegerField(
        default=4,
        help_text="Upscaling factor (2x or 4x) — le BESOIN que « auto » filtre avant de "
                  "classer ; un modèle désigné impose le sien"
    )
    # Curseur rapide ↔ qualité (chantier C, 2026-09-21) : vide = équilibré (réglage d'app
    # de l'utilisateur, puis 50). Pèse sur le tirage « auto » parmi les upscalers.
    quality_intent = models.IntegerField(
        null=True, blank=True,
        help_text='Curseur rapide/qualité 0-100 du tirage automatique (vide = équilibré)'
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

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Enhancement'
        verbose_name_plural = 'Enhancements'

    def __str__(self):
        return f"Enhancement {self.id} ({self.user.username}) - {self.get_status_display()}"

    def save(self, *args, **kwargs):
        # Valeur de modèle = CLÉ DE CATALOGUE (route F4b ⑤, 2026-10-06 — patron de l'imager).
        # Normalisée ICI, point de passage de TOUS les écrivains (vues, modale, lots, assistant
        # `add_to_enhancer`, duplication) : un identifiant nu (`RealESR_Gx4`) est lu dans
        # l'espace de l'enhancer. `auto` et le vide restent (brique `model_keys`).
        from wama.common.utils.model_keys import catalog_key
        self.ai_model = catalog_key(self.ai_model, 'enhancer')
        super().save(*args, **kwargs)

    @property
    def gear_data(self):
        """data-* du bouton ⚙ (reflet dans le volet inspecteur) — brique COMMUNE card_gear
        dérivée du schéma MEDIA (remplace les attrs à la main, 18/08)."""
        from wama.common.utils.card_gear import gear_data
        from .params import MEDIA_PARAMS
        return gear_data(self, MEDIA_PARAMS)

    def get_input_filename(self):
        """Return the input filename without path."""
        import os
        return os.path.basename(self.input_file.name) if self.input_file else ''

    def get_output_filename(self):
        """Return the output filename without path."""
        import os
        return os.path.basename(self.output_file.name) if self.output_file else ''


class AudioEnhancement(ProcessingTimeMixin, NativeOutputsMixin, ScopedVisibility):
    """
    Represents an audio speech enhancement task.
    Engines: Resemble Enhance (quality) | DeepFilterNet 3 (speed).

    Partageable — mêmes règles que `Enhancement` (PROFILES_PERMISSIONS §7).
    """

    objects = ScopedManager()
    # Ingest URL déclaratif (brique commune, cf. Enhancement.WAMA_INGEST).
    WAMA_INGEST = {
        'source': 'source_url',
        'target': 'input_file',
        'mode': 'audio',
    }

    ENGINE_CHOICES = [
        ('auto',          'Automatique — choisi au lancement'),
        ('resemble',      'Resemble Enhance (Recommandé — 44.1kHz)'),
        ('deepfilternet', 'DeepFilterNet 3 (Rapide — temps réel)'),
    ]
    MODE_CHOICES = [
        ('both',    'Débruitage + Amélioration (Recommandé)'),
        ('denoise', 'Débruitage seul (Rapide)'),
        ('enhance', 'Amélioration seule (Qualité)'),
    ]
    #: Vocabulaire COMMUN (wama.common.models) — plus de copie par app.
    STATUS_CHOICES = JOB_STATUS_CHOICES
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='audio_enhancements')
    created_at = models.DateTimeField(auto_now_add=True)

    input_file = models.FileField(upload_to=UploadToUserPath('enhancer', 'input/audio'), blank=True, null=True)
    output_file = models.FileField(
        upload_to=UploadToUserPath('enhancer', 'output/audio'), blank=True, null=True
    )

    # Format de sortie (conversion inline via Converter) — 'original' = pas de conversion
    output_format = models.CharField(max_length=20, default='original')
    output_quality = models.CharField(max_length=20, default='balanced')

    # Source URL (used for batch imports — file not yet downloaded)
    source_url = models.CharField(max_length=2000, blank=True, default='')

    file_size = models.BigIntegerField(default=0, help_text='Input file size in bytes')
    duration = models.FloatField(default=0, help_text='Duration in seconds')

    # Engine / processing settings
    engine = models.CharField(max_length=20, choices=ENGINE_CHOICES, default='auto')
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='both')
    denoising_strength = models.FloatField(
        default=0.5, help_text='Denoising strength 0.0–1.0 (Resemble only)'
    )
    quality = models.IntegerField(
        default=64, help_text='NFE quality steps 32/64/128 (Resemble only) — quand le '
                              'moteur est « auto », le NFE se DÉCLINE du curseur'
    )
    # Curseur rapide ↔ qualité (chantier C, 2026-09-21) : arbitre « auto » entre DeepFilterNet
    # (rapide) et Resemble (qualité), et décline le NFE de Resemble quand le moteur est auto.
    quality_intent = models.IntegerField(
        null=True, blank=True,
        help_text='Curseur rapide/qualité 0-100 du tirage automatique (vide = équilibré)'
    )

    # Processing state
    task_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='PENDING')
    progress = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Audio Enhancement'
        verbose_name_plural = 'Audio Enhancements'

    def __str__(self):
        return f"AudioEnhancement {self.id} ({self.user.username}) - {self.get_status_display()}"

    @property
    def gear_data(self):
        """data-* du bouton ⚙ (reflet dans le volet inspecteur) — brique COMMUNE card_gear
        dérivée du schéma AUDIO. Mapping DÉCLARÉ (params.py:76) : le param 'strength' du
        schéma correspond au champ modèle denoising_strength."""
        from wama.common.utils.card_gear import gear_data
        from .params import AUDIO_PARAMS
        return gear_data(self, AUDIO_PARAMS, values={'strength': self.denoising_strength})

    def get_input_filename(self):
        import os
        return os.path.basename(self.input_file.name) if self.input_file else ''

    def get_output_filename(self):
        import os
        return os.path.basename(self.output_file.name) if self.output_file else ''


class UserSettings(models.Model):
    """
    ⚠ PLUS LU NI ÉCRIT depuis le 2026-09-29 : les réglages du volet de l'enhancer sont la brique
    commune (`common.utils.user_settings`, `UserAppSetting`). Cette table n'avait jamais été
    ÉCRITE (seulement `get_or_create`) — ses 7 lignes portaient les défauts du modèle, aucun
    choix. Elle reste le temps que le code en service soit rechargé (la retirer avant ferait
    échouer la page encore servie par l'ancien code) — retrait : REMOVAL_LEDGER R83.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='enhancer_settings',
        related_query_name='enhancer_settings'
    )

    # Default settings
    # `choices` retirés avec la liste (2026-10-06) : table plus lue, retrait R83.
    default_ai_model = models.CharField(max_length=32, default='auto')
    default_denoise = models.BooleanField(default=False)
    default_blend_factor = models.FloatField(default=0.0)

    # UI preferences
    show_advanced_settings = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'User Settings'
        verbose_name_plural = 'User Settings'

    def __str__(self):
        return f"Settings for {self.user.username}"


from wama.common.models import QueueOrderMixin, BatchMixin


class BatchEnhancement(BatchMixin, QueueOrderMixin, ScopedVisibility):
    """Groupe d'améliorations créé depuis un fichier batch.

    **Unité de partage de la file** (cf. `batch_common.build_batches_list`) : une card isolée
    ayant déjà son propre batch, partager ce batch revient à partager la card. Lecture seule
    pour le destinataire.
    """

    objects = ScopedManager()

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


class BatchAudioEnhancement(BatchMixin, QueueOrderMixin, ScopedVisibility):
    """Groupe d'améliorations audio créé depuis un fichier batch ou upload multiple.

    Même règle de partage que `BatchEnhancement`.
    """

    objects = ScopedManager()

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
