"""
Studio — orchestration d'un pipeline (tâche Celery).

Exécution V1 : ordre TOPOLOGIQUE d'un graphe acyclique ; chaque nœud-app est traité par
son runner (studio/services/runners.py) : create → start → poll (le traitement lui-même
tourne dans le Celery de l'app cible — le studio ne fait qu'orchestrer et chaîner les
sorties). Les nœuds-source intégrés (prompt_batch, media_import) ne sont pas exécutables
en V1 : les entrées initiales viennent des params de nœud (ex. « Texte » du synthesizer).
"""
import time

from celery import shared_task

from wama.common.utils.console_utils import push_console_line

POLL_INTERVAL_S = 3
NODE_TIMEOUT_S = 30 * 60


def _console(user_id, message, level='info'):
    try:
        push_console_line(user_id, message, level=level, app='studio')
    except Exception:
        pass


def topo_order(graph):
    """Ordre topologique des nœuds ({id: [ids amont]}) ; lève ValueError si cycle."""
    nodes = {n['id']: n for n in graph.get('nodes', [])}
    incoming = {nid: set() for nid in nodes}
    for l in graph.get('links', []):
        if l['from'] in nodes and l['to'] in nodes:
            incoming[l['to']].add(l['from'])
    order, ready = [], [nid for nid, deps in incoming.items() if not deps]
    pending = {nid: set(deps) for nid, deps in incoming.items() if deps}
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for other, deps in list(pending.items()):
            deps.discard(nid)
            if not deps:
                del pending[other]
                ready.append(other)
    if pending:
        raise ValueError('Le graphe contient un cycle — exécution impossible.')
    return [nodes[nid] for nid in order]


@shared_task(bind=True)
def run_pipeline_task(self, run_id):
    from django.contrib.auth import get_user_model
    from .models import StudioRun
    from .services.runners import runner_for

    run = StudioRun.objects.get(pk=run_id)
    user = run.user
    t0 = time.time()
    run.status = 'RUNNING'
    run.save(update_fields=['status'])
    _console(user.id, f"Studio run #{run.pk} : démarrage")

    states = dict(run.node_states or {})

    def _save_state(node_id, **kw):
        states.setdefault(node_id, {})
        states[node_id].update(kw)
        run.node_states = states
        run.save(update_fields=['node_states'])

    try:
        order = topo_order(run.graph)
        links = run.graph.get('links', [])
        outputs = {}   # node_id -> {'type': 'audio'|..., 'value': chemin MEDIA relatif}

        for node in order:
            nid, app = node['id'], node['app']
            runner = runner_for(app)
            if runner is None:
                # Nœud-source intégré ou app non exécutable : toléré s'il n'a PAS d'amont
                # (V1 : ses aval liront leurs params) — sinon erreur claire.
                if any(l['to'] == nid for l in links):
                    raise ValueError(f"Nœud « {app} » : app non exécutable dans un pipeline (V1).")
                _save_state(nid, status='SUCCESS', note='source non exécutée (V1)')
                continue

            # Entrées = sorties des nœuds amont, indexées par type de port
            inputs = {}
            for l in links:
                if l['to'] == nid and l['from'] in outputs:
                    up = outputs[l['from']]
                    inputs[l.get('to_port') or up['type']] = up['value']
                    inputs[up['type']] = up['value']

            _save_state(nid, status='RUNNING', progress=0)
            _console(user.id, f"Studio run #{run.pk} : nœud {app} — création")
            item_id = runner['create'](user, inputs, node.get('params') or {})
            _save_state(nid, item_id=item_id)
            runner['start'](user, item_id)

            deadline = time.time() + NODE_TIMEOUT_S
            while True:
                time.sleep(POLL_INTERVAL_S)
                st = runner['poll'](user, item_id)
                _save_state(nid, progress=st.get('progress', 0))
                if st['status'] == 'SUCCESS':
                    if not st.get('output'):
                        raise ValueError(f"Nœud {app} : terminé mais aucune sortie.")
                    outputs[nid] = {'type': runner['output_type'], 'value': st['output']}
                    _save_state(nid, status='SUCCESS', progress=100, output=st['output'])
                    _console(user.id, f"Studio run #{run.pk} : nœud {app} ✔ → {st['output']}")
                    break
                if st['status'] == 'FAILURE':
                    raise ValueError(f"Nœud {app} : échec — {st.get('error') or 'sans détail'}")
                if time.time() > deadline:
                    raise ValueError(f"Nœud {app} : délai dépassé ({NODE_TIMEOUT_S // 60} min).")

        run.status = 'SUCCESS'
        run.processing_seconds = time.time() - t0
        run.save(update_fields=['status', 'processing_seconds', 'node_states'])
        _console(user.id, f"Studio run #{run.pk} : pipeline terminé ✔")
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(user, 'Studio', f"pipeline #{run.pk}", True)
        except Exception:
            pass
        return {'run': run.pk, 'status': 'SUCCESS'}

    except Exception as exc:
        run.status = 'FAILURE'
        run.error_message = str(exc)[:2000]
        run.processing_seconds = time.time() - t0
        run.save(update_fields=['status', 'error_message', 'processing_seconds', 'node_states'])
        _console(user.id, f"Studio run #{run.pk} : ÉCHEC — {exc}", level='error')
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(user, 'Studio', f"pipeline #{run.pk}", False, detail=str(exc))
        except Exception:
            pass
        return {'run': run.pk, 'status': 'FAILURE', 'error': str(exc)}
