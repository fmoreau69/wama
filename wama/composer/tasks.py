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

    # Garde anti-boucle-de-crash (brique COMMUNE) : message `redelivered` = worker mort
    # sans acquitter (freeze/panic machine) → ne PAS rejouer l'exécution qui l'a tué.
    from wama.common.utils.process_control import refuse_crash_redelivery
    if refuse_crash_redelivery(self, gen, error_field='error_message'):
        logger.warning(f"[Composer] Generation #{generation_id}: reprise après crash refusée — relancer manuellement.")
        return

    user_id = gen.user_id

    # Entrée URL déclarative (WAMA_INGEST du modèle) : télécharge source_url →
    # melody_reference si la cible est vide. AVANT la résolution auto (la présence
    # d'une mélodie peut orienter le choix du modèle).
    try:
        from wama.common.utils.source_ingest import ensure_local_input
        ensure_local_input(gen, console=lambda m: _console(user_id, m))
    except Exception as exc:
        logger.warning(f"[Composer] ensure_local_input({generation_id}) : {exc}")

    if gen.model in ('auto-music', 'auto-sfx'):
        from wama.composer.utils.auto_model import resolve_auto_model
        gen.model = resolve_auto_model(gen)
        gen.save(update_fields=['model'])
        _console(user_id, f"[Composer] 🧠 Auto → {gen.model} (capacités + VRAM libre au lancement)")
    # Durée plafonnée par la capacité du modèle FINAL (source unique = clamp_duration : schéma +
    # max_duration du modèle). Seul point où le vrai modèle est connu (auto-* résolu ci-dessus).
    from wama.composer.utils.model_config import clamp_duration
    _capped = clamp_duration(gen.duration, gen.model)
    if _capped != gen.duration:
        _console(user_id, f"[Composer] Durée {gen.duration:g}s → {_capped:g}s (max du modèle {gen.model})")
        gen.duration = _capped
        gen.save(update_fields=['duration'])
    _console(user_id, f"[Composer] Démarrage : {gen.model} — {gen.prompt[:60]}…")

    import time as _time
    _t0 = _time.time()  # chrono pour le seeding ETA

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
        # Brique COMMUNE de nommage (2026-08-25). ⚠ Le rendu CHANGE ici, volontairement
        # (arbitrage Fabien : l'homogénéité prime sur le portage à l'identique) :
        # `{modèle}_{uuid8}.wav` → `audio{id}_{modèle}.wav`. L'uuid était unique mais MUET —
        # il ne rattachait le fichier à aucune card, alors que le composer était la seule app
        # à prompt sans identifiant ni index dans son nom.
        from wama.common.utils.output_naming import compose_output_name
        output_filename = compose_output_name(app='composer', model=gen.model,
                                              item_id=gen.id, ext='.wav')
        output_abs_path = os.path.join(output_dir, output_filename)
        output_rel_path = os.path.relpath(output_abs_path, settings.MEDIA_ROOT)

        melody_abs = None
        if gen.melody_reference:
            melody_abs = os.path.join(settings.MEDIA_ROOT, gen.melody_reference.name)

        # PromptPipeline (§16.6) : MusicGen/AudioCraft est entraîné en anglais → un prompt FR
        # est traduit avant génération (métadonnée PROMPT_TARGETS['composer'], KIND generative).
        # Résource-safe : passthrough si déjà EN / modèle multilingue.
        from wama.common.utils.app_metadata import process_prompt_for
        routed_prompt = process_prompt_for(
            'composer', 'prompt', gen.prompt,
            instance=gen, user=gen.user, console=lambda m: _console(user_id, m),
        )

        backend = AudioCraftBackend()
        from wama.common.utils.preview_utils import emit_streaming_peaks, clear_partial
        backend.generate(
            model_id=gen.model,
            prompt=routed_prompt,
            duration=gen.duration,
            output_path=output_abs_path,
            melody_path=melody_abs,
            progress_callback=lambda p: _set_progress(generation_id, p),
            # Preview « pendant » (COMMUN) : publie l'audio produit → onde de la face during.
            # Dormant tant que composer ne déclare pas la capacité during_preview (rôle manifeste).
            on_audio=lambda arr, sr: emit_streaming_peaks('composer', generation_id, arr, sr),
        )

        gen.refresh_from_db()
        gen.audio_output = output_rel_path
        # Output-format conversion (Phase 3 élargie)
        _fmt = (getattr(gen, 'output_format', '') or 'original').lower()
        if _fmt not in ('', 'original', 'wav'):
            try:
                from wama.converter.utils.inline_convert import apply_inline_conversion
                new_path = apply_inline_conversion(
                    output_abs_path, _fmt,
                    getattr(gen, 'output_quality', 'balanced') or 'balanced',
                )
                gen.audio_output = os.path.relpath(new_path, settings.MEDIA_ROOT).replace('\\', '/')
            except Exception as _conv_err:
                _console(user_id, f"[Composer] conversion format échouée: {_conv_err}", level='warning')
        gen.status = 'SUCCESS'
        gen.progress = 100
        gen.processing_seconds = _time.time() - _t0  # persiste le temps réel (déjà mesuré pour l'ETA)
        gen.save(update_fields=['audio_output', 'status', 'progress', 'processing_seconds'])
        clear_partial('composer', generation_id)   # fin du « pendant » → la face SORTIE prend le relais

        _console(user_id, f"[Composer] ✓ Terminé : {output_filename}", level='info')

        # Seeding ETA : génération audio → temps ∝ durée produite (clé par modèle)
        try:
            from wama.model_manager.services.eta_estimator import record_run
            record_run(f'composer:{gen.model}', size=float(gen.duration or 0),
                       unit='audio_sec', process_seconds=gen.processing_seconds, load_seconds=None)
        except Exception:
            pass

        try:
            from wama.common.utils.notifications import notify_job
            notify_job(getattr(gen, 'user', None), 'Composer',
                       getattr(gen, 'name', '') or output_filename, True)
        except Exception:
            pass

    except Exception as exc:
        logger.exception(f"[Composer] Erreur generation {generation_id}: {exc}")
        _set_progress(generation_id, 0)
        try:
            from wama.common.utils.preview_utils import clear_partial
            clear_partial('composer', generation_id)   # échec → pas de partiel obsolète
        except Exception:
            pass
        try:
            gen.refresh_from_db()
            gen.status = 'FAILURE'
            gen.error_message = str(exc)[:1000]
            gen.save(update_fields=['status', 'error_message'])
        except Exception:
            pass
        _console(user_id, f"[Composer] ✗ Erreur : {exc}", level='error')
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(getattr(gen, 'user', None), 'Composer',
                       getattr(gen, 'name', '') or f"composition #{getattr(gen, 'id', '')}", False, detail=str(exc))
        except Exception:
            pass
