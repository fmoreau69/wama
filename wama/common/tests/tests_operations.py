"""The « Exploitation » page (2026-11-14, `ROADMAP §31.1`): what makes WAMA run and what checks it.

Asked by Fabien: the model manager page had grown restart buttons that do not concern models, and
some commands (`check_docs`, the tests…) were worth launching from WAMA. The page gathers the
processes one can restart (`service_supervision.processes_overview`), the DECLARED operations
(`common/operations.py`) and the last nightly reports.

Held here: an operation is a `manage.py` command with FIXED arguments — never a command line
composed by the caller; the page and its routes are for administrators; the web server never
imports the development tools (it relays to them); the two scripts render pure lists.
"""
import importlib.util
import json
import tempfile
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.accounts.permissions import set_account_tier
from wama.common import operations

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
ROOT = Path(settings.BASE_DIR)
JS = ROOT / 'wama' / 'common' / 'static' / 'common' / 'js'


class OperationsAreFixedCommandsTest(SimpleTestCase):

    def test_every_operation_is_an_existing_command_and_says_what_it_does(self):
        from django.core.management import get_commands
        known = get_commands()
        self.assertGreaterEqual(len(operations.OPERATIONS), 5)
        for key, spec in operations.OPERATIONS.items():
            with self.subTest(operation=key):
                self.assertIn(spec['argv'][0], known)
                self.assertTrue(spec['label'] and spec['description'] and spec['icon'].startswith('fa-'))
                # At most ONE free argument, bounded by a pattern.
                self.assertLessEqual(spec['argv'].count('{argument}'), 1)
                self.assertEqual('{argument}' in spec['argv'], bool(spec.get('argument')))
        self.assertEqual(list(operations.OPERATIONS), [o['key'] for o in operations.operations()])

    def test_the_arguments_are_those_of_the_declaration_and_nothing_else(self):
        self.assertEqual(['doc_facts', '--check'], operations.command('doc_facts'))
        self.assertEqual(['test', 'wama.common.tests.tests_operations', '--keepdb'],
                         operations.command('tests', ' wama.common.tests.tests_operations '))
        for key, argument in (('no_such', ''), ('doc_facts', '--force'), ('tests', ''),
                              ('tests', 'wama'), ('tests', 'os.system'), ('tests', '--help'),
                              ('tests', 'wama.common; rm -rf x'), ('manifest_export', 'x')):
            with self.subTest(operation=key, argument=argument):
                with self.assertRaises(ValueError):
                    operations.command(key, argument)

    def test_no_operation_can_write_the_corpus_or_the_docs(self):
        # Counter-check on the DECLARATION: the two commands that write are launched in their
        # checking form only.
        for key in ('doc_facts', 'manifest_export'):
            self.assertIn('--check', operations.OPERATIONS[key]['argv'])


class DevToolTest(TestCase):
    """`dev_run_operation`, the only door: administrators, a background job of `manage.py`."""

    def setUp(self):
        from wama.common.services import dev_inspect, dev_tools
        self.inspect, self.tools = dev_inspect, dev_tools
        User = get_user_model()
        self.admin = User.objects.create_user('ops_admin', password='x')
        set_account_tier(self.admin, 'admin')
        self.dev = User.objects.create_user('ops_dev', password='x')
        set_account_tier(self.dev, 'developpeur')

    def test_an_operation_starts_one_job_named_after_it(self):
        with mock.patch.object(self.inspect, 'start_job', return_value={'job_id': 'j'}) as started:
            self.assertEqual({'job_id': 'j'}, self.tools.call(
                self.admin, 'dev_run_operation', {'operation': 'check_docs'}))
            tool, argv = started.call_args.args[1], started.call_args.args[2]
            self.assertEqual(self.inspect.OPERATION_TOOL + 'check_docs', tool)
            self.assertEqual(['check_docs'], argv[2:])
            self.assertTrue(argv[1].endswith('manage.py'))
            for refused in ({'operation': 'no_such'}, {'operation': 'tests', 'argument': 'wama'},
                            {'operation': 'check_docs', 'argument': 'x'}):
                with self.subTest(refused=refused):
                    self.assertIn('error', self.tools.call(self.admin, 'dev_run_operation', refused))
            self.assertEqual(1, started.call_count)

    def test_a_developer_neither_lists_nor_launches(self):
        for name in ('dev_run_operation', 'dev_list_operations'):
            self.assertIn(name, self.tools.ADMIN_ONLY)
            self.assertEqual('forbidden', self.tools.call(self.dev, name, {'operation': 'check_docs'})['error'])
        self.assertEqual('forbidden', self.inspect.dev_run_operation(self.dev, 'check_docs')['error'])
        listed = self.tools.call(self.admin, 'dev_list_operations', {})['operations']
        self.assertEqual(list(operations.OPERATIONS), [o['key'] for o in listed])


class ThePageTest(TestCase):

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('ops_page_admin', 'a@x.fr', 'x')
        self.dev = User.objects.create_user('ops_page_dev', password='x')
        set_account_tier(self.dev, 'developpeur')

    def test_the_page_follows_the_charter_of_the_management_pages(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('common:operations')).content.decode()
        for piece in ('class="wama-cat-wrap"', 'wama-cat-header', 'class="wama-cat-hero"',
                      'class="wama-cat-stats"', 'wama-cat-grid'):
            self.assertIn(piece, html)
        self.assertIn('Exploitation', html)
        for op in operations.operations():
            self.assertIn(f'data-operation="{op["key"]}"', html)
            self.assertIn(op['label'], html)
        self.assertIn('data-wama-processes', html)
        # The right panel, as on the other management pages: the processes at its head, the
        # derived record of the selected tile; and the COMMON bar (search, facet, declared sort).
        centre, _, panel = html.partition('class="wama-cat-wrap"')[2].partition('id="right-panel-top"')
        self.assertIn('data-wama-processes', panel, 'the processes live in the right panel')
        self.assertNotIn('data-wama-processes', centre)
        self.assertIn('id="inspectorRegistreDetail"', html)
        self.assertIn('data-wama-inspecte=".wama-cat-card"', centre)
        for piece in ('data-wama-filter-bar', 'data-cible-vivante="1"', 'data-f-role="sort"',
                      'data-f-facette="nature"', 'data-f-groupe'):
            self.assertIn(piece, centre)
        for nature in operations.NATURES.values():
            self.assertIn(nature, centre)
        self.assertIn(f'data-f-nature="{operations.NATURES["operation"]}"', centre)
        self.assertIn(f'data-nature="{operations.NATURES["job"]}"', centre)
        self.assertIn(f'data-api="{reverse("model_manager:api_services")}"', html)
        for script in ('wama-processes.js', 'wama-operations.js'):
            self.assertIn(script, html)

    def test_the_page_and_its_routes_are_for_administrators(self):
        for user in (None, self.dev):
            self.client.logout()
            if user is not None:
                self.client.force_login(user)
            # The relay would ANSWER (mocked): the refusal must be the view's own, before any call
            # — a first version of this guard passed because the development server refused.
            from wama.common.services import mcp_client
            with self.subTest(user=getattr(user, 'username', 'visitor')), \
                    mock.patch.object(mcp_client, 'call_dev_tool',
                                      return_value={'job_id': 'j', 'jobs': []}) as relayed:
                self.assertNotEqual(200, self.client.get(reverse('common:operations')).status_code)
                self.assertNotEqual(200, self.client.get(reverse('common:api_operations_jobs')).status_code)
                self.assertNotEqual(200, self.client.post(reverse('common:api_operations_run'),
                                                          {'operation': 'check_docs'}).status_code)
                relayed.assert_not_called()

    def test_the_menu_carries_it_in_the_administration_section(self):
        from wama.common.services.navigation import account_menu
        admin_section = next(s for s in account_menu(self.admin) if s['key'] == 'admin')
        self.assertIn('Exploitation', [p['label'] for p in admin_section['pages']])
        self.assertNotIn('admin', [s['key'] for s in account_menu(self.dev)])

    def test_the_routes_relay_to_the_development_server(self):
        """The web server never imports the development tools: it relays (`mcp_client`)."""
        from wama.common.services import dev_inspect, mcp_client
        self.client.force_login(self.admin)
        with mock.patch.object(mcp_client, 'call_dev_tool', return_value={'job_id': 'j'}) as relayed:
            ran = self.client.post(reverse('common:api_operations_run'),
                                   {'operation': 'tests', 'argument': 'wama.common.tests.tests_operations'})
        self.assertEqual((200, {'job_id': 'j'}), (ran.status_code, ran.json()))
        self.assertEqual(('dev_run_operation', {'operation': 'tests',
                                                'argument': 'wama.common.tests.tests_operations'}),
                         relayed.call_args.args[1:])
        with mock.patch.object(mcp_client, 'call_dev_tool', return_value={'error': 'refusé'}):
            self.assertEqual(400, self.client.post(reverse('common:api_operations_run'),
                                                   {'operation': 'x'}).status_code)
        jobs = {'jobs': [{'id': 'a', 'tool': dev_inspect.OPERATION_TOOL + 'check_docs', 'status': 'done'},
                         {'id': 'b', 'tool': 'role:librarian', 'status': 'done'}]}
        with mock.patch.object(mcp_client, 'call_dev_tool', return_value=jobs):
            listed = self.client.get(reverse('common:api_operations_jobs')).json()
        self.assertEqual(['a'], [j['id'] for j in listed['jobs']], 'its own jobs only')
        # What the tile says comes from the declaration, not from the script.
        self.assertEqual((operations.OPERATIONS['check_docs']['label'], 'Terminée', 'success'),
                         tuple(listed['jobs'][0][k] for k in ('label', 'state_label', 'tone')))
        self.assertNotIn('dev_tools', (ROOT / 'wama' / 'common' / 'views.py').read_text(encoding='utf-8'))

    def test_the_model_manager_page_no_longer_restarts_processes(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('model_manager:index')).content.decode()
        self.assertNotIn('processes-list', html)
        self.assertNotIn('controlProcess', html)
        self.assertIn(reverse('common:operations'), html, 'it says where the gesture went')
        self.assertIn('id="services-list"', html, 'counter-check: the services stay')


class NightlyReportsTest(SimpleTestCase):

    def test_the_last_reports_are_read_newest_first_with_what_did_not_answer(self):
        from wama.common.services import nightly_tests
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'logs' / 'nightly_tests'
            out.mkdir(parents=True)
            (out / 'nightly_20261101_010000.json').write_text(json.dumps({
                'generated_at': '2026-11-01T01:00:00', 'cadence': 'daily',
                'summary': {'total': 2, 'passed': 2, 'skipped': 0, 'failed': 0},
                'results': [{'ok': True, 'duration_s': 60}, {'ok': True, 'duration_s': 60}]}))
            (out / 'nightly_20261102_010000.json').write_text(json.dumps({
                'generated_at': '2026-11-02T01:00:00', 'cadence': 'weekly',
                'summary': {'total': 2, 'passed': 0, 'skipped': 0, 'failed': 2},
                'results': [{'ok': False, 'duration_s': 2400,
                             'detail': 'dépassé 2400 s sans rendre son verdict'},
                            {'ok': False, 'duration_s': 30, 'detail': 'AssertionError'}]}))
            (out / 'nightly_20261103_010000.json').write_text('{ not json')
            with mock.patch.object(nightly_tests.settings, 'BASE_DIR', folder):
                rows = nightly_tests.recent_reports()
        self.assertEqual(['nightly_20261102_010000.json', 'nightly_20261101_010000.json'],
                         [r['file'] for r in rows])
        self.assertEqual((2, 1, 40, 'weekly'),
                         (rows[0]['failed'], rows[0]['unanswered'], rows[0]['minutes'], rows[0]['cadence']))
        self.assertEqual((0, 0, 2), (rows[1]['failed'], rows[1]['unanswered'], rows[1]['minutes']))


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class ScriptsRenderPureListsTest(SimpleTestCase):

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval('var window = this; var WamaApp = {escapeHtml: function (t) {'
                     ' return String(t).replace(/</g, "&lt;"); }};')
        for script in ('wama-processes.js', 'wama-operations.js'):
            source = (JS / script).read_text(encoding='utf-8')
            self.assertEqual(source, (ROOT / 'staticfiles' / 'common' / 'js' / script).read_text(
                encoding='utf-8'), 'staticfiles/ en retard')
            self.v8.eval(source)

    def test_a_process_is_a_card_with_its_state_and_its_gesture(self):
        rows = json.dumps([{'key': 'gpu', 'label': 'Worker <gpu>', 'kind': 'worker', 'state': 'ok',
                            'state_label': 'En marche', 'tone': 'success', 'actions': ['restart'],
                            'when_off': 'Il finit sa tâche.'},
                           {'key': 'default', 'label': 'Worker default', 'kind': 'worker',
                            'state': 'restarting', 'state_label': 'Relance', 'tone': 'info', 'actions': []}])
        html = self.v8.eval(f'WamaProcesses._render({rows}, true)')
        self.assertEqual(2, html.count('class="ops-process '))
        self.assertIn('title="Il finit sa tâche."', html, 'what its restart cuts, said on the line')
        self.assertIn('Worker &lt;gpu>', html)
        self.assertIn('data-process="gpu"', html)
        self.assertNotIn('data-process="default"', html, 'no gesture offered while it restarts')
        self.assertNotIn('disabled', html)
        self.assertIn('disabled', self.v8.eval(f'WamaProcesses._render({rows}, false)'),
                      'no watchdog, no order')

    def test_the_jobs_say_their_state_and_an_empty_list_says_so(self):
        jobs = json.dumps([operations.job_row(
            {'id': '20261114-101010-abcdef', 'tool': 'operation:check_docs', 'status': 'running',
             'user': 'ada'}, 'operation:')])
        html = self.v8.eval(f'WamaOperations._renderJobs({jobs}, "Opération lancée")')
        self.assertIn(operations.OPERATIONS['check_docs']['label'], html)
        self.assertIn('En cours', html)
        self.assertIn('bg-info', html, 'the tone table of the processes')
        # A tile of the management pages: filtered, sorted and inspected by the common bricks.
        for piece in ('class="wama-cat-card', 'data-f-nature="Opération lancée"',
                      'data-f-etat="En cours"', 'data-s-since="20261114-101010-abcdef"'):
            self.assertIn(piece, html)
        self.assertIn('data-job="20261114-101010-abcdef"', html)
        self.assertIn('Aucune opération lancée', self.v8.eval('WamaOperations._renderJobs([])'))
