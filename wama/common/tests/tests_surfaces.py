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
        from py_mini_racer import MiniRacer
        from wama.common.surfaces import BRICKS
        paths = {p for b in BRICKS.values() for p in b.scripts()} | {'common/js/surfaces/wama-surface.js'}
        for path in sorted(paths):
            with self.subTest(script=path):
                self.assertTrue((STATIC / path).is_file(), path)
                # Parse WITHOUT executing (the bricks touch the DOM) : a function wrapping it.
                MiniRacer().eval('(function(){' + _js(path) + '})')

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
