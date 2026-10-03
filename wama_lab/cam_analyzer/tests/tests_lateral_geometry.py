"""Géométrie des caméras LATÉRALES (2026-10-02) — champ cohérent avec l'image, orientation mesurée.

Mesuré sur ENA_CASA : le couple saisi 97° H × 53° V (fiche F1015) donnait deux focales sur la vidéo
384×244 ; le sténopé à 53° V fait ~76° H. Et les orientations saisies ±75° valent ~67,5° (droite)
et ~−77,5° (gauche), mesurées par le mouvement connu (`known_motion_yaw`) avec la caméra avant en
contrôle — doublons de jonction 35 → 24, relais ratés 33 → 22 (`CAM_ANALYZER_CHANGELOG.md`).
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, RequestFactory

from wama_lab.cam_analyzer import views
from wama_lab.cam_analyzer.utils.camera_intrinsics import (apply_yaw_control, measured_yaw,
                                                           straight_windows, YAW_CONTROL_MAX_DEG)
from wama_lab.cam_analyzer.utils.prediction_adapter import (camera_yaw_map, configured_yaw_map,
                                                            square_pixel_fov)

SID = '00000000-0000-0000-0000-00000000fa11'


class SquarePixelFovTest(SimpleTestCase):

    def test_one_field_sets_the_other_through_the_image_proportions(self):
        self.assertAlmostEqual(square_pixel_fov(384, 244, fov_v=53.0)[0], 76.25, delta=0.05)
        self.assertAlmostEqual(square_pixel_fov(408, 244, fov_v=53.0)[0], 79.6, delta=0.05)
        h, v = square_pixel_fov(384, 248, fov_h=75.7)
        self.assertAlmostEqual(v, 53.3, delta=0.1)      # le couple MESURÉ de la caméra avant
        self.assertAlmostEqual(square_pixel_fov(384, 244, fov_h=h)[0], h, delta=0.01)

    def test_the_datasheet_pair_is_not_one_focal(self):
        """97° H ↔ 53° V : sur 384×244, 53° V impose ~76° H — pas 97°."""
        self.assertGreater(abs(square_pixel_fov(384, 244, fov_v=53.0)[0] - 97.0), 15.0)

    def test_nothing_without_an_image_size(self):
        self.assertIsNone(square_pixel_fov(None, 244, fov_v=53.0))
        self.assertIsNone(square_pixel_fov(384, 244))


class CameraFovEndpointTest(SimpleTestCase):

    def _post(self, body):
        req = RequestFactory().post(f'/x/{SID}/camera-yaw/', data=json.dumps(body),
                                    content_type='application/json')
        req.user = SimpleNamespace(is_authenticated=True, id=1)
        cams = [SimpleNamespace(position='right', width=384, height=244),
                SimpleNamespace(position='left', width=408, height=244)]
        session = SimpleNamespace(id=SID, config={}, cameras=SimpleNamespace(all=lambda: cams),
                                  save=lambda **k: None)
        with mock.patch.object(views, 'get_object_or_404', return_value=session):
            resp = views.set_camera_yaw(req, SID)
        return resp, session

    def test_the_vertical_field_gives_each_side_camera_its_own_horizontal(self):
        resp, s = self._post({'camera_yaw': {'right': 67.5}, 'camera_fov': {'right': {'v': 53}, 'left': {'v': 53}}})
        self.assertEqual(resp.status_code, 200)
        self.assertAlmostEqual(s.config['camera_fov']['right']['h'], 76.25, delta=0.05)
        self.assertAlmostEqual(s.config['camera_fov']['left']['h'], 79.6, delta=0.05)
        self.assertEqual(s.config['camera_fov']['right']['v'], 53.0)

    def test_an_incoherent_pair_is_refused(self):
        resp, s = self._post({'camera_fov': {'right': {'h': 97, 'v': 53}}})
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn('camera_fov', s.config)

    def test_a_coherent_pair_is_kept(self):
        resp, s = self._post({'camera_fov': {'right': {'h': 76.2, 'v': 53}}})
        self.assertEqual(resp.status_code, 200)
        self.assertAlmostEqual(s.config['camera_fov']['right']['h'], 76.25, delta=0.05)


def _measures(front_yaw=-0.5, front_measured=True, right_measured=True):
    return {'front': {'yaw_deg': front_yaw, 'measured': front_measured},
            'right': {'yaw_deg': 67.6, 'measured': right_measured},
            'left': {'yaw_deg': -77.4, 'measured': True},
            'rear': {'yaw_deg': 178.0, 'measured': True}}


class YawControlTest(SimpleTestCase):

    def test_side_cameras_are_applicable_when_the_front_control_holds(self):
        m = _measures()
        ctl = apply_yaw_control(m, 0.0)
        self.assertTrue(ctl['ok'])
        self.assertTrue(m['right']['applicable'] and m['left']['applicable'])
        self.assertFalse(m['front']['applicable'], "l'avant est le contrôle, jamais corrigé")
        self.assertFalse(m['rear']['applicable'], "l'arrière n'a pas été confronté aux doublons")

    def test_a_failed_control_rejects_every_side_camera(self):
        m = _measures(front_yaw=YAW_CONTROL_MAX_DEG + 1.0)
        self.assertFalse(apply_yaw_control(m, 0.0)['ok'])
        self.assertFalse(m['right']['applicable'] or m['left']['applicable'])
        m = _measures(front_measured=False)
        self.assertFalse(apply_yaw_control(m, 0.0)['ok'])
        self.assertFalse(m['left']['applicable'])

    def test_a_flat_side_measurement_is_not_applied(self):
        m = _measures(right_measured=False)
        apply_yaw_control(m, 0.0)
        self.assertFalse(m['right']['applicable'])
        self.assertTrue(m['left']['applicable'])


class MeasuredYawFlagTest(SimpleTestCase):

    def _session(self, on, applicable=True):
        rs = {'camera_intrinsics': {'right': {'mount_yaw': {'yaw_deg': 67.6, 'applicable': applicable}}}}
        return SimpleNamespace(config={'camera_yaw': {'right': 75.0}, 'features': {'measured_camera_yaw': on}},
                               results_summary=rs)

    def test_the_measured_yaw_replaces_the_typed_one_only_under_the_flag(self):
        self.assertEqual(camera_yaw_map(self._session(True))['right'], 67.6)
        self.assertEqual(camera_yaw_map(self._session(False))['right'], 75.0)
        self.assertEqual(configured_yaw_map(self._session(True))['right'], 75.0)

    def test_a_non_applicable_measure_changes_nothing(self):
        s = self._session(True, applicable=False)
        self.assertIsNone(measured_yaw(s, 'right'))
        self.assertEqual(camera_yaw_map(s)['right'], 75.0)

    def test_the_flag_is_off_by_default(self):
        from wama_lab.cam_analyzer.utils.features import FEATURES
        flag = {f.key: f for f in FEATURES}['measured_camera_yaw']
        self.assertFalse(flag.default)
        self.assertEqual(flag.scope, 'compute')

    def test_the_js_mirror_reads_the_effective_yaw(self):
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / 'wama_lab' / 'cam_analyzer' / 'static' / 'cam_analyzer'
               / 'js' / 'index.js').read_text(encoding='utf-8')
        self.assertIn("camFeat.measured_camera_yaw && measuredYaw[p] != null", src)
        self.assertIn("_drawCam(cp, camGeo[cp].yaw)", src)
        self.assertNotIn("_drawCam(cp, camYaw[cp])", src)


class StraightWindowsTest(SimpleTestCase):

    def test_straight_driving_gives_windows_and_a_turn_does_not(self):
        import math
        rows, e, n = [], 0.0, 0.0
        for i in range(400):
            t = i * 0.5
            h = 0.0 if t < 100 else min(90.0, 9.0 * (t - 100))
            rows.append((t, e, n, h))
            e += 2.0 * math.sin(math.radians(h)); n += 2.0 * math.cos(math.radians(h))
        w = straight_windows(rows)
        self.assertTrue(w)
        for t0, t1, turn in w:
            self.assertLess(abs(turn), 4.0)
            self.assertFalse(100.0 < t1 and t0 < 110.0, (t0, t1))


class LensDistortionTest(SimpleTestCase):
    """Distorsion des latérales (2026-10-03) : modèle radial INVERSE, et plancher de la calibration."""

    def test_the_inverse_model_is_monotonic_up_to_the_image_corner(self):
        """Brown-Conrady à k1 = −0,42 ne représentait aucun point au-delà de r = 0,59 : les bords
        (r ≈ 0,8) devenaient du bruit. Le modèle inverse est explicite et croissant."""
        from wama_lab.cam_analyzer.utils.ground_projection import undistort_radial_inverse
        fx, cx, cy = 244.6, 192.0, 122.0
        xs = [undistort_radial_inverse(u, 122.0, 0.7, fx, fx, cx, cy)[0] for u in range(192, 385, 8)]
        self.assertTrue(all(b > a for a, b in zip(xs, xs[1:])))
        self.assertEqual(undistort_radial_inverse(300.0, 50.0, 0.0, fx, fx, cx, cy), (300.0, 50.0))

    def test_the_measured_left_value_matches_the_datasheet_edge_angle(self):
        """k = 0,5 sur la gauche (408 px, 79,6° au centre) redonne ~97° de bord à bord : la fiche F1015."""
        import math
        from wama_lab.cam_analyzer.utils.ground_projection import undistort_radial_inverse
        fx = 204.0 / math.tan(math.radians(79.64) / 2)
        u = undistort_radial_inverse(408.0, 122.0, 0.5, fx, fx, 204.0, 122.0)[0]
        self.assertAlmostEqual(2 * math.degrees(math.atan((u - 204.0) / fx)), 97.0, delta=2.0)

    def test_the_ground_calibration_refuses_to_explain_a_minority(self):
        """Le coût moyennait sur les seuls immobiles restés à portée : écarter les autres le faisait baisser
        (4 voitures sur 24 retenues, étalement 0,09 m)."""
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / 'wama_lab' / 'cam_analyzer' / 'utils'
               / 'homography_estimator.py').read_text(encoding='utf-8')
        self.assertIn('if len(spreads) < max(3, (len(obs) + 1) // 2):', src)

    def test_the_switch_is_declared_off_and_feeds_the_geometry(self):
        from wama_lab.cam_analyzer.utils.features import FEATURES
        f = {x.key: x for x in FEATURES}['lens_distortion']
        self.assertFalse(f.default)
        cfg = {'camera_distortion': {'left': 0.5}, 'features': {'lens_distortion': True}}
        from wama_lab.cam_analyzer.utils.prediction_adapter import camera_geometry
        self.assertEqual(camera_geometry(SimpleNamespace(config=cfg))['left']['k1'], 0.5)
        cfg['features']['lens_distortion'] = False
        self.assertEqual(camera_geometry(SimpleNamespace(config=cfg))['left']['k1'], 0.0)
