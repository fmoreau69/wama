"""Le lecteur audio commun (`wama-audio-player.js`) sous un id RÉUTILISÉ, et ses pics serveur.

Deux défauts mesurés au navigateur le 2026-09-28, en alignant l'aperçu de voix du synthesizer
sur ce lecteur :
  1. un conteneur RECONSTRUIT sous le même id (l'inspecteur n'a qu'un id, `insp`, pour toute
     card ; une card rafraîchie garde le sien) rejouait l'audio de l'ANCIEN — le registre
     gardait l'état du premier, canvas sorti du DOM compris ;
  2. `setPeaks` juste après `create` ne faisait rien : l'init est paresseuse (1er clic), donc
     les pics que le serveur envoie à l'inspecteur et aux cards n'étaient jamais dessinés.

Le fichier est exécuté dans V8 (`py_mini_racer`, venv_win seulement — SKIP ailleurs) avec un
faux DOM minimal : il n'a besoin que de conteneurs, de canvas et d'`Audio`.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

FAKE_DOM = r"""
var window = this;
var fetched = [];
function fetch(url) { fetched.push(url); return new Promise(function () {}); }
function Audio() {
  this.src = ''; this.paused = true; this.preload = ''; this.readyState = 4;
  var on = [];
  this.addEventListener = function (k, fn, o) { on.push([k, fn, !!(o && o.once)]); };
  this.fire = function (k) {
    var due = on.filter(function (l) { return l[0] === k; });
    on = on.filter(function (l) { return !(l[0] === k && l[2]); });
    due.forEach(function (l) { l[1](); });
  };
  this.pause = function () { this.paused = true; };
  this.play = function () { this.paused = false; return { catch: function () {} }; };
}
function el() {
  return { style: {}, dataset: {}, width: 0, height: 0, offsetWidth: 300, className: '',
           textContent: '', appendChild: function () {},
           addEventListener: function () {},
           getContext: function () { return { clearRect: function () {}, fillRect: function () {} }; } };
}
var containers = {}, announced = [];
function CustomEvent(type, o) { this.type = type; this.detail = o.detail; this.bubbles = o.bubbles; }
var document = {
  addEventListener: function () {},
  createElement: function () { return el(); },
  getElementById: function (id) { return containers[id] || null; },
};
function container(id, url) {
  var parts = {};
  var c = { id: 'audioPlayer_' + id, dataset: { audioUrl: url, waveformHeight: '48' },
            dispatchEvent: function (e) { announced.push([e.type, e.detail.id, e.bubbles]); },
            querySelector: function (sel) { return parts[sel] || (parts[sel] = el()); } };
  containers[c.id] = c;
  return c;
}
"""


class CommonAudioPlayerTest(SimpleTestCase):

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-audio-player.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(FAKE_DOM + source)
        return ctx

    def test_a_rebuilt_container_plays_its_own_audio(self):
        ctx = self._ctx()
        ctx.eval("WamaAudioPlayer.init(container('insp', '/first.wav'), false);")
        ctx.eval("WamaAudioPlayer.init(container('insp', '/second.wav'), false);")
        self.assertEqual('/second.wav', ctx.eval("WamaAudioPlayer.getAudio('insp').src"),
                         "le conteneur reconstruit rejoue l'audio du précédent")

    def test_the_same_container_keeps_its_player(self):
        """Contre-épreuve : un 2ᵉ init du MÊME conteneur ne recrée rien (play/pause direct)."""
        ctx = self._ctx()
        ctx.eval("var c = container('card7', '/a.wav'); WamaAudioPlayer.init(c, false);"
                 "var first = WamaAudioPlayer.getAudio('card7'); WamaAudioPlayer.init(c, false);")
        self.assertTrue(ctx.eval("WamaAudioPlayer.getAudio('card7') === first"))

    def test_server_peaks_are_drawn_without_downloading_the_file(self):
        ctx = self._ctx()
        ctx.eval("container('insp', '/long.wav'); WamaAudioPlayer.setPeaks('insp', [0, 128, 255]);")
        self.assertTrue(ctx.eval("!!WamaAudioPlayer.getAudio('insp')"),
                        'setPeaks sur un lecteur pas encore initialisé est resté sans effet')
        self.assertEqual(0, ctx.eval('fetched.length'),
                         'les pics sont fournis : retélécharger le fichier pour les recalculer est inutile')
        self.assertEqual('none', ctx.eval("WamaAudioPlayer.getAudio('insp').preload"))

    def test_a_player_follows_an_axis_through_its_own_rules(self):
        """2026-11-16 : ONE attach of a player's sound to a time axis (`follow`) — the surface
        transport and the preview both take it. The axis plays and places the sound THROUGH the
        player (exclusive playback, a position set again once seekable)."""
        ctx = self._ctx()
        out = list(ctx.eval("""(function () {
            container('s1', '/b.wav');
            var got = [], axis = {attach: function (el, o) { got.push(el, o); return function () { got.push('dropped'); }; }};
            var drop = WamaAudioPlayer.follow('s1', axis, 2), a = WamaAudioPlayer.getAudio('s1');
            var r = [got[0] === a, got[1].offset, got[1].play() === a, a.paused];
            got[1].seek(5); r.push(a.currentTime);
            drop(); r.push(got[2]);
            r.push(WamaAudioPlayer.follow('absent', axis), WamaAudioPlayer.follow('s1', null));
            return r;
        })()"""))
        self.assertEqual([True, 2, True, False, 5, 'dropped', None, None], out)

    def test_the_first_start_of_a_sound_on_no_axis_is_announced_once(self):
        """A card or the panel : the page learns the first start, and may put the sound on an axis
        (`media-preview.js`). Not at mount, not twice, and never for a sound already on an axis."""
        ctx = self._ctx()
        out = ctx.eval("""(function () {
            WamaAudioPlayer.init(container('card7', '/a.wav'), false);
            var mounted = announced.length, a = WamaAudioPlayer.getAudio('card7');
            a.fire('play'); a.fire('play');
            container('s1', '/b.wav');
            WamaAudioPlayer.follow('s1', {attach: function () { return function () {}; }});
            WamaAudioPlayer.getAudio('s1').fire('play');
            return JSON.stringify([mounted, announced]);
        })()""")
        self.assertEqual('[0,[["wama:audio-started","card7",true]]]', out)
