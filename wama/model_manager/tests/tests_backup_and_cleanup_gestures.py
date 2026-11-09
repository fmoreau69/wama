"""Two buttons of the model manager that failed in silence, found while giving the page's gestures to
the assistant (2026-11-09, Fabien : « si elles existent, l'assistant doit pouvoir les utiliser »).

1. « Backup selected » sends the model's CATALOGUE KEY as `source_path` (`index.html`) ; the view took
   it for a path : « Source file not found », every time — the defect `resolve_weight_file` closed for
   « Convertir » on 2026-08-31. The body (`remote_backup.backup_model`) now resolves the key to the
   model's whole location, and the view and the tool `start_backup` read it.
2. « Clean Idle » and « Aggressive » unloaded in THEIR process only — gunicorn, which holds no model.
   A HUMAN gesture now goes through the tenants' channel (`unload_resident`, the « Décharger »
   button's since 2026-11-03) ; the automatic callers (the cleaner's loop, `nightly_tests`,
   `cam_analyzer`) keep to their process : unloading the others' models without consent is excluded
   (decision B1, 2026-09-20).
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.model_manager.services import remote_backup as RB
from wama.model_manager.services.memory_cleaner import WAMAMemoryCleaner


class BackupResolvesTheCatalogueKeyTest(TestCase):

    def setUp(self):
        from wama.model_manager.models import AIModel
        self.folder = Path(tempfile.mkdtemp(prefix='wama_backup_key_'))
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        (self.folder / 'weights.safetensors').write_bytes(b'x')
        self.row = AIModel.objects.create(model_key='reader:backup-test', name='backup test',
                                          model_type='vision', source='reader',
                                          local_path=str(self.folder))
        self.service = mock.Mock(is_available=mock.Mock(return_value=True),
                                 backup_directory=mock.Mock(return_value=[
                                     RB.BackupResult(True, 'a', 'b', size_mb=1.0)]))

    def test_the_key_the_page_sends_backs_up_the_models_whole_folder(self):
        with mock.patch.object(RB, 'get_backup_service', return_value=self.service):
            out = RB.backup_model('reader:backup-test', format_type='models')
        self.assertEqual((True, 1), (out['success'], out['files_backed_up']))
        self.service.backup_directory.assert_called_once_with(
            str(self.folder), 'unknown', 'backup-test', 'models', overwrite=False)

    def test_a_key_nothing_resolves_is_said_not_found(self):
        with mock.patch.object(RB, 'get_backup_service', return_value=self.service):
            out = RB.backup_model('reader:nothing-here')
        self.assertTrue(out['not_found'])
        self.service.backup_directory.assert_not_called()

    def test_the_view_answers_404_for_it_and_backs_up_the_key(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory

        from wama.model_manager import views
        dev = get_user_model().objects.create_user('backup_key_dev', password='x')
        factory = RequestFactory()

        def post(source):
            request = factory.post('/', {'source_path': source}, content_type='application/json')
            request.user = dev
            return views.api_backup_model(request)
        with mock.patch('wama.accounts.permissions.can_manage_registries', return_value=True), \
                mock.patch.object(RB, 'get_backup_service', return_value=self.service):
            self.assertEqual(404, post('reader:nothing-here').status_code)
            self.assertEqual(200, post('reader:backup-test').status_code)
        self.service.backup_directory.assert_called_once()


class CleanupUnloadsEverywhereOnlyForAHumanGestureTest(SimpleTestCase):

    IDLE = [{'model_key': 'reader:ocr', 'vram_gb': 2.0}]

    def _cleanup(self, **kw):
        from wama.common.services import resource_governor as gov
        from wama.model_manager.services.memory_manager import MemoryManager
        with mock.patch.object(gov, 'idle_models', return_value=self.IDLE), \
                mock.patch.object(gov, 'resident_models', return_value={'reader:ocr': 2.0}), \
                mock.patch.object(gov, 'unload_resident', return_value=(True, 'ok')) as channel, \
                mock.patch.object(MemoryManager, 'unload_model', return_value=False) as local, \
                mock.patch.object(WAMAMemoryCleaner, 'clear_gpu_cache', return_value=False):
            cleaner = WAMAMemoryCleaner()
            idle = cleaner.cleanup_idle_models(**kw)
            full = cleaner.aggressive_cleanup(**kw)
        return idle, full, channel, local

    def test_the_human_gesture_goes_through_the_tenants_channel(self):
        idle, full, channel, local = self._cleanup(everywhere=True)
        self.assertEqual((['reader:ocr'], ['reader:ocr']), (idle.models_unloaded, full.models_unloaded))
        self.assertEqual(2, channel.call_count)
        local.assert_not_called()

    def test_an_automatic_caller_keeps_to_its_process(self):
        idle, full, channel, local = self._cleanup()
        channel.assert_not_called()
        self.assertEqual(2, local.call_count)
        self.assertEqual(([], []), (idle.models_unloaded, full.models_unloaded))

    def test_clear_gpu_reaches_every_process_only_when_asked(self):
        from wama.common.services import resource_governor as gov
        from wama.model_manager.services.memory_manager import MemoryManager
        with mock.patch.object(gov, 'resident_models', return_value={'reader:ocr': 2.0}), \
                mock.patch.object(gov, 'unload_resident', return_value=(True, 'ok')) as channel, \
                mock.patch('torch.cuda.is_available', return_value=False):
            MemoryManager.clear_gpu_memory()
            channel.assert_not_called()
            MemoryManager.clear_gpu_memory(everywhere=True)
        channel.assert_called_once_with('reader:ocr')
