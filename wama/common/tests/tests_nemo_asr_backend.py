"""
`NemoASRBackend` (Canary 1B v2 / Parakeet TDT 0.6B v3, 2026-09-28) — what can be held WITHOUT the
NeMo runtime: the declarations the installer and the catalogue read, the model a request loads,
and the conversion of NeMo stamps to the common segment shape (words like Whisper's).
The runtime itself is attested by a real run (see `TRANSCRIBER_CORRECTION §5`).
"""
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from wama.common.backends.nemo_asr_backend import NemoASRBackend


class DeclarationTest(SimpleTestCase):

    def test_the_runtime_installs_without_its_pins_and_the_list_is_exhaustive(self):
        """Honouring nemo_toolkit's pins would downgrade lightning, protobuf and fsspec: `--no-deps`,
        so every NEW package must be listed — each one pinned (the installer refuses otherwise)."""
        self.assertTrue(NemoASRBackend.PIP_NO_DEPS)
        self.assertIn('nemo-toolkit==3.0.0', NemoASRBackend.PIP_PACKAGES)
        self.assertTrue(all('==' in p for p in NemoASRBackend.PIP_PACKAGES), NemoASRBackend.PIP_PACKAGES)
        self.assertIn('nemo', NemoASRBackend.REQUIRED_PACKAGES)

    def test_a_request_selects_the_model_it_names_else_the_default(self):
        B = NemoASRBackend
        self.assertEqual('canary-1b-v2', B.model_id_for('transcriber:canary-1b-v2'))
        self.assertEqual('canary-1b-v2', B.model_id_for('nvidia/canary-1b-v2'))
        self.assertEqual('parakeet-tdt-0.6b-v3', B.model_id_for(None))
        self.assertEqual('parakeet-tdt-0.6b-v3', B.model_id_for('nemo'))

    def test_only_canary_demands_its_language(self):
        self.assertTrue(NemoASRBackend.SUPPORTED_MODELS['canary-1b-v2']['multitask'])
        self.assertFalse(NemoASRBackend.SUPPORTED_MODELS['parakeet-tdt-0.6b-v3']['multitask'])


class StampsToSegmentsTest(SimpleTestCase):

    def test_segments_carry_their_words_in_the_common_shape(self):
        hyp = SimpleNamespace(text='Bonjour à tous. Merci.', timestamp={
            'word': [{'word': 'Bonjour', 'start': 0.1, 'end': 0.5}, {'word': 'à', 'start': 0.5, 'end': 0.6},
                     {'word': 'tous.', 'start': 0.6, 'end': 1.0}, {'word': 'Merci.', 'start': 1.4, 'end': 1.9}],
            'segment': [{'segment': 'Bonjour à tous.', 'start': 0.1, 'end': 1.0},
                        {'segment': 'Merci.', 'start': 1.4, 'end': 1.9}]})
        segs = NemoASRBackend._segments_of(hyp, 2.0)
        self.assertEqual([(0.1, 1.0), (1.4, 1.9)], [(s.start_time, s.end_time) for s in segs])
        self.assertEqual(['Bonjour', 'à', 'tous.'], [w['word'] for w in segs[0].words])
        self.assertEqual({'word', 'start', 'end', 'probability'}, set(segs[0].words[0]))

    def test_without_segment_stamps_one_segment_spans_the_chunk(self):
        segs = NemoASRBackend._segments_of(SimpleNamespace(text='Bonjour.', timestamp={}), 9.4)
        self.assertEqual([(0.0, 9.4, 'Bonjour.')], [(s.start_time, s.end_time, s.text) for s in segs])


class LanguageTest(SimpleTestCase):
    """First GPU run (2026-09-28): a French clip, no language on the item, Canary given the SITE
    language (`LANGUAGE_CODE = 'en-us'`) — it came out TRANSLATED into English, with no error."""

    def _canary(self, captured):
        from unittest import mock

        import numpy as np
        backend = NemoASRBackend()
        backend._loaded, backend._model_id = True, 'canary-1b-v2'

        def transcribe(audio, **options):
            captured.update(options)
            return [SimpleNamespace(text='Bonjour.', timestamp={})]
        backend._model = SimpleNamespace(transcribe=transcribe)
        return backend, mock.patch.object(NemoASRBackend, '_load_audio',
                                          return_value=np.zeros(16000, dtype='float32'))

    def test_canary_gets_the_HEARD_language_never_the_site_language(self):
        from unittest import mock
        captured = {}
        backend, audio = self._canary(captured)
        with audio, mock.patch('wama.common.utils.spoken_language.detect_spoken_language',
                               return_value=('fr', 0.97)):
            result = backend.transcribe('clip.wav')
        self.assertEqual(('fr', 'fr'), (captured['source_lang'], captured['target_lang']))
        self.assertEqual('fr', result.language)

    def test_a_given_language_is_used_without_listening(self):
        from unittest import mock
        captured = {}
        backend, audio = self._canary(captured)
        with audio, mock.patch('wama.common.utils.spoken_language.detect_spoken_language') as heard:
            backend.transcribe('clip.wav', language='de')
        heard.assert_not_called()
        self.assertEqual('de', captured['source_lang'])

    def test_an_unsupported_heard_language_fails_instead_of_being_translated(self):
        from unittest import mock
        backend, audio = self._canary({})
        with audio, mock.patch('wama.common.utils.spoken_language._model') as model:
            model.return_value.detect_language.return_value = ('zh', 0.93, [])
            result = backend.transcribe('clip.wav')
        self.assertFalse(result.success)
        self.assertIn('zh', result.error)

    def _heard(self, language, probability, fallback):
        from unittest import mock
        captured = {}
        backend, audio = self._canary(captured)
        with audio, mock.patch('wama.common.utils.spoken_language._model') as model:
            model.return_value.detect_language.return_value = (language, probability, [])
            result = backend.transcribe('clip.wav', fallback_language=fallback)
        return result, captured.get('source_lang')

    def test_an_unsupported_pass_takes_the_fallback_instead_of_failing_the_card(self):
        """FLEURS-CS #904 : un passage détecté « la » (latin, p = 0,40) faisait échouer la card."""
        result, source = self._heard('la', 0.40, fallback='fr')
        self.assertTrue(result.success)
        self.assertEqual('fr', source)

    def test_an_unsure_pass_takes_the_fallback_a_sure_one_keeps_its_language(self):
        self.assertEqual('fr', self._heard('es', 0.35, fallback='fr')[1])
        self.assertEqual('es', self._heard('es', 0.90, fallback='fr')[1], 'une bascule sûre est suivie')


class WiringTest(TestCase):

    def test_the_transcriber_routes_canary_and_parakeet_to_nemo(self):
        from wama.transcriber.backends.manager import TranscriberBackendManager as M
        from wama.transcriber.catalogue_fixtures import transcription_catalogue
        # Le moteur se RÉSOUT par le catalogue depuis le 2026-09-30 (route F4b ⑦).
        transcription_catalogue('transcriber:canary-1b-v2', 'transcriber:parakeet-tdt-0.6b-v3')
        self.assertEqual('nemo', M._backend_for_model_key('transcriber:canary-1b-v2'))
        self.assertEqual('nemo', M._backend_for_model_key('parakeet-tdt-0.6b-v3'))
        self.assertEqual('canary-1b-v2',
                         M.model_for_request(NemoASRBackend(), 'transcriber:canary-1b-v2'))

    def test_the_discovery_lists_both_with_their_languages_and_install_dir(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry()
        registry._models = {}
        registry._discover_transcriber_models()
        for key in ('transcriber:canary-1b-v2', 'transcriber:parakeet-tdt-0.6b-v3'):
            with self.subTest(key=key):
                info = registry._models[key]
                self.assertIn('fr', info.capabilities['languages'])
                self.assertNotIn('*', info.capabilities['languages'])
                self.assertTrue(info.extra_info.get('install_dir'))
                self.assertEqual('transcription', info.capabilities['task'])
