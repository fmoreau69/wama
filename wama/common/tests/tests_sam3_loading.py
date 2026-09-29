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
        fake.Sam3Processor.assert_called_once_with('image-model')
        self.assertEqual('processor', analyzer._processor)
