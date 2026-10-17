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
        # Le Markdown part TEL QUEL depuis le 2026-10-18 : sa préparation est au serveur
        # (`tts_text`). Ce que garde ce test : les mots restent séparés.
        self.assertEqual(
            ['Bonjour je suis votre assistant et je réponds à vos questions **en gras** aussi.'],
            list(ctx.eval("asked")))

    def test_inline_code_reaches_the_server_instead_of_being_erased(self):
        """Le navigateur EFFAÇAIT le code en ligne : « (`instant_preview`) » partait en « () » —
        les mots entre parenthèses « n'étaient pas lus » (Fabien, 2026-10-18)."""
        ctx = self._ctx()
        ctx.eval("turn.push(%r); turn.end();" % "Le réglage (`instant_preview`) suit la frappe.")
        self.assertEqual(['Le réglage (`instant_preview`) suit la frappe.'], list(ctx.eval("asked")))

    def test_a_code_block_is_never_cut_in_two(self):
        """Une fin de phrase DANS un bloc de code ne découpe pas : le serveur recevrait un bloc
        sans sa clôture, et le lirait au lieu de l'annoncer."""
        ctx = self._ctx()
        reply = ("Voici un exemple de code que vous pouvez utiliser tel quel dans votre script :\n"
                 "```python\nprint('Bonjour. Ceci est une phrase entière du code.')\n```\n"
                 "Ensuite, relancez simplement le traitement depuis la file d'attente.")
        ctx.eval("turn.push(%r); turn.end();" % reply)
        for piece in ctx.eval("asked"):
            self.assertEqual(0, piece.count('```') % 2, piece)

    def test_the_lips_follow_what_the_server_said(self):
        """L'avatar cale ses lèvres sur le texte EFFECTIVEMENT dit (`spoken`), pas sur le texte
        envoyé — ils diffèrent dès que la préparation réécrit (incises, lexique, code)."""
        ctx = self._ctx()
        ctx.eval("""
            var lips = [];
            window.WamaAvatar = { isReady: function () { return true; }, stop: function () {},
                                  instance: function () { return null; },
                                  speak: function (blob, text) { lips.push(text); return Promise.resolve(true); } };
            fetch = function (url, options) {
              asked.push(JSON.parse(options.body).text);
              return Promise.resolve({ json: function () {
                return Promise.resolve({ audio_b64: 'AA==', spoken: 'Bienvenue dans Ouama.' }); } });
            };
            turn.push('Bienvenue dans WAMA.'); turn.end();
        """)
        self.assertEqual(['Bienvenue dans Ouama.'], list(ctx.eval("lips")))

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


REPLY = ("Bonjour, je suis l'assistant de WAMA et je peux vous aider dans vos traitements. "
         "Vous avez trois transcriptions terminées et une en cours dans le Transcriber. "
         "La dernière a duré quatre minutes, et sa correction assistée vous attend. "
         "Voulez-vous que je lance la synthèse vocale du résumé maintenant ?")


class ReplyReceivedAtOnceIsSplitTest(SimpleTestCase):
    """Une réponse reçue D'UN BLOC (bouton « Écouter », tour synchrone, fournisseur sans flux) se
    découpe comme la même réponse reçue en flux (2026-10-13). Le découpage était gourmand : le
    bloc partait en UN audio, et l'avatar, qui répartit les mots sur la durée de chaque audio,
    décrochait de la voix sur toute sa longueur."""

    _ctx = NextSentenceIsRequestedDuringPlaybackTest._ctx

    def _asked(self, pieces):
        ctx = self._ctx()
        ctx.eval("%r.forEach(function (p) { turn.push(p); }); turn.end();" % pieces)
        for i in range(10):
            if i < ctx.eval("playing.length"):
                ctx.eval("finishPlayback(%d);" % i)
        return list(ctx.eval("asked"))

    def test_a_reply_received_at_once_is_split_like_a_streamed_one(self):
        words = REPLY.split(' ')
        streamed = self._asked([words[0]] + [' ' + w for w in words[1:]])
        at_once = self._asked([REPLY])
        self.assertEqual(4, len(streamed))
        self.assertEqual(streamed, at_once)

    def test_a_short_reply_stays_one_piece(self):
        """Contre-épreuve : sous le seuil, rien à découper."""
        self.assertEqual(['Avec plaisir ! Autre chose ?'], self._asked(['Avec plaisir ! Autre chose ?']))


#: Réponse réelle de l'assistant (13/10) dont la fin, encore jouée par le haut-parleur, est
#: repartie au micro comme réplique de l'utilisateur.
ECHOED_REPLY = "Avec plaisir ! N'hésitez pas si vous avez besoin d'autre chose. "
ECHO_HEARD = "vous avez besoin d'autre chose."


class VoiceKnowsItsOwnWordsTest(SimpleTestCase):
    """La voix sait ce qu'elle vient de dire, et jusqu'à quand on l'entend : c'est ce que lit
    l'écoute de la conversation pour ne jamais renvoyer l'assistant à lui-même (2026-10-13)."""

    _ctx = NextSentenceIsRequestedDuringPlaybackTest._ctx

    def _speaking(self):
        ctx = self._ctx()
        ctx.eval("turn.push(%r);" % ECHOED_REPLY)
        return ctx

    def _own(self, ctx, text, heard_at='Date.now()'):
        return ctx.eval("WamaAssistantVoice.isOwnSpeech(%r, %s)" % (text, heard_at))

    def test_its_own_words_heard_while_it_speaks_are_its_echo(self):
        self.assertTrue(self._own(self._speaking(), ECHO_HEARD))

    def test_another_sentence_heard_while_it_speaks_is_not_an_echo(self):
        """Contre-épreuve : on peut lui couper la parole — même en reprenant quelques-uns de ses
        mots (« besoin », « d'autre » : 4 mots sur 10, dans l'ordre)."""
        self.assertFalse(self._own(self._speaking(), "Non, je n'ai besoin de rien d'autre, merci."))

    def test_words_heard_after_it_went_silent_belong_to_the_user(self):
        """Une réponse qui REPREND ses mots, dite une fois qu'il s'est tu, n'est pas un écho."""
        ctx = self._speaking()
        ctx.eval("turn.end(); finishPlayback(0);")
        self.assertFalse(ctx.eval("WamaAssistantVoice.isSpeaking()"))
        self.assertFalse(self._own(ctx, ECHO_HEARD, 'Date.now() + 1000'))
        self.assertTrue(self._own(ctx, ECHO_HEARD, 'Date.now() - 1000'),
                        "commencée pendant qu'il parlait, elle reste son écho")

    def test_it_stays_audible_for_the_output_latency(self):
        ctx = self._speaking()
        ctx.eval("""
            var fakeNow = 1000000;
            Date.now = function () { return fakeNow; };
            var clearInterval = function () {};
            window.WamaAvatar = { isReady: function () { return true; }, stop: function () {},
                                  outputLatencyMs: function () { return 300; } };
            WamaAssistantVoice.stop();
        """)
        self.assertFalse(ctx.eval("WamaAssistantVoice.isSpeaking()"))
        self.assertTrue(ctx.eval("WamaAssistantVoice.isAudible()"), 'le haut-parleur joue encore')
        ctx.eval("fakeNow += 301;")
        self.assertFalse(ctx.eval("WamaAssistantVoice.isAudible()"))


FAKE_HEAD = r"""
var window = this;
var spoken = null;
var audioSeconds = 12.18;
var fakeAudioCtx = { outputLatency: 0.2, baseLatency: 0.01 };
class TalkingHead {
  constructor() { this.audioCtx = fakeAudioCtx; }
  showAvatar() { return Promise.resolve(); }
  speakAudio(r) { spoken = r; }
  stopSpeaking() {}
}
window.AudioContext = function () {
  return { decodeAudioData: function () { return Promise.resolve({ duration: audioSeconds }); } };
};
var fakeBlob = { arrayBuffer: function () { return Promise.resolve(new ArrayBuffer(4)); } };
"""

#: Réponse réelle de l'assistant (13/10) et ce que la voix française de Kokoro en fait : 12,18 s,
#: la phrase qui suit le nom de fichier reprend à 8,16 s (fin du silence, mesurée sur le WAV).
MEASURED_TEXT = ("Oui, je vous entends ! Je suis là et prêt.\n\nReprenons : vous vouliez flouter la "
                 "plaque sur le fichier DSC05016.jpg. Je vais le chercher dans votre dossier "
                 "temporaire et le lancer dans l'Anonymizer.")
MEASURED_RESTART_S = 8.16


class AvatarLipTimingTest(SimpleTestCase):
    """Les horaires de mots que `wama-avatar.js` donne aux lèvres (2026-10-13). Le module importe
    TalkingHead : on retire l'import et on lui substitue un faux qui retient ce qu'on lui dit."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        import re
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-avatar.js').read_text(encoding='utf-8')
        source = re.sub(r'^import .*$', '', source, flags=re.M).replace('export ', '')
        ctx = MiniRacer()
        ctx.eval(FAKE_HEAD + source)
        ctx.eval("WamaAvatar.init({}, { glbUrl: 'x' });")
        return ctx

    def _words(self, ctx, args):
        import json
        ctx.eval("WamaAvatar.speak(fakeBlob, %s);" % args)
        return json.loads(ctx.eval("JSON.stringify(spoken)"))

    def test_the_sentence_after_a_file_name_starts_near_the_measured_voice(self):
        """Au prorata des lettres, elle partait 1,1 s trop tôt : les chiffres se disent en mots,
        et les pauses des ponctuations n'étaient pas comptées."""
        ctx = self._ctx()
        ctx.eval("fakeAudioCtx.outputLatency = 0; fakeAudioCtx.baseLatency = 0;")
        spoken = self._words(ctx, "%r, 'fr'" % MEASURED_TEXT)
        words = MEASURED_TEXT.split()
        index = words.index('DSC05016.jpg.') + 1
        self.assertAlmostEqual(MEASURED_RESTART_S, spoken['wtimes'][index] / 1000, delta=0.4)

    def test_live_lips_wait_for_the_output_latency(self):
        spoken = self._words(self._ctx(), "'Bonjour à vous.', 'fr'")
        self.assertEqual(210, spoken['wtimes'][0])

    def test_a_video_render_has_no_speaker_latency(self):
        """Contre-épreuve : le rendu vidéo assemble image et son hors navigateur."""
        spoken = self._words(self._ctx(), "'Bonjour à vous.', 'fr', null, { live: false }")
        self.assertEqual(0, spoken['wtimes'][0])

    def test_measured_timings_are_passed_unchanged(self):
        """Contre-épreuve : des mots MESURÉS (transcription) ne s'estiment ni ne se décalent."""
        measured = "{ words: ['Bonjour'], wtimes: [40], wdurations: [300] }"
        spoken = self._words(self._ctx(), "'Bonjour', 'fr', %s" % measured)
        self.assertEqual([40], spoken['wtimes'])
        self.assertEqual([300], spoken['wdurations'])


class ChatScriptParsesTest(SimpleTestCase):
    """Le script du chat (décompte d'attente, 2026-10-04) touche au DOM : on ne l'exécute pas,
    on vérifie que V8 l'ANALYSE — un script qui ne s'analyse plus casse le chat de toutes les
    pages sans qu'aucun test Python ne le voie."""

    def test_the_served_chat_script_is_valid_javascript(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        MiniRacer().eval('(function(){' + source + '\n})')
        self.assertIn("evt.type === 'eta'", source)
        self.assertIn('showCountdown', source)
