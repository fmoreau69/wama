"""
Kind `pipeline` — EXTRAIT de `StudioPipeline.graph` (graphe nommé du canvas studio).

Kind EXTRAIT (l'objet existe en DB) → `extract(key)` + round-trip. `key` = pk du StudioPipeline (str).

Le graphe brut = {"nodes":[{id,app,x,y,params}], "links":[{from,to,to_port}]}. Discipline DÉCLARATIVE
(comme `model`) : on sépare le FONCTIONNEL (nodes id/kind/app/params + links) de la PRÉSENTATION (x/y du
canvas) rangée sous `layout` — cosmétique, préservée pour régénérer le canvas mais hors du cœur du graphe.

Un nœud dont `app` ∈ {text_input, media_import, studio_output} n'est pas une app mais une SOURCE/SINK
(cf. studio_node_ports / GENERIC_APPS) → classé `kind` = source|sink|app.
"""

from __future__ import annotations

from typing import Optional

from ..kinds import ManifestKind, register_kind

SOURCE_NODES = {'text_input', 'media_import'}
SINK_NODES = {'studio_output'}


def _node_kind(app: str) -> str:
    if app in SOURCE_NODES:
        return 'source'
    if app in SINK_NODES:
        return 'sink'
    return 'app'


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
            if k and k not in ('source', 'sink', 'app'):
                errs.append(f"nodes[{nid or i}] : kind '{k}' invalide (source|sink|app)")
            if _node_kind(n.get('app', '')) == 'app' and not n.get('app'):
                errs.append(f"nodes[{nid or i}] : 'app' manquant pour un nœud applicatif")

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


def extract_pipeline(key: str) -> Optional[dict]:
    from wama.studio.models import StudioPipeline

    try:
        p = StudioPipeline.objects.filter(pk=int(key)).first()
    except (ValueError, TypeError):
        p = None
    if p is None:
        return None

    graph = p.graph or {}
    raw_nodes = graph.get('nodes', []) or []
    raw_links = graph.get('links', []) or []

    nodes, layout = [], {}
    for n in raw_nodes:
        nid = n.get('id')
        app = n.get('app', '')
        nodes.append({
            'id': nid,
            'kind': _node_kind(app),
            'app': app or None,
            'params': n.get('params', {}) or {},
        })
        if nid is not None and ('x' in n or 'y' in n):
            layout[str(nid)] = {'x': n.get('x'), 'y': n.get('y')}

    links = [{'from': l.get('from'), 'to': l.get('to'), 'to_port': l.get('to_port')}
             for l in raw_links]

    body = {
        'nodes': nodes,          # fonctionnel
        'links': links,          # fonctionnel
        'layout': layout,        # présentation (x/y canvas), préservée pour régénération
    }

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
    description="Pipeline studio (extrait de StudioPipeline.graph) : nodes (source|sink|app) + links "
                "typés (to_port=group), séparé de la présentation (layout x/y).",
))
