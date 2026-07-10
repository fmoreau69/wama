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

    import time as _time
    _t0 = _time.time()  # chrono pour le seeding ETA

    # ── Resolve input path ────────────────────────────────────────────────────
    input_path  = job.input_file.path

    from django.conf import settings
    from pathlib import Path as _Path
    import os

    # Output location:
    #   - dest_dir set (quick convert in-place) → write next to the source,
    #     keep the original stem, add a numeric suffix on collision.
    #   - otherwise → default converter/output/<user>/ with a timestamped name.
    in_place = bool(job.dest_dir)
    if in_place:
        output_rel_dir = job.dest_dir if job.dest_dir.endswith('/') else job.dest_dir + '/'
        output_dir     = settings.MEDIA_ROOT / output_rel_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name    = _build_inplace_name(output_dir, job.input_filename, job.output_format)
    else:
        # Convention standard {app}/{user_id}/output (cohérent avec UploadToUserPath
        # et avec l'arbre du Filemanager).
        output_rel_dir = f"converter/{user_id}/output/"
        output_dir     = settings.MEDIA_ROOT / output_rel_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name    = _build_output_name(job.input_filename, job.output_format)

    final_output_path = str(output_dir / output_name)

    # Atomic output for in-place quick convert: backends write to a temp file
    # (correct extension so ffmpeg/Pillow pick the right muxer), moved to the
    # final location only on success. Cancelling/erroring never leaves a
    # partial/corrupt file next to the user's source.
    if in_place:
        import tempfile as _tf
        _fd, output_path = _tf.mkstemp(prefix='wama_conv_', suffix=f'.{job.output_format.lower()}')
        os.close(_fd)
        os.unlink(output_path)  # backends create it themselves; we only reserved the name
    else:
        output_path = final_output_path

    # Apply quality preset (explicit options always win over preset defaults).
    from .utils.quality_presets import resolve_options
    eff_opts = resolve_options(job.media_type, job.quality_preset, job.options)

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
                quality=int(eff_opts.get('quality', 90)),
                options=eff_opts,
            )
            _set_progress(job_id, 90)

        elif media_type == 'video':
            from .backends.video_backend import convert_video
            convert_video(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                options=eff_opts,
                progress_callback=_progress,
            )

        elif media_type == 'audio':
            from .backends.audio_backend import convert_audio
            convert_audio(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                options=eff_opts,
                progress_callback=_progress,
            )

        elif media_type == 'document':
            from .backends.document_backend import convert_document
            _set_progress(job_id, 10)
            convert_document(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                options=eff_opts,
            )
            _set_progress(job_id, 90)

        elif media_type == 'archive':
            from .backends.archive_backend import convert_archive
            convert_archive(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                options=eff_opts,
                progress_callback=_progress,
            )

        else:
            raise ValueError(f"Type de média non supporté : {media_type}")

        # In-place: move the temp result to its final location next to the source.
        if in_place:
            import shutil as _sh
            _sh.move(output_path, final_output_path)

        # ── Save output file reference ────────────────────────────────────
        rel_path = f"{output_rel_dir}{output_name}"
        ConversionJob.objects.filter(pk=job_id).update(
            output_file=rel_path,
            status='DONE',
            progress=100,
            # Temps réel persisté (ProcessingTimeMixin) — même mesure que le seeding ETA ci-dessous.
            processing_seconds=_time.time() - _t0,
        )
        job.refresh_from_db()
        _set_progress(job_id, 100)
        _console(user_id, f"✓ Conversion terminée : {output_name}", level='info')
        logger.info(f"convert_media_task DONE | job_id={job_id} output={output_path}")

        # Seeding ETA : temps ∝ taille d'entrée (Mo) ; clé par type de conversion (ffmpeg, pas de modèle)
        try:
            from wama.model_manager.services.eta_estimator import record_run
            _mb = max(os.path.getsize(input_path) / 1e6, 0.01)
            record_run(f'converter:{job.media_type}:{job.output_format}', size=_mb,
                       unit='mb', process_seconds=_time.time() - _t0, load_seconds=None)
        except Exception:
            pass
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(getattr(job, 'user', None), 'Converter', output_name, True)
        except Exception:
            pass

    except Exception as exc:
        error_msg = str(exc)[:500]
        logger.exception(f"convert_media_task ERROR | job_id={job_id}: {exc}")
        # Remove the in-place temp file so no partial output lingers.
        if in_place:
            try:
                if os.path.exists(output_path):
                    os.unlink(output_path)
            except Exception:
                pass
        ConversionJob.objects.filter(pk=job_id).update(
            status='ERROR',
            error_message=error_msg,
        )
        _console(user_id, f"✗ Erreur conversion : {error_msg}", level='error')
        try:
            from wama.common.utils.notifications import notify_job
            from django.contrib.auth.models import User
            _u = User.objects.filter(pk=user_id).first()
            notify_job(_u, 'Converter', f"conversion #{job_id}", False, detail=error_msg)
        except Exception:
            pass


def _build_output_name(input_filename: str, output_format: str) -> str:
    """Replace extension with output format, ensuring uniqueness via timestamp."""
    import time
    stem = Path(input_filename).stem
    ts   = int(time.time())
    return f"{stem}_{ts}.{output_format.lower()}"


def _build_inplace_name(output_dir, input_filename: str, output_format: str) -> str:
    """Keep the original stem (no timestamp) for in-place quick convert.

    Adds ' (N)' before the extension if a file with that name already exists,
    so the source is never overwritten and successive conversions don't clash.
    """
    stem = Path(input_filename).stem
    ext  = output_format.lower()
    candidate = f"{stem}.{ext}"
    if not (Path(output_dir) / candidate).exists():
        return candidate
    n = 1
    while True:
        candidate = f"{stem} ({n}).{ext}"
        if not (Path(output_dir) / candidate).exists():
            return candidate
        n += 1
