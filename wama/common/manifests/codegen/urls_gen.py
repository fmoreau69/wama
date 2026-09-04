"""
Gabarit `urls.py` (palier A1, route §10.3) — routes conventionnelles + routes déclarées.

Trois rôles, UNE source de vérité (l'URLconf réelle) :
  - `app_routes(app_id)`  : lit les routes RÉELLES de `wama.<app>.urls` (runtime, déterministe)
    et les sépare : conformes à `ROUTE_TABLE` (compressées : le nom suffit) / déviantes ou
    hors table (déclarées in extenso dans `extra_routes`). Consommé par l'EXTRACT de la
    facette `processing` — remplace l'ancienne affirmation `STANDARD_ENDPOINTS` (une CIBLE
    que le manifeste présentait comme réalité pour les 10 apps, cadrage A0).
  - `render_urls(manifest)` : régénère un `urls.py` complet depuis la facette (table pour les
    noms conventionnels, `extra_routes` tels quels). Rend (None, manquantes) si une route
    n'est couverte ni par la table ni par les déclarations — on ne génère jamais partiel.
  - `current_routes_from_file(path)` : relit un `urls.py` au FICHIER (ast) pour la comparaison
    sémantique du projecteur — jamais le module importé (périmé dès la première écriture).

`ROUTE_TABLE` est l'idiome du PILOTE (converter, l'app la plus proche du jeu standard —
cadrage A0) : les motifs y sont MESURÉS, pas normatifs. Les autres apps déclarent leurs
variantes (`start/<int:pk>/` du transcriber, `_media` de l'anonymizer…) en `extra_routes` ;
harmoniser ces variantes est un chantier de PORTAGE, pas l'affaire du gabarit.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

# Noyau conventionnel MESURÉ (converter, 2026-08-11) : nom → (motif, expression de vue).
# L'ordre de déclaration est l'ordre de rendu (lisibilité du fichier généré).
ROUTE_TABLE = {
    'index':             ('',                              'views.IndexView.as_view()'),
    'upload':            ('upload/',                       'views.upload'),
    'start':             ('<int:pk>/start/',               'views.start'),
    'stop':              ('<int:pk>/stop/',                'views.stop'),
    'status':            ('<int:pk>/status/',              'views.status'),
    'progress':          ('<int:pk>/progress/',            'views.progress'),
    'download':          ('<int:pk>/download/',            'views.download'),
    'delete':            ('<int:pk>/delete/',              'views.delete'),
    'duplicate':         ('<int:pk>/duplicate/',           'views.duplicate'),
    'start_all':         ('start-all/',                    'views.start_all'),
    'download_all':      ('download-all/',                 'views.download_all'),
    'clear_all':         ('clear-all/',                    'views.clear_all'),
    'global_progress':   ('global_progress/',              'views.global_progress'),
    'card_html':         ('card/<int:pk>/html/',           'views.card_html'),
    'console':           ('console/',                      'views.console_content'),
    'about':             ('about/',                        'AppAboutView.as_view()'),
    'help':              ('help/',                         'AppHelpView.as_view()'),
    'reorder':           ('reorder/',                      'views.reorder'),
    'reorder_queue':     ('reorder-queue/',                'views.reorder_queue'),
    'merge':             ('merge/',                        'views.merge'),
    'move_to_batch':     ('move-to-batch/<int:pk>/',       'views.move_to_batch'),
    'remove_from_batch': ('remove-from-batch/<int:pk>/',   'views.remove_from_batch'),
    'consolidate':       ('consolidate/',                  'views.consolidate'),
    'batch_template':    ('batch/template/',               'views.batch_template'),
    'batch_preview':     ('batch/preview/',                'views.batch_preview'),
    'batch_create':      ('batch/create/',                 'views.batch_create'),
    'batch_start':       ('batch/<int:pk>/start/',         'views.batch_start'),
    'batch_update':      ('batch/<int:pk>/update/',        'views.batch_update'),
    'batch_delete':      ('batch/<int:pk>/delete/',        'views.batch_delete'),
    'batch_duplicate':   ('batch/<int:pk>/duplicate/',     'views.batch_duplicate'),
    'batch_download':    ('batch/<int:pk>/download/',      'views.batch_download'),
}

# Variantes de NOM d'une route conventionnelle — MESURÉES sur les 9 manifestes le 2026-08-29 :
# nom canonique → autres orthographes rencontrées (route ou fonction de vue). Le CORPS est le
# même ; seul le nom change. Cette table n'harmonise RIEN (harmoniser reste un chantier de
# PORTAGE, cf. docstring) : elle permet aux gabarits de RECONNAÎTRE une route déjà couverte,
# déclarée sous un autre nom, au lieu de la boucher (501 côté views) ou de la supposer
# (POST 404 muet côté template). Elle vit ici parce que ce module est le propriétaire du
# vocabulaire de routes — la dupliquer dans chaque gabarit est précisément le chemin parallèle
# qu'on veut éviter.
ROUTE_ALIASES = {
    'stop':   ('cancel',),        # converter : `<pk>/cancel/` → views.cancel
    'update': ('update_job',),    # converter : route `update` → views.update_job
    # Cadrage A0 : « status n'existe QUE chez converter ; la convention réelle est
    # progress » — même corps ({id, status, progress, …}), seul le nom change. Sans cet
    # alias, le polling généré se gâtait silencieusement sur le converter (mesuré 31/08 :
    # `poll: False`, aucune boucle émise — un gating qui teste le nom canonique en dur
    # refait exactement le défaut que cette table existe pour absorber).
    'progress': ('status',),
}

# Classes de vues COMMUNES admises dans les expressions (import connu du gabarit).
_COMMON_VIEWS = ('AppAboutView', 'AppHelpView')


def route_variants(canonique: str) -> tuple:
    """Toutes les orthographes admises d'une route conventionnelle (canonique en tête)."""
    return (canonique,) + tuple(ROUTE_ALIASES.get(canonique, ()))


def resolve_route(canonique: str, declarees) -> str:
    """Orthographe RÉELLEMENT déclarée par l'app pour cette route conventionnelle, '' si aucune.
    `declarees` = noms de routes du manifeste (endpoints ∪ extra_routes)."""
    for nom in route_variants(canonique):
        if nom in declarees:
            return nom
    return ''


def urls_file_path(app_id: str) -> Path:
    import wama
    return Path(wama.__file__).parent / app_id / 'urls.py'


def _view_expr(cb, app_id: str):
    """Expression de vue CANONIQUE d'un callback d'URLconf — celle qu'on écrirait dans le
    fichier. La résolution se fait par IDENTITÉ d'attribut du module `views` de l'app, pas
    par `__module__` : une vue produite par une fabrique commune (make_queue_manipulation_views)
    porte le module de la fabrique alors que la vérité d'écriture est `views.<attr>` — et le
    chemin runtime (closure) n'est même pas importable. None = inexprimable (la route ne
    pourra pas être régénérée : elle POISONNE la couverture, jamais de fichier partiel)."""
    views_mod = importlib.import_module(f'wama.{app_id}.views')
    vc = getattr(cb, 'view_class', None)
    if vc is not None:
        for attr, val in vars(views_mod).items():
            if val is vc:
                return f'views.{attr}.as_view()'
        if vc.__module__ == 'wama.common.views':
            return f'{vc.__name__}.as_view()'
        try:
            mod = importlib.import_module(vc.__module__)
            if getattr(mod, vc.__name__, None) is vc:
                return f'{vc.__module__}.{vc.__name__}.as_view()'
        except Exception:
            pass
        return None
    for attr, val in vars(views_mod).items():
        if val is cb:
            return f'views.{attr}'
    try:
        mod = importlib.import_module(cb.__module__)
        if getattr(mod, cb.__name__, None) is cb:
            return f'{cb.__module__}.{cb.__name__}'
    except Exception:
        pass
    return None


def app_routes(app_id: str) -> tuple:
    """(endpoints triés, extra_routes) réels de `wama.<app>.urls`. Une route est `extra`
    dès que (motif, vue) dévie de ROUTE_TABLE — la fidélité ne dépend donc PAS de la
    justesse de la table, seulement le taux de compression. Les extras gardent l'ORDRE de
    l'URLconf (l'ordre EST la sémantique de résolution Django — pas de tri cosmétique).

    Une entrée qu'on ne sait pas ré-exprimer — include() imbriqué, route anonyme, nom en
    doublon, vue inexprimable — est déclarée `view: None` : elle EMPOISONNE la couverture
    (`routes_target` la range en manquantes) au lieu de disparaître en silence. La sauter
    ferait mentir l'axe ① du harnais : le fichier régénéré sans elle se ré-extrairait
    identique au manifeste qui l'ignorait déjà."""
    mod = importlib.import_module(f'wama.{app_id}.urls')
    routes, poisons, vus = [], [], set()
    for i, p in enumerate(getattr(mod, 'urlpatterns', [])):
        cb = getattr(p, 'callback', None)
        name = getattr(p, 'name', None)
        if cb is None or not name:
            poisons.append({'name': f'<entrée {i} : include() ou route anonyme>',
                            'pattern': str(getattr(p, 'pattern', '')), 'view': None})
            continue
        if name in vus:
            poisons.append({'name': name, 'pattern': str(p.pattern), 'view': None})
            continue
        vus.add(name)
        routes.append((name, str(p.pattern), _view_expr(cb, app_id)))
    noms = sorted(r[0] for r in routes)
    extras = [{'name': n, 'pattern': pat, 'view': v}
              for n, pat, v in routes
              if v is None or ROUTE_TABLE.get(n) != (pat, v)]
    return noms, extras + poisons


def routes_target(manifest: dict) -> tuple:
    """Table {name: (pattern, view)} PROJETÉE du manifeste + noms non couverts."""
    proc = (manifest.get('body') or {}).get('processing') or {}
    extras = {r['name']: (r['pattern'], r['view'])
              for r in (proc.get('extra_routes') or []) if r.get('name')}
    cible, manquantes = {}, []
    # Toute entrée déclarée SANS vue (inexprimable, include, doublon) empoisonne la
    # couverture, qu'elle figure ou non dans `endpoints` — jamais de fichier partiel.
    manquantes += [r['name'] for r in (proc.get('extra_routes') or [])
                   if r.get('name') and not r.get('view')]
    for name in (proc.get('endpoints') or []):
        if name in manquantes:
            continue
        if name in extras and extras[name][1]:
            cible[name] = extras[name]
        elif name in ROUTE_TABLE:
            cible[name] = ROUTE_TABLE[name]
        else:
            manquantes.append(name)
    return cible, manquantes


def namespace_of(manifest: dict) -> str:
    """Le namespace vient d'`identity.url_name` ('converter:index' → 'converter') — l'accesseur
    existant, pas une convention parallèle."""
    url_name = ((manifest.get('body') or {}).get('identity') or {}).get('url_name') or ''
    return url_name.split(':')[0] if ':' in url_name else (manifest.get('key') or '')


def render_urls(manifest: dict) -> tuple:
    """(source, manquantes) — source complète du `urls.py` généré, ou (None, [noms]) si des
    routes ne sont couvertes ni par ROUTE_TABLE ni par extra_routes (jamais de fichier partiel)."""
    from ..builtin.app import _GEN_MARK   # import tardif (pas de cycle au chargement)
    app_id = manifest.get('key')
    proc = (manifest.get('body') or {}).get('processing') or {}
    cible, manquantes = routes_target(manifest)
    if manquantes:
        return None, manquantes
    if not cible:
        return None, ['(facette processing sans endpoints)']

    # Ordre de rendu : table d'abord (ordre de déclaration de ROUTE_TABLE), puis les extras
    # dans l'ORDRE du manifeste (= l'ordre de l'URLconf d'origine : c'est la sémantique de
    # résolution Django, pas un choix cosmétique).
    ordre = [n for n in ROUTE_TABLE if n in cible and cible[n] == ROUTE_TABLE[n]]
    ordre += [r['name'] for r in (proc.get('extra_routes') or [])
              if r.get('name') in cible and r['name'] not in ordre]
    ordre += [n for n in cible if n not in ordre]

    exprs = [cible[n][1] for n in ordre]
    imports = ['from django.urls import path']
    communes = sorted({c for c in _COMMON_VIEWS if any(e.startswith(f'{c}.') for e in exprs)})
    if communes:
        imports.append(f"from wama.common.views import {', '.join(communes)}")
    # Expressions pleinement qualifiées : importer le MODULE porteur (l'attribut est le
    # dernier segment — deux pour `Cls.as_view()`), jamais un préfixe intermédiaire.
    dottes = set()
    for e in exprs:
        if e.startswith('views.') or any(e.startswith(f'{c}.') for c in _COMMON_VIEWS):
            continue
        if '.' in e:
            base = e[:-len('.as_view()')] if e.endswith('.as_view()') else e
            dottes.add(base.rsplit('.', 1)[0])
    imports += [f'import {d}' for d in sorted(dottes)]
    imports.append('from . import views')

    mark = _GEN_MARK.format(app_id=app_id)
    lignes = [
        '"""',
        f"{mark} — urls.py GÉNÉRÉ par write_back_app (facette processing, gabarit A1).",
        '',
        'Routes conventionnelles rendues depuis ROUTE_TABLE (common/manifests/codegen/urls_gen.py),',
        'routes déclarées (extra_routes du manifeste) rendues telles quelles. Ne pas éditer à la',
        'main : rejouer write_back après modification du manifeste.',
        '"""',
        *imports,
        '',
        f"app_name = '{namespace_of(manifest)}'",
        '',
        'urlpatterns = [',
    ]
    larg_pat = max(len(cible[n][0]) for n in ordre) + 3
    larg_vue = max(len(cible[n][1]) for n in ordre) + 1
    for n in ordre:
        pat, vue = cible[n]
        gauche = f"'{pat}',"
        lignes.append(f"    path({gauche:<{larg_pat}} {vue + ',':<{larg_vue}} name='{n}'),")
    lignes.append(']')
    lignes.append('')
    return '\n'.join(lignes), []


def current_routes_from_file(path: Path) -> tuple:
    """({name: (pattern, view_expr)}, app_name) relus du FICHIER via ast — la vérité d'écriture,
    jamais le module importé. Les vues sont ré-exprimées par `ast.unparse` (même canon que
    `_view_expr` pour les idiomes du repo : `views.f`, `Cls.as_view()`)."""
    src = path.read_text(encoding='utf-8')
    arbre = ast.parse(src)
    routes, app_name = {}, None
    for node in ast.walk(arbre):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, 'id', None) == 'app_name' for t in node.targets)
                and isinstance(node.value, ast.Constant)):
            app_name = node.value.value
        if (isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'path'
                and node.args and isinstance(node.args[0], ast.Constant)):
            pattern = node.args[0].value
            vue = ast.unparse(node.args[1]) if len(node.args) > 1 else ''
            name = next((kw.value.value for kw in node.keywords
                         if kw.arg == 'name' and isinstance(kw.value, ast.Constant)), None)
            if name:
                routes[name] = (pattern, vue)
    return routes, app_name
