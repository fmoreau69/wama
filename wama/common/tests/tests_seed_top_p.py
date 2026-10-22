"""The SEED and the TOP P — the two neighbours of the temperature (2026-10-22).

Fabien: « certains modèles comme dans l'Imager portent déjà seed ou graine. Vérifie bien ce qui
existe déjà pour ne pas faire de doublon. On aligne tout parfaitement. » What is kept here:
  • ONE setting each (`seed_param`, `top_p_param`), bound to a model choice, greyed under a model
    that does not read it, EMPTY = a choice (a fresh draw ; the model's own) — the imager's seed
    joined it and its local exception went;
  • the model CARRIES it — an engine declares `reads_seed` / `default_top_p` (every image and video
    engine reads the seed, declared once on their base), Ollama and an OpenAI-compatible provider
    read both, the Anthropic API neither;
  • the call sends them only when set, and only where they are read.
"""
import importlib.util
import json
import random
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common.utils import llm_utils
from wama.common.utils.model_capabilities import (SEED, TEMPERATURE, TOP_P, apply_engine_flags,
                                                  ollama_parameter)
from wama.common.utils.param_schema import (EMPTY_IS_NONE_TYPES, cap_bindings, coerce_schema_values,
                                            sampling_of, sampling_options, seed_param, top_p_param)

MEASURE = 'wama.common.utils.ollama_host.measured_load'


class TheTwoSettingsTest(SimpleTestCase):

    SCHEMA = [{'name': 'model', 'type': 'select'},
              {'name': 'seed', **seed_param('model')}, {'name': 'top_p', **top_p_param('model')}]

    def test_each_is_advanced_and_bound_to_what_the_model_reads(self):
        for p, name in ((seed_param('m'), SEED), (top_p_param('m'), TOP_P)):
            with self.subTest(setting=name):
                self.assertEqual((name, True, None), (p['type'], p['advanced'], p['default']))
                binding = cap_bindings(p)[0]
                self.assertEqual(('m', 'params', 'reads', name),
                                 (binding['field'], binding['capability'], binding['mode'],
                                  binding['param']))

    def test_empty_is_a_choice_and_a_value_is_bounded(self):
        self.assertEqual({'seed': None, 'top_p': None},
                         coerce_schema_values(self.SCHEMA, {'seed': '', 'top_p': ''}))
        self.assertEqual({'seed': 42, 'top_p': 1.0},
                         coerce_schema_values(self.SCHEMA, {'seed': '42', 'top_p': '1.5'}))
        self.assertIsInstance(coerce_schema_values(self.SCHEMA, {'seed': '41.6'})['seed'], int)
        # Counter-check: a number left empty is « not given », never a choice.
        self.assertEqual({}, coerce_schema_values([{'name': 'n', 'type': 'number'}], {'n': ''}))

    def test_the_rule_is_shared_by_the_panel_and_the_imager_lost_its_own(self):
        from wama.common.utils import user_settings
        from wama.imager import views as imager_views
        self.assertTrue(set(EMPTY_IS_NONE_TYPES) <= set(user_settings._EMPTY_IS_VALUE))
        self.assertFalse(hasattr(imager_views, 'SETTINGS_EMPTY_IS_VALUE'))

    def test_an_item_reads_as_three_settings_and_an_engine_gets_the_set_ones(self):
        item = mock.Mock(llm_temperature=0.3, llm_seed=None, llm_top_p=0.9)
        self.assertEqual({'temperature': 0.3, 'seed': None, 'top_p': 0.9}, sampling_of(item, 'llm_'))
        self.assertEqual({'temperature': 0.3, 'top_p': 0.9}, sampling_options(item, 'llm_'))
        self.assertEqual({'seed': 5}, sampling_options({'seed': 5, 'temperature': ''}))


class TheModelCarriesThemTest(SimpleTestCase):

    def test_the_engines_declare_what_they_read(self):
        from wama.common.backends.audio8_backend import Audio8Backend
        from wama.common.backends.bark_backend import BarkBackend
        from wama.common.backends.coqui_backend import CoquiBackend
        from wama.common.backends.diffusers_backend import DiffusersBackend
        from wama.common.backends.higgs_backend import HiggsAudioBackend
        from wama.common.backends.kokoro_backend import KokoroBackend
        from wama.common.backends.qwen3_tts_backend import Qwen3TTSBackend
        # Values measured in the libraries (2026-10-22): Audio8's hard-coded 0.95, Higgs'
        # `serve_engine` default, XTTS' `config.json`, Qwen3-TTS' `generation_config.json`.
        for cls, top_p in ((Audio8Backend, 0.95), (HiggsAudioBackend, 0.95), (CoquiBackend, 0.85),
                           (Qwen3TTSBackend, 1.0)):
            with self.subTest(engine=cls.__name__):
                caps = apply_engine_flags({}, cls)
                self.assertTrue({SEED, TOP_P} <= set(caps['params']))
                self.assertEqual(top_p, caps['recommended_top_p'])
        bark = apply_engine_flags({}, BarkBackend)
        self.assertEqual((True, False), (SEED in bark['params'], TOP_P in bark['params']))
        kokoro = apply_engine_flags({'params': [SEED, TOP_P], 'recommended_top_p': 0.9}, KokoroBackend)
        self.assertEqual(([], None), (kokoro['params'], kokoro['recommended_top_p']),
                         'nothing to draw: a value left by an earlier sync does not survive')
        self.assertIn(SEED, apply_engine_flags({}, DiffusersBackend)['params'],
                      'declared once on the image and video base')

    def test_an_engine_that_says_nothing_affirms_nothing(self):
        from wama.common.backends.tts_base import TTSBackend

        class Silent(TTSBackend):
            def load(self, model=None):
                return True

            def unload(self):
                pass

            def process(self, **kwargs):
                return ''
        self.assertEqual({'params': ['voice']}, apply_engine_flags({'params': ['voice']}, Silent))

    def test_ollama_and_an_openai_compatible_provider_read_both_the_anthropic_api_neither(self):
        from wama.model_manager.services.cloud_models import declared_listing, model_info_for
        from wama.model_manager.services.model_registry import ModelRegistry
        chat = ModelRegistry._capacites_canoniques({'completion'}, 'gemma4:12b')
        self.assertEqual([TEMPERATURE, SEED, TOP_P], chat['params'])
        ocr = ModelRegistry._capacites_canoniques({'completion', 'vision'}, 'glm-ocr:latest')
        self.assertEqual(['language'], ocr['params'], 'a family that declares keeps its own')
        albert = model_info_for('albert', {'id': 'gpt-oss-120b', 'type': 'text-generation'})
        self.assertEqual([TEMPERATURE, SEED, TOP_P], albert.capabilities['params'])
        anthropic = model_info_for('anthropic', {'id': 'claude-x', 'type': 'image-text-to-text'})
        self.assertEqual([TEMPERATURE], anthropic.capabilities['params'])
        cli = model_info_for('claude_code', declared_listing('claude_code')[0])
        self.assertEqual([], cli.capabilities['params'])

    def test_the_ollama_model_file_gives_the_publishers_top_p(self):
        self.assertEqual(0.95, ollama_parameter('temperature 1\ntop_p 0.95\ntop_k 64', TOP_P))
        self.assertIsNone(ollama_parameter('temperature 1', TOP_P))


class TheEngineUsesThemTest(SimpleTestCase):

    def test_a_seed_is_set_on_the_generators_and_none_draws_afresh(self):
        from wama.common.backends.higgs_backend import HiggsAudioBackend
        engine = HiggsAudioBackend()
        self.assertEqual(11, engine.sampling_seed({'options': {'seed': '11'}}))
        first = random.random()
        engine.sampling_seed({'options': {'seed': 11}})
        self.assertEqual(first, random.random(), 'the same seed, the same draw')
        self.assertIsNone(engine.sampling_seed({'options': {}}))

    def test_a_call_takes_the_cards_top_p_or_the_engines(self):
        from wama.common.backends.higgs_backend import HiggsAudioBackend
        engine = HiggsAudioBackend()
        self.assertEqual(0.95, engine.sampling_top_p({}))
        self.assertEqual(0.5, engine.sampling_top_p({'options': {'top_p': '0.5'}}))

    def test_qwen3_tts_draws_both_stages_with_the_cards_top_p(self):
        import numpy as np

        from wama.common.backends.qwen3_tts_backend import Qwen3TTSBackend
        engine = Qwen3TTSBackend()
        engine._model = mock.Mock()
        engine._model.generate_custom_voice.return_value = ([np.zeros(240, dtype=np.float32)], 24000)
        for asked, expected in ((None, 1.0), (0.7, 0.7)):
            with self.subTest(asked=asked):
                Path(engine.process(text='Bonjour', options={'top_p': asked})).unlink()
                sent = engine._model.generate_custom_voice.call_args.kwargs
                self.assertEqual((expected, expected), (sent['top_p'], sent['subtalker_top_p']))

    def test_audio8_no_longer_writes_its_top_p(self):
        import torch

        from wama.common.backends.audio8_backend import Audio8Backend
        engine = Audio8Backend()
        engine._device = 'cpu'
        engine._processor = mock.Mock(return_value={'input_ids': torch.zeros(1, 2)})
        engine._model = mock.Mock()
        engine._model.generate.return_value = mock.Mock(codes=None)
        engine._model.decode_audio.return_value = (torch.zeros(1, 240), [240])
        engine._model.config.codec_sample_rate = 24000
        Path(engine.process(text='Bonjour', options={'top_p': 0.6})).unlink()
        self.assertEqual(0.6, engine._model.generate.call_args.kwargs['top_p'])

    def test_yue_takes_the_cards_seed_or_its_fixed_one(self):
        from wama.common.backends.yue2_3b_backend import YuE2Backend
        engine = YuE2Backend()
        self.assertEqual(77, engine._seed({'seed': 77}))
        self.assertEqual(YuE2Backend.SEED, engine._seed(None))


class TheCallSendsThemOnlyWhenSetTest(SimpleTestCase):

    def _ollama_options(self, **kwargs):
        reply = mock.Mock(status_code=200, json=lambda: {'message': {'content': 'ok'}})
        client = mock.MagicMock()
        client.__enter__.return_value.post.return_value = reply
        with mock.patch('httpx.Client', return_value=client), \
                mock.patch(MEASURE, side_effect=lambda name, call, keep_alive=None: call()):
            llm_utils.ollama_chat([{'role': 'user', 'content': 'x'}], model='gemma4:12b', **kwargs)
        return client.__enter__.return_value.post.call_args.kwargs['json']['options']

    def test_ollama_receives_them_when_set(self):
        sent = self._ollama_options(seed='7', top_p=0.8)
        self.assertEqual((7, 0.8), (sent['seed'], sent['top_p']))
        sent = self._ollama_options()
        self.assertNotIn('seed', sent)
        self.assertNotIn('top_p', sent)

    def _cloud_kwargs(self, provider, compatible):
        reply = mock.Mock()
        reply.choices = [mock.Mock(message=mock.Mock(content='ok', tool_calls=None))]
        source = mock.Mock(no_reuse_request_body='', rate_limit_wait_s=None, api_key_env='K')
        with mock.patch.object(llm_utils, 'declared_llm_source', return_value=source), \
                mock.patch.object(llm_utils, 'openai_compatible_source',
                                  return_value=provider if compatible else ''), \
                mock.patch('wama.common.external_sources.api_key', return_value='key'), \
                mock.patch('wama.common.external_sources.base_url', return_value='http://x'), \
                mock.patch.object(llm_utils, '_record_served'), \
                mock.patch.object(llm_utils, '_completion', return_value=reply) as completion, \
                mock.patch.dict('sys.modules', {'litellm': mock.Mock()}):
            self.assertEqual(('ok', None), llm_utils.llm_chat(
                [{'role': 'user', 'content': 'x'}], model='m', provider=provider,
                temperature=0.2, seed=3, top_p=0.9))
        return completion.call_args.kwargs

    def test_an_openai_compatible_provider_receives_them_the_anthropic_api_does_not(self):
        sent = self._cloud_kwargs('albert', compatible=True)
        self.assertEqual((3, 0.9), (sent['seed'], sent['top_p']))
        native = self._cloud_kwargs('anthropic', compatible=False)
        self.assertNotIn('seed', native)
        self.assertNotIn('top_p', native)
        self.assertEqual(0.2, native['temperature'], 'the temperature still goes')

    def test_a_summary_relays_them(self):
        reply = '{"summary": "s", "key_points": [], "action_items": []}'
        with mock.patch.object(llm_utils, 'llm_chat', return_value=(reply, None)) as chat:
            llm_utils.generate_structured_summary('texte', model='m', provider='ollama',
                                                  temperature=None, seed=4, top_p=0.5)
        self.assertEqual((4, 0.5), (chat.call_args.kwargs['seed'], chat.call_args.kwargs['top_p']))

    def test_the_assistant_sends_the_users_seed_and_top_p(self):
        from wama.common.services import assistant_engine
        usage = {'input_tokens': 0, 'output_tokens': 0}
        with mock.patch.object(assistant_engine, '_ollama_stream',
                               return_value=('ok', usage)) as stream, \
                mock.patch(MEASURE, side_effect=lambda name, call, keep_alive=None: call()):
            assistant_engine._llm_call([], 'gemma4:e4b', 'ollama', seed=9, top_p=0.4)
            options = stream.call_args.args[1]['options']
            self.assertEqual((9, 0.4), (options['seed'], options['top_p']))
            assistant_engine._llm_call([], 'gemma4:e4b', 'ollama')
            self.assertNotIn('seed', stream.call_args.args[1]['options'])


class TheAppsCarryThemTest(SimpleTestCase):
    """Each app that sets a temperature sets its neighbours beside it, bound to the same model —
    the composer its seed alone (none of its engines reads a top_p)."""

    def _bound(self, schema, kind):
        return {p['name']: cap_bindings(p)[0]['field'] for p in schema if p.get('type') == kind}

    def test_every_app_binds_them_to_the_model_of_its_temperature(self):
        from wama.assistant.params import PARAMS_JSON as ASSISTANT
        from wama.avatarizer.params import PARAMS_JSON as AVATARIZER
        from wama.composer.params import PARAMS_JSON as COMPOSER
        from wama.describer.params import PARAMS_JSON as DESCRIBER
        from wama.reader.params import PARAMS_JSON as READER
        from wama.synthesizer.params import PARAMS_JSON as SYNTHESIZER
        expected = {
            'describer': (DESCRIBER, {'vision_seed': 'vision_model', 'llm_seed': 'llm_model'},
                          {'vision_top_p': 'vision_model', 'llm_top_p': 'llm_model'}),
            'reader': (READER, {'llm_seed': 'llm_model'}, {'llm_top_p': 'llm_model'}),
            'assistant': (ASSISTANT, {'seed': 'model'}, {'top_p': 'model'}),
            'synthesizer': (SYNTHESIZER, {'seed': 'tts_model'}, {'top_p': 'tts_model'}),
            'avatarizer': (AVATARIZER, {'tts_seed': 'tts_model'}, {'tts_top_p': 'tts_model'}),
            'composer': (COMPOSER, {'seed': 'model'}, {}),
        }
        for app, (schema, seeds, top_ps) in expected.items():
            with self.subTest(app=app):
                self.assertEqual(seeds, self._bound(schema, 'seed'))
                self.assertEqual(top_ps, self._bound(schema, 'top_p'))

    def test_the_imager_seed_is_the_common_one_in_both_domains(self):
        from wama.imager.params import IMAGE_PARAMS_JSON, VIDEO_PARAMS_JSON
        for schema in (IMAGE_PARAMS_JSON, VIDEO_PARAMS_JSON):
            p = next(p for p in schema if p['name'] == 'seed')
            self.assertEqual(('seed', 'model', 'qualite'),
                             (p['type'], cap_bindings(p)[0]['field'], p['group']))
        self.assertEqual({'seed': None}, coerce_schema_values(IMAGE_PARAMS_JSON, {'seed': ''}),
                         'empty: a fresh draw, without the view saying it')

    def test_the_routes_write_them(self):
        from wama.describer.views import SETTINGS_FIELDS as DESCRIBER
        from wama.reader.views import SETTINGS_FIELDS as READER
        self.assertTrue({'vision_seed', 'vision_top_p', 'llm_seed', 'llm_top_p'} <= set(DESCRIBER))
        self.assertTrue({'llm_seed', 'llm_top_p'} <= set(READER))

    def test_a_describer_image_is_seen_with_the_cards_seed(self):
        from wama.describer.backends import image_backend
        with mock.patch('wama.model_manager.services.vision_probe.describe_image_ollama',
                        return_value={'ok': True, 'description': 'une route'}) as seen:
            image_backend._describe_with_ollama_vision('gemma4:12b', 'x.png', 'p',
                                                       {'seed': 5, 'top_p': 0.7})
        self.assertEqual((5, 0.7), (seen.call_args.kwargs['seed'], seen.call_args.kwargs['top_p']))

    def test_the_generator_gives_them_a_nullable_column(self):
        from wama.common.manifests.codegen.models_gen import _champ_option
        self.assertEqual('seed = models.IntegerField(null=True, blank=True)',
                         _champ_option({'name': 'seed', 'type': 'seed'}))
        for kind in ('temperature', 'top_p'):
            self.assertEqual(f'{kind} = models.FloatField(null=True, blank=True)',
                             _champ_option({'name': kind, 'type': kind}))


class AnElementBornWithAnEmptySeedTest(TestCase):
    """At birth, a posted EMPTY seed beats a kept preference — the imager declared it by hand."""

    def test_an_empty_seed_is_a_fresh_draw_even_over_a_kept_one(self):
        from wama.common.utils.user_settings import new_element_settings, save_panel_settings
        from wama.imager.models import ImageGeneration
        from wama.imager.params import IMAGE_PARAMS_JSON
        user = get_user_model().objects.create_user('seed-birth', password='x')
        save_panel_settings(user, 'imager', IMAGE_PARAMS_JSON, {'seed': '7'})
        self.assertIsNone(new_element_settings(user, 'imager', IMAGE_PARAMS_JSON, ImageGeneration,
                                               post={'seed': ''}).get('seed'))
        # Counter-check: nothing posted, the kept seed plays.
        self.assertEqual(7, new_element_settings(user, 'imager', IMAGE_PARAMS_JSON,
                                                 ImageGeneration, post={}).get('seed'))


HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
JS = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
DOM = """
var window = {};
var CSS = {escape: function (s) { return s; }};
var document = {readyState: 'complete', querySelectorAll: function () { return []; },
                querySelector: function () { return null; }, getElementById: function () { return null; },
                addEventListener: function () {}};
function Event(type) { this.type = type; }
"""


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class TheWidgetsJsTest(SimpleTestCase):

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(DOM)
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def _run(self, body):
        return self.v8.eval('(function () {' + body + '})()')

    def _render(self, schema):
        return self._run(
            "var host = {innerHTML: '', querySelectorAll: function () { return []; },"
            "            querySelector: function () { return null; }, addEventListener: function () {}};"
            f"window.WamaParams.render(host, {json.dumps(schema)}, {{context: 'item'}});"
            "return host.innerHTML;")

    def test_the_seed_field_says_random_and_offers_a_draw_to_keep(self):
        out = self._render([{'name': 'seed', 'type': 'seed', 'label': 'Graine', 'help': 'h'}])
        self.assertIn('id="wp-item-seed" name="seed" value="" placeholder="Aléatoire"', out)
        self.assertIn('wama-seed-draw', out)
        self.assertNotIn('<small class="text-muted d-block">h', out, 'the help is a tooltip')

    def test_the_top_p_field_says_the_publishers_value_when_known(self):
        out = self._render([{'name': 'top_p', 'type': 'top_p', 'label': 'Top P'}])
        self.assertIn('name="top_p" value="" placeholder="Celui du modèle"', out)
        self.assertEqual('Celui du modèle : 0,95',
                         self._run("return window.WamaParams.topPPlaceholder({recommended_top_p: 0.95});"))
        self.assertEqual('Celui du modèle', self._run("return window.WamaParams.topPPlaceholder(null);"))

    def test_the_temperature_line_mentions_a_seed_where_the_model_reads_one(self):
        hint = lambda caps: self._run(  # noqa: E731
            f"return window.WamaParams.temperatureHint({json.dumps(caps)}, '0.7', false, false);")
        self.assertIn('graine', hint({'params': ['temperature', 'seed']}))
        self.assertNotIn('graine', hint({'params': ['temperature']}), 'not under a model without one')
