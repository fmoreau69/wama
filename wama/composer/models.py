from django.db import models
from wama.common.models import (JOB_STATUS_CHOICES, NativeOutputsMixin, ProcessingTimeMixin,
                                PromptScoped, ScopedManager, ScopedVisibility)
from django.contrib.auth.models import User

from wama.common.utils.media_paths import upload_to_user_input, upload_to_user_output


# `PromptScoped` (2026-10-04, la route de l'imager) : `prompt` reste ce que l'utilisateur a tapé,
# `prompt_processed` ce qui part au modèle — enrichi à l'ingestion, éditable à deux états, annulable.
class ComposerGeneration(ProcessingTimeMixin, NativeOutputsMixin, PromptScoped, ScopedVisibility):
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
    # Défaut 3:30 (210 s), celui du schéma (`params.py`, 2026-10-03) — une chanson, pas un extrait.
    duration = models.FloatField(default=210.0, help_text='Durée en secondes (10–600)')
    # Clé de CATALOGUE du modèle, ou un « auto » de groupe (`auto:text-to-music`…) — route F4b,
    # 2026-10-01 (`utils/model_choice`). 128 : une clé de dépôt HF dépasse vite 64 caractères.
    model = models.CharField(max_length=128, default='composer:musicgen-small')
    # Curseur rapide/qualité commun (chantier C, 2026-09-20) : guide le tirage « auto-* » au
    # LANCEMENT (`resolve_model_choice(item=…)`). Null = équilibré (50).
    quality_intent = models.IntegerField(null=True, blank=True,
                                         help_text='Curseur rapide/qualité 0-100 du tirage auto')

    # Optional melody reference (MusicGen Melody only)
    melody_reference = models.FileField(
        upload_to=upload_to_user_input('composer'),
        blank=True, null=True,
    )
    # Partition de référence (2026-10-01) — ABC, MIDI ou MusicXML, suivie par un modèle qui la
    # DÉCLARE (`reference_score`, YuE2). Nommé comme son PORT : la card, l'outil `add_to_composer`
    # et le nœud du Studio parlent du même nom. Nullable : sûr pour le code en service.
    reference_score = models.FileField(
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
    # Partition ÉCRITE par le process `plan` (ROUTE §10.6, pilote P3 — 2026-10-02) : la sortie
    # d'un process intermédiaire est un fichier de la card comme un autre (retrait, rétention,
    # index des fichiers la voient par ce champ) ; la ligne d'exécution n'en garde que le
    # pointeur. Distincte de `reference_score`, que l'utilisateur FOURNIT. Nullable : sûr pour
    # le code en service.
    planned_score = models.FileField(
        upload_to=upload_to_user_output('composer'),
        blank=True, null=True,
    )
    # Partition EXTRAITE de l'audio du cover par le process `extract_score` (2026-10-03,
    # SheetSage2) : la mélodie du morceau à reprendre, que le rendu suit dans le style de la
    # consigne. Même statut que `planned_score` (une sortie de la card) ; un seul des deux process
    # a lieu pour une card. Nullable : sûr pour le code en service.
    extracted_score = models.FileField(
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

    def save(self, *args, **kwargs):
        # Valeur de modèle = CLÉ DE CATALOGUE (route F4b, 2026-10-01). Normalisée ICI, point de
        # passage de TOUS les écrivains (vues, modale, lot, assistant, duplication) — et le type
        # musique/bruitage s'en DÉRIVE (la tâche du modèle), il n'est plus posé par chaque vue.
        from wama.composer.utils.model_choice import generation_type, normalize
        self.model = normalize(self.model)
        self.generation_type = generation_type(self.model)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'model' in update_fields \
                and 'generation_type' not in update_fields:
            kwargs['update_fields'] = list(update_fields) + ['generation_type']
        super().save(*args, **kwargs)

    @property
    def gear_data(self):
        """data-* du bouton ⚙ (reflet dans le volet inspecteur + préremplissage modale JS) —
        brique COMMUNE card_gear dérivée du schéma (remplace les attrs à la main, 18/08)."""
        from wama.common.utils.card_gear import gear_data
        from .params import PARAMS
        # L'enrichi accompagne le prompt : la modale le rend à deux états (`WamaPromptEnrich`).
        return gear_data(self, PARAMS, extra={'prompt_processed': self.prompt_processed})

    @property
    def duration_display(self):
        return f"{int(self.duration)}s"

    def get_model_label(self):
        from wama.composer.utils.model_choice import label_of
        return label_of(self.model)

    @property
    def estimated_seconds(self) -> int:
        """Temps de génération estimé (s). Apprend des runs réels (ETA seeding) ;
        l'heuristique statique sert de démarrage à froid (fallback) tant qu'aucun run
        n'est enregistré pour ce modèle sur ce matériel."""
        from wama.common.utils.model_keys import model_id
        from wama.composer.utils.model_choice import normalize
        from wama.composer.utils.model_config import estimate_seconds
        key = normalize(self.model)
        static = estimate_seconds(model_id(key), self.duration)
        try:
            from wama.model_manager.services.eta_estimator import estimate
            # Clé ETA = la clé de catalogue (identique à l'ancienne `composer:<id>` pour les
            # modèles du composer : l'historique appris est conservé).
            return int(round(estimate(
                key, size=float(self.duration or 0),
                unit='audio_sec', model_loaded=True, fallback_seconds=static)))
        except Exception:
            return static

    @property
    def estimated_display(self) -> str:
        s = self.estimated_seconds
        if s < 60:
            return f"~{s}s"
        return f"~{s // 60}min{s % 60:02d}s" if s % 60 else f"~{s // 60}min"


from wama.common.models import QueueOrderMixin, BatchMixin


class ComposerBatch(BatchMixin, QueueOrderMixin, ScopedVisibility):
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
