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
from django.test import SimpleTestCase, override_settings

from wama.common.manifests.corpus import SWITCHED_OFF, follow


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
