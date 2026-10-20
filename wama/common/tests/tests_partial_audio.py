"""The « during » face of a SOUND being computed — the common partial publisher
(`preview_utils.PartialFrames`, which publishes sound since 2026-10-20) and the composer's music
engine (`audiocraft_backend._follow_tokens`).

Fabien: « dans Composer, la preview est censée se charger au fur et à mesure de l'avancement de la
génération. Ce qui a été fait, mais ne fonctionne pas concrètement. » Measured: the three music
backends called `on_audio` ONCE, on the FINAL audio, and the task cleared the partial in the next
line — the « Pendant » face existed for milliseconds. The conformity criterion stayed green: it
reads that the app CALLS the brick, not WHEN.
"""
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase, override_settings

try:
    import torch
    from audiocraft.modules.codebooks_patterns import DelayedPatternProvider
    HAS_AUDIOCRAFT = True
except Exception:          # venv without audiocraft (Windows)
    HAS_AUDIOCRAFT = False


class PartialSoundTest(SimpleTestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_publishing_serves_a_playable_file_with_its_wave_then_closing_clears_it(self):
        import numpy as np
        from wama.common.utils.preview_utils import PartialFrames, _during_preview_data
        with override_settings(MEDIA_ROOT=self.root, MEDIA_URL='/media/'):
            frames = PartialFrames('composer', 987650, os.path.join(self.root, 'u', 'partials'))
            frames.publish_audio(np.zeros((16000, 1), dtype='float32') + 0.1, 16000)
            data = _during_preview_data('composer', SimpleNamespace(pk=987650), RequestFactory().get('/'))
            self.assertIsNotNone(data)
            self.assertIn('/media/u/partials/during_987650.wav?v=', data['url'])
            self.assertTrue(data['peaks'])
            self.assertAlmostEqual(1.0, float(data['duration']), places=1)
            frames.close()
            self.assertFalse(os.path.exists(frames.audio_path))
            self.assertIsNone(_during_preview_data('composer', SimpleNamespace(pk=987650),
                                                   RequestFactory().get('/')))

    def test_the_sound_sink_keeps_the_cadence_of_the_brick(self):
        from wama.common.utils.preview_utils import PartialFrames
        frames = PartialFrames('composer', 987651, self.root, every=3600)
        import time
        published = []

        def publish_audio(pcm, sr):     # the real one stamps `_last` first
            frames._last = time.time()
            published.append(len(pcm))
        frames.publish_audio = publish_audio
        sink = frames.audio_sink()
        self.assertTrue(sink.due(), 'a producer asks BEFORE decoding')
        sink([0.0] * 10, 10)
        self.assertFalse(sink.due())
        sink([0.0] * 20, 10)          # inside the cadence: skipped
        self.assertEqual([10], published)

    def test_the_file_written_by_the_producer_is_cleared_by_another_instance(self):
        """The synthesizer writes `audio_path` itself, then cleans up from another point of its run."""
        from wama.common.utils.preview_utils import PartialFrames
        os.makedirs(os.path.join(self.root, 'p'))
        first = PartialFrames('synthesizer', 987652, os.path.join(self.root, 'p'))
        open(first.audio_path, 'wb').close()
        PartialFrames('synthesizer', 987652, os.path.join(self.root, 'p')).close()
        self.assertFalse(os.path.exists(first.audio_path))


@unittest.skipUnless(HAS_AUDIOCRAFT, 'audiocraft is only installed in venv_linux')
class MusicGenPartialsTest(SimpleTestCase):
    """No GPU: a fake model with AudioCraft's REAL delay pattern (4 codebooks, delays 0-3)."""

    K = 4

    def _model(self, duration=8.0, max_duration=30.0):
        decoded = []

        class Codec:
            def decode(self, codes, scale):
                decoded.append(codes.clone())
                # One sample per timestep, its value = the codebook-0 code: the order is visible.
                return codes[:, :1, :].float()

        lm = SimpleNamespace(card=2048, special_token_id=2048,
                             pattern_provider=DelayedPatternProvider(n_q=self.K))
        model = SimpleNamespace(lm=lm, duration=duration, max_duration=max_duration,
                                sample_rate=32000, compression_model=Codec(), _cb=None)
        model.set_custom_progress_callback = lambda cb: setattr(model, '_cb', cb)
        return model, decoded

    def _step(self, i):
        """Sequence step i+1 of the delay pattern: codebook q carries timestep i - q."""
        values = [(i - q) if i - q >= 0 else 2048 for q in range(self.K)]
        return torch.tensor(values, dtype=torch.long).view(1, self.K, 1)

    def test_tokens_are_put_back_in_timestep_order_before_decoding(self):
        from wama.common.backends.audiocraft_backend import _partial_audio
        model, decoded = self._model()
        audio = _partial_audio(model, [self._step(i) for i in range(10)])
        codes = decoded[-1][0]
        self.assertEqual((self.K, 10 - 3), tuple(codes.shape), 'the last max_delay steps are incomplete')
        for q in range(self.K):
            self.assertEqual(list(range(7)), codes[q].tolist())
        self.assertEqual(list(range(7)), [int(v) for v in audio.ravel()])

    def test_nothing_is_decoded_before_a_complete_timestep(self):
        from wama.common.backends.audiocraft_backend import _partial_audio
        model, decoded = self._model()
        self.assertIsNone(_partial_audio(model, [self._step(i) for i in range(3)]))
        self.assertEqual([], decoded)

    def test_the_engine_hands_partials_while_it_samples_and_reports_real_progress(self):
        from wama.common.backends import audiocraft_backend as ab
        model, _ = self._model()
        counter = iter(range(10_000))
        model.lm._sample_next_token = lambda *a, **k: self._step(next(counter))
        heard, progress = [], []
        ab._follow_tokens(model, progress.append, lambda pcm, sr: heard.append(len(pcm)))
        total = 250
        for i in range(1, total + 1):
            model.lm._sample_next_token()
            model._cb(i, total)
        self.assertEqual([100 - 3, 200 - 3], heard, 'a partial every PARTIAL_EVERY_STEPS steps')
        self.assertGreaterEqual(min(progress), 40)
        self.assertEqual(80, max(progress))
        self.assertGreater(len(set(progress)), 30, 'progress moves step by step, not 40 → 80')

    def test_a_sink_with_a_cadence_is_asked_BEFORE_decoding(self):
        """Like `ImageGenerationBackend.preview_step`: no decoding while the sink says not due."""
        from wama.common.backends import audiocraft_backend as ab
        model, decoded = self._model()
        counter = iter(range(10_000))
        model.lm._sample_next_token = lambda *a, **k: self._step(next(counter))
        heard = []

        class Sink:
            ready = False

            def due(self):
                return self.ready

            def __call__(self, pcm, sr):
                heard.append(len(pcm))
        sink = Sink()
        ab._follow_tokens(model, None, sink)
        for i in range(1, 301):
            sink.ready = i == 150
            model.lm._sample_next_token()
            model._cb(i, 300)
        self.assertEqual(1, len(decoded), 'one decode, when the sink asked for it')
        self.assertEqual([150 - 3], heard)

    def test_beyond_one_window_only_progress_is_followed(self):
        from wama.common.backends import audiocraft_backend as ab
        model, decoded = self._model(duration=60.0)
        model.lm._sample_next_token = lambda *a, **k: self._step(0)
        heard = []
        ab._follow_tokens(model, None, lambda pcm, sr: heard.append(pcm))
        for i in range(1, 201):
            model._cb(i, 200)
        self.assertEqual([], heard)
        self.assertEqual([], decoded)
