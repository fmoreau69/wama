"""The LANGUAGE of a text — `common/utils/text_language` (2026-10-05, first consumer: the lyrics of
a song, which are never translated and must be in a language the model sings)."""
from django.test import SimpleTestCase

from wama.common.utils.text_language import detect_text_language


class TheLanguageOfATextTest(SimpleTestCase):

    def test_lyrics_say_their_language_once_the_section_tags_are_put_aside(self):
        self.assertEqual('fr', detect_text_language(
            "[Verse]\nSous la pluie je marche seul\n[Chorus]\nEt je chante pour toi ce soir"))
        self.assertEqual('en', detect_text_language(
            "[Verse]\nWalking in the rain alone\n[Chorus]\nAnd I sing for you tonight"))

    def test_an_unsure_verdict_is_no_verdict(self):
        # Measured: « la la la » with a tag came out as Spanish at 0.71 — worse than no opinion.
        self.assertEqual('', detect_text_language("[Verse]\nla la la la la la la la"))
        self.assertEqual('', detect_text_language('[Chorus]\noh oh'))
        self.assertEqual('', detect_text_language(''))
