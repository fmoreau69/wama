"""
WAMA Model Manager - Database Models

PostgreSQL-backed catalog for all AI models.
Provides instant loading instead of dynamic filesystem scanning.
"""

from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class ModelType(models.TextChoices):
    """Types of AI models."""
    VISION = 'vision', 'Vision'
    DIFFUSION = 'diffusion', 'Diffusion'
    SPEECH = 'speech', 'Speech'
    VLM = 'vlm', 'Vision-Language'
    LLM = 'llm', 'Large Language Model'
    SUMMARIZATION = 'summarization', 'Summarization'
    UPSCALING = 'upscaling', 'Upscaling'


class ModelSource(models.TextChoices):
    """Sources/applications that use models."""
    WAMA_IMAGER = 'imager', 'WAMA Imager'
    WAMA_DESCRIBER = 'describer', 'WAMA Describer'
    WAMA_ANONYMIZER = 'anonymizer', 'WAMA Anonymizer'
    WAMA_TRANSCRIBER = 'transcriber', 'WAMA Transcriber'
    WAMA_SYNTHESIZER = 'synthesizer', 'WAMA Synthesizer'
    WAMA_ENHANCER = 'enhancer', 'WAMA Enhancer'
    OLLAMA = 'ollama', 'Ollama'
    HUGGINGFACE = 'huggingface', 'HuggingFace'
    CUSTOM = 'custom', 'Custom'


class AIModel(models.Model):
    """
    Unified AI Model catalog entry.
    Stores both downloaded and available (not yet downloaded) models.
    """

    # Primary identifier (unique per source)
    # Format: "{source}:{model_id}" e.g., "imager:wan-ti2v-5b", "ollama:llama3.2"
    model_key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique identifier: {source}:{model_id}"
    )

    # Display name
    name = models.CharField(max_length=255, db_index=True)

    # Classification
    model_type = models.CharField(
        max_length=20,
        choices=ModelType.choices,
        db_index=True
    )
    source = models.CharField(
        max_length=20,
        choices=ModelSource.choices,
        db_index=True
    )

    # Description
    description = models.TextField(blank=True, default='')

    # External references
    hf_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="HuggingFace model ID (e.g., 'Wan-AI/Wan2.2-T2V')"
    )

    # Resource requirements
    vram_gb = models.FloatField(default=0, help_text="Estimated VRAM in GB")
    ram_gb = models.FloatField(default=0, help_text="Estimated RAM in GB")
    disk_gb = models.FloatField(default=0, help_text="Disk space in GB")

    # Status flags
    is_downloaded = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Model files exist locally"
    )
    is_loaded = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Model is currently loaded in memory"
    )
    is_available = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Model is available for use (not deprecated/removed)"
    )

    # File paths and format
    local_path = models.CharField(
        max_length=1024,
        blank=True,
        default='',
        help_text="Local file/directory path"
    )
    format = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="Current format: pt, safetensors, onnx, gguf, etc."
    )
    preferred_format = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="Recommended format per policy"
    )

    # Flexible metadata (JSON)
    extra_info = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional model-specific metadata"
    )

    # Conversion capabilities
    can_convert_to = models.JSONField(
        default=list,
        blank=True,
        help_text="List of formats model can be converted to"
    )

    # Backend reference for loading/unloading
    backend_ref = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Backend identifier for model operations"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this model was synced from source"
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this model was loaded/used"
    )

    class Meta:
        verbose_name = "AI Model"
        verbose_name_plural = "AI Models"
        ordering = ['source', 'model_type', 'name']
        indexes = [
            models.Index(fields=['source', 'model_type']),
            models.Index(fields=['is_downloaded', 'is_available']),
            models.Index(fields=['hf_id']),
            models.Index(fields=['updated_at']),
        ]

    def __str__(self):
        status = "Downloaded" if self.is_downloaded else "Not Downloaded"
        return f"{self.name} ({self.source}) - {status}"

    @property
    def model_id(self):
        """Extract model_id from model_key (part after colon)."""
        if ':' in self.model_key:
            return self.model_key.split(':', 1)[1]
        return self.model_key

    @property
    def size_display(self):
        """Human-readable size display."""
        if self.vram_gb:
            return f"{self.vram_gb:.1f}GB VRAM"
        elif self.ram_gb:
            return f"{self.ram_gb:.1f}GB RAM"
        return "Unknown"

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.model_key,
            'model_key': self.model_key,
            'name': self.name,
            'type': self.model_type,
            'source': self.source,
            'description': self.description,
            'hf_id': self.hf_id,
            'vram_gb': self.vram_gb,
            'ram_gb': self.ram_gb,
            'disk_gb': self.disk_gb,
            'is_downloaded': self.is_downloaded,
            'is_loaded': self.is_loaded,
            'is_available': self.is_available,
            'local_path': self.local_path,
            'format': self.format,
            'preferred_format': self.preferred_format,
            'can_convert_to': self.can_convert_to,
            'backend_ref': self.backend_ref,
            'extra_info': self.extra_info,
        }


class ModelSyncLog(models.Model):
    """
    Log of model sync operations for debugging and auditing.
    """

    SYNC_TYPE_CHOICES = [
        ('full', 'Full Sync'),
        ('incremental', 'Incremental'),
        ('manual', 'Manual Trigger'),
        ('watchdog', 'File Watcher'),
    ]

    STATUS_CHOICES = [
        ('started', 'Started'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    sync_type = models.CharField(max_length=20, choices=SYNC_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='started')

    models_added = models.IntegerField(default=0)
    models_updated = models.IntegerField(default=0)
    models_removed = models.IntegerField(default=0)

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    error_message = models.TextField(blank=True, default='')
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Model Sync Log"
        verbose_name_plural = "Model Sync Logs"
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.sync_type} sync at {self.started_at} - {self.status}"

    @property
    def duration_seconds(self):
        """Calculate sync duration."""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
