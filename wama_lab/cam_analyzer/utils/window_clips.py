"""Les PLAGES D'IMAGES des fenêtres d'intersection, et l'extrait vidéo exact d'une plage.

Écrit DANS la détection YOLO (`tasks.process_session_task`, chemin « F ») jusqu'au 2026-10-12 ;
sorti ici quand une seconde passe — l'anonymisation pour l'affichage — a eu besoin du même
découpage : deux passes qui borneraient les fenêtres chacune à sa façon ne regarderaient pas les
mêmes images.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


def merge_frame_ranges(ranges) -> list:
    """Plages (début, fin) d'images, inclusives, fusionnées quand elles se chevauchent ou se
    touchent (à une image près). Deux fenêtres sur la même route se recouvrent dès qu'elles sont
    plus proches que deux rayons : sans fusion, la même image serait rendue deux fois (et la
    détection YOLO heurterait la contrainte d'unicité (caméra, image) de `DetectionFrame`)."""
    if not ranges:
        return []
    ranges = sorted(ranges)
    merged = [list(ranges[0])]
    for start, end in ranges[1:]:
        if start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(r) for r in merged]


def window_frame_ranges(windows, fps: float, total_frames: int) -> list:
    """Les fenêtres d'intersection (`t_enter`/`t_exit`, temps VIDÉO en secondes) en plages
    d'images de la vidéo, bornées à la vidéo et fusionnées."""
    raw = []
    for w in windows or []:
        start = max(0, int(w['t_enter'] * fps))
        end = min(total_frames - 1, int(w['t_exit'] * fps))
        if start <= end:
            raw.append((start, end))
    return merge_frame_ranges(raw)


def ffmpeg_path():
    """L'exécutable ffmpeg, ou None — l'appelant choisit alors son repli."""
    return shutil.which('ffmpeg')


def extract_clip(video_path: str, start: int, end: int, fps: float, clip_path: str,
                 ffmpeg: str = None) -> bool:
    """Écrit dans `clip_path` les images `start`…`end` (inclusives) de la vidéo. Rend False si
    l'extraction a échoué (le journal dit pourquoi).

    Ré-encodé (libx264, crf 18, quasi sans perte) : c'est ce qui donne un nombre d'images EXACT,
    là où une copie de flux (`-c copy`) s'aligne sur les images clés."""
    ffmpeg = ffmpeg or ffmpeg_path()
    if ffmpeg is None:
        return False
    proc = subprocess.run([
        ffmpeg, '-y', '-loglevel', 'error',
        '-ss', f"{start / fps:.6f}",
        '-i', video_path,
        '-t', f"{(end - start + 1) / fps:.6f}",
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
        '-pix_fmt', 'yuv420p', '-an',
        clip_path,
    ], capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not os.path.exists(clip_path):
        logger.warning(f"[ffmpeg-seg] extrait {start}-{end} : échec "
                       f"{(proc.stderr or '')[-200:]}")
        return False
    return True
