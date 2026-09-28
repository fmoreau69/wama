"""⚑ ortho_correction côté serveur — la bascule CHOISIT, le serveur et le JS appliquent la MÊME chose.

Jusqu'au 2026-09-28 la correction ortho n'était appliquée qu'à l'AFFICHAGE (`_applyOrthoCorrection`) :
le tracking, les marquages et la prédiction lisaient la trace brute alors que la bascule se disait
`compute`. Et sa tâche ne calculait rien bascule OFF. Gardé ici : l'application au point d'accès
unique (`ego_pose.effective_gps_track`), le miroir JS (exécuté dans V8 sur le fichier SERVI), et la
règle « jamais la correction sur elle-même » pour les calculs qui la fondent.
⚠ `py_mini_racer` n'est que dans venv_win : le test du miroir SKIPPE sous venv_linux.
"""
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils.ego_pose import apply_ortho_correction, effective_gps_track

GPS = [{'ts': 10.0, 'lat': 43.6188, 'lon': 7.0751, 'heading': 0.0},
       {'ts': 20.0, 'lat': 43.6190, 'lon': 7.0751, 'heading': 0.0},
       {'ts': 30.0, 'lat': 43.6192, 'lon': 7.0751, 'heading': 0.0}]
ANCHORS = [{'ts': 10.0, 'de_m': -3.0, 'dn_m': 1.0, 'n': 4, 'alpha': 1.0},
           {'ts': 30.0, 'de_m': -1.0, 'dn_m': 0.0, 'n': 2, 'alpha': 1.0}]


def _session(on):
    return SimpleNamespace(gps_track=GPS, config={'features': {'ortho_correction': on, 'shuttle_filter': False,
                                                               'lane_map_recalage': False}},
                           results_summary={'ortho_correction': {'anchors': ANCHORS}})


class OrthoToggleTest(SimpleTestCase):
    def test_off_returns_the_track_untouched(self):
        self.assertIs(effective_gps_track(_session(False)), GPS)

    def test_on_moves_the_positioning_track(self):
        out = effective_gps_track(_session(True))
        self.assertAlmostEqual((out[0]['lon'] - GPS[0]['lon']) * 111320 * 0.7243, -3.0, delta=0.01)
        self.assertAlmostEqual((out[0]['lat'] - GPS[0]['lat']) * 111320, 1.0, delta=0.01)
        self.assertEqual(out[0]['lat_preortho'], GPS[0]['lat'])

    def test_the_measure_and_the_lane_computation_read_the_track_without_it(self):
        self.assertIs(effective_gps_track(_session(True), ortho=False), GPS)
        self.assertIs(effective_gps_track(_session(True), lane_map=False), GPS)


class SelfCorrectionTest(SimpleTestCase):
    def test_world_markings_are_placed_without_the_ortho_correction(self):
        # le recalage ortho MESURE sur ces marquages : les placer corrigés lui ferait mesurer un
        # résidu, et la correction suivante oscillerait
        from wama_lab.cam_analyzer.utils import marking_world
        self.assertIn('effective_gps_track(session, ortho=False)', inspect.getsource(marking_world))

    def test_the_correction_is_computed_whatever_the_toggle(self):
        from wama_lab.cam_analyzer import tasks
        src = inspect.getsource(tasks.compute_ortho_correction_task)
        self.assertNotIn("get('ortho_correction'", src)
        self.assertIn("mark_completed(session, 'ortho_correction'", src)


class JsMirrorTest(SimpleTestCase):
    def test_the_display_applies_exactly_what_the_server_applies(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        from wama_lab.cam_analyzer.tests_overlay_js import extract_function
        src = (Path(settings.BASE_DIR) / 'staticfiles/cam_analyzer/js/index.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval('var camFeat = {ortho_correction: true}; var orthoCorrection = {anchors: %s};'
                 % json.dumps(ANCHORS))
        ctx.eval(extract_function(src, '_orthoOffsetAt'))
        ctx.eval(extract_function(src, '_applyOrthoCorrection'))
        track = GPS + [{'ts': 15.0, 'lat': 43.6189, 'lon': 7.0751}]
        js = json.loads(ctx.eval('JSON.stringify(_applyOrthoCorrection(%s))' % json.dumps(track)))
        py = apply_ortho_correction(track, ANCHORS)
        for a, b in zip(js, py):
            self.assertAlmostEqual(a['lat'], b['lat'], places=9)
            self.assertAlmostEqual(a['lon'], b['lon'], places=9)
