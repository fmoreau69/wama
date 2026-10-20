"""What a Django START costs, and the app-generation chain that pays it (2026-10-20).

Measured under WSL that day: `django.setup()` took 58-63 s. Registering the nightly UI scenarios
resolved each app's index (`reverse`), which loaded the WHOLE URL configuration — the views, tasks
and backends of every app, torch, ultralytics and cv2 with them —; the Studio's registration
imported `generic_runner`, which derives every app's ports at import (7.5 s); the CUDA cap
imported torch in every process; `model_manager.services` imported its twenty modules on any
submodule import. Gunicorn, every worker, every command and every test run paid it, and the
sandbox chain paid it about thirty times per twin (`app_sandbox`: three judge processes per
substitution). After: `django.setup()` 11 s, one judge process per substitution, one command
process per chain.
"""
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from wama.common.management.commands import app_sandbox as cmd_sandbox
from wama.common.services import nightly_tests

ROOT = Path(settings.BASE_DIR)

#: What a fresh process holds right after `django.setup()`.
SETUP_PROBE = r'''
import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django
django.setup()
heavy = [m for m in ('torch', 'ultralytics', 'cv2', 'transformers', 'diffusers') if m in sys.modules]
views = [m for m in sys.modules if m.startswith('wama.') and m.endswith('.views')]
print('HEAVY', ','.join(heavy))
print('URLCONF', 'wama.urls' in sys.modules)
print('VIEWS', len(views))
print('GENERIC_RUNNER', 'wama.studio.services.generic_runner' in sys.modules)
'''


class DjangoSetupStaysLightTest(SimpleTestCase):
    """A fresh `django.setup()` loads neither the URL configuration nor a heavy ML library."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        run = subprocess.run([sys.executable, '-c', SETUP_PROBE], capture_output=True, text=True,
                             cwd=str(ROOT), timeout=600)
        cls.lines = dict(line.split(' ', 1) for line in run.stdout.splitlines()
                         if line.split(' ', 1)[0] in ('HEAVY', 'URLCONF', 'VIEWS', 'GENERIC_RUNNER'))
        cls.error = run.stderr[-2000:]

    def test_setup_imports_no_heavy_ml_library(self):
        self.assertIn('HEAVY', self.lines, self.error)
        self.assertEqual('', self.lines['HEAVY'].strip())

    def test_setup_does_not_load_the_url_configuration(self):
        self.assertEqual('False', self.lines.get('URLCONF'), self.error)
        self.assertEqual('0', self.lines.get('VIEWS'), self.error)

    def test_setup_does_not_derive_the_studio_ports(self):
        self.assertEqual('False', self.lines.get('GENERIC_RUNNER'), self.error)


class NightlyRegistryLoadsOnFirstReadTest(SimpleTestCase):
    """Apps DECLARE their registrars in `ready()`; the registry plays them on its first read."""

    def setUp(self):
        self.saved = (nightly_tests.REGISTRY, list(nightly_tests._REGISTRARS), nightly_tests._loading)
        nightly_tests.REGISTRY = nightly_tests._Registry()
        nightly_tests._REGISTRARS[:] = []
        nightly_tests._loading = False

    def tearDown(self):
        nightly_tests.REGISTRY, registrars, nightly_tests._loading = self.saved
        nightly_tests._REGISTRARS[:] = registrars

    @staticmethod
    def _witness(ident):
        def registrar():
            nightly_tests.register(id=ident, app='t', stage='ui', description=ident,
                                   run=lambda ctx: (True, ''))
        return registrar

    def test_a_declared_registrar_runs_only_when_the_registry_is_read(self):
        calls = []
        nightly_tests.add_registrar(lambda: calls.append(1))
        self.assertEqual([], calls, 'declaring must not run it')
        len(nightly_tests.REGISTRY)
        self.assertEqual([1], calls)
        list(nightly_tests.REGISTRY)
        self.assertEqual([1], calls, 'played once')

    def test_every_reader_sees_the_scenarios(self):
        nightly_tests.add_registrar(self._witness('t.a'))
        self.assertIn('t.a', {s.id for s in nightly_tests.REGISTRY})
        self.assertEqual(['t.a'], [s.id for s in nightly_tests.select_scenarios(app='t')])

    def test_a_dotted_registrar_is_imported_at_load_time_only(self):
        with mock.patch.object(nightly_tests.importlib, 'import_module',
                               wraps=nightly_tests.importlib.import_module) as imported:
            nightly_tests.add_registrar('wama.common.tests.tests_boot_cost:_dotted_registrar')
            imported.assert_not_called()
            ids = {s.id for s in nightly_tests.REGISTRY}
        self.assertIn('t.dotted', ids)

    def test_a_failing_registrar_does_not_deprive_the_others(self):
        def broken():
            raise RuntimeError('boom')
        nightly_tests.add_registrar(broken)
        nightly_tests.add_registrar('wama.no_such_module:nothing')
        nightly_tests.add_registrar(self._witness('t.survivor'))
        with self.assertLogs(nightly_tests.logger, 'WARNING'):
            ids = {s.id for s in nightly_tests.REGISTRY}
        self.assertIn('t.survivor', ids)

    def test_a_registrar_declared_after_loading_runs_at_once(self):
        list(nightly_tests.REGISTRY)
        nightly_tests.add_registrar(self._witness('t.late'))
        self.assertIn('t.late', {s.id for s in nightly_tests.REGISTRY})

    def test_a_plain_list_put_in_place_by_a_test_stays_isolated(self):
        calls = []
        nightly_tests.add_registrar(lambda: calls.append(1))
        nightly_tests.REGISTRY = []
        self._witness('t.only')()
        self.assertEqual(['t.only'], [s.id for s in nightly_tests.select_scenarios()])
        self.assertEqual([], calls)


def _dotted_registrar():
    nightly_tests.register(id='t.dotted', app='t', stage='ui', description='t.dotted',
                           run=lambda ctx: (True, ''))


class CudaCapFollowsTorchTest(SimpleTestCase):
    """The CUDA allocator cap is set the moment torch is imported — never skipped, never paid by a
    process that does not import it."""

    PROBE = r'''
import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django
django.setup()
from wama.common.services import resource_governor as rg
calls = []
rg.configure_cuda_process = lambda: calls.append('cap') or False
hooked = any(type(f).__name__ == '_CapWhenTorchLoads' for f in sys.meta_path)
print('BEFORE', 'torch' in sys.modules, hooked, calls)
try:
    import torch  # noqa: F401
except ImportError:
    print('NO_TORCH')
    raise SystemExit(0)
print('AFTER', calls, any(type(f).__name__ == '_CapWhenTorchLoads' for f in sys.meta_path))
'''

    def test_the_cap_is_set_when_torch_loads_and_the_hook_leaves(self):
        run = subprocess.run([sys.executable, '-c', self.PROBE], capture_output=True, text=True,
                             cwd=str(ROOT), timeout=600)
        out = run.stdout
        self.assertIn('BEFORE False True []', out, run.stderr[-2000:])
        if 'NO_TORCH' in out:
            self.skipTest('torch absent de ce venv')
        self.assertIn("AFTER ['cap'] False", out)

    def test_torch_already_loaded_gets_the_cap_at_once(self):
        from wama.common.services import resource_governor as rg
        calls = []
        with mock.patch.object(rg, 'configure_cuda_process', side_effect=lambda: calls.append(1)), \
             mock.patch.dict(sys.modules, {'torch': mock.MagicMock()}):
            rg.configure_cuda_process_when_torch_loads()
        self.assertEqual([1], calls)


class ModelManagerServicesLoadOnDemandTest(SimpleTestCase):
    """`wama.model_manager.services` imports a module only when one of its names is used."""

    def test_every_exported_name_resolves_and_is_mapped(self):
        """Every name of `__all__` is served, and every served name resolves — the eager
        `__init__` also bound two names it did not list (`QUALITY_PRESETS`, `QUALITY_DEFAULT`)."""
        import wama.model_manager.services as services
        self.assertEqual([], sorted(set(services.__all__) - set(services._MODULE_OF)))
        for name in services._MODULE_OF:
            with self.subTest(name=name):
                self.assertIsNotNone(getattr(services, name))

    def test_an_unknown_name_is_an_attribute_error(self):
        import wama.model_manager.services as services
        with self.assertRaises(AttributeError):
            services.no_such_name  # noqa: B018


class OneJudgeProcessPerSubstitutionTest(SimpleTestCase):
    """`check`, the page and the populated queue run in ONE fresh process (`_judge`)."""

    def test_the_stage_is_read_from_the_last_announcement(self):
        done = subprocess.CompletedProcess([], 1, 'JUDGE-STAGE check\nJUDGE-STAGE page\n404\n', '')
        self.assertEqual('page', cmd_sandbox._judge_stage(done))
        self.assertEqual('boot', cmd_sandbox._judge_stage(subprocess.CompletedProcess([], 1, '', 'x')))

    def test_the_script_parses(self):
        compile(cmd_sandbox._JUDGE_SCRIPT, '_JUDGE_SCRIPT', 'exec')

    def _substitute(self, judge_result, target='tasks'):
        import io
        from tempfile import TemporaryDirectory
        saved = []
        ok = subprocess.CompletedProcess([], 0, 'No changes detected', '')
        with TemporaryDirectory() as d:
            (Path(d) / 'jumelle_00' / 'migrations').mkdir(parents=True)
            entry = {'label': 'jumelle_00', 'generated_from': 'appfictive', 'substituted': {},
                     'stage': 'S1'}
            with mock.patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)), \
                 mock.patch.object(cmd_sandbox, 'load_registry', return_value=[entry]), \
                 mock.patch.object(cmd_sandbox, '_save_entry', side_effect=saved.append), \
                 mock.patch.object(cmd_sandbox, '_manage', return_value=ok) as manage, \
                 mock.patch.object(cmd_sandbox, '_judge', return_value=judge_result) as judge, \
                 mock.patch.dict(cmd_sandbox._SUBSTITUTABLE,
                                 {target: (f'{target}.py', 'wama.common.tests.tests_sandbox_coherence',
                                           '_render_stub_tasks')}), \
                 mock.patch('wama.common.manifests.ingest.extract',
                            return_value={'key': 'appfictive', 'body': {}}):
                cmd = cmd_sandbox.Command()
                cmd.stdout = cmd.stderr = io.StringIO()
                cmd._substitute('jumelle_00', target)
        return saved[-1]['substituted'][target], judge, manage

    def test_a_substitution_starts_one_judge_and_no_separate_check(self):
        verdict, judge, manage = self._substitute(subprocess.CompletedProcess([], 0, '200', ''))
        self.assertEqual('ok', verdict['verdict'])
        judge.assert_called_once()
        self.assertTrue(judge.call_args.kwargs.get('run_check'))
        manage.assert_not_called()

    def test_a_failing_page_is_named_and_reverted(self):
        failed = subprocess.CompletedProcess([], 1, 'JUDGE-STAGE check\nJUDGE-STAGE page\n404\n', '')
        verdict, _judge, _manage = self._substitute(failed)
        self.assertEqual('revert', verdict['verdict'])
        self.assertTrue(any('smoke /jumelle_00/ KO' in d for d in verdict['details']), verdict)

    def test_models_keeps_check_before_makemigrations(self):
        verdict, judge, manage = self._substitute(subprocess.CompletedProcess([], 0, '200', ''),
                                                  target='models')
        self.assertEqual(['check'], manage.call_args_list[0].args[0])
        self.assertFalse(judge.call_args.kwargs.get('run_check'))


class SubstitutionChainTest(SimpleTestCase):
    """One command plays a whole chain; a reverted group is replayed once if a LATER group held."""

    def _chain(self, outcomes):
        import io
        played = []
        registry = {'label': 'jumelle_00', 'substituted': {}}

        def substitute(label, group):
            played.append(group)
            result = outcomes[group].pop(0)
            if result == 'rien':
                raise CommandError(f'Gabarit {group} : rien à générer — test')
            for target in group.split('+'):
                registry['substituted'][target] = {'verdict': result}

        cmd = cmd_sandbox.Command()
        cmd.stdout = cmd.stderr = io.StringIO()
        with mock.patch.object(cmd, '_substitute', side_effect=substitute), \
             mock.patch.object(cmd_sandbox, 'load_registry', return_value=[registry]):
            cmd._substitute_chain('jumelle_00', ','.join(outcomes))
        return played, cmd.stdout.getvalue()

    def test_a_group_unblocked_by_a_later_one_is_replayed(self):
        played, out = self._chain({'tasks': ['revert', 'ok'], 'surfaces': ['rien'],
                                   'tasks+function_specs': ['ok'], 'models': ['revert']})
        self.assertEqual(['tasks', 'surfaces', 'tasks+function_specs', 'models', 'tasks'], played)
        self.assertIn('tasks=ok', out)
        self.assertIn('surfaces=rien', out)
        self.assertIn('models=revert', out, 'nothing held after it: not replayed')
