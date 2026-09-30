"""
Journal DATÉ des installations — l'écriture (`opened`/`record`) et la couche du calendrier.

Modèle : `model_manager.InstallEvent`. Doc : `WAMA_MEMORY.md §9bis.1` (la couche « Installations »
du calendrier) et `PROSPECTION_PIPELINE.md` (la route unique d'installation).

Écrit aux points UNIQUES de la route (demande de Fabien, 2026-09-30 : *les installations par
l'assistant et par le model manager*) — jamais par surface :
  • au DISPATCH (`model_installer.dispatch_install`, appelé par `request_install` — la route du
    bouton ET de l'assistant — et par le marcheur d'app) : l'événement s'ouvre avec sa VOIE ;
  • dans les deux tâches Celery (`resumed`) : l'événement retrouvé par sa clé est marqué DÉMARRÉ
    à la prise en charge, puis clos avec l'issue ;
  • `uninstall_model` ; `install_library` quand pip est réellement appelé (`opened`, synchrones).

⚠ AUCUN ARGUMENT NOUVEAU DANS LES MESSAGES CELERY (mesuré le 2026-09-30, relevé par une autre
instance) : la première version passait `via=` à la tâche. Un processus au code neuf (un shell,
gunicorn rechargé) dispatchait alors vers un worker resté sur l'ancien code, qui levait
`TypeError: unexpected keyword argument 'via'` — l'installation échouait. La voie s'écrit donc
côté DEMANDE, la tâche ne reçoit que ce qu'elle recevait déjà : anciens et nouveaux workers
acceptent les mêmes messages. Tenu par `tests_install_history`.

⚠ BEST-EFFORT, TOUJOURS : un journal qui échoue ne fait JAMAIS échouer une installation — même
règle que la provenance (`record_provenance`).
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import timedelta

logger = logging.getLogger(__name__)

#: Voies connues. Une voie inconnue est gardée telle quelle (elle dit d'où vient la demande).
VIA_LABELS = {
    'model_manager': 'model manager',
    'assistant': 'assistant IA',
    'app_requirements': 'prérequis d’une app',
    'cli': 'ligne de commande',
}

#: Facette du calendrier (barre de filtrage commune) et son libellé.
CALENDAR_LAYER = 'installation'
CALENDAR_LAYER_LABEL = 'Installations'


@contextmanager
def opened(kind, key, *, name='', action='install', via=''):
    """Ouvre un événement `RUNNING` ; le bloc remplit `outcome` avec le résultat du driver.

        with opened('model', key, name=row.name, via=via) as outcome:
            outcome.update(install_from_spec(spec))

    Une exception du bloc clôt l'événement en échec puis se propage : le journal ne l'avale pas.
    """
    event_id = _open(kind, key, name=name, action=action, via=via)
    outcome = {}
    try:
        yield outcome
    except Exception as exc:
        _close(event_id, {'ok': False, 'error': f'{type(exc).__name__}: {exc}'})
        raise
    _close(event_id, outcome)


def record(kind, key, *, name='', action='install', via='', result=None, started_at=None):
    """Un événement déjà TERMINÉ (désinstallation : un geste court et synchrone)."""
    event_id = _open(kind, key, name=name, action=action, via=via, started_at=started_at)
    _close(event_id, result or {})


#: Un événement ouvert au dispatch et jamais repris au-delà de ce délai (worker mort, message
#: perdu) n'est plus rattaché : la tâche suivante ouvre le sien.
QUEUED_MAX_AGE = timedelta(hours=24)


def queued(kind, key, *, name='', via=''):
    """Ouvre l'événement AU DISPATCH, avec sa voie — la tâche le reprendra (`resumed`)."""
    return _open(kind, key, name=name, via=via)


@contextmanager
def resumed(kind, key, *, name=''):
    """Reprend, dans la tâche, l'événement ouvert au dispatch (ou en ouvre un sans voie).

    La prise en charge DATE le début réel (l'attente en file n'est pas l'installation) ; la
    sortie du bloc clôt l'événement comme `opened`.
    """
    from django.utils import timezone

    from ..models import InstallEvent
    event_id = None
    try:
        row = (InstallEvent.objects
               .filter(kind=kind, key=key, status=InstallEvent.STATUS_RUNNING,
                       finished_at__isnull=True,
                       started_at__gte=timezone.now() - QUEUED_MAX_AGE)
               .order_by('-started_at').first())
        if row is not None:
            fields = {'started_at': timezone.now()}
            if name and not row.name:
                fields['name'] = str(name)[:255]
            InstallEvent.objects.filter(pk=row.pk).update(**fields)
            event_id = row.pk
    except Exception:
        logger.warning('[install_history] reprise impossible pour %s:%s', kind, key, exc_info=True)
    if event_id is None:
        event_id = _open(kind, key, name=name)
    outcome = {}
    try:
        yield outcome
    except Exception as exc:
        _close(event_id, {'ok': False, 'error': f'{type(exc).__name__}: {exc}'})
        raise
    _close(event_id, outcome)


def _open(kind, key, *, name='', action='install', via='', started_at=None):
    from django.utils import timezone

    from ..models import InstallEvent
    try:
        return InstallEvent.objects.create(
            kind=kind, key=str(key or '')[:255], name=str(name or '')[:255], action=action,
            via=via or '', started_at=started_at or timezone.now()).pk
    except Exception:
        logger.warning('[install_history] ouverture impossible pour %s:%s', kind, key, exc_info=True)
        return None


def _close(event_id, result):
    if event_id is None:
        return
    from django.utils import timezone

    from ..models import InstallEvent
    ok = bool((result or {}).get('ok'))
    detail = {k: result[k] for k in ('error', 'reason', 'freed_gb', 'version', 'size_gb', 'disk_gb',
                                     'already_satisfied', 'installed')
              if k in (result or {}) and result[k] not in (None, '')}
    try:
        InstallEvent.objects.filter(pk=event_id).update(
            status=InstallEvent.STATUS_SUCCESS if ok else InstallEvent.STATUS_FAILURE,
            finished_at=timezone.now(), detail=detail)
    except Exception:
        logger.warning('[install_history] clôture impossible (#%s)', event_id, exc_info=True)


# ── La couche du calendrier ──────────────────────────────────────────────────────────────────

def calendar_events(start, end):
    """Les installations de `[start, end)` — couche de l'INSTANCE (inscrite par `apps.ready`).

    En cours : jusqu'à maintenant. Terminée sans durée mesurable : un bloc minimal, sinon elle
    serait invisible dans une grille horaire.
    """
    from django.db.models import Q
    from django.urls import reverse
    from django.utils import timezone

    from wama.common.services.calendar import (CalendarEvent, NATURE_OBSERVED, POINT_MINUTES,
                                               SCOPE_INSTANCE, app_identity)

    from ..models import InstallEvent

    now = timezone.now()
    rows = (InstallEvent.objects
            .filter(started_at__lt=end)
            .filter(Q(finished_at__gte=start) | Q(finished_at__isnull=True, started_at__gte=start
                                                   - timedelta(days=1)))[:500])
    _label, color = app_identity('model_manager')
    try:
        url = reverse('model_manager:index')
    except Exception:
        url = ''
    events = []
    for row in rows:
        verb = 'Installation' if row.action == InstallEvent.ACTION_INSTALL else 'Désinstallation'
        what = 'librairie ' if row.kind == InstallEvent.KIND_LIBRARY else ''
        title = f'{verb} : {what}{row.name or row.key}'
        if row.status == InstallEvent.STATUS_FAILURE:
            title += ' — échec'
        finish = row.finished_at or now
        if finish - row.started_at < timedelta(minutes=POINT_MINUTES):
            finish = row.started_at + timedelta(minutes=POINT_MINUTES)
        events.append(CalendarEvent(
            key=f'install:{row.pk}', title=title, start=row.started_at, end=finish,
            nature=NATURE_OBSERVED, scope=SCOPE_INSTANCE, app='model_manager',
            status=row.status, color=color, url=url,
            duration_source='measured' if row.finished_at else 'declared',
            extra={'kind': 'install', 'layer': CALENDAR_LAYER,
                   'via': VIA_LABELS.get(row.via, row.via), 'installRunning': row.finished_at is None,
                   'error': (row.detail or {}).get('error', '')},
        ))
    return events
