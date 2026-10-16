"""SURFACES (2026-10-10) — a page of edition COMPOSED of declared bricks, served by common views.

Held here without a browser : the registry (bricks consume only the EXISTING vocabularies, their
scripts exist and parse under V8) ; the anonymizer's `review` surface (read / save / rights /
availability) ; and the PARITY of the two writings of the correction rule — Python for the blur,
JS for the live page — run on the same cases.
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.utils import detections as dets

STATIC = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static'


def _js(path):
    return (STATIC / path).read_text(encoding='utf-8')


class RegistryTest(SimpleTestCase):

    def test_every_brick_consumes_only_existing_vocabularies(self):
        from wama.common.app_registry import MEDIA_CATEGORIES
        from wama.common.catalog.data_types import known_types
        from wama.common.surfaces import BRICKS
        known = set(MEDIA_CATEGORIES) | known_types()
        for brick in BRICKS.values():
            with self.subTest(brick=brick.key):
                self.assertFalse(set(brick.consumes) - known,
                                 'a brick never invents a third vocabulary')

    def test_every_declared_script_exists_and_parses_under_v8(self):
        from django.contrib.staticfiles import finders
        from py_mini_racer import MiniRacer
        from wama.common.surfaces import BRICKS
        paths = {p for b in BRICKS.values() for p in b.scripts()} | {'common/js/surfaces/wama-surface.js'}
        for path in sorted(paths):
            with self.subTest(script=path):
                # Resolved like the page resolves it : a vendored library lives under `wama/static`.
                found = finders.find(path)
                self.assertTrue(found, path)
                # Parse WITHOUT executing (the bricks touch the DOM) : a function wrapping it.
                MiniRacer().eval('(function(){' + Path(found).read_text(encoding='utf-8') + '})')

    def test_the_anonymizer_review_surface_is_declared_and_complete(self):
        from wama.common.surfaces import surface
        review = surface('anonymizer', 'review')
        self.assertIsNotNone(review)
        self.assertEqual(['image_boxes', 'object_list', 'surface_actions'],
                         [s.brick for s in review.slots])
        self.assertEqual(('detection_corrections', 'blur'), (review.edits, review.reruns))
        self.assertEqual('common/js/wama-detections.js', review.scripts()[0],
                         'a dependency loads before the bricks that need it')

    def test_the_blur_watches_the_corrections_not_the_detection(self):
        from wama.anonymizer.function_specs import PIPELINE
        self.assertIn('detection_corrections', PIPELINE.watched_of(PIPELINE.spec('blur')))
        self.assertNotIn('detection_corrections', PIPELINE.watched_of(PIPELINE.spec('detect')))


class CorrectionsParityTest(SimpleTestCase):
    """The page shows what the blur will do only if the JS rule IS the Python rule."""

    CASES = [
        {'removed': [{'i': 0, 'box': [61, 61, 81, 81]}]},
        # IoU 0,444 with the first face : just UNDER the threshold — a drift of the JS threshold
        # would remove it on the page and not in the blur.
        {'removed': [{'i': 0, 'box': [10, 10, 30, 55]}]},
        {'added': [{'i': 0, 'box': [2.5, 3.5, 10.5, 12.5], 'label': 'plate'}]},
        {'added': [{'i': 2, 'box': [1, 1, 9, 9], 'label': 'face'}],
         'removed': [{'i': 0, 'box': [0, 0, 12, 12]}, {'i': 0, 'box': [10, 10, 30, 30]}]},
        {},
    ]

    def _doc(self):
        doc = dets.new_document(media='image', width=100, height=100)
        dets.add(doc, 0, [dets.detection(box=[10, 10, 30, 30], label='face', conf=0.9),
                          dets.detection(box=[60, 60, 80, 80], label='face', conf=0.4)])
        return {k: v for k, v in doc.items() if not k.startswith('_')}

    def test_python_and_js_apply_the_same_corrections(self):
        from py_mini_racer import MiniRacer
        engine = MiniRacer()
        engine.eval('var window = {};' + _js('common/js/wama-detections.js'))
        for case in self.CASES:
            with self.subTest(case=case):
                py = dets.apply_corrections(self._doc(), case)
                js = json.loads(engine.eval(
                    'JSON.stringify(window.WamaDetections.applyCorrections(%s, %s))'
                    % (json.dumps(self._doc()), json.dumps(case))))
                norm = lambda d: [(f['i'], [(x['label'], x['box'], bool(x.get('manual')))
                                            for x in f['d']]) for f in sorted(d['frames'], key=lambda f: f['i'])]
                self.assertEqual(norm(py), norm(js))
                self.assertEqual(py.get('corrected'), js.get('corrected'))

    def test_moving_a_detection_removes_it_and_adds_it_where_it_was_put(self):
        from py_mini_racer import MiniRacer
        engine = MiniRacer()
        engine.eval('var window = {};' + _js('common/js/wama-detections.js'))
        value = json.loads(engine.eval(
            'var D = window.WamaDetections, doc = %s;'
            'var o = D.objects(doc, {}, 0)[0];'
            'JSON.stringify(D.move({}, o, [12, 12, 32, 32], 0))' % json.dumps(self._doc())))
        self.assertEqual([{'i': 0, 'box': [10, 10, 30, 30]}], value['removed'])
        self.assertEqual([{'i': 0, 'box': [12, 12, 32, 32], 'label': 'face'}], value['added'])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ReviewSurfaceViewsTest(TestCase):

    def setUp(self):
        from wama.anonymizer.models import Media
        from wama.common.utils.media_paths import app_media_dir, get_app_media_path
        self.addCleanup(shutil.rmtree, settings.MEDIA_ROOT, True)
        self.user = get_user_model().objects.create_user('surface_owner', password='x')
        self.other = get_user_model().objects.create_user('surface_other', password='x')
        folder = get_app_media_path('anonymizer', self.user.id, 'input')
        folder.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(folder / 'street.png'), np.zeros((40, 60, 3), np.uint8))
        doc = dets.new_document(media='image', width=60, height=40)
        dets.add(doc, 0, [dets.detection(box=[5, 5, 20, 20], label='face', conf=0.8)])
        out = get_app_media_path('anonymizer', self.user.id, 'output')
        out.mkdir(parents=True, exist_ok=True)
        dets.write(str(out / 'street_detections.json'), doc)
        self.media = Media.objects.create(
            user=self.user, file_ext='.png', media_type='image', classes2blur=['face'],
            file=f"{app_media_dir('anonymizer', self.user.id, 'input')}/street.png",
            detections_file=f"{app_media_dir('anonymizer', self.user.id, 'output')}/street_detections.json")
        self.base = f'/common/surface/anonymizer/review/{self.media.pk}/'

    def test_the_owner_opens_the_page_and_reads_the_data(self):
        self.client.force_login(self.user)
        page = self.client.get(self.base)
        self.assertEqual(200, page.status_code)
        self.assertContains(page, 'brick-image-boxes.js')
        self.assertContains(page, 'gridstack-13.3.0/gridstack-all.js')
        data = self.client.get(self.base + 'data/').json()
        self.assertTrue(data['reads']['image'].endswith('street.png'))
        self.assertEqual([5, 5, 20, 20], data['reads']['detections']['frames'][0]['d'][0]['box'])
        self.assertEqual({'classes': ['face']}, data['context'])
        self.assertTrue(data['can_edit'])

    def test_a_saved_correction_is_validated_and_kept_apart(self):
        self.client.force_login(self.user)
        value = {'added': [{'i': 0, 'box': [30, 5, 45, 18], 'label': 'face'}],
                 'removed': [{'i': 0, 'box': [5, 5, 20, 20]}]}
        res = self.client.post(self.base + 'save/', json.dumps({'value': value}),
                               content_type='application/json')
        self.assertEqual(200, res.status_code, res.content)
        self.media.refresh_from_db()
        self.assertEqual(value['removed'], self.media.detection_corrections['removed'])
        bad = self.client.post(self.base + 'save/', json.dumps({'value': {'added': [{'box': [9, 9, 1, 1]}]}}),
                               content_type='application/json')
        self.assertEqual(400, bad.status_code, 'an inverted box is refused')

    def test_someone_else_neither_reads_nor_writes(self):
        self.client.force_login(self.other)
        self.assertEqual(404, self.client.get(self.base).status_code)
        res = self.client.post(self.base + 'save/', json.dumps({'value': {}}),
                               content_type='application/json')
        self.assertEqual(404, res.status_code)

    def test_a_video_says_why_it_does_not_open_yet(self):
        type(self.media).objects.filter(pk=self.media.pk).update(media_type='video')
        self.client.force_login(self.user)
        page = self.client.get(self.base)
        self.assertContains(page, 'la vidéo viendra')
        self.assertEqual(409, self.client.get(self.base + 'data/').status_code)

    def test_a_save_prepared_on_a_stale_state_is_refused_not_written(self):
        self.client.force_login(self.user)
        token = self.client.get(self.base + 'data/').json()['token']
        first = {'removed': [{'i': 0, 'box': [5, 5, 20, 20]}]}
        res = self.client.post(self.base + 'save/', json.dumps({'value': first, 'base': token}),
                               content_type='application/json')
        self.assertEqual(200, res.status_code, res.content)
        # A second page opened on the SAME first state saves after the first one : refused.
        late = self.client.post(self.base + 'save/', json.dumps({'value': {}, 'base': token}),
                                content_type='application/json')
        self.assertEqual(409, late.status_code)
        self.media.refresh_from_db()
        self.assertEqual(first['removed'], self.media.detection_corrections['removed'])
        # The token the first save returned is the current state : accepted.
        ok = self.client.post(self.base + 'save/', json.dumps({'value': {}, 'base': res.json()['token']}),
                              content_type='application/json')
        self.assertEqual(200, ok.status_code, ok.content)


class TextSectionsSplitTest(SimpleTestCase):
    """The text brick cuts a document at its headings WITHOUT losing a character : what it
    writes back is what was read, plus the user's corrections."""

    CASES = [
        '# Title\n\nIntro.\n\n## Part\nBody\n',
        'No heading at all.\nSecond line.',
        '',
        '# A\n```\n# not a heading, inside code\n```\n# B\n\n\n',
        'Preamble\n# First\ntext',
    ]

    def _split(self, engine, text):
        return json.loads(engine.eval('JSON.stringify(window.__brick.split(%s))' % json.dumps(text)))

    def test_the_sections_rebuild_the_text_exactly(self):
        from py_mini_racer import MiniRacer
        engine = MiniRacer()
        engine.eval('var window = {WamaSurface: {registerBrick: function (k, d) { window.__brick = d; }}};'
                    + _js('common/js/surfaces/brick-text-sections.js'))
        for text in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(text, ''.join(self._split(engine, text)))
        self.assertEqual(['# A\n```\n# not a heading, inside code\n```\n', '# B\n\n\n'],
                         self._split(engine, self.CASES[3]),
                         'a « # » inside a code block does not start a section')
        self.assertEqual(['Preamble\n', '# First\ntext'], self._split(engine, self.CASES[4]))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TextSurfaceViewsTest(TestCase):
    """A surface whose edited field is a FILE edits its TEXT — the common rule of the Writer's
    fond. Held on the anonymizer, whose `detect` produces `detections_file` and whose `blur`
    depends on it : the same shape as the Writer's `write` → `layout`, without the sandbox."""

    def setUp(self):
        from wama.anonymizer.models import Media
        from wama.common.surfaces import SURFACES, BrickSlot, Surface, register_surface
        from wama.common.utils.media_paths import app_media_dir, get_app_media_path
        self.addCleanup(shutil.rmtree, settings.MEDIA_ROOT, True)
        self.user = get_user_model().objects.create_user('text_surface_owner', password='x')
        out = get_app_media_path('anonymizer', self.user.id, 'output')
        out.mkdir(parents=True, exist_ok=True)
        (out / 'draft.md').write_text('# Title\nFirst text.\n', encoding='utf-8')
        self.rel = f"{app_media_dir('anonymizer', self.user.id, 'output')}/draft.md"
        self.media = Media.objects.create(user=self.user, file_ext='.png', media_type='image',
                                          detections_file=self.rel)
        register_surface(Surface(
            app='anonymizer', key='text_probe', label='Probe', model='anonymizer.Media',
            slots=(BrickSlot('text', 'text_sections', 0, 0, 12, 10),),
            reads={}, edits='detections_file', reruns='blur'))
        self.addCleanup(SURFACES.pop, 'anonymizer.text_probe', None)
        self.base = f'/common/surface/anonymizer/text_probe/{self.media.pk}/'
        self.client.force_login(self.user)

    def _save(self, value, base=None):
        body = {'value': value}
        if base is not None:
            body['base'] = base
        return self.client.post(self.base + 'save/', json.dumps(body), content_type='application/json')

    def _file(self):
        return (Path(settings.MEDIA_ROOT) / self.rel).read_text(encoding='utf-8')

    def test_the_page_reads_the_text_of_the_file(self):
        data = self.client.get(self.base + 'data/').json()
        self.assertEqual('# Title\nFirst text.\n', data['value'])
        self.assertTrue(data['token'])

    def test_a_save_rewrites_the_file_in_place_and_stales_the_downstream_process(self):
        from wama.anonymizer.function_specs import PIPELINE
        from wama.common.models import ItemRevision
        from wama.common.services import process_runs
        process_runs.succeed(self.media, 'detect', output_ref=self.rel, process_key='anonymizer.detect',
                             settings_snapshot=PIPELINE.snapshot(PIPELINE.spec('detect'), self.media))
        process_runs.succeed(self.media, 'blur', process_key='anonymizer.blur',
                             settings_snapshot=PIPELINE.snapshot(PIPELINE.spec('blur'), self.media))
        token = self.client.get(self.base + 'data/').json()['token']
        res = self._save('# Title\r\nCorrected text.\n', base=token)
        self.assertEqual(200, res.status_code, res.content)
        self.assertEqual('# Title\nCorrected text.\n', self._file(), 'line endings normalised')
        self.media.refresh_from_db()
        self.assertEqual(self.rel, self.media.detections_file.name, 'same path : the process row still designates it')
        self.assertEqual(['blur'], res.json()['stale'], 'the new fingerprint stales the downstream process')
        revision = ItemRevision.objects.get(app='anonymizer', object_id=self.media.pk)
        self.assertEqual(ItemRevision.ORIGIN_MANUAL, revision.origin)
        self.assertEqual(['detections_file'], [o['field'] for o in revision.outputs])

    def test_an_unchanged_text_writes_nothing(self):
        from wama.common.models import ItemRevision
        res = self._save('# Title\nFirst text.\n')
        self.assertEqual(200, res.status_code, res.content)
        self.assertFalse(ItemRevision.objects.filter(app='anonymizer', object_id=self.media.pk).exists())

    def test_a_stale_base_is_refused_and_the_file_is_untouched(self):
        res = self._save('Overwritten.\n', base='not-the-current-state')
        self.assertEqual(409, res.status_code)
        self.assertEqual('# Title\nFirst text.\n', self._file())

    def test_a_file_another_row_designates_is_never_rewritten(self):
        from wama.anonymizer.models import Media
        from wama.common.services import process_runs
        Media.objects.create(user=self.user, file_ext='.png', media_type='image', detections_file=self.rel)
        process_runs.succeed(self.media, 'detect', output_ref=self.rel, process_key='anonymizer.detect')
        res = self._save('# Title\nMine only.\n')
        self.assertEqual(200, res.status_code, res.content)
        self.assertEqual('# Title\nFirst text.\n', self._file(), 'the other holder keeps its file')
        self.media.refresh_from_db()
        new = self.media.detections_file.name
        self.assertNotEqual(self.rel, new)
        self.assertEqual('# Title\nMine only.\n', (Path(settings.MEDIA_ROOT) / new).read_text(encoding='utf-8'))
        self.assertEqual(new, process_runs.line(self.media, 'detect').output_ref,
                         'the process row follows : its output is not taken for lost')

    def test_an_empty_file_field_names_the_process_that_produces_it(self):
        type(self.media).objects.filter(pk=self.media.pk).update(detections_file='')
        self.assertEqual(409, self.client.get(self.base + 'data/').status_code)
        self.assertContains(self.client.get(self.base), 'Détection')

    def test_a_non_string_value_is_refused(self):
        self.assertEqual(400, self._save({'not': 'text'}).status_code)


class ScoreRulesTest(SimpleTestCase):
    """`wama-score.js` — what the score brick does without a DOM : which notes sound at a time
    (voice by voice), where a clicked note starts, how a dragged note is rewritten."""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.engine = MiniRacer()
        self.engine.eval('var window = {};' + _js('common/js/wama-score.js'))

    def _call(self, expr):
        return json.loads(self.engine.eval('JSON.stringify(window.WamaScore.%s)' % expr))

    def _transpose(self, abc, note, step):
        start = abc.index(note)
        return self._call('transposeAt(%s, %d, %d, %d)' % (json.dumps(abc), start, start + len(note), step))

    def test_a_dragged_note_moves_by_degrees_and_follows_the_key(self):
        abc = 'K:C\nC2 ^F/2 "Am"[CEG]2 c\' B,|'
        self.assertEqual('K:C\nD2 ^F/2 "Am"[CEG]2 c\' B,|', self._transpose(abc, 'C2', -1), 'up one degree')
        self.assertEqual('K:C\nB,2 ^F/2 "Am"[CEG]2 c\' B,|', self._transpose(abc, 'C2', 1), 'down across the octave')
        self.assertEqual('K:C\nC2 G/2 "Am"[CEG]2 c\' B,|', self._transpose(abc, '^F/2', -1),
                         'the written accidental is dropped : the moved note follows the key')
        self.assertEqual('K:C\nC2 ^F/2 "Am"[A,CE]2 c\' B,|', self._transpose(abc, '"Am"[CEG]2', 2),
                         'a chord moves as a block, its chord symbol does not')
        self.assertEqual("K:C\nC2 ^F/2 \"Am\"[CEG]2 d' B,|", self._transpose(abc, "c'", -1))
        self.assertEqual('K:C\nC2 ^F/2 "Am"[CEG]2 c\' A,|', self._transpose(abc, 'B,', 1))
        self.assertEqual(abc, self._transpose(abc, 'C2', 0), 'no step, no change')

    def test_each_voice_keeps_its_sounding_note_lit(self):
        tl = ('timeline([{ms: 0, sets: [{voice: 0, ref: "a"}, {voice: 1, ref: "x"}]},'
              ' {ms: 1000, sets: [{voice: 0, ref: "b"}]}, {ms: 2000, sets: [{voice: 0, ref: "c"}]},'
              ' {ms: 2500, sets: [{voice: 1, ref: "y"}]}], 3000)')
        at = lambda ms: sorted(self._call('playingAt(%s, %d)' % (tl.replace('timeline', 'window.WamaScore.timeline'), ms)))
        self.assertEqual(['a', 'x'], at(500))
        self.assertEqual(['b', 'x'], at(1500), "a long note of one voice stays lit while the other moves")
        self.assertEqual(['c', 'y'], at(2600))
        self.assertEqual([], at(3000), 'nothing after the end')
        self.assertEqual([], at(-1))

    # The measured case (#754, 2026-10-16) : written at 88 (0.682 s a beat), played at 89.1
    # (0.673 s), the pickup on written beat 3, the music starting at 0.8 s.
    ALIGN_SETUP = '''
        // A tune that REPEATS every 12 beats, like a chorus : a shift of a whole period sounds the
        // same — the alignment must still pick the right one.
        var melody = [0, 4, 7, 2, 5, 9, 11, 0, 7, 4, 2, 9];
        var notes = [];
        for (var b = 3; b < 60; b++) notes.push({beat: b, pcs: [melody[b % 12]]});
        function grid(step, perWritten) {
            var beats = [], chroma = [];
            for (var i = 0; i < 80 * perWritten; i++) {
                beats.push(0.8 + i * step);
                var written = Math.floor(i / perWritten) + 3;      // played beat 0 = written beat 3
                var v = [20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20];
                v[melody[written % 12]] = 255;
                chroma.push(v);
            }
            return {beats: beats, chroma: chroma};
        }
    '''

    def _align(self, script):
        return json.loads(self.engine.eval('(function(){' + self.ALIGN_SETUP + script + '})()'))

    def test_the_written_beats_are_set_on_the_played_beats_pickup_included(self):
        out = self._align('''
            var a = window.WamaScore.align(notes, 0.682, grid(0.673, 1));
            return JSON.stringify({shift: a.shift, pickup: a.toAudio(3), late: a.toAudio(53),
                                   back: a.toScore(a.toAudio(10.5))});''')
        self.assertEqual(-3, out['shift'], 'the pickup is anchored by the pitches that sound')
        self.assertAlmostEqual(0.8, out['pickup'], places=3)
        self.assertAlmostEqual(0.8 + 50 * 0.673, out['late'], places=3,
                               msg='fifty beats on, the rounded written tempo has not drifted')
        self.assertAlmostEqual(10.5, out['back'], places=6)

    def test_a_grid_found_at_twice_the_written_tempo_is_folded_back(self):
        out = self._align('''
            var a = window.WamaScore.align(notes, 0.682, grid(0.3365, 2));
            return JSON.stringify({pickup: a.toAudio(3), next: a.toAudio(4)});''')
        self.assertAlmostEqual(0.8, out['pickup'], places=3)
        self.assertAlmostEqual(0.8 + 0.673, out['next'], places=3)

    def test_without_a_grid_or_notes_there_is_no_alignment(self):
        self.assertIsNone(self._align('return JSON.stringify(window.WamaScore.align(notes, 0.682, null));'))
        self.assertIsNone(self._align('return JSON.stringify(window.WamaScore.align([], 0.682, grid(0.673, 1)));'))

    def test_a_clicked_note_gives_its_time_and_its_voice(self):
        timings = json.dumps([{'type': 'bar', 'milliseconds': 0},
                              {'type': 'event', 'milliseconds': 750, 'startCharArray': [12, 40]}])
        self.assertEqual(750, self._call('eventTime(%s, 40)' % timings))
        self.assertIsNone(self._call('eventTime(%s, 99)' % timings))
        self.assertEqual(1, self._call('voiceOf("abcjs-note abcjs-v1 abcjs-n2")'))
        self.assertEqual(12, self._call('voiceOf("abcjs-v12")'))
        self.assertEqual(0, self._call('voiceOf("")'))


class AxisTest(SimpleTestCase):
    """`wama-axis.js` — the shared time axis, run under V8 with an injected clock : commands move
    the axis, observers follow, an attached medium is the CLOCK forward and is silenced backward."""

    SETUP = '''
        var window = {}; var T = 0, pending = null;
        var opts = {now: function () { return T; }, frame: function (fn) { pending = fn; return 1; },
                    cancelFrame: function () { pending = null; }};
        function step(ms) { T += ms; var fn = pending; pending = null; if (fn) fn(T); }
        function fakeMedia(duration) {
            var listeners = {};
            var m = {currentTime: 0, duration: duration, paused: true, playbackRate: 1,
                     addEventListener: function (k, fn) { (listeners[k] = listeners[k] || []).push(fn); },
                     removeEventListener: function () {},
                     fire: function (k) { (listeners[k] || []).forEach(function (fn) { fn(); }); },
                     play: function () { m.paused = false; m.fire('play'); return null; },
                     pause: function () { m.paused = true; m.fire('pause'); }};
            return m;
        }
    '''

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.engine = MiniRacer()
        self.engine.eval(self.SETUP + _js('common/js/wama-axis.js'))

    def _eval(self, script):
        return json.loads(self.engine.eval('JSON.stringify((function(){' + script + '})())'))

    def test_commands_move_the_axis_and_observers_follow(self):
        out = self._eval('''
            var axis = window.WamaAxis.create(Object.assign({duration: 10}, opts)), seen = [];
            axis.subscribe(function (s) { seen.push(s.reason); });
            axis.seek(12); var clamped = axis.time(); axis.seek(-3); var floor = axis.time();
            axis.play(); step(1000); var played = axis.time();
            axis.setRate(-2); step(250); var back = axis.time(); step(400);
            var stopped = [axis.time(), axis.playing()];
            axis.jump(4); axis.shuttle(0);
            return {clamped: clamped, floor: floor, played: played, back: back, stopped: stopped,
                    jumped: axis.time(), rate: axis.rate(), first: seen[0]};
        ''')
        self.assertEqual(10, out['clamped'])
        self.assertEqual(0, out['floor'])
        self.assertAlmostEqual(1.0, out['played'])
        self.assertAlmostEqual(0.5, out['back'], msg='backward at twice the speed')
        self.assertEqual([0, False], out['stopped'], 'backward play stops at the start')
        self.assertEqual(4, out['jumped'])
        self.assertEqual(1, out['rate'], 'the shuttle stop resets the speed')
        self.assertEqual('subscribe', out['first'], 'an observer gets the present state at once')

    def test_an_attached_medium_is_the_clock_forward_and_silent_backward(self):
        out = self._eval('''
            var axis = window.WamaAxis.create(opts), media = fakeMedia(8);
            axis.attach(media);
            var duration = axis.duration();
            axis.play(); var audible = !media.paused;
            media.currentTime = 3; step(16); var followed = axis.time();
            axis.setRate(-1); var silenced = media.paused; var stillPlaying = axis.playing();
            step(1000);
            var back = [axis.time(), media.currentTime];
            axis.setRate(1); var resumed = !media.paused;
            media.pause(); var userPaused = !axis.playing();
            media.currentTime = 6; media.fire('seeked');
            return {duration: duration, audible: audible, followed: followed, silenced: silenced,
                    stillPlaying: stillPlaying, back: back, resumed: resumed, userPaused: userPaused,
                    sought: axis.time()};
        ''')
        self.assertEqual(8, out['duration'], 'the medium gives its duration')
        self.assertTrue(out['audible'])
        self.assertEqual(3, out['followed'], "forward, the medium's time is the axis time")
        self.assertTrue(out['silenced'])
        self.assertTrue(out['stillPlaying'], 'pausing the medium for backward play does not stop the axis')
        self.assertAlmostEqual(2.0, out['back'][0], places=2)
        self.assertAlmostEqual(2.0, out['back'][1], places=2, msg='the medium is set back in step')
        self.assertTrue(out['resumed'], 'forward again : the medium plays again')
        self.assertTrue(out['userPaused'], 'a pause made on the medium itself stops the axis')
        self.assertEqual(6, out['sought'], 'a seek made on the medium itself moves the axis')

    def test_times_are_written_and_read_back(self):
        self.assertEqual('1:23.4', self._eval('return window.WamaAxis.formatTime(83.45, true);'))
        self.assertEqual('1:02:05', self._eval('return window.WamaAxis.formatTime(3725);'))
        self.assertAlmostEqual(83.4, self._eval('return window.WamaAxis.parseTime("1:23.4");'))
        self.assertIsNone(self._eval('return window.WamaAxis.parseTime("x");'))


ABC = 'X:1\nM:4/4\nL:1/8\nQ:1/4=80\nK:C\nC2 D2 E2 F2|G8|\n'


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ComposerScoreSurfaceTest(TestCase):
    """The composer's `score` surface : a score written by EITHER of two alternative processes is
    edited as text ; correcting it keeps the original as a version, then stales the render."""

    def setUp(self):
        from wama.common.utils.media_paths import app_media_dir, get_app_media_path
        from wama.composer.models import ComposerGeneration
        self.addCleanup(shutil.rmtree, settings.MEDIA_ROOT, True)
        self.user = get_user_model().objects.create_user('score_owner', password='x')
        out = get_app_media_path('composer', self.user.id, 'output')
        out.mkdir(parents=True, exist_ok=True)
        (out / 'score_extracted.abc').write_text(ABC, encoding='utf-8')
        self.rel = f"{app_media_dir('composer', self.user.id, 'output')}/score_extracted.abc"
        self.gen = ComposerGeneration.objects.create(user=self.user, prompt='pop', extracted_score=self.rel)
        self.base = f'/common/surface/composer/score/{self.gen.pk}/'
        self.client.force_login(self.user)

    def _save(self, value, base=None):
        body = {'value': value, **({'base': base} if base else {})}
        return self.client.post(self.base + 'save/', json.dumps(body), content_type='application/json')

    def test_the_page_composes_the_score_the_transport_and_the_versions(self):
        from wama.common.surfaces import surface
        score = surface('composer', 'score')
        self.assertEqual(['score_view', 'score_view', 'media_transport', 'text_sections',
                          'revision_history', 'surface_actions'], [s.brick for s in score.slots])
        self.assertEqual('parts', score.slots[1].options['role'], 'the full score, read only')
        scripts = score.scripts()
        self.assertLess(scripts.index('vendors/abcjs-6.4.4/abcjs-basic-min.js'),
                        scripts.index('common/js/surfaces/brick-score-view.js'))
        self.assertEqual(1, scripts.count('common/js/wama-axis.js'), 'one axis module for two bricks')
        page = self.client.get(self.base)
        self.assertEqual(200, page.status_code)
        self.assertContains(page, 'abcjs-6.4.4/abcjs-basic-min.js')
        self.assertContains(page, 'brick-media-transport.js')

    def test_the_filled_alternative_is_the_one_edited(self):
        from wama.common.surfaces import surface
        score = surface('composer', 'score')
        self.assertEqual('extracted_score', score.edited(self.gen))
        data = self.client.get(self.base + 'data/').json()
        self.assertEqual(ABC, data['value'])
        self.assertEqual('', data['reads']['audio'], 'no render yet : nothing to play')
        type(self.gen).objects.filter(pk=self.gen.pk).update(planned_score=self.rel)
        self.gen.refresh_from_db()
        self.assertEqual('planned_score', score.edited(self.gen), 'the declared order decides')

    def test_a_correction_keeps_the_original_as_a_version_and_stales_the_render(self):
        from wama.common.models import ItemRevision
        from wama.common.services import process_runs
        from wama.composer.function_specs import PIPELINE
        process_runs.succeed(self.gen, 'extract_score', output_ref=self.rel, process_key='composer.extract_score',
                             settings_snapshot=PIPELINE.snapshot(PIPELINE.spec('extract_score'), self.gen))
        process_runs.succeed(self.gen, 'render', process_key='composer.render',
                             settings_snapshot=PIPELINE.snapshot(PIPELINE.spec('render'), self.gen))
        token = self.client.get(self.base + 'data/').json()['token']
        corrected = ABC.replace('C2 D2', 'D2 D2')
        res = self._save(corrected, base=token)
        self.assertEqual(200, res.status_code, res.content)
        self.assertIn('render', res.json()['stale'], 'the render follows the corrected score')
        origins = list(ItemRevision.objects.filter(app='composer', object_id=self.gen.pk)
                       .order_by('number').values_list('origin', flat=True))
        self.assertEqual([ItemRevision.ORIGIN_PROCESS, ItemRevision.ORIGIN_MANUAL], origins,
                         'the extracted original is kept BEFORE it is rewritten in place')
        listed = self.client.get(self.base + 'revisions/').json()
        self.assertTrue(listed['keeps'])
        self.assertTrue(all(r['kept'] for r in listed['revisions']))
        self.assertEqual(ABC, self.client.get(self.base + 'revisions/1/').json()['value'])
        self.assertEqual(corrected, self.client.get(self.base + 'revisions/2/').json()['value'])

    def test_the_full_score_is_read_as_text_and_never_as_a_beat_grid(self):
        data = self.client.get(self.base + 'data/').json()
        self.assertEqual('', data['reads']['parts'], 'no full score yet')
        parts = self.rel.replace('score_extracted.abc', 'score_parts.abc')
        (Path(settings.MEDIA_ROOT) / parts).write_text('X:1\nV:I0\nK:C\nC4|\n', encoding='utf-8')
        type(self.gen).objects.filter(pk=self.gen.pk).update(parts_score=parts)
        data = self.client.get(self.base + 'data/').json()
        self.assertEqual('X:1\nV:I0\nK:C\nC4|\n', data['reads']['parts'], 'its text, not its URL')
        self.assertEqual(ABC, data['value'], 'the edited score is still the melody')
        self.assertIsNone(self.client.get(self.base + 'data/?only=rhythm&role=parts').json()['rhythm'])

    def test_only_the_score_is_kept_never_the_render(self):
        from wama.common.services.revisions import record_revision
        audio = Path(settings.MEDIA_ROOT) / self.rel.replace('score_extracted.abc', 'song.wav')
        audio.write_bytes(b'RIFF' + b'\0' * 64)
        type(self.gen).objects.filter(pk=self.gen.pk).update(audio_output=self.rel.replace('.abc', '.wav')
                                                             .replace('score_extracted', 'song'))
        self.gen.refresh_from_db()
        record_revision('composer', self.gen, output_fields=['audio_output', 'extracted_score'])
        self.gen.refresh_from_db()
        self.assertEqual(['extracted_score'], [e['field'] for e in self.gen.kept_outputs],
                         'a render is redone from its score : twenty copies of it are not kept')

    def test_the_beat_grid_of_the_audio_is_served_on_demand(self):
        """A real click track at 120 per minute : the grid finds a beat every half second."""
        import soundfile as sf
        rate = 22050
        track = np.zeros(rate * 12, dtype=np.float32)
        burst = np.sin(2 * np.pi * 880 * np.arange(int(0.03 * rate)) / rate).astype(np.float32)
        for start in range(int(0.5 * rate), len(track) - len(burst), int(0.5 * rate)):
            track[start:start + len(burst)] = burst
        rel = self.rel.replace('score_extracted.abc', 'clicks.wav')
        sf.write(str(Path(settings.MEDIA_ROOT) / rel), track, rate)
        type(self.gen).objects.filter(pk=self.gen.pk).update(audio_output=rel)
        grid = self.client.get(self.base + 'data/?only=rhythm&role=audio').json()['rhythm']
        gaps = np.diff(grid['beats'])
        self.assertAlmostEqual(0.5, float(np.median(gaps)), delta=0.03)
        self.assertEqual(len(grid['beats']), len(grid['chroma']))
        self.assertTrue(all(len(c) == 12 and max(c) <= 255 for c in grid['chroma']))
        self.assertIsNone(self.client.get(self.base + 'data/?only=rhythm&role=nope').json()['rhythm'])

    def test_an_unchanged_score_keeps_nothing(self):
        from wama.common.models import ItemRevision
        self.assertEqual(200, self._save(ABC).status_code)
        self.assertFalse(ItemRevision.objects.filter(app='composer', object_id=self.gen.pk).exists())

    def test_a_model_that_composes_without_a_score_says_so(self):
        from wama.composer.models import ComposerGeneration
        plain = ComposerGeneration.objects.create(user=self.user, prompt='rain', model='composer:musicgen-small')
        page = self.client.get(f'/common/surface/composer/score/{plain.pk}/')
        self.assertContains(page, 'compose sans partition')

    def test_someone_else_neither_reads_nor_writes(self):
        other = get_user_model().objects.create_user('score_other', password='x')
        self.client.force_login(other)
        self.assertEqual(404, self.client.get(self.base + 'data/').status_code)
        self.assertEqual(404, self._save('X:1\n').status_code)


class SurfacesGeneratorTest(SimpleTestCase):
    """A generated app DECLARES its surfaces in its manifest ; `surfaces.py` is rendered (rule D5 :
    only the manifest is written by hand)."""

    def _manifest(self):
        path = Path(settings.BASE_DIR) / 'manifests' / 'app_drafts' / 'writer.json'
        return json.loads(path.read_text(encoding='utf-8'))

    def test_the_writer_surface_is_rendered_from_its_manifest(self):
        from wama.common.manifests.codegen.surfaces_gen import render_surfaces
        src, reason = render_surfaces(self._manifest())
        self.assertIsNone(reason)
        compile(src, 'surfaces.py', 'exec')
        self.assertIn("edits='draft_file'", src)
        self.assertIn("reruns='layout'", src)
        self.assertIn("_APP = __name__.rsplit('.', 2)[-2]", src, 'the label is never written in full')

    def test_what_cannot_be_declared_is_refused_with_its_reason(self):
        from wama.common.manifests.codegen.surfaces_gen import render_surfaces
        cases = {
            'brick': ('slots', 0, 'brick', 'no_such_brick', 'brique inconnue'),
            'grid': ('slots', 0, 'w', 13, 'hors de la grille'),
        }
        for name, (facet, index, field, value, expected) in cases.items():
            with self.subTest(case=name):
                m = self._manifest()
                m['body']['surfaces'][0][facet][index][field] = value
                self.assertIn(expected, render_surfaces(m)[1])
        m = self._manifest()
        m['body']['surfaces'][0]['edits'] = 'prompt'
        self.assertIn("n'est la sortie d'aucun process", render_surfaces(m)[1],
                      'a data field carries its validation in Python : never generated')
        m = self._manifest()
        m['body']['surfaces'][0]['reruns'] = 'publish'
        self.assertIn('process rejoué inconnu', render_surfaces(m)[1])
        m = self._manifest()
        del m['body']['surfaces']
        self.assertIsNone(render_surfaces(m)[0])
