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


class TensorFlowGrowsItsMemoryTest(SimpleTestCase):
    """Un TensorFlow qui voit la carte en prend TOUTE la mémoire sans `TF_FORCE_GPU_ALLOW_GROWTH`
    (2026-11-08, mesuré : 23 579 Mio occupés pour 108 Mio utiles) — hors du gouverneur. La variable
    se pose UNE fois, au démarrage du processus, avant tout import de TensorFlow."""

    def test_the_settings_make_tensorflow_grow_its_memory(self):
        self.assertEqual(os.environ.get('TF_FORCE_GPU_ALLOW_GROWTH'), 'true')

    def test_a_django_process_has_it_before_tensorflow_is_imported(self):
        import subprocess
        import sys
        from django.conf import settings
        code = ("import os, django, sys; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings'); "
                "django.setup(); print(os.environ.get('TF_FORCE_GPU_ALLOW_GROWTH'), "
                "'tensorflow' in sys.modules)")
        env = {k: v for k, v in os.environ.items() if k != 'TF_FORCE_GPU_ALLOW_GROWTH'}
        out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                             cwd=str(settings.BASE_DIR), env=env, timeout=600)
        self.assertEqual(0, out.returncode, out.stderr[-2000:])
        self.assertEqual('true False', out.stdout.strip().splitlines()[-1])


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


class ChildStopsWithItsTaskTest(SimpleTestCase):
    """⏹ reaches a computing child and its own children (2026-11-04): MuseTalk and CodeFormer ran
    through `subprocess.run`, which the stop never reached, and a time limit killed the direct
    child only. Real processes: a Python child that starts a grandchild, both of which sleep."""

    def setUp(self):
        if not hasattr(os, 'killpg'):
            self.skipTest('process groups (Linux) required')
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.pids = os.path.join(folder.name, 'pids')
        script = textwrap.dedent(f"""
            import os, subprocess, sys, time
            grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
            open({self.pids!r}, 'w').write(f'{{os.getpid()}} {{grandchild.pid}}')
            time.sleep(60)
        """)
        self.cmd = [sys.executable, '-c', script]

    def _alive(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        # A zombie still answers: read its state.
        with open(f'/proc/{pid}/stat') as stat:
            return stat.read().split(') ')[1][0] != 'Z'

    def _wait_for_pids(self):
        import time
        for _ in range(100):
            if os.path.exists(self.pids) and open(self.pids).read().strip():
                return [int(p) for p in open(self.pids).read().split()]
            time.sleep(0.05)
        self.fail('the child never started its grandchild')

    def test_a_stop_seen_by_the_heartbeat_ends_the_child_and_its_children(self):
        from wama.common.utils.process_control import run_child
        from wama.common.utils.task_skeleton import LaunchSuperseded
        seen = []

        def heartbeat():
            seen.extend(self._wait_for_pids())
            raise LaunchSuperseded()
        with self.assertRaises(LaunchSuperseded):
            run_child(self.cmd, heartbeat=heartbeat, poll_s=0.2)
        self.assertEqual(2, len(seen))
        for pid in seen:
            self.assertFalse(self._alive(pid), f'pid {pid} survived the stop')

    def test_the_time_limit_ends_the_whole_group(self):
        from wama.common.utils.process_control import run_child
        with self.assertRaises(subprocess.TimeoutExpired):
            run_child(self.cmd, timeout=1.0, poll_s=0.2)
        for pid in self._wait_for_pids():
            self.assertFalse(self._alive(pid), f'pid {pid} survived the time limit')

    def test_a_child_that_ends_gives_its_code_and_its_output(self):
        from wama.common.utils.process_control import run_child
        beats = []
        done = run_child([sys.executable, '-c', 'import sys; print("out"); '
                          'print("err", file=sys.stderr); sys.exit(3)'],
                         heartbeat=lambda: beats.append(1), poll_s=0.2)
        self.assertEqual((3, 'out\n', 'err\n'), (done.returncode, done.stdout, done.stderr))

    def test_codeformer_beats_with_the_progress_of_its_glue(self):
        from wama.common.backends import codeformer_backend
        done = subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr='boom')
        calls = []
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch('wama.common.utils.process_control.run_child', return_value=done) as run, \
                mock.patch.object(codeformer_backend, 'vram_reservation',
                                  lambda *a, **k: __import__('contextlib').nullcontext()):
            codeformer_backend._codeformer_dans('in.mp4', __import__('pathlib').Path(folder),
                                                calls.append)
        run.call_args.kwargs['heartbeat']()
        self.assertEqual([0.0], calls)
