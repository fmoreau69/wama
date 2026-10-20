"""
Studio — le GRAPHE comme porteur de valeurs : ce que chaque nœud FOURNIT, connu avant le lancement,
et ce que chaque nœud en REÇOIT (ROUTE §10.6 point 3.3bis, règle 5 — 2026-10-18).

« Le porteur des valeurs se déclare ; le schéma ne change pas avec lui. » Sur une card, c'est
l'ÉLÉMENT qui porte la nature de son fichier (`media_type`, posé au dépôt) ou le texte à dire : les
conditions d'affichage du schéma (`show_if`) et ses listes d'options s'en déduisent. Au Studio il
n'y a pas encore d'élément : le porteur est le graphe. Le nœud Converter montrait 1 réglage sur 19,
l'Avatarizer ne montrait jamais la voix — leurs schémas étaient justes, rien ne leur disait ce qui
leur était branché.

UN parcours, pas deux : `node_flows` est le parcours topologique que faisait seul
`launch.diagnostiquer_chainage` pour les CHAMPS des fonctions pures (« c'est CE parcours qu'on
étend — pas un second », `function_catalog.champs_apres`). Il porte désormais aussi les TYPES de ce
qui sort de chaque nœud et le TEXTE d'une saisie ; le diagnostic lit les champs ici.

Ce que reçoit un nœud se range dans les champs que son app DÉCLARE déjà, sans déclaration neuve :
  • `source_type` de la spec de détail (`detail_registry`) — le champ qui porte la nature de la
    source (converter, anonymizer, enhancer : `media_type` ; describer : `detected_type`) ;
  • `source_text` — le champ qui porte le texte de la source (synthesizer, avatarizer :
    `text_content` ; composer, imager : `prompt`) ;
  • pour une ÉTAPE de card (nœud fonction rattaché à un process), l'élément désigné porte ses
    valeurs lui-même : les porteurs cachés du schéma sont lus sur lui.

« Inconnu n'est pas vide » (`launch.diagnostiquer_chainage`) : une nature qui n'est pas encore
connue — aucun média choisi, un amont qui peut sortir une image OU une vidéo — se porte en LISTE
(« l'une de ») ; les conditions d'affichage la lisent comme telle (`param_schema._show_if_met`,
`wama-params.js::met`) : le nœud montre les réglages de CHAQUE nature possible, et chaque élément
appliquera ceux de la sienne, détectée à sa création.
"""
from __future__ import annotations


def _node_output_types(node) -> list:
    """Ce qu'un nœud PEUT sortir, d'après ses ports déclarés (sans ses réglages)."""
    from wama.common.manifests.builtin.pipeline import builtin_node, function_key, node_kind
    kind = node_kind(node)
    if kind == 'function':
        from wama.common.catalog import function_catalog as fc
        if fc.get(function_key(node)) is None:
            return []
        out = fc.function_node_ports(function_key(node)).get('output') or {}
        return list(out.get('types') or [])
    if kind in ('source', 'sink'):
        out = builtin_node(node.get('app')).ports().get('output') or {}
        return list(out.get('types') or [])
    from wama.common.app_registry import studio_node_ports
    out = (studio_node_ports(node.get('app') or '') or {}).get('output') or {}
    return list(out.get('types') or [])


def node_flows(graph) -> dict:
    """`{id: {'types': [...], 'fields': set | None, 'text': str | None}}` — ce que FOURNIT chaque
    nœud, dans l'ordre d'exécution. `types` : ce que la sortie PEUT être (un seul = connu) ;
    `fields` : les champs d'une donnée typée (fonctions pures seulement, `None` = inconnu) ;
    `text` : le texte d'une saisie, s'il est connu avant le lancement."""
    from wama.common.catalog import function_catalog as fc
    from wama.common.catalog.function_catalog import champs_apres
    from wama.common.manifests.builtin.pipeline import builtin_node, function_key, node_kind
    from wama.studio.tasks import topo_order

    graph = graph or {}
    links = graph.get('links', []) or []
    fc.load_all()
    flows: dict = {}
    for node in topo_order(graph):
        nid = node.get('id')
        kind = node_kind(node)
        flow = {'types': _node_output_types(node), 'fields': None, 'text': None}
        if kind == 'source':
            b = builtin_node(node.get('app'))
            emitted = b.emits(node.get('params') or {}) if b and b.emits else None
            if emitted:
                flow['types'] = list(emitted.get('types') or flow['types'])
                flow['text'] = emitted.get('text')
                # Une card ENTIÈRE dit ce qu'elle remplit, port par port (2026-10-20).
                if emitted.get('ports') is not None:
                    flow['ports'] = dict(emitted['ports'])
        elif kind == 'function':
            # Les CHAMPS — la règle de `launch.diagnostiquer_chainage`, déplacée telle quelle :
            # accumulés si l'amont est connu, inconnus sinon ; seule une fonction PURE rend une
            # donnée typée (l'exécuteur range la sortie d'un app-bound en TEXTE).
            spec = fc.get(function_key(node))
            if spec is not None and spec.binding == fc.Binding.PURE and spec.outputs:
                entrants = [l for l in links if l.get('to') == nid]
                before = set()
                for l in entrants:
                    upstream = (flows.get(l.get('from')) or {}).get('fields')
                    if upstream is None:
                        before = None
                        break
                    before |= upstream
                flow['fields'] = None if (entrants and before is None) else champs_apres(
                    spec.outputs[0], spec.key, before or set())
        flows[nid] = flow
    return flows


def _detail_spec(app_id) -> dict:
    from wama.common.utils.detail_registry import DetailRegistry
    return (DetailRegistry.get(app_id) or {}).get('spec') or {}


def _accepted_natures(app_id) -> list:
    """Les natures que l'entrée principale du nœud de l'app ACCEPTE — ce que peut être une nature
    encore inconnue. LUES dans `input_kinds` du runner (déclarées, ou dérivées des ports par
    `generic_runner._fill_io_from_ports`, rétrécissement `io_scope` compris) — ramené à la
    revérification : un premier jet les recalculait depuis les ports, plus larges qu'un
    rétrécissement déclaré."""
    from wama.common.app_registry import MEDIA_CATEGORIES
    from wama.studio.services.generic_runner import GENERIC_APPS
    kinds = (GENERIC_APPS.get(app_id) or {}).get('input_kinds') or ()
    return [t for t in kinds if t in MEDIA_CATEGORIES]


def _put_nature(values, field, possible):
    """Une nature connue : sa valeur ; possible parmi plusieurs : la liste (« l'une de »)."""
    if len(possible) == 1:
        values[field] = possible[0]
    elif possible:
        values[field] = list(possible)


def _app_carriers(app_id, inputs, values, provided):
    """Les champs DÉCLARÉS de l'app (`source_type`, `source_text`) remplis par ce que reçoit son
    nœud. La nature : celle de l'entrée principale, bornée à ce que le port accepte — connue, une
    valeur ; possible parmi plusieurs (aucun lien, aucun média choisi, amont ambigu), la liste."""
    from wama.studio.services.generic_runner import GENERIC_APPS, primary_ports
    spec = _detail_spec(app_id)
    source_type, source_text = spec.get('source_type'), spec.get('source_text')

    if isinstance(source_type, str) and app_id in GENERIC_APPS:
        primary = primary_ports(app_id)
        linked = [(port, i) for port, i in inputs.items() if port in primary]
        possible = _accepted_natures(app_id)
        if linked:
            port, received = linked[0]
            possible = [t for t in possible if t in (received['types'] or possible)]
            provided[source_type] = {'node': received['from']}
        _put_nature(values, source_type, possible)

    if isinstance(source_text, str) and 'prompt' in inputs:
        received = inputs['prompt']
        # Connu (une saisie) : le texte. Produit à l'exécution par l'amont : le champ est quand
        # même FOURNI — sa valeur ne se saisit pas au nœud, le lien prime (`generic_runner.create`).
        values[source_text] = received['text'] or ''
        provided[source_text] = {'node': received['from'], 'at_run': not received['text']}


def _step_carriers(node, user, values, provided, defaults):
    """Une ÉTAPE de card : l'élément désigné porte ses valeurs. Sa ⚙ (`node_params.step_schema`,
    la règle de la card) se lit sur lui : un porteur CACHÉ (`media_type`) est FOURNI (`values`, il
    prime) ; un réglage montré — l'interrupteur de l'étape compris — en reçoit la valeur ACTUELLE
    (`defaults`, sous les réglages décidés au nœud, qui priment), comme la ⚙ de la card."""
    from wama.common.catalog import function_catalog as fc
    from wama.common.manifests.builtin.pipeline import function_key
    from wama.common.services.process_pipeline import process_of_function
    from wama.common.utils.detail_registry import DetailRegistry
    from wama.studio.services.node_params import step_schema
    spec = fc.get(function_key(node))
    if spec is None or spec.binding != fc.Binding.APP or not spec.impl:
        return
    pipeline, process = process_of_function(spec.key)
    if process is None:
        return
    schema = step_schema(pipeline, process)
    carriers = [p['name'] for p in schema if p.get('type') == 'hidden']
    model = (DetailRegistry.get(pipeline.app) or {}).get('model')
    if not schema or model is None:
        return
    from wama.studio.tasks import app_function_job_kwargs
    try:
        kwargs = app_function_job_kwargs(spec.impl)
    except ValueError:
        return
    params = node.get('params') or {}
    raw = next((params.get(k) for k in kwargs if params.get(k) not in (None, '')), None)
    try:
        item = model.objects.filter(pk=int(raw), user=user).first() if raw is not None else None
    except (TypeError, ValueError):
        item = None
    if item is None:
        # Aucun élément désigné (ou pas le sien) : sa nature est INCONNUE, pas vide — celles que
        # l'app accepte, comme pour le nœud de l'app (« inconnu n'est pas vide »).
        source_type = _detail_spec(pipeline.app).get('source_type')
        if source_type in carriers:
            _put_nature(values, source_type, _accepted_natures(pipeline.app))
        return
    for p in schema:
        value = getattr(item, p['name'], None)
        if value in (None, ''):
            continue
        if p['name'] in carriers:
            values[p['name']] = value
            provided[p['name']] = {'element': item.pk}
        else:
            defaults[p['name']] = value


def node_context(graph, node_id, user=None) -> dict:
    """Ce que REÇOIT le nœud `node_id` du graphe : `{'inputs': {port: {'from', 'types', 'text'}},
    'values': {champ: valeur | [valeurs possibles]}, 'provided': {champ: {'node'|'element', …}},
    'defaults': {champ: valeur actuelle de l'élément d'une étape}}`. Au rendu de l'inspecteur :
    `defaults` SOUS les réglages décidés au nœud, `values` (fourni) AU-DESSUS ; rien ne
    s'enregistre — l'élément déduira les siennes à sa création, comme sur une card."""
    from wama.common.manifests.builtin.pipeline import node_kind
    graph = graph or {}
    node = next((n for n in graph.get('nodes', []) or [] if n.get('id') == node_id), None)
    if node is None:
        return {'inputs': {}, 'values': {}, 'provided': {}, 'defaults': {}}
    flows = node_flows(graph)
    inputs = {}
    for l in graph.get('links', []) or []:
        if l.get('to') != node_id:
            continue
        flow = flows.get(l.get('from')) or {}
        if flow.get('ports') is not None:
            # Une card ENTIÈRE (port « Entrée de card ») : chacun des ports qu'elle remplit est
            # reçu comme s'il était relié — ce que le nœud montre « fourni » (2026-10-20).
            for port, carried in flow['ports'].items():
                inputs[port] = {'from': l.get('from'), 'types': carried.get('types') or [],
                                'text': carried.get('text')}
            continue
        inputs[l.get('to_port') or ''] = {'from': l.get('from'), 'types': flow.get('types') or [],
                                          'text': flow.get('text')}
    values, provided, defaults = {}, {}, {}
    kind = node_kind(node)
    if kind == 'app':
        _app_carriers(node.get('app') or '', inputs, values, provided)
    elif kind == 'function':
        _step_carriers(node, user, values, provided, defaults)
    return {'inputs': inputs, 'values': values, 'provided': provided, 'defaults': defaults}
