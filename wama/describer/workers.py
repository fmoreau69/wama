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
    """Ingestion média (page web -> texte / média -> download) via le mécanisme
    commun déclaratif ensure_local_input (spec WAMA_INGEST du modèle Description).
    Seule part spécifique describer restante : la dérivation de detected_type.
    """
    from wama.common.utils.source_ingest import ensure_local_input

    def _derive(inst, path, fname):
        ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
        from .views import detect_type_from_extension
        inst.detected_type = detect_type_from_extension(ext)
        return ['detected_type']

    ensure_local_input(
        description,
        console=lambda m: console(description.user_id, m),
        derive=_derive,
    )




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

    import time as _time
    _t0 = _time.time()  # chrono pour le seeding ETA (apprentissage des durées réelles)

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
        if description.generate_summary and result and description.output_style != 'meeting':
            try:
                _console(user_id, "Génération du résumé LLM (Ollama)…")
                from wama.common.utils.llm_utils import generate_structured_summary, get_describer_model
                _sum_model = get_describer_model(content_type, description.output_style)
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

        # Persiste le temps réel (déjà mesuré pour l'ETA) — total incluant résumé/cohérence.
        description.processing_seconds = _time.time() - _t0
        description.save(update_fields=['processing_seconds'])

        _set_progress(description, 100, force=True)
        _console(user_id, f"Description terminée: {description.filename}")

        # ── Seeding ETA : enregistre la durée réelle pour affiner l'estimation ──
        # Clé par type de contenu (driver de coût dominant) ; unité selon le média.
        try:
            from wama.model_manager.services.eta_estimator import record_run
            from .eta import eta_size_unit
            _size, _unit = eta_size_unit(content_type, description)
            record_run(f'describer:{content_type}', size=_size, unit=_unit,
                       process_seconds=description.processing_seconds, load_seconds=None)
        except Exception:
            pass

        try:
            from wama.common.utils.notifications import notify_job
            notify_job(getattr(description, 'user', None), 'Describer',
                       getattr(description, 'filename', '') or f"description #{description.id}", True)
        except Exception:
            pass

        return {'ok': True, 'id': description.id}

    except Exception as e:
        logger.exception(f"Error describing {description.filename}: {e}")
        _console(user_id, f"Error: {str(e)}")

        description.status = 'FAILURE'
        description.error_message = str(e)
        description.save()
        _set_progress(description, 0, force=True)
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(getattr(description, 'user', None), 'Describer',
                       getattr(description, 'filename', '') or f"description #{description.id}", False, detail=str(e))
        except Exception:
            pass

        return {'ok': False, 'error': str(e)}
