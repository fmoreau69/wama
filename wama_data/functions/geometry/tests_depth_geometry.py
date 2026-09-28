"""Plan de sol par profondeur : le SIGNE du pitch et la focale VERTICALE.

Deux défauts mesurés le 2026-09-28, aucun test n'existait sur ce module :
  • `plane_pitch_height` rendait une caméra penchée vers le bas avec un pitch NÉGATIF, alors que
    tout l'aval (`GroundProjector`, calib 2a, garde-fou −10…35°) suppose « positif = vers le bas ».
    La validation du 2026-08-05 était circulaire : sa route synthétique était générée avec la
    convention même qu'elle vérifiait ;
  • `deproject_depth` n'avait qu'une focale, or le rig ENA a des pixels non carrés (110° H / 61° V
    sur ~384×248 → fx ≈ 134, fy ≈ 210 px).

⭐ La route synthétique est construite ICI par ROTATION explicite de la caméra (axes de la caméra
exprimés dans le repère « niveau »), sans la formule testée : c'est ce qui rompt la circularité.
"""
import math

import numpy as np
from django.test import SimpleTestCase

from wama_data.functions.geometry.depth_geometry import (deproject_depth, fit_plane_ransac,
                                                          ground_plane_from_depth, plane_pitch_height)

W, H, FX, FY = 384, 248, 134.0, 210.0


def synthetic_road_depth(pitch_down_deg, height_m, fx=FX, fy=FY, w=W, h=H):
    """Profondeur (le long de l'axe optique) d'une route plate vue par une caméra penchée de
    `pitch_down_deg` vers le bas, à `height_m`. Repère niveau : Y vers le bas ; axe optique de la
    caméra = (0, sin θ, cos θ), axe « bas » = (0, cos θ, −sin θ). Le rayon d'un pixel coupe le sol
    Y = h pour une profondeur z = h / (dy·cos θ + sin θ), dy = (v − cy) / fy."""
    th = math.radians(pitch_down_deg)
    v = np.arange(h, dtype=np.float64)[:, None].repeat(w, axis=1)
    dy = (v - h / 2.0) / fy
    den = dy * math.cos(th) + math.sin(th)
    return np.where(den > 1e-3, height_m / den, np.nan).astype(np.float32)


def fit_camera_orientation(depth, fx, fy=None):
    pts = deproject_depth(depth, fx, focal_y_px=fy, z_min=0.5, z_max=60.0, max_points=20000)
    normal, offset, _, _ = fit_plane_ransac(pts, min_inliers=100)
    return plane_pitch_height(normal, offset)


class PitchSignTest(SimpleTestCase):
    def test_a_camera_pitched_down_has_a_positive_pitch(self):
        pitch, height = fit_camera_orientation(synthetic_road_depth(22.0, 2.4), FX, FY)
        self.assertAlmostEqual(pitch, 22.0, delta=0.1)
        self.assertAlmostEqual(height, 2.4, delta=0.01)

    def test_a_smaller_tilt_reads_smaller_and_still_positive(self):
        # Contre-épreuve du sens : 8° vers le bas se lit 8°, pas 22° ni −8°.
        pitch, _ = fit_camera_orientation(synthetic_road_depth(8.0, 2.4), FX, FY)
        self.assertAlmostEqual(pitch, 8.0, delta=0.1)


class VerticalFocalTest(SimpleTestCase):
    def test_the_vertical_focal_recovers_pitch_and_height_on_non_square_pixels(self):
        pitch, height = fit_camera_orientation(synthetic_road_depth(22.0, 2.4), FX, FY)
        self.assertAlmostEqual(pitch, 22.0, delta=0.1)
        self.assertAlmostEqual(height, 2.4, delta=0.01)

    def test_counterproof_the_horizontal_focal_alone_distorts_pitch_and_height(self):
        # Sans fy, la même route donne ~32° / ~3,4 m : le paramètre n'est pas décoratif.
        pitch, height = fit_camera_orientation(synthetic_road_depth(22.0, 2.4), FX)
        self.assertGreater(abs(pitch - 22.0), 5.0)
        self.assertGreater(abs(height - 2.4), 0.5)

    def test_omitting_the_vertical_focal_keeps_square_pixels(self):
        depth = synthetic_road_depth(15.0, 2.0, fx=FX, fy=FX)
        a = deproject_depth(depth, FX, z_min=0.5, max_points=5000)
        b = deproject_depth(depth, FX, focal_y_px=FX, z_min=0.5, max_points=5000)
        np.testing.assert_array_equal(a, b)

    def test_ground_plane_from_depth_forwards_the_vertical_focal(self):
        depth = synthetic_road_depth(22.0, 2.4)
        res = ground_plane_from_depth(depth, np.ones(depth.shape, dtype=bool), FX, focal_y_px=FY,
                                      z_min=0.5, max_points=20000)
        self.assertAlmostEqual(res['pitch_deg'], 22.0, delta=0.1)
        self.assertAlmostEqual(res['height_m'], 2.4, delta=0.01)
