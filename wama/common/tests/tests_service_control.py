"""Voir, lancer, arrêter, relancer les services uvicorn depuis le model manager (2026-11-10).

La page dépose un ordre dans `logs/`, la surveillance l'exécute (`supervise_one`, gardé par
`tests_tensorflow_service.SupervisionShellTest`) : aucun processus n'est touché ici.
"""
import importlib.util
import json
import os
import re
import tempfile
import time
from pathlib import Path
from unittest import mock, skipUnless

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from wama.common.utils import service_supervision as supervision

BASE = Path(settings.BASE_DIR)
STARTERS = (BASE / 'start_wama_prod.sh', BASE / 'start_wama_dev.sh')
HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None


def _start_list(starter: Path) -> list:
    return re.search(r'^export WAMA_SERVICES_AT_START="([^"]*)"', starter.read_text(encoding='utf-8'),
                     re.M).group(1).split()


class _WithLogs(SimpleTestCase):

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.logs = self.root / 'logs'
        self.logs.mkdir()
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts' / 'wama_services.sh').write_text(
            'x=1\nWAMA_SERVICES="tts_service tensorflow_service"\n', encoding='utf-8')
        override = override_settings(BASE_DIR=self.root)
        override.enable()
        self.addCleanup(override.disable)

    def _watchdog_alive(self):
        (self.logs / 'worker_watchdog.alive').touch()

    def _flags(self):
        return {p.name for p in self.logs.iterdir() if p.name.startswith('service_')}


class WatchdogStateTest(_WithLogs):

    def test_no_sign_of_life_means_absent(self):
        self.assertEqual('absent', supervision.watchdog_state())

    def test_an_old_sign_of_life_means_absent(self):
        self._watchdog_alive()
        old = time.time() - supervision.WATCHDOG_SILENCE_S - 5
        os.utime(self.logs / 'worker_watchdog.alive', (old, old))
        self.assertEqual('absent', supervision.watchdog_state())

    def test_alive_and_paused_are_told_apart(self):
        self._watchdog_alive()
        self.assertEqual('running', supervision.watchdog_state())
        (self.logs / 'worker_watchdog.pause').touch()
        self.assertEqual('paused', supervision.watchdog_state())


class OrdersTest(_WithLogs):

    def test_stopping_drops_a_pending_launch_and_holds_it(self):
        self._watchdog_alive()
        (self.logs / 'service_launch.tts_service').touch()
        accepted, _ = supervision.control_service('tts_service', 'stop')
        self.assertTrue(accepted)
        self.assertEqual({'service_held.tts_service'}, self._flags())

    def test_starting_lifts_the_hold_and_asks_for_a_launch(self):
        self._watchdog_alive()
        (self.logs / 'service_held.tensorflow_service').touch()
        with mock.patch.object(supervision, '_health', return_value=None):
            accepted, _ = supervision.control_service('tensorflow_service', 'start')
        self.assertTrue(accepted)
        self.assertEqual({'service_launch.tensorflow_service'}, self._flags())

    def test_starting_a_service_already_running_does_not_restart_it(self):
        self._watchdog_alive()
        with mock.patch.object(supervision, '_health', return_value='ok'):
            accepted, message = supervision.control_service('tts_service', 'start')
        self.assertTrue(accepted)
        self.assertIn('déjà', message)
        self.assertEqual(set(), self._flags())

    def test_restarting_asks_for_a_launch_even_when_it_runs(self):
        self._watchdog_alive()
        with mock.patch.object(supervision, '_health', return_value='ok'):
            supervision.control_service('tts_service', 'restart')
        self.assertEqual({'service_launch.tts_service'}, self._flags())

    def test_without_a_living_watchdog_no_order_is_left_behind(self):
        accepted, message = supervision.control_service('tts_service', 'stop')
        self.assertFalse(accepted)
        self.assertIn('surveillance', message)
        self.assertEqual(set(), self._flags())

    def test_a_paused_watchdog_takes_no_order(self):
        self._watchdog_alive()
        (self.logs / 'worker_watchdog.pause').touch()
        self.assertFalse(supervision.control_service('tts_service', 'stop')[0])
        self.assertEqual(set(), self._flags())

    def test_an_unknown_service_or_action_is_refused(self):
        self._watchdog_alive()
        self.assertFalse(supervision.control_service('ollama', 'stop')[0])
        self.assertFalse(supervision.control_service('tts_service', 'explode')[0])
        self.assertEqual(set(), self._flags())


class ServiceStateTest(_WithLogs):

    def test_what_the_service_says_of_itself(self):
        cases = ((requests.ConnectionError(), None), (requests.Timeout(), 'busy'))
        for error, expected in cases:
            with mock.patch('requests.get', side_effect=error):
                self.assertEqual(expected, supervision._health('tts_service'))
        answer = mock.Mock(status_code=200, json=mock.Mock(return_value={'status': 'loading'}))
        with mock.patch('requests.get', return_value=answer):
            self.assertEqual('loading', supervision._health('tts_service'))
        answer = mock.Mock(status_code=200, json=mock.Mock(return_value={'detectors': []}))
        with mock.patch('requests.get', return_value=answer):
            self.assertEqual('ok', supervision._health('tts_service'))

    def test_the_state_reads_the_process_then_the_orders_then_the_start_list(self):
        off = {'held': False, 'launch': False, 'wanted': False, 'at_start': False}
        resolve = supervision._resolve_state
        self.assertEqual('on_demand', resolve(None, **off))
        self.assertEqual('down', resolve(None, **{**off, 'at_start': True}))
        self.assertEqual('held', resolve(None, **{**off, 'held': True, 'wanted': True}))
        self.assertEqual('starting', resolve(None, **{**off, 'launch': True}))
        self.assertEqual('starting', resolve(None, **{**off, 'wanted': True}))
        self.assertEqual('ok', resolve('ok', **off))
        self.assertEqual('stopping', resolve('ok', **{**off, 'held': True}))
        self.assertEqual('restarting', resolve('ok', **{**off, 'launch': True}))

    def test_an_order_in_flight_offers_no_button(self):
        for state in ('stopping', 'restarting', 'starting'):
            self.assertEqual([], supervision._actions(state), state)
        self.assertEqual(['stop', 'restart'], supervision._actions('ok'))
        self.assertEqual(['start'], supervision._actions('on_demand'))

    def test_the_overview_says_what_starts_with_wama(self):
        self._watchdog_alive()
        with mock.patch.object(supervision, '_health', return_value=None), \
                mock.patch.dict(os.environ, {'WAMA_SERVICES_AT_START': 'tts_service'}):
            overview = supervision.services_overview()
        self.assertEqual('running', overview['watchdog'])
        states = {s['key']: (s['state'], s['at_start'], s['port']) for s in overview['services']}
        self.assertEqual({'tts_service': ('down', True, 8001),
                          'tensorflow_service': ('on_demand', False, 8004)}, states)


class TheDeclarationsHoldTogetherTest(SimpleTestCase):

    def test_every_service_is_a_source_that_says_what_stopping_it_changes(self):
        from wama.common.external_sources import by_key
        services = supervision.declared_services()
        self.assertIn('tts_service', services)
        for service in services:
            self.assertTrue(by_key()[service].when_off, service)

    def test_the_voice_starts_with_wama_and_tensorflow_does_not(self):
        for starter in STARTERS:
            listed = _start_list(starter)
            self.assertIn('tts_service', listed, starter.name)
            self.assertNotIn('tensorflow_service', listed, starter.name)

    def test_the_start_lists_name_only_known_services(self):
        known = set(supervision.declared_services())
        for starter in STARTERS:
            self.assertLessEqual(set(_start_list(starter)), known, starter.name)

    def test_the_starters_launch_only_what_the_list_says(self):
        for starter in STARTERS:
            calls = re.findall(r'start_wama_service (\S+)', starter.read_text(encoding='utf-8'))
            self.assertEqual({'tts_service', '"$s"'}, set(calls), starter.name)

    def test_a_restart_of_wama_forgets_the_orders_of_the_previous_run(self):
        for starter in STARTERS:
            source = starter.read_text(encoding='utf-8')
            for flag in ('wanted', 'stopped', 'held', 'launch'):
                self.assertIn(f'"$LOG_DIR"/service_{flag}.*', source, starter.name)

    def test_a_caller_that_finds_a_service_off_asks_for_it(self):
        from wama.common.privacy import service_client as privacy
        from wama.common.tts import service_client as tts
        from wama.common.vectors import service_client as vectors
        down = requests.ConnectionError()
        with mock.patch('requests.post', side_effect=down), \
                mock.patch.object(supervision, 'ask_for_service') as asked, \
                mock.patch.object(privacy.engine, 'detect_segments', return_value={}):
            privacy.detect_segments(['texte'])
        asked.assert_called_once_with('privacy_service')
        with mock.patch('requests.post', side_effect=down), \
                mock.patch.object(supervision, 'ask_for_service') as asked, \
                mock.patch.object(vectors.engine, 'embed_inputs', return_value=[]):
            vectors._embed_prepared(mock.Mock(key='s'), ['x'], timeout=1, keep_alive=None)
        asked.assert_called_once_with('vector_service')
        source = Path(tts.__file__).read_text(encoding='utf-8')
        branch = source[source.index('except requests.ConnectionError:'):source.index('except requests.Timeout:')]
        self.assertIn("ask_for_service('tts_service')", branch)


class TheRoutesTest(TestCase):

    def setUp(self):
        self.client.force_login(User.objects.create_superuser('services_admin', 's@x.fr', 'x'))

    def test_the_state_route_answers_the_overview(self):
        overview = {'watchdog': 'running', 'watchdog_message': '', 'services': []}
        with mock.patch.object(supervision, 'services_overview', return_value=overview):
            data = self.client.get(reverse('model_manager:api_services')).json()
        self.assertEqual({'success': True, **overview}, data)

    def _order(self, body):
        return self.client.post(reverse('model_manager:api_service_control'), json.dumps(body),
                                content_type='application/json')

    def test_an_accepted_order_says_so(self):
        with mock.patch.object(supervision, 'control_service', return_value=(True, 'fait')) as control:
            response = self._order({'service': 'tts_service', 'action': 'stop'})
        self.assertEqual((200, 'fait'), (response.status_code, response.json()['message']))
        control.assert_called_once_with('tts_service', 'stop')

    def test_a_refused_order_is_a_conflict_with_its_reason(self):
        with mock.patch.object(supervision, 'control_service', return_value=(False, 'non')):
            response = self._order({'service': 'tts_service', 'action': 'stop'})
        self.assertEqual((409, 'non'), (response.status_code, response.json()['error']))

    def test_the_routes_are_closed_to_a_simple_account(self):
        self.client.force_login(User.objects.create_user('services_user', password='x'))
        with mock.patch.object(supervision, 'control_service') as control:
            for response in (self._order({'service': 'tts_service', 'action': 'stop'}),
                             self.client.get(reverse('model_manager:api_services'))):
                self.assertEqual(302, response.status_code)
        control.assert_not_called()

    def test_the_tool_needs_the_users_agreement_to_stop_or_restart(self):
        from wama import tool_api
        admin = User.objects.get(username='services_admin')
        with mock.patch.object(tool_api, '_model_manager_answer', return_value={'success': True}) as answer:
            for action in ('stop', 'restart'):
                self.assertIn('error', tool_api.control_service(admin, 'tts_service', action))
            answer.assert_not_called()
            self.assertEqual({'success': True},
                             tool_api.control_service(admin, 'tts_service', 'stop', confirm=True))
            self.assertEqual({'success': True}, tool_api.control_service(admin, 'tts_service', 'start'))


class ThePageTest(TestCase):

    def setUp(self):
        self.client.force_login(User.objects.create_superuser('services_page', 'p@x.fr', 'x'))
        self.html = self.client.get(reverse('model_manager:index')).content.decode()

    def test_the_card_sits_in_the_system_row_that_the_panel_takes(self):
        row = self.html.index('id="mmSystemRow"')
        self.assertLess(row, self.html.index('id="services-list"'))
        self.assertLess(self.html.index('id="idle-models-list"'), self.html.index('id="services-list"'))
        self.assertLess(self.html.index('id="services-list"'), self.html.index('wama-filter-bar"'))

    @skipUnless(HAS_V8, 'V8 (py_mini_racer) absent')
    def test_the_buttons_follow_the_actions_and_the_watchdog(self):
        from py_mini_racer import MiniRacer
        script = self.html[self.html.index('const SERVICE_TONES'):self.html.index('async function controlService')]
        v8 = MiniRacer()
        v8.eval('''
            var nodes = {};
            var document = {getElementById: function (id) {
                return nodes[id] = nodes[id] || {hidden: false, textContent: '', innerHTML: ''}; }};
            var WamaApp = {escapeHtml: function (t) { return String(t); }};
        ''')
        v8.eval(script)
        service = ("{key:'tts_service',label:'Voix',usage:'u',when_off:'w',port:8001,state:'ok',"
                   "state_label:'En marche',tone:'success',at_start:true,actions:['stop','restart']}")
        v8.eval(f"updateServices({{watchdog:'running',watchdog_message:'',services:[{service}]}})")
        html = v8.eval("nodes['services-list'].innerHTML")
        self.assertIn('data-action="stop"', html)
        self.assertIn('data-action="restart"', html)
        self.assertNotIn('disabled', html)
        self.assertEqual('1/1', v8.eval("nodes['services-count'].textContent"))
        self.assertTrue(v8.eval("nodes['services-watchdog'].hidden"))
        v8.eval(f"updateServices({{watchdog:'absent',watchdog_message:'pas de surveillance',services:[{service}]}})")
        self.assertIn('disabled', v8.eval("nodes['services-list'].innerHTML"))
        self.assertFalse(v8.eval("nodes['services-watchdog'].hidden"))

    def test_the_compact_panel_keeps_every_element_the_script_reads(self):
        for element in ('cpu-bar', 'ram-bar', 'ram-used', 'ram-free', 'gpu-bar', 'gpu-used', 'gpu-free',
                        'disk-bar', 'disk-used', 'disk-free', 'disk-total', 'disk-warning',
                        'cleaner-indicator', 'cleaner-auto', 'process-rss', 'tracked-total',
                        'idle-threshold', 'idle-count', 'btn-cleanup-idle', 'btn-aggressive-cleanup',
                        'btn-clear-gpu-cache', 'btn-force-gc', 'btn-backup-db', 'btn-backup-models',
                        'btn-backup-media'):
            self.assertEqual(1, self.html.count(f'id="{element}"'), element)

    def test_the_backups_left_the_memory_card(self):
        self.assertLess(self.html.index('id="btn-force-gc"'), self.html.index('>Sauvegardes</h5>'))
        self.assertLess(self.html.index('>Sauvegardes</h5>'), self.html.index('id="btn-backup-db"'))

    def test_the_switch_replaced_the_two_buttons(self):
        self.assertNotIn('btn-cleaner-start', self.html)
        self.assertNotIn('btn-cleaner-stop', self.html)
        handler = self.html[self.html.index("getElementById('cleaner-auto').addEventListener"):]
        self.assertIn(reverse('model_manager:api_cleaner_start'), handler[:400])
        self.assertIn(reverse('model_manager:api_cleaner_stop'), handler[:400])

    @skipUnless(HAS_V8, 'V8 (py_mini_racer) absent')
    def test_the_switch_shows_the_real_state_of_the_cleaner(self):
        from py_mini_racer import MiniRacer
        script = self.html[self.html.index('function updateCleanerStatus('):self.html.index('function updateIdleModels(')]
        v8 = MiniRacer()
        v8.eval('''
            var nodes = {};
            var document = {getElementById: function (id) {
                return nodes[id] = nodes[id] || {className: '', checked: false, textContent: ''}; }};
        ''')
        v8.eval(script)
        v8.eval("updateCleanerStatus({running: true, idle_threshold: 300})")
        self.assertTrue(v8.eval("nodes['cleaner-auto'].checked"))
        self.assertIn('status-running', v8.eval("nodes['cleaner-indicator'].className"))
        v8.eval("updateCleanerStatus({running: false, idle_threshold: 300})")
        self.assertFalse(v8.eval("nodes['cleaner-auto'].checked"))
        self.assertIn('status-stopped', v8.eval("nodes['cleaner-indicator'].className"))

    def test_a_simple_account_gets_no_state_reading_from_the_script(self):
        self.assertIn('if (CAN_MANAGE) Object.keys(MEMORY_DETAIL)', self.html)
