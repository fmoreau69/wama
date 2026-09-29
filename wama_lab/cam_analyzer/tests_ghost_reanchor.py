"""Fantômes : ils prolongent la trajectoire AFFICHÉE (lissée) et ne tombent jamais dans la navette.

Mesuré le 2026-09-29 sur `4da52df3` (tracker rejoué écritures neutralisées) : saut à l'entrée /
sortie d'un fantôme p90 2,19 m / p99 8,73 m quand il interpolait entre positions BRUTES, contre
p90 0,46 m / p99 0,83 m reposé sur la trajectoire lissée (pas normal : p90 0,37 m).
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils.multicam_tracker import reanchor_ghosts


def _ghost(raw_e, raw_n):
    return {'type': 'ghost', 'predicted': True, 'world_en': [raw_e, raw_n], 'vehicle_xy': [9.0, 20.0]}


def _shuttle_facing_north(_fn):
    return 0.0, 0.0, 0.0            # navette à l'origine, cap nord : véhicule = monde


class GhostReanchorTest(SimpleTestCase):
    def setUp(self):
        # trou entre f0=10 et f1=14 ; bruts décalés de +3 m à l'est, lissés sur x = 10
        self.smoothed = {(7, 10): (10.0, 30.0), (7, 14): (10.0, 34.0)}
        self.frames, self.links = [], []
        for k, fn in enumerate(range(11, 14), start=1):
            det = _ghost(13.0, 30.0 + k)
            fr = SimpleNamespace(detections=[det])
            self.frames.append(fr)
            self.links.append((fr, det, 7, 10, 14, k / 4, fn))

    def test_the_ghost_continues_the_smoothed_track_without_a_jump(self):
        jumps, removed = reanchor_ghosts(self.links, self.smoothed, _shuttle_facing_north)
        self.assertEqual(removed, 0)
        self.assertEqual([fr.detections[0]['world_en'] for fr in self.frames],
                         [[10.0, 31.0], [10.0, 32.0], [10.0, 33.0]])
        self.assertLess(max(jumps), 1.01)            # un pas de 1 m par image, pas 3 m de côté

    def test_counterproof_raw_interpolation_keeps_the_jump(self):
        jumps, _ = reanchor_ghosts(self.links, self.smoothed, _shuttle_facing_north, use_smoothed=False)
        self.assertGreater(min(jumps), 3.0)

    def test_a_ghost_inside_the_shuttle_footprint_is_removed(self):
        det = _ghost(0.3, 2.0)
        det['vehicle_xy'] = [0.3, 2.0]               # à 2 m devant le centre arrière : DANS la navette
        fr = SimpleNamespace(detections=[det])
        _, removed = reanchor_ghosts([(fr, det, 8, 1, 5, 0.5, 3)], {}, _shuttle_facing_north)
        self.assertEqual(removed, 1)
        self.assertEqual(fr.detections, [])

    def test_a_ghost_beside_the_shuttle_is_kept(self):
        # le comblement à CÔTÉ de la navette est voulu (dépassement, `3fdbb41`)
        det = _ghost(2.5, 2.0)
        det['vehicle_xy'] = [2.5, 2.0]
        fr = SimpleNamespace(detections=[det])
        _, removed = reanchor_ghosts([(fr, det, 8, 1, 5, 0.5, 3)], {}, _shuttle_facing_north)
        self.assertEqual(removed, 0)
