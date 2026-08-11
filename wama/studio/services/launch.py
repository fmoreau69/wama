"""
Lancement d'un graphe studio — brique PARTAGÉE vue ⟷ tool_api (assistant IA).

Extraite d'`api_run` (2026-08-11) au moment d'exposer le studio à l'assistant :
la validation (acyclicité, nœuds exécutables) et le dispatch doivent être LES MÊMES
quelle que soit la surface d'appel — les dupliquer aurait créé deux contrats divergents.
"""

from __future__ import annotations


def launch_graph(user, graph, *, pipeline_id=None):
    """Valide puis lance un graphe studio. Retourne (run, None) ou (None, message_d_erreur).

    Validation AVANT dispatch (contrat historique d'`api_run`) :
      - graphe non vide et ACYCLIQUE (`topo_order`) ;
      - tout nœud CONNECTÉ doit être exécutable (app du runner générique, source
        Texte/Médiathèque, ou sortie `studio_output`) ;
      - au moins un nœud-app exécutable dans le graphe.
    """
    from wama.studio.models import StudioRun
    from wama.studio.services.runners import runner_for
    from wama.studio.services.generic_runner import GENERIC_APPS
    from wama.studio.tasks import run_pipeline_task, topo_order, SOURCE_HANDLERS

    graph = graph or {}
    nodes = graph.get('nodes', [])
    if not nodes:
        return None, 'Graphe vide'
    try:
        topo_order(graph)
    except ValueError as exc:
        return None, str(exc)
    links = graph.get('links', [])

    def _executable(app):
        return runner_for(app) is not None or app in SOURCE_HANDLERS or app == 'studio_output'

    runnable = ', '.join(sorted(GENERIC_APPS.keys()))
    for n in nodes:
        # Un nœud non exécutable ne peut être CONNECTÉ ni en amont ni en aval : il ne
        # produira aucune sortie et ne peut rien consommer (validation AVANT dispatch).
        if not _executable(n['app']) and any(
                l['to'] == n['id'] or l['from'] == n['id'] for l in links):
            return None, (f"Nœud « {n['app']} » : non exécutable dans un pipeline "
                          f"(apps : {runnable} + nœuds Texte/Médiathèque/Sortie).")
    if not any(runner_for(n['app']) for n in nodes):
        return None, f'Aucun nœud-app exécutable dans le graphe (apps : {runnable}).'

    run = StudioRun.objects.create(user=user, graph=graph, pipeline_id=pipeline_id)
    task = run_pipeline_task.delay(run.pk)
    run.task_id = task.id
    run.save(update_fields=['task_id'])
    return run, None
