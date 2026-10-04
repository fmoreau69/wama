"""The common « Sortie » process brick (`output_process`) — what its glue REMOVES, and what it
never touches.

When the engine of a card plays again, the renders of the time before are replaced. That
replacement follows the two rules of `queue_duplication.safe_delete_file`, here for a path as for
a file field : the file lives in the HOME of the card's app, and no other card designates it.
Until 2026-10-04 the brick held the second rule only — a render that lived outside the app's home
would have been deleted.

The chaining (format changed → output alone, lost original → engine again, failure → nothing
left behind) is held by the tests of each app ; this file holds the rule the apps cannot see.
"""
import os
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.services import output_process
from wama.common.utils.media_paths import app_media_dir
from wama.synthesizer.models import VoiceSynthesis

User = get_user_model()


class WhatAReplayedEngineRemovesTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('output_process_owner', password='x')
        self.home = app_media_dir('synthesizer', self.user.id, 'output')

    def _file(self, relative, content=b'audio'):
        path = Path(settings.MEDIA_ROOT) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self.addCleanup(lambda: path.exists() and path.unlink())
        return relative

    def _card(self, audio, kept=()):
        return VoiceSynthesis.objects.create(user=self.user, status='SUCCESS', audio_output=audio,
                                             native_outputs=list(kept))

    def _exists(self, relative):
        return (Path(settings.MEDIA_ROOT) / relative).exists()

    def test_the_own_render_and_its_kept_original_are_removed(self):
        render = self._file(f'{self.home}/voice_1.mp3')
        original = self._file(f'{self.home}/voice_1.native.wav')
        output_process.drop_previous_outputs(self._card(render, [original]), 'audio_output')
        self.assertEqual((False, False), (self._exists(render), self._exists(original)))

    def test_a_file_outside_the_home_of_the_app_is_never_removed(self):
        """The rule the brick lacked : a card that only DESIGNATES a file (the user's temp, the
        media library) does not own it."""
        elsewhere = self._file(f'users/{self.user.id}/temp/voice_elsewhere.wav')
        kept_elsewhere = self._file(f'users/{self.user.id}/temp/voice_elsewhere.native.wav')
        output_process.drop_previous_outputs(self._card(elsewhere, [kept_elsewhere]),
                                             'audio_output')
        self.assertEqual((True, True), (self._exists(elsewhere), self._exists(kept_elsewhere)))

    def test_a_file_another_card_still_designates_is_kept(self):
        shared = self._file(f'{self.home}/voice_shared.wav')
        card = self._card(shared)
        self._card(shared)                              # a duplicate shares its file
        output_process.drop_previous_outputs(card, 'audio_output')
        self.assertTrue(self._exists(shared))

    def test_what_the_engine_just_wrote_is_kept(self):
        render = self._file(f'{self.home}/voice_same_name.wav')
        output_process.drop_previous_outputs(
            self._card(render), 'audio_output',
            keep=[os.path.join(settings.MEDIA_ROOT, render)])
        self.assertTrue(self._exists(render))

    def test_in_doubt_nothing_is_removed(self):
        """A card without an owner has no home : the question « is it mine ? » has no yes."""
        orphan = SimpleNamespace(pk=1, user_id=None, _meta=VoiceSynthesis._meta)
        render = self._file(f'{self.home}/voice_orphan.wav')
        self.assertFalse(output_process._replaceable(
            orphan, os.path.join(settings.MEDIA_ROOT, render), 'audio_output'))


class TheReturnOfAnEngineGlueTest(TestCase):

    def test_the_fingerprint_replaces_the_output_reference_and_the_kept_originals_are_cleared(self):
        folder = Path(settings.MEDIA_ROOT) / 'output_process_tests'
        folder.mkdir(parents=True, exist_ok=True)
        first, second = folder / 'a.png', folder / 'b.png'
        first.write_bytes(b'one')
        second.write_bytes(b'two')
        self.addCleanup(lambda: [p.unlink() for p in (first, second) if p.exists()])
        result = output_process.generated([str(first), str(second)], fields={'x': 1},
                                          output_ref='a.png', label='two images')
        self.assertNotIn('output_ref', result,
                         'the output process MOVES the original : a path would be lost')
        self.assertEqual({'x': 1, 'native_outputs': []}, result['fields'])
        self.assertEqual('two images', result['label'])
        same = output_process.files_fingerprint([str(first), str(second)])
        self.assertEqual(same, result['output_fingerprint'])
        second.write_bytes(b'changed')
        self.assertNotEqual(same, output_process.files_fingerprint([str(first), str(second)]))

    def test_a_lost_original_forgets_the_line_of_the_engine_and_a_present_one_does_not(self):
        from wama.common.services import process_runs
        user = User.objects.create_user('output_process_lost', password='x')
        home = app_media_dir('synthesizer', user.id, 'output')
        path = Path(settings.MEDIA_ROOT) / home / 'voice_lost.wav'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'audio')
        card = VoiceSynthesis.objects.create(user=user, status='SUCCESS',
                                             audio_output=f'{home}/voice_lost.wav')
        process_runs.start(card, 'generate')
        process_runs.succeed(card, 'generate')
        self.assertFalse(output_process.forget_lost_generation(card, 'audio_output', 'generate'))
        self.assertIsNotNone(process_runs.line(card, 'generate'))
        path.unlink()
        self.assertTrue(output_process.forget_lost_generation(card, 'audio_output', 'generate'))
        self.assertIsNone(process_runs.line(card, 'generate'))
