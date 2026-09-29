"""⚑ lane_map_recalage côté app — la bascule CHOISIT, le serveur et le JS appliquent la MÊME chose.

La géométrie est gardée dans `wama_data/functions/driving/tests_lane_map_matching.py` ; ici : le
point d'ingestion unique de la pose (`effective_gps_track`), le centre véhicule (levier
d'antenne) et le miroir JS (`_applyLaneMapRecalage`, exécuté dans V8 sur le fichier SERVI).
⚠ `py_mini_racer` n'est que dans venv_win : le test du miroir SKIPPE sous venv_linux.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils.ego_pose import apply_lane_map_correction, effective_gps_track
from wama_lab.cam_analyzer.utils.lane_map_recalage import centre_track

GPS = [{'ts': 1.0, 'lat': 43.6188, 'lon': 7.0751, 'heading': 0.7},
       {'ts': 2.0, 'lat': 43.6189, 'lon': 7.0751, 'heading': 0.7}]
CORR = [{'ts': 1.0, 'de_m': -2.0, 'dn_m': 0.0, 'dh_deg': -5.9, 'anchored': True},
        {'ts': 2.0, 'de_m': 0.0, 'dn_m': 0.0, 'dh_deg': 0.0, 'anchored': False}]


def _session(on):
    return SimpleNamespace(gps_track=GPS, config={'features': {'lane_map_recalage': on, 'shuttle_filter': False}},
                           results_summary={'lane_map_recalage': {'track': CORR}})


class LaneMapToggleTest(SimpleTestCase):
    def test_off_returns_the_track_untouched(self):
        self.assertIs(effective_gps_track(_session(False)), GPS)

    def test_on_moves_the_position_and_its_heading(self):
        out = effective_gps_track(_session(True))
        self.assertAlmostEqual((out[0]['lon'] - GPS[0]['lon']) * 111320 * 0.7243, -2.0, delta=0.01)
        self.assertAlmostEqual(out[0]['heading'], (0.7 - 5.9) % 360, places=6)
        self.assertEqual(out[0]['lon_prelane'], GPS[0]['lon'])
        self.assertEqual(out[1], GPS[1])                     # correction nulle : point inchangé

    def test_its_own_computation_never_reads_the_corrected_track(self):
        self.assertIs(effective_gps_track(_session(True), lane_map=False), GPS)


class CentreTrackTest(SimpleTestCase):
    def test_the_centre_is_left_of_a_right_hand_antenna_heading_north(self):
        s = SimpleNamespace(config={'gps_antenna': [1.0, 0.0]})
        c = centre_track(s, [{'ts': 0.0, 'lat': 43.6188, 'lon': 7.0751, 'heading': 0.0}])[0]
        east = (c['lon'] - 7.0751) * 111320 * 0.7243
        self.assertLess(east, -0.5)                           # l'antenne est à droite du centre


class JsMirrorTest(SimpleTestCase):
    def test_the_display_applies_exactly_what_the_server_applies(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        from wama_lab.cam_analyzer.tests.tests_overlay_js import extract_function
        src = (Path(settings.BASE_DIR) / 'staticfiles/cam_analyzer/js/index.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval('var camFeat = {lane_map_recalage: true}; var laneMapRecalage = {track: %s};' % json.dumps(CORR))
        ctx.eval(extract_function(src, '_applyLaneMapRecalage'))
        js = json.loads(ctx.eval('JSON.stringify(_applyLaneMapRecalage(%s))' % json.dumps(GPS)))
        py = apply_lane_map_correction(GPS, CORR)
        for a, b in zip(js, py):
            self.assertAlmostEqual(a['lat'], b['lat'], places=9)
            self.assertAlmostEqual(a['lon'], b['lon'], places=9)
            self.assertAlmostEqual(a['heading'], b['heading'], places=9)
