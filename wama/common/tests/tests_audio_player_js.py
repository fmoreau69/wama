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
  this.src = ''; this.paused = true; this.preload = '';
  this.addEventListener = function () {};
  this.pause = function () { this.paused = true; };
  this.play = function () { this.paused = false; return { catch: function () {} }; };
}
function el() {
  return { style: {}, dataset: {}, width: 0, height: 0, offsetWidth: 300, className: '',
           textContent: '', appendChild: function () {},
           addEventListener: function () {},
           getContext: function () { return { clearRect: function () {}, fillRect: function () {} }; } };
}
var containers = {};
var document = {
  addEventListener: function () {},
  createElement: function () { return el(); },
  getElementById: function (id) { return containers[id] || null; },
};
function container(id, url) {
  var parts = {};
  var c = { id: 'audioPlayer_' + id, dataset: { audioUrl: url, waveformHeight: '48' },
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
