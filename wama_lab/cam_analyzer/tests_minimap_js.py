"""Mini-carte : le clic sur le parcours et la surbrillance du passage parlent la bonne base de temps.

La trace GPS est indexée en temps GPS (`ts`) ; la lecture, la barre, les fenêtres d'intersection et
la pose navette parlent en temps VIDÉO (t_gps = t_vidéo × gpsTimeScale + gpsTimeOffset). Mesuré au
navigateur le 2026-09-29 : un clic sur le tracé plaçait la navette à 119 m du point cliqué
(`best.ts` passé tel quel, reconverti une seconde fois par `findGpsAtTime`), et la surbrillance du
passage courant tombait à 36 m de la navette (bornes vidéo comparées à des `ts` GPS).
Gardes exécutées dans V8 sur le fichier SERVI ; ⚠ elles SKIPPENT sous venv_linux (pas de V8).
"""
import json

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.tests_overlay_js import SERVED_JS, extract_function

SCALE, OFFSET = 0.961, 0.72
# 3 fixes/s le long d'une rue nord-sud, ~5 m/s
TRACK = [{'ts': round(100 + k / 3, 4), 'lat': 43.6180 + k * 1.5e-5, 'lon': 7.0750, 'heading': 0.0}
         for k in range(600)]


class MiniMapTimeBaseTest(SimpleTestCase):
    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        src = SERVED_JS.read_text(encoding='utf-8')
        self.ctx = MiniRacer()
        self.ctx.eval(f"""
            var cachedGpsTrack = {json.dumps(TRACK)}; var gpsTimeScale = {SCALE}, gpsTimeOffset = {OFFSET};
            var camAntenna = [1.0, 0.0]; var calls = {{}}; var miniMap = {{ removeLayer() {{}} }};
            var miniMapClickMarker = null, miniMapPassHighlight = null, miniMapHighlightedPassIdx = -1,
                miniMapShuttleMarker = null, intersectionWindows = [], drawn = null;
            var L = {{ circleMarker: () => ({{ addTo() {{ return this; }} }}),
                      polyline: (pts) => {{ drawn = pts; return {{ addTo() {{ return this; }} }}; }} }};
            function syncSeek(t) {{ calls.seek = t; }}
            function updateMiniMapShuttle(t) {{ calls.shuttle = t; }}
            function updatePassInfo(t) {{ calls.info = t; }}
        """)
        for name in ('antennaCorrect', 'findGpsAtTime', 'gpsToVideoTime', 'handleMiniMapClick',
                     'updateMiniMapPassHighlight'):
            self.ctx.eval(extract_function(src, name))

    def test_clicking_the_drawn_track_puts_the_shuttle_where_one_clicked(self):
        target = self.ctx.eval('JSON.stringify(antennaCorrect(cachedGpsTrack[400]))')
        p = json.loads(target)
        self.ctx.eval(f'handleMiniMapClick({p["lat"]}, {p["lon"]})')
        calls = json.loads(self.ctx.eval('JSON.stringify(calls)'))
        self.assertEqual(calls['seek'], calls['shuttle'])
        self.assertEqual(calls['seek'], calls['info'])
        # la pose que la navette prendra à ce temps VIDÉO est le point cliqué
        shuttle_at = json.loads(self.ctx.eval(f'JSON.stringify(findGpsAtTime({calls["seek"]}))'))
        self.assertAlmostEqual(shuttle_at['lat'], p['lat'], places=7)
        self.assertAlmostEqual(calls['seek'], (TRACK[400]['ts'] - OFFSET) / SCALE, places=6)

    def test_the_current_pass_is_highlighted_where_the_shuttle_is(self):
        t_enter, t_exit = 150.0, 152.0        # temps VIDÉO, comme `window_recompute`
        self.ctx.eval(f'intersectionWindows = [{{t_enter: {t_enter}, t_exit: {t_exit}, _passIdx: 0}}];'
                      f'updateMiniMapPassHighlight({(t_enter + t_exit) / 2});')
        drawn = json.loads(self.ctx.eval('JSON.stringify(drawn)'))
        shuttle_at = json.loads(self.ctx.eval(f'JSON.stringify(findGpsAtTime({(t_enter + t_exit) / 2}))'))
        nearest = min(abs(q[0] - shuttle_at['lat']) * 111320 for q in drawn)
        self.assertLess(nearest, 1.0)
