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
