"""
La voix de l'assistant ne prononce pas les BALISES de bascule de langue d'espeak (2026-10-03).

Défaut ENTENDU par Fabien : « WAMA » lu « WAMAfreu ». Mesure : en `fr-fr`, espeak-ng rend
`asistˈɑ̃ (en)wˈɑːmə(fr).` pour « assistant WAMA. » ; le tokenizer de `kokoro_onnx` garde ces
balises (tous leurs caractères sont à son vocabulaire) — le modèle les lit : « wama-fr ».
`kokoro_onnx_backend.phonemes_without_language_flags` phonémise avec `remove-flags`.

Aucun poids n'est chargé : le tokenizer seul (espeak embarqué par `espeakng_loader`). Sans le
paquet `kokoro_onnx` (autre venv), les tests sont SAUTÉS — ils ne mesurent que ce moteur.
"""
from unittest import skipUnless

from django.test import SimpleTestCase

try:
    from kokoro_onnx.tokenizer import Tokenizer
except Exception:                                            # paquet absent de ce venv
    Tokenizer = None

SENTENCE = 'Bonjour, je suis votre assistant WAMA.'
#: Les balises de bascule telles qu'elles arrivent au modèle (les parenthèses SONT au vocabulaire).
LEAKED_TAIL = '(fr)'
LEAKED_HEAD = '(en)'


@skipUnless(Tokenizer is not None, 'kokoro_onnx absent de ce venv')
class LanguageSwitchFlagsTest(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tokenizer = Tokenizer()

    def test_a_foreign_word_is_spoken_without_the_flag_letters(self):
        from wama.common.backends.kokoro_onnx_backend import phonemes_without_language_flags
        phonemes = phonemes_without_language_flags(self.tokenizer, SENTENCE, 'fr-fr')
        compact = phonemes.replace(' ', '')
        self.assertNotIn(LEAKED_TAIL, compact)
        self.assertNotIn(LEAKED_HEAD, compact)
        self.assertTrue(phonemes.endswith('.'), phonemes)     # la ponctuation, elle, reste
        self.assertIn('asist', phonemes)                      # et le français autour aussi

    def test_a_plain_french_sentence_is_unchanged_by_the_workaround(self):
        """Contre-épreuve : sans mot étranger, notre chemin rend ce que rend la librairie."""
        from wama.common.backends.kokoro_onnx_backend import phonemes_without_language_flags
        plain = 'Bonjour, que puis-je faire pour vous ?'
        self.assertEqual(self.tokenizer.phonemize(plain, 'fr-fr'),
                         phonemes_without_language_flags(self.tokenizer, plain, 'fr-fr'))

    def test_the_library_tokenizer_still_leaks_the_flags(self):
        """Le DÉTECTEUR voit le défaut : la phonémisation de la librairie le porte encore.

        Si ce test échoue, `kokoro_onnx` a corrigé en amont — le contournement du backend peut
        être retiré (et ce test avec lui).
        """
        compact = self.tokenizer.phonemize(SENTENCE, 'fr-fr').replace(' ', '')
        self.assertIn(LEAKED_TAIL, compact)


@skipUnless(Tokenizer is not None, 'kokoro_onnx absent de ce venv')
class VoicePausesAreSilencesBetweenSegmentsTest(SimpleTestCase):
    """Le RÉGLAGE des pauses (2026-10-18). Notre modèle ne rend pas la durée de ses phonèmes
    (`has_timings` faux) : `Kokoro.create(sentence_pause=…)` n'allonge AUCUNE pause à l'intérieur
    d'une réplique (mesuré : 3,58 s de son pour 0, 0,25 et 0,8 s). Le moteur synthétise donc
    chaque segment et pose le silence demandé. Aucun poids : le modèle est un double qui rend
    une seconde de « son » par appel."""

    TEXT = 'Le chat dort, puis il mange. Ensuite il joue.'
    RATE = 24000

    def _render(self, options):
        import numpy as np
        import soundfile
        from unittest import mock
        from wama.common.backends.kokoro_onnx_backend import KokoroOnnxBackend
        backend = KokoroOnnxBackend()
        fake = mock.Mock()
        fake.tokenizer = Tokenizer()
        fake.create.side_effect = lambda *a, **k: (np.ones(self.RATE, dtype=np.float32), self.RATE)
        backend._kokoro = fake
        path = backend.process(self.TEXT, language='fr', options=options)
        audio, _ = soundfile.read(path)
        import os
        os.unlink(path)
        return fake.create.call_count, len(audio) / self.RATE

    def test_each_mark_gets_the_silence_it_asks_for(self):
        calls, seconds = self._render({'sentence_pause': 0.5, 'clause_pause': 0.2})
        self.assertEqual(3, calls)                         # « …dort, » « …mange. » « …joue. »
        self.assertAlmostEqual(3 + 0.2 + 0.5, seconds, places=2)

    def test_no_pause_asked_is_one_call_as_before(self):
        """Contre-épreuve : sans réglage, le texte part d'un seul tenant — le comportement d'avant."""
        self.assertEqual((1, 1.0), self._render(None))

    def test_an_absurd_pause_is_bounded_by_the_engine(self):
        _, seconds = self._render({'sentence_pause': 60, 'clause_pause': 0})
        self.assertAlmostEqual(2 + 2.0, seconds, places=2)  # MAX_PAUSE_S, une seule pause
