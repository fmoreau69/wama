"""
Composer Celery Tasks — Music and SFX generation via AudioCraft.
"""

import logging
import os

from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections

from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)

PROGRESS_CACHE_TIMEOUT = 3600  # 1 hour


def _set_progress(gen_id: int, percent: int) -> None:
    cache.set(f'composer_progress_{gen_id}', percent, timeout=PROGRESS_CACHE_TIMEOUT)
    from wama.composer.models import ComposerGeneration
    ComposerGeneration.objects.filter(pk=gen_id).update(progress=percent)


def _console(user_id: int, message: str, level: str = 'info') -> None:
    push_console_line(user_id, message, level=level, app='composer')


@shared_task(bind=True)
def compose_task(self, generation_id: int):
    """Generate music or SFX for a ComposerGeneration instance."""
    close_old_connections()

    from wama.composer.models import ComposerGeneration

    try:
        gen = ComposerGeneration.objects.get(id=generation_id)
    except ComposerGeneration.DoesNotExist:
        logger.error(f"[Composer] Generation {generation_id} introuvable")
        return

    user_id = gen.user_id
    _console(user_id, f"[Composer] Démarrage : {gen.model} — {gen.prompt[:60]}…")

    gen.status = 'RUNNING'
    gen.task_id = self.request.id
    gen.progress = 0
    gen.error_message = None
    gen.save(update_fields=['status', 'task_id', 'progress', 'error_message'])

    try:
        from wama.composer.backends.audiocraft_backend import AudioCraftBackend

        # Build output path
        import uuid
        from django.conf import settings
        output_dir = os.path.join(
            settings.MEDIA_ROOT,
            'composer', str(gen.user_id), 'output',
        )
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"{gen.model}_{uuid.uuid4().hex[:8]}.wav"
        output_abs_path = os.path.join(output_dir, output_filename)
        output_rel_path = os.path.relpath(output_abs_path, settings.MEDIA_ROOT)

        melody_abs = None
        if gen.melody_reference:
            melody_abs = os.path.join(settings.MEDIA_ROOT, gen.melody_reference.name)

        backend = AudioCraftBackend()
        backend.generate(
            model_id=gen.model,
            prompt=gen.prompt,
            duration=gen.duration,
            output_path=output_abs_path,
            melody_path=melody_abs,
            progress_callback=lambda p: _set_progress(generation_id, p),
        )

        gen.refresh_from_db()
        gen.audio_output = output_rel_path
        gen.status = 'SUCCESS'
        gen.progress = 100
        gen.save(update_fields=['audio_output', 'status', 'progress'])

        _console(user_id, f"[Composer] ✓ Terminé : {output_filename}", level='info')

    except Exception as exc:
        logger.exception(f"[Composer] Erreur generation {generation_id}: {exc}")
        _set_progress(generation_id, 0)
        try:
            gen.refresh_from_db()
            gen.status = 'FAILURE'
            gen.error_message = str(exc)[:1000]
            gen.save(update_fields=['status', 'error_message'])
        except Exception:
            pass
        _console(user_id, f"[Composer] ✗ Erreur : {exc}", level='error')
