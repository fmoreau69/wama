"""`hermite_gap` et `box_iou` — les primitives de trajectoire portées du cam_analyzer au commun
(2026-10-05) : le cam_analyzer comble ainsi les trous de ses fantômes, l'anonymizer ceux de ses
détections."""
import itertools

from django.test import SimpleTestCase

from wama_data.functions.geometry.shapes import box_iou
from wama_data.functions.kinematics.gap_fill import hermite_gap


class HermiteGapTest(SimpleTestCase):

    def test_a_steady_object_crosses_the_gap_in_a_straight_line_at_its_speed(self):
        for a in (0.25, 0.5, 0.75):
            x, y = hermite_gap((0, 0), (2, 1), (8, 4), (2, 1), 4, a)
            self.assertAlmostEqual(8 * a, x)
            self.assertAlmostEqual(4 * a, y)

    def test_without_a_speed_or_with_a_detour_it_falls_back_to_the_straight_line(self):
        self.assertEqual((5.0, 0.0), hermite_gap((0, 0), None, (10, 0), (1, 0), 5, 0.5))
        # Leaves upward fast, arrives downward fast : the curve would bulge far off the chord.
        self.assertEqual((5.0, 0.0), hermite_gap((0, 0), (0, 10), (10, 0), (0, -10), 5, 0.5))

    def test_the_thresholds_follow_the_unit_of_the_caller(self):
        # A bulge of 4 : refused under a 2-unit floor (metres), accepted under a 10-unit one (pixels).
        args = ((0, 0), (10, 0), (24, 0), (2, 0), 4, 0.25)
        self.assertEqual((6.0, 0.0), hermite_gap(*args, min_bulge=2.0, bulge_share=0.0))
        self.assertAlmostEqual(9.0, hermite_gap(*args, min_bulge=10.0)[0])

    def test_edge_speeds_too_slow_for_the_distance_give_a_straight_line_when_asked(self):
        # 200 to cover in 6 frames, edges at 1 and 11 per frame : at most 66 explained.
        args = ((0, 0), (1, 0), (200, 0), (11, 0), 6, 0.5)
        self.assertNotEqual((100.0, 0.0), hermite_gap(*args, min_bulge=50.0),
                            'not asked (the cam_analyzer) : the curve')
        self.assertEqual((100.0, 0.0), hermite_gap(*args, min_bulge=50.0, min_speed_share=0.5))


class TheOldCopiesDelegateTest(SimpleTestCase):
    """The cam_analyzer and the Data world kept their NAMES (`hermite_ghost`, `box_iou`,
    `_iou`) but delegate to the common primitives since `feb56cd2` — until then this class
    compared their results. Comparing results is now trivial ; what must hold is that no copy
    grows back : replace the common function, the old name must follow it."""

    def test_the_ghosts_of_the_cam_analyzer_are_the_common_curve(self):
        from unittest import mock
        from wama_lab.cam_analyzer.utils.multicam_tracker import hermite_ghost
        with mock.patch('wama_data.functions.kinematics.gap_fill.hermite_gap',
                        return_value=('common',)) as common:
            self.assertEqual(('common',), hermite_ghost((0, 0), None, (1, 1), None, 2.0, 0.5))
        common.assert_called_once_with((0, 0), None, (1, 1), None, 2.0, 0.5)
        # … with the cam_analyzer's defaults : the slowness guard is not asked there.
        self.assertNotEqual((100.0, 0.0), hermite_ghost((0, 0), (1, 0), (200, 0), (11, 0), 6, 0.5))

    def test_the_two_iou_copies_are_the_common_one(self):
        from unittest import mock
        from wama_data.functions.geometry.placement_metrics import _iou
        from wama_lab.cam_analyzer.utils import multicam_tracker
        self.assertIs(box_iou, multicam_tracker.box_iou)
        with mock.patch('wama_data.functions.geometry.shapes.box_iou', return_value=0.42):
            self.assertEqual(0.42, _iou([0, 0, 1, 1], [0, 0, 1, 1]))

    def test_box_iou_values(self):
        boxes = [None, [], [0, 0, 10, 10], [5, 5, 15, 15], [20, 20, 30, 30], [0, 0, 0, 0]]
        expected = {(2, 2): 1.0, (2, 3): 25 / 175, (3, 2): 25 / 175, (3, 3): 1.0, (4, 4): 1.0}
        for (i, a), (j, b) in itertools.product(enumerate(boxes), repeat=2):
            self.assertAlmostEqual(expected.get((i, j), 0.0), box_iou(a, b))
