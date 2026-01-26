"""
WAMA Common - Media Path Utilities

Centralized utilities for generating user-specific media paths across all applications.
Structure: media/{app_name}/{user_id}/{subfolder}/

This ensures:
- User isolation: each user sees only their files
- Consistent structure across all apps
- Easy migration path for existing apps
"""

import os
import uuid
from pathlib import Path
from typing import Union, Optional
from django.conf import settings


def get_app_media_path(app_name: str, user_id: Union[int, str], subfolder: str = 'input') -> Path:
    """
    Get the absolute path for an app's user-specific media folder.

    Args:
        app_name: Application name (e.g., 'anonymizer', 'enhancer')
        user_id: User ID
        subfolder: Subfolder name (e.g., 'input', 'output')

    Returns:
        Path object for: MEDIA_ROOT/{app_name}/{user_id}/{subfolder}/

    Example:
        get_app_media_path('anonymizer', 1, 'input')
        -> Path('/media/anonymizer/1/input/')
    """
    return Path(settings.MEDIA_ROOT) / app_name / str(user_id) / subfolder


def get_app_media_url(app_name: str, user_id: Union[int, str], subfolder: str = 'input') -> str:
    """
    Get the URL path for an app's user-specific media folder.

    Args:
        app_name: Application name (e.g., 'anonymizer', 'enhancer')
        user_id: User ID
        subfolder: Subfolder name (e.g., 'input', 'output')

    Returns:
        URL string: /media/{app_name}/{user_id}/{subfolder}/
    """
    return f"{settings.MEDIA_URL}{app_name}/{user_id}/{subfolder}/"


def ensure_app_media_dirs(app_name: str, user_id: Union[int, str]) -> dict:
    """
    Ensure input and output directories exist for an app/user.

    Args:
        app_name: Application name
        user_id: User ID

    Returns:
        Dict with 'input' and 'output' Path objects
    """
    input_path = get_app_media_path(app_name, user_id, 'input')
    output_path = get_app_media_path(app_name, user_id, 'output')

    input_path.mkdir(parents=True, exist_ok=True)
    output_path.mkdir(parents=True, exist_ok=True)

    return {
        'input': input_path,
        'output': output_path,
    }


def get_unique_filename(folder: Union[str, Path], filename: str) -> str:
    """
    Generate a unique filename in a folder.
    If 'file.mp4' exists, generates 'file_<uuid>.mp4'.

    Args:
        folder: Directory path
        filename: Original filename

    Returns:
        Unique filename (not full path)
    """
    folder = Path(folder)
    base, ext = os.path.splitext(filename)
    candidate = filename
    full_path = folder / candidate

    while full_path.exists():
        candidate = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
        full_path = folder / candidate

    return candidate


def get_relative_media_path(app_name: str, user_id: Union[int, str], subfolder: str, filename: str) -> str:
    """
    Get the relative path for storing in Django FileField.

    Args:
        app_name: Application name
        user_id: User ID
        subfolder: Subfolder name ('input' or 'output')
        filename: Filename

    Returns:
        Relative path string: {app_name}/{user_id}/{subfolder}/{filename}
    """
    return f"{app_name}/{user_id}/{subfolder}/{filename}"


class UploadToUserPath:
    """
    Callable class for Django FileField upload_to that generates user-specific paths.
    This class is serializable by Django migrations.

    Usage in models.py:
        file = models.FileField(upload_to=UploadToUserPath('anonymizer', 'input'))
    """

    def __init__(self, app_name: str, subfolder: str = 'input'):
        self.app_name = app_name
        self.subfolder = subfolder

    def __call__(self, instance, filename):
        user_id = instance.user_id if hasattr(instance, 'user_id') else instance.user.id
        # Ensure directory exists
        path = get_app_media_path(self.app_name, user_id, self.subfolder)
        path.mkdir(parents=True, exist_ok=True)
        # Generate unique filename if needed
        unique_name = get_unique_filename(path, filename)
        return get_relative_media_path(self.app_name, user_id, self.subfolder, unique_name)

    def deconstruct(self):
        """Required for Django migrations serialization."""
        return (
            'wama.common.utils.media_paths.UploadToUserPath',
            [self.app_name, self.subfolder],
            {}
        )


def upload_to_user_input(app_name: str):
    """
    Convenience function to create an UploadToUserPath for input folder.

    Usage in models.py:
        file = models.FileField(upload_to=upload_to_user_input('anonymizer'))
    """
    return UploadToUserPath(app_name, 'input')


def upload_to_user_output(app_name: str):
    """
    Convenience function to create an UploadToUserPath for output folder.

    Usage in models.py:
        output_file = models.FileField(upload_to=upload_to_user_output('anonymizer'))
    """
    return UploadToUserPath(app_name, 'output')


def migrate_file_to_user_path(
    old_path: Union[str, Path],
    app_name: str,
    user_id: Union[int, str],
    subfolder: str = 'input',
    move: bool = True
) -> Optional[str]:
    """
    Migrate a file from old location to new user-specific location.

    Args:
        old_path: Current file path (relative to MEDIA_ROOT or absolute)
        app_name: Application name
        user_id: User ID
        subfolder: Target subfolder ('input' or 'output')
        move: If True, move the file. If False, copy it.

    Returns:
        New relative path for storing in DB, or None if file doesn't exist
    """
    import shutil

    # Handle relative paths
    if not os.path.isabs(old_path):
        old_path = Path(settings.MEDIA_ROOT) / old_path
    else:
        old_path = Path(old_path)

    if not old_path.exists():
        return None

    # Get new path
    new_dir = get_app_media_path(app_name, user_id, subfolder)
    new_dir.mkdir(parents=True, exist_ok=True)

    filename = old_path.name
    unique_name = get_unique_filename(new_dir, filename)
    new_path = new_dir / unique_name

    # Move or copy
    if move:
        shutil.move(str(old_path), str(new_path))
    else:
        shutil.copy2(str(old_path), str(new_path))

    return get_relative_media_path(app_name, user_id, subfolder, unique_name)
