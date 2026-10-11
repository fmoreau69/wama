"""A model removed by `ollama rm` outside WAMA is marked uninstalled (2026-10-12).

Before, its row stayed « downloaded » — so the selector could pick it — until a `--clean` sync,
which marks unavailable EVERYTHING a discovery did not see. Only an answer of the Ollama
daemon proves a removal: a timeout, an error or the directory fallback never does.
"""
from datetime import timedelta
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from wama.model_manager.models import AIModel


def _ollama_row(name, **fields):
    defaults = dict(name=name, model_type='llm', source='ollama', is_downloaded=True)
    defaults.update(fields)
    return AIModel.objects.create(model_key=f'ollama:{name}', **defaults)


class DaemonListingIsRecordedTest(SimpleTestCase):

    def _discover(self, completed):
        from wama.model_manager.services import model_registry as mr
        registry = mr.ModelRegistry()
        saved = dict(registry._models)
        registry._models.clear()
        registry.ollama_listed = None
        try:
            with mock.patch.object(mr.subprocess, 'run', return_value=completed), \
                    mock.patch.object(mr.ModelRegistry, '_ollama_charges', return_value={}), \
                    mock.patch.object(mr.ModelRegistry, '_ollama_capacites', return_value={}), \
                    mock.patch.object(mr.ModelRegistry, '_ollama_fiche', return_value={}), \
                    mock.patch.object(mr.ModelRegistry, '_discover_ollama_from_directory') as scan:
                registry._discover_ollama_models()
            return registry.ollama_listed, scan
        finally:
            registry._models.clear()
            registry._models.update(saved)
            registry.ollama_listed = None

    def test_an_answer_of_the_daemon_is_recorded_without_runner_manifests(self):
        listing = ("NAME            ID              SIZE      MODIFIED\n"
                   "qwen3.5:4b      96f38c742e0a    3.4 GB    4 days ago\n"
                   f"llamacpp:{'a' * 64}  96f38c742e0a    3.4 GB    4 days ago\n")
        listed, _ = self._discover(mock.Mock(returncode=0, stdout=listing))
        self.assertEqual({'qwen3.5:4b'}, listed)

    def test_an_empty_answer_is_an_answer_and_the_disk_does_not_contradict_it(self):
        listed, scan = self._discover(mock.Mock(returncode=0, stdout="NAME ID SIZE MODIFIED\n"))
        self.assertEqual(set(), listed)
        scan.assert_not_called()

    def test_no_answer_is_no_proof(self):
        listed, scan = self._discover(mock.Mock(returncode=1, stdout='', stderr='could not connect'))
        self.assertIsNone(listed)
        scan.assert_called_once()


class MarkRemovedOutsideTest(TestCase):

    def test_an_unlisted_downloaded_row_is_marked_and_the_rest_is_left(self):
        from wama.model_manager.services.model_sync import ModelSyncService
        kept = _ollama_row('qwen3.5:4b')
        removed = _ollama_row('gemma4:12b')
        already = _ollama_row('old:latest', is_downloaded=False)
        proposed = AIModel.objects.create(model_key='proposed:ollama:x:latest', name='x',
                                          model_type='llm', source='ollama', is_proposed=True,
                                          is_downloaded=True)
        seen_at = timezone.now() + timedelta(seconds=1)
        marked = ModelSyncService._mark_ollama_removed_outside({'qwen3.5:4b'}, seen_at)
        self.assertEqual(['ollama:gemma4:12b'], marked)
        removed.refresh_from_db()
        self.assertFalse(removed.is_downloaded)
        self.assertIn('uninstalled_at', removed.extra_info)
        for row in (kept, proposed):
            row.refresh_from_db()
            self.assertTrue(row.is_downloaded, row.model_key)
        already.refresh_from_db()
        self.assertNotIn('uninstalled_at', already.extra_info or {})

    def test_a_row_touched_after_the_listing_is_left(self):
        """An install that finished after the daemon was asked: the listing is older."""
        from wama.model_manager.services.model_sync import ModelSyncService
        seen_at = timezone.now() - timedelta(minutes=5)
        fresh = _ollama_row('just-pulled:latest')
        self.assertEqual([], ModelSyncService._mark_ollama_removed_outside(set(), seen_at))
        fresh.refresh_from_db()
        self.assertTrue(fresh.is_downloaded)


class FullSyncReadsOnlyTheDaemonTest(TestCase):

    def _full_sync(self, listed):
        from wama.model_manager.services.model_sync import ModelSyncService
        registry = mock.Mock(discovery_errors=[], ollama_listed=listed, _models={})
        registry.discover_all_models.return_value = {}
        service = ModelSyncService()
        with mock.patch.object(service, '_get_registry', return_value=registry), \
                mock.patch.object(ModelSyncService, 'persist_weights', return_value=0):
            service.full_sync()

    def test_with_a_daemon_answer_the_removed_model_is_marked(self):
        row = _ollama_row('gemma4:12b')
        AIModel.objects.filter(pk=row.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        self._full_sync(set())
        row.refresh_from_db()
        self.assertFalse(row.is_downloaded)

    def test_without_a_daemon_answer_nothing_is_marked(self):
        row = _ollama_row('gemma4:12b')
        AIModel.objects.filter(pk=row.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        self._full_sync(None)
        row.refresh_from_db()
        self.assertTrue(row.is_downloaded)
