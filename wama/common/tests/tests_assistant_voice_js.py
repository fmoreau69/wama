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
var clearInterval = function () {};
var asked = [];        // les textes demandés au service, dans l'ordre
var playing = [];      // les lectures en cours : fin déclenchée par le test
function fetch(url, options) {
  asked.push(JSON.parse(options.body).text);
  return Promise.resolve({ json: function () { return Promise.resolve({ audio_b64: 'AA==' }); } });
}
function atob() { return 'x'; }
function Blob() {}
var channelOwned = true;   // faux quand un AUTRE lecteur a pris le canal commun
var WamaApp = { Speech: { stop: function () {}, claim: function () {
  return { signal: null, valid: function () { return channelOwned; },
           play: function () {
             var audio = { handlers: {}, addEventListener: function (name, fn) { this.handlers[name] = fn; } };
             playing.push(audio);
             return audio;
           } };
} } };
function finishPlayback(index) { playing[index].handlers.ended(); }
// Un autre son met la lecture en PAUSE (sans effet sur une brique qui ne l'écoute pas).
function pauseFrom(index) { var h = playing[index].handlers.pause; if (h) h(); }
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


class VoiceNeverStaysAudibleForeverTest(SimpleTestCase):
    """L'écoute de la conversation est sourde tant que la voix est audible (sans annulation d'écho
    confirmée). Le 2026-10-27, trois chemins laissaient la voix audible POUR TOUJOURS — « je vois
    le micro qui module, mais aucun texte n'apparaît » : un tour ouvert l'était dès la question,
    réflexion comprise ; une lecture coupée par un autre son ne finissait jamais ; un tour dont
    un autre lecteur avait pris le canal finissait sans se déclarer muet."""

    _ctx = NextSentenceIsRequestedDuringPlaybackTest._ctx

    def _audible(self, ctx):
        return ctx.eval("WamaAssistantVoice.isAudible()")

    def test_a_turn_that_has_played_nothing_yet_is_not_audible(self):
        ctx = self._ctx()
        self.assertTrue(ctx.eval("WamaAssistantVoice.isSpeaking()"), 'le tour est ouvert')
        self.assertFalse(self._audible(ctx), "il réfléchit : rien ne sort du haut-parleur")
        ctx.eval("turn.push(%r);" % FIRST)
        self.assertTrue(self._audible(ctx), 'audible dès le premier son')

    def test_a_voice_cut_by_another_sound_falls_silent(self):
        ctx = self._ctx()
        ctx.eval("turn.push(%r); turn.push(%r);" % (FIRST, SECOND))
        ctx.eval("pauseFrom(0);")       # un média de la page l'a mise en pause
        self.assertFalse(self._audible(ctx))
        self.assertFalse(ctx.eval("WamaAssistantVoice.isSpeaking()"))
        self.assertEqual(1, ctx.eval("playing.length"), 'coupée, la voix ne reprend pas la suite')

    def test_a_turn_whose_channel_another_player_took_ends_silent(self):
        ctx = self._ctx()
        ctx.eval("turn.push(%r);" % FIRST)
        ctx.eval("channelOwned = false; pauseFrom(0); turn.end();")
        self.assertFalse(self._audible(ctx))

    def test_a_late_pause_does_not_cut_the_next_turn(self):
        """Contre-épreuve : la pause de l'ancienne lecture arrive APRÈS coup, quand la voix a
        déjà ouvert le tour suivant — elle ne le coupe pas."""
        ctx = self._ctx()
        ctx.eval("turn.push(%r);" % FIRST)
        ctx.eval("var next = WamaAssistantVoice.speakStream(); next.push(%r);" % SECOND)
        ctx.eval("pauseFrom(0);")
        self.assertTrue(self._audible(ctx))
        self.assertEqual(2, ctx.eval("playing.length"))


CHAT_BROWSER = r"""
var window = this;
var document = { readyState: 'complete', querySelectorAll: function () { return []; }, cookie: '' };
window.ReadableStream = function () {};
window.TextDecoder = function () {};
window.fetch = function () { return Promise.reject(new TypeError('Failed to fetch')); };
var fetch = window.fetch;
var ended = 0;
window.WamaAssistantVoice = { speakStream: function () {
  return { push: function () {}, end: function () { ended++; return Promise.resolve(true); } };
} };
"""


class FailedTurnClosesItsVoiceTest(SimpleTestCase):
    """Un tour en flux qui ÉCHOUE ferme son tour de parole : resté ouvert, la voix se croyait
    audible et l'écoute de la conversation restait sourde (2026-10-27)."""

    def test_a_turn_lost_on_the_network_ends_its_voice(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(CHAT_BROWSER + source)
        ctx.eval("""
            var failed = null;
            var chat = Object.create(WamaAssistantChat._Chat.prototype);
            chat.cfg = { streamUrl: '/api/ai-chat/stream/' };
            chat.controller = null;
            chat.sendStreaming('Bonjour').catch(function (e) { failed = e.message; });
        """)
        self.assertEqual('Failed to fetch', ctx.eval("failed"), "l'échec remonte au tour")
        self.assertEqual(1, ctx.eval("ended"))


#: Un tour qui ne se dénoue que quand le test le décide (`answer(i)`) ou quand on l'interrompt.
CHAT_TURNS = r"""
var aborts = 0, asked = [], answers = [];
window.WamaAssistantVoice.stop = function () {};
window.AbortController = function () {
  var self = this;
  this.signal = {};
  this.abort = function () { aborts++; if (self.onabort) self.onabort(); };
};
var chat = Object.create(WamaAssistantChat._Chat.prototype);
var noop = function () {};
chat.cfg = { streamUrl: '/api/ai-chat/stream/' };
chat.root = { setAttribute: noop };
chat.input = { value: '', disabled: false, focus: noop };
chat.sendBtn = { disabled: false };
chat.feed = { appendChild: noop };
chat.deposits = [];
chat.controller = null;
['dropGreeting', 'startWaiting', 'stopWaiting', 'renderDeposits', 'autoGrow', 'scrollToEnd']
  .forEach(function (name) { chat[name] = noop; });
chat.bubble = function () { return {}; };
chat.sendStreaming = function (message) {
  var ctl = chat.controller;
  asked.push(message);
  return new Promise(function (resolve, reject) {
    answers.push(resolve);
    ctl.onabort = function () { var e = new Error('aborted'); e.name = 'AbortError'; reject(e); };
  });
};
function type(text) { chat.input.value = text; chat.send(); }
function answer(i) { answers[i](); }
"""


class TypingWhileItThinksTest(SimpleTestCase):
    """La saisie reste ouverte pendant un tour (2026-10-27, Fabien : « quand l'assistant
    réfléchit, je ne peux plus lui écrire ») : la zone et le bouton étaient désactivés jusqu'à la
    fin de la réponse, et un message envoyé pendant la réflexion était ignoré."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(CHAT_BROWSER + source)
        ctx.eval(CHAT_TURNS)
        return ctx

    def test_the_input_stays_open_while_it_thinks(self):
        ctx = self._ctx()
        ctx.eval("type('Première question');")
        self.assertTrue(ctx.eval("chat.isBusy()"))
        self.assertFalse(ctx.eval("chat.input.disabled || chat.sendBtn.disabled"))

    def test_a_message_sent_while_it_thinks_replaces_the_question(self):
        """La règle de la conversation vocale : le tour en cours s'interrompt, le nouveau part
        une fois l'ancien dénoué."""
        ctx = self._ctx()
        ctx.eval("type('Première question');")
        ctx.eval("type('En fait, autre chose');")
        ctx.eval("0")                                  # le tour interrompu se dénoue
        self.assertEqual(1, ctx.eval("aborts"))
        self.assertEqual('["Première question","En fait, autre chose"]',
                         ctx.eval("JSON.stringify(asked)"))
        self.assertTrue(ctx.eval("chat.isBusy()"), 'le nouveau tour est en cours')

    def test_a_message_sent_after_the_answer_interrupts_nothing(self):
        """Contre-épreuve : un tour fini ne s'interrompt pas."""
        ctx = self._ctx()
        ctx.eval("type('Première question');")
        ctx.eval("answer(0);")
        ctx.eval("type('Deuxième question');")
        ctx.eval("0")
        self.assertEqual(0, ctx.eval("aborts"))
        self.assertEqual(2, ctx.eval("asked.length"))


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


# ── La voix AU FIL DE L'EAU (2026-10-28) ──────────────────────────────────────────────────────

def _js_function(source, name):
    """Le texte de la fonction `name` d'un fichier servi (accolades équilibrées) — pour exécuter
    dans V8 une brique d'un fichier qui touche au DOM au chargement (`wama-app-base.js`)."""
    start = source.index('function %s(' % name)
    depth, i = 0, source.index('{', start)
    while True:
        depth += {'{': 1, '}': -1}.get(source[i], 0)
        i += 1
        if depth == 0:
            return source[start:i]


class Pcm16ReadingTest(SimpleTestCase):
    """`WamaApp.Speech.readPcm16` : le réseau coupe le PCM n'importe où, un échantillon (2 octets)
    peut être à cheval sur deux blocs — l'octet impair doit passer au bloc suivant, sinon tout ce
    qui suit est décalé d'un octet (un souffle, jamais une erreur)."""

    def test_samples_cut_across_network_blocks_are_rejoined(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-app-base.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(_js_function(source, 'readPcm16') + r"""
            var blocks = [[1], [0, 2, 0], [3], [0]];       // 1, 2, 3 en int16 LE, coupés au hasard
            var got = [], finished = false;
            var response = { body: { getReader: function () { return {
              read: function () { var b = blocks.shift();
                return Promise.resolve(b ? { done: false, value: new Uint8Array(b) } : { done: true }); },
              cancel: function () {} }; } } };
            readPcm16(response, function (buffer) {
              Array.prototype.push.apply(got, Array.from(new Int16Array(buffer)));
            }).done.then(function () { finished = true; });
        """)
        self.assertTrue(ctx.eval("finished"))
        self.assertEqual([1, 2, 3], list(ctx.eval("got")))


FAKE_STREAM_HEAD = r"""
var calls = [];
TalkingHead.prototype.streamStart = function (opt, onStart, onEnd) {
  calls.push(['start', opt.sampleRate, opt.lipsyncType]); this.onEnd = onEnd; this.isStreaming = true;
  return Promise.resolve(); };
TalkingHead.prototype.streamAudio = function (r) {
  calls.push(['audio', r.audio.byteLength, r.words ? r.words.length : 0,
              r.wtimes ? r.wtimes[r.wtimes.length - 1] : null]); };
TalkingHead.prototype.streamNotifyEnd = function () { calls.push(['end']); };
TalkingHead.prototype.streamInterrupt = function () { calls.push(['interrupt']); };
var feed = null, finishReading = null;
window.WamaApp = { Speech: { readPcm16: function (response, onChunk) {
  feed = onChunk;
  return { done: new Promise(function (resolve) { finishReading = resolve; }),
           cancel: function () { calls.push(['cancel']); } };
} } };
"""


class AvatarStreamTest(SimpleTestCase):
    """`WamaAvatar.streamPlayer` : l'avatar parle EN FLUX — les mots partent avec le premier
    morceau sur une durée PRÉDITE, la fin est notifiée une fois tout reçu, le débit se RECALE sur la
    durée réellement dite, et l'arrêt interrompt le flux."""

    TEXT = 'Bonjour, je suis votre assistant.'

    def _ctx(self):
        ctx = AvatarLipTimingTest._ctx(self)
        ctx.eval(FAKE_STREAM_HEAD)
        return ctx

    def _play(self, ctx, seconds):
        import json
        ctx.eval("var p = WamaAvatar.streamPlayer({}, 24000, %r, 'fr'); var ended = 0;"
                 "p.addEventListener('ended', function () { ended++; });"
                 "feed(new ArrayBuffer(4800)); p.start();" % self.TEXT)
        ctx.eval("feed(new ArrayBuffer(%d)); finishReading();" % (int(seconds * 24000) * 2 - 4800))
        ctx.eval("WamaAvatar.instance().onEnd();")
        return json.loads(ctx.eval("JSON.stringify(calls)")), ctx.eval("ended")

    def test_words_go_with_the_first_chunk_and_the_end_follows_the_last(self):
        calls, ended = self._play(self._ctx(), 2.0)
        self.assertEqual(['start', 24000, 'words'], calls[0])
        self.assertEqual(5, calls[1][2], "les cinq mots partent avec le premier morceau")
        self.assertEqual(0, calls[2][2], "les morceaux suivants n'en portent plus")
        self.assertEqual(['end'], calls[-1])
        self.assertEqual(1, ended)

    def test_the_speaking_rate_learns_from_what_was_really_said(self):
        """Un débit faux de départ fait dériver les lèvres ; le morceau suivant se cale sur la voix."""
        ctx = self._ctx()
        first, _ = self._play(ctx, 4.0)                  # voix bien plus lente que prévu
        ctx.eval("calls = [];")
        second, _ = self._play(ctx, 4.0)
        self.assertGreater(second[1][3], first[1][3] * 1.3,
                           "le dernier mot du second morceau doit partir plus tard : débit appris")

    def test_stopping_interrupts_the_stream(self):
        import json
        ctx = self._ctx()
        ctx.eval("var p = WamaAvatar.streamPlayer({}, 24000, %r, 'fr'); var paused = 0;"
                 "p.addEventListener('pause', function () { paused++; });"
                 "feed(new ArrayBuffer(4800)); p.start();" % self.TEXT)
        ctx.eval("p.pause();")
        calls = json.loads(ctx.eval("JSON.stringify(calls)"))
        self.assertIn(['cancel'], calls)
        self.assertIn(['interrupt'], calls)
        self.assertEqual(1, ctx.eval("paused"))


class VoiceAsksForTheStreamTest(SimpleTestCase):
    """`wama-assistant-voice.js` : la voix demande le flux quand le navigateur sait le jouer, retombe
    sur la réponse entière sinon, et ne demande la phrase suivante qu'une fois la précédente REÇUE."""

    STREAMING = r"""
        var created = [];
        WamaApp.Speech.canStream = function () { return true; };
        WamaApp.Speech.stream = function (resp, rate) {
          var p = { rate: rate, addEventListener: function () {}, start: function () {} };
          p.received = new Promise(function (r) { p.done = r; });
          created.push(p); return p; };
        var bodies = [];
        fetch = function (url, options) {
          bodies.push(JSON.parse(options.body)); asked.push(JSON.parse(options.body).text);
          return Promise.resolve({ ok: true,
            headers: { get: function (h) { return { 'Content-Type': 'audio/L16', 'X-Sample-Rate': '24000',
                                                    'X-Spoken': 'Dit%20ainsi.' }[h] || null; } },
            json: function () { return Promise.resolve({ audio_b64: 'AA==' }); } });
        };
    """

    def _ctx(self):
        ctx = NextSentenceIsRequestedDuringPlaybackTest._ctx(self)
        ctx.eval(self.STREAMING)
        return ctx

    def test_the_stream_is_asked_and_played_by_the_common_channel(self):
        ctx = self._ctx()
        ctx.eval("turn.push(%r); turn.end();" % FIRST)
        self.assertTrue(ctx.eval("bodies[0].stream"))
        self.assertEqual(24000, ctx.eval("created[0].rate"))
        self.assertEqual(1, ctx.eval("playing.length"), "le lecteur en flux passe par le canal")

    def test_the_next_sentence_waits_for_the_reception_not_the_playback(self):
        ctx = self._ctx()
        ctx.eval("turn.push(%r); turn.push(%r);" % (FIRST, SECOND))
        self.assertEqual(1, ctx.eval("asked.length"), "le service dit une phrase à la fois")
        ctx.eval("created[0].done();")
        self.assertEqual(2, ctx.eval("asked.length"),
                         "la phrase suivante part dès la RÉCEPTION de la première")

    def test_a_browser_that_cannot_stream_keeps_the_whole_answer(self):
        ctx = self._ctx()
        ctx.eval("WamaApp.Speech.canStream = function () { return false; };"
                 "turn.push(%r); turn.end();" % FIRST)
        self.assertFalse(ctx.eval("!!bodies[0].stream"))
        self.assertEqual(0, ctx.eval("created.length"))
