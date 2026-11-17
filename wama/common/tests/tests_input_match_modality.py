"""The card's FILE, judged by what each model READS — `WamaInputMatch.modalitySlot` (2026-10-13).

The describer has one input (`work_file`, four natures) and three model selects: the port token does
not say what a step receives, the file's NATURE does — an image goes to the vision model, an audio or
a video to the transcription model. A model is compatible when its canonical `modalities` hold the
modality; an undeclared list affirms nothing and greys nothing. The nature comes from the extension,
read in the server table (`app_registry.media_extensions`) passed by the view.

Also kept here: the common domain reader `input_match.select_match_meta` (extracted at its third
consumer — the transcriber and the reader each carried it, the domain written in the view next to the
one the schema declares) and the describer page that states its two slots.
Executed in V8 on the SERVED brick (a `.js` never breaks at Python compile time).
"""
import json
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

SERVED = Path(settings.BASE_DIR) / 'staticfiles/common/js'

FAKE_DOM = """
var window = this;
function Event(type) { this.type = type; }
function option(value) { return { value: value, textContent: value, dataset: {}, disabled: false, title: '' }; }
var options = [option('auto'), option('describer:blip'), option('ollama:qwen3.8:latest'),
               option('ollama:mute:1b')];
var select = { id: 'vision_model', options: options, value: 'ollama:qwen3.8:latest', isConnected: true,
  get selectedOptions() { var v = this.value; return options.filter(function (o) { return o.value === v; }); },
  querySelectorAll: function () { return []; }, addEventListener: function () {},
  dispatchEvent: function () {} };
var fileInput = { id: 'fileInput', type: 'file', files: [], dataset: {}, addEventListener: function () {} };
var byId = { vision_model: select, fileInput: fileInput };
var document = { getElementById: function (id) { return byId[id] || null; }, addEventListener: function () {} };
var EXT = { image: ['jpg', 'png'], video: ['mp4'], audio: ['wav'], document: ['pdf'] };
var META = { 'describer:blip': {label: 'BLIP', modalities: ['image']},
             'ollama:qwen3.8:latest': {label: 'Qwen', modalities: ['text', 'image']},
             'ollama:mute:1b': {label: 'Mute', modalities: ['text']} };
"""


def _v8(test):
    try:
        from py_mini_racer import MiniRacer
    except ImportError:
        test.skipTest('py_mini_racer absent de ce venv')
    ctx = MiniRacer()
    ctx.eval(FAKE_DOM + (SERVED / 'wama-input-match.js').read_text(encoding='utf-8'))
    ctx.eval("var m = WamaInputMatch.init({ selectId: 'vision_model', meta: META, slots: {"
             " image: WamaInputMatch.modalitySlot('fileInput', { modality: 'image',"
             "   natures: ['image', 'video'], extensions: EXT, label: 'Image ou vidéo' }) } });")
    return ctx


class AModalitySlotJudgesTheFileByWhatTheModelReadsTest(SimpleTestCase):

    def _drop(self, ctx, name, designated=False):
        if designated:
            ctx.eval("fileInput.files = []; window.WamaApp = { designationOf: function () {"
                     f" return {{ path: 'media/x/{name}', name: {json.dumps(name)} }}; }} }};")
        else:
            ctx.eval(f"window.WamaApp = undefined; fileInput.files = [{{ name: {json.dumps(name)} }}];")
        return {o['value']: (o['disabled'], o['title'])
                for o in json.loads(ctx.eval("m.refresh(); JSON.stringify(options)"))}

    def test_an_image_greys_the_model_that_does_not_see(self):
        state = self._drop(_v8(self), 'photo.JPG')
        self.assertTrue(state['ollama:mute:1b'][0])
        self.assertIn('Image ou vidéo', state['ollama:mute:1b'][1])
        for seeing in ('describer:blip', 'ollama:qwen3.8:latest'):
            self.assertFalse(state[seeing][0], seeing)
        self.assertFalse(state['auto'][0], 'auto is the draw, never greyed')

    def test_a_designated_video_is_judged_by_its_name(self):
        state = self._drop(_v8(self), 'clip.mp4', designated=True)
        self.assertTrue(state['ollama:mute:1b'][0])

    def test_a_file_of_another_nature_greys_nothing(self):
        """Counter-test: a document never reaches the vision step — nothing to judge."""
        state = self._drop(_v8(self), 'report.pdf')
        self.assertEqual([False] * 4, [disabled for disabled, _ in state.values()])

    def test_undeclared_modalities_affirm_nothing(self):
        ctx = _v8(self)
        ctx.eval("META['ollama:mute:1b'] = {label: 'Mute'};")
        self.assertFalse(self._drop(ctx, 'photo.png')['ollama:mute:1b'][0])

    def test_no_requirement_is_announced_for_inputs_the_pipeline_composes(self):
        """The meta carries no `inputs_*` (`select_match_meta(inputs=False)`): the status line
        never says « ce modèle requiert : Consigne » under a chat model."""
        ctx = _v8(self)
        self.assertTrue(json.loads(ctx.eval("JSON.stringify(m.refresh().launchable)")))


class SelectMatchMetaReadsTheDeclaredDomainTest(SimpleTestCase):

    SCHEMA = {'schemas': {'PARAMS_JSON': [
        {'name': 'engine', 'options_source': 'catalog', 'options_auto': True,
         'options_query': {'task': 'captioning,text-generation', 'modality': 'image'}},
        {'name': 'silent', 'options_source': 'catalog', 'options_auto': 'silent',
         'options_query': {'model_type': 'llm'}},
        {'name': 'plain', 'options': []}]}}

    def _meta(self, field, **kwargs):
        calls = []

        def fake_meta(**kw):
            calls.append(kw)
            return {'a:x': {'label': 'X', 'inputs_required': ['prompt'], 'inputs_optional': [],
                            'modalities': ['image']}}
        with mock.patch('wama.common.utils.param_schema.declared_param_schemas',
                        lambda app: self.SCHEMA), \
             mock.patch('wama.common.utils.input_match.input_match_meta', fake_meta):
            from wama.common.utils.input_match import select_match_meta
            return select_match_meta('app', field, **kwargs), calls

    def test_the_whole_declared_domain_is_read_and_auto_joins_a_common_draw(self):
        meta, calls = self._meta('engine')
        self.assertEqual({'task': 'captioning,text-generation', 'modality': 'image'},
                         calls[0]['query'])
        self.assertEqual({'inputs_required': ['prompt'], 'inputs_optional': []}, meta['auto'])

    def test_a_silent_auto_gets_no_intersection(self):
        meta, _calls = self._meta('silent')
        self.assertNotIn('auto', meta)

    def test_without_inputs_only_the_label_and_the_extra_capabilities_stay(self):
        meta, _calls = self._meta('engine', extra_caps=('modalities',), inputs=False)
        self.assertEqual({'a:x': {'label': 'X', 'modalities': ['image']}}, meta)

    def test_a_field_without_a_catalogue_domain_has_no_meta(self):
        self.assertEqual({}, self._meta('plain')[0])

    def test_the_select_of_a_domain_is_read_in_the_schema_of_that_domain(self):
        """Park-wide, on the declarations: with a domain, the matching is the one of the select
        THAT domain's schema carries — two domains may name theirs alike on two tasks, and the
        first schema found answered for both."""
        from wama.common.utils import input_match
        from wama.common.utils.app_modes import APP_MODES, domain_schema, get_domains
        from wama.common.utils.auto_model import catalog_field

        asked = []

        def fake_meta(**kw):
            asked.append(kw['query'])
            return {'a:x': {'label': 'X', 'inputs_required': ['port'], 'inputs_optional': []}}

        seen, apart = 0, 0
        with mock.patch.object(input_match, 'input_match_meta', fake_meta):
            for app in sorted(APP_MODES):
                queries = []
                for dom in [d['id'] for d in get_domains(app)]:
                    own = [p for p in domain_schema(app, dom) if p.get('options_source') == 'catalog']
                    with self.subTest(app=app, domain=dom):
                        self.assertEqual(own[0] if own else None, catalog_field(app, dom))
                        del asked[:]
                        match = input_match.card_match(app, [{'id': 'port'}], domain=dom)
                        if not own or not own[0].get('options_query'):
                            self.assertEqual({}, match)
                            continue
                        self.assertEqual([own[0]['options_query']], asked)
                        self.assertEqual(own[0]['name'], match['field'])
                        queries.append(own[0]['options_query'])
                        seen += 1
                apart += len(queries) > 1 and len({repr(q) for q in queries}) > 1
        self.assertGreater(seen, 1)
        self.assertGreater(apart, 0, 'no app has two domains on two catalogue queries')
        self.assertEqual({}, self._meta('absent')[0])

    def test_the_page_meta_gathers_the_select_of_every_domain(self):
        """`domains_match_meta` (2026-11-17): the select of EACH domain, read in its own schema —
        park-wide, every catalogue query a domain declares reaches the page's meta."""
        from wama.common.utils import input_match
        from wama.common.utils.app_modes import APP_MODES, domain_schema, get_domains

        def fake_meta(**kw):
            return {repr(kw['query']): {'label': 'X', 'inputs_required': [], 'inputs_optional': []}}

        seen = 0
        with mock.patch.object(input_match, 'input_match_meta', fake_meta):
            for app in sorted(APP_MODES):
                expected = set()
                for d in get_domains(app):
                    first = next((p for p in domain_schema(app, d['id'])
                                  if p.get('options_source') == 'catalog'), None)
                    if first and first.get('options_query'):
                        expected.add(repr(first['options_query']))
                with self.subTest(app=app):
                    self.assertEqual(expected, set(input_match.domains_match_meta(app)) - {'auto'})
                seen += len(expected) > 1
        self.assertGreater(seen, 0, 'no app has two domains on two catalogue queries')

    def test_the_endpoint_keys_only_reach_the_catalogue(self):
        """Same reading as `api_model_options`: task, model_type, modality (+ source)."""
        from wama.common.utils import input_match
        seen = {}
        with mock.patch('wama.model_manager.services.get_registry_models',
                        lambda source, **kw: (seen.update(source=source, **kw) or ([], []))):
            input_match.input_match_meta(query={'task': 't', 'modality': 'image', 'group': 'task',
                                                'source': 'ollama'})
        self.assertEqual({'source': 'ollama', 'task': 't', 'modality': 'image'}, seen)


class TheDescriberStatesItsTwoSlotsTest(SimpleTestCase):
    """The page DECLARES (INPUT_MODEL_MATCHING §6.7): which select hears, which one sees."""

    def test_the_page_loads_the_brick_and_states_the_modality_slots(self):
        page = (Path(settings.BASE_DIR) / 'wama/describer/templates/describer/index.html'
                ).read_text(encoding='utf-8')
        self.assertIn('with_input_match=True', page)
        self.assertIn("WamaInputMatch.modalitySlot('fileInput'", page)
        self.assertIn("['asr_model', 'audio', ['audio', 'video']", page)
        self.assertIn("['vision_model', 'image', ['image', 'video']", page)

    def test_the_heard_natures_are_those_of_the_pipeline(self):
        """The transcription slot's natures are the ones the pipeline transcribes (`HEARD`)."""
        from wama.describer.function_specs import HEARD
        page = (Path(settings.BASE_DIR) / 'wama/describer/templates/describer/index.html'
                ).read_text(encoding='utf-8')
        self.assertIn(f"['asr_model', 'audio', {json.dumps(list(HEARD)).replace(chr(34), chr(39))}",
                      page)
