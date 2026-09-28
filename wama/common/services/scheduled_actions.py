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

#: Heures creuses DÉCLARÉES — le REPLI seulement, quand l'activité mesurée ne suffit pas
#: (`QUIET_MIN_SAMPLES`). Depuis l'étape 4 (2026-09-28) elles se MESURENT (`quiet_hours`).
OFF_PEAK_HOURS = (22, 7)

#: Heures creuses MESURÉES : une heure est creuse si l'activité des VRAIS utilisateurs (`RunOutcome`
#: des `QUIET_LOOKBACK_DAYS` derniers jours, comptes de test exclus — ils travaillent la nuit par
#: construction) y est au plus `QUIET_SHARE` de l'heure la plus chargée.
QUIET_LOOKBACK_DAYS = 60
QUIET_SHARE = 0.10
QUIET_MIN_SAMPLES = 100

#: Une tâche est LONGUE au-delà de cette durée typique : le placement automatique l'envoie en
#: heures creuses plutôt que de la laisser occuper la carte aux heures chargées.
LONG_TASK_SECONDS = 30 * 60

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

    hours, source = quiet_hours()
    measured = 'mesurées sur l’activité des %d derniers jours' % QUIET_LOOKBACK_DAYS
    return [
        Param(name=FIELD_WHEN, type='radio', label='Quand', choices=list(SA.PLACEMENT_CHOICES),
              default=SA.PLACEMENT_AUTO, contexts=('item',),
              help=('« Automatique » tient compte de la file de WAMA : la tâche part quand la carte '
                    'se libère, et une tâche longue part en heures creuses. Aucun placement '
                    'automatique n’empiète sur les plages réservées aux tests nocturnes. Heures '
                    'creuses : %s (%s).' % (hours_label(hours),
                                            measured if source == 'measured' else 'déclarées'))),
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


def overlapping_window(start, end):
    """La première plage réservée qui CHEVAUCHE `[start, end)`, ou None.

    ⚠ C'est TOUTE la durée de la tâche qui doit rester hors plage, pas son seul départ : une tâche
    d'une heure lancée à 04:00 déborderait sur les tests de 04:15 — exactement ce que la décision
    de Fabien veut éviter (étape 4 ; l'étape 3 ne regardait que l'instant de départ)."""
    for window in _reserved(start - timedelta(days=1), end + timedelta(days=1)):
        if window.start < end and window.end > start:
            return window
    return None


def _fit(moment, seconds):
    """Premier instant ≥ `moment` où une tâche de `seconds` secondes ne touche aucune plage."""
    duration = timedelta(seconds=seconds or 0)
    for _ in range(40):
        window = overlapping_window(moment, moment + max(duration, timedelta(seconds=1)))
        if window is None:
            return moment
        moment = window.end
    return moment


def _out_of_reserved(moment):
    """`moment` repoussé à la fin de toute plage réservée qui le contient (en chaîne)."""
    return _fit(moment, 0)


def quiet_hours(*, refresh=False):
    """`(heures creuses, 'measured' | 'declared')` — heures LOCALES 0-23.

    Mesurées sur `RunOutcome` (comptes de test exclus), mises en cache une heure : l'activité d'un
    labo ne change pas d'une requête à l'autre, et la fenêtre « Programmer… » les affiche.
    """
    from django.core.cache import cache

    key = 'wama:schedule:quiet_hours'
    cached = None if refresh else cache.get(key)
    if cached is not None:
        return frozenset(cached[0]), cached[1]
    result = _measure_quiet_hours()
    cache.set(key, (sorted(result[0]), result[1]), 3600)
    return result


def _declared_quiet_hours():
    begin, end = OFF_PEAK_HOURS
    return frozenset(h for h in range(24) if h >= begin or h < end), 'declared'


def _measure_quiet_hours():
    from django.db.models import Count
    from django.db.models.functions import ExtractHour
    from django.utils import timezone

    from ..models import RunOutcome
    from .nightly_tests import TEST_USERNAMES

    # DEUX signaux d'activité, cumulés : les gestes (`RunOutcome`) et les DÉPÔTS d'éléments (dates
    # de création des sources du journal). Mesuré le 2026-09-28 sur 60 jours : 48 gestes réels et 29
    # dépôts — ni l'un ni l'autre ne suffit seul, et le repli déclaré reste la réponse honnête tant
    # que le cumul n'atteint pas `QUIET_MIN_SAMPLES`.
    from .journal import sources

    try:
        since = timezone.now() - timedelta(days=QUIET_LOOKBACK_DAYS)
        tz = timezone.get_current_timezone()
        rows = (RunOutcome.objects.filter(occurred_at__gte=since, user__isnull=False)
                .exclude(user__username__in=TEST_USERNAMES)
                .annotate(hour=ExtractHour('occurred_at', tzinfo=tz))
                .values('hour').annotate(n=Count('id')))
        counts = {r['hour']: r['n'] for r in rows}
        for src in sources():
            deposits = (src.model.objects.filter(**{f'{src.champ_date}__gte': since})
                        .exclude(**{f'{src.champ_user}__username__in': TEST_USERNAMES})
                        .annotate(hour=ExtractHour(src.champ_date, tzinfo=tz))
                        .values('hour').annotate(n=Count('pk')))
            for r in deposits:
                counts[r['hour']] = counts.get(r['hour'], 0) + r['n']
    except Exception:
        logger.debug('[schedule] activité illisible', exc_info=True)
        return _declared_quiet_hours()
    if sum(counts.values()) < QUIET_MIN_SAMPLES:
        return _declared_quiet_hours()
    busiest = max(counts.values())
    quiet = frozenset(h for h in range(24) if counts.get(h, 0) <= QUIET_SHARE * busiest)
    return (quiet, 'measured') if quiet else _declared_quiet_hours()


def hours_label(hours):
    """« 05 h – 11 h » : les tranches contiguës d'un ensemble d'heures (le tour de minuit compris)."""
    hours = sorted(hours)
    if not hours:
        return 'aucune'
    if len(hours) == 24:
        return 'toute la journée'
    starts = [h for h in hours if (h - 1) % 24 not in hours]
    parts = []
    for start in sorted(starts):
        end = start
        while (end + 1) % 24 in hours:
            end = (end + 1) % 24
        parts.append('%02d h – %02d h' % (start, (end + 1) % 24))
    return ', '.join(parts)


def _is_quiet(moment, hours):
    from django.utils import timezone
    return timezone.localtime(moment).hour in hours


def _next_quiet(moment, hours):
    """Prochain début d'heure creuse ≥ `moment` (lui-même s'il est creux)."""
    from django.utils import timezone
    if _is_quiet(moment, hours):
        return moment
    local = timezone.localtime(moment).replace(minute=0, second=0, microsecond=0)
    for step in range(1, 25 * _SEARCH_DAYS):
        candidate = local + timedelta(hours=step)
        if candidate.hour in hours:
            return candidate
    return moment


def place(placement, requested, now, *, seconds=0, queue_free=None):
    """`(instant, plage en conflit)` d'une programmation d'une tâche de `seconds` secondes.

    Seul le placement MANUEL peut rendre un conflit : l'utilisateur a choisi une heure, on ne la
    change pas dans son dos — on la refuse en lui proposant la fin de la plage.
    `queue_free` : instant où la file GPU se vide (`global_queue.free_at`), pour `auto`.
    """
    from ..models import ScheduledAction as SA

    if placement == SA.PLACEMENT_MANUAL:
        if requested is None:
            raise ScheduleError('Choisissez une date et une heure.')
        if requested < now - timedelta(minutes=1):
            raise ScheduleError('Cette date est déjà passée.')
        window = overlapping_window(requested, requested + timedelta(seconds=max(seconds, 1)))
        return requested, window
    if placement == SA.PLACEMENT_ASAP:
        return _fit(now, seconds), None
    hours, _source = quiet_hours()
    if placement == SA.PLACEMENT_OFF_PEAK:
        return _quiet_slot(now, seconds, hours), None
    if placement == SA.PLACEMENT_AUTO:
        # 1. pas avant que la carte se libère (la file GPU est sérielle) ;
        # 2. une tâche LONGUE part en heures creuses, une courte dès que la carte est libre ;
        # 3. et jamais sur une plage réservée, toute sa durée comprise.
        moment = max(now, queue_free or now)
        if seconds >= LONG_TASK_SECONDS:
            return _quiet_slot(moment, seconds, hours), None
        return _fit(moment, seconds), None
    raise ScheduleError(f'Placement inconnu : {placement}')


def _quiet_slot(moment, seconds, hours):
    """Premier départ en heure creuse, hors plages réservées pour toute la durée de la tâche."""
    moment = _next_quiet(moment, hours)
    for _ in range(_SEARCH_DAYS * 4):
        fitted = _fit(moment, seconds)
        if _is_quiet(fitted, hours):
            return fitted
        moment = _next_quiet(fitted, hours)
    raise ScheduleError('Aucun créneau en heures creuses hors des plages réservées.')


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


def _placement_inputs(placement, model, now, count=1):
    """`(durée prévue en secondes, instant de libération de la file)` d'une programmation.

    La durée est MESURÉE (`global_queue.typical_seconds`, médiane du même modèle) — celle de TOUTES
    les tâches programmées ensemble, qui s'exécuteront l'une après l'autre sur la file sérielle.
    La file n'est lue que pour `auto` : c'est le seul placement qui en dépend.
    """
    from ..models import ScheduledAction as SA
    from .global_queue import free_at, typical_seconds

    seconds = 0.0
    if model is not None:
        seconds = typical_seconds(model)[0] * max(1, count)
    queue_free = free_at(now) if placement == SA.PLACEMENT_AUTO else None
    return seconds, queue_free


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
    seconds, queue_free = _placement_inputs(placement, model, now, count=len(ids or []))
    run_at, conflict = place(placement, requested, now, seconds=seconds, queue_free=queue_free)
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
    now = now or timezone.now()
    model = target_of(action.tool)[1] if action.app else None
    seconds, queue_free = _placement_inputs(placement, model, now)
    run_at, conflict = place(placement, requested, now, seconds=seconds, queue_free=queue_free)
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
