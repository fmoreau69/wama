"""Partitions en entrée (2026-10-01) — une NATURE de plus, et la card qui suit d'elle-même.

Demande de Fabien : « transmettre un fichier MIDI tout aussi bien qu'une partition […] la card
d'entrée se met à jour toute seule selon les capacités déclarées des moteurs ». Rien n'est écrit
pour le composer : la nature `score` est déclarée une fois (`app_registry`, `natures`), le jeton
`reference_score` dit le rôle (`app_modes.INPUT_TYPES`), YuE2 le déclare (capacité au catalogue),
et la card en dérive son onglet — parce que le select du composer DÉCLARE que ses modèles sont
ceux de l'app (`Param.options_ports`).
"""
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from wama.model_manager.models import AIModel


def _model(key, *, task, required=(), optional=(), model_type='music'):
    return AIModel.objects.create(
        model_key=key, name=key.split(':')[-1], model_type=model_type, source=key.split(':')[0],
        vram_gb=1.0, is_available=True, is_downloaded=True, is_proposed=False,
        capabilities={'task': task, 'inputs_required': list(required),
                      'inputs_optional': list(optional)})


class ScoreNatureTest(SimpleTestCase):

    def test_scores_and_midi_files_are_their_own_nature(self):
        from wama.common.app_registry import category_of_path
        for name in ('tune.abc', 'take.mid', 'take.MIDI', 'sheet.musicxml', 'sheet.mxl'):
            self.assertEqual('score', category_of_path(name), name)
        self.assertEqual('document', category_of_path('data.xml'),
                         'a bare .xml does not say it is a score')

    def test_a_score_port_accepts_the_score_extensions_without_any_app_declaration(self):
        from wama.common.app_registry import port_accept
        self.assertEqual('.abc,.mid,.midi,.musicxml,.mxl', port_accept('composer', ['score']))

    def test_the_media_library_has_a_score_nature(self):
        from wama.media_library.natures import ASSET_NATURES, resolve_asset_type
        self.assertEqual('score', ASSET_NATURES['score'].category)
        self.assertEqual('score', resolve_asset_type('score'), 'a category resolves to its nature')

    def test_the_reference_score_token_follows_the_nature(self):
        from wama.common.app_registry import normalize_types
        from wama.common.utils.app_modes import INPUT_TYPES
        token = INPUT_TYPES['reference_score']
        self.assertEqual(('score', 'reference', False), (token['accept'], token['port'], token['multi']))
        self.assertTrue(token['description'])
        self.assertEqual(['score'], normalize_types([token['accept']]))


class SelectModelsOpenPortsTest(TestCase):
    """`options_ports` : les modèles que le select PROPOSE ouvrent les ports de la card."""

    def setUp(self):
        _model('composer:musicgen-melody', task='text-to-music', required=['prompt'],
               optional=['reference_melody'])
        _model('huggingface:m-a-p/YuE2-3B', task='text-to-music', required=['prompt'],
               optional=['reference_score'])
        _model('huggingface:org/tts', task='text-to-speech', required=['prompt'],
               optional=['reference_voice'], model_type='speech')

    def test_a_model_of_another_source_opens_its_port_in_the_composer(self):
        from wama.common.app_registry import app_input_ports
        ports = [p['id'] for p in app_input_ports('composer')]
        self.assertEqual(['prompt', 'reference_melody', 'reference_score'], ports)

    def test_a_select_without_the_flag_opens_nothing(self):
        """Contre-épreuve : le select de VOIX de l'avatarizer propose des modèles TTS (une étape),
        pas ceux de l'app — leur voix de référence n'ouvre pas de port chez lui."""
        from wama.common.app_registry import app_input_ports
        self.assertNotIn('reference_voice', [p['id'] for p in app_input_ports('avatarizer')])

    def test_the_second_reference_port_gets_ids_of_its_own(self):
        from wama.common.templatetags.wama_actions import input_slots
        slots = {s['id']: s for s in input_slots('composer')}
        self.assertFalse(slots['reference_melody']['secondary_reference'])
        self.assertTrue(slots['reference_score']['secondary_reference'])
        self.assertEqual('score', slots['reference_score']['library_type'])

    def test_the_card_renders_both_reference_tabs_without_a_duplicate_id(self):
        html = render_to_string('common/_new_item_card_v4.html', {
            'app_id': 'composer', 'card_id': 'c', 'reference_input_id': 'melodyInput'})
        self.assertEqual(1, html.count('id="melodyInput"'))
        self.assertEqual(1, html.count('id="c-reference_score-input"'))
        self.assertIn('accept=".abc,.mid,.midi,.musicxml,.mxl"', html)


class ScoreReachesTheModelTest(TestCase):
    """De la card au moteur : la partition n'est jamais IGNORÉE — suivie, ou refusée en le disant."""

    def setUp(self):
        import os
        from django.conf import settings
        from django.contrib.auth import get_user_model
        _model('composer:musicgen-small', task='text-to-music', required=['prompt'])
        _model('huggingface:m-a-p/YuE2-3B', task='text-to-music', required=['prompt'],
               optional=['reference_score'])
        self.user = get_user_model().objects.create_user('score_owner', password='x')
        self.rel = f'users/{self.user.id}/temp/tune.abc'
        path = os.path.join(settings.MEDIA_ROOT, self.rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('X:1\nK:C\nCDEF|\n')

    def _compose(self, model):
        from unittest import mock
        from wama.tool_api import compose_music
        with mock.patch('wama.composer.tasks.compose_task.apply_async') as dispatch:
            dispatch.return_value.id = 'no-task'
            return compose_music(self.user, 'a calm song', model=model, reference_score=self.rel)

    def test_the_tool_rejects_a_score_for_a_model_without_it(self):
        from wama.composer.models import ComposerGeneration
        result = self._compose('composer:musicgen-small')
        self.assertIn('error', result)
        self.assertFalse(ComposerGeneration.objects.filter(user=self.user).exists(),
                         'refused BEFORE anything is created')

    def test_the_tool_points_the_score_for_a_model_that_follows_it(self):
        from wama.composer.models import ComposerGeneration
        result = self._compose('huggingface:m-a-p/YuE2-3B')
        gen = ComposerGeneration.objects.get(pk=result['generation_id'])
        self.assertEqual(self.rel, gen.reference_score.name, 'a designated file is POINTED, not copied')

    def test_auto_draws_among_the_models_that_follow_the_score(self):
        from unittest import mock
        from wama.composer.models import ComposerGeneration
        from wama.composer.utils.auto_model import resolve_auto_model
        gen = ComposerGeneration.objects.create(user=self.user, prompt='x', model='auto:text-to-music',
                                                reference_score=self.rel)
        seen = {}

        def fake_select(source, **kw):
            seen.update(kw)
            return 'huggingface:m-a-p/YuE2-3B'

        with mock.patch('wama.model_manager.services.select_model_id', fake_select):
            resolve_auto_model(gen)
        self.assertIn('reference_score', seen.get('consumes') or [])

    def test_the_studio_node_port_is_read_by_the_tool(self):
        from wama.studio.services.generic_runner import unwired_ports
        self.assertNotIn('reference_score', unwired_ports('composer'))


class EnginesFollowOrRefuseTheScoreTest(SimpleTestCase):

    def test_an_engine_without_scores_rejects_one_in_words(self):
        from wama.common.backends.music_generation_base import MusicGenerationBackend
        with self.assertRaisesMessage(ValueError, 'ne suit pas de partition'):
            MusicGenerationBackend.refuse_score('/x/tune.abc', 'AudioCraft')
        MusicGenerationBackend.refuse_score(None, 'AudioCraft')     # rien fourni : rien à dire

    def test_yue2_reads_an_abc_score_and_rejects_musicxml_in_words(self):
        import tempfile
        from pathlib import Path
        from wama.common.backends.yue2_3b_backend import YuE2Backend
        with tempfile.TemporaryDirectory() as tmp:
            abc = Path(tmp, 'tune.abc')
            abc.write_text('X:1\nK:C\nCDEF|\n', encoding='utf-8')
            self.assertTrue(YuE2Backend._score_abc(str(abc)).startswith('X:1'))
            xml = Path(tmp, 'tune.musicxml')
            xml.write_text('<score-partwise/>', encoding='utf-8')
            with self.assertRaisesMessage(ValueError, 'MusicXML'):
                YuE2Backend._score_abc(str(xml))

    @staticmethod
    def _midi(path, notes, *, drum=None, tempo_bpm=90, meter=(3, 4), key='G'):
        """Un petit MIDI : `notes` = [(début, durée, hauteur)] en noires ; 480 ticks par noire."""
        import mido
        mid = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(tempo_bpm), time=0))
        track.append(mido.MetaMessage('time_signature', numerator=meter[0], denominator=meter[1], time=0))
        track.append(mido.MetaMessage('key_signature', key=key, time=0))
        events = []
        for start, dur, pitch in notes:
            events += [(start * 480, 'note_on', pitch, 0), ((start + dur) * 480, 'note_off', pitch, 0)]
        if drum:
            events += [(0, 'note_on', drum, 9), (480, 'note_off', drum, 9)]
        now = 0
        for tick, kind, pitch, channel in sorted(events, key=lambda e: (e[0], e[1] == 'note_on')):
            track.append(mido.Message(kind, note=pitch, velocity=80, channel=channel, time=int(tick - now)))
            now = tick
        mid.save(path)

    def test_yue2_turns_a_midi_into_its_own_abc_dialect_through_the_engine_compiler(self):
        import tempfile
        from pathlib import Path
        from wama.common.backends.yue2_3b_backend import YuE2Backend
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp, 'tune.mid'))
            # Un accord (G4+B4+D5) à l'attaque, puis deux notes ; une note de batterie à écarter.
            self._midi(path, [(0, 1, 67), (0, 1, 71), (0, 1, 74), (1, 1, 72), (2, 1, 71)], drum=36)
            events = YuE2Backend._midi_events(path)
            self.assertEqual((90, 'G', [{'meter': '3/4'}]), (events['bpm'], events['key'], events['bars']))
            self.assertEqual([['0', '1', 74], ['1', '1', 72], ['2', '1', 71]], events['notes'],
                             'the chord is reduced to its TOP note, the drum is left out')
            abc = YuE2Backend._score_abc(path)
        self.assertIn('V: Ins', abc)
        self.assertIn('Q:1/4=90', abc)
        self.assertIn('K:G', abc)
