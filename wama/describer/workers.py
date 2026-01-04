"""
WAMA Describer - Celery Workers
Async tasks for content description and summarization
"""

import os
import logging
from pathlib import Path
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections
from django.conf import settings

logger = logging.getLogger(__name__)


def _set_progress(description, value: int, force: bool = False) -> None:
    """Update progress in cache and database."""
    cache_key = f"describer_progress_{description.id}"
    cache.set(cache_key, value, timeout=3600)

    if force or value % 10 == 0:  # Update DB every 10%
        from .models import Description
        Description.objects.filter(pk=description.id).update(progress=value)


def _set_partial(description, text: str) -> None:
    """Set partial result text in cache."""
    cache_key = f"describer_partial_{description.id}"
    cache.set(cache_key, text, timeout=3600)


def _console(user_id: int, message: str) -> None:
    """Add message to console output."""
    cache_key = f"describer_console_{user_id}"
    lines = cache.get(cache_key, [])
    lines.append(message)
    # Keep last 100 lines
    if len(lines) > 100:
        lines = lines[-100:]
    cache.set(cache_key, lines, timeout=3600)


@shared_task(bind=True)
def describe_content(self, description_id: int):
    """Main description task."""
    close_old_connections()

    from .models import Description

    try:
        description = Description.objects.get(pk=description_id)
    except Description.DoesNotExist:
        logger.error(f"Description {description_id} not found")
        return {'ok': False, 'error': 'Description not found'}

    user_id = description.user_id
    _console(user_id, f"Starting description for: {description.filename}")

    try:
        _set_progress(description, 5, force=True)

        # Get file path
        file_path = description.input_file.path
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Detect content type if auto
        content_type = description.detected_type or description.content_type
        if content_type == 'auto':
            from .utils.content_analyzer import detect_content_type
            content_type = detect_content_type(file_path)
            description.detected_type = content_type
            description.save(update_fields=['detected_type'])

        _console(user_id, f"Content type: {content_type}")
        _set_progress(description, 10)

        # Process based on content type
        if content_type == 'image':
            from .utils.image_describer import describe_image
            result = describe_image(description, _set_progress, _set_partial, _console)

        elif content_type == 'video':
            from .utils.video_describer import describe_video
            result = describe_video(description, _set_progress, _set_partial, _console)

        elif content_type == 'audio':
            from .utils.audio_describer import describe_audio
            result = describe_audio(description, _set_progress, _set_partial, _console)

        elif content_type in ('text', 'pdf'):
            from .utils.text_describer import describe_text
            result = describe_text(description, _set_progress, _set_partial, _console)

        else:
            raise ValueError(f"Unsupported content type: {content_type}")

        # Save result
        _set_progress(description, 95)
        _console(user_id, "Saving result...")

        description.result_text = result
        description.status = 'SUCCESS'
        description.save()

        _set_progress(description, 100, force=True)
        _console(user_id, f"Description completed for: {description.filename}")

        return {'ok': True, 'id': description.id}

    except Exception as e:
        logger.exception(f"Error describing {description.filename}: {e}")
        _console(user_id, f"Error: {str(e)}")

        description.status = 'FAILURE'
        description.error_message = str(e)
        description.save()
        _set_progress(description, 0, force=True)

        return {'ok': False, 'error': str(e)}
