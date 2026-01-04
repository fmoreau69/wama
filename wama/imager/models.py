"""
WAMA Imager - Models
Image generation using Diffusers with multi-modal input support
"""

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator


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
        ('480p', '480p (832x480)'),
        ('720p', '720p (1280x720)'),
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
        upload_to='imager/input/prompts/',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(['txt', 'json', 'yaml', 'yml'])],
        help_text="Text file containing prompts for batch generation"
    )

    # Reference image for img2img/style/describe modes
    reference_image = models.ImageField(
        upload_to='imager/input/references/',
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
        upload_to='imager/videos/',
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
