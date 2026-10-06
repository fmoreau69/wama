"""Trajectoires jumelles (`twin_tracks`, 2026-10-06) : un même véhicule porté par deux identifiants."""
import pandas as pd
from django.test import SimpleTestCase

from wama.common.catalog.data_types import DataType, TypedFrame
from wama_data.functions.kinematics.twin_tracks import trajectory_twins


def _track(gid, cam, x0, y, vx, frames, box=None):
    """Un identifiant vu par une caméra, roulant à `vx` m par image le long de x."""
    return [(f, cam, gid, x0 + vx * (f - frames[0]), y, box) for f in frames]


class TrajectoryTwinsTest(SimpleTestCase):

    def test_one_car_seen_by_two_cameras_is_one_car(self):
        obs = _track('A', 'front', 0.0, 3.0, 0.5, range(30)) + _track('B', 'left', 5.4, 3.8, 0.5, range(10, 30))
        out, stats = trajectory_twins(obs)
        self.assertEqual(out, {'B': 'A'})
        self.assertEqual(stats['fusions'], 1)

    def test_a_car_in_the_next_lane_is_another_car(self):
        """Contre-épreuve : voie voisine (3,5 m), même vitesse — jamais réunie."""
        obs = _track('A', 'front', 0.0, 0.0, 0.5, range(30)) + _track('B', 'left', 0.0, 3.5, 0.5, range(30))
        out, stats = trajectory_twins(obs)
        self.assertEqual(out, {})
        self.assertEqual(stats['trop_loin'], 1)

    def test_opposite_directions_are_two_vehicles(self):
        obs = _track('A', 'front', 0.0, 0.0, 0.15, range(20)) + _track('B', 'left', 3.0, 0.5, -0.15, range(20))
        out, stats = trajectory_twins(obs)
        self.assertEqual(out, {})
        self.assertEqual(stats['sens_differents'], 1)

    def test_two_boxes_of_one_image_are_two_vehicles(self):
        obs = (_track('A', 'front', 0.0, 3.0, 0.5, range(30), box=[0, 0, 40, 30])
               + _track('B', 'left', 5.4, 3.8, 0.5, range(10, 30))
               + [(5, 'front', 'B', 2.5, 3.8, [100, 0, 140, 30])])
        out, _stats = trajectory_twins(obs)
        self.assertEqual(out, {})

    def test_two_still_objects_are_left_to_the_long_exposure(self):
        obs = _track('A', 'front', 0.0, 3.0, 0.0, range(30)) + _track('B', 'left', 0.5, 3.4, 0.0, range(30))
        out, stats = trajectory_twins(obs)
        self.assertEqual(out, {})
        self.assertEqual(stats['immobiles'], 1)

    def test_twins_do_not_chain_through_a_middle_track(self):
        """A et B jumeaux, B et C jumeaux, mais A et C jamais proches : C ne rejoint pas A par B."""
        obs = (_track('A', 'front', 0.0, 0.0, 0.5, range(0, 30)) + _track('B', 'left', 0.3, 1.0, 0.5, range(0, 60))
               + _track('C', 'rear', 15.6, 2.0, 0.5, range(32, 60)))
        out, _stats = trajectory_twins(obs)
        self.assertEqual(out, {'B': 'A'})                 # la paire la plus longue d'abord ; C reste à part

    def test_declared_in_the_catalogue(self):
        from wama.common.catalog import function_catalog as fc
        fc.load_all()
        spec = fc.get('trajectory_twins')
        self.assertIsNotNone(spec)
        obs = _track('A', 'front', 0.0, 3.0, 0.5, range(30)) + _track('B', 'left', 5.4, 3.8, 0.5, range(10, 30))
        df = pd.DataFrame([o[:5] for o in obs], columns=['frame', 'camera', 'track_id', 'x', 'y'])
        out = spec.fn(TypedFrame(df, DataType.TABLE))
        self.assertEqual(out.df.to_dict('records'), [{'track_id': 'B', 'root': 'A'}])
