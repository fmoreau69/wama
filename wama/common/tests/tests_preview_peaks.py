"""Server-side waveform PEAKS for an audio too heavy for the browser (2026-10-04).

Fabien: « dans Composer, j'ai testé YuE2 ; la forme d'onde de la preview ne s'affiche pas, alors
qu'elle s'affiche sur les cards plus anciennes ». Measured: a 3:52 song in 32-bit float at 48 kHz
weighs 89 MB, beyond the common player's decoding bound (30 MB) — it fell back to a bare timeline.
The front already draws peaks it is given; the preview now gives them for such a file.
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from wama.common.utils import preview_utils


@override_settings(MEDIA_URL='/media/', CACHES={
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class AHeavyAudioGetsItsPeaksTest(SimpleTestCase):

    def setUp(self):
        import numpy as np
        import soundfile as sf
        self.media = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)
        target = Path(self.media) / 'users/1/composer/output/song.wav'
        target.parent.mkdir(parents=True)
        tone = np.sin(np.linspace(0, 2000, 16000 * 3)).astype('float32')
        sf.write(str(target), tone, 16000, subtype='FLOAT')
        self.url = 'http://localhost/media/users/1/composer/output/song.wav?v=1'

    def _data(self):
        return {'name': 'song.wav', 'url': self.url, 'mime_type': 'audio/x-wav'}

    def test_beyond_the_browser_bound_the_server_draws_the_peaks(self):
        data = self._data()
        with mock.patch.object(preview_utils, 'CLIENT_DECODE_LIMIT_BYTES', 1000):
            preview_utils._add_server_peaks(data)
        self.assertEqual(800, len(data['peaks']))
        self.assertAlmostEqual(3.0, data['duration'], places=1)

    def test_a_light_audio_stays_decoded_by_the_browser(self):
        data = self._data()
        preview_utils._add_server_peaks(data)
        self.assertNotIn('peaks', data, 'additive: below the bound, nothing changes')

    def test_peaks_already_given_and_other_media_are_left_alone(self):
        given = dict(self._data(), peaks=[1, 2, 3])
        image = dict(self._data(), mime_type='image/png')
        with mock.patch.object(preview_utils, 'CLIENT_DECODE_LIMIT_BYTES', 1000):
            preview_utils._add_server_peaks(given)
            preview_utils._add_server_peaks(image)
        self.assertEqual([1, 2, 3], given['peaks'])
        self.assertNotIn('peaks', image)

    def test_the_bound_is_the_player_s(self):
        """One bound, two places: the server takes over exactly where the player gives up."""
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-audio-player.js'
              ).read_text(encoding='utf-8')
        self.assertIn('MAX_DECODE_BYTES = 30 * 1024 * 1024', js)
        self.assertEqual(30 * 1024 * 1024, preview_utils.CLIENT_DECODE_LIMIT_BYTES)
