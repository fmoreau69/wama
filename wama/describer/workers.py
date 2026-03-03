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

from wama.common.utils.console_utils import push_console_line

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


def _console(user_id: int, message: str, level: str = None) -> None:
    """Add message to console output."""
    try:
        if level is None:
            msg_lower = message.lower()
            if any(w in msg_lower for w in ['error', 'failed', '\u2717', 'erreur']):
                level = 'error'
            elif any(w in msg_lower for w in ['warning', 'attention']):
                level = 'warning'
            elif any(w in msg_lower for w in ['[debug]', '[parallel']):
                level = 'debug'
            else:
                level = 'info'
        push_console_line(user_id, message, level=level, app='describer')
    except Exception:
        pass


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
        _set_progress(description, 90)
        _console(user_id, "Sauvegarde du résultat…")

        description.result_text = result
        description.status = 'SUCCESS'
        description.save()

        # Optional LLM summary via Ollama (skip if meeting format — already IS the summary)
        if description.generate_summary and result and description.output_format != 'meeting':
            try:
                _console(user_id, "Génération du résumé LLM (Ollama)…")
                from wama.common.utils.llm_utils import generate_structured_summary
                summary_data = generate_structured_summary(
                    result,
                    content_hint=content_type,   # 'image', 'video', 'audio', 'text'
                    language=description.output_language or 'fr',
                )
                description.summary = summary_data['summary']
                description.save(update_fields=['summary'])
                _console(user_id, "Résumé LLM généré ✓")
            except Exception as llm_err:
                _console(user_id, f"Avertissement: résumé LLM échoué ({llm_err})")

        # Optional coherence verification via Ollama
        if description.verify_coherence and result:
            try:
                _console(user_id, "Vérification de cohérence (Ollama)…")
                from wama.common.utils.llm_utils import verify_text_coherence
                coherence = verify_text_coherence(
                    result,
                    content_hint=content_type,
                    language=description.output_language or 'fr',
                )
                description.coherence_score = coherence['score']
                description.coherence_notes = '\n'.join(coherence['notes'])
                description.coherence_suggestion = coherence['suggestion']
                description.save(update_fields=['coherence_score', 'coherence_notes', 'coherence_suggestion'])
                _console(user_id, f"Cohérence vérifiée — score: {coherence['score']}/100 ✓")
            except Exception as coh_err:
                _console(user_id, f"Avertissement: vérification cohérence échouée ({coh_err})")

        _set_progress(description, 100, force=True)
        _console(user_id, f"Description terminée: {description.filename}")

        return {'ok': True, 'id': description.id}

    except Exception as e:
        logger.exception(f"Error describing {description.filename}: {e}")
        _console(user_id, f"Error: {str(e)}")

        description.status = 'FAILURE'
        description.error_message = str(e)
        description.save()
        _set_progress(description, 0, force=True)

        return {'ok': False, 'error': str(e)}
