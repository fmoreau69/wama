"""
Browser-compatibility helpers for video files.

These are *infrastructure* primitives — sync, blocking, no progress UI.
They live in ``wama/common/`` because multiple apps need to take a video
file of unknown codec and make it playable in a ``<video>`` HTML element
(typical scenario: user drags an iPhone HEVC clip into an upload zone,
the browser can't preview it, we need it in H.264).

For *user-driven* conversions with progress UI, format selection, batch,
etc., go through the Converter app instead — Converter will eventually
consume these same helpers as its trivial H.264 backend, with async
queueing on top.

Public surface
--------------
- ``BROWSER_COMPATIBLE_CODECS``  : frozenset of codec names browsers play
- ``get_video_codec(path)``      : ffprobe wrapper, returns codec name lowercased
- ``is_browser_compatible_codec(codec)`` : set membership check
- ``ensure_h264(path)``          : if codec is not browser-compatible, re-encode
                                   to H.264 .mp4 (promotes .avi → .mp4 when needed)
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional, Union

logger = logging.getLogger(__name__)


# Codecs HTML5 ``<video>`` can play across Chrome/Firefox/Safari/Edge (modern
# versions). HEVC is acceptable in Safari and recent Chrome; the others are
# universally supported. AVI/MJPG/mp4v/ProRes/DNxHD all need re-encoding.
BROWSER_COMPATIBLE_CODECS: frozenset[str] = frozenset({
    'h264', 'hevc', 'vp8', 'vp9', 'av1',
})


def get_video_codec(file_path: str, *, timeout: int = 10) -> Optional[str]:
    """
    Return the codec name of the first video stream, lowercased
    (e.g. ``'h264'``, ``'mjpeg'``, ``'mpeg4'``). Returns ``None`` when
    ffprobe is unavailable, the file is unreadable, or there is no video
    stream.
    """
    try:
        from wama.common.utils.ffmpeg_utils import get_ffprobe_exe, adapt_path_for_ffmpeg
        _fp = get_ffprobe_exe()
        result = subprocess.run(
            [_fp, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name',
             '-of', 'csv=p=0', adapt_path_for_ffmpeg(file_path, _fp)],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        logger.warning("ffprobe not found — cannot detect codec")
        return None
    except Exception as exc:
        logger.warning(f"Codec detection failed for {file_path}: {exc}")
        return None
    codec = (result.stdout or '').strip().lower()
    return codec or None


def is_browser_compatible_codec(codec: Optional[str]) -> bool:
    """True when the codec is one HTML5 ``<video>`` can play directly."""
    return bool(codec) and codec.lower() in BROWSER_COMPATIBLE_CODECS


def _transcode(source: str, target: str, args: list, *, timeout: int) -> bool:
    """Réencode `source` vers `target` avec les options ffmpeg `args`, par un fichier temporaire
    voisin qui ne remplace `target` qu'une fois complet — un échec ne laisse ni demi-fichier ni
    `target` abîmé. Rend True si `target` est écrit. Partagé par `ensure_h264` et la copie de
    lecture : chacun garde SA recette, le geste d'écriture n'existe qu'une fois."""
    tmp = target + '.tmp.mp4'
    try:
        from wama.common.utils.ffmpeg_utils import adapt_path_for_ffmpeg, get_ffmpeg_exe
        ffmpeg = get_ffmpeg_exe()
        proc = subprocess.run(
            [ffmpeg, '-y', '-v', 'error', '-i', adapt_path_for_ffmpeg(source, ffmpeg), *args,
             adapt_path_for_ffmpeg(tmp, ffmpeg)],
            capture_output=True, text=True, timeout=timeout)
        ok = proc.returncode == 0 and os.path.isfile(tmp)
        if not ok:
            logger.error(f"ffmpeg re-encode failed for {source}: {(proc.stderr or '')[-500:]}")
    except Exception as exc:
        logger.warning(f"ffmpeg invocation failed for {source}: {exc}")
        ok = False
    if not ok:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    os.replace(tmp, target)
    return True


def ensure_h264(file_path: str, *, timeout: int = 1800) -> Union[bool, str]:
    """
    Ensure a video is browser-compatible. When the codec is already in
    ``BROWSER_COMPATIBLE_CODECS``, the function is a no-op. Otherwise the
    file is re-encoded to H.264 (libx264, CRF 18 = visually lossless) in
    place, and the result is returned as a path.

    The output container is promoted from ``.avi`` to ``.mp4`` when needed
    (typical scenario : OpenCV MJPG fallback that wrote a ``.avi`` whose
    extension lies about the actual codec). The original ``.avi`` is
    removed after successful re-encode.

    Returns
    -------
    - ``False``  : no conversion was needed *or* the conversion failed (the
                   caller can keep using the original path).
    - ``str``    : the final file path. May differ from ``file_path`` if the
                   extension was promoted ; callers should update DB pointers
                   accordingly.
    """
    codec = get_video_codec(file_path)
    if codec is None:
        # ffprobe absent or file unreadable — bail out, caller decides
        return False
    if is_browser_compatible_codec(codec):
        return False

    base, ext = os.path.splitext(file_path)
    target_path = base + '.mp4' if ext.lower() == '.avi' else file_path

    logger.info(
        f"Video codec '{codec}' not browser-compatible, re-encoding to H.264: "
        f"{file_path} → {target_path}"
    )

    if not _transcode(file_path, target_path,
                      ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                       '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags', '+faststart'],
                      timeout=timeout):
        return False

    # If the extension changed, drop the legacy file.
    if target_path != file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError as rm_err:
            logger.warning(f"Could not remove original {file_path}: {rm_err}")

    logger.info(f"Re-encoded to H.264: {target_path}")
    return target_path


# ── Lisibilité RÉELLE dans un navigateur, et COPIE DE LECTURE (2026-10-06) ─────────────────
# Décision de Fabien : un média que le navigateur ne lit pas reçoit, DÈS SON IMPORT, une copie
# de lecture servie par l'aperçu SEULEMENT ; l'original reste intact pour les traitements (une
# source quasi sans perte ne se dégrade pas pour être regardée). Rangée dans un dossier CACHÉ de
# l'utilisateur (`users/<id>/.preview/…`), au chemin de l'original : l'arbre des fichiers ne
# l'affiche pas, un import PAR DOSSIER ne la ramasse pas comme une entrée de plus.
#
# ⚠ Pourquoi un verdict de plus à côté de `is_browser_compatible_codec` : celui-ci juge au SEUL
# nom du codec. `SEQ08-01.mp4` (card #1034) le passe — `h264` — alors qu'il est un conteneur AVI
# sous une extension `.mp4`, en profil High 4:4:4 Predictive : illisible par Chrome, pour deux
# raisons dont aucune n'est le codec. `ensure_h264` (réencodage EN PLACE, cam_analyzer) garde
# son verdict : le durcir changerait ce qu'il réécrit.

#: Conteneurs que lit `<video>` (noms `format_name` de ffprobe, qui en liste plusieurs).
BROWSER_CONTAINERS: frozenset[str] = frozenset({'mov', 'mp4', 'webm'})
#: Profils H.264 que décodent les navigateurs (les 10 bits, 4:2:2 et 4:4:4 n'y sont pas).
BROWSER_H264_PROFILES: frozenset[str] = frozenset({
    'baseline', 'constrained baseline', 'main', 'high'})
#: Formats de pixels lus partout.
BROWSER_PIX_FMTS: frozenset[str] = frozenset({'yuv420p', 'yuvj420p'})
#: Dossier caché des copies de lecture, à la racine de l'utilisateur.
PLAYBACK_DIR = '.preview'


def playability(info: Optional[dict]) -> tuple:
    """`(lisible, raison)` d'une vidéo décrite par la sonde COMMUNE (`media_probe.
    probe_video_format` — elle vivait ici sous le nom `probe_video` jusqu'au 2026-10-06, homonyme
    de la sonde d'affichage : revérification « rien réinventé ») — pure. HEVC n'est pas compté
    lisible : Chrome ne le lit qu'avec un décodeur matériel, que le serveur ne peut pas savoir."""
    if not info:
        return False, 'aucun flux vidéo lisible'
    if not set(info['container'].split(',')) & BROWSER_CONTAINERS:
        return False, f"conteneur {info['container'] or 'inconnu'}"
    codec = info['codec']
    if codec not in ('h264', 'vp8', 'vp9', 'av1'):
        return False, f'codec {codec or "inconnu"}'
    if codec == 'h264' and info['profile'] not in BROWSER_H264_PROFILES:
        return False, f"profil H.264 {info['profile'] or 'inconnu'}"
    if info['pix_fmt'] and info['pix_fmt'] not in BROWSER_PIX_FMTS:
        return False, f"pixels {info['pix_fmt']}"
    return True, ''


def playback_copy_rel(rel: str) -> str:
    """Le chemin (relatif à MEDIA_ROOT) de la copie de lecture d'un média — pure. Sous
    `users/<id>/` : `users/<id>/.preview/<reste>.mp4` ; ailleurs : `.preview/<chemin>.mp4`."""
    rel = str(rel or '').replace('\\', '/').lstrip('/')
    parts = rel.split('/')
    if len(parts) > 2 and parts[0] == 'users':
        return '/'.join(parts[:2] + [PLAYBACK_DIR] + parts[2:]) + '.mp4'
    return f'{PLAYBACK_DIR}/{rel}.mp4'


def _absolute(rel: str) -> str:
    from django.conf import settings
    return os.path.join(settings.MEDIA_ROOT, rel)


def playback_copy_for(rel: str) -> str:
    """La copie de lecture À JOUR d'un média (chemin relatif), ou '' — plus ancienne que
    l'original, elle ne vaut plus (l'original a été remplacé)."""
    copy = playback_copy_rel(rel)
    try:
        if os.path.getmtime(_absolute(copy)) >= os.path.getmtime(_absolute(rel)):
            return copy
    except OSError:
        pass
    return ''


def make_playback_copy(rel: str, *, timeout: int = 3600) -> str:
    """Crée la copie de lecture d'un média si le navigateur ne le lit pas — idempotent. Rend le
    chemin de la copie, ou '' (lisible tel quel, pas une vidéo, ou échec : l'original reste
    servi, rien n'est perdu). Même résolution et même cadence que l'original : les détections
    dessinées sur l'aperçu tombent au même endroit."""
    if playback_copy_for(rel):
        return playback_copy_rel(rel)
    source = _absolute(rel)
    if not os.path.isfile(source):
        return ''
    from wama.common.utils.media_probe import probe_video_format
    playable, reason = playability(probe_video_format(source))
    if playable:
        return ''
    copy = playback_copy_rel(rel)
    target = _absolute(copy)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if not _transcode(source, target,
                      ['-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'libx264', '-preset', 'veryfast',
                       '-crf', '20', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                       '-b:a', '160k', '-movflags', '+faststart'], timeout=timeout):
        return ''
    logger.info(f"[lecture] copie de lecture de {rel} ({reason}) → {copy}")
    return copy


def drop_playback_copy(rel: str) -> bool:
    """Retire la copie de lecture d'un média (l'original part). Ne lève jamais."""
    try:
        os.remove(_absolute(playback_copy_rel(rel)))
        return True
    except OSError:
        return False


def original_of_copy(copy_rel: str) -> str:
    """L'original (chemin relatif) d'une copie de lecture — l'inverse de `playback_copy_rel`."""
    copy_rel = str(copy_rel or '').replace('\\', '/')
    if not copy_rel.endswith('.mp4'):
        return ''
    parts = copy_rel[:-4].split('/')
    if len(parts) > 3 and parts[0] == 'users' and parts[2] == PLAYBACK_DIR:
        return '/'.join(parts[:2] + parts[3:])
    if parts and parts[0] == PLAYBACK_DIR:
        return '/'.join(parts[1:])
    return ''


def sweep_orphan_playback_copies(dry_run: bool = False) -> dict:
    """Retire les copies de lecture dont l'original n'existe plus — quel que soit le geste qui
    l'a fait partir (retrait, arbre des fichiers, rétention, dossier vidé à la main). Une copie
    orpheline n'est de toute façon jamais servie (`playback_copy_for` lit l'original) : ce
    balayage ne rend que la place. Rend `{'seen', 'removed'}`."""
    from django.conf import settings
    root = str(settings.MEDIA_ROOT)
    roots = [os.path.join(root, PLAYBACK_DIR)]
    users = os.path.join(root, 'users')
    if os.path.isdir(users):
        roots += [os.path.join(users, u, PLAYBACK_DIR) for u in os.listdir(users)]
    seen = removed = 0
    for top in roots:
        if not os.path.isdir(top):
            continue
        for folder, _dirs, files in os.walk(top):
            for name in files:
                path = os.path.join(folder, name)
                copy = os.path.relpath(path, root).replace('\\', '/')
                seen += 1
                original = original_of_copy(copy)
                if original and os.path.isfile(_absolute(original)):
                    continue
                if not dry_run:
                    try:
                        os.remove(path)
                    except OSError:
                        continue
                removed += 1
    return {'seen': seen, 'removed': removed}


#: Extensions vidéo d'après le vocabulaire média COMMUN (`app_registry.VIDEO_EXTENSIONS`).
def _video_extensions() -> frozenset:
    from wama.common.app_registry import VIDEO_EXTENSIONS
    return frozenset(e.lower() for e in VIDEO_EXTENSIONS)


def schedule_playback_copy(rel: str) -> bool:
    """Met en file la copie de lecture d'un média vidéo, UNE fois par version du fichier (chemin,
    taille, date) : le récepteur passe à chaque enregistrement de la card, la file ne voit que le
    premier. Rend True si une tâche part. Ne lève jamais : un import n'échoue pas pour un aperçu."""
    rel = str(rel or '').replace('\\', '/')
    if not rel or os.path.splitext(rel)[1].lower() not in _video_extensions():
        return False
    if f'/{PLAYBACK_DIR}/' in f'/{rel}':
        return False                              # une copie de lecture n'en reçoit pas
    try:
        stat = os.stat(_absolute(rel))
    except OSError:
        return False
    try:
        from django.core.cache import cache
        from django.db import transaction

        from wama.common.tasks import make_playback_copy_task
        if not cache.add(f'playback:{rel}:{stat.st_size}:{int(stat.st_mtime)}', 1, 30 * 86400):
            return False
        transaction.on_commit(lambda: make_playback_copy_task.delay(rel))
        return True
    except Exception as exc:
        logger.debug(f"[lecture] mise en file ignorée pour {rel} : {exc}")
        return False


def backfill_playback_copies(dry_run: bool = False) -> dict:
    """Le RATTRAPAGE : les vidéos que des cards portaient AVANT le récepteur (aucun import ne
    repassera dessus). Parcourt les champs fichier de toutes les cards et met en file une copie
    par vidéo — la tâche décide (lisible tel quel : rien). Rend `{'videos', 'queued'}`."""
    from wama.common.utils.file_references import EXCLUDED_MODELS, file_field_models
    videos, queued = set(), 0
    extensions = _video_extensions()
    for model, fields in file_field_models():
        if model._meta.label in EXCLUDED_MODELS:
            continue
        for field in fields:
            names = (model.objects.exclude(**{field.name: ''})
                     .values_list(field.name, flat=True).distinct())
            for name in names:
                if name and os.path.splitext(name)[1].lower() in extensions \
                        and f'/{PLAYBACK_DIR}/' not in f'/{name}':
                    videos.add(name)
    for name in sorted(videos):
        if not dry_run and schedule_playback_copy(name):
            queued += 1
    return {'videos': len(videos), 'queued': queued}


_connected = []


def _on_saved(sender, instance, created, update_fields=None, **kwargs):
    """Récepteur `post_save` : toute vidéo qu'une card PORTE (champ fichier) a sa copie de
    lecture si le navigateur ne la lit pas — quelle que soit la voie d'import (téléversement,
    désignation dans l'arbre, dossier connecté, lot). Un enregistrement qui ne touche pas aux
    champs fichier (progression, statut : `update_fields`) est ignoré."""
    fields = _FILE_FIELDS.get(sender) or ()
    if update_fields is not None and not (set(update_fields) & {f.name for f in fields}):
        return
    for field in fields:
        name = getattr(getattr(instance, field.name, None), 'name', '') or ''
        if name:
            schedule_playback_copy(name)


_FILE_FIELDS: dict = {}


def register_playback_copy_receivers():
    """Branche le récepteur sur tout modèle à champ fichier (le recensement COMMUN,
    `file_references.file_field_models`). Appelé depuis `CommonConfig.ready()`."""
    from django.db.models.signals import post_save

    from wama.common.utils.file_references import EXCLUDED_MODELS, file_field_models
    for model, fields in file_field_models():
        if model._meta.label in EXCLUDED_MODELS or model in _connected:
            continue
        _FILE_FIELDS[model] = fields
        post_save.connect(_on_saved, sender=model, dispatch_uid=f'playback_copy:{model._meta.label}')
        _connected.append(model)
