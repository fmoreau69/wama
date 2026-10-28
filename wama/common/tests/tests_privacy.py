"""The common PRIVACY brick (ROADMAP §16.4bis, 2026-10-28) — detect personal data in a text, then
occult it with a bracketed label, conserving everything else.

What is held here : the language engine never downloads a spaCy model ; the pattern detectors (and
the French identifiers with their check keys) find what they must and refuse a wrong key ;
overlapping passages become one, seen by all the detectors that saw it ; the occultation label
follows the language ; a human correction (by `span`) is applied before occulting, without
re-detecting ; the client falls back to the in-process engine when the service is down but REFUSES
on a timeout (a privacy filter never answers « nothing found » for not having looked) ; every
installed detector maps only into the common vocabulary. The real models are exercised when
installed.
"""
from unittest import mock, skipUnless

from django.test import SimpleTestCase

PATTERNS_ONLY = ()      # `detectors=()` : the union without any model — patterns alone.


def _nir(body: str) -> str:
    """A NIR with its valid key (97 − body mod 97)."""
    return f"{body}{97 - int(body) % 97:02d}"


def _luhn_complete(prefix: str) -> str:
    """`prefix` + the digit that makes it Luhn-valid."""
    from wama.common.privacy.recognizers import _luhn
    return next(prefix + str(d) for d in range(10) if _luhn(prefix + str(d)))


def _spans(doc):
    return [(d['label'], d['span']) for f in doc['frames'] for d in f['d']]


class LanguageEngineTest(SimpleTestCase):

    def test_the_blank_engine_never_downloads_a_model(self):
        from wama.common.privacy.recognizers import BlankNlpEngine
        with mock.patch('spacy.cli.download', side_effect=AssertionError('download attempted')):
            engine = BlankNlpEngine(['fr', 'en'])
            engine.load()
            artifacts = engine.process_text('Bonjour Marie', 'fr')
        self.assertEqual(['Bonjour', 'Marie'], [t.text for t in artifacts.tokens])
        self.assertEqual([], engine.get_supported_entities())


class PatternDetectionTest(SimpleTestCase):

    def _detect(self, text, language='fr'):
        from wama.common.privacy import engine
        return engine.detect(text, language, detectors=PATTERNS_ONLY)

    def test_contact_and_bank_data_are_found_offline(self):
        text = 'Écrire à anne.leroy@exemple.fr, IBAN FR76 3000 6000 0112 3456 7890 189.'
        from wama.common.privacy.recognizers import OfflineEmailRecognizer
        labels = {label for label, _ in _spans(self._detect(text))}
        self.assertTrue({'EMAIL_ADDRESS', 'IBAN_CODE'} <= labels, labels)
        # Offline : the extractor used carries no suffix-list URL (the bundled list only).
        self.assertEqual((), OfflineEmailRecognizer._extractor.suffix_list_urls)

    def test_a_french_nir_siren_and_siret_with_valid_keys_are_found(self):
        nir, siren = _nir('1840369123456'), _luhn_complete('73282932')
        siret = _luhn_complete(siren + '0001')
        doc = self._detect(f'NIR {nir}, SIREN {siren}, SIRET {siret}.')
        labels = [label for label, _ in _spans(doc)]
        for expected in ('FR_NIR', 'FR_SIREN', 'FR_SIRET'):
            self.assertIn(expected, labels)

    def test_a_wrong_check_key_is_refused(self):
        """Counter-proof : the same shapes with a broken key are not identifiers."""
        from wama.common.privacy.recognizers import FrNirRecognizer, FrSirenRecognizer
        good = _nir('1840369123456')
        bad = good[:-2] + f'{(int(good[-2:]) + 1) % 97:02d}'
        self.assertTrue(FrNirRecognizer('fr').validate_result(good))
        self.assertFalse(FrNirRecognizer('fr').validate_result(bad))
        siren = _luhn_complete('73282932')
        self.assertFalse(FrSirenRecognizer('fr').validate_result(siren[:-1] + str((int(siren[-1]) + 1) % 10)))

    def test_corsican_departments_count_as_19_and_18(self):
        from wama.common.privacy.recognizers import FrNirRecognizer
        body = '184032A123456'          # sex 1, 1984, March, department 2A, commune, order
        key = 97 - int(body.replace('2A', '19')) % 97
        self.assertTrue(FrNirRecognizer('fr').validate_result(f'{body}{key:02d}'))


class MergeAndOccultTest(SimpleTestCase):

    def test_overlapping_passages_become_one_seen_by_all(self):
        from presidio_analyzer import RecognizerResult
        from wama.common.privacy.engine import _merge

        def result(start, end, entity, score, name):
            return RecognizerResult(entity, start, end, score,
                                    recognition_metadata={'recognizer_name': name})

        merged = _merge([result(0, 9, 'PHONE_NUMBER', 0.4, 'phone'),
                         result(0, 11, 'FR_SIREN', 1.0, 'siren'),
                         result(20, 25, 'PERSON', 0.9, 'model')])
        self.assertEqual([(0, 11, 'FR_SIREN'), (20, 25, 'PERSON')],
                         [(s['start'], s['end'], s['entity']) for s in merged])
        self.assertEqual({'phone', 'siren'}, merged[0]['sources'])

    def test_the_label_follows_the_language(self):
        from wama.common.privacy.engine import occult_segment
        spans = [{'label': 'PERSON', 'span': [0, 4], 'conf': 0.9}]
        self.assertEqual('[PERSONNE] viendra.', occult_segment('Anne viendra.', spans, 'fr'))
        self.assertEqual('[PERSON] will come.', occult_segment('Anne will come.', spans, 'en'))

    def test_a_human_correction_is_occulted_without_detecting_again(self):
        from wama.common.privacy import engine
        from wama.common.utils import detections
        text = 'Contact : Paul Girard, paul@exemple.fr'
        doc = engine.detect(text, 'fr', detectors=PATTERNS_ONLY)
        fixed = detections.apply_corrections(doc, {
            'added': [{'i': 0, 'span': [10, 21], 'label': 'PERSON'}],
            'removed': [{'i': 0, 'span': [23, 38]}]})
        with mock.patch.object(engine, '_detect_one', side_effect=AssertionError('re-detected')):
            out = engine.occult(text, fixed, 'fr')
        self.assertEqual('Contact : [PERSONNE], paul@exemple.fr', out)

    def test_an_image_correction_still_works_by_box(self):
        """Counter-proof : the box documents of the image anonymizer are unchanged."""
        from wama.common.utils import detections
        doc = detections.new_document(media='image', width=10, height=10)
        detections.add(doc, 0, [detections.detection(box=[0, 0, 5, 5], label='face')])
        fixed = detections.apply_corrections(doc, {'removed': [{'i': 0, 'box': [0, 0, 5, 5]}]})
        self.assertEqual(0, detections.count(fixed))


class UnavailableDetectorTest(SimpleTestCase):

    def test_a_detector_that_cannot_load_is_named_and_the_analyzer_not_kept(self):
        """A filter that loses a detector loses recall : never silently."""
        from wama.common.privacy import engine
        engine._analyzers.clear()
        with mock.patch('wama.common.backends.manager.backend_instance_for_key',
                        side_effect=RuntimeError('not served')):
            doc = engine.detect('Anne Martin', 'fr', detectors=('huggingface:org/absent',))
        self.assertEqual(['huggingface:org/absent'], doc['unavailable'])
        self.assertEqual([], doc['models'])
        self.assertNotIn(('fr', ('huggingface:org/absent',)), engine._analyzers)


class ClientTest(SimpleTestCase):

    def test_a_service_that_is_down_falls_back_on_the_same_engine(self):
        import requests
        from wama.common.privacy import service_client
        with mock.patch('requests.post', side_effect=requests.ConnectionError), \
                mock.patch.object(service_client.engine, 'detect_segments',
                                  return_value={'kind': 'detections'}) as local:
            self.assertEqual('detections', service_client.detect('x', 'fr')['kind'])
        local.assert_called_once()

    def test_a_timeout_is_an_error_never_an_empty_answer(self):
        import requests
        from wama.common.privacy import service_client
        with mock.patch('requests.post', side_effect=requests.Timeout):
            with self.assertRaises(service_client.PrivacyUnavailable):
                service_client.detect('Anne Martin', 'fr')


class ServiceTest(SimpleTestCase):

    def test_detect_answers_a_document_and_health_lists_the_detectors(self):
        from fastapi.testclient import TestClient
        from wama.common.privacy import service
        api = TestClient(service.app)
        with mock.patch.object(service.engine, 'installed_detectors', return_value=[('k', ['fr'])]):
            self.assertEqual(['k'], api.get('/health').json()['detectors'])
        doc = api.post('/detect', json={'segments': ['écrire à a.b@exemple.fr'], 'language': 'fr',
                                        'detectors': []}).json()
        self.assertEqual('text', doc['media'])
        self.assertIn('EMAIL_ADDRESS', [label for label, _ in _spans(doc)])


class DetectorDeclarationTest(SimpleTestCase):

    def test_every_detector_maps_into_the_common_vocabulary_and_pins_its_files(self):
        from wama.common.backends import bardsai_pii_backend, gliner2_pii_backend
        from wama.common.privacy.entities import ENTITY_TYPES
        for module, files in ((bardsai_pii_backend, bardsai_pii_backend.BARDSAI_FILES),
                              (gliner2_pii_backend, gliner2_pii_backend.GLINER2_FILES)):
            backend = [c for c in vars(module).values() if isinstance(c, type)
                       and getattr(c, 'ENTITY_MAP', None) and c.__module__ == module.__name__][0]
            self.assertTrue(set(backend.ENTITY_MAP.values()) <= set(ENTITY_TYPES), module.__name__)
            for f in files:
                self.assertEqual(64, len(f['sha256']))
                self.assertEqual(module.HF_REVISION, f['origin']['revision'])


def _installed(module) -> bool:
    try:
        return __import__(f'wama.common.backends.{module}', fromlist=['x']).model_installed()
    except Exception:
        return False


@skipUnless(_installed('bardsai_pii_backend') and _installed('gliner2_pii_backend'),
            'modèles pii-detection non installés')
class RealUnionTest(SimpleTestCase):

    def test_the_union_finds_and_occults_french_and_english_personal_data(self):
        """The real models, without the catalogue (absent from the test base) : the backends are
        handed to the union directly — the catalogue path is held by the other tests."""
        from wama.common.backends.bardsai_pii_backend import MODEL_KEY as BARDSAI, BardsaiPIIBackend
        from wama.common.backends.gliner2_pii_backend import MODEL_KEY as GLINER2, Gliner2PIIBackend
        from wama.common.privacy import engine
        engine._analyzers.clear()
        backends = {BARDSAI: BardsaiPIIBackend(), GLINER2: Gliner2PIIBackend()}
        with mock.patch('wama.common.backends.manager.backend_instance_for_key',
                        side_effect=lambda key: backends[key]):
            fr = 'Madame Claire Martin habite 14 rue des Lilas, 69003 Lyon.'
            doc = engine.detect(fr, 'fr', detectors=(BARDSAI, GLINER2))
            en = 'Dr. Robert Brown lives at 221B Baker Street, London.'
            out_en = engine.occult(en, engine.detect(en, 'en', detectors=(BARDSAI, GLINER2)))
        engine._analyzers.clear()
        self.assertEqual([], doc['unavailable'])
        out = engine.occult(fr, doc)
        self.assertNotIn('Claire Martin', out)
        self.assertIn('[PERSONNE]', out)
        self.assertIn('[PERSON]', out_en)
        self.assertNotIn('Robert Brown', out_en)
