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
  • `uninstall_model` ; `install_library` et `uninstall_library` (2026-10-23) quand pip est
    réellement appelé (`opened`, synchrones).

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

#: Contre quoi un pilote a vérifié ce qu'il a posé — le vocabulaire de `detail['verified']`
#: (`model_installer`, en-tête « L'empreinte de ce qu'on installe », 2026-11-05).
VERIFIED_AGAINST = {
    'pinned': "l'empreinte épinglée dans sa déclaration",
    'published': "l'empreinte publiée par sa source",
    'size': "la taille publiée par sa source (aucune empreinte publiée)",
}


def verified_text(detail) -> str:
    """Ce que dit `detail['verified']`, en une phrase — '' quand rien n'a été vérifié ou que la
    valeur est hors du vocabulaire (on ne dit pas vérifié ce qu'on ne sait pas nommer)."""
    verified = (detail or {}).get('verified') or {}
    against = VERIFIED_AGAINST.get(verified.get('against'))
    if not against:
        return ''
    count = verified.get('count')
    by = ' — par le démon Ollama' if verified.get('by') == 'ollama' else ''
    return f"{f'{count} fichier(s) ' if count else ''}vérifié(s) contre {against}{by}"


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
    outcome = Outcome()
    outcome.event_id = event_id
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


class Outcome(dict):
    """Le résultat que le bloc d'une installation remplit (`opened`, `resumed`), et l'événement
    qu'il datera (`event_id`, None si le journal n'a pas pu l'ouvrir) — l'élément que suivent la
    mesure de l'avancement et la notification de fin (2026-11-06)."""
    event_id = None


#: Un événement ouvert au dispatch et jamais repris au-delà de ce délai (worker mort, message
#: perdu) n'est plus rattaché : la tâche suivante ouvre le sien, et le calendrier cesse de le
#: montrer « en cours ».
QUEUED_MAX_AGE = timedelta(hours=24)
NOT_RESUMED = 'demande jamais prise en charge par une tâche'


def open_event(kind, key):
    """L'événement OUVERT le plus récent de cette clé (une demande que la tâche reprendra, ou une
    installation en cours), None sinon — celui que reprend la tâche (`resumed`) et que la demande
    rend comme l'élément suivi (`request_install`, `install_id`)."""
    from django.utils import timezone

    from ..models import InstallEvent
    return (InstallEvent.objects
            .filter(kind=kind, key=key, status=InstallEvent.STATUS_RUNNING,
                    finished_at__isnull=True, started_at__gte=timezone.now() - QUEUED_MAX_AGE)
            .order_by('-started_at').first())


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
        row = open_event(kind, key)
        if row is not None:
            fields = {'started_at': timezone.now()}
            if name and not row.name:
                fields['name'] = str(name)[:255]
            InstallEvent.objects.filter(pk=row.pk).update(**fields)
            event_id = row.pk
            # Les demandes PLUS ANCIENNES de la même clé restées ouvertes ne seront jamais
            # reprises (mesuré le 2026-09-30 : deux demandes pyannote, l'une tombée sur un worker
            # d'avant le journal) — elles se closent ici plutôt que de rester « en cours ».
            (InstallEvent.objects
             .filter(kind=kind, key=key, status=InstallEvent.STATUS_RUNNING,
                     finished_at__isnull=True)
             .exclude(pk=row.pk)
             .update(status=InstallEvent.STATUS_FAILURE, finished_at=timezone.now(),
                     detail={'error': NOT_RESUMED}))
    except Exception:
        logger.warning('[install_history] reprise impossible pour %s:%s', kind, key, exc_info=True)
    if event_id is None:
        event_id = _open(kind, key, name=name)
    outcome = Outcome()
    outcome.event_id = event_id
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
    # `verified` (2026-11-05) : contre quelle empreinte le pilote a vérifié ce qu'il a posé —
    # épinglée, publiée par la source, ou la seule taille (`model_installer`, en-tête des pilotes).
    detail = {k: result[k] for k in ('error', 'reason', 'freed_gb', 'version', 'size_gb', 'disk_gb',
                                     'already_satisfied', 'installed', 'verified')
              if k in (result or {}) and result[k] not in (None, '')}
    try:
        InstallEvent.objects.filter(pk=event_id).update(
            status=InstallEvent.STATUS_SUCCESS if ok else InstallEvent.STATUS_FAILURE,
            finished_at=timezone.now(), detail=detail)
    except Exception:
        logger.warning('[install_history] clôture impossible (#%s)', event_id, exc_info=True)


def title(row) -> str:
    """« Installation : <nom> » — l'intitulé d'un événement, au calendrier comme dans l'échange de
    l'assistant et dans la notification de sa fin."""
    from ..models import InstallEvent
    what = 'librairie ' if row.kind == InstallEvent.KIND_LIBRARY else ''
    return f'{row.get_action_display()} : {what}{row.name or row.key}'


# ── Où en est une installation (2026-11-06) ──────────────────────────────────────────────────
# Demande de Fabien : une barre de progression à l'installation d'un modèle, « puis on l'étend à
# l'assistant avec message ». L'ÉLÉMENT d'une installation est son événement daté (`InstallEvent`,
# qui existait) : il a un numéro, il survit à la tâche, il dit l'issue. L'avancement VIVANT est
# celui que la tâche publie (`InstallMeter` → `INSTALL_CACHE_PREFIX`), rattaché à l'événement par
# son numéro (`install_id`) — une installation suivante de la même clé ne se lit pas à sa place.

#: L'app à laquelle une installation appartient : la page qui la montre, la famille sous laquelle
#: l'assistant la suit (`job_families`), l'`app` de la notification de sa fin.
FAMILY = 'model_manager'


def live_state(row) -> dict:
    """L'avancement publié par la tâche de CET événement, {} sinon (pas encore pris en charge,
    publié par une autre installation de la même clé, ou tâche que Celery ne dit plus vivante —
    la lecture commune `task_progress.progression_en_cours`, garde des vues de lancement)."""
    from wama.common.utils.task_progress import progression_en_cours

    from ..tasks import INSTALL_CACHE_PREFIX
    live = progression_en_cours(INSTALL_CACHE_PREFIX + row.key) or {}
    return live if live.get('install_id') == row.pk else {}


def progress_row(row, now=None) -> dict:
    """La ligne de suivi d'UNE installation, au contrat de `tool_api.job_progress` (la ligne d'une
    card dans l'échange) : `family`, `id`, `label`, statut normalisé, `progress`, `terminal`, `ok`
    — et ce qu'une installation sait de plus (`model_key`, l'étape en clair, Go reçus / attendus).
    Une demande ouverte que la tâche n'a pas encore prise attend dans la file : PENDING."""
    from django.utils import timezone

    from wama.common.models import JOB_PENDING, JOB_RUNNING, normalize_job_status
    from wama.common.services.job_families import line
    now = now or timezone.now()
    status, error, _abandoned = effective_state(row, now)
    status = normalize_job_status(status)
    live = live_state(row) if status == JOB_RUNNING else {}
    if status == JOB_RUNNING and not live:
        status = JOB_PENDING
    out = line(FAMILY, row.pk, label=title(row), status=status, progress=live.get('pct'),
               model_key=row.key, started_at=row.started_at)
    if live.get('status'):
        out['step'] = live['status']
    for key in ('done_gb', 'total_gb'):
        if live.get(key) is not None:
            out[key] = live[key]
    if error:
        out['error'] = error
    return out


def job_row(user, pk):
    """L'installation n° `pk` pour `user` — None hors de son droit de voir le model manager (la
    garde de la couche « Installations » du calendrier : une installation vaut pour l'instance, la
    page qui la montre a ses lecteurs). Lue par la famille suivie `model_manager` (`job_families`)."""
    from wama.accounts.permissions import accessible

    from ..models import InstallEvent
    try:
        if not accessible(user, 'app', FAMILY):
            return None
        row = InstallEvent.objects.filter(pk=int(pk), kind=InstallEvent.KIND_MODEL).first()
    except (TypeError, ValueError):
        return None
    return progress_row(row) if row is not None else None


def install_rows(since=None, now=None) -> list:
    """Les installations de modèles EN COURS ou en attente, et celles FINIES depuis `since` — ce
    que la page du model manager suit : à son ouverture (un F5, une installation lancée par
    l'assistant ou par une app qui attend son modèle), puis à chaque passage, pour en dire l'issue.
    Une ligne par clé, la plus récente."""
    from django.db.models import Q
    from django.utils import timezone

    from ..models import InstallEvent
    now = now or timezone.now()
    wanted = Q(status=InstallEvent.STATUS_RUNNING, finished_at__isnull=True,
               started_at__gte=now - QUEUED_MAX_AGE)
    if since is not None:
        wanted |= Q(finished_at__gte=since)
    rows = (InstallEvent.objects
            .filter(kind=InstallEvent.KIND_MODEL, action=InstallEvent.ACTION_INSTALL)
            .filter(wanted).order_by('-started_at'))
    seen, out = set(), []
    for row in rows:
        if row.key in seen:
            continue                  # la plus récente d'une clé : les autres seront closes
        seen.add(row.key)
        out.append(progress_row(row, now))
    return out


def notify_end(user_id, event_id, name: str, result: dict) -> None:
    """La fin d'une installation, à QUI L'A DEMANDÉE — par LA fin commune des traitements
    (`notify_job_end` : e-mail et notification dans WAMA selon son profil), qui DÉSIGNE l'élément
    (`model_manager` / `InstallEvent`) : l'échange de l'assistant la raconte dans le fil d'où elle
    a été demandée (`job_follow_ups`). Personne n'est prévenu sans demandeur (installation de la
    ligne de commande) — le journal ne nomme personne (décision ② de `WAMA_MEMORY §9bis.1`).
    Best-effort, comme le journal."""
    if not user_id or not event_id:
        return
    try:
        from django.contrib.auth import get_user_model

        from wama.common.utils.notifications import notify_job_end

        from ..models import InstallEvent
        user = get_user_model().objects.filter(pk=user_id).first()
        row = InstallEvent.objects.filter(pk=event_id).first()
        if user is None or row is None:
            return
        ok = bool((result or {}).get('ok'))
        detail = (result or {}).get('error') or ('' if not ok else verified_text(result))
        notify_job_end(row, FAMILY, row.get_action_display(), name or row.name or row.key, ok,
                       detail=detail or '', user=user)
    except Exception:
        logger.warning('[install_history] fin non notifiée (#%s)', event_id, exc_info=True)


def effective_state(row, now):
    """`(statut, erreur, abandonnée)` d'un événement tel qu'il se DIT — au calendrier et à
    l'assistant (`tool_api.list_installations`). Ouvert depuis plus que `QUEUED_MAX_AGE` sans
    jamais être repris, il n'est plus « en cours » : c'est une demande restée sans tâche."""
    from ..models import InstallEvent
    status, error = row.status, (row.detail or {}).get('error', '')
    abandoned = row.finished_at is None and now - row.started_at > QUEUED_MAX_AGE
    if abandoned:
        status, error = InstallEvent.STATUS_FAILURE, NOT_RESUMED
    return status, error, abandoned


# ── La couche du calendrier ──────────────────────────────────────────────────────────────────

def calendar_events(start, end):
    """Les installations de `[start, end)` — couche de l'INSTANCE (inscrite par `apps.ready`).

    En cours : jusqu'à maintenant. Terminée sans durée mesurable : un bloc minimal, sinon elle
    serait invisible dans une grille horaire.
    """
    from django.db.models import Q
    from django.urls import reverse
    from django.utils import timezone

    from wama.common.app_registry import app_identity
    from wama.common.services.calendar import (CalendarEvent, NATURE_OBSERVED, NATURE_PREDICTED,
                                               POINT_MINUTES, SCOPE_INSTANCE, predicted_end)

    from ..models import InstallEvent

    now = timezone.now()
    rows = (InstallEvent.objects
            .filter(started_at__lt=end)
            .filter(Q(finished_at__gte=start) | Q(finished_at__isnull=True, started_at__gte=start
                                                   - timedelta(days=1)))[:500])
    color = app_identity('model_manager')['color']
    try:
        url = reverse('model_manager:index')
    except Exception:
        url = ''
    events = []
    for row in rows:
        label = title(row)
        status, error, abandoned = effective_state(row, now)
        if status == InstallEvent.STATUS_FAILURE:
            label += ' — échec'
        running = row.finished_at is None and not abandoned
        # En cours : la fin PRÉVUE par le débit observé (2026-11-06), la règle des traitements en
        # cours du calendrier (`calendar.predicted_end`) sur l'avancement que la tâche publie —
        # sans avancement, aucune fin inventée : l'événement s'arrête à maintenant.
        expected = (predicted_end(row.started_at, live_state(row).get('pct') or None, now)
                    if running else None)
        finish = row.finished_at or (row.started_at if abandoned else expected or now)
        if finish - row.started_at < timedelta(minutes=POINT_MINUTES):
            finish = row.started_at + timedelta(minutes=POINT_MINUTES)
        events.append(CalendarEvent(
            key=f'install:{row.pk}', title=label, start=row.started_at, end=finish,
            nature=NATURE_PREDICTED if running else NATURE_OBSERVED, scope=SCOPE_INSTANCE,
            app='model_manager', status=status, color=color, url=url,
            duration_source='measured' if row.finished_at or expected else 'declared',
            extra={'kind': 'install', 'layer': CALENDAR_LAYER,
                   'via': VIA_LABELS.get(row.via, row.via), 'installRunning': running,
                   'error': error},
        ))
    return events
