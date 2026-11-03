"""The name of a card of the queue comes from what names its INPUT (2026-11-03).

Measured on a batch of 12 covers without a prompt: all named `generation_aleatoire_<id>.wav`, while
each carried its song. The same rule as the Input face of the card (`apps.py`): the work file, then
its URL, then the prompt; « random » only when nothing names the card.
"""
from django.test import SimpleTestCase

from wama.composer.models import ComposerGeneration
from wama.composer.views import _batch_item_extra


def _name(**fields):
    return _batch_item_extra(ComposerGeneration(id=7, **fields))['output_filename']


class OutputNameTest(SimpleTestCase):

    def test_a_cover_takes_the_name_of_its_song(self):
        self.assertEqual('01_-_Al_Dunya_7.wav', _name(melody_reference='users/1/composer/input/01_-_Al_Dunya.mp3'))

    def test_the_song_wins_over_the_prompt(self):
        self.assertEqual('Fall_7.wav', _name(melody_reference='users/1/input/Fall.mp3', prompt='folk nu-metal'))

    def test_a_score_names_its_card_too(self):
        self.assertEqual('theme_7.wav', _name(reference_score='users/1/input/theme.abc'))

    def test_an_url_names_a_song_that_has_not_arrived_yet(self):
        self.assertEqual('song_7.wav', _name(source_url='https://example.org/a/song.mp3?x=1'))

    def test_without_an_input_the_prompt_names_it(self):
        self.assertEqual('upbeat_jazz_7.wav', _name(prompt='upbeat jazz'))

    def test_a_truly_random_generation_says_so(self):
        self.assertEqual('generation_aleatoire_7.wav', _name())
