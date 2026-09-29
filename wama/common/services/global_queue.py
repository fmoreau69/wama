"""
La FILE GLOBALE de WAMA — où en est chaque traitement GPU, pour tous (calendrier, étape 4).
Doc : `WAMA_APP_GENERATION_ROUTE.md §10.6` point 13.8 ; la vue : `WAMA_MEMORY.md §9bis.1`.

Demande de Fabien (2026-09-28) : programmer AUTOMATIQUEMENT une tâche en fonction de la file
globale, et que l'utilisateur sache OÙ EN EST la sienne.

⚠ RIEN N'EST DEVINÉ — la file se LIT à ses deux endroits réels :
- ce qui TOURNE : le gouverneur (`resource_governor.running_tasks`), où le squelette de tâche
  déclare chaque traitement GPU à son démarrage, horodaté ;
- ce qui ATTEND : les listes du broker Celery, dans l'ORDRE où le worker les consommera — une liste
  par palier de priorité (`gpu`, `gpu:3`, … — `priority_steps`/`sep` de `settings`), le palier 0
  d'abord ; dans une liste le message le plus ANCIEN part le premier (poussé à gauche, consommé à
  droite). Chaque message porte l'identifiant de sa tâche ; les items le gardent (`task_id`), d'où
  l'élément, son app et son propriétaire.

LA FILE GPU EST SÉRIELLE : son worker tourne en `--pool=solo` (`scripts/wama_services.sh:87`). Une
heure de début s'obtient donc en ADDITIONNANT les durées de ce qui précède — une durée MESURÉE :
la médiane des `processing_seconds` récents du même modèle (`ProcessingTimeMixin`), et pour ce qui
tourne, le débit observé (même règle que `wama-eta.js`).

⚠ CONFIDENTIALITÉ : la file est commune, ses éléments ne le sont pas. Un utilisateur voit la PLACE
et la DURÉE des tâches des autres (sans quoi il ne comprendrait pas son attente), jamais leur titre.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone

logger = logging.getLogger(__name__)

GPU_QUEUE = 'gpu'

#: Durée DÉCLARÉE d'une tâche dont rien n'est mesuré (aucun élément réussi du même modèle).
DEFAULT_TASK_SECONDS = 300

#: Nombre d'exécutions réussies récentes dont la médiane fait la durée typique d'un modèle.
DURATION_SAMPLE = 30


@dataclass
class QueueEntry:
    position: int                     # 0 = en cours, 1 = la prochaine, …
    state: str                        # 'running' | 'queued'
    task_id: str
    task_name: str
    expected_start: datetime
    expected_end: datetime
    duration_source: str             # 'measured' | 'declared'
    app: str = ''
    item_id: object = None
    user_id: int | None = None
    title: str = ''
    started_at: datetime | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self, viewer=None) -> dict:
        own = viewer is not None and self.user_id == getattr(viewer, 'pk', None)
        return {
            'position': self.position, 'state': self.state, 'app': self.app,
            'itemId': self.item_id if own else None, 'own': own,
            'title': self.title if own else 'Traitement d’un autre utilisateur',
            'expectedStart': self.expected_start.isoformat(),
            'expectedEnd': self.expected_end.isoformat(),
            'durationSource': self.duration_source,
        }


# ── Lecture du broker ────────────────────────────────────────────────────────────────────────

def _queue_keys(queue):
    from django.conf import settings
    options = getattr(settings, 'CELERY_BROKER_TRANSPORT_OPTIONS', {}) or {}
    steps = sorted(options.get('priority_steps') or [0])
    sep = options.get('sep', '\x06\x16')
    return [queue if not step else f'{queue}{sep}{step}' for step in steps]


def broker_messages(queue=GPU_QUEUE, client=None) -> list[dict]:
    """Messages en ATTENTE sur `queue`, dans l'ordre où le worker les prendra.

    `[{task_id, task_name}]` ; vide si le broker est injoignable (le calendrier retombe alors sur
    ce que disent les items eux-mêmes — une file qu'on ne peut pas lire n'est pas une file vide,
    mais on ne l'invente pas).
    """
    if client is None:
        try:
            from celery import current_app
            conn = current_app.connection_for_read()
            client = conn.default_channel.client
        except Exception:
            logger.debug('[global_queue] broker injoignable', exc_info=True)
            return []
    out = []
    for key in _queue_keys(queue):
        try:
            raw = client.lrange(key, 0, -1) or []
        except Exception:
            logger.debug('[global_queue] lecture de %s impossible', key, exc_info=True)
            return []
        for message in reversed(raw):              # la tête de consommation est à DROITE
            try:
                headers = json.loads(message).get('headers') or {}
            except (TypeError, ValueError):
                continue
            if headers.get('id'):
                out.append({'task_id': headers['id'], 'task_name': headers.get('task', '')})
    return out


# ── Durées mesurées ──────────────────────────────────────────────────────────────────────────

def typical_seconds(model, _cache=None) -> tuple[float, str]:
    """Durée TYPIQUE d'un traitement de `model` : `(secondes, 'measured' | 'declared')`.

    Médiane des `processing_seconds` > 0 des derniers éléments RÉUSSIS, tous utilisateurs RÉELS
    confondus — c'est une propriété de la machine et du modèle, pas de la personne ; les comptes de
    test sont exclus (leurs témoins sont synthétiques).
    """
    if _cache is not None and model in _cache:
        return _cache[model]
    result = (float(DEFAULT_TASK_SECONDS), 'declared')
    try:
        from ..models import JOB_SUCCESS
        names = {f.name for f in model._meta.get_fields()}
        if 'processing_seconds' in names and 'status' in names:
            qs = model.objects.filter(status=JOB_SUCCESS, processing_seconds__gt=0)
            if 'user' in names:
                # Les témoins des comptes de TEST (images de 8×8 px…) ne mesurent pas la machine —
                # même règle que l'ETA apprise (`eta_estimator.record_run`, 2026-09-29).
                from .nightly_tests import TEST_USERNAMES
                qs = qs.exclude(user__username__in=TEST_USERNAMES)
            values = sorted(qs.order_by('-pk').values_list('processing_seconds', flat=True)
                            [:DURATION_SAMPLE])
            if values:
                result = (float(values[len(values) // 2]), 'measured')
    except Exception:
        logger.debug('[global_queue] durée typique de %s illisible', model, exc_info=True)
    if _cache is not None:
        _cache[model] = result
    return result


# ── L'instantané de la file ──────────────────────────────────────────────────────────────────

def _items_by_task(task_ids):
    """`task_id → (source, objet)` pour les items qui portent l'un de ces identifiants."""
    from .journal import sources
    found = {}
    if not task_ids:
        return found
    for src in sources():
        names = {f.name for f in src.model._meta.get_fields()}
        if 'task_id' not in names:
            continue
        for obj in src.model.objects.filter(task_id__in=task_ids):
            found[str(obj.task_id)] = (src, obj)
    return found


def _items_by_key(keys):
    """`(app, id) → (source, objet)` pour les tâches EN COURS lues au gouverneur."""
    from .journal import sources
    by_app = {src.app: src for src in sources()}
    found = {}
    for app, item_id in keys:
        src = by_app.get(app)
        if src is None:
            continue
        obj = src.model.objects.filter(pk=item_id).first()
        if obj is not None:
            found[(app, str(item_id))] = (src, obj)
    return found


def snapshot(now=None, *, running=None, queued=None) -> list[QueueEntry]:
    """La file GPU telle qu'elle s'exécutera : en cours, puis en attente, avec des heures PRÉVUES.

    `running`/`queued` sont injectables (tests) ; par défaut lus au gouverneur et au broker.
    """
    from django.utils import timezone

    from .calendar import _progress_of, predicted_end

    now = now or timezone.now()
    if running is None:
        try:
            from .resource_governor import running_tasks
            running = running_tasks()
        except Exception:
            running = []
    if queued is None:
        queued = broker_messages()

    cache = {}
    entries, cursor = [], now
    known = _items_by_key([(r.get('app'), r.get('item')) for r in running])
    for row in sorted(running, key=lambda r: float(r.get('ts') or 0)):
        started = datetime.fromtimestamp(float(row.get('ts') or 0), tz=dt_timezone.utc)
        src_obj = known.get((row.get('app'), str(row.get('item'))))
        seconds, source = (typical_seconds(src_obj[0].model, cache) if src_obj
                           else (float(DEFAULT_TASK_SECONDS), 'declared'))
        end = predicted_end(started, _progress_of(row.get('app'), src_obj[1]), now) if src_obj else None
        if end is None:
            end = max(now + timedelta(minutes=1), started + timedelta(seconds=seconds))
        else:
            source = 'measured'
        entries.append(_entry(0, 'running', row, src_obj, started, end, source, started_at=started))
        cursor = max(cursor, end)

    by_task = _items_by_task([m['task_id'] for m in queued])
    for position, message in enumerate(queued, start=1):
        src_obj = by_task.get(message['task_id'])
        if src_obj:
            seconds, source = typical_seconds(src_obj[0].model, cache)
        else:
            seconds, source = _system_task_seconds(message['task_name'])
        start, end = cursor, cursor + timedelta(seconds=seconds)
        entries.append(_entry(position, 'queued', message, src_obj, start, end, source))
        cursor = end
    return entries


def _system_task_seconds(task_name):
    """Une tâche sans élément (tests nocturnes, prospection) : sa durée réservée si elle en a une."""
    if task_name == 'common.run_nightly_tests':
        from .calendar import window_minutes
        minutes, source = window_minutes('nightly-functional-tests')
        return float(minutes * 60), source
    return float(DEFAULT_TASK_SECONDS), 'declared'


def _entry(position, state, row, src_obj, start, end, source, started_at=None):
    src, obj = src_obj if src_obj else (None, None)
    return QueueEntry(
        position=position, state=state,
        task_id=str(row.get('task_id') or row.get('token') or ''),
        task_name=row.get('task_name', ''), expected_start=start, expected_end=end,
        duration_source=source, app=src.app if src else (row.get('app') or ''),
        item_id=obj.pk if obj is not None else None,
        user_id=getattr(obj, f'{src.champ_user}_id', None) if src else None,
        title=str(obj) if obj is not None else _system_title(row.get('task_name', '')),
        started_at=started_at)


def _system_title(task_name):
    return {'common.run_nightly_tests': 'Tests nocturnes',
            'model_manager.assess_proposed': 'Évaluation de modèles'}.get(task_name, 'Tâche système')


def free_at(now=None, entries=None):
    """Instant où la file GPU sera VIDE, d'après l'instantané."""
    from django.utils import timezone
    now = now or timezone.now()
    entries = snapshot(now) if entries is None else entries
    return max([now] + [e.expected_end for e in entries])


def for_user(user, now=None, entries=None) -> list[dict]:
    """Les éléments de `user` dans la file, avec leur place et le nombre de tâches devant eux."""
    entries = snapshot(now) if entries is None else entries
    own = []
    for e in entries:
        if e.user_id != getattr(user, 'pk', None):
            continue
        row = e.as_dict(user)
        row['ahead'] = sum(1 for other in entries
                           if other.expected_start < e.expected_start)
        own.append(row)
    return own
