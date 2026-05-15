"""
Browser-compatibility helpers for video files.

These are *infrastructure* primitives — sync, blocking, no progress UI.
They live in ``wama/common/`` because multiple apps need to take a video
file of unknown codec and make it playable in a ``<video>`` HTML element
(typical scenario: user drags an iPhone HEVC clip into an upload zone,
the browser can't preview it, we need it in H.264).

For *user-driven* conversions with progress UI, format selection, batch,
etc., go through the Converter app instead — Converter will eventually
consume these same helpers as its trivial H.264 backend, with async
queueing on top.

Public surface
--------------
- ``BROWSER_COMPATIBLE_CODECS``  : frozenset of codec names browsers play
- ``get_video_codec(path)``      : ffprobe wrapper, returns codec name lowercased
- ``is_browser_compatible_codec(codec)`` : set membership check
- ``ensure_h264(path)``          : if codec is not browser-compatible, re-encode
                                   to H.264 .mp4 (promotes .avi → .mp4 when needed)
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional, Union

logger = logging.getLogger(__name__)


# Codecs HTML5 ``<video>`` can play across Chrome/Firefox/Safari/Edge (modern
# versions). HEVC is acceptable in Safari and recent Chrome; the others are
# universally supported. AVI/MJPG/mp4v/ProRes/DNxHD all need re-encoding.
BROWSER_COMPATIBLE_CODECS: frozenset[str] = frozenset({
    'h264', 'hevc', 'vp8', 'vp9', 'av1',
})


def get_video_codec(file_path: str, *, timeout: int = 10) -> Optional[str]:
    """
    Return the codec name of the first video stream, lowercased
    (e.g. ``'h264'``, ``'mjpeg'``, ``'mpeg4'``). Returns ``None`` when
    ffprobe is unavailable, the file is unreadable, or there is no video
    stream.
    """
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name',
             '-of', 'csv=p=0', file_path],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        logger.warning("ffprobe not found — cannot detect codec")
        return None
    except Exception as exc:
        logger.warning(f"Codec detection failed for {file_path}: {exc}")
        return None
    codec = (result.stdout or '').strip().lower()
    return codec or None


def is_browser_compatible_codec(codec: Optional[str]) -> bool:
    """True when the codec is one HTML5 ``<video>`` can play directly."""
    return bool(codec) and codec.lower() in BROWSER_COMPATIBLE_CODECS


def ensure_h264(file_path: str, *, timeout: int = 1800) -> Union[bool, str]:
    """
    Ensure a video is browser-compatible. When the codec is already in
    ``BROWSER_COMPATIBLE_CODECS``, the function is a no-op. Otherwise the
    file is re-encoded to H.264 (libx264, CRF 18 = visually lossless) in
    place, and the result is returned as a path.

    The output container is promoted from ``.avi`` to ``.mp4`` when needed
    (typical scenario : OpenCV MJPG fallback that wrote a ``.avi`` whose
    extension lies about the actual codec). The original ``.avi`` is
    removed after successful re-encode.

    Returns
    -------
    - ``False``  : no conversion was needed *or* the conversion failed (the
                   caller can keep using the original path).
    - ``str``    : the final file path. May differ from ``file_path`` if the
                   extension was promoted ; callers should update DB pointers
                   accordingly.
    """
    codec = get_video_codec(file_path)
    if codec is None:
        # ffprobe absent or file unreadable — bail out, caller decides
        return False
    if is_browser_compatible_codec(codec):
        return False

    base, ext = os.path.splitext(file_path)
    target_path = base + '.mp4' if ext.lower() == '.avi' else file_path

    logger.info(
        f"Video codec '{codec}' not browser-compatible, re-encoding to H.264: "
        f"{file_path} → {target_path}"
    )

    tmp_path = target_path + '.h264.tmp.mp4'
    try:
        proc = subprocess.run(
            ['ffmpeg', '-i', file_path,
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
             '-pix_fmt', 'yuv420p', '-c:a', 'copy',
             '-movflags', '+faststart',
             tmp_path, '-y'],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        logger.warning("ffmpeg not found — skipping re-encode")
        return False
    except Exception as exc:
        logger.warning(f"ffmpeg invocation failed: {exc}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False

    if proc.returncode != 0:
        logger.error(f"ffmpeg re-encode failed: {(proc.stderr or '')[-500:]}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False

    os.replace(tmp_path, target_path)

    # If the extension changed, drop the legacy file.
    if target_path != file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError as rm_err:
            logger.warning(f"Could not remove original {file_path}: {rm_err}")

    logger.info(f"Re-encoded to H.264: {target_path}")
    return target_path
