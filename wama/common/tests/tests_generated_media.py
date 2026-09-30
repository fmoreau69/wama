"""La mention « généré par IA » dans les métadonnées d'un média (2026-09-30).

Décision de Fabien : usage recherche, MÉTADONNÉE seule (pas de filigrane pour le moment). Ce que
ces tests gardent : la mention est RELISIBLE par un outil tiers (`ffprobe`) après le passage, le
son n'est pas ré-encodé (même taille à l'en-tête près), et un échec ne fait jamais échouer.
"""
import json
import os
import subprocess
import tempfile
from unittest import skipUnless

from django.test import SimpleTestCase

from wama.common.utils.generated_media import generated_notice, mark_as_generated


def _ffmpeg():
    try:
        from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except Exception:
        return ''


def _probe_tags(path):
    from wama.common.utils.ffmpeg_utils import get_ffprobe_exe
    out = subprocess.run([get_ffprobe_exe(), '-v', 'error', '-show_entries', 'format_tags',
                          '-of', 'json', path], stdout=subprocess.PIPE, check=True, text=True)
    return {k.lower(): v for k, v in (json.loads(out.stdout).get('format', {}).get('tags') or {}).items()}


@skipUnless(_ffmpeg(), 'ffmpeg absent')
class GeneratedMediaNoticeTest(SimpleTestCase):

    def _tone(self, folder, ext):
        path = os.path.join(folder, f'out.{ext}')
        subprocess.run([_ffmpeg(), '-nostdin', '-y', '-f', 'lavfi', '-i', 'sine=duration=1', path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return path

    def test_the_notice_is_readable_by_a_third_party_tool_in_wav_and_mp3(self):
        with tempfile.TemporaryDirectory() as tmp:
            for ext in ('wav', 'mp3'):
                path = self._tone(tmp, ext)
                self.assertTrue(mark_as_generated(path, app='synthesizer',
                                                  model='synthesizer:coqui-xtts', detail='voix clonée'))
                tags = _probe_tags(path)
                self.assertIn('généré par IA', tags.get('comment', ''), (ext, tags))
                self.assertIn('synthesizer:coqui-xtts', tags.get('comment', ''))
                self.assertIn('voix clonée', tags.get('comment', ''))

    def test_the_sound_is_copied_not_reencoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._tone(tmp, 'wav')
            before = os.path.getsize(path)
            mark_as_generated(path, app='synthesizer', model='m')
            self.assertLess(abs(os.path.getsize(path) - before), 4096)

    def test_a_failure_leaves_the_file_untouched_and_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'broken.wav')
            with open(path, 'wb') as fh:
                fh.write(b'not audio at all')
            self.assertFalse(mark_as_generated(path, app='synthesizer'))
            with open(path, 'rb') as fh:
                self.assertEqual(b'not audio at all', fh.read())
            self.assertEqual(['broken.wav'], os.listdir(tmp))
        self.assertFalse(mark_as_generated('', app='synthesizer'))

    def test_the_notice_names_the_app_and_the_model(self):
        text = generated_notice('synthesizer', 'synthesizer:kokoro')
        self.assertIn('WAMA synthesizer', text)
        self.assertIn('synthesizer:kokoro', text)
