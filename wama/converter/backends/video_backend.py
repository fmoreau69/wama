"""
WAMA Converter — Video Backend (FFmpeg)

Supported conversions: mp4, avi, mov, mkv, webm, flv, mpg, mpeg, 3gp, wmv, ts, m4v
→ mp4, webm, avi, mov, mkv, gif, mp3, wav, ogg
"""

import logging
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)


def _get_ffmpeg() -> str:
    """Return the ffmpeg binary path (reuses common video_utils logic)."""
    from wama.common.utils.video_utils import _get_ffmpeg_path
    ffmpeg = _get_ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg introuvable. Installez FFmpeg et assurez-vous qu'il est dans le PATH."
        )
    return ffmpeg


# Output format → FFmpeg container + codec presets
_FORMAT_PRESETS = {
    'mp4':  {'container': 'mp4',  'vcodec': 'libx264',  'acodec': 'aac',       'extra': ['-movflags', '+faststart']},
    'webm': {'container': 'webm', 'vcodec': 'libvpx-vp9','acodec': 'libopus',  'extra': []},
    'avi':  {'container': 'avi',  'vcodec': 'libxvid',  'acodec': 'mp3',        'extra': []},
    'mov':  {'container': 'mov',  'vcodec': 'libx264',  'acodec': 'aac',        'extra': ['-movflags', '+faststart']},
    'mkv':  {'container': 'matroska', 'vcodec': 'libx264', 'acodec': 'aac',    'extra': []},
    # Audio extraction formats
    'mp3':  {'container': 'mp3',  'vcodec': None,        'acodec': 'libmp3lame','extra': ['-q:a', '2']},
    'wav':  {'container': 'wav',  'vcodec': None,        'acodec': 'pcm_s16le', 'extra': []},
    'ogg':  {'container': 'ogg',  'vcodec': None,        'acodec': 'libvorbis', 'extra': []},
    # Animated GIF (special handling)
    'gif':  {'container': 'gif',  'vcodec': None,        'acodec': None,        'extra': []},
}


def convert_video(input_path: str, output_path: str, output_format: str,
                  options: dict = None,
                  progress_callback: Optional[Callable[[int], None]] = None) -> None:
    """
    Convert a video file using FFmpeg.

    Args:
        input_path: Source video file path.
        output_path: Output file path.
        output_format: Target format key (e.g. 'mp4', 'gif', 'mp3', …).
        options: Optional dict:
            - fps: target frame rate (float or int)
            - width / height: target resolution (0 = keep aspect)
            - video_quality: CRF value for libx264/vp9 (0–51, lower = better; default 23)
            - audio_bitrate: e.g. '192k'
            - gif_fps: FPS for GIF output (default 12)
            - gif_width: width for GIF output (default 480)
            - no_audio: bool — strip audio track
        progress_callback: Called with integer 0-100 during conversion.
    """
    ffmpeg    = _get_ffmpeg()
    fmt_key   = output_format.lower()
    preset    = _FORMAT_PRESETS.get(fmt_key)
    if preset is None:
        raise ValueError(f"Format vidéo non supporté : {output_format}")

    if options is None:
        options = {}

    if fmt_key == 'gif':
        _convert_to_gif(ffmpeg, input_path, output_path, options, progress_callback)
        return

    cmd = [ffmpeg, '-y', '-i', input_path]

    # Video codec
    if preset['vcodec']:
        cmd += ['-c:v', preset['vcodec']]
        crf = options.get('video_quality', 23)
        cmd += ['-crf', str(crf)]
        cmd += ['-preset', 'medium']
    else:
        cmd += ['-vn']  # audio-only

    # Audio codec
    if preset['acodec'] and not options.get('no_audio'):
        cmd += ['-c:a', preset['acodec']]
        if options.get('audio_bitrate'):
            cmd += ['-b:a', options['audio_bitrate']]
    elif not options.get('no_audio') and preset['vcodec']:
        cmd += ['-c:a', preset['acodec']]
    else:
        cmd += ['-an']

    # Frame rate
    if options.get('fps'):
        cmd += ['-r', str(options['fps'])]

    # Resolution
    vf_parts = _build_vf(options)
    if vf_parts:
        cmd += ['-vf', ','.join(vf_parts)]

    # Extra container flags
    cmd += preset.get('extra', [])

    cmd.append(output_path)

    logger.info(f"FFmpeg commande : {' '.join(cmd)}")
    _run_ffmpeg(cmd, input_path, progress_callback)
    logger.info(f"Vidéo convertie : {input_path} → {output_path} [{fmt_key.upper()}]")


def _convert_to_gif(ffmpeg: str, input_path: str, output_path: str,
                    options: dict, progress_callback):
    """Two-pass GIF conversion: palette generation + dithering."""
    import tempfile, os
    fps   = options.get('gif_fps', 12)
    width = options.get('gif_width', 480)
    vf_palette = f"fps={fps},scale={width}:-1:flags=lanczos,palettegen"
    vf_gif     = f"fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer"

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        palette_path = f.name

    try:
        # Pass 1: generate palette
        cmd1 = [ffmpeg, '-y', '-i', input_path, '-vf', vf_palette, palette_path]
        _run_ffmpeg(cmd1, input_path, None)

        # Pass 2: apply palette
        cmd2 = [ffmpeg, '-y', '-i', input_path, '-i', palette_path,
                '-lavfi', vf_gif, output_path]
        _run_ffmpeg(cmd2, input_path, progress_callback)
    finally:
        if os.path.exists(palette_path):
            os.unlink(palette_path)

    logger.info(f"GIF animé créé : {input_path} → {output_path}")


def _build_vf(options: dict) -> list:
    """Build FFmpeg -vf filter string parts from options."""
    parts = []
    w = options.get('width', 0)
    h = options.get('height', 0)
    if w and h:
        parts.append(f"scale={w}:{h}")
    elif w:
        parts.append(f"scale={w}:-2")
    elif h:
        parts.append(f"scale=-2:{h}")
    return parts


def _run_ffmpeg(cmd: list, input_path: str,
                progress_callback: Optional[Callable[[int], None]]) -> None:
    """Execute FFmpeg, streaming stderr for progress parsing."""
    import re
    duration_sec = _probe_duration(input_path)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stderr_lines = []
    for line in proc.stderr:
        stderr_lines.append(line)
        if progress_callback and duration_sec and 'time=' in line:
            m = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
            if m:
                h, mn, s, cs = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                elapsed = h * 3600 + mn * 60 + s + cs / 100.0
                pct = min(99, int(elapsed / duration_sec * 100))
                progress_callback(pct)

    proc.wait()
    if proc.returncode != 0:
        stderr_text = ''.join(stderr_lines[-20:])
        raise RuntimeError(f"FFmpeg a échoué (code {proc.returncode}):\n{stderr_text}")


def _probe_duration(input_path: str) -> Optional[float]:
    """Use ffprobe to get video duration in seconds."""
    from wama.common.utils.video_utils import _get_ffmpeg_path
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, '-v', 'quiet', '-print_format', 'json',
             '-show_format', input_path],
            capture_output=True, text=True, timeout=15,
        )
        import json
        data = json.loads(result.stdout)
        return float(data.get('format', {}).get('duration', 0)) or None
    except Exception:
        return None
