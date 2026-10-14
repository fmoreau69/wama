"""Export PDF d'une page de WAMA (présentations, rapports, fiches) — sans que le serveur s'appelle lui-même.

La page est rendue comme sa vue la rend (`render_to_string` avec la requête), puis confiée à la brique
`html_render.render_page_to_pdf`. Ce que la page demande ensuite à son origine est servi EN PROCESSUS :
les statiques depuis le disque (le dossier servi d'abord), le reste par la vue Django qui répond à ce
chemin, avec l'utilisateur de la requête — une page ne voit donc rien de plus dans son PDF qu'à l'écran.

Le PDF est gardé en cache, indexé par le HTML rendu : un même contenu ne se refait pas.
"""
import hashlib
import mimetypes
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

CACHE_DIR = Path(tempfile.gettempdir()) / 'wama_page_pdf'


def _static_file(rel):
    from django.conf import settings
    from django.contrib.staticfiles import finders
    served = Path(settings.STATIC_ROOT) / rel
    if served.is_file():
        return served
    found = finders.find(rel)
    return Path(found) if found else None


def make_fetcher(request):
    """`fetch(chemin)` → (statut, type, octets), pour l'utilisateur et la session de `request`."""
    from django.conf import settings
    from django.test import RequestFactory
    from django.urls import Resolver404, resolve

    def fetch(target):
        parts = urlsplit(target)
        if parts.path.startswith(settings.STATIC_URL):
            f = _static_file(parts.path[len(settings.STATIC_URL):])
            if f is None:
                return 404, 'text/plain', b''
            return 200, mimetypes.guess_type(str(f))[0] or 'application/octet-stream', f.read_bytes()
        try:
            match = resolve(parts.path)
        except Resolver404:
            return 404, 'text/plain', b''
        sub = RequestFactory().get(parts.path + (f'?{parts.query}' if parts.query else ''))
        sub.user, sub.session = request.user, request.session
        resp = match.func(sub, *match.args, **match.kwargs)
        if hasattr(resp, 'render') and not getattr(resp, 'is_rendered', True):
            resp.render()
        body = b''.join(resp.streaming_content) if resp.streaming else resp.content
        return resp.status_code, resp.get('Content-Type', 'application/octet-stream'), body

    return fetch


def page_pdf(request, template, *, page_path, slides=False, context=None):
    """Chemin du PDF de `template` tel que le voit `request.user`, ou None si aucun moteur n'a pu le faire.

    `context` : celui que la VUE de la page passe à son gabarit — sans lui, le PDF montrerait
    une autre page que celle qu'on lit (la frise de la présentation, par exemple).
    """
    from django.template.loader import render_to_string
    from wama.common.utils.html_render import render_page_to_pdf

    html = render_to_string(template, context, request=request)
    key = hashlib.sha256(f'{slides}\n{page_path}\n{html}'.encode('utf-8')).hexdigest()[:24]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f'{key}.pdf'
    if out.is_file() and out.stat().st_size > 0:
        return out
    tmp = out.with_suffix('.part.pdf')
    if not render_page_to_pdf(html, str(tmp), fetch=make_fetcher(request), path=page_path, slides=slides):
        return None
    tmp.replace(out)
    return out
