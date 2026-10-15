"""
Le rôle `task` de wama-dev-ai (2026-10-15) — ses contrôles MÉCANIQUES, seuls garants d'une
proposition écrite par un modèle : périmètre de lecture, unicité de chaque `old`, fichier
résultant lisible, citations adossées à une ligne réelle, et application qui REFAIT tout.

Chargé par chemin, comme `tests_dev_ai_bridge` (`wama-dev-ai` n'est pas importable).
"""
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from wama.common.tests.tests_dev_ai_bridge import _charger as load_dev_ai_module


class TaskRoleChecksTest(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.task = load_dev_ai_module('run_task')

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._saved_root = self.task.REPO_ROOT
        self.task.REPO_ROOT = self.root
        (self.root / 'pkg').mkdir()
        (self.root / 'pkg' / 'mod.py').write_text(
            "def total(values):\n    return sum(values)\n\n\ndef first(values):\n"
            "    return values[0]\n", encoding='utf-8')

    def tearDown(self):
        self.task.REPO_ROOT = self._saved_root
        self._tmp.cleanup()

    def _scope(self, spec='pkg/mod.py'):
        return self.task.parse_scope(spec)

    def test_a_unique_edit_is_applied_in_memory_and_diffed(self):
        proposal = {'edits': [{'path': 'pkg/mod.py', 'old': '    return values[0]',
                               'new': '    return values[0] if values else None'}]}
        concerns, results = self.task.check_edits(proposal, self._scope())
        self.assertEqual([], concerns)
        diff = self.task.unified(results)
        self.assertIn('+    return values[0] if values else None', diff)
        # Rien n'est écrit sur le disque par le contrôle.
        self.assertIn('    return values[0]\n', (self.root / 'pkg' / 'mod.py').read_text())

    def test_an_ambiguous_or_missing_old_is_refused(self):
        for old, count in (('    return ', 2), ('return nothing', 0)):
            with self.subTest(old=old):
                concerns, _ = self.task.check_edits(
                    {'edits': [{'path': 'pkg/mod.py', 'old': old, 'new': 'x'}]}, self._scope())
                self.assertTrue(any(f'trouvé {count} fois' in c for c in concerns), concerns)

    def test_an_edit_that_breaks_the_syntax_is_refused(self):
        concerns, _ = self.task.check_edits(
            {'edits': [{'path': 'pkg/mod.py', 'old': 'def first(values):',
                        'new': 'def first(values'}]}, self._scope())
        self.assertTrue(any('ne se lit plus' in c for c in concerns), concerns)

    def test_an_edit_outside_the_shown_files_or_on_a_migration_is_refused(self):
        (self.root / 'pkg' / 'migrations').mkdir()
        (self.root / 'pkg' / 'migrations' / '0001_x.py').write_text('A = 1\n', encoding='utf-8')
        concerns, _ = self.task.check_edits(
            {'edits': [{'path': 'pkg/other.py', 'old': 'a', 'new': 'b'},
                       {'path': 'pkg/migrations/0001_x.py', 'old': 'A = 1', 'new': 'A = 2'}]},
            self._scope('pkg/mod.py,pkg/migrations/0001_x.py'))
        self.assertTrue(any('non montré' in c for c in concerns), concerns)
        self.assertTrue(any("ne s'écrit pas" in c for c in concerns), concerns)

    def test_secrets_and_paths_outside_the_repo_are_never_read(self):
        (self.root / '.env').write_text('SECRET=1\n', encoding='utf-8')
        for spec in ('.env', '../outside.py', 'pkg/missing.py'):
            with self.subTest(spec=spec):
                with self.assertRaises(self.task.TaskRefused):
                    self.task.parse_scope(spec)

    def test_a_range_shows_only_its_lines(self):
        text = self.task.numbered(self._scope('pkg/mod.py:5-6')[0])
        self.assertIn('    5| def first(values):', text)
        self.assertNotIn('def total', text)

    def test_a_citation_must_name_a_real_line_carrying_the_quote(self):
        scope = self._scope()
        good = {'citations': [{'path': 'pkg/mod.py', 'line': 2, 'quote': 'return sum(values)'}]}
        self.assertEqual([], self.task.check_citations(good, scope))
        bad = {'citations': [{'path': 'pkg/mod.py', 'line': 1, 'quote': 'return sum(values)'},
                             {'path': 'pkg/mod.py', 'line': 99, 'quote': ''}]}
        concerns = self.task.check_citations(bad, scope)
        self.assertEqual(2, len(concerns), concerns)

    def _proposal_file(self):
        out = self.root / 'task_out.json'
        out.write_text(json.dumps({
            'status': 'PENDING_HUMAN_VALIDATION', 'role': 'task', 'mode': 'write',
            'files': [{'path': 'pkg/mod.py', 'start': None, 'end': None}],
            'proposal': {'edits': [{'path': 'pkg/mod.py', 'old': '    return sum(values)',
                                    'new': '    return sum(values or ())'}]}}), encoding='utf-8')
        return out

    def test_apply_rechecks_against_the_file_as_it_is_now(self):
        out = self._proposal_file()
        # Le fichier a bougé depuis la proposition : rien n'est écrit.
        (self.root / 'pkg' / 'mod.py').write_text('def total(values):\n    return 0\n',
                                                  encoding='utf-8')
        with self.assertRaises(self.task.TaskRefused):
            self.task.apply_output(str(out))
        self.assertEqual('PENDING_HUMAN_VALIDATION', json.loads(out.read_text())['status'])

    def test_apply_writes_then_marks_the_proposal_applied_once(self):
        out = self._proposal_file()
        self.task.apply_output(str(out))
        self.assertIn('sum(values or ())', (self.root / 'pkg' / 'mod.py').read_text())
        self.assertEqual('APPLIED', json.loads(out.read_text())['status'])
        with self.assertRaises(self.task.TaskRefused):
            self.task.apply_output(str(out))


class TaskRoleOnTheDevSurfaceTest(SimpleTestCase):
    """La surface (assistant, Discord, MCP) lance le rôle ; elle ne peut pas l'APPLIQUER."""

    def test_the_surface_admits_task_files_write_and_never_apply(self):
        from wama.common.services.dev_tools import DevToolError, role_command
        argv = role_command('task', {'task': 'où est X ?', 'files': 'wama/a.py', 'write': True})
        self.assertEqual(['--task', 'où est X ?', '--files', 'wama/a.py', '--write'], argv[2:])
        with self.assertRaises(DevToolError):
            role_command('task', {'apply': 'wama-dev-ai/outputs/task_x.json'})
