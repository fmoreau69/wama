"""La voix AU FIL DE L'EAU (2026-10-28) : le premier son part pendant que le reste se calcule.

Quatre étages, chacun gardé là où un défaut ne se verrait pas à l'oreille d'un essai :
  • le contrat commun (`TTSBackend.synthesize_stream`) garde les règles de `synthesize` — lexique,
    pauses — et calcule le premier son AVANT de rendre la main ;
  • Phonon rend son flux natif au niveau du fichier (gain fixe) et rend son verrou, flux lu ou
    abandonné ;
  • le service (`/tts/stream`) diffuse du PCM 16 bits et libère le moteur à la fin du flux ;
  • la vue de l'assistant diffuse quand le navigateur le demande, et rend la réponse entière d'avant
    quand le service ne peut pas.
"""
import json
import os
import threading
from unittest import mock

import numpy as np
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase

from wama.common.backends.tts_base import TTSBackend, write_wav_int16

RATE = 16000


class _ToneBackend(TTSBackend):
    """Un moteur factice : chaque segment dit = 0,1 s d'un niveau constant, et un journal."""
    engine = 'tone'
    is_loaded = True

    def __init__(self):
        super().__init__()
        self.said = []

    def load(self, *args, **kwargs):
        return True

    def unload(self):
        pass

    def process(self, text='', **_):
        self.said.append(text)
        return write_wav_int16(np.full(int(RATE * 0.1), 0.25, dtype=np.float32), RATE,
                               normalize=False)


class StreamContractTest(SimpleTestCase):

    def test_segments_and_their_pauses_come_one_by_one_the_first_before_returning(self):
        be = _ToneBackend()
        rate, chunks = be.synthesize_stream(text='Bonjour. Comment allez-vous ?',
                                            options={'sentence_pause': 0.5})
        self.assertEqual(RATE, rate)
        self.assertEqual(['Bonjour.'], be.said, "le premier son est calculé avant la réponse, "
                                                "le second segment pas encore")
        parts = list(chunks)
        self.assertEqual(['Bonjour.', 'Comment allez-vous ?'], be.said)
        lengths = [len(p) for p in parts]
        self.assertIn(int(RATE * 0.5), lengths, "la pause réglée est posée entre les segments")
        self.assertAlmostEqual(0.25, float(np.abs(parts[0]).max()), places=2)

    def test_the_lexicon_rewrites_the_text_like_the_whole_rendering(self):
        be = _ToneBackend()
        _, chunks = be.synthesize_stream(text='Il reste 8 Go.', language='fr')
        list(chunks)
        self.assertNotIn('Go', ' '.join(be.said).split())
        self.assertIn('gigaoctets', ' '.join(be.said))

    def test_an_engine_that_streams_hands_its_own_chunks(self):
        class Streaming(_ToneBackend):
            supports_streaming = True

            def process_stream(self, text='', **_):
                self.said.append(text)
                return RATE, iter([np.ones(10, dtype=np.float32), np.ones(20, dtype=np.float32)])
        _, chunks = Streaming().synthesize_stream(text='Bonjour.')
        self.assertEqual([10, 20], [len(c) for c in chunks])


class _FakeAudioStream:
    def __init__(self, parts):
        self.parts, self.closed = list(parts), False

    def __iter__(self):
        return iter(self.parts)

    def close(self):
        self.closed = True


class PhononStreamTest(SimpleTestCase):

    def _backend(self, parts):
        from wama.common.backends.phonon_backend import PhononBackend
        be = PhononBackend()
        be._tts = mock.Mock(sample_rate=24000)
        be._tts.stream.return_value = self.stream = _FakeAudioStream(parts)
        return be

    def test_the_stream_carries_the_file_level_and_frees_the_engine(self):
        be = self._backend([np.full(4, 0.4, dtype=np.float32), np.full(4, 0.9, dtype=np.float32)])
        rate, chunks = be.process_stream(text='Bonjour.', voice_preset='phonon_lucien')
        out = list(chunks)
        self.assertEqual(24000, rate)
        self.assertAlmostEqual(0.4 * be.OUTPUT_GAIN, float(out[0][0]), places=5)
        self.assertEqual(1.0, float(out[1][0]), "le gain écrête à 1, jamais au-delà")
        self.assertEqual('Lucien', be._tts.stream.call_args.kwargs['voice'])
        self.assertTrue(self.stream.closed)
        self.assertFalse(be._lock.locked(), "le moteur reste verrouillé après son flux")

    def test_an_abandoned_stream_stops_the_engine_and_frees_it(self):
        be = self._backend([np.ones(4, dtype=np.float32)] * 3)
        _, chunks = be.process_stream(text='Bonjour.')
        next(chunks)
        chunks.close()                                   # l'appelant raccroche
        self.assertTrue(self.stream.closed)
        self.assertFalse(be._lock.locked())


class ServiceStreamTest(SimpleTestCase):
    """`/tts/stream`, sans modèle ni GPU (gestionnaire de moteurs factice)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import torch
        cls._torch_load = torch.load
        cls._env_weights = os.environ.get('TORCH_FORCE_WEIGHTS_ONLY_LOAD')
        from wama.common.tts import service as tts_service
        cls.s = tts_service

    @classmethod
    def tearDownClass(cls):
        import torch
        torch.load = cls._torch_load
        if cls._env_weights is None:
            os.environ.pop('TORCH_FORCE_WEIGHTS_ONLY_LOAD', None)
        else:
            os.environ['TORCH_FORCE_WEIGHTS_ONLY_LOAD'] = cls._env_weights
        super().tearDownClass()

    def setUp(self):
        self.be = _ToneBackend()
        manager = mock.Mock()
        manager.get_backend.side_effect = lambda e: self.be
        for target, value in (('_manager', manager), ('engine_for_model', lambda m, d=None: m),
                              ('local_model_name', lambda m: m), ('_service_ready', True),
                              ('_current_engine', None), ('_current_model_name', None),
                              ('_engine_lock', threading.Lock())):
            patcher = mock.patch.object(self.s, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(self.s.torch.cuda, 'is_available', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pcm16_streams_and_the_engine_is_free_after(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.s.app)                  # hors `with` : pas de démarrage réel
        reply = client.post('/tts/stream', json={'text': 'Bonjour. Au revoir.', 'model': 'tone',
                                                 'options': {'sentence_pause': 0.2}})
        self.assertEqual(200, reply.status_code, reply.text)
        self.assertEqual(str(RATE), reply.headers['x-sample-rate'])
        self.assertTrue(reply.headers['content-type'].startswith('audio/L16'))
        samples = np.frombuffer(reply.content, dtype='<i2')
        # Deux segments, la pause ENTRE eux (le dernier n'en porte pas, `pause_segments`).
        self.assertEqual(int(RATE * 0.1) * 2 + int(RATE * 0.2), len(samples))
        self.assertAlmostEqual(0.25, samples[0] / 32767, places=3)
        self.assertFalse(self.s._engine_lock.locked(), "moteur verrouillé après le flux")

    def test_an_engine_error_before_the_first_sound_is_an_http_error(self):
        from fastapi.testclient import TestClient
        self.be.process = mock.Mock(side_effect=RuntimeError('moteur en panne'))
        reply = TestClient(self.s.app).post('/tts/stream', json={'text': 'Bonjour.', 'model': 'tone'})
        self.assertEqual(500, reply.status_code)
        self.assertFalse(self.s._engine_lock.locked())


class AssistantStreamViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('assistant_voice_stream', password='x')
        self.client = Client()
        self.client.force_login(self.user)
        voice = {'model': 'huggingface:gradium/phonon-40m-fr', 'voice_preset': 'phonon_noemie',
                 'language': 'fr'}
        patcher = mock.patch('wama.common.tts.assistant_voice.assistant_voice', return_value=voice)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, **data):
        return self.client.post('/api/tts-kokoro/', json.dumps(data),
                                content_type='application/json')

    def test_a_stream_request_gets_pcm_with_its_rate_and_spoken_text(self):
        with mock.patch('wama.common.tts.service_client.tts_stream_via_service',
                        return_value=(24000, iter([b'\x01\x00', b'\x02\x00']))) as service:
            reply = self._post(text='Bonjour à vous.', stream=True)
        self.assertTrue(reply.streaming, "la voix doit partir au fil de l'eau")
        self.assertEqual('audio/L16', reply['Content-Type'])
        self.assertEqual('24000', reply['X-Sample-Rate'])
        from urllib.parse import unquote
        self.assertEqual('Bonjour à vous.', unquote(reply['X-Spoken']))
        self.assertEqual(b'\x01\x00\x02\x00', b''.join(reply.streaming_content))
        self.assertEqual('phonon_noemie', service.call_args.kwargs['voice_preset'])

    def test_a_service_that_cannot_stream_falls_back_to_the_whole_answer(self):
        with mock.patch('wama.common.tts.service_client.tts_stream_via_service',
                        side_effect=RuntimeError('service ancien')), \
                mock.patch('wama.views._tts_via_service', return_value='UklGRg=='):
            reply = self._post(text='Bonjour.', stream=True)
        self.assertFalse(reply.streaming)
        self.assertEqual('UklGRg==', reply.json()['audio_b64'])

    def test_without_the_flag_nothing_changes(self):
        with mock.patch('wama.common.tts.service_client.tts_stream_via_service') as service, \
                mock.patch('wama.views._tts_via_service', return_value='UklGRg=='):
            reply = self._post(text='Bonjour.')
        service.assert_not_called()
        self.assertEqual('UklGRg==', reply.json()['audio_b64'])
