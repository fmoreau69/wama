"""La CAPTURE caméra / micro, brique commune `common/js/wama-capture.js` (2026-10-26).

Trois gardes :
  1. la brique servie (`staticfiles/`), exécutée dans V8 avec un faux navigateur : refus expliqués,
     repli sur le périphérique par défaut, noms des périphériques sans flux laissé ouvert,
     enregistrement, pistes rendues en quittant la page ;
  2. `base.html` la charge AVANT ses consommateurs (médiathèque, écoute de l'assistant) ;
  3. aucune page n'accède plus au périphérique sans elle — la raison de la brique : quatre sites
     refaisaient chacun une partie du contrôle, aucun le tout.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

User = get_user_model()

STATIC_JS = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'

# Un navigateur minimal : `getUserMedia` répond par la file `answers` (un nom d'erreur, ou rien pour
# un flux), chaque flux compte ses pistes arrêtées, `enumerateDevices` rend `found`.
FAKE_BROWSER = r"""
var window = this;
var listeners = {};
window.addEventListener = function (name, fn) { (listeners[name] = listeners[name] || []).push(fn); };
window.isSecureContext = true;
var asked = [], answers = [], found = [], stopped = 0, applied = [];
function Track(kind) {
  this.kind = kind;
  this.getSettings = function () { return { width: 1920, height: 1080, echoCancellation: true }; };
  this.getCapabilities = function () { return kind === 'video' ? { zoom: { min: 1, max: 4, step: 0.1 } } : {}; };
  this.applyConstraints = function (c) { applied.push(c); return Promise.resolve(); };
  this.readyState = 'live';
  this.stop = function () { stopped++; this.readyState = 'ended'; };
}
function Stream(constraints) {
  var tracks = [];
  if (constraints.video) tracks.push(new Track('video'));
  if (constraints.audio) tracks.push(new Track('audio'));
  this.getTracks = function () { return tracks; };
  this.getVideoTracks = function () { return tracks.filter(function (t) { return t.kind === 'video'; }); };
  this.getAudioTracks = function () { return tracks.filter(function (t) { return t.kind === 'audio'; }); };
}
var navigator = { mediaDevices: {
  getUserMedia: function (c) {
    asked.push(c);
    var name = answers.shift();
    if (name) { var e = new Error('refus simulé'); e.name = name; return Promise.reject(e); }
    return Promise.resolve(new Stream(c));
  },
  enumerateDevices: function () { return Promise.resolve(found); },
}, permissions: { query: function (d) { return Promise.resolve({ state: d.name === 'camera' ? 'granted' : 'prompt' }); } } };
var Blob = function (parts, opts) { this.parts = parts; this.type = (opts || {}).type; this.size = parts.length; };
function MediaRecorder(stream) {
  var self = this;
  this.state = 'inactive';
  this.mimeType = 'audio/ogg';
  this.start = function () { self.state = 'recording'; };
  this.stop = function () {
    self.state = 'inactive';
    self.ondataavailable({ data: { size: 3 } });
    self.onstop();
  };
}
window.MediaRecorder = MediaRecorder;
var out = {};
function keep(key) { return function (v) { out[key] = v; }; }
function keepError(key) { return function (e) { out[key] = { message: e.message, reason: e.reason }; }; }
"""


class CaptureBrickTest(SimpleTestCase):
    """La brique servie, exécutée par V8."""

    def _ctx(self, secure=True, public_url=None):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        ctx = MiniRacer()
        # La balise de la brique, telle que base.html la pose (`data-public-url`).
        tag = ('' if public_url is None else
               'var document = { currentScript: { getAttribute: function (n) { '
               'return n === "data-public-url" ? %s : null; } } };' % json.dumps(public_url))
        ctx.eval(FAKE_BROWSER + tag + ('' if secure else 'window.isSecureContext = false;')
                 + (STATIC_JS / 'wama-capture.js').read_text(encoding='utf-8'))
        return ctx

    def _js(self, ctx, expr):
        return json.loads(ctx.eval('JSON.stringify(%s)' % expr))

    def test_an_insecure_page_is_told_to_use_https_and_asks_nothing(self):
        ctx = self._ctx(secure=False)
        ctx.eval("WamaCapture.open({ audio: true }).catch(keepError('mic'));"
                 "WamaCapture.open({ video: true }).catch(keepError('cam'));")
        mic, cam = self._js(ctx, 'out.mic'), self._js(ctx, 'out.cam')
        self.assertFalse(self._js(ctx, 'WamaCapture.available()'))
        self.assertEqual(('insecure', 'insecure'), (mic['reason'], cam['reason']))
        self.assertIn("Le micro n'est disponible qu'en connexion sécurisée", mic['message'])
        self.assertIn("La caméra n'est disponible qu'en connexion sécurisée", cam['message'])
        for message in (mic['message'], cam['message']):
            self.assertIn('https', message)
            self.assertIn('localhost', message)
            self.assertNotIn('(http', message, 'aucune adresse déclarée : aucune adresse citée')
        self.assertEqual([], self._js(ctx, 'asked'), 'aucune demande au navigateur')

    def test_the_declared_public_address_is_named_only_when_it_is_https(self):
        insecure = "WamaCapture.explain({ reason: 'insecure' }, 'microphone')"
        self.assertIn('https (https://wama.exemple.fr) ou',
                      self._ctx(secure=False, public_url='https://wama.exemple.fr').eval(insecure))
        self.assertNotIn('wama.exemple.fr',
                         self._ctx(secure=False, public_url='http://wama.exemple.fr').eval(insecure),
                         "une adresse en http n'est pas la réponse à « il faut https »")

    def test_every_refusal_is_explained_for_each_device(self):
        ctx = self._ctx()
        cases = {
            'NotAllowedError': ('Micro refusé : autorisez-le', 'Caméra refusée : autorisez-la'),
            'SecurityError': ('Micro refusé', 'Caméra refusée'),
            'NotFoundError': ('Aucun micro détecté', 'Aucune caméra détectée'),
            'OverconstrainedError': ('Aucun micro détecté', 'Aucune caméra détectée'),
            'NotReadableError': ('Le micro est utilisé par une autre application',
                                 'La caméra est utilisée par une autre application'),
            'AbortError': ('Micro indisponible : refus simulé', 'Caméra indisponible : refus simulé'),
        }
        for name, (mic, cam) in cases.items():
            with self.subTest(name):
                ctx.eval("out = {}; answers = [%r, %r];"
                         "WamaCapture.open({ audio: true }).catch(keepError('mic'));"
                         "WamaCapture.open({ video: true }).catch(keepError('cam'));" % (name, name))
                self.assertIn(mic, self._js(ctx, 'out.mic.message'))
                self.assertIn(cam, self._js(ctx, 'out.cam.message'))
                self.assertEqual(name, self._js(ctx, 'out.mic.reason'))

    def test_an_already_explained_error_keeps_its_message(self):
        ctx = self._ctx()
        ctx.eval("answers = ['NotReadableError']; WamaCapture.open({ audio: true }).catch(keep('err'));")
        self.assertEqual('Le micro est utilisé par une autre application.',
                         ctx.eval("WamaCapture.explain(out.err, 'camera')"),
                         "le message d'`open` n'est pas réécrit pour un autre périphérique")
        self.assertEqual('Micro indisponible : module absent',
                         ctx.eval("WamaCapture.explain(new Error('module absent'), 'microphone')"))

    def test_a_chosen_camera_that_fails_falls_back_to_the_default_and_says_so(self):
        ctx = self._ctx()
        ctx.eval("""
            var fellBack = 0;
            answers = ['OverconstrainedError'];
            WamaCapture.open({ video: { deviceId: { exact: 'gone' }, width: { ideal: 1920 } }, audio: false },
                             { fallback: true, onFallback: function () { fellBack++; } }).then(keep('stream'));
        """)
        asked = self._js(ctx, 'asked')
        self.assertEqual(2, len(asked))
        self.assertEqual({'width': {'ideal': 1920}, 'facingMode': 'user'}, asked[1]['video'],
                         'le choix est retiré, le reste de la demande est gardé')
        self.assertEqual(1, self._js(ctx, 'fellBack'))
        self.assertTrue(self._js(ctx, '!!out.stream'))

    def test_a_refused_access_never_falls_back(self):
        ctx = self._ctx()
        ctx.eval("answers = ['NotAllowedError'];"
                 "WamaCapture.open({ video: { deviceId: { exact: 'cam1' } } }, { fallback: true })"
                 ".catch(keepError('err'));")
        self.assertEqual(1, self._js(ctx, 'asked.length'), 'un refus ne redemande pas en silence')
        self.assertEqual('NotAllowedError', self._js(ctx, 'out.err.reason'))

    def test_without_fallback_a_chosen_device_failure_is_reported(self):
        ctx = self._ctx()
        ctx.eval("answers = ['NotFoundError'];"
                 "WamaCapture.open({ video: { deviceId: { exact: 'cam1' } } }).catch(keepError('err'));")
        self.assertEqual(1, self._js(ctx, 'asked.length'))
        self.assertIn('Aucune caméra détectée', self._js(ctx, 'out.err.message'))

    def test_device_names_are_asked_for_with_a_probe_that_is_closed_at_once(self):
        ctx = self._ctx()
        ctx.eval("""
            found = [{ kind: 'videoinput', deviceId: 'a', label: '' },
                     { kind: 'audioinput', deviceId: 'm', label: '' }];
            var probing = navigator.mediaDevices.getUserMedia;
            navigator.mediaDevices.getUserMedia = function (c) {
              found = [{ kind: 'videoinput', deviceId: 'a', label: 'Webcam HD' },
                       { kind: 'videoinput', deviceId: 'b', label: '' }];
              return probing(c);
            };
            WamaCapture.devices('camera', { ask: true }).then(keep('cams'));
        """)
        self.assertEqual([{'deviceId': 'a', 'label': 'Webcam HD'}, {'deviceId': 'b', 'label': 'Caméra 2'}],
                         self._js(ctx, 'out.cams'))
        self.assertEqual([{'video': True}], self._js(ctx, 'asked'))
        self.assertEqual(1, self._js(ctx, 'stopped'), 'le flux de la demande est refermé')

    def test_device_names_already_known_ask_for_nothing(self):
        ctx = self._ctx()
        ctx.eval("found = [{ kind: 'audioinput', deviceId: 'm', label: 'Micro USB' },"
                 "         { kind: 'videoinput', deviceId: 'a', label: 'Webcam' }];"
                 "WamaCapture.devices('microphone', { ask: true }).then(keep('mics'));"
                 "WamaCapture.devices('camera').then(keep('cams'));")
        self.assertEqual([{'deviceId': 'm', 'label': 'Micro USB'}], self._js(ctx, 'out.mics'))
        self.assertEqual([{'deviceId': 'a', 'label': 'Webcam'}], self._js(ctx, 'out.cams'))
        self.assertEqual([], self._js(ctx, 'asked'))

    def test_permission_is_read_without_asking(self):
        ctx = self._ctx()
        ctx.eval("WamaCapture.permission('camera').then(keep('cam'));"
                 "WamaCapture.permission('microphone').then(keep('mic'));")
        self.assertEqual(('granted', 'prompt'), (self._js(ctx, 'out.cam'), self._js(ctx, 'out.mic')))
        ctx.eval("delete navigator.permissions; WamaCapture.permission('camera').then(keep('none'));")
        self.assertEqual('unknown', self._js(ctx, 'out.none'))
        self.assertEqual([], self._js(ctx, 'asked'))

    def test_track_settings_and_hardware_zoom(self):
        ctx = self._ctx()
        ctx.eval("WamaCapture.open({ video: true }).then(keep('s'));")
        self.assertEqual(1920, self._js(ctx, "WamaCapture.trackSettings(out.s, 'camera').width"))
        self.assertTrue(self._js(ctx, "WamaCapture.trackSettings(out.s, 'microphone').echoCancellation === undefined"))
        self.assertEqual({'min': 1, 'max': 4, 'step': 0.1}, self._js(ctx, 'WamaCapture.zoomRange(out.s)'))
        ctx.eval("WamaCapture.setZoom(out.s, 9); WamaCapture.setZoom(out.s, null);")
        self.assertEqual([{'advanced': [{'zoom': 4}]}, {'advanced': [{'zoom': 1}]}], self._js(ctx, 'applied'),
                         'borné à la plage ; sans valeur, le plus large')
        self.assertEqual({}, self._js(ctx, 'WamaCapture.trackSettings(null)'))

    def test_a_recording_ends_once_with_the_recorder_type(self):
        ctx = self._ctx()
        ctx.eval("""
            WamaCapture.open({ audio: true }).then(function (s) {
              var r = WamaCapture.record(s);
              out.state = r.state();
              var first = r.stop();
              out.same = first === r.stop();
              first.then(keep('blob'));
            });
        """)
        self.assertEqual('recording', self._js(ctx, 'out.state'))
        self.assertTrue(self._js(ctx, 'out.same'), 'un second stop() rend la même fin')
        self.assertEqual('audio/ogg', self._js(ctx, 'out.blob.type'))

    def test_no_recorder_means_no_recording(self):
        ctx = self._ctx()
        ctx.eval("window.MediaRecorder = undefined;"
                 "WamaCapture.open({ audio: true }).then(function (s) { out.r = WamaCapture.record(s); });")
        self.assertIsNone(self._js(ctx, 'out.r'))

    def test_leaving_the_page_releases_every_open_stream_once(self):
        ctx = self._ctx()
        ctx.eval("WamaCapture.open({ video: true, audio: true }).then(keep('a'));"
                 "WamaCapture.open({ audio: true }).then(keep('b'));")
        ctx.eval("WamaCapture.close(out.b); WamaCapture.close(out.b); WamaCapture.close(null);")
        self.assertEqual(1, self._js(ctx, 'stopped'))
        ctx.eval("listeners.pagehide.forEach(function (fn) { fn(); });")
        self.assertEqual(3, self._js(ctx, 'stopped'), 'les deux pistes du flux encore ouvert')
        ctx.eval("listeners.pagehide.forEach(function (fn) { fn(); });")
        self.assertEqual(3, self._js(ctx, 'stopped'), 'rien de rendu deux fois')


class CaptureBrickIsLoadedFirstTest(TestCase):
    """`base.html` charge la brique avant les pages et briques qui ouvrent un périphérique."""

    def _home(self):
        user = User.objects.create_user('capture_tester', password='x', is_staff=True, is_superuser=True)
        self.client.force_login(user)
        return self.client.get(reverse('home')).content.decode()

    @override_settings(WAMA_PUBLIC_URL='https://wama.exemple.fr')
    def test_the_brick_is_given_the_declared_public_address(self):
        self.assertRegex(self._home(), r'wama-capture\.js[^"]*" data-public-url="https://wama\.exemple\.fr"')

    @override_settings(WAMA_PUBLIC_URL='')
    def test_without_a_declared_address_the_brick_is_given_none(self):
        self.assertRegex(self._home(), r'wama-capture\.js[^"]*" data-public-url=""')

    def test_the_capture_brick_comes_before_its_consumers(self):
        html = self._home()
        at = html.find('common/js/wama-capture.js')
        self.assertNotEqual(-1, at)
        for consumer in ('common/js/library-add.js', 'common/js/wama-assistant-listen.js'):
            with self.subTest(consumer):
                self.assertLess(at, html.find(consumer))


class NoDeviceAccessOutsideTheBrickTest(SimpleTestCase):
    """Aucune page, aucune brique n'ouvre la caméra ou le micro, ne liste les périphériques ni
    n'enregistre sans `WamaCapture` : c'est elle qui vérifie le contexte sécurisé, explique un
    refus et rend les pistes."""

    PATTERN = re.compile(r'\bgetUserMedia\s*\(|\benumerateDevices\s*\(|\bMediaRecorder\s*\('
                         r'|permissions\.query\s*\(')
    HOME = 'wama/common/static/common/js/wama-capture.js'

    def test_only_the_brick_touches_the_devices(self):
        base = Path(settings.BASE_DIR)
        found = []
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in list((base / root).rglob('*.js')) + list((base / root).rglob('templates/**/*.html')):
                parts = set(path.parts)
                if 'vendors' in parts or 'staticfiles' in parts or path.name.endswith('.min.js'):
                    continue
                rel = path.relative_to(base).as_posix()
                if rel == self.HOME:
                    continue
                text = path.read_text(encoding='utf-8', errors='replace')
                found += ['%s:%d' % (rel, text.count('\n', 0, m.start()) + 1) for m in self.PATTERN.finditer(text)]
        self.assertEqual([], found)

    def test_the_guard_sees_a_direct_access(self):
        """Contre-épreuve : le motif reconnaît les quatre formes qu'il interdit."""
        for line in ("navigator.mediaDevices.getUserMedia({ video: true })",
                     "await navigator.mediaDevices.enumerateDevices()",
                     "new MediaRecorder(stream)",
                     "navigator.permissions.query({ name: 'microphone' })"):
            with self.subTest(line):
                self.assertRegex(line, self.PATTERN)
