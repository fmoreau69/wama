"""Servir `/media/` et `/static/` sans dépendre de `DEBUG` — et `/media/` sous une RÈGLE de lecture.

Reste n°2 de l'audit de sécurité du 2026-11-06, décision de Fabien du 2026-11-08 (option b) :
jusque-là, `/media/` était servi SANS aucun contrôle — par l'`Alias` d'Apache
(`C:\\Apache24\\conf\\extra\\wama-common.conf`) et, `DEBUG` allumé, par gunicorn
(`static()` de `wama/urls.py`). Quiconque connaissait l'adresse d'un fichier le lisait, et
`DEBUG = True` restait écrit en dur parce que, sans lui, plus rien ne servait le CSS et le JS.

Désormais :
  • `serve_media` — une session est exigée (un visiteur va à la connexion, sauf pour les fichiers
    de l'identité éphémère que lui donne l'app d'essai, `accounts/visitors.py`), le chemin est confiné
    sous `MEDIA_ROOT` (`media_paths.resolve_under_media_root`), et le fichier n'est servi que si
    LA règle de lecture l'accepte (`media_paths.readable_by` : son arbre, un administrateur, un
    asset système, ce qu'on lui partage). Un fichier DÉRIVÉ (copie de lecture, pics fins de
    l'onde, `video_compat.original_of_copy`) se juge sur son ORIGINAL. Lecture par morceaux
    conservée (`ranged_response`), mêmes en-têtes protecteurs qu'Apache : `nosniff`, et un
    HTML ou un SVG en bac à sable (`MEDIA_STORAGE_TIERING §9.8`).
  • `serve_static` — la vue de toujours (`django.views.static.serve`, sur `STATIC_ROOT`), routée
    explicitement : couper `DEBUG` ne fait plus tomber l'interface.
"""
from __future__ import annotations

import os

#: Les extensions qu'un navigateur EXÉCUTERAIT sur l'origine de WAMA : servies en bac à sable.
SANDBOXED_EXTENSIONS = ('.html', '.htm', '.svg')


def media_judged_path(rel: str) -> str:
    """Le chemin sur lequel se juge la lecture de `rel` : l'original d'un fichier dérivé, sinon
    lui-même."""
    from wama.common.utils.video_compat import original_of_copy
    return original_of_copy(rel) or rel


def serve_media(request, path):
    """`/media/<path>` — servi au compte qui a le droit de le lire, par morceaux si demandé."""
    from django.contrib.auth.views import redirect_to_login
    from django.http import Http404, HttpResponseForbidden, HttpResponseNotModified
    from django.utils.http import http_date
    from django.views.static import was_modified_since

    from wama.common.utils.media_paths import (OutsideMediaRoot, readable_by,
                                               resolve_under_media_root)
    from wama.common.utils.ranged_response import ranged_file_response

    user = request.user
    if not user.is_authenticated:
        # Le VISITEUR de l'app d'essai (le converter) lit les fichiers de SON identité éphémère,
        # retenue par sa session (`accounts/visitors.py`) — l'aperçu de sa conversion en dépend.
        from wama.accounts import visitors
        user = visitors.current(request)
        if user is None:
            return redirect_to_login(request.get_full_path())
    try:
        full, rel = resolve_under_media_root(path)
    except (OutsideMediaRoot, FileNotFoundError):
        raise Http404
    full = str(full)
    if not os.path.isfile(full):
        raise Http404
    if not readable_by(media_judged_path(rel), user):
        return HttpResponseForbidden()
    mtime = os.stat(full).st_mtime
    if not was_modified_since(request.META.get('HTTP_IF_MODIFIED_SINCE'), mtime):
        return HttpResponseNotModified()
    response = ranged_file_response(request, full)
    response['Last-Modified'] = http_date(mtime)
    # La réponse dépend du COMPTE : aucun cache partagé ne doit la resservir à un autre.
    response['Cache-Control'] = 'private'
    response['X-Content-Type-Options'] = 'nosniff'
    if full.lower().endswith(SANDBOXED_EXTENSIONS):
        response['Content-Security-Policy'] = 'sandbox'
    return response


def serve_static(request, path):
    """`/static/<path>` — les fichiers collectés (`STATIC_ROOT`), quel que soit `DEBUG`."""
    from django.conf import settings
    from django.views.static import serve
    return serve(request, path, document_root=settings.STATIC_ROOT)
