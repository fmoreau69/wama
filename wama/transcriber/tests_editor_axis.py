"""L'éditeur de correction sur le TRANSPORT COMMUN (2026-10-20, `WAMA_APP_GENERATION_ROUTE.md §F3b`).

Le transport de l'éditeur était écrit dans `edit.js` (échelle J/K/L recopiée de `wama-shuttle.js`,
lecture arrière par minuterie, sauts, Espace, lecture du temps) et chaque vue lisait l'`<audio>`.
Il passe par l'axe commun (`wama-axis.js`) : ces gardes empêchent qu'une seconde version du même
geste revienne dans la page. Le COMPORTEMENT, lui, est attesté dans le navigateur par le scénario
`transcriber.editor_parity` (joué avant et après le portage, mêmes 38 gestes).
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

APP = Path(settings.BASE_DIR) / 'wama' / 'transcriber'
EDITOR = APP / 'static' / 'transcriber' / 'js' / 'edit.js'
TEMPLATE = APP / 'templates' / 'transcriber' / 'edit.html'
SERVED = Path(settings.BASE_DIR) / 'staticfiles'


def _read(path):
    return path.read_text(encoding='utf-8')


class EditorOnTheCommonAxisTest(SimpleTestCase):

    def test_the_editor_drives_the_common_axis_and_shuttle(self):
        js = _read(EDITOR)
        self.assertIn('WamaAxis.create(', js)
        self.assertIn('WamaShuttle.create(', js)
        self.assertIn('axis.bindKeys(', js, 'Space, arrows and J/K/L come from the axis keyboard')
        self.assertIn('axis.attach(', js)

    def test_no_second_transport_lives_in_the_page(self):
        js = _read(EDITOR)
        for gone, why in (('const SHUTTLE', 'the J/K/L ladder is the brick default'),
                          ('reverseTimer', 'backward play is the axis, silent'),
                          ('parseTimecode', 'times are read by WamaAxis.parseTime'),
                          ('.currentTime', 'views read the axis time, not the <audio>'),
                          ('.playbackRate', 'the speed is the axis speed'),
                          ('.preload', 'the common player asks for the metadata itself')):
            self.assertNotIn(gone, js, why)
        # The page seeks through the axis ; the axis hands the medium to the common player, whose
        # rules (exclusive playback, a position set again once seekable) are never redone here.
        self.assertEqual(1, js.count('WamaAudioPlayer.seek('), 'one seek : the hook given to the axis')
        self.assertIn('seek: function (t) { WamaAudioPlayer.seek(playerId, t, false); }', js)
        self.assertIn('play: function () { return WamaAudioPlayer.play(playerId); }', js)

    def test_the_page_loads_the_bricks_once_and_before_the_editor(self):
        html = _read(TEMPLATE)
        editor = html.index("transcriber/js/edit.js")
        for brick in ('common/js/wama-axis.js', 'common/js/wama-shuttle.js', 'common/js/wama-history.js'):
            self.assertEqual(1, html.count(brick), brick)
            self.assertLess(html.index(brick), editor, f'{brick} before edit.js (used at evaluation)')
        self.assertNotIn("{% static_v 'common/js/wama-audio-player.js' %}", html,
                         'the common player is mounted by base.html — a second load made two registries')

    def test_the_parity_is_measured_by_a_scenario(self):
        from wama.common.services import nightly_tests
        self.assertIn('transcriber.editor_parity', {s.id for s in nightly_tests.REGISTRY})

    def test_the_served_copies_are_the_sources(self):
        common = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
        for source, served in ((EDITOR, SERVED / 'transcriber' / 'js' / 'edit.js'),
                               (common / 'wama-axis.js', SERVED / 'common' / 'js' / 'wama-axis.js')):
            self.assertEqual(_read(source), _read(served), f'{served} is stale')
