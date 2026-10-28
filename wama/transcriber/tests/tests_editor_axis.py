"""La page de correction sur le TRANSPORT COMMUN, puis en SURFACE déclarée (ROUTE §F3b).

2026-10-20 : le transport écrit dans `edit.js` (échelle J/K/L recopiée, lecture arrière par
minuterie, sauts, Espace, lecture du temps) passe par l'axe commun. 2026-10-21 (décisions de
Fabien) : la page entière devient la surface `transcriber.correct` — la liste des segments une
brique universelle, le titre, la date et les noms des RÉGLAGES de la card. Le même jour, le TEMPS
est redécoupé en quatre niveaux : l'axe, le transport (ses commandes seules, `wama-transport.js`),
la ligne de temps (une vue : onde fenêtrée et couches, bande de qualité, minimap, zoom, outil
Bornes — `wama-timeline.js`) et l'écriture à la lecture (un outil, brique `playback_writing`).
Ces gardes empêchent qu'une seconde version d'un geste revienne, et que le transport reprenne ce
qui n'est pas du temps ; le COMPORTEMENT est attesté dans le navigateur par
`transcriber.editor_parity` (66 gestes, 66/66 avant puis après chaque étape).
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
TIMELINE = COMMON_JS / 'wama-timeline.js'
TRANSPORT_BRICK = COMMON_JS / 'surfaces' / 'brick-media-transport.js'
WRITING_BRICK = COMMON_JS / 'surfaces' / 'brick-playback-writing.js'
SERVED = BASE / 'staticfiles'


def _read(path):
    return path.read_text(encoding='utf-8')


class CorrectionIsADeclaredSurfaceTest(SimpleTestCase):

    def test_the_page_written_by_hand_is_gone(self):
        for gone in (APP / 'static' / 'transcriber' / 'js' / 'edit.js',
                     APP / 'templates' / 'transcriber' / 'edit.html',
                     SERVED / 'transcriber' / 'js' / 'edit.js'):
            self.assertFalse(gone.exists(), f'{gone} : the page is a declared surface now')

    def test_the_surface_composes_the_time_in_four_levels(self):
        from wama.common.surfaces import surface
        found = surface('transcriber', 'correct')
        self.assertIsNotNone(found)
        bricks = {s.brick: s.options for s in found.slots}
        self.assertEqual({'segment_list', 'media_timeline', 'media_transport', 'playback_writing',
                          'surface_actions', 'item_settings', 'speaker_names'}, set(bricks))
        timeline = bricks['media_timeline']
        for option in ('segments', 'quality', 'minimap', 'zoom'):
            self.assertTrue(timeline.get(option), option)
        self.assertEqual('retime', timeline['boundaries'])
        transport = bricks['media_transport']
        self.assertEqual({'role': 'audio', 'wave': False, 'goto': True, 'speed': 'steps'}, transport,
                         'the transport carries the commands of the time, nothing else')
        self.assertTrue(found.autosave)
        self.assertEqual('Terminer la correction', found.finish)
        # + the version listened to, kept on the card (`sources_setting`, 2026-10-22), read and
        # written with them without being said twice (`page_settings`, 2026-10-27).
        self.assertEqual(('title', 'meeting_date', 'speaker_map'), found.settings)
        self.assertEqual(found.settings + ('listened_sources',), found.page_settings())
        self.assertEqual({'retime', 'write_cursor', 'write_results', 'suggest_speakers'}, set(found.routes))

    def test_one_transport_drives_the_common_axis_and_player(self):
        js = _read(TRANSPORT)
        self.assertIn('WamaShuttle.create(', js)
        self.assertIn('axis.bindKeys(', js, 'Space, arrows and J/K/L come from the axis keyboard')
        for path in (TRANSPORT, TIMELINE, TRANSPORT_BRICK, WRITING_BRICK):
            code = _read(path)
            for gone, why in (('const SHUTTLE', 'the J/K/L ladder is the brick default'),
                              ('reverseTimer', 'backward play is the axis, silent'),
                              ('parseTimecode', 'times are read by WamaAxis.parseTime'),
                              ('.currentTime', 'views read the axis time, not the <audio>'),
                              ('.playbackRate', 'the speed is the axis speed'),
                              ('.preload', 'the common player asks for the metadata itself')):
                self.assertNotIn(gone, code, f'{path.name}: {why}')
        # The medium plays and seeks through the common player — its rules (exclusive playback, a
        # position set again once seekable) are never redone by the brick that attaches it.
        brick = _read(TRANSPORT_BRICK)
        self.assertIn('play: function () { return Player.play(playerId); }', brick)
        self.assertIn('seek: function (t) { Player.seek(playerId, t, false); }', brick)

    def test_the_transport_knows_no_view_no_medium_and_no_data(self):
        # Redécoupage du 2026-10-21 : le transport envoie des commandes à l'axe, rien d'autre. Un
        # « aller à » se DIT aux abonnés (`goto`) : la ligne de temps recentre, la liste choisit.
        js = _read(TRANSPORT)
        for gone, why in (('WamaSegments', 'segments are a view or a tool, never the transport'),
                          ('WamaAudioPlayer', 'the medium is attached by its brick, not the transport'),
                          ('WamaGestures', 'gestures on time are a view'),
                          ('canvas', 'drawing time is a view'),
                          ('write_cursor', 'writing while playing is a domain tool'),
                          ('select(', 'choosing a segment is the list, told by the axis')):
            self.assertNotIn(gone, js, why)
        self.assertIn("axis.seek(D ? Math.min(sec, D) : sec, 'goto')", js)
        self.assertIn("st.reason === 'goto'", _read(TIMELINE))
        self.assertIn("st.reason === 'goto'", _read(COMMON_JS / 'surfaces' / 'brick-segment-list.js'))

    def test_the_time_bricks_share_one_keyboard_rule_and_one_play_from(self):
        # Revérification du 2026-10-21 : la règle « le clavier est à une saisie » était écrite trois
        # fois (transport, ligne de temps, écriture), « écouter depuis » quatre (dont le ▶ d'un
        # segment), l'échappement HTML recopié à côté de `WamaApp.escapeHtml`.
        segment_list = _read(COMMON_JS / 'surfaces' / 'brick-segment-list.js')
        for path in (TRANSPORT, TIMELINE, WRITING_BRICK):
            code = _read(path)
            self.assertIn('WamaApp.isTyping()', code, path.name)
            self.assertNotIn('a.isContentEditable', code, f'{path.name} writes the rule again')
        for path, code in ((TIMELINE, _read(TIMELINE)), (WRITING_BRICK, _read(WRITING_BRICK)),
                           (COMMON_JS / 'surfaces' / 'brick-segment-list.js', segment_list)):
            self.assertIn('axis.playFrom(', code, path.name)
            self.assertNotIn('axis.shuttle(0);\n', code.replace('if (s.shuttling) axis.shuttle(0);', ''),
                             f'{path.name} releases the shuttle by hand')
        self.assertIn('WamaApp.escapeHtml(', _read(WRITING_BRICK))
        self.assertNotIn('function esc(', _read(WRITING_BRICK))

    def test_a_tool_marks_its_spans_on_the_views_through_the_bus(self):
        # L'écriture à la lecture ne connaît aucune vue : elle MARQUE ses plages (`bands`), la
        # ligne de temps les dessine. Une brique ne parle jamais à une autre (§5bis).
        writing = _read(WRITING_BRICK)
        self.assertIn("ctx.emit('bands'", writing)
        self.assertNotIn('WamaTimeline', writing)
        self.assertIn("ctx.on('bands'", _read(COMMON_JS / 'surfaces' / 'brick-media-timeline.js'))

    def test_the_parity_is_measured_by_a_scenario_on_the_surface(self):
        from wama.common.services import nightly_tests, ui_smoke_editor
        self.assertIn('transcriber.editor_parity', {s.id for s in nightly_tests.REGISTRY})
        self.assertEqual('surface', ui_smoke_editor.FORM)

    def test_the_play_button_is_not_rewritten_at_each_frame(self):
        # 2026-10-28 (Fabien) : un clic sur « pause » pendant la lecture était perdu — l'abonné à
        # l'axe, appelé à chaque image, réécrivait le bouton et remplaçait l'icône sous le pointeur.
        source = _read(TRANSPORT)
        subscriber = source[source.index('axis.subscribe(function (st)'):]
        subscriber = subscriber[:subscriber.index('});')]
        self.assertNotIn('play.innerHTML', subscriber)
        self.assertIn('if (st.playing !== shownPlaying)', subscriber)

    def test_the_served_copies_are_the_sources(self):
        surfaces = COMMON_JS / 'surfaces'
        pairs = [(COMMON_JS / name, SERVED / 'common' / 'js' / name)
                 for name in ('wama-axis.js', 'wama-transport.js', 'wama-timeline.js', 'wama-segments.js',
                              'wama-params.js', 'wama-app-base.js', 'wama-brick-layout.js')]
        pairs += [(surfaces / name, SERVED / 'common' / 'js' / 'surfaces' / name)
                  for name in ('wama-surface.js', 'brick-media-transport.js', 'brick-media-timeline.js',
                               'brick-playback-writing.js', 'brick-segment-list.js',
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
        self.assertEqual({'title', 'meeting_date', 'speaker_map', 'listened_sources'},
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
