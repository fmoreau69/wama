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
