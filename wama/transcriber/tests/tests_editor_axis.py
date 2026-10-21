"""La page de correction sur le TRANSPORT COMMUN, puis en SURFACE déclarée (ROUTE §F3b).

2026-10-20 : le transport écrit dans `edit.js` (échelle J/K/L recopiée, lecture arrière par
minuterie, sauts, Espace, lecture du temps) passe par l'axe commun. 2026-10-21 (décisions de
Fabien) : la page entière devient la surface `transcriber.correct` — onde fenêtrée et couches,
bande de qualité, minimap, outil Bornes et modes d'écriture sont des OPTIONS du transport commun
(`wama-transport.js`), la liste des segments une brique universelle, le titre, la date et les noms
des RÉGLAGES de la card. Ces gardes empêchent qu'une seconde version d'un geste revienne ; le
COMPORTEMENT est attesté dans le navigateur par `transcriber.editor_parity` (66 gestes, 66/66 sur
l'ancienne page puis sur la surface).
"""
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase

BASE = Path(settings.BASE_DIR)
APP = BASE / 'wama' / 'transcriber'
COMMON_JS = BASE / 'wama' / 'common' / 'static' / 'common' / 'js'
TRANSPORT = COMMON_JS / 'wama-transport.js'
SERVED = BASE / 'staticfiles'


def _read(path):
    return path.read_text(encoding='utf-8')


class CorrectionIsADeclaredSurfaceTest(SimpleTestCase):

    def test_the_page_written_by_hand_is_gone(self):
        for gone in (APP / 'static' / 'transcriber' / 'js' / 'edit.js',
                     APP / 'templates' / 'transcriber' / 'edit.html',
                     SERVED / 'transcriber' / 'js' / 'edit.js'):
            self.assertFalse(gone.exists(), f'{gone} : the page is a declared surface now')

    def test_the_surface_composes_universal_bricks_with_the_transport_options(self):
        from wama.common.surfaces import surface
        found = surface('transcriber', 'correct')
        self.assertIsNotNone(found)
        bricks = {s.brick: s.options for s in found.slots}
        self.assertEqual({'segment_list', 'media_transport', 'surface_actions', 'item_settings',
                          'speaker_names'}, set(bricks))
        transport = bricks['media_transport']
        for option in ('window', 'segments', 'quality', 'minimap', 'goto', 'zoom', 'writing'):
            self.assertTrue(transport.get(option), option)
        self.assertEqual('retime', transport['boundaries'])
        self.assertEqual('steps', transport['speed'])
        self.assertTrue(found.autosave)
        self.assertEqual('Terminer la correction', found.finish)
        self.assertEqual(('title', 'meeting_date', 'speaker_map'), found.settings)
        self.assertEqual({'retime', 'write_cursor', 'write_results', 'suggest_speakers'}, set(found.routes))

    def test_one_transport_drives_the_common_axis_and_player(self):
        js = _read(TRANSPORT)
        self.assertIn('WamaShuttle.create(', js)
        self.assertIn('axis.bindKeys(', js, 'Space, arrows and J/K/L come from the axis keyboard')
        for gone, why in (('const SHUTTLE', 'the J/K/L ladder is the brick default'),
                          ('reverseTimer', 'backward play is the axis, silent'),
                          ('parseTimecode', 'times are read by WamaAxis.parseTime'),
                          ('.currentTime', 'views read the axis time, not the <audio>'),
                          ('.playbackRate', 'the speed is the axis speed'),
                          ('.preload', 'the common player asks for the metadata itself')):
            self.assertNotIn(gone, js, why)
        # The medium plays and seeks through the common player — its rules (exclusive playback, a
        # position set again once seekable) are never redone in the transport.
        self.assertIn('play: function () { return Player.play(cfg.playerId); }', js)
        self.assertIn('seek: function (t) { Player.seek(cfg.playerId, t, false); }', js)

    def test_the_parity_is_measured_by_a_scenario_on_the_surface(self):
        from wama.common.services import nightly_tests, ui_smoke_editor
        self.assertIn('transcriber.editor_parity', {s.id for s in nightly_tests.REGISTRY})
        self.assertEqual('surface', ui_smoke_editor.FORM)

    def test_the_served_copies_are_the_sources(self):
        surfaces = COMMON_JS / 'surfaces'
        pairs = [(COMMON_JS / name, SERVED / 'common' / 'js' / name)
                 for name in ('wama-axis.js', 'wama-transport.js', 'wama-segments.js', 'wama-params.js')]
        pairs += [(surfaces / name, SERVED / 'common' / 'js' / 'surfaces' / name)
                  for name in ('wama-surface.js', 'brick-media-transport.js', 'brick-segment-list.js',
                               'brick-item-settings.js', 'brick-speaker-names.js',
                               'brick-surface-actions.js')]
        css = BASE / 'wama' / 'common' / 'static' / 'common' / 'css' / 'wama-surface.css'
        pairs.append((css, SERVED / 'common' / 'css' / 'wama-surface.css'))
        for source, served in pairs:
            self.assertEqual(_read(source), _read(served), f'{served} is stale')


class CorrectionSurfaceEndToEndTest(TestCase):
    """What the surface writes, through the COMMON views — and what the app draws from it."""

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        from wama.transcriber.models import Transcript
        self.user = get_user_model().objects.create_user('correction_surface_owner', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)
        self.item = Transcript.objects.create(
            user=self.user, audio='users/0/transcriber/input/fictif.wav', status='SUCCESS',
            segments_json=[{'start_time': 0, 'end_time': 1, 'text': 'bonjour', 'speaker_id': '0'}])
        self.base = f'/common/surface/transcriber/correct/{self.item.pk}/'

    def test_the_old_address_leads_to_the_surface(self):
        answer = self.client.get(f'/transcriber/edit/{self.item.pk}/')
        self.assertEqual(302, answer.status_code)
        self.assertEqual(self.base, answer['Location'])

    def test_the_page_opens_on_the_asr_output_and_its_settings(self):
        data = self.client.get(self.base + 'data/').json()
        self.assertEqual('bonjour', data['value'][0]['text'])
        self.assertEqual('SPEAKER_00', data['value'][0]['speaker_id'], 'speakers in canonical form')
        self.assertEqual('bonjour', data['reads']['latest'][0]['text'], 'the ASR output, read beside')
        self.assertEqual({'title', 'meeting_date', 'speaker_map'},
                         {p['name'] for p in data['settings']['schema']})

    def test_finishing_marks_the_correction_done_and_rebuilds_the_rows(self):
        token = self.client.get(self.base + 'data/').json()['token']
        value = [{'start_time': 0, 'end_time': 1, 'text': 'bonjour à tous', 'speaker_id': 'SPEAKER_00'}]
        draft = self.client.post(self.base + 'save/', json.dumps({'value': value, 'base': token}),
                                 content_type='application/json').json()
        self.item.refresh_from_db()
        self.assertEqual('draft', self.item.correction_status)
        self.assertEqual('bonjour à tous', self.item.text)
        done = self.client.post(self.base + 'save/',
                                json.dumps({'value': value, 'base': draft['token'], 'finished': True}),
                                content_type='application/json').json()
        self.assertTrue(done['finished'])
        self.item.refresh_from_db()
        self.assertEqual('done', self.item.correction_status)
        self.assertEqual(['bonjour à tous'], [s.text for s in self.item.segments.order_by('order')])

    def test_title_date_and_names_go_through_the_common_settings_route(self):
        answer = self.client.post(f'/transcriber/settings/{self.item.pk}/', json.dumps({
            'title': 'x' * 400, 'meeting_date': '2026-10-21', 'speaker_map': {'0': 'Alice', '1': ' '},
        }), content_type='application/json')
        self.assertEqual(200, answer.status_code, answer.content[:200])
        self.item.refresh_from_db()
        self.assertEqual(300, len(self.item.title), 'cut to its column, never a 500')
        self.assertEqual('2026-10-21', self.item.meeting_date.isoformat())
        self.assertEqual({'SPEAKER_00': 'Alice'}, self.item.speaker_map, 'canonical keys, empty names out')
        self.client.post(f'/transcriber/settings/{self.item.pk}/',
                         json.dumps({'meeting_date': '', 'title': ''}), content_type='application/json')
        self.item.refresh_from_db()
        self.assertIsNone(self.item.meeting_date, 'an empty date clears it')
        self.assertEqual('', self.item.title, 'an empty title is a value')

    def test_the_card_pencil_opens_the_surface_and_says_draft_or_done(self):
        from wama.common.templatetags.wama_actions import surface_button
        self.assertEqual('none', surface_button('transcriber', 'correct', self.item)['state'])
        for status, suffix in (('draft', 'brouillon en cours'), ('done', 'corrigé')):
            self.item.correction_status = status
            button = surface_button('transcriber', 'correct', self.item)
            self.assertEqual((True, status, self.base), (button['ok'], button['state'], button['url']))
            self.assertTrue(button['title'].endswith(suffix), button['title'])
        self.item.status = 'RUNNING'
        refused = surface_button('transcriber', 'correct', self.item)
        self.assertFalse(refused['ok'])
        self.assertIn('transcription réussie', refused['title'])

    def test_the_batch_route_never_writes_the_document_settings(self):
        from wama.transcriber.views import ITEM_ONLY_SETTINGS, SETTINGS_FIELDS
        self.assertFalse(set(ITEM_ONLY_SETTINGS) & set(SETTINGS_FIELDS))
