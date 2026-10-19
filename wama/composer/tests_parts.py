"""The composer's optional process `parts` (2026-10-16): the RENDERED song → its full score, one
part per instrument (task `audio-to-midi`, MuScriptor), written in ABC by the common notation
(`common/utils/midi_score.py`) and read on the score page under the melody.

What each test holds:
  * the process only runs when the card asks for it (`extract_parts`) AND a model of the task is
    installed ; it comes after the output, on the final song ;
  * its model is not the card's: drawn by task, released at once, named on its execution line ;
  * the MIDI is written as a score output of the card, never handed to the render ;
  * a failed transcription fails the card's line and releases the model.

No model, no GPU: the engines are stand-ins (the ones of `tests_pipeline`, plus a transcriber).
"""
import io
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from wama.common.models import JOB_FAILURE, JOB_SUCCESS
from wama.common.services import process_runs
from wama.composer import tasks
from wama.composer.models import ComposerGeneration
from wama.composer.tests_pipeline import ENGINES, PLAIN_MODEL, _PlainEngine
from wama.composer.tests_task import _celery_task

TRANSCRIBER = 'huggingface:MuScriptor/muscriptor-large'


def _two_parts_midi() -> bytes:
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    pm.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0))
    for name, pitch in (('voice', 67), ('electric bass', 40)):
        inst = pretty_midi.Instrument(program=0, name=name)
        inst.notes = [pretty_midi.Note(100, pitch, 0.0, 1.0)]
        pm.instruments.append(inst)
    buffer = io.BytesIO()
    pm.write(buffer)
    return buffer.getvalue()


class _Transcriber:
    """Stand-in of a MIDI-extraction backend (`MidiExtractionBackend`)."""
    built, unloaded, calls = 0, 0, []
    error = None

    def __init__(self):
        type(self).built += 1

    def unload(self):
        _Transcriber.unloaded += 1

    def extract_midi(self, **kwargs):
        _Transcriber.calls.append(kwargs)
        if _Transcriber.error:
            raise _Transcriber.error
        return _two_parts_midi()


class FullScoreTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = get_user_model().objects.create_user('composer_parts', password='x')
        _PlainEngine.renders = []
        _Transcriber.built, _Transcriber.unloaded, _Transcriber.calls, _Transcriber.error = 0, 0, [], None
        self.installed = True

    def _run(self, gen=None, **fields):
        if gen is None:
            gen = ComposerGeneration.objects.create(user=self.user, prompt='pop song',
                                                    model=PLAIN_MODEL, status='RUNNING', **fields)
        engines = {**ENGINES, TRANSCRIBER: _Transcriber}
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.common.backends.manager.backend_for_key',
                           side_effect=lambda key: engines.get(key)), \
                mock.patch('wama.composer.utils.model_choice.parts_extractor',
                           side_effect=lambda: TRANSCRIBER if self.installed else ''), \
                mock.patch('wama.composer.utils.model_choice.parts_extraction_available',
                           side_effect=lambda: self.installed), \
                mock.patch('wama.common.utils.audio_rhythm.beat_grid', return_value=None), \
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           side_effect=lambda app, field, text, **kw: text), \
                mock.patch('wama.common.utils.model_readiness.warn_if_weights_missing'), \
                mock.patch('wama.composer.utils.model_config.clamp_duration',
                           side_effect=lambda value, model_id=None: value), \
                mock.patch('wama.model_manager.services.eta_estimator.record_run'):
            tasks.compose_task.run.__func__(_celery_task(), gen.pk, None)
        return ComposerGeneration.objects.get(pk=gen.pk)

    def _states(self, gen):
        return {row.node_id: row.status for row in process_runs.lines(gen)}

    def test_the_full_score_is_written_after_the_song_when_the_card_asks(self):
        gen = self._run(extract_parts=True)
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual({'render': JOB_SUCCESS, 'output': JOB_SUCCESS, 'parts': JOB_SUCCESS}, self._states(gen))
        self.assertTrue(_Transcriber.calls[0]['audio_path'].replace('\\', '/')
                        .endswith(gen.audio_output.name), 'the transcription reads the FINAL song')
        self.assertIn(f'/score{gen.pk}_', gen.parts_score.name, 'named by its nature : a score')
        written = (Path(self.tmp) / gen.parts_score.name).read_text(encoding='utf-8')
        self.assertIn('name="Voix"', written)
        self.assertIn('name="Basse électrique"', written)
        self.assertEqual(1, len(_PlainEngine.renders), 'the song is rendered once, before')

    def test_its_model_is_drawn_by_task_released_and_named_on_its_line(self):
        gen = self._run(extract_parts=True)
        self.assertEqual((1, 1), (_Transcriber.built, _Transcriber.unloaded))
        line = process_runs.line(gen, 'parts')
        self.assertEqual((gen.parts_score.name, 'composer.parts', TRANSCRIBER),
                         (line.output_ref, line.process_key, line.model_key))

    def test_without_the_toggle_nothing_is_transcribed(self):
        gen = self._run()
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertNotIn('parts', self._states(gen))
        self.assertEqual([], _Transcriber.calls)

    def test_without_a_model_of_the_task_the_process_does_not_take_place(self):
        self.installed = False
        gen = self._run(extract_parts=True)
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertNotIn('parts', self._states(gen))
        self.assertEqual([], _Transcriber.calls)

    def test_turned_on_after_the_song_only_the_full_score_is_played(self):
        """The gesture of #849 (2026-10-19): a song rendered without the toggle, the toggle turned
        on, the card relaunched — the full score is written, the song is not rendered again."""
        gen = self._run()
        self.assertNotIn('parts', self._states(gen))
        ComposerGeneration.objects.filter(pk=gen.pk).update(extract_parts=True, status='RUNNING')
        gen = self._run(ComposerGeneration.objects.get(pk=gen.pk))
        self.assertEqual(JOB_SUCCESS, self._states(gen)['parts'], gen.error_message)
        self.assertTrue(gen.parts_score)
        self.assertEqual(1, len(_PlainEngine.renders), 'the song is not rendered again')

    def test_a_failed_transcription_fails_its_line_and_releases_the_model(self):
        _Transcriber.error = RuntimeError('no beat decoded')
        gen = self._run(extract_parts=True)
        self.assertEqual(JOB_FAILURE, self._states(gen)['parts'])
        self.assertEqual(JOB_SUCCESS, self._states(gen)['output'], 'the song itself is kept')
        self.assertEqual(1, _Transcriber.unloaded)
        self.assertFalse(gen.parts_score)


class TheToggleReachesTheCardTest(TestCase):
    """« Partition complète » set on, the card must carry it (2026-10-19, #849: set on, then seen
    back off — the panel's add-to-queue posted a hand list without it, and the ⚙ route dropped
    it). The ⚙ modal and the inspector are held by the common contract
    (`tests_item_settings_contract`, every writable setting); here the creation and the panel."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        self.user = get_user_model().objects.create_user('composer_parts_toggle', password='x')
        for role in (DEFAULT_APP_ACCESS.get('composer') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)

    def test_the_toggle_posted_at_creation_is_on_the_new_card(self):
        from django.urls import reverse
        for posted, expected in (('true', True), ('false', False)):
            with self.subTest(posted=posted):
                response = self.client.post(reverse('composer:generate'),
                                            {'prompt': 'a song', 'model': 'musicgen-small',
                                             'duration': '5', 'extract_parts': posted})
                self.assertEqual(200, response.status_code, response.content[:300])
                gen = ComposerGeneration.objects.get(pk=response.json()['id'])
                self.assertIs(expected, gen.extract_parts)

    def test_the_panel_posts_its_whole_host_not_a_hand_list(self):
        """Every panel setting travels with the deposit because the add-to-queue reads the panel
        HOST (`WamaApp.addToQueue` `paramsHostId`), which the template renders from the schema."""
        from django.conf import settings
        from wama.composer.params import PARAMS
        root = Path(settings.BASE_DIR) / 'wama' / 'composer'
        script = (root / 'static' / 'composer' / 'js' / 'index.js').read_text(encoding='utf-8')
        template = (root / 'templates' / 'composer' / 'index.html').read_text(encoding='utf-8')
        self.assertIn("paramsHostId: 'composerPanelHost'", script)
        self.assertIn('id="composerPanelHost"', template)
        self.assertNotIn('extraFields', script, 'a hand list of panel settings forgets the next one')
        panel = {p.name for p in PARAMS if 'panel' in (p.contexts or ())}
        self.assertIn('extract_parts', panel)
