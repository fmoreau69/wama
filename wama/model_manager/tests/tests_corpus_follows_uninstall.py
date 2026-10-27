"""The manifest corpus follows the uninstall (2026-10-11, Fabien's decision).

The refresh of « already seeded » manifests rewrote the manifest of an UNINSTALLED row: five
OCR models removed on 11/10 entered the corpus the same day — two of them GGUF without their
image projector, a wrong composition for the few-shot that picks examples in that folder. A
key with no catalogue row stayed on disk forever (« extraction impossible »).
The archive is git history; an EXCLUDED row (decided, with its reason) keeps its manifest.
"""
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from wama.model_manager.models import AIModel


def _row(key, **fields):
    defaults = dict(name=key.split(':', 1)[1], model_type='ocr', source='huggingface',
                    is_downloaded=True)
    defaults.update(fields)
    return AIModel.objects.create(model_key=key, **defaults)


UNINSTALLED = {'is_downloaded': False, 'extra_info': {'uninstalled_at': '2026-10-11T01:41:46'}}


class GoneModelKeysTest(TestCase):

    def test_an_uninstalled_row_and_a_missing_row_leave_the_corpus(self):
        from wama.common.management.commands.manifest_export import _gone_model_keys
        _row('huggingface:Org/Removed', **UNINSTALLED)
        _row('huggingface:Org/Kept')
        gone = _gone_model_keys(['huggingface:Org/Removed', 'huggingface:Org/Kept',
                                 'reader:no-such-row'])
        self.assertEqual({'huggingface:Org/Removed', 'reader:no-such-row'}, gone)

    def test_an_excluded_row_keeps_its_manifest(self):
        """`is_available=False` + `exclusion`: a human decision with its reason — knowledge."""
        from wama.common.management.commands.manifest_export import _gone_model_keys
        _row('anonymizer:excluded', is_available=False,
             extra_info={'exclusion': {'date': '2026-08-12', 'raison': 'measured'}})
        self.assertEqual(set(), _gone_model_keys(['anonymizer:excluded']))

    def test_a_row_that_lost_its_mark_is_back_in_the_enumeration(self):
        """An app-declared row loses `uninstalled_at` at the next sync and is « not downloaded »
        again — installable, so declared knowledge again; only the mark takes a row out."""
        from wama.common.management.commands.manifest_export import _model_keys
        _row('composer:declared', is_downloaded=False)
        _row('huggingface:Org/Removed', **UNINSTALLED)
        keys = _model_keys()
        self.assertIn('composer:declared', keys)
        self.assertNotIn('huggingface:Org/Removed', keys)


class ExportRemovesGoneManifestsTest(TestCase):

    def _seed(self, out, key):
        from wama.common.management.commands.manifest_export import _nom_fichier
        f = Path(out) / f"{_nom_fichier(key)}.json"
        f.write_text('{}\n', encoding='utf-8')
        return f

    def test_the_explicit_key_export_removes_an_uninstalled_manifest(self):
        _row('huggingface:Org/Removed', **UNINSTALLED)
        with tempfile.TemporaryDirectory() as out:
            f = self._seed(out, 'huggingface:Org/Removed')
            call_command('manifest_export', 'huggingface:Org/Removed', kind='model', out=out,
                         verbosity=0, stdout=mock.MagicMock())
            self.assertFalse(f.exists())

    def test_a_key_without_a_row_is_removed_too(self):
        with tempfile.TemporaryDirectory() as out:
            f = self._seed(out, 'reader:no-such-row')
            call_command('manifest_export', 'reader:no-such-row', kind='model', out=out,
                         verbosity=0, stdout=mock.MagicMock())
            self.assertFalse(f.exists())

    def test_check_reports_it_and_removes_nothing(self):
        _row('huggingface:Org/Removed', **UNINSTALLED)
        with tempfile.TemporaryDirectory() as out:
            f = self._seed(out, 'huggingface:Org/Removed')
            with self.assertRaises(SystemExit):
                call_command('manifest_export', 'huggingface:Org/Removed', kind='model',
                             out=out, check=True, verbosity=0, stdout=mock.MagicMock())
            self.assertTrue(f.exists())

    def test_an_excluded_manifest_is_never_removed(self):
        """Counter-check: the excluded row exists — its file is re-read, not deleted."""
        _row('anonymizer:excluded', is_available=False,
             extra_info={'exclusion': {'date': '2026-08-12', 'raison': 'measured'}})
        with tempfile.TemporaryDirectory() as out:
            f = self._seed(out, 'anonymizer:excluded')
            call_command('manifest_export', 'anonymizer:excluded', kind='model', out=out,
                         verbosity=0, stdout=mock.MagicMock())
            self.assertTrue(f.exists())


class UninstallForgetsInCorpusTest(TestCase):

    def test_a_done_uninstall_hands_its_keys_to_the_corpus(self):
        from wama.model_manager.services.model_installer import uninstall_model
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            family = root / 'models' / 'ocr' / 'Fam'
            family.mkdir(parents=True)
            _row('huggingface:Org/Gone', platform_ref='huggingface:Org/Gone',
                 local_path=str(family / 'models--Org--Gone'))
            with override_settings(AI_MODELS_DIR=root), mock.patch(
                    'wama.model_manager.services.model_installer.forget_in_corpus') as forget:
                res = uninstall_model('huggingface:Org/Gone')
        self.assertTrue(res['ok'], res)
        forget.assert_called_once_with(['huggingface:Org/Gone'])

    def test_a_refused_uninstall_touches_nothing(self):
        from wama.model_manager.services.model_installer import uninstall_model
        _row('huggingface:Org/Loaded', is_loaded=True)
        with mock.patch('wama.model_manager.services.model_installer.forget_in_corpus') as forget:
            res = uninstall_model('huggingface:Org/Loaded')
        self.assertFalse(res['ok'])
        forget.assert_not_called()

    def test_the_test_runner_switches_the_corpus_off(self):
        """A test database uninstalls keys that exist in the REAL corpus (`synthesizer:bark`):
        the runner turns the sync off, so the versioned file can never be deleted by a test."""
        from wama.model_manager.services.model_installer import forget_in_corpus
        with mock.patch('django.core.management.call_command') as export:
            forget_in_corpus(['synthesizer:bark'])
        export.assert_not_called()

    def test_switched_on_it_runs_the_export_at_the_key(self):
        from wama.model_manager.services.model_installer import forget_in_corpus
        with override_settings(MANIFEST_CORPUS_SYNC=True), \
                mock.patch('django.core.management.call_command') as export:
            forget_in_corpus(['huggingface:Org/Gone'])
        export.assert_called_once_with('manifest_export', 'huggingface:Org/Gone',
                                       kind='model', verbosity=0)
