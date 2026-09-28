"""
Actions PROGRAMMÉES — `common/services/scheduled_actions.py` (calendrier, étape 3).
Doc : `WAMA_APP_GENERATION_ROUTE.md §10.6` point 13, `WAMA_MEMORY.md §9bis.1`.

Ce que ces gardes tiennent :
- le PLACEMENT respecte les plages réservées aux tests nocturnes (décision de Fabien) : le manuel
  y est REFUSÉ avec la fin de plage proposée, l'automatique en sort de lui-même ;
- le DISTRIBUTEUR passe par `tool_api.execute_tool` (la porte unique), une seule fois, et ne
  relance jamais un élément lancé à la main entre-temps ;
- le ▶ annule la programmation SANS confirmation (décision de Fabien), par le middleware ;
- les routes, la file (`queue_dnd_attrs`), le calendrier et l'abonnement `.ics` à jeton.

⚠ Aucune tâche n'est réellement lancée : `execute_tool` est remplacé par un double.
"""
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.models import Notification, RunOutcome, ScheduledAction as SA
from wama.common.services import scheduled_actions as S

PARIS = ZoneInfo('Europe/Paris')
TOOL = 'start_describer'


def _at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=PARIS)


class PlacementTest(SimpleTestCase):

    def test_a_manual_time_inside_a_reserved_window_is_refused_with_its_end(self):
        run_at, conflict = S.place(SA.PLACEMENT_MANUAL, _at(1, 5, 0), _at(1, 0, 0))
        self.assertIsNotNone(conflict, '05:00 tombe dans la plage des tests fonctionnels')
        self.assertIn('Tests nocturnes', conflict.title)
        self.assertLessEqual(conflict.start, _at(1, 5, 0))
        self.assertGreater(conflict.end, _at(1, 5, 0))

    def test_a_manual_time_outside_reserved_windows_is_kept(self):
        run_at, conflict = S.place(SA.PLACEMENT_MANUAL, _at(1, 14, 30), _at(1, 9, 0))
        self.assertEqual((run_at, conflict), (_at(1, 14, 30), None))

    def test_a_past_manual_time_is_refused(self):
        with self.assertRaises(S.ScheduleError):
            S.place(SA.PLACEMENT_MANUAL, _at(1, 8, 0), _at(1, 9, 0))

    def test_as_soon_as_possible_leaves_the_reserved_window(self):
        now = _at(1, 5, 0)
        window = S.reserved_window_at(now)
        run_at, conflict = S.place(SA.PLACEMENT_ASAP, None, now)
        self.assertIsNone(conflict)
        self.assertEqual(run_at, window.end)
        self.assertIsNone(S.reserved_window_at(run_at))

    def test_as_soon_as_possible_in_the_afternoon_is_now(self):
        now = _at(1, 15, 0)
        self.assertEqual(S.place(SA.PLACEMENT_ASAP, None, now), (now, None))

    def test_off_peak_from_the_afternoon_is_tonight(self):
        run_at, _ = S.place(SA.PLACEMENT_OFF_PEAK, None, _at(1, 15, 0))
        self.assertEqual(run_at, _at(1, 22, 0))

    def test_off_peak_never_lands_in_a_reserved_window(self):
        # À 05:00, les heures creuses durent encore, mais la plage des tests court jusqu'à ~07:30 :
        # en sortir fait quitter les heures creuses — la prochaine tranche est le soir même.
        run_at, _ = S.place(SA.PLACEMENT_OFF_PEAK, None, _at(1, 5, 0))
        self.assertEqual(run_at, _at(1, 22, 0))
        self.assertIsNone(S.reserved_window_at(run_at))


class ScheduleAndDispatchTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('sched_owner', password='x')
        cls.other = User.objects.create_user('sched_other', password='x')

    def _item(self, user=None, **fields):
        from wama.describer.models import Description
        return Description.objects.create(user=user or self.user, filename='x.jpg', **fields)

    def _schedule(self, item, run_at=None):
        with mock.patch('wama.accounts.permissions.tool_accessible', return_value=True):
            result = S.schedule_items(self.user, TOOL, [item.pk], SA.PLACEMENT_MANUAL,
                                      run_at or _at(2, 14), now=_at(1, 9))
        return result['actions'][0]

    def test_scheduling_targets_the_item_through_its_start_tool(self):
        action = self._schedule(self._item())
        self.assertEqual((action.app, action.object_type, action.state),
                         ('describer', 'Description', SA.STATE_SCHEDULED))
        self.assertEqual(action.run_at, _at(2, 14))

    def test_someone_elses_item_cannot_be_scheduled(self):
        foreign = self._item(user=self.other)
        with mock.patch('wama.accounts.permissions.tool_accessible', return_value=True), \
                self.assertRaises(S.ScheduleError):
            S.schedule_items(self.user, TOOL, [foreign.pk], SA.PLACEMENT_MANUAL, _at(2, 14),
                             now=_at(1, 9))

    def test_rescheduling_an_item_replaces_its_previous_schedule(self):
        item = self._item()
        first = self._schedule(item, _at(2, 14))
        self._schedule(item, _at(3, 14))
        first.refresh_from_db()
        self.assertEqual(first.state, SA.STATE_CANCELLED)
        self.assertEqual(SA.objects.filter(object_id=str(item.pk), state=SA.STATE_SCHEDULED).count(), 1)

    def test_only_a_start_tool_can_be_scheduled(self):
        with self.assertRaises(S.ScheduleError):
            S.target_of('get_describer_status')

    def test_a_due_action_is_launched_once_through_the_single_door(self):
        item = self._item()
        action = self._schedule(item)
        with mock.patch('wama.tool_api.execute_tool', return_value={'status': 'started'}) as run:
            first = S.dispatch_due(now=_at(2, 14, 1))
            second = S.dispatch_due(now=_at(2, 14, 2))
        self.assertEqual(first['dispatched'], 1)
        self.assertEqual(second, {'dispatched': 0, 'skipped': 0, 'failed': 0})
        run.assert_called_once()
        tool, args, user = run.call_args.args
        self.assertEqual((tool, args, user), (TOOL, {'description_id': item.pk}, self.user))
        action.refresh_from_db()
        self.assertEqual(action.state, SA.STATE_DISPATCHED)

    def test_an_action_not_yet_due_is_left_alone(self):
        self._schedule(self._item())
        with mock.patch('wama.tool_api.execute_tool') as run:
            self.assertEqual(S.dispatch_due(now=_at(2, 13, 59))['dispatched'], 0)
        run.assert_not_called()

    def test_an_item_launched_by_hand_meanwhile_is_not_relaunched(self):
        item = self._item()
        action = self._schedule(item)
        RunOutcome.objects.create(app='describer', object_type='Description', object_id=item.pk,
                                  user=self.user, signal='produit')
        with mock.patch('wama.tool_api.execute_tool') as run:
            summary = S.dispatch_due(now=_at(2, 14, 1))
        run.assert_not_called()
        self.assertEqual(summary['skipped'], 1)
        action.refresh_from_db()
        self.assertEqual(action.state, SA.STATE_SKIPPED)

    def test_a_failed_launch_is_recorded_and_notified(self):
        action = self._schedule(self._item())
        with mock.patch('wama.tool_api.execute_tool', return_value={'error': 'forbidden',
                                                                      'detail': 'Accès refusé'}):
            summary = S.dispatch_due(now=_at(2, 14, 1))
        self.assertEqual(summary['failed'], 1)
        action.refresh_from_db()
        self.assertEqual(action.state, SA.STATE_FAILED)
        self.assertTrue(Notification.objects.filter(recipient=self.user,
                                                    kind='schedule_failed').exists())

    def test_a_recurring_action_schedules_its_next_occurrence(self):
        action = self._schedule(self._item())
        SA.objects.filter(pk=action.pk).update(rrule='FREQ=WEEKLY')
        with mock.patch('wama.tool_api.execute_tool', return_value={'status': 'started'}):
            S.dispatch_due(now=_at(2, 14, 1))
        following = SA.objects.filter(object_id=action.object_id, state=SA.STATE_SCHEDULED).get()
        self.assertEqual(following.run_at, _at(9, 14))

    def test_the_start_button_cancels_the_schedule_without_asking(self):
        from wama.common.middleware import RunOutcomeCaptureMiddleware
        item = self._item()
        action = self._schedule(item)
        request = SimpleNamespace(
            method='POST', user=self.user,
            resolver_match=SimpleNamespace(url_name='start', app_name='describer',
                                           namespace='describer', kwargs={'pk': item.pk}))
        RunOutcomeCaptureMiddleware(lambda r: None)._capter(request, SimpleNamespace(status_code=200))
        action.refresh_from_db()
        self.assertEqual(action.state, SA.STATE_CANCELLED)


class ScheduleRoutesTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('sched_routes', password='x')
        cls.other = User.objects.create_user('sched_routes_other', password='x')

    def setUp(self):
        from wama.describer.models import Description
        self.item = Description.objects.create(user=self.user, filename='y.jpg')
        self.client.force_login(self.user)
        patcher = mock.patch('wama.accounts.permissions.tool_accessible', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _create(self, **payload):
        body = {'tool': TOOL, 'ids': [self.item.pk], 'when': 'manual'}
        body.update(payload)
        return self.client.post(reverse('common:schedule_create'), body,
                                content_type='application/json').json()

    def test_create_list_and_cancel(self):
        res = self._create(at='2030-01-10T14:00')
        self.assertTrue(res['ok'], res)
        listed = self.client.get(reverse('common:schedule_active')).json()['actions']
        self.assertEqual([a['objectId'] for a in listed], [str(self.item.pk)])
        action_id = res['actions'][0]['id']
        self.assertTrue(self.client.post(reverse('common:schedule_cancel', args=[action_id])).json()['ok'])
        self.assertEqual(self.client.get(reverse('common:schedule_active')).json()['actions'], [])

    def test_a_reserved_time_answers_a_conflict_and_creates_nothing(self):
        res = self._create(at='2030-01-10T05:00')
        self.assertFalse(res['ok'])
        self.assertIn('suggested', res['conflict'])
        self.assertFalse(SA.objects.filter(user=self.user).exists())

    def test_another_user_cannot_cancel_it(self):
        action_id = self._create(at='2030-01-10T14:00')['actions'][0]['id']
        self.client.force_login(self.other)
        self.assertFalse(self.client.post(reverse('common:schedule_cancel', args=[action_id])).json()['ok'])
        self.assertEqual(SA.objects.get(pk=action_id).state, SA.STATE_SCHEDULED)

    def test_a_schedule_is_a_declared_event_of_the_calendar(self):
        self._create(at='2030-01-10T14:00')
        events = self.client.get(reverse('common:calendar_events'),
                                 {'start': '2030-01-06T00:00:00+01:00',
                                  'end': '2030-01-13T00:00:00+01:00', 'maintenance': '0'}).json()
        declared = [e for e in events if e['extendedProps']['nature'] == 'declared']
        self.assertEqual(len(declared), 1)
        self.assertEqual(declared[0]['extendedProps']['itemId'], self.item.pk)


class QueueAttributesTest(SimpleTestCase):

    def test_each_queue_names_its_own_start_tool(self):
        from wama.common.templatetags.wama_actions import queue_dnd_attrs
        self.assertIn('data-schedule-tool="start_describer"', queue_dnd_attrs('describer'))
        self.assertIn('data-schedule-tool="start_audio_enhancer"', queue_dnd_attrs('enhancer', 'audio'))
        self.assertIn('data-schedule-tool="start_imager"', queue_dnd_attrs('imager', 'video'))
        self.assertNotIn('data-schedule-tool', queue_dnd_attrs('converter_01'),
                         'une jumelle de bac à sable n’a pas d’outil : rien à programmer')


class CalendarFeedTest(TestCase):

    def test_a_subscription_link_works_without_session_and_dies_when_regenerated(self):
        user = User.objects.create_user('feed_owner', password='x')
        self.client.force_login(user)
        first = self.client.post(reverse('common:calendar_feed')).json()['url']
        again = self.client.post(reverse('common:calendar_feed')).json()['url']
        self.assertEqual(first, again, 'le lien est stable tant qu’on ne le régénère pas')
        self.client.logout()
        path = first.split('://', 1)[1].split('/', 1)[1]
        response = self.client.get('/' + path)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/calendar'))
        self.client.force_login(user)
        renewed = self.client.post(reverse('common:calendar_feed'), {'regenerate': '1'}).json()['url']
        self.assertNotEqual(renewed, first)
        self.client.logout()
        self.assertEqual(self.client.get('/' + path).status_code, 404)


class ScheduleSchemaTest(SimpleTestCase):
    """UNE déclaration (`schedule_params`), lue par la fenêtre, l'API et le fichier batch."""

    def test_the_schema_declares_the_model_placements_and_a_datetime(self):
        params = {p.name: p for p in S.schedule_params()}
        self.assertEqual([v for v, _ in params['when'].choices],
                         [v for v, _ in SA.PLACEMENT_CHOICES],
                         'les placements viennent du modèle, ils ne sont pas réécrits')
        self.assertEqual(params['at'].type, 'datetime')
        self.assertEqual(params['at'].show_if, {'field': 'when', 'in': ['manual']})

    def test_reading_follows_the_schema(self):
        self.assertEqual(S.read_schedule({'when': 'off_peak'}), ('off_peak', None))
        placement, moment = S.read_schedule({'at': '2030-01-10 14:00'})
        self.assertEqual(placement, 'manual', 'une date seule vaut un placement manuel')
        self.assertEqual((moment.year, moment.hour, moment.minute), (2030, 14, 0))
        with self.assertRaises(S.ScheduleError):
            S.read_schedule({'when': 'tomorrow'})
        with self.assertRaises(S.ScheduleError):
            S.read_schedule({'at': 'demain matin'})

    def test_the_batch_template_documents_the_schedule_options(self):
        from wama.common.utils.batch_parsers import build_batch_template
        template = build_batch_template(['input'], {'input': 'x.jpg'}, app_label='describer')
        # Les valeurs sont celles du MODÈLE, lues par le schéma — jamais recopiées : l'étape 4 a
        # ajouté `auto` et le gabarit l'a documenté sans qu'on y touche.
        self.assertIn('--when ' + '|'.join(v for v, _ in SA.PLACEMENT_CHOICES), template)
        self.assertIn('--at AAAA-MM-JJTHH:MM', template)


class BatchFileScheduleTest(TestCase):
    """Un fichier batch programme ses lignes par `--when` / `--at` — par la vue RÉELLE de l'app,
    le middleware faisant le lien (aucune ligne dans l'app)."""

    def setUp(self):
        # Rôles lus dans la politique d'accès de l'app — le moyen de `tests_import_contract`.
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        self.user = User.objects.create_user('batch_sched', password='x')
        for role in (DEFAULT_APP_ACCESS.get('describer') or {}).get('roles', []):
            group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
            self.user.groups.add(group)
        self.client.force_login(self.user)
        patcher = mock.patch('wama.accounts.permissions.tool_accessible', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, text):
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload = SimpleUploadedFile('lot.txt', text.encode('utf-8'), content_type='text/plain')
        response = self.client.post(reverse('describer:batch_create'), {'batch_file': upload})
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def test_a_line_with_when_is_scheduled_and_the_others_are_not(self):
        created = self._post('-i https://example.org/a.jpg --when off_peak\n'
                             '-i https://example.org/b.jpg\n')
        first, second = created['description_ids']
        scheduled = SA.objects.filter(user=self.user, state=SA.STATE_SCHEDULED)
        self.assertEqual([a.object_id for a in scheduled], [str(first)])
        self.assertEqual(scheduled[0].placement, 'off_peak')
        self.assertNotIn(str(second), [a.object_id for a in scheduled])

    def test_a_csv_column_schedules_at_a_date(self):
        created = self._post('input,at\nhttps://example.org/c.jpg,2030-01-10T14:00\n')
        action = SA.objects.get(user=self.user, object_id=str(created['description_ids'][0]))
        self.assertEqual(action.placement, 'manual')
        self.assertEqual(action.run_at.astimezone(PARIS).hour, 14)

    def test_a_reserved_time_in_a_line_is_refused_and_notified(self):
        self._post('-i https://example.org/d.jpg --at 2030-01-10T05:00\n')
        self.assertFalse(SA.objects.filter(user=self.user).exists())
        note = Notification.objects.get(recipient=self.user, kind='schedule_batch')
        self.assertIn('réserve ce créneau', note.body)


class ScheduleScriptsTest(SimpleTestCase):
    """Les briques JS touchées parsent sous V8 et `staticfiles/` sert la source."""

    def test_scripts_parse_and_are_served_as_written(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv')
        for name in ('wama-schedule.js', 'wama-card-menu.js', 'wama-calendar.js',
                     'wama-params.js'):
            src = Path(settings.BASE_DIR, 'wama/common/static/common/js', name).read_text(encoding='utf-8')
            served = Path(settings.BASE_DIR, 'staticfiles/common/js', name).read_text(encoding='utf-8')
            with self.subTest(script=name):
                MiniRacer().eval('(function(){' + src + '\n})')
                self.assertEqual(served, src)
