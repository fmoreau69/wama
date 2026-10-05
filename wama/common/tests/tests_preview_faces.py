"""Faces d'aperçu DÉCLARÉES par une app, et Comparer sur des vidéos (2026-10-05, demande de
Fabien : voir la détection de l'anonymizer APRÈS le traitement, « la même formule » que le mode
Comparer des autres apps).

Held here : the « Détection » face exists once the detection ran, serves the INPUT with the
detections document as an overlay, is the reference side of Compare ; Compare is offered for two
videos (not only two images) ; an app that declares no face keeps the old shape.
"""
import json
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from wama.anonymizer.models import Media
from wama.common.utils.media_paths import app_media_dir


class DetectionFaceOfTheAnonymizerTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root, MEDIA_URL='/media/')
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('preview_faces_owner', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)

    def _file(self, sub, name, data=b'x'):
        rel = f"{app_media_dir('anonymizer', self.user.id, sub)}/{name}"
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as out:
            out.write(data)
        return rel

    def _media(self, **kw):
        return Media.objects.create(user=self.user, file=self._file('input', 'street.mp4'),
                                    file_ext='.mp4', media_type='video', status='SUCCESS', **kw)

    def _preview(self, media, side=None):
        url = f'/common/preview/anonymizer/{media.pk}/' + (f'?side={side}' if side else '')
        return self.client.get(url).json()

    def test_after_the_detection_the_face_serves_the_input_with_its_detections(self):
        doc = self._file('output', 'street_detections_yolo_1.json',
                         json.dumps({'kind': 'detections', 'frames': []}).encode())
        media = self._media(detections_file=doc,
                            output_file=self._file('output', 'street_blurred_yolo_1.mp4'))
        sides = self._preview(media)['sides']
        self.assertEqual([{'key': 'detection', 'label': 'Détection', 'icon': 'fa-vector-square'}],
                         sides['faces'])
        self.assertEqual('detection', sides['compare_base'])
        self.assertTrue(sides['comparable'], 'two videos are comparable now')
        face = self._preview(media, 'detection')
        self.assertEqual('detection', face['side'])
        self.assertTrue(face['url'].endswith('/street.mp4'), 'the INPUT is shown')
        self.assertIn('street_detections_yolo_1.json', face['overlay']['url'])
        self.assertEqual('detections', face['overlay']['kind'])
        self.assertTrue(face['overlay']['boxes'])

    def test_before_the_detection_there_is_no_face_and_compare_goes_back_to_the_input(self):
        media = self._media(output_file=self._file('output', 'street_blurred_yolo_2.mp4'))
        sides = self._preview(media)['sides']
        self.assertEqual([], sides['faces'])
        self.assertEqual('input', sides['compare_base'])
        self.assertTrue(sides['comparable'])
        self.assertEqual('input', self._preview(media, 'detection')['side'],
                         'an absent face falls back to the input')

    def test_the_display_settings_of_the_card_follow_the_overlay(self):
        doc = self._file('output', 'street_detections_yolo_3.json', b'{"kind": "detections"}')
        media = self._media(detections_file=doc, show_boxes=False, show_conf=False)
        overlay = self._preview(media, 'detection')['overlay']
        self.assertEqual((False, True, False),
                         (overlay['boxes'], overlay['labels'], overlay['confidence']))


class CompareLetsBothVideosPlayTest(TestCase):
    """The common « exclusive playback » (`wama-app-base.js`) pauses every other media when one
    starts : the compared video started by the sync paused the reference at once (seen in the
    browser on 2026-10-05). Since 2026-10-06 the panel and the modal build Compare with ONE common
    view (`WamaInspector.compareView` : the output laid OVER the reference, a slider — the modal
    showed two videos side by side) : the escape hatch lives there, and both surfaces use it."""

    @staticmethod
    def _body(name, function, indent='    '):
        from django.conf import settings
        path = os.path.join(settings.BASE_DIR, 'wama', 'common', 'static', 'common', 'js', name)
        with open(path, encoding='utf-8') as source:
            text = source.read()
        body = text[text.index(function):]
        return body[:body.index('\n' + indent + '}\n')]

    def test_the_common_compare_view_lets_the_two_videos_play_together(self):
        view = self._body('wama-inspector.js', 'function compareView', indent='  ')
        self.assertIn("setAttribute('data-wama-multiplay'", view)
        self.assertIn('syncVideos', view)
        self.assertIn('wama-compare-top', view, 'the output laid over the reference')
        self.assertIn('wama-compare-range', view, 'a slider')

    def test_the_panel_and_the_modal_build_compare_with_the_common_view(self):
        self.assertIn('compareView(', self._body('wama-inspector.js', 'function _renderCompare'))
        modal = self._body('media-preview.js', 'function _modalCompare')
        self.assertIn('I.compareView(', modal)
        self.assertNotIn('buildPreviewContent', modal, 'no more side-by-side copies')
