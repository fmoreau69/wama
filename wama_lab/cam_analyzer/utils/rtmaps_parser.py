"""
RTMaps .rec file parser for WAMA cam_analyzer.

RTMaps record format (one line per sample):
    MM:SS.microseconds / StreamName#index@timestamp=value

Streams of interest:
    - GPGGA#N@ts=NMEA_sentence   (lat/lon/alt, ~1 Hz)
    - GPVTG#N@ts=NMEA_sentence   (speed/heading, ~1 Hz)
    - h264_stream_framer_1.output_stream#N@ts=<binary>  (video frames)
    - AccelData#N@ts=x,y,z       (accelerometer, ~10 Hz)

API CSV format (exported separately):
    timestamp(ms), lat, lon, speed, batteryLevel, vehicle_mode, robot_mode
"""
import csv
import logging
import math
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── NMEA helpers ─────────────────────────────────────────────────────────────

def _nmea_lat_lon(lat_str: str, lat_dir: str, lon_str: str, lon_dir: str) -> Optional[tuple]:
    """
    Convert NMEA lat/lon strings to decimal degrees.
    NMEA format: DDDMM.MMMMM (degrees + decimal minutes)
    """
    try:
        # Latitude: DDMM.MMMMM
        lat_deg = int(lat_str[:2])
        lat_min = float(lat_str[2:])
        lat = lat_deg + lat_min / 60.0
        if lat_dir.upper() == 'S':
            lat = -lat

        # Longitude: DDDMM.MMMMM
        lon_deg = int(lon_str[:3])
        lon_min = float(lon_str[3:])
        lon = lon_deg + lon_min / 60.0
        if lon_dir.upper() == 'W':
            lon = -lon

        return lat, lon
    except (ValueError, IndexError):
        return None


def _parse_gpgga(sentence: str) -> Optional[dict]:
    """
    Parse a GPGGA NMEA sentence.
    $GPGGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,x,xx,x.x,x.x,M,...
    Fields: 0=GPGGA, 1=time, 2=lat, 3=N/S, 4=lon, 5=E/W, 6=fix, 7=sats,
            8=hdop, 9=alt, 10=M, ...
    """
    # Strip leading/trailing whitespace and the $ prefix
    sentence = sentence.strip().lstrip('$')
    parts = sentence.split(',')
    if len(parts) < 10:
        return None
    try:
        lat_str, lat_dir = parts[2], parts[3]
        lon_str, lon_dir = parts[4], parts[5]
        if not lat_str or not lon_str:
            return None
        coords = _nmea_lat_lon(lat_str, lat_dir, lon_str, lon_dir)
        if coords is None:
            return None
        lat, lon = coords
        alt = float(parts[9]) if parts[9] else 0.0
        return {'lat': lat, 'lon': lon, 'alt': alt}
    except (ValueError, IndexError):
        return None


def _parse_gpvtg(sentence: str) -> Optional[dict]:
    """
    Parse a GPVTG NMEA sentence.
    $GPVTG,T,d,d,d,d,N,d,d,K,N*cs
    Fields: 0=GPVTG, 1=track_true, 2=T, 3=track_mag, 4=M,
            5=speed_knots, 6=N, 7=speed_kmh, 8=K, 9=mode
    """
    sentence = sentence.strip().lstrip('$')
    # Strip checksum
    if '*' in sentence:
        sentence = sentence[:sentence.index('*')]
    parts = sentence.split(',')
    try:
        heading = float(parts[1]) if parts[1] else 0.0
        # Prefer km/h field (index 7), fallback to knots (index 5)
        speed_kmh = 0.0
        if len(parts) > 7 and parts[7]:
            speed_kmh = float(parts[7])
        elif len(parts) > 5 and parts[5]:
            speed_kmh = float(parts[5]) * 1.852
        return {'speed_kmh': speed_kmh, 'heading': heading}
    except (ValueError, IndexError):
        return None


# ─── RTMaps line parser ────────────────────────────────────────────────────────

# Matches: "MM:SS.microseconds / StreamName#index@timestamp=..."
_LINE_RE = re.compile(
    r'^(\d+:\d+\.\d+)\s*/\s*([^#]+)#(\d+)@(\d+)=(.*)$',
    re.DOTALL,
)

# Stream name patterns
_GPS_STREAMS = re.compile(r'GP(GGA|VTG)', re.IGNORECASE)
_VIDEO_STREAM = re.compile(r'h264_stream', re.IGNORECASE)
_ACCEL_STREAM = re.compile(r'accel', re.IGNORECASE)


def _rec_time_to_seconds(time_str: str) -> float:
    """Convert 'MM:SS.microseconds' to float seconds."""
    try:
        parts = time_str.split(':')
        minutes = int(parts[0])
        seconds = float(parts[1])
        return minutes * 60.0 + seconds
    except (ValueError, IndexError):
        return 0.0


class RTMapsParser:
    """
    Parse a RTMaps .rec file and extract:
    - GPS points (lat, lon, speed_kmh, heading) from NMEA streams
    - Video frame timestamps from h264_stream_framer_1.output_stream
    - Accelerometer data (optional)
    """

    def parse(self, rec_path: str) -> dict:
        """
        Parse the .rec file and return:
        {
            'gps': [{'ts': float, 'lat': float, 'lon': float,
                      'speed_kmh': float, 'heading': float}, ...],
            'video_timestamps': [float, ...],   # ts of each video frame
            'accel': [{'ts': float, 'x': float, 'y': float, 'z': float}, ...],
            'duration': float,
            'rec_start_ts': int,  # first RTMaps timestamp (nanoseconds)
        }
        """
        rec_path = Path(rec_path)
        if not rec_path.exists():
            raise FileNotFoundError(f"RTMaps file not found: {rec_path}")

        gps_raw = []         # list of (ts_ns, {'lat':..., 'lon':..., 'alt':...})
        vtg_raw = []         # list of (ts_ns, {'speed_kmh':..., 'heading':...})
        video_ts = []        # list of ts_ns for video frames
        accel_raw = []       # list of (ts_ns, x, y, z)

        rec_start_ts = None  # first timestamp in nanoseconds

        logger.info(f"[RTMapsParser] Parsing: {rec_path.name}")

        with open(rec_path, 'r', encoding='utf-8', errors='replace') as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith('#'):
                    continue

                m = _LINE_RE.match(line)
                if not m:
                    continue

                _rec_time_str, stream_name, _idx, ts_str, value = m.groups()
                ts_ns = int(ts_str)

                if rec_start_ts is None:
                    rec_start_ts = ts_ns

                # GPS streams
                if _GPS_STREAMS.search(stream_name):
                    nmea = value.strip()
                    if 'GPGGA' in stream_name.upper() or nmea.startswith('$GPGGA') or nmea.startswith('GPGGA'):
                        result = _parse_gpgga(nmea)
                        if result:
                            gps_raw.append((ts_ns, result))
                    elif 'GPVTG' in stream_name.upper() or nmea.startswith('$GPVTG') or nmea.startswith('GPVTG'):
                        result = _parse_gpvtg(nmea)
                        if result:
                            vtg_raw.append((ts_ns, result))

                # Video stream — just collect timestamps
                elif _VIDEO_STREAM.search(stream_name):
                    video_ts.append(ts_ns)

                # Accelerometer
                elif _ACCEL_STREAM.search(stream_name):
                    try:
                        parts = value.split(',')
                        if len(parts) >= 3:
                            accel_raw.append((ts_ns, float(parts[0]), float(parts[1]), float(parts[2])))
                    except ValueError:
                        pass

        if rec_start_ts is None:
            rec_start_ts = 0

        # ── Merge GPS position + speed/heading ──────────────────────────────
        # Both streams are ~1 Hz. Merge by nearest timestamp.
        gps_merged = self._merge_gps_vtg(gps_raw, vtg_raw, rec_start_ts)

        # ── Convert video timestamps to seconds from start ──────────────────
        video_seconds = []
        for ts_ns in video_ts:
            video_seconds.append((ts_ns - rec_start_ts) / 1e9)

        duration = 0.0
        all_ts = [ts for ts, _ in gps_raw] + video_ts
        if all_ts:
            duration = (max(all_ts) - rec_start_ts) / 1e9

        logger.info(
            f"[RTMapsParser] GPS points: {len(gps_merged)}, "
            f"Video frames: {len(video_seconds)}, "
            f"Duration: {duration:.1f}s"
        )

        return {
            'gps': gps_merged,
            'video_timestamps': video_seconds,
            'accel': [
                {'ts': (ts - rec_start_ts) / 1e9, 'x': x, 'y': y, 'z': z}
                for ts, x, y, z in accel_raw
            ],
            'duration': round(duration, 2),
            'rec_start_ts': rec_start_ts,
        }

    def _merge_gps_vtg(self, gps_raw: list, vtg_raw: list, rec_start_ts: int) -> list:
        """
        Merge GPGGA (lat/lon) with GPVTG (speed/heading) by nearest timestamp.
        Returns list of {ts, lat, lon, speed_kmh, heading}.
        """
        merged = []
        # Build speed/heading lookup indexed by ts_ns
        # For each GPGGA point, find closest GPVTG
        vtg_sorted = sorted(vtg_raw, key=lambda x: x[0])

        def find_closest_vtg(ts_ns):
            if not vtg_sorted:
                return {'speed_kmh': 0.0, 'heading': 0.0}
            # Binary search for closest
            lo, hi = 0, len(vtg_sorted) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if vtg_sorted[mid][0] < ts_ns:
                    lo = mid + 1
                else:
                    hi = mid
            # lo is the first index >= ts_ns
            candidates = []
            if lo > 0:
                candidates.append(vtg_sorted[lo - 1])
            if lo < len(vtg_sorted):
                candidates.append(vtg_sorted[lo])
            best = min(candidates, key=lambda x: abs(x[0] - ts_ns))
            return best[1]

        for ts_ns, pos in gps_raw:
            vtg = find_closest_vtg(ts_ns)
            ts_sec = (ts_ns - rec_start_ts) / 1e9
            merged.append({
                'ts': round(ts_sec, 3),
                'lat': pos['lat'],
                'lon': pos['lon'],
                'alt': pos.get('alt', 0.0),
                'speed_kmh': round(vtg.get('speed_kmh', 0.0), 2),
                'heading': round(vtg.get('heading', 0.0), 1),
            })

        merged.sort(key=lambda x: x['ts'])
        return merged


# ─── API CSV merger ────────────────────────────────────────────────────────────

def merge_with_api_csv(rtmaps_gps: list, csv_path: Optional[str]) -> list:
    """
    Merge RTMaps GPS data with API CSV export.
    API CSV format: timestamp(ms), lat, lon, speed, batteryLevel, vehicle_mode, robot_mode

    Strategy:
    - If CSV is available: prefer it as primary source (clean decimal lat/lon)
    - Speed from CSV field 'speed' (unit unspecified — assume km/h from context)
    - Falls back to RTMaps GPS if CSV is absent or empty

    Returns list of {ts, lat, lon, speed_kmh, heading} sorted by ts.
    """
    if not csv_path:
        logger.info("[RTMapsParser] No API CSV provided, using RTMaps GPS only")
        return rtmaps_gps or []

    csv_path = Path(csv_path)
    if not csv_path.exists():
        logger.warning(f"[RTMapsParser] CSV not found: {csv_path}, using RTMaps GPS")
        return rtmaps_gps or []

    csv_points = []
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts_ms = float(row.get('timestamp', row.get('timestamp(ms)', 0)))
                    lat = float(row.get('lat', 0))
                    lon = float(row.get('lon', 0))
                    speed = float(row.get('speed', 0))
                    if lat == 0.0 and lon == 0.0:
                        continue
                    csv_points.append({
                        'ts': round(ts_ms / 1000.0, 3),
                        'lat': lat,
                        'lon': lon,
                        'speed_kmh': round(speed, 2),
                        'heading': 0.0,  # not in CSV
                    })
                except (ValueError, KeyError):
                    continue
    except Exception as e:
        logger.warning(f"[RTMapsParser] Failed to parse CSV: {e}, using RTMaps GPS")
        return rtmaps_gps or []

    if not csv_points:
        logger.warning("[RTMapsParser] CSV empty, using RTMaps GPS")
        return rtmaps_gps or []

    # Normalize timestamps: make them relative to first CSV point
    # (RTMaps ts are already relative to rec_start_ts)
    # If RTMaps data is available, try to add heading from it
    if rtmaps_gps:
        rtmaps_sorted = sorted(rtmaps_gps, key=lambda x: x['ts'])
        rtmaps_start = rtmaps_sorted[0]['ts']
        csv_start = csv_points[0]['ts']
        # Offset to align (both start near 0 from their respective origins)
        offset = csv_start - rtmaps_start

        def get_rtmaps_heading(ts):
            target = ts + offset
            best = min(rtmaps_sorted, key=lambda x: abs(x['ts'] - target))
            return best.get('heading', 0.0)

        for pt in csv_points:
            pt['heading'] = round(get_rtmaps_heading(pt['ts']), 1)

    # Re-normalize CSV ts to start from 0
    if csv_points:
        t0 = csv_points[0]['ts']
        for pt in csv_points:
            pt['ts'] = round(pt['ts'] - t0, 3)

    csv_points.sort(key=lambda x: x['ts'])
    logger.info(f"[RTMapsParser] Using API CSV: {len(csv_points)} GPS points")
    return csv_points
