"""The sound of a notification, page side (`wama-app-base.js`, 2026-10-06).

Fabien: the main benefit he saw in a Discord notification was its SOUND — « ne pourrait-on pas
ajouter une notification sonore directement dans WAMA ? ». The server says which sound to play
(`sound` of each notification, `notifications.notification_sound`) ; the page:
  - picks ONE sound per batch, « échoué » winning over « terminé » ;
  - lets ONE tab ring when several WAMA tabs are open (last id rung, shared like the last seen) ;
  - plays two short GENERATED notes — rising for « terminé », falling for « échoué » — without
    borrowing the speech channel, which would silence the assistant's voice or a playing media.

Same pattern as `tests_toast.py`: embedded V8, each function extracted and run alone (the whole
module touches the DOM when it loads), fake `localStorage` and `AudioContext`.
⚠ `py_mini_racer` is only installed in venv_win: these tests SKIP under venv_linux.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SOURCE = Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-app-base.js'
SERVED = Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-app-base.js'

#: A fake browser : a shared localStorage, and an AudioContext that RECORDS what it is asked.
FAKE_BROWSER = """
var store = {};
var localStorage = { getItem: function (k) { return k in store ? store[k] : null; },
                     setItem: function (k, v) { store[k] = String(v); } };
var played = [];
function FakeAudioContext() { this.state = 'running'; this.currentTime = 0;
                              this.destination = {}; }
FakeAudioContext.prototype.createOscillator = function () {
  var osc = { frequency: { value: 0 }, connect: function () {},
              start: function () {}, stop: function () {} };
  played.push(osc); return osc; };
FakeAudioContext.prototype.createGain = function () {
  var ramp = function () {};
  return { gain: { setValueAtTime: ramp, exponentialRampToValueAtTime: ramp },
           connect: function () {} }; };
var global = { AudioContext: FakeAudioContext };
"""


def _extract(src, name):
    match = re.search(r'\n  function ' + name + r'\(.*?\n  }\n', src, re.S)
    return match.group(0) if match else None


class NotificationSoundPageTest(SimpleTestCase):

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        self.src = SOURCE.read_text(encoding='utf-8')
        self.ctx = MiniRacer()
        self.ctx.eval('(function(){' + self.src + '\n})')          # parse of the WHOLE module
        consts = [re.search(r"  const CHIME_KEY = '[^']+';", self.src),
                  re.search(r'  const CHIMES = \{[^}]*\};', self.src)]
        self.assertTrue(all(consts), 'the sound constants disappeared')
        bodies = [_extract(self.src, name)
                  for name in ('chimeFor', 'claimChime', 'chimeContext', 'playChime')]
        self.assertTrue(all(bodies), 'a sound function disappeared or changed shape')
        self.ctx.eval(FAKE_BROWSER + '\n'.join(m.group(0) for m in consts)
                      + '\nvar chimeAudio = null;\n' + '\n'.join(bodies))

    def test_failed_wins_and_only_sounding_items_count(self):
        pick = self.ctx.eval("""JSON.stringify(chimeFor([
            {id: 3, sound: 'done'}, {id: 5, sound: 'failed'}, {id: 9, sound: ''}]))""")
        self.assertEqual('{"sound":"failed","lastId":5}', pick)
        self.assertEqual('{"sound":"done","lastId":4}', self.ctx.eval(
            "JSON.stringify(chimeFor([{id: 4, sound: 'done'}, {id: 2, sound: 'mystery'}]))"))

    def test_nothing_to_play_without_a_sounding_item(self):
        self.assertEqual('', self.ctx.eval("chimeFor([{id: 1, sound: ''}]).sound"))
        self.assertEqual('', self.ctx.eval('chimeFor(undefined).sound'))

    def test_one_tab_only_rings_for_a_notification(self):
        self.assertTrue(self.ctx.eval('claimChime(7)'), 'the first tab rings')
        self.assertFalse(self.ctx.eval('claimChime(7)'), 'another tab, same notification')
        self.assertTrue(self.ctx.eval('claimChime(8)'), 'a newer notification rings again')

    def test_done_rises_and_failed_falls(self):
        self.assertTrue(self.ctx.eval("playChime('done')"))
        rising = self.ctx.eval('played.map(function (o) { return o.frequency.value; })')
        self.ctx.eval('played = [];')
        self.ctx.eval("playChime('failed')")
        falling = self.ctx.eval('played.map(function (o) { return o.frequency.value; })')
        self.assertEqual(2, len(rising))
        self.assertLess(rising[0], rising[1])
        self.assertGreater(falling[0], falling[1])

    def test_no_audio_context_means_silence_not_an_error(self):
        self.ctx.eval('global = {}; chimeAudio = null;')
        self.assertFalse(self.ctx.eval("playChime('done')"))

    def test_the_sound_does_not_take_the_speech_channel(self):
        body = _extract(self.src, 'playChime')
        for forbidden in ('claimAudioChannel', 'Speech', 'pauseDomMedia'):
            self.assertNotIn(forbidden, body, 'a notification must not silence the voice or a media')

    def test_the_poll_plays_what_the_server_says(self):
        """Wiring: the live notifications play the chosen sound, once per notification — through
        the silence rule (`ringUnlessPlaying`, 2026-10-06), never straight to the speaker."""
        self.assertIn('if (chime.sound && claimChime(chime.lastId)) ringUnlessPlaying(chime.sound);',
                      self.src)
        self.assertIn("document.addEventListener('pointerdown', unlockChime, { once: true });",
                      self.src)

    def test_the_served_copy_matches_its_source(self):
        if SERVED.exists():
            self.assertEqual(SOURCE.read_bytes(), SERVED.read_bytes())


#: Un faux navigateur pour la question « un son joue-t-il ? » : médias du DOM, players hors DOM,
#: voix de l'assistant, canal inter-onglets et minuteurs — tous OBSERVABLES.
FAKE_PLAYING = """
var media = [];
var document = { querySelectorAll: function () { return media; } };
var speechAudio = null;
var global = {};
var sent = [];
var mediaChannel = { postMessage: function (m) { sent.push(m); } };
var timers = [];
function setTimeout(fn, ms) { timers.push(fn); }
var TAB_ID = 'here';
var rung = [];
function playChime(sound) { rung.push(sound); return true; }
"""


class NotificationSoundStaysSilentWhilePlayingTest(SimpleTestCase):
    """Le son des notifications SE TAIT pendant une lecture (décision de Fabien, 2026-10-06 :
    l'option 3 — ne rien couper, ne rien superposer ; la pop-up s'affiche quand même). Il pose la
    question INVERSE du mécanisme de lecture exclusive (« faire taire ») aux MÊMES sources :
    médias du DOM, players hors DOM, voix de synthèse, voix de l'assistant (avatar compris) —
    ici et, par le même canal `wama-media`, dans les autres onglets."""

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        self.src = SOURCE.read_text(encoding='utf-8')
        self.ctx = MiniRacer()
        consts = [re.search(r'  const ASK_WAIT_MS = \d+;', self.src),
                  re.search(r'  const pendingAsks = \{\};', self.src)]
        self.assertTrue(all(consts), 'the cross-tab constants disappeared')
        bodies = [_extract(self.src, name) for name in
                  ('isAudioPlaying', 'askOthersPlaying', 'onMediaMessage', 'ringUnlessPlaying')]
        self.assertTrue(all(bodies), 'a function of the silence rule disappeared or changed shape')
        self.ctx.eval(FAKE_PLAYING + '\n'.join(m.group(0) for m in consts)
                      + '\nfunction silenceLocal() {}\n' + '\n'.join(bodies))

    def _media(self, **state):
        props = {'paused': False, 'ended': False, 'muted': False, 'volume': 1}
        props.update(state)
        js = ', '.join(f"{k}: {str(v).lower() if isinstance(v, bool) else v}" for k, v in props.items())
        self.ctx.eval(f'media.push({{{js}}});')

    def test_nothing_playing_is_silence_of_the_page(self):
        self.assertFalse(self.ctx.eval('isAudioPlaying()'))

    def test_a_playing_media_counts_a_paused_or_muted_one_does_not(self):
        self._media(paused=True)
        self._media(muted=True)
        self._media(volume=0)
        self.assertFalse(self.ctx.eval('isAudioPlaying()'))
        self._media()
        self.assertTrue(self.ctx.eval('isAudioPlaying()'))

    def test_players_out_of_the_dom_and_both_voices_count(self):
        self.ctx.eval('global.WamaAudioPlayer = {isPlaying: function () { return true; }};')
        self.assertTrue(self.ctx.eval('isAudioPlaying()'))
        self.ctx.eval('global = {}; speechAudio = {paused: false};')
        self.assertTrue(self.ctx.eval('isAudioPlaying()'), 'synthesized speech')
        self.ctx.eval('speechAudio = null; global.WamaAssistantVoice = '
                      '{isSpeaking: function () { return true; }};')
        self.assertTrue(self.ctx.eval('isAudioPlaying()'), 'the assistant voice, avatar included')

    def test_a_playing_page_rings_nothing_and_asks_nobody(self):
        self._media()
        self.assertFalse(self.ctx.eval("ringUnlessPlaying('done')"))
        self.assertEqual(0, self.ctx.eval('sent.length + rung.length'))

    def test_a_silent_page_asks_the_other_tabs_and_rings_without_an_answer(self):
        self.assertTrue(self.ctx.eval("ringUnlessPlaying('done')"))
        self.assertEqual('ask', self.ctx.eval('sent[0].t'))
        self.ctx.eval('timers.forEach(function (fn) { fn(); });')
        self.assertEqual('["done"]', self.ctx.eval('JSON.stringify(rung)'))

    def test_a_busy_tab_keeps_the_sound_quiet(self):
        self.ctx.eval("ringUnlessPlaying('failed');")
        self.ctx.eval("onMediaMessage({t: 'busy', tab: 'other', id: sent[0].id});")
        self.ctx.eval('timers.forEach(function (fn) { fn(); });')
        self.assertEqual('[]', self.ctx.eval('JSON.stringify(rung)'))

    def test_a_tab_answers_busy_only_while_it_plays(self):
        self.ctx.eval("onMediaMessage({t: 'ask', tab: 'other', id: 'q1'});")
        self.assertEqual(0, self.ctx.eval('sent.length'), 'silent here : no answer')
        self._media()
        self.ctx.eval("onMediaMessage({t: 'ask', tab: 'other', id: 'q2'});")
        self.assertEqual('busy', self.ctx.eval('sent[0].t'))
        self.assertEqual('q2', self.ctx.eval('sent[0].id'))

    def test_the_poll_goes_through_the_silence_rule(self):
        self.assertIn('if (chime.sound && claimChime(chime.lastId)) ringUnlessPlaying(chime.sound);',
                      self.src)

    def test_the_player_answers_the_question_and_its_served_copy_matches(self):
        player = Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-audio-player.js'
        served = Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-audio-player.js'
        src = player.read_text(encoding='utf-8')
        # IIFE `(function (global) {…})(window)` ; au chargement elle écoute `document` (clic).
        self.ctx.eval('var window = {}; document.addEventListener = function () {};')
        self.ctx.eval(src)
        self.assertFalse(self.ctx.eval('window.WamaAudioPlayer.isPlaying()'), 'no player : silence')
        if served.exists():
            self.assertEqual(player.read_bytes(), served.read_bytes())
