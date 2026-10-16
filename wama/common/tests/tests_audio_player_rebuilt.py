"""The common audio player under a REBUILT container (2026-10-15, reported by Fabien : back on the
audio Entry of the side panel, after starting it, « je ne vois plus la lecture ni la waveforme »).

Measured in a browser : the panel renders every face under ONE player id (`insp`). `getAudio` returned
the audio registered for the REPLACED container — still playing outside the DOM — while the player
shown was never initialised. Run under V8 with a fake DOM : the brick's own code, not a copy."""
import importlib.util
import json
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
PLAYER = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js' / 'wama-audio-player.js'

#: A DOM good enough for the player : containers found by id, elements that swallow what they are
#: given, an `Audio` that records its listeners and can fire them, a `fetch` that fails (no waveform
#: decoding : the player falls back to its timeline, as on a long file).
FAKE = """
var window = this;
var listeners = {};
function el() { return {style: {}, dataset: {}, children: [], appendChild: function (c) { this.children.push(c); },
  querySelector: function () { return null; }, addEventListener: function () {},
  getContext: function () { return {clearRect: function () {}, fillRect: function () {}}; }}; }
var dom = {};
var document = {getElementById: function (id) { return dom[id] || null; }, createElement: el,
                addEventListener: function () {}};
function container(url) { var c = el(); c.id = 'audioPlayer_insp'; c.dataset = {audioUrl: url}; return c; }
var made = [];
function Audio() { var a = this; a.paused = true; a.ended = false; a.currentTime = 0; a.readyState = 0;
  a.duration = NaN; a.preload = ''; a.src = ''; a.on = {};
  a.seekable = {length: 0, end: function () { return 0; }};
  a.addEventListener = function (t, fn) { (a.on[t] = a.on[t] || []).push(fn); };
  a.removeEventListener = function (t, fn) { a.on[t] = (a.on[t] || []).filter(function (f) { return f !== fn; }); };
  a.fire = function (t) { (a.on[t] || []).slice().forEach(function (fn) { fn(); }); };
  a.play = function () { a.paused = false; return {catch: function () {}}; };
  a.pause = function () { a.paused = true; }; a.load = function () {};
  made.push(a); }
function fetch() { return Promise.reject(new Error('no network in V8')); }
"""


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class RebuiltContainerTest(SimpleTestCase):

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE)
        self.v8.eval(PLAYER.read_text(encoding='utf-8'))

    def _run(self, body):
        return json.loads(self.v8.eval('JSON.stringify((function () {' + body + '})())'))

    def test_the_audio_of_a_replaced_container_is_never_handed_out(self):
        out = self._run("""
            var P = window.WamaAudioPlayer;
            dom.audioPlayer_insp = container('/a.wav');
            var first = P.getAudio('insp'); first.play();          // the Entry, played
            dom.audioPlayer_insp = container('/a.wav');            // the panel renders the face again
            var stale = P.current('insp');                         // nothing initialised for it yet
            var second = P.getAudio('insp');
            return [first === second, first.paused, stale === null, P.current('insp') === second];
        """)
        self.assertEqual([False, True, True, True], out,
                         'a new player for the new container ; the old audio stops instead of playing unseen')

    def test_release_stops_and_forgets_without_touching_the_dom(self):
        out = self._run("""
            var P = window.WamaAudioPlayer;
            dom.audioPlayer_insp = container('/a.wav');
            var a = P.getAudio('insp'); a.play();
            P.release('insp');
            return [a.paused, P.current('insp') === null, !!dom.audioPlayer_insp];
        """)
        self.assertEqual([True, True, True], out)

    def test_a_position_set_before_the_file_is_seekable_is_applied_once_it_is(self):
        """Measured in a browser : set before the metadata, the position went back to 0 when the
        file was not yet seekable — the playback « followed » the face switch to 0:00."""
        out = self._run("""
            var P = window.WamaAudioPlayer;
            dom.audioPlayer_insp = container('/a.wav');
            P.seek('insp', 12.5, false);
            var a = P.current('insp');
            a.currentTime = 0;                                     // what the browser did at the metadata
            a.readyState = 1; a.duration = 60; a.fire('loadedmetadata');
            var early = a.currentTime;                             // still not seekable : waits
            a.seekable = {length: 1, end: function () { return 60; }}; a.fire('progress');
            var settled = a.currentTime;
            a.currentTime = 3; a.fire('progress');                 // a later seek by the user is kept
            return [early, settled, a.currentTime];
        """)
        self.assertEqual([0, 12.5, 3], out)
