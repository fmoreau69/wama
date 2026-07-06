"""
WAMA Common — Sonde média ffprobe (durée / codec / échantillonnage / canaux).

Extraction du `_describe_audio` du transcriber (audit A5-18, 2026-07-06) : la sonde est
générique (toute app qui affiche les propriétés d'un média audio/vidéo sur sa card).
Utilise la brique ffmpeg_utils (chemins candidats + escape hatch FFMPEG_BINARY).
"""

import json
import subprocess


def format_duration(seconds: float) -> str:
    """``95.4 -> '1:35'`` — affichage court pour les cards ('' si inconnu/zéro)."""
    if not seconds or seconds <= 0:
        return ''
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def probe_audio(path: str) -> dict:
    """Sonde le premier flux audio d'un fichier.

    Returns:
        dict {'duration': float, 'duration_display': str, 'properties': str}
        — properties = « codec • 44.1 kHz • stéréo » (libellés FR, prêts pour la card).
        {} si ffprobe indisponible ou fichier illisible (jamais d'exception).
    """
    from wama.common.utils.ffmpeg_utils import get_ffprobe_exe
    ffprobe = get_ffprobe_exe()
    if not ffprobe:
        return {}

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=duration,codec_name,sample_rate,channels:format=duration",
                "-of", "json",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        duration = float(stream.get("duration") or 0)
        if not duration:
            fmt_duration = (data.get("format") or {}).get("duration")
            if fmt_duration:
                duration = float(fmt_duration)
        sample_rate = stream.get("sample_rate")
        codec = stream.get("codec_name")
        channels = int(stream.get("channels") or 0)

        channel_label = ""
        if channels == 1:
            channel_label = "mono"
        elif channels == 2:
            channel_label = "stéréo"
        elif channels:
            channel_label = f"{channels} canaux"

        sr_label = ""
        if sample_rate:
            try:
                sr_hz = int(sample_rate)
                sr_label = f"{sr_hz / 1000:.1f} kHz"
            except (TypeError, ValueError):
                sr_label = f"{sample_rate} Hz"

        return {
            'duration': duration,
            'duration_display': format_duration(duration),
            'properties': " • ".join(filter(None, [codec, sr_label, channel_label])),
        }
    except Exception:
        return {}
