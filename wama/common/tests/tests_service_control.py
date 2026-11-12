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
            'x=1\nWAMA_CELERY_WORKERS="gpu default"\nWAMA_SERVICES="tts_service tensorflow_service"\n'
            'WAMA_COMPANIONS=""\n',
            encoding='utf-8')
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

    def test_the_web_server_start_does_not_trust_a_process_search(self):
        source = STARTERS[0].read_text(encoding='utf-8')
        launch = source[:source.index('gunicorn wama.wsgi:application')]
        guard = launch[launch.rindex('\nif '):]
        self.assertIn('gunicorn.pid', guard)
        self.assertNotIn('pgrep', guard)

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


class EnvironmentsTest(SimpleTestCase):
    """Multi-venv (2026-11-11): environments are declared ONCE, in the script that launches the
    services, and the Python reads the same lines — a service of another environment is launched,
    watched and stopped by the same functions as any other."""

    def test_the_reference_environment_comes_first_and_is_the_venv_running_wama(self):
        import sys
        environments = supervision.declared_environments()
        self.assertEqual(supervision.reference_environment(), next(iter(environments)))
        self.assertEqual(Path(sys.prefix).resolve(),
                         environments[supervision.reference_environment()].resolve())

    def test_every_service_runs_in_a_declared_environment(self):
        environments = supervision.declared_environments()
        for service in supervision.declared_services():
            self.assertIn(supervision.service_environment(service), environments, service)
        named = [pair.partition(':')[0] for pair in supervision._script_list('WAMA_SERVICE_ENVIRONMENTS')]
        self.assertLessEqual(set(named), set(supervision.declared_services()))

    def test_no_script_writes_the_reference_venv_by_hand(self):
        """The starters and the watchdog wrote `venv_linux` each, beside the declaration."""
        for script in (*STARTERS, BASE / 'scripts' / 'worker_watchdog.sh'):
            source = script.read_text(encoding='utf-8')
            self.assertNotIn('venv_linux', source, script.name)
            self.assertIn('wama_reference_venv', source, script.name)

    def test_both_starters_stop_every_declared_service(self):
        """The production starter named three services by hand: one added for another environment
        would have survived a restart, holding its port and its share of the card."""
        for starter in STARTERS:
            source = starter.read_text(encoding='utf-8')
            stop = source[:source.index('CONFIGURATION')]
            self.assertIn('for s in $WAMA_SERVICES', stop, starter.name)
            self.assertNotIn('wama_service_pattern vector_service', stop, starter.name)

    def test_a_service_without_declaration_runs_in_the_reference_environment(self):
        with mock.patch.object(supervision, '_script_list', side_effect=lambda name: {
                'WAMA_ENVIRONMENTS': ['main:venv_a', 'recent:venv_b'],
                'WAMA_SERVICE_ENVIRONMENTS': ['flux_service:recent']}[name]):
            self.assertEqual('recent', supervision.service_environment('flux_service'))
            self.assertEqual('main', supervision.service_environment('tts_service'))
            self.assertEqual(BASE / 'venv_b' / 'bin' / 'python', supervision.environment_python('recent'))


class EnvironmentLaunchShellTest(SimpleTestCase):
    """`start_wama_service` launches a service with the python of ITS environment, that venv at the
    head of PATH and in VIRTUAL_ENV (bash, fake venvs) — skipped without bash (Windows)."""

    def setUp(self):
        import shutil
        self.bash = shutil.which('bash')
        if not self.bash or not Path('/proc/version').exists():
            self.skipTest('bash (Linux) required')
        folder = tempfile.TemporaryDirectory(prefix='wama-environments-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for venv in ('venv_a', 'venv_b'):
            python = self.root / venv / 'bin' / 'python'
            python.parent.mkdir(parents=True)
            python.write_text(f'#!/bin/bash\necho "{venv} $VIRTUAL_ENV ${{PATH%%:*}} $*" '
                              f'>> "{self.root}/launched"\n', encoding='utf-8')
            python.chmod(0o755)

    def _launch(self, service):
        import subprocess
        script = f'''
            PROJECT_DIR="{self.root}"; LOG_DIR="{self.root}"; source "{BASE / 'scripts' / 'wama_services.sh'}"
            WAMA_ENVIRONMENTS="main:venv_a recent:venv_b"
            WAMA_SERVICE_ENVIRONMENTS="tensorflow_service:recent"
            start_wama_service {service}; echo "rc=$?"
            # The launch is detached (`nohup … & disown`): wait for its line, not for the job.
            for i in $(seq 50); do [ -s "{self.root}/launched" ] && break; sleep 0.1; done
        '''
        out = subprocess.run([self.bash, '-c', script], capture_output=True, text=True, timeout=30)
        launched = self.root / 'launched'
        return out, (launched.read_text(encoding='utf-8').strip() if launched.exists() else '')

    def test_a_service_of_another_environment_runs_with_its_python(self):
        out, launched = self._launch('tensorflow_service')
        self.assertIn('rc=0', out.stdout, out.stderr)
        venv = self.root / 'venv_b'
        self.assertEqual(f'venv_b {venv} {venv}/bin -m uvicorn wama.common.tensorflow_service.service:app '
                         '--host 127.0.0.1 --port 8004 --workers 1 --log-level warning', launched)

    def test_a_service_without_declaration_runs_in_the_reference_environment(self):
        out, launched = self._launch('tts_service')
        self.assertIn('rc=0', out.stdout, out.stderr)
        self.assertTrue(launched.startswith(f'venv_a {self.root / "venv_a"} '), launched)

    def test_a_missing_venv_launches_nothing_and_says_so(self):
        import shutil
        shutil.rmtree(self.root / 'venv_b')
        out, launched = self._launch('tensorflow_service')
        self.assertIn('rc=1', out.stdout)
        self.assertIn('venv absent', out.stderr)
        self.assertEqual('', launched)


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
        with mock.patch.object(tool_api, '_model_manager_view',
                               return_value=(None, {'success': True})) as view:
            for action in ('stop', 'restart'):
                self.assertIn('error', tool_api.control_service(admin, 'tts_service', action))
            view.assert_not_called()
            self.assertEqual({'success': True},
                             tool_api.control_service(admin, 'tts_service', 'stop', confirm=True))
            self.assertEqual({'success': True}, tool_api.control_service(admin, 'tts_service', 'start'))


class ProcessOrdersTest(_WithLogs):
    """Relancer depuis WAMA ce qui est relançable (2026-11-11, demande de Fabien) : un worker, le
    serveur web, WAMA entier — sur la même voie d'ordre que les services."""

    def setUp(self):
        super().setUp()
        (self.root / 'scripts' / 'wama_services.sh').write_text(
            'WAMA_CELERY_WORKERS="gpu default beat"\nWAMA_SERVICES="tts_service"\n'
            'WAMA_COMPANIONS="gateway_discord wama_mcp_dev"\n', encoding='utf-8')

    def _files(self):
        return {p.name for p in self.logs.iterdir() if not p.name.startswith('worker_watchdog')}

    def test_each_order_drops_its_flag_for_the_watchdog(self):
        self._watchdog_alive()
        for key, flag in (('gpu', 'service_launch.gpu'), ('web', 'service_launch.web'),
                          ('wama', 'wama_restart')):
            with self.subTest(key=key):
                accepted, _ = supervision.control_process(key, 'restart')
                self.assertTrue(accepted)
                self.assertIn(flag, self._files())

    def test_all_the_workers_are_restarted_by_one_order(self):
        """2026-11-12 : le serveur web, puis tous les workers — deux gestes pour servir du code neuf."""
        self._watchdog_alive()
        accepted, _ = supervision.control_process('workers', 'restart')
        self.assertTrue(accepted)
        self.assertEqual({'service_launch.gpu', 'service_launch.default', 'service_launch.beat'},
                         self._files())
        rows = {p['key']: p for p in supervision.processes_overview()}
        self.assertEqual(('restarting', []), (rows['workers']['state'], rows['workers']['actions']))
        with mock.patch.object(supervision, '_worker_busy', side_effect=lambda w: w == 'gpu'):
            self.assertTrue(supervision.needs_password('workers', 'restart'), 'un worker en pleine tâche')
        with mock.patch.object(supervision, '_worker_busy', return_value=False):
            self.assertFalse(supervision.needs_password('workers', 'restart'))

    def test_the_gateway_and_the_mcp_servers_are_processes_one_can_restart(self):
        """Ils gardaient le code de leur démarrage : aucun geste de WAMA ne les relançait."""
        self._watchdog_alive()
        (self.logs / 'companion_seen.wama_mcp_dev').touch()
        rows = {p['key']: p for p in supervision.processes_overview()}
        mcp = rows['wama_mcp_dev']
        self.assertEqual(('ok', ['restart'], 'companion'), (mcp['state'], mcp['actions'], mcp['kind']))
        # Un serveur MCP est une SOURCE déclarée : son libellé et ce que coupe son arrêt s'y lisent.
        from wama.common.external_sources import by_key
        source = by_key()['wama_mcp_dev']
        self.assertEqual((source.label, source.when_off), (mcp['label'], mcp['when_off']))
        self.assertTrue(source.when_off)
        self.assertEqual(('down', ['restart']),
                         (rows['gateway_discord']['state'], rows['gateway_discord']['actions']))
        self.assertTrue(rows['gateway_discord']['label'] and rows['gateway_discord']['when_off'])
        self.assertTrue(supervision.control_process('wama_mcp_dev', 'restart')[0])
        self.assertIn('service_launch.wama_mcp_dev', self._files())
        self.assertEqual('restarting', {p['key']: p['state']
                                        for p in supervision.processes_overview()}['wama_mcp_dev'])
        self.assertFalse(supervision.needs_password('wama_mcp_dev', 'restart'))
        # Contre-épreuve : un compagnon que le script ne déclare pas n'est pas un processus.
        self.assertFalse(supervision.control_process('wama_mcp', 'restart')[0])

    def test_only_a_restart_of_a_known_process_is_taken_and_never_without_a_watchdog(self):
        self.assertFalse(supervision.control_process('gpu', 'restart')[0])   # pas de surveillance
        self._watchdog_alive()
        self.assertFalse(supervision.control_process('gpu', 'stop')[0])
        self.assertFalse(supervision.control_process('postgresql', 'restart')[0])
        self.assertEqual(set(), self._files())

    def test_what_cuts_a_running_task_needs_the_password(self):
        with mock.patch.object(supervision, '_worker_busy', return_value=True):
            self.assertTrue(supervision.needs_password('gpu', 'restart'))
            self.assertTrue(supervision.needs_password('wama', 'restart'))
            self.assertFalse(supervision.needs_password('web', 'restart'))
        with mock.patch.object(supervision, '_worker_busy', return_value=False):
            self.assertFalse(supervision.needs_password('gpu', 'restart'))
            self.assertTrue(supervision.needs_password('wama', 'restart'))

    def test_a_worker_that_does_not_answer_is_held_busy(self):
        """Un worker gpu en pool solo ne répond pas pendant une tâche : sans réponse, OCCUPÉ. La
        lecture est la photo de la réconciliation (`collect_worker_snapshot`), pas une seconde."""
        import socket
        node = f'gpu@{socket.gethostname()}'
        inspect = mock.Mock()
        with mock.patch('celery.current_app.control.inspect', return_value=inspect):
            for active, busy in ((None, True), ({'other@h': []}, True), ({node: []}, False),
                                 ({node: [{'id': 't'}]}, True)):
                inspect.active.return_value = active
                inspect.reserved.return_value = {}
                self.assertEqual(busy, supervision._worker_busy('gpu'), active)
        self.assertFalse(supervision._worker_busy('beat'))

    def test_the_overview_reads_the_sign_of_life_and_the_orders_in_flight(self):
        self._watchdog_alive()
        (self.logs / 'worker_seen.gpu').touch()
        (self.logs / 'service_stopped.default').touch()
        rows = {p['key']: (p['state'], p['actions']) for p in supervision.processes_overview()}
        self.assertEqual(('ok', ['restart']), rows['gpu'])
        self.assertEqual(('restarting', []), rows['default'])
        self.assertEqual(('down', ['restart']), rows['beat'])
        self.assertEqual(('ok', ['restart']), rows['web'])
        (self.logs / 'wama_restart').touch()
        self.assertEqual('restarting', {p['key']: p['state'] for p in supervision.processes_overview()}['wama'])


class ProcessRoutesTest(TestCase):
    """La vue : administrateur seul, mot de passe WAMA revérifié pour ce qui coupe, une fenêtre de
    session ; l'outil de l'assistant ne transporte jamais de mot de passe."""

    def setUp(self):
        self.admin = User.objects.create_superuser('process_admin', 'a@x.fr', 'the-password')
        self.client.force_login(self.admin)

    def _order(self, key, password=''):
        return self.client.post(reverse('model_manager:api_service_control'),
                                json.dumps({'service': key, 'action': 'restart', 'password': password}),
                                content_type='application/json')

    def test_what_cuts_asks_the_password_and_a_good_one_opens_a_window(self):
        with mock.patch.object(supervision, 'declared_workers', return_value=['gpu']), \
                mock.patch.object(supervision, '_worker_busy', return_value=True), \
                mock.patch.object(supervision, 'control_process', return_value=(True, 'fait')) as order, \
                mock.patch('wama.common.utils.notifications.notify_admins',
                           return_value=(1, False)) as told:
            refused = self._order('gpu')
            self.assertEqual((403, True), (refused.status_code, refused.json().get('needs_password')))
            self.assertEqual(403, self._order('gpu', 'wrong').status_code)
            order.assert_not_called()
            self.assertEqual(200, self._order('gpu', 'the-password').status_code)
            self.assertEqual(200, self._order('gpu').status_code, "la fenêtre de reconfirmation")
            self.assertEqual(2, order.call_count)
            # The notification can be OPENED: it leads to the page where the restart is followed.
            from django.urls import reverse
            self.assertEqual(reverse('model_manager:index'), told.call_args.kwargs.get('url'))

    def test_an_idle_worker_or_the_web_server_need_no_password(self):
        with mock.patch.object(supervision, 'declared_workers', return_value=['gpu']), \
                mock.patch.object(supervision, '_worker_busy', return_value=False), \
                mock.patch.object(supervision, 'control_process', return_value=(True, 'fait')):
            self.assertEqual(200, self._order('gpu').status_code)
            self.assertEqual(200, self._order('web').status_code)

    def test_restarting_all_of_wama_asks_the_password_every_time(self):
        """Décision de Fabien (2026-11-11) : WAMA entier redemande le mot de passe À CHAQUE fois —
        la fenêtre ouverte par un autre geste ne vaut pas pour lui (vu en service : sans cette règle,
        la relance de WAMA juste après celle d'un worker occupé passait sans mot de passe)."""
        with mock.patch.object(supervision, 'declared_workers', return_value=['gpu']), \
                mock.patch.object(supervision, '_worker_busy', return_value=True), \
                mock.patch.object(supervision, 'control_process', return_value=(True, 'fait')) as order, \
                mock.patch('wama.common.utils.notifications.notify_admins', return_value=(1, False)):
            self.assertEqual(200, self._order('gpu', 'the-password').status_code)   # fenêtre ouverte
            again = self._order('wama')
            self.assertEqual((403, True), (again.status_code, again.json().get('needs_password')))
            self.assertEqual(200, self._order('wama', 'the-password').status_code)
            self.assertEqual(403, self._order('wama').status_code, 'pas de fenêtre pour WAMA entier')
            self.assertEqual(200, self._order('gpu').status_code, 'contre-épreuve : la fenêtre vaut ailleurs')
            self.assertEqual(3, order.call_count)

    def test_a_developer_sees_and_orders_no_process(self):
        from wama.accounts.permissions import is_admin_tier
        developer = User.objects.create_user('process_dev', password='x')
        self.client.force_login(developer)
        with mock.patch('wama.model_manager.views.is_admin_or_dev', return_value=True), \
                mock.patch('wama.accounts.permissions.is_admin_tier', return_value=False), \
                mock.patch.object(supervision, 'control_process') as order:
            self.assertFalse(is_admin_tier(developer))
            response = self._order('web')
            order.assert_not_called()
        self.assertIn(response.status_code, (302, 403))

    def test_the_assistant_never_carries_a_password(self):
        from wama import tool_api
        with mock.patch.object(tool_api, '_model_manager_view',
                               return_value=({'error': 'x'}, {'needs_password': True})):
            told = tool_api.control_service(self.admin, 'gpu', 'restart', confirm=True)
        self.assertTrue(told.get('needs_password'))
        self.assertIn('page du model manager', told['error'])


class ProcessOrdersShellTest(SimpleTestCase):
    """La surveillance exécute les ordres (bash, avec des bouchons) — sautée sans bash (Windows)."""

    def setUp(self):
        import shutil
        self.bash = shutil.which('bash')
        if not self.bash or not Path('/proc/version').exists():
            self.skipTest('bash (Linux) required')
        folder = tempfile.TemporaryDirectory(prefix='wama-processes-')
        self.addCleanup(folder.cleanup)
        self.logs = Path(folder.name)

    def _run(self, body):
        import subprocess
        script = f'''
            PROJECT_DIR="{BASE}"; LOG_DIR="{self.logs}"; source "{BASE / 'scripts' / 'wama_services.sh'}"
            declare -A RESTARTS GAVE_UP
            MAX_RESTARTS=2; WINDOW_S=1800; READY_WAIT_S=2
            log() {{ :; }}
            report() {{ echo "REPORT $1 $2 $4"; }}
            sleep() {{ :; }}
            {body}
        '''
        return subprocess.run([self.bash, '-c', script], capture_output=True, text=True, timeout=30)

    def test_a_worker_is_stopped_warm_then_restarted_without_a_report(self):
        (self.logs / 'service_launch.gpu').touch()
        out = self._run('''
            UP=1
            celery_worker_alive() { [ "$UP" = 1 ]; }
            pgrep() { echo 4242; }
            kill() { echo "KILL $*"; UP=0; }
            start_celery_worker() { echo "START $1"; UP=1; }
            supervise_one gpu celery
            supervise_one gpu celery
        ''')
        self.assertEqual('KILL -TERM 4242\nSTART gpu\n', out.stdout, out.stderr)
        self.assertEqual([], [p.name for p in self.logs.iterdir() if p.name.startswith('service_')])

    def test_a_worker_in_warm_shutdown_is_left_to_finish(self):
        (self.logs / 'service_stopped.gpu').touch()
        out = self._run('''
            celery_worker_alive() { true; }
            start_celery_worker() { echo "START $1"; }
            supervise_one gpu celery
        ''')
        self.assertEqual('', out.stdout, out.stderr)
        self.assertTrue((self.logs / 'service_stopped.gpu').exists())
        self.assertFalse((self.logs / 'worker_seen.gpu').exists())

    def test_a_running_worker_leaves_its_sign_of_life(self):
        out = self._run('celery_worker_alive() { true; }; supervise_one gpu celery')
        self.assertEqual('', out.stdout, out.stderr)
        self.assertTrue((self.logs / 'worker_seen.gpu').exists())

    def test_the_web_server_is_reloaded_by_its_pid_file(self):
        (self.logs / 'gunicorn.pid').write_text('777')
        (self.logs / 'service_launch.web').touch()
        out = self._run('kill() { echo "KILL $*"; }; supervise_web; supervise_web')
        self.assertEqual('KILL -HUP 777\n', out.stdout, out.stderr)

    def test_a_companion_is_stopped_and_started_once_on_order_and_never_by_itself(self):
        (self.logs / 'service_launch.wama_mcp_dev').touch()
        out = self._run("""
            UP=1
            wama_companion_alive() { [ "$UP" = 1 ]; }
            stop_wama_companion() { echo "STOP $1"; UP=0; }
            start_wama_companion() { echo "START $1"; }
            supervise_companion wama_mcp_dev
            supervise_companion wama_mcp_dev
            supervise_companion gateway_discord
        """)
        self.assertEqual('STOP wama_mcp_dev\nSTART wama_mcp_dev\n', out.stdout, out.stderr)
        self.assertFalse((self.logs / 'service_launch.wama_mcp_dev').exists())
        # Éteint et sans ordre : laissé éteint, sans signe de vie (le script de développement ne
        # les lance pas, exprès).
        self.assertFalse((self.logs / 'companion_seen.gateway_discord').exists())

    def test_a_running_companion_leaves_its_sign_of_life_and_its_pattern_is_exact(self):
        out = self._run("""
            wama_companion_alive() { true; }
            supervise_companion wama_mcp
            wama_companion_pattern wama_mcp; wama_companion_pattern wama_mcp_dev
            wama_companion_pattern no_such || echo REFUSED
        """)
        self.assertTrue((self.logs / 'companion_seen.wama_mcp').exists())
        self.assertEqual('[m]anage.py run_mcp_server --surface wama\n'
                         '[m]anage.py run_mcp_server --surface dev\nREFUSED\n', out.stdout, out.stderr)

    def test_the_gateway_is_checked_before_it_is_launched(self):
        out = self._run("""
            python() { echo "PY $*"; case " $* " in *" --check "*) return 1 ;; esac; }
            nohup() { echo "NOHUP $*"; }
            start_wama_companion gateway_discord || echo NOT_STARTED
        """)
        # La vérification refuse : rien n'est lancé, et son message est au journal de la passerelle.
        self.assertEqual('NOT_STARTED\n', out.stdout, out.stderr)
        self.assertEqual('PY manage.py run_gateway discord --check --settings=wama.settings\n',
                         (self.logs / 'gateway-discord.log').read_text())

    def test_the_start_script_launches_them_by_the_shared_command(self):
        source = (BASE / 'start_wama_prod.sh').read_text(encoding='utf-8')
        self.assertIn('start_wama_companion gateway_discord', source)
        self.assertIn('start_wama_companion "$companion"', source)
        self.assertEqual([], re.findall(r'^\s*nohup python manage\.py run_(?:gateway|mcp_server)',
                                        source, re.M))
        watchdog = (BASE / 'scripts' / 'worker_watchdog.sh').read_text(encoding='utf-8')
        self.assertIn('for c in $WAMA_COMPANIONS; do supervise_companion "$c"; done', watchdog)

    def test_a_restart_of_wama_runs_the_start_script_once(self):
        starter = self.logs / 'fake_start.sh'
        starter.write_text(f'touch "{self.logs}/started"\n')
        (self.logs / 'wama_restart').touch()
        out = self._run(f'WAMA_START_SCRIPT="{starter}"; unset -f sleep; supervise_wama_restart; '
                        f'supervise_wama_restart; for i in 1 2 3 4 5 6 7 8 9 10; do '
                        f'[ -f "{self.logs}/started" ] && break; command sleep 0.2; done')
        self.assertTrue((self.logs / 'started').exists(), out.stderr)
        self.assertFalse((self.logs / 'wama_restart').exists())

    def test_the_starters_say_which_script_restarts_wama_and_forget_the_order(self):
        for starter in STARTERS:
            source = starter.read_text(encoding='utf-8')
            self.assertIn(f'export WAMA_START_SCRIPT="$PROJECT_DIR/{starter.name}"', source)
            self.assertIn('"$LOG_DIR"/wama_restart', source)
            # Relancé DÉTACHÉ, sans terminal : un `sudo` nu échoue et `set -e` arrête tout après
            # avoir tué la pile (start_wama_dev.sh, vu à la revérification du 2026-11-11).
            self.assertEqual([], re.findall(r'^\s*sudo\s+(?!-n\b).*$', source, re.M), starter.name)
        watchdog = (BASE / 'scripts' / 'worker_watchdog.sh').read_text(encoding='utf-8')
        self.assertIn('supervise_web', watchdog)
        self.assertIn('supervise_wama_restart', watchdog)


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
        # Les processus : rendus pour l'administrateur seul (la vue les retire pour un développeur).
        self.assertTrue(v8.eval("nodes['processes-block'].hidden"))
        process = ("{key:'gpu',label:'Worker gpu',kind:'worker',state:'ok',state_label:'En marche',"
                   "tone:'success',actions:['restart'],when_off:'w'}")
        v8.eval(f"updateServices({{watchdog:'running',watchdog_message:'',services:[{service}],"
                f"processes:[{process}]}})")
        self.assertFalse(v8.eval("nodes['processes-block'].hidden"))
        html = v8.eval("nodes['processes-list'].innerHTML")
        self.assertIn('data-process="gpu"', html)
        self.assertNotIn('disabled', html)

    @skipUnless(HAS_V8, 'V8 (py_mini_racer) absent')
    def test_the_password_is_never_asked_in_clear_without_the_modal(self):
        """La reconfirmation passe par la confirmation commune (`WamaApp.ask`, champ masqué) ; sans
        Bootstrap son repli est `window.prompt`, qui l'afficherait en clair : le geste est refusé."""
        import re
        from py_mini_racer import MiniRacer
        src = (Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-app-base.js').read_text(
            encoding='utf-8')
        served = Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-app-base.js'
        self.assertEqual(src, served.read_text(encoding='utf-8'), 'staticfiles/ en retard')
        body = re.search(r'\n  function ask\(opts\) \{.*?\n  \}\n', src, re.S).group(0)
        v8 = MiniRacer()
        v8.eval('var prompted = 0, answer = null; var global = {prompt: function () { prompted++; '
                'return "x"; }, confirm: function () { return true; }}; '
                'function escapeHtml(t) { return String(t); }' + body)
        v8.eval("ask({text: 't', input: {label: 'Mot de passe WAMA', secret: true}})"
                ".then(function (r) { answer = r; })")
        self.assertEqual(0, v8.eval('prompted'))
        self.assertFalse(v8.eval('answer.ok'))
        v8.eval("ask({text: 't', input: {label: 'Nom'}}).then(function (r) { answer = r; })")
        self.assertEqual(1, v8.eval('prompted'), 'contre-épreuve : un champ ordinaire garde son repli')

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
