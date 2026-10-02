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


class ServerHeadingTest(SimpleTestCase):
    """Le cap d'un véhicule qui roule vient de la vitesse LISSÉE du serveur (2026-10-02) : la trace
    de la page, vidée à chaque saut, faisait dessiner un véhicule qui traverse dans l'axe de la route."""

    def test_the_smoothed_velocity_travels_with_the_smoothed_position(self):
        src = inspect.getsource(mt.annotate_global_tracks)
        block = src[src.index("d['world_en'] = [round(w[0], 2), round(w[1], 2)]"):]
        self.assertIn("d['world_vel'] = [round(wv[0], 2), round(wv[1], 2)]", block[:400])

    def test_the_velocity_is_purged_like_every_tracker_field(self):
        self.assertIn('world_vel', mt.TRACKER_FIELDS)

    def test_the_page_uses_it_under_its_switch(self):
        from pathlib import Path
        js = (Path(mt.__file__).resolve().parents[1] / 'static/cam_analyzer/js/index.js').read_text(encoding='utf-8')
        self.assertIn("camFeat.server_heading !== false && Array.isArray(det.world_vel)", js)
        self.assertIn("let _vEst = _srvSpeed;", js)
        self.assertTrue({f.key: f for f in FEATURES}['server_heading'].default)
