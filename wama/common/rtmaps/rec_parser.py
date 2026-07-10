"""
Parser de fichier RTMaps `.rec` (format TEXTE, ligne par ligne).

Un enregistrement RTMaps `.rec` est un fichier texte où chaque ligne a la forme :

    MM:SS.ffffff / composant.sortie#idx[.suffixe][@MM:SS.ffffff][=data]

- le 1er champ = *time of issue* (moment où l'échantillon a été émis dans le diagramme) ;
- `composant.sortie` = le flux (ex. `h264_stream_framer_1.output_stream`,
  `GPS_NMEA0183_3.oPosition`) ;
- `@MM:SS.ffffff` = *timestamp* de l'échantillon (moment de capture) — c'est LUI qui
  sert à synchroniser les flux entre eux (tous dans la même base de temps = début du .rec) ;
- `=data` = la donnée (pour oPosition : `lat<TAB>lon[...]`).

Tous les timestamps partagent la même origine (début du .rec), donc :

    offset_video_gps = video_timestamps[0] - gps[0]['ts']

Et surtout, `video_timestamps[i]` donne le temps RÉEL de la frame i → mapping exact
frame→temps (gère le VFR / les frames perdues), pour une synchro sans dérive.

Brique généraliste WAMA (BIND/pynd/rec2trip-like), autonome et sans dépendance.
"""
import re

# Ligne : "[H:]MM:SS.ffffff / comp.sortie#idx ... [@[H:]MM:SS.ffffff] [=data]"
# Le timestamp est M:SS.ffffff sous 1h, puis H:MM:SS.ffffff au-delà (heures optionnelles).
_TS = r"\d+:\d{2}(?::\d{2})?\.\d{6}"
_LINE_RE = re.compile(
    r"^\s*(?P<toi>" + _TS + r")\s*/\s*"
    r"(?P<stream>[\w.]+?)#(?P<idx>\d+)"
    r"(?:[^@=\n]*)?"
    r"(?:@(?P<ts>" + _TS + r"))?"
    r"(?:=(?P<data>.*))?$"
)

# Détection auto des flux si non fournis.
_VIDEO_HINT = re.compile(r"h264.*output_stream", re.I)
_GPS_HINT = re.compile(r"oPosition$", re.I)


def rec_time_to_seconds(s):
    """'[H:]MM:SS.ffffff' → secondes (float). Gère M:SS (sous 1h) ET H:MM:SS (au-delà)."""
    if not s:
        return None
    parts = s.split(":")
    if len(parts) == 3:        # H:MM:SS.ffffff
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:        # M:SS.ffffff
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _parse_position(data):
    """Data d'un échantillon oPosition → (lat, lon) ou None. Champs séparés par TAB
    (parfois ';'), format `lat lon [alt heading fix ...]`."""
    if not data:
        return None
    parts = re.split(r"[\t;, ]+", data.strip())
    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except (ValueError, IndexError):
        return None
    if abs(lat) > 90 or abs(lon) > 180:
        return None
    return lat, lon


def parse_rec(path, video_stream=None, gps_stream=None, max_lines=None):
    """
    Parse un `.rec` et renvoie un dict :
      {
        'video_stream': str, 'gps_stream': str,
        'video_timestamps': [float, ...],   # temps (s) de chaque frame vidéo
        'gps': [{'ts': float, 'lat': float, 'lon': float}, ...],
        'streams': {stream_name: count},    # inventaire (diagnostic)
        'duration': float,                  # dernier ts vu
      }

    Si `video_stream`/`gps_stream` non fournis, ils sont auto-détectés (1er flux qui
    matche `h264…output_stream` / `…oPosition`). Timestamps relatifs au début du .rec.
    """
    streams = {}
    video_ts = []
    gps = []
    last_ts = 0.0
    vstream = video_stream
    gstream = gps_stream

    with open(path, "r", encoding="latin-1", errors="replace") as f:
        for i, line in enumerate(f):
            if max_lines and i >= max_lines:
                break
            m = _LINE_RE.match(line)
            if not m:
                continue
            stream = m.group("stream")
            streams[stream] = streams.get(stream, 0) + 1

            # Auto-détection des flux cibles.
            if vstream is None and _VIDEO_HINT.search(stream):
                vstream = stream
            if gstream is None and _GPS_HINT.search(stream):
                gstream = stream

            ts_s = rec_time_to_seconds(m.group("ts"))
            if ts_s is None:
                # Certaines lignes n'ont pas de @ts explicite ; fallback sur time-of-issue.
                ts_s = rec_time_to_seconds(m.group("toi"))
            if ts_s is not None and ts_s > last_ts:
                last_ts = ts_s

            if stream == vstream and ts_s is not None:
                video_ts.append(ts_s)
            elif stream == gstream and ts_s is not None:
                pos = _parse_position(m.group("data"))
                if pos:
                    gps.append({"ts": ts_s, "lat": pos[0], "lon": pos[1]})

    return {
        "video_stream": vstream,
        "gps_stream": gstream,
        "video_timestamps": video_ts,
        "gps": gps,
        "streams": streams,
        "duration": last_ts,
    }
