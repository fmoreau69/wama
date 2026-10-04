"""La voix de l'assistant (`wama-assistant-voice.js`) demande la phrase suivante PENDANT la
lecture de la précédente — levier 4 de `WAMA_LLM §1bis`, 2026-10-04.

Défaut mesuré en lisant le code : une seule chaîne faisait « demander puis lire », donc hors
avatar la phrase suivante n'était demandée au service de voix qu'une fois la précédente
entièrement lue — un silence égal au temps de calcul entre deux phrases. Aucun test Python ne
peut le voir : le fichier est exécuté dans V8 (`py_mini_racer`), avec un faux navigateur
minimal dont la lecture ne se termine que lorsque le test le décide.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

FAKE_BROWSER = r"""
var window = this;
window.addEventListener = function () {};
var document = { cookie: '' };
var console = { error: function () {} };
var asked = [];        // les textes demandés au service, dans l'ordre
var playing = [];      // les lectures en cours : fin déclenchée par le test
function fetch(url, options) {
  asked.push(JSON.parse(options.body).text);
  return Promise.resolve({ json: function () { return Promise.resolve({ audio_b64: 'AA==' }); } });
}
function atob() { return 'x'; }
function Blob() {}
var WamaApp = { Speech: { stop: function () {}, claim: function () {
  return { signal: null, valid: function () { return true; },
           play: function () {
             var audio = { handlers: {}, addEventListener: function (name, fn) { this.handlers[name] = fn; } };
             playing.push(audio);
             return audio;
           } };
} } };
function finishPlayback(index) { playing[index].handlers.ended(); }
"""

FIRST = "Voici une première phrase assez longue pour partir seule au service de voix. "
SECOND = "Et voici la deuxième phrase, elle aussi assez longue pour partir à son tour. "


class NextSentenceIsRequestedDuringPlaybackTest(SimpleTestCase):

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-assistant-voice.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(FAKE_BROWSER + source)
        ctx.eval("var turn = WamaAssistantVoice.speakStream();")
        return ctx

    def test_the_second_sentence_is_requested_while_the_first_is_still_playing(self):
        ctx = self._ctx()
        ctx.eval("turn.push(%r); turn.push(%r);" % (FIRST, SECOND))
        self.assertEqual(1, ctx.eval("playing.length"), "la première phrase devrait être en lecture")
        self.assertEqual(2, ctx.eval("asked.length"),
                         "la deuxième phrase attend la fin de la lecture pour être demandée")

    def test_sentences_are_still_played_one_after_the_other_and_in_order(self):
        """Contre-épreuve : demander en avance ne doit pas faire lire en même temps."""
        ctx = self._ctx()
        ctx.eval("turn.push(%r); turn.push(%r);" % (FIRST, SECOND))
        self.assertEqual(1, ctx.eval("playing.length"))
        ctx.eval("finishPlayback(0);")
        self.assertEqual(2, ctx.eval("playing.length"))
        self.assertEqual([FIRST.strip(), SECOND.strip()], list(ctx.eval("asked")))

    def test_streamed_fragments_keep_their_words_apart(self):
        """Un flux arrive par jetons, espace EN TÊTE (« Bonjour », « je », « suis »). Nettoyer
        chaque fragment séparément les collait — la voix lisait « Bonjourjesuis »."""
        ctx = self._ctx()
        ctx.eval("""
            ['Bonjour', ' je', ' suis', ' votre', ' assistant', ' et', ' je', ' réponds',
             ' à', ' vos', ' questions', ' **en', ' gras**', ' aussi', '.', ' Suite']
              .forEach(function (piece) { turn.push(piece); });
        """)
        self.assertEqual(
            ['Bonjour je suis votre assistant et je réponds à vos questions en gras aussi.'],
            list(ctx.eval("asked")))

    def test_the_service_is_asked_one_request_at_a_time(self):
        """Une réponse de dix phrases ne doit pas ouvrir dix requêtes d'un coup."""
        ctx = self._ctx()
        ctx.eval("""
            var pending = [];
            fetch = function (url, options) {
              asked.push(JSON.parse(options.body).text);
              return new Promise(function (resolve) { pending.push(resolve); });
            };
            turn.push(%r); turn.push(%r);
        """ % (FIRST, SECOND))
        self.assertEqual(1, ctx.eval("asked.length"))
        ctx.eval("pending[0]({ json: function () { return Promise.resolve({ audio_b64: 'AA==' }); } });")
        self.assertEqual(2, ctx.eval("asked.length"))
