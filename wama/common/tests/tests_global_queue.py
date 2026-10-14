"""
File GLOBALE et placement automatique — calendrier, étape 4 (2026-09-28).
`common/services/global_queue.py`, `scheduled_actions.place` ; doc `ROUTE §10.6` 13.8.

Ce que ces gardes tiennent :
- la file se LIT dans l'ordre réel de consommation du broker (palier 0 d'abord, le plus ancien
  d'abord) et les heures prévues ADDITIONNENT des durées MESURÉES (file GPU sérielle) ;
- la confidentialité : la place des tâches des autres, jamais leur titre ;
- `auto` attend que la carte se libère, envoie une tâche longue en heures creuses MESURÉES
  (comptes de test exclus), et aucune tâche ne DÉBORDE sur une plage réservée — sa durée comprise ;
- l'utilisateur voit où en est sa tâche : l'API des pastilles et le calendrier ;
- (2026-10-13) la file lit aussi ce que le worker TIENT (`unacked`) : la tâche en cours non
  déclarée au gouverneur (la campagne re-livrée de l'OCR #1485), sans compter un orphelin ni une
  tâche déclarée deux fois ; un message différé attend son heure ; et l'ASSISTANT voit la même
  place que la pastille (`get_<app>_status`, `get_item_detail`).
"""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from wama.common.models import RunOutcome, ScheduledAction as SA
from wama.common.services import global_queue as Q
from wama.common.services import scheduled_actions as S

PARIS = ZoneInfo('Europe/Paris')


def _at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=PARIS)


class _FakeRedis:
    def __init__(self, lists):
        self.lists = lists

    def lrange(self, key, start, end):
        return [json.dumps({'headers': {'id': t, 'task': n}}) for t, n in self.lists.get(key, [])]


class BrokerOrderTest(SimpleTestCase):

    def test_the_first_priority_list_is_consumed_first_and_oldest_first(self):
        # Kombu pousse à GAUCHE et consomme à DROITE : le plus ancien est le dernier de la liste.
        client = _FakeRedis({
            'gpu': [('p0-new', 'a'), ('p0-old', 'a')],
            'gpu:6': [('p6-only', 'b')],
        })
        order = [m['task_id'] for m in Q.broker_messages('gpu', client=client)]
        self.assertEqual(order, ['p0-old', 'p0-new', 'p6-only'])

    def test_an_unreachable_broker_is_not_an_empty_queue_invented(self):
        class Broken:
            def lrange(self, *a):
                raise ConnectionError('down')
        self.assertEqual(Q.broker_messages('gpu', client=Broken()), [])


class SnapshotTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        from wama.describer.models import Description
        cls.owner = User.objects.create_user('queue_owner', password='x')
        cls.other = User.objects.create_user('queue_other', password='x')
        # Durée typique MESURÉE du modèle : 10 min (médiane de trois réussites).
        for seconds in (500, 600, 700):
            Description.objects.create(user=cls.other, filename='done.jpg', status='SUCCESS',
                                       processing_seconds=seconds)
        cls.running = Description.objects.create(user=cls.other, filename='run.jpg',
                                                 status='RUNNING', task_id='t-run')
        cls.mine = Description.objects.create(user=cls.owner, filename='mine.jpg',
                                              status='RUNNING', task_id='t-mine')
        cls.theirs = Description.objects.create(user=cls.other, filename='secret.jpg',
                                                status='RUNNING', task_id='t-theirs')

    def setUp(self):
        cache.clear()

    def _snapshot(self, now):
        cache.set(f'describer_progress_{self.running.pk}', 50)
        running = [{'app': 'describer', 'item': self.running.pk,
                    'ts': (now - timedelta(minutes=5)).timestamp()}]
        queued = [{'task_id': 't-theirs', 'task_name': 'x'}, {'task_id': 't-mine', 'task_name': 'x'}]
        return Q.snapshot(now, running=running, queued=queued)

    def test_times_add_up_measured_durations_on_the_serial_queue(self):
        now = _at(1, 10)
        entries = self._snapshot(now)
        self.assertEqual([e.state for e in entries], ['running', 'queued', 'queued'])
        # En cours : 5 min pour 50 % → fin dans 5 min (débit observé).
        self.assertEqual(entries[0].expected_end, now + timedelta(minutes=5))
        # Puis 10 min (médiane mesurée) chacune, l'une APRÈS l'autre.
        self.assertEqual(entries[1].expected_start, now + timedelta(minutes=5))
        self.assertEqual(entries[2].expected_start, now + timedelta(minutes=15))
        self.assertEqual(entries[2].expected_end, now + timedelta(minutes=25))
        self.assertEqual(entries[2].duration_source, 'measured')
        self.assertEqual(Q.free_at(now, entries), now + timedelta(minutes=25))

    def test_a_user_sees_his_place_but_never_the_title_of_others(self):
        entries = self._snapshot(_at(1, 10))
        own = Q.for_user(self.owner, entries=entries)
        self.assertEqual(len(own), 1)
        self.assertEqual((own[0]['itemId'], own[0]['ahead']), (self.mine.pk, 2))
        foreign = entries[1].as_dict(self.owner)
        self.assertIsNone(foreign['itemId'])
        self.assertNotIn('secret', foreign['title'])

    def test_the_calendar_places_a_waiting_item_at_its_expected_start(self):
        from wama.common.services import calendar as cal
        now = _at(1, 10)
        entries = self._snapshot(now)
        with mock.patch.object(Q, 'snapshot', return_value=entries):
            events = cal.events_for(self.owner, _at(1, 0), _at(2, 0))
        mine = next(e for e in events if e.key == f'describer:Description:{self.mine.pk}')
        self.assertEqual((mine.start, mine.nature), (now + timedelta(minutes=15), cal.NATURE_PREDICTED))
        self.assertEqual(mine.extra['queuePosition'], 2)
        blocks = [e for e in events if e.extra.get('kind') == 'queue']
        self.assertEqual(len(blocks), 2, 'les deux traitements de l’autre, anonymes')
        self.assertTrue(all('secret' not in e.title and 'run.jpg' not in e.title for e in blocks))

    def test_the_active_endpoint_tells_where_my_task_is(self):
        entries = self._snapshot(timezone.now())
        self.client.force_login(self.owner)
        with mock.patch.object(Q, 'snapshot', return_value=entries):
            res = self.client.get(reverse('common:schedule_active')).json()
        self.assertEqual([e['itemId'] for e in res['queue']], [self.mine.pk])
        self.assertEqual(res['queueLength'], 3)

    def test_test_accounts_do_not_shape_the_typical_duration(self):
        from wama.common.services.nightly_tests import TEST_USERNAME
        from wama.describer.models import Description
        robot = User.objects.get_or_create(username=TEST_USERNAME)[0]
        for _ in range(10):                               # 10 témoins éclair, sous le compte de test
            Description.objects.create(user=robot, filename='t.jpg', status='SUCCESS',
                                       processing_seconds=1)
        seconds, source = Q.typical_seconds(Description)
        self.assertEqual((seconds, source), (600.0, 'measured'),
                         'la médiane doit rester celle des trois réussites réelles (10 min)')

    def test_the_nightly_campaign_never_waits_in_the_gpu_queue(self):
        """It ORCHESTRATES gestures whose tasks go to `gpu` (solo): queued there, it served them
        only after itself (2026-10-13). Its own queue is `nightly`, and its window is the
        calendar's (`reserved_windows`), not an entry of this queue."""
        from django.conf import settings
        self.assertEqual('nightly', settings.CELERY_TASK_ROUTES['common.run_nightly_tests']['queue'])
        for name in ('nightly-functional-tests', 'nightly-weekly-tests'):
            entry = settings.CELERY_BEAT_SCHEDULE.get(name)
            if entry:
                self.assertEqual('nightly', entry['options']['queue'], name)


class AutoPlacementTest(SimpleTestCase):

    def setUp(self):
        cache.clear()

    def _declared(self):
        return mock.patch.object(S, 'quiet_hours', return_value=S._declared_quiet_hours())

    def test_a_short_task_waits_for_the_card_to_be_free(self):
        now, free = _at(1, 14), _at(1, 14, 40)
        with self._declared():
            self.assertEqual(S.place('auto', None, now, seconds=600, queue_free=free), (free, None))

    def test_a_long_task_goes_to_quiet_hours(self):
        with self._declared():
            run_at, _ = S.place('auto', None, _at(1, 14), seconds=2 * 3600, queue_free=_at(1, 14))
        self.assertEqual(run_at, _at(1, 22))

    def test_no_task_overflows_onto_a_reserved_window(self):
        # 03:40 + 1 h déborderait sur la cohérence de 04:15 : repoussé après TOUTES les plages.
        run_at, _ = S.place('asap', None, _at(1, 3, 40), seconds=3600)
        self.assertIsNone(S.overlapping_window(run_at, run_at + timedelta(hours=1)))
        # After the LAST window of that night, read from the calendar — not a fixed hour: the
        # windows follow their measures (the daily one ended at 07:00 sharp on 2026-10-13).
        from wama.common.services.calendar import reserved_windows
        night = [w for w in reserved_windows(_at(1, 0), _at(1, 12)) if w.start >= _at(1, 4)]
        self.assertTrue(night, 'no reserved window that night: nothing measured')
        self.assertGreaterEqual(run_at, max(w.end for w in night))

    def test_a_manual_time_whose_duration_overflows_is_refused(self):
        _run_at, conflict = S.place('manual', _at(1, 4, 0), _at(1, 0), seconds=3600)
        self.assertIsNotNone(conflict, '04:00 + 1 h touche la plage de 04:15')

    def test_hours_label_reads_contiguous_ranges_across_midnight(self):
        self.assertEqual(S.hours_label({22, 23, 0, 1}), '22 h – 02 h')
        self.assertEqual(S.hours_label({5, 6, 9}), '05 h – 07 h, 09 h – 10 h')


class QuietHoursTest(TestCase):

    def test_quiet_hours_are_measured_on_real_users_only(self):
        from wama.common.services.nightly_tests import TEST_USERNAME
        real = User.objects.create_user('quiet_real', password='x')
        robot = User.objects.get_or_create(username=TEST_USERNAME)[0]
        rows = []
        for hour in range(9, 18):                       # journée chargée
            rows += [RunOutcome(app='describer', object_type='D', object_id=1, user=real,
                                signal='telecharge') for _ in range(15)]
        rows += [RunOutcome(app='describer', object_type='D', object_id=1, user=robot,
                            signal='produit') for _ in range(200)]   # la nuit des tests
        RunOutcome.objects.bulk_create(rows)
        # Répartit les lignes réelles de 9 h à 17 h, et celles du robot à 3 h (heure locale).
        base = timezone.localtime().replace(minute=5, second=0, microsecond=0)
        ids = list(RunOutcome.objects.filter(user=real).values_list('pk', flat=True))
        for index, pk in enumerate(ids):
            RunOutcome.objects.filter(pk=pk).update(
                occurred_at=base.replace(hour=9 + index // 15) - timedelta(days=1))
        RunOutcome.objects.filter(user=robot).update(occurred_at=base.replace(hour=3) - timedelta(days=1))
        hours, source = S.quiet_hours(refresh=True)
        self.assertEqual(source, 'measured')
        self.assertIn(3, hours, 'la nuit des comptes de TEST ne compte pas comme une activité')
        self.assertNotIn(12, hours)
        self.assertIn(21, hours)

    def test_deposits_of_real_users_count_as_activity(self):
        from wama.describer.models import Description
        real = User.objects.create_user('quiet_depositor', password='x')
        Description.objects.bulk_create(
            [Description(user=real, filename=f'{i}.jpg') for i in range(120)])
        afternoon = timezone.localtime().replace(hour=14, minute=10) - timedelta(days=1)
        Description.objects.filter(user=real).update(created_at=afternoon)
        hours, source = S.quiet_hours(refresh=True)
        self.assertEqual(source, 'measured')
        self.assertNotIn(14, hours, 'l’heure des dépôts n’est pas creuse')

    def test_too_little_activity_falls_back_to_declared_hours(self):
        with mock.patch.object(S, 'QUIET_MIN_SAMPLES', 10 ** 9):
            hours, source = S.quiet_hours(refresh=True)
        self.assertEqual(source, 'declared')
        self.assertIn(23, hours)


# ── Ce que le worker TIENT (2026-10-13) ──────────────────────────────────────────────────────

# Une tâche SYSTÈME de la file `gpu` hors squelette, donc jamais déclarée au gouverneur — le cas
# réel. (Celle de l'OCR #1485, la campagne nocturne, n'est plus routée sur `gpu` : R122.)
SYSTEM_TASK = 'model_manager.assess_proposed'
SYSTEM_TITLE = 'Évaluation de modèles'


def _held(task_id, since, task_name='x', eta=None):
    return {'task_id': task_id, 'task_name': task_name, 'since': since, 'eta': eta}


class _FakeUnacked:
    """La table `unacked` de kombu : `tag → json([message, exchange, routing_key])`, et l'index
    `tag → instant de délivrance`."""

    def __init__(self, rows):
        self.table = {tag: json.dumps([{'headers': {'id': tid, 'task': name, 'eta': eta}},
                                       '', routing])
                      for tag, (tid, name, routing, eta, _ts) in rows.items()}
        self.index = [(tag, ts) for tag, (_t, _n, _r, _e, ts) in rows.items()]

    def hgetall(self, key):
        return self.table if key == 'unacked' else {}

    def zrange(self, key, start, end, withscores=False):
        return self.index if key == 'unacked_index' else []


class HeldMessagesReadTest(SimpleTestCase):

    def test_only_the_messages_of_the_queue_are_read_oldest_first_with_their_eta(self):
        client = _FakeUnacked({
            'b': ('t-new', 'n', 'gpu', None, 2000.0),
            'a': ('t-old', SYSTEM_TASK, 'gpu', None, 1000.0),
            'c': ('t-default', 'n', 'default', None, 500.0),
            'd': ('t-later', 'n', 'gpu', '2026-10-13T14:58:24.225009+00:00', 3000.0),
        })
        held = Q.held_messages('gpu', client=client)
        self.assertEqual([m['task_id'] for m in held], ['t-old', 't-new', 't-later'])
        self.assertEqual(held[0]['since'], datetime.fromtimestamp(1000.0, tz=ZoneInfo('UTC')))
        self.assertEqual(held[2]['eta'], datetime(2026, 10, 13, 14, 58, 24, 225009,
                                                  tzinfo=ZoneInfo('UTC')))

    def test_an_unreadable_table_is_not_an_empty_worker_invented(self):
        class Broken:
            def hgetall(self, key):
                raise ConnectionError('down')
        self.assertEqual(Q.held_messages('gpu', client=Broken()), [])


class HeldSnapshotTest(TestCase):
    """Le cas de l'OCR #1485 : une tâche RE-LIVRÉE occupait le worker GPU sans être déclarée au
    gouverneur ; la pastille disait « 3 tâches avant » et une heure fausse."""

    @classmethod
    def setUpTestData(cls):
        from wama.describer.models import Description
        cls.owner = User.objects.create_user('held_owner', password='x')
        cls.other = User.objects.create_user('held_other', password='x')
        for seconds in (500, 600, 700):                  # durée typique mesurée : 10 min
            Description.objects.create(user=cls.other, filename='done.jpg', status='SUCCESS',
                                       processing_seconds=seconds)
        cls.running = Description.objects.create(user=cls.other, filename='run.jpg',
                                                 status='RUNNING', task_id='h-run')
        cls.mine = Description.objects.create(user=cls.owner, filename='mine.jpg',
                                              status='RUNNING', task_id='h-mine')
        cls.theirs = Description.objects.create(user=cls.other, filename='secret.jpg',
                                                status='RUNNING', task_id='h-theirs')

    def setUp(self):
        cache.clear()
        self.now = _at(1, 15)

    def _running_row(self, minutes_ago=5):
        cache.set(f'describer_progress_{self.running.pk}', 50)
        return {'app': 'describer', 'item': self.running.pk,
                'ts': (self.now - timedelta(minutes=minutes_ago)).timestamp()}

    def test_an_undeclared_task_held_by_the_worker_is_running_and_named(self):
        entries = Q.snapshot(self.now, running=[], ready_at=None,
                             queued=[{'task_id': 'h-mine', 'task_name': 'x'}],
                             held=[_held('sys', self.now - timedelta(hours=4), SYSTEM_TASK)])
        self.assertEqual([e.state for e in entries], ['running', 'queued'])
        place = Q.place_of(self.mine, self.owner, entries)
        self.assertEqual(place['ahead'], 1)
        self.assertEqual((place['before'][0]['title'], place['before'][0]['system']),
                         (SYSTEM_TITLE, True))
        self.assertEqual(place['before'][0]['startedAt'],
                         (self.now - timedelta(hours=4)).isoformat())
        self.assertGreater(datetime.fromisoformat(place['expectedStart']), self.now)

    def test_a_message_delivered_before_the_worker_started_is_an_orphan_and_occupies_nothing(self):
        """Un message resté dans `unacked` après le `kill` de son worker (la campagne révoquée de
        l'OCR #1485) : il n'attend que l'échéance de visibilité. Le compter ferait attendre
        derrière une morte."""
        entries = Q.snapshot(self.now, running=[], ready_at=self.now - timedelta(hours=1),
                             queued=[{'task_id': 'h-mine', 'task_name': 'x'}],
                             held=[_held('sys', self.now - timedelta(hours=4), SYSTEM_TASK)])
        self.assertEqual([e.state for e in entries], ['queued'])
        self.assertEqual(entries[0].expected_start, self.now)

    def test_a_task_declared_to_the_governor_is_not_counted_twice(self):
        entries = Q.snapshot(self.now, running=[self._running_row()], queued=[], ready_at=None,
                             held=[_held('h-run', self.now - timedelta(minutes=5))])
        self.assertEqual([(e.state, e.item_id) for e in entries], [('running', self.running.pk)])

    def test_a_declared_task_is_the_one_running_even_beside_an_older_held_message(self):
        """Pool `solo` : une seule à la fois. La déclarée est en cours ; l'autre message tenu,
        sans preuve d'orphelinat (démarrage inconnu), n'est PAS une seconde tâche en cours."""
        entries = Q.snapshot(self.now, running=[self._running_row()], queued=[], ready_at=None,
                             held=[_held('sys', self.now - timedelta(hours=4), SYSTEM_TASK),
                                   _held('h-run', self.now - timedelta(minutes=5))])
        self.assertEqual([e.state for e in entries], ['running'])

    def test_of_several_undeclared_held_messages_only_the_latest_runs(self):
        entries = Q.snapshot(self.now, running=[], queued=[], ready_at=None, held=[
            _held('old', self.now - timedelta(hours=5), 'x'),
            _held('sys', self.now - timedelta(minutes=10), SYSTEM_TASK)])
        self.assertEqual([(e.state, e.title) for e in entries], [('running', SYSTEM_TITLE)])

    def test_the_nightly_campaign_held_by_the_gpu_worker_is_not_named(self):
        """R122 : la campagne a quitté la file `gpu`, son titre est sorti de cette file avec elle.
        Un message d'avant le changement, s'il en restait, n'est qu'une tâche système."""
        entries = Q.snapshot(self.now, running=[], queued=[], ready_at=None,
                             held=[_held('n', self.now - timedelta(hours=1),
                                         'common.run_nightly_tests')])
        self.assertEqual([(e.state, e.title) for e in entries], [('running', 'Tâche système')])

    def test_a_deferred_message_waits_for_its_hour(self):
        """Le report « faute de VRAM » du squelette (`task.retry(countdown=…)`) : au repos, le
        worker TIENT le message jusqu'à son échéance — il n'est dans aucune liste (mesuré)."""
        eta = self.now + timedelta(minutes=20)
        entries = Q.snapshot(self.now, running=[], queued=[], ready_at=None,
                             held=[_held('h-mine', self.now - timedelta(minutes=1), eta=eta)])
        self.assertEqual([(e.state, e.expected_start) for e in entries], [('queued', eta)])
        place = Q.place_of(self.mine, self.owner, entries)
        self.assertEqual(place['deferredUntil'], eta.isoformat())

    def test_a_listed_message_with_a_future_eta_waits_for_its_hour_too(self):
        """Envoyé pendant que le worker travaillait : occupé, il ne va rien chercher, le message
        à échéance reste dans la LISTE (mesuré) — il n'en part pas plus tôt pour autant."""
        eta = self.now + timedelta(minutes=30)
        entries = Q.snapshot(self.now, running=[], held=[], ready_at=None,
                             queued=[{'task_id': 'h-mine', 'task_name': 'x', 'eta': eta}])
        self.assertEqual(entries[0].expected_start, eta)

    def test_a_deferred_message_whose_hour_has_come_passes_before_the_list(self):
        due = self.now + timedelta(minutes=2)              # avant la fin de la tâche en cours
        entries = Q.snapshot(self.now, running=[self._running_row()], ready_at=None,
                             queued=[{'task_id': 'h-theirs', 'task_name': 'x'}],
                             held=[_held('h-mine', self.now - timedelta(minutes=1), eta=due)])
        self.assertEqual([e.item_id for e in entries],
                         [self.running.pk, self.mine.pk, self.theirs.pk])
        self.assertEqual(entries[1].expected_start, self.now + timedelta(minutes=5))

    def test_what_runs_before_me_never_tells_the_title_of_another_user(self):
        entries = Q.snapshot(self.now, running=[self._running_row()], held=[], ready_at=None,
                             queued=[{'task_id': 'h-theirs', 'task_name': 'x'},
                                     {'task_id': 'h-mine', 'task_name': 'x'}])
        before = Q.place_of(self.mine, self.owner, entries)['before']
        self.assertEqual(len(before), 2)
        self.assertTrue(all(row['itemId'] is None and not row['system'] for row in before))
        self.assertFalse(any('secret' in row['title'] or 'run.jpg' in row['title'] for row in before))

    def test_an_item_out_of_the_queue_has_no_place(self):
        entries = Q.snapshot(self.now, running=[], queued=[], held=[], ready_at=None)
        self.assertIsNone(Q.place_of(self.mine, self.owner, entries))


class ConsumerReadyTest(TestCase):

    def setUp(self):
        cache.clear()

    def test_a_starting_worker_notes_when_its_queues_are_served(self):
        from wama.celery import _wama_note_consumer_ready
        sender = SimpleNamespace(app=SimpleNamespace(amqp=SimpleNamespace(
            queues=SimpleNamespace(consume_from={'gpu': object()}))))
        self.assertIsNone(Q.consumer_ready_at('gpu'))
        _wama_note_consumer_ready(sender=sender)
        self.assertIsNotNone(Q.consumer_ready_at('gpu'))
        self.assertIsNone(Q.consumer_ready_at('default'), 'seules ses files')

    def test_the_snapshot_reads_the_noted_start_to_drop_an_orphan(self):
        now = _at(1, 15)
        orphan = [_held('sys', now - timedelta(hours=4), SYSTEM_TASK)]
        with mock.patch.object(Q, 'held_messages', return_value=orphan), \
                mock.patch.object(Q, 'broker_messages', return_value=[]):
            self.assertEqual(['running'], [e.state for e in Q.snapshot(now, running=[])],
                             'démarrage inconnu : aucune preuve, le message tenu compte')
            Q.note_consumer_ready(['gpu'], at=now - timedelta(hours=1))
            self.assertEqual([], Q.snapshot(now, running=[]))


class AssistantSeesTheQueueTest(TestCase):
    """L'assistant lit la place que montre la pastille — la question du fil Discord (« les tests
    bloquent-ils le traitement ? ») se répond en lisant, plus en devinant."""

    @classmethod
    def setUpTestData(cls):
        from wama.describer.models import Description
        cls.owner = User.objects.create_user('tool_queue_owner', password='x')
        cls.mine = Description.objects.create(user=cls.owner, filename='mine.jpg',
                                              status='RUNNING', task_id='a-mine')
        cls.done = Description.objects.create(user=cls.owner, filename='done.jpg',
                                              status='SUCCESS', processing_seconds=60)

    def setUp(self):
        cache.clear()
        now = timezone.now()
        self.entries = Q.snapshot(now, running=[], ready_at=None,
                                  queued=[{'task_id': 'a-mine', 'task_name': 'x'}],
                                  held=[_held('sys', now - timedelta(hours=4), SYSTEM_TASK)])

    def test_the_status_tool_tells_where_a_waiting_job_is(self):
        from wama.tool_api import TOOL_REGISTRY
        with mock.patch.object(Q, 'snapshot', return_value=self.entries):
            jobs = {j['id']: j for j in TOOL_REGISTRY['get_describer_status'](self.owner)['jobs']}
        self.assertEqual((jobs[self.mine.pk]['status'], jobs[self.mine.pk]['progress']), ('RUNNING', 0))
        queue = jobs[self.mine.pk]['queue']
        self.assertEqual((queue['state'], queue['ahead']), ('queued', 1))
        self.assertEqual(queue['before'][0]['title'], SYSTEM_TITLE)
        self.assertNotIn('queue', jobs[self.done.pk])

    def test_the_detail_tool_tells_it_too(self):
        from wama.tool_api import get_item_detail
        with mock.patch.object(Q, 'snapshot', return_value=self.entries):
            result = get_item_detail(self.owner, 'describer', self.mine.pk)
        self.assertEqual(result['queue']['before'][0]['title'], SYSTEM_TITLE)

    def test_a_finished_item_does_not_read_the_queue(self):
        from wama.tool_api import get_item_detail
        with mock.patch.object(Q, 'snapshot') as read:
            result = get_item_detail(self.owner, 'describer', self.done.pk)
        read.assert_not_called()
        self.assertNotIn('queue', result)

    def test_an_unreadable_queue_never_breaks_the_answer(self):
        from wama.tool_api import get_item_detail
        with mock.patch.object(Q, 'snapshot', side_effect=ConnectionError('down')):
            result = get_item_detail(self.owner, 'describer', self.mine.pk)
        self.assertNotIn('queue', result)
        self.assertNotIn('error', result)

    def test_the_tool_description_tells_the_model_what_queue_means(self):
        from wama.tool_api import tool_descriptions
        self.assertIn('file GPU', tool_descriptions()['get_describer_status']['description'])
