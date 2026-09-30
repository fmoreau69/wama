"""Métriques de cohérence de placement (brique WAMA Data) — métrique #2 `camera_consistency`.

Rig de référence : caméra avant en (0, 4,5) regardant devant (yaw 0), caméra droite en (1, 3,4)
regardant à droite (yaw 90) — repère véhicule, x droite, y avant.
"""
import pandas as pd
from django.test import SimpleTestCase

from wama.common.catalog.data_types import DataType, TypedFrame
from wama_data.functions.geometry.placement_metrics import (camera_consistency,
                                                            camera_consistency_frame)

FRONT = ('front', 0.0, 0.0, 4.5)     # (caméra, yaw, mount_x, mount_y)
RIGHT = ('right', 90.0, 1.0, 3.4)


def obs(cam, x, y, depth, n=1):
    c, yaw, mx, my = cam
    return [(c, x, y, yaw, mx, my, depth)] * n


class CameraConsistencyTest(SimpleTestCase):
    def test_objects_in_front_of_their_camera_are_consistent(self):
        rows = obs(FRONT, 0.5, 24.5, 20.0, 10) + obs(RIGHT, 7.0, 3.4, 6.0, 10)
        res = camera_consistency(rows, min_obs=5)
        self.assertEqual(res['front']['behind_share'], 0.0)
        self.assertEqual(res['right']['behind_share'], 0.0)
        self.assertAlmostEqual(res['front']['depth_rel_err_median'], 0.0)
        self.assertAlmostEqual(res['right']['depth_rel_err_median'], 0.0)

    def test_an_object_placed_behind_its_own_camera_is_counted(self):
        """Vu par la caméra DROITE mais posé à gauche de la navette : impossible."""
        rows = obs(RIGHT, 7.0, 3.4, 6.0, 8) + obs(RIGHT, -2.0, 3.4, 6.0, 2)
        self.assertEqual(camera_consistency(rows, min_obs=5)['right']['behind_share'], 0.2)

    def test_the_label_versus_drawn_depth_gap_is_measured(self):
        """Le cas qui l'a fait écrire : étiqueté 32,8 m, dessiné à 43 m de la caméra avant."""
        res = camera_consistency(obs(FRONT, 0.0, 4.5 + 43.0, 32.8, 5), min_obs=5)
        self.assertAlmostEqual(res['front']['depth_rel_err_median'], (43.0 - 32.8) / 32.8, places=3)

    def test_unknown_depth_only_skips_the_depth_check(self):
        res = camera_consistency(obs(FRONT, 0.0, 10.0, None, 5), min_obs=5)
        self.assertEqual(res['front']['n'], 5)
        self.assertEqual(res['front']['depth_n'], 0)
        self.assertIsNone(res['front']['depth_rel_err_median'])

    def test_a_camera_with_too_few_observations_is_not_summarised(self):
        self.assertEqual(camera_consistency(obs(FRONT, 0.0, 10.0, 5.5, 3), min_obs=5), {})

    def test_the_catalogue_wrapper_returns_one_row_per_camera(self):
        rows = obs(FRONT, 0.0, 24.5, 20.0, 5) + obs(RIGHT, -2.0, 3.4, 6.0, 5)
        df = pd.DataFrame([{'camera': c, 'veh_x': x, 'veh_y': y, 'cam_yaw': yw, 'mount_x': mx,
                            'mount_y': my, 'distance_m': d} for c, x, y, yw, mx, my, d in rows])
        out = camera_consistency_frame(TypedFrame(df, DataType.DETECTIONS), min_obs=5)
        self.assertEqual(out.data_type, DataType.TABLE)
        by_cam = out.df.set_index('camera')
        self.assertEqual(by_cam.loc['right', 'behind_share'], 1.0)
        self.assertEqual(by_cam.loc['front', 'behind_share'], 0.0)
