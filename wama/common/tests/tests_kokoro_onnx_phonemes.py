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
class TechnicalTermsAreSaidByTheLexiconTest(SimpleTestCase):
    """Les termes techniques dits par les phonèmes du lexique (2026-10-27). Mesuré avant :
    « git » → `ʒˈi`, « commit » → `kɔmˈi`. Aucun poids : le modèle est un double qui retient la
    chaîne de phonèmes qu'on lui donne."""

    TEXT = 'Fais un git commit, puis un merge.'

    def _phonemes(self, text=None, options=None):
        import numpy as np
        import os
        from unittest import mock
        from wama.common.backends.kokoro_onnx_backend import KokoroOnnxBackend
        backend = KokoroOnnxBackend()
        backend._kokoro = mock.Mock(tokenizer=Tokenizer())
        backend._kokoro.create.side_effect = lambda *a, **k: (np.ones(10, np.float32), 24000)
        os.unlink(backend.synthesize(text=text or self.TEXT, language='fr', options=options))
        return backend._kokoro.create.call_args.args[0]

    def test_the_voice_receives_the_lexicon_phonemes(self):
        phonemes = self._phonemes()
        for said in ('ɡˈit', 'kɔmˈit,', 'mˈœʁdʒ.'):
            self.assertIn(said, phonemes)
        self.assertNotIn('ʒˈi', phonemes)
        self.assertIn('fˈɛz', phonemes)                     # le français autour, par espeak

    def test_without_the_lexicon_espeak_reads_them_the_french_way(self):
        """Contre-épreuve : le lexique vidé, on retrouve la lecture mesurée avant lui."""
        from unittest import mock
        with mock.patch('wama.common.utils.tts_text.pronunciations', lambda language: {}):
            phonemes = self._phonemes()
        self.assertIn('ʒˈi', phonemes)
        self.assertNotIn('ɡˈit', phonemes)

    def test_every_entry_is_in_the_voice_vocabulary(self):
        """Un caractère hors du vocabulaire est EFFACÉ sans erreur par le tokenizer."""
        from wama.common.utils.tts_text import pronunciations
        vocab = Tokenizer().vocab
        unknown = {term: [c for c in entry.get('phonemes', '').replace('^', '') if c not in vocab]
                   for term, entry in pronunciations('fr').items()}
        self.assertEqual({}, {term: chars for term, chars in unknown.items() if chars})

    def test_the_account_lexicon_sent_with_the_request_is_said(self):
        """Les lignes d'un compte arrivent par `options['lexicon']` (le service n'a pas Django) :
        une orthographe à dire est phonémisée par espeak, à la place de la lecture française."""
        said = self._phonemes('Un git.', {'lexicon': {'git': {'spelling': 'jite'}}})
        self.assertNotIn('ɡˈit', said)
        self.assertEqual(said, self._phonemes('Un jite.'))

    def test_wama_is_said_the_french_way_by_its_spelling(self):
        """L'ancien `SPOKEN_FORMS` : « WAMA » est dit comme « Ouama » (`wamˈa`), le texte ne
        change plus avant le moteur."""
        self.assertEqual(self._phonemes('Bienvenue dans Ouama.'),
                         self._phonemes('Bienvenue dans WAMA.'))


class PytorchTwinSaysTheLexiconTooTest(SimpleTestCase):
    """Le jumeau `.pt` (KPipeline, misaki `EspeakG2P`) reçoit le même lexique, dans la notation de
    misaki (`d^ʒ` → `ʤ`)."""

    def test_the_twin_phonemizer_gets_the_lexicon(self):
        try:
            from misaki.espeak import EspeakG2P
        except Exception:
            self.skipTest('misaki absent de ce venv')
        from wama.common.backends.kokoro_backend import LexiconG2P
        phonemes, _ = LexiconG2P(EspeakG2P(language='fr-fr'), 'fr')('Fais un git merge.')
        self.assertIn('ɡˈit', phonemes)
        self.assertIn('mˈœʁʤ.', phonemes)
        self.assertNotIn('ʒˈi', phonemes)

    def test_the_twin_says_the_account_lexicon_posed_for_its_thread(self):
        """Le pipeline est partagé, les lignes d'un compte changent à chaque demande : elles sont
        posées pour le fil qui synthétise (`use`), et seulement pour lui."""
        import threading
        try:
            from misaki.espeak import EspeakG2P
        except Exception:
            self.skipTest('misaki absent de ce venv')
        from wama.common.backends.kokoro_backend import LexiconG2P
        g2p = LexiconG2P(EspeakG2P(language='fr-fr'), 'fr')
        g2p.use({'git': {'spelling': 'jite'}})
        self.assertNotIn('ɡˈit', g2p('Un git.')[0])
        other = []
        thread = threading.Thread(target=lambda: other.append(g2p('Un git.')[0]))
        thread.start()
        thread.join()
        self.assertIn('ɡˈit', other[0], "un autre fil garde le lexique système")


@skipUnless(Tokenizer is not None, 'kokoro_onnx absent de ce venv')
class VoicePausesAreSilencesBetweenSegmentsTest(SimpleTestCase):
    """Le RÉGLAGE des pauses (2026-10-18). Notre modèle ne rend pas la durée de ses phonèmes
    (`has_timings` faux) : `Kokoro.create(sentence_pause=…)` n'allonge AUCUNE pause à l'intérieur
    d'une réplique (mesuré : 3,58 s de son pour 0, 0,25 et 0,8 s). Chaque segment est donc dit
    et le silence demandé posé entre eux — par le contrat COMMUN des moteurs depuis le 18/10
    (`TTSBackend.synthesize`, la porte qu'emprunte le service). Aucun poids : le modèle est un
    double qui rend une seconde de « son » par appel."""

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
        path = backend.synthesize(text=self.TEXT, language='fr', options=options)
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

    def test_the_engine_itself_no_longer_cuts(self):
        """Contre-épreuve : appelé DIRECTEMENT, le moteur dit le texte d'un trait — la découpe
        vit au contrat, une seule fois pour tous les moteurs."""
        import numpy as np
        from unittest import mock
        from wama.common.backends.kokoro_onnx_backend import KokoroOnnxBackend
        backend = KokoroOnnxBackend()
        backend._kokoro = mock.Mock(tokenizer=Tokenizer())
        backend._kokoro.create.side_effect = lambda *a, **k: (np.ones(self.RATE, np.float32), self.RATE)
        import os
        os.unlink(backend.process(self.TEXT, language='fr', options={'sentence_pause': 0.5}))
        self.assertEqual(1, backend._kokoro.create.call_count)
