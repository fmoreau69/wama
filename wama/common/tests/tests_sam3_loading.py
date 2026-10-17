"""SAM3 is loaded in ONE place, from its LOCAL weights (2026-09-27, REMOVAL_LEDGER R75).

The cam_analyzer called `build_sam3_image_model()` bare: the library then resolved `sam3.pt` through
the Hub, in the SHARED cache — where it does not exist (the only copy lives in the model's own
folder, `vision/sam/`). Since 2026-09-07 (the environment preparation that pointed the cache there
was removed) that call could only download 3.4 GB again with the instance token, or fail offline.
Nothing showed it: the SAM3 pass is a chained task, run rarely, on the GPU.

Equivalence of the aligned path was MEASURED, not assumed: on the reference session (camera 27),
9 frames re-analysed with the exact prompts of the stored pass (2026-07-17) gave the same markings,
class and confidence to 3 decimals (script-level probe, GPU, `HF_HUB_OFFLINE=1`).
"""
import ast
import sys
import types
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.tests.tests_unbound_names import project_modules

LOADER_HOME = Path('wama/common/backends/sam3_processor.py')


class Sam3SingleLoaderTest(SimpleTestCase):

    def test_only_the_common_loader_builds_the_sam3_image_model(self):
        callers = []
        for path in project_modules():
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.id if isinstance(f, ast.Name) else getattr(f, 'attr', None)
                    if name == 'build_sam3_image_model':
                        callers.append((path.relative_to(settings.BASE_DIR).as_posix(), node.lineno))
        self.assertEqual([LOADER_HOME.as_posix()], sorted({p for p, _ in callers}),
                         f'SAM3 built outside load_sam3_image_model: {callers}')

    def test_the_loader_gives_the_library_a_local_path_and_never_the_hub(self):
        builder = mock.Mock(return_value='model')
        fake = types.ModuleType('sam3.model_builder')
        fake.build_sam3_image_model = builder
        with mock.patch.dict(sys.modules, {'sam3': types.ModuleType('sam3'), 'sam3.model_builder': fake}), \
                mock.patch('wama.common.utils.hf_weights.poids_locaux', return_value='/weights/snap') as local:
            from wama.common.backends.sam3_processor import load_sam3_image_model
            self.assertEqual('model', load_sam3_image_model())
        self.assertEqual('facebook/sam3', local.call_args.args[0])
        kwargs = builder.call_args.kwargs
        self.assertIs(False, kwargs['load_from_HF'])
        self.assertEqual(Path('/weights/snap/sam3.pt'), Path(kwargs['checkpoint_path']))

    def test_the_cam_analyzer_pipeline_loads_through_it(self):
        """The three entry points of the pipeline (SAM3 pass, test frame, ortho markings) all go
        through `SAM3RoadAnalyzer.load` — which must use the common loader."""
        fake = types.ModuleType('sam3.model.sam3_image_processor')
        fake.Sam3Processor = mock.Mock(return_value='processor')
        stubs = {'sam3': types.ModuleType('sam3'), 'sam3.model': types.ModuleType('sam3.model'),
                 'sam3.model.sam3_image_processor': fake}
        with mock.patch.dict(sys.modules, stubs), \
                mock.patch('wama.common.backends.sam3_processor.load_sam3_image_model',
                           return_value='image-model') as loader:
            from wama_lab.cam_analyzer.utils.sam3_road_analyzer import SAM3RoadAnalyzer
            analyzer = SAM3RoadAnalyzer()
            analyzer.load()
        loader.assert_called_once_with()
        # Le seuil DÉCLARÉ part avec la construction (2026-10-16) — construit nu, le processeur
        # coupait à 0,5 quel que soit `CONFIDENCE_THRESHOLD`.
        from wama_lab.cam_analyzer.utils.sam3_road_analyzer import CONFIDENCE_THRESHOLD
        fake.Sam3Processor.assert_called_once_with('image-model',
                                                   confidence_threshold=CONFIDENCE_THRESHOLD)
        self.assertEqual('processor', analyzer._processor)


def _processor_stubs():
    fake = types.ModuleType('sam3.model.sam3_image_processor')
    fake.Sam3Processor = mock.Mock(return_value='processor')
    return fake, {'sam3': types.ModuleType('sam3'), 'sam3.model': types.ModuleType('sam3.model'),
                  'sam3.model.sam3_image_processor': fake}


class Sam3ThresholdReachesTheLibraryTest(SimpleTestCase):
    """2026-10-16 — `Sam3Processor` TRIE ses sorties avant de les rendre (`keep = out_probs >
    self.confidence_threshold`, défaut 0,5) : construit sans seuil, il ignorait le 0,3 déclaré
    par l'anonymizer comme par le cam_analyzer. Mesuré sur faces_02 : 39 visages à 0,5, 83 à 0,3,
    aucune détection sous 0,502 avant la correction."""

    def test_only_the_common_constructor_builds_the_sam3_processor(self):
        callers = []
        for path in project_modules():
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == 'sam3.model.sam3_image_processor':
                    callers.append(path.relative_to(settings.BASE_DIR).as_posix())
        self.assertEqual([LOADER_HOME.as_posix()], sorted(set(callers)),
                         'Sam3Processor built outside sam3_image_processor')

    def test_the_caller_threshold_is_given_to_the_library(self):
        fake, stubs = _processor_stubs()
        with mock.patch.dict(sys.modules, stubs):
            from wama.common.backends.sam3_processor import sam3_image_processor
            self.assertEqual('processor', sam3_image_processor('model', 0.3))
        fake.Sam3Processor.assert_called_once_with('model', confidence_threshold=0.3)

    def test_the_anonymizer_engine_builds_it_with_its_own_threshold(self):
        fake, stubs = _processor_stubs()
        with mock.patch.dict(sys.modules, stubs), \
                mock.patch('wama.common.backends.sam3_processor.load_sam3_image_model',
                           return_value='image-model'):
            from wama.common.backends.sam3_processor import SAM3Processor
            engine = SAM3Processor()
            engine.load_model('image')
        fake.Sam3Processor.assert_called_once_with('image-model',
                                                   confidence_threshold=engine.confidence_threshold)

    def test_the_cam_analyzer_sets_the_threshold_of_each_call(self):
        """Le diagnostic à seuil 0 (« tous les masks ») ne voyait rien sous 0,5."""
        from wama_lab.cam_analyzer.utils.sam3_road_analyzer import SAM3RoadAnalyzer
        import numpy as np
        analyzer = SAM3RoadAnalyzer(road_fallback=False)
        analyzer._processor = mock.Mock()
        analyzer._processor.set_text_prompt.return_value = {}
        analyzer.analyze_frame(np.zeros((8, 8, 3), dtype=np.uint8), min_confidence=0.0)
        analyzer._processor.set_confidence_threshold.assert_called_once_with(0.0)
