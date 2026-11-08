"""Servir un fichier PAR MORCEAUX (requêtes HTTP `Range`) — ce qui rend un média SEEKABLE.

Né le 2026-10-15 du smoke de la page d'édition de la partition du composer : un clic sur une note
ramenait la lecture à 0:00. Mesuré : `/media/` répondait `200` sans `Accept-Ranges`, sur le
serveur éphémère comme sur le gunicorn vivant (`static.serve` de Django ne connaît pas `Range`) —
un navigateur ne peut alors aller qu'à ce qu'il a déjà téléchargé, et un rendu de 96 Mo ne l'est
jamais. Tout lecteur de WAMA (cards, volet, éditeurs) avait la même limite sans la dire.

La règle vivait déjà, une fois, dans le cam_analyzer (`stream_video`, ses quatre vidéos) : elle
est extraite ici, et il la consomme. Un usage : `ranged_file_response(request, path)`, pour une
vue qui a déjà résolu et AUTORISÉ son fichier — la vidéo du cam_analyzer, et depuis le 2026-11-08
`/media/` lui-même (`media_serving.serve_media`, sous la règle de lecture). Le `serve()` qui
servait `/media/` en `DEBUG`, sans contrôle, est retiré le même jour (`REMOVAL_LEDGER`).
"""
from __future__ import annotations

import mimetypes
import os
import re

_RANGE = re.compile(r'^bytes=(\d*)-(\d*)$')
CHUNK = 64 * 1024


def _iterate(path: str, start: int, length: int):
    with open(path, 'rb') as source:
        source.seek(start)
        remaining = length
        while remaining > 0:
            data = source.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def parse_range(header: str, size: int):
    """`(début, fin)` inclusifs d'un en-tête `Range` à UN intervalle, bornés à la taille ; None si
    l'en-tête est absent, multiple ou illisible (on sert alors le fichier entier) ; `()` s'il ne
    désigne rien de servable (416)."""
    m = _RANGE.match((header or '').strip())
    if not m or size <= 0:
        return None
    first, last = m.group(1), m.group(2)
    if not first and not last:
        return None
    if not first:                       # `bytes=-N` : les N derniers octets
        start, end = max(0, size - int(last)), size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        return ()
    return start, end


def ranged_file_response(request, path: str, content_type: str | None = None):
    """La réponse qui sert `path` — son morceau (206) si la requête en demande un, sinon le
    fichier entier ; toujours `Accept-Ranges: bytes`. `path` est un chemin LOCAL déjà autorisé."""
    from django.http import FileResponse, HttpResponse, StreamingHttpResponse
    size = os.path.getsize(path)
    content_type = content_type or mimetypes.guess_type(path)[0] or 'application/octet-stream'
    wanted = parse_range(request.META.get('HTTP_RANGE', ''), size)
    if wanted == ():
        response = HttpResponse(status=416)
        response['Content-Range'] = f'bytes */{size}'
    elif wanted:
        start, end = wanted
        response = StreamingHttpResponse(_iterate(path, start, end - start + 1), status=206,
                                         content_type=content_type)
        response['Content-Length'] = str(end - start + 1)
        response['Content-Range'] = f'bytes {start}-{end}/{size}'
    else:
        response = FileResponse(open(path, 'rb'), content_type=content_type)
        response['Content-Length'] = str(size)
    response['Accept-Ranges'] = 'bytes'
    return response
