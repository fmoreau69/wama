"""L'overlay des caméras ne se FIGE plus hors des fenêtres SAM3 — gardes exécutées dans V8.

Défaut mesuré au navigateur le 2026-09-28 (session P97, parcours analysé en entier) :
`sam3Interpolated` évinçait une keyframe trop ancienne APRÈS son test « ni avant ni après »,
puis lisait `kf2.timestamp` sur null. Le try/finally de la boucle d'animation (2026-07-20) la
faisait survivre, mais le canvas n'était plus ni effacé ni redessiné : l'overlay restait sur la
dernière image réussie pendant que la vidéo avançait, dès la sortie d'une fenêtre d'intersection.

Les fonctions sont EXTRAITES du fichier servi (`staticfiles/`) — le module est un IIFE qui touche
au DOM, on n'exécute que ce qu'on teste. Même patron que `common/tests_wama_params_options.py`.
⚠ `py_mini_racer` n'est installé que dans venv_win : ces tests SKIPPENT sous venv_linux.
"""
import json
import random
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SERVED_JS = Path(settings.BASE_DIR) / 'staticfiles/cam_analyzer/js/index.js'
FUNCTIONS = ('_sam3Of', '_sam3BBox', 'firstFrameAtOrAfter', 'sam3Interpolated', 'withSam3Interp',
             'drawOverlayAt')


def extract_function(src, name):
    """Le texte de `function <name>(…) { … }`, accolades appariées."""
    start = src.index(f'function {name}(')
    depth, i = 0, src.index('{', start)
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise ValueError(name)


# Référence NAÏVE : l'ancien balayage depuis la 1re image, avec l'ordre des tests CORRIGÉ.
# La version dichotomique doit rendre exactement la même chose.
NAIVE_KEYFRAMES = """
function naiveKeyframes(frames, t) {
  let kf1 = null, kf2 = null;
  for (let i = 0; i < frames.length; i++) {
    const fr = frames[i];
    if (fr.timestamp > t + 1.2) break;
    if (fr.timestamp <= t + 0.02 && _sam3Of(fr).length) kf1 = fr;
    else if (fr.timestamp > t + 0.02 && !kf2 && _sam3Of(fr).length && fr.timestamp <= t + 1.2) { kf2 = fr; break; }
  }
  if (kf1 && t - kf1.timestamp > 1.2) kf1 = null;
  return [kf1 ? kf1.timestamp : null, kf2 ? kf2.timestamp : null];
}
"""


class OverlayJsTestBase(SimpleTestCase):
    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter le module')
        src = SERVED_JS.read_text(encoding='utf-8')
        self.ctx = MiniRacer()
        self.ctx.eval('var camFeat = {}; var calls = []; var warns = [];'
                      'var console = {warn: (...a) => warns.push(String(a[0]))};'
                      'function clearCanvas(pos) { calls.push("clear:" + pos); }'
                      'function drawDetections(pos) { calls.push("draw:" + pos); }'
                      'function findClosestFrame(frames, t) { return frames[0] || null; }'
                      'const _overlayErrorWarned = {};')
        for name in FUNCTIONS:
            self.ctx.eval(extract_function(src, name))

    @staticmethod
    def frames(sam3_times, until=60.0, fps=12.0):
        """Des images régulières ; une keyframe SAM3 aux instants donnés (les fenêtres)."""
        keys = {round(t * fps) for t in sam3_times}
        out = []
        for n in range(int(until * fps)):
            dets = [{'type': 'yolo', 'bbox': [0, 0, 10, 10]}]
            if n in keys:
                dets.append({'type': 'sam3_marking', 'label': 'crossing', 'bbox': [1, 1, 5, 5]})
            out.append({'timestamp': n / fps, 'detections': dets})
        return out


class Sam3InterpolationOutsideWindowsTest(OverlayJsTestBase):
    def test_no_keyframe_left_after_a_window_returns_null_instead_of_raising(self):
        # SAM3 jusqu'à 10 s (dans la fenêtre), puis plus rien : à 20 s, la dernière keyframe a
        # 10 s — c'est le cas qui levait `kf2.timestamp` sur null.
        self.ctx.eval('var F = %s;' % json.dumps(self.frames([i * 0.5 for i in range(21)])))
        self.assertIsNone(self.ctx.eval('sam3Interpolated(F, 20.0)'))

    def test_detections_pass_through_unchanged_outside_windows(self):
        self.ctx.eval('var F = %s;' % json.dumps(self.frames([i * 0.5 for i in range(21)])))
        out = json.loads(self.ctx.eval('JSON.stringify(withSam3Interp(F, 20.0, [{type: "yolo"}]))'))
        self.assertEqual(out, [{'type': 'yolo'}])

    def test_counterproof_a_recent_keyframe_still_fades_out(self):
        # Contre-épreuve : 0,3 s après la dernière keyframe, le fondu de sortie est toujours là.
        self.ctx.eval('var F = %s;' % json.dumps(self.frames([i * 0.5 for i in range(21)])))
        out = json.loads(self.ctx.eval('JSON.stringify(sam3Interpolated(F, 10.3))'))
        self.assertEqual(len(out), 1)
        self.assertLess(out[0]['_alpha'], 1.0)


class Sam3KeyframeSearchEquivalenceTest(OverlayJsTestBase):
    def test_bisection_start_finds_the_same_keyframes_as_a_full_scan(self):
        # Keyframes par grappes (fenêtres) et trous longs : on compare, instant par instant, les
        # keyframes retenues par `sam3Interpolated` (via son effet : null ou non) et par un
        # balayage complet — sur des instants tirés partout, bords de fenêtres compris.
        rng = random.Random(20260928)
        keys = [t for w0 in (5.0, 22.0, 41.0) for t in [w0 + k * 0.5 for k in range(12)]]
        self.ctx.eval('var F = %s;' % json.dumps(self.frames(keys)))
        self.ctx.eval(extract_function(NAIVE_KEYFRAMES, 'naiveKeyframes'))
        instants = [rng.uniform(0, 60) for _ in range(300)] + [k + d for k in keys for d in (-1.21, -0.3, 0.02, 1.19)]
        for t in instants:
            naive = self.ctx.eval('JSON.stringify(naiveKeyframes(F, %r))' % t)
            got = self.ctx.eval('sam3Interpolated(F, %r) === null' % t)
            self.assertEqual(got, naive == '[null,null]', f't={t:.3f} naïf={naive}')


class OverlayNeverFreezesTest(OverlayJsTestBase):
    def test_a_rendering_error_clears_the_canvas_and_warns_once(self):
        self.ctx.eval('drawDetections = function () { throw new Error("rendu cassé"); };')
        data = {'frames': [{'timestamp': 0, 'detections': [{'type': 'yolo'}]}], 'width': 10, 'height': 10}
        for _ in range(3):
            self.ctx.eval('drawOverlayAt("front", %s, 0)' % json.dumps(data))
        self.assertEqual(json.loads(self.ctx.eval('JSON.stringify(calls)')), ['clear:front'] * 3)
        self.assertEqual(len(json.loads(self.ctx.eval('JSON.stringify(warns)'))), 1)

    def test_counterproof_a_healthy_frame_is_drawn(self):
        data = {'frames': [{'timestamp': 0, 'detections': [{'type': 'yolo'}]}], 'width': 10, 'height': 10}
        self.ctx.eval('drawOverlayAt("rear", %s, 0)' % json.dumps(data))
        self.assertEqual(json.loads(self.ctx.eval('JSON.stringify(calls)')), ['draw:rear'])
