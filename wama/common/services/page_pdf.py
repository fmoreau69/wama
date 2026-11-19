"""Export PDF d'une page de WAMA (présentations, rapports, fiches) — sans que le serveur s'appelle lui-même.

La page est rendue comme sa vue la rend (`render_to_string` avec la requête), puis confiée à la brique
`html_render.render_page_to_pdf`. Ce que la page demande ensuite à son origine est servi EN PROCESSUS :
les statiques depuis le disque (le dossier servi d'abord), le reste par la vue Django qui répond à ce
chemin, avec l'utilisateur de la requête — une page ne voit donc rien de plus dans son PDF qu'à l'écran.

Le PDF est gardé en cache, indexé par le HTML rendu et la version du rendu : un même contenu ne se
refait pas. Une présentation y garde ses VIDÉOS jouables (`html_render`, 2026-11-19).
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

    def fetch_off_loop(target):
        # Le gestionnaire de route de Playwright s'exécute DANS sa boucle asyncio : l'ORM de Django y
        # lève `SynchronousOnlyOperation` (vu le 2026-11-12 sur `api_released_files`, d'où « Export PDF
        # indisponible »). La vue est donc jouée dans un fil sans boucle, dont la connexion est fermée.
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connection

        def run():
            try:
                return fetch(target)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result()

    return fetch_off_loop


def export_params(slides: bool) -> list:
    """Les RÉGLAGES de l'export PDF d'une page (2026-11-19, demande de Fabien : « une petite modale à
    l'export pdf […] centralisé et parfaitement aligné sur le fonctionnement du converter ») — la
    QUALITÉ de la sortie commune (`output_formats.output_quality_param` : Rapide / Équilibré /
    Qualité), appliquée par le converter aux vidéos embarquées et aux images des pages. Une
    présentation seulement : un document A4 n'a ni capture ni vidéo à réencoder."""
    if not slides:
        return []
    from wama.common.utils.output_formats import output_quality_param
    return [output_quality_param(
        contexts=('item',), dom_id='pageExportQuality',
        help="Qualité des vidéos embarquées (réencodées par le converter) et des images des pages : "
             "« Rapide » donne le PDF le plus léger.")]


def read_export_options(data, slides: bool) -> dict:
    """Les réglages d'un export lus dans `data` (la requête), bornés par leur schéma — un choix hors
    liste lève `ValueError` (la porte commune, `invalid_choice_values`), un réglage absent prend
    son défaut déclaré."""
    from wama.common.utils.param_schema import invalid_choice_values, schema_to_dicts
    schema = schema_to_dicts(export_params(slides))
    given = {p['name']: data.get(p['name']) for p in schema if data.get(p['name']) not in (None, '')}
    bad = invalid_choice_values(schema, given)
    if bad:
        name, (refused, valid) = next(iter(bad.items()))
        raise ValueError(f"{name} : « {', '.join(map(str, refused))} » refusé "
                         f"(valides : {', '.join(valid)})")
    return {p['name']: given.get(p['name'], p.get('default')) for p in schema}


def page_pdf(request, template, *, page_path, slides=False, context=None, options=None):
    """Chemin du PDF de `template` tel que le voit `request.user`, ou None si aucun moteur n'a pu le faire.

    `context` : celui que la VUE de la page passe à son gabarit — sans lui, le PDF montrerait
    une autre page que celle qu'on lit (la frise de la présentation, par exemple).
    `options` : les réglages de l'export (`read_export_options`) — la qualité de sortie.
    """
    import json

    from django.template.loader import render_to_string
    from wama.common.utils.html_render import PAGE_RENDER_VERSION, render_page_to_pdf

    options = dict(options or {})
    html = render_to_string(template, context, request=request)
    # La version du rendu et les réglages entrent dans la clé : un rendu qui change, ou une autre
    # qualité, ne resert pas l'ancien PDF.
    key = hashlib.sha256(f'{PAGE_RENDER_VERSION}\n{json.dumps(options, sort_keys=True)}\n{slides}'
                         f'\n{page_path}\n{html}'.encode('utf-8')).hexdigest()[:24]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f'{key}.pdf'
    if out.is_file() and out.stat().st_size > 0:
        return out
    tmp = out.with_suffix('.part.pdf')
    if not render_page_to_pdf(html, str(tmp), fetch=make_fetcher(request), path=page_path, slides=slides,
                              quality=options.get('output_quality') or ''):
        return None
    tmp.replace(out)
    return out
