"""
Où en est une exécution du Studio — sa ligne de suivi, au contrat de `tool_api.job_progress`
(2026-11-06).

Demande de Fabien : après l'installation d'un modèle, le Studio — « encore en construction. À voir
si on peut faire quelque chose d'universel et pérenne ». Rien ici n'est propre à un nœud : la
ligne se lit sur ce que l'exécuteur publie déjà, l'état et la progression de chaque nœud
(`node_states`, ce que lit le canvas) et le résumé d'un run de LOT (`entries.lot_progress`, la règle
d'un lot d'app). Le début se lit aux lignes d'exécution communes (`process_runs.lines`, une par
nœud de traitement, ROUTE §10.6 4.1). Un nœud ou un monde ajouté au Studio y entre sans retouche.

Inscrite comme famille suivie `studio` (`job_families`, par `studio.apps.ready`) : la barre sous la
réponse de l'assistant qui a lancé le pipeline, et la fin racontée dans son fil.
"""
from __future__ import annotations

def _work_kinds() -> tuple:
    """Les nœuds qui TRAITENT : ceux qui écrivent une ligne d'exécution (`ProcessRun`, une app ou
    une fonction) — ce sont eux qui portent la durée d'un run ; une card d'entrée ou de sortie
    passe en un instant."""
    from wama.common.models import ProcessRun
    return ProcessRun.KIND_APP, ProcessRun.KIND_FUNCTION


def run_progress(run) -> int:
    """0-100 : pour un run de lot, la règle de la card mère — éléments RÉUSSIS / total
    (`_batch_card.html`, `queue-actions.js`, `tool_api.batch_progress`) ; sinon la moyenne de ses
    nœuds de traitement (un nœud réussi compte 100, un nœud en cours sa progression publiée)."""
    from wama.common.manifests.builtin.pipeline import node_kind
    from wama.common.models import JOB_SUCCESS

    from .entries import lot_progress
    lot = lot_progress(run)
    if lot is not None:
        summary = lot['lot']
        return round(100 * summary['done'] / summary['total']) if summary['total'] else 0
    nodes = (run.graph or {}).get('nodes', [])
    work = [n for n in nodes if node_kind(n) in _work_kinds()] or nodes
    if not work:
        return 0
    states = run.node_states or {}
    total = 0
    for node in work:
        state = states.get(node['id']) or {}
        if state.get('status') == JOB_SUCCESS:
            total += 100
        else:
            try:
                total += max(0, min(100, int(state.get('progress') or 0)))
            except (TypeError, ValueError):
                pass
    return int(total / len(work))


def run_started_at(run):
    """Le début MESURÉ d'un run : le plus tôt de ses lignes d'exécution (celles de ses éléments
    pour un lot), None tant qu'aucun nœud de traitement n'a démarré."""
    from wama.common.services import process_runs
    runs = list(run.elements.all()) or [run]
    starts = [line.started_at for rows in process_runs.lines_by_item(runs).values()
              for line in rows if line.started_at]
    return min(starts) if starts else None


def job_row(user, pk):
    """La ligne de suivi du run n° `pk` de `user` (le sien seul, comme `get_studio_run_status`),
    ou None."""
    from wama.common.services.job_families import line

    from ..models import StudioRun
    try:
        run = StudioRun.objects.filter(user=user, pk=int(pk)).select_related('pipeline').first()
    except (TypeError, ValueError):
        return None
    if run is None:
        return None
    row = line('studio', run.pk, label=str(run), status=run.status, progress=run_progress(run),
               started_at=run_started_at(run))
    if run.error_message:
        row['error'] = run.error_message
    return row
