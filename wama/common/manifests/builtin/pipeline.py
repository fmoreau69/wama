"""
Kind `pipeline` — EXTRAIT de `StudioPipeline.graph` (graphe nommé du canvas studio).

Kind EXTRAIT (l'objet existe en DB) → `extract(key)` + round-trip. `key` = pk du StudioPipeline (str).

Le graphe brut = {"nodes":[{id,app,x,y,params}], "links":[{from,to,to_port}]}. Discipline DÉCLARATIVE
(comme `model`) : on sépare le FONCTIONNEL (nodes id/kind/app/params + links) de la PRÉSENTATION (x/y du
canvas) rangée sous `layout` — cosmétique, préservée pour régénérer le canvas mais hors du cœur du graphe.

Un nœud dont `app` ∈ {text_input, media_import, dataset_input, studio_output} n'est pas une app
mais une SOURCE/SINK (cf. studio_node_ports / GENERIC_APPS) → classé `kind` = source|sink|app.

D13 (`WAMA_DATA_WORLD §9undecies.2`, tranchée le 2026-08-24, CODÉE le 2026-09-09) : UN seul kind
`pipeline`, étendu d'un nœud **`function`** — une fonction du catalogue (`FUNCTION_CATALOG`,
`FunctionSpec` pure ou app-bound) est un nœud au même titre qu'une app, parce qu'un protocole
réel TRAVERSE les mondes (« transcris la vidéo, puis segmente autour des mots-clés »). La
différence app / fonction (job de file asynchrone vs transformation typée synchrone) se traite
dans l'EXÉCUTEUR (`studio/tasks.py`), qui dispatche sur `kind` — jamais dans le schéma. Sur le
canvas, un nœud fonction porte `app = 'function:<clé>'` (le JS ne connaît qu'un identifiant
de palette) ; `node_kind()` / `function_key()` sont les DEUX seuls lecteurs de cette convention.
"""

from __future__ import annotations

from typing import Optional

from ..kinds import ManifestKind, register_kind

SOURCE_NODES = {'text_input', 'media_import', 'dataset_input'}
SINK_NODES = {'studio_output'}
NODE_KINDS = ('source', 'sink', 'app', 'function')
#: Préfixe d'identifiant de palette d'un nœud fonction (`app` du graphe canvas).
FUNCTION_NODE_PREFIX = 'function:'


def _node_kind(app: str) -> str:
    if app in SOURCE_NODES:
        return 'source'
    if app in SINK_NODES:
        return 'sink'
    if (app or '').startswith(FUNCTION_NODE_PREFIX):
        return 'function'
    return 'app'


def node_kind(node: dict) -> str:
    """Kind d'un nœud, forme CANVAS (`app`) ou forme MANIFESTE (`kind` explicite) — le point
    de dispatch unique de l'exécuteur et du validateur."""
    return node.get('kind') or _node_kind(node.get('app') or '')


def function_key(node: dict) -> str:
    """Clé `FUNCTION_CATALOG` d'un nœud `function` ('' sinon) — les deux formes acceptées."""
    if node.get('function'):
        return str(node['function'])
    app = node.get('app') or ''
    return app[len(FUNCTION_NODE_PREFIX):] if app.startswith(FUNCTION_NODE_PREFIX) else ''


def validate_pipeline_body(body: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(body, dict):
        return ["body 'pipeline' doit être un dict"]

    nodes = body.get('nodes')
    node_ids: set = set()
    if not isinstance(nodes, list):
        errs.append("nodes doit être une liste")
        nodes = []
    else:
        for i, n in enumerate(nodes):
            if not isinstance(n, dict):
                errs.append(f"nodes[{i}] doit être un dict"); continue
            nid = n.get('id')
            if not nid:
                errs.append(f"nodes[{i}] : 'id' manquant")
            else:
                if nid in node_ids:
                    errs.append(f"nodes : id '{nid}' dupliqué")
                node_ids.add(nid)
            k = n.get('kind')
            if k and k not in NODE_KINDS:
                errs.append(f"nodes[{nid or i}] : kind '{k}' invalide ({'|'.join(NODE_KINDS)})")
            kind = node_kind(n)
            if kind == 'app' and not n.get('app'):
                errs.append(f"nodes[{nid or i}] : 'app' manquant pour un nœud applicatif")
            if kind == 'function' and not function_key(n):
                errs.append(f"nodes[{nid or i}] : 'function' (clé du catalogue) manquante "
                            f"pour un nœud fonction")

    links = body.get('links', [])
    if not isinstance(links, list):
        errs.append("links doit être une liste")
    else:
        for i, l in enumerate(links):
            if not isinstance(l, dict):
                errs.append(f"links[{i}] doit être un dict"); continue
            for end in ('from', 'to'):
                ref = l.get(end)
                if not ref:
                    errs.append(f"links[{i}] : '{end}' manquant")
                elif node_ids and ref not in node_ids:
                    errs.append(f"links[{i}] : '{end}' référence un nœud inconnu '{ref}'")
    return errs


def graph_to_body(graph: dict) -> dict:
    """Graphe CANVAS (`{nodes:[{id,app,x,y,params}], links}`) → body du manifeste : le
    FONCTIONNEL (nodes id/kind/app|function/params + links) séparé de la PRÉSENTATION (layout).
    Un nœud fonction sort avec `kind='function'` + `function=<clé>` et `app=None` — la
    convention de palette `function:` ne franchit pas la frontière du manifeste."""
    raw_nodes = (graph or {}).get('nodes', []) or []
    raw_links = (graph or {}).get('links', []) or []
    nodes, layout = [], {}
    for n in raw_nodes:
        nid = n.get('id')
        app = n.get('app', '')
        kind = node_kind(n)
        node = {'id': nid, 'kind': kind,
                'app': None if kind == 'function' else (app or None),
                'params': n.get('params', {}) or {}}
        if kind == 'function':
            node['function'] = function_key(n)
        nodes.append(node)
        if nid is not None and ('x' in n or 'y' in n):
            layout[str(nid)] = {'x': n.get('x'), 'y': n.get('y')}
    links = [{'from': l.get('from'), 'to': l.get('to'), 'to_port': l.get('to_port')}
             for l in raw_links]
    return {
        'nodes': nodes,          # fonctionnel
        'links': links,          # fonctionnel
        'layout': layout,        # présentation (x/y canvas), préservée pour régénération
    }


#: Pipelines DÉCLARÉS EN CODE (registre d'un monde, ex. `cam_analyzer.pass_tracking.PASSES`) —
#: clé → fabrique de manifeste complet. Le kind ne connaît pas ses producteurs : chaque monde
#: s'y inscrit depuis son module déclarant (`function_specs` / `functions`, chargé par
#: `function_catalog.load_all()`), exactement comme les fonctions. « UNE représentation, DEUX
#: éditeurs » (§9undecies) : le canvas (DB, clé = pk) et le registre (code, clé = nom).
PIPELINE_SOURCES: dict = {}


def register_pipeline_source(key: str, factory) -> None:
    """Inscrit une fabrique `() -> manifeste pipeline complet` sous `key` (idempotent)."""
    PIPELINE_SOURCES[key] = factory


def registered_pipeline_keys() -> list:
    from wama.common.catalog.function_catalog import load_all
    try:
        load_all()
    except Exception:
        pass
    return sorted(PIPELINE_SOURCES)


def extract_pipeline(key: str) -> Optional[dict]:
    """Clé numérique → `StudioPipeline` (canvas) ; sinon → pipeline déclaré en code."""
    from wama.studio.models import StudioPipeline

    try:
        p = StudioPipeline.objects.filter(pk=int(key)).first()
    except (ValueError, TypeError):
        p = None
    if p is None:
        registered_pipeline_keys()
        factory = PIPELINE_SOURCES.get(str(key))
        return factory() if factory else None

    graph = p.graph or {}

    body = graph_to_body(graph)
    return {
        'manifest_kind': 'pipeline',
        'key': str(p.pk),
        'schema_version': '1.0',
        'name': p.name,
        'description': '',
        'world': 'transverse',       # orchestration studio
        'owner': p.user.get_username() if p.user_id else None,
        'visibility': 'private',     # un pipeline utilisateur est privé par défaut
        'projects': [],
        'source': {'type': 'extract', 'ref': f'StudioPipeline:{p.pk}'},
        'body': body,
    }


register_kind(ManifestKind(
    kind='pipeline',
    validate=validate_pipeline_body,
    extract=extract_pipeline,
    description="Pipeline (extrait de StudioPipeline.graph OU d'un registre de code inscrit par "
                "register_pipeline_source) : nodes (source|sink|app|function — D13) + links typés "
                "(to_port = id de port), séparé de la présentation (layout x/y).",
))
