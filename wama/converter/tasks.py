"""
WAMA Converter — Celery Tasks

Tâche principale : convert_media_task
Routing : CPU-bound → queue 'default' (pas de GPU requis — mais les options cross-app
(upscale, audio_enhance) peuvent charger des modèles GPU depuis cette tâche, d'où la garde
anti-boucle-de-crash du squelette commun).

Squelette (gardes, progress, chrono, statuts, ETA, console, notifications) = brique COMMUNE
`common/utils/task_skeleton.run_item_task` (marche A2, route §10.3). Ce fichier ne porte plus
que la GLU du converter : routage de format, presets qualité, nommage de sortie, quick-convert
in-place atomique.
"""
import logging
import os
from pathlib import Path

from celery import shared_task

from .models import ConversionJob

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def convert_media_task(self, job_id: int):
    from wama.common.utils.task_skeleton import run_item_task
    run_item_task(self, app_id='converter', model=ConversionJob, item_id=job_id,
                  process=_convert, ingest_derive=_derive_media_type,
                  notify_label='Converter')


def _derive_media_type(inst, path, fname):
    """Hook `derive` de l'ingest URL (WAMA_INGEST) : renseigne media_type au téléchargement."""
    if inst.media_type:
        return []
    from .utils.format_router import detect_media_type
    inst.media_type = detect_media_type(fname) or ''
    return ['media_type']


def _convert(job, ctx):
    """GLU converter (contrat task_skeleton) : résout chemins et options, dispatche au backend
    du type de média, déplace atomiquement le résultat in-place. Une exception = FAILURE (le
    squelette gère statut/console/notification) ; le fichier temporaire in-place est nettoyé
    ICI (le squelette ne connaît pas les artefacts de la glu)."""
    from django.conf import settings

    ctx.console(f"Conversion démarrée : {job.input_filename} → .{job.output_format}")
    input_path = job.input_file.path

    # Output location:
    #   - dest_dir set (quick convert in-place) → write next to the source,
    #     keep the original stem, add a numeric suffix on collision.
    #   - otherwise → default converter/output/<user>/ with a timestamped name.
    in_place = bool(job.dest_dir)
    if in_place:
        output_rel_dir = job.dest_dir if job.dest_dir.endswith('/') else job.dest_dir + '/'
        output_dir = settings.MEDIA_ROOT / output_rel_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = _build_inplace_name(output_dir, job.input_filename, job.output_format)
    else:
        # Convention standard {app}/{user_id}/output (cohérent avec UploadToUserPath
        # et avec l'arbre du Filemanager).
        output_rel_dir = f"converter/{job.user_id}/output/"
        output_dir = settings.MEDIA_ROOT / output_rel_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = _build_output_name(job.input_filename, job.output_format)

    final_output_path = str(output_dir / output_name)

    # Atomic output for in-place quick convert: backends write to a temp file
    # (correct extension so ffmpeg/Pillow pick the right muxer), moved to the
    # final location only on success. Cancelling/erroring never leaves a
    # partial/corrupt file next to the user's source.
    if in_place:
        import tempfile as _tf
        _fd, output_path = _tf.mkstemp(prefix='wama_conv_',
                                       suffix=f'.{job.output_format.lower()}')
        os.close(_fd)
        os.unlink(output_path)  # backends create it themselves; we only reserved the name
    else:
        output_path = final_output_path

    # Apply quality preset (explicit options always win over preset defaults).
    from .utils.quality_presets import resolve_options
    eff_opts = resolve_options(job.media_type, job.quality_preset, job.options)

    # Aperçu « PENDANT » (brique commune, 2026-08-13) : hors in-place, ffmpeg écrit la sortie
    # progressivement sous MEDIA — l'URL partielle est lisible PENDANT la conversion pour les
    # formats à décodage en flux : tout l'AUDIO (mp3/wav/ogg…), et la VIDÉO en conteneur
    # streamable (webm/mkv/ts — un mp4/mov partiel est illisible, `moov` écrit à la FIN).
    # Documents/images/archives : partiel structurellement illisible, et conversions courtes.
    # Best-effort ; retirée en fin de glu (les deux issues).
    _streamable = (job.media_type == 'audio'
                   or (job.media_type == 'video'
                       and (job.output_format or '').lower() in ('webm', 'mkv', 'ts')))
    if not in_place and _streamable:
        from wama.common.utils.preview_utils import publish_partial
        publish_partial('converter', job.pk, settings.MEDIA_URL + output_rel_dir + output_name)

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
            ctx.progress(90)

        elif media_type == 'video':
            from .backends.video_backend import convert_video
            convert_video(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                options=eff_opts,
                progress_callback=ctx.progress,
            )

        elif media_type == 'audio':
            from .backends.audio_backend import convert_audio
            convert_audio(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                options=eff_opts,
                progress_callback=ctx.progress,
            )

        elif media_type == 'document':
            from .backends.document_backend import convert_document
            ctx.progress(10)
            convert_document(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                options=eff_opts,
            )
            ctx.progress(90)

        elif media_type == 'archive':
            from .backends.archive_backend import convert_archive
            convert_archive(
                input_path=input_path,
                output_path=output_path,
                output_format=job.output_format,
                options=eff_opts,
                progress_callback=ctx.progress,
            )

        else:
            raise ValueError(f"Type de média non supporté : {media_type}")
    except Exception:
        # Remove the in-place temp file so no partial output lingers.
        if in_place:
            try:
                if os.path.exists(output_path):
                    os.unlink(output_path)
            except Exception:
                pass
        _clear_during(job)
        raise

    # In-place: move the temp result to its final location next to the source.
    if in_place:
        import shutil as _sh
        _sh.move(output_path, final_output_path)

    _clear_during(job)

    # Seeding ETA : temps ∝ taille d'entrée (Mo) ; clé par type de conversion (ffmpeg, pas de modèle)
    _mb = max(os.path.getsize(input_path) / 1e6, 0.01)
    return {
        'fields': {'output_file': f"{output_rel_dir}{output_name}"},
        'eta': (f'converter:{job.media_type}:{job.output_format}', _mb, 'mb'),
        'label': output_name,
    }


def _clear_during(job):
    """Fin du « pendant » (succès OU échec) : la face SORTIE prend le relais. Best-effort."""
    try:
        from wama.common.utils.preview_utils import clear_partial
        clear_partial('converter', job.pk)
    except Exception:
        pass


def _build_output_name(input_filename: str, output_format: str) -> str:
    """Replace extension with output format, ensuring uniqueness via timestamp."""
    import time
    stem = Path(input_filename).stem
    ts = int(time.time())
    return f"{stem}_{ts}.{output_format.lower()}"


def _build_inplace_name(output_dir, input_filename: str, output_format: str) -> str:
    """Keep the original stem (no timestamp) for in-place quick convert.

    Adds ' (N)' before the extension if a file with that name already exists,
    so the source is never overwritten and successive conversions don't clash.
    """
    stem = Path(input_filename).stem
    ext = output_format.lower()
    candidate = f"{stem}.{ext}"
    if not (Path(output_dir) / candidate).exists():
        return candidate
    n = 1
    while True:
        candidate = f"{stem} ({n}).{ext}"
        if not (Path(output_dir) / candidate).exists():
            return candidate
        n += 1
