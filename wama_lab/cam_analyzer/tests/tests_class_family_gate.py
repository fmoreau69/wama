"""⚑ class_family_gate — un deux-roues n'est jamais relié à un quatre-roues par le tracking 360°.

Mesuré le 2026-09-29 (image 15404, caméra droite) : deux motos classées `motorcycle` par YOLO
affichées « car » — leur gid (743, 739) avait fondu 25-28 observations de moto à droite dans
~240-340 observations d'une voiture vue à l'avant. Le vote de classe était juste pour ce gid ;
c'est le gid qui était faux.
"""
from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils.multicam_tracker import (
    _mixed_family_gids, dominant_family, families_conflict)


class DominantFamilyTest(SimpleTestCase):
    def test_car_and_truck_flapping_stay_one_family(self):
        self.assertEqual(dominant_family({'car': 5.0, 'truck': 2.0}), 'four_wheel')

    def test_a_single_mislabelled_frame_does_not_establish_a_family(self):
        self.assertIsNone(dominant_family({'motorcycle': 0.4}))          # poids < seuil

    def test_a_balanced_track_has_no_established_family(self):
        self.assertIsNone(dominant_family({'motorcycle': 3.0, 'car': 3.0}))

    def test_a_real_motorcycle_with_some_car_frames_stays_two_wheel(self):
        # gid 760 mesuré : 72 motorcycle / 22 car
        self.assertEqual(dominant_family({'motorcycle': 72 * 0.45, 'car': 22 * 0.3}), 'two_wheel')


class ConflictTest(SimpleTestCase):
    def test_two_wheel_versus_four_wheel_conflicts(self):
        self.assertTrue(families_conflict('two_wheel', 'four_wheel'))

    def test_an_unestablished_family_never_blocks(self):
        self.assertFalse(families_conflict(None, 'four_wheel'))
        self.assertFalse(families_conflict('two_wheel', None))

    def test_the_metric_counts_mixed_tracks_only(self):
        votes = {1: {'car': 239, 'motorcycle': 28 * 3}, 2: {'car': 10, 'truck': 5}, 3: {'motorcycle': 9}}
        self.assertEqual(_mixed_family_gids(votes), 1)
