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
        # La brique des durées, que `WamaApp.formatDuration` appelle (2026-11-19) — chargée avant
        # lui par `base.html`.
        self.v8.eval((JS / 'wama-durations.js').read_text(encoding='utf-8'))
        self.v8.eval((JS / 'wama-app-base.js').read_text(encoding='utf-8'))
        # Les ports de la card d'entrée se lisent par `WamaInputSlots.filePorts` depuis le
        # 2026-10-20 (307c6177) : sans sa brique, `default_from` ne se liait plus et cette garde
        # était rouge quel que soit le code (relevé le 2026-10-29).
        self.v8.eval((JS / 'wama-input-slots.js').read_text(encoding='utf-8'))
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def _js(self, expr):
        return self.v8.eval(f'JSON.stringify({expr})') and json.loads(
            self.v8.eval(f'JSON.stringify({expr})'))

    def test_a_duration_reads_in_minutes_and_seconds_next_to_the_sizes(self):
        self.assertEqual(['0:45', '3:30', '1:02:30', '—', '1:30'], self._js(
            "[45, 210, 3750, 0, 1.5].map(function (v, i) {"
            " return window.WamaApp.formatDuration(v, i === 4 ? 'min' : 's'); })"))
        self.assertEqual('3,8 Go', self._js("window.WamaApp.formatSize(3.8, 'GB')"))

    def test_a_setting_with_a_format_reads_in_it_and_the_others_do_not_move(self):
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
            var pane = {getAttribute: function (a) {
              return {'data-port-pane': 'work_audio', 'data-port-input': 'melodyInput'}[a]; }};
            document.querySelectorAll = function (sel) {
              return sel.indexOf('data-port-pane') !== -1 ? [pane] : []; };
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

    #: Une card dont le port tient `input.files` : le curseur, sa note, l'écouteur `change` du port.
    PORT_AND_SLIDER = """
        var listeners = {}, sliderListeners = {}, probed = 0;
        var input = {dataset: {}, files: [], addEventListener: function (t, f) { listeners[t] = f; }};
        var note = {textContent: ''};
        var slider = {value: '210', step: '5', min: '10', max: '600', dataset: {},
                      dispatchEvent: function () {},
                      addEventListener: function (t, f) { sliderListeners[t] = f; },
                      closest: function () { return {querySelector: function () { return note; }}; }};
        var pane = {getAttribute: function (a) {
          return {'data-port-pane': 'work_audio', 'data-port-input': 'melodyInput'}[a]; }};
        document.querySelectorAll = function (sel) {
          return sel.indexOf('data-port-pane') !== -1 ? [pane] : []; };
        document.getElementById = function (id) {
          return id === 'melodyInput' ? input : (id === 'durationSlider' ? slider : null); };
        var CSS = {escape: function (s) { return s; }};
        var container = {querySelector: function (sel) {
          return sel === '#durationSlider' ? slider : null; }};
        window.WamaApp.mediaDuration = function () { probed += 1; return Promise.resolve(187.2); };
        window.WamaParams.bindDefaultFrom(container, [{name: 'duration', dom_id:
          {panel: 'durationSlider'}, contexts: ['panel'],
          default_from: {port: 'work_audio', property: 'duration'}}], 'panel');
    """

    def test_a_lot_on_the_port_leaves_each_file_its_own_value(self):
        """Le premier fichier ne décide pas pour les autres (2026-11-03) : le réglage est marqué,
        sa valeur ne bouge pas, et la note le dit."""
        self.v8.eval(self.PORT_AND_SLIDER + "input.files = [{name: 'a'}, {name: 'b'}]; listeners.change();")
        self.assertEqual({'value': 210, 'held': 'input', 'probed': 0}, self._js(
            "{value: Number(slider.value), held: slider.dataset.unset, probed: probed}"))
        self.assertIn('lot', self._js('note.textContent'))

    def test_back_to_one_file_the_setting_follows_it_again(self):
        self.v8.eval(self.PORT_AND_SLIDER + "input.files = [{name: 'a'}, {name: 'b'}]; listeners.change();")
        self.v8.eval("input.files = [{name: 'a'}]; listeners.change();")
        self.assertEqual({'value': 185, 'probed': 1, 'note': "Reprise du fichier d'entrée (3:07)."}, self._js(
            "{value: Number(slider.value), probed: probed, note: note.textContent}"))
        self.assertFalse(self._js("'unset' in slider.dataset"))

    def test_touching_the_setting_applies_it_to_the_whole_lot(self):
        self.v8.eval(self.PORT_AND_SLIDER + "input.files = [{name: 'a'}, {name: 'b'}]; listeners.change();"
                     "sliderListeners.input({isTrusted: true});")
        self.assertFalse(self._js("'unset' in slider.dataset"))
        self.assertEqual('', self._js('note.textContent') or '')

    def test_a_fill_by_code_does_not_count_as_touching_it(self):
        """Une borne de modèle qui se recale émet `input` : ce n'est pas une décision."""
        self.v8.eval(self.PORT_AND_SLIDER + "input.files = [{name: 'a'}, {name: 'b'}]; listeners.change();"
                     "sliderListeners.input({isTrusted: false});")
        self.assertEqual('input', self._js('slider.dataset.unset'))

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


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class OneWritingOfADurationTest(SimpleTestCase):
    """2026-11-19 (Fabien : « une petite fonction au commun pour aligner les durées […] il faudrait
    qu'elle soit utilisée partout où il y a des durées ») : the common brick of durations, two twins
    — `common/utils/durations.py` and `WamaDurations` (`wama-durations.js`) — that write the SAME
    text for the same value (they did not : the browser rounded, 95.6 s read « 1:36 » there and
    « 1:35 » on the server) ; the SRT stamp kept byte for byte (the SRT references of the media
    library are measured by their fingerprint) ; and no duration written by hand anywhere else."""

    CLOCK = [0, 45, 95.6, 210, 3599.9, 3750, 83.45, 5.12]
    ELAPSED = [0, 0.4, 45, 65, 120, 159.1, 3600, 3750]

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval('var window = this;' + (JS / 'wama-durations.js').read_text(encoding='utf-8'))

    def _js(self, expr):
        return json.loads(self.v8.eval(f'JSON.stringify({expr})'))

    def test_both_twins_write_the_same_text(self):
        from wama.common.utils.durations import format_clock, format_duration, format_elapsed
        values = json.dumps(self.CLOCK)
        for precision in (0, 1, 3):
            with self.subTest(precision=precision):
                self.assertEqual([format_clock(v, precision) for v in self.CLOCK], self._js(
                    f"{values}.map(function (v) {{ return window.WamaDurations.clock(v, 's', {precision}); }})"))
        self.assertEqual([format_duration(v) for v in self.CLOCK],
                         self._js(f"{values}.map(function (v) {{ return window.WamaDurations.duration(v); }})"))
        self.assertEqual([format_elapsed(v) for v in self.ELAPSED], self._js(
            f"{json.dumps(self.ELAPSED)}.map(function (v) {{ return window.WamaDurations.elapsed(v); }})"))

    def test_the_value_is_cut_never_rounded(self):
        from wama.common.utils.durations import format_clock, format_duration, format_elapsed
        self.assertEqual(('1:35', '', '0:00', '1:23.4', '0:05.120'),
                         (format_duration(95.6), format_duration(0), format_clock(0),
                          format_clock(83.45, 1), format_clock(5.12, 3)))
        self.assertEqual(('', '45 s', '1 min 05 s', '2 min', '1 h', '1 h 02 min'),
                         tuple(format_elapsed(v) for v in (0.4, 45, 65, 120, 3600, 3750)))
        self.assertEqual('1:02:30', format_duration(3750), 'the hours past 59:59, never « 62:30 »')

    def test_the_srt_stamp_is_the_one_that_made_the_references(self):
        """The writing of `asr_eval_corpus` (rounded to the millisecond) — the transcriber wrote two
        others, cut, one of them wrong on a float (0.29 s gave « 289 »)."""
        from wama.common.utils.durations import srt_timestamp
        from wama.transcriber.management.commands.asr_eval_corpus import srt_time

        def reference(seconds):                      # the writing of asr_eval_corpus, before
            ms = int(round(max(seconds, 0.0) * 1000))
            h, ms = divmod(ms, 3_600_000)
            m, ms = divmod(ms, 60_000)
            s, ms = divmod(ms, 1000)
            return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
        for value in (0, 0.29, 1.9996, 59.9999, 95.4, 3725.004, 36000.5):
            with self.subTest(value=value):
                self.assertEqual(reference(value), srt_timestamp(value))
                self.assertEqual(reference(value), srt_time(value))
        self.assertEqual('00:00:00,290', srt_timestamp(0.29))

    #: A duration written by hand (minutes from seconds) : `divmod(…, 60)` or `x // 60` in Python,
    #: `Math.floor(… / 60)` in a script — what the copies of the clock were made of.
    BY_HAND_PY = r"divmod\([^)\n]*,\s*60\)|//\s*60\b"
    BY_HAND_JS = r"Math\.(?:floor|round|trunc)\([^)\n]*/\s*60\)"
    #: What is left, with its reason — may only go DOWN.
    DECLARED_GAPS = {
        # The COARSE estimate of a low confidence (« ≈ 12 min », no false precision) — a rule of
        # the ETA, not a writing of a duration ; its precise form goes through the brick.
        'wama/common/static/common/js/wama-eta.js': 1,
        # « il y a 5 min » : a RELATIVE date of a notification, not a duration.
        'wama/common/static/common/js/wama-notifications.js': 1,
    }

    def test_no_duration_is_written_by_hand_outside_the_brick(self):
        import re
        from wama.common.sandbox import sandbox_labels
        twins = set(sandbox_labels())               # generated copies, regenerated on their own
        found = {}
        for world in ('wama', 'wama_lab', 'wama_data'):
            for path in (Path(settings.BASE_DIR) / world).rglob('*'):
                rel = path.relative_to(Path(settings.BASE_DIR)).as_posix()
                parts = rel.split('/')
                if (path.suffix not in ('.py', '.js', '.html')
                        or any(p in ('vendor', 'vendors', 'migrations', 'node_modules') for p in parts)
                        or (len(parts) > 1 and parts[1] in twins)
                        or parts[-1].startswith('tests') or '/tests/' in rel
                        or parts[-1] in ('durations.py', 'wama-durations.js')):
                    continue
                pattern = self.BY_HAND_PY if path.suffix == '.py' else self.BY_HAND_JS
                count = len(re.findall(pattern, path.read_text(encoding='utf-8', errors='replace')))
                if count:
                    found[rel] = count
        self.assertEqual(self.DECLARED_GAPS, found,
                         'a duration is put in minutes and seconds by hand : use the common brick '
                         '(`common/utils/durations.py`, `WamaDurations`)')

    def test_the_card_chip_reads_in_the_declared_format(self):
        from wama.common.utils.card_chips import chips_for
        from types import SimpleNamespace
        field = {'name': 'duration', 'type': 'range', 'label': 'Durée', 'unit': 's', 'chip': True}
        item = SimpleNamespace(duration=210)
        self.assertEqual('210 s', chips_for(item, [field])[0]['label'], 'nothing declared: as before')
        self.assertEqual('3:30', chips_for(item, [dict(field, display_format='duration')])[0]['label'])

    def test_the_composer_duration_carries_its_format_its_default_and_its_source(self):
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
