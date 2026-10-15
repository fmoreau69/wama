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


def _innermost_callers(names) -> set:
    """`'<fichier> (<fonction>)'` de chaque appel hors tests d'une fonction de `names`, attribué à
    la fonction qui le CONTIENT au plus près (`<module>` hors de toute fonction)."""
    found = set()
    base = Path(settings.BASE_DIR)
    for root in ('wama', 'wama_lab', 'wama_data'):
        for path in (base / root).rglob('*.py'):
            rel = path.relative_to(base).as_posix()
            if '/tests/' in rel or path.name.startswith('tests') or '/migrations/' in rel:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            if not any(n in text for n in names):
                continue

            def visit(node, where):
                for child in ast.iter_child_nodes(node):
                    inner = (child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                             else where)
                    if isinstance(child, ast.Call):
                        name = getattr(child.func, 'id', None) or getattr(child.func, 'attr', None)
                        if name in names:
                            found.add(f'{rel} ({where})')
                    visit(child, inner)
            visit(ast.parse(text), '<module>')
    return found


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

    def test_only_the_request_dispatches(self):
        """`dispatch_install` n'est appelé que par `request_install` : la garde d'espace disque,
        l'idempotence et le refus « déjà téléchargé » vivent là. Le marcheur d'app l'appelait
        directement depuis sa création (31/08) et n'a jamais eu la garde (2026-10-10)."""
        self.assertEqual(
            ['wama/model_manager/services/model_installer.py (request_install)'],
            sorted(_innermost_callers({'dispatch_install'})))


class TheDriversStayInsideTheRouteTest(SimpleTestCase):
    """Les pilotes INTERNES (téléchargement réel) ne s'appellent que DANS la route : par
    `install_from_spec` et `install_candidate` (eux-mêmes appelés par les deux tâches), plus la
    validation de nom à blanc de la proposition YOLO. Tout autre appelant est une entrée parallèle
    — sans garde d'espace disque, sans journal (2026-10-10 : `pull_model` en avait deux)."""

    DRIVERS = {'install_from_spec', 'install_candidate', 'pull_hf_model', 'pull_ollama_model',
               'pull_yolo_weights', 'pull_github_asset', 'pull_declared_files'}
    INSIDE = {
        'wama/model_manager/services/model_installer.py (install_from_spec)',
        'wama/model_manager/services/model_installer.py (install_candidate)',
        'wama/model_manager/tasks.py (install_proposed_task)',
        'wama/model_manager/tasks.py (install_catalog_task)',
        'wama/model_manager/services/prospector.py (seed_yolo_candidate)',     # dry_run=True
        # Plus d'exception : `pull_model <nom Ollama>` passe par sa proposition nommée depuis le
        # 2026-10-11 (`seed_ollama_candidate`, décision de Fabien).
    }

    def test_no_driver_is_called_from_outside_the_route(self):
        self.assertEqual(sorted(self.INSIDE), sorted(_innermost_callers(self.DRIVERS)))


class PullModelTakesTheRouteTest(TestCase):
    """`pull_model <org/dépôt>` : la ligne du catalogue, sinon la proposition, puis la DEMANDE."""

    def _run(self, name):
        from io import StringIO

        from django.core.management import call_command

        from wama.model_manager.services import model_installer as mi
        from wama.model_manager.services import prospector
        with mock.patch.object(mi, 'request_install',
                               return_value={'ok': True, 'started': True, 'task_id': 't'}) as req, \
                mock.patch.object(mi, 'pull_hf_model') as driver, \
                mock.patch.object(prospector, 'seed_hf_search',
                                  side_effect=self._seed) as seed:
            call_command('pull_model', name, stdout=StringIO())
        driver.assert_not_called()
        return req, seed

    def _seed(self, repo, **kw):
        if repo == 'org/proposable':
            AIModel.objects.create(model_key='proposed:hf:org/proposable', name='p', hf_id=repo,
                                   model_type='vision', source='huggingface', is_proposed=True)
        return {'ok': True, 'refs': [repo]}

    def test_a_catalogue_repo_is_requested_by_its_key(self):
        AIModel.objects.create(model_key='huggingface:depthpro', name='d', hf_id='apple/DepthPro-hf',
                               model_type='vision', source='huggingface')
        req, seed = self._run('https://huggingface.co/apple/DepthPro-hf')
        req.assert_called_once_with('huggingface:depthpro', via='cli')
        seed.assert_not_called()

    def test_an_unknown_repo_is_proposed_then_requested(self):
        req, seed = self._run('org/proposable')
        seed.assert_called_once()
        req.assert_called_once_with('proposed:hf:org/proposable', via='cli')

    def test_a_repo_the_prospection_rejects_is_never_downloaded(self):
        from django.core.management import CommandError
        with self.assertRaisesMessage(CommandError, 'HF_TASKS'):
            self._run('org/out-of-scope')


class PullModelOllamaTakesTheRouteTest(TestCase):
    """`pull_model <nom Ollama>` : sa proposition nommée (vérifiée au registre), puis la DEMANDE —
    jamais `pull_ollama_model` en direct (dernier écart de la route, soldé le 2026-10-11)."""

    def _run(self, name, *, exists=True, size=4.2):
        from io import StringIO

        from django.core.management import call_command

        from wama.model_manager.services import model_installer as mi
        from wama.model_manager.services import ollama_registry as reg
        with mock.patch.object(mi, 'request_install',
                               return_value={'ok': True, 'started': True, 'task_id': 't'}) as req, \
                mock.patch.object(mi, 'pull_ollama_model') as driver, \
                mock.patch.object(reg, 'existe', return_value=exists), \
                mock.patch.object(reg, 'size_gb', return_value=size):
            call_command('pull_model', name, stdout=StringIO())
        driver.assert_not_called()
        return req

    def test_a_name_is_proposed_then_requested(self):
        req = self._run('bge-m3')
        req.assert_called_once_with('proposed:ollama:bge-m3:latest', via='cli')
        cand = AIModel.objects.get(model_key='proposed:ollama:bge-m3:latest')
        self.assertTrue(cand.is_proposed)
        self.assertEqual(cand.source, 'ollama')
        self.assertEqual(cand.name, 'bge-m3:latest')
        self.assertEqual(cand.disk_gb, 4.2)        # la garde d'espace pèse ce qu'on tirera

    def test_an_explicit_tag_is_kept(self):
        req = self._run('qwen3:8b')
        req.assert_called_once_with('proposed:ollama:qwen3:8b', via='cli')

    def test_an_existing_proposal_is_requested_without_being_rewritten(self):
        AIModel.objects.create(model_key='proposed:ollama:gemma4:latest', name='gemma4:latest',
                               model_type='vlm', source='ollama', is_proposed=True,
                               capabilities={'task': 'captioning'},
                               extra_info={'prospect': {'role': 'vlm'}})
        req = self._run('gemma4')
        req.assert_called_once_with('proposed:ollama:gemma4:latest', via='cli')
        cand = AIModel.objects.get(model_key='proposed:ollama:gemma4:latest')
        self.assertEqual(cand.capabilities, {'task': 'captioning'})
        self.assertEqual(cand.extra_info['prospect']['role'], 'vlm')

    def test_an_installed_model_is_requested_by_its_row(self):
        AIModel.objects.create(model_key='ollama:bge-m3:latest', name='bge-m3:latest',
                               model_type='embedding', source='ollama', is_downloaded=True)
        req = self._run('bge-m3')
        req.assert_called_once_with('ollama:bge-m3:latest', via='cli')
        self.assertFalse(AIModel.objects.filter(is_proposed=True).exists())

    def test_a_name_the_registry_does_not_serve_is_refused_and_nothing_is_written(self):
        from django.core.management import CommandError
        with self.assertRaisesMessage(CommandError, 'registre Ollama'):
            self._run('no-such-model', exists=False)
        self.assertFalse(AIModel.objects.filter(is_proposed=True).exists())

    def test_the_role_prospection_never_purges_a_named_request(self):
        from wama.model_manager.services import ollama_registry as reg
        from wama.model_manager.services import prospect_ollama
        self._run('bge-m3')
        AIModel.objects.create(model_key='proposed:ollama:old:latest', name='old:latest',
                               model_type='llm', source='ollama', is_proposed=True,
                               proposal_kind='new', extra_info={'prospect': {'role': 'llm'}})
        with mock.patch.object(reg, 'search', return_value=()), \
                mock.patch('wama.model_manager.services.update_checker.check_updates',
                           return_value={'ollama_review': []}), \
                mock.patch('wama.model_manager.services.update_checker.local_digests',
                           return_value={}):
            prospect_ollama.prospect_ollama()
        keys = set(AIModel.objects.filter(is_proposed=True).values_list('model_key', flat=True))
        # Contre-épreuve : le candidat de rôle hors périmètre, lui, est purgé.
        self.assertEqual(keys, {'proposed:ollama:bge-m3:latest'})


class EmbeddingRoleWinsOverVisionTest(TestCase):
    """`embeddinggemma-2` est rangé par la bibliothèque Ollama sous `vision` ET `embedding`
    (mesuré le 2026-10-15) : le rôle `vlm`, parcouru le premier, l'écrivait `vlm`/`captioning`."""

    def _prospect(self, lists):
        from wama.model_manager.services import ollama_registry as reg
        from wama.model_manager.services import prospect_ollama
        with mock.patch.object(reg, 'search',
                               side_effect=lambda requete='', capacite='': lists.get(capacite, ())), \
                mock.patch.object(reg, 'tag_equivalent', return_value='latest'), \
                mock.patch('wama.model_manager.services.update_checker.check_updates',
                           return_value={'ollama_review': []}), \
                mock.patch('wama.model_manager.services.update_checker.local_digests',
                           return_value={}):
            prospect_ollama.prospect_ollama()

    def test_a_model_listed_as_embedding_is_never_proposed_as_a_vlm(self):
        self._prospect({'vision': ('embeddinggemma-2', 'minicpm-v4.6'),
                        'embedding': ('embeddinggemma-2',)})
        emb = AIModel.objects.get(model_key='proposed:ollama:embeddinggemma-2:latest')
        self.assertEqual(emb.model_type, 'embedding')
        self.assertEqual(emb.capabilities, {'task': 'feature-extraction'})
        self.assertEqual(emb.extra_info['prospect']['role'], 'embedding')
        # Contre-épreuve : un VLM que la bibliothèque ne range pas sous `embedding` reste un VLM.
        vlm = AIModel.objects.get(model_key='proposed:ollama:minicpm-v4.6:latest')
        self.assertEqual(vlm.model_type, 'vlm')

    def test_a_row_already_written_as_vlm_is_corrected_by_the_next_pass(self):
        AIModel.objects.create(model_key='proposed:ollama:embeddinggemma-2:latest',
                               name='embeddinggemma-2:latest', model_type='vlm',
                               source='ollama', is_proposed=True, proposal_kind='new',
                               capabilities={'task': 'captioning'},
                               extra_info={'prospect': {'role': 'vlm'}})
        self._prospect({'vision': ('embeddinggemma-2',), 'embedding': ('embeddinggemma-2',)})
        emb = AIModel.objects.get(model_key='proposed:ollama:embeddinggemma-2:latest')
        self.assertEqual((emb.model_type, emb.capabilities['task']),
                         ('embedding', 'feature-extraction'))


class DepthModelsAreInstallableByTheRouteTest(SimpleTestCase):
    """Les lignes de profondeur déclarent leur `install_dir` (2026-10-10) : la route en dérive
    EXACTEMENT le dossier que le moteur lit (`depth_engine`, `cache_dir=`). Avant, rien ne les
    installait et le Lab renvoyait à un `pull_model <org/dépôt>` hors route."""

    def test_the_derived_folder_is_the_one_the_engine_reads(self):
        from wama.common.backends.depth_engine import DEPTH_MODELS
        from wama.common.utils.model_locations import model_dir
        from wama.model_manager.services.model_installer import spec_for_catalog_row
        from wama.model_manager.services.model_registry import ModelRegistry

        registry = ModelRegistry()
        registry._models = {}
        registry._discover_depth_models()
        for key, declared in DEPTH_MODELS.items():
            with self.subTest(key=key):
                info = registry._models[f'huggingface:{key}']
                spec = spec_for_catalog_row(AIModel(model_key=f'huggingface:{key}',
                                                    hf_id=info.hf_id, extra_info=info.extra_info))
                self.assertIsNotNone(spec, 'la ligne doit être installable par la route')
                self.assertEqual(declared['hf_id'], spec['ref'])
                self.assertEqual(Path(declared['dir']).resolve(),
                                 Path(model_dir(spec['category'], spec['family'])).resolve())


class ThePageReadsTheServerRulesTest(SimpleTestCase):
    """La page du model manager LIT les règles du serveur au lieu de les recopier : `installable`
    (`spec_for_catalog_row`) pour le bouton « Installer », `platform_url` pour le lien."""

    def _row(self, **kw):
        return AIModel(model_key='app:m', name='M', model_type='vision', **kw)

    def test_installable_is_the_route_rule(self):
        root = Path(settings.AI_MODELS_DIR) / 'models'
        hf_row = self._row(hf_id='o/x', extra_info={'install_dir': str(root / 'vision' / 'x')})
        declared = [{'path': 'a.pth', 'size': 1, 'sha256': 'a' * 64,
                     'origin': {'source': 'github', 'release': 'o/r:v1', 'file': 'a.pth'}}]
        files_row = self._row(extra_info={'install_dir': str(root / 'lipsync' / 'cf'),
                                          'declared_files': declared})
        self.assertTrue(hf_row.to_dict()['installable'])
        self.assertTrue(files_row.to_dict()['installable'],
                        'a row with DECLARED files has no hf_id — and is installable')
        self.assertFalse(self._row(hf_id='o/x').to_dict()['installable'], 'no install_dir')
        downloaded = self._row(hf_id='o/x', is_downloaded=True,
                               extra_info={'install_dir': str(root / 'vision' / 'x')})
        self.assertFalse(downloaded.to_dict()['installable'])

    def test_the_template_copies_neither_rule(self):
        page = (Path(settings.BASE_DIR) / 'wama' / 'model_manager' / 'templates' /
                'model_manager' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('return !!m.installable;', page)
        self.assertNotIn('install_dir); }', page)
        self.assertNotIn('https://huggingface.co/${', page)
        self.assertIn('model.platform_url ?', page)

    def test_a_github_release_links_to_its_release_page(self):
        row = self._row(platform_ref='github:Phhofm/models/releases/tag/4xNomosUni_span_multijpg')
        self.assertEqual('https://github.com/Phhofm/models/releases/tag/4xNomosUni_span_multijpg',
                         row.to_dict()['platform_url'])


class TheAppWalkerTakesTheRouteTest(TestCase):
    """`install_requirements(apply=True)` : chaque modèle requis passe par `request_install`."""

    def _walk(self, request_result):
        import json
        import tempfile

        from wama.model_manager.services import model_installer as mi
        row = _catalog_row('test:walker-model')
        manifest = {'requires': [{'kind': 'model', 'key': row.model_key}]}
        with tempfile.TemporaryDirectory() as root:
            apps = Path(root) / 'manifests' / 'apps'
            apps.mkdir(parents=True)
            (apps / 'walkertest.json').write_text(json.dumps(manifest), encoding='utf-8')
            fake_module = Path(root) / 'a' / 'b' / 'c' / 'model_installer.py'
            with mock.patch.object(mi, '__file__', str(fake_module)), \
                    mock.patch.object(mi, 'spec_for_catalog_row',
                                      return_value={'kind': 'hf', 'ref': 'o/x'}), \
                    mock.patch.object(mi, 'request_install',
                                      return_value=request_result) as req:
                res = mi.install_requirements('walkertest', apply=True)
        return row, res, req

    def test_each_model_is_requested_on_the_walker_way(self):
        row, res, req = self._walk({'ok': True, 'started': True, 'task_id': 't-9'})
        req.assert_called_once_with(row.model_key, via='app_requirements')
        self.assertTrue(res['ok'])
        self.assertEqual('t-9', res['models'][0]['task_id'])

    def test_a_disk_refusal_is_said_and_fails_the_walk(self):
        _row, res, _req = self._walk({'ok': False, 'reason': 'insufficient_storage',
                                      'blocked': {'error': 'Espace insuffisant'}})
        self.assertFalse(res['ok'])
        self.assertEqual('Espace insuffisant', res['models'][0]['error'])


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


class OpenRequestsDoNotLingerTest(TestCase):
    """Une demande jamais reprise ne reste pas « en cours » (2026-09-30 : deux demandes pyannote,
    l'une tombée sur un worker d'avant le journal, restaient ouvertes sans fin)."""

    def test_the_task_closes_older_requests_of_the_same_key(self):
        from wama.model_manager import tasks
        install_history.queued('model', 'proposed:test:twice', name='Deux fois', via='assistant')
        install_history.queued('model', 'proposed:test:twice', name='Deux fois', via='assistant')
        tasks.install_proposed_task.apply(args=['proposed:test:twice']).get()
        statuses = sorted(InstallEvent.objects.filter(key='proposed:test:twice')
                          .values_list('status', flat=True))
        self.assertEqual(statuses, ['FAILURE', 'FAILURE'])     # l'ancienne close, la reprise refusée
        self.assertFalse(InstallEvent.objects.filter(key='proposed:test:twice',
                                                     finished_at__isnull=True).exists())

    def test_the_calendar_shows_a_stale_request_as_never_taken_up(self):
        old = timezone.now() - install_history.QUEUED_MAX_AGE - timedelta(hours=1)
        InstallEvent.objects.create(kind='model', key='k-old', name='Oublié', via='assistant',
                                    started_at=old)
        events = install_history.calendar_events(old - timedelta(hours=1), timezone.now())
        event = next(e for e in events if e.key.startswith('install:'))
        self.assertEqual((event.status, event.extra['installRunning']), ('FAILURE', False))
        self.assertLess(event.end - event.start, timedelta(hours=1), 'pas de barre qui s’allonge')

    def test_counter_proof_a_recent_open_request_is_still_running(self):
        InstallEvent.objects.create(kind='model', key='k-new', name='En cours', via='assistant',
                                    started_at=timezone.now() - timedelta(minutes=5))
        now = timezone.now()
        event = install_history.calendar_events(now - timedelta(hours=1), now + timedelta(hours=1))[0]
        self.assertEqual((event.status, event.extra['installRunning']), ('RUNNING', True))
