"""WER / CER à vérité terrain (`services/text_metrics.py`) — comptes vérifiés à la main."""
from django.test import SimpleTestCase

from wama.common.services.text_metrics import (
    character_error_rate, comparable_words, word_error_rate,
)


class WordErrorRateTest(SimpleTestCase):

    def test_each_kind_of_error_is_counted_on_its_own(self):
        """chat→chien (substitution), « sur » absent (suppression), « rouge » en trop
        (insertion) : 3 erreurs sur 6 mots de référence."""
        r = word_error_rate('le chat dort sur le tapis', 'le chien dort le tapis rouge')
        self.assertEqual((1, 1, 1), (r.substitutions, r.deletions, r.insertions))
        self.assertEqual((6, 6), (r.reference_length, r.hypothesis_length))
        self.assertEqual(0.5, r.rate)
        self.assertEqual(3, r.errors)

    def test_case_and_punctuation_are_transcription_choices_not_errors(self):
        self.assertEqual(0.0, word_error_rate('Bonjour, ça va ?', 'bonjour ça va').rate)

    def test_an_apostrophe_is_a_separator_on_both_sides(self):
        self.assertEqual(0.0, word_error_rate("aujourd'hui", 'aujourd hui').rate)

    def test_a_hesitation_is_DATA_and_its_omission_counts(self):
        """Verbatim : « euh » dit et non transcrit est une suppression, pas un détail."""
        r = word_error_rate('oui euh je crois', 'oui je crois')
        self.assertEqual((0, 1, 0), (r.substitutions, r.deletions, r.insertions))
        self.assertEqual(0.25, r.rate)

    def test_an_empty_reference_gives_an_UNDEFINED_rate_never_zero(self):
        self.assertIsNone(word_error_rate('', 'du texte').rate)
        self.assertIsNone(word_error_rate('  ', '').rate)

    def test_an_empty_output_misses_everything(self):
        r = word_error_rate('trois mots ici', '')
        self.assertEqual((3, 1.0), (r.deletions, r.rate))

    def test_the_rate_can_exceed_one_when_the_output_adds_more_than_it_keeps(self):
        self.assertEqual(3.0, word_error_rate('oui', 'oui non non non').rate)

    def test_as_dict_carries_the_counts_and_the_total(self):
        d = word_error_rate('a b', 'a c').as_dict()
        self.assertEqual({'unit': 'word', 'rate': 0.5, 'substitutions': 1, 'deletions': 0,
                          'insertions': 0, 'reference_length': 2, 'hypothesis_length': 2,
                          'errors': 1}, d)


class CharacterErrorRateTest(SimpleTestCase):

    def test_a_nearly_right_word_costs_less_in_characters_than_in_words(self):
        wer = word_error_rate('les chats', 'les chat')
        cer = character_error_rate('les chats', 'les chat')
        self.assertEqual(0.5, wer.rate)
        self.assertEqual((1, 9), (cer.deletions, cer.reference_length))
        self.assertLess(cer.rate, wer.rate)


class OneTokenizerForEveryQualitySignalTest(SimpleTestCase):
    """Le découpage a été DÉPLACÉ de `divergence.py` : la divergence (M1) et le WER (M3) doivent
    découper le même texte de la même façon, sinon deux signaux se contrediraient à tort."""

    def test_divergence_reads_the_same_tokenizer(self):
        from wama.common.services import divergence
        self.assertIs(comparable_words, divergence.comparable_words)
        self.assertEqual(0.0, divergence.divergence_texte("aujourd'hui", 'aujourd hui'))

    def test_the_tokenizer_itself(self):
        self.assertEqual(['l', 'été', 'm', 'appelle'], comparable_words("L'été m’appelle !"))
