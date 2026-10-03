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


class TrackingContinuityTest(SimpleTestCase):
    """Métrique #3 : ce qu'un suivi multi-caméras duplique ou perd (2026-10-01)."""

    def test_a_detector_chain_carried_by_two_track_ids_is_a_split(self):
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        obs = [(f, 'front', 7, 1 if f < 5 else 2, float(f), 0.0) for f in range(10)]
        res = tracking_continuity(obs)
        self.assertEqual((res['chains'], res['chain_splits']), (1, 1))
        # recollé après coup : plus d'éclatement
        self.assertEqual(tracking_continuity(obs, root=lambda g: 1)['chain_splits'], 0)

    def test_close_ids_never_seen_together_are_probable_duplicates(self):
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        obs = []
        for f in range(20):
            obs.append((f, 'front', 1, 10, float(f), 0.0))
            obs.append((f, 'right', 5, 11, float(f), 2.5))        # même objet, autre caméra, 2,5 m
        res = tracking_continuity(obs)
        self.assertEqual((res['cross_camera_close_pairs'], res['same_camera_close_pairs']), (1, 0))

    def test_close_ids_seen_together_by_one_camera_are_real_neighbours(self):
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        obs = []
        for f in range(20):
            obs.append((f, 'front', 1, 10, float(f), 0.0))
            obs.append((f, 'front', 2, 11, float(f), 2.5))         # deux boîtes d'une même image
        res = tracking_continuity(obs)
        self.assertEqual((res['cross_camera_close_pairs'], res['same_camera_close_pairs']), (0, 1))

    def test_a_brief_encounter_is_not_counted(self):
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        obs = [(f, 'front', 1, 10, 0.0, 0.0) for f in range(5)] + \
              [(f, 'left', 3, 11, 1.0, 0.0) for f in range(5)]
        self.assertEqual(tracking_continuity(obs)['cross_camera_close_pairs'], 0)

    def test_a_reused_detector_number_after_a_long_gap_is_another_chain(self):
        """Analyse par fenêtres : le détecteur repart et réutilise ses numéros pour d'autres objets."""
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        obs = [(f, 'front', 7, 1, 0.0, 0.0) for f in range(10)] + \
              [(f, 'front', 7, 2, 50.0, 0.0) for f in range(500, 510)]
        res = tracking_continuity(obs)
        self.assertEqual((res['chains'], res['chain_splits']), (2, 0))

    def test_a_new_id_born_where_another_just_left_is_a_relay_break(self):
        """Le détecteur change de numéro ET le suivi aussi : même objet, identifiant perdu."""
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        box = [100, 50, 160, 90]
        obs = [(f, 'front', 1, 10, 0.0, 0.0, box) for f in range(10)] + \
              [(f, 'front', 2, 11, 0.0, 0.0, box) for f in range(12, 20)]
        self.assertEqual(tracking_continuity(obs)['relay_breaks'], 1)
        self.assertEqual(tracking_continuity(obs, root=lambda g: 10)['relay_breaks'], 0,
                         "recollé : plus de perte")

    def test_a_new_object_elsewhere_in_the_image_is_not_a_relay_break(self):
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        obs = [(f, 'front', 1, 10, 0.0, 0.0, [100, 50, 160, 90]) for f in range(10)] + \
              [(f, 'front', 2, 11, 9.0, 0.0, [300, 50, 360, 90]) for f in range(12, 20)]
        self.assertEqual(tracking_continuity(obs)['relay_breaks'], 0)

    def test_an_id_flickering_between_two_separate_objects_is_a_false_merge(self):
        """Une caméra ne suit qu'UNE chaîne par objet : revenir à une chaîne quittée, l'autre boîte
        étant ailleurs dans l'image, c'est porter deux objets sous un numéro (G2788, 2026-10-03)."""
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        a, b = [100, 50, 160, 90], [300, 50, 360, 90]
        obs = [(f, 'front', 1 if f % 2 else 2, 10, 0.0, 0.0, a if f % 2 else b) for f in range(20)]
        res = tracking_continuity(obs)
        self.assertGreater(res['switchbacks'], 10)
        self.assertEqual(res['tracks_mixing_objects'], 1)

    def test_two_detector_boxes_on_one_object_are_not_a_false_merge(self):
        """Le détecteur dédouble parfois un objet (deux boîtes presque identiques) : pas une fusion."""
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        a, b = [100, 50, 160, 90], [102, 51, 158, 91]
        obs = [(f, 'front', 1 if f % 2 else 2, 10, 0.0, 0.0, a if f % 2 else b) for f in range(20)]
        self.assertEqual(tracking_continuity(obs)['switchbacks'], 0)

    def test_a_chain_number_reused_much_later_is_not_a_false_merge(self):
        from wama_data.functions.geometry.placement_metrics import tracking_continuity
        a, b = [100, 50, 160, 90], [300, 50, 360, 90]
        obs = [(f, 'front', 1, 10, 0.0, 0.0, a) for f in range(10)] + \
              [(f, 'front', 2, 10, 0.0, 0.0, b) for f in range(10, 20)] + \
              [(f, 'front', 1, 10, 0.0, 0.0, a) for f in range(200, 210)]
        self.assertEqual(tracking_continuity(obs)['switchbacks'], 0)
