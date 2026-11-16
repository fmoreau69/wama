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

Le geste lui-même est `start_one_process` : la vue le traduit en HTTP, l'outil `start_<app>` de
l'assistant (`tool_api._triad_fns`, argument `process`) en réponse d'outil — un seul ▶ d'étape,
deux portes (2026-10-14, décision de Fabien).

Usage (views.py de l'app) :
    from wama.common.utils.process_views import make_process_start_view
    start_process = make_process_start_view(
        work_model=Transcript, task_for=_task_for, reset_on_start=_reset_and_clear_progress)
"""
import sys

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from wama.common.utils.progress_views import request_user

#: Remise à zéro PAR PROCESS inscrite par la fabrique de l'APP, par modèle d'élément (2026-10-29) :
#: l'outil `start_<app>` de l'assistant la lit au lieu de la renommer par son chemin.
_PROCESS_RESETS: dict = {}


def process_reset_for(work_model):
    """La remise à zéro par process que l'app de `work_model` déclare à sa fabrique, ou None.
    Ses vues se chargent ici quand le processus ne l'a pas encore fait (`item_views.declaration_for`)."""
    if work_model not in _PROCESS_RESETS:
        from wama.common.utils.item_views import declaration_for
        declaration_for(work_model)
    return _PROCESS_RESETS.get(work_model)


def start_one_process(work_model, pk, process, *, user, task_for,
                      reset_on_start=None, reset_for_process=None):
    """Le ▶ d'UNE étape d'un élément : `(élément, tâche, None)`, ou `(None, None, (statut HTTP,
    message))` quand il est refusé. Arguments : ceux de `make_process_start_view`.

    Refusé : étape inconnue — le message nomme celles du pipeline, c'est ce qui les apprend à
    l'assistant (400) ; étape qui n'a pas lieu pour cette card (400) ; élément déjà en cours
    (409). Un élément introuvable ou non modifiable par `user` LÈVE `Http404`
    (`editable_or_404`), comme la vue l'a toujours fait ; l'outil le traduit."""
    from wama.common.services.process_pipeline import pipeline_of
    from wama.common.utils.process_control import begin_processing
    from wama.common.utils.scoping import editable_or_404

    item = editable_or_404(work_model, user, pk=pk)
    pipeline = pipeline_of(item)
    if pipeline is None or process not in {s.key for s in pipeline.specs}:
        known = ', '.join(f'{s.key} (« {s.label or s.key} »)'
                          for s in (pipeline.ordered() if pipeline else ()))
        return None, None, (400, f"process inconnu : {process}"
                                 + (f" — étapes : {known}" if known else ''))
    key = pipeline.requested_model(item)
    if key is not None and process not in {s.key for s in pipeline.applicable(item, key)}:
        # La raison est celle que la bande donne (`step_state`, 2026-11-07) : une formulation.
        spec = pipeline.spec(process)
        state, reason = pipeline.step_state(spec, item, key)
        why = 'elle est désactivée' if state == 'off' else (reason[:1].lower() + reason[1:]
                                                            if reason else '')
        return None, None, (400, f"« {spec.label} » n'a pas lieu pour cette card"
                                 + (f" : {why}" if why else ''))

    reset = ((lambda element: reset_for_process(element, process))
             if reset_for_process is not None else reset_on_start)
    item, err = begin_processing(work_model, pk, user=user, reset=reset)
    if err == 'not_found':
        return None, None, (404, 'Élément introuvable')
    if err:
        return None, None, (409, 'Traitement déjà en cours')
    task = task_for(item).apply_async(args=(item.pk,), kwargs={'process': process})
    item.task_id = task.id
    item.save(update_fields=['task_id'])
    return item, task, None


def selection_specs(pipeline) -> list:
    """Les process de `pipeline` qui se lancent depuis une SÉLECTION de cards dérivées
    (`ProcessSpec.from_selection`), dans l'ordre du graphe — ce que le menu de card offre."""
    return [s for s in (pipeline.ordered() if pipeline else ()) if s.from_selection]


def start_on_selection(work_model, ids, process, *, user):
    """Le process `process` de la card d'ORIGINE, lancé depuis une SÉLECTION de ses cards DÉRIVÉES
    (2026-11-16, demande de Fabien : sélectionner les pistes séparées à refusionner, clic droit).
    Le process DÉCLARE ce qu'il prend de la sélection (`ProcessSpec.from_selection` :
    `(origine, rôles) -> {réglage: valeur}`) ; ces réglages s'écrivent par l'écrivain DÉCLARÉ de
    l'app (celui de sa ⚙, `write_element_settings`), puis le ▶ de l'étape est celui de la bande
    (`start_one_process`). Rend `(origine, tâche, None)` ou `(None, None, (statut, message))`.

    Refusé : des cards qui ne sont pas toutes dérivées d'une MÊME card ; un process qui ne se
    lance pas depuis une sélection ; une sélection que l'app refuse (`ValueError`, dite) ; la card
    d'origine en cours (409, AVANT d'écrire ses réglages). Une card que `user` ne peut pas
    modifier LÈVE `Http404` (`editable_or_404`), comme le ▶."""
    from wama.common.catalog.function_catalog import resolve_impl
    from wama.common.services.process_pipeline import pipeline_of
    from wama.common.utils.batch_views import write_element_settings
    from wama.common.utils.item_views import declaration_for
    from wama.common.utils.scoping import editable_or_404

    cards = [editable_or_404(work_model, user, pk=pk) for pk in dict.fromkeys(ids or ())]
    if not cards:
        return None, None, (400, "aucune card choisie")
    sources = {getattr(card, 'derived_from_id', None) for card in cards}
    if (None in sources or len(sources) != 1
            or not all(getattr(card, 'derived_role', '') for card in cards)):
        return None, None, (400, "ces cards ne sont pas toutes tirées d'une même card "
                                 "(les pistes séparées d'un même morceau, par exemple)")
    origin = editable_or_404(work_model, user, pk=sources.pop())
    pipeline = pipeline_of(origin)
    spec = next((s for s in selection_specs(pipeline) if s.key == process), None)
    if spec is None:
        offered = ', '.join(f'{s.key} (« {s.label or s.key} »)' for s in selection_specs(pipeline))
        return None, None, (400, f"« {process} » ne se lance pas depuis une sélection"
                                 + (f" — process proposés : {offered}" if offered else ''))
    if getattr(origin, 'status', None) == 'RUNNING':
        return None, None, (409, 'Traitement déjà en cours sur la card d’origine')
    declaration = declaration_for(work_model)
    if declaration is None:
        return None, None, (400, f"{work_model.__name__} : aucun lancement déclaré")
    try:
        chosen = (resolve_impl(spec.from_selection) if isinstance(spec.from_selection, str)
                  else spec.from_selection)
        write_element_settings(origin, chosen(origin, [card.derived_role for card in cards]))
    except (ValueError, LookupError) as error:
        return None, None, (400, str(error))
    return start_one_process(work_model, origin.pk, process, user=user,
                             task_for=declaration.task_of,
                             reset_on_start=declaration.reset_on_start,
                             reset_for_process=process_reset_for(work_model))


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
    caller = sys._getframe(1).f_globals.get('__name__', '')
    owner = work_model._meta.app_config.name
    if (reset_for_process is not None and '.tests' not in caller
            and (caller == owner or caller.startswith(owner + '.'))):
        _PROCESS_RESETS[work_model] = reset_for_process

    @require_POST
    def start_process(request, pk, process):
        item, task, refused = start_one_process(
            work_model, pk, process, user=get_user(request), task_for=task_for,
            reset_on_start=reset_on_start, reset_for_process=reset_for_process)
        if refused:
            status, message = refused
            return JsonResponse({'error': message}, status=status)
        return JsonResponse({'success': True, 'id': item.pk, 'task_id': task.id,
                             'status': 'RUNNING', 'process': process})

    return start_process
