"""
WAMA Converter — Celery Tasks

Tâche principale : convert_media_task
Routing : CPU-bound → queue 'default' (pas de GPU requis)
"""

import logging
from pathlib import Path
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections

from .models import ConversionJob
from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)


def _set_progress(job_id: int, pct: int) -> None:
    pct = max(0, min(100, int(pct)))
    cache.set(f"converter_progress_{job_id}", pct, timeout=3600)
    ConversionJob.objects.filter(pk=job_id).update(progress=pct)


def _console(user_id: int, message: str, level: str = None) -> None:
    try:
        if level is None:
            msg_lower = message.lower()
            if any(w in msg_lower for w in ['error', 'failed', 'erreur', '✗']):
                level = 'error'
            elif any(w in msg_lower for w in ['warning', 'attention']):
                level = 'warning'
            else:
                level = 'info'
        push_console_line(user_id, message, level=level, app='converter')
    except Exception:
        pass


@shared_task(bind=True)
def convert_media_task(self, job_id: int):
    """
    Celery task : performs file format conversion.

    Steps:
    1. Load ConversionJob
    2. Route to image / video / audio backend
    3. Update progress + status
    4. Handle cross-app options (upscale, audio_enhance) — P2
    """
    close_old_connections()
    logger.info(f"=== convert_media_task START | job_id={job_id} task={self.request.id} ===")

    try:
        job = ConversionJob.objects.select_related('user').get(pk=job_id)
    except ConversionJob.DoesNotExist:
        logger.error(f"ConversionJob #{job_id} introuvable")
        return

    user_id = job.user_id
    _set_progress(job_id, 0)
    _console(user_id, f"Conversion démarrée : {job.input_filename} → .{job.output_format}")

    # ── Resolve input path ────────────────────────────────────────────────────
    input_path  = job.input_file.path
    output_name = _build_output_name(job.input_filename, job.output_format)

    from django.conf import settings
    from wama.common.utils.media_paths import UploadToUserPath
    import os

    output_rel_dir = f"converter/output/{user_id}/"
    output_dir     = settings.MEDIA_ROOT / output_rel_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / output_name)

    def _progress(pct: int):
        _set_progress(job_id, pct)

    try:
        media_type = job.media_type

        if media_type == 'image':
            from .backends.image_backend import convert_image
            convert_image(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                quality=int(job.options.get('quality', 85)),
                options=job.options,
            )
            _set_progress(job_id, 90)

        elif media_type == 'video':
            from .backends.video_backend import convert_video
            convert_video(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                options=job.options,
                progress_callback=_progress,
            )

        elif media_type == 'audio':
            from .backends.audio_backend import convert_audio
            convert_audio(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                options=job.options,
                progress_callback=_progress,
            )

        else:
            raise ValueError(f"Type de média non supporté : {media_type}")

        # ── Save output file reference ────────────────────────────────────
        rel_path = f"{output_rel_dir}{output_name}"
        ConversionJob.objects.filter(pk=job_id).update(
            output_file=rel_path,
            status='DONE',
            progress=100,
        )
        job.refresh_from_db()
        _set_progress(job_id, 100)
        _console(user_id, f"✓ Conversion terminée : {output_name}", level='info')
        logger.info(f"convert_media_task DONE | job_id={job_id} output={output_path}")

    except Exception as exc:
        error_msg = str(exc)[:500]
        logger.exception(f"convert_media_task ERROR | job_id={job_id}: {exc}")
        ConversionJob.objects.filter(pk=job_id).update(
            status='ERROR',
            error_message=error_msg,
        )
        _console(user_id, f"✗ Erreur conversion : {error_msg}", level='error')


def _build_output_name(input_filename: str, output_format: str) -> str:
    """Replace extension with output format, ensuring uniqueness via timestamp."""
    import time
    stem = Path(input_filename).stem
    ts   = int(time.time())
    return f"{stem}_{ts}.{output_format.lower()}"
