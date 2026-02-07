"""
WAMA Imager - Models
Image generation using Diffusers with multi-modal input support
"""

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
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
    "openjourney-v4": {
        "min_size": 256,
        "max_size": 768,
        "default": "512x512",
        "recommended": ["512x512", "768x768", "896x512", "512x896"],
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
    "realistic-vision-v5": {
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


class ImageGeneration(models.Model):
    """Model for an image generation task"""

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

    # Parent generation for batch processing
    parent_generation = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='batch_children',
        help_text="Parent generation for batch items"
    )

    # Model and size settings
    model = models.CharField(max_length=100, default="openjourney-v4", help_text="AI model to use")
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

    # Status and progress
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    progress = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    error_message = models.TextField(blank=True, default="")

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
        """Return formatted duration"""
        if self.completed_at and self.created_at:
            delta = self.completed_at - self.created_at
            seconds = int(delta.total_seconds())
            if seconds < 60:
                return f"{seconds}s"
            else:
                minutes = seconds // 60
                seconds = seconds % 60
                return f"{minutes}m {seconds}s"
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
    default_model = models.CharField(max_length=100, default="openjourney-v4")
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
