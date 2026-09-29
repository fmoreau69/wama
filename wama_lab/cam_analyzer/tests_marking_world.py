"""Marquages SAM3 agrégés en monde — projection calibrée et passages piétons calés sur le corridor.

Constat de Fabien (2026-09-29, 6771,8 s) : des lignes bleues « placées n'importe comment » sur la
mini-carte. Deux causes mesurées aux deux carrefours ENA face aux passages piétons de
l'orthophoto : des caméras projetées à pitch 0° (la réalité : 16° avant, 25° arrière), et un axe
de nuage agrégé qui dérivait (diagonales, traits étirés LE LONG de la rue).
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils import marking_world as mw


class SnapCrossingTest(SimpleTestCase):
    def test_a_diagonal_crossing_snaps_across_the_road(self):
        axis, half = mw.snap_crossing(139.8, 7.0, 12.0, 0.5)       # mesuré à Roumanille-Poincaré
        self.assertEqual(axis, 97.0)
        self.assertEqual(half, mw.CROSSING_MAX_HALF_M)             # étirement borné à une chaussée

    def test_a_parallel_crossing_on_the_shuttle_path_is_impossible(self):
        self.assertIsNone(mw.snap_crossing(9.7, 7.0, 6.0, 1.0))

    def test_a_parallel_crossing_off_the_road_crosses_a_side_street(self):
        axis, _ = mw.snap_crossing(9.7, 7.0, 6.0, 6.0)
        self.assertEqual(axis, 7.0)


class ProjectorTest(SimpleTestCase):
    def test_a_camera_without_calibration_projects_nothing(self):
        # plus de repli paramétrique à pitch 0° : il envoyait les marquages dans l'axe de visée
        cam = SimpleNamespace(session=object(), position='left', ground_homography=None,
                              width=384, height=248)
        with mock.patch('wama_lab.cam_analyzer.utils.prediction_adapter.ground_projector_for',
                        return_value=None):
            self.assertEqual(mw._projector_for(cam, {'fov_h': 97.0}), (None, False))

    def test_the_2a_ground_calibration_comes_first(self):
        cam = SimpleNamespace(session=object(), position='front', ground_homography=[[1, 0, 0]],
                              width=384, height=248)
        sentinel = object()
        with mock.patch('wama_lab.cam_analyzer.utils.prediction_adapter.ground_projector_for',
                        return_value=sentinel):
            self.assertEqual(mw._projector_for(cam, {'fov_h': 110.0}), (sentinel, True))
