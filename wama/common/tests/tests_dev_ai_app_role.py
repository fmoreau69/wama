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
from django.test import SimpleTestCase

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

    def test_a_remote_cut_is_replayed_once_locally_and_a_role_error_is_not(self):
        from unittest import mock
        cut = (1, 'RuntimeError: ilaas : litellm.InternalServerError: Connection error.')
        for first, expected_calls in ((cut, 2), ((1, 'SystemExit: [app] REFUS : clé'), 1),
                                      ((0, 'ok'), 1)):
            with self.subTest(first=first[1][:30]):
                log = []
                with mock.patch.object(self.chain, 'run', side_effect=[first, (0, 'ok')]) as run:
                    self.chain.run_role('run_app_manifest.py', ['--key', 'x'], 'ilaas', 'qwen', log)
                self.assertEqual(expected_calls, run.call_count)
                if expected_calls == 2:
                    self.assertEqual(['--provider', 'ollama'], run.call_args_list[1].args[0][-2:])
        # Un rôle LOCAL qui échoue n'est jamais rejoué : il n'y a pas de « plus local ».
        with mock.patch.object(self.chain, 'run', side_effect=[cut, (0, 'ok')]) as run:
            self.chain.run_role('run_app_manifest.py', [], 'ollama', '', [])
        self.assertEqual(1, run.call_count)


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
