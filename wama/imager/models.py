"""
WAMA Imager - Models
Image generation using Diffusers with multi-modal input support
"""

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from wama.common.models import (
    JOB_STATUS_CHOICES,
    BatchMixin, NativeOutputsMixin, ProcessingTimeMixin, PromptScoped, QueueOrderMixin,
    ScopedManager,
    ScopedVisibility,
)
from wama.common.utils.media_paths import UploadToUserPath


# =============================================================================
# Resolution Presets Configuration
# =============================================================================

# Image resolution presets by aspect ratio
IMAGE_RESOLUTION_PRESETS = {
    # Square (1:1)
    "512x512": {"width": 512, "height": 512, "label": "512x512 (1:1)", "ratio": "1:1"},
    "768x768": {"width": 768, "height": 768, "label": "768x768 (1:1)", "ratio": "1:1"},
    "1024x1024": {"width": 1024, "height": 1024, "label": "1024x1024 (1:1)", "ratio": "1:1"},
    "2048x2048": {"width": 2048, "height": 2048, "label": "2048x2048 (1:1) 2K", "ratio": "1:1"},

    # Landscape 16:9
    "896x512": {"width": 896, "height": 512, "label": "896x512 (16:9)", "ratio": "16:9"},
    "1344x768": {"width": 1344, "height": 768, "label": "1344x768 (16:9)", "ratio": "16:9"},
    "1920x1088": {"width": 1920, "height": 1088, "label": "1920x1088 (16:9) HD", "ratio": "16:9"},
    "2048x1152": {"width": 2048, "height": 1152, "label": "2048x1152 (16:9) 2K", "ratio": "16:9"},

    # Portrait 9:16
    "512x896": {"width": 512, "height": 896, "label": "512x896 (9:16)", "ratio": "9:16"},
    "768x1344": {"width": 768, "height": 1344, "label": "768x1344 (9:16)", "ratio": "9:16"},
    "1088x1920": {"width": 1088, "height": 1920, "label": "1088x1920 (9:16) HD", "ratio": "9:16"},
    "1152x2048": {"width": 1152, "height": 2048, "label": "1152x2048 (9:16) 2K", "ratio": "9:16"},

    # Landscape 4:3
    "680x512": {"width": 680, "height": 512, "label": "680x512 (4:3)", "ratio": "4:3"},
    "1024x768": {"width": 1024, "height": 768, "label": "1024x768 (4:3)", "ratio": "4:3"},

    # Portrait 3:4
    "512x680": {"width": 512, "height": 680, "label": "512x680 (3:4)", "ratio": "3:4"},
    "768x1024": {"width": 768, "height": 1024, "label": "768x1024 (3:4)", "ratio": "3:4"},

    # Cinematic 21:9
    "1192x512": {"width": 1192, "height": 512, "label": "1192x512 (21:9)", "ratio": "21:9"},
    "2048x880": {"width": 2048, "height": 880, "label": "2048x880 (21:9) 2K", "ratio": "21:9"},
}

# Tailles proposées PAR MODÈLE — DÉRIVÉES des capacités du catalogue (2026-09-30).
# La table `MODEL_RESOLUTION_CONFIG` qui vivait ici redéclarait, par identifiant NU, ce que les
# déclarations d'app portent (`IMAGER_MODELS['resolution']`) : un modèle installé depuis le
# model manager n'y figurait jamais et recevait 256-1024 px — Supra2-IMG, résolution FIXE de
# 256, se voyait proposer 896×512 (constat Fabien). Les bornes sont désormais des capacités
# canoniques (`native_resolution`, `min_resolution`, `max_resolution`), quelle que soit leur
# source : déclaration d'app, manifeste d'un modèle installé.

#: Bornes d'un modèle qui n'en déclare AUCUNE — celles de l'ancienne table par défaut.
DEFAULT_RESOLUTION_BOUNDS = {"min": 256, "max": 1024, "native": (512, 512)}


def _catalog_caps(model_key: str) -> dict:
    """Capacités du catalogue pour une CLÉ de catalogue (une valeur nue est lue dans l'imager)."""
    from wama.common.utils.model_keys import catalog_key
    try:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=catalog_key(model_key, 'imager')).only(
            'capabilities').first()
        return dict(row.capabilities or {}) if row else {}
    except Exception:
        return {}


def get_model_resolution_config(model_key: str) -> dict:
    """`{min_size, max_size, default, fixed}` du modèle, tirés de ses CAPACITÉS."""
    from wama.common.utils.model_capabilities import resolution_bounds
    bounds = resolution_bounds(_catalog_caps(model_key))
    lo = bounds["min"] or DEFAULT_RESOLUTION_BOUNDS["min"]
    hi = bounds["max"] or (max(bounds["native"]) if bounds["native"]
                           else DEFAULT_RESOLUTION_BOUNDS["max"])
    native = bounds["native"] or ((hi, hi) if bounds["fixed"] else DEFAULT_RESOLUTION_BOUNDS["native"])
    return {"min_size": lo, "max_size": hi, "default": f"{native[0]}x{native[1]}",
            "fixed": bounds["fixed"]}


def get_recommended_resolutions(model_key: str) -> list:
    """Préréglages de taille que le modèle accepte : la taille NATIVE d'abord, puis les
    préréglages dont le PLUS GRAND côté tient dans ses bornes. Un modèle à résolution FIXE ne
    se propose qu'à sa taille — même si aucun préréglage ne la porte (256×256)."""
    config = get_model_resolution_config(model_key)
    lo, hi, default = config["min_size"], config["max_size"], config["default"]
    w, _, h = default.partition("x")
    native = {"key": default, "width": int(w), "height": int(h),
              "label": f"{w}x{h} (natif)", "ratio": ""}
    if config["fixed"]:
        return [native]
    presets = [{"key": key, **p} for key, p in IMAGE_RESOLUTION_PRESETS.items()
               if lo <= max(p["width"], p["height"]) <= hi]
    rest = [p for p in presets if p["key"] != default]
    first = next((p for p in presets if p["key"] == default), native)
    return [first] + rest


class ImageGeneration(ProcessingTimeMixin, NativeOutputsMixin, PromptScoped, ScopedVisibility):
    """Model for an image generation task.

    `ScopedVisibility` (brique COMMUNE) : la card est privée par défaut et peut être partagée à
    l'unité, à un projet ou publiquement — cf. PROFILES_PERMISSIONS §7. Le partage est en
    **lecture seule par construction** : les vues de liste filtrent par `visible_to(user)`, les
    vues mutantes gardent `owned_by(user)`. Aucune vue ne peut donc accorder l'écriture par
    inadvertance avant que `ObjectGrant` (§7.3) n'existe.
    """

    objects = ScopedManager()

    #: Vocabulaire COMMUN (wama.common.models) — plus de copie par app.
    STATUS_CHOICES = JOB_STATUS_CHOICES
    GENERATION_MODE_CHOICES = [
        ('txt2img', 'Text to Image'),
        ('file2img', 'File to Image (batch)'),
        ('describe2img', 'Describe to Image'),
        ('style2img', 'Style Transfer'),
        ('img2img', 'Image to Image'),
        ('txt2vid', 'Text to Video'),
        ('img2vid', 'Image to Video'),
    ]

    OUTPUT_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
    ]

    VIDEO_RESOLUTION_CHOICES = [
        ('480p', '480p (832x480) 16:9'),
        ('720p', '720p (1280x720) 16:9'),
    ]

    # `related_name` EXPLICITE (2026-09-05) — la seule FK utilisateur du parc qui n'en avait
    # pas. Sans lui, l'accesseur inverse par défaut est `User.imagegeneration_set`, dérivé du
    # seul nom de MODÈLE : une app-jumelle du bac à sable (`imager_01`, même modèle, autre
    # app_label) revendiquait donc le MÊME accesseur → `fields.E304` et `manage.py check` en
    # erreur, c'est-à-dire un boot Django cassé par la simple existence de la jumelle. Imager
    # étant l'app aux 3 ports, c'était la seule intestable en bac à sable, et précisément la
    # seule à pouvoir démontrer deux slots FICHIER côte à côte (CARD_DESIGN §11.11).
    # Zéro consommateur de `imagegeneration_set` dans le dépôt (grep exhaustif) : le
    # renommage n'a aucun appelant à suivre, et la migration ne touche pas le schéma SQL.
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='image_generations')

    # Generation mode
    generation_mode = models.CharField(
        max_length=20,
        choices=GENERATION_MODE_CHOICES,
        default='txt2img',
        help_text="Type of generation"
    )

    # Input parameters
    prompt = models.TextField(help_text="Description of the image to generate")
    negative_prompt = models.TextField(blank=True, default="", help_text="What to avoid in the image")

    # Les champs `prompt_processed` / `prompt_trace` / `prompt_keywords` viennent du mixin
    # COMMUN `PromptScoped` (ils étaient retapés ici le 30/07 — remplacé, pas juxtaposé).

    # Prompt file for batch processing (file2img mode)
    prompt_file = models.FileField(
        upload_to=UploadToUserPath('imager', 'input/prompts'),
        null=True,
        blank=True,
        validators=[FileExtensionValidator(['txt', 'json', 'yaml', 'yml'])],
        help_text="Text file containing prompts for batch generation"
    )

    # Reference image for img2img/style/describe modes
    reference_image = models.ImageField(
        upload_to=UploadToUserPath('imager', 'input/references'),
        null=True,
        blank=True,
        help_text="Reference image for img2img, style transfer, or auto-describe"
    )

    # Ingest média déclaratif commun (source_ingest.ensure_local_input, appelé en tête de
    # tâche — contrat composer 307b9fb) : URL d'IMAGE de référence → téléchargée vers
    # reference_image AU LANCEMENT. Un fichier local déjà joint prime (ensure_local_input
    # ne télécharge que si la cible est vide).
    WAMA_INGEST = {
        'source': 'source_url',
        'target': 'reference_image',
        'mode': 'media',
    }
    source_url = models.CharField(max_length=1000, blank=True, default='')

    # Image influence strength (for img2img/style modes)
    image_strength = models.FloatField(
        default=0.75,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Influence of reference image (0=ignore, 1=copy)"
    )

    # Auto-generated prompt (for describe2img mode)
    auto_prompt = models.TextField(
        blank=True,
        default="",
        help_text="Prompt automatically generated from reference image"
    )

    # `parent_generation` (self-FK) RETIRÉ le 2026-08-07 : il portait le regroupement en batch
    # avant `GenerationBatch` (`9922f65`), qui l'a doublé sans le remplacer. Le batch commun est
    # l'unité de FILE **et de PARTAGE** — ce que le self-FK ne permettait pas. 0 ligne l'utilisait
    # en base au moment du retrait (mesuré), la migration est donc sans perte.

    # Model and size settings
    # CLÉ DE CATALOGUE entière depuis le 2026-09-29 (route F4b) : `imager:hunyuan-image-2.1`,
    # `huggingface:org/nom` — la valeur même que sert le select. `auto` = tirage au lancement.
    # L'identifiant nu d'avant se lit encore (`common/utils/model_keys`), jamais ne s'écrit.
    # Défaut `auto` : l'ancien `stable-diffusion-v1-5` en dur remontait au schéma des deux selects.
    model = models.CharField(max_length=100, default="auto",
                             help_text="Clé de catalogue du modèle, ou « auto » (tirage au lancement)")
    width = models.IntegerField(default=512, validators=[MinValueValidator(64), MaxValueValidator(2048)])
    height = models.IntegerField(default=512, validators=[MinValueValidator(64), MaxValueValidator(2048)])

    # Generation parameters
    steps = models.IntegerField(default=30, validators=[MinValueValidator(1), MaxValueValidator(100)],
                                help_text="Number of diffusion steps")
    guidance_scale = models.FloatField(default=7.5, validators=[MinValueValidator(1.0), MaxValueValidator(20.0)],
                                       help_text="How closely to follow the prompt")
    seed = models.IntegerField(null=True, blank=True, help_text="Random seed for reproducibility")
    num_images = models.IntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(4)],
                                     help_text="Number of images to generate")
    # Curseur rapide/qualité commun (chantier C, 2026-09-20) : guide le tirage « auto » au
    # LANCEMENT (`resolve_model_choice(item=…)` → `quality_intent_of`). Null = équilibré (50).
    quality_intent = models.IntegerField(null=True, blank=True,
                                         help_text="Curseur rapide/qualité 0-100 du tirage auto")

    # Output type (image or video)
    output_type = models.CharField(
        max_length=10,
        choices=OUTPUT_TYPE_CHOICES,
        default='image',
        help_text="Type of output (image or video)"
    )

    # Video-specific settings
    video_duration = models.FloatField(
        default=5.0,
        validators=[MinValueValidator(1.0), MaxValueValidator(15.0)],
        help_text="Video duration in seconds (1-15)"
    )
    video_fps = models.IntegerField(
        default=16,
        validators=[MinValueValidator(8), MaxValueValidator(30)],
        help_text="Video frames per second"
    )
    video_frames = models.IntegerField(
        default=81,
        help_text="Number of video frames (calculated as 4k+1)"
    )
    video_resolution = models.CharField(
        max_length=10,
        choices=VIDEO_RESOLUTION_CHOICES,
        default='480p',
        help_text="Video resolution preset"
    )

    # Output
    generated_images = models.JSONField(default=list, blank=True, help_text="List of generated image paths")

    # Video output
    output_video = models.FileField(
        upload_to=UploadToUserPath('imager', 'output/video'),
        null=True,
        blank=True,
        help_text="Generated video file"
    )

    # Format de sortie (conversion inline via Converter) — 'original' = PNG/MP4 natif
    output_format = models.CharField(max_length=20, default='original')
    output_quality = models.CharField(max_length=20, default='balanced')
    # Agrandissement de sortie ('' / 'x2' / 'x4'), post-traitement COMMUN appliqué après tout
    # backend (`output_formats.apply_output_settings`). Remplace le booléen `upscale` (2026-09-30),
    # que seul le backend diffusers générique appliquait — les backends dédiés l'ignoraient.
    output_upscale = models.CharField(max_length=8, blank=True, default='',
                                      help_text="Agrandissement de la sortie : '', 'x2' ou 'x4'")

    # Status and progress
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    progress = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    error_message = models.TextField(blank=True, default="")
    task_id = models.CharField(max_length=255, blank=True, default="")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Image #{self.id} - {self.prompt[:50]}"

    @property
    def duration_display(self):
        """Durée de traitement — ALIAS de `processing_display` (ProcessingTimeMixin).

        L'implémentation maison calculait `completed_at - created_at`, c.-à-d. le temps écoulé
        depuis la CRÉATION, file d'attente comprise : une génération en attente 20 min puis
        calculée en 2 min affichait 22 min. Le mixin persiste la durée RÉELLE, celle que le
        worker mesure déjà et passe au learner ETA (`record_run`) — le réel en regard de la
        prédiction, cf. CARD_DESIGN §10.6.

        Alias conservé : consommé par l'admin, le template de card et la vue `progress`.
        """
        return self.processing_display
        return None

    @property
    def is_video_generation(self):
        """Check if this is a video generation task"""
        return self.generation_mode in ('txt2vid', 'img2vid')

    @property
    def gear_data(self):
        """data-* de réglages de la card (reflet dans le volet inspecteur) — brique COMMUNE
        card_gear dérivée du schéma du DOMAINE (image/vidéo), remplace les attributs écrits
        à la main sur la racine de card (18/08)."""
        from wama.common.utils.card_gear import gear_data
        from .params import IMAGE_PARAMS, VIDEO_PARAMS
        return gear_data(self, VIDEO_PARAMS if self.is_video_generation else IMAGE_PARAMS)

    @property
    def output_images(self):
        """Return list of image URLs for display in templates"""
        import os
        from django.conf import settings

        if not self.generated_images:
            return []

        urls = []
        for path in self.generated_images:
            if os.path.exists(path):
                # Convert absolute path to relative URL
                try:
                    rel_path = os.path.relpath(path, settings.MEDIA_ROOT)
                    url = f"{settings.MEDIA_URL}{rel_path.replace(os.sep, '/')}"
                    urls.append(url)
                except ValueError:
                    # Path is not under MEDIA_ROOT, try to build URL anyway
                    urls.append(path)
        return urls

    def calculate_video_frames(self):
        """Calculate number of frames based on duration and fps (must be 4k+1)"""
        raw_frames = int(self.video_duration * self.video_fps)
        k = round((raw_frames - 1) / 4)
        return 4 * k + 1

    def get_video_resolution(self):
        """Get width and height for video resolution preset"""
        resolutions = {
            '480p': (832, 480),
            '720p': (1280, 720),
        }
        return resolutions.get(self.video_resolution, (832, 480))

    def save(self, *args, **kwargs):
        # Valeur de modèle = CLÉ DE CATALOGUE (route F4b, 2026-09-29). Normalisée ICI, point de
        # passage de TOUS les écrivains (vues, modale, assistant `add_to_imager`, fichiers de lot,
        # duplication) : un identifiant nu posté par une surface pas encore portée est lu dans
        # l'espace de l'imager. `auto` et le vide restent (brique `model_keys`).
        from wama.common.utils.model_keys import catalog_key
        self.model = catalog_key(self.model, 'imager')
        # Auto-set output_type based on generation mode
        if self.generation_mode in ('txt2vid', 'img2vid'):
            self.output_type = 'video'
            # Calculate video frames if not set
            if self.video_frames == 81:  # default value
                self.video_frames = self.calculate_video_frames()
            # Set dimensions based on resolution
            width, height = self.get_video_resolution()
            self.width = width
            self.height = height
        super().save(*args, **kwargs)


# RETIRÉ 2026-08-11 — `UserSettings` (5 colonnes de défauts, OneToOne user) : remplacé par la
# brique commune `common/utils/user_settings.py` (défauts DÉRIVÉS du schéma params.py, écriture à
# la création dans `create_generation`). Le modèle n'avait plus aucun écrivain depuis le retrait
# de `update_settings` (2026-08-06) ; ses 3 lignes en base pointaient des modèles supprimés du
# catalogue (openjourney-v4) et les vieux défauts 512×512 — rien à migrer. Migration 0016.


class GenerationBatch(BatchMixin, QueueOrderMixin, ScopedVisibility):
    """Groupe de générations — unité de FILE et de PARTAGE (contrat commun `build_batches_list`).

    Remplace le self-FK `ImageGeneration.parent_generation`, qui portait la même intention sans
    UI ni partage possible (0 batch en base au portage : le mécanisme n'a jamais servi).

    `ScopedVisibility` AUSSI sur le batch : la file est bâtie à partir des batchs — une card
    partagée sans son batch n'apparaîtrait pas.
    """
    objects = ScopedManager()

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='generation_batches')
    created_at = models.DateTimeField(auto_now_add=True)
    # Fichier de prompts (mode file2img) — partagé par les items, nettoyé par BatchMixin.
    batch_file = models.FileField(
        upload_to=UploadToUserPath('imager', 'input/prompts'),
        blank=True, null=True,
    )
    # Domaine du batch (image | video) : la file de l'imager est scopée par onglet de domaine.
    domain = models.CharField(max_length=10, default='image')
    total = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Batch de génération"
        verbose_name_plural = "Batchs de génération"
        ordering = ['-created_at']

    def __str__(self):
        return f"Batch #{self.id} — {self.user.username} ({self.total} items)"


class GenerationBatchItem(models.Model):
    """Item d'un batch de génération (contrat commun : batch → items → work)."""
    batch = models.ForeignKey(GenerationBatch, on_delete=models.CASCADE, related_name='items')
    generation = models.OneToOneField(
        ImageGeneration, on_delete=models.CASCADE,
        related_name='batch_item', null=True, blank=True,
    )
    row_index = models.IntegerField(default=0)

    class Meta:
        ordering = ['row_index']

    def __str__(self):
        return f"GenerationBatchItem #{self.id} — batch {self.batch_id}"
