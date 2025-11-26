"""
WAMA Synthesizer - Models
Gère la synthèse vocale (Text-to-Speech)
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator

User = get_user_model()


class VoiceSynthesis(models.Model):
    """
    Modèle représentant une tâche de synthèse vocale.
    """

    STATUS_CHOICES = [
        ('PENDING', 'En attente'),
        ('RUNNING', 'En cours'),
        ('SUCCESS', 'Terminé'),
        ('FAILURE', 'Échec'),
    ]

    TTS_MODEL_CHOICES = [
        ('xtts_v2', 'XTTS v2 (Multilingual, Voice Cloning)'),
        ('vits', 'VITS (Fast, Good Quality)'),
        ('tacotron2', 'Tacotron2 (Classic, Stable)'),
        ('speedy_speech', 'SpeedySpeech (Very Fast)'),
    ]

    LANGUAGE_CHOICES = [
        ('en', 'English'),
        ('fr', 'Français'),
        ('es', 'Español'),
        ('de', 'Deutsch'),
        ('it', 'Italiano'),
        ('pt', 'Português'),
        ('pl', 'Polski'),
        ('tr', 'Türkçe'),
        ('ru', 'Русский'),
        ('nl', 'Nederlands'),
        ('cs', 'Čeština'),
        ('ar', 'العربية'),
        ('zh-cn', '中文'),
        ('ja', '日本語'),
        ('ko', '한국어'),
    ]

    VOICE_PRESET_CHOICES = [
        ('default', 'Voix par défaut'),
        ('male_1', 'Voix masculine 1'),
        ('male_2', 'Voix masculine 2'),
        ('female_1', 'Voix féminine 1'),
        ('female_2', 'Voix féminine 2'),
        ('custom', 'Voix personnalisée (clonage)'),
    ]

    # Informations de base
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='voice_syntheses')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Fichier texte source
    text_file = models.FileField(
        upload_to='synthesizer/texts/%Y/%m/%d/',
        validators=[FileExtensionValidator(allowed_extensions=['txt', 'pdf', 'docx', 'csv', 'md'])],
        help_text="Fichier texte à synthétiser"
    )

    # Contenu texte extrait
    text_content = models.TextField(
        blank=True,
        help_text="Contenu texte extrait du fichier"
    )

    # Fichier de référence vocale (pour le clonage)
    voice_reference = models.FileField(
        upload_to='synthesizer/voice_refs/%Y/%m/%d/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=['wav', 'mp3', 'flac', 'ogg'])],
        help_text="Échantillon audio pour clonage de voix (6-10 secondes recommandé)"
    )

    # Options de synthèse
    tts_model = models.CharField(
        max_length=50,
        choices=TTS_MODEL_CHOICES,
        default='xtts_v2',
        help_text="Modèle TTS à utiliser"
    )

    language = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default='fr',
        help_text="Langue de synthèse"
    )

    voice_preset = models.CharField(
        max_length=20,
        choices=VOICE_PRESET_CHOICES,
        default='default',
        help_text="Preset de voix"
    )

    # Paramètres audio
    speed = models.FloatField(
        default=1.0,
        help_text="Vitesse de parole (0.5 = lent, 2.0 = rapide)"
    )

    pitch = models.FloatField(
        default=1.0,
        help_text="Hauteur de la voix (0.5 = grave, 2.0 = aigu)"
    )

    emotion_intensity = models.FloatField(
        default=1.0,
        help_text="Intensité émotionnelle (0.0 = neutre, 2.0 = très expressif)"
    )

    # Résultat
    audio_output = models.FileField(
        upload_to='synthesizer/outputs/%Y/%m/%d/',
        blank=True,
        null=True,
        help_text="Fichier audio généré"
    )

    # Métadonnées
    word_count = models.IntegerField(
        default=0,
        help_text="Nombre de mots dans le texte"
    )

    duration_seconds = models.FloatField(
        default=0.0,
        help_text="Durée estimée de l'audio en secondes"
    )

    duration_display = models.CharField(
        max_length=20,
        blank=True,
        help_text="Durée formatée (mm:ss)"
    )

    properties = models.CharField(
        max_length=200,
        blank=True,
        help_text="Propriétés audio (format, sample rate, etc.)"
    )

    # État de la tâche
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )

    progress = models.IntegerField(
        default=0,
        help_text="Progression de la synthèse (0-100)"
    )

    task_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="ID de la tâche Celery"
    )

    error_message = models.TextField(
        blank=True,
        help_text="Message d'erreur en cas d'échec"
    )

    class Meta:
        verbose_name = "Synthèse vocale"
        verbose_name_plural = "Synthèses vocales"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Synthesis #{self.id} - {self.user.username} - {self.status}"

    @property
    def filename(self):
        """Retourne le nom du fichier texte source."""
        if self.text_file:
            return self.text_file.name.split('/')[-1]
        return "N/A"

    @property
    def audio_filename(self):
        """Retourne le nom du fichier audio généré."""
        if self.audio_output:
            return self.audio_output.name.split('/')[-1]
        return "N/A"

    def estimate_duration(self):
        """
        Estime la durée de l'audio basée sur le nombre de mots.
        Règle approximative: 150 mots/minute pour un débit normal.
        """
        if self.word_count > 0:
            # Ajuster selon la vitesse
            base_wpm = 150  # mots par minute
            adjusted_wpm = base_wpm * self.speed
            duration = (self.word_count / adjusted_wpm) * 60
            return duration
        return 0.0

    def format_duration(self, seconds):
        """Formate une durée en secondes vers mm:ss."""
        if not seconds or seconds <= 0:
            return '0:00'
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"

    def update_metadata(self):
        """Met à jour les métadonnées (word count, durée estimée)."""
        if self.text_content:
            # Compter les mots
            self.word_count = len(self.text_content.split())

            # Estimer la durée
            estimated_duration = self.estimate_duration()
            self.duration_seconds = estimated_duration
            self.duration_display = self.format_duration(estimated_duration)

            self.save(update_fields=['word_count', 'duration_seconds', 'duration_display'])


class VoicePreset(models.Model):
    """
    Modèle pour stocker des presets de voix personnalisés.
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    # Fichier de référence
    reference_audio = models.FileField(
        upload_to='synthesizer/presets/',
        validators=[FileExtensionValidator(allowed_extensions=['wav', 'mp3', 'flac'])]
    )

    # Métadonnées
    language = models.CharField(max_length=10, default='en')
    gender = models.CharField(
        max_length=10,
        choices=[('male', 'Male'), ('female', 'Female'), ('neutral', 'Neutral')],
        default='neutral'
    )

    # Disponibilité
    is_public = models.BooleanField(
        default=False,
        help_text="Si activé, disponible pour tous les utilisateurs"
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='voice_presets'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Preset de voix"
        verbose_name_plural = "Presets de voix"
        ordering = ['name']

    def __str__(self):
        return self.name