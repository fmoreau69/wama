"""
Kind `pipeline` — EXTRAIT de `StudioPipeline.graph` (graphe nommé du canvas studio).

Kind EXTRAIT (l'objet existe en DB) → `extract(key)` + round-trip. `key` = pk du StudioPipeline (str).

Le graphe brut = {"nodes":[{id,app,x,y,params,process?}], "links":[{from,to,to_port}]}. Discipline DÉCLARATIVE
(comme `model`) : on sépare le FONCTIONNEL (nodes id/kind/app/params + links) de la PRÉSENTATION (x/y du
canvas) rangée sous `layout` — cosmétique, préservée pour régénérer le canvas mais hors du cœur du graphe.

DEUX champs, deux natures (2026-10-18, ROUTE §10.6 3.2 — décision D1) : `params` = les VALEURS de
réglage du nœud, celles que l'utilisateur DÉCIDE (l'inspecteur du Studio n'écrit que là) ; `process`
= la DÉCLARATION du process qu'un registre de code exporte (degré, réglages surveillés, sorties,
GPU, part, étage…), relue par les générateurs (`codegen/pipeline_decl.process_specs`). Elles vivaient
toutes deux dans `params` : un geste de l'inspecteur pouvait donc effacer la déclaration (relevé le
2026-10-13). `process` est facultatif — un nœud posé au canvas n'en a pas.

Un nœud dont `app` est un nœud INTÉGRÉ du registre `BUILTIN_NODES` (ci-dessous, R2 du
2026-10-18 — il remplace les ensembles `SOURCE_NODES`/`SINK_NODES`) n'est pas une app mais une
SOURCE/SINK (cf. studio_node_ports / GENERIC_APPS) → classé `kind` = source|sink|app|function
(corrigé le 2026-09-15 : `function` existe depuis le 2026-09-09, cf. D13 ci-dessous).

D13 (`WAMA_DATA_WORLD §9undecies.2`, tranchée le 2026-08-24, CODÉE le 2026-09-09) : UN seul kind
`pipeline`, étendu d'un nœud **`function`** — une fonction du catalogue (`FUNCTION_CATALOG`,
`FunctionSpec` pure ou app-bound) est un nœud au même titre qu'une app, parce qu'un protocole
réel TRAVERSE les mondes (« transcris la vidéo, puis segmente autour des mots-clés »). La
différence app / fonction (job de file asynchrone vs transformation typée synchrone) se traite
dans l'EXÉCUTEUR (`studio/tasks.py` — pièce du futur moteur commun, précisé le 2026-09-15 →
WAMA_APP_GENERATION_ROUTE.md §10.6), qui dispatche sur `kind` — jamais dans le schéma. Sur le
canvas, un nœud fonction porte `app = 'function:<clé>'` (le JS ne connaît qu'un identifiant
de palette) ; `node_kind()` / `function_key()` sont les DEUX seuls lecteurs de cette convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..kinds import ManifestKind, register_kind

# ⏳ Type de nœud `pipeline` (un pipeline enregistré réutilisé comme nœud, sous-graphe) décidé le
# 2026-09-15, NON implémenté — WAMA_APP_GENERATION_ROUTE.md §10.6 3.1.
NODE_KINDS = ('source', 'sink', 'app', 'function')
#: Préfixe d'identifiant de palette d'un nœud fonction (`app` du graphe canvas).
FUNCTION_NODE_PREFIX = 'function:'
#: Les deux rôles d'un nœud INTÉGRÉ : une card d'ENTRÉE (produit une valeur depuis ses réglages)
#: ou une card de SORTIE (range ce qu'elle reçoit). Ni l'une ni l'autre n'est un process.
BUILTIN_ROLES = ('source', 'sink')


@dataclass(frozen=True)
class BuiltinNode:
    """Un nœud INTÉGRÉ du pipeline — card d'entrée ou de sortie —, déclaré UNE fois par son monde.

    ROUTE §10.6 point 3.3bis, marche R2 (2026-10-18). Avant, un nœud intégré se déclarait à SIX
    endroits qui divergeaient : la palette JS (`BUILTINS`, avec un « Batch de prompts » que le
    serveur ne savait pas exécuter), les ensembles `SOURCE_NODES`/`SINK_NODES` d'ici, ses réglages
    (`studio/services/node_params`), son exécuteur (`studio/tasks.SOURCE_HANDLERS` et des branches
    par nom de nœud), et une liste de libellés recopiée dans le message de refus du lancement.
    Désormais la palette, l'inspecteur, le lancement et l'exécuteur lisent CE registre.

    Le registre ne connaît pas ses producteurs : chaque monde inscrit ses nœuds depuis son module
    déclarant (`functions` / `function_specs`, chargé par `function_catalog.load_all`), comme ses
    fonctions — le Studio ses entrées et sa sortie médiathèque, le monde Data sa base connectée et
    son export.

      key         identifiant de palette (`app` du graphe canvas) — une DONNÉE persistée dans les
                  graphes enregistrés : il ne se renomme pas ;
      role        'source' | 'sink' ;
      label, icon, color, description   ce que lit l'utilisateur (palette, inspecteur, refus) ;
      run         source : `run(user, réglages) -> (type, valeur)` ;
                  sink   : `run(user, entrées, réglages, run_id) -> note` — `entrées` = les
                  sorties des nœuds amont (`{'type', 'value', 'is_text'|'is_frame'|'is_lots'}`) ;
      params      `() -> [Param]` — calculé à l'appel (une taxonomie, des formats d'export) ;
      port_label  le libellé du port : la sortie d'une source, l'entrée d'une sortie ;
      port_types  `() -> [types]` — ce que produit une source, ce qu'accepte une sortie ;
      emits       source seulement, optionnel : `emits(réglages) -> {'types': [...], 'text'?}` —
                  ce que la source FOURNIRA, lu dans ses réglages SANS la lancer (le média
                  choisi est une image ; le texte saisi est tel texte). C'est ce que le Studio
                  sait d'un lien avant le lancement (`studio/services/graph_flow.py`, 2026-10-18).
                  Absent, ou rien de décidé : les `port_types` — tout ce que la source PEUT
                  produire, donc une nature inconnue.
      world       le MONDE de la card (`media`, `data`) : la palette range ses entrées par monde
                  — on ne mélange pas les cards d'entrée médias et données (décision de Fabien,
                  2026-10-20, `STUDIO_VISION §Entrées du Studio`) ; vide = transverse ;
      lot         source seulement, optionnel : `lot(user, graphe, nœud) -> [(réglage entry,
                  réglages de l'app alimentée)]` — les ÉLÉMENTS que la card fournit (plusieurs
                  fichiers de travail ou un fichier de lot = un lot, et le pipeline tourne une
                  fois par élément : `studio/services/entries.lot_graphs`). Absent : un seul.
      compose     source seulement, optionnel : ce que la MODALE de la card montre de la card
                  d'entrée v4 de l'app alimentée — `card` (tous ses onglets et sa consigne),
                  `files` (l'onglet de SON port), `lot` (l'onglet du fichier de lot) ; vide : la
                  card ne se compose pas dans une modale (Texte, données).
    """
    key: str
    role: str
    label: str
    icon: str
    color: str
    description: str
    run: Callable
    params: Callable = field(default=lambda: [])
    port_label: str = ''
    port_types: Callable = field(default=lambda: [])
    emits: Optional[Callable] = None
    world: str = ''
    lot: Optional[Callable] = None
    compose: str = ''

    def ports(self) -> dict:
        """Les ports du nœud, sous la MÊME forme que `app_registry.studio_node_ports` et
        `function_catalog.function_node_ports` : `{'inputs': [{id, label, group, types, multi}],
        'output': {id, label, types} | False}` (une sortie n'a pas de port de sortie)."""
        types = list(self.port_types() or [])
        if self.role == 'source':
            return {'inputs': [], 'output': {'id': 'output', 'label': self.port_label,
                                             'types': types}}
        return {'inputs': [{'id': 'travail', 'label': self.port_label, 'group': 'travail',
                            'types': types, 'multi': False}],
                'output': False}


#: clé → `BuiltinNode`, rempli par les mondes (`register_builtin_node`).
BUILTIN_NODES: dict = {}


def register_builtin_node(node: BuiltinNode) -> BuiltinNode:
    """Inscrit un nœud intégré (idempotent : une seconde inscription remplace la première)."""
    if node.role not in BUILTIN_ROLES:
        raise ValueError(f"nœud intégré « {node.key} » : rôle '{node.role}' invalide "
                         f"({'|'.join(BUILTIN_ROLES)})")
    if node.key.startswith(FUNCTION_NODE_PREFIX):
        raise ValueError(f"nœud intégré « {node.key} » : le préfixe '{FUNCTION_NODE_PREFIX}' "
                         f"désigne un nœud fonction")
    BUILTIN_NODES[node.key] = node
    return node


def builtin_nodes() -> dict:
    """Les nœuds intégrés de TOUS les mondes, dans l'ordre d'inscription. Charge les modules
    déclarants s'ils ne l'ont pas encore été (`load_all`, mémorisé : coût nul ensuite)."""
    from wama.common.catalog.function_catalog import load_all
    load_all()
    return BUILTIN_NODES


def builtin_node(key: str) -> Optional[BuiltinNode]:
    """Le nœud intégré `key`, ou None."""
    return builtin_nodes().get(key or '')


def _node_kind(app: str) -> str:
    if (app or '').startswith(FUNCTION_NODE_PREFIX):
        return 'function'
    builtin = builtin_node(app)
    return builtin.role if builtin else 'app'


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
            if 'process' in n and not isinstance(n['process'], dict):
                errs.append(f"nodes[{nid or i}] : 'process' (déclaration du process) doit être "
                            f"un dict")

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
        if n.get('process'):
            node['process'] = n['process']
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


def topo_order(graph):
    """Ordre topologique des nœuds d'un graphe CANVAS (`{nodes, links}`) — rend les NŒUDS
    (dicts), pas leurs identifiants ; lève ValueError si le graphe contient un cycle.

    Écrit dans l'exécuteur du studio (`studio/tasks.py`), remonté ici le 2026-10-02 : le moteur
    à plusieurs process d'une app (`common/services/process_pipeline.py`) ordonne ses process
    par le MÊME graphe — un seul tri pour le canvas et pour les registres de code.

    STABLE (2026-10-03, alignement du cam_analyzer) : à égalité, l'ordre de DÉCLARATION des
    nœuds. C'est l'algorithme de `pass_tracking.topological_order`, repris tel quel — on balaie
    les nœuds dans l'ordre déclaré et on retient ceux dont les amonts sont faits, jusqu'à
    épuisement. Un registre s'en sert pour dire un ordre SANS déclarer une dépendance (le
    cam_analyzer place ses recalages avant le tracking par leur seule position : en faire des
    amonts périmerait le tracking de toute session qui ne les a jamais joués). Le tri d'avant —
    par vague de disponibilité — rendait un ordre valide mais ne tenait pas cette promesse."""
    nodes = {n['id']: n for n in graph.get('nodes', [])}
    incoming = {nid: set() for nid in nodes}
    for l in graph.get('links', []):
        if l['from'] in nodes and l['to'] in nodes:
            incoming[l['to']].add(l['from'])
    order, done, remaining = [], set(), list(nodes)
    while remaining:
        progressed = False
        for nid in list(remaining):
            if incoming[nid] <= done:
                order.append(nid)
                done.add(nid)
                remaining.remove(nid)
                progressed = True
        if not progressed:
            raise ValueError('Le graphe contient un cycle — exécution impossible.')
    return [nodes[nid] for nid in order]


#: Pas de la disposition automatique (px) : une colonne par profondeur, une rangée par nœud.
AUTO_LAYOUT_DX, AUTO_LAYOUT_DY, AUTO_LAYOUT_X0, AUTO_LAYOUT_Y0 = 280, 120, 40, 40


def _depths(node_ids, links):
    """Profondeur de chaque nœud = plus long chemin depuis une racine (graphe acyclique ; un
    cycle, refusé à l'exécution, est simplement borné ici pour ne jamais boucler)."""
    preds = {nid: [] for nid in node_ids}
    for l in links:
        if l.get('from') in preds and l.get('to') in preds:
            preds[l['to']].append(l['from'])
    depth = {}

    def walk(nid, seen):
        if nid in depth:
            return depth[nid]
        if nid in seen:
            return 0
        seen = seen | {nid}
        depth[nid] = 1 + max((walk(p, seen) for p in preds[nid]), default=-1)
        return depth[nid]
    for nid in node_ids:
        walk(nid, frozenset())
    return depth


def _resolve_to_port(src_node, dst_node):
    """Port d'arrivée d'un lien qui n'en précise pas : le premier port d'entrée de la cible dont
    les types croisent la sortie de la source (nœuds fonction) — sinon None (le canvas prend
    alors le premier port). Un registre qui déclare des DÉPENDANCES (pas des flux de données)
    ne dit pas le port ; sans cela `yolo_detect → depth` arrivait sur le port « vidéo »."""
    if node_kind(src_node) != 'function' or node_kind(dst_node) != 'function':
        return None
    from wama.common.catalog.function_catalog import function_node_ports
    try:
        out = function_node_ports(function_key(src_node))['output']
        ins = function_node_ports(function_key(dst_node))['inputs']
    except Exception:
        return None
    # Types produits DANS L'ORDRE déclaré (le plus spécifique d'abord : `detections` avant le
    # générique `table`) — un port vidéo qui accepte `table` ne doit pas capter des détections.
    produced = [] if out is False else list((out or {}).get('types') or [])
    for t in produced:
        for p in ins:
            if t in (p.get('types') or []):
                return p.get('id')
    return None


def body_to_graph(body: dict) -> dict:
    """Inverse de `graph_to_body` : body de manifeste → graphe CANVAS du Studio
    (`{nodes:[{id,app,x,y,params}], links:[{from,to,to_port}]}`) — ce qui permet d'OUVRIR au
    studio un pipeline déclaré en code ou reçu en manifeste (ROUTE §10.6 2.2 : « tout ce qui
    s'exécute dans une file doit pouvoir s'ouvrir au studio »). Un nœud fonction reprend
    l'identifiant de palette `function:<clé>` ; la position vient du `layout`, sinon d'une
    disposition automatique en colonnes par profondeur (un registre n'a pas de présentation)."""
    raw_nodes = (body or {}).get('nodes', []) or []
    raw_links = (body or {}).get('links', []) or []
    layout = (body or {}).get('layout') or {}
    by_id = {n.get('id'): n for n in raw_nodes}
    depth = _depths(list(by_id), raw_links)
    rows = {}
    nodes = []
    for n in raw_nodes:
        nid = n.get('id')
        kind = node_kind(n)
        app = f'{FUNCTION_NODE_PREFIX}{function_key(n)}' if kind == 'function' else n.get('app')
        pos = layout.get(str(nid)) or {}
        if pos.get('x') is None or pos.get('y') is None:
            d = depth.get(nid, 0)
            r = rows.get(d, 0)
            rows[d] = r + 1
            pos = {'x': AUTO_LAYOUT_X0 + d * AUTO_LAYOUT_DX, 'y': AUTO_LAYOUT_Y0 + r * AUTO_LAYOUT_DY}
        node = {'id': nid, 'app': app, 'x': pos['x'], 'y': pos['y'],
                'params': n.get('params', {}) or {}}
        if n.get('process'):
            node['process'] = n['process']
        nodes.append(node)
    links = []
    for l in raw_links:
        to_port = l.get('to_port')
        if not to_port and l.get('from') in by_id and l.get('to') in by_id:
            to_port = _resolve_to_port(by_id[l['from']], by_id[l['to']])
        links.append({'from': l.get('from'), 'to': l.get('to'), 'to_port': to_port})
    return {'nodes': nodes, 'links': links}


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

    from ..ownership import envelope_of

    graph = p.graph or {}

    body = graph_to_body(graph)
    return {
        'manifest_kind': 'pipeline',
        'key': str(p.pk),
        'schema_version': '1.0',
        'name': p.name,
        'description': '',
        'world': 'transverse',       # pipeline transverse
        # Propriétaire, portée et codes lus sur la LIGNE (`ROADMAP §29` étape 4) — la portée
        # était écrite `private` en dur, quel que soit le partage.
        **envelope_of(p, owner_field='user'),
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
