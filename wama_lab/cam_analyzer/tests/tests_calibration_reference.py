"""La calibration sol se juge sur les immobiles COMPACTS, pas sur les garés (2026-10-01).

Sous ⚑ parked_off_road, les garés sont qualifiés hors chaussée — 1433 à 1694 objets, observés à 19 m —
et la calibration y mesurait 2,7 à 7,8 m d'étalement : toutes les caméras rejetées, placement 100 %
pinhole. Sur les compacts (115 à 155 objets, 13 m) : 0,64 à 1,45 m, toutes acceptées.
"""
import inspect

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils import multicam_tracker
from wama_lab.cam_analyzer.utils.homography_estimator import calibration_reference


class CalibrationReferenceTest(SimpleTestCase):
    def test_the_compact_reference_wins_over_the_parked_vehicles(self):
        rs = {'calibration_reference_gids': [3, 4], 'stationary_global_tracks': [1, 2, 3, 4, 5]}
        self.assertEqual(calibration_reference(rs), {3, 4})

    def test_an_empty_reference_is_a_measure_not_a_missing_value(self):
        """Aucun immobile compact : la calibration n'a rien sur quoi se juger — elle ne doit pas
        retomber en silence sur les garés, qui sont précisément la population qui la fausse."""
        rs = {'calibration_reference_gids': [], 'stationary_global_tracks': [1, 2]}
        self.assertEqual(calibration_reference(rs), set())

    def test_a_tracking_older_than_the_reference_falls_back_on_parked_vehicles(self):
        self.assertEqual(calibration_reference({'stationary_global_tracks': [7]}), {7})
        self.assertEqual(calibration_reference(None), set())

    def test_the_compactness_gates_run_whatever_the_parked_rule(self):
        """La référence est remplie AVANT la branche « hors voies », qui sort de la boucle."""
        src = inspect.getsource(multicam_tracker.annotate_global_tracks)
        gate = src.index('def _compactness_gate')
        loop = src[src.index('for gid, hist in track_hist.items():', gate):]
        self.assertLess(loop.index('calibration_reference.append(gid)'),
                        loop.index('if _footprint is not None:'))
        self.assertIn("'calibration_reference_gids': calibration_reference", src)

    def test_the_placement_metric_measures_the_same_population_as_the_calibration(self):
        src = inspect.getsource(multicam_tracker.annotate_global_tracks)
        block = src[src.index('_pos_by_stat = '):src.index('placement_spread = track_position_spread')]
        self.assertIn('calibration_reference', block)
        self.assertNotIn('_stat_set', block)


class OrthoPerPassMeasureTest(SimpleTestCase):
    """Mesure PAR PASSAGE du recalage ortho (2026-10-01) : ce qu'elle rend est rangé tel quel dans
    `results_summary` — un flottant numpy y casserait l'écriture JSON."""

    def test_the_measure_casts_projected_values_to_python_floats(self):
        src = inspect.getsource(__import__(
            'wama_lab.cam_analyzer.utils.ortho_markings', fromlist=['measure_passes']).measure_passes)
        self.assertIn('delta = float(map_near - min(pts))', src)
        self.assertIn('stamps.append(float(tg))', src)

    def test_the_correction_pass_measures_per_pass_not_per_place(self):
        from wama_lab.cam_analyzer import tasks
        src = inspect.getsource(tasks.compute_ortho_correction_task)
        self.assertIn('measure_passes(session)', src)
        self.assertIn('decompose_passes(passes)', src)
        self.assertIn('reach_s=PASS_REACH_S', src)
        self.assertNotIn('decompose(rec)', src)
