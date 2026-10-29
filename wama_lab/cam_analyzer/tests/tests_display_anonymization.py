"""Anonymisation des vidéos pour l'AFFICHAGE (passes `anonymize_detect` / `anonymize_blur`,
2026-10-12) : les fenêtres découpées comme pour la détection YOLO, les détections ramenées aux
indices de la vidéo, l'image entière floutée hors des fenêtres, la vidéo floutée de même longueur
que l'originale, et une branche qui ne part jamais sans être nommée.

    python manage.py test wama_lab.cam_analyzer.tests.tests_display_anonymization --keepdb
"""
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from django import test as django_test

from wama_lab.cam_analyzer.utils import display_anonymization as anon
from wama_lab.cam_analyzer.utils import pass_tracking as pt
from wama_lab.cam_analyzer.utils.window_clips import (ffmpeg_path, merge_frame_ranges,
                                                      window_frame_ranges)


class WindowRangesTest(unittest.TestCase):

    def test_overlapping_and_adjacent_ranges_merge(self):
        self.assertEqual(merge_frame_ranges([(10, 20), (0, 5), (6, 8), (18, 30)]),
                         [(0, 8), (10, 30)])

    def test_windows_become_frame_ranges_bounded_to_the_video(self):
        windows = [{'t_enter': 1.0, 't_exit': 2.0}, {'t_enter': 9.5, 't_exit': 20.0},
                   {'t_enter': 30.0, 't_exit': 31.0}]
        self.assertEqual(window_frame_ranges(windows, fps=10, total_frames=100),
                         [(10, 20), (95, 99)])


class OutsideWindowsTest(unittest.TestCase):

    def test_a_frame_outside_every_range_gets_the_whole_image(self):
        whole = {'label': anon.OUTSIDE_LABEL, 'box': [0, 0, 4, 4]}
        seen = {'label': 'face', 'box': [1, 1, 2, 2]}
        frames = anon._FramesWithOutside({3: [seen]}, [[2, 4], [8, 9]], whole)
        self.assertEqual(frames.get(3, []), [seen])
        self.assertEqual(frames.get(2, []), [], "dans une plage, sans détection : rien à flouter")
        self.assertEqual(frames.get(9, []), [])
        self.assertEqual(frames.get(5, []), [whole])
        self.assertEqual(frames.get(0, []), [whole])
        self.assertEqual(frames.get(10, []), [whole])


class ConfidenceFloorTest(unittest.TestCase):
    """Le seuil du floutage (2026-10-26) : ce qui passe sous lui n'est plus flouté."""

    def test_detections_under_the_floor_are_dropped_and_empty_frames_with_them(self):
        doc = {'kind': 'detections', 'frames': [
            {'i': 1, 'd': [{'label': 'plate', 'conf': 0.10}, {'label': 'face', 'conf': 0.60}]},
            {'i': 2, 'd': [{'label': 'plate', 'conf': 0.12}]},
            {'i': 3, 'd': [{'label': 'plate'}]}]}
        kept = anon.confident(doc, 0.25)
        self.assertEqual([f['i'] for f in kept['frames']], [1, 3])
        self.assertEqual(kept['frames'][0]['d'], [{'label': 'face', 'conf': 0.60}])
        self.assertEqual(kept['frames'][1]['d'], [{'label': 'plate'}],
                         "une détection sans confiance est gardée")
        self.assertEqual(len(doc['frames']), 3, "le document lu n'est pas modifié")

    def test_a_floor_of_zero_keeps_everything(self):
        doc = {'frames': [{'i': 1, 'd': [{'conf': 0.0}, {'conf': 0.10}]}]}
        self.assertEqual(anon.confident(doc, 0.0), doc)

    def test_each_class_has_its_own_floor_under_the_detector_name(self):
        """Un seuil par classe (2026-10-28) : relever les plaques ne touche pas aux visages. La
        détection se nomme comme son jeu de poids (`license_plate`), le seuil comme le profil
        (`plate`) ; une classe sans seuil propre prend le seuil commun."""
        doc = {'frames': [{'i': 1, 'd': [{'label': 'license_plate', 'conf': 0.40},
                                         {'label': 'face', 'conf': 0.30},
                                         {'label': 'person', 'conf': 0.30}]}]}
        kept = anon.confident(doc, 0.35, {'plate': 0.50, 'face': 0.25})
        self.assertEqual([d['label'] for d in kept['frames'][0]['d']], ['face'])

    def test_counterproof_without_class_floors_the_common_floor_applies_to_all(self):
        doc = {'frames': [{'i': 1, 'd': [{'label': 'license_plate', 'conf': 0.40},
                                         {'label': 'face', 'conf': 0.30}]}]}
        self.assertEqual([d['label'] for d in anon.confident(doc, 0.35)['frames'][0]['d']],
                         ['license_plate'])

    def test_class_floors_fall_back_on_the_common_floor(self):
        profile = SimpleNamespace(anonymize_min_confidence=0.25, anonymize_classes=['face', 'plate'],
                                  anonymize_class_min_confidence={'plate': 0.5})
        self.assertEqual(anon.class_floors(profile), {'face': 0.25, 'plate': 0.5})

    def test_class_floors_from_a_form_are_clamped_and_must_be_an_object(self):
        self.assertEqual(anon.clean_class_floors({'plate': 1.7, 'face': '0.3', ' ': 0.1}),
                         {'plate': 1.0, 'face': 0.3})
        with self.assertRaises(ValueError):
            anon.clean_class_floors(0.3)


class OnDemandPassesTest(unittest.TestCase):

    def test_the_anonymization_branch_is_declared_on_demand_and_nothing_else_is(self):
        self.assertEqual({p.key for p in pt.PASSES if p.on_demand},
                         {'anonymize_detect', 'anonymize_blur'})

    def test_the_blur_follows_the_detection_which_follows_the_windows(self):
        self.assertEqual(pt._DEPENDS_ON['anonymize_blur'], ['anonymize_detect'])
        self.assertIn('intersection_windows', pt._DEPENDS_ON['anonymize_detect'])
        self.assertEqual(pt._WATCHED['anonymize_detect'], ['anonymize_classes', 'anonymize_quality'])

    def test_the_blur_threshold_stales_the_blur_and_never_the_detection(self):
        self.assertEqual(pt._WATCHED['anonymize_blur'],
                         ['anonymize_min_confidence', 'anonymize_floors', 'anonymize_blur_look'])
        self.assertNotIn('anonymize_min_confidence', pt._WATCHED['anonymize_detect'])
        self.assertNotIn('anonymize_floors', pt._WATCHED['anonymize_detect'])
        self.assertNotIn('anonymize_blur_look', pt._WATCHED['anonymize_detect'])

    def test_the_new_blur_finishes_stale_a_blur_made_before_them(self):
        """Les finitions du 2026-10-29 (`BLUR_LOOK`) : un floutage plus ancien les ignorait — son
        état est le flou de l'Anonymizer (`_LEGACY_SETTINGS`), différent de la photo courante."""
        profile = SimpleNamespace(anonymize_min_confidence=0.25, anonymize_classes=['face'],
                                  anonymize_class_min_confidence={})
        legacy = pt._LEGACY_SETTINGS['anonymize_blur_look'](profile)
        current = pt._profile_snapshot(profile, ['anonymize_blur_look'])['anonymize_blur_look']
        self.assertNotEqual(legacy, current)
        self.assertEqual(current, {'style': 'inside', **anon.BLUR_LOOK})

    def test_a_class_floor_stales_a_blur_made_with_the_single_threshold(self):
        """Un floutage du 26/10 n'a photographié que le seuil commun : son état par classe est ce
        seuil pour toutes (`_LEGACY_SETTINGS`). Poser un seuil propre aux plaques le rend différent
        de la photo courante — périmé ; sans seuil propre, rien ne change."""
        plain = SimpleNamespace(anonymize_min_confidence=0.25, anonymize_classes=['face', 'plate'],
                                anonymize_class_min_confidence={})
        own = SimpleNamespace(**{**vars(plain), 'anonymize_class_min_confidence': {'plate': 0.5}})
        for profile, stale in ((plain, False), (own, True)):
            legacy = pt._LEGACY_SETTINGS['anonymize_floors'](profile)
            current = pt._profile_snapshot(profile, ['anonymize_floors'])['anonymize_floors']
            self.assertEqual(legacy != current, stale)

    def test_a_panel_row_says_whether_its_pass_is_on_demand(self):
        row = pt._panel_row(pt._BY_KEY['anonymize_detect'], 'front')
        self.assertTrue(row['on_demand'])
        self.assertFalse(pt._panel_row(pt._BY_KEY['yolo_detect'], 'front')['on_demand'])


def _write_video(path, frames=12, size=(64, 48), fps=12.0):
    import cv2
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'MJPG'), fps, size, True)
    for i in range(frames):
        image = np.zeros((size[1], size[0], 3), np.uint8)
        image[:, ::4] = 255                      # des rayures : un flou s'y voit
        image[0, 0] = (i, i, i)
        writer.write(image)
    writer.release()


def _frame_count(path):
    import cv2
    capture = cv2.VideoCapture(path)
    count = 0
    while capture.read()[0]:
        count += 1
    capture.release()
    return count


@unittest.skipIf(ffmpeg_path() is None, "ffmpeg absent")
class VideoRoundTripTest(unittest.TestCase):
    """Sur une vraie petite vidéo : extraits, indices, longueur de la sortie."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='wama_anon_test_')
        self.source = os.path.join(self.tmp, 'front.avi')
        _write_video(self.source)
        self.camera = SimpleNamespace(id=0, fps=12.0, video_file=SimpleNamespace(path=self.source))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detections_found_in_a_window_land_on_the_video_frame_numbers(self):
        clip_lengths = []

        class FakeDetectors:
            def detect(self, *, media_path, classes2blur, detection_threshold, progress=None):
                n = _frame_count(media_path)
                clip_lengths.append(n)
                return {'engine': 'fake', 'models': ['fake'],
                        'frames': [{'i': 0, 'd': [{'label': 'face', 'conf': 0.9,
                                                   'box': [1, 1, 9, 9], 'track': 'm0:1'}]},
                                   {'i': n + 5, 'd': [{'label': 'face', 'box': [1, 1, 2, 2]}]}]}

        windows = [{'t_enter': 3 / 12, 't_exit': 5 / 12}, {'t_enter': 8 / 12, 't_exit': 9 / 12}]
        doc = anon.detect_camera(self.camera, windows, FakeDetectors(), classes=['face'],
                                 threshold=0.25)
        self.assertEqual(doc['scope'], [[3, 5], [8, 9]])
        self.assertEqual(clip_lengths, [3, 2], "un extrait = exactement les images de sa plage")
        self.assertEqual([f['i'] for f in doc['frames']], [3, 8],
                         "indice de l'extrait + début de la plage ; rien au-delà de la plage")
        self.assertEqual(doc['frames'][0]['d'][0]['track'], 'r0:m0:1')
        self.assertEqual(doc['frame_count'], 12)

    def test_the_blurred_video_keeps_every_frame_and_blurs_outside_the_windows(self):
        import cv2
        from wama.common.utils import detections as dets
        doc = dets.new_document(media='video', width=64, height=48, fps=12.0, frame_count=12)
        doc['scope'] = [[2, 4]]
        target = os.path.join(self.tmp, 'out', 'front.mp4')
        written = anon.blur_camera(self.camera, doc, {'blur_ratio': 25, 'interpolate_detections': False},
                                   target)
        self.assertEqual(_frame_count(written), 12)
        capture = cv2.VideoCapture(written)
        frames = [capture.read()[1] for _ in range(12)]
        capture.release()
        stripes = lambda image: float(np.std(image[:, :, 0].astype(float)))
        self.assertGreater(stripes(frames[3]), 3 * stripes(frames[8]),
                           "dans la fenêtre l'image reste nette, hors fenêtre elle est floutée")

    def _blurred_frame_3(self, min_confidence, floors=None):
        """Image 3 (dans la fenêtre) floutée selon une détection FAIBLE qui couvre toute l'image."""
        import cv2
        from wama.common.utils import detections as dets
        doc = dets.new_document(media='video', width=64, height=48, fps=12.0, frame_count=12)
        doc['scope'] = [[2, 4]]
        dets.add(doc, 3, [{'label': 'license_plate', 'conf': 0.12, 'box': [0, 0, 64, 48]}])
        doc.pop('_index', None)
        target = os.path.join(self.tmp, f'out_{min_confidence}_{sorted((floors or {}).items())}', 'front.mp4')
        written = anon.blur_camera(self.camera, doc, {'blur_ratio': 25, 'interpolate_detections': False},
                                   target, min_confidence=min_confidence, floors=floors)
        capture = cv2.VideoCapture(written)
        frames = [capture.read()[1] for _ in range(4)]
        capture.release()
        return float(np.std(frames[3][:, :, 0].astype(float)))

    def test_a_detection_under_the_threshold_is_left_sharp(self):
        self.assertGreater(self._blurred_frame_3(0.25), 3 * self._blurred_frame_3(0.10),
                           "à 0,25 la détection à 0,12 reste nette ; à 0,10 elle est floutée")

    def test_the_plate_floor_decides_for_a_plate_not_the_common_one(self):
        self.assertGreater(self._blurred_frame_3(0.10, {'plate': 0.25}),
                           3 * self._blurred_frame_3(0.25, {'plate': 0.10}),
                           "le seuil des plaques l'emporte sur le seuil commun, dans les deux sens")


class ThresholdViewsTest(django_test.TestCase):
    """Le seuil se règle seul depuis le ▾ du bouton « Anonymisé », et l'aperçu lit les détections."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from wama_lab.cam_analyzer.models import AnalysisProfile, AnalysisSession, CameraView
        User = get_user_model()
        self.user = User.objects.create_user('anon-threshold-test', password='x')
        self.other = User.objects.create_user('anon-threshold-other', password='x')
        self.profile = AnalysisProfile.objects.create(user=self.user, name='p', model_path='yolo11n.pt',
                                                      intersections=[{'lat': 1.0, 'lon': 2.0}])
        self.session = AnalysisSession.objects.create(user=self.user, name='s', profile=self.profile)
        self.camera = CameraView.objects.create(session=self.session, position='front')

    def _call(self, view, user, *args, body=None):
        import json
        from django.test import RequestFactory
        from wama_lab.cam_analyzer import views
        factory = RequestFactory()
        request = (factory.post('/', data=json.dumps(body), content_type='application/json')
                   if body is not None else factory.get('/'))
        request.user = user
        return getattr(views, view)(request, *args)

    def test_the_threshold_is_saved_alone_and_clamped(self):
        import json
        res = self._call('save_anonymize_threshold', self.user, self.profile.id,
                         body={'anonymize_min_confidence': 1.7})
        self.assertEqual(json.loads(res.content)['anonymize_min_confidence'], 1.0)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.anonymize_min_confidence, 1.0)
        self.assertEqual(self.profile.intersections, [{'lat': 1.0, 'lon': 2.0}],
                         "le reste du profil n'est pas touché")

    def test_class_floors_are_saved_alone_and_served_with_the_class_forms(self):
        import json
        res = json.loads(self._call('save_anonymize_threshold', self.user, self.profile.id,
                                    body={'anonymize_class_min_confidence': {'plate': 0.45, 'face': 0.2}}).content)
        self.assertEqual(res['anonymize_class_min_confidence'], {'plate': 0.45, 'face': 0.2})
        self.assertIn('license plate', res['anonymize_class_forms']['plate'],
                      "l'aperçu range `license_plate` sous les plaques sans recopier la table")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.anonymize_class_min_confidence, {'plate': 0.45, 'face': 0.2})
        self.assertEqual(self.profile.anonymize_min_confidence, 0.25, "le seuil commun n'est pas touché")

    def test_class_floors_that_are_not_an_object_are_refused(self):
        res = self._call('save_anonymize_threshold', self.user, self.profile.id,
                         body={'anonymize_class_min_confidence': [0.3]})
        self.assertEqual(res.status_code, 400)
        res = self._call('save_anonymize_threshold', self.user, self.profile.id, body={})
        self.assertEqual(res.status_code, 400)

    def test_a_threshold_that_is_not_a_number_is_refused(self):
        res = self._call('save_anonymize_threshold', self.user, self.profile.id,
                         body={'anonymize_min_confidence': 'beaucoup'})
        self.assertEqual(res.status_code, 400)

    def test_another_users_profile_is_not_found(self):
        from django.http import Http404
        with self.assertRaises(Http404):
            self._call('save_anonymize_threshold', self.other, self.profile.id,
                       body={'anonymize_min_confidence': 0.3})

    def test_the_detections_are_served_only_once_the_detection_ran(self):
        from unittest.mock import patch
        missing = os.path.join(tempfile.gettempdir(), 'wama-anon-missing.json')
        with patch.object(anon, 'detections_path', return_value=missing):
            self.assertEqual(self._call('anonymize_detections', self.user, self.camera.id).status_code, 404)
        tmp = tempfile.mkdtemp(prefix='wama_anon_view_')
        try:
            path = os.path.join(tmp, 'front_detections.json')
            with open(path, 'w') as out:
                out.write('{"kind": "detections", "frames": []}')
            with patch.object(anon, 'detections_path', return_value=path):
                res = self._call('anonymize_detections', self.user, self.camera.id)
                self.assertEqual(res.status_code, 200)
                self.assertEqual(b''.join(res.streaming_content), b'{"kind": "detections", "frames": []}')
                # le fichier, pas `res.close()` : celle-ci émet la fin de requête, qui ferme la
                # connexion de la base au milieu de la transaction du test
                res.file_to_stream.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
