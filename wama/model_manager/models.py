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
    LIPSYNC = 'lipsync', 'Lip Sync'
    # Alignées sur l'enum de découverte (services/model_registry.py) : la découverte
    # écrivait déjà 'music'/'ocr' dans le CharField, mais ils manquaient ici (choices/admin).
    MUSIC = 'music', 'Music / Audio'
    OCR = 'ocr', 'OCR / Document'


class ModelSource(models.TextChoices):
    """Sources/applications that use models."""
    WAMA_IMAGER = 'imager', 'WAMA Imager'
    WAMA_DESCRIBER = 'describer', 'WAMA Describer'
    WAMA_ANONYMIZER = 'anonymizer', 'WAMA Anonymizer'
    WAMA_TRANSCRIBER = 'transcriber', 'WAMA Transcriber'
    WAMA_SYNTHESIZER = 'synthesizer', 'WAMA Synthesizer'
    WAMA_ENHANCER = 'enhancer', 'WAMA Enhancer'
    WAMA_AVATARIZER = 'avatarizer', 'WAMA Avatarizer'
    # Alignées sur l'enum de découverte (services/model_registry.py) : la découverte écrit déjà
    # 'composer'/'reader' dans le CharField `source` (4 + 2 modèles en base), mais ils manquaient ici
    # (choices/admin). Converter n'a PAS de modèles IA (ffmpeg/pandoc) → pas de source dédiée.
    WAMA_COMPOSER = 'composer', 'WAMA Composer'
    WAMA_READER = 'reader', 'WAMA Reader'
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

    # Description — deux tiers par usage :
    #   description       = long/canonique (page model_manager, à-propos, tooltip détaillé)
    #   description_short = une ligne pour l'aide sous le sélecteur de modèle (WamaModelHelp)
    description = models.TextField(blank=True, default='')
    description_short = models.CharField(max_length=255, blank=True, default='')

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

    # Capacités fonctionnelles du modèle — source UNIQUE consommée par : filtrage UI
    # (voix/langues), sélection par tâche (select_model requires=…), méta-app (compat I/O),
    # description dynamique. Schéma souple par type. Conventions courantes :
    #   speech/TTS : {"supports_cloning": bool, "languages": ["fr","en",...]}
    #   vision/YOLO: {"classes": ["face","plate",...], "task": "detect|segment|pose"}
    #   vlm/llm    : {"languages": [...], "context_length": int}
    capabilities = models.JSONField(
        default=dict,
        blank=True,
        help_text="Functional capabilities (cloning, languages, classes, task...) — single source for UI filtering & task selection"
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

    # ── Prospection (proposé par IA) ──────────────────────────────────────────
    # Une entrée is_proposed=True est un CANDIDAT (MAJ d'un modèle existant ou
    # nouveau modèle/concurrent) suggéré par la prospection, pas un modèle réel
    # installé. Exclu des filtres all/loaded/downloaded ; visible sous l'onglet
    # « Proposés par IA ». Le verdict des agents est stocké dans extra_info.
    is_proposed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Candidat de prospection (proposé par IA), pas un modèle installé"
    )
    proposal_kind = models.CharField(
        max_length=10,
        blank=True,
        default='',
        choices=[('update', 'Mise à jour'), ('new', 'Nouveau / concurrent')],
        help_text="Type de proposition : maj d'un modèle existant ou nouveau modèle"
    )
    confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Taux de confiance de la recommandation (0..1)"
    )
    update_complexity = models.CharField(
        max_length=10,
        blank=True,
        default='',
        choices=[('simple', 'Simple'), ('moderate', 'Modérée'), ('complex', 'Complexe')],
        help_text="Complexité estimée de la mise à jour / installation"
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
            'description_short': self.description_short,
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
            'capabilities': self.capabilities,
            'is_proposed': self.is_proposed,
            'proposal_kind': self.proposal_kind,
            'confidence': self.confidence,
            'update_complexity': self.update_complexity,
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


class ModelRuntimeStat(models.Model):
    """
    Durées de traitement APPRISES par modèle ET par hardware — base du *seeding* de l'ETA
    (cf. common WamaEta). Couplé au registre via `model_key` ("{source}:{model_id}").

    Modèle d'estimation :  ETA ≈ (chargement à froid) + per_unit × taille
      - `load_ema_seconds`     : temps de chargement à froid (size-indépendant) ; None tant qu'inconnu.
      - `per_unit_ema_seconds` : secondes de traitement par unité de `unit` (ex. s de calcul / s d'audio).
      - `unit`                 : grandeur du domaine (audio_sec|video_sec|megapixel|step|token|item).

    Bucketisé par **empreinte hardware** : un changement de GPU repart de l'a-priori et réapprend
    (les stats de l'ancien matériel ne polluent pas le nouveau). L'a-priori (1ʳᵉ utilisation) vit
    dans `AIModel.extra_info['eta']` ; ici on stocke ce qui est mesuré, via moyenne mobile (EMA).
    """
    model_key = models.CharField(max_length=255, db_index=True,
                                 help_text='Identifiant registre : {source}:{model_id}')
    hardware_fingerprint = models.CharField(max_length=128, db_index=True,
                                            help_text='ex. "NVIDIA GeForce RTX 4090|24GB" ou "cpu"')
    unit = models.CharField(max_length=32, default='item')

    load_ema_seconds = models.FloatField(null=True, blank=True)
    per_unit_ema_seconds = models.FloatField(default=0.0)
    samples = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Model Runtime Stat"
        verbose_name_plural = "Model Runtime Stats"
        unique_together = ('model_key', 'hardware_fingerprint')
        indexes = [
            models.Index(fields=['model_key', 'hardware_fingerprint']),
        ]

    def __str__(self):
        return f"{self.model_key} @ {self.hardware_fingerprint} (n={self.samples})"
