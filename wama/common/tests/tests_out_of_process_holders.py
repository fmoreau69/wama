"""Ce qui tient la carte HORS du worker GPU, en venv unique — quatre défauts soldés le 2026-11-02.

POURQUOI. Bilan demandé par Fabien avant toute décision sur le multi-venv (« tout fonctionne-t-il
de la même façon ? »). Mesuré au code : ① le battement des lignes du registre ne partait que dans
les workers Celery et le service TTS — le service privacy et gunicorn publiaient sans le battre, la
ligne expirait au bout d'1 h pendant que le modèle restait chargé ; ② les sous-processus MuseTalk
et CodeFormer tournaient sans plafond d'allocateur CUDA ; ③ un chargement de l'Ollama hôte n'avait
de ligne qu'au relevé périodique (10 min), et « Libérer la carte » ne le déchargeait jamais ;
④ aucun écran ne montrait les détenteurs sans modèle du catalogue (sous-processus).

Aucun GPU, aucun Redis : le faux Redis des tests du registre ; l'enfant du ② est un vrai
processus Python, avec un faux `torch`.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
from unittest import mock

from django.test import SimpleTestCase, override_settings

from wama.common.services import resource_governor as gov
from wama.common.tests.tests_vram_governance import _WithRegistry


class HeartbeatStartsWithTheFirstResidentTest(SimpleTestCase):

    def test_tracking_a_live_backend_starts_the_heartbeat_of_its_process(self):
        from wama.common.backends import base
        with mock.patch.object(base, 'start_reservation_heartbeat') as beat:
            instance = type('LiveBackend', (), {})()
            base._track_live(instance)
            self.addCleanup(base._untrack_live, instance)
        beat.assert_called_once_with()


class CappedChildTest(SimpleTestCase):

    def test_the_child_environment_puts_the_boot_first_and_keeps_the_rest(self):
        env = gov.capped_child_env({'PYTHONPATH': '/vendor/engine', 'KEEP': '1'})
        self.assertEqual(env['PYTHONPATH'].split(os.pathsep),
                         [gov.CHILD_BOOT_DIR, '/vendor/engine'])
        self.assertEqual(env['KEEP'], '1')
        self.assertEqual(float(env['WAMA_CUDA_CAP_FRACTION']), gov.ALLOCATOR_CAP_FRACTION)

    def test_a_python_child_caps_its_allocator_when_it_imports_torch(self):
        """Un vrai enfant : l'amorce pose le plafond au premier import de `torch` (un faux, qui
        enregistre l'appel) — sans le paquet `wama`, dont l'`__init__` monterait Celery."""
        fake = tempfile.mkdtemp(prefix='fake_torch_')
        self.addCleanup(__import__('shutil').rmtree, fake, True)
        with open(os.path.join(fake, 'torch.py'), 'w', encoding='utf-8') as fh:
            fh.write(textwrap.dedent('''
                class cuda:
                    calls = []
                    @staticmethod
                    def is_available():
                        return True
                    @staticmethod
                    def set_per_process_memory_fraction(fraction):
                        cuda.calls.append(fraction)
                    @staticmethod
                    def get_device_properties(index):
                        return type('P', (), {'total_memory': 24 * 1024 ** 3})()
            '''))
        env = gov.capped_child_env({'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': fake})
        code = "import sys, torch; print(torch.cuda.calls, 'wama' in sys.modules)"
        out = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True,
                             text=True, timeout=60, cwd=fake)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), f"[{gov.ALLOCATOR_CAP_FRACTION}] False")

    def test_musetalk_and_codeformer_children_receive_the_capped_environment(self):
        from wama.common.backends import musetalk_backend
        self.assertTrue(musetalk_backend._build_musetalk_env()['PYTHONPATH'].startswith(
            gov.CHILD_BOOT_DIR))
        import inspect
        from wama.common.backends import codeformer_backend
        self.assertIn('env=capped_child_env()', inspect.getsource(codeformer_backend._codeformer_dans))


class ForkSafeCudaCheckTest(SimpleTestCase):
    """Le test de disponibilité de CUDA ne doit pas empoisonner les enfants d'un pool qui forke
    (2026-11-02) : chaque enfant du worker `default` (prefork) relevait « Cannot re-initialize CUDA
    in forked subprocess », plafond de l'allocateur non posé. Mesuré sur un worker jetable : la
    variable posée par `settings.py` suffit."""

    def test_the_settings_make_torch_check_cuda_through_nvml(self):
        self.assertEqual(os.environ.get('PYTORCH_NVML_BASED_CUDA_CHECK'), '1')


class OllamaHostTest(_WithRegistry):

    def test_a_granted_release_unloads_every_resident_of_the_host(self):
        gov.reserve_vram(gov.ollama_host_owner('qwen3:4b'), 3.2)
        gov.reserve_vram(f'avatarizer.musetalk:{os.getpid()}', 8.0)
        with mock.patch('wama.model_manager.services.memory_manager.MemoryManager.unload_model',
                        return_value=True) as unload:
            self.assertEqual(gov.release_ollama_host(), 1)
        unload.assert_called_once_with('ollama:qwen3:4b')

    def test_obtaining_vram_asks_the_host_to_unload(self):
        with mock.patch.object(gov, 'release_ollama_host') as host, \
                mock.patch.object(gov, 'effective_free_gb', return_value=30.0):
            ok, _free = gov.obtain_vram(5.0, requester='4242')
        self.assertTrue(ok)
        host.assert_called_once_with()

    @override_settings(WAMA_TASKS_DISPATCHED=True)
    def test_a_load_that_keeps_the_model_publishes_its_line_at_once(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        with mock.patch.object(ModelRegistry, 'refresh_ollama_residency') as refresh:
            self.assertTrue(ModelRegistry.publish_ollama_load('qwen3:4b'))
            self.assertFalse(ModelRegistry.publish_ollama_load('qwen3:4b', keep_alive=0))
        refresh.assert_called_once_with()

    def test_every_measured_load_publishes_the_residence(self):
        """Le point d'entrée de tous les appelants (vecteurs, conversation, assistant, vision)."""
        from wama.common.utils.ollama_host import measured_load
        from wama.model_manager.services.model_registry import ModelRegistry
        with mock.patch.object(ModelRegistry, 'measure_ollama_load', return_value='answer'), \
                mock.patch.object(ModelRegistry, 'publish_ollama_load') as publish:
            self.assertEqual(measured_load('qwen3:4b', lambda: 'answer', keep_alive='5m'),
                             'answer')
        publish.assert_called_once_with('qwen3:4b', keep_alive='5m')

    @override_settings(WAMA_TASKS_DISPATCHED=True)
    def test_a_model_already_in_the_registry_is_not_read_again(self):
        from wama.common.utils.ollama_host import full_tag
        from wama.model_manager.services.model_registry import ModelRegistry
        gov.reserve_vram(gov.ollama_host_owner(full_tag('qwen3:4b')), 3.2)
        with mock.patch.object(ModelRegistry, 'refresh_ollama_residency') as refresh:
            self.assertFalse(ModelRegistry.publish_ollama_load('qwen3:4b'))
        refresh.assert_not_called()


class OtherHoldersTest(_WithRegistry):

    def test_a_subprocess_and_an_unresolved_backend_are_named_not_hidden(self):
        gov.reserve_vram(f'avatarizer.musetalk:{os.getpid()}', 8.0)
        gov.reserve_vram(f'wama.common.backends.x.XBackend:{os.getpid()}#@unknown-name', 1.5)
        gov.reserve_vram(gov.ollama_host_owner('qwen3:4b'), 3.2)
        with mock.patch('wama.common.backends.manager.catalog_keys_for_owner', return_value=[]):
            self.assertEqual(gov.other_holders(),
                             {'avatarizer.musetalk': 8.0, 'unknown-name': 1.5})
            summary = gov.holders_summary()
        self.assertIn('avatarizer.musetalk (8.0 Go)', summary)
        self.assertIn('ollama:qwen3:4b (3.2 Go)', summary)
