"""The common timed video render (`common/utils/video_render.render_video`) — out of
`detections.py` on 2026-10-29, when the enhancer's video upscale became its second caller
(Fabien : « on porte l'upscale vidéo sur le rendu commun en conservant le son comme Anonymizer »).

What is held here, beyond what `tests_detections.RewriteVideoKeepsItsSoundTest` holds for the
blur : a paint that CHANGES the size gives a video of the painted size, its sound copied and in
phase, every frame at its time ; an interrupted render leaves no half-written file.
"""
import os
import shutil
import tempfile

import cv2
from django.test import SimpleTestCase

from wama.common.tests.helpers import frame_times, media_streams, video_with_sound
from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe
from wama.common.utils.video_render import render_video


class _Interrupted(BaseException):
    """A stop that is not an `Exception` — a time limit, a worker shutdown."""


class RenderVideoTest(SimpleTestCase):

    def setUp(self):
        if not get_ffmpeg_exe():
            self.skipTest('ffmpeg absent')
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.source = video_with_sound(self.folder, 'talk.mp4', 'aac')

    def test_a_paint_that_doubles_the_size_keeps_the_sound_and_the_frame_times(self):
        seen = []
        written = render_video(
            self.source, lambda index, image: cv2.resize(image, None, fx=2, fy=2),
            os.path.join(self.folder, 'out', 'talk_x2.mp4'),
            on_frame=lambda index, original, painted: seen.append(
                (original.shape[:2], painted.shape[:2])))
        container, streams = media_streams(written)
        self.assertIn('mp4', container)
        self.assertEqual((128, 96), (streams['video']['width'], streams['video']['height']))
        self.assertEqual('aac', streams['audio']['codec_name'], 'the sound is copied')
        self.assertAlmostEqual(float(streams['video']['duration']),
                               float(streams['audio']['duration']), delta=0.12)
        before, after = frame_times(self.source), frame_times(written)
        self.assertEqual(len(before), len(after))
        self.assertLess(max(abs(a - b) for a, b in zip(before, after)), 0.002)
        self.assertEqual(((48, 64), (96, 128)), seen[0], 'the preview gets both images')
        self.assertEqual(len(before), len(seen))

    def test_an_interrupted_render_leaves_no_file_behind(self):
        def paint(index, image):
            if index == 3:
                raise _Interrupted()
            return image

        out = os.path.join(self.folder, 'out')
        with self.assertRaises(_Interrupted):
            render_video(self.source, paint, os.path.join(out, 'talk_cut.mp4'))
        self.assertEqual([], os.listdir(out), 'neither the render nor its half-written file')
