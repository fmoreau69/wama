"""
Les PAUSES de la voix sont posées par le CONTRAT COMMUN des moteurs TTS (2026-10-18).

La boucle « découper là où le texte respire, dire chaque segment, poser le silence » vivait dans le
seul `kokoro_onnx_backend` : les autres moteurs du synthesizer (XTTS, Higgs, Bark, Qwen3-TTS…)
recevaient le réglage dans `options` et l'ignoraient. Elle vit désormais dans
`tts_base.TTSBackend.synthesize`, la porte qu'emprunte le service pour TOUT moteur. Ces tests jouent
un moteur double, sans poids : une seconde de « son » par segment.
"""
import os

from django.test import SimpleTestCase

RATE = 16000


def _engine():
    import numpy as np

    from wama.common.backends.tts_base import TTSBackend, write_wav_int16

    class Engine(TTSBackend):
        engine = 'double'

        def __init__(self):
            super().__init__()
            self.calls = []

        def load(self, *args, **kwargs):
            return True

        def unload(self):
            pass

        def is_loaded(self):
            return True

        def process(self, text='', scene_description='', **kwargs):
            self.calls.append((text, scene_description))
            return write_wav_int16(np.ones(RATE, dtype=np.float32), RATE)

    return Engine()


def _seconds(path):
    from scipy.io.wavfile import read
    rate, data = read(path)
    os.unlink(path)
    return len(data) / rate


class AnyEngineGetsThePausesTest(SimpleTestCase):

    TEXT = 'Le chat dort, puis il mange. Ensuite il joue.'

    def test_every_engine_says_each_segment_and_gets_the_silence_asked(self):
        engine = _engine()
        seconds = _seconds(engine.synthesize(text=self.TEXT, options={'sentence_pause': 0.5,
                                                                      'clause_pause': 0.2}))
        self.assertEqual(['Le chat dort,', 'puis il mange.', 'Ensuite il joue.'],
                         [text for text, _ in engine.calls])
        self.assertAlmostEqual(3 + 0.2 + 0.5, seconds, places=2)

    def test_without_pauses_the_engine_is_called_once_as_before(self):
        engine = _engine()
        self.assertAlmostEqual(1.0, _seconds(engine.synthesize(text=self.TEXT, options={})))
        self.assertEqual([(self.TEXT, '')], engine.calls)

    def test_a_multi_speaker_dialogue_is_never_cut(self):
        """Higgs : `[S1]` vaut pour la suite du texte — un segment perdrait son locuteur."""
        engine = _engine()
        _seconds(engine.synthesize(text='[S1] Bonjour, toi. [S2] Salut.', multi_speaker=True,
                                   options={'sentence_pause': 0.5, 'clause_pause': 0.2}))
        self.assertEqual(1, len(engine.calls))

    def test_the_scene_opens_the_first_segment_only(self):
        engine = _engine()
        _seconds(engine.synthesize(text=self.TEXT, scene_description='Une cuisine.',
                                   options={'sentence_pause': 0.5}))
        self.assertEqual(['Une cuisine.', ''], [scene for _, scene in engine.calls])

    def test_a_segment_with_nothing_to_say_is_a_silence_not_a_call(self):
        """« … » seul entre deux phrases : un moteur sans phonème lèverait pour tout le texte."""
        engine = _engine()
        seconds = _seconds(engine.synthesize(text='Bonjour. ... Au revoir.',
                                             options={'sentence_pause': 0.5}))
        self.assertEqual(['Bonjour.', 'Au revoir.'], [text for text, _ in engine.calls])
        self.assertAlmostEqual(2 + 0.5 + 0.5, seconds, places=2)

    def test_an_absurd_pause_is_bounded(self):
        engine = _engine()
        seconds = _seconds(engine.synthesize(text='Un. Deux.', options={'sentence_pause': 60}))
        self.assertAlmostEqual(2 + 2.0, seconds, places=2)          # MAX_PAUSE_S
