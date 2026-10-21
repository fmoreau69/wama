"""A setting bound to a capability of the chosen model (`cap_from`) — the DECLARATIONS, every app.

`tests_cap_from_js` keeps the rule itself (V8). Here: what the apps DECLARE can be bound at all,
and the capability the screen reads is the one the task applies. Session of 2026-10-02: the
composer offered 10 minutes on its slider while MusicGen produces 30 s — the task reduced the
duration silently at launch. The mechanism existed (imager, 2026-09-23); the composer now declares
it, its capability comes from its model declarations, and the grid criterion recognises the
declarative form. No app is named in the generic class: an app that declares `cap_from` enters.
"""
from django.test import SimpleTestCase, TestCase

from wama.common.services import conformity_checker as cc
from wama.common.utils.model_capabilities import (CANONICAL_CAPABILITIES,
                                                  duration_caps_from_declaration)


def _declared_bindings():
    """(app, schema attribute, schema, param) for every BINDING of a declared setting — a setting
    may read several capabilities (the temperature, 2026-10-21): one tuple per binding, the param
    carrying that binding alone as its `cap_from`."""
    from wama.common.app_registry import APP_CATALOG
    from wama.common.utils.param_schema import cap_bindings, declared_param_schemas
    out = []
    for app, spec in APP_CATALOG.items():
        if (spec or {}).get('sandbox'):
            continue
        declared = declared_param_schemas(app) or {}
        for attr, schema in (declared.get('schemas') or {}).items():
            for p in schema:
                if isinstance(p, dict):
                    out += [(app, attr, schema, {**p, 'cap_from': cf}) for cf in cap_bindings(p)]
    return out


class EveryDeclaredBindingCanBeBoundTest(SimpleTestCase):

    def test_the_fleet_is_measured(self):
        apps = {app for app, *_ in _declared_bindings()}
        self.assertGreaterEqual(len(apps), 2, sorted(apps))

    def test_each_binding_names_a_catalogue_model_field_of_its_own_schema(self):
        """`WamaParams._bindCapFrom` needs the model field in the SAME schema, with a catalogue
        source — otherwise the bound is inactive (and now says so in the console)."""
        for app, attr, schema, p in _declared_bindings():
            with self.subTest(app=app, schema=attr, param=p['name']):
                cf = p['cap_from']
                model = next((q for q in schema if q.get('name') == cf.get('field')), None)
                self.assertIsNotNone(model, f"`{cf.get('field')}` is not a field of this schema")
                self.assertTrue(cf.get('source') or model.get('help_source'),
                                'no catalogue source to read the capabilities from')
                shared = set(p.get('contexts') or ()) & set(model.get('contexts') or ())
                self.assertTrue(shared or not (p.get('contexts') and model.get('contexts')),
                                'the setting and its model field are never rendered together')

    def test_each_binding_reads_a_canonical_capability(self):
        for app, attr, _schema, p in _declared_bindings():
            with self.subTest(app=app, schema=attr, param=p['name']):
                cf = p['cap_from']
                self.assertIn(cf.get('capability'), CANONICAL_CAPABILITIES)
                if cf.get('extension'):
                    self.assertIn(cf['extension'], CANONICAL_CAPABILITIES)
                self.assertIn(cf.get('mode', 'range'), ('range', 'fixed', 'note', 'reads'))

    def test_a_reads_binding_reads_a_list_of_settings_or_a_boolean(self):
        """« reads » greys a setting the chosen model does not read: the capability must be the
        list of settings an engine reads (`params`) or a boolean `supports_*` — a numeric limit
        would grey nothing, or everything, without a word."""
        reads = [(app, p) for app, _attr, _schema, p in _declared_bindings()
                 if p['cap_from'].get('mode') == 'reads']
        self.assertGreaterEqual(len({app for app, _p in reads}), 3, 'transcriber, enhancer, reader')
        for app, p in reads:
            with self.subTest(app=app, param=p['name']):
                capability = p['cap_from']['capability']
                self.assertTrue(capability == 'params' or capability.startswith('supports_'),
                                capability)


class DurationCapabilityFromDeclarationTest(SimpleTestCase):

    def test_a_declared_maximum_becomes_the_canonical_capability(self):
        self.assertEqual({'max_duration_s': 30.0}, duration_caps_from_declaration({'max_duration': 30}))

    def test_nothing_declared_affirms_nothing(self):
        for config in ({}, {'max_duration': 0}, {'max_duration': None}, {'max_duration': True}):
            self.assertEqual({}, duration_caps_from_declaration(config), config)


class ComposerDurationFollowsTheModelTest(TestCase):
    """One fact — the model's maximum duration — for the screen, the catalogue and the task."""

    def test_the_slider_is_bound_to_the_capability_of_the_chosen_model(self):
        from wama.composer.params import PARAMS_JSON
        duration = next(p for p in PARAMS_JSON if p['name'] == 'duration')
        self.assertEqual({'field': 'model', 'capability': 'max_duration_s'}, duration['cap_from'])

    def test_the_slider_starts_where_the_model_starts(self):
        """Rendered without a value (new profile) the slider sat at the middle of its scale, 305 s,
        with an empty label (seen in the browser, 2026-10-03): the schema default is the model's."""
        from wama.composer.models import ComposerGeneration
        from wama.composer.params import PARAMS_JSON
        duration = next(p for p in PARAMS_JSON if p['name'] == 'duration')
        self.assertEqual(ComposerGeneration._meta.get_field('duration').default, duration['default'])

    def test_the_catalogue_receives_the_capability_of_every_declared_model(self):
        from wama.common.utils.model_declarations import declarations
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry()
        registry._models = {}
        registry._discover_composer_models()
        declared = declarations('composer')
        self.assertTrue(declared)
        for model_id, config in declared.items():
            with self.subTest(model=model_id):
                caps = registry._models[f'composer:{model_id}'].capabilities
                self.assertEqual(float(config['max_duration']), caps['max_duration_s'])

    def test_the_task_applies_the_same_limit_by_catalogue_key_or_bare_id(self):
        from wama.composer.utils.model_config import clamp_duration
        self.assertEqual(30, clamp_duration(600, 'composer:musicgen-small'))
        self.assertEqual(30, clamp_duration(600, 'musicgen-small'))
        self.assertEqual(300, clamp_duration(600, 'composer:minimax-music3'))

    def test_without_a_declared_limit_only_the_schema_bounds(self):
        """Counter-test: no model, a model of another source, an « auto » — the schema's 600 s."""
        from wama.composer.utils.model_config import clamp_duration
        for model in (None, 'huggingface:m-a-p/YuE2-3B', 'auto:text-to-music'):
            self.assertEqual(600, clamp_duration(600, model), model)
        self.assertEqual(600, clamp_duration(9999, None), 'the schema still bounds')


class ModelCapabilitiesCriterionTest(SimpleTestCase):
    """`model_caps_ui` recognises BOTH forms — it only knew the wired one, so the imager, bound by
    `cap_from` since 2026-09-23, was red."""

    def _verdict(self, app):
        criterion = next(c for c in cc.CRITERIA if c.key == 'model_caps_ui')
        return criterion.fn(cc._AppFiles(app))

    def test_the_declarative_form_is_green_and_names_its_line(self):
        for app in ('imager', 'composer'):
            with self.subTest(app=app):
                state, evidence = self._verdict(app)
                self.assertIs(state, True)
                self.assertIn(f'{app}/params.py:', evidence)

    def test_the_wired_form_is_still_green(self):
        """Counter-test: the synthesizer calls `WamaModelCaps` and declares no `cap_from`."""
        state, evidence = self._verdict('synthesizer')
        self.assertIs(state, True)
        self.assertNotIn('cap_from', evidence)

    def test_an_app_without_an_engine_select_stays_outside(self):
        self.assertEqual((None, None), self._verdict('converter'))

    def test_a_comment_naming_the_mechanism_is_not_an_adoption(self):
        from wama.common.tests.tests_queue_delete_contract import CriteresDeLaGrilleTest
        f, _cc = CriteresDeLaGrilleTest._app(self, {'params.py': "# cap_from={'field': 'model'}\n"})
        self.assertIsNone(f.find_code(cc.PARAMS, r'\bcap_from\s*=\s*\{'))


#: The three comment shapes that made `model_caps_ui` / `input_match_ui` green on 2026-10-13 —
#: the transcriber and the enhancer announced the REMOVAL of their `WamaModelCaps` in a comment.
COMMENTED = {
    'templates/app/index.html': (
        "{% comment %}Le grisage par `WamaModelCaps.init(` est RETIRÉ.{% endcomment %}\n"
        "<script>\n  // WamaInputMatch.init({ … }) retiré lui aussi\n</script>\n"),
    'static/app/js/index.js': "// WamaModelCaps.init({ controls }) — ancienne forme\n",
}


class TheGridCountsACallNotAMentionTest(SimpleTestCase):
    """`model_caps_ui` and `input_match_ui` look for a CALL of the brick outside comments."""

    def _files(self, files):
        from wama.common.tests.tests_queue_delete_contract import CriteresDeLaGrilleTest
        return CriteresDeLaGrilleTest._app(self, files)[0]

    def _verdict(self, key, files, named=frozenset({'hotwords'})):
        from unittest import mock
        criterion = next(c for c in cc.CRITERIA if c.key == key)
        with mock.patch.object(cc, '_uses_models', lambda f: True), \
             mock.patch.object(cc, '_has_engine_select', lambda f: True), \
             mock.patch.object(cc, '_capability_named_settings',
                               lambda f: set(named) if named is not None else None):
            return criterion.fn(self._files(files))

    def test_a_comment_announcing_the_removal_is_not_an_adoption(self):
        for key in ('model_caps_ui', 'input_match_ui'):
            with self.subTest(criterion=key):
                self.assertIs(self._verdict(key, COMMENTED)[0], False)

    def test_a_call_is_an_adoption(self):
        """Counter-test: the same files plus a real call — green, and the evidence names it."""
        for key, call in (('model_caps_ui', 'WamaModelCaps.init({modelSelectId: "m"});'),
                          ('input_match_ui', 'WamaInputMatch.init({selectId: "m"});')):
            with self.subTest(criterion=key):
                files = dict(COMMENTED)
                files['static/app/js/index.js'] += call + '\n'
                state, evidence = self._verdict(key, files)
                self.assertIs(state, True)
                self.assertIn('index.js:2', evidence)

    def test_nothing_to_derive_is_outside_with_its_reason_never_blindly(self):
        """No capability of the proposed models names a setting (the describer): outside, said.
        An unreadable catalogue (None) is NOT « nothing »: red, never N/A on a blind read."""
        state, reason = self._verdict('model_caps_ui', COMMENTED, named=set())
        self.assertIsNone(state)
        self.assertIn('ne nomme', reason)
        self.assertIs(self._verdict('model_caps_ui', COMMENTED, named=None)[0], False)


class CapabilityNamedSettingsTest(SimpleTestCase):
    """What « a capability names a setting » reads: `params` lists, and `supports_<setting>`."""

    def _named(self, schema, models):
        from unittest import mock
        from wama.common.tests.tests_queue_delete_contract import CriteresDeLaGrilleTest
        f = CriteresDeLaGrilleTest._app(self, {})[0]
        with mock.patch('wama.common.utils.param_schema.declared_param_schemas',
                        lambda app: {'schemas': {'PARAMS_JSON': schema}}), \
             mock.patch('wama.model_manager.services.get_registry_models',
                        lambda source, **q: ([], [{'capabilities': c} for c in models])):
            return cc._capability_named_settings(f)

    SELECT = {'name': 'backend', 'type': 'select', 'options_source': 'catalog',
              'options_query': {'task': 'transcription'}}

    def test_a_listed_setting_and_a_supports_flag_name_settings(self):
        schema = [self.SELECT, {'name': 'hotwords'}, {'name': 'mode'}, {'name': 'other'}]
        models = [{'supports_hotwords': False, 'supports_timestamps': True},
                  {'params': ['mode', 'unknown']}]
        self.assertEqual({'hotwords', 'mode'}, self._named(schema, models))

    def test_capabilities_that_name_no_setting_of_the_app_name_nothing(self):
        """The describer: transcription models flag hotwords and timestamps, chat models flag
        vision and tools — none of them is a describer setting."""
        schema = [self.SELECT, {'name': 'output_style'}, {'name': 'max_length'}]
        models = [{'supports_hotwords': True, 'supports_timestamps': True},
                  {'vision': True, 'tools': True, 'inputs_required': ['prompt']}]
        self.assertEqual(set(), self._named(schema, models))
