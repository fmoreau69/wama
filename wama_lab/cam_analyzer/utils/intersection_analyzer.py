"""
Intersection insertion analyzer for WAMA cam_analyzer.

Detects vehicles that insert in front of the shuttle at road intersections.

Algorithm (Phase Initiale + Intermédiaire):
1. Find time windows where shuttle GPS is within radius_m of a known intersection
2. In each window, analyze YOLO detection tracks on the front camera:
   a. Identify vehicles that were STOPPED (position stable, compensated for ego-motion)
   b. Classify each stopped vehicle as:
      - INSERTION : moves toward shuttle lane after being stopped
      - WAIT      : stays stopped until shuttle has passed
      - TURN      : moves but away from shuttle lane (exit/turn)
3. Compute timing markers:
   - t0 : first detection of the vehicle in the intersection window
   - t1 : vehicle starts moving (insertion/departure begins)
   - t2 : vehicle stabilizes in shuttle lane (insertion complete) — INSERTION only
4. Compute D0_relative = frame_height / bbox_height (distance proxy, no calibration yet)
5. Compute traffic density : simultaneous stopped vehicles per frame in the window
6. Record bbox trajectory for each event : [{ts, x1, y1, x2, y2}, ...]
"""
import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Minimum number of frames a vehicle must be stationary to be considered stopped
MIN_STOPPED_FRAMES = 3

# Base pixel movement threshold per frame to be considered "stopped"
# (bbox center displacement in pixels per frame)
BASE_STOPPED_PX = 5.0

# How much to relax the stopped threshold per km/h of shuttle speed
# (ego-motion compensation: shuttle moving 5 km/h -> +2.5 px tolerance)
SPEED_FACTOR_PX_PER_KMH = 0.5

# Minimum number of frames moving toward center to classify as insertion
MIN_INSERTION_FRAMES = 2

# Fraction of frame_width from center that counts as "shuttle lane"
# (center ± CENTER_ZONE_RATIO * frame_width)
CENTER_ZONE_RATIO = 0.35

# Minimum D0_relative to count as a plausible vehicle (very small = too far)
MIN_D0_RELATIVE = 0.2

# Number of consecutive frames to consider "stabilized" after insertion (t2 detection)
T2_STABLE_FRAMES = 3

# Movement threshold below which a vehicle is considered "stabilized" (for t2)
T2_STABLE_PX = 4.0

# Max bbox trajectory points to store (trim to keep metadata compact)
MAX_TRAJ_POINTS = 200


# ─── Haversine distance ────────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two WGS-84 points."""
    R = 6_371_000.0  # Earth radius in metres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ─── Analyzer ────────────────────────────────────────────────────────────────

class IntersectionAnalyzer:
    """
    Analyzes vehicle behavior at known intersections using YOLO tracking
    results on the front camera combined with shuttle GPS telemetry.

    Args:
        intersections: List of dicts: [{name, lat, lon, radius_m}, ...]
        gps_track:     List of dicts: [{ts, lat, lon, speed_kmh, heading}, ...]
        fps:           Video FPS (for timestamp calculation)
        frame_height:  Height of the front camera crop in pixels
    """

    def __init__(self, intersections: list, gps_track: list, fps: float, frame_height: int):
        self.intersections = intersections or []
        self.gps_track = sorted(gps_track or [], key=lambda x: x['ts'])
        self.fps = fps or 12.0
        self.frame_height = frame_height or 250

    # ── GPS interpolation ──────────────────────────────────────────────────

    def gps_at(self, ts_seconds: float) -> dict:
        """
        Linearly interpolate GPS data at the given timestamp.
        Returns {ts, lat, lon, speed_kmh, heading} or a default zero point.
        """
        if not self.gps_track:
            return {'ts': ts_seconds, 'lat': 0.0, 'lon': 0.0, 'speed_kmh': 0.0, 'heading': 0.0}

        track = self.gps_track

        if ts_seconds <= track[0]['ts']:
            return track[0]
        if ts_seconds >= track[-1]['ts']:
            return track[-1]

        lo, hi = 0, len(track) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if track[mid]['ts'] <= ts_seconds:
                lo = mid
            else:
                hi = mid

        p0, p1 = track[lo], track[hi]
        dt = p1['ts'] - p0['ts']
        if dt <= 0:
            return p0

        frac = (ts_seconds - p0['ts']) / dt
        return {
            'ts': ts_seconds,
            'lat': p0['lat'] + frac * (p1['lat'] - p0['lat']),
            'lon': p0['lon'] + frac * (p1['lon'] - p0['lon']),
            'speed_kmh': p0['speed_kmh'] + frac * (p1['speed_kmh'] - p0['speed_kmh']),
            'heading': p0['heading'] + frac * (p1['heading'] - p0['heading']),
        }

    # ── Intersection window detection ─────────────────────────────────────

    def find_intersection_windows(self,
                                  merge_gap_s: float = 120.0,
                                  min_duration_s: float = 3.0,
                                  exit_distance_factor: float = 1.5) -> list:
        """
        Find time windows during which the shuttle is within radius_m of
        each configured intersection.

        Returns list of dicts:
        {
            'intersection': {name, lat, lon, radius_m},
            't_enter': float,   # seconds — shuttle enters proximity zone
            't_exit': float,    # seconds — shuttle leaves proximity zone
            'gps_points': list, # GPS points within the window
        }

        Post-processing:
        - Consecutive windows for the same intersection are merged when EITHER
          the time gap is ≤ ``merge_gap_s`` OR the shuttle never reached more
          than ``exit_distance_factor × radius_m`` from the intersection during
          the gap (= GPS jitter around the boundary, the shuttle never truly
          left the area).
        - Windows shorter than ``min_duration_s`` after merging are dropped
          (transient GPS noise spikes).
        """
        if not self.gps_track or not self.intersections:
            return []

        raw = []

        for intersection in self.intersections:
            i_lat = intersection.get('lat', 0)
            i_lon = intersection.get('lon', 0)
            radius = intersection.get('radius_m', 100)

            in_window = False
            window_start = None
            window_gps = []

            for gps in self.gps_track:
                dist = haversine(gps['lat'], gps['lon'], i_lat, i_lon)

                if dist <= radius:
                    if not in_window:
                        in_window = True
                        window_start = gps['ts']
                        window_gps = []
                    window_gps.append(gps)
                else:
                    if in_window:
                        in_window = False
                        raw.append({
                            'intersection': intersection,
                            't_enter': window_start,
                            't_exit': gps['ts'],
                            'gps_points': window_gps,
                        })
                        window_start = None
                        window_gps = []

            # Handle window still open at end of track
            if in_window and window_gps:
                raw.append({
                    'intersection': intersection,
                    't_enter': window_start,
                    't_exit': self.gps_track[-1]['ts'],
                    'gps_points': window_gps,
                })

        # ── Merge close windows + filter short ones ──────────────────────────
        windows = self._post_process_windows(
            raw, merge_gap_s, min_duration_s, exit_distance_factor, self.gps_track
        )

        # ── Center each window on the moment of closest pass ─────────────────
        # The radius-based block boundaries are asymmetric whenever the shuttle
        # approaches the intersection slowly and leaves quickly (or vice-versa)
        # — the closest GPS point may sit at the very start or end of the
        # block. Re-anchor each window so its midpoint is the time of closest
        # approach to the intersection center; preserve the block duration.
        for w in windows:
            i_lat = (w.get('intersection') or {}).get('lat', 0)
            i_lon = (w.get('intersection') or {}).get('lon', 0)
            gps_pts = w.get('gps_points') or []
            if not gps_pts:
                w['t_closest'] = (w['t_enter'] + w['t_exit']) / 2
                w['min_distance_m'] = None
                continue

            closest = min(gps_pts, key=lambda g: haversine(g['lat'], g['lon'], i_lat, i_lon))
            t_closest = closest['ts']
            min_dist = haversine(closest['lat'], closest['lon'], i_lat, i_lon)
            duration = w['t_exit'] - w['t_enter']

            # Symmetric window centered on t_closest, same total duration.
            # Clamp to the available GPS track range.
            track_start = self.gps_track[0]['ts']
            track_end = self.gps_track[-1]['ts']
            new_enter = max(track_start, t_closest - duration / 2)
            new_exit = min(track_end, t_closest + duration / 2)

            w['t_enter'] = new_enter
            w['t_exit'] = new_exit
            w['t_closest'] = t_closest
            w['min_distance_m'] = round(min_dist, 1)

        # Re-sort after recentering (start times may have shifted)
        windows.sort(key=lambda w: w['t_enter'])

        logger.info(
            f"[IntersectionAnalyzer] {len(raw)} raw windows → {len(windows)} after merging "
            f"(gap≤{merge_gap_s}s OR max_dist<{exit_distance_factor}×radius) "
            f"+ filtering (duration≥{min_duration_s}s) + centering on closest pass"
        )
        for i, w in enumerate(windows):
            logger.info(
                f"[IntersectionAnalyzer]   #{i+1} {w['intersection'].get('name', '?'):30s} "
                f"{w['t_enter']:7.1f}s → {w['t_exit']:7.1f}s "
                f"(closest@{w.get('t_closest', 0):.1f}s, min={w.get('min_distance_m')}m)"
            )
        return windows

    @staticmethod
    def _post_process_windows(raw: list, merge_gap_s: float, min_duration_s: float,
                              exit_distance_factor: float, gps_track: list) -> list:
        """Merge GPS-jitter fragments, drop noise spikes."""
        if not raw:
            return []

        # Sort GPS by ts once, build a quick accessor
        gps_sorted = sorted(gps_track or [], key=lambda g: g['ts'])

        def max_distance_in_gap(intersection: dict, t0: float, t1: float) -> float:
            """Maximum distance to intersection center during [t0, t1]."""
            i_lat = intersection.get('lat', 0)
            i_lon = intersection.get('lon', 0)
            best = 0.0
            for g in gps_sorted:
                if g['ts'] < t0:
                    continue
                if g['ts'] > t1:
                    break
                d = haversine(g['lat'], g['lon'], i_lat, i_lon)
                if d > best:
                    best = d
            return best

        by_name = {}
        for w in raw:
            name = (w.get('intersection') or {}).get('name', '')
            by_name.setdefault(name, []).append(w)

        merged = []
        for name, group in by_name.items():
            group.sort(key=lambda w: w['t_enter'])
            current = None
            for w in group:
                if current is None:
                    current = {
                        'intersection': w['intersection'],
                        't_enter': w['t_enter'],
                        't_exit': w['t_exit'],
                        'gps_points': list(w.get('gps_points') or []),
                    }
                    continue

                gap_s = w['t_enter'] - current['t_exit']
                radius = (current['intersection'] or {}).get('radius_m', 100)

                # Merge if time gap is small OR if shuttle never traveled far enough
                # to count as a real exit/return.
                should_merge = gap_s <= merge_gap_s
                if not should_merge and gps_sorted:
                    max_d = max_distance_in_gap(
                        current['intersection'], current['t_exit'], w['t_enter']
                    )
                    if max_d < exit_distance_factor * radius:
                        should_merge = True
                        logger.debug(
                            f"[IntersectionAnalyzer] merging '{name}' across gap of "
                            f"{gap_s:.1f}s — max_dist={max_d:.1f}m < {exit_distance_factor}×{radius}m"
                        )

                if should_merge:
                    current['t_exit'] = w['t_exit']
                    current['gps_points'].extend(w.get('gps_points') or [])
                else:
                    if current['t_exit'] - current['t_enter'] >= min_duration_s:
                        merged.append(current)
                    current = {
                        'intersection': w['intersection'],
                        't_enter': w['t_enter'],
                        't_exit': w['t_exit'],
                        'gps_points': list(w.get('gps_points') or []),
                    }
            if current is not None and current['t_exit'] - current['t_enter'] >= min_duration_s:
                merged.append(current)

        merged.sort(key=lambda w: w['t_enter'])
        return merged

    # ── Window analysis ───────────────────────────────────────────────────

    def analyze_window(self, window: dict, window_frames: list) -> list:
        """
        Analyze YOLO detection frames within an intersection window.

        Each frame in window_frames is a DetectionFrame-like object with:
            .timestamp : float (seconds)
            .detections: list of detection dicts

        Returns list of event dicts:
        {
            'type': 'insertion_front' | 'intersection_stop',
            'start': float,
            'end': float,
            'metadata': {
                # Phase Initiale
                'intersection_name': str,
                'event_type': 'insertion' | 'wait' | 'turn',
                'track_id': int,
                'vehicle_class': str,
                'D0_relative': float,
                'shuttle_speed_kmh': float,
                # Phase Intermédiaire — timing
                't0': float,   # first detection in window
                't1': float,   # start of movement (insertion/departure)
                't2': float,   # insertion complete — INSERTION events only
                'duration_insertion_s': float,  # t2 - t1 — INSERTION only
                # Phase Intermédiaire — traffic density
                'traffic_density': {
                    'max_simultaneous': int,
                    'avg_simultaneous': float,
                    'peak_ts': float,
                    'vehicle_classes_at_peak': [str, ...],
                },
                # Phase Intermédiaire — bbox trajectory
                'bbox_trajectory': [{'ts': float, 'x1': int, 'y1': int, 'x2': int, 'y2': int}, ...],
            }
        }
        """
        if not window_frames:
            return []

        intersection = window['intersection']
        # Assume 2:1 aspect ratio for the cropped front view (e.g. 400×250 → width=400)
        frame_width = self.frame_height * 2

        # ── Compute traffic density across all frames in window ────────────
        # (uses all tracks, before individual track analysis)
        traffic_density = self._compute_traffic_density(window_frames, frame_width)

        # ── Extract road masks per timestamp ──────────────────────────────
        # Road mask dicts are stored in DetectionFrame.detections with type='road_mask'
        # when the road segmenter was active during processing.
        road_masks_by_ts = {}
        for frame in window_frames:
            road_regions = [d for d in (frame.detections or []) if d.get('type') == 'road_mask']
            if road_regions:
                road_masks_by_ts[frame.timestamp] = road_regions
        road_masks = road_masks_by_ts if road_masks_by_ts else None

        if road_masks:
            logger.debug(f"[IntersectionAnalyzer] Road masks available for "
                         f"{len(road_masks)}/{len(window_frames)} frames in window")

        # ── Extract SAM3 markings per timestamp ────────────────────────────
        sam3_markings_by_ts = {}
        for frame in window_frames:
            markings = [d for d in (frame.detections or []) if d.get('type') == 'sam3_marking']
            if markings:
                sam3_markings_by_ts[frame.timestamp] = markings

        # ── Build per-track history ────────────────────────────────────────
        # Tuple: (timestamp, x_center, y_center, bbox_height, class_name, x1, y1, x2, y2)
        tracks = {}

        for frame in window_frames:
            ts = frame.timestamp
            for det in (frame.detections or []):
                # Skip non-vehicle entries (road_mask, sam3_marking…)
                if det.get('type') in ('road_mask', 'sam3_marking'):
                    continue
                tid = det.get('track_id')
                if tid is None:
                    continue
                bbox = det.get('bbox', [0, 0, 0, 0])
                if len(bbox) < 4:
                    continue
                x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
                x_center = (x1 + x2) / 2.0
                y_center = (y1 + y2) / 2.0
                bbox_h = y2 - y1
                if bbox_h <= 0:
                    continue
                cls = det.get('class_name', 'unknown')
                tracks.setdefault(tid, []).append(
                    (ts, x_center, y_center, bbox_h, cls, x1, y1, x2, y2)
                )

        # ── Analyze each track ─────────────────────────────────────────────
        events = []

        for tid, points in tracks.items():
            if len(points) < MIN_STOPPED_FRAMES:
                continue

            # Most common class
            cls_counts = {}
            for p in points:
                cls_counts[p[4]] = cls_counts.get(p[4], 0) + 1
            vehicle_class = max(cls_counts, key=cls_counts.get)

            # D0 from median bbox height during earliest detection
            early_bboxh = [p[3] for p in points[:5]]
            median_bboxh = sorted(early_bboxh)[len(early_bboxh) // 2]
            d0_relative = round(self.frame_height / median_bboxh, 2) if median_bboxh > 0 else 99.0

            if d0_relative < MIN_D0_RELATIVE:
                continue

            # ── GPS at mid-window (shuttle speed for ego-motion) ─────────
            mid_ts = points[len(points) // 2][0]
            gps_mid = self.gps_at(mid_ts)
            shuttle_speed = gps_mid.get('speed_kmh', 0.0)

            # ── t0: first detection ──────────────────────────────────────
            t0 = points[0][0]

            # ── Find stopped phase ───────────────────────────────────────
            stopped_start_idx = self._find_stopped_phase(points, shuttle_speed)
            if stopped_start_idx is None:
                continue

            # ── Classify post-stop movement → get t1 ────────────────────
            post_stop = points[stopped_start_idx:]
            event_type, t1, move_start_idx_in_post = self._classify_post_stop_v2(
                post_stop, frame_width, road_masks
            )

            # ── t2: end of insertion (only for insertion events) ─────────
            t2 = None
            duration_insertion_s = None
            if event_type == 'insertion' and t1 is not None and move_start_idx_in_post is not None:
                abs_move_idx = stopped_start_idx + move_start_idx_in_post
                t2 = self._find_t2(points, abs_move_idx, frame_width)
                if t2 is not None and t1 is not None:
                    duration_insertion_s = round(t2 - t1, 2)

            # ── Bbox trajectory (downsampled) ────────────────────────────
            bbox_traj = self._record_bbox_trajectory(points)

            # ── Build segment ────────────────────────────────────────────
            t_start = points[stopped_start_idx][0]
            t_end = t2 if t2 is not None else points[-1][0]
            if t_end <= t_start:
                t_end = t_start + (1.0 / self.fps)

            seg_type = 'insertion_front' if event_type == 'insertion' else 'intersection_stop'

            # ── SAM3 markings in this track's time span ──────────────────
            stop_line_detected = False
            crossing_detected = False
            if sam3_markings_by_ts:
                track_ts_set = {p[0] for p in points}
                for ts_mark, marks in sam3_markings_by_ts.items():
                    # Check if this marking timestamp is near any frame of this track
                    if any(abs(ts_mark - t) < (1.0 / self.fps + 0.01) for t in track_ts_set):
                        for m in marks:
                            lbl = m.get('label', '')
                            if lbl == 'stop_line':
                                stop_line_detected = True
                            elif lbl == 'crossing':
                                crossing_detected = True

            metadata = {
                # Phase Initiale
                'intersection_name': intersection.get('name', ''),
                'event_type': event_type,
                'track_id': tid,
                'vehicle_class': vehicle_class,
                'D0_relative': d0_relative,
                'shuttle_speed_kmh': round(shuttle_speed, 1),
                # Phase Initiale — detection method
                'road_mask_used': road_masks is not None,
                # Phase Avancée — SAM3 markings
                'stop_line_detected': stop_line_detected,
                'crossing_detected': crossing_detected,
                # Phase Intermédiaire — timing
                't0': round(t0, 3),
                't1': round(t1, 3) if t1 is not None else None,
                't2': round(t2, 3) if t2 is not None else None,
                'duration_insertion_s': duration_insertion_s,
                # Phase Intermédiaire — traffic density
                'traffic_density': traffic_density,
                # Phase Intermédiaire — bbox trajectory
                'bbox_trajectory': bbox_traj,
            }

            events.append({
                'type': seg_type,
                'start': round(t_start, 3),
                'end': round(t_end, 3),
                'metadata': metadata,
            })

        return events

    # ── Traffic density ────────────────────────────────────────────────────

    def _compute_traffic_density(self, window_frames: list, frame_width: int) -> dict:
        """
        Count simultaneously stopped vehicles per frame across the window.

        A vehicle is "stopped" at a given frame if its bbox center displacement
        vs. the previous frame is below the base threshold (no ego-motion correction
        here — used for global density estimate only).

        Returns:
        {
            'max_simultaneous': int,
            'avg_simultaneous': float,
            'peak_ts': float,           # timestamp of frame with most stopped vehicles
            'vehicle_classes_at_peak': [str, ...],
        }
        """
        if not window_frames:
            return {'max_simultaneous': 0, 'avg_simultaneous': 0.0, 'peak_ts': None,
                    'vehicle_classes_at_peak': []}

        # Build track positions per frame: {frame_ts: {tid: (x_center, y_center, cls)}}
        frame_data = {}
        for frame in window_frames:
            ts = frame.timestamp
            frame_data[ts] = {}
            for det in (frame.detections or []):
                tid = det.get('track_id')
                if tid is None:
                    continue
                bbox = det.get('bbox', [0, 0, 0, 0])
                if len(bbox) < 4:
                    continue
                x_c = (bbox[0] + bbox[2]) / 2.0
                y_c = (bbox[1] + bbox[3]) / 2.0
                frame_data[ts][tid] = (x_c, y_c, det.get('class_name', 'unknown'))

        sorted_ts = sorted(frame_data.keys())
        if len(sorted_ts) < 2:
            count = len(frame_data.get(sorted_ts[0], {})) if sorted_ts else 0
            cls_list = [v[2] for v in frame_data.get(sorted_ts[0], {}).values()] if sorted_ts else []
            return {
                'max_simultaneous': count,
                'avg_simultaneous': float(count),
                'peak_ts': sorted_ts[0] if sorted_ts else None,
                'vehicle_classes_at_peak': cls_list,
            }

        # For each frame (except the first), count tracks whose displacement is below threshold
        counts_per_frame = []
        for i in range(1, len(sorted_ts)):
            curr_ts = sorted_ts[i]
            prev_ts = sorted_ts[i - 1]
            curr = frame_data[curr_ts]
            prev = frame_data[prev_ts]

            stopped_tids = []
            for tid, (xc, yc, cls) in curr.items():
                if tid in prev:
                    px, py, _ = prev[tid]
                    disp = math.sqrt((xc - px) ** 2 + (yc - py) ** 2)
                    if disp <= BASE_STOPPED_PX:
                        stopped_tids.append((tid, cls))
                else:
                    # First appearance in this frame — consider stopped (just arrived/detected)
                    stopped_tids.append((tid, cls))

            counts_per_frame.append((curr_ts, len(stopped_tids), [c for _, c in stopped_tids]))

        if not counts_per_frame:
            return {'max_simultaneous': 0, 'avg_simultaneous': 0.0, 'peak_ts': None,
                    'vehicle_classes_at_peak': []}

        max_count = max(c for _, c, _ in counts_per_frame)
        avg_count = sum(c for _, c, _ in counts_per_frame) / len(counts_per_frame)
        peak_entry = max(counts_per_frame, key=lambda x: x[1])

        return {
            'max_simultaneous': max_count,
            'avg_simultaneous': round(avg_count, 2),
            'peak_ts': round(peak_entry[0], 3),
            'vehicle_classes_at_peak': peak_entry[2],
        }

    # ── Stopped phase ─────────────────────────────────────────────────────

    def _find_stopped_phase(self, points: list, shuttle_speed_kmh: float) -> Optional[int]:
        """
        Find the index where the vehicle first enters a stationary phase.
        Returns None if no stopped phase found.

        Ego-motion compensation: relax stopped threshold proportionally to shuttle speed.
        """
        threshold = BASE_STOPPED_PX + shuttle_speed_kmh * SPEED_FACTOR_PX_PER_KMH
        consecutive = 0
        start_idx = None

        for i in range(1, len(points)):
            prev = points[i - 1]
            curr = points[i]
            dx = curr[1] - prev[1]  # x_center delta
            dy = curr[2] - prev[2]  # y_center delta
            displacement = math.sqrt(dx * dx + dy * dy)

            if displacement <= threshold:
                if consecutive == 0:
                    start_idx = i - 1
                consecutive += 1
                if consecutive >= MIN_STOPPED_FRAMES:
                    return start_idx
            else:
                consecutive = 0
                start_idx = None

        return None

    # ── Post-stop classification (updated: also returns move_start_idx) ───

    def _classify_post_stop_v2(self, points: list, frame_width: int,
                               road_masks_by_ts: dict = None) -> tuple:
        """
        Classify what happens after the vehicle was stopped.

        When road_masks_by_ts is provided (dict: timestamp → list of road-mask dicts),
        uses road-polygon containment to detect insertion into the shuttle lane.
        Falls back to the center-zone heuristic when no road masks are available.

        Returns (event_type, t_move_start, move_start_idx_in_points):
        - event_type: 'insertion' | 'wait' | 'turn'
        - t_move_start: timestamp when movement begins (None for 'wait')
        - move_start_idx_in_points: index in points where movement starts (None for 'wait')
        """
        center_x = frame_width / 2.0
        center_zone_half = frame_width * CENTER_ZONE_RATIO
        move_threshold = BASE_STOPPED_PX * 2

        # ── Find movement start ───────────────────────────────────────────
        move_start_idx = None
        for i in range(1, len(points)):
            dx = points[i][1] - points[i - 1][1]
            dy = points[i][2] - points[i - 1][2]
            if math.sqrt(dx * dx + dy * dy) > move_threshold:
                move_start_idx = i
                break

        if move_start_idx is None:
            return ('wait', None, None)

        t_move = points[move_start_idx][0]
        post_move = points[move_start_idx:move_start_idx + 10]

        if not post_move:
            return ('wait', None, None)

        # ── Road-mask path: bbox foot enters road polygon ─────────────────
        if road_masks_by_ts:
            from .road_segmenter import _point_in_polygon

            def _get_road_regions(ts):
                """Return road regions for timestamp (nearest within 1 s)."""
                if ts in road_masks_by_ts:
                    return road_masks_by_ts[ts]
                # Nearest-timestamp lookup
                nearest = min(road_masks_by_ts, key=lambda t: abs(t - ts), default=None)
                if nearest is not None and abs(nearest - ts) < 1.0:
                    return road_masks_by_ts[nearest]
                return None

            in_road_count = 0
            for p in post_move:
                # p = (ts, x_c, y_c, bbox_h, cls, x1, y1, x2, y2)
                road_regions = _get_road_regions(p[0])
                if not road_regions:
                    continue
                x_foot = (p[5] + p[7]) / 2.0  # (x1 + x2) / 2
                y_foot = float(p[8])            # y2 (bottom of bbox)
                for region in road_regions:
                    if _point_in_polygon(x_foot, y_foot, region.get('polygon', [])):
                        in_road_count += 1
                        break

            if in_road_count >= MIN_INSERTION_FRAMES:
                return ('insertion', t_move, move_start_idx)
            else:
                # Vehicle moved but didn't enter road polygon → turn/exit
                return ('turn', t_move, move_start_idx)

        # ── Heuristic fallback: center-zone proximity ─────────────────────
        x_before = points[move_start_idx - 1][1]
        post_move_x = [p[1] for p in post_move]
        x_final = post_move_x[-1]

        moves_toward_center = abs(x_final - center_x) < abs(x_before - center_x)
        ends_in_center_zone = abs(x_final - center_x) <= center_zone_half

        if moves_toward_center and ends_in_center_zone:
            return ('insertion', t_move, move_start_idx)
        elif moves_toward_center:
            insertion_frames = sum(
                1 for x in post_move_x
                if abs(x - center_x) < abs(x_before - center_x)
            )
            if insertion_frames >= MIN_INSERTION_FRAMES:
                return ('insertion', t_move, move_start_idx)

        return ('turn', t_move, move_start_idx)

    # ── t2 detection ──────────────────────────────────────────────────────

    def _find_t2(self, points: list, move_start_idx: int, frame_width: int) -> Optional[float]:
        """
        Find t2: the timestamp when the inserted vehicle stabilizes inside the
        shuttle lane, i.e. consecutive frames where:
        1. x_center is within the CENTER_ZONE
        2. displacement per frame is below T2_STABLE_PX

        Returns the timestamp of the first such stable frame, or the last
        known timestamp if the vehicle never fully stabilizes (still an insertion).
        """
        center_x = frame_width / 2.0
        center_zone_half = frame_width * CENTER_ZONE_RATIO

        post_move = points[move_start_idx:]
        if len(post_move) < T2_STABLE_FRAMES:
            # Not enough frames after movement — return last known timestamp
            return points[-1][0] if points else None

        consecutive_stable = 0
        for i in range(1, len(post_move)):
            prev = post_move[i - 1]
            curr = post_move[i]
            dx = curr[1] - prev[1]
            dy = curr[2] - prev[2]
            displacement = math.sqrt(dx * dx + dy * dy)
            in_lane = abs(curr[1] - center_x) <= center_zone_half

            if displacement <= T2_STABLE_PX and in_lane:
                consecutive_stable += 1
                if consecutive_stable >= T2_STABLE_FRAMES:
                    # Return the start of this stable run
                    return post_move[i - T2_STABLE_FRAMES + 1][0]
            else:
                consecutive_stable = 0

        # Vehicle never fully stabilized in lane within the window
        # Return the last tracked timestamp as a conservative t2
        return post_move[-1][0]

    # ── Bbox trajectory ───────────────────────────────────────────────────

    def _record_bbox_trajectory(self, points: list) -> list:
        """
        Build a compact list of bbox positions over time for this track.

        Each entry: {'ts': float, 'x1': int, 'y1': int, 'x2': int, 'y2': int}

        Downsampled to MAX_TRAJ_POINTS if the track is very long, keeping
        uniform temporal distribution.
        """
        if not points:
            return []

        # Uniform downsample if needed
        total = len(points)
        if total <= MAX_TRAJ_POINTS:
            indices = range(total)
        else:
            step = total / MAX_TRAJ_POINTS
            indices = [int(i * step) for i in range(MAX_TRAJ_POINTS)]

        traj = []
        for idx in indices:
            p = points[idx]
            # p = (ts, x_center, y_center, bbox_h, cls, x1, y1, x2, y2)
            if len(p) >= 9:
                traj.append({
                    'ts': round(p[0], 3),
                    'x1': int(p[5]),
                    'y1': int(p[6]),
                    'x2': int(p[7]),
                    'y2': int(p[8]),
                })
            else:
                # Fallback for legacy tuples without full bbox
                x_c, y_c, bh = p[1], p[2], p[3]
                half_w = bh * 0.8  # approximate width from height
                traj.append({
                    'ts': round(p[0], 3),
                    'x1': int(x_c - half_w),
                    'y1': int(y_c - bh / 2),
                    'x2': int(x_c + half_w),
                    'y2': int(y_c + bh / 2),
                })

        return traj
