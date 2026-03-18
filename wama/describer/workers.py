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


def _download_from_source_url(description, console):
    """
    Download the file from description.source_url and save it to description.input_file.
    Updates description.filename, file_size, detected_type in the DB.
    """
    import re
    import tempfile
    import shutil
    from django.core.files import File
    from wama.common.utils.video_utils import upload_media_from_url

    url = description.source_url
    user_id = description.user_id

    _MEDIA_PLATFORM_DOMAINS = (
        'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com',
        'twitch.tv', 'soundcloud.com', 'bandcamp.com', 'mixcloud.com',
    )
    _MEDIA_EXTS = ('.mp4', '.webm', '.mkv', '.avi', '.mov',
                   '.mp3', '.wav', '.flac', '.ogg', '.m4a',
                   '.jpg', '.jpeg', '.png', '.gif', '.webp')
    _is_media_platform = any(d in url for d in _MEDIA_PLATFORM_DOMAINS)
    _has_media_ext = url.lower().split('?')[0].endswith(_MEDIA_EXTS)

    _is_html_page = False
    if not _is_media_platform and not _has_media_ext:
        try:
            import requests as _req
            _head = _req.head(url, timeout=10, allow_redirects=True,
                              headers={'User-Agent': 'Mozilla/5.0'})
            _ct = _head.headers.get('Content-Type', '')
            _is_html_page = 'text/html' in _ct
        except Exception:
            pass

    temp_dir = tempfile.mkdtemp()
    try:
        if _is_html_page:
            from .views import _fetch_html_as_text
            downloaded_path = _fetch_html_as_text(url, temp_dir)
        else:
            downloaded_path = upload_media_from_url(url, temp_dir)
            _dl_name = os.path.basename(downloaded_path)
            _dl_ext = _dl_name.rsplit('.', 1)[-1].lower() if '.' in _dl_name else ''
            if not _dl_ext or _dl_ext in ('html', 'htm'):
                try:
                    with open(downloaded_path, 'rb') as _fh:
                        _sample = _fh.read(2048).lower()
                    if b'<html' in _sample or b'<!doctype' in _sample:
                        with open(downloaded_path, 'r', encoding='utf-8', errors='replace') as _fh:
                            _html = _fh.read()
                        from .utils.text_describer import _html_to_readable_text
                        _text = _html_to_readable_text(_html)
                        from urllib.parse import urlparse as _urlparse
                        _parts = [p for p in _urlparse(url).path.split('/') if p]
                        _base = '_'.join(_parts[-2:]) if len(_parts) >= 2 else (_parts[-1] if _parts else 'page')
                        _base = re.sub(r'[^\w\-]', '_', _base)[:60] or 'page'
                        _new_path = os.path.join(temp_dir, f"{_base}.txt")
                        with open(_new_path, 'w', encoding='utf-8') as _fh:
                            _fh.write(_text)
                        os.remove(downloaded_path)
                        downloaded_path = _new_path
                except Exception as _ex:
                    logger.warning(f"[workers] Post-download sniff failed: {_ex}")

        filename = os.path.basename(downloaded_path)
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        file_size = os.path.getsize(downloaded_path)

        from .views import detect_type_from_extension
        detected_type = detect_type_from_extension(ext)

        with open(downloaded_path, 'rb') as f:
            description.input_file.save(filename, File(f), save=False)
        description.filename = filename
        description.file_size = file_size
        description.detected_type = detected_type
        description.save(update_fields=['input_file', 'filename', 'file_size', 'detected_type'])
        console(user_id, f"Fichier téléchargé : {filename} ({file_size} o)")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


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

        # If created from batch import (source_url set, no local file yet), download now
        if description.source_url and not description.input_file:
            _console(user_id, f"Import batch — téléchargement de l'URL…")
            _download_from_source_url(description, _console)
            description.refresh_from_db()

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
                from wama.common.utils.llm_utils import generate_structured_summary, get_describer_model
                _sum_model = get_describer_model(content_type, description.output_format)
                _console(user_id, f"Modèle résumé : {_sum_model}")
                summary_data = generate_structured_summary(
                    result,
                    content_hint=content_type,
                    language=description.output_language or 'fr',
                    model=_sum_model,
                )
                description.summary = summary_data['summary']
                description.save(update_fields=['summary'])
                _console(user_id, "Résumé LLM généré ✓")
            except Exception as llm_err:
                _console(user_id, f"Avertissement: résumé LLM échoué ({llm_err})")

        # Optional coherence verification via Ollama (always uses heavy model — careful analysis)
        if description.verify_coherence and result:
            try:
                _console(user_id, "Vérification de cohérence (Ollama)…")
                from wama.common.utils.llm_utils import verify_text_coherence, get_describer_model
                _coh_model = get_describer_model(content_type, 'scientific')  # heavy tier
                _console(user_id, f"Modèle cohérence : {_coh_model}")
                coherence = verify_text_coherence(
                    result,
                    content_hint=content_type,
                    language=description.output_language or 'fr',
                    model=_coh_model,
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
