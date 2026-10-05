"""What a process WATCHES is derived from the settings (`Param.stales`, 2026-10-05).

`check_redundancy` found the `watched` lists of the SIX app pipelines to be setting names copied
from the schema, by hand, process by process. The setting now says once which processes it makes
stale; `AppPipeline.watched_of(spec)` joins those with the fields OFF the schema
(`ProcessSpec.watched`: input files, `prompt_processed`…). Form chosen by the pipeline session:
no implicit default — a setting that forgets would make nothing stale, silently.

Generic guards over every REAL app pipeline (sandbox twins are regenerated, never edited):
  1. every ELEMENT setting of the schema is accounted for — it makes a process stale, or it is
     a process's on/off switch (`toggle`), or an OUTPUT setting (`output_spec`), or it is
     DECLARED without staleness (`stales=()`, display settings);
  2. a `stales` names a process of the app's pipeline (a typo would watch nothing);
  3. a schema setting is never listed again by hand in `ProcessSpec.watched` (one source).
"""
from django.test import SimpleTestCase

from wama.common.services.process_pipeline import (APP_PIPELINES, _load_declarations,
                                                   declared_stales)
from wama.common.utils.output_formats import OUTPUT_PARAM_NAMES
from wama.common.utils.param_schema import _pget, declared_param_schemas


def _real_pipelines():
    from wama.common.sandbox import sandbox_labels
    _load_declarations()
    twins = set(sandbox_labels())
    return {app: pipe for app, pipe in APP_PIPELINES.items() if app not in twins}


def _element_settings(app):
    """`{name: param}` of the ELEMENT settings (context `item`) of every declared schema."""
    out = {}
    for schema in ((declared_param_schemas(app) or {}).get('schemas') or {}).values():
        for p in schema:
            if 'item' in (_pget(p, 'contexts') or ()):
                out.setdefault(_pget(p, 'name'), p)
    return out


class EverySettingSaysWhatItMakesStaleTest(SimpleTestCase):

    def test_the_real_app_pipelines_are_measured(self):
        self.assertGreaterEqual(len(_real_pipelines()), 7)

    def test_every_element_setting_is_accounted_for(self):
        for app, pipe in _real_pipelines().items():
            watched = {w for spec in pipe.specs for w in pipe.watched_of(spec)}
            toggles = {spec.toggle for spec in pipe.specs if spec.toggle}
            for name, p in _element_settings(app).items():
                with self.subTest(app=app, setting=name):
                    declared_none = _pget(p, 'stales') == () or _pget(p, 'stales') == []
                    self.assertTrue(name in watched or name in toggles
                                    or name in OUTPUT_PARAM_NAMES or declared_none,
                                    'this setting makes no process stale and says nothing: '
                                    'declare `stales=(<process>,)`, or `stales=()` for a '
                                    'display setting')

    def test_a_stales_names_a_process_of_the_pipeline(self):
        for app, pipe in _real_pipelines().items():
            keys = {spec.key for spec in pipe.specs}
            for process in declared_stales(app):
                with self.subTest(app=app, process=process):
                    self.assertIn(process, keys)

    def test_no_schema_setting_is_copied_back_into_a_process_list(self):
        for app, pipe in _real_pipelines().items():
            settings = set(_element_settings(app)) - set(OUTPUT_PARAM_NAMES)
            for spec in pipe.specs:
                with self.subTest(app=app, process=spec.key):
                    self.assertEqual([], [w for w in spec.watched if w in settings],
                                     'declare it on the setting (`stales`), not in `watched`')


class TheDerivationTest(SimpleTestCase):

    def test_settings_come_first_in_schema_order_then_the_off_schema_fields(self):
        pipe = _real_pipelines()['composer']
        watched = pipe.watched_of(pipe.spec('render'))
        self.assertEqual(('prompt', 'model', 'vocals', 'lyrics', 'quality_intent', 'duration'),
                         watched[:6])
        self.assertEqual(('prompt_processed', 'reference_score', 'melody_reference', 'source_url'),
                         watched[6:])
        self.assertNotIn('duration', pipe.watched_of(pipe.spec('plan')),
                         'the duration is the render only: the score does not read it')

    def test_a_pipeline_without_schema_keeps_its_own_list(self):
        from wama.common.services.process_pipeline import AppPipeline, ProcessSpec
        pipe = AppPipeline('no_such_app', (ProcessSpec('only', watched=('a', 'b')),), label='x')
        self.assertEqual(('a', 'b'), pipe.watched_of(pipe.spec('only')))
