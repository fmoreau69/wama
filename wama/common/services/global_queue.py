"""
La FILE GLOBALE de WAMA — où en est chaque traitement GPU, pour tous (calendrier, étape 4).
Doc : `WAMA_APP_GENERATION_ROUTE.md §10.6` point 13.8 ; la vue : `WAMA_MEMORY.md §9bis.1`.

Demande de Fabien (2026-09-28) : programmer AUTOMATIQUEMENT une tâche en fonction de la file
globale, et que l'utilisateur sache OÙ EN EST la sienne.

⚠ RIEN N'EST DEVINÉ — la file se LIT à ses trois endroits réels :
- ce qui TOURNE : le gouverneur (`resource_governor.running_tasks`), où le squelette de tâche
  déclare chaque traitement GPU à son démarrage, horodaté ;
- ce que le worker TIENT : la table `unacked` du broker (`held_messages`). Ajouté le 2026-10-13 :
  la file ne voyait que ce qui était DÉCLARÉ au gouverneur, et une campagne de tests nocturnes
  RE-LIVRÉE (aucune déclaration) a occupé le worker GPU tout un après-midi pendant que la pastille
  annonçait « 3 tâches avant » et une heure de début fausse. MESURÉ sur un worker jetable de mêmes
  versions (celery 5.5.3, kombu 5.5.4) : en pool `solo`, une tâche EN COURS reste dans `unacked`
  jusqu'à sa fin — l'accusé de réception part par la boucle d'événements, que la tâche bloque —, et
  un message à échéance (`countdown`, le report « faute de VRAM » du squelette) y est TENU, hors des
  listes, tant que le worker est au repos. Ce que la table tient, et qui n'est pas déclaré :
    · le message EN COURS d'une tâche hors squelette (évaluation de modèles…) ;
    · un message ORPHELIN : délivré à un worker mort, il attend l'échéance de visibilité (6 h) pour
      revenir en file. Il n'occupe RIEN — preuve positive : il a été délivré AVANT le démarrage du
      worker qui consomme la file (`consumer_ready_at`, noté au `worker_ready`) ;
    · un message DIFFÉRÉ (échéance future) : il attend, à son heure ;
- ce qui ATTEND : les listes du broker Celery, dans l'ORDRE où le worker les consommera — une liste
  par palier de priorité (`gpu`, `gpu:3`, … — `priority_steps`/`sep` de `settings`), le palier 0
  d'abord ; dans une liste le message le plus ANCIEN part le premier (poussé à gauche, consommé à
  droite). Chaque message porte l'identifiant de sa tâche ; les items le gardent (`task_id`), d'où
  l'élément, son app et son propriétaire. Un message de liste à échéance future (envoyé pendant
  que le worker travaillait : occupé, il ne va rien chercher — mesuré) attend son heure, lui aussi.

LA FILE GPU EST SÉRIELLE : son worker tourne en `--pool=solo` (`scripts/wama_services.sh:87`). Une
heure de début s'obtient donc en ADDITIONNANT les durées de ce qui précède — une durée MESURÉE :
la médiane des `processing_seconds` récents du même modèle (`ProcessingTimeMixin`), et pour ce qui
tourne, le débit observé (même règle que `wama-eta.js`).

⚠ CONFIDENTIALITÉ : la file est commune, ses éléments ne le sont pas. Un utilisateur voit la PLACE
et la DURÉE des tâches des autres (sans quoi il ne comprendrait pas son attente), jamais leur titre.
Une tâche SYSTÈME (sans élément : évaluation de modèles) se nomme — même règle que
le calendrier (`calendar.queue_events`) : c'est ce qui permet de répondre « derrière quoi ».

LECTEURS : la pastille « En file » (`views.schedule_active`), le calendrier, le placement `auto`, et
depuis le 2026-10-13 l'API de l'assistant (`place_of`, appelée par `get_<app>_status` et
`get_item_detail`) — l'assistant voit la place que la card montre, pas un statut RUNNING à 0 %.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone

logger = logging.getLogger(__name__)

GPU_QUEUE = 'gpu'

#: Durée DÉCLARÉE d'une tâche dont rien n'est mesuré (aucun élément réussi du même modèle).
DEFAULT_TASK_SECONDS = 300

#: Nombre d'exécutions réussies récentes dont la médiane fait la durée typique d'un modèle.
DURATION_SAMPLE = 30

#: Tâches qui précèdent un élément, rendues avec sa place (`place_of`) : de quoi dire « derrière
#: quoi » sans recopier une file entière dans une réponse d'outil.
BEFORE_SHOWN = 5


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
    #: `app_label.model` de l'élément — la clé qui le retrouve sans dépendre du nom d'app
    #: (journal, triade et détail ne nomment pas toutes les apps pareil).
    model_label: str = ''

    def as_dict(self, viewer=None) -> dict:
        own = viewer is not None and self.user_id == getattr(viewer, 'pk', None)
        system = self.item_id is None
        row = {
            'position': self.position, 'state': self.state, 'app': self.app,
            'itemId': self.item_id if own else None, 'own': own, 'system': system,
            'title': self.title if (own or system) else 'Traitement d’un autre utilisateur',
            'expectedStart': self.expected_start.isoformat(),
            'expectedEnd': self.expected_end.isoformat(),
            'durationSource': self.duration_source,
            'startedAt': self.started_at.isoformat() if self.started_at else None,
        }
        if self.extra.get('deferred_until'):
            row['deferredUntil'] = self.extra['deferred_until'].isoformat()
        return row


# ── Lecture du broker ────────────────────────────────────────────────────────────────────────

def _queue_keys(queue):
    from django.conf import settings
    options = getattr(settings, 'CELERY_BROKER_TRANSPORT_OPTIONS', {}) or {}
    steps = sorted(options.get('priority_steps') or [0])
    sep = options.get('sep', '\x06\x16')
    return [queue if not step else f'{queue}{sep}{step}' for step in steps]


@contextmanager
def _broker():
    """`(client, canal)` du broker, connexion RENDUE à la sortie ; `(None, None)` s'il est
    injoignable. Les noms des clés `unacked` se lisent sur le canal (kombu), jamais en dur."""
    try:
        from celery import current_app
        conn = current_app.connection_for_read()
    except Exception:
        logger.debug('[global_queue] broker injoignable', exc_info=True)
        yield None, None
        return
    try:
        try:
            channel = conn.default_channel
            client = channel.client             # absent du transport `memory://` (tests, Windows)
        except Exception:
            logger.debug('[global_queue] broker injoignable', exc_info=True)
            channel = client = None
        yield client, channel
    finally:
        try:
            conn.release()
        except Exception:
            pass


def _eta(headers):
    """L'échéance d'un message (`countdown`/`eta` à l'envoi), en datetime conscient, ou None."""
    value = headers.get('eta')
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)


def broker_messages(queue=GPU_QUEUE, client=None) -> list[dict]:
    """Messages en ATTENTE sur `queue`, dans l'ordre où le worker les prendra.

    `[{task_id, task_name, eta}]` ; vide si le broker est injoignable (le calendrier retombe alors
    sur ce que disent les items eux-mêmes — une file qu'on ne peut pas lire n'est pas une file vide,
    mais on ne l'invente pas).
    """
    if client is None:
        with _broker() as (client, _channel):
            return broker_messages(queue, client=client) if client is not None else []
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
                out.append({'task_id': headers['id'], 'task_name': headers.get('task', ''),
                            'eta': _eta(headers)})
    return out


def held_messages(queue=GPU_QUEUE, client=None, *, keys=('unacked', 'unacked_index')) -> list[dict]:
    """Messages DÉLIVRÉS à un worker de `queue` et pas encore confirmés — la table `unacked`.

    `[{task_id, task_name, since, eta}]`, du plus ancien au plus récent ; `since` = l'instant de la
    délivrance (`unacked_index`). Vide si le broker est injoignable. Ce que chacun EST (en cours,
    orphelin, différé) se décide dans `_classify_held` — cf. l'en-tête du module.
    """
    if client is None:
        with _broker() as (client, channel):
            if client is None:
                return []
            keys = (getattr(channel, 'unacked_key', keys[0]),
                    getattr(channel, 'unacked_index_key', keys[1]))
            return held_messages(queue, client=client, keys=keys)
    try:
        table = client.hgetall(keys[0]) or {}
        delivered = dict(client.zrange(keys[1], 0, -1, withscores=True) or [])
    except Exception:
        logger.debug('[global_queue] table %s illisible', keys[0], exc_info=True)
        return []
    out = []
    for tag, payload in table.items():
        try:
            message, _exchange, routing_key = json.loads(payload)
            headers = message.get('headers') or {}
        except (TypeError, ValueError, AttributeError):
            continue
        if routing_key != queue or not headers.get('id'):
            continue
        score = delivered.get(tag)
        out.append({'task_id': headers['id'], 'task_name': headers.get('task', ''),
                    'since': (datetime.fromtimestamp(float(score), tz=dt_timezone.utc)
                              if score is not None else None),
                    'eta': _eta(headers)})
    return sorted(out, key=lambda m: m['since'] or datetime.max.replace(tzinfo=dt_timezone.utc))


# ── Démarrage du worker d'une file ───────────────────────────────────────────────────────────
# La preuve qu'un message tenu est ORPHELIN : il a été délivré avant que le worker qui consomme sa
# file ne démarre. Un seul worker par file (`scripts/wama_services.sh`, `start_celery_worker`).

def _ready_key(queue):
    return f'wama:queue_consumer_ready:{queue}'


def note_consumer_ready(queues, at=None) -> None:
    """Note l'instant où un worker consommant `queues` est PRÊT (`wama/celery.py`, `worker_ready`).
    Sans expiration : la valeur ne vaut que jusqu'au démarrage suivant, qui la remplace."""
    from django.core.cache import cache
    stamp = (at or datetime.now(dt_timezone.utc)).timestamp()
    for queue in queues or ():
        try:
            cache.set(_ready_key(queue), stamp, None)
        except Exception:
            logger.debug('[global_queue] démarrage de %s non noté', queue, exc_info=True)


def consumer_ready_at(queue=GPU_QUEUE):
    """Instant de démarrage du worker de `queue`, ou None s'il n'est pas connu (cache perdu,
    worker antérieur au 2026-10-13) — alors aucun message tenu n'est déclaré orphelin par lui."""
    from django.core.cache import cache
    try:
        stamp = cache.get(_ready_key(queue))
    except Exception:
        return None
    return datetime.fromtimestamp(float(stamp), tz=dt_timezone.utc) if stamp else None


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


def _classify_held(held, running, by_task, now, ready_at):
    """Ce que sont les messages TENUS : `(en_cours, différés)`.

    - échéance FUTURE → différé : il attend son heure ;
    - délivré AVANT le démarrage du worker de la file → orphelin : il n'occupe rien (écarté) ;
    - parmi les autres, le worker `solo` n'en exécute QU'UN (`--prefetch-multiplier=1`) : celui
      qu'une ligne du gouverneur déclare déjà — il y est représenté, rien à ajouter —, sinon le
      plus RÉCEMMENT délivré. Les plus anciens sont des orphelins dont la preuve manque (worker
      d'avant le 2026-10-13, cache perdu) : les compter ferait attendre derrière une tâche morte.
    `en_cours` est un message non déclaré, ou None.
    """
    declared = {(r.get('app'), str(r.get('item'))) for r in running}
    deferred, candidates = [], []
    for message in held:
        if message.get('eta') and message['eta'] > now:
            deferred.append(message)
        elif ready_at is None or message.get('since') is None or message['since'] >= ready_at:
            candidates.append(message)

    def declared_row(message):
        src_obj = by_task.get(message['task_id'])
        return bool(src_obj) and (src_obj[0].app, str(src_obj[1].pk)) in declared

    if not candidates or any(declared_row(m) for m in candidates):
        return None, deferred
    return candidates[-1], deferred


def _running_entry(row, src_obj, started, now, cache):
    """Une ligne EN COURS : fin au débit observé de l'élément, sinon à sa durée typique."""
    from .calendar import _progress_of, predicted_end

    if src_obj:
        seconds, source = typical_seconds(src_obj[0].model, cache)
    elif row.get('task_name'):
        seconds, source = _system_task_seconds(row['task_name'])
    else:
        seconds, source = float(DEFAULT_TASK_SECONDS), 'declared'
    end = predicted_end(started, _progress_of(src_obj[0].app, src_obj[1]), now) if src_obj else None
    if end is None:
        end = max(now + timedelta(minutes=1), started + timedelta(seconds=seconds))
    else:
        source = 'measured'
    return _entry(0, 'running', row, src_obj, started, end, source, started_at=started)


def snapshot(now=None, *, running=None, queued=None, held=None, ready_at=None) -> list[QueueEntry]:
    """La file GPU telle qu'elle s'exécutera : en cours, puis en attente, avec des heures PRÉVUES.

    `running`/`queued`/`held`/`ready_at` sont injectables (tests) ; par défaut lus au gouverneur,
    aux listes et à la table `unacked` du broker, et au démarrage noté du worker GPU.

    ORDRE de ce qui attend : la file du broker dans son ordre de consommation ; un message DIFFÉRÉ
    passe devant dès que son échéance est atteinte (le worker le tient déjà, il l'exécute à la
    première place libre), sinon il attend son heure — sa place est alors celle de son échéance.
    """
    from django.utils import timezone

    now = now or timezone.now()
    if running is None:
        try:
            from .resource_governor import running_tasks
            running = running_tasks()
        except Exception:
            running = []
    if queued is None:
        queued = broker_messages()
    if held is None:
        held = held_messages()
        if ready_at is None:
            ready_at = consumer_ready_at(GPU_QUEUE)

    cache = {}
    entries, cursor = [], now
    known = _items_by_key([(r.get('app'), r.get('item')) for r in running])
    by_task = _items_by_task([m['task_id'] for m in list(queued) + list(held)])
    executing, deferred_held = _classify_held(held, running, by_task, now, ready_at)

    for row in sorted(running, key=lambda r: float(r.get('ts') or 0)):
        started = datetime.fromtimestamp(float(row.get('ts') or 0), tz=dt_timezone.utc)
        src_obj = known.get((row.get('app'), str(row.get('item'))))
        entry = _running_entry(row, src_obj, started, now, cache)
        entries.append(entry)
        cursor = max(cursor, entry.expected_end)
    if executing is not None:
        # En cours SANS déclaration au gouverneur (tâche hors squelette) : le worker la tient.
        entry = _running_entry(executing, by_task.get(executing['task_id']),
                               executing.get('since') or now, now, cache)
        entries.append(entry)
        cursor = max(cursor, entry.expected_end)

    ready = [m for m in queued if not (m.get('eta') and m['eta'] > now)]
    deferred = sorted([m for m in queued if m.get('eta') and m['eta'] > now] + deferred_held,
                      key=lambda m: m['eta'])
    position = 0
    while ready or deferred:
        if deferred and (not ready or deferred[0]['eta'] <= cursor):
            message = deferred.pop(0)
            start = max(cursor, message['eta'])
        else:
            message, start = ready.pop(0), cursor
        position += 1
        src_obj = by_task.get(message['task_id'])
        if src_obj:
            seconds, source = typical_seconds(src_obj[0].model, cache)
        else:
            seconds, source = _system_task_seconds(message['task_name'])
        end = start + timedelta(seconds=seconds)
        entry = _entry(position, 'queued', message, src_obj, start, end, source)
        if message.get('eta') and message['eta'] > now:
            entry.extra['deferred_until'] = message['eta']
        entries.append(entry)
        cursor = end
    return entries


def _system_task_seconds(task_name):
    """Une tâche sans élément (prospection) : sa durée déclarée. La campagne de tests nocturnes
    n'est plus dans cette file depuis le 2026-10-13 : elle a sa file, `nightly` (`settings.py`) —
    sa plage réservée reste lue par le calendrier (`calendar.reserved_windows`)."""
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
        started_at=started_at,
        model_label=obj._meta.label_lower if obj is not None else '')


def _system_title(task_name):
    return {'model_manager.assess_proposed': 'Évaluation de modèles'}.get(task_name, 'Tâche système')


def free_at(now=None, entries=None):
    """Instant où la file GPU sera VIDE, d'après l'instantané."""
    from django.utils import timezone
    now = now or timezone.now()
    entries = snapshot(now) if entries is None else entries
    return max([now] + [e.expected_end for e in entries])


def _before(entry, entries):
    """Ce qui passe AVANT `entry` : les tâches dont le début prévu précède le sien."""
    return [other for other in entries if other.expected_start < entry.expected_start]


def for_user(user, now=None, entries=None) -> list[dict]:
    """Les éléments de `user` dans la file, avec leur place et le nombre de tâches devant eux."""
    entries = snapshot(now) if entries is None else entries
    own = []
    for e in entries:
        if e.user_id != getattr(user, 'pk', None):
            continue
        row = e.as_dict(user)
        row['ahead'] = len(_before(e, entries))
        own.append(row)
    return own


def place_of(obj, viewer, entries=None) -> dict | None:
    """Où en est l'élément `obj` dans la file GPU, vu par `viewer` — None s'il n'y est pas.

    La ligne de la pastille de sa card (`for_user`), plus ce qui passe AVANT lui (`before`, les
    `BEFORE_SHOWN` premières, sous la même règle de confidentialité) : c'est ce qui répond à
    « pourquoi ma tâche n'avance pas ? ». Lu par l'API de l'assistant (`tool_api`)."""
    entries = snapshot() if entries is None else entries
    label = obj._meta.label_lower
    for e in entries:
        if e.model_label == label and str(e.item_id) == str(obj.pk):
            before = _before(e, entries)
            row = e.as_dict(viewer)
            row['ahead'] = len(before)
            row['before'] = [other.as_dict(viewer) for other in before[:BEFORE_SHOWN]]
            return row
    return None
