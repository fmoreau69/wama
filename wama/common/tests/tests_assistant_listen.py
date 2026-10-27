"""L'ÉCOUTE de l'assistant — dictée et conversation vocale, transcription LOCALE (2026-10-10).

Trois étages, chacun gardé ici :
  1. la vue `/api/stt/` (droits, garde de taille, langue du profil, erreurs du service) ;
  2. le client commun du service vocal (`stt_via_service`), qui partage la traduction d'erreurs
     de la voix ;
  3. la brique `wama-assistant-listen.js`, exécutée dans V8 (`py_mini_racer`) : découpage de la
     parole, en-tête WAV, et l'enchaînement de la conversation (reprendre la parole coupe la
     voix ET interrompt le tour ; sans annulation d'écho, l'écoute est sourde pendant que
     l'assistant parle).
Aucun micro, aucun GPU, aucun service réel : tout ce qui sort de WAMA est simulé.
"""
import io
import json
import wave
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class SpeechToTextViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('listen_tester', password='x')
        self.client.force_login(self.user)
        self.url = reverse('speech_to_text')
        patcher = mock.patch('wama.common.services.resource_governor.release_in_progress',
                             return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, body=b'RIFF....WAVE', content_type='audio/wav'):
        return self.client.post(self.url, data=body, content_type=content_type)

    def test_an_anonymous_visitor_is_refused(self):
        self.client.logout()
        self.assertEqual(401, self._post().status_code)

    def test_an_empty_body_is_refused(self):
        self.assertEqual(400, self._post(b'').status_code)

    def test_a_clip_too_long_for_a_reply_is_refused_before_the_service(self):
        with mock.patch('wama.common.tts.service_client.stt_via_service') as stt:
            self.assertEqual(413, self._post(b'x' * (2 * 1024 * 1024 + 1)).status_code)
        stt.assert_not_called()

    def test_the_transcript_comes_back_with_the_profile_language_reduced_for_whisper(self):
        self.user.profile.preferred_language = 'zh-cn'
        self.user.profile.save()
        with mock.patch('wama.common.tts.service_client.stt_via_service',
                        return_value={'text': '  你好  ', 'language': 'zh'}) as stt:
            response = self._post()
        self.assertEqual(200, response.status_code)
        self.assertEqual({'text': '你好', 'language': 'zh', 'engine': 'local'}, response.json())
        self.assertEqual('zh', stt.call_args.kwargs['language'])
        self.assertEqual('audio/wav', stt.call_args.kwargs['content_type'])

    def test_a_service_still_loading_says_so_instead_of_failing(self):
        from wama.common.tts.service_client import TTSServiceLoadingError
        with mock.patch('wama.common.tts.service_client.stt_via_service',
                        side_effect=TTSServiceLoadingError('loading')):
            response = self._post()
        self.assertEqual(503, response.status_code)
        self.assertTrue(response.json()['busy'])

    def test_an_unreachable_service_is_explained(self):
        with mock.patch('wama.common.tts.service_client.stt_via_service',
                        side_effect=RuntimeError('Service TTS inaccessible')):
            response = self._post()
        self.assertEqual(502, response.status_code)
        self.assertIn('inaccessible', response.json()['error'])

    def test_nothing_is_heard_while_the_card_is_being_released(self):
        with mock.patch('wama.common.services.resource_governor.release_in_progress',
                        return_value=True), \
             mock.patch('wama.common.tts.service_client.stt_via_service') as stt:
            self.assertEqual(503, self._post().status_code)
        stt.assert_not_called()


    def test_a_subtitle_credit_invented_on_noise_never_becomes_a_reply(self):
        """Vécu le 2026-10-11 : trois « Sous-titrage ST' 501 » envoyés à l'assistant."""
        with mock.patch('wama.common.tts.service_client.stt_via_service',
                        return_value={'text': "Sous-titrage ST' 501", 'language': 'fr'}):
            response = self._post()
        self.assertEqual('', response.json()['text'])


class SpeechInputEngineTest(TestCase):
    """Quel moteur écoute : le profil décide, le local reprend toute phrase que le distant lâche."""

    REMOTE = 'albert:whisper-large-v3'

    def setUp(self):
        from wama.model_manager.models import AIModel
        self.user = User.objects.create_user('listen_engine', password='x')
        AIModel.objects.update_or_create(
            model_key=self.REMOTE,
            defaults=dict(name='whisper-large-v3', model_type='speech', source='albert',
                          execution='cloud', is_available=True,
                          composition={'runtime': {'engine': 'albert'}},
                          capabilities={'task': 'transcription'}))
        AIModel.objects.update_or_create(
            model_key='albert:gpt-oss-120b',
            defaults=dict(name='gpt-oss-120b', model_type='llm', source='albert',
                          execution='cloud', is_available=True,
                          composition={'runtime': {'engine': 'albert'}},
                          capabilities={'task': 'text-generation'}))

    def _opened(self, keys):
        return mock.patch('wama.model_manager.services.cloud_models.allowed_cloud_keys',
                          return_value=set(keys))

    def _local(self, text='bonjour'):
        return mock.patch('wama.common.tts.service_client.stt_via_service',
                          return_value={'text': text, 'language': 'fr'})

    def test_a_local_only_profile_is_heard_locally(self):
        from wama.common.tts import speech_input
        with self._opened([]), self._local() as local, \
             mock.patch.object(speech_input, '_transcribe_remote') as remote:
            result = speech_input.transcribe_utterance(self.user, b'WAV', language='fr')
        remote.assert_not_called()
        local.assert_called_once()
        self.assertEqual('local', result['engine'])

    def test_the_remote_model_is_the_transcription_one_the_profile_opens(self):
        from wama.common.tts.speech_input import remote_stt_key
        with self._opened([self.REMOTE, 'albert:gpt-oss-120b']):
            self.assertEqual(self.REMOTE, remote_stt_key(self.user))
        with self._opened(['albert:gpt-oss-120b']):
            self.assertEqual('', remote_stt_key(self.user), 'un modèle de chat n\'écoute pas')

    def test_a_cloud_profile_is_heard_remotely_without_the_local_service(self):
        from wama.common.tts import speech_input
        with self._opened([self.REMOTE]), self._local() as local, \
             mock.patch.object(speech_input, '_transcribe_remote',
                               return_value={'text': 'Liste mes fichiers.', 'language': 'fr'}):
            result = speech_input.transcribe_utterance(self.user, b'WAV', language='fr')
        local.assert_not_called()
        self.assertEqual({'text': 'Liste mes fichiers.', 'language': 'fr', 'engine': self.REMOTE},
                         result)

    def test_a_remote_failure_falls_back_to_the_local_listener(self):
        from wama.common.tts import speech_input
        with self._opened([self.REMOTE]), self._local('bonjour') as local, \
             mock.patch.object(speech_input, '_transcribe_remote',
                               side_effect=RuntimeError('HTTP 429')):
            result = speech_input.transcribe_utterance(self.user, b'WAV', language='fr')
        local.assert_called_once()
        self.assertEqual(('bonjour', 'local'), (result['text'], result['engine']))

    def test_warming_up_a_remote_listener_sends_nothing_anywhere(self):
        from wama.common.tts import speech_input
        with self._opened([self.REMOTE]), self._local() as local, \
             mock.patch.object(speech_input, '_transcribe_remote') as remote:
            result = speech_input.transcribe_utterance(self.user, b'WAV', warm_up=True)
        remote.assert_not_called()
        local.assert_not_called()
        self.assertEqual(self.REMOTE, result['engine'])

    def test_the_remote_call_goes_through_the_common_launch_door(self):
        """La garde `cloud_access` et la clé passent par `backend_instance_for_key`."""
        from wama.common.backends.speech_to_text_base import TranscriptionResult
        from wama.common.tts import speech_input
        backend = mock.Mock()
        backend.load.return_value = True
        backend.transcribe.return_value = TranscriptionResult(success=True, text='Oui.',
                                                              language='fr')
        with mock.patch('wama.common.backends.manager.backend_instance_for_key',
                        return_value=backend) as door, \
             mock.patch('wama.common.tts.service_client.speech_only_via_service',
                        return_value=b'SPEECH') as vad:
            result = speech_input._transcribe_remote(self.user, self.REMOTE, b'WAV', 'audio/wav')
        door.assert_called_once_with(self.REMOTE, self.user)
        backend.load.assert_called_once_with('whisper-large-v3')
        vad.assert_called_once()
        kwargs = backend.transcribe.call_args.kwargs
        # Le filtre a tourné dans le SERVICE : le backend ne le refait pas (import de 52 à 66 s).
        self.assertEqual((False, False), (kwargs['vad_filter'], kwargs['wait_on_rate_limit']))
        self.assertNotIn('language', kwargs, 'chez Albert, `language` TRADUIT la sortie')
        self.assertEqual('Oui.', result['text'])

    def test_a_clip_without_speech_never_leaves_wama(self):
        from wama.common.tts import speech_input
        backend = mock.Mock()
        backend.load.return_value = True
        with mock.patch('wama.common.backends.manager.backend_instance_for_key',
                        return_value=backend), \
             mock.patch('wama.common.tts.service_client.speech_only_via_service',
                        return_value=b''):
            result = speech_input._transcribe_remote(self.user, self.REMOTE, b'WAV', 'audio/wav')
        backend.transcribe.assert_not_called()
        self.assertEqual('', result['text'])

    def test_without_the_voice_service_the_clip_is_sent_unfiltered(self):
        """Contre-épreuve : le filtre est un plus, son absence ne coupe pas le micro."""
        from wama.common.backends.speech_to_text_base import TranscriptionResult
        from wama.common.tts import speech_input
        backend = mock.Mock()
        backend.load.return_value = True
        backend.transcribe.return_value = TranscriptionResult(success=True, text='Oui.')
        with mock.patch('wama.common.backends.manager.backend_instance_for_key',
                        return_value=backend), \
             mock.patch('wama.common.tts.service_client.speech_only_via_service',
                        side_effect=RuntimeError('Service TTS inaccessible')):
            result = speech_input._transcribe_remote(self.user, self.REMOTE, b'WAV', 'audio/wav')
        self.assertEqual('Oui.', result['text'])


class PhantomPhraseTest(SimpleTestCase):

    def test_known_subtitle_credits_are_removed(self):
        from wama.common.tts.speech_input import drop_phantom_phrases as drop
        for phantom in ("Sous-titrage ST' 501", "Sous-titrage ST’ 501.",
                        "Sous-titres réalisés par la communauté d'Amara.org",
                        "Sous-titrage Société Radio-Canada", "Merci d'avoir regardé cette vidéo !",
                        "Thank you for watching!"):
            self.assertEqual('', drop(phantom), phantom)

    def test_a_real_sentence_keeps_its_words_and_loses_the_credit(self):
        from wama.common.tts.speech_input import drop_phantom_phrases as drop
        self.assertEqual("Wama, est-ce que tu m'entends ?",
                         drop("Wama, est-ce que tu m'entends ? Sous-titrage ST' 501"))

    def test_what_a_user_really_says_is_never_filtered(self):
        """Contre-épreuve : des phrases voisines des génériques restent des répliques."""
        from wama.common.tts.speech_input import drop_phantom_phrases as drop
        for said in ('Merci.', 'Sous-titre cette vidéo.', 'Lance le sous-titrage du fichier 501.'):
            self.assertEqual(said, drop(said))


class AlbertRateLimitTest(SimpleTestCase):

    def test_a_caller_with_a_fallback_does_not_wait_on_the_rate_limit(self):
        import tempfile

        import requests

        from wama.common.backends.albert_asr_backend import AlbertTranscriptionBackend
        limited = requests.Response()
        limited.status_code = 429
        limited._content = b'{"detail": "rate limit"}'
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            with wave.open(f.name, 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(b'\x00\x00' * 1600)
            backend = AlbertTranscriptionBackend()
            backend.authorize('key')
            backend.load('whisper-large-v3')
            with mock.patch('requests.post', return_value=limited) as post, \
                 mock.patch('time.sleep') as sleep, \
                 mock.patch('wama.common.external_sources.base_url', return_value='https://x'):
                result = backend.transcribe(f.name, wait_on_rate_limit=False)
        self.assertFalse(result.success)
        self.assertEqual(1, post.call_count)
        sleep.assert_not_called()


class SpeechOnlyRouteTest(SimpleTestCase):
    """`/speech-only` du service vocal : le filtre de parole de l'écoute distante."""

    def setUp(self):
        import tts_service
        from fastapi.testclient import TestClient
        self.service = tts_service
        self.client = TestClient(tts_service.app)      # hors `with` : pas de démarrage réel

    def test_speech_comes_back_as_a_wav_and_silence_as_no_content(self):
        with mock.patch.object(self.service, '_speech_only_clip', return_value=b'RIFFSPEECH'):
            response = self.client.post('/speech-only', content=b'WAV',
                                        headers={'Content-Type': 'audio/wav'})
        self.assertEqual((200, b'RIFFSPEECH'), (response.status_code, response.content))
        with mock.patch.object(self.service, '_speech_only_clip', return_value=b''):
            response = self.client.post('/speech-only', content=b'WAV')
        self.assertEqual(204, response.status_code)

    def test_the_client_reads_no_content_as_no_speech(self):
        import requests

        from wama.common.tts import service_client
        empty = requests.Response()
        empty.status_code = 204
        empty._content = b''
        with mock.patch('requests.post', return_value=empty) as post:
            self.assertEqual(b'', service_client.speech_only_via_service(b'WAV'))
        self.assertTrue(post.call_args.args[0].endswith('/speech-only'))


class SttServiceClientTest(SimpleTestCase):

    def _response(self, status, payload):
        import requests
        resp = requests.Response()
        resp.status_code = status
        resp._content = json.dumps(payload).encode()
        return resp

    def test_the_audio_goes_raw_to_the_stt_route_with_the_assistant_model(self):
        from wama.common.tts import service_client
        from wama.common.tts.constants import ASSISTANT_STT_MODEL
        with mock.patch('requests.post', return_value=self._response(
                200, {'text': 'bonjour', 'language': 'fr'})) as post:
            result = service_client.stt_via_service(b'AUDIO', language='fr')
        self.assertEqual({'text': 'bonjour', 'language': 'fr'}, result)
        url = post.call_args.args[0]
        self.assertTrue(url.endswith('/stt'), url)
        self.assertEqual(b'AUDIO', post.call_args.kwargs['data'])
        self.assertEqual({'language': 'fr', 'model': ASSISTANT_STT_MODEL},
                         post.call_args.kwargs['params'])
        self.assertEqual('audio/wav', post.call_args.kwargs['headers']['Content-Type'])

    def test_a_loading_service_raises_the_same_error_as_for_the_voice(self):
        from wama.common.tts import service_client
        loading = self._response(503, {'detail': {'status': 'loading', 'message': 'wait'}})
        with mock.patch('requests.post', return_value=loading):
            with self.assertRaises(service_client.TTSServiceLoadingError):
                service_client.stt_via_service(b'AUDIO')

    def test_the_voice_still_posts_its_payload_to_the_tts_route(self):
        """Contre-épreuve de l'extraction de `_post` : la voix garde son contrat."""
        from wama.common.tts import service_client
        ok = self._response(200, {})
        ok._content = b'RIFFWAV'
        with mock.patch('requests.post', return_value=ok) as post, \
             mock.patch('wama.common.tts.ui_meta.tts_engine_declared', return_value=None):
            audio = service_client.tts_via_service('Bonjour', 'kokoro-onnx', raw=True)
        self.assertEqual(b'RIFFWAV', audio)
        self.assertTrue(post.call_args.args[0].endswith('/tts'))
        self.assertEqual('Bonjour', post.call_args.kwargs['json']['text'])


FAKE_BROWSER = r"""
var window = this;
window.addEventListener = function () {};
window.sessionStorage = null;
var document = { readyState: 'complete', cookie: '',
                 querySelectorAll: function () { return []; },
                 addEventListener: function () {}, removeEventListener: function () {} };
var navigator = {};
var console = { warn: function () {}, error: function () {} };
function Event(name) { this.type = name; }
function fakeButton() {
  return { disabled: false, title: '', classList: { toggle: function () {} },
           querySelector: function () { return { className: '' }; },
           addEventListener: function () {} };
}
var calls = [];
var voice = { speaking: false, audible: false, echo: false,
              isSpeaking: function () { return this.speaking; },
              isAudible: function () { return this.speaking || this.audible; },
              isOwnSpeech: function () { return this.echo; },
              stop: function () { calls.push('voice.stop'); }, onChange: function () {} };
window.WamaAssistantVoice = voice;
var chat = { busy: false, sent: [],
             input: { value: '', dispatchEvent: function () {}, focus: function () {} },
             isBusy: function () { return this.busy; },
             abort: function () { calls.push('chat.abort'); },
             send: function () { this.sent.push(this.input.value); this.input.value = '';
                                 return Promise.resolve(true); } };
var root = { querySelector: function () { return fakeButton(); } };
"""


class ListenBrickTest(SimpleTestCase):
    """La brique servie (`staticfiles/`), exécutée par V8 avec un faux navigateur minimal."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        # Dans l'ordre de base.html : la capture (accès au micro, 2026-10-26) avant l'écoute.
        js = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
        source = ''.join((js / name).read_text(encoding='utf-8')
                         for name in ('wama-capture.js', 'wama-assistant-listen.js'))
        ctx = MiniRacer()
        ctx.eval(FAKE_BROWSER + source)
        return ctx

    def _segment(self, ctx, pattern, mode='normal'):
        """Rend les événements du découpage pour [(amplitude, durée ms), …] à 48 kHz."""
        return json.loads(ctx.eval("""
            JSON.stringify((function () {
              var events = [], rate = 48000, len = 2048, k = 0;
              var seg = new WamaAssistantListen._Segmenter(rate, 900, function (evt, samples) {
                events.push(evt);
              });
              %s.forEach(function (p) {
                var n = Math.round(p[1] / (len / rate * 1000));
                for (var i = 0; i < n; i++, k++) {
                  var f = new Float32Array(len);
                  for (var j = 0; j < len; j++) {
                    f[j] = 0.001 * Math.sin(j * 7.3 + k)
                         + p[0] * Math.sin(2 * Math.PI * 220 * (j + k * len) / rate);
                  }
                  seg.feed(f, %r);
                }
              });
              return events;
            })())
        """ % (json.dumps(pattern), mode)))

    def test_a_spoken_phrase_between_two_silences_makes_one_utterance(self):
        ctx = self._ctx()
        self.assertEqual(['start', 'end'], self._segment(ctx, [[0, 1000], [0.1, 1500], [0, 1500]]))

    def test_a_short_click_is_not_a_phrase(self):
        ctx = self._ctx()
        self.assertNotIn('end', self._segment(ctx, [[0, 1000], [0.1, 130], [0, 1500]]))

    def test_interrupting_the_assistant_needs_a_sustained_voice(self):
        ctx = self._ctx()
        self.assertEqual([], self._segment(ctx, [[0, 1000], [0.1, 200], [0, 1500]], 'interrupt'))
        self.assertEqual(['start', 'end'],
                         self._segment(ctx, [[0, 1000], [0.1, 800], [0, 1500]], 'interrupt'))

    def test_a_deaf_listener_hears_nothing(self):
        ctx = self._ctx()
        self.assertEqual([], self._segment(ctx, [[0, 1000], [0.1, 1500], [0, 1500]], 'deaf'))

    def _room(self, ctx, pattern, opening_zeros=True):
        """Comme `_segment`, dans une pièce BRUITÉE : [(voix, durée ms, bruit rms)], précédé des
        trames nulles d'un micro qui s'ouvre."""
        return json.loads(ctx.eval("""
            JSON.stringify((function () {
              var events = [], rate = 48000, len = 2048, k = 0, seed = 7;
              function noise() { seed = (seed * 16807) %% 2147483647; return seed / 1073741823.5 - 1; }
              var seg = new WamaAssistantListen._Segmenter(rate, 900, function (evt) { events.push(evt); });
              if (%s) for (var z = 0; z < 3; z++) seg.feed(new Float32Array(len), 'normal');
              %s.forEach(function (p) {
                var n = Math.round(p[1] / (len / rate * 1000));
                for (var i = 0; i < n; i++, k++) {
                  var f = new Float32Array(len);
                  for (var j = 0; j < len; j++) {
                    f[j] = p[2] * 1.732 * noise() + p[0] * Math.sin(2 * Math.PI * 220 * (j + k * len) / rate);
                  }
                  seg.feed(f, 'normal');
                }
              });
              return events;
            })())
        """ % ('true' if opening_zeros else 'false', json.dumps(pattern))))

    def test_a_noisy_room_is_learnt_as_the_background(self):
        """2026-10-27 : au-dessus de -55 dBFS (souffle d'un casque, gain automatique), le fond
        n'était jamais appris — la « phrase » s'ouvrait à 85 ms et ne se fermait qu'au plafond
        de 30 s. Mesuré sur la brique servie : -56 dBFS découpait, -54 ne découpait plus."""
        ctx = self._ctx()
        noise = 10 ** (-50 / 20)
        self.assertEqual(['start', 'end', 'start', 'end'], self._room(ctx, [
            [0, 2000, noise], [0.05, 2000, noise], [0, 3000, noise],
            [0.05, 1500, noise], [0, 3000, noise]]))

    def test_the_noise_of_a_room_alone_is_not_a_phrase(self):
        """Contre-épreuve : le même bruit, sans voix, n'ouvre rien — pas même aux trames nulles
        de l'ouverture du micro, qui ne deviennent pas le fond."""
        ctx = self._ctx()
        self.assertEqual([], self._room(ctx, [[0, 8000, 10 ** (-50 / 20)]]))

    def test_the_clip_is_a_standard_16_khz_mono_wav(self):
        ctx = self._ctx()
        data = json.loads(ctx.eval("""
            JSON.stringify(Array.from(new Uint8Array(WamaAssistantListen._wavBytes(
              WamaAssistantListen._downsample(new Float32Array(24000), 48000)))))
        """))
        with wave.open(io.BytesIO(bytes(data))) as w:
            self.assertEqual((1, 16000, 2, 8000),
                             (w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes()))

    def _controller(self, ctx, echo_cancelled):
        ctx.eval("""
            var c = new WamaAssistantListen._Controller(chat, root);
            c.mode = 'conversation';
            c.mic = { echoCancelled: %s, rate: 16000 };
        """ % ('true' if echo_cancelled else 'false'))

    def test_the_listener_only_interrupts_when_the_browser_cancels_the_echo(self):
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=True)
        self.assertEqual('normal', ctx.eval("c.frameMode()"))
        ctx.eval("voice.speaking = true;")
        self.assertEqual('interrupt', ctx.eval("c.frameMode()"))
        ctx.eval("c.mic.echoCancelled = false;")
        self.assertEqual('deaf', ctx.eval("c.frameMode()"),
                         "sans annulation d'écho, l'assistant s'interromprait lui-même")
        ctx.eval("voice.speaking = false; chat.busy = true;")
        self.assertEqual('normal', ctx.eval("c.frameMode()"),
                         "pendant qu'il réfléchit, rien ne joue : l'écoute reste ordinaire (2026-10-27)")

    def test_the_listening_button_names_the_microphone_the_browser_opened(self):
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=True)
        ctx.eval("c.phase = 'listening'; c.mic.label = 'Casque USB'; c.mic.ctx = { state: 'running' };"
                 "c.render();")
        self.assertIn('micro : Casque USB', ctx.eval("c.talkBtn.title"))
        ctx.eval("c.mic.label = ''; c.render();")
        self.assertNotIn('micro :', ctx.eval("c.talkBtn.title"), 'sans nom, rien de plus')

    def test_a_phrase_said_while_it_thinks_replaces_the_question(self):
        """2026-10-27, décision de Fabien : l'écoute était sourde (ou durcie) pendant toute la
        réflexion, alors qu'aucun son ne sortait — « ma parole ne semble pas reçue »."""
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=False)
        ctx.eval("chat.busy = true; c.onSegment('start', null, c.frameMode());")
        self.assertEqual(['Plutôt la liste des images'], self._heard(ctx, 'Plutôt la liste des images'))
        self.assertEqual(['voice.stop', 'chat.abort'], json.loads(ctx.eval("JSON.stringify(calls)")))

    def test_speaking_over_the_assistant_stops_it_once_the_phrase_is_understood(self):
        """2026-10-13 : on ne coupe plus au premier son — l'annulation d'écho du navigateur peut
        ne pas couvrir ce que joue la page, et un écho coupait l'assistant."""
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=True)
        ctx.eval("c.onSegment('start', null, 'interrupt');")
        self.assertEqual([], json.loads(ctx.eval("JSON.stringify(calls)")), 'pas au premier son')
        self.assertEqual('hearing', ctx.eval("c.phase"))
        self.assertEqual(['Arrête-toi'], self._heard(ctx, 'Arrête-toi'))
        self.assertEqual(['voice.stop', 'chat.abort'], json.loads(ctx.eval("JSON.stringify(calls)")))

    def test_its_own_echo_heard_over_it_does_not_stop_it(self):
        """Contre-épreuve : sa propre voix, revenue au micro, ne lui coupe pas la parole."""
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=True)
        ctx.eval("voice.echo = true; c.onSegment('start', null, 'interrupt');")
        self.assertEqual([], self._heard(ctx, "vous avez besoin d'autre chose."))
        self.assertEqual([], json.loads(ctx.eval("JSON.stringify(calls)")))

    def test_an_ordinary_phrase_stops_nothing(self):
        """Contre-épreuve : une phrase dite pendant qu'il se tait part sans rien interrompre."""
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=True)
        ctx.eval("c.onSegment('start', null, 'normal');")
        self.assertEqual(['Liste mes fichiers'], self._heard(ctx, 'Liste mes fichiers'))
        self.assertEqual([], json.loads(ctx.eval("JSON.stringify(calls)")))

    def test_a_transcribed_phrase_is_sent_as_the_next_turn(self):
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=True)
        ctx.eval("c.sendTurn('Liste mes fichiers');")
        self.assertEqual(['Liste mes fichiers'], json.loads(ctx.eval("JSON.stringify(chat.sent)")))

    def test_a_stopped_conversation_sends_nothing_left_over(self):
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=True)
        ctx.eval("c.mode = 'off'; c.sendTurn('trop tard');")
        self.assertEqual([], json.loads(ctx.eval("JSON.stringify(chat.sent)")))

    def _heard(self, ctx, text):
        """Une phrase captée en conversation, que le service transcrit en `text`."""
        ctx.eval("""
            var Blob = function (parts, opts) { this.parts = parts; };
            var fetch = function () {
              return Promise.resolve({ json: function () { return Promise.resolve({ text: %r }); } });
            };
            c.onSegment('end', new Float32Array(1600));
        """ % text)
        return json.loads(ctx.eval("JSON.stringify(chat.sent)"))

    def test_the_assistant_s_own_voice_heard_at_the_mic_is_not_sent_back(self):
        """2026-10-13 : « … si vous avez besoin d'autre chose », fin d'une réponse encore jouée
        par le haut-parleur, est repartie comme réplique — l'assistant s'est répondu."""
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=True)
        ctx.eval("voice.echo = true;")
        self.assertEqual([], self._heard(ctx, "vous avez besoin d'autre chose."))

    def test_a_phrase_that_is_not_its_echo_is_still_sent(self):
        """Contre-épreuve."""
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=True)
        self.assertEqual(['Liste mes fichiers'], self._heard(ctx, 'Liste mes fichiers'))

    def test_the_assistant_is_active_while_its_voice_is_still_audible(self):
        """Le haut-parleur joue encore après la fin de l'audio (latence de sortie)."""
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=False)
        ctx.eval("voice.audible = true;")
        self.assertEqual('deaf', ctx.eval("c.frameMode()"))
        ctx.eval("voice.audible = false;")
        self.assertEqual('normal', ctx.eval("c.frameMode()"))

    def test_what_the_mic_kept_while_the_assistant_spoke_is_not_the_next_phrase(self):
        """L'avance du découpage (400 ms) se remplit aussi pendant que l'assistant parle : quand il
        se tait, elle est faite de SA voix et n'ouvre pas la phrase suivante."""
        ctx = self._ctx()
        self._controller(ctx, echo_cancelled=True)
        ctx.eval("""
            c.segmenter = new WamaAssistantListen._Segmenter(48000, 900, function () {});
            var frame = new Float32Array(2048);
            for (var j = 0; j < 2048; j++) frame[j] = 0.003 * Math.sin(j * 0.05);
            voice.speaking = true;
            for (var i = 0; i < 10; i++) c.onFrame(frame);
        """)
        self.assertGreater(ctx.eval("c.segmenter.prerollMs"), 300, 'avance pleine pendant sa voix')
        ctx.eval("voice.speaking = false; c.onFrame(frame);")
        self.assertLess(ctx.eval("c.segmenter.prerollMs"), 50)

    def test_the_warm_up_announces_itself_and_the_label_names_who_listens(self):
        ctx = self._ctx()
        ctx.eval("""
            var fetched = [];
            var Blob = function (parts, opts) { this.parts = parts; };
            var fetch = function (url) {
              fetched.push(url);
              return Promise.resolve({ json: function () {
                return Promise.resolve({ text: '', engine: 'albert:whisper-large-v3' }); } });
            };
        """)
        self.assertIn('rien ne sort de WAMA', ctx.eval("WamaAssistantListen._listenerLabel()"))
        ctx.eval("WamaAssistantListen._warmUp();")
        self.assertEqual(['/api/stt/?warmup=1'], json.loads(ctx.eval("JSON.stringify(fetched)")))
        label = ctx.eval("WamaAssistantListen._listenerLabel()")
        self.assertIn('albert', label)
        self.assertNotIn('rien ne sort', label, "l'info-bulle ne dit plus « local » à tort")

    def _capture(self, ctx):
        """Une capture sans chat, micro simulé ; `answer(i, corps)` répond au i-ème envoi."""
        ctx.eval("""
            var posted = [], pending = [], heard = [], ended = [], errors = [];
            var Blob = function (parts, opts) { this.parts = parts; this.type = (opts || {}).type; };
            var fetch = function (url) {
              posted.push(url);
              return new Promise(function (resolve) { pending.push(resolve); });
            };
            function answer(i, body) {
              pending[i]({ json: function () { return Promise.resolve(body); } });
            }
            var cap = new WamaAssistantListen._Capture({
              onText: function (text) { heard.push(text); },
              onError: function (message) { errors.push(message); },
              onEnd: function (result) { ended.push(result); } });
            cap.mic = { rate: 16000 };
        """)

    def _js(self, ctx, expr):
        return json.loads(ctx.eval('JSON.stringify(%s)' % expr))

    def test_a_capture_transcribes_one_phrase_at_a_time_in_the_order_of_speech(self):
        ctx = self._ctx()
        self._capture(ctx)
        ctx.eval("cap.onSegment('end', new Float32Array(1600));"
                 "cap.onSegment('end', new Float32Array(1600));")
        self.assertEqual(1, self._js(ctx, 'posted.length'),
                         "la seconde phrase attend la première : pas de rafale chez le fournisseur")
        ctx.eval("answer(0, { text: 'Bonjour', language: 'fr', engine: 'albert:whisper-large-v3' });")
        self.assertEqual(2, self._js(ctx, 'posted.length'))
        ctx.eval("answer(1, { text: 'tout le monde', language: 'fr' });")
        self.assertEqual(['Bonjour', 'tout le monde'], self._js(ctx, 'heard'))

    def test_stopping_a_capture_waits_for_the_last_phrase_and_ends_once(self):
        ctx = self._ctx()
        self._capture(ctx)
        ctx.eval("""
            cap.onSegment('end', new Float32Array(1600));
            var result = null;
            cap.stop().then(function (r) { result = r; });
            cap.stop();
        """)
        self.assertEqual([], self._js(ctx, 'ended'), 'la phrase en vol arrive avant la fin')
        ctx.eval("answer(0, { text: 'Fin de la réunion', language: 'fr', engine: 'local' });")
        self.assertEqual(1, self._js(ctx, 'ended.length'), 'un second stop() ne rejoue pas la fin')
        result = self._js(ctx, 'result')
        self.assertEqual(('Fin de la réunion', 'fr', 'local', None),
                         (result['text'], result['language'], result['engine'], result['recording']))
        self.assertEqual('off', ctx.eval('cap.mode'))

    def test_a_refused_phrase_is_reported_and_the_next_one_still_goes(self):
        ctx = self._ctx()
        self._capture(ctx)
        # L'envoi part dans une micro-tâche : il existe à l'évaluation SUIVANTE.
        ctx.eval("cap.onSegment('end', new Float32Array(1600));"
                 "cap.onSegment('end', new Float32Array(1600));")
        ctx.eval("answer(0, { error: 'service vocal indisponible' });")
        self.assertEqual(['service vocal indisponible'], self._js(ctx, 'errors'))
        ctx.eval("answer(1, { text: 'encore là' });")
        self.assertEqual(['encore là'], self._js(ctx, 'heard'))

    def test_the_chat_brick_exposes_what_the_conversation_needs(self):
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        for needed in ('Chat.prototype.abort', 'Chat.prototype.isBusy', 'signal: this.signal()'):
            self.assertIn(needed, source)


class ListenBrickIsMountedEverywhereTest(TestCase):
    """Les deux surfaces de l'assistant DÉCLARENT les boutons ; la brique est chargée par
    `base.html`. L'ancienne dictée par le navigateur (audio envoyé à Google) a disparu."""

    def setUp(self):
        self.user = User.objects.create_user('listen_mount', password='x', is_staff=True,
                                             is_superuser=True)
        self.client.force_login(self.user)

    def test_the_home_chat_offers_dictation_and_conversation(self):
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('wama-assistant-listen.js', html)
        self.assertIn('data-assistant-talk', html)
        self.assertIn('data-assistant-mic', html)
        # Le CODE de l'ancienne dictée, pas le mot (un commentaire le nomme pour dire qu'il est parti).
        self.assertNotIn('window.webkitSpeechRecognition', html)
        self.assertNotIn('new SR()', html)

    def test_the_panel_chat_template_offers_the_same_buttons(self):
        source = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'templates' / 'common'
                  / '_assistant_avatar.html').read_text(encoding='utf-8')
        self.assertIn('data-assistant-talk', source)
        self.assertIn('data-assistant-mic', source)
        self.assertIn("{% url 'speech_to_text' %}", source)


class TranscriberSpeakListensThroughTheCommonBrickTest(TestCase):
    """Le port « en direct » du transcriber (Speak, 2026-10-12) écoute par la même brique que
    l'assistant : plus de reconnaissance du navigateur, et la card dit quel moteur a écouté."""

    def setUp(self):
        # Superutilisateur : l'accès à l'app (profil) n'est pas l'objet de ces tests.
        self.user = User.objects.create_user('speak_tester', password='x', is_staff=True,
                                             is_superuser=True)
        self.client.force_login(self.user)

    def test_the_served_speak_script_uses_the_common_capture(self):
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'transcriber' / 'js'
                  / 'index.js').read_text(encoding='utf-8')
        self.assertIn('listen.capture(', source)
        self.assertIn('record: true', source)
        self.assertNotIn('webkitSpeechRecognition', source, "l'audio partait chez Google")

    def _save(self, engine):
        import shutil
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from wama.transcriber.models import Transcript
        media = tempfile.mkdtemp(prefix='wama_speak_')
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        with override_settings(MEDIA_ROOT=media):
            response = self.client.post(reverse('transcriber:save_realtime'), {
                'audio': SimpleUploadedFile('realtime.webm', b'\x1aE\xdf\xa3', 'audio/webm'),
                'text': 'Bonjour', 'language': 'fr', 'engine': engine})
        self.assertEqual(200, response.status_code, response.content)
        return Transcript.objects.get(pk=response.json()['id'])

    def test_a_realtime_card_names_the_engine_that_listened(self):
        self.assertEqual('albert', self._save('albert:whisper-large-v3').used_backend)
        self.assertEqual('whisper', self._save('local').used_backend)

    def test_a_realtime_card_is_not_a_measure_of_the_model(self):
        """Contre-épreuve : un texte découpé phrase à phrase n'est attribué à aucun modèle."""
        t = self._save('albert:whisper-large-v3')
        self.assertEqual('', t.model_key)
        self.assertTrue(t.is_realtime)

    def test_a_realtime_card_is_born_with_the_author_preferences(self):
        """La card naît par la cascade commune des dépôts : sa relance suit les préférences de
        l'auteur. Avant, la diarisation était FORCÉE et le reste prenait les défauts du modèle."""
        import json
        self.client.post(reverse('transcriber:save_user_settings'),
                         json.dumps({'enable_diarization': False, 'hotwords': 'Eiffel, WAMA',
                                     'vad_mode': 'off'}), content_type='application/json')
        t = self._save('local')
        self.assertEqual((False, 'Eiffel, WAMA', 'off'),
                         (t.enable_diarization, t.hotwords, t.vad_mode))

    def test_without_preferences_a_realtime_card_keeps_the_defaults(self):
        """Contre-épreuve : sans préférence, la diarisation reste active par défaut — un
        lancement rapide la garde, comme pour un fichier déposé."""
        self.assertTrue(self._save('local').enable_diarization)

    def test_the_speak_post_does_not_rewrite_the_author_preferences(self):
        """Speak ne poste aucun réglage du volet : enregistrer une card ne touche pas aux
        préférences, qui restent celles que l'auteur a posées."""
        import json
        self.client.post(reverse('transcriber:save_user_settings'),
                         json.dumps({'enable_diarization': False}),
                         content_type='application/json')
        self._save('local')
        served = self.client.get(reverse('transcriber:get_user_settings')).json()
        self.assertFalse(served['enable_diarization'])

    def test_relaunching_a_realtime_card_goes_through_the_normal_transcription(self):
        """La qualité vient de la relance (↻) sur l'audio enregistré : la card temps réel part
        dans la tâche de transcription ordinaire, rien de propre au temps réel."""
        from unittest import mock
        t = self._save('local')
        task = mock.Mock()
        task.delay.return_value = mock.Mock(id='speak-relaunch')
        with mock.patch('wama.transcriber.views._task_for', return_value=task) as task_for:
            response = self.client.post(reverse('transcriber:start', args=[t.pk]))
        self.assertEqual(200, response.status_code, response.content)
        task.delay.assert_called_once_with(t.pk)
        self.assertTrue(task_for.call_args.args[0].is_realtime)
        t.refresh_from_db()
        self.assertEqual('RUNNING', t.status)
