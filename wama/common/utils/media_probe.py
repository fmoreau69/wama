"""
WAMA Common — Sonde média (durée / codec / dimensions / pages / entrées).

Extraction du `_describe_audio` du transcriber (audit A5-18, 2026-07-06) : la sonde est
générique (toute app qui affiche les propriétés d'un média audio/vidéo sur sa card).
Utilise la brique ffmpeg_utils (chemins candidats + escape hatch FFMPEG_BINARY).

`probe_media(path)` (généralisation 2026-07-09, INSPECTOR_DETAIL_FIELDS.md « chantier lié ») :
sonde TOUS types — image (format • L×H), vidéo (codec • L×H • fps + durée), audio (codec •
kHz • canaux + durée), PDF (pages), archive (entrées) — pour que `source_properties` de
l'inspecteur soit rempli partout, pas seulement là où l'app le calcule. Fail-safe ({} jamais
d'exception) ; variante `probe_media_cached` (cache Django par chemin+mtime) pour les
endpoints à la requête (`detail_registry.build_detail` = consommateur fallback universel).

Dispatch par catégorie via `app_registry.normalize_types()` (source UNIQUE des extensions/
catégories média, initialement bâtie pour le typage des ports studio) — pas de listes
d'extensions locales (doublon identifié 2026-07-09 : cette sonde en avait recréé une, de même
que `media_library.TYPE_GROUPS` ; consolidé sur `app_registry.py`).
"""

import json
import subprocess

from wama.common.app_registry import normalize_types


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


def probe_video(path: str) -> dict:
    """Sonde le premier flux vidéo : codec • L×H • fps, + durée (stream puis format)."""
    from wama.common.utils.ffmpeg_utils import get_ffprobe_exe
    ffprobe = get_ffprobe_exe()
    if not ffprobe:
        return {}
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height,avg_frame_rate,duration:format=duration",
             "-of", "json", path],
            check=True, capture_output=True, text=True,
        )
        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        duration = float(stream.get("duration") or 0)
        if not duration:
            fmt = (data.get("format") or {}).get("duration")
            if fmt:
                duration = float(fmt)
        w, h = stream.get("width"), stream.get("height")
        fps_label = ""
        raw = stream.get("avg_frame_rate") or ""
        if "/" in raw:
            num, den = raw.split("/", 1)
            try:
                fps = float(num) / float(den) if float(den) else 0
                if fps:
                    fps_label = f"{fps:.0f} img/s" if fps == int(fps) else f"{fps:.1f} img/s"
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        dims = f"{w}×{h}" if w and h else ""
        return {
            'duration': duration,
            'duration_display': format_duration(duration),
            'properties': " • ".join(filter(None, [stream.get("codec_name"), dims, fps_label])),
        }
    except Exception:
        return {}


def _gltf_document(path: str):
    """Le document JSON d'un glTF — lu dans le chunk JSON d'un GLB (en-tête binaire 12 octets,
    chunk 0 = JSON, spécification glTF 2.0) ou directement pour un `.gltf`. `None` si illisible.
    Aucune dépendance : on ne décode PAS la géométrie, on lit la TABLE des matières."""
    import struct
    from pathlib import Path
    try:
        if Path(path).suffix.lower() == '.gltf':
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        with open(path, 'rb') as f:
            magic, version, _length = struct.unpack('<4sII', f.read(12))
            if magic != b'glTF':
                return None
            chunk_len, chunk_type = struct.unpack('<I4s', f.read(8))
            if chunk_type != b'JSON':
                return None
            return json.loads(f.read(chunk_len).decode('utf-8'))
    except Exception:
        return None


def probe_object3d(path: str) -> dict:
    """Sonde d'un OBJET 3D (ROADMAP §17ter, trou 2) — ce que le fichier DÉCLARE, sans le décoder.

    Returns:
        {'properties': 'GLB • 3 maillages • 1 234 faces • riggé • 2 animations',
         'attributes': {format, polygons, rigged, animations}}   ← clés de la nature `object3d`
        Pour un format sans table des matières lisible ici (obj, stl, fbx…) : le format seul.
        {} si le fichier est illisible (jamais d'exception).
    """
    from pathlib import Path
    try:
        fmt = Path(path).suffix.lower().lstrip('.')
    except Exception:
        return {}
    attrs = {'format': fmt}
    doc = _gltf_document(path) if fmt in ('glb', 'gltf') else None
    if doc is not None:
        accessors = doc.get('accessors') or []
        faces = 0
        for mesh in doc.get('meshes') or []:
            for prim in mesh.get('primitives') or []:
                idx = prim.get('indices')
                if idx is not None and idx < len(accessors):
                    faces += int(accessors[idx].get('count') or 0) // 3
                else:
                    pos = (prim.get('attributes') or {}).get('POSITION')
                    if pos is not None and pos < len(accessors):
                        faces += int(accessors[pos].get('count') or 0) // 3
        animations = [a.get('name') or f'animation {i + 1}'
                      for i, a in enumerate(doc.get('animations') or [])]
        attrs.update({
            'polygons': faces,
            'rigged': bool(doc.get('skins')),
            'animations': animations,
        })
        n_meshes = len(doc.get('meshes') or [])
        parts = [fmt.upper(), f"{n_meshes} maillage{'s' if n_meshes > 1 else ''}",
                 f"{faces:,} face{'s' if faces > 1 else ''}".replace(',', ' ')]
        if attrs['rigged']:
            parts.append('riggé')
        if animations:
            parts.append(f"{len(animations)} animation{'s' if len(animations) > 1 else ''}")
        return {'properties': ' • '.join(parts), 'attributes': attrs}
    return {'properties': fmt.upper(), 'attributes': attrs}


def probe_media(path: str) -> dict:
    """Sonde générique TOUS types (dispatch par extension).

    Returns:
        dict {'media_type': str, 'properties': str [, 'duration', 'duration_display']}
        — media_type ∈ image|video|audio|pdf|archive|document ('' si inconnu).
        {} si fichier illisible/inconnu (jamais d'exception).
    """
    from pathlib import Path
    try:
        ext = Path(path).suffix.lower()
    except Exception:
        return {}

    # PDF = cas particulier (comptage de pages) même si sa CATÉGORIE canonique est 'document' —
    # vérifié en premier, littéral sur l'extension (pas une catégorie à part dans app_registry).
    if ext == '.pdf':
        pages = None
        try:
            import fitz  # PyMuPDF (déjà utilisé par reader)
            with fitz.open(path) as doc:
                pages = doc.page_count
        except Exception:
            try:
                from pypdf import PdfReader
                pages = len(PdfReader(path).pages)
            except Exception:
                pass
        return {'media_type': 'pdf',
                'properties': f"PDF • {pages} page{'s' if pages and pages > 1 else ''}" if pages else 'PDF'}

    cat = (normalize_types([ext]) or [None])[0]

    if cat == 'image':
        try:
            from PIL import Image
            with Image.open(path) as im:
                return {'media_type': 'image',
                        'properties': " • ".join(filter(None, [im.format, f"{im.width}×{im.height}"]))}
        except Exception:
            return {'media_type': 'image', 'properties': ''}

    if cat == 'video':
        info = probe_video(path)
        return {'media_type': 'video', **info} if info else {'media_type': 'video', 'properties': ''}

    if cat == 'audio':
        info = probe_audio(path)
        return {'media_type': 'audio', **info} if info else {'media_type': 'audio', 'properties': ''}

    if cat == '3d':
        info = probe_object3d(path)
        return {'media_type': '3d', **info} if info else {'media_type': '3d', 'properties': ''}

    if cat == 'archive':
        count = None
        try:
            import zipfile, tarfile
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as z:
                    count = len(z.namelist())
            elif tarfile.is_tarfile(path):
                with tarfile.open(path) as t:
                    count = len(t.getnames())
        except Exception:
            pass
        return {'media_type': 'archive',
                'properties': f"archive • {count} entrée{'s' if count and count > 1 else ''}" if count else 'archive'}

    return {}


def probe_media_cached(path: str, ttl: int = 86400) -> dict:
    """`probe_media` avec cache Django par (chemin, mtime) — pour les endpoints à la requête
    (ex. detail_registry) : une sonde ffprobe/PDF par fichier, pas par clic."""
    import os
    try:
        mtime = int(os.path.getmtime(path))
    except OSError:
        return {}
    key = f"wama:probe:{path}:{mtime}"
    try:
        from django.core.cache import cache
        cached = cache.get(key)
        if cached is not None:
            return cached
    except Exception:
        cache = None
    info = probe_media(path)
    if cache is not None:
        try:
            cache.set(key, info, ttl)
        except Exception:
            pass
    return info
