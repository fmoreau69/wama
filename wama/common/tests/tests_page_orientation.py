"""L'orientation de page passe par le contrat commun (2026-11-07) — et docTR garde son prédicteur.

Le classifieur d'orientation de docTR était chargé par `ocr_base` lui-même (`loaded_by`), dans une
liste de module ; `DocTRBackend.load()` ne chargeait rien et annonçait 2 Go de VRAM pour un modèle
sur le processeur. ⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
import sys
import types
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.common.backends import ocr_base

ORIENTATION = ocr_base.PAGE_ORIENTATION_KEY


class PageOrientationThroughTheCommonContractTest(TestCase):

    def setUp(self):
        from wama.model_manager.models import AIModel
        for key, task in ((ORIENTATION, 'page-orientation'), ('reader:doctr', 'ocr')):
            AIModel.objects.create(model_key=key, name=key, model_type='vision',
                                   source=key.split(':')[0], is_downloaded=True,
                                   capabilities={'task': task},
                                   composition={'runtime': {'engine': 'doctr'}})

    def test_one_engine_two_backends_each_model_its_own(self):
        from wama.common.backends.doctr_backend import DocTRBackend
        from wama.common.backends.doctr_orientation_backend import DocTROrientationBackend
        from wama.common.backends.manager import backend_for_key
        self.assertIs(DocTROrientationBackend, backend_for_key(ORIENTATION))
        self.assertIs(DocTRBackend, backend_for_key('reader:doctr'))

    def test_the_straightening_gets_its_backend_from_the_common_gate(self):
        """Une instance à elle, gardée par le cache commun, à côté de celle qui lit."""
        from wama.common.backends.doctr_orientation_backend import DocTROrientationBackend
        from wama.common.backends.manager import backend_instance_for_key
        with mock.patch.object(ocr_base, 'page_orientation_installed', return_value=True), \
                mock.patch.object(DocTROrientationBackend, 'load', return_value=True) as load:
            first, second = ocr_base._orientation_backend(), ocr_base._orientation_backend()
        self.assertIsInstance(first, DocTROrientationBackend)
        self.assertIs(first, second)
        load.assert_called_with(ORIENTATION)
        self.assertIsNot(first, backend_instance_for_key('reader:doctr'))

    def test_an_absent_classifier_leaves_the_page_untouched(self):
        """Le redressement est un confort : non installé, rien n'est chargé ni téléchargé."""
        from wama.common.backends.manager import backend_instance_for_key
        with mock.patch.object(ocr_base, 'page_orientation_installed', return_value=False), \
                mock.patch('wama.common.backends.manager.backend_instance_for_key',
                           wraps=backend_instance_for_key) as gate:
            self.assertIsNone(ocr_base._orientation_backend())
        gate.assert_not_called()

    def test_the_contract_and_the_placement(self):
        from wama.common.backends.doctr_backend import DocTRBackend
        from wama.common.backends.doctr_orientation_backend import DocTROrientationBackend
        from wama.common.backends.manager import _work_method
        self.assertEqual('page_orientation', _work_method(DocTROrientationBackend))
        for cls in (DocTROrientationBackend, DocTRBackend):
            with self.subTest(backend=cls.__name__):
                self.assertEqual(('cpu', 0), (cls.device, cls.recommended_vram_gb),
                                 'processeur : rien à publier au gouverneur')

    def test_the_manifest_requires_the_library_of_its_backend(self):
        from wama.common.manifests.builtin.model import _requires_librairies
        body = {'composition': {'runtime': {'engine': 'doctr'}},
                'capabilities': {'task': 'page-orientation'}}
        self.assertEqual([{'kind': 'library', 'key': 'python-doctr'}],
                         _requires_librairies(body, ORIENTATION))

    def test_the_discovery_retracts_the_loader_it_used_to_name(self):
        from wama.model_manager.services.model_sync import merged_composition
        from wama.model_manager.tests.tests_model_loaded_by import _registry
        r = _registry()
        r._discover_page_orientation_models()
        discovered = r._models[ORIENTATION].composition
        prior = {'runtime': {'engine': 'doctr', 'loaded_by': 'wama.common.backends.ocr_base'}}
        merged = merged_composition(prior, discovered)
        self.assertEqual({'engine': 'doctr'}, merged['runtime'])


class TheLiteralDeclarationsAgreeTest(SimpleTestCase):
    """Les listes des deux backends de docTR sont des LITTÉRAUX (lus par AST) : elles redisent les
    clés que leurs modules déclarent, qui font foi."""

    def test_each_listed_model_is_the_key_its_module_names(self):
        from wama.common.backends.doctr_backend import DOCTR_KEY, DocTRBackend
        from wama.common.backends.doctr_orientation_backend import DocTROrientationBackend
        from wama.common.utils.model_keys import backend_model_id
        self.assertEqual({backend_model_id(ORIENTATION): {'model_key': ORIENTATION}},
                         DocTROrientationBackend.SUPPORTED_MODELS)
        self.assertEqual({backend_model_id(DOCTR_KEY): {'model_key': DOCTR_KEY}},
                         DocTRBackend.SUPPORTED_MODELS)
        self.assertEqual(DocTRBackend.ENGINE, DocTROrientationBackend.ENGINE)


class _FakePredictor:
    built = 0

    def __init__(self, **kwargs):
        type(self).built += 1

    def __call__(self, doc):
        return types.SimpleNamespace(pages=[])


class DocTRKeepsItsPredictorTest(SimpleTestCase):
    """`load()` construit le prédicteur une fois ; deux lectures ne le reconstruisent pas."""

    def test_two_reads_build_the_predictor_once(self):
        from wama.common.backends import doctr_backend
        _FakePredictor.built = 0
        fake_doctr = {
            'doctr': types.ModuleType('doctr'),
            'doctr.models': types.SimpleNamespace(ocr_predictor=_FakePredictor),
            'doctr.io': types.SimpleNamespace(DocumentFile=types.SimpleNamespace(
                from_images=lambda paths: paths)),
        }
        backend = doctr_backend.DocTRBackend()
        with mock.patch.dict(sys.modules, fake_doctr), \
                mock.patch.object(doctr_backend, 'doctr_installed', return_value=True), \
                mock.patch('PIL.Image.open') as image_open:
            image_open.return_value.__enter__.return_value = types.SimpleNamespace(width=400,
                                                                                 height=400)
            with mock.patch.object(doctr_backend.DocTRBackend, '_ensure_min_size',
                                   side_effect=lambda path: path):
                self.assertTrue(backend.load('doctr'))
                backend.run('page.png')
                backend.run('page.png')
        self.assertEqual(1, _FakePredictor.built)
        self.assertTrue(backend.is_loaded)
        backend.unload()
        self.assertFalse(backend.is_loaded)


FAKE_ORIENTATION = '''
from .page_orientation_base import PageOrientationBackend


class FakeOrientation(PageOrientationBackend):
    def load(self, model=None):
        self._loaded = True
        return True

    def unload(self):
        self._loaded = False

    def page_orientation(self, image):
        return __ANSWER__
'''


class OrientationSmokeTest(SimpleTestCase):
    """L'essai du contrat (`backend_proposals.SMOKES`) : un classifieur proposé par le rôle
    `backend` doit REDRESSER une page de texte tournée d'un quart de tour."""

    def _smoke(self, answer):
        from wama.common.services.backend_proposals import SMOKES
        return SMOKES['PageOrientationBackend'](
            FAKE_ORIENTATION.replace('__ANSWER__', repr(answer)), module='fake_orientation_backend',
            model_key='github:org/fake-orientation:v1', out_dir=None)

    def test_the_angle_that_straightens_the_page_passes(self):
        out = self._smoke((270, 0.99))
        self.assertTrue(out['ok'], out)

    def test_a_wrong_angle_or_an_answer_outside_the_contract_fails(self):
        self.assertIn('ne revient pas droite', self._smoke((90, 0.99))['error'])
        self.assertIn('hors contrat', self._smoke((-90, 0.99))['error'])
