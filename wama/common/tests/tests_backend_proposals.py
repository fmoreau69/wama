"""Backends PROPOSÉS par le rôle `backend` (marche B2, 2026-09-29) — contrôles et geste d'écriture.

La règle « l'agent n'écrit jamais dans wama/ » est levée pour CE geste (décision de Fabien) :
un backend validé par un humain s'écrit dans `wama/common/backends/`. Ces gardes tiennent ce qui
reste de la règle :
  1. les contrôles de FORME refusent ce que l'inventaire ne saurait pas résoudre (SUPPORTED_MODELS
     hors module, moteur faux, méthode du contrat manquante) et les interdits (cache HF, réseau) ;
  2. la résolution SIMULÉE choisit bien ce backend face à un autre du même moteur ;
  3. l'écriture REFAIT les contrôles, n'écrase jamais un module, et ne sort pas d'`outputs/` ;
  4. un rejet ne touche pas au paquet.
Aucun GPU, aucun LLM : le code proposé est écrit ici.
"""
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.common.services import backend_proposals as bp

IMAGE = ('image_generation_base', 'ImageGenerationBackend')
GOOD = '''
"""Backend de test."""
from .image_generation_base import ImageGenerationBackend, GenerationResult

SUPPORTED_MODELS = {"Org/Img-ONNX": {"name": "Img", "description": "t", "vram": "1GB"}}


class ImgOnnxBackend(ImageGenerationBackend):
    ENGINE = "onnxruntime"
    REQUIRED_PACKAGES = ["onnxruntime"]
    name = "img_onnx"
    display_name = "Img ONNX"
    recommended_vram_gb = 1.0

    @classmethod
    def is_available(cls):
        return True

    def load(self, model_name=None):
        from wama.common.utils.model_components import component_paths
        self._paths = component_paths("huggingface:Org/Img-ONNX")
        return True

    def generate(self, params, progress_callback=None):
        return GenerationResult(success=False, error="test")

    def unload(self):
        self._paths = None
'''


class CheckSourceTest(SimpleTestCase):

    def _check(self, code, engine='onnxruntime'):
        return bp.check_source(code, engine=engine, model_id='Org/Img-ONNX', contract=IMAGE)

    def test_a_well_formed_backend_passes(self):
        res = self._check(GOOD)
        self.assertTrue(res['ok'], res['errors'])
        self.assertEqual('ImgOnnxBackend', res['class_name'])

    def test_the_contract_methods_are_derived_from_the_contract_itself(self):
        self.assertEqual({'is_available', 'load', 'generate', 'unload'},
                         bp.required_methods(IMAGE))

    def test_each_defect_is_named(self):
        cases = {
            'SUPPORTED_MODELS absent': GOOD.replace('SUPPORTED_MODELS = {', 'OTHER = {'),
            'ENGINE': GOOD.replace('ENGINE = "onnxruntime"', 'ENGINE = "torch"'),
            'non implémentées': GOOD.replace('def generate(', 'def _generate('),
            'mutation du cache HF': GOOD.replace(
                'return True\n\n    def load', 'import os\n        os.environ["HF_HUB_CACHE"] = "x"'
                '\n        return True\n\n    def load'),
            'téléchargement': GOOD.replace('component_paths("', 'snapshot_download("'),
        }
        for expected, code in cases.items():
            res = self._check(code)
            self.assertFalse(res['ok'], expected)
            self.assertTrue(any(expected in e for e in res['errors']), (expected, res['errors']))

    def test_the_model_id_must_be_declared(self):
        res = bp.check_source(GOOD, engine='onnxruntime', model_id='Org/Other', contract=IMAGE)
        self.assertIn('Org/Other', ' '.join(res['errors']))


class SimulatedResolutionTest(SimpleTestCase):

    def test_the_proposed_backend_wins_its_model_over_the_upscaler_of_the_same_engine(self):
        """`onnxruntime` est déjà revendiqué par AIUpscaler : c'est SUPPORTED_MODELS qui
        départage — sinon l'inventaire rendrait None (indécidable) ou le mauvais."""
        res = bp.simulate_resolution(GOOD, module='img_onnx_backend', engine='onnxruntime',
                                     model_id='Org/Img-ONNX')
        self.assertTrue(res['resolved'], res)
        self.assertTrue(any('ai_upscaler' in r for r in res['rivals']), res['rivals'])


class ApplyGestureTest(SimpleTestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.backends, self.outputs = Path(tmp.name) / 'backends', Path(tmp.name) / 'outputs'
        self.backends.mkdir()
        self.outputs.mkdir()
        for name, path in (('backends_dir', self.backends), ('outputs_dir', self.outputs)):
            p = mock.patch.object(bp, name, return_value=path)
            p.start()
            self.addCleanup(p.stop)

    def _proposal(self, code=GOOD, module='img_onnx_backend'):
        f = self.outputs / 'backend_huggingface_Org_Img-ONNX_2026-09-29_12-00.json'
        f.write_text(json.dumps({'status': 'PENDING_HUMAN_VALIDATION', 'role': 'backend',
                                 'model_key': 'huggingface:Org/Img-ONNX', 'module': module,
                                 'engine': 'onnxruntime', 'contract': list(IMAGE),
                                 'code': code}), encoding='utf-8')
        # Le contrat doit être LISIBLE depuis le dossier simulé (lecture AST des méthodes).
        real = Path(bp.__file__).resolve().parents[1] / 'backends' / 'image_generation_base.py'
        (self.backends / 'image_generation_base.py').write_text(real.read_text(encoding='utf-8'),
                                                                 encoding='utf-8')
        return f.name

    def test_validating_writes_the_module_and_marks_the_proposal(self):
        name = self._proposal()
        self.assertEqual([name], [p['file'] for p in bp.pending()])
        res = bp.apply(name)
        self.assertTrue(res['applied'], res)
        self.assertEqual(GOOD, (self.backends / 'img_onnx_backend.py').read_text(encoding='utf-8'))
        self.assertEqual([], bp.pending())

    def test_the_checks_are_redone_at_writing_time(self):
        """Un fichier d'outputs/ modifié après le rôle ne passe pas pour autant."""
        name = self._proposal(code=GOOD.replace('ENGINE = "onnxruntime"', 'ENGINE = "x"'))
        res = bp.apply(name)
        self.assertFalse(res['applied'])
        self.assertFalse((self.backends / 'img_onnx_backend.py').exists())

    def test_an_existing_module_is_never_overwritten(self):
        (self.backends / 'img_onnx_backend.py').write_text('# existant\n', encoding='utf-8')
        res = bp.apply(self._proposal())
        self.assertFalse(res['applied'])
        self.assertEqual('# existant\n',
                         (self.backends / 'img_onnx_backend.py').read_text(encoding='utf-8'))

    def test_a_module_name_or_a_path_outside_outputs_is_refused(self):
        self.assertFalse(bp.apply(self._proposal(module='../../evil'))['applied'])
        with self.assertRaises(FileNotFoundError):
            bp.apply('../../settings.py')

    def test_rejecting_writes_nothing_in_the_package(self):
        name = self._proposal()
        self.assertTrue(bp.reject(name))
        self.assertFalse((self.backends / 'img_onnx_backend.py').exists())
        self.assertEqual([], bp.pending())


class ComponentPathsTest(TestCase):
    """La brique que tout backend généré appelle : une CLÉ → les fichiers de ses composants
    DÉCLARÉS, dans la révision que désigne `refs/main`. Un manque se DIT, avec son rôle."""

    def setUp(self):
        from wama.model_manager.models import AIModel
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / 'models--Org--Img-ONNX'
        for rev in ('old', 'pinned'):
            (self.repo / 'snapshots' / rev / 'dit').mkdir(parents=True)
            (self.repo / 'snapshots' / rev / 'dit' / 'model.onnx').write_bytes(b'x')
        (self.repo / 'refs').mkdir()
        (self.repo / 'refs' / 'main').write_text('pinned\n', encoding='utf-8')
        self.row = AIModel.objects.create(
            model_key='huggingface:Org/Img-ONNX', name='Img', model_type='diffusion',
            source='huggingface', is_downloaded=True, local_path=str(self.repo),
            composition={'components': [{'role': 'dit', 'pattern': 'dit/model.onnx',
                                         'format': 'onnx'}],
                         'runtime': {'engine': 'onnxruntime'}})

    def test_the_declared_component_is_found_in_the_pinned_revision(self):
        from wama.common.utils.model_components import component_paths
        paths = component_paths('huggingface:Org/Img-ONNX')
        self.assertEqual(self.repo / 'snapshots' / 'pinned' / 'dit' / 'model.onnx', paths['dit'])

    def test_a_missing_component_or_anatomy_is_said_with_its_role(self):
        from wama.common.utils.model_components import ComponentsUnavailable, component_paths
        self.row.composition = {'components': [{'role': 'vae', 'pattern': 'vae/*.onnx'}]}
        self.row.save()
        with self.assertRaisesRegex(ComponentsUnavailable, 'vae'):
            component_paths('huggingface:Org/Img-ONNX')
        self.row.composition = {}
        self.row.save()
        with self.assertRaisesRegex(ComponentsUnavailable, 'anatomie'):
            component_paths('huggingface:Org/Img-ONNX')


class OnnxProvidersTest(SimpleTestCase):

    def test_cpu_only_never_offers_a_gpu_and_cpu_is_always_the_fallback(self):
        from wama.common.utils.onnx_utils import onnx_providers
        self.assertEqual(['CPUExecutionProvider'], onnx_providers(cpu_only=True))
        with mock.patch('onnxruntime.get_available_providers',
                        return_value=['CUDAExecutionProvider', 'CPUExecutionProvider']):
            self.assertEqual([('CUDAExecutionProvider', {'device_id': 0}), 'CPUExecutionProvider'],
                             onnx_providers())
