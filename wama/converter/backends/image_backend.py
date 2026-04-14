"""
WAMA Converter — Image Backend (Pillow)

Supported conversions: jpg, jpeg, png, webp, tiff, bmp, gif, avif → jpg, png, webp, tiff, bmp, gif, avif, pdf
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Pillow format identifiers (for Image.save())
_PIL_FORMAT = {
    'jpg':  'JPEG',
    'jpeg': 'JPEG',
    'png':  'PNG',
    'webp': 'WEBP',
    'tiff': 'TIFF',
    'tif':  'TIFF',
    'bmp':  'BMP',
    'gif':  'GIF',
    'avif': 'AVIF',
    'pdf':  'PDF',
}

# Formats that require RGB (no alpha channel)
_REQUIRES_RGB = {'jpg', 'jpeg', 'bmp', 'pdf'}

# Formats that support animation (preserve if source is animated)
_SUPPORTS_ANIMATION = {'gif', 'webp'}


def convert_image(input_path: str, output_path: str, output_format: str,
                  quality: int = 85, options: dict = None) -> None:
    """
    Convert an image file to another format using Pillow.

    Args:
        input_path: Absolute path to the source image file.
        output_path: Absolute path for the output file.
        output_format: Target format key (e.g. 'jpg', 'png', 'webp', …).
        quality: JPEG/WEBP/AVIF quality (1–100). Ignored for lossless formats.
        options: Optional dict with extra params:
            - resize_w / resize_h: target width/height (px); 0 = keep aspect ratio
            - keep_metadata: bool (default False) — preserve EXIF data
    """
    from PIL import Image, ImageSequence

    if options is None:
        options = {}

    fmt_key   = output_format.lower()
    pil_fmt   = _PIL_FORMAT.get(fmt_key)
    if pil_fmt is None:
        raise ValueError(f"Format de sortie non supporté : {output_format}")

    resize_w  = int(options.get('resize_w', 0) or 0)
    resize_h  = int(options.get('resize_h', 0) or 0)

    img = Image.open(input_path)

    # --- Handle animated GIFs / WebPs ---
    if hasattr(img, 'n_frames') and img.n_frames > 1 and fmt_key in _SUPPORTS_ANIMATION:
        frames = []
        for frame in ImageSequence.Iterator(img):
            frame = frame.copy()
            if resize_w or resize_h:
                frame = _resize_frame(frame, resize_w, resize_h)
            if fmt_key in _REQUIRES_RGB:
                frame = frame.convert('RGB')
            frames.append(frame)

        save_kwargs = _build_save_kwargs(fmt_key, quality, options)
        save_kwargs['save_all'] = True
        save_kwargs['append_images'] = frames[1:]
        if hasattr(img, 'info') and 'duration' in img.info:
            save_kwargs['duration'] = img.info['duration']
        save_kwargs['loop'] = 0
        frames[0].save(output_path, pil_fmt, **save_kwargs)
        return

    # --- Single frame ---
    if resize_w or resize_h:
        img = _resize_frame(img, resize_w, resize_h)

    if fmt_key in _REQUIRES_RGB and img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    # EXIF passthrough
    exif_bytes = None
    if options.get('keep_metadata') and hasattr(img, 'info') and 'exif' in img.info:
        exif_bytes = img.info['exif']

    save_kwargs = _build_save_kwargs(fmt_key, quality, options)
    if exif_bytes and fmt_key in ('jpg', 'jpeg', 'webp'):
        save_kwargs['exif'] = exif_bytes

    img.save(output_path, pil_fmt, **save_kwargs)
    logger.info(f"Image convertie : {input_path} → {output_path} [{fmt_key.upper()}]")


def _resize_frame(img, target_w: int, target_h: int):
    """Resize preserving aspect ratio when only one dimension is given."""
    from PIL import Image
    orig_w, orig_h = img.size
    if target_w and target_h:
        new_size = (target_w, target_h)
    elif target_w:
        ratio   = target_w / orig_w
        new_size = (target_w, max(1, int(orig_h * ratio)))
    else:
        ratio   = target_h / orig_h
        new_size = (max(1, int(orig_w * ratio)), target_h)
    return img.resize(new_size, Image.LANCZOS)


def _build_save_kwargs(fmt_key: str, quality: int, options: dict) -> dict:
    """Build Pillow save() keyword arguments for a given format."""
    kwargs = {}
    if fmt_key in ('jpg', 'jpeg'):
        kwargs['quality']   = quality
        kwargs['optimize']  = True
        kwargs['progressive'] = True
    elif fmt_key == 'webp':
        kwargs['quality']   = quality
        kwargs['method']    = 4
    elif fmt_key == 'avif':
        kwargs['quality']   = quality
    elif fmt_key == 'png':
        compress = options.get('png_compress', 6)
        kwargs['compress_level'] = int(compress)
    elif fmt_key == 'pdf':
        kwargs['resolution'] = options.get('pdf_dpi', 150)
    return kwargs
