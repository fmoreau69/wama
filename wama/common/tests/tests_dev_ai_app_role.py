"""
Le rôle `app` de wama-dev-ai (2026-10-15) — le brouillon du manifeste `app` d'une app NOUVELLE,
le maillon que la route « dépôt → app » n'outillait pas (ROUTE §10.5). Ses gardes sont les
contrôles mécaniques : une enveloppe IMPOSÉE quoi qu'écrive le modèle, une clé neuve, une brique
pas encore validée DITE sans faire échouer le brouillon — et une surface qui ne fait naître une
app que d'un manifeste du corpus de brouillons ou d'une sortie du rôle.

Chargé par chemin, comme `tests_dev_ai_bridge` (`wama-dev-ai` n'est pas importable).
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from wama.common.tests.tests_dev_ai_bridge import _charger as load_dev_ai_module


class AppRoleChecksTest(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role = load_dev_ai_module('run_app_manifest')

    def test_an_existing_app_or_a_malformed_key_is_refused_before_any_call(self):
        # `translator2` : la copie de la règle que le rôle tenait l'admettait, la naissance
        # (`app_sandbox.new_app_key_error`) la refuse — le rôle applique désormais la sienne.
        for key in ('reader', 'Translator', 'translator2', 'my-app', ''):
            with self.subTest(key=key):
                with self.assertRaises(self.role.AppDraftRefused):
                    self.role.check_key(key)
        self.role.check_key('translator_draft_test')

    def test_requires_take_the_kind_key_form_only(self):
        self.assertEqual([{'kind': 'library', 'key': 'libretranslate'},
                          {'kind': 'model', 'key': 'ollama:qwen3.8:latest'}],
                         self.role.parse_requires('library:libretranslate,model:ollama:qwen3.8:latest'))
        with self.assertRaises(self.role.AppDraftRefused):
            self.role.parse_requires('libretranslate')

    def test_the_envelope_is_imposed_whatever_the_model_wrote(self):
        concerns = []
        written = {'key': 'other', 'manifest_kind': 'model', 'visibility': 'public',
                   'requires': [{'kind': 'model', 'key': 'invented:model'}],
                   'source': {'type': 'github'},
                   'body': {'identity': {'url_name': 'other:index'}, 'data': {'x': 1},
                            'tool_api': {'triad_spec': {}}}}
        manifest = self.role.enforce_envelope(
            written, 'translator', [{'kind': 'library', 'key': 'libretranslate'}], concerns)
        self.assertEqual(('translator', 'app', 'private', 'authored'),
                         (manifest['key'], manifest['manifest_kind'], manifest['visibility'],
                          manifest['source']['type']))
        self.assertEqual([{'kind': 'library', 'key': 'libretranslate'}], manifest['requires'])
        self.assertEqual('translator:index', manifest['body']['identity']['url_name'])
        self.assertNotIn('data', manifest['body'])
        self.assertNotIn('tool_api', manifest['body'])
        # Chaque correction est DITE, jamais muette.
        self.assertTrue(any("'other'" in c for c in concerns), concerns)
        self.assertTrue(any('invented:model' in c for c in concerns), concerns)

    def test_a_brick_not_yet_validated_is_pending_not_an_error(self):
        manifest = self.role.enforce_envelope(
            {'name': 'T', 'description': 'd', 'body': {'ports': {'inputs': [{'no_id': 1}]}}},
            'translator', [{'kind': 'library', 'key': 'no-such-library-anywhere'}], [])
        errors, pending = self.role.split_checks(manifest)
        self.assertEqual(['library:no-such-library-anywhere'], pending)
        # Contre-épreuve : une faute de FORME du brouillon reste une erreur.
        self.assertTrue(any('ports.inputs' in e for e in errors), errors)

    def test_the_generators_judge_the_draft_before_any_birth(self):
        """Vécu le 2026-10-16 : un brouillon « clean » portait la surface d'édition du Writer
        (`draft_file`) ; seule la naissance l'a refusé. Le rôle passe désormais le brouillon dans
        les gabarits mêmes de la naissance, à blanc."""
        import json
        draft = json.loads(self.role.SHAPE_EXAMPLE.read_text(encoding='utf-8'))
        draft = self.role.enforce_envelope(draft, 'translator_judge_test', [], [])
        draft['body']['surfaces'] = [{'key': 'edit', 'label': 'x', 'edits': 'draft_file',
                                      'slots': []}]
        errors, _ = self.role.split_checks(draft)
        self.assertTrue(any(e.startswith('Gabarit surfaces') for e in errors), errors)

    def test_a_draft_without_facets_says_every_refusal_not_only_the_first_form_fault(self):
        """Vécu le 2026-10-16 : un brouillon sans `ports` ni `processing` ne rapportait que sa
        faute de capacité — la génération à blanc ne jouait qu'en l'absence de faute de forme."""
        draft = self.role.enforce_envelope(
            {'name': 'T', 'description': 'd',
             'body': {'capabilities': {'instant_preview': True}}}, 'translator', [], [])
        errors, _ = self.role.split_checks(draft)
        self.assertTrue(any('instant' in e for e in errors), errors)
        self.assertTrue(any(e.startswith('Gabarit tasks') for e in errors), errors)

    def test_a_facet_written_beside_the_body_goes_back_into_it(self):
        """Vécu le 2026-10-16 : le modèle refermait `body` après `params` et posait `processing`
        à la racine — aucun gabarit ne le voyait."""
        concerns = []
        kept = self.role.enforce_envelope(
            {'name': 'T', 'description': 'd', 'body': {'params': {'primary': 'P'}},
             'processing': {'item_model': 'TranslatorText'}}, 'translator', [], concerns)
        self.assertEqual('TranslatorText', kept['body']['processing']['item_model'])
        self.assertNotIn('processing', kept)
        self.assertTrue(any('processing' in c for c in concerns), concerns)

    def test_the_roles_that_write_a_long_object_share_one_window(self):
        """Trois rôles portaient chacun 32 768 (2026-10-16) : une valeur, dans `role_utils`."""
        from pathlib import Path
        root = Path(self.role.__file__).parent
        for name in ('run_app_manifest.py', 'run_codegen.py', 'run_backend.py'):
            src = (root / name).read_text(encoding='utf-8')
            self.assertIn('LONG_WRITE_NUM_CTX', src, name)
            self.assertNotIn('32768', src, f'{name} : fenêtre recopiée au lieu de lue')

    def test_the_category_is_derived_from_the_types_not_chosen_by_the_model(self):
        concerns = []
        kept = self.role.enforce_envelope(
            {'body': {'identity': {'category': 'transform'},
                      'ports': {'inputs': [{'id': 'text', 'group': 'prompt', 'types': ['prompt']}],
                                'outputs': [{'id': 'out', 'types': ['audio']}]}}},
            'translator', [], concerns)
        self.assertEqual('create', kept['body']['identity']['category'])
        self.assertTrue(any('transform' in c for c in concerns), concerns)

    def test_the_writer_surface_is_neither_shown_nor_kept(self):
        import json
        self.assertNotIn('surfaces', json.loads(self.role.shape_example())['body'])
        concerns = []
        kept = self.role.enforce_envelope({'body': {'surfaces': [{'key': 'edit'}]}},
                                          'translator', [], concerns)
        self.assertNotIn('surfaces', kept['body'])
        self.assertTrue(any('surfaces' in c for c in concerns), concerns)

    def test_the_shape_example_is_a_valid_app_draft(self):
        """Le seul brouillon né de zéro sert d'exemple de FORME : s'il ne valide plus, le rôle
        enseignerait une forme fausse."""
        import json
        example = json.loads(self.role.SHAPE_EXAMPLE.read_text(encoding='utf-8'))
        self.assertEqual('app', example['manifest_kind'])
        errors, _ = self.role.split_checks(example)
        self.assertEqual([], errors)


class RepoToAppChainTest(SimpleTestCase):
    """La chaîne passe la sortie d'une marche à la suivante, sans juger ; une coupure DISTANTE est
    rejouée une fois en local — jamais une erreur du rôle lui-même."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.chain = load_dev_ai_module('run_repo_app')

    def test_the_report_announced_by_a_step_is_read_and_its_manifest_file_skipped(self):
        from unittest import mock
        stdout = ("[app] → wama-dev-ai/outputs/app_x_2026-10-15_00-00.json\n"
                  "[app] → wama-dev-ai/outputs/app_x_2026-10-15_00-00.manifest.json\n")
        with mock.patch.object(Path, 'read_text', return_value='{"verdict": "clean"}') as read:
            self.assertEqual({'verdict': 'clean'}, self.chain.output_of(stdout))
        self.assertEqual(1, read.call_count)
        self.assertEqual({}, self.chain.output_of('[app] verdict : clean\n'))

    def test_a_remote_cut_is_replayed_once_locally_by_every_role_and_an_error_is_not(self):
        """La reprise vit dans `role_utils.call_llm` (2026-10-16) : le rôle `app` lancé SEUL par
        l'assistant n'en avait aucune quand elle vivait dans la chaîne."""
        from unittest import mock
        from wama.common.utils import llm_utils
        role_utils = load_dev_ai_module('role_utils')
        for error, replayed in (('litellm.InternalServerError: Connection error.', True),
                                ('401 clé refusée', False)):
            with self.subTest(error=error), \
                    mock.patch.object(llm_utils, 'chat_with_source', return_value=(None, error)), \
                    mock.patch.object(role_utils, 'resolve_model', return_value='qwen3.8:latest'), \
                    mock.patch.object(role_utils, 'local_llm_guard', return_value='0') as guard, \
                    mock.patch.object(role_utils, 'call_ollama', return_value='ok') as local:
                if replayed:
                    self.assertEqual('ok', role_utils.call_llm('ilaas', 'qwen', 's', 'u'))
                    self.assertEqual('qwen3.8:latest', local.call_args.args[0])
                    self.assertEqual('0', local.call_args.kwargs['keep_alive'])
                    guard.assert_called_once()
                else:
                    with self.assertRaises(RuntimeError):
                        role_utils.call_llm('ilaas', 'qwen', 's', 'u')
                    local.assert_not_called()


class ValidatedLibraryIsNeverReproposedTest(TestCase):
    """Relancer la chaîne sur un dépôt dont la librairie est VALIDÉE ne la repropose pas :
    `propose()` la remettrait en visibilité privée, défaisant la validation humaine."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.chain = load_dev_ai_module('run_repo_app')

    def test_a_registered_library_is_reused_and_the_librarian_not_run(self):
        import sys
        from unittest import mock
        from wama.common.models import Library
        Library.objects.create(key='zz_lib_test', name='zz',
                               vendor={'repo': 'Owner/ZzRepo', 'commit': 'abc', 'engine': 'zz'})
        self.assertEqual('zz_lib_test', self.chain.validated_library('Owner/ZzRepo'))
        self.assertEqual('', self.chain.validated_library('Owner/Other'))
        argv = ['run_repo_app.py', '--repo', 'Owner/ZzRepo', '--key', 'zz_app', '--need', 'x']
        with mock.patch.object(sys, 'argv', argv), \
                mock.patch.object(self.chain, 'run_role', return_value=(1, '')) as role, \
                mock.patch.object(self.chain, 'finish') as finish:
            self.chain.main()
        self.assertEqual(['run_app_manifest.py'], [c.args[0] for c in role.call_args_list])
        self.assertIn('library:zz_lib_test', role.call_args.args[1])
        self.assertTrue(finish.call_args.args[1]['library']['reused'])


class PlanAppIntegrationReadsPriorDecisionsTest(SimpleTestCase):
    """Le plan d'un DÉPÔT cherche lui-même ce que WAMA a déjà décidé : l'assistant, sans son skill
    de développement chargé, a lancé la chaîne sur LibreTranslate sans voir la décision du 12/08."""

    def test_a_repo_url_is_normalised_and_its_prior_decisions_returned(self):
        from unittest import mock
        from wama import tool_api
        hit = {'label': 'Route', 'section': '§10.5', 'doc': 'route', 'content': 'Translator…'}
        with mock.patch.object(tool_api, 'search_docs',
                               return_value={'results': [hit], 'count': 1}) as search:
            out = tool_api.plan_app_integration(
                object(), 'https://github.com/LibreTranslate/LibreTranslate.git')
        self.assertEqual('LibreTranslate/LibreTranslate', out['repo'])
        self.assertIn('LibreTranslate', search.call_args.args[1])
        self.assertEqual('§10.5', out['prior_decisions'][0]['section'])
        self.assertIn('prior_decisions', out['read_first'])
        self.assertTrue(any(r.startswith('repo_app') for r in out['roles']))


class AppRoleOnTheDevSurfaceTest(SimpleTestCase):
    """La surface lance le rôle et fait naître l'app au bac à sable — d'un manifeste admis seul."""

    def test_args_given_as_a_string_are_refused_with_the_expected_form(self):
        from wama.common.services.dev_tools import DevToolError, role_command
        with self.assertRaisesMessage(DevToolError, 'doit être un OBJET'):
            role_command('repo_app', 'repo=LibreTranslate/LibreTranslate, key=translator')

    def test_the_surface_admits_the_app_role_arguments(self):
        from wama.common.services.dev_tools import DevToolError, role_command
        argv = role_command('app', {'key': 'translator', 'need': 'traduire',
                                    'like': 'reader', 'requires': 'library:libretranslate'})
        self.assertEqual(['--key', 'translator', '--need', 'traduire', '--like', 'reader',
                          '--requires', 'library:libretranslate'], argv[2:])
        with self.assertRaises(DevToolError):
            role_command('app', {'manifest_file': 'x.json'})
        argv = role_command('repo_app', {'repo': 'LibreTranslate/LibreTranslate',
                                         'key': 'translator', 'need': 'traduire'})
        self.assertEqual(['--repo', 'LibreTranslate/LibreTranslate', '--key', 'translator',
                          '--need', 'traduire'], argv[2:])

    def test_an_app_is_born_only_from_a_draft_or_an_app_role_output(self):
        from wama.common.services.dev_tools import DevToolError, outputs_dir, sandbox_command
        outputs_dir().mkdir(parents=True, exist_ok=True)
        output = outputs_dir() / 'app_zz_test_2026-10-15_00-00.manifest.json'
        output.write_text('{}', encoding='utf-8')
        self.addCleanup(output.unlink)
        argv = sandbox_command('create', owner='dev', manifest=str(
            output.relative_to(Path(settings.BASE_DIR)).as_posix()))
        self.assertEqual(['app_sandbox', 'create', '--from-manifest',
                          'wama-dev-ai/outputs/app_zz_test_2026-10-15_00-00.manifest.json',
                          '--owner', 'dev'], argv[2:])
        self.assertIn('manifests/app_drafts/writer.json',
                      sandbox_command('create', manifest='manifests/app_drafts/writer.json'))
        for refused in ('manage.py', 'wama-dev-ai/outputs/task_x.json', '../etc/passwd',
                        'manifests/apps/reader.json'):
            with self.subTest(path=refused):
                with self.assertRaises(DevToolError):
                    sandbox_command('create', manifest=refused)
