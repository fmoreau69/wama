"""
WAMA Converter — Inline conversion helper

Lets any app convert its result to a user-chosen output format + quality preset
at the end of its Celery task, WITHOUT going through the Converter queue.

    new_path = apply_inline_conversion(result_path, output_format='webp',
                                       quality_preset='balanced')

Reuses the Converter backends + quality presets (single source of truth).
Returns the original path unchanged when output_format is falsy/'original' or the
target is unsupported for that media type; a target equal to the current format
re-encodes in place with the quality preset.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def apply_inline_conversion(src_path: str, output_format: str,
                            quality_preset: str = 'balanced',
                            extra_options: dict | None = None,
                            delete_original: bool = True) -> str:
    """Convert `src_path` to `output_format` next to it; return the new path.

    No-op (returns src_path) if output_format is empty/'original' or is unsupported for
    the detected media type. When it equals the current extension, the file is RE-ENCODED
    with the quality preset and replaces the source in place (2026-09-23).
    """
    fmt = (output_format or '').strip().lower()
    if not fmt or fmt == 'original':
        return src_path

    from .format_router import detect_media_type, get_output_formats
    from .quality_presets import resolve_options

    p = Path(src_path)
    if not p.exists():
        return src_path

    media_type = detect_media_type(p.name)
    if media_type is None:
        logger.warning(f"[inline_convert] type inconnu pour {p.name}, conversion ignorée")
        return src_path
    if fmt not in get_output_formats(media_type):
        logger.warning(f"[inline_convert] format '{fmt}' non supporté pour {media_type}, ignoré")
        return src_path
    # MÊME format que la source : on RÉENCODE quand même (2026-09-23). Choisir « .MP4 + Web »
    # pour une vidéo déjà en MP4 est une demande de QUALITÉ, pas de conteneur — la rendre
    # inopérante faisait mentir le réglage. Écrit à côté, puis substitué à la source.
    same_format = p.suffix.lower().lstrip('.') == fmt
    dest = str(p.with_name(p.stem + '.requalified.' + fmt)) if same_format \
        else str(p.with_suffix('.' + fmt))
    if os.path.abspath(dest) == os.path.abspath(src_path):
        return src_path

    opts = resolve_options(media_type, quality_preset, extra_options or {})

    if media_type == 'image':
        from ..backends.image_backend import convert_image
        convert_image(src_path, dest, fmt, quality=int(opts.get('quality', 90)), options=opts)
    elif media_type == 'video':
        from ..backends.video_backend import convert_video
        convert_video(src_path, dest, fmt, options=opts)
    elif media_type == 'audio':
        from ..backends.audio_backend import convert_audio
        convert_audio(src_path, dest, fmt, options=opts)
    elif media_type == 'document':
        from ..backends.document_backend import convert_document
        convert_document(src_path, dest, fmt, options=opts)
    elif media_type == 'archive':
        from ..backends.archive_backend import convert_archive
        convert_archive(src_path, dest, fmt, options=opts)
    else:
        return src_path

    if not os.path.exists(dest):
        logger.error(f"[inline_convert] sortie introuvable {dest}, conserve l'original")
        return src_path

    if same_format:
        if not delete_original:
            return dest
        os.replace(dest, src_path)
        logger.info(f"[inline_convert] {p.name} réencodé (preset={quality_preset})")
        return src_path

    if delete_original:
        try:
            os.unlink(src_path)
        except Exception:
            pass

    logger.info(f"[inline_convert] {p.name} → {Path(dest).name} (preset={quality_preset})")
    return dest
