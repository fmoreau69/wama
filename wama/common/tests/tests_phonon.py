"""Phonon (Gradium, 2026-10-28) branché partout où une voix se dit — moteur, catalogue, voix.

Le runtime `ptts` est remplacé par un double qui enregistre ses appels : ce qui se garde ici est
ce que WAMA lui DEMANDE (la voix, le tirage, le texte après le contrat commun), pas le son.
"""
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

import numpy as np
from django.test import SimpleTestCase

from wama.common.backends import phonon_backend
from wama.common.backends.phonon_backend import PhononBackend, voice_file


class _FakeTTS:
    calls = []

    def __init__(self, folder, lang='fr', quant='q8'):
        self.folder, self.lang, self.quant = folder, lang, quant
        self.voices = ['Noemie', 'Augustin']
        self.sample_rate = 24000

    def synth(self, text, **kwargs):
        self.calls.append({'text': text, **kwargs})
        return np.full(2400, 0.1, dtype=np.float32)


class PhononVoicesTest(SimpleTestCase):

    def test_its_own_voices_and_the_common_presets_name_an_installed_voice(self):
        self.assertEqual('Augustin', voice_file('phonon_augustin'))
        self.assertEqual('Tiphaine', voice_file('female_2'))
        self.assertEqual('Lucien', voice_file('male_2'))
        self.assertEqual('Noemie', voice_file('default'))
        installed = {f['path'] for f in phonon_backend.PHONON_FILES}
        for voice in phonon_backend.VOICES:
            self.assertIn(f"voices/{voice['file']}.safetensors", installed, voice['value'])

    def test_a_voice_of_another_engine_falls_back_to_the_default_voice(self):
        self.assertEqual('Noemie', voice_file('ff_siwis'))
        self.assertEqual('Noemie', voice_file('ua_12'))


class PhononProcessTest(SimpleTestCase):

    def setUp(self):
        _FakeTTS.calls = []
        self.folder = Path(tempfile.mkdtemp())
        (self.folder / 'config.json').write_text('{}')
        patches = [mock.patch.dict(sys.modules, {'ptts': types.SimpleNamespace(TTS=_FakeTTS)}),
                   mock.patch.object(phonon_backend, 'model_folder', return_value=self.folder)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _say(self, text, **kwargs):
        import os
        path = PhononBackend().synthesize(text=text, language='fr', **kwargs)
        self.addCleanup(os.remove, path)
        return path

    def test_it_says_the_chosen_voice_with_the_card_sampling(self):
        self._say('Bonjour.', voice_preset='phonon_augustin',
                  options={'temperature': 0.2, 'seed': 7})
        self.assertEqual([{'text': 'Bonjour.', 'voice': 'Augustin', 'temperature': 0.2, 'seed': 7}],
                         _FakeTTS.calls)

    def test_without_settings_it_samples_at_its_own_temperature_and_no_seed(self):
        self._say('Bonjour.')
        self.assertEqual(0.3, _FakeTTS.calls[0]['temperature'])
        self.assertNotIn('seed', _FakeTTS.calls[0])

    def test_the_common_contract_gives_it_the_pauses_and_the_lexicon(self):
        """Il reçoit du TEXTE : « 8 Go » lui arrive réécrit, et la phrase est dite en deux
        segments séparés par le silence réglé."""
        from wama.common.utils.audio_decode import decode_audio
        path = self._say('Il faut 8 Go. Merci.', options={'sentence_pause': 0.5})
        self.assertEqual(['Il faut 8 gigaoctets.', 'Merci.'], [c['text'] for c in _FakeTTS.calls])
        audio, rate = decode_audio(path, mono=True)
        self.assertGreaterEqual(len(audio), 2 * 2400 + int(0.5 * rate) - 1)


class PhononCatalogTest(SimpleTestCase):
    """Sa ligne de catalogue porte son moteur et ce que le moteur déclare."""

    def _line(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry.__new__(ModelRegistry)
        registry._models, registry.discovery_errors = {}, []
        registry._discover_phonon_models()
        self.assertEqual([], registry.discovery_errors)
        return registry._models[phonon_backend.MODEL_KEY]

    def test_the_line_runs_on_its_engine_and_carries_its_voices(self):
        line = self._line()
        self.assertEqual('phonon', line.composition['runtime']['engine'])
        caps = line.capabilities
        self.assertEqual(['phonon_noemie', 'phonon_tiphaine', 'phonon_augustin', 'phonon_lucien'],
                         [v['value'] for v in caps['voices']])
        self.assertIs(True, caps['realtime'])
        self.assertEqual(1.1, caps['first_audio_s'])
        self.assertIs(False, caps['supports_cloning'])
        self.assertIn('seed', caps['params'])
        self.assertIn('temperature', caps['params'])

    def test_the_voice_service_finds_its_engine(self):
        from wama.synthesizer.backends import ENGINE_BACKENDS, engine_for_model
        self.assertIn('phonon', ENGINE_BACKENDS)
        self.assertEqual('phonon', engine_for_model(phonon_backend.MODEL_KEY, 'phonon'))
