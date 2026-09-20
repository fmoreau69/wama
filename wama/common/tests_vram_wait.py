"""Chantier B1 — le squelette ATTEND sans plafond, REFUSE ce qui ne tiendra jamais, LIBÈRE sur
accord explicite, DÉCLARE sa tâche au gouverneur et BORNE sa durée (2026-09-20).

POURQUOI. Trois cas de Fabien (20/09) au lieu de « différer puis échouer » ; et deux faits
mesurés : « une tâche GPU tourne » n'était visible que dans les statuts des tables d'app, et
`--pool=solo` n'honore aucune limite de temps Celery (`concurrency/solo.py:29`).

Aucun GPU, aucun Redis : la sonde et la carte sont simulées, le registre est le faux Redis.
"""
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.services import resource_governor as gov
from wama.common.tests_vram_ledger import _FauxRedis
from wama.common.utils.task_skeleton import _differer_faute_de_vram, run_item_task, TaskContext


class _Retry(Exception):
    pass


def _task(essais=0):
    class _T:
        class request:
            id = 'tache-test'
            retries = essais
            delivery_info = {}

        @staticmethod
        def retry(**kw):
            return _Retry(f"retry {kw}")
    return _T


class _Base(TestCase):

    def setUp(self):
        from wama.synthesizer.models import VoiceSynthesis
        self.user = get_user_model().objects.create_user('b1_owner', password='x')
        self.other = get_user_model().objects.create_user('b1_other', password='x')
        self.model = VoiceSynthesis
        self.item = VoiceSynthesis.objects.create(user=self.user, text_content='bonjour')
        self.redis = _FauxRedis()
        for kw in ({'_redis': mock.Mock(return_value=self.redis)},
                   {'total_vram_gb': mock.Mock(return_value=24.0)}):
            p = mock.patch.multiple(gov, **kw)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch('wama.common.utils.task_skeleton.close_old_connections')
        p.start()
        self.addCleanup(p.stop)

    def _ctx(self):
        return TaskContext('synthesizer', self.model, self.item)

    def _defer(self, needed, free=1.0, essais=0):
        with mock.patch.object(gov, 'effective_free_gb', return_value=free):
            return _differer_faute_de_vram(_task(essais), self._ctx(), self.item, self.model,
                                           self.item.pk, 'synthesizer', needed, 'error_message')

    def _status(self):
        self.item.refresh_from_db()
        return self.item.status


class ThreeCasesTest(_Base):

    def test_what_never_fits_is_refused_at_once_and_said(self):
        self.assertTrue(self._defer(32.5))
        self.assertEqual(self._status(), 'FAILURE')
        self.assertIn('même seul', self.item.error_message)

    def test_what_fits_alone_but_not_now_waits_without_a_ceiling_and_says_who_holds(self):
        gov.reserve_vram('wama.x.Big:1#imager:qwen-image-2', 18.0)
        with self.assertRaises(_Retry) as cm:
            self._defer(20.0, essais=999)
        self.assertIn("'max_retries': None", str(cm.exception))
        self.assertEqual(self._status(), 'AWAITING_RESOURCES')
        self.assertEqual(self.item.error_message, '')

    def test_the_owner_s_grant_asks_the_tenants_and_is_consumed(self):
        gov.grant_release('synthesizer', self.item.pk, user_id=self.user.pk)
        with mock.patch.object(gov, 'obtain_vram', return_value=(True, 22.0)) as obtain:
            self.assertFalse(self._defer(20.0))
        obtain.assert_called_once()
        self.assertEqual(obtain.call_args.args[0], 20.0)
        self.assertIsNone(gov.release_granted('synthesizer', self.item.pk))

    def test_a_stranger_s_grant_is_ignored_and_the_item_waits(self):
        gov.grant_release('synthesizer', self.item.pk, user_id=self.other.pk)
        with mock.patch.object(gov, 'obtain_vram') as obtain:
            with self.assertRaises(_Retry):
                self._defer(20.0)
        obtain.assert_not_called()

    def test_an_admin_s_grant_is_honoured(self):
        admin = get_user_model().objects.create_user('b1_admin', password='x', is_staff=True)
        gov.grant_release('synthesizer', self.item.pk, user_id=admin.pk)
        with mock.patch.object(gov, 'obtain_vram', return_value=(True, 22.0)):
            self.assertFalse(self._defer(20.0))

    def test_when_the_release_does_not_suffice_the_item_waits_with_the_measured_free(self):
        gov.grant_release('synthesizer', self.item.pk, user_id=self.user.pk)
        with mock.patch.object(gov, 'obtain_vram', return_value=(False, 3.0)):
            with self.assertRaises(_Retry):
                self._defer(20.0)
        self.assertEqual(self._status(), 'AWAITING_RESOURCES')


class TaskLineAndTimeGuardTest(_Base):

    def _run(self, glu, limit_s=None):
        with mock.patch.object(gov, 'task_time_limit_s', return_value=limit_s or 1800):
            run_item_task(_task(), app_id='synthesizer', model=self.model,
                          item_id=self.item.pk, process=glu)

    def test_the_running_task_is_declared_to_the_governor_for_the_time_of_the_process(self):
        seen = []

        def glu(item, ctx):
            seen.append([(t['app'], t['item']) for t in gov.running_tasks()])
            return {}

        self._run(glu)
        self.assertEqual(seen, [[('synthesizer', self.item.pk)]])
        self.assertEqual(gov.running_tasks(), [])
        self.assertEqual(self._status(), 'SUCCESS')

    def test_the_line_is_released_even_when_the_process_fails(self):
        def glu(item, ctx):
            raise RuntimeError('boum')

        self._run(glu)
        self.assertEqual(gov.running_tasks(), [])
        self.assertEqual(self._status(), 'FAILURE')

    def test_the_duration_limit_stops_the_process_cleanly_and_says_so(self):
        """`--pool=solo` n'honore aucune limite Celery : la garde du squelette la tient, dans le
        thread principal (ici aussi), et l'échec est relançable et explicite."""
        import signal
        if not hasattr(signal, 'SIGALRM'):
            self.skipTest('SIGALRM absent (Windows)')

        def glu(item, ctx):
            for _ in range(200):
                time.sleep(0.05)
            return {}

        t0 = time.monotonic()
        self._run(glu, limit_s=1)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(self._status(), 'FAILURE')
        self.assertIn('Durée maximale', self.item.error_message)
        self.assertEqual(gov.running_tasks(), [])


class GrantEndpointAndMuteAssistantTest(TestCase):
    """L'accord explicite passe par UN endpoint commun ; pendant une libération, l'assistant
    répond un message d'attente (texte) et la voix rend 503 — jamais un silence."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('b1_web', password='x')
        self.redis = _FauxRedis()
        p = mock.patch.object(gov, '_redis', return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)
        self.client.force_login(self.user)

    def test_the_grant_is_recorded_with_the_user_who_gave_it(self):
        from django.urls import reverse
        r = self.client.post(reverse('model_manager:api_vram_grant'),
                             data='{"app": "imager", "item": 7}',
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(gov.release_granted('imager', 7)['user'], self.user.pk)
        r = self.client.post(reverse('model_manager:api_vram_grant'), data='{"app": ""}',
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_the_grant_needs_a_logged_in_user(self):
        from django.urls import reverse
        self.client.logout()
        r = self.client.post(reverse('model_manager:api_vram_grant'),
                             data='{"app": "imager", "item": 7}',
                             content_type='application/json')
        self.assertIn(r.status_code, (302, 401, 403))
        self.assertIsNone(gov.release_granted('imager', 7))

    def test_the_awaiting_card_carries_the_grant_link_only_when_the_item_is_named(self):
        from django.template.loader import render_to_string
        with_link = render_to_string('common/_card_state.html',
                                     {'status': 'AWAITING_RESOURCES', 'app': 'imager', 'pk': 7})
        self.assertIn('vram-grant', with_link)
        self.assertIn('data-item="7"', with_link)
        without = render_to_string('common/_card_state.html', {'status': 'AWAITING_RESOURCES'})
        self.assertNotIn('vram-grant', without)
        self.assertIn('En attente de ressources', without)

    def test_the_assistant_stays_silent_with_a_waiting_message_during_a_release(self):
        from django.urls import reverse
        gov.request_release(20.0, requester='1')
        with mock.patch('wama.common.services.assistant_engine.conversation_turn') as turn:
            r = self.client.post(reverse('ai_chat'), data='{"message": "bonjour"}',
                                 content_type='application/json')
        turn.assert_not_called()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['busy'])
        self.assertIn('libère la carte', r.json()['response'])
        r = self.client.post(reverse('kokoro_tts'), data='{"text": "bonjour"}',
                             content_type='application/json')
        self.assertEqual(r.status_code, 503)
        self.assertTrue(r.json()['busy'])


class TaskTimeLimitSettingTest(TestCase):

    def test_the_default_is_thirty_minutes_and_the_user_can_raise_it(self):
        from wama.common.utils.user_settings import save_user_app_settings
        u = get_user_model().objects.create_user('b1_limit', password='x')
        self.assertEqual(gov.task_time_limit_s('imager', None), 1800)
        self.assertEqual(gov.task_time_limit_s('imager', u), 1800)
        save_user_app_settings(u, 'common', {gov.USER_SETTING_MAX_TASK_MINUTES: 90})
        self.assertEqual(gov.task_time_limit_s('imager', u), 5400)
        with mock.patch.dict(gov.TASK_MAX_MINUTES, {'composer': 45}):
            self.assertEqual(gov.task_time_limit_s('composer', None), 2700)
            self.assertEqual(gov.task_time_limit_s('composer', u), 5400)
