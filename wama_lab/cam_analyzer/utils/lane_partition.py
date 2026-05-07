"""
Lane attribution from YOLOPv2 outputs.

YOLOPv2 returns:
  - drivable area as a (typically single) closed polygon
  - lane lines as a set of closed contours (the painted markings themselves)

This module turns those into a per-detection ``lane_id`` integer:

  lane_id = number of lane-line crossings at the detection's foot point
            scanning leftward across the frame.

i.e. lane_id = 0 means the foot is to the LEFT of any lane line at its row,
lane_id = 1 means it crossed one lane line, etc. The shuttle lane is then
the lane_id at the bottom-centre of the image (0.5 × W, 0.95 × H).

Approximate but robust enough for V1: doesn't require connecting broken lane
dashes into a single polyline (BDD100K-style dashes break frequently). When
the detection's foot row contains no lane crossings, we fall back to
``-1`` so downstream consumers can ignore it.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

# Vertical search window around the foot point's y when sampling lane crossings.
# A lane dash spans only a few rows once projected; we take a band around
# foot_y so we hit at least one polygon vertex on most frames.
_Y_SLICE_HALFWIDTH = 8


def _polygon_x_at_y(polygon: Sequence[Sequence[float]], y: float) -> Optional[float]:
    """
    Average x-coordinate of polygon vertices whose y is within
    [y-_Y_SLICE_HALFWIDTH, y+_Y_SLICE_HALFWIDTH]. None if the polygon doesn't
    cross that band.
    """
    xs = [p[0] for p in polygon if abs(p[1] - y) <= _Y_SLICE_HALFWIDTH]
    if not xs:
        return None
    return sum(xs) / len(xs)


def attribute_lane(
    foot_xy: Tuple[float, float],
    lane_polygons: List[Sequence[Sequence[float]]],
) -> int:
    """
    Return a lane index ∈ {-1, 0, 1, …} for the given foot point.

    Parameters
    ----------
    foot_xy : (x, y) pixel coordinates of the detection's foot point.
    lane_polygons : list of closed contours (each contour: list of (x, y)).

    Returns
    -------
    lane_id : ≥ 0 if at least one lane line is sampled at this row ; -1 if
              the detection's row contains no lane crossings (we can't tell
              which lane).
    """
    if not lane_polygons:
        return -1

    foot_x, foot_y = foot_xy
    crossings: List[float] = []
    for poly in lane_polygons:
        x = _polygon_x_at_y(poly, foot_y)
        if x is not None:
            crossings.append(x)

    if not crossings:
        return -1

    crossings.sort()
    return sum(1 for cx in crossings if cx < foot_x)


def find_shuttle_lane(
    lane_polygons: List[Sequence[Sequence[float]]],
    frame_width: int,
    frame_height: int,
) -> int:
    """
    Lane id of the shuttle itself: the lane containing the image's
    bottom-centre (just in front of the front camera).
    """
    bottom_center = (frame_width / 2.0, frame_height * 0.95)
    return attribute_lane(bottom_center, lane_polygons)


def annotate_detections_with_lane(
    detections: List[dict],
    lane_polygons: List[Sequence[Sequence[float]]],
    shuttle_lane: int,
) -> None:
    """
    Mutates ``detections`` in place: each entry that has a bbox gets a
    ``lane_id`` (int, possibly -1) and ``in_shuttle_lane`` (bool) field.
    SAM3 / road_mask entries (no bbox) are skipped.
    """
    if shuttle_lane < 0:
        return  # can't tell which lane the shuttle is in → don't tag others
    for det in detections:
        bbox = det.get('bbox')
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        # Foot point = bottom-centre of bbox (where the object touches the road)
        foot_x = (bbox[0] + bbox[2]) / 2.0
        foot_y = bbox[3]
        lane = attribute_lane((foot_x, foot_y), lane_polygons)
        det['lane_id'] = lane
        det['in_shuttle_lane'] = (lane == shuttle_lane)
