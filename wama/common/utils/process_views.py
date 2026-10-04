"""
WAMA Common — La vue « ▶ d'UN process » d'une card : fabrique commune (`make_process_start_view`).

`WAMA_APP_GENERATION_ROUTE.md §10.6` 5.1 : la bande des process d'une card porte un ▶ par
process, qui poste sur `start/<pk>/<process>/` — un lancement BORNÉ (ce process, précédé des
seuls amonts périmés, jamais son aval : `AppPipeline.steps_to_run(only=)`). La vue était écrite
à la main dans six apps (composer, transcriber, avatarizer, imager, synthesizer, anonymizer),
avec trois formes de refus et quatre formes de réponse ; elle est ici UNE fois, sur le modèle
de `make_batch_views` dont elle reprend les crochets (`task_for`, `reset_on_start`).

Ni le pipeline ni le modèle ne sont des arguments : le pipeline se lit de l'app de l'élément
(`pipeline_of`), et « le modèle que la card demande » de sa déclaration (`requested_model`).

Usage (views.py de l'app) :
    from wama.common.utils.process_views import make_process_start_view
    start_process = make_process_start_view(
        work_model=Transcript, task_for=_task_for, reset_on_start=_reset_and_clear_progress)
"""
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from wama.common.utils.progress_views import request_user

def make_process_start_view(*, work_model, task_for, get_user=request_user,
                            reset_on_start=None, reset_for_process=None):
    """La vue `start_process(request, pk, process)` d'une app à pipeline.

    Args:
        work_model        : le modèle de l'élément de file.
        task_for          : callable(élément) -> tâche Celery (le crochet de `make_batch_views`) ;
                            elle reçoit `(pk,)` et `process=<clé>`.
        get_user          : callable(request) -> utilisateur ; défaut : connecté, sinon anonyme.
        reset_on_start    : dict champ→valeur ou callable(élément) — la remise à zéro du ▶ de
                            la card, appliquée SOUS le verrou (`begin_processing`).
        reset_for_process : callable(élément, process) — à la place de `reset_on_start` quand
                            la remise à zéro dépend du process lancé (composer : seules les
                            sorties DÉCLARÉES de ce process sont remplacées).

    Un process que le modèle demandé ne sert pas est refusé (`AppPipeline.applicable`). Quand
    ce modèle n'est connu qu'AU LANCEMENT (`requested_model` rend `None` : « auto » tiré par la
    tâche), la vue ne tranche pas — la tâche le fera (`steps_to_run` refuse en le disant).
    """

    @require_POST
    def start_process(request, pk, process):
        from wama.common.services.process_pipeline import pipeline_of
        from wama.common.utils.process_control import begin_processing
        from wama.common.utils.scoping import editable_or_404

        user = get_user(request)
        item = editable_or_404(work_model, user, pk=pk)
        pipeline = pipeline_of(item)
        if pipeline is None or process not in {s.key for s in pipeline.specs}:
            return JsonResponse({'error': f"process inconnu : {process}"}, status=400)
        key = pipeline.requested_model(item)
        if key is not None and process not in {s.key for s in pipeline.applicable(item, key)}:
            return JsonResponse({'error': f"« {pipeline.spec(process).label} » n'a pas lieu "
                                          "pour cette card"}, status=400)

        reset = ((lambda element: reset_for_process(element, process))
                 if reset_for_process is not None else reset_on_start)
        item, err = begin_processing(work_model, pk, user=user, reset=reset)
        if err == 'not_found':
            return JsonResponse({'error': 'Élément introuvable'}, status=404)
        if err:
            return JsonResponse({'error': 'Traitement déjà en cours'}, status=409)
        task = task_for(item).apply_async(args=(item.pk,), kwargs={'process': process})
        item.task_id = task.id
        item.save(update_fields=['task_id'])
        return JsonResponse({'success': True, 'id': item.pk, 'task_id': task.id,
                             'status': 'RUNNING', 'process': process})

    return start_process
