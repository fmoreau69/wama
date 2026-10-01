"""Leviers de CONTINUITÉ du tracking 360° (2026-10-01, demande de Fabien : « ne pas dupliquer les
objets, ni les perdre » — sans pansement). Mesurés sur ENA_CASA avec la métrique #3
(`placement_metrics.tracking_continuity`) : chaînes éclatées 867 → 597, doublons 28 → 25, relais ratés
39 → 38, aucune fusion abusive.
"""
import inspect

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils import multicam_tracker as mt
from wama_lab.cam_analyzer.utils.features import FEATURES


class TrackingLeversTest(SimpleTestCase):
    def setUp(self):
        self.src = inspect.getsource(mt.annotate_global_tracks)

    def test_locked_chains_are_served_before_new_ones(self):
        loop = self.src.index('for f, d, e, n, pos, relaxed in dets_here:')
        self.assertLess(self.src.index('dets_here.sort(key=_locked_first)'), loop,
                        "l'ordre doit être posé AVANT l'association de l'image")

    def test_the_birth_guard_lets_a_detector_renumbering_through(self):
        """Une boîte qui recouvre la dernière de l'autre chaîne = même objet renuméroté : permise.
        Sans cette clause, la garde fabriquait des pertes (+789 identifiants mesurés)."""
        guard = self.src[self.src.index('if _birth_guard:'):self.src.index('pe = tr[\'e\'] + tr[\'ve\'] * dt')]
        self.assertIn('box_iou(_lv[2], d.get(\'bbox\')) < DUPLICATE_BOX_IOU', guard)
        self.assertIn('t - _lv[1] <= 0.5', guard)

    def test_both_levers_are_declared_and_on(self):
        by_key = {f.key: f for f in FEATURES}
        for k in ('chain_lock_priority', 'birth_same_camera_guard'):
            self.assertTrue(by_key[k].default, k)
            self.assertEqual(by_key[k].scope, 'compute', k)

    def test_the_continuity_metric_is_reported(self):
        self.assertIn('tracking_continuity(_continuity_obs, root=_root)', self.src)
        self.assertIn("'continuity': continuity", self.src)
