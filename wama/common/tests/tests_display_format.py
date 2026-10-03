"""A setting's DISPLAY FORMAT and its value PROPOSED by a card input (2026-10-04, Fabien).

« Si on met un audio de travail, il faudrait afficher par défaut la durée de la chanson d'origine,
et par défaut une valeur plus logique comme 3'30 » — then « on a fait un mécanisme qui gère les
ko, Mo, Go : on pourrait y ajouter la gestion min/sec ». What each test holds:
  * `WamaApp.formatDuration` sits next to `formatSize`, and its Python twin is
    `media_probe.format_duration` — one writing of a duration (« 3:30 », « 1:02:30 »);
  * `Param.display_format` drives every place a value is READ: the slider label, its bounds, the
    `cap_from` notes, the card chip; a setting that declares nothing keeps its display;
  * `Param.default_from` proposes the duration of the file put on a port — read in the browser for
    an uploaded file, by `common:api_media_probe` for a designated one (the designation's guard).
V8 comes from `py_mini_racer` (cf. AGENTS.md §JS), as in `tests_cap_from_js`.
"""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from wama.common.tests.tests_cap_from_js import FAKE_DOM

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
JS = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class FormatInTheBrowserTest(SimpleTestCase):

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM + "\ndocument.cookie = ''; var navigator = {}; var localStorage = "
                     "{getItem: function () { return null; }, setItem: function () {}};")
        self.v8.eval((JS / 'wama-app-base.js').read_text(encoding='utf-8'))
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def _js(self, expr):
        return self.v8.eval(f'JSON.stringify({expr})') and json.loads(
            self.v8.eval(f'JSON.stringify({expr})'))

    def test_a_duration_reads_in_minutes_and_seconds_next_to_the_sizes(self):
        self.assertEqual(['0:45', '3:30', '1:02:30', '—', '1:30'], self._js(
            "[45, 210, 3750, 0, 1.5].map(function (v, i) {"
            " return window.WamaApp.formatDuration(v, i === 4 ? 'min' : 's'); })"))
        self.assertEqual('3,8 Go', self._js("window.WamaApp.formatSize(3.8, 'GB')"))

    def test_a_setting_that_declares_a_format_reads_in_it_and_the_others_do_not_move(self):
        self.assertEqual(['3:30', '3,8 Go', '85s', '0.5'], self._js(
            "[window.WamaParams.valueLabel(210, 'duration', 's'),"
            " window.WamaParams.valueLabel(3.8 * 1024 * 1024 * 1024, 'size', ''),"
            " window.WamaParams.valueLabel(85, '', 's'),"
            " window.WamaParams.valueLabel(0.5, '', '')]"))

    def test_the_proposed_value_follows_the_step_and_the_bound_of_the_moment(self):
        """A 3:27 song on a 5 s step → 3:25 ; with MusicGen (`cap_from` set max to 30) → 30."""
        self.assertEqual([205, 30, 10], self._js(
            "[window.WamaParams.proposedValue({step: '5', min: '10', max: '600'}, 207.4),"
            " window.WamaParams.proposedValue({step: '5', min: '10', max: '30'}, 207.4),"
            " window.WamaParams.proposedValue({step: '5', min: '10', max: '600'}, 3)]"))

    def test_putting_a_file_on_the_declared_port_sets_the_slider(self):
        """The whole wiring, with a fake page: the card's pane names its input, the input fires
        `change`, the duration comes back, the slider takes it and says so (input + change)."""
        self.v8.eval("""
            var listeners = {}, fired = [];
            var input = {addEventListener: function (t, f) { listeners[t] = f; }};
            var slider = {value: '210', step: '5', min: '10', max: '600',
                          dispatchEvent: function (e) { fired.push(e.type); }};
            var pane = {dataset: {portInput: 'melodyInput'}};
            document.querySelector = function (sel) {
              return sel.indexOf('data-port-pane="work_audio"') !== -1 ? pane : null; };
            document.getElementById = function (id) {
              return id === 'melodyInput' ? input : (id === 'durationSlider' ? slider : null); };
            var CSS = {escape: function (s) { return s; }};
            var container = {querySelector: function (sel) {
              return sel === '#durationSlider' ? slider : null; }};
            window.WamaApp.mediaDuration = function () { return Promise.resolve(187.2); };
            window.WamaParams.bindDefaultFrom(container, [{name: 'duration', dom_id:
              {panel: 'durationSlider'}, contexts: ['panel'],
              default_from: {port: 'work_audio', property: 'duration'}}], 'panel');
            listeners.change();
        """)
        self.assertEqual({'value': 185, 'fired': ['input', 'change']},
                         self._js("{value: Number(slider.value), fired: fired}"))

    def test_a_modal_of_an_existing_item_does_not_follow_the_next_card_s_file(self):
        self.v8.eval("""
            var bound = false;
            var CSS = {escape: function (s) { return s; }};
            document.querySelector = function () { bound = true; return null; };
            window.WamaParams.bindDefaultFrom({querySelector: function () { return {}; }},
              [{name: 'duration', default_from: {port: 'work_audio', property: 'duration'}}], 'item');
        """)
        self.assertFalse(self._js('bound'))


class FormatOnTheServerTest(SimpleTestCase):

    def test_the_python_twin_writes_durations_the_same_way(self):
        from wama.common.utils.media_probe import format_duration
        self.assertEqual(['0:45', '3:30', '1:02:30', ''],
                         [format_duration(v) for v in (45, 210, 3750, 0)])

    def test_the_card_chip_reads_in_the_declared_format(self):
        from wama.common.utils.card_chips import chips_for
        from types import SimpleNamespace
        field = {'name': 'duration', 'type': 'range', 'label': 'Durée', 'unit': 's', 'chip': True}
        item = SimpleNamespace(duration=210)
        self.assertEqual('210 s', chips_for(item, [field])[0]['label'], 'nothing declared: as before')
        self.assertEqual('3:30', chips_for(item, [dict(field, display_format='duration')])[0]['label'])

    def test_the_composer_duration_declares_its_format_its_default_and_its_source(self):
        from wama.composer.params import PARAMS
        duration = next(p for p in PARAMS if p.name == 'duration')
        self.assertEqual((210, 'duration', {'port': 'work_audio', 'property': 'duration'}),
                         (duration.default, duration.display_format, duration.default_from))


class TheProbeOfADesignatedFileTest(TestCase):
    """`common:api_media_probe` — what a designated file is made of, behind the designation's
    guard (confinement, then `readable_by`)."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)
        users = get_user_model().objects
        self.me = users.create_user('probe_me', password='x')
        self.other = users.create_user('probe_other', password='x')
        self.client.force_login(self.me)

    def _wav(self, owner, seconds):
        import numpy as np
        import soundfile as sf
        rel = f'users/{owner.pk}/temp/wama_temoin_probe.wav'
        target = Path(self.media) / rel
        target.parent.mkdir(parents=True)
        sf.write(str(target), np.zeros(int(16000 * seconds), dtype='float32'), 16000)
        return rel

    def test_my_file_tells_its_duration(self):
        from wama.common.utils.ffmpeg_utils import get_ffprobe_exe
        if not get_ffprobe_exe():
            self.skipTest('ffprobe absent')
        response = self.client.get(reverse('common:api_media_probe'),
                                    {'path': self._wav(self.me, 3.5)})
        self.assertEqual(200, response.status_code)
        self.assertAlmostEqual(3.5, response.json()['duration'], places=1)
        self.assertEqual('audio', response.json()['media_type'])

    def test_a_file_i_cannot_designate_is_not_probed(self):
        response = self.client.get(reverse('common:api_media_probe'),
                                   {'path': self._wav(self.other, 1.0)})
        self.assertEqual(403, response.status_code)

    def test_a_path_outside_the_media_root_is_refused(self):
        response = self.client.get(reverse('common:api_media_probe'), {'path': '../../etc/passwd'})
        self.assertEqual(404, response.status_code)

    def test_the_file_manager_properties_say_what_the_media_is(self):
        """« Compléter les infos des médias depuis le filemanager » (Fabien, 2026-10-04) : la
        fenêtre Propriétés reçoit la MÊME sonde (durée, codec • kHz • canaux)."""
        from wama.common.utils.ffmpeg_utils import get_ffprobe_exe
        if not get_ffprobe_exe():
            self.skipTest('ffprobe absent')
        response = self.client.get(reverse('filemanager:api_info'),
                                   {'path': self._wav(self.me, 2.0)})
        self.assertEqual(200, response.status_code)
        media = response.json()['media']
        self.assertAlmostEqual(2.0, media['duration'], places=1)
        self.assertIn('16.0 kHz', media['properties'])
        self.assertIn('mono', media['properties'])
