"""Centre d'un véhicule depuis sa face visible (`shapes.visible_face_to_center`, 2026-10-03).

Signalé par Fabien sur ENA_CASA (511,8 s) : des voitures garées, étiquetées à 4-5 m, dessinées à
moitié sur la voie — le point placé était leur flanc, et le rectangle était centré dessus.
"""
import math
import unittest

from .shapes import visible_face_to_center

CAR = (4.5, 1.8)


class VisibleFaceToCenterTest(unittest.TestCase):

    def test_a_car_seen_from_the_side_moves_away_by_half_its_width(self):
        x, y = visible_face_to_center(-4.6, 0.0, *CAR, axis_deg=0.0)
        self.assertAlmostEqual(x, -5.5)
        self.assertAlmostEqual(y, 0.0)

    def test_a_car_seen_from_behind_moves_away_by_half_its_length(self):
        x, y = visible_face_to_center(0.0, 10.0, *CAR, axis_deg=0.0)
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, 12.25)

    def test_a_car_seen_at_an_angle_moves_by_its_center_to_edge_distance(self):
        x, y = visible_face_to_center(5.0, 5.0, *CAR, axis_deg=0.0)
        t = min(2.25 / math.cos(math.radians(45)), 0.9 / math.sin(math.radians(45)))
        self.assertAlmostEqual(math.hypot(x, y) - math.hypot(5.0, 5.0), t)

    def test_the_direction_of_the_axis_does_not_matter(self):
        self.assertEqual(visible_face_to_center(3.0, 4.0, *CAR, axis_deg=30.0),
                         visible_face_to_center(3.0, 4.0, *CAR, axis_deg=210.0))

    def test_a_crossing_car_seen_from_behind_moves_by_half_its_width(self):
        x, y = visible_face_to_center(0.0, 10.0, *CAR, axis_deg=90.0)
        self.assertAlmostEqual(y, 10.9)

    def test_a_point_at_the_camera_is_left_alone(self):
        self.assertEqual(visible_face_to_center(0.0, 0.0, *CAR, axis_deg=0.0), (0.0, 0.0))


if __name__ == '__main__':
    unittest.main()
