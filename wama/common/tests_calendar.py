"""
Calendrier — `common/services/calendar.py`, doc `WAMA_MEMORY.md §9bis.1`.

Trois familles de gardes :
- la couche OBSERVÉE dérive bien des sources du journal (aucune ligne par app), l'intervalle
  d'exécution vient de la mesure, et rien d'un autre utilisateur n'y entre ;
- la PLAGE RÉSERVÉE des tests nocturnes (décision de Fabien, 2026-09-28) n'est chevauchée par
  aucune autre entrée planifiée — avec sa contre-épreuve ;
- l'export iCalendar et les routes (menu du profil, connexion exigée).
"""
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from celery.schedules import crontab
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from wama.common.models import RunOutcome
from wama.common.services import calendar as cal

PARIS = ZoneInfo('Europe/Paris')


def _week():
    start = datetime(2026, 9, 28, tzinfo=PARIS)
    return start, start + timedelta(days=7)


class ObservedEventsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('cal_owner', password='x')
        cls.other = User.objects.create_user('cal_other', password='x')

    def _description(self, user, created_at, **fields):
        from wama.describer.models import Description
        item = Description.objects.create(user=user, filename='photo.jpg', **fields)
        Description.objects.filter(pk=item.pk).update(created_at=created_at)
        return item

    def test_describer_is_a_calendar_source_without_a_line_in_the_app(self):
        from wama.common.services.journal import sources
        self.assertIn('describer', {s.app for s in sources()},
                      'le calendrier lit les sources du journal, dérivées de detail_registry')

    def test_an_executed_item_spans_its_measured_processing_time(self):
        ended_at = datetime(2026, 9, 29, 10, 0, tzinfo=PARIS)
        item = self._description(self.user, ended_at - timedelta(days=3), processing_seconds=600)
        outcome = RunOutcome.objects.create(app='describer', object_type='Description',
                                            object_id=item.pk, user=self.user, signal='produit')
        RunOutcome.objects.filter(pk=outcome.pk).update(occurred_at=ended_at)

        events = {e.key: e for e in cal.observed_events(self.user, *_week())}
        event = events[f'describer:Description:{item.pk}']
        self.assertEqual(event.end, ended_at)
        self.assertEqual(event.start, ended_at - timedelta(seconds=600))
        self.assertEqual(event.duration_source, 'measured')
        self.assertTrue(event.extra['executed'])
        from wama.common.app_registry import APP_CATALOG
        self.assertEqual(event.color, APP_CATALOG['describer']['color'],
                         "la couleur est l'IDENTITÉ de l'app, jamais une couleur d'état")

    def test_a_never_executed_item_appears_at_its_creation(self):
        created_at = datetime(2026, 9, 30, 14, 0, tzinfo=PARIS)
        item = self._description(self.user, created_at)
        event = {e.key: e for e in cal.observed_events(self.user, *_week())}[
            f'describer:Description:{item.pk}']
        self.assertEqual(event.start, created_at)
        self.assertEqual(event.end, created_at + timedelta(minutes=cal.POINT_MINUTES))
        self.assertFalse(event.extra['executed'])

    def test_an_app_without_catalog_entry_keeps_an_identity_color(self):
        from wama.common.app_registry import category_color
        label, color = cal.app_identity('app_without_entry')
        self.assertEqual(color, category_color('platform'))
        self.assertEqual(label, 'App without entry')

    def test_another_users_items_never_appear(self):
        item = self._description(self.other, datetime(2026, 9, 30, 9, 0, tzinfo=PARIS))
        keys = {e.key for e in cal.observed_events(self.user, *_week())}
        self.assertNotIn(f'describer:Description:{item.pk}', keys)

    def test_an_item_outside_the_window_is_left_out(self):
        item = self._description(self.user, datetime(2026, 8, 1, 9, 0, tzinfo=PARIS))
        keys = {e.key for e in cal.observed_events(self.user, *_week())}
        self.assertNotIn(f'describer:Description:{item.pk}', keys)


class ReservedNightlyWindowTest(TestCase):
    """La plage des tests nocturnes est RÉSERVÉE : rien d'autre de planifié ne doit y entrer."""

    def test_every_declared_window_names_a_real_beat_entry(self):
        beat = set(getattr(settings, 'CELERY_BEAT_SCHEDULE', {}) or {})
        for name in cal.BEAT_WINDOWS:
            if name == 'nightly-functional-tests' and os.environ.get('NIGHTLY_TESTS_ENABLED') == '0':
                continue   # retirée volontairement par l'exploitation
            with self.subTest(entry=name):
                self.assertIn(name, beat, 'déclaration orpheline : aucune entrée beat de ce nom')

    def test_the_nightly_tests_reserve_their_window(self):
        reserved = cal.reserved_windows(*_week())
        self.assertTrue(any(w.extra['beatEntry'] == 'nightly-consistency' for w in reserved))
        if 'nightly-functional-tests' in settings.CELERY_BEAT_SCHEDULE:
            gpu = cal.reserved_windows(*_week(), resource='gpu')
            self.assertEqual(len(gpu), 7, 'une plage GPU réservée par nuit')

    def test_no_scheduled_entry_overlaps_a_reserved_window(self):
        conflicts = cal.reserved_window_conflicts(*_week())
        self.assertEqual(
            [], [(r.title, r.start.isoformat(), o.title, o.start.isoformat()) for r, o in conflicts],
            'une entrée planifiée chevauche la plage des tests nocturnes — déplacer l\'entrée '
            '(ou la campagne) plutôt que de laisser les tests se rallonger')

    def test_counter_proof_an_entry_moved_into_the_window_is_seen(self):
        schedule = dict(settings.CELERY_BEAT_SCHEDULE)
        schedule['backup-db-daily'] = dict(schedule['backup-db-daily'],
                                           schedule=crontab(hour=4, minute=20))
        with override_settings(CELERY_BEAT_SCHEDULE=schedule):
            conflicts = cal.reserved_window_conflicts(*_week())
        self.assertTrue(any(o.extra['beatEntry'] == 'backup-db-daily' for _, o in conflicts),
                        'la garde est aveugle : une sauvegarde à 04:20 devait la rougir')

    def test_interval_entries_are_background_beats_not_appointments(self):
        keys = {w.extra['beatEntry'] for w in cal.maintenance_windows(*_week())}
        self.assertNotIn('ollama-residency-refresh', keys)

    def test_occurrences_follow_the_beat_timezone(self):
        windows = [w for w in cal.maintenance_windows(*_week())
                   if w.extra['beatEntry'] == 'nightly-consistency']
        self.assertEqual(len(windows), 7)
        for w in windows:
            local = w.start.astimezone(PARIS)
            self.assertEqual((local.hour, local.minute), (4, 15))


class MeasuredDurationTest(TestCase):

    def _report(self, folder, name, durations, stage='ui'):
        results = [{'scenario_id': f's{i}', 'stage_target': stage, 'duration_s': d}
                   for i, d in enumerate(durations)]
        Path(folder, name).write_text(json.dumps({'results': results}), encoding='utf-8')

    def test_the_longest_recent_run_is_the_measure(self):
        with tempfile.TemporaryDirectory() as folder:
            self._report(folder, 'nightly_20260901_020000.json', [300, 300])       # 10 min
            self._report(folder, 'nightly_20260902_020000.json', [3000, 3000])     # 100 min
            self.assertAlmostEqual(cal.measured_nightly_minutes(None, folder), 100.0)

    def test_a_stage_measure_ignores_mixed_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            self._report(folder, 'nightly_20260901_020000.json', [120], stage='consistency')
            self._report(folder, 'nightly_20260902_020000.json', [6000], stage='ui')
            self.assertAlmostEqual(cal.measured_nightly_minutes('consistency', folder), 2.0)

    def test_no_report_falls_back_to_the_declared_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(cal.measured_nightly_minutes(None, folder))


class IcsExportTest(TestCase):

    def test_text_is_escaped_and_long_lines_are_folded(self):
        start = timezone.now()
        event = cal.CalendarEvent(key='describer:Description:1', title='Réunion, bilan; ' * 10,
                                  start=start, end=start + timedelta(minutes=5),
                                  nature=cal.NATURE_OBSERVED, scope=cal.SCOPE_USER,
                                  app='describer')
        ics = cal.to_ics([event], host='wama.test')
        self.assertIn('BEGIN:VEVENT', ics)
        self.assertIn('UID:describer:Description:1@wama.test', ics)
        self.assertIn('Réunion\\, bilan\\;', ics)
        for line in ics.split('\r\n'):
            self.assertLessEqual(len(line.encode('utf-8')), 75)


class CalendarRoutesTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('cal_viewer', password='x')

    def test_the_page_is_reached_from_the_profile_menu(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('common:calendar'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="%s"' % reverse('common:calendar'))
        self.assertContains(response, 'vendors/fullcalendar-6.1.15/index.global.min.js')

    def test_events_require_a_login(self):
        response = self.client.get(reverse('common:calendar_events'))
        self.assertEqual(response.status_code, 302)

    def test_events_are_served_in_the_fullcalendar_shape(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('common:calendar_events'),
                                   {'start': '2026-09-28T00:00:00+02:00',
                                    'end': '2026-10-05T00:00:00+02:00'})
        self.assertEqual(response.status_code, 200)
        events = response.json()
        self.assertTrue(events, 'la maintenance planifiée au moins')
        self.assertTrue({'id', 'title', 'start', 'end', 'extendedProps'} <= set(events[0]))
        hidden = self.client.get(reverse('common:calendar_events'),
                                 {'start': '2026-09-28T00:00:00+02:00',
                                  'end': '2026-10-05T00:00:00+02:00', 'maintenance': '0'}).json()
        self.assertFalse([e for e in hidden if e['extendedProps']['scope'] == 'instance'])

    def test_ics_export_is_an_attachment(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('common:calendar_ics'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/calendar'))
        self.assertIn('attachment', response['Content-Disposition'])
