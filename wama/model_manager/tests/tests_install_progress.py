"""
L'AVANCEMENT d'une installation de modèle, et son suivi hors du model manager (2026-11-06).

Demande de Fabien : « vérifie qu'on a une barre de progression à l'installation d'un modèle depuis
le model manager, puis on l'étend à l'assistant avec message ». Il n'y en avait pas : un voile et
une phrase, un pourcentage pour Ollama seul, rien au F5, rien pour l'assistant, et aucune fin
notifiée. Les gardes :
- une seule MESURE pour tous les pilotes (`InstallMeter`) : octets comptés par la boucle d'un
  pilote, dossier mesuré quand une librairie télécharge, `completed/total` d'Ollama ; plafonnée à
  99 % tant que l'installation n'est pas finie ;
- la tâche la publie avec l'ÉLÉMENT de l'installation, son événement daté (`install_id`) ;
- la ligne de suivi lit l'avancement de CET événement seul, et attend (PENDING) tant que la tâche
  n'a rien publié ;
- l'assistant désigne l'installation (`item_id`), en lit la ligne et en raconte la fin au fil ;
- la fin est notifiée à qui l'a demandée, par LA fin commune ;
- au calendrier, une installation en cours a sa fin PRÉVUE par le débit observé.
"""
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from wama.model_manager.models import AIModel, InstallEvent
from wama.model_manager.services import install_history
from wama.model_manager.services import model_installer as mi
from wama.model_manager.tasks import INSTALL_CACHE_PREFIX

GB = 1024 ** 3


class InstallMeterTest(SimpleTestCase):

    def _meter(self, expected=None):
        seen = []
        return mi.InstallMeter(seen.append, expected_bytes=expected, every_s=0), seen

    def test_received_bytes_become_a_percentage_capped_until_the_end(self):
        meter, seen = self._meter(expected=4 * GB)
        meter.add(GB)
        self.assertEqual((25, 1.0, 4.0), (seen[-1]['pct'], seen[-1]['done_gb'], seen[-1]['total_gb']))
        meter.add(10 * GB)
        self.assertEqual(99, seen[-1]['pct'], '100 % is the end of the install, not of the download')

    def test_without_an_expected_weight_it_says_the_bytes_and_no_percentage(self):
        meter, seen = self._meter()
        meter.say('téléchargement org/x…')
        meter.add(GB // 2)
        self.assertEqual({'status': 'téléchargement org/x…', 'done_gb': 0.5}, seen[-1])

    def test_a_source_that_announces_its_own_total_is_read_as_such(self):
        meter, seen = self._meter(expected=40 * GB)
        meter.received(3, 4)
        self.assertEqual(75, seen[-1]['pct'], 'an Ollama layer says its own completed/total')

    def test_a_folder_written_by_a_library_is_measured_while_it_downloads(self):
        meter, seen = self._meter(expected=1000)
        with tempfile.TemporaryDirectory() as tmp:
            blobs = Path(tmp) / 'blobs'
            blobs.mkdir()
            with meter.measuring(blobs, every_s=0.05):
                (blobs / 'a.incomplete').write_bytes(b'x' * 300)
                import time
                deadline = time.time() + 3
                while not seen and time.time() < deadline:
                    time.sleep(0.05)
        self.assertTrue(seen, 'the watcher published while the block ran')
        self.assertEqual(30, seen[-1]['pct'])
        self.assertEqual(300, meter.done, 'measured again when the block ends')

    def test_a_link_is_not_counted_twice(self):
        from wama.common.utils.disk_utils import tree_bytes
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'blob').write_bytes(b'x' * 10)
            (root / 'snap').symlink_to(root / 'blob')
            self.assertEqual(10, tree_bytes(root))
            self.assertEqual(0, tree_bytes(root / 'absent'))

    def test_a_work_folder_purge_says_the_bytes_it_frees(self):
        import shutil

        from django.conf import settings

        from wama.common.utils.work_dir import purge_job_dir
        base = Path(tempfile.mkdtemp(dir=settings.MEDIA_ROOT))   # sous les médias de TEST
        try:
            (base / 'job_7').mkdir()
            (base / 'job_7' / 'frame.png').write_bytes(b'x' * 12)
            self.assertEqual(12, purge_job_dir(base, 7))
            self.assertFalse((base / 'job_7').exists())
        finally:
            shutil.rmtree(base, ignore_errors=True)    # le chemin CRÉÉ, jamais MEDIA_ROOT lu ici

    def test_the_sum_under_a_folder_has_one_home(self):
        """The meter, the uninstall, the purge of a work folder and the discovery of a snapshot
        each summed the same sizes (2026-11-06): they read `disk_utils.tree_bytes`."""
        from django.conf import settings

        from wama.common.utils import disk_utils
        self.assertIs(disk_utils.tree_bytes, mi.tree_bytes)
        base = Path(settings.BASE_DIR) / 'wama'
        work_dir = (base / 'common/utils/work_dir.py').read_text(encoding='utf-8')
        self.assertIn('tree_bytes(cible)', work_dir)
        self.assertNotIn('.stat().st_size for f in', work_dir)
        registry = (base / 'model_manager/services/model_registry.py').read_text(encoding='utf-8')
        self.assertIn('tree_bytes(blobs)', registry)
        self.assertNotIn('st_size for f in blobs', registry)


class DriversFeedTheMeterTest(SimpleTestCase):

    def test_the_common_download_counts_each_chunk(self):
        meter = mi.InstallMeter(lambda s: None, expected_bytes=8, every_s=0)
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [b'abc', b'defgh']
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch('requests.get', return_value=response):
            res = mi.download_asset('https://example/x.bin', str(Path(tmp) / 'x.bin'), meter=meter)
        self.assertTrue(res['ok'], res)
        self.assertEqual(8, meter.done)

    def test_the_hub_driver_measures_the_blobs_of_its_repository(self):
        meter = mi.InstallMeter(lambda s: None, every_s=0)
        watched = []

        def measuring(path, every_s=2.0):
            watched.append(Path(path))
            from contextlib import nullcontext
            return nullcontext(meter)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch('wama.common.utils.model_locations.model_dir', return_value=Path(tmp)), \
                mock.patch.object(meter, 'measuring', side_effect=measuring), \
                mock.patch('huggingface_hub.snapshot_download', return_value=tmp),                 mock.patch.object(mi, 'format_duplicates', return_value=[]), \
                mock.patch.object(mi, 'verify_hf_snapshot',
                                  return_value={'ok': True, 'verified': {}}):
            self.assertTrue(mi.pull_hf_model('org/Name-1', 'llm', meter=meter, token=False)['ok'])
        self.assertEqual([Path(tmp) / 'models--org--Name-1' / 'blobs'], watched)

    def test_a_kept_declared_file_counts_as_received(self):
        import hashlib
        payload = b'weights'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'w.bin').write_bytes(payload)
            spec = {'kind': 'files', 'ref': 'app:x', 'target_dir': str(root),
                    'files': [{'path': 'w.bin', 'size': len(payload),
                               'sha256': hashlib.sha256(payload).hexdigest(),
                               'origin': {'source': 'github', 'release': 'o/r:v1', 'file': 'w.bin'}}]}
            meter = mi.InstallMeter(lambda s: None, every_s=0)
            with mock.patch('wama.common.utils.model_locations.models_root', return_value=root), \
                    mock.patch.object(mi, 'declared_files_error', return_value=None):
                res = mi.pull_declared_files(spec, meter=meter)
        self.assertTrue(res['ok'], res)
        self.assertEqual(len(payload), meter.done)


class TheTaskPublishesItsEventTest(TestCase):

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('install_requester', password='x')
        self.row = AIModel.objects.create(model_key='test:progress-row', name='Modèle suivi',
                                          model_type='llm', source='huggingface',
                                          is_downloaded=False, disk_gb=2)

    def _run(self, driver):
        from wama.model_manager import tasks
        install_history.queued('model', self.row.model_key, name=self.row.name, via='assistant')
        with mock.patch('wama.model_manager.services.model_installer.spec_for_catalog_row',
                        return_value={'kind': 'hf', 'ref': 'org/x', 'category': 'llm'}), \
                mock.patch('wama.model_manager.services.model_installer.install_from_spec',
                           side_effect=driver):
            tasks.install_catalog_task.apply(args=[self.row.model_key],
                                             kwargs={'user_id': self.user.pk}).get()
        return InstallEvent.objects.get(key=self.row.model_key)

    def test_the_progress_carries_the_install_and_the_expected_weight(self):
        seen = []

        def driver(spec, token=None, meter=None):
            meter.add(GB)
            meter.say('vérification…')         # une étape publie toujours (l'octet, au plus 1/s)
            seen.append(dict(cache.get(INSTALL_CACHE_PREFIX + self.row.model_key)))
            return {'ok': True}
        event = self._run(driver)
        self.assertEqual(('RUNNING', event.pk, 50, 2.0),
                         (seen[0]['state'], seen[0]['install_id'], seen[0]['pct'],
                          seen[0]['total_gb']))
        self.assertEqual(('SUCCESS', event.pk),
                         (cache.get(INSTALL_CACHE_PREFIX + self.row.model_key)['state'],
                          cache.get(INSTALL_CACHE_PREFIX + self.row.model_key)['install_id']))

    def test_the_end_is_notified_to_who_asked_by_the_common_end(self):
        from wama.common.models import Notification
        event = self._run(lambda spec, token=None, meter=None: {'ok': False, 'error': 'quota HF'})
        note = Notification.objects.get(recipient=self.user)
        self.assertEqual(('job_failed', 'model_manager', 'InstallEvent', str(event.pk)),
                         (note.kind, note.app, note.object_type, note.object_id))
        self.assertIn('Modèle suivi', note.title)
        self.assertIn('quota HF', note.body)

    def test_counter_proof_nobody_is_told_without_a_requester(self):
        from wama.common.models import Notification
        from wama.model_manager import tasks
        install_history.queued('model', self.row.model_key, name=self.row.name, via='cli')
        with mock.patch('wama.model_manager.services.model_installer.spec_for_catalog_row',
                        return_value={'kind': 'hf', 'ref': 'org/x', 'category': 'llm'}), \
                mock.patch('wama.model_manager.services.model_installer.install_from_spec',
                           return_value={'ok': True}):
            tasks.install_catalog_task.apply(args=[self.row.model_key]).get()
        self.assertFalse(Notification.objects.exists())

    def test_the_request_names_the_event_the_task_will_take(self):
        with mock.patch('wama.model_manager.tasks.install_catalog_task.delay',
                        return_value=mock.Mock(id='t1')), \
                mock.patch.object(mi, 'spec_for_catalog_row',
                                  return_value={'kind': 'hf', 'ref': 'org/x', 'category': 'llm'}), \
                mock.patch.object(mi, 'disk_space_guard', return_value=None):
            res = mi.request_install(self.row.model_key, user=self.user, via='assistant')
        self.assertEqual(InstallEvent.objects.get(key=self.row.model_key).pk, res['install_id'])


class TheProgressRowTest(TestCase):

    def setUp(self):
        cache.clear()
        self.event = InstallEvent.objects.create(kind='model', key='test:row', name='Témoin',
                                                 started_at=timezone.now())

    def test_a_request_not_yet_taken_waits(self):
        row = install_history.progress_row(self.event)
        self.assertEqual(('PENDING', False, 0, 'Installation : Témoin'),
                         (row['status'], row['terminal'], row['progress'], row['label']))

    def test_the_task_progress_of_this_event_is_read(self):
        cache.set(INSTALL_CACHE_PREFIX + 'test:row',
                  {'state': 'RUNNING', 'install_id': self.event.pk, 'pct': 42,
                   'status': 'téléchargement…', 'done_gb': 1.0, 'total_gb': 2.4})
        row = install_history.progress_row(self.event)
        self.assertEqual(('RUNNING', 42, 'téléchargement…', 2.4),
                         (row['status'], row['progress'], row['step'], row['total_gb']))

    def test_counter_proof_another_install_of_the_same_key_is_not_this_one(self):
        cache.set(INSTALL_CACHE_PREFIX + 'test:row',
                  {'state': 'RUNNING', 'install_id': self.event.pk + 1, 'pct': 90})
        self.assertEqual('PENDING', install_history.progress_row(self.event)['status'])

    def test_a_finished_install_says_its_outcome(self):
        InstallEvent.objects.filter(pk=self.event.pk).update(
            status='FAILURE', finished_at=timezone.now(), detail={'error': 'disque'})
        self.event.refresh_from_db()
        row = install_history.progress_row(self.event)
        self.assertEqual(('FAILURE', True, False, 'disque'),
                         (row['status'], row['terminal'], row['ok'], row['error']))

    def test_the_page_follows_what_runs_and_what_ended_since_its_last_pass(self):
        before = timezone.now()
        old = InstallEvent.objects.create(kind='model', key='test:old', status='SUCCESS',
                                          started_at=before - timedelta(hours=2),
                                          finished_at=before - timedelta(hours=1))
        ended = InstallEvent.objects.create(kind='model', key='test:ended', status='SUCCESS',
                                            started_at=before, finished_at=timezone.now())
        keys = {r['model_key'] for r in install_history.install_rows(since=before)}
        self.assertEqual({'test:row', 'test:ended'}, keys)
        self.assertNotIn(old.key, {r['model_key'] for r in install_history.install_rows()})
        self.assertNotIn(ended.key, {r['model_key'] for r in install_history.install_rows()})


class TheAssistantFollowsTheInstallTest(TestCase):

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser('install_admin', 'a@x.fr', 'x')
        self.event = InstallEvent.objects.create(kind='model', key='test:asst', name='Suivi',
                                                 started_at=timezone.now(), via='assistant')

    def test_the_tool_result_designates_the_install_as_its_element(self):
        from wama.tool_api import install_model, items_of_step
        with mock.patch('wama.model_manager.services.model_installer.request_install',
                        return_value={'ok': True, 'started': True, 'model_key': 'test:asst',
                                      'task_id': 't', 'install_id': self.event.pk}):
            result = install_model(self.admin, 'test:asst')
        self.assertEqual(self.event.pk, result['item_id'])
        self.assertIn('install_model', result['next_step'])
        self.assertEqual([('model_manager', self.event.pk)],
                         items_of_step('install_model', {'model_key': 'test:asst'}, result))

    def test_its_line_is_the_progress_row_and_bounded_by_the_page_access(self):
        from wama.tool_api import job_progress
        row = job_progress(self.admin, 'model_manager', self.event.pk)
        self.assertEqual(('model_manager', self.event.pk, 'PENDING'),
                         (row['family'], row['id'], row['status']))
        with mock.patch('wama.accounts.permissions.accessible', return_value=False):
            self.assertIsNone(job_progress(self.admin, 'model_manager', self.event.pk))

    def test_its_end_is_told_in_the_thread_it_was_asked_from(self):
        from wama.common.models import Notification
        from wama.common.services import conversation_store
        from wama.common.services.job_follow_ups import origin_conversation, status_step
        steps = [{'tool': 'install_model', 'args': {'model_key': 'test:asst'},
                  'result': {'started': True, 'item_id': self.event.pk}}]
        conversation = conversation_store.thread(self.admin, surface='web')
        conversation_store.record_exchange(conversation, 'installe-le',
                                           {'response': 'Lancé.', 'tool_steps': steps})
        install_history.notify_end(self.admin.pk, self.event.pk, 'Suivi', {'ok': True})
        note = Notification.objects.get(recipient=self.admin)
        self.assertEqual(conversation.pk, origin_conversation(note, 'web').pk)
        step = status_step(note, self.admin)
        self.assertEqual(('list_installations', {'install_id': self.event.pk}),
                         (step['tool'], step['args']))
        self.assertEqual([self.event.pk], [r['id'] for r in step['result']['installations']])


class CalendarPredictsARunningInstallTest(TestCase):

    def test_a_running_install_ends_where_its_observed_rate_says(self):
        cache.clear()
        now = timezone.now()
        event = InstallEvent.objects.create(kind='model', key='test:cal', name='Long',
                                            started_at=now - timedelta(minutes=10))
        cache.set(INSTALL_CACHE_PREFIX + 'test:cal',
                  {'state': 'RUNNING', 'install_id': event.pk, 'pct': 25})
        (ev,) = install_history.calendar_events(now - timedelta(hours=1), now + timedelta(hours=2))
        self.assertEqual('predicted', ev.nature)
        self.assertAlmostEqual(30, (ev.end - now).total_seconds() / 60, delta=1,
                               msg='10 min for 25 % leaves 30 min')
        cache.delete(INSTALL_CACHE_PREFIX + 'test:cal')
        (ev,) = install_history.calendar_events(now - timedelta(hours=1), now + timedelta(hours=2))
        self.assertLess((ev.end - event.started_at), timedelta(minutes=16),
                        'without progress no end is invented: it stops at now (15 min block)')
