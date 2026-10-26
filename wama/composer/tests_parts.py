"""The composer's optional process `parts` (2026-10-16): the RENDERED song → its full score, one
part per instrument (task `audio-to-midi`, MuScriptor), written in ABC by the common notation
(`common/utils/midi_score.py`) and read on the score page under the melody.

What each test holds:
  * the process only runs when the card asks for it (`extract_parts`) AND a model of the task is
    installed ; it is a BRANCH of the render, beside the output (2026-10-26), and reads the
    render's audio — a new output format does not stale it ;
  * its model is not the card's: chosen on the card (`parts_model`, 2026-10-19) or drawn by task
    under « auto », asked from the route, released at once, named on its execution line ;
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
#: A second model of the task, CHOSEN on the card (`parts_model`) — the draw never returns it.
OTHER_TRANSCRIBER = 'huggingface:org/other-transcriber'


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
        self.draws, self.asked = [], []

    def _draw(self, source=None, requested=None, fallback=None, task=None, **domain):
        """The common selector's draw (`select_model_id`), stood in BELOW the composer's choice
        (`model_choice.parts_extractor`), which these tests hold : the installed model of the task."""
        self.draws.append({'task': task, **domain})
        return TRANSCRIBER if (self.installed and task == 'audio-to-midi') else fallback

    def _cover(self) -> str:
        """An audio of the song to cover (`melody_reference`) : the INPUT the full score reads."""
        rel = 'users/1/temp/cover.wav'
        (Path(self.tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
        (Path(self.tmp) / rel).write_bytes(b'RIFF' + b'\0' * 64)
        return rel

    def _run(self, gen=None, **fields):
        if gen is None:
            gen = ComposerGeneration.objects.create(user=self.user, prompt='pop song',
                                                    model=PLAIN_MODEL, status='RUNNING', **fields)
        engines = {**ENGINES, TRANSCRIBER: _Transcriber, OTHER_TRANSCRIBER: _Transcriber}
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.common.backends.manager.backend_for_key',
                           side_effect=lambda key: engines.get(key)), \
                mock.patch('wama.model_manager.services.select_model_id', side_effect=self._draw), \
                mock.patch('wama.common.utils.model_readiness.ensure_installed',
                           side_effect=lambda key, **kw: self.asked.append(key) or True), \
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

    def test_the_full_score_reads_the_input_audio_when_the_card_asks(self):
        """2026-10-26, Fabien : « la partition devrait refléter cet audio d'entrée » — the full
        score describes the SAME audio as the reduced one : the cover, not the song produced."""
        from django.conf import settings
        cover = self._cover()
        gen = self._run(extract_parts=True, melody_reference=cover)
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual(JOB_SUCCESS, self._states(gen)['parts'])
        self.assertEqual(str(Path(settings.MEDIA_ROOT) / cover),
                         str(Path(_Transcriber.calls[0]['audio_path'])), 'the cover is read')
        self.assertIn(f'/score{gen.pk}_', gen.parts_score.name, 'named by its nature : a score')
        written = (Path(self.tmp) / gen.parts_score.name).read_text(encoding='utf-8')
        self.assertIn('name="Voix"', written)
        self.assertIn('name="Basse électrique"', written)
        from wama.composer.function_specs import PIPELINE
        self.assertEqual([], list(PIPELINE.spec('parts').depends_on), 'an INPUT reading')

    def test_without_a_cover_or_with_an_imported_score_there_is_nothing_to_read(self):
        gen = self._run(extract_parts=True)
        self.assertNotIn('parts', self._states(gen), 'no input audio')
        self.assertEqual([], _Transcriber.calls)
        from wama.composer.function_specs import PIPELINE
        imported = ComposerGeneration(melody_reference=self._cover(), reference_score='x.abc',
                                      extract_parts=True)
        self.assertFalse(PIPELINE.spec('parts').applies(imported, PLAIN_MODEL),
                         'an IMPORTED score is the input itself')

    def test_its_model_is_drawn_by_task_released_and_named_on_its_line(self):
        gen = self._run(extract_parts=True, melody_reference=self._cover())
        self.assertEqual((1, 1), (_Transcriber.built, _Transcriber.unloaded))
        line = process_runs.line(gen, 'parts')
        self.assertEqual((gen.parts_score.name, 'composer.parts', TRANSCRIBER),
                         (line.output_ref, line.process_key, line.model_key))

    def test_the_model_chosen_on_the_card_writes_the_full_score(self):
        """2026-10-19 : several models can write this process ; the card names one
        (`parts_model`). It is not drawn, it is asked from the ROUTE (absent, installed while the
        task waits), loaded and named on the line."""
        gen = self._run(extract_parts=True, parts_model=OTHER_TRANSCRIBER,
                        melody_reference=self._cover())
        self.assertEqual(JOB_SUCCESS, self._states(gen)['parts'], gen.error_message)
        self.assertEqual(OTHER_TRANSCRIBER, process_runs.line(gen, 'parts').model_key)
        self.assertEqual('org/other-transcriber', _Transcriber.calls[0]['model_id'])
        self.assertIn(OTHER_TRANSCRIBER, self.asked)
        self.assertEqual([], [d for d in self.draws if d['task'] == 'audio-to-midi'])

    def test_under_auto_the_draw_is_made_for_the_card(self):
        """« auto » : the common selector draws among the task's models FOR this card — its
        account and its quality cursor, the ones its select's forecast reads."""
        gen = self._run(extract_parts=True, quality_intent=10, melody_reference=self._cover())
        self.assertEqual(TRANSCRIBER, process_runs.line(gen, 'parts').model_key)
        (draw,) = [d for d in self.draws if d['task'] == 'audio-to-midi']
        self.assertEqual((10, self.user.pk), (draw.get('quality_intent'), draw['user'].pk))
        self.assertIn(TRANSCRIBER, self.asked)

    def test_without_the_toggle_nothing_is_transcribed(self):
        gen = self._run(melody_reference=self._cover())
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertNotIn('parts', self._states(gen))
        self.assertNotIn('rendered_parts', self._states(gen))
        self.assertEqual([], _Transcriber.calls)

    def test_without_a_model_of_the_task_the_process_does_not_take_place(self):
        self.installed = False
        gen = self._run(extract_parts=True, extract_rendered_parts=True,
                        melody_reference=self._cover())
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertNotIn('parts', self._states(gen))
        self.assertNotIn('rendered_parts', self._states(gen))
        self.assertEqual([], _Transcriber.calls)

    def test_turned_on_after_the_song_only_the_full_score_is_played(self):
        """The gesture of #849 (2026-10-19): a song rendered without the toggle, the toggle turned
        on, the card relaunched — the full score is written, the song is not rendered again."""
        gen = self._run(melody_reference=self._cover())
        self.assertNotIn('parts', self._states(gen))
        ComposerGeneration.objects.filter(pk=gen.pk).update(extract_parts=True, status='RUNNING')
        gen = self._run(ComposerGeneration.objects.get(pk=gen.pk))
        self.assertEqual(JOB_SUCCESS, self._states(gen)['parts'], gen.error_message)
        self.assertTrue(gen.parts_score)
        self.assertEqual(1, len(_PlainEngine.renders), 'the song is not rendered again')

    def test_the_score_of_the_render_reads_the_song_produced(self):
        """2026-10-26, Fabien : « on propose les deux, l'entrée et la sortie » — the score of the
        RENDER, a branch of it, written beside the input's full score, never in its place."""
        from wama.common.services.output_process import output_sources
        gen = self._run(extract_parts=True, extract_rendered_parts=True,
                        melody_reference=self._cover())
        self.assertEqual((JOB_SUCCESS, JOB_SUCCESS),
                         (self._states(gen)['parts'], self._states(gen)['rendered_parts']),
                         gen.error_message)
        read = {Path(call['audio_path']).name for call in _Transcriber.calls}
        self.assertIn(Path(output_sources(gen, 'audio_output')[0]).name, read,
                      "the render's audio, whatever the output did")
        self.assertIn('cover.wav', read, 'and the cover, for the input')
        self.assertIn(f'/render_score{gen.pk}_', gen.rendered_parts_score.name)
        self.assertNotEqual(gen.parts_score.name, gen.rendered_parts_score.name)

    def test_a_new_output_format_stales_the_output_never_the_score_of_the_render(self):
        """2026-10-26, Fabien : « je ne vois pas la logique d'avoir la partition complète après la
        sortie ». A BRANCH of the render : the output may be redone, its score stays."""
        from wama.composer.function_specs import PIPELINE
        gen = self._run(extract_rendered_parts=True)
        self.assertEqual(JOB_SUCCESS, self._states(gen)['rendered_parts'], gen.error_message)
        self.assertEqual(['render'], list(PIPELINE.spec('rendered_parts').depends_on))
        current = gen.output_format
        other = next(v for v in ('mp3', 'flac', 'wav', 'ogg') if v != current)
        ComposerGeneration.objects.filter(pk=gen.pk).update(output_format=other)
        gen = ComposerGeneration.objects.get(pk=gen.pk)
        stale = PIPELINE.refresh(gen)
        self.assertIn('output', stale, 'the output follows its format')
        self.assertNotIn('rendered_parts', stale, 'the score of the render does not depend on it')

    def test_a_failed_transcription_fails_its_line_and_releases_the_model(self):
        _Transcriber.error = RuntimeError('no beat decoded')
        gen = self._run(extract_parts=True, melody_reference=self._cover())
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
                                             'duration': '5', 'extract_parts': posted,
                                             'parts_model': OTHER_TRANSCRIBER})
                self.assertEqual(200, response.status_code, response.content[:300])
                gen = ComposerGeneration.objects.get(pk=response.json()['id'])
                self.assertIs(expected, gen.extract_parts)
                self.assertEqual(OTHER_TRANSCRIBER, gen.parts_model)

    def test_the_model_setting_follows_its_process(self):
        """Its select : the catalogue models of the task the glue draws in, « auto » first ; it
        serves the two full-score processes (the input's, the render's — 2026-10-26) and stales
        them alone ; no `show_if`, which names a single toggle."""
        from wama.composer.function_specs import PIPELINE
        from wama.composer.params import PARAMS
        from wama.composer.utils.model_choice import PARTS_EXTRACTION_TASK
        (param,) = [p for p in PARAMS if p.name == 'parts_model']
        self.assertEqual(('catalog', {'task': PARTS_EXTRACTION_TASK}, True, None),
                         (param.options_source, param.options_query, param.options_auto,
                          param.show_if))
        others = [s.key for s in PIPELINE.specs if 'parts_model' in PIPELINE.watched_of(s)]
        self.assertEqual(['parts', 'rendered_parts'], others)
        self.assertEqual('auto', ComposerGeneration().parts_model)

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


class TheCoverIsTheInputTest(TestCase):
    """2026-10-26, Fabien on #880 : « si on fournit un audio cover en entrée, il devrait être en
    preview d'entrée » — the Input face was EMPTY (a cover has no prompt, nothing named the file).
    The common rule of the preview : the WORK port first, the prompt otherwise."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = get_user_model().objects.create_user('composer_cover_input', password='x')

    def _input(self, gen):
        """The Input face. The composer's WORK ports come from the models of the CATALOGUE (empty
        in the test base) : set to what the live catalogue gives (measured 2026-10-26 : group
        `travail`, natures audio and score) — what is held here is which FILE is the input."""
        from django.test import RequestFactory
        from wama.common.utils import preview_utils
        with mock.patch.object(preview_utils, '_input_port_group', return_value='travail'), \
                mock.patch.object(preview_utils, '_work_natures', return_value={'audio', 'score'}):
            return preview_utils._input_preview(
                'composer', gen, RequestFactory().get('/', HTTP_HOST='localhost')) or {}

    def test_the_cover_audio_is_the_input_face_the_prompt_otherwise(self):
        rel = 'users/1/temp/cover.mp3'
        (Path(self.tmp) / rel).parent.mkdir(parents=True)
        (Path(self.tmp) / rel).write_bytes(b'ID3' + b'\0' * 64)
        cover = ComposerGeneration.objects.create(user=self.user, prompt='', melody_reference=rel)
        face = self._input(cover)
        self.assertEqual(('cover.mp3', 'audio/mpeg'), (face.get('name'), face.get('mime_type')))
        plain = ComposerGeneration.objects.create(user=self.user, prompt='pop song')
        self.assertEqual('pop song', self._input(plain).get('content'), 'no work file : the prompt')
