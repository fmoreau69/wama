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
