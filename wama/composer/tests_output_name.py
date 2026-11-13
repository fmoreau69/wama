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


class WorkTitleTest(SimpleTestCase):
    """The TITLE a score of the card carries (2026-11-13, Fabien : « the score carries the number
    of the card, #1516 — we would rather see the title of the song »). The same input as the name
    of the card, without its number ; a separated track adds its instrument."""

    def test_a_cover_is_titled_by_its_song(self):
        gen = ComposerGeneration(id=7, melody_reference='users/1/temp/Keep Hope_V02.mp3', prompt='folk')
        self.assertEqual('Keep Hope_V02', gen.work_title)

    def test_without_an_input_the_prompt_titles_it(self):
        self.assertEqual('upbeat jazz', ComposerGeneration(id=7, prompt='  upbeat\n jazz ').work_title)

    def test_a_track_carries_its_song_and_its_instrument_not_its_file(self):
        song = ComposerGeneration(id=7, melody_reference='users/1/temp/Keep Hope.mp3')
        track = ComposerGeneration(
            id=8, derived_from=song, derived_role='piano',
            melody_reference='users/1/composer/input/Keep Hope_piano_htdemucs_6s_7.wav')
        self.assertEqual('Keep Hope — Piano', track.work_title)
