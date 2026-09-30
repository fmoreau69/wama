"""
Lancement du sous-processus MuseTalk — ce que la mesure du 2026-09-30 a établi (3 s de vidéo en
505 s) : le temps partait au DÉMARRAGE à froid (imports, dont TensorFlow inutile), l'inférence
tournait en float32, et le délai FIXE de 600 s tuait tout audio de plus d'une demi-minute.

Aucun GPU ici : le sous-processus est simulé, on lit ce qui PART vers lui.
"""
import subprocess
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from wama.common.backends import musetalk_backend as mb


class MuseTalkLaunchTest(SimpleTestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'engine').mkdir()
        self.out = self.root / 'out'
        (self.out / 'v15').mkdir(parents=True)
        (self.out / 'v15' / 'avatar_audio.mp4').write_bytes(b'mp4')
        patchers = [mock.patch.object(mb, 'MUSETALK_DIR', self.root / 'engine'),
                    mock.patch.object(mb, 'vram_reservation', lambda *a, **k: nullcontext())]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _launch(self, duration):
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
        with mock.patch('wama.common.utils.audio_decode.probe_duration_seconds',
                        return_value=duration), \
                mock.patch.object(mb.subprocess, 'run', return_value=done) as run:
            video = mb._run_musetalk('photo.jpg', 'audio.wav', str(self.out))
        self.assertTrue(video.endswith('avatar_audio.mp4'))
        return run.call_args

    def test_inference_runs_in_float16(self):
        args, _ = self._launch(3.0)
        self.assertIn('--use_float16', args[0])

    def test_the_timeout_grows_with_the_audio(self):
        _, kwargs = self._launch(60.0)
        self.assertEqual(mb.TIMEOUT_BASE_S + 60 * mb.TIMEOUT_PER_AUDIO_S, kwargs['timeout'])
        self.assertGreater(kwargs['timeout'], 600, "un audio d'une minute dépassait l'ancien délai fixe")

    def test_an_unknown_duration_keeps_the_base_timeout(self):
        """Contre-épreuve : sonde en échec → la base seule, jamais zéro."""
        _, kwargs = self._launch(None)
        self.assertEqual(mb.TIMEOUT_BASE_S, kwargs['timeout'])

    def test_the_subprocess_never_imports_tensorflow(self):
        _, kwargs = self._launch(3.0)
        self.assertEqual('0', kwargs['env']['USE_TF'])
        self.assertEqual(str(mb.MUSETALK_HF_CACHE), kwargs['env']['HF_HUB_CACHE'],
                         "le cache HF du sous-processus reste le sien")
