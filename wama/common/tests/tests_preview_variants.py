"""The « during » preview publishes several VIEWS of the same instant (2026-10-04) — the
anonymizer shows the frame with its detections drawn AND the blurred frame, and the inspector
switches between them (`?side=during&variant=<key>`). Held here : the last published view is the
default, a requested one is served, the list says every view, `clear_partial` forgets them ; and
the frame publisher writes, throttles and cleans up.
"""
import os
import shutil
import tempfile
from unittest import mock

import numpy as np
from django.test import RequestFactory, SimpleTestCase, override_settings

from wama.common.utils import preview_utils

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'preview-variants-tests'}}


@override_settings(CACHES=LOCMEM)
class DuringVariantsTest(SimpleTestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        capable = mock.patch('wama.common.app_registry.app_supports_during_preview',
                             return_value=True)
        capable.start()
        self.addCleanup(capable.stop)
        self.item = mock.Mock(pk=41)

    def _during(self, **query):
        request = RequestFactory().get('/preview/', query)
        return preview_utils._during_preview_data('anonymizer', self.item, request)

    def test_the_last_published_view_is_the_default_and_a_requested_one_is_served(self):
        preview_utils.publish_partial('anonymizer', 41, '/media/d.jpg?v=1', variant='detection',
                                      label='Détection')
        preview_utils.publish_partial('anonymizer', 41, '/media/b.jpg?v=1', variant='blur',
                                      label='Floutage')
        data = self._during()
        self.assertEqual('blur', data['variant'])
        self.assertTrue(data['url'].endswith('/media/b.jpg?v=1'))
        self.assertEqual([{'key': 'detection', 'label': 'Détection'},
                          {'key': 'blur', 'label': 'Floutage'}], data['variants'])
        asked = self._during(variant='detection')
        self.assertEqual('detection', asked['variant'])
        self.assertTrue(asked['url'].endswith('/media/d.jpg?v=1'))
        self.assertEqual('blur', self._during(variant='unknown')['variant'])

    def test_a_view_published_again_becomes_the_default(self):
        for variant in ('detection', 'blur', 'detection'):
            preview_utils.publish_partial('anonymizer', 41, f'/media/{variant}.jpg',
                                          variant=variant, label=variant)
        self.assertEqual('detection', self._during()['variant'])

    def test_a_single_url_without_variant_keeps_the_old_shape(self):
        preview_utils.publish_partial('anonymizer', 41, '/media/p.jpg')
        data = self._during()
        self.assertNotIn('variants', data)
        self.assertTrue(data['url'].endswith('/media/p.jpg'))

    def test_clearing_forgets_every_view(self):
        preview_utils.publish_partial('anonymizer', 41, '/media/d.jpg', variant='detection')
        preview_utils.clear_partial('anonymizer', 41)
        self.assertIsNone(self._during())


@override_settings(CACHES=LOCMEM)
class PartialFramesTest(SimpleTestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root, MEDIA_URL='/media/')
        media.enable()
        self.addCleanup(media.disable)

    def test_it_writes_each_view_throttles_and_cleans_up(self):
        from django.core.cache import cache
        folder = os.path.join(self.root, 'anonymizer', 'partials')
        frames = preview_utils.PartialFrames('anonymizer', 7, folder, every=60)
        self.assertTrue(frames.due())
        image = np.zeros((8, 8, 3), dtype=np.uint8)
        frames.publish({'detection': ('Détection', image), 'blur': ('Floutage', image)}, index=12)
        self.assertFalse(frames.due(), 'throttled until `every` seconds have passed')
        written = sorted(os.listdir(folder))
        self.assertEqual(['during_7_blur.jpg', 'during_7_detection.jpg'], written)
        variants = cache.get(preview_utils._partial_variants_key('anonymizer', 7))
        self.assertEqual('/media/anonymizer/partials/during_7_blur.jpg?v=12',
                         variants['blur']['url'])
        frames.close()
        self.assertEqual([], os.listdir(folder))
        self.assertIsNone(cache.get(preview_utils._partial_variants_key('anonymizer', 7)))

    def test_an_already_encoded_jpeg_is_written_as_is(self):
        """The 3D render of the avatarizer yields JPEG bytes: no decode/re-encode round trip."""
        folder = os.path.join(self.root, 'avatarizer', 'partials')
        frames = preview_utils.PartialFrames('avatarizer', 9, folder)
        jpeg = b'\xff\xd8\xff\xe0witness-jpeg\xff\xd9'
        frames.publish({'animation': ('Animation', jpeg)}, index=50)
        with open(os.path.join(folder, 'during_9_animation.jpg'), 'rb') as written:
            self.assertEqual(jpeg, written.read())
        frames.close()


class NoAppWritesItsOwnPartialFrameTest(SimpleTestCase):
    """Generic over the apps : a FRAME published to the « during » preview goes through
    `PartialFrames` (2026-10-04). The enhancer copied the anonymizer's hand-written publisher —
    path, URL, publication, and no cleanup of its JPEG — which the brick now holds once."""

    def test_no_app_module_writes_an_image_and_publishes_it_by_hand(self):
        from pathlib import Path
        from django.conf import settings
        offenders = []
        for root in ('wama', 'wama_lab'):
            for path in (Path(settings.BASE_DIR) / root).rglob('*.py'):
                if 'tests' in path.name or 'common' in path.parts or 'migrations' in path.parts:
                    continue
                text = path.read_text(encoding='utf-8', errors='ignore')
                if 'publish_partial(' in text and 'imwrite(' in text:
                    offenders.append(str(path.relative_to(settings.BASE_DIR)))
        self.assertEqual([], offenders, 'use `preview_utils.PartialFrames`')


class DuringPreviewCriterionKnowsTheBrickTest(SimpleTestCase):
    """The grid criterion `during_preview` reads the EMISSION in the app's code : an app that
    publishes through `PartialFrames` emits (the anonymizer and the enhancer went red the day
    they adopted it — a criterion behind its mechanism)."""

    def test_an_app_that_publishes_through_the_brick_emits(self):
        from wama.common.tests import tests_queue_delete_contract as contract
        f, cc = contract.CriteresDeLaGrilleTest._app(self, {
            'tasks.py': "frames = PartialFrames('app', 1, folder)\n"})
        criterion = next(c for c in cc.CRITERIA if c.key == 'during_preview')
        self.assertIs(True, criterion.fn(f)[0])
        f, cc = contract.CriteresDeLaGrilleTest._app(self, {'tasks.py': "x = 1\n"})
        self.assertIs(False, criterion.fn(f)[0], 'counter-proof : no emission, red')
