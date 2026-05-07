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
import numpy as np

logger = logging.getLogger(__name__)


# ─── Auto-detect crop layout from black separator bands ──────────────────────

def detect_quadrature_layout(
    src_path: str,
    *,
    sample_frames: int = 5,
    black_threshold: int = 15,
) -> Optional[dict]:
    """
    Auto-detect the 4 view bounding boxes from a quadrature video by
    scanning for solid black separator bands. Returns a layout dict in the
    same format as LAYOUT_NAVYA, or None if detection fails (caller should
    then fall back to LAYOUT_NAVYA).

    Algorithm:
      1. Sample N evenly-spaced frames, take per-pixel min across them
         (true black separators stay black at every timestep — moving scene
         elements that are momentarily black do not).
      2. Per row / per column median luminance < threshold → "black row/col".
      3. Find the central horizontal black band (splits top/bottom rows of
         the grid) and central vertical black band (splits left/right cols).
      4. Strip outer black borders.
    """
    cap = cv2.VideoCapture(str(src_path))
    if not cap.isOpened():
        return None

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    if total <= 0 or h <= 0 or w <= 0:
        cap.release()
        return None

    # Pick N timestamps spread across the video so a single dark frame
    # doesn't pollute the per-pixel min.
    n = max(2, min(sample_frames, total))
    grays = []
    for i in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, total * (i + 1) // (n + 1))
        ok, frame = cap.read()
        if ok and frame is not None:
            grays.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    cap.release()

    if not grays:
        return None

    stack = np.stack(grays, axis=0)
    min_frame = stack.min(axis=0)  # true-black bands stay dark across all samples
    row_med = np.median(min_frame, axis=1)
    col_med = np.median(min_frame, axis=0)
    black_rows = np.where(row_med < black_threshold)[0]
    black_cols = np.where(col_med < black_threshold)[0]

    if black_rows.size == 0 or black_cols.size == 0:
        logger.warning("[QuadratureVideo] No black bands detected — falling back to default layout")
        return None

    def _group_runs(idxs):
        """Return list of (start, end_inclusive) for consecutive index runs."""
        if len(idxs) == 0:
            return []
        runs = []
        start = idxs[0]
        prev = idxs[0]
        for i in idxs[1:]:
            if i == prev + 1:
                prev = i
            else:
                runs.append((start, prev))
                start = i
                prev = i
        runs.append((start, prev))
        return runs

    def _central_band(black_idxs, dim):
        """Pick the run whose midpoint is closest to dim/2 (the central separator)."""
        runs = _group_runs(black_idxs)
        if not runs:
            return None
        center = dim / 2.0
        return min(runs, key=lambda r: abs((r[0] + r[1]) / 2.0 - center))

    def _strip_outer(med, thr):
        non_black = np.where(med >= thr)[0]
        if non_black.size:
            return int(non_black[0]), int(non_black[-1] + 1)
        return 0, len(med)

    h_band = _central_band(black_rows, h)
    v_band = _central_band(black_cols, w)
    if h_band is None or v_band is None:
        return None

    inner_y1, inner_y2 = _strip_outer(row_med, black_threshold)
    inner_x1, inner_x2 = _strip_outer(col_med, black_threshold)

    top_y1 = max(0, inner_y1)
    top_y2 = int(h_band[0])
    bot_y1 = int(h_band[1] + 1)
    bot_y2 = min(h, inner_y2)
    lef_x1 = max(0, inner_x1)
    lef_x2 = int(v_band[0])
    rig_x1 = int(v_band[1] + 1)
    rig_x2 = min(w, inner_x2)

    # Sanity: every quadrant must have positive area
    boxes = {
        'rear':  (lef_x1, top_y1, lef_x2, top_y2),
        'front': (rig_x1, top_y1, rig_x2, top_y2),
        'left':  (lef_x1, bot_y1, lef_x2, bot_y2),
        'right': (rig_x1, bot_y1, rig_x2, bot_y2),
    }
    for name, (x1, y1, x2, y2) in boxes.items():
        if x2 - x1 < 50 or y2 - y1 < 50:
            logger.warning(
                f"[QuadratureVideo] Detected layout has degenerate '{name}' "
                f"box ({x1},{y1})-({x2},{y2}) — falling back"
            )
            return None

    logger.info(
        f"[QuadratureVideo] Auto-detected layout from {os.path.basename(str(src_path))}: "
        f"frame {w}×{h}, h-band rows {h_band[0]}-{h_band[1]}, "
        f"v-band cols {v_band[0]}-{v_band[1]}, "
        f"boxes={boxes}"
    )
    return boxes

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
