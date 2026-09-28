"""
Actions PROGRAMMÉES — le QUAND du calendrier, étape 3 (2026-09-28).
Doc : `WAMA_APP_GENERATION_ROUTE.md §10.6` point 13 ; la vue : `WAMA_MEMORY.md §9bis.1`.

TROIS GESTES, UNE PORTE. On programme le lancement d'une card (menu « Programmer… »), on le
déplace ou on l'annule ; l'heure venue, le distributeur (UNE entrée beat, toutes les minutes)
appelle l'outil `start_<app>` par `tool_api.execute_tool`, au nom de l'utilisateur — la même porte
que l'assistant. Aucune app n'a une ligne à écrire : l'outil est dérivé de la triade, son argument
d'identifiant de sa signature (`primary_arg_name`).

LE PLACEMENT (« auto + curseur + manuel ») :
- `manual` — à la date demandée ; si elle tombe dans une PLAGE RÉSERVÉE (tests nocturnes,
  décision de Fabien), rien n'est créé : on rend la plage et la fin de plage proposée ;
- `asap` — maintenant, repoussé à la fin de toute plage réservée ;
- `off_peak` — la prochaine tranche d'heures creuses (`OFF_PEAK_HOURS`, déclarée — l'étape 4 la
  MESURERA sur l'activité), hors plages réservées.

⚠ LE ▶ LANCE MAINTENANT ET ANNULE LA PROGRAMMATION, sans confirmation (décision de Fabien). Deux
filets : le middleware des gestes annule à chaque `start`/`restart` réussi, et le distributeur
ne relance JAMAIS un élément déjà lancé depuis la programmation (état `skipped`) — ce second
filet couvre les routes que le middleware ne reconnaît pas (lots, file audio de l'enhancer).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

#: Heures creuses DÉCLARÉES : de 22 h à 7 h (heure locale). Mesuré le 2026-09-28 : aucune activité
#: utilisateur entre 05:00 et 08:00, activité jusqu'à 01:00 — l'étape 4 dérivera la tranche de
#: l'histogramme de `RunOutcome` au lieu de la déclarer.
OFF_PEAK_HOURS = (22, 7)

#: Horizon de recherche d'un créneau : au-delà, une plage réservée mal déclarée bouclerait.
_SEARCH_DAYS = 8


class ScheduleError(ValueError):
    """Une programmation refusée — le message est montré à l'utilisateur."""


# ── Le SCHÉMA de la programmation — une déclaration, trois surfaces ─────────────────────────
#
# Demande de Fabien (2026-09-28) : *« on le fait bien schéma-driven »*, et *« les fichiers batch
# devraient pouvoir paramétrer la programmation »*. Les deux champs sont donc déclarés ICI, une
# fois, comme n'importe quels réglages (`param_schema.Param`) ; et leurs NOMS sont le vocabulaire
# des trois surfaces qui les lisent :
#   • la fenêtre « Programmer… » — rendue par `WamaParams.render`, lue par `WamaParams.read` ;
#   • l'API (`schedule_create`, `schedule_update`) et donc l'assistant ;
#   • le fichier BATCH : `--when off_peak`, `--at "2026-10-01 22:00"`, ou les colonnes `when` /
#     `at` d'un CSV à en-têtes — des OPTIONS de ligne, comme `--voice` (`BATCH_FORMAT.md`).

FIELD_WHEN = 'when'
FIELD_AT = 'at'


def schedule_params():
    """Le schéma de programmation (liste de `Param`)."""
    from ..models import ScheduledAction as SA
    from ..utils.param_schema import Param

    return [
        Param(name=FIELD_WHEN, type='radio', label='Quand', choices=list(SA.PLACEMENT_CHOICES),
              default=SA.PLACEMENT_MANUAL, contexts=('item',),
              help=('« Dès que possible » et « en heures creuses » évitent d’eux-mêmes les plages '
                    'réservées aux tests nocturnes ; heures creuses : de %d h à %d h.'
                    % OFF_PEAK_HOURS)),
        Param(name=FIELD_AT, type='datetime', label='Date et heure', contexts=('item',),
              show_if={'field': FIELD_WHEN, 'in': [SA.PLACEMENT_MANUAL]}),
    ]


def parse_moment(value):
    """Instant demandé → aware, ou None. Formes acceptées : ISO 8601 (avec ou sans fuseau), la
    valeur d'un `datetime-local`, et `AAAA-MM-JJ HH:MM` d'un fichier batch — sans fuseau, c'est
    l'heure de l'instance."""
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or '').strip()
        moment = parse_datetime(text.replace(' ', 'T', 1)) if text else None
        if text and moment is None:
            raise ScheduleError(f'Date illisible : « {text} » (attendu AAAA-MM-JJ HH:MM).')
    if moment is not None and timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


def read_schedule(data):
    """`(placement, instant demandé)` depuis des valeurs NOMMÉES PAR LE SCHÉMA (`when`, `at`).

    Les bornes de choix sont celles du schéma (`invalid_choice_values`, la brique d'`execute_tool`) :
    aucune liste de placements n'est réécrite ici. Un `at` seul vaut placement manuel — c'est ce
    qu'écrit naturellement une ligne de fichier batch (`--at 2026-10-01 22:00`).
    """
    from ..models import ScheduledAction as SA
    from ..utils.param_schema import invalid_choice_values

    values = {k: data.get(k) for k in (FIELD_WHEN, FIELD_AT) if data.get(k) not in (None, '')}
    bad = invalid_choice_values(schedule_params(), values)
    if bad:
        refused, valid = bad[FIELD_WHEN]
        raise ScheduleError(f'« {", ".join(map(str, refused))} » n’est pas un placement '
                            f'(valides : {", ".join(valid)}).')
    requested = parse_moment(values.get(FIELD_AT))
    placement = values.get(FIELD_WHEN) or (SA.PLACEMENT_MANUAL if requested else '')
    return placement, requested


# ── Placement ────────────────────────────────────────────────────────────────────────────────

def _reserved(start, end):
    from .calendar import reserved_windows
    return reserved_windows(start, end)


def reserved_window_at(moment):
    """La plage réservée qui CONTIENT `moment`, ou None."""
    for window in _reserved(moment - timedelta(days=1), moment + timedelta(days=1)):
        if window.start <= moment < window.end:
            return window
    return None


def _out_of_reserved(moment):
    """`moment` repoussé à la fin de toute plage réservée qui le contient (en chaîne)."""
    for _ in range(20):
        window = reserved_window_at(moment)
        if window is None:
            return moment
        moment = window.end
    return moment


def _is_off_peak(moment):
    from django.utils import timezone
    hour = timezone.localtime(moment).hour
    begin, end = OFF_PEAK_HOURS
    return hour >= begin or hour < end


def _next_off_peak_start(moment):
    from django.utils import timezone
    local = timezone.localtime(moment)
    start = local.replace(hour=OFF_PEAK_HOURS[0], minute=0, second=0, microsecond=0)
    return start if start > local else start + timedelta(days=1)


def place(placement, requested, now):
    """`(instant, plage en conflit)` d'une programmation.

    Seul le placement MANUEL peut rendre un conflit : l'utilisateur a choisi une heure, on ne la
    change pas dans son dos — on la refuse en lui proposant la fin de la plage.
    """
    from ..models import ScheduledAction as SA

    if placement == SA.PLACEMENT_MANUAL:
        if requested is None:
            raise ScheduleError('Choisissez une date et une heure.')
        if requested < now - timedelta(minutes=1):
            raise ScheduleError('Cette date est déjà passée.')
        return requested, reserved_window_at(requested)
    if placement == SA.PLACEMENT_ASAP:
        return _out_of_reserved(now), None
    if placement == SA.PLACEMENT_OFF_PEAK:
        moment = now if _is_off_peak(now) else _next_off_peak_start(now)
        for _ in range(_SEARCH_DAYS):
            moment = _out_of_reserved(moment)
            if _is_off_peak(moment):
                return moment, None
            moment = _next_off_peak_start(moment)
        raise ScheduleError('Aucun créneau en heures creuses hors des plages réservées.')
    raise ScheduleError(f'Placement inconnu : {placement}')


# ── Cible : l'outil de lancement d'une card ─────────────────────────────────────────────────

def start_tool_for(app, prefix=''):
    """Outil `start_*` d'une FILE, ou None. La file d'un domaine a le sien
    (`start_audio_enhancer`), sinon celui de l'app (`start_imager` pour ses deux files, un seul
    modèle) ; une jumelle de bac à sable n'en a pas. Lu par la file (`queue_dnd_attrs`) ET par le
    fichier batch (`schedule_from_batch`) — une seule dérivation."""
    try:
        from wama import tool_api
    except Exception:
        return None
    for name in ((f'start_{prefix}_{app}',) if prefix else ()) + (f'start_{app}',):
        if name in tool_api.TOOL_REGISTRY and tool_api.tool_role(name) == 'start':
            return name
    return None


def target_of(tool):
    """`(clé d'app, modèle, argument d'identifiant)` d'un outil `start_<app>`.

    La clé est celle de `detail_registry` (`start_audio_enhancer` → `audio_enhancer`), le modèle
    celui qu'il y déclare, l'argument est lu dans la signature de l'outil — rien n'est écrit par app.
    """
    from wama import tool_api

    from ..utils.detail_registry import DetailRegistry

    if tool not in tool_api.TOOL_REGISTRY or tool_api.tool_role(tool) != 'start':
        raise ScheduleError(f'« {tool} » n’est pas un outil de lancement.')
    key = tool[len('start_'):]
    entry = DetailRegistry.get(key)
    if not entry or entry.get('model') is None:
        raise ScheduleError(f'« {key} » n’a pas de file programmable.')
    arg = tool_api.primary_arg_name(tool)
    if not arg:
        raise ScheduleError(f'« {tool} » ne désigne pas d’élément.')
    return key, entry['model'], arg


def schedule_items(user, tool, ids, placement, requested=None, *, now=None):
    """Programme le lancement des éléments `ids` par `tool`. Rend `{actions, conflict}`.

    Un élément n'a qu'UNE programmation active : en reprogrammer un remplace la précédente.
    """
    from django.db import transaction
    from django.utils import timezone

    from wama.accounts.permissions import tool_accessible

    from ..models import ScheduledAction as SA

    now = now or timezone.now()
    if not tool_accessible(user, tool):
        raise ScheduleError('Accès non autorisé à cette application.')
    key, model, _arg = target_of(tool)
    run_at, conflict = place(placement, requested, now)
    if conflict is not None:
        return {'actions': [], 'conflict': conflict}

    wanted = [str(i) for i in ids if str(i).strip()]
    items = {str(o.pk): o for o in model.objects.filter(user=user, pk__in=wanted)}
    if not items:
        raise ScheduleError('Aucun élément à programmer.')
    created = []
    with transaction.atomic():
        SA.objects.filter(user=user, app=key, object_id__in=list(items),
                          state=SA.STATE_SCHEDULED).update(state=SA.STATE_CANCELLED)
        for pk, obj in items.items():
            created.append(SA.objects.create(
                user=user, tool=tool, app=key, object_type=model.__name__, object_id=pk,
                title=str(obj)[:255], placement=placement, run_at=run_at))
    return {'actions': created, 'conflict': None}


def reschedule(user, action_id, placement, requested=None, *, now=None):
    """Déplace une programmation. Même règle de placement ; un conflit ne change rien."""
    from django.utils import timezone

    from ..models import ScheduledAction as SA

    action = SA.objects.filter(pk=action_id, user=user, state=SA.STATE_SCHEDULED).first()
    if action is None:
        raise ScheduleError('Cette programmation n’existe plus.')
    run_at, conflict = place(placement, requested, now or timezone.now())
    if conflict is not None:
        return {'action': action, 'conflict': conflict}
    action.placement, action.run_at = placement, run_at
    action.save(update_fields=['placement', 'run_at', 'updated_at'])
    return {'action': action, 'conflict': None}


def schedule_from_batch(user, app, route_name, batch_id, *, now=None) -> dict | None:
    """Programme les lignes d'un FICHIER BATCH qui portent `when` / `at` (`BATCH_FORMAT.md`).

    Appelé par le middleware des gestes après un `batch_create` réussi — aucune app n'a de ligne
    à écrire : le fichier est archivé sur le lot (`batch_file`), les éléments sont relus DANS
    L'ORDRE DES LIGNES (`batch_common.batch_elements`), et chaque ligne est lue par le MÊME
    schéma que la fenêtre (`read_schedule`).

    ⚠ L'ALIGNEMENT LIGNE ↔ ÉLÉMENT n'est sûr que si l'app a créé un élément par ligne. Si elle en
    a écarté (ligne invalide), rien n'est programmé et l'utilisateur est prévenu : programmer le
    mauvais élément serait pire que ne rien programmer.

    Rend `{scheduled, refused, reason}`, ou None si le lot ne porte aucune programmation.
    """
    from django.apps import apps as django_apps
    from django.utils import timezone

    from ..models import BatchMixin
    from ..utils.batch_common import batch_elements
    from ..utils.batch_parsers import parse_unified_batch
    from ..utils.notifications import notify_in_app

    now = now or timezone.now()
    # Préfixe de DOMAINE lu sur le nom de route (`audio_batch_create` → `audio`) ; une route qui
    # n'en porte pas (`batch_create`, `batch_import`, `import_batch`) retombe sur l'outil de l'app.
    prefix = (route_name or '').split('batch')[0].rstrip('_')
    tool = start_tool_for(app, prefix)
    if not tool:
        return None
    _key, element_model, _arg = target_of(tool)

    batch, elements = None, []
    for model in django_apps.get_models():
        if not issubclass(model, BatchMixin) or model._meta.app_label != app:
            continue
        candidate = model.objects.filter(pk=batch_id, user=user).first()
        found = batch_elements(candidate, element_model) if candidate else []
        if found:
            batch, elements = candidate, found
            break
    batch_file = getattr(batch, 'batch_file', None)
    if batch is None or not batch_file:
        return None
    try:
        rows, _warnings = parse_unified_batch(batch_file.path)
    except Exception:
        logger.debug('[schedule] fichier batch illisible', exc_info=True)
        return None
    wanted = [(i, r.get('options') or {}) for i, r in enumerate(rows)
              if (r.get('options') or {}).get(FIELD_WHEN) or (r.get('options') or {}).get(FIELD_AT)]
    if not wanted:
        return None

    summary = {'scheduled': 0, 'refused': [], 'reason': ''}
    if len(rows) != len(elements):
        summary['reason'] = (f'le lot compte {len(elements)} élément(s) pour {len(rows)} ligne(s) : '
                             'la correspondance ligne à ligne n’est pas sûre, rien n’a été programmé')
    else:
        for index, options in wanted:
            element = elements[index]
            try:
                placement, requested = read_schedule(options)
                result = schedule_items(user, tool, [element.pk], placement, requested, now=now)
            except ScheduleError as e:
                summary['refused'].append(f'ligne {index + 1} : {e}')
                continue
            if result['conflict'] is not None:
                summary['refused'].append(
                    f'ligne {index + 1} : « {result["conflict"].title} » réserve ce créneau')
            else:
                summary['scheduled'] += 1
    if summary['refused'] or summary['reason']:
        notify_in_app([user], 'schedule_batch',
                      f'Programmation du lot #{batch.pk} : {summary["scheduled"]} élément(s) programmé(s)',
                      body='\n'.join(([summary['reason']] if summary['reason'] else [])
                                     + summary['refused'])[:1000],
                      url=_queue_url(app))
    return summary


def cancel(user, action_id) -> bool:
    from ..models import ScheduledAction as SA
    return bool(SA.objects.filter(pk=action_id, user=user, state=SA.STATE_SCHEDULED)
                .update(state=SA.STATE_CANCELLED))


def cancel_for_item(app, object_id) -> int:
    """Le ▶ a lancé l'élément : sa programmation n'a plus d'objet (décision de Fabien : sans
    confirmation). Appelé par le middleware des gestes."""
    from ..models import ScheduledAction as SA
    return SA.objects.filter(app=app, object_id=str(object_id),
                             state=SA.STATE_SCHEDULED).update(state=SA.STATE_CANCELLED)


def active_for(user):
    from ..models import ScheduledAction as SA
    return SA.objects.filter(user=user, state=SA.STATE_SCHEDULED).order_by('run_at')


# ── Distributeur ─────────────────────────────────────────────────────────────────────────────

def _launched_meanwhile(action) -> bool:
    """L'élément a-t-il été lancé depuis la programmation (▶, « Démarrer tout », un lot) ?"""
    from ..models import JOB_RUNNING, RunOutcome, normalize_job_status
    from ..utils.detail_registry import DetailRegistry

    if not action.app:
        return False
    if RunOutcome.objects.filter(app=action.app, object_type=action.object_type,
                                 object_id=action.object_id, signal__in=('produit', 'echec'),
                                 occurred_at__gt=action.updated_at).exists():
        return True
    entry = DetailRegistry.get(action.app) or {}
    model = entry.get('model')
    obj = model.objects.filter(pk=action.object_id).first() if model else None
    return bool(obj) and normalize_job_status(getattr(obj, 'status', '')) == JOB_RUNNING


def _next_occurrence(action, after):
    if not action.rrule:
        return None
    from dateutil.rrule import rrulestr
    try:
        return rrulestr(action.rrule, dtstart=action.run_at).after(after)
    except (ValueError, TypeError):
        logger.warning('[schedule] récurrence illisible : %s', action.rrule)
        return None


def dispatch_due(now=None) -> dict:
    """Lance ce qui est dû. Rend `{dispatched, skipped, failed}`.

    Les lignes dues sont VERROUILLÉES et passées à `dispatched` avant tout appel : deux
    distributeurs concurrents (beat relancé, worker doublé) ne lancent jamais deux fois.
    """
    from django.db import transaction
    from django.utils import timezone

    from wama import tool_api

    from ..models import ScheduledAction as SA
    from ..utils.notifications import notify_in_app

    now = now or timezone.now()
    with transaction.atomic():
        due = list(SA.objects.select_for_update(skip_locked=True)
                   .filter(state=SA.STATE_SCHEDULED, run_at__lte=now).select_related('user'))
        SA.objects.filter(pk__in=[a.pk for a in due]).update(
            state=SA.STATE_DISPATCHED, dispatched_at=now)

    summary = {'dispatched': 0, 'skipped': 0, 'failed': 0}
    for action in due:
        following = _next_occurrence(action, now)
        if following is not None:
            SA.objects.create(user=action.user, tool=action.tool, args=action.args,
                              app=action.app, object_type=action.object_type,
                              object_id=action.object_id, title=action.title,
                              placement=action.placement, run_at=following, rrule=action.rrule)
        if not action.rrule and _launched_meanwhile(action):
            SA.objects.filter(pk=action.pk).update(state=SA.STATE_SKIPPED)
            summary['skipped'] += 1
            continue
        args = dict(action.args or {})
        if action.object_id:
            try:
                arg = tool_api.primary_arg_name(action.tool)
                args[arg] = int(action.object_id) if action.object_id.isdigit() else action.object_id
            except Exception:
                pass
        result = tool_api.execute_tool(action.tool, args, action.user)
        failed = isinstance(result, dict) and bool(result.get('error'))
        SA.objects.filter(pk=action.pk).update(
            state=SA.STATE_FAILED if failed else SA.STATE_DISPATCHED,
            last_result=_jsonable(result))
        if failed:
            summary['failed'] += 1
            notify_in_app([action.user], 'schedule_failed',
                          f'Lancement programmé impossible : {action.title or action.tool}',
                          body=str(result.get('detail') or result.get('error'))[:500],
                          url=_queue_url(action.app))
        else:
            summary['dispatched'] += 1
    return summary


def _jsonable(result):
    import json
    try:
        json.dumps(result)
        return result
    except (TypeError, ValueError):
        return {'repr': repr(result)[:1000]}


def _queue_url(app):
    from .journal import app_queue_url
    return app_queue_url(app) if app else ''
