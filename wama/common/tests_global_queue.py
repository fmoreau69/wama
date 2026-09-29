"""
File GLOBALE et placement automatique — calendrier, étape 4 (2026-09-28).
`common/services/global_queue.py`, `scheduled_actions.place` ; doc `ROUTE §10.6` 13.8.

Ce que ces gardes tiennent :
- la file se LIT dans l'ordre réel de consommation du broker (palier 0 d'abord, le plus ancien
  d'abord) et les heures prévues ADDITIONNENT des durées MESURÉES (file GPU sérielle) ;
- la confidentialité : la place des tâches des autres, jamais leur titre ;
- `auto` attend que la carte se libère, envoie une tâche longue en heures creuses MESURÉES
  (comptes de test exclus), et aucune tâche ne DÉBORDE sur une plage réservée — sa durée comprise ;
- l'utilisateur voit où en est sa tâche : l'API des pastilles et le calendrier.
"""
import json
from datetime import datetime, timedelta
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

    def test_a_nightly_campaign_in_the_queue_lasts_its_reserved_window(self):
        from wama.common.services.calendar import window_minutes
        entries = Q.snapshot(_at(1, 10), running=[],
                             queued=[{'task_id': 'n1', 'task_name': 'common.run_nightly_tests'}])
        self.assertEqual(entries[0].expected_end - entries[0].expected_start,
                         timedelta(minutes=window_minutes('nightly-functional-tests')[0]))
        self.assertEqual(entries[0].title, 'Tests nocturnes')


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
        self.assertGreater(run_at, _at(1, 7))

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
