"""
WAMA Converter — Audio Backend (FFmpeg)

Supported conversions: mp3, wav, flac, ogg, m4a, aac, opus, wma, aiff, aif
→ mp3, wav, flac, ogg, m4a, aac, opus
"""

import logging
import subprocess
from typing import Optional, Callable

logger = logging.getLogger(__name__)


# Output format → FFmpeg codec + container settings
_AUDIO_PRESETS = {
    'mp3':  {'acodec': 'libmp3lame', 'container': 'mp3',  'quality_flag': '-q:a',  'default_quality': '2'},
    'wav':  {'acodec': 'pcm_s16le',  'container': 'wav',  'quality_flag': None,    'default_quality': None},
    'flac': {'acodec': 'flac',       'container': 'flac', 'quality_flag': None,    'default_quality': None},
    'ogg':  {'acodec': 'libvorbis',  'container': 'ogg',  'quality_flag': '-q:a',  'default_quality': '5'},
    'm4a':  {'acodec': 'aac',        'container': 'ipod', 'quality_flag': '-b:a',  'default_quality': '192k'},
    'aac':  {'acodec': 'aac',        'container': 'adts', 'quality_flag': '-b:a',  'default_quality': '192k'},
    'opus': {'acodec': 'libopus',    'container': 'opus', 'quality_flag': '-b:a',  'default_quality': '128k'},
}


def convert_audio(input_path: str, output_path: str, output_format: str,
                  options: dict = None,
                  progress_callback: Optional[Callable[[int], None]] = None) -> None:
    """
    Convert an audio file using FFmpeg.

    Args:
        input_path: Source audio file path.
        output_path: Output file path.
        output_format: Target format key (e.g. 'mp3', 'flac', 'opus', …).
        options: Optional dict:
            - audio_bitrate: e.g. '192k' (overrides default_quality for bitrate-based codecs)
            - audio_quality: e.g. '2' (overrides default_quality for VBR codecs like mp3/vorbis)
            - sample_rate: e.g. 44100, 48000
            - channels: 1 (mono) or 2 (stereo)
            - normalize: bool — apply loudnorm filter
        progress_callback: Called with integer 0–100.
    """
    from wama.common.utils.video_utils import _get_ffmpeg_path
    ffmpeg = _get_ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("FFmpeg introuvable. Installez FFmpeg et assurez-vous qu'il est dans le PATH.")

    if options is None:
        options = {}

    fmt_key = output_format.lower()
    preset  = _AUDIO_PRESETS.get(fmt_key)
    if preset is None:
        raise ValueError(f"Format audio non supporté : {output_format}")

    cmd = [ffmpeg, '-y', '-i', input_path]

    # Audio codec
    cmd += ['-c:a', preset['acodec']]

    # Quality / bitrate
    if options.get('audio_bitrate') and preset['quality_flag']:
        cmd += [preset['quality_flag'], options['audio_bitrate']]
    elif options.get('audio_quality') and preset['quality_flag']:
        cmd += [preset['quality_flag'], str(options['audio_quality'])]
    elif preset['quality_flag'] and preset['default_quality']:
        cmd += [preset['quality_flag'], preset['default_quality']]

    # Sample rate
    if options.get('sample_rate'):
        cmd += ['-ar', str(options['sample_rate'])]

    # Channels
    if options.get('channels'):
        cmd += ['-ac', str(options['channels'])]

    # Loudness normalization (EBU R128)
    af_parts = []
    if options.get('normalize'):
        af_parts.append('loudnorm=I=-23:TP=-1:LRA=7')
    if af_parts:
        cmd += ['-af', ','.join(af_parts)]

    # No video stream
    cmd += ['-vn']

    # Container format
    cmd += ['-f', preset['container']]
    cmd.append(output_path)

    logger.info(f"FFmpeg audio commande : {' '.join(cmd)}")
    _run_ffmpeg_audio(cmd, input_path, progress_callback)
    logger.info(f"Audio converti : {input_path} → {output_path} [{fmt_key.upper()}]")


def _run_ffmpeg_audio(cmd: list, input_path: str,
                      progress_callback: Optional[Callable[[int], None]]) -> None:
    """Execute FFmpeg for audio, parsing stderr for progress."""
    import re
    duration_sec = _probe_audio_duration(input_path)

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
        raise RuntimeError(f"FFmpeg audio a échoué (code {proc.returncode}):\n{stderr_text}")


def _probe_audio_duration(input_path: str) -> Optional[float]:
    """Get audio duration in seconds via ffprobe."""
    import shutil, json
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, '-v', 'quiet', '-print_format', 'json',
             '-show_format', input_path],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        return float(data.get('format', {}).get('duration', 0)) or None
    except Exception:
        return None
