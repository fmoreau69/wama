from django.db import models
from wama.common.models import ProcessingTimeMixin, ScopedVisibility, ScopedManager, JOB_STATUS_CHOICES
from django.contrib.auth.models import User

from wama.common.utils.media_paths import upload_to_user_input, upload_to_user_output


class ComposerGeneration(ProcessingTimeMixin, ScopedVisibility):
    # Partage F7 (PROFILES_PERMISSIONS §7.4bis) : lectures via visible_to()/visible_or_404,
    # mutations inchangées (filtrées par user) → lecture seule par construction.
    objects = ScopedManager()

    """Single music/SFX generation job."""

    GENERATION_TYPE_CHOICES = [
        ('music', 'Musique'),
        ('sfx', 'Bruitage / SFX'),
    ]
    #: Vocabulaire COMMUN (wama.common.models) — plus de copie par app.
    STATUS_CHOICES = JOB_STATUS_CHOICES
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='composer_generations')

    # What to generate
    generation_type = models.CharField(max_length=10, choices=GENERATION_TYPE_CHOICES, default='music')
    prompt = models.TextField()
    duration = models.FloatField(default=10.0, help_text='Durée en secondes (10–600)')
    model = models.CharField(max_length=64, default='musicgen-small')

    # Optional melody reference (MusicGen Melody only)
    melody_reference = models.FileField(
        upload_to=upload_to_user_input('composer'),
        blank=True, null=True,
    )

    # Ingest média déclaratif commun (source_ingest.ensure_local_input, appelé en tête de
    # tâche) : URL de MÉLODIE de référence (YouTube/lien audio) → téléchargée vers
    # melody_reference AU LANCEMENT. Un fichier local déjà joint prime (ensure_local_input
    # ne télécharge que si la cible est vide).
    WAMA_INGEST = {
        'source': 'source_url',
        'target': 'melody_reference',
        'mode': 'audio',
    }
    source_url = models.CharField(max_length=1000, blank=True, default='')

    # Output
    audio_output = models.FileField(
        upload_to=upload_to_user_output('composer'),
        blank=True, null=True,
    )

    # Format de sortie (conversion inline via Converter) — 'original' = WAV natif
    output_format = models.CharField(max_length=20, default='original')
    output_quality = models.CharField(max_length=20, default='balanced')

    # Processing state
    # max_length 16 -> 24 : `AWAITING_RESOURCES` fait 18 caracteres (refus Django E009).
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='PENDING')
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
    def gear_data(self):
        """data-* du bouton ⚙ (reflet dans le volet inspecteur + préremplissage modale JS) —
        brique COMMUNE card_gear dérivée du schéma (remplace les attrs à la main, 18/08)."""
        from wama.common.utils.card_gear import gear_data
        from .params import PARAMS
        return gear_data(self, PARAMS)

    @property
    def duration_display(self):
        return f"{int(self.duration)}s"

    def get_model_label(self):
        from wama.composer.utils.model_config import COMPOSER_MODELS
        return COMPOSER_MODELS.get(self.model, {}).get('description', self.model)

    @property
    def estimated_seconds(self) -> int:
        """Temps de génération estimé (s). Apprend des runs réels (ETA seeding) ;
        l'heuristique statique sert de démarrage à froid (fallback) tant qu'aucun run
        n'est enregistré pour ce modèle sur ce matériel."""
        from wama.composer.utils.model_config import estimate_seconds
        static = estimate_seconds(self.model, self.duration)
        try:
            from wama.model_manager.services.eta_estimator import estimate
            return int(round(estimate(
                f'composer:{self.model}', size=float(self.duration or 0),
                unit='audio_sec', model_loaded=True, fallback_seconds=static)))
        except Exception:
            return static

    @property
    def estimated_display(self) -> str:
        s = self.estimated_seconds
        if s < 60:
            return f"~{s}s"
        return f"~{s // 60}min{s % 60:02d}s" if s % 60 else f"~{s // 60}min"


from wama.common.models import BatchMixin


class ComposerBatch(BatchMixin, ScopedVisibility):
    # ScopedVisibility AUSSI sur le batch : la file est bâtie à partir des batchs.
    objects = ScopedManager()

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
