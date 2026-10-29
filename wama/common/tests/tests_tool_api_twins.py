"""The creation tool of a sandbox TWIN, derived from its source's (2026-10-29, Fabien's decision :
« le même mécanisme qu'`importer_for` »).

What is held : `app_label` is INTERNAL — never announced (description, MCP schema, Studio ports)
nor accepted from a caller, so no model chooses the app it writes into ; the derivation fixes it to
the twin's label ; a source whose tool cannot be re-targeted gives no twin tool at all (rather none
than one writing into the ORIGINAL app) ; every creation tool of the ten apps can be re-targeted.
"""
from unittest import mock

from django.test import TestCase

from wama import tool_api as T


def _source(user, file_path: str, mode: str = 'auto', app_label: str = 'reader', **params):
    """A stand-in creator : it reports what it was called with."""
    return {'item_id': 1, 'app_label': app_label, 'file_path': file_path, 'params': params}


class AppLabelIsInternalTest(TestCase):

    def test_the_public_signature_hides_app_label(self):
        names = set(T._tool_signature(T.add_to_reader).parameters)
        self.assertIn('file_path', names)
        self.assertNotIn('app_label', names)

    def test_a_caller_cannot_pass_app_label(self):
        kept, _ignored = T.sanitize_tool_args('add_to_reader', {'file_path': 'x.pdf',
                                                                'app_label': 'reader_01'})
        self.assertEqual('x.pdf', kept['file_path'])
        self.assertNotIn('app_label', kept)

    def test_no_description_announces_it(self):
        for name, described in T.tool_descriptions().items():
            with self.subTest(tool=name):
                self.assertNotIn('app_label', described['args'])

    def test_every_creation_tool_of_the_ten_apps_can_be_retargeted(self):
        import inspect
        for app in ('anonymizer', 'avatarizer', 'composer', 'converter', 'describer', 'enhancer',
                    'imager', 'reader', 'synthesizer', 'transcriber'):
            with self.subTest(app=app):
                params = inspect.signature(T.TOOL_REGISTRY[f'add_to_{app}']).parameters
                self.assertIn('app_label', params)
                self.assertEqual(app, params['app_label'].default)


class TwinCreatorIsDerivedTest(TestCase):

    def _register(self, registry, entries, installed):
        # The module namespace too : the derivation publishes `add_to_<twin>` there as well, and a
        # stand-in left behind would be what the NEXT test of the run calls (vécu : the generic
        # designation guard met this file's `_source` under the name `add_to_reader_01`).
        with mock.patch.dict(vars(T)), \
                mock.patch.dict(T.TOOL_REGISTRY, registry, clear=True), \
                mock.patch('wama.common.sandbox.load_registry', return_value=entries), \
                mock.patch('wama.common.sandbox.sandbox_labels', return_value=installed):
            T._register_twin_creators()
            return dict(T.TOOL_REGISTRY)

    def test_the_twin_tool_calls_its_source_with_the_twin_label_fixed(self):
        registry = self._register({'add_to_reader': _source},
                                  [{'label': 'reader_01', 'generated_from': 'reader'}],
                                  ['reader_01'])
        twin = registry['add_to_reader_01']
        self.assertEqual('add_to_reader_01', twin.__name__)
        out = twin(None, 'users/1/temp/a.pdf', app_label='reader', language='fr')
        self.assertEqual(('reader_01', 'users/1/temp/a.pdf', {'language': 'fr'}),
                         (out['app_label'], out['file_path'], out['params']),
                         'the label is FIXED, whatever the caller passes')
        self.assertEqual(set(T._tool_signature(_source).parameters),
                         set(T._tool_signature(twin).parameters), 'same public surface')

    def test_a_source_that_cannot_be_retargeted_gives_no_twin_tool(self):
        def legacy(user, file_path: str, **params):
            return {'item_id': 1}
        registry = self._register({'add_to_reader': legacy},
                                  [{'label': 'reader_01', 'generated_from': 'reader'}],
                                  ['reader_01'])
        self.assertNotIn('add_to_reader_01', registry)

    def test_a_twin_without_its_package_or_born_from_a_manifest_gets_nothing(self):
        registry = self._register({'add_to_reader': _source},
                                  [{'label': 'reader_01', 'generated_from': 'reader'},
                                   {'label': 'writer_01', 'generated_from': None}],
                                  ['writer_01'])
        self.assertEqual({'add_to_reader'}, set(registry))
