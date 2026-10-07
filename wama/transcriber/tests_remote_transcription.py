"""
Transcription par un modèle DISTANT (Albert API) — 2026-09-30.

CE QUE CES GARDES PROTÈGENT :
- le modèle distant se résout par le lien COMMUN modèle ↔ moteur, et ce lien ne déborde pas :
  le backend de transcription du moteur `albert` n'est PAS rendu pour un modèle de chat du même
  fournisseur (filtre des moteurs distants, `backend_inventory.resolve_entry`) ;
- une clé distante n'est JAMAIS traduite en moteur local (`albert:whisper-large-v3` contient
  « whisper ») : un refus lève, il ne se replie pas en silence sur le GPU local ;
- l'appel passe la garde commune (`cloud_access`) : « 100 % local » refuse, un modèle que la clé
  de CET utilisateur n'ouvre pas refuse, et la clé transmise est la sienne ;
- le backend lit le protocole mesuré le 2026-09-30 (`verbose_json`) et ne traduit pas la sortie
  par erreur (`language` n'est envoyé que s'il est imposé) ;
- le filtre de parole (2026-10-01) n'envoie que la parole et replace les horodatages sur l'audio
  d'origine — un temps décalé ruinerait la diarisation et l'éditeur sans rien signaler.
Aucun appel réseau : le point d'entrée d'Albert est simulé à la forme qu'il rend réellement.
"""
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from wama.common.backends.albert_asr_backend import AlbertTranscriptionBackend
from wama.common.backends.manager import backend_for_model
from wama.model_manager.models import AIModel
from wama.transcriber.backends.manager import TranscriberBackendManager

SECRET = 'a' * 50
ASR_KEY = 'albert:whisper-large-v3'

#: Forme RÉELLE de `POST /v1/audio/transcriptions` en `verbose_json` (relevée le 2026-09-30).
VERBOSE_JSON = {
    'id': 'x', 'model': 'whisper-large-v3', 'task': 'transcribe', 'language': 'fr',
    'duration': 9.399, 'text': ' Notre délégation défendra la lutte.',
    'segments': [{'id': 0, 'type': 'transcript.text.segment', 'text': ' Notre délégation',
                  'start': 0.183, 'end': 4.0, 'speaker': None},
                 {'id': 1, 'type': 'transcript.text.segment', 'text': ' défendra la lutte.',
                  'start': 4.0, 'end': 9.346, 'speaker': None}],
    'usage': {'prompt_tokens': 0, 'completion_tokens': 37, 'total_tokens': 37},
}


def _remote_rows():
    """Les deux lignes qu'Albert dépose au catalogue : même moteur, tâches différentes."""
    asr = AIModel.objects.create(
        model_key=ASR_KEY, name='whisper-large-v3', model_type='speech', source='albert',
        execution='cloud', is_available=True, composition={'runtime': {'engine': 'albert'}},
        capabilities={'task': 'transcription'})
    chat = AIModel.objects.create(
        model_key='albert:gpt-oss-120b', name='gpt-oss-120b', model_type='llm', source='albert',
        execution='cloud', is_available=True, composition={'runtime': {'engine': 'albert'}},
        capabilities={'task': 'text-generation', 'completion': True})
    return asr, chat


def _wav_16k_mono(folder) -> str:
    import numpy as np
    import soundfile as sf
    path = str(Path(folder) / 'speech.wav')
    sf.write(path, np.zeros(1600, dtype='float32'), 16000)
    return path


class RemoteEngineResolutionTest(TestCase):

    def test_the_transcription_backend_serves_the_remote_speech_model(self):
        asr, _ = _remote_rows()
        self.assertIs(AlbertTranscriptionBackend, backend_for_model(asr))

    def test_it_does_not_serve_a_chat_model_of_the_same_provider(self):
        _, chat = _remote_rows()
        self.assertIsNone(backend_for_model(chat))


@override_settings(SECRET_KEY=SECRET, SECRET_KEY_FALLBACKS=[])
class RemoteBackendThroughTheManagerTest(TestCase):

    def setUp(self):
        from wama.accounts.models import UserApiKey
        from wama.transcriber.catalogue_fixtures import transcription_catalogue
        _remote_rows()
        transcription_catalogue('transcriber:whisper')
        self.user = get_user_model().objects.create_user('asr_cloud', password='x')
        self.user.profile.cloud_policy = 'cloud_allowed'
        self.user.profile.save()
        UserApiKey.objects.create(user=self.user, source='albert', api_key='personal-key',
                                  open_models=[ASR_KEY])
        self.manager = TranscriberBackendManager.get_instance()
        self.addCleanup(self.manager._instances.pop, ASR_KEY, None)

    def test_a_remote_key_is_never_translated_to_a_local_engine(self):
        self.assertIsNone(TranscriberBackendManager._backend_for_model_key(ASR_KEY))
        self.assertEqual('whisper',
                         TranscriberBackendManager._backend_for_model_key('transcriber:whisper'))

    def test_the_request_resolves_to_the_remote_backend_with_the_users_key(self):
        backend = self.manager.get_backend(ASR_KEY, user=self.user)
        self.assertIsInstance(backend, AlbertTranscriptionBackend)
        self.assertEqual(ASR_KEY, backend.catalogue_key)
        self.assertEqual('personal-key', backend._api_key)
        self.assertTrue(TranscriberBackendManager.honours(backend, ASR_KEY))
        self.assertEqual('whisper-large-v3',
                         TranscriberBackendManager.model_for_request(backend, ASR_KEY))

    def test_a_local_only_profile_is_refused_not_replaced_by_a_local_engine(self):
        self.user.profile.cloud_policy = 'local_only'
        self.user.profile.save()
        with self.assertRaisesMessage(RuntimeError, '100 % local'):
            self.manager.get_backend(ASR_KEY, user=self.user)

    def test_a_model_the_users_key_does_not_open_is_refused(self):
        other = get_user_model().objects.create_user('asr_no_key', password='x')
        other.profile.cloud_policy = 'cloud_allowed'
        other.profile.save()
        with self.assertRaisesMessage(RuntimeError, "n'est pas ouvert"):
            self.manager.get_backend(ASR_KEY, user=other)

    def test_the_evaluation_varies_the_speech_filter_only_where_it_exists(self):
        """`asr_eval_corpus` lit la capacité sur la CLASSE, sans clé ni appel (2026-10-01)."""
        from wama.transcriber.backends.manager import filters_speech
        self.assertTrue(filters_speech(ASR_KEY))
        self.assertTrue(filters_speech('whisper'))
        self.assertFalse(filters_speech('qwen_asr'))

    def test_the_assistant_discovers_the_remote_model_by_the_catalogue(self):
        """Since 2026-10-07 (one rule, no door domain), the assistant learns the transcription
        models through `list_ai_models` — the remote ASR model is listed, the chat model is not."""
        from wama.tool_api import list_ai_models
        keys = {m['key'] for m in list_ai_models(self.user, task='transcription')['models']}
        self.assertIn(ASR_KEY, keys)
        self.assertNotIn('albert:gpt-oss-120b', keys)


class AlbertProtocolTest(TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.audio = _wav_16k_mono(self.folder)
        self.backend = AlbertTranscriptionBackend()
        self.backend.load('whisper-large-v3')
        self.backend.authorize('personal-key')

    def _post(self, status=200, payload=VERBOSE_JSON):
        response = mock.Mock(status_code=status, text='', json=mock.Mock(return_value=payload))
        return mock.patch('requests.post', return_value=response)

    def test_the_verbose_json_answer_becomes_timed_segments(self):
        with self._post() as post:
            result = self.backend.transcribe(audio_path=self.audio)
        self.assertTrue(result.success)
        self.assertEqual(('fr', 2), (result.language, len(result.segments)))
        self.assertEqual((0.183, 'Notre délégation'),
                         (result.segments[0].start_time, result.segments[0].text))
        sent = post.call_args.kwargs
        self.assertEqual('Bearer personal-key', sent['headers']['Authorization'])
        self.assertEqual({'model': 'whisper-large-v3', 'response_format': 'verbose_json'},
                         sent['data'])
        self.assertTrue(post.call_args.args[0].endswith('/audio/transcriptions'))

    def test_language_is_sent_only_when_imposed_since_albert_translates_to_it(self):
        with self._post() as post:
            self.backend.transcribe(audio_path=self.audio, language='fr')
        self.assertEqual('fr', post.call_args.kwargs['data']['language'])

    def test_a_refusal_is_reported_with_the_providers_reason(self):
        with self._post(413, {'detail': 'File size limit exceeded.'}):
            result = self.backend.transcribe(audio_path=self.audio)
        self.assertFalse(result.success)
        self.assertIn('413', result.error)
        self.assertIn('File size limit exceeded', result.error)

    def test_the_rate_limit_is_waited_out_not_reported_as_a_failure(self):
        """Albert plafonne à 10 requêtes par minute : un 429 se patiente (2026-10-01)."""
        busy = mock.Mock(status_code=429, text='', headers={'Retry-After': '0'})
        done = mock.Mock(status_code=200, text='', json=mock.Mock(return_value=VERBOSE_JSON))
        with mock.patch('requests.post', side_effect=[busy, done]) as post, \
                mock.patch('time.sleep') as slept:
            result = self.backend.transcribe(audio_path=self.audio)
        self.assertTrue(result.success)
        self.assertEqual(2, post.call_count)
        slept.assert_called_once_with(0.0)

    def test_without_a_key_nothing_is_sent(self):
        self.backend.authorize('')
        with self._post() as post:
            result = self.backend.transcribe(audio_path=self.audio)
        self.assertFalse(result.success)
        post.assert_not_called()

    def _speech_at(self, spans):
        """Un audio de 4 s, et le VAD qui y entend `spans` (échantillons à 16 kHz)."""
        import numpy as np
        import soundfile as sf
        sf.write(self.audio, np.full(64000, 0.1, dtype='float32'), 16000)
        return mock.patch('faster_whisper.vad.get_speech_timestamps', return_value=spans)

    def test_the_speech_filter_sends_only_speech_and_puts_times_back_on_the_original(self):
        """Parole de 1 à 2 s et de 3 à 4 s : 2 s envoyées, et un segment à 0,5 s / 1,2 s de
        l'envoi revient à 1,5 s / 3,2 s de l'audio d'origine (2026-10-01)."""
        import soundfile as sf
        sent = {}

        def capture(*args, **kwargs):
            sent['seconds'] = sf.info(kwargs['files']['file'][1]).duration
            payload = dict(VERBOSE_JSON, segments=[
                {'text': ' un', 'start': 0.5, 'end': 0.9}, {'text': ' deux', 'start': 1.2,
                                                           'end': 1.8}])
            return mock.Mock(status_code=200, text='', json=mock.Mock(return_value=payload))

        with self._speech_at([{'start': 16000, 'end': 32000}, {'start': 48000, 'end': 64000}]), \
                mock.patch('requests.post', side_effect=capture):
            result = self.backend.transcribe(audio_path=self.audio, vad_filter=True)
        self.assertAlmostEqual(2.0, sent['seconds'], places=2)
        self.assertEqual([(1.5, 1.9), (3.2, 3.8)],
                         [(s.start_time, s.end_time) for s in result.segments])

    def test_without_the_filter_the_whole_audio_is_sent(self):
        with self._speech_at([{'start': 16000, 'end': 32000}]) as vad, self._post():
            self.backend.transcribe(audio_path=self.audio)
        vad.assert_not_called()

    def test_no_speech_heard_means_no_request_and_an_empty_transcript(self):
        with self._speech_at([]), self._post() as post:
            result = self.backend.transcribe(audio_path=self.audio, vad_filter=True)
        post.assert_not_called()
        self.assertEqual((True, ''), (result.success, result.text))

    def test_a_16k_mono_wav_is_sent_as_is_and_anything_else_is_converted(self):
        self.assertEqual(self.audio, self.backend._upload_path(self.audio, self.folder))
        with mock.patch('wama.common.utils.audio_decode.transcode_to_wav',
                        return_value='converted.wav') as convert:
            self.assertEqual('converted.wav',
                             self.backend._upload_path('meeting.m4a', self.folder))
        convert.assert_called_once()
