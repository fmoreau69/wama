"""The versioned manifest corpus follows the registries hot through ONE door (2026-10-12).

Three gestures rewrite a corpus manifest while WAMA runs — install (`provenance`), validating a
role's proposal (`proposals.apply`), uninstall (`forget_in_corpus`) — and each called
`manifest_export` its own way. A test database replays them on keys that exist in the real
corpus (`synthesizer:bark`): the runner switches the door off, as it redirects `MEDIA_ROOT`.
Here: the door, the harness switch, and no writer around the door.
"""
import ast
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.manifests.corpus import SWITCHED_OFF, follow
from wama.model_manager.models import AIModel


class CorpusDoorTest(SimpleTestCase):

    def test_the_test_runner_switches_the_door_off(self):
        self.assertFalse(getattr(settings, 'MANIFEST_CORPUS_SYNC', True),
                         "the runner must switch the corpus off, or a test writes `manifests/`")

    def test_switched_off_it_writes_nothing(self):
        with mock.patch('django.core.management.call_command') as export:
            self.assertEqual(SWITCHED_OFF, follow('synthesizer:bark'))
        export.assert_not_called()

    @override_settings(MANIFEST_CORPUS_SYNC=True)
    def test_switched_on_it_runs_the_export_at_the_key_and_kind(self):
        with mock.patch('django.core.management.call_command') as export:
            self.assertEqual('écrit', follow('reader', kind='app'))
        export.assert_called_once_with('manifest_export', 'reader', kind='app', verbosity=0)

    @override_settings(MANIFEST_CORPUS_SYNC=True)
    def test_a_failure_is_raised_to_the_caller_who_keeps_its_policy(self):
        with mock.patch('django.core.management.call_command', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                follow('huggingface:Org/X')


class AppManifestFollowsItsModelsTest(TestCase):
    """2026-11-02 (Fabien: « c'est en double sens, une correction des applications doit être
    projetée dans le manifeste aussi »). Uninstalling olmOCR v1 removed its manifest while the
    Reader's kept requiring it — and listing the Reader's models by SOURCE alone left out
    olmOCR-2, a `huggingface:` row it proposes, with the libraries it needs."""

    def _row(self, key, source, **kw):
        return AIModel.objects.create(model_key=key, name=key, model_type='ocr', source=source,
                                      **kw)

    def _facet(self, proposed):
        from wama.common.manifests.builtin.app import _models
        with mock.patch('wama.common.utils.param_schema.catalog_choice_keys',
                        return_value=[({'name': 'backend'}, proposed)]):
            return (_models('reader') or {}).get('catalog_keys')

    def test_the_facet_is_its_rows_left_installed_plus_what_it_proposes(self):
        self._row('reader:stage', 'reader')                       # internal step: no select
        self._row('reader:old', 'reader', is_downloaded=False,
                  extra_info={'uninstalled_at': '2026-11-02T11:01:05'})
        self._row('huggingface:org/proposed', 'huggingface')
        # Uninstalled but left in the choices (reinstalled on demand): its manifest leaves the
        # corpus (`_gone_model_keys`), so no app may require it.
        self._row('huggingface:org/on-demand', 'huggingface', is_downloaded=False,
                  extra_info={'uninstalled_at': '2026-10-29T10:00:00'})
        self.assertEqual(['huggingface:org/proposed', 'reader:stage'],
                         self._facet(['huggingface:org/proposed', 'huggingface:org/on-demand']))

    def test_counter_proof_a_row_never_installed_is_not_an_uninstalled_one(self):
        """A catalogue row without weights is still the app's: only the uninstall MARK removes it."""
        self._row('reader:not-yet', 'reader', is_downloaded=False)
        self.assertEqual(['reader:not-yet'], self._facet([]))

    @override_settings(MANIFEST_CORPUS_SYNC=True)
    def test_a_model_followed_sends_its_apps_to_the_background_once_committed(self):
        """The uninstall button waits for its answer: the apps follow in a task."""
        with mock.patch('django.core.management.call_command') as export, \
                mock.patch('wama.model_manager.tasks.follow_apps_in_corpus_task.delay') as task, \
                self.captureOnCommitCallbacks(execute=True):
            follow('reader:olmocr')
            task.assert_not_called()                  # not before the transaction is committed
        export.assert_called_once_with('manifest_export', 'reader:olmocr', kind='model',
                                       verbosity=0)
        task.assert_called_once_with('reader:olmocr')

    @override_settings(MANIFEST_CORPUS_SYNC=True)
    def test_the_task_re_exports_the_apps_concerned(self):
        from wama.common.manifests.corpus import follow_apps
        from wama.model_manager.tasks import follow_apps_in_corpus_task
        with mock.patch('wama.common.manifests.corpus.apps_concerned', return_value=['reader']), \
                mock.patch('django.core.management.call_command') as export:
            self.assertEqual({'model': 'reader:olmocr', 'apps': ['reader']},
                             follow_apps_in_corpus_task('reader:olmocr'))
        export.assert_called_once_with('manifest_export', 'reader', kind='app', verbosity=0)
        with override_settings(MANIFEST_CORPUS_SYNC=False), \
                mock.patch('wama.common.manifests.corpus.apps_concerned') as concerned:
            self.assertEqual([], follow_apps('reader:olmocr'), 'the harness switch holds')
        concerned.assert_not_called()

    def test_the_apps_concerned_are_those_citing_it_or_due_to_cite_it(self):
        import json
        import tempfile
        from wama.common.manifests.corpus import apps_concerned
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'manifests' / 'apps'
            folder.mkdir(parents=True)
            (folder / 'reader.json').write_text(json.dumps(
                {'requires': [{'kind': 'model', 'key': 'reader:olmocr'}]}), encoding='utf-8')
            listed = {'transcriber': {'catalog_keys': ['huggingface:org/asr']}}
            with override_settings(BASE_DIR=tmp), \
                    mock.patch('wama.common.manifests.builtin.app._models',
                               side_effect=lambda app_id: listed.get(app_id)):
                self.assertEqual(['reader'], apps_concerned('reader:olmocr'))
                self.assertEqual(['transcriber'], apps_concerned('huggingface:org/asr'))
                self.assertEqual([], apps_concerned('huggingface:org/elsewhere'))


def _writing_exports(path: Path) -> list:
    """Lines calling `call_command('manifest_export', …)` WITHOUT `--check` (a check writes nothing)."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (SyntaxError, UnicodeDecodeError):
        return []
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'call_command'
                or isinstance(node, ast.Call) and getattr(node.func, 'attr', None) == 'call_command'):
            continue
        if not (node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == 'manifest_export'):
            continue
        checks = any(isinstance(a, ast.Constant) and a.value == '--check' for a in node.args[1:]) \
            or any(k.arg == 'check' for k in node.keywords)
        if not checks:
            found.append(node.lineno)
    return found


class NoCorpusWriterAroundTheDoorTest(SimpleTestCase):
    """Production code reaches the corpus through `corpus.follow` only — tests call the command
    themselves with `out=` a temporary folder, and are left out."""

    DOOR = 'wama/common/manifests/corpus.py'

    def test_no_module_calls_the_export_itself(self):
        from wama.common.services.mecanismes_scan import python_modules
        base = Path(settings.BASE_DIR)
        offenders = []
        for rel in python_modules(base):
            name = rel.rsplit('/', 1)[-1]
            if rel == self.DOOR or name.startswith('tests') or '/tests/' in rel:
                continue
            offenders += [f'{rel}:{line}' for line in _writing_exports(base / rel)]
        self.assertEqual([], offenders, 'write the corpus through `manifests.corpus.follow`')

    def test_the_scanner_sees_a_writer(self):
        """Counter-check: a hand-written call is found, a `--check` one is not."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'writer.py'
            f.write_text("from django.core.management import call_command\n"
                         "call_command('manifest_export', 'k', kind='model')\n"
                         "call_command('manifest_export', '--check')\n", encoding='utf-8')
            self.assertEqual([2], _writing_exports(f))
