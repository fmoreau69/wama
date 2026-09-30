"""
Journal DATÉ des installations et sa couche du calendrier (2026-09-30, demande de Fabien).

Rien ne datait une installation : la progression vivait en cache le temps de la tâche. Les gardes :
- la DEMANDE ouvre l'événement avec sa VOIE, la tâche le reprend (début réel), puis le clôt — y
  compris quand elle refuse, quand le driver échoue ou quand il lève ;
- le message Celery ne porte RIEN de plus qu'avant (mesuré le 30/09 : un `via=` dans le message
  faisait lever un worker resté sur l'ancien code, l'installation échouait) ;
- chaque appel des points d'entrée dit sa voie, et les tâches ne se dispatchent que par
  `dispatch_install` — sans quoi une voie nouvelle rouvrirait le trou en silence ;
- le calendrier montre la couche à qui a accès au model_manager, et à personne d'autre.
"""
import ast
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from wama.model_manager.models import AIModel, InstallEvent
from wama.model_manager.services import install_history


def _catalog_row(key='test:history-row'):
    return AIModel.objects.create(model_key=key, name='Modèle témoin', model_type='llm',
                                  source='huggingface', is_downloaded=False)


class RouteRecordsTest(TestCase):

    def _run_catalog(self, driver, via='assistant'):
        from wama.model_manager import tasks
        row = _catalog_row()
        install_history.queued('model', row.model_key, name=row.name, via=via)
        with mock.patch('wama.model_manager.services.model_installer.spec_for_catalog_row',
                        return_value={'kind': 'hf', 'ref': 'org/x', 'category': 'llm'}), \
                mock.patch('wama.model_manager.services.model_installer.install_from_spec',
                           side_effect=driver):
            try:
                tasks.install_catalog_task.apply(args=[row.model_key]).get()
            except RuntimeError:
                pass
        return InstallEvent.objects.get(key=row.model_key)

    def test_the_task_resumes_the_event_opened_by_the_request(self):
        event = self._run_catalog(lambda spec, token=None: {'ok': True})
        self.assertEqual((event.kind, event.action, event.status, event.via),
                         ('model', 'install', 'SUCCESS', 'assistant'))
        self.assertEqual(event.name, 'Modèle témoin')
        self.assertGreaterEqual(event.finished_at, event.started_at)
        self.assertEqual(InstallEvent.objects.count(), 1, 'une seule ligne par installation')

    def test_a_refusal_of_the_driver_is_recorded_as_a_failure(self):
        event = self._run_catalog(lambda spec, token=None: {'ok': False, 'error': 'quota HF'})
        self.assertEqual((event.status, event.detail.get('error')), ('FAILURE', 'quota HF'))

    def test_an_exception_closes_the_event_and_still_propagates(self):
        def boom(spec, token=None):
            raise RuntimeError('réseau coupé')
        event = self._run_catalog(boom)
        self.assertEqual(event.status, 'FAILURE')
        self.assertIn('réseau coupé', event.detail.get('error', ''))

    def test_a_task_that_declines_closes_the_event_it_picked_up(self):
        from wama.model_manager import tasks
        install_history.queued('model', 'proposed:test:gone', name='Parti', via='model_manager')
        tasks.install_proposed_task.apply(args=['proposed:test:gone']).get()
        event = InstallEvent.objects.get(key='proposed:test:gone')
        self.assertEqual(event.status, 'FAILURE', 'un refus ne laisse pas une installation « en cours »')

    def test_a_task_without_a_request_still_dates_its_install(self):
        from wama.model_manager import tasks
        cand = AIModel.objects.create(model_key='proposed:test:history', name='Candidat témoin',
                                      model_type='llm', source='ollama', is_proposed=True)
        with mock.patch('wama.model_manager.services.model_installer.install_candidate',
                        return_value={'ok': True}):
            tasks.install_proposed_task.apply(args=[cand.model_key]).get()
        event = InstallEvent.objects.get(key=cand.model_key)
        self.assertEqual((event.status, event.via), ('SUCCESS', ''))

    def test_the_request_dates_its_route_and_sends_nothing_new_to_celery(self):
        from wama.model_manager.services import model_installer as mi
        row = _catalog_row('test:history-request')
        with mock.patch.object(mi, 'spec_for_catalog_row', return_value={'kind': 'hf', 'ref': 'o/x'}), \
                mock.patch.object(mi, 'disk_space_guard', return_value=None), \
                mock.patch('wama.model_manager.tasks.install_catalog_task.delay') as delay:
            delay.return_value.id = 't-1'
            mi.request_install(row.model_key, via='assistant')
        # Le message d'avant, à l'identique : un worker resté sur l'ancien code l'accepte.
        delay.assert_called_once_with(row.model_key, user_id=None)
        event = InstallEvent.objects.get(key=row.model_key)
        self.assertEqual((event.via, event.status), ('assistant', 'RUNNING'))

    def test_a_failing_log_never_fails_the_install(self):
        with mock.patch.object(InstallEvent.objects, 'create', side_effect=RuntimeError('db')):
            with install_history.opened('model', 'x') as outcome:
                outcome.update({'ok': True})
        self.assertFalse(InstallEvent.objects.filter(key='x').exists())


class EveryEntryPointNamesItsRouteTest(SimpleTestCase):
    """Hors tests : chaque appel de la route porte `via=`, et les deux tâches ne partent que par
    `dispatch_install` (qui date la demande et n'ajoute rien au message)."""

    ENTRY_POINTS = {'request_install', 'uninstall_model', 'install_library', 'dispatch_install'}
    TASKS = {'install_catalog_task', 'install_proposed_task'}

    def _calls(self):
        base = Path(settings.BASE_DIR)
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in (base / root).rglob('*.py'):
                rel = path.relative_to(base).as_posix()
                if '/tests/' in rel or path.name.startswith('tests') or '/migrations/' in rel:
                    continue
                text = path.read_text(encoding='utf-8', errors='replace')
                if not any(n in text for n in self.ENTRY_POINTS | self.TASKS):
                    continue
                tree = ast.parse(text)
                for func in ast.walk(tree):
                    if not isinstance(func, (ast.FunctionDef, ast.Module)):
                        continue
                    for node in ast.walk(func):
                        if isinstance(node, ast.Call):
                            yield rel, getattr(func, 'name', '<module>'), node

    def test_each_call_names_its_route(self):
        seen, missing = 0, []
        for rel, _where, node in self._calls():
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if name not in self.ENTRY_POINTS:
                continue
            seen += 1
            if not any(k.arg == 'via' for k in node.keywords):
                missing.append(f'{rel}:{node.lineno}')
        self.assertGreaterEqual(seen, 6, 'trop peu d’appels trouvés : le parcours est aveugle')
        self.assertEqual(sorted(set(missing)), [], 'une voie d’installation sans `via=`')

    def test_the_install_tasks_leave_only_through_dispatch_install(self):
        outside = set()
        for rel, where, node in self._calls():
            func = node.func
            if (getattr(func, 'attr', None) in ('delay', 'apply_async')
                    and getattr(getattr(func, 'value', None), 'id', None) in self.TASKS
                    and where != 'dispatch_install'):
                outside.add(f'{rel}:{node.lineno} ({where})')
        self.assertEqual(sorted(outside), [], 'une tâche d’installation dispatchée hors de '
                                              '`dispatch_install` échappe au journal')


class CalendarLayerTest(TestCase):

    def setUp(self):
        now = timezone.now()
        InstallEvent.objects.create(kind='model', key='k1', name='FrWhisper', status='SUCCESS',
                                    via='assistant', started_at=now - timedelta(minutes=30),
                                    finished_at=now - timedelta(minutes=10))
        InstallEvent.objects.create(kind='library', key='kokoro-onnx', name='kokoro-onnx',
                                    status='FAILURE', via='cli', started_at=now - timedelta(hours=2),
                                    finished_at=now - timedelta(hours=2), detail={'error': 'pin'})
        self.window = (now - timedelta(days=1), now + timedelta(days=1))

    def _installs(self, user):
        from wama.common.services.calendar import events_for
        with mock.patch('wama.common.services.global_queue.snapshot', return_value=[]):
            return [e for e in events_for(user, *self.window) if e.extra.get('kind') == 'install']

    def test_an_authorised_user_sees_installs_with_their_route_and_outcome(self):
        admin = User.objects.create_superuser('history_admin', 'a@x.fr', 'x')
        events = {e.title: e for e in self._installs(admin)}
        self.assertIn('Installation : FrWhisper', events)
        self.assertIn('Installation : librairie kokoro-onnx — échec', events)
        ev = events['Installation : FrWhisper']
        self.assertEqual((ev.scope, ev.status, ev.extra['layer'], ev.extra['via']),
                         ('instance', 'SUCCESS', 'installation', 'assistant IA'))
        short = events['Installation : librairie kokoro-onnx — échec']
        self.assertGreaterEqual(short.end - short.start, timedelta(minutes=15),
                                'une installation éclair reste visible dans la grille')

    def test_counter_proof_a_user_without_access_sees_none(self):
        user = User.objects.create_user('history_plain', password='x')
        with mock.patch('wama.accounts.permissions.accessible', return_value=False):
            self.assertEqual(self._installs(user), [])

    def test_the_layer_has_its_own_filter_value(self):
        from wama.common.services.calendar import nature_labels
        self.assertEqual(nature_labels().get('installation'), 'Installations')


class DiskGuardKnownZeroTest(SimpleTestCase):
    """Une taille de 0,0 Go est CONNUE (dépôt de pipeline léger), pas une absence (2026-09-30).

    Mesuré sur `pyannote/speaker-diarization-community-1` (~27 Mo) : la garde prenait 0,0 pour
    « pas de taille », interrogeait le registre Ollama sur une référence HuggingFace et refusait.
    """

    DISK = {'free_gb': 150.9, 'drive': 'D:'}

    def _guard(self, needed):
        from wama.model_manager.services import model_installer as mi
        with mock.patch('wama.common.services.system_monitor.SystemMonitor.get_disk_info',
                        return_value=self.DISK), \
                mock.patch('wama.model_manager.services.ollama_registry.size_gb',
                           return_value=None) as ollama:
            return mi.disk_space_guard('pyannote/speaker-diarization-community-1',
                                       needed_gb=needed), ollama

    def test_a_known_zero_size_passes_without_asking_ollama(self):
        refusal, ollama = self._guard(0.0)
        self.assertIsNone(refusal)
        ollama.assert_not_called()

    def test_counter_proof_an_unknown_size_is_still_refused(self):
        refusal, _ollama = self._guard(None)
        self.assertEqual(refusal['reason'], 'taille_inconnue')
