"""Le tracking 360° repart de ZÉRO à chaque calcul (2026-09-30).

Mesuré sur la session 4da52df3 : 293 153 détections de stationnés gardaient un `world_en` d'un calcul
antérieur (6 m en médiane de leur ancre fraîche, jusqu'à 838 m), et 17 737 artefacts un
`global_track_id` périmé que les Indicateurs fondaient dans le track d'un autre objet.
"""
import inspect

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils import multicam_tracker, prediction_adapter
from wama_lab.cam_analyzer.utils.multicam_tracker import TRACKER_FIELDS, reset_tracker_fields


class TrackerResetTest(SimpleTestCase):
    def test_every_tracker_field_of_a_real_detection_is_removed(self):
        d = {'class_name': 'car', 'track_id': 7, 'bbox': [1, 2, 3, 4], 'distance_m': 5.0,
             'global_track_id': 3326, 'world_en': [61.3, -242.3], 'stable_class': 'car',
             'stable_class_margin': 0.9, 'artifact': True, 'placement_source': 'pinhole'}
        self.assertEqual(reset_tracker_fields([d]), 1)
        for k in TRACKER_FIELDS:
            self.assertNotIn(k, d)
        # ce que la DÉTECTION a produit reste : seul l'état du tracker s'efface
        self.assertEqual(d, {'class_name': 'car', 'track_id': 7, 'bbox': [1, 2, 3, 4],
                             'distance_m': 5.0})

    def test_ghosts_and_untouched_detections_are_left_alone(self):
        ghost = {'predicted': True, 'global_track_id': 12, 'world_en': [1.0, 2.0]}
        clean = {'class_name': 'car', 'track_id': 3}
        self.assertEqual(reset_tracker_fields([ghost, clean]), 0)
        self.assertEqual(ghost['global_track_id'], 12)      # les fantômes ont leur propre purge
        self.assertEqual(clean, {'class_name': 'car', 'track_id': 3})

    def test_the_report_counts_only_what_the_new_calculation_did_not_rewrite(self):
        from wama_lab.cam_analyzer.utils.multicam_tracker import stale_fields_report
        parked = {'global_track_id': 5, 'world_en': [0, 0]}     # stationné : gid réécrit, pas world_en
        reflection = {'global_track_id': 9, 'artifact': True}   # artefact : plus associé
        moving = {'global_track_id': 7, 'world_en': [1, 1]}     # mobile : tout réécrit
        removed = []
        reset_tracker_fields([parked, reflection, moving], removed)
        parked['global_track_id'] = 5
        moving.update(global_track_id=7, world_en=[1, 1])
        self.assertEqual(stale_fields_report(removed),
                         {'detections_reset': 3, 'dropped_gid': 1, 'dropped_world_en': 1})

    def test_the_purge_runs_before_the_association(self):
        src = inspect.getsource(multicam_tracker.annotate_global_tracks)
        self.assertIn('reset_tracker_fields(f.detections, _reset)', src)
        self.assertLess(src.index('reset_tracker_fields(f.detections, _reset)'), src.index('for fn in all_fns:'),
                        "la purge précède l'association, sinon elle effacerait le calcul courant")

    def test_indicators_skip_artifacts_before_grouping_by_track(self):
        src = inspect.getsource(prediction_adapter)
        self.assertIn("if d.get('artifact'):", src)
        self.assertLess(src.index("if d.get('artifact'):"),
                        src.index("gid = d.get('global_track_id')"),
                        "un reflet écarté par le tracker ne doit pas devenir un objet des indicateurs")
