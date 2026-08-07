"""
WAMA Imager - Models
Image generation using Diffusers with multi-modal input support
"""

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from wama.common.models import (
    BatchMixin, ProcessingTimeMixin, PromptScoped, ScopedManager, ScopedVisibility,
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

# Model-specific resolution configurations
MODEL_RESOLUTION_CONFIG = {
    # HunyuanImage 2.1 - Requires 2K resolution
    "hunyuan-image-2.1": {
        "min_size": 1024,
        "max_size": 2048,
        "default": "2048x2048",
        "recommended": ["2048x2048", "2048x1152", "1152x2048", "2048x880"],
        "vram_warning": "24GB+ VRAM recommended for 2K generation",
    },

    # Stable Diffusion 1.5 - Standard SD models
    "stable-diffusion-v1-5": {
        "min_size": 256,
        "max_size": 768,
        "default": "512x512",
        "recommended": ["512x512", "768x768", "896x512", "512x896", "680x512", "512x680"],
    },
    "dreamshaper-8": {
        "min_size": 256,
        "max_size": 768,
        "default": "512x512",
        "recommended": ["512x512", "768x768", "896x512", "512x896"],
    },
    "deliberate-v6": {
        "min_size": 256,
        "max_size": 768,
        "default": "512x512",
        "recommended": ["512x512", "768x768", "896x512", "512x896"],
    },
    "anything-v5": {
        "min_size": 256,
        "max_size": 768,
        "default": "512x512",
        "recommended": ["512x512", "768x768", "896x512", "512x896"],
    },
    "dreamlike-art-2": {
        "min_size": 256,
        "max_size": 768,
        "default": "512x512",
        "recommended": ["512x512", "768x768", "896x512", "512x896"],
    },

    # Stable Diffusion 2.1 - Slightly larger
    "stable-diffusion-2-1": {
        "min_size": 256,
        "max_size": 1024,
        "default": "768x768",
        "recommended": ["768x768", "1024x1024", "896x512", "512x896"],
    },

    # SDXL - Large resolution support
    "stable-diffusion-xl": {
        "min_size": 512,
        "max_size": 1536,
        "default": "1024x1024",
        "recommended": ["1024x1024", "1344x768", "768x1344", "1920x1088", "1088x1920"],
        "vram_warning": "10GB+ VRAM recommended for 1024+ resolution",
    },
    # FLUX Logo Design LoRA — max 768 px avec MODEL_OFFLOAD sur RTX 4090.
    # 1024×1024 dépasse les 24 GB (23 GB transformer + activations d'attention
    # sur 4096 tokens) et provoque un OOM silencieux dans WSL2.
    # 768×768 est stable et produit des logos haute qualité.
    "flux-lora-logo-design": {
        "min_size": 512,
        "max_size": 768,
        "default": "768x768",
        "recommended": ["768x768", "768x512", "512x768"],
        "vram_warning": "16GB+ VRAM requis — max 768px avec MODEL_OFFLOAD",
    },

    # Qwen Image 2 models - 2K native resolution
    "qwen-image-2": {
        "min_size": 512,
        "max_size": 2048,
        "default": "1024x1024",
        "recommended": ["1024x1024", "2048x2048", "2048x1152", "1152x2048"],
        "vram_warning": "16GB+ VRAM required",
    },
    "qwen-image-edit": {
        "min_size": 512,
        "max_size": 2048,
        "default": "1024x1024",
        "recommended": ["1024x1024", "2048x2048", "2048x1152", "1152x2048"],
        "vram_warning": "12GB+ VRAM required",
    },
}

# Default config for unknown models
DEFAULT_MODEL_RESOLUTION_CONFIG = {
    "min_size": 256,
    "max_size": 1024,
    "default": "512x512",
    "recommended": ["512x512", "768x768", "896x512", "512x896"],
}


def get_model_resolution_config(model_name: str) -> dict:
    """Get resolution configuration for a model."""
    return MODEL_RESOLUTION_CONFIG.get(model_name, DEFAULT_MODEL_RESOLUTION_CONFIG)


def get_recommended_resolutions(model_name: str) -> list:
    """Get list of recommended resolution presets for a model."""
    config = get_model_resolution_config(model_name)
    recommended_keys = config.get("recommended", ["512x512"])
    return [
        {"key": key, **IMAGE_RESOLUTION_PRESETS[key]}
        for key in recommended_keys
        if key in IMAGE_RESOLUTION_PRESETS
    ]


class ImageGeneration(ProcessingTimeMixin, PromptScoped, ScopedVisibility):
    """Model for an image generation task.

    `ScopedVisibility` (brique COMMUNE) : la card est privée par défaut et peut être partagée à
    l'unité, à un projet ou publiquement — cf. PROFILES_PERMISSIONS §7. Le partage est en
    **lecture seule par construction** : les vues de liste filtrent par `visible_to(user)`, les
    vues mutantes gardent `owned_by(user)`. Aucune vue ne peut donc accorder l'écriture par
    inadvertance avant que `ObjectGrant` (§7.3) n'existe.
    """

    objects = ScopedManager()

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('RUNNING', 'Running'),
        ('SUCCESS', 'Success'),
        ('FAILURE', 'Failure'),
    ]

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

    user = models.ForeignKey(User, on_delete=models.CASCADE)

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
    model = models.CharField(max_length=100, default="stable-diffusion-v1-5", help_text="AI model to use")
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

    # Upscaling options
    upscale = models.BooleanField(default=False, help_text="Upscale the generated image")

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


class UserSettings(models.Model):
    """User preferences for image generation"""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='imager_settings')

    # Default generation settings
    default_model = models.CharField(max_length=100, default="stable-diffusion-v1-5")
    default_width = models.IntegerField(default=512)
    default_height = models.IntegerField(default=512)
    default_steps = models.IntegerField(default=30)
    default_guidance_scale = models.FloatField(default=7.5)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Settings"
        verbose_name_plural = "User Settings"

    def __str__(self):
        return f"Settings for {self.user.username}"


class GenerationBatch(BatchMixin, ScopedVisibility):
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
