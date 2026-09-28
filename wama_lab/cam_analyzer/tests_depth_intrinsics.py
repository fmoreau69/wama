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
        src = inspect.getsource(depth_estimator.estimate_ground_plane_ph)
        self.assertIn("geo['fov_v']", src)
        self.assertIn('focal_y_px=focal_y_px', src)
