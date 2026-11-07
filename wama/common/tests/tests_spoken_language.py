"""Langues parlées d'un audio (`utils/spoken_language.py`) et leur étiquetage par Whisper.

⚠ Identifiants en anglais ; commentaires et docstrings en français. Aucun modèle chargé.
"""
from unittest import mock

import numpy as np
from django.test import SimpleTestCase, TestCase

from wama.common.backends.speech_to_text_base import TranscriptionSegment
from wama.common.utils.spoken_language import (
    dominant_language, language_agreement, language_shares, languages_heard,
)


class LanguageAgreementTest(SimpleTestCase):
    REFERENCE = [{'start_time': 0.0, 'end_time': 10.0, 'language': 'en'},
                 {'start_time': 10.0, 'end_time': 20.0, 'language': 'fr'}]

    def test_time_in_the_right_language_is_agreement_the_rest_only_coverage(self):
        """Un seul segment « fr » sur 0-20 s : la moitié française est juste, l'anglaise non."""
        hypothesis = [{'start_time': 0.0, 'end_time': 20.0, 'language': 'fr'}]
        self.assertEqual({'agreement': 0.5, 'covered': 1.0},
                         language_agreement(self.REFERENCE, hypothesis))

    def test_what_is_not_transcribed_is_not_covered(self):
        hypothesis = [TranscriptionSegment('', 12.0, 20.0, 'x', language='fr')]
        self.assertEqual({'agreement': 0.4, 'covered': 0.4},
                         language_agreement(self.REFERENCE, hypothesis))

    def test_a_reference_without_languages_has_no_agreement(self):
        self.assertEqual({'agreement': None, 'covered': None},
                         language_agreement([{'start_time': 0, 'end_time': 5}], []))


class ProbeWindowsTest(SimpleTestCase):
    """La sonde écoute par fenêtres de 10 s (une phrase), pas 30 s (FLEURS-CS, 2026-09-29)."""

    def test_a_five_minute_file_is_heard_in_24_ten_second_windows_spread_over_it(self):
        from wama.common.utils import spoken_language
        windows = []

        def decode(path, target_sr, start_s, duration_s):
            windows.append((start_s, duration_s))
            return np.zeros(16000, dtype=np.float32), 16000
        with mock.patch('wama.common.utils.audio_decode.decode_window', side_effect=decode), \
                mock.patch.object(spoken_language, '_identifier') as identifier:
            identifier.return_value.identify_language.return_value = ('fr', 0.9)
            heard = spoken_language.probe_languages('x.wav', 300.0)
        self.assertEqual(24, len(heard))
        self.assertTrue(all(d == 10 for _, d in windows))
        self.assertLess(windows[0][0], 10)
        self.assertGreater(windows[-1][0], 280)


class LanguagesHeardTest(SimpleTestCase):

    def test_only_confident_windows_vote_and_the_most_frequent_comes_first(self):
        probe = [('fr', 0.9), ('en', 0.8), ('fr', 0.95), ('de', 0.4), ('en', 0.85)]
        self.assertEqual(['fr', 'en'], languages_heard(probe))

    def test_one_stray_window_is_not_a_second_language(self):
        """`012c_EBPZ` (réunion toute française) : une fenêtre sortie « es » avec assurance."""
        self.assertEqual(['fr'], languages_heard([('fr', 0.9)] * 22 + [('es', 0.8)]))

    def test_a_one_window_probe_keeps_its_language(self):
        self.assertEqual(['fr'], languages_heard([('fr', 0.9)]))

    def test_a_silent_probe_hears_nothing(self):
        self.assertEqual([], languages_heard([('en', 0.3)]))


class DominantLanguageTest(SimpleTestCase):

    def test_the_most_spoken_language_wins_not_the_first_one(self):
        segments = [TranscriptionSegment('', 0.0, 5.0, 'intro', language='en'),
                    {'start_time': 5.0, 'end_time': 60.0, 'text': 'suite', 'language': 'fr'}]
        self.assertEqual({'en': 5.0, 'fr': 55.0}, language_shares(segments))
        self.assertEqual('fr', dominant_language(segments))

    def test_segments_without_language_leave_the_fallback(self):
        self.assertEqual('fr', dominant_language([TranscriptionSegment('', 0, 1, 'x')], 'fr'))


class WhisperWindowLanguagesTest(SimpleTestCase):
    """Whisper multilingue : chaque segment prend la langue de SA fenêtre de 30 s."""

    def _backend(self, by_window):
        from wama.common.backends.whisper_backend import WhisperBackend
        backend = WhisperBackend.__new__(WhisperBackend)
        calls = []

        def detect_language(audio):
            calls.append(int(audio[0]))
            return by_window[int(audio[0])], 0.9, []
        backend._model = mock.Mock(detect_language=detect_language)
        return backend, calls

    def test_each_segment_takes_the_language_of_its_window_detected_once(self):
        backend, calls = self._backend({0: 'fr', 2: 'en'})
        segments = [TranscriptionSegment('', 1.0, 4.0, 'a'), TranscriptionSegment('', 10.0, 20.0, 'b'),
                    TranscriptionSegment('', 61.0, 65.0, 'c')]
        # La fenêtre décodée porte son index en 1ᵉʳ échantillon : le faux modèle le lit.
        fake_window = lambda path, start_s, duration_s: (np.array([start_s // 30], dtype=np.float32), 16000)
        with mock.patch('wama.common.utils.audio_decode.decode_window', side_effect=fake_window):
            backend._label_window_languages('x.wav', segments, 'fr')
        self.assertEqual(['fr', 'fr', 'en'], [s.language for s in segments])
        self.assertEqual([0, 2], sorted(calls), 'une détection par fenêtre, pas par segment')

    def test_an_unreadable_window_falls_back_to_the_global_language(self):
        backend, _ = self._backend({})
        segments = [TranscriptionSegment('', 1.0, 2.0, 'a')]
        with mock.patch('wama.common.utils.audio_decode.decode_window',
                        side_effect=RuntimeError('ffmpeg')):
            backend._label_window_languages('x.wav', segments, 'de')
        self.assertEqual('de', segments[0].language)


TINY = 'huggingface:Systran/faster-whisper-tiny'


class ProbeThroughTheCommonContractTest(TestCase):
    """La sonde passe par la porte commune (2026-11-06) : Whisper tiny est servi par le backend du
    contrat `language-identification`, résolu par son moteur et sa tâche comme tout modèle — plus
    par un singleton de module qui construisait `WhisperModel` lui-même (`loaded_by`)."""

    def setUp(self):
        from wama.model_manager.models import AIModel
        for key, task in ((TINY, 'language-identification'), ('transcriber:whisper', 'transcription')):
            AIModel.objects.create(model_key=key, name=key, model_type='speech',
                                   source=key.split(':')[0], is_downloaded=True,
                                   capabilities={'task': task},
                                   composition={'runtime': {'engine': 'faster-whisper'}})

    def test_one_engine_two_backends_each_model_its_own(self):
        from wama.common.backends.manager import backend_for_key
        from wama.common.backends.whisper_backend import WhisperBackend
        from wama.common.backends.whisper_language_backend import WhisperLanguageBackend
        self.assertIs(WhisperLanguageBackend, backend_for_key(TINY))
        self.assertIs(WhisperBackend, backend_for_key('transcriber:whisper'))

    def test_the_probe_gets_its_backend_from_the_common_gate_beside_the_transcriber(self):
        """L'instance de la sonde n'est pas celle qui transcrit : le cache commun en garde une par
        CLASSE, et un `load('tiny')` de celle de large-v3 la déchargerait."""
        from wama.common.backends.manager import backend_instance_for_key
        from wama.common.backends.whisper_language_backend import WhisperLanguageBackend
        from wama.common.utils import spoken_language
        with mock.patch.object(WhisperLanguageBackend, 'load', return_value=True) as load:
            first, second = spoken_language._identifier(), spoken_language._identifier()
        self.assertIsInstance(first, WhisperLanguageBackend)
        self.assertIs(first, second, 'gardé chargé par le cache commun')
        load.assert_called_with(TINY)
        self.assertIsNot(first, backend_instance_for_key('transcriber:whisper'))

    def test_the_contract_work_method_is_identify_language(self):
        from wama.common.backends.manager import _work_method
        from wama.common.backends.whisper_language_backend import WhisperLanguageBackend
        self.assertEqual('identify_language', _work_method(WhisperLanguageBackend))
        self.assertEqual(0, WhisperLanguageBackend.recommended_vram_gb,
                         'processeur : rien à publier au gouverneur')

    def test_the_manifest_requires_the_library_of_its_backend(self):
        from wama.common.manifests.builtin.model import _requires_librairies
        body = {'composition': {'runtime': {'engine': 'faster-whisper'}},
                'capabilities': {'task': 'language-identification'}}
        self.assertEqual([{'kind': 'library', 'key': 'faster-whisper'}],
                         _requires_librairies(body, TINY))

    def test_the_discovery_retracts_the_loader_it_used_to_name(self):
        """Émis à None, `loaded_by` est RETIRÉ par la synchro (`merged_composition`) : son silence
        l'aurait laissé au catalogue, et la ligne serait restée hors de son backend."""
        from wama.model_manager.services.model_sync import merged_composition
        from wama.model_manager.tests.tests_model_loaded_by import _registry
        r = _registry()
        r._discover_language_identification_models()
        discovered = r._models[TINY].composition
        prior = {'runtime': {'engine': 'faster-whisper',
                             'loaded_by': 'wama.common.utils.spoken_language'}}
        self.assertEqual({'runtime': {'engine': 'faster-whisper'}},
                         merged_composition(prior, discovered))


class TheEngineDeclarationsAgreeTest(SimpleTestCase):
    """Les listes des deux backends de faster-whisper sont des LITTÉRAUX (l'inventaire les lit par
    AST, sans importer) : elles redisent la déclaration du moteur, qui fait foi."""

    def test_each_listed_model_is_a_declared_size_of_the_engine(self):
        from wama.common.backends.whisper_backend import (
            DEFAULT_WHISPER_MODEL, WHISPER_REPOS, WhisperBackend)
        from wama.common.backends.whisper_language_backend import WhisperLanguageBackend
        self.assertEqual(DEFAULT_WHISPER_MODEL, WhisperBackend.SUPPORTED_MODELS['whisper']['size'])
        for model_id, spec in WhisperLanguageBackend.SUPPORTED_MODELS.items():
            with self.subTest(model=model_id):
                repo = WHISPER_REPOS[spec['size']]['repo']
                self.assertEqual(repo, model_id)
                self.assertEqual(f'huggingface:{repo}', spec['model_key'])
        self.assertEqual(WhisperBackend.ENGINE, WhisperLanguageBackend.ENGINE)

    def test_the_line_of_the_catalogue_names_the_engine_of_its_backend(self):
        """La découverte écrit le moteur de la ligne (le modèle le porte, la classe ne s'importe pas
        par son chemin) : ce littéral doit rester celui du moteur."""
        from wama.common.backends.whisper_backend import WhisperBackend
        from wama.model_manager.tests.tests_model_loaded_by import _registry
        r = _registry()
        r._discover_language_identification_models()
        self.assertEqual(WhisperBackend.ENGINE, r._models[TINY].composition['runtime']['engine'])


FAKE_IDENTIFIER = '''
from .language_identification_base import LanguageIdentificationBackend


class FakeIdentifier(LanguageIdentificationBackend):
    def load(self, model=None):
        self._loaded = True
        return True

    def unload(self):
        self._loaded = False

    def identify_language(self, audio):
        return __ANSWER__
'''


class LanguageSmokeTest(SimpleTestCase):
    """L'essai du contrat (`backend_proposals.SMOKES`) : un identificateur que propose le rôle
    `backend` est éprouvé sur l'extrait de parole réelle du smoke de PAROLE."""

    def _smoke(self, answer, declared='fr'):
        from types import SimpleNamespace
        from wama.common.services import backend_proposals
        clip = SimpleNamespace(attributes={'language': declared}, file=SimpleNamespace(path='x.wav'))
        with mock.patch.object(backend_proposals, 'smoke_speech_clip', return_value=(clip, None)),                 mock.patch('wama.common.utils.audio_decode.decode_window',
                           return_value=(np.zeros(16000, dtype=np.float32), 16000)):
            return backend_proposals.SMOKES['LanguageIdentificationBackend'](
                FAKE_IDENTIFIER.replace('__ANSWER__', repr(answer)),
                module='fake_language_backend', model_key='huggingface:org/fake-lid',
                out_dir=None)

    def test_the_declared_language_passes(self):
        out = self._smoke(('fr', 0.9))
        self.assertTrue(out['ok'], out)

    def test_another_language_or_an_answer_outside_the_contract_fails(self):
        self.assertIn('déclaré', self._smoke(('en', 0.9))['error'])
        self.assertIn('hors contrat', self._smoke(('french', 0.9))['error'])
