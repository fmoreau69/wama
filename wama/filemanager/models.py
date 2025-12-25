"""
FileManager models - Track user files and folders.
"""
import os
from django.db import models
from django.contrib.auth.models import User


def user_directory_path(instance, filename):
    """Generate upload path: users/{user_id}/temp/{filename}"""
    return f'users/{instance.user.id}/temp/{filename}'


class UserFile(models.Model):
    """
    Represents a file uploaded by a user via the file manager.
    Files from other apps (enhancer, anonymizer, etc.) are not stored here,
    but can be browsed through the virtual file system.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to=user_directory_path)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, blank=True, default='')
    file_size = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # Optional: parent folder for organization
    folder = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'User File'
        verbose_name_plural = 'User Files'

    def __str__(self):
        return f"{self.original_name} ({self.user.username})"

    def get_filename(self):
        """Return the filename without path."""
        return os.path.basename(self.file.name) if self.file else ''

    def delete(self, *args, **kwargs):
        """Delete file from storage when model is deleted."""
        if self.file:
            try:
                self.file.delete(save=False)
            except Exception:
                pass
        super().delete(*args, **kwargs)
