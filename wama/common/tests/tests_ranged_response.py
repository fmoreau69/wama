"""Serving a file BY PIECES (HTTP `Range`) — what makes a medium seekable (2026-10-15).

Measured before the brick : `/media/` answered `200` without `Accept-Ranges`, so a browser could
only go to what it had already downloaded of a long render. The rule lived once, in the
cam_analyzer's `stream_video`, which now consumes it. Since 2026-11-08 `/media/` itself is served
by the guarded view (`media_serving.serve_media`, its own tests), which consumes it too.
"""
import shutil
import tempfile
from pathlib import Path

from django.test import RequestFactory, SimpleTestCase

from wama.common.utils.ranged_response import parse_range, ranged_file_response


def _body(response) -> bytes:
    return b''.join(response.streaming_content) if response.streaming else response.content


class ParseRangeTest(SimpleTestCase):

    def test_the_ranges_a_media_element_sends_are_read_and_bounded(self):
        self.assertEqual((0, 9), parse_range('bytes=0-9', 100))
        self.assertEqual((50, 99), parse_range('bytes=50-', 100), 'open end = to the end')
        self.assertEqual((90, 99), parse_range('bytes=-10', 100), 'suffix = the last bytes')
        self.assertEqual((95, 99), parse_range('bytes=95-500', 100), 'bounded to the size')

    def test_what_cannot_be_served_is_told_apart_from_what_is_ignored(self):
        self.assertEqual((), parse_range('bytes=100-', 100), 'beyond the file : 416')
        self.assertIsNone(parse_range('', 100))
        self.assertIsNone(parse_range('bytes=0-1,5-6', 100), 'several ranges : the whole file')
        self.assertIsNone(parse_range('items=0-1', 100))


class RangedFileResponseTest(SimpleTestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = bytes(range(256)) * 4
        self.path = self.root / 'song.wav'
        self.path.write_bytes(self.data)
        self.factory = RequestFactory()

    def test_a_requested_piece_is_served_as_206(self):
        request = self.factory.get('/media/users/song.wav', HTTP_RANGE='bytes=100-199')
        response = ranged_file_response(request, str(self.path))
        self.assertEqual(206, response.status_code)
        self.assertEqual('bytes 100-199/1024', response['Content-Range'])
        self.assertEqual(self.data[100:200], _body(response))
        self.assertEqual('bytes', response['Accept-Ranges'])

    def test_without_a_range_the_whole_file_says_pieces_are_accepted(self):
        response = ranged_file_response(self.factory.get('/media/users/song.wav'), str(self.path))
        self.assertEqual(200, response.status_code)
        self.assertEqual('bytes', response['Accept-Ranges'])
        self.assertEqual(self.data, _body(response))

    def test_a_piece_beyond_the_file_is_refused(self):
        response = ranged_file_response(self.factory.get('/', HTTP_RANGE='bytes=5000-'), str(self.path))
        self.assertEqual(416, response.status_code)
