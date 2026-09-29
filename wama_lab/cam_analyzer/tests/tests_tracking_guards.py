"""Trois gardes du tracking 360° posées le 2026-09-29 sur les constats de Fabien (6784-6789 s).

- une boîte coupée en BAS n'est pas projetée au sol (son point de contact est hors image) ;
- une boîte couvrant l'image entière est écartée quelle que soit sa confiance (reflet de vitre
  en plein écran à l'arrière, conf 0,66, devenu un fantôme de bus sur la navette) ;
- deux boîtes DISTINCTES d'une même image d'une même caméra sont deux objets (trois voitures
  garées vues à gauche portaient toutes G4712) — un doublon de détection, lui, reste un objet.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils.artifact_filter import is_giant_reflection
from wama_lab.cam_analyzer.utils.multicam_tracker import box_iou, claims_distinct_box
from wama_lab.cam_analyzer.utils.prediction_adapter import ground_ego


class _Projector:
    image_size = (408, 248)

    @staticmethod
    def project(u, v):
        return (0.5, 3.0)


class GroundEgoEdgeTest(SimpleTestCase):
    def test_a_box_cut_at_the_bottom_is_not_projected(self):
        self.assertIsNone(ground_ego(_Projector(), [100, 122, 187, 246]))      # G4712, 81467

    def test_a_box_cut_on_a_side_is_not_projected(self):
        self.assertIsNone(ground_ego(_Projector(), [0.3, 100, 87, 200]))

    def test_a_whole_box_is_projected(self):
        self.assertEqual(ground_ego(_Projector(), [100, 100, 180, 200]), (0.5, 3.0))


class FullFrameReflectionTest(SimpleTestCase):
    def test_a_full_frame_box_is_rejected_even_when_confident(self):
        det = {'confidence': 0.659, 'bbox': [0, 0, 408, 248], 'class_name': 'bus'}
        self.assertTrue(is_giant_reflection(det, 408, 248))

    def test_a_large_confident_box_below_the_threshold_is_kept(self):
        det = {'confidence': 0.8, 'bbox': [0, 60, 300, 248], 'class_name': 'car'}   # ~56 % de l'image
        self.assertFalse(is_giant_reflection(det, 408, 248))


class SameCameraExclusionTest(SimpleTestCase):
    def test_two_parked_cars_side_by_side_are_distinct(self):
        self.assertTrue(claims_distinct_box([[142, 51, 322, 129]], [0, 48, 94, 133]))

    def test_a_duplicate_detection_of_one_object_may_share_the_track(self):
        # « truck » et « car » de même contour (81416, caméra avant)
        self.assertFalse(claims_distinct_box([[0.1, 84.1, 41.1, 145.3]], [0.1, 84.0, 41.2, 144.7]))
        self.assertGreater(box_iou([0.1, 84.1, 41.1, 145.3], [0.1, 84.0, 41.2, 144.7]), 0.9)

    def test_an_unclaimed_track_is_free(self):
        self.assertFalse(claims_distinct_box(None, [0, 0, 10, 10]))
