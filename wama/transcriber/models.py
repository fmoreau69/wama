from django.db import models
from django.contrib.auth.models import User
from wama.common.utils.media_paths import upload_to_user_input


class Transcript(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transcripts')
    audio = models.FileField(upload_to=upload_to_user_input('transcriber'))
    created_at = models.DateTimeField(auto_now_add=True)

    # Options
    preprocess_audio = models.BooleanField(default=False)

    # Backend selection
    backend = models.CharField(max_length=32, default='auto', blank=True)  # auto, whisper, vibevoice

    # VibeVoice-specific options
    hotwords = models.TextField(blank=True, default='')  # Domain-specific terms
    enable_diarization = models.BooleanField(default=True)

    # Advanced parameters (optional)
    temperature = models.FloatField(default=0.0)
    max_tokens = models.IntegerField(default=32768)

    # Processing state
    task_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=32, default='PENDING')  # PENDING/RUNNING/SUCCESS/FAILURE
    progress = models.IntegerField(default=0)
    properties = models.CharField(max_length=128, blank=True, default='')
    duration_seconds = models.FloatField(default=0)
    duration_display = models.CharField(max_length=16, blank=True, default='')

    # Result
    language = models.CharField(max_length=16, blank=True, default='')
    text = models.TextField(blank=True, default='')

    # Structured result backup (JSON)
    segments_json = models.JSONField(null=True, blank=True)

    # Backend used for transcription (filled after processing)
    used_backend = models.CharField(max_length=32, blank=True, default='')

    def __str__(self):
        return f"Transcript {self.id} ({self.user.username})"

    @property
    def has_segments(self) -> bool:
        """Check if transcript has segments with diarization."""
        return self.segments.exists()

    @property
    def speaker_count(self) -> int:
        """Get number of unique speakers."""
        return self.segments.values('speaker_id').distinct().count()


class TranscriptSegment(models.Model):
    """
    A segment of transcription with speaker identification and timestamps.

    Used primarily for VibeVoice ASR output which provides:
    - Speaker diarization (who is speaking)
    - Precise timestamps (when)
    - Segmented text (what)
    """
    transcript = models.ForeignKey(
        Transcript,
        on_delete=models.CASCADE,
        related_name='segments'
    )

    # Speaker identification
    speaker_id = models.CharField(max_length=50, blank=True, default='')  # e.g., "Speaker_1"

    # Timestamps (in seconds)
    start_time = models.FloatField(default=0)
    end_time = models.FloatField(default=0)

    # Content
    text = models.TextField(default='')

    # Optional confidence score
    confidence = models.FloatField(null=True, blank=True)

    # Order for sorting
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order', 'start_time']

    def __str__(self):
        speaker = self.speaker_id or 'Unknown'
        return f"[{speaker}] {self.start_time:.1f}s: {self.text[:50]}..."

    @property
    def duration(self) -> float:
        """Get segment duration in seconds."""
        return max(0, self.end_time - self.start_time)

    def format_time_range(self) -> str:
        """Format time range as HH:MM:SS - HH:MM:SS."""
        return f"{self._format_time(self.start_time)} - {self._format_time(self.end_time)}"

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as HH:MM:SS.mmm."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
        return f"{minutes:02d}:{secs:06.3f}"

    def to_srt_time(self, seconds: float) -> str:
        """Format time for SRT format (HH:MM:SS,mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def to_srt_entry(self, index: int) -> str:
        """Generate SRT entry for this segment."""
        start = self.to_srt_time(self.start_time)
        end = self.to_srt_time(self.end_time)
        speaker_prefix = f"[{self.speaker_id}] " if self.speaker_id else ""
        return f"{index}\n{start} --> {end}\n{speaker_prefix}{self.text}\n\n"
