from __future__ import unicode_literals
from django.db import models
from django.contrib.auth.models import User
from django.template.defaulttags import register

from wama.settings import BASE_DIR, AI_MODELS_DIR
from wama.common.models import (JOB_STATUS_CHOICES, NativeOutputsMixin, ProcessingTimeMixin,
                                ScopedManager, ScopedVisibility)
from wama.common.utils.media_paths import upload_to_user_input, upload_to_user_output
import os

# Model path - now points to centralized AI-models directory
MODEL_PATH = os.path.join(AI_MODELS_DIR, "anonymizer", "models--ultralytics--yolo", "detect", "yolo11s.pt")

# Optional: utility for splitting templates
@register.filter(name='split')
def split(value, key):
    return value.split(key)

@register.filter
def get_value(dictionary, key):
    return dictionary.get(key)

def default_classes2blur():
    return ["face"]


class Media(ProcessingTimeMixin, NativeOutputsMixin, ScopedVisibility):
    # Partage F7 (PROFILES_PERMISSIONS §7.4bis) : lectures via visible_to()/visible_or_404,
    # mutations inchangées (filtrées par user) → lecture seule par construction.
    objects = ScopedManager()

    # Ingest commun (source_ingest.ensure_local_input, appelé en tête de tâche) :
    # télécharge source_url vers le FileField si le fichier n'est pas encore local.
    WAMA_INGEST = {'source': 'source_url', 'target': 'file', 'mode': 'media'}

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="media")
    title = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to=upload_to_user_input('anonymizer'))
    file_ext = models.CharField(max_length=255)
    media_type = models.CharField(max_length=10, choices=[('video', 'Vidéo'), ('image', 'Image'), ('audio', 'Audio'),], default='video')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Statut canonique WAMA (audit 2026-07-11) — remplace le booléen `processed` (hors norme
    # la plus profonde de la grille). `processed` survit en PROPERTY dérivée pour les lecteurs
    # (templates/JS) ; les écritures et les filtres SQL passent par `status`.
    #: Vocabulaire COMMUN (wama.common.models) — plus de copie par app.
    STATUS_CHOICES = JOB_STATUS_CHOICES
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    task_id = models.CharField(max_length=255, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    # La sortie floutée — un FICHIER DE LA CARD, comme dans toutes les autres apps (2026-09-27).
    # Elle était un TEXTE (chemin relatif posé au SUCCESS, 2026-07-13), et la plupart des
    # lecteurs l'ignoraient pour RECALCULER le chemin depuis le nom de l'ENTRÉE : des cards
    # dupliquées (entrée partagée) écrivaient et lisaient donc le même fichier. Devenue champ
    # fichier, elle est servie, zippée, dupliquée (vidée) et supprimée (partage jugé) par les
    # briques communes. Même colonne (varchar 500) : aucune écriture en base à la migration.
    output_file = models.FileField(upload_to=upload_to_user_output('anonymizer'), max_length=500,
                                   blank=True, default='')
    # Les DÉTECTIONS du média (document `detections`, `common/utils/detections.py`) — la sortie du
    # process « Détection », que le process « Floutage » relit (2026-10-04, décision de Fabien :
    # détection et floutage séparés). Un fichier de la card comme la sortie : servi, vidé à la
    # duplication, libéré au retrait. `db_default` : le code d'AVANT le rechargement crée des
    # médias sans connaître ce champ — sans défaut côté base, l'insertion échouerait sur NOT NULL
    # (même précaution que `target_mode`).
    detections_file = models.FileField(upload_to=upload_to_user_output('anonymizer'),
                                       max_length=500, blank=True, default='', db_default='')

    @property
    def processed(self):
        return self.status == 'SUCCESS'
    show_ms = models.BooleanField(default=False, verbose_name='Show media settings')
    # Badge « Personnalisé » de la card : réglé APRÈS la naissance. N'est plus lu par la tâche
    # depuis le 2026-09-27 (le média naît complet, sa tâche ne lit que ses colonnes).
    MSValues_customised = models.BooleanField(default=False, verbose_name='Media settings customised')

    fps = models.IntegerField(default=0)
    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)
    duration_inSec = models.FloatField(default=0.0)
    duration_inMinSec = models.CharField(max_length=255, blank=True)

    blur_progress = models.IntegerField(default=0)
    # 75 depuis le 2026-09-27 (Fabien : 25 floutait trop peu). C'est LE défaut : le schéma le
    # dérive, le volet et la naissance d'un média le lisent de là (brique `user_settings`).
    blur_ratio = models.IntegerField(default=75)
    rounded_edges = models.IntegerField(default=5)
    roi_enlargement = models.FloatField(default=1.05)
    progressive_blur = models.IntegerField(default=25)
    detection_threshold = models.FloatField(default=0.25)
    interpolate_detections = models.BooleanField(default=True, verbose_name='Interpolate missing detections')
    max_interpolation_frames = models.IntegerField(default=15, verbose_name='Max frames to interpolate')

    show_preview = models.BooleanField(default=True)
    show_boxes = models.BooleanField(default=True)
    show_labels = models.BooleanField(default=True)
    show_conf = models.BooleanField(default=True)

    classes2blur = models.JSONField(
        default=default_classes2blur,
        blank=True,
        verbose_name='Objects to blur',
        help_text="List of objects to blur"
    )

    precision_level = models.IntegerField(
        default=50,
        verbose_name='Processing precision level',
        help_text='0=Quick (fast), 50=Balanced, 100=Precise (slow but accurate)'
    )

    use_segmentation = models.BooleanField(
        default=True,
        verbose_name='Use segmentation models',
        help_text='Automatically determined by precision level'
    )

    # MODE de l'élément (`app_modes`, `mode_param` du domaine `image_video`) : COMMENT on désigne
    # ce qu'il faut flouter — une liste de classes, ou une description en texte. Remplace le
    # booléen `use_sam3` (2026-09-27), qui nommait une famille de modèles au lieu du choix.
    TARGET_MODES = [('classes', 'Classes'), ('description', 'Description')]
    # `db_default` : le code d'AVANT le rechargement crée des médias sans connaître ce champ —
    # sans défaut côté base, l'insertion échouait sur NOT NULL (même précaution que `vad_mode`).
    target_mode = models.CharField(max_length=16, choices=TARGET_MODES, default='classes',
                                   db_default='classes', verbose_name='Désignation')

    # (`use_sam3` RETIRÉ le 2026-09-27, converti en `target_mode` — REMOVAL_LEDGER R73.)
    sam3_prompt = models.TextField(
        blank=True,
        null=True,
        verbose_name='SAM3 Text Prompt',
        help_text='Text prompt for SAM3 segmentation (e.g., "blur all faces and license plates")'
    )

    model_to_use = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='YOLO model to use',
        # Identifiant du CATALOGUE sans la source (`yolo:<fichier>`, `sam3`), ou « auto » — depuis
        # le 2026-09-27 ; les chemins d'avant (`detect/…pt`) restent lisibles
        # (`utils.model_selector.model_path_for`) jusqu'à leur conversion.
        help_text='Catalogue id of the model for this media (empty or "auto" = automatic choice)'
    )

    source_url = models.CharField(
        max_length=2000,
        blank=True,
        default='',
        verbose_name='Source URL',
        help_text='URL to download from (batch import) — populated only when file is not yet downloaded'
    )

    # Format de sortie (Phase 3 élargie) :
    #   'original' = format produit par le pipeline (par défaut)
    #   'input'    = reconvertir vers le format du fichier source
    #   '<fmt>'    = format explicite (mp4, webp, …)
    output_format = models.CharField(max_length=20, default='original')
    output_quality = models.CharField(max_length=20, default='balanced')

    def __str__(self):
        return self.title or f"Media {self.pk}"

    def get_filename(self):
        return os.path.basename(self.file.name) if self.file else ''

    def get_field_value(self, field):
        return getattr(self, field, None)

    @property
    def gear_data(self):
        """data-* du bouton ⚙ — brique COMMUNE `card_gear`, dérivée du schéma (2026-08-19).

        L'anonymizer n'émettait AUCUN paramètre sur son gear (seulement `data-id`) : sa modale
        va chercher les valeurs au serveur (`settingsGetUrlTemplate`), ce qui marche pour la
        modale mais laisse le VOLET sans rien à refléter — le `cardSettings` par défaut de
        `WamaInspector.initFromSchema` lit les data-* du gear, et il n'y en avait pas. Les
        valeurs viennent des champs de modèle homonymes (schéma `derive_from_model`).
        """
        from wama.common.utils.card_gear import gear_data
        from .params import PARAMS
        return gear_data(self, PARAMS)


# `GlobalSettings` et `UserSettings` RETIRÉS le 2026-09-27 (REMOVAL_LEDGER R73) : les réglages de
# l'utilisateur vivent dans la brique commune `user_settings` (préférences transférées), leurs
# défauts dans le schéma (`params.py`, dérivé des colonnes de `Media`).


from wama.common.models import QueueOrderMixin, BatchMixin


class BatchAnonymizer(BatchMixin, QueueOrderMixin, ScopedVisibility):
    """Groupe de médias créé depuis un fichier batch (liste d'URLs/chemins).

    ScopedVisibility AUSSI sur le batch : la file est bâtie à partir des batchs
    (build_batches_list) — une card partagée sans son batch n'apparaîtrait pas.
    """
    objects = ScopedManager()

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='batch_anonymizers')
    created_at = models.DateTimeField(auto_now_add=True)
    batch_file = models.FileField(
        upload_to=upload_to_user_input('anonymizer'),
        blank=True, null=True,
    )
    total = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Batch d'anonymisation"
        verbose_name_plural = "Batchs d'anonymisation"
        ordering = ['-created_at']

    def __str__(self):
        return f"Batch #{self.id} — {self.user.username} ({self.total} items)"


class BatchAnonymizerItem(models.Model):
    """Item d'un batch d'anonymisation."""
    batch = models.ForeignKey(BatchAnonymizer, on_delete=models.CASCADE, related_name='items')
    media = models.OneToOneField(
        Media, on_delete=models.CASCADE,
        related_name='batch_item', null=True, blank=True,
    )
    row_index = models.IntegerField(default=0)

    class Meta:
        ordering = ['row_index']

    def __str__(self):
        return f"BatchAnonymizerItem #{self.id} — batch {self.batch_id}"
