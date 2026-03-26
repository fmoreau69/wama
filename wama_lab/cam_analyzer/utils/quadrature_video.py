"""
Quadrature video extractor for WAMA cam_analyzer.

A quadrature video (800x500) contains 4 camera views in a 2x2 grid.
This module extracts individual views and saves them as separate MP4 files.

Navya shuttle layout (Rear TL, Front TR, Left BL, Right BR):
    +--------------+--------------+
    |   ARRIERE    |    AVANT     |
    |  (0,0)       |  (400,0)     |
    |  400x250     |  400x250     |
    +--------------+--------------+
    |   GAUCHE     |   DROITE     |
    |  (0,250)     |  (400,250)   |
    |  400x250     |  400x250     |
    +--------------+--------------+

NOTE: This layout should be verified against actual recorded footage before
      production use. The LAYOUT_NAVYA constant can be updated without code
      changes to the rest of the pipeline.
"""
import logging
import os
from pathlib import Path
from typing import Optional

import cv2

logger = logging.getLogger(__name__)

# ─── Crop layouts ─────────────────────────────────────────────────────────────
# Format: {position: (x1, y1, x2, y2)} in pixel coordinates

LAYOUT_NAVYA = {
    'rear':  (0,   0,   400, 250),
    'front': (400, 0,   800, 250),
    'left':  (0,   250, 400, 500),
    'right': (400, 250, 800, 500),
}


def export_quadrature_view(
    src_path: str,
    dst_path: str,
    position: str,
    layout: dict = None,
    progress_callback=None,
) -> dict:
    """
    Extract one view from a quadrature video and write it to dst_path (MP4 H264).

    Args:
        src_path:          Path to the source quadrature video (800x500)
        dst_path:          Output path for the extracted view (.mp4)
        position:          View name ('front', 'rear', 'left', 'right')
        layout:            Crop layout dict (defaults to LAYOUT_NAVYA)
        progress_callback: Optional callable(pct: float) called every 100 frames

    Returns:
        dict with keys: width, height, fps, frame_count, duration
    """
    if layout is None:
        layout = LAYOUT_NAVYA

    if position not in layout:
        raise ValueError(f"Unknown position '{position}'. Valid: {list(layout.keys())}")

    x1, y1, x2, y2 = layout[position]
    out_width = x2 - x1
    out_height = y2 - y1

    src_path = str(src_path)
    dst_path = str(dst_path)

    Path(dst_path).parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {src_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 12.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    logger.info(
        f"[QuadratureVideo] Extracting '{position}' from {os.path.basename(src_path)} "
        f"({src_width}x{src_height}) → crop ({x1},{y1})-({x2},{y2}) → {out_width}x{out_height}"
    )

    # Use H264 codec (avc1 on Windows, x264 fallback)
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    writer = cv2.VideoWriter(dst_path, fourcc, fps, (out_width, out_height))
    if not writer.isOpened():
        # Fallback to MJPG if H264 not available
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        dst_path_mjpg = dst_path.replace('.mp4', '.avi')
        writer = cv2.VideoWriter(dst_path_mjpg, fourcc, fps, (out_width, out_height))
        if not writer.isOpened():
            cap.release()
            raise IOError(f"Cannot create video writer for: {dst_path}")
        dst_path = dst_path_mjpg
        logger.warning(f"[QuadratureVideo] H264 unavailable, using MJPG: {dst_path}")

    frames_written = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Sanity check frame dimensions
            h, w = frame.shape[:2]
            if w < x2 or h < y2:
                logger.warning(
                    f"[QuadratureVideo] Frame {frames_written} too small ({w}x{h}), "
                    f"expected at least ({x2}x{y2})"
                )
                # Write blank frame to keep sync
                writer.write(
                    cv2.resize(frame[0:min(h, y2-y1), 0:min(w, x2-x1)], (out_width, out_height))
                )
            else:
                cropped = frame[y1:y2, x1:x2]
                writer.write(cropped)

            frames_written += 1

            if progress_callback and frames_written % 100 == 0 and total_frames > 0:
                pct = (frames_written / total_frames) * 100.0
                progress_callback(pct)

    finally:
        cap.release()
        writer.release()

    duration = frames_written / fps if fps > 0 else 0.0
    logger.info(
        f"[QuadratureVideo] '{position}' extracted: {frames_written} frames, "
        f"{duration:.1f}s → {os.path.basename(dst_path)}"
    )

    return {
        'path': dst_path,
        'width': out_width,
        'height': out_height,
        'fps': round(fps, 2),
        'frame_count': frames_written,
        'duration': round(duration, 2),
    }


def extract_all_views(
    src_path: str,
    output_dir: str,
    positions: Optional[list] = None,
    layout: dict = None,
    progress_callback=None,
) -> dict:
    """
    Extract multiple views from a quadrature video.

    Args:
        src_path:     Source quadrature video
        output_dir:   Directory for output files
        positions:    List of positions to extract (default: ['front', 'rear'])
        layout:       Crop layout (default: LAYOUT_NAVYA)
        progress_callback: Optional callable(position: str, pct: float)

    Returns:
        dict mapping position -> metadata dict (from export_quadrature_view)
    """
    if positions is None:
        positions = ['front', 'rear']
    if layout is None:
        layout = LAYOUT_NAVYA

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    src_stem = Path(src_path).stem
    results = {}

    for i, pos in enumerate(positions):
        dst_path = os.path.join(output_dir, f"{src_stem}_{pos}.mp4")

        def _cb(pct, _pos=pos, _i=i, _n=len(positions)):
            if progress_callback:
                # Overall progress: each view is an equal slice
                overall = (_i / _n * 100.0) + (pct / _n)
                progress_callback(_pos, overall)

        try:
            meta = export_quadrature_view(src_path, dst_path, pos, layout, _cb)
            results[pos] = meta
        except Exception as e:
            logger.error(f"[QuadratureVideo] Failed to extract '{pos}': {e}")
            results[pos] = {'error': str(e)}

    return results
