"""La géométrie du rig expose la focale VERTICALE — et le plan de sol par profondeur s'en sert.

`camera_geometry` calculait déjà le FOV V réel (pour `dist_scale`) sans le rendre ; depuis le
2026-09-28 il l'expose, et `estimate_ground_plane_ph` déprojette avec fx ET fy du rig au lieu de
la focale unique estimée par le modèle (Depth Pro l'estime ~2× trop grande sur ce rig).
"""
import inspect
from types import SimpleNamespace

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils import depth_estimator
from wama_lab.cam_analyzer.utils.prediction_adapter import CAMERA_FOV_V, camera_geometry


class RigVerticalFovTest(SimpleTestCase):
    def test_camera_geometry_exposes_the_real_vertical_fov(self):
        geo = camera_geometry(SimpleNamespace(config={}))
        for pos, fov_v in CAMERA_FOV_V.items():
            self.assertEqual(geo[pos]['fov_v'], fov_v)

    def test_a_session_override_of_the_vertical_fov_is_honoured(self):
        geo = camera_geometry(SimpleNamespace(config={'camera_fov': {'left': {'v': 53.0}}}))
        self.assertEqual(geo['left']['fov_v'], 53.0)
        self.assertEqual(geo['right']['fov_v'], CAMERA_FOV_V['right'])

    def test_the_depth_ground_plane_deprojects_with_both_focals(self):
        # Garde par lecture de source : le calcul lit la base (DepthFrame), hors de portée d'un
        # test sans données ; on garde que la focale verticale ARRIVE à la déprojection.
        src = inspect.getsource(depth_estimator.ground_plane_from_stored_depth)
        self.assertIn("geo['fov_v']", src)
        self.assertIn('focal_y_px=focal_y_px', src)


class RigCameraHeightTest(SimpleTestCase):
    def test_camera_geometry_exposes_the_reference_height(self):
        from wama_lab.cam_analyzer.utils.prediction_adapter import CAMERA_HEIGHT_M
        geo = camera_geometry(SimpleNamespace(config={}))
        for pos, h in CAMERA_HEIGHT_M.items():
            self.assertEqual(geo[pos]['height_m'], h)

    def test_a_measured_height_overrides_the_estimate(self):
        geo = camera_geometry(SimpleNamespace(config={'camera_height': {'front': 2.27}}))
        self.assertEqual(geo['front']['height_m'], 2.27)
        self.assertEqual(geo['rear']['height_m'], 2.4)


class DepthModelChoiceTest(SimpleTestCase):
    def test_the_session_uses_the_engine_default_unless_it_names_a_known_model(self):
        from wama.common.backends.depth_engine import DEFAULT_DEPTH_MODEL
        self.assertEqual(depth_estimator.depth_model_for(SimpleNamespace(config={})), DEFAULT_DEPTH_MODEL)
        self.assertEqual(depth_estimator.depth_model_for(
            SimpleNamespace(config={'depth_model': 'depthpro'})), 'depthpro')
        self.assertEqual(depth_estimator.depth_model_for(
            SimpleNamespace(config={'depth_model': 'inconnu'})), DEFAULT_DEPTH_MODEL)

    def test_maps_stored_before_the_model_was_recorded_are_depth_pro(self):
        self.assertEqual(depth_estimator.stored_depth_model(SimpleNamespace(results_summary={})), 'depthpro')
        self.assertEqual(depth_estimator.stored_depth_model(
            SimpleNamespace(results_summary={'depth_model': 'zoedepth-kitti'})), 'zoedepth-kitti')
