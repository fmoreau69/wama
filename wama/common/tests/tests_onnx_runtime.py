"""
Le moteur ONNX atteint la carte graphique — et rien ne le lui retire en silence (2026-10-04).

Défaut MESURÉ en cherchant pourquoi la voix de l'assistant était lente : deux distributions
concurrentes étaient installées dans le venv Linux, `onnxruntime` (processeur) et
`onnxruntime-gpu`. Elles fournissent le MÊME module ; la première masquait la seconde, donc le
moteur n'offrait que le processeur — sans erreur, sans avertissement. La voix (Kokoro ONNX) et
l'agrandisseur de l'Enhancer tournaient sur le processeur depuis un temps inconnu.

⚠ Le défaut REVIENDRA à la première installation d'une librairie qui dépend du nom
`onnxruntime` (faster-whisper, kokoro-onnx, qwen-tts…) : pip réinstallera la version processeur.
C'est exactement ce que la première garde attrape.
"""
import sys
from importlib import metadata
from unittest import mock, skipUnless

from django.test import SimpleTestCase


def _installed(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


GPU_BUILD = _installed('onnxruntime-gpu')


@skipUnless(sys.platform.startswith('linux') and GPU_BUILD, 'pas de moteur ONNX GPU dans ce venv')
class GpuRuntimeNotShadowedTest(SimpleTestCase):

    def test_the_cpu_build_is_not_installed_next_to_the_gpu_build(self):
        self.assertIsNone(
            _installed('onnxruntime'),
            "`onnxruntime` (processeur) est installé à côté de `onnxruntime-gpu` : il le masque, "
            "et tout moteur ONNX retombe sur le processeur en silence. Réparer : "
            "`pip uninstall -y onnxruntime` puis "
            f"`pip install --force-reinstall --no-deps onnxruntime-gpu=={GPU_BUILD}`.")

    def test_the_runtime_offers_the_graphics_card(self):
        import onnxruntime
        self.assertIn('CUDAExecutionProvider', onnxruntime.get_available_providers())

    def test_the_common_provider_list_asks_for_the_card_first_and_keeps_the_cpu_last(self):
        from wama.common.utils.onnx_utils import onnx_providers
        providers = onnx_providers()
        self.assertEqual(providers[0][0], 'CUDAExecutionProvider')
        self.assertEqual(providers[-1], 'CPUExecutionProvider')
        self.assertEqual(onnx_providers(cpu_only=True), ['CPUExecutionProvider'])


class VoiceEngineUsesTheCommonProvidersTest(SimpleTestCase):
    """Le moteur de voix construit SA session avec la liste commune : laissé à lui-même,
    `kokoro_onnx` ne demande la carte que si une variable d'environnement le dit."""

    def test_the_session_is_built_with_the_common_provider_list(self):
        from pathlib import Path

        from wama.common.backends import kokoro_onnx_backend as module

        session = mock.Mock()
        session.get_providers.return_value = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        fake_ort = mock.Mock()
        fake_ort.InferenceSession.return_value = session
        fake_kokoro = mock.Mock()
        fake_kokoro.Kokoro.from_session.return_value.get_voices.return_value = ['ff_siwis']
        backend = module.KokoroOnnxBackend()
        with mock.patch.dict(sys.modules, {'onnxruntime': fake_ort, 'kokoro_onnx': fake_kokoro}), \
                mock.patch.object(module, '_snapshot_dir', return_value=Path('/snapshot')), \
                mock.patch.object(module, '_declared_patterns',
                                  return_value={'acoustic_model': 'model.onnx', 'voices': '*.bin'}), \
                mock.patch.object(Path, 'is_file', return_value=True), \
                mock.patch.object(module.KokoroOnnxBackend, '_ensure_voices_npz',
                                  return_value=Path('/voices.npz')), \
                mock.patch('wama.common.utils.onnx_utils.onnx_providers',
                           return_value=['SENTINEL']), \
                mock.patch.object(module.KokoroOnnxBackend, 'process', return_value='/nowhere'), \
                mock.patch.object(module.os, 'unlink'):
            backend.load()
        self.assertEqual(fake_ort.InferenceSession.call_args.kwargs['providers'], ['SENTINEL'])
        self.assertEqual(backend.execution_provider, 'CUDAExecutionProvider')
