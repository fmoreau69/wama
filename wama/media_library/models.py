"""
WAMA Media Library — Modèles
Gestion centralisée des assets réutilisables cross-apps.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator
from wama.common.utils.media_paths import UploadToUserPath

User = get_user_model()

ASSET_TYPES = [
    ('voice',       'Voix'),
    ('audio_music', 'Musique'),
    ('audio_sfx',   'Bruitage'),
    ('image',       'Image'),
    ('video',       'Vidéo'),
    ('document',    'Document'),
    ('avatar',      'Avatar'),
]

ALLOWED_EXTENSIONS = {
    'voice':       ['wav', 'mp3', 'flac', 'ogg', 'm4a'],
    'audio_music': ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac'],
    'audio_sfx':   ['mp3', 'wav', 'ogg', 'flac', 'aiff'],
    'image':       ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'],
    'video':       ['mp4', 'webm', 'mov', 'avi', 'mkv'],
    'document':    ['pdf', 'txt', 'docx', 'md', 'csv'],
    'avatar':      ['jpg', 'jpeg', 'png', 'webp'],
}

# Union de toutes les extensions pour le FileExtensionValidator
_ALL_EXTENSIONS = sorted({ext for exts in ALLOWED_EXTENSIONS.values() for ext in exts})


class UserAsset(models.Model):
    """Asset personnel d'un utilisateur, réutilisable dans toutes les apps."""

    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_assets')
    name       = models.CharField(max_length=200)
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPES)
    file       = models.FileField(
        upload_to=UploadToUserPath('media_library', 'assets'),
        validators=[FileExtensionValidator(allowed_extensions=_ALL_EXTENSIONS)],
    )
    mime_type  = models.CharField(max_length=100, blank=True)
    file_size  = models.PositiveBigIntegerField(default=0)         # bytes
    duration   = models.FloatField(null=True, blank=True)          # secondes (voix, vidéo)
    description = models.TextField(blank=True)
    tags       = models.CharField(max_length=500, blank=True)      # CSV "tag1,tag2"
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Asset utilisateur'
        verbose_name_plural = 'Assets utilisateurs'
        ordering = ['asset_type', 'name']
        unique_together = [['user', 'name', 'asset_type']]
        indexes = [
            models.Index(fields=['user', 'asset_type']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_asset_type_display()}) — {self.user.username}"

    @property
    def file_size_display(self):
        """Taille lisible (Ko, Mo)."""
        if self.file_size < 1024:
            return f"{self.file_size} o"
        if self.file_size < 1024 ** 2:
            return f"{self.file_size / 1024:.1f} Ko"
        return f"{self.file_size / 1024 ** 2:.1f} Mo"

    @property
    def duration_display(self):
        if not self.duration:
            return ''
        m, s = divmod(int(self.duration), 60)
        return f"{m}:{s:02d}"


class SystemAsset(models.Model):
    """
    Asset générique partagé par tous les utilisateurs.
    Géré par les admins ou par téléchargement automatique.
    Non supprimable par les utilisateurs finaux.
    """

    name       = models.CharField(max_length=200, unique=True)
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPES)
    file       = models.FileField(upload_to='media_library/system/')
    mime_type  = models.CharField(max_length=100, blank=True)
    file_size  = models.PositiveBigIntegerField(default=0)
    duration   = models.FloatField(null=True, blank=True)
    description = models.TextField(blank=True)
    tags       = models.CharField(max_length=500, blank=True)
    source_url = models.URLField(blank=True, help_text="URL d'origine pour re-téléchargement")
    license    = models.CharField(max_length=100, blank=True, help_text="CC0, CC-BY, etc.")
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Asset système'
        verbose_name_plural = 'Assets système'
        ordering = ['asset_type', 'name']
        indexes = [
            models.Index(fields=['asset_type', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_asset_type_display()}) [système]"

    @property
    def file_size_display(self):
        if self.file_size < 1024:
            return f"{self.file_size} o"
        if self.file_size < 1024 ** 2:
            return f"{self.file_size / 1024:.1f} Ko"
        return f"{self.file_size / 1024 ** 2:.1f} Mo"

    @property
    def duration_display(self):
        if not self.duration:
            return ''
        m, s = divmod(int(self.duration), 60)
        return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Phase 3 — Providers (sources externes)
# ---------------------------------------------------------------------------

class MediaProvider(models.Model):
    """
    Catalogue des connecteurs/sources media disponibles (Wikimedia, Pixabay, Freesound, …).
    Créé via data migration — ne pas modifier manuellement en prod.
    """
    slug        = models.SlugField(unique=True)
    name        = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    # JSON list of asset_type values this provider supports, e.g. ['image', 'video']
    supported_types  = models.JSONField(default=list)
    requires_api_key = models.BooleanField(default=True)
    # Where the user can obtain an API key
    api_key_help_url = models.URLField(blank=True)
    # Label displayed on the profile page
    api_key_label    = models.CharField(max_length=100, blank=True, default='Clé API')
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fournisseur media'
        verbose_name_plural = 'Fournisseurs media'
        ordering = ['name']

    def __str__(self):
        return self.name


class UserProviderConfig(models.Model):
    """Clé API personnelle d'un utilisateur pour un provider donné."""
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='provider_configs')
    provider = models.ForeignKey(MediaProvider, on_delete=models.CASCADE, related_name='user_configs')
    api_key  = models.CharField(max_length=500, blank=True)
    is_active   = models.BooleanField(default=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Config provider utilisateur'
        verbose_name_plural = 'Configs providers utilisateurs'
        unique_together = [['user', 'provider']]

    def __str__(self):
        return f"{self.user.username} — {self.provider.name}"
