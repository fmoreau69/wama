"""
Le nœud `pipeline` côté Studio : ce qu'un compte peut RÉFÉRENCER, et ce que la palette en montre
(2026-11-02, ROUTE §10.6 3.1 — accord Briques UI ↔ Monde Data).

Un nœud `pipeline` (`app = 'pipeline:<clé>'`) référence un pipeline ENREGISTRÉ sans le recopier ;
il est déployé au lancement par `manifests.builtin.pipeline.expand_pipeline_nodes`, à qui ce module
fournit le RÉSOLVEUR d'un compte. Périmètre de la 1ʳᵉ marche :
  • seuls les `StudioPipeline` enregistrés se posent — le pipeline déclaré d'une app, c'est le nœud
    APP qui le pose déjà (une card créée, son pipeline joué) ; les étages du Lab restent hors du
    Studio tant que ses apps ne sont pas alignées (décision n°8 de ROUTE §10.6 6.1) ;
  • la référence se lit par `extract_pipeline` (le kind `pipeline`, aucun registre neuf) et se
    VOIT par la règle de la liste des pipelines (`listable_by`, celle d'`api_pipelines`) — revérifiée
    au lancement, pas seulement dans la palette.
"""


def resolver(user):
    """`resolve(clé) -> (nom, graphe canvas)` pour `user` — lève `ValueError` en nommant la clé
    pour une référence qui n'est pas un pipeline enregistré, supprimé ou non visible du compte."""
    from wama.common.manifests.builtin.pipeline import body_to_graph, extract_pipeline
    from wama.common.utils.scoping import listable_by
    from wama.studio.models import StudioPipeline

    def resolve(key):
        if not str(key).isdigit():
            raise ValueError(f"« {key} » n'est pas un pipeline enregistré du Studio — seul un "
                             f"pipeline enregistré se pose comme nœud.")
        row = listable_by(StudioPipeline.objects.filter(pk=int(key)), user).first()
        manifest = extract_pipeline(str(key)) if row is not None else None
        if manifest is None:
            raise ValueError(f"pipeline {key} introuvable ou non visible pour ce compte.")
        return row.name, body_to_graph(manifest.get('body') or {})
    return resolve


def pipeline_palette_nodes(user, offered: dict) -> dict:
    """`{'pipeline:<pk>': description}` des pipelines enregistrés que `user` voit — sous la forme
    des autres nœuds de la palette. Ses PORTS se dérivent du sous-graphe DÉPLOYÉ, lus sur
    `offered` (la palette déjà construite) : une entrée par source interne, la sortie du nœud
    unique qui alimente ses sorties internes (aucune sinon). Un pipeline dont un nœud interne
    n'est pas offert au compte — ou qui ne se déploie pas — n'est pas offert non plus : la
    palette reste ce que le compte peut lancer.

    Le canvas ne leur ouvre pas de section : le pipeline enregistré de la section « Pipelines »
    du catalogue se GLISSE pour être posé (son clic l'ouvre toujours, ROUTE §10.6 5.4)."""
    from wama.common.manifests.builtin.pipeline import (PIPELINE_NODE_PREFIX,
                                                        expand_pipeline_nodes, node_kind)
    from wama.common.utils.scoping import listable_by
    from wama.studio.models import StudioPipeline
    resolve = resolver(user)
    nodes = {}
    for row in listable_by(StudioPipeline.objects.all(), user).order_by('name'):
        key = str(row.pk)
        try:
            graph = expand_pipeline_nodes(resolve(key)[1], resolve, (key,))
        except ValueError:
            continue
        inner = graph['nodes']
        if not inner or any(n.get('app') not in offered for n in inner):
            continue
        sinks = {n['id'] for n in inner if node_kind(n) == 'sink'}
        feeders = list(dict.fromkeys(l['from'] for l in graph['links'] if l['to'] in sinks))
        by_id = {n['id']: n for n in inner}
        output = (offered[by_id[feeders[0]]['app']].get('output') or False
                  if len(feeders) == 1 and feeders[0] in by_id else False)
        nodes[f'{PIPELINE_NODE_PREFIX}{key}'] = {
            'label': row.name,
            'icon': 'fas fa-diagram-project',
            'color': '#b9d7a8',
            'description': f"Pipeline enregistré — {len(inner)} nœud(s), référencé sans être "
                           f"recopié.",
            'inputs': [{'id': n['id'], 'label': offered[n['app']].get('label', n['id']),
                        'group': 'travail',
                        'types': list((offered[n['app']].get('output') or {}).get('types') or []),
                        'multi': False}
                       for n in inner if node_kind(n) == 'source'],
            'output': output,
            'kind': 'pipeline',
            'pipeline': key,
        }
    return nodes


def folded_states(graph: dict, node_states: dict, run_status: str) -> dict:
    """`{id du nœud pipeline: {'status', 'nodes_done', 'nodes_total'}}` — l'état que le canvas
    montre d'un nœud REPLIÉ, déduit de ses nœuds internes (ids `<nœud>/…` du graphe DÉPLOYÉ que
    le run a figé).

    UNE règle, celle des cards : `process_runs.aggregate` (ROUTE §10.6 4.4), lue par l'adaptateur
    de `AppPipeline.shown_state` — le RUN est la vérité de ce qui est EN VOL. Deux lectures que la
    règle exige (relecture de Monde Data, 2026-11-02) :
      • les membres viennent du GRAPHE, pas de `node_states` : un nœud interne pas encore lancé
        n'y a pas d'entrée, et compte `PENDING` — sinon le nœud passerait SUCCESS après son
        premier membre réussi ;
      • run en vol, groupe commencé et non terminé → `RUNNING` (`AWAITING_RESOURCES` si un membre
        l'est) : l'intervalle entre deux membres n'est pas un retour à « en attente »."""
    from wama.common.manifests.builtin.pipeline import EXPANDED_ID_SEP
    from wama.common.models import (JOB_AWAITING_RESOURCES, JOB_FAILURE, JOB_PENDING,
                                    JOB_RUNNING, JOB_SUCCESS)
    from wama.common.services.process_runs import REQUIRED, aggregate
    groups = {}
    for node in (graph or {}).get('nodes') or []:
        nid = str(node.get('id') or '')
        if EXPANDED_ID_SEP in nid:
            groups.setdefault(nid.split(EXPANDED_ID_SEP, 1)[0], []).append(nid)
    in_flight = run_status in (JOB_RUNNING, JOB_AWAITING_RESOURCES)
    out = {}
    for top, members in groups.items():
        states = [((node_states or {}).get(m) or {}).get('status') or JOB_PENDING for m in members]
        status = aggregate((state, REQUIRED) for state in states)
        started = any(state != JOB_PENDING for state in states)
        if in_flight and started and status not in (JOB_SUCCESS, JOB_FAILURE):
            status = (JOB_AWAITING_RESOURCES if JOB_AWAITING_RESOURCES in states
                      else JOB_RUNNING)
        out[top] = {'status': status, 'nodes_total': len(states),
                    'nodes_done': sum(state == JOB_SUCCESS for state in states)}
    return out


def pipeline_exists(key) -> bool:
    """La référence désigne-t-elle un pipeline enregistré, quel que soit le compte ?"""
    from wama.studio.models import StudioPipeline
    return str(key).isdigit() and StudioPipeline.objects.filter(pk=int(key)).exists()
