"""An app BORN FROM A MANIFEST (`app_sandbox create --from-manifest`) has its assistant tools and its
Studio node DERIVED, like a twin has its source's (2026-11-01, Fabien's decision : « on porte tout,
régénérable »). Until then the Writer had a creator and a triad entry written by hand in
`tool_api.py`, which no regeneration reproduced.

What is held :
  1. a born app receives the registry entry ITS declaration carries (`inject_sandbox_registry(born=)`),
     paths written for the manifest key and retargeted to the label, under the same `resolves` judge ;
  2. its creator is derived from the deposit view of its card : one argument per input port, of the
     same name (the Studio contract), the schema settings through `**params` ; a refused file refuses
     the call BEFORE anything is posted ;
  3. birth and regeneration keep the same facts in the registry (`born_registry_facts`) — the triad
     and the Studio node included ;
  4. the Studio node keeps only the declarative fields `write_back` would write (`STUDIO_FIELDS`) ;
  5. on the real Writer (when installed) : the three tools exist, an element is born through the
     card's view, a refused file creates nothing, and the « CV » document kind is accepted.
"""
from unittest import mock, skipUnless

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from wama import tool_api as T
from wama.common import sandbox

BORN = {'label': 'notes_01', 'generated_from': '', 'from_manifest': 'manifests/app_drafts/notes.json',
        'declarations': {'tool_api': {'triad_spec': {'model': 'wama.notes.models.Note',
                                                     'task': 'wama.notes.tasks.write_task'}}}}
PORTS = {'inputs': [{'id': 'prompt', 'label': 'Prompt', 'group': 'prompt', 'types': ['prompt']},
                    {'id': 'reference_document', 'label': 'Document de référence',
                     'group': 'reference', 'types': ['document']}]}


def _triad(declarations):
    return (declarations.get('tool_api') or {}).get('triad_spec')


class BornRegistryInjectionTest(SimpleTestCase):

    def _inject(self, entries, resolves=True, born=_triad):
        registry = {}
        with mock.patch.object(sandbox, 'load_registry', return_value=entries), \
                mock.patch.object(sandbox, 'sandbox_labels', return_value=['notes_01']), \
                mock.patch.object(sandbox, 'resolves', return_value=resolves):
            sandbox.inject_sandbox_registry(registry, born=born)
        return registry

    def test_a_born_app_receives_its_declared_entry_retargeted_on_its_label(self):
        entry = self._inject([BORN])['notes_01']
        self.assertEqual('wama.notes_01.models.Note', entry['model'])
        self.assertEqual('wama.notes_01.tasks.write_task', entry['task'])

    def test_a_declared_path_that_does_not_resolve_gives_no_entry(self):
        """Counter-proof : the judge of the twins holds for a born app too."""
        self.assertEqual({}, self._inject([BORN], resolves=False))

    def test_without_a_born_reader_or_a_declaration_nothing_is_injected(self):
        self.assertEqual({}, self._inject([BORN], born=None))
        self.assertEqual({}, self._inject([{**BORN, 'declarations': {}}]))

    def test_the_manifest_key_is_the_base_of_the_label(self):
        self.assertEqual('writer', sandbox.manifest_key('writer_01'))
        self.assertEqual('', sandbox.manifest_key('writer'))


class BornCreatorTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('born_creator_user', password='x')
        with mock.patch('wama.common.app_registry.studio_node_ports', return_value=PORTS):
            self.creator = T._born_creator('notes_01')
        patches = [mock.patch.object(T, '_route_dispo', return_value='upload'),
                   mock.patch.object(T, '_refus_app', return_value=None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_one_argument_per_port_of_the_same_name_then_the_settings(self):
        import inspect
        params = inspect.signature(self.creator).parameters
        self.assertEqual(['user', 'prompt', 'reference_document', 'params'], list(params))
        self.assertEqual(inspect.Parameter.VAR_KEYWORD, params['params'].kind)
        self.assertEqual('write', self.creator.wama_effect['effect'])

    def test_the_deposit_view_receives_the_prompt_the_designated_file_and_the_settings(self):
        with mock.patch('wama.common.utils.media_paths.designated_file',
                        return_value='/media/users/1/temp/cv.pdf'), \
                mock.patch.object(T, '_poster_vue',
                                  return_value=(200, {'id': 7, 'status': 'PENDING'})) as post:
            out = self.creator(self.user, prompt=' Mon parcours ',
                               reference_document='users/1/temp/cv.pdf', document_kind='cv')
        self.assertEqual({'item_id': 7, 'status': 'PENDING'}, out)
        (user, app, route, args, data), _ = post.call_args
        self.assertEqual(('notes_01', 'upload'), (app, route))
        self.assertEqual({'prompt': 'Mon parcours',
                          'reference_document__designated': ['users/1/temp/cv.pdf'],
                          'document_kind': 'cv'}, data)

    def test_a_rejected_file_stops_the_call_before_anything_is_posted(self):
        from wama.common.utils.media_paths import InputRefused
        with mock.patch('wama.common.utils.media_paths.designated_file',
                        side_effect=InputRefused('fichier introuvable')), \
                mock.patch.object(T, '_poster_vue') as post:
            out = self.creator(self.user, prompt='x', reference_document='users/9/nope.pdf')
        self.assertIn('fichier introuvable', out['error'])
        post.assert_not_called()

    def test_a_file_the_port_does_not_take_stops_the_call_before_anything_is_posted(self):
        """The format gate is the card's list for THIS port (`port_takes`): a document port takes
        no image, whatever the app declares elsewhere."""
        with mock.patch('wama.common.utils.media_paths.designated_file',
                        return_value='/media/users/1/temp/photo.png'), \
                mock.patch.object(T, '_poster_vue') as post:
            out = self.creator(self.user, prompt='x', reference_document='users/1/temp/photo.png')
        self.assertIn('.png', out['error'])
        post.assert_not_called()

    def test_what_the_view_rejects_is_reported_in_its_own_words(self):
        with mock.patch.object(T, '_poster_vue',
                               return_value=(400, {'error': 'Rien à ajouter'})):
            out = self.creator(self.user)
        self.assertIn('Rien à ajouter', out['error'])


class BornRegistryFactsTest(SimpleTestCase):

    def test_birth_and_regeneration_keep_the_triad_and_the_studio_node(self):
        import json
        from pathlib import Path

        from django.conf import settings

        from wama.common.management.commands.app_sandbox import born_registry_facts
        manifest = json.loads((Path(settings.BASE_DIR) / 'manifests/app_drafts/writer.json')
                              .read_text(encoding='utf-8'))
        facts = born_registry_facts(manifest, 'writer_07')
        self.assertEqual({'modes', 'prompts', 'tool_api', 'studio'}, set(facts['declarations']))
        self.assertEqual('writer_07:index', facts['catalog']['url_name'])
        self.assertIn('CV', facts['catalog']['description'])


class BornStudioEntryTest(SimpleTestCase):

    def test_only_the_declarative_fields_of_a_runnable_node_are_kept(self):
        from wama.studio.services.generic_runner import _born_studio_entry
        studio = {'runnable': True, 'params_module': 'wama.notes.params', 'params_attr': 'PARAMS_JSON'}
        self.assertEqual({'params_module': 'wama.notes.params', 'params_attr': 'PARAMS_JSON'},
                         _born_studio_entry({'studio': studio}))
        self.assertIsNone(_born_studio_entry({'studio': {**studio, 'runnable': False}}))
        self.assertIsNone(_born_studio_entry({}))


@skipUnless('writer_01' in sandbox.sandbox_labels(), 'the Writer sandbox (unversioned) is not installed')
class RealWriterTest(TestCase):
    """The real Writer, born from `manifests/app_drafts/writer.json` — its tools come from its
    declarations once its registry entry has been regenerated (`app_sandbox substitute`)."""

    def setUp(self):
        self.user = self._account('writer_tool_user')

    @staticmethod
    def _account(name, tier='admin'):
        """Through the TOOLS a sandbox app opens to an administrator, or to the developer who
        created it (`tool_app_accessible`, 2026-11-02) ; the Writer was created by the command
        line, so : an administrator."""
        from wama.accounts.models import UserProfile
        user = User.objects.create_user(name, password='x')
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.account_tier = tier
        profile.save()
        return User.objects.get(pk=user.pk)

    def test_the_three_tools_are_derived(self):
        for name in ('add_to_writer_01', 'start_writer_01', 'get_writer_01_status'):
            self.assertIn(name, T.TOOL_REGISTRY)
        self.assertEqual('wama.writer_01.models.WriterDocument', T.TRIAD_SPECS['writer_01']['model'])

    def test_a_prompt_alone_is_born_through_the_card_view_with_a_cv_kind(self):
        from wama.writer_01.models import WriterBatchItem, WriterDocument
        out = T.execute_tool('add_to_writer_01', {'prompt': ' Mon parcours ', 'document_kind': 'cv',
                                                  'language': 'en'}, self.user)
        self.assertNotIn('error', out, out)
        doc = WriterDocument.objects.get(pk=out['item_id'])
        self.assertEqual(('Mon parcours', 'cv', 'CV', 'en', 'PENDING'),
                         (doc.prompt, doc.document_kind, doc.get_document_kind_display(),
                          doc.language, doc.status))
        self.assertTrue(WriterBatchItem.objects.filter(document=doc).exists())

    def test_nothing_to_write_and_an_unknown_file_create_nothing(self):
        from wama.writer_01.models import WriterDocument
        self.assertIn('error', T.execute_tool('add_to_writer_01', {'prompt': '   '}, self.user))
        out = T.execute_tool('add_to_writer_01', {'prompt': 'x',
                                                  'reference_document': 'users/999/nope.pdf'},
                             self.user)
        self.assertIn('error', out)
        self.assertEqual(0, WriterDocument.objects.filter(user=self.user).count())

    def test_the_status_row_follows_the_element_and_another_users_is_not_started(self):
        out = T.execute_tool('add_to_writer_01', {'prompt': 'x'}, self.user)
        rows = T.execute_tool('get_writer_01_status', {}, self.user)['jobs']
        self.assertEqual([out['item_id']], [r['id'] for r in rows])
        self.assertIsNone(rows[0]['output_url'])
        other = self._account('writer_tool_other')
        res = T.execute_tool('start_writer_01', {'document_id': out['item_id']}, other)
        self.assertIn('error', res)
        developer = self._account('writer_tool_developer', 'developpeur')
        refused = T.execute_tool('add_to_writer_01', {'prompt': 'x'}, developer)
        self.assertIn('error', refused, "a developer who did not create it : refused by the tools")

    def test_the_studio_has_a_writer_node(self):
        from wama.studio.services.generic_runner import GENERIC_APPS
        self.assertEqual('wama.writer_01.params', GENERIC_APPS['writer_01']['params_module'])


@skipUnless('translator_01' in sandbox.sandbox_labels(),
            'the Translator sandbox (unversioned) is not installed')
class RealTranslatorTest(TestCase):
    """The Translator had NO tool (2026-11-02) : born from a manifest without its `tool_api` facet.
    Declared in `manifests/app_drafts/translator.json`, regenerated by its route."""

    def test_a_text_is_born_through_the_card_view_and_its_status_is_read(self):
        from wama.translator_01.models import TranslatorText
        user = RealWriterTest._account('translator_tool_user')
        out = T.execute_tool('add_to_translator_01', {'prompt': 'Bonjour', 'target_language': 'en'},
                             user)
        self.assertNotIn('error', out, out)
        text = TranslatorText.objects.get(pk=out['item_id'])
        self.assertEqual(('Bonjour', 'en', 'PENDING'), (text.prompt, text.target_language, text.status))
        rows = T.execute_tool('get_translator_01_status', {}, user)['jobs']
        self.assertEqual([(text.pk, 'en')], [(r['id'], r['target_language']) for r in rows])
        self.assertIn('text_id', T.tool_arg_names('start_translator_01'))
