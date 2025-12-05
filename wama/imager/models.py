"""
WAMA Imager - Models
Image generation using imaginAIry
"""

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator


class ImageGeneration(models.Model):
    """Model for an image generation task"""

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('RUNNING', 'Running'),
        ('SUCCESS', 'Success'),
        ('FAILURE', 'Failure'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # Input parameters
    prompt = models.TextField(help_text="Description of the image to generate")
    negative_prompt = models.TextField(blank=True, default="", help_text="What to avoid in the image")

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

    # Output
    generated_images = models.JSONField(default=list, blank=True, help_text="List of generated image paths")

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
