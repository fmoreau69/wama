"""Trace GPS : une entrée par FIXE, et la latence du GPS dans la synchro (2026-10-13).

Constat sur ENA_CASA : le .rec porte chaque fixe dans trois trames NMEA (RMC, GGA, GLL, reçues à
+0, +0,1 et +0,4 s, même position). Lue entrée par entrée, la trace donnait une vitesse nulle deux
fois sur trois (« navette à l'arrêt 78 % du temps ») et 1,7 fois trop forte la troisième, et la vue
de dessus dessinait la navette jusqu'à 2,3 m en arrière. Puis la position GPS arrive ~0,55 s après
l'image : ⚑ `gps_latency` l'ajoute à la synchro.

Sans base : une session factice suffit.
"""
import unittest

from wama_lab.cam_analyzer.utils.ego_pose import (annotate_gps_heading_speed, distinct_fixes,
                                                  effective_gps_track, gps_fixes)
from wama_lab.cam_analyzer.utils.prediction_adapter import gps_time_mapping, video_to_gps_time


class _Session:
    def __init__(self, gps_track=None, features=None, latency=None):
        self.gps_track = gps_track or []
        self.config = {'features': features or {}}
        self.results_summary = {'visual_yaw': {'gps_latency': latency}} if latency else {}
        self.gps_time_scale = 0.96
        self.gps_time_offset = 0.72


def _rec_like(n=6, step_m=3.0):
    """Trois trames par fixe (+0, +0,1, +0,4 s), la navette avance de `step_m` par seconde vers le nord."""
    out = []
    for k in range(n):
        lat = 45.0 + k * step_m / 111320.0
        for dt in (0.556, 0.654, 0.971):
            out.append({'ts': k + dt, 'lat': lat, 'lon': 4.0})
    return out


class DistinctFixesTest(unittest.TestCase):

    def test_each_fix_is_kept_once_at_its_first_reception(self):
        fixes = distinct_fixes(_rec_like())
        self.assertEqual([round(p['ts'], 3) for p in fixes], [0.556, 1.556, 2.556, 3.556, 4.556, 5.556])

    def test_a_clean_track_comes_back_as_the_same_object(self):
        clean = distinct_fixes(_rec_like())
        self.assertIs(distinct_fixes(clean), clean)

    def test_a_held_position_keeps_its_last_entry_so_the_stop_does_not_slide(self):
        track = [{'ts': 0.0, 'lat': 45.0, 'lon': 4.0}]
        track += [{'ts': t, 'lat': 45.00001, 'lon': 4.0} for t in (1.0, 2.0, 3.0, 4.0)]
        track += [{'ts': 5.0, 'lat': 45.00005, 'lon': 4.0}]
        self.assertEqual([p['ts'] for p in distinct_fixes(track)], [0.0, 1.0, 4.0, 5.0])

    def test_the_speed_is_the_real_one_and_never_zero_while_moving(self):
        fixes = annotate_gps_heading_speed(distinct_fixes(_rec_like(step_m=3.0)))
        for p in fixes[1:]:
            self.assertAlmostEqual(p['speed_kmh'], 3.0 * 3.6, delta=0.05)

    def test_the_stored_triplicated_track_gave_zero_two_times_out_of_three(self):
        """Le défaut corrigé, rejoué : l'ancienne annotation sur les entrées répétées."""
        old = annotate_gps_heading_speed([dict(p) for p in _rec_like()])
        zeros = sum(1 for p in old[1:] if p['speed_kmh'] == 0.0)
        self.assertEqual(zeros, 12, 'deux trames répétées par fixe, six fixes')


class GpsFixesTest(unittest.TestCase):

    def test_an_old_triplicated_track_is_read_as_fixes_without_rewriting_it(self):
        stored = _rec_like()
        s = _Session(stored)
        fixes = gps_fixes(s)
        self.assertEqual(len(fixes), 6)
        self.assertEqual(len(s.gps_track), 18, "la trace stockée n'est pas réécrite")
        self.assertNotIn('speed_kmh', stored[0], "les entrées stockées ne sont pas modifiées")
        self.assertIs(gps_fixes(s), fixes, 'mémorisé sur la session')

    def test_effective_track_reads_the_fixes(self):
        s = _Session(_rec_like())
        self.assertEqual(len(effective_gps_track(s)), 6)


class GpsLatencyMappingTest(unittest.TestCase):
    LAT = {'latency_s': 0.55, 'r': 0.83, 'applicable': True}

    def test_off_by_default_the_mapping_is_the_rec_sync(self):
        self.assertEqual(gps_time_mapping(_Session(latency=self.LAT)), (0.96, 0.72))

    def test_on_the_measured_latency_is_added_to_the_offset(self):
        s = _Session(features={'gps_latency': True}, latency=self.LAT)
        scale, off = gps_time_mapping(s)
        self.assertAlmostEqual(off, 0.72 + 0.55)
        self.assertAlmostEqual(video_to_gps_time(s, 100.0), 100.0 * 0.96 + 0.72 + 0.55)

    def test_a_measure_judged_not_applicable_is_not_applied(self):
        s = _Session(features={'gps_latency': True}, latency={**self.LAT, 'applicable': False})
        self.assertEqual(gps_time_mapping(s), (0.96, 0.72))

    def test_on_without_a_measure_changes_nothing(self):
        self.assertEqual(gps_time_mapping(_Session(features={'gps_latency': True})), (0.96, 0.72))
