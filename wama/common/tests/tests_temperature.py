"""The sampling TEMPERATURE — one setting for every model that samples (2026-10-21).

Fabien's request: « le modèle doit porter l'information et le réglage doit apparaître si le modèle
le permet », for every model whatever its type, and without entering the fast/quality slider.
What is kept here, from the source to the call:
  • the model CARRIES it — the catalogue says it reads it (`params`), the publisher's value
    (`recommended_temperature`) and the engine's maximum (`max_temperature`);
  • ONE rule at the call — no value = the model's own, nothing is sent (it was 0.3 imposed by
    `ollama_chat`, against gemma4 and qwen3.5 whose publishers say 1; 0.7 in the assistant);
    a task with no setting gives `STEADY_TEMPERATURE` itself, by name;
  • ONE setting (`temperature_param`) bound to a model choice, greyed under a model that does not
    sample, empty = the model's own — and the apps that choose such a model carry it to the call.
"""
import ast
import importlib.util
import json
import re
import tempfile
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from wama.common.utils import llm_utils
from wama.common.utils.model_capabilities import (CANONICAL_CAPABILITIES, TEMPERATURE,
                                                  ollama_recommended_temperature,
                                                  reads_temperature,
                                                  sampling_caps_from_declaration)
from wama.common.utils.param_schema import (cap_bindings, coerce_params, coerce_schema_values,
                                            temperature_param)

MEASURE = 'wama.common.utils.ollama_host.measured_load'


def _bare_measure():
    return mock.patch(MEASURE, side_effect=lambda name, call, keep_alive=None: call())


class TheModelCarriesItsTemperatureTest(SimpleTestCase):

    def test_the_three_facts_are_canonical_capabilities(self):
        for key in ('recommended_temperature', 'max_temperature'):
            self.assertIn(key, CANONICAL_CAPABILITIES)

    def test_the_ollama_model_file_gives_the_publishers_value(self):
        """Measured on the served Ollama (2026-10-21): gemma4 and qwen3.5 publish 1, glm-ocr 0."""
        self.assertEqual(1.0, ollama_recommended_temperature(
            'presence_penalty               1.5\ntemperature                    1\ntop_k 20'))
        self.assertEqual(0.0, ollama_recommended_temperature('temperature                    0'))
        # Counter-checks: a model file without it (translategemma), or none at all.
        self.assertIsNone(ollama_recommended_temperature('stop "<end_of_turn>"\ntop_k 64'))
        self.assertIsNone(ollama_recommended_temperature(''))

    def test_an_ollama_chat_model_reads_it_and_an_ocr_family_does_not(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        chat = ModelRegistry._capacites_canoniques({'completion', 'vision'}, 'gemma4:12b')
        self.assertTrue(reads_temperature(chat))
        ocr = ModelRegistry._capacites_canoniques({'completion', 'vision'}, 'glm-ocr:latest')
        self.assertEqual(['language'], ocr['params'], 'its engine fixes it at 0')
        embedding = ModelRegistry._capacites_canoniques({'embedding'}, 'bge-m3:latest')
        self.assertFalse(reads_temperature(embedding))

    def test_a_remote_chat_model_reads_it_bounded_by_its_provider(self):
        from wama.model_manager.services.cloud_models import declared_listing, model_info_for
        albert = model_info_for('albert', {'id': 'gpt-oss-120b', 'type': 'text-generation'})
        self.assertTrue(reads_temperature(albert.capabilities))
        self.assertNotIn('max_temperature', albert.capabilities)
        anthropic = model_info_for('anthropic', {'id': 'claude-x', 'type': 'image-text-to-text'})
        self.assertEqual(1.0, anthropic.capabilities['max_temperature'])
        # The subscription's CLI takes none: said, so the setting greys under it.
        cli = model_info_for('claude_code', declared_listing('claude_code')[0])
        self.assertEqual([], cli.capabilities['params'])

    def test_blip_says_it_does_not_sample(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry()
        registry._models = {}
        registry._discover_describer_models()
        self.assertEqual([], registry._models['describer:blip'].capabilities['params'])

    def test_an_app_declaration_says_it_for_a_model_of_any_type(self):
        """A voice or a music model declares `default_temperature` in its app's model config."""
        caps = sampling_caps_from_declaration({'default_temperature': 0.7, 'params': ['voice']})
        self.assertEqual((0.7, ['voice', TEMPERATURE]),
                         (caps['recommended_temperature'], caps['params']))
        self.assertEqual({}, sampling_caps_from_declaration({}), 'nothing declared, nothing said')


class NoValueIsTheModelsOwnTest(SimpleTestCase):

    def _ollama_options(self, **kwargs):
        reply = mock.Mock(status_code=200, json=lambda: {'message': {'content': 'ok'}})
        client = mock.MagicMock()
        client.__enter__.return_value.post.return_value = reply
        with mock.patch('httpx.Client', return_value=client), _bare_measure():
            self.assertEqual(('ok', None), llm_utils.ollama_chat(
                [{'role': 'user', 'content': 'x'}], model='gemma4:12b', **kwargs))
        return client.__enter__.return_value.post.call_args.kwargs['json']['options']

    def test_a_local_chat_without_a_value_sends_none(self):
        self.assertNotIn('temperature', self._ollama_options())
        # Counter-checks: a value is sent as is, zero included.
        self.assertEqual(0.6, self._ollama_options(temperature=0.6)['temperature'])
        self.assertEqual(0.0, self._ollama_options(temperature=0.0)['temperature'])

    def test_a_task_without_a_setting_keeps_its_steady_temperature(self):
        """The transcriber's summaries have no setting: they keep their 0.3, by name."""
        reply = '{"summary": "s", "key_points": [], "action_items": []}'
        with mock.patch.object(llm_utils, 'llm_chat', return_value=(reply, None)) as chat:
            llm_utils.generate_structured_summary('texte', model='m', provider='ollama')
            self.assertEqual(llm_utils.STEADY_TEMPERATURE, chat.call_args.kwargs['temperature'])
            # Counter-check: a card that leaves it to the model passes None, never the 0.3.
            llm_utils.generate_structured_summary('texte', model='m', provider='ollama',
                                                  temperature=None)
            self.assertIsNone(chat.call_args.kwargs['temperature'])

    def test_the_vision_probe_is_a_chat_with_an_image(self):
        from wama.model_manager.services import vision_probe
        with tempfile.NamedTemporaryFile(suffix='.png') as image, \
                mock.patch.object(llm_utils, 'ollama_chat',
                                  side_effect=[('un chat', None), (None, 'boom')]) as chat:
            image.write(b'png')
            image.flush()
            self.assertEqual({'ok': True, 'description': 'un chat'},
                             vision_probe.describe_image_ollama(image.name, model='gemma4:12b',
                                                                temperature=0.4))
            self.assertEqual({'ok': False, 'error': 'boom'},
                             vision_probe.describe_image_ollama(image.name, model='gemma4:12b'))
        first = chat.call_args_list[0]
        self.assertEqual(['cG5n'], first.args[0][0]['images'])
        self.assertEqual(0.4, first.kwargs['temperature'])
        self.assertIsNone(chat.call_args_list[1].kwargs['temperature'], "the model's own")

    def test_the_prompt_translation_keeps_its_steady_value_and_a_card_passes_its_own(self):
        from wama.common.utils.translator import TranslatorService
        with mock.patch.object(llm_utils, 'llm_chat', return_value=('hello', None)) as chat:
            TranslatorService(use_cache=False).translate('bonjour', 'fr', 'en')
            self.assertEqual(llm_utils.STEADY_TEMPERATURE, chat.call_args.kwargs['temperature'])
            TranslatorService(use_cache=False, temperature=None).translate('bonjour', 'fr', 'en')
            self.assertIsNone(chat.call_args.kwargs['temperature'])

    def test_a_set_temperature_does_not_reuse_another_ones_cached_translation(self):
        from wama.common.utils.translator import TranslatorService
        keys = []
        with mock.patch.object(TranslatorService, '_cache_get',
                               side_effect=lambda key: keys.append(key)), \
                mock.patch.object(TranslatorService, '_cache_set'), \
                mock.patch.object(llm_utils, 'llm_chat', return_value=('hello', None)):
            for service in (TranslatorService(), TranslatorService(),
                            TranslatorService(temperature=0.9)):
                service.translate('bonjour', 'fr', 'en')
        self.assertEqual(keys[0], keys[1], 'without a setting, the key of before')
        self.assertNotEqual(keys[0], keys[2])


#: The base calls of a model — every call names its temperature (or relays `**kwargs`).
BASE_CALLS = {'llm_chat', 'ollama_chat', 'chat_with_source', 'chat_with_catalog_model'}
SANDBOX_TWIN = re.compile(r'_\d\d$')


class EveryCallNamesItsTemperatureTest(SimpleTestCase):
    """The defect this closes does not show at run time: a call that names no temperature takes
    a DEFAULT, and the default moved (0.3 → the model's own). A summary that suddenly samples at 1
    renders a plausible text, never an error — so every call says what it wants."""

    def _silent_calls(self):
        out = []
        base = Path(settings.BASE_DIR)
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in sorted((base / root).rglob('*.py')):
                parts = path.relative_to(base).parts
                if (any(SANDBOX_TWIN.search(p) for p in parts) or 'vendor' in parts
                        or 'migrations' in parts or path.name.startswith('tests')
                        or 'tests' in parts):
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding='utf-8'))
                except (SyntaxError, UnicodeDecodeError):
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
                    if name not in BASE_CALLS:
                        continue
                    if not any(k.arg in ('temperature', None) for k in node.keywords):
                        out.append(f'{path.relative_to(base)}:{node.lineno} {name}')
        return out

    def test_no_call_relies_on_an_implicit_temperature(self):
        self.assertEqual([], self._silent_calls())

    def test_the_guard_sees_the_calls(self):
        """Counter-check: the walk finds the calls it judges (an empty walk would pass)."""
        found = 0
        tree = ast.parse(Path(llm_utils.__file__).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', None) in BASE_CALLS:
                found += 1
        self.assertGreaterEqual(found, 10)


class TheCommonSettingTest(SimpleTestCase):

    SCHEMA = [{'name': 'model', 'type': 'select'},
              {'name': 'temperature', **temperature_param('model')}]

    def test_it_is_bound_to_the_four_facts_of_its_model(self):
        p = temperature_param('vision_model')
        self.assertEqual(('temperature', None), (p['type'], p['default']))
        self.assertEqual(['params', 'recommended_temperature', 'max_temperature', 'min_temperature'],
                         [b['capability'] for b in cap_bindings(p)])
        self.assertIn('même résultat', p['help'], 'the help says what the value implies')
        self.assertEqual({'vision_model'}, {b['field'] for b in cap_bindings(p)})
        self.assertEqual(TEMPERATURE, cap_bindings(p)[0]['param'],
                         'the app names its field as it wants, the model lists `temperature`')

    def test_a_single_binding_is_a_list_of_one(self):
        self.assertEqual([{'field': 'm', 'capability': 'fps'}],
                         cap_bindings({'cap_from': {'field': 'm', 'capability': 'fps'}}))
        self.assertEqual([], cap_bindings({'name': 'x'}))

    def test_empty_is_the_models_own_and_a_value_is_bounded(self):
        for raw, expected in (('', None), (None, None), ('n/a', None), ('0.7', 0.7),
                              ('9', 2.0), ('-1', 0.0)):
            with self.subTest(raw=raw):
                self.assertEqual(expected, coerce_params(self.SCHEMA, {'temperature': raw})
                                 ['temperature'])

    def test_a_posted_empty_value_gives_it_back_to_the_model(self):
        """`''` is a CHOICE here (« Celle du modèle »), where a number left empty is « not given »."""
        self.assertEqual({'temperature': None},
                         coerce_schema_values(self.SCHEMA, {'temperature': ''}))
        self.assertEqual({}, coerce_schema_values(self.SCHEMA, {}), 'absent stays absent')


class ThePanelForgetsAPreferenceGivenBackTest(TestCase):

    def test_choosing_the_models_own_clears_the_kept_value(self):
        from django.contrib.auth import get_user_model

        from wama.common.utils.user_settings import get_user_app_setting, save_panel_settings
        user = get_user_model().objects.create_user('temperature-panel', password='x')
        schema = [{'name': 'temperature', 'contexts': ('panel',),
                   **temperature_param('model', dom_id={'panel': 'temperature'})}]
        save_panel_settings(user, 'describer', schema, {'temperature': '0.6'})
        self.assertEqual(0.6, get_user_app_setting(user, 'describer', 'temperature'))
        save_panel_settings(user, 'describer', schema, {'temperature': ''})
        self.assertIsNone(get_user_app_setting(user, 'describer', 'temperature'))


class TheAppsCarryItToTheCallTest(SimpleTestCase):

    def test_the_describer_has_one_per_model_that_samples(self):
        from wama.describer.params import PARAMS_JSON
        from wama.describer.views import SETTINGS_FIELDS
        bound = {p['name']: cap_bindings(p)[0]['field'] for p in PARAMS_JSON
                 if p.get('type') == 'temperature'}
        self.assertEqual({'vision_temperature': 'vision_model', 'llm_temperature': 'llm_model'},
                         bound)
        self.assertLessEqual(set(bound), set(SETTINGS_FIELDS), 'the routes write them')

    def test_the_reader_and_the_assistant_have_theirs(self):
        from wama.assistant.params import PARAMS_JSON as ASSISTANT, USER_SETTINGS_DEFAULTS
        from wama.reader.params import PARAMS_JSON as READER
        from wama.reader.views import SETTINGS_FIELDS
        for schema, name, field in ((READER, 'llm_temperature', 'llm_model'),
                                    (ASSISTANT, 'temperature', 'model')):
            with self.subTest(setting=name):
                p = next(p for p in schema if p['name'] == name)
                self.assertEqual(('temperature', field), (p['type'], cap_bindings(p)[0]['field']))
        self.assertIn('llm_temperature', SETTINGS_FIELDS)
        self.assertIsNone(USER_SETTINGS_DEFAULTS['temperature'])

    def test_a_describer_image_is_seen_at_the_cards_temperature(self):
        from PIL import Image

        from wama.describer.backends import image_backend
        with tempfile.NamedTemporaryFile(suffix='.png') as f, \
                mock.patch.object(image_backend, '_best_ollama_vision_model',
                                  return_value='gemma4:12b'), \
                mock.patch.object(image_backend, '_gpu_safe_mode', return_value=False), \
                mock.patch('wama.model_manager.services.vision_probe.describe_image_ollama',
                           return_value={'ok': True, 'description': 'une voiture'}) as seen:
            Image.new('RGB', (4, 4)).save(f.name)
            image_backend.describe_image(f.name, {'vision_model': 'auto', 'output_language': 'en',
                                                  'vision_temperature': 0.6})
        self.assertEqual(0.6, seen.call_args.kwargs['temperature'])

    def test_the_key_frames_are_seen_at_the_cards_temperature(self):
        from wama.describer.backends import image_backend, video_backend
        with mock.patch.object(image_backend, '_describe_with_ollama_vision',
                               return_value='a road') as seen:
            video_backend.describe_frames_with('gemma4:12b', ['f1.jpg'], temperature=0.2)
        self.assertEqual(0.2, seen.call_args.args[3])

    def test_a_describer_document_is_written_at_the_cards_temperature(self):
        from wama.describer.backends import text_backend
        summary = {'summary': 's', 'key_points': [], 'action_items': []}
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write('un deux trois quatre')
        with mock.patch.object(llm_utils, 'generate_structured_summary',
                               return_value=summary) as written:
            text_backend.describe_text(f.name, {'max_length': 1, 'output_language': 'en',
                                                'llm_model': 'ollama:qwen3.8:latest',
                                                'llm_temperature': 0.9})
        Path(f.name).unlink()
        self.assertEqual(0.9, written.call_args.kwargs['temperature'])

    def test_the_describer_coherence_reads_the_column_and_none_is_the_models(self):
        from wama.describer import workers
        from wama.describer.models import Description
        report = {'score': 90, 'notes': [], 'suggestion': 'x'}
        for column, expected in ((0.8, 0.8), (None, None)):
            with self.subTest(column=column), \
                    mock.patch.object(llm_utils, 'verify_text_coherence',
                                      return_value=report) as checked:
                item = Description(result_text='x', detected_type='document',
                                   llm_model='ollama:qwen3.8:latest', llm_temperature=column)
                workers._coherence_step(item, mock.Mock())
                self.assertEqual(expected, checked.call_args.kwargs['temperature'])

    def test_the_reader_formats_at_the_cards_temperature(self):
        from wama.reader import tasks
        with mock.patch.object(llm_utils, 'llm_chat', return_value=('# ok', None)) as chat:
            tasks._format_as_markdown('texte', model='m', provider='ollama', temperature=0.1)
        self.assertEqual(0.1, chat.call_args.kwargs['temperature'])

    def test_the_assistant_sends_the_users_temperature_or_none(self):
        from wama.common.services import assistant_engine
        usage = {'input_tokens': 0, 'output_tokens': 0}
        with mock.patch.object(assistant_engine, '_ollama_stream',
                               return_value=('ok', usage)) as stream, _bare_measure():
            assistant_engine._llm_call([], 'gemma4:e4b', 'ollama')
            self.assertNotIn('temperature', stream.call_args.args[1]['options'], 'was 0.7 imposed')
            assistant_engine._llm_call([], 'gemma4:e4b', 'ollama', temperature=0.5)
            self.assertEqual(0.5, stream.call_args.args[1]['options']['temperature'])


class TheEngineSaysItsTemperatureTest(SimpleTestCase):
    """A voice engine says whether it samples — the same rule as cloning (`apply_engine_flags`),
    for the discovery and for the sync of a prospected row."""

    def test_an_engine_that_samples_reads_it_with_its_own_value(self):
        from wama.common.backends.higgs_backend import HiggsAudioBackend
        from wama.common.utils.model_capabilities import apply_engine_flags
        caps = apply_engine_flags({'task': 'text-to-speech', 'params': ['voice']}, HiggsAudioBackend)
        self.assertEqual((['voice', TEMPERATURE], 0.7),
                         (caps['params'], caps['recommended_temperature']))

    def test_an_engine_that_does_not_sample_says_so(self):
        from wama.common.backends.kokoro_backend import KokoroBackend
        from wama.common.utils.model_capabilities import apply_engine_flags
        caps = apply_engine_flags({'task': 'text-to-speech', 'params': [TEMPERATURE],
                                   'recommended_temperature': 1.0}, KokoroBackend)
        self.assertEqual(([], None), (caps['params'], caps['recommended_temperature']),
                         'a value left by an earlier sync does not survive')

    def test_an_engine_that_says_nothing_affirms_nothing(self):
        from wama.common.backends.tts_base import TTSBackend
        from wama.common.utils.model_capabilities import apply_engine_flags

        class Silent(TTSBackend):
            def load(self, model=None):
                return True

            def unload(self):
                pass

            def process(self, **kwargs):
                return ''
        self.assertEqual({'task': 'text-to-speech'},
                         apply_engine_flags({'task': 'text-to-speech'}, Silent))

    def test_every_voice_engine_says_it(self):
        """Seven voice engines, seven declarations — none left to « unknown »."""
        from wama.common.backends import tts_base
        from wama.common.backends.manager import backend_for_engine
        from wama.common.utils.model_capabilities import declared_engine_value
        from wama.synthesizer.utils.model_config import SYNTHESIZER_MODELS
        for key, config in SYNTHESIZER_MODELS.items():
            cls = backend_for_engine(config.get('engine'), key) if config.get('engine') else None
            if cls is None or not issubclass(cls, tts_base.TTSBackend):
                continue
            with self.subTest(engine=cls.__name__):
                self.assertTrue(declared_engine_value(cls, 'default_temperature')[0])

    def test_a_call_takes_the_cards_value_or_the_engines(self):
        from wama.common.backends.higgs_backend import HiggsAudioBackend
        engine = HiggsAudioBackend()
        self.assertEqual(0.7, engine.sampling_temperature({'options': {}}))
        self.assertEqual(0.3, engine.sampling_temperature({'options': {'temperature': '0.3'}}))
        self.assertEqual(0.7, engine.sampling_temperature({}))

    def test_bark_samples_both_stages_at_the_cards_temperature(self):
        import numpy as np

        from wama.common.backends.bark_backend import BarkBackend
        engine = BarkBackend()
        spoken = mock.Mock(return_value=np.zeros(240, dtype=np.float32))
        engine._funcs = {'generate_audio': spoken, 'SAMPLE_RATE': 24000}
        Path(engine.process(text='Bonjour', options={'temperature': 0.5})).unlink()
        self.assertEqual((0.5, 0.5), (spoken.call_args.kwargs['text_temp'],
                                      spoken.call_args.kwargs['waveform_temp']))
        Path(engine.process(text='Bonjour')).unlink()
        self.assertEqual(0.7, spoken.call_args.kwargs['text_temp'], "the engine's own")

    def test_the_speech_render_sends_it_to_the_service_only_when_set(self):
        from wama.synthesizer.utils import speech_render

        def spoken(text, model, **kwargs):
            sent.append(kwargs['options'])
            raise RuntimeError('stop')       # the options are what this test reads
        for temperature, expected in ((None, False), (0.6, True)):
            sent = []
            with self.subTest(temperature=temperature), \
                    mock.patch.object(speech_render, 'tts_via_service', side_effect=spoken), \
                    self.assertRaises(RuntimeError):
                speech_render.render_speech('Bonjour.', '/tmp/x.wav', model='synthesizer:bark',
                                            language='fr', voice_preset='default',
                                            temperature=temperature)
            self.assertEqual(expected, 'temperature' in sent[0])

    def test_the_avatarizer_voice_is_spoken_at_the_cards_temperature(self):
        from wama.avatarizer import workers
        from wama.avatarizer.models import AvatarJob
        from wama.avatarizer.params import PARAMS_JSON
        p = next(p for p in PARAMS_JSON if p['name'] == 'tts_temperature')
        self.assertEqual(('temperature', 'tts_model'), (p['type'], cap_bindings(p)[0]['field']))
        for column, expected in ((0.5, {'temperature': 0.5}), (None, None)):
            with self.subTest(column=column), \
                    mock.patch('wama.common.tts.voice_refs.speaker_wav_for', return_value=None), \
                    mock.patch.object(workers, 'tts_via_service', return_value='x.wav') as spoken:
                from django.contrib.auth import get_user_model
                workers._call_tts_service(AvatarJob(user=get_user_model()(username='voice'),
                                                    text_content='Bonjour.', language='fr',
                                                    tts_model='synthesizer:bark',
                                                    voice_preset='default',
                                                    tts_temperature=column))
                self.assertEqual(expected, spoken.call_args.kwargs['options'])

    def test_musicgen_samples_at_the_cards_temperature_or_its_own(self):
        import os

        from wama.common.backends.audiocraft_backend import AudioCraftBackend
        engine = AudioCraftBackend()
        for asked, expected in ((0.4, 0.4), (None, 1.0)):
            with self.subTest(asked=asked), mock.patch.dict(os.environ), \
                    mock.patch.object(AudioCraftBackend, '_generate_music',
                                      side_effect=RuntimeError('stop')) as music, \
                    self.assertRaises(RuntimeError):
                engine.generate('musicgen-small', 'a calm piano', 10, '/tmp/x.wav',
                                temperature=asked)
            self.assertEqual(expected, music.call_args.kwargs['temperature'])

    def test_every_music_engine_says_it(self):
        from wama.common.backends.audiocpp_backend import AudioCppBackend
        from wama.common.backends.audiocraft_backend import AudioCraftBackend
        from wama.common.backends.yue2_3b_backend import YuE2Backend
        from wama.common.utils.model_capabilities import declared_engine_value
        self.assertEqual({AudioCraftBackend: (True, 1.0), YuE2Backend: (True, None),
                          AudioCppBackend: (True, None)},
                         {cls: declared_engine_value(cls, 'default_temperature')
                          for cls in (AudioCraftBackend, YuE2Backend, AudioCppBackend)})

    def test_the_composer_catalogue_rows_carry_their_engines_temperature(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry()
        registry._models = {}
        registry._discover_composer_models()
        caps = registry._models['composer:musicgen-small'].capabilities
        self.assertEqual((True, 1.0), (TEMPERATURE in caps['params'],
                                       caps['recommended_temperature']))
        self.assertEqual(30.0, caps['max_duration_s'], 'the other facts stay')

    def test_at_zero_audio8_takes_the_most_likely_choice(self):
        import torch

        from wama.common.backends.audio8_backend import Audio8Backend
        engine = Audio8Backend()
        engine._device = 'cpu'
        engine._processor = mock.Mock(return_value={'input_ids': torch.zeros(1, 2)})
        engine._model = mock.Mock()
        engine._model.generate.return_value = mock.Mock(codes=None)
        engine._model.decode_audio.return_value = (torch.zeros(1, 240), [240])
        engine._model.config.codec_sample_rate = 24000
        for asked, expected in ((0, {'do_sample': False}),
                                (0.5, {'do_sample': True, 'temperature': 0.5})):
            with self.subTest(asked=asked):
                Path(engine.process(text='Bonjour', options={'temperature': asked})).unlink()
                sent = engine._model.generate.call_args.kwargs
                self.assertEqual(expected, {k: sent[k] for k in expected})
                if not asked:
                    self.assertNotIn('temperature', sent, 'transformers refuses to sample at 0')

    def test_xtts_receives_the_cards_temperature_and_zero_is_the_most_likely(self):
        from wama.common.backends.coqui_backend import CoquiBackend
        engine = CoquiBackend()
        engine._tts = mock.Mock()
        engine.loaded_model = 'coqui-xtts'
        with tempfile.NamedTemporaryFile(suffix='.wav') as ref:
            for asked, expected in ((None, {'temperature': 0.75, 'do_sample': True}),
                                    (0, {'do_sample': False})):
                with self.subTest(asked=asked):
                    out = engine.process(text='Bonjour', model='coqui-xtts', speaker_wav=ref.name,
                                         options={'temperature': asked})
                    Path(out).unlink(missing_ok=True)
                    sent = engine._tts.tts_to_file.call_args.kwargs
                    self.assertEqual(expected, {k: sent[k] for k in expected})

    def test_qwen3_tts_samples_both_stages_at_the_cards_temperature(self):
        import numpy as np

        from wama.common.backends.qwen3_tts_backend import Qwen3TTSBackend
        engine = Qwen3TTSBackend()
        engine._model = mock.Mock()
        engine._model.generate_custom_voice.return_value = ([np.zeros(240, dtype=np.float32)], 24000)
        for asked, expected in ((None, {'temperature': 0.9, 'subtalker_temperature': 0.9}),
                                (0, {'do_sample': False, 'subtalker_dosample': False})):
            with self.subTest(asked=asked):
                Path(engine.process(text='Bonjour', options={'temperature': asked})).unlink()
                sent = engine._model.generate_custom_voice.call_args.kwargs
                self.assertEqual(expected, {k: sent[k] for k in expected})

    def test_bark_never_goes_below_its_floor(self):
        import numpy as np

        from wama.common.backends.bark_backend import BarkBackend
        engine = BarkBackend()
        spoken = mock.Mock(return_value=np.zeros(240, dtype=np.float32))
        engine._funcs = {'generate_audio': spoken, 'SAMPLE_RATE': 24000}
        Path(engine.process(text='Bonjour', options={'temperature': 0})).unlink()
        self.assertEqual(0.1, spoken.call_args.kwargs['text_temp'], 'it divides by it')

    def test_the_fiche_says_the_floor_and_what_always_renders_the_same(self):
        from wama.common.backends.bark_backend import BarkBackend
        from wama.common.backends.kokoro_backend import KokoroBackend
        from wama.common.backends.yue2_3b_backend import YuE2Backend
        from wama.common.utils.model_capabilities import apply_engine_flags
        from wama.model_manager.services.model_registry import ModelRegistry
        self.assertEqual(0.1, apply_engine_flags({}, BarkBackend)['min_temperature'])
        for cls in (KokoroBackend, YuE2Backend):
            with self.subTest(engine=cls.__name__):
                self.assertIs(True, apply_engine_flags({}, cls)['reproducible'])
        registry = ModelRegistry()
        registry._models = {}
        registry._discover_describer_models()
        self.assertIs(True, registry._models['describer:blip'].capabilities['reproducible'])

    def test_the_avatarizer_voice_is_on_the_panel_like_the_synthesizers(self):
        from wama.avatarizer.params import PARAMS_JSON
        for name in ('tts_model', 'quality_intent', 'language', 'voice_preset', 'tts_temperature'):
            with self.subTest(setting=name):
                p = next(p for p in PARAMS_JSON if p['name'] == name)
                self.assertTrue({'panel', 'item'} <= set(p['contexts']), p['contexts'])

    def test_the_synthesizer_binds_it_to_its_voice_engine(self):
        from wama.synthesizer.params import PARAMS_JSON
        p = next(p for p in PARAMS_JSON if p['name'] == 'temperature')
        self.assertEqual(('temperature', 'tts_model', ('generate',)),
                         (p['type'], cap_bindings(p)[0]['field'], tuple(p['stales'])))


class TheAvatarizerPageServesTheVoiceOnItsPanelTest(TestCase):
    """The served page (the deliverable is VISIBLE, `/reverif §2`): the schema the panel renders
    carries the voice with its panel ids — and the deposit reads the whole panel."""

    def test_the_page_carries_the_voice_for_its_panel(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        user = get_user_model().objects.create_superuser('avatar-panel', 'a@b.c', 'x')
        self.client.force_login(user)
        page = self.client.get(reverse('avatarizer:index'))
        self.assertEqual(200, page.status_code)
        html = page.content.decode()
        for dom_id in ('"panel": "tts_model"', '"panel": "voice_preset"', '"panel": "tts_temperature"'):
            self.assertIn(dom_id, html)
        script = (Path(settings.BASE_DIR) / 'wama/avatarizer/static/avatarizer/js/index.js').read_text(
            encoding='utf-8')
        self.assertIn("WamaParams.read(panel)", script)
        self.assertNotIn("fd.append('animation_model'", script, 'no field read by hand any more')


class TheAssistantSettingsRouteTest(TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user('temperature-assistant', password='x')
        self.client.force_login(self.user)

    def _post(self, data):
        from django.urls import reverse
        response = self.client.post(reverse('ai_chat_settings'), data=json.dumps(data),
                                    content_type='application/json')
        self.assertEqual(200, response.status_code, response.content)

    def _stored(self):
        from wama.common.services.assistant_engine import assistant_settings
        return assistant_settings(self.user)['temperature']

    def test_a_temperature_is_kept_and_given_back_to_the_model(self):
        self._post({'temperature': '0.4'})
        self.assertEqual(0.4, self._stored())
        # Another setting alone does not touch it (the defaults of absent numbers were written).
        self._post({'quality_intent': 70})
        self.assertEqual(0.4, self._stored())
        self._post({'temperature': ''})
        self.assertIsNone(self._stored())


HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
JS = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'

#: A DOM just big enough for the temperature: elements with a class list, `closest`, and a
#: document that KEEPS its listeners so the delegated ones can be fired.
DOM = """
var window = {};
var listeners = {};
var CSS = {escape: function (s) { return s; }};
var document = {readyState: 'complete', querySelectorAll: function () { return []; },
                querySelector: function () { return null; }, getElementById: function () { return null; },
                addEventListener: function (t, fn) { (listeners[t] = listeners[t] || []).push(fn); }};
function Event(type) { this.type = type; }
function CustomEvent(type) { this.type = type; }
function classList(initial) {
  var s = {};
  (initial || []).forEach(function (c) { s[c] = 1; });
  return {add: function (c) { s[c] = 1; }, remove: function (c) { delete s[c]; },
          toggle: function (c, on) { if (on === undefined) on = !s[c]; if (on) s[c] = 1; else delete s[c]; },
          contains: function (c) { return !!s[c]; }};
}
function temperatureWidget(value, recommended, caps) {
  var wrap = {classList: classList(['wama-temperature'])};
  function part(cls, extra) {
    var el = {classList: classList([cls]), dataset: {}, disabled: false, dispatched: [],
              dispatchEvent: function (e) { el.dispatched.push(e.type); },
              closest: function () { return wrap; }};
    for (var k in extra) el[k] = extra[k];
    return el;
  }
  var parts = {value: part('wama-temperature-value', {value: value}),
               slider: part('wama-temperature-slider', {value: '1'}),
               own: part('wama-temperature-own', {checked: false}),
               val: part('wama-temperature-val', {textContent: ''}),
               hint: part('wama-temperature-hint', {textContent: ''})};
  if (recommended !== undefined || caps) {
    parts.slider.wamaModelCaps = caps || {recommended_temperature: recommended};
  }
  var byClass = {'.wama-temperature-value': parts.value, '.wama-temperature-slider': parts.slider,
                 '.wama-temperature-own': parts.own, '.wama-temperature-val': parts.val,
                 '.wama-temperature-hint': parts.hint};
  wrap.querySelector = function (sel) { return byClass[sel] || null; };
  parts.wrap = wrap;
  return parts;
}
function fire(type, target, trusted) {
  (listeners[type] || []).forEach(function (fn) { fn({type: type, target: target, isTrusted: !!trusted}); });
}
function state(w) {
  return {value: w.value.value, slider: String(w.slider.value), own: w.own.checked,
          label: w.val.textContent, boxDisabled: w.own.disabled, hint: w.hint.textContent,
          announced: w.value.dispatched.slice()};
}
"""


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class TemperatureWidgetJsTest(SimpleTestCase):

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(DOM)
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def _run(self, body):
        return self.v8.eval('(function () {' + body + '})()')

    def test_left_to_the_model_it_sits_on_the_publishers_value(self):
        out = self._run("var w = temperatureWidget('', '1'); window.WamaParams.syncTemperature(w.wrap);"
                        "return state(w);")
        self.assertEqual(('', '1', True, 'du modèle (1)'),
                         (out['value'], out['slider'], out['own'], out['label']))

    def test_a_set_value_unticks_the_models_own(self):
        out = self._run("var w = temperatureWidget('0.4', '1'); window.WamaParams.syncTemperature(w.wrap);"
                        "return state(w);")
        self.assertEqual(('0.4', '0.4', False, '0.4'),
                         (out['value'], out['slider'], out['own'], out['label']))

    def test_moving_the_slider_sets_it_and_says_so(self):
        out = self._run("var w = temperatureWidget('', '1'); w.slider.value = '0.6';"
                        "fire('input', w.slider, true); fire('change', w.slider, true);"
                        "return state(w);")
        self.assertEqual(('0.6', False), (out['value'], out['own']))
        self.assertEqual(['change'], list(out['announced']), 'the field that posts says it')

    def test_a_bound_that_moves_the_slider_does_not_set_it(self):
        """The engine's maximum brings the slider back by program: the model's own stays."""
        out = self._run("var w = temperatureWidget('', '1'); w.slider.value = '1';"
                        "fire('input', w.slider, false); return state(w);")
        self.assertEqual(('', True), (out['value'], out['own']))

    def test_ticking_the_models_own_empties_the_value(self):
        out = self._run("var w = temperatureWidget('0.4'); w.own.checked = true;"
                        "fire('change', w.own, true); return state(w);")
        self.assertEqual(('', True, 'du modèle'), (out['value'], out['own'], out['label']))

    def test_under_a_model_that_does_not_sample_the_box_greys_with_the_slider(self):
        out = self._run(
            "var w = temperatureWidget('0.4'); var note = {textContent: '', classList: classList()};"
            "var row = {classList: classList()};"
            "var cf = {field: 'm', capability: 'params', mode: 'reads', param: 'temperature'};"
            "window.WamaParams.applyCapFrom(w.slider, note, row, {name: 'vision_temperature'}, cf,"
            "                               {params: []});"
            "fire('wama:cap-applied', w.slider); return state(w);")
        self.assertTrue(out['boxDisabled'])
        self.assertEqual('0.4', out['value'], "the value stays the user's")

    def test_the_note_says_the_publishers_value_zero_included(self):
        out = self._run(
            "var el = {dataset: {}}; var note = {textContent: '', classList: classList()};"
            "var cf = {field: 'm', capability: 'recommended_temperature', mode: 'note',"
            "          label: 'Celle du modèle :'};"
            "window.WamaParams.applyCapFrom(el, note, null, {}, cf, {recommended_temperature: 0});"
            "var zero = note.textContent;"
            "window.WamaParams.applyCapFrom(el, note, null, {}, cf, {recommended_temperature: null});"
            "return {zero: zero, text: note.textContent};")
        self.assertEqual(('Celle du modèle : 0', ''), (out['zero'], out['text']))

    def test_the_line_under_the_slider_says_whether_the_result_is_reproducible(self):
        hint = lambda caps, value, own, disabled=False: self._run(  # noqa: E731
            f"return window.WamaParams.temperatureHint({json.dumps(caps)}, {json.dumps(value)},"
            f" {json.dumps(own)}, {json.dumps(disabled)});")
        self.assertIn('Reproductible', hint({}, '0', False))
        self.assertIn('varie', hint({}, '0.7', False))
        self.assertIn('varie', hint({'recommended_temperature': 1}, '', True),
                      "the model's own is often above 0")
        self.assertIn('Reproductible', hint({'recommended_temperature': 0}, '', True))
        self.assertIn('en général', hint(None, '', True), 'unknown under « auto »')
        self.assertIn('ne descend pas à 0', hint({'min_temperature': 0.1}, '0.1', False))
        self.assertIn('Reproductible', hint({'reproducible': True}, '', True, True),
                      'a model that always renders the same says so, greyed or not')
        self.assertEqual('', hint({'params': []}, '0.4', False, True))

    def test_the_slider_shows_the_line_for_the_value_of_the_moment(self):
        out = self._run("var w = temperatureWidget('', 1); window.WamaParams.syncTemperature(w.wrap);"
                        "var own = w.hint.textContent; w.value.value = '0';"
                        "window.WamaParams.syncTemperature(w.wrap); return [own, w.hint.textContent];")
        self.assertIn('varie', out[0])
        self.assertIn('Reproductible', out[1])

    def test_an_engine_floor_stops_the_slider_and_lifts_a_value_below(self):
        out = self._run(
            "var el = {value: '0', min: '0', dataset: {}, dispatched: [],"
            "          dispatchEvent: function (e) { el.dispatched.push(e.type); }};"
            "var note = {textContent: '', classList: classList()};"
            "var cf = {field: 'm', capability: 'min_temperature', mode: 'min'};"
            "window.WamaParams.applyCapFrom(el, note, null, {min: 0}, cf, {min_temperature: 0.1});"
            "var lifted = [String(el.value), String(el.min), note.textContent, el.dispatched.join()];"
            "window.WamaParams.applyCapFrom(el, note, null, {min: 0}, cf, {});"
            "return {lifted: lifted, back: String(el.min), note: note.textContent};")
        self.assertEqual(['0.1', '0.1', 'Minimum du modèle : 0,1', 'input'], list(out['lifted']))
        self.assertEqual(('0', ''), (out['back'], out['note']), 'another model: the schema floor')

    def test_a_condition_on_a_field_not_rendered_here_leaves_the_setting_visible(self):
        """The avatarizer's voice in the panel depends on the deposit card's text, which the
        panel does not render (2026-10-22): not judged, shown. A field rendered here still rules."""
        def shown(fields):
            return self._run(
                "var row = {style: {}, getAttribute: function () { return 'text_content'; }};"
                f"var fields = {json.dumps(fields)}.map(function (f) {{ return {{value: f[1],"
                "  getAttribute: function (n) { return n === 'name' ? f[0] : null; }}; });"
                "var box = {addEventListener: function () {}, querySelectorAll: function (sel) {"
                "  return sel === '[data-show-if]' ? [row] : fields; }};"
                "window.WamaParams.bindConditional(box); return row.style.display !== 'none';")
        self.assertTrue(shown([['tts_model', 'auto']]), 'the field is not in this rendering')
        self.assertFalse(shown([['text_content', '']]), 'rendered and empty: hidden')
        self.assertTrue(shown([['text_content', 'Bonjour.']]))

    def test_a_list_of_bindings_and_a_single_one_read_alike(self):
        out = self._run("return [window.WamaParams.capBindings({cap_from: {field: 'm'}}).length,"
                        " window.WamaParams.capBindings({cap_from: [{field: 'a'}, {field: 'b'}]}).length,"
                        " window.WamaParams.capBindings({}).length];")
        self.assertEqual([1, 2, 0], list(out))

    def test_the_renderer_posts_an_empty_value_when_left_to_the_model(self):
        out = self._run(
            "var host = {innerHTML: '', querySelectorAll: function () { return []; },"
            "            querySelector: function () { return null; }, addEventListener: function () {}};"
            "window.WamaParams.render(host, [{name: 'temperature', type: 'temperature', min: 0,"
            "  max: 2, step: 0.05, label: 'Température', default: null}], {context: 'item'});"
            "return host.innerHTML;")
        self.assertIn('id="wp-item-temperature" name="temperature" '
                      'data-cap-target="wp-item-temperature-slider" value=""', out,
                      'an id reader (the panel inspector) reads the field that carries the value')
        self.assertIn('id="wp-item-temperature-slider"', out)
        self.assertIn('wama-temperature-own" type="checkbox" id="wp-item-temperature-own" checked',
                      out)
        self.assertIn('wama-temperature-hint', out)

    def test_the_capability_bindings_act_on_the_slider_not_on_the_carrying_field(self):
        """`data-cap-target`: the id is the carrying field's, the bounds go to the slider — run
        through the real wiring (`bindCapFrom`) with a stand-in catalogue."""
        self._run("""
            document.createElement = function () { return {className: '', textContent: '',
                                                           classList: classList()}; };
            window.fetch = fetch = function () { return Promise.resolve({json: function () {
                return Promise.resolve({models: [{model_key: 'synthesizer:kokoro',
                                                  capabilities: {params: [], reproducible: true}}]}); }}); };
            window.slider = {value: '1', min: '0', max: '2', dataset: {}, disabled: false, title: '',
                             classList: classList(), style: {setProperty: function () {},
                             removeProperty: function () {}}, closest: function () { return null; },
                             parentNode: {appendChild: function () {}},
                             addEventListener: function () {}, dispatchEvent: function () {}};
            window.carrier = {getAttribute: function (n) {
                return n === 'data-cap-target' ? 'wp-item-temperature-slider' : null; }};
            var select = {value: 'synthesizer:kokoro', addEventListener: function () {}};
            var byId = {'#wp-item-temperature': window.carrier, '#wp-item-temperature-slider': window.slider,
                        '#wp-item-tts_model': select};
            var box = {querySelector: function (sel) { return byId[sel] || null; }};
            var schema = [{name: 'tts_model', type: 'select', options_source: 'catalog',
                           options_query: {task: 'text-to-speech'}, help_source: 'synthesizer'},
                          {name: 'temperature', type: 'temperature', min: 0, max: 2,
                           cap_from: [{field: 'tts_model', capability: 'params', mode: 'reads',
                                       param: 'temperature'}]}];
            window.WamaParams.bindCapFrom(box, schema, 'item');
            return true;""")
        out = self._run("return [window.slider.disabled, !!window.slider.wamaModelCaps,"
                        " window.carrier.disabled === undefined];")
        self.assertEqual([True, True, True], list(out),
                         'the slider is greyed and knows its model; the carrying field is untouched')

    def test_a_value_set_on_the_carrying_field_moves_the_surface(self):
        """The panel inspector sets the field by its id, then says `change`: the surface follows."""
        out = self._run("var w = temperatureWidget(''); w.value.value = '0.3';"
                        "fire('change', w.value, false); return state(w);")
        self.assertEqual(('0.3', '0.3', False), (out['value'], out['slider'], out['own']))
