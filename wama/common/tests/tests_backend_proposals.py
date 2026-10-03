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


def _generating(images_expr):
    """A proposed backend whose `generate` returns `images_expr` (evaluated with `params`)."""
    return GOOD.replace(
        'return GenerationResult(success=False, error="test")',
        'from PIL import Image\n'
        '        return GenerationResult(success=True, images=' + images_expr + ')')


class SmokeContractTest(SimpleTestCase):
    """The smoke asks for TWO images and requires two DISTINCT ones (2026-09-30): the two backends
    proposed for Supra2-IMG passed a one-image smoke while one ignored `num_images` and the other
    returned identical images."""

    def _smoke(self, code):
        with tempfile.TemporaryDirectory() as out, \
                mock.patch('wama.common.utils.model_components.component_paths', return_value={}), \
                mock.patch.object(bp, 'settings', mock.Mock(BASE_DIR=Path(out))):
            return bp.smoke(code, module='img_onnx_smoke', model_key='huggingface:Org/Img-ONNX',
                            contract=IMAGE, out_dir=Path(out))

    def test_distinct_images_pass(self):
        res = self._smoke(_generating(
            '[Image.new("RGB", (8, 8), (i * 60, 0, 0)) for i in range(params.num_images)]'))
        self.assertTrue(res['ok'], res)

    def test_ignoring_num_images_fails(self):
        res = self._smoke(_generating('[Image.new("RGB", (8, 8))]'))
        self.assertFalse(res['ok'])
        self.assertIn('num_images', res['error'])

    def test_identical_images_fail(self):
        res = self._smoke(_generating(
            '[Image.new("RGB", (8, 8)) for _ in range(params.num_images)]'))
        self.assertFalse(res['ok'])
        self.assertIn('IDENTIQUES', res['error'])


SPEECH = ('speech_to_text_base', 'SpeechToTextBackend')
TRANSCRIBING = '''
"""Backend de test."""
from .speech_to_text_base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

SUPPORTED_MODELS = {"Org/Asr": {}}


class AsrBackend(SpeechToTextBackend):
    ENGINE = "transformers"
    REQUIRED_PACKAGES = []
    name = "asr_smoke"

    def load(self, model_name=None):
        self._loaded = True
        return True

    def unload(self):
        self._loaded = False

    def transcribe(self, audio_path, language=None, hotwords=None, **kwargs):
        return TranscriptionResult(success=True, text=TEXT, language=language or "",
                                   segments=[TranscriptionSegment("", s, e, t) for s, e, t in SEGMENTS])
'''


class SpeechSmokeContractTest(SimpleTestCase):
    """The transcription contract had NO smoke until 2026-10-02: the two backends proposed for
    FrWhisper and Kyutai passed the checks and the simulated resolution, and failed on EVERY
    transcription. The smoke transcribes a real speech extract (here a fake one, 2 s, reference
    « bonjour à tous ») and judges behaviour, plus a guard against the absurd."""

    def _smoke(self, text, segments):
        import numpy as np
        code = TRANSCRIBING.replace('TEXT', repr(text)).replace('SEGMENTS', repr(segments))
        clip = mock.Mock(attributes={'language': 'fr'}, file=mock.Mock(path='clip.wav'))
        clip.name = 'clip'
        with tempfile.TemporaryDirectory() as out, \
                mock.patch.object(bp, 'smoke_speech_clip', return_value=(clip, 'ref.srt')), \
                mock.patch.object(bp, '_reference_window', return_value=(60.0, 62.0, 'bonjour à tous')), \
                mock.patch('wama.common.utils.audio_decode.decode_window',
                           return_value=(np.zeros(32000, dtype='float32'), 16000)):
            return bp.smoke(code, module='asr_smoke', model_key='huggingface:Org/Asr',
                            contract=SPEECH, out_dir=Path(out))

    def test_a_faithful_transcription_passes_and_reports_its_error_rate(self):
        res = self._smoke('Bonjour à tous.', [(0.0, 1.5, 'Bonjour à tous.')])
        self.assertTrue(res['ok'], res)
        self.assertEqual((0.0, [60.0, 62.0], 1), (res['wer'], res['window'], res['segments']))

    def test_no_text_fails(self):
        res = self._smoke('', [])
        self.assertFalse(res['ok'])
        self.assertIn('aucun texte', res['error'])

    def test_segments_out_of_order_or_outside_the_extract_fail(self):
        for segments in ([(1.0, 1.5, 'tous'), (0.0, 0.5, 'bonjour')], [(0.0, 9.0, 'bonjour')]):
            with self.subTest(segments=segments):
                res = self._smoke('bonjour tous', segments)
                self.assertFalse(res['ok'])
                self.assertIn('segments', res['error'])

    def test_an_output_unrelated_to_the_speech_fails(self):
        res = self._smoke('the weather is fine today', [(0.0, 1.5, 'the weather is fine today')])
        self.assertFalse(res['ok'])
        self.assertIn("taux d'erreur", res['error'])

    def test_a_contract_without_smoke_says_so(self):
        res = bp.smoke('', module='m', model_key='k:m', contract=('x', 'DetectionBackend'),
                       out_dir=Path('.'))
        self.assertEqual({'ran': False, 'reason': 'pas de smoke pour le contrat DetectionBackend'},
                         res)


SCORE = ('score_transcription_base', 'ScoreTranscriptionBackend')
SCORING = '''
"""Backend de test."""
from .score_transcription_base import ScoreTranscriptionBackend

SUPPORTED_MODELS = {"Org/Score": {}}


class ScoreBackend(ScoreTranscriptionBackend):
    ENGINE = "transformers-remote-code"
    REQUIRED_PACKAGES = []
    name = "score_smoke"

    def load(self, model_name=None):
        return True

    def unload(self):
        pass

    def transcribe_score(self, model_id, audio_path, output_dir=None, melody_only=True,
                         progress_callback=None):
        return ABC
'''
#: What SheetSage2 really returned on the smoke melody (2026-10-03): 32 notes + one stray F.
FAITHFUL_ABC = ('X:1\nM:4/4\nL:1/16\nQ:1/4=120\nV: Ins clef=treble name="Ins Melody"\nK:C\n'
                '% intro\nV: Ins\nC4D4E4F4|G4A4B4c4|B4A4G4F4|E4D4C4C4|\n'
                'C4D4E4F4|G4A4B4c4|B4A4G4F4|E4D4C4C4|\nF4z12|Z|\n')


class ScoreSmokeContractTest(SimpleTestCase):
    """The `audio-to-score` contract (2026-10-03) is judged on a SYNTHESIZED melody whose notes are
    known — no music is shipped in the system library — like speech is judged on its reference."""

    def _smoke(self, abc):
        with tempfile.TemporaryDirectory() as out:
            return bp.smoke(SCORING.replace('ABC', repr(abc)), module='score_smoke',
                            model_key='huggingface:Org/Score', contract=SCORE, out_dir=Path(out))

    def test_the_real_engine_output_passes(self):
        res = self._smoke(FAITHFUL_ABC)
        self.assertTrue(res['ok'], res)
        self.assertEqual(33, res['notes'])
        self.assertGreater(res['match'], 0.95)

    def test_a_score_unrelated_to_the_melody_fails(self):
        res = self._smoke('X:1\nK:C\nG8G8G8G8|G8G8G8G8|\n')
        self.assertFalse(res['ok'])
        self.assertIn('notes de la mélodie', res['error'])

    def test_text_without_a_key_header_is_not_a_score(self):
        res = self._smoke('C D E F G A B c')
        self.assertFalse(res['ok'])
        self.assertIn('K:', res['error'])

    def test_note_names_skip_headers_comments_rests_annotations_and_octaves(self):
        abc = 'X:1\nT:Titre\nK:G\n% commentaire\n"Am"A2 !trill!B,2 z4 ^c\'2|Z|\n'
        self.assertEqual('ABC', bp.abc_note_names(abc))

    def test_the_smoke_clip_names_the_notes_it_plays(self):
        import soundfile as sf
        with tempfile.TemporaryDirectory() as tmp:
            expected = bp.smoke_score_clip(Path(tmp) / 'clip.wav')
            info = sf.info(str(Path(tmp) / 'clip.wav'))
        self.assertEqual('CDEFGABCBAGFEDCC' * 2, expected)
        self.assertAlmostEqual(32 * 0.5 + bp.SMOKE_SCORE_TAIL_SECONDS, info.duration, places=1)


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


MUSIC = ('music_generation_base', 'MusicGenerationBackend')

VENDORED_GOOD = '''
from typing import Callable, Optional
from .music_generation_base import MusicGenerationBackend, split_caption_lyrics

SUPPORTED_MODELS = {"m-a-p/YuE2-3B": {}}


class SongBackend(MusicGenerationBackend):
    ENGINE = "yue"
    VENDORED = True
    REQUIRED_PACKAGES: list = []

    def load(self, model=None):
        self._p = self.import_vendored("yue2.pipeline", subdir="src")
        return True

    @property
    def is_loaded(self):
        return True

    def unload(self):
        import torch
        torch.cuda.set_per_process_memory_fraction(1.0)

    def generate(self, model_id, prompt, duration, output_path, melody_path=None,
                 progress_callback=None, on_audio=None):
        style, lyrics = split_caption_lyrics(prompt)
        return output_path
'''


class VendoredEngineCheckTest(SimpleTestCase):
    """Les règles d'un backend dont le moteur est VENDORISÉ (2026-10-01, YuE2) — sur un faux clone."""

    def setUp(self):
        from django.test import override_settings
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pkg = Path(tmp.name) / 'yue' / 'src' / 'yue2'
        pkg.mkdir(parents=True)
        (pkg / '__init__.py').write_text('', encoding='utf-8')
        (pkg / 'pipeline.py').write_text(
            'import torch\ntorch.cuda.set_per_process_memory_fraction(0.9)\n', encoding='utf-8')
        override = override_settings(BACKEND_VENDOR_DIR=tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        patcher = mock.patch.object(bp, '_is_vendored_engine', lambda engine: engine == 'yue')
        patcher.start()
        self.addCleanup(patcher.stop)

    def _check(self, code):
        return bp.check_source(code, engine='yue', model_id='m-a-p/YuE2-3B', contract=MUSIC)

    def test_a_well_formed_vendored_backend_passes(self):
        res = self._check(VENDORED_GOOD)
        self.assertTrue(res['ok'], res['errors'])

    def test_the_music_contract_requires_generate(self):
        self.assertIn('generate', bp.required_methods(MUSIC))
        self.assertEqual(MUSIC, bp.contract_for_task('text-to-music'))

    def test_each_vendored_defect_is_named(self):
        cases = {
            'VENDORED = True': VENDORED_GOOD.replace('    VENDORED = True\n', ''),
            'import_vendored(...)': VENDORED_GOOD.replace(
                'self.import_vendored("yue2.pipeline", subdir="src")', 'None'),
            'PAQUET': VENDORED_GOOD.replace('"yue2.pipeline", subdir="src"',
                                            '"pipeline", subdir="src/yue2"'),
            'aucun module': VENDORED_GOOD.replace('yue2.pipeline', 'yue2.nowhere'),
            'plafonne la VRAM': VENDORED_GOOD.replace(
                'torch.cuda.set_per_process_memory_fraction(1.0)', 'pass'),
            'nomme le code VENDORISÉ': VENDORED_GOOD.replace('REQUIRED_PACKAGES: list = []',
                                                             'REQUIRED_PACKAGES = ["yue2"]'),
        }
        for expected, code in cases.items():
            res = self._check(code)
            self.assertFalse(res['ok'], expected)
            self.assertTrue(any(expected in e for e in res['errors']), (expected, res['errors']))

    def test_an_annotated_class_attribute_is_read(self):
        """Contre-épreuve du faux positif : `REQUIRED_PACKAGES: list = []` est bien déclaré."""
        res = self._check(VENDORED_GOOD)
        self.assertFalse([e for e in res['errors'] if 'REQUIRED_PACKAGES' in e])

    def test_a_non_vendored_engine_is_not_held_to_these_rules(self):
        res = bp.check_source(VENDORED_GOOD.replace('"yue"', '"audiocraft"'), engine='audiocraft',
                              model_id='m-a-p/YuE2-3B', contract=MUSIC)
        self.assertFalse([e for e in res['errors'] if 'VENDORISÉ' in e or 'VRAM' in e], res['errors'])


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

    def test_a_sibling_repo_is_given_with_the_cache_dir_of_the_model(self):
        """Un dépôt FRÈRE (YuE2 → son VAE) : son identifiant et le cache_dir du modèle principal,
        pour qu'il arrive À CÔTÉ de lui ; component_paths, lui, ne le rend pas (aucun motif)."""
        from wama.common.utils.model_components import component_paths, component_repos
        self.row.composition = {'components': [{'role': 'dit', 'pattern': 'dit/model.onnx'},
                                               {'role': 'vae', 'repo': 'Org/Img-Vae'}],
                                'runtime': {'engine': 'onnxruntime'}}
        self.row.save()
        self.assertEqual({'vae': ('Org/Img-Vae', self.repo.parent)},
                         component_repos('huggingface:Org/Img-ONNX'))
        self.assertNotIn('vae', component_paths('huggingface:Org/Img-ONNX'))


class OnnxProvidersTest(SimpleTestCase):

    def test_cpu_only_never_offers_a_gpu_and_cpu_is_always_the_fallback(self):
        from wama.common.utils.onnx_utils import onnx_providers
        self.assertEqual(['CPUExecutionProvider'], onnx_providers(cpu_only=True))
        with mock.patch('onnxruntime.get_available_providers',
                        return_value=['CUDAExecutionProvider', 'CPUExecutionProvider']):
            self.assertEqual([('CUDAExecutionProvider', {'device_id': 0}), 'CPUExecutionProvider'],
                             onnx_providers())
