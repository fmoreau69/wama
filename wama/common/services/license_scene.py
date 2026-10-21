"""La SCÈNE des licences (WAMA_SCENES_3D §3.2, C1) — l'exemple de Fabien (2026-10-21) : *« une
constellation de licences avec la distance qui dépend de la proximité de la permissivité des
licences et autres facteurs »*.

Une étoile par licence (taille = éléments couverts), une sphère par FAMILLE (permissive → interdite),
ses satellites = les éléments qu'elle couvre (modèles, librairies, médias). Les apps y entrent
aussi, reliées aux licences que leur composition traverse (`requires` des manifestes) : c'est la
question qui compte au moment de publier — *qu'est-ce qu'une app hérite de pire ?*

RIEN N'EST RECOPIÉ : l'inventaire, la qualification et la traversée par app sont ceux de la page
des licences (`license_audit.inventaire`, `qualifier`, `par_app`) ; le nom et le monde d'une app,
ceux d'`app_registry.app_identity`. Les médias d'utilisateur suivent le périmètre visible du
demandeur, comme sur la page.
"""
from collections import Counter, defaultdict

#: Plafond d'éléments NOMMÉS par licence (satellites et volet) — le compte, lui, est exact.
ITEM_LIMIT = 12

#: Forme d'un satellite selon le registre d'où vient l'élément.
SHAPES = {'model': 'octa', 'library': 'tetra', 'media': 'box'}

UNKNOWN = '(inconnue)'


def _plural(n, one, many):
    return f'{n} {one if n == 1 else many}'


def _one(registry):
    """« modèle » pour `model` — le singulier du nom déclaré (`license_audit.REGISTRES`)."""
    from .license_audit import REGISTRES
    return REGISTRES[registry][:-1].lower()


def license_scene(user=None) -> dict:
    """Le contrat de la scène (`common/scenes.py`) : nœuds, sphères, liens, colorations."""
    from django.urls import reverse

    from wama.common.app_registry import app_identity

    from .license_audit import FAMILLES, REGISTRES, inventaire, par_app

    lines = inventaire(user)
    apps = par_app(lines)
    by_licence = {}
    for line in lines:
        entry = by_licence.setdefault(line['q']['id'] or UNKNOWN, {'q': line['q'], 'lines': []})
        entry['lines'].append(line)
    crossed = defaultdict(dict)                    # licence → {app: éléments requis sous elle}
    for a in apps:
        for e in a['licences']:
            crossed[e['id']][a['app']] = e['n']
    app_label = {a['app']: app_identity(a['app'])['label'] for a in apps}
    catalog_url = reverse('common:licenses_catalog')

    nodes, links = [], []
    for key, entry in sorted(by_licence.items(), key=lambda kv: (kv[1]['q']['rang'], kv[0])):
        q, items = entry['q'], entry['lines']
        regs = Counter(l['registre'] for l in items)
        name = key if key != UNKNOWN else 'Inconnue'
        uncited = sum(1 for l in items if not l['auteur'])
        nodes.append({
            'id': f'lic:{key}', 'kind': 'licence', 'name': name, 'handle': q['famille'],
            'sub': f"{q['famille']} · {_plural(len(items), 'élément', 'éléments')}",
            'size': len(items), 'groups': [f"fam:{q['rang']}"],
            'attrs': {'rank': q['rang'], 'attribution': q['attribution']},
            'attr_labels': {'attribution': 'attribution exigée' if q['attribution'] else 'sans attribution'},
            'sets': {'apps': sorted(crossed.get(key, {}))},
            'cats': {'family': str(q['rang']), 'registry': regs.most_common(1)[0][0]},
            'sats': [{'shape': SHAPES.get(l['registre'], 'dodeca'), 'color': f"--wc-registry-{l['registre']}"}
                     for l in items[:ITEM_LIMIT]],
            'tip': [q['famille'] + (' · attribution exigée' if q['attribution'] else ''),
                    ' · '.join(_plural(n, _one(r), REGISTRES[r].lower()) for r, n in regs.most_common())],
            'detail': {
                'mark': name[:3].upper(),
                'badges': [{'text': q['famille'], 'color': f"--wc-rank-{q['rang']}"}]
                          + ([{'text': 'Attribution exigée'}] if q['attribution'] else []),
                'text': q['explication'],
                'url': catalog_url, 'url_label': 'Catalogue des licences',
                'sections': [
                    {'title': 'Ce qu’elle couvre', 'type': 'kv',
                     'rows': [[REGISTRES[r], str(n)] for r, n in regs.most_common()]
                             + [['Rang', f"{q['rang'] + 1} / {len(FAMILLES)} (permissive → interdite)"]]},
                    {'title': 'Éléments', 'type': 'list',
                     'items': [{'text': l['nom'], 'note': ' · '.join(
                         x for x in (REGISTRES[l['registre']], l['auteur']) if x)} for l in items[:ITEM_LIMIT]],
                     'note': (f"et {len(items) - ITEM_LIMIT} autre(s)." if len(items) > ITEM_LIMIT else '')
                             + (f" {uncited} sans auteur connu : l’attribution ne peut pas être tenue."
                                if q['attribution'] and q['id'] and uncited else '')},
                    {'title': 'Apps qui la traversent', 'type': 'list',
                     'items': [{'text': app_label[app], 'goto': f'app:{app}',
                                'note': _plural(n, 'élément requis', 'éléments requis')}
                               for app, n in sorted(crossed.get(key, {}).items(), key=lambda kv: -kv[1])],
                     'empty': 'Aucune app ne la requiert dans sa composition déclarée.'},
                ],
            },
        })
    for a in apps:
        worst = a['pire']
        nodes.append({
            'id': f"app:{a['app']}", 'kind': 'app', 'layer': 'apps', 'shape': 'octa',
            'name': app_label[a['app']], 'handle': a['app'],
            'sub': 'App · ' + (worst['famille'] if worst else 'aucune licence connue'),
            'size': a['requires'],
            'attrs': {'rank': worst['rang']} if worst else {},
            'cats': {'family': str(worst['rang']) if worst else None, 'registry': 'app'},
            'tip': [f"Hérite au pire : {worst['famille']}" if worst else 'Aucune licence connue',
                    _plural(a['requires'], 'élément requis', 'éléments requis')
                    + (f" · {a['hors_registre']} hors registre" if a['hors_registre'] else '')],
            'detail': {
                'badges': ([{'text': f"Au pire : {worst['famille']}", 'color': f"--wc-rank-{worst['rang']}"}]
                           if worst else []),
                'text': worst['explication'] if worst else '',
                'sections': [
                    {'title': 'Licences traversées', 'type': 'list',
                     'items': [{'text': e['id'] if e['id'] != UNKNOWN else 'Inconnue', 'goto': f"lic:{e['id']}",
                                'note': f"×{e['n']} — {', '.join(e['exemples'])}"} for e in a['licences']],
                     'empty': 'Rien de ce qu’elle requiert n’est au registre.'},
                    {'title': 'Composition', 'type': 'kv',
                     'rows': [['Éléments requis', str(a['requires'])],
                              ['Hors registre', str(a['hors_registre'])]]},
                ],
            },
        })
        for e in a['licences']:
            links.append({'from': f"app:{a['app']}", 'to': f"lic:{e['id']}", 'count': e['n']})

    present = {by_licence[k]['q']['rang'] for k in by_licence}
    groups = [{'id': f'fam:{rank}', 'kind': 'family', 'name': label, 'sub': explanation,
               'color': f'--wc-rank-{rank}', 'legend': label}
              for rank, (label, explanation) in FAMILLES.items() if rank in present]
    return {
        'nodes': nodes, 'groups': groups, 'links': links, 'beams': [],
        'colorings': {
            'family': {'palette': {str(r): f'--wc-rank-{r}' for r in FAMILLES},
                       'legend': [[label, str(r)] for r, (label, _) in FAMILLES.items()]},
            'registry': {'palette': {**{r: f'--wc-registry-{r}' for r in REGISTRES}, 'app': '--wc-registry-app'},
                         'legend': [[label, r] for r, label in REGISTRES.items()] + [['Apps', 'app']]},
        },
    }


def register_scene():
    """Déclare la scène `licenses` (appelé par `CommonConfig.ready`)."""
    from wama.common.scenes import Scene, register_scene as register
    register(Scene(
        key='licenses', page_title='Constellation des licences', kicker='Licences · WAMA',
        description="Les licences de tout ce que WAMA embarque, rapprochées par leur permissivité ; "
                    "les apps reliées à ce que leur composition traverse.",
        data='wama.common.services.license_scene:license_scene', registry='licenses',
        back_url_name='common:licenses_catalog', back_label='Catalogue des licences',
        loading='Chargement des licences…', search_placeholder='Trouver une licence, une app…',
        layers=(
            {'key': 'families', 'role': 'groups', 'label': 'Familles', 'dot': 'rank-0', 'on': True},
            {'key': 'apps', 'role': 'nodes', 'label': 'Apps', 'dot': 'registry-app', 'on': True},
            {'key': 'crossings', 'role': 'links', 'label': 'Traversées', 'dot': 'share', 'on': True},
            {'key': 'items', 'role': 'satellites', 'label': 'Éléments couverts', 'dot': 'ink',
             'glow': 'trans', 'on': True},
        ),
        colorings=({'key': 'family', 'label': 'Famille'}, {'key': 'registry', 'label': 'Registre'}),
        forces_hint="La distance entre deux licences se calcule de ces facteurs ; changez leur "
                    "poids, la constellation se réarrange.",
        factors=(
            {'key': 'permissivity', 'kind': 'closeness', 'attr': 'rank', 'range': 3,
             'label': 'Permissivité voisine', 'value': 3, 'max': 6, 'why': 'permissivité voisine',
             'help': "Deux licences à moins de trois rangs l'une de l'autre, de la plus permissive "
                     "à l'interdite, se rapprochent d'autant plus que leurs rangs sont voisins."},
            {'key': 'family', 'kind': 'groups', 'group': 'family', 'label': 'Même famille',
             'value': 2, 'max': 6, 'help': 'Une famille commune (`license_audit.FAMILLES`).'},
            {'key': 'crossing', 'kind': 'relation', 'label': 'Traversée par une app', 'value': 2.5,
             'max': 6, 'one': 'élément requis', 'many': 'éléments requis',
             'help': "Une app et une licence que sa composition traverse (log du nombre)."},
            {'key': 'apps', 'kind': 'jaccard', 'set': 'apps', 'label': 'Apps communes',
             'value': 1.2, 'max': 4, 'one': 'app commune', 'many': 'apps communes',
             'help': 'Part des apps qui traversent les deux licences.'},
            {'key': 'attribution', 'kind': 'same', 'attr': 'attribution', 'label': 'Attribution',
             'value': 0.5, 'max': 4, 'help': "Toutes deux exigent de citer l'auteur, ou aucune."},
        ),
        group_kinds={
            'family': {'layer': 'families', 'label': 'Famille', 'base': 0.03, 'rim': 0.5,
                       'margin': 1.4, 'pull': {'weight': 'family', 'k': 0.012}},
        },
        stats=({'count': 'nodes', 'kind': 'licence', 'one': 'licence', 'many': 'licences'},
               {'count': 'groups', 'kind': 'family', 'one': 'famille', 'many': 'familles'},
               {'count': 'nodes', 'kind': 'app', 'one': 'app', 'many': 'apps'},
               {'count': 'links', 'one': 'élément requis traversé',
                'many': 'éléments requis traversés'}),
        legend={
            'intro': "Chaque étoile est une licence : sa taille dit combien d'éléments elle "
                     "couvre, sa place sa permissivité. Les octaèdres sont les apps, reliées aux "
                     "licences que leur composition traverse.",
            'nodes_note': "Taille = éléments couverts (modèles, librairies, médias).",
            'sats': [{'label': f'Satellite : {_one(r)}', 'color': f'--wc-registry-{r}'}
                     for r in ('model', 'library', 'media')],
            'groups_note': "Une sphère enveloppe les licences d'une même famille.",
            'links': [{'label': "Traversée : une app requiert des éléments sous cette licence",
                       'color': '--wc-share'}],
            'notes': ["Les licences se lisent au catalogue des licences ; corriger une licence se "
                      "fait à la source (catalogue de modèles, manifeste de librairie, fiche du média)."],
        },
        nearest_empty="Rien ne relie encore cette licence aux autres.",
        layout={'repulsion': 40, 'spring': 0.03, 'rest': 16, 'spread': 1.6, 'home': 46},
    ))
