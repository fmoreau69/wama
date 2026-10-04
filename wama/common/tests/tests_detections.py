"""The `detections` document on disk (`common/utils/detections.py`) and the blur that reads it
(`blur_utils.blur_detections`) — born on 2026-10-04 when the anonymizer's detection became a
process of its own (Fabien : « on sépare détection/segmentation et floutage »).

What is held : the document round-trips (sparse, ordered, merged per frame across models) ; a
segmentation mask survives as polygons ; the gaps of a TRACK are interpolated between two known
detections only, within the ceiling, never beyond the last one ; the drawing and the blur touch
the detected zone and nothing else ; a media is re-rendered frame by frame.
"""
import os
import shutil
import tempfile

import cv2
import numpy as np
from django.test import SimpleTestCase

from wama.common.utils import detections as dets
from wama.common.utils.blur_utils import blur_detections


def _stripes(size=64):
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[:, ::4] = 255
    return image


class TheDocumentTest(SimpleTestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_it_round_trips_sparse_ordered_and_merged_per_frame(self):
        doc = dets.new_document(media='video', width=64, height=48, fps=25, frame_count=100,
                                engine='yolo', models=['faces.pt', 'plates.pt'], classes=['face'])
        dets.add(doc, 7, [dets.detection(box=[1.4, 2.6, 30, 40], label='face', conf=0.91234,
                                         track='m0:3')])
        dets.add(doc, 2, [dets.detection(box=[5, 5, 20, 20], label='plate', conf=0.5)])
        dets.add(doc, 7, [dets.detection(box=[40, 4, 60, 20], label='plate', conf=0.7,
                                         track='m1:1')])           # a 2nd model, same frame
        dets.add(doc, 9, [])                                         # an empty frame costs nothing
        path = dets.write(os.path.join(self.folder, 'x', 'doc.json'), doc)
        back = dets.read(path)
        self.assertEqual([2, 7], [f['i'] for f in back['frames']])
        self.assertEqual(3, dets.count(back))
        first = back['frames'][1]['d'][0]
        self.assertEqual(([1, 3, 30, 40], 0.912, 'm0:3'), (first['box'], first['conf'], first['track']))
        self.assertNotIn('_index', back, 'the working index is not written')
        self.assertEqual(('video', 25.0, 100), (back['media'], back['fps'], back['frame_count']))

    def test_a_file_that_is_not_a_document_is_refused(self):
        path = os.path.join(self.folder, 'other.json')
        with open(path, 'w', encoding='utf-8') as out:
            out.write('{"kind": "something else"}')
        with self.assertRaises(ValueError):
            dets.read(path)


class GeometryTest(SimpleTestCase):

    def test_a_mask_survives_as_polygons(self):
        mask = np.zeros((40, 40), dtype=np.uint8)
        cv2.circle(mask, (20, 20), 10, 255, -1)
        polygons = dets.mask_to_polygons(mask)
        self.assertEqual(1, len(polygons))
        back = dets.polygons_to_mask(polygons, (40, 40))
        overlap = np.logical_and(mask > 0, back > 0).sum() / (mask > 0).sum()
        self.assertGreater(overlap, 0.9)
        self.assertEqual([], dets.mask_to_polygons(np.zeros((10, 10))), 'empty mask : nothing')
        x1, y1, x2, y2 = dets.box_of_polygons(polygons)
        self.assertTrue(9 <= x1 <= 11 and 29 <= x2 <= 31 and 9 <= y1 <= 11 and 29 <= y2 <= 31)

    def test_a_contour_given_as_points_is_simplified_to_integers(self):
        square = [[10.2, 10.0], [10.4, 20.0], [10.6, 30.0], [30.0, 30.0], [30.0, 10.0]]
        polygons = dets.points_to_polygons(square)
        self.assertEqual(1, len(polygons))
        self.assertTrue(all(isinstance(v, int) for p in polygons[0] for v in p))
        self.assertLessEqual(len(polygons[0]), 5)
        self.assertEqual([], dets.points_to_polygons([[1, 1], [2, 2]]))

    def test_a_box_is_brought_back_inside_the_image_or_dropped(self):
        self.assertEqual([0, 0, 30, 20], dets.valid_box([-5, -5, 30, 20], (40, 40)))
        self.assertIsNone(dets.valid_box([10, 10, 12, 30], (40, 40)), 'thinner than 5 px')
        self.assertIsNone(dets.valid_box(None, (40, 40)))


class InterpolationTest(SimpleTestCase):

    def _doc(self, *seen):
        doc = dets.new_document(media='video', width=100, height=100, fps=30)
        for index, box, track in seen:
            dets.add(doc, index, [dets.detection(box=box, label='face', track=track)])
        return doc

    def test_a_gap_of_a_track_is_filled_between_two_known_detections(self):
        doc = self._doc((0, [0, 0, 10, 10], 'm0:1'), (4, [40, 0, 50, 10], 'm0:1'))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5)
        self.assertEqual([0, 1, 2, 3, 4], sorted(frames))
        middle = frames[2][0]
        self.assertEqual(([20, 0, 30, 10], True), (middle['box'], middle['interpolated']))
        self.assertNotIn('interpolated', frames[0][0])

    def test_nothing_is_deduced_beyond_the_ceiling_after_the_last_or_without_a_track(self):
        doc = self._doc((0, [0, 0, 10, 10], 'm0:1'), (10, [40, 0, 50, 10], 'm0:1'),
                        (20, [0, 0, 10, 10], None), (22, [0, 0, 10, 10], None))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5)
        self.assertEqual([0, 10, 20, 22], sorted(frames), 'a 9-frame gap is above the ceiling')
        self.assertEqual([0, 10, 20, 22], sorted(dets.by_frame(doc)), 'off : only what was seen')

    def test_two_tracks_never_mix(self):
        doc = self._doc((0, [0, 0, 10, 10], 'm0:1'), (2, [90, 90, 99, 99], 'm1:1'),
                        (4, [40, 0, 50, 10], 'm0:1'))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5)
        deduced = [d for f in frames.values() for d in f if d.get('interpolated')]
        self.assertTrue(all(d['track'] == 'm0:1' for d in deduced))

    def test_the_gap_is_capped_at_half_a_second_of_video(self):
        self.assertEqual(15, dets.max_gap_for(30, 20))
        self.assertEqual(10, dets.max_gap_for(30, 10))
        self.assertEqual(15, dets.max_gap_for(0, 60), 'unknown fps : 30 assumed')


class DrawAndBlurTest(SimpleTestCase):

    def test_the_drawing_touches_the_detection_and_leaves_the_original_intact(self):
        image = np.zeros((64, 64, 3), dtype=np.uint8)
        found = [dets.detection(box=[10, 10, 40, 40], label='face', conf=0.9,
                                polygons=[[[12, 12], [38, 12], [38, 38], [12, 38]]])]
        drawn = dets.draw(image, found)
        self.assertTrue((image == 0).all(), 'a COPY is drawn on')
        self.assertGreater(drawn[10:41, 10:41].sum(), 0)
        self.assertTrue((drawn[50:, 50:] == 0).all())
        bare = dets.draw(image, found, boxes=False, labels=False, confidence=False)
        self.assertGreater(bare[20:30, 20:30].sum(), 0, 'the contour is still shown')

    def test_the_blur_follows_the_contour_when_there_is_one(self):
        square = [[[16, 16], [48, 16], [48, 48], [16, 48]]]
        boxed = blur_detections(_stripes(), [dets.detection(box=[0, 0, 64, 64], label='face')],
                                blur_ratio=15, progressive_blur=0)
        shaped = blur_detections(_stripes(), [dets.detection(box=[0, 0, 64, 64], label='face',
                                                             polygons=square)],
                                 blur_ratio=15, progressive_blur=0)
        original = _stripes()
        self.assertFalse((boxed[2:6, 2:6] == original[2:6, 2:6]).all(), 'the box blurs everything')
        self.assertTrue((shaped[2:6, 2:6] == original[2:6, 2:6]).all(), 'the contour does not')
        self.assertFalse((shaped[28:36, 28:36] == original[28:36, 28:36]).all())

    def test_a_deduced_box_outside_the_image_is_skipped(self):
        out = blur_detections(_stripes(), [{'box': [200, 200, 300, 300], 'label': 'face',
                                            'interpolated': True}], blur_ratio=15)
        self.assertTrue((out == _stripes()).all())


class RenderMediaTest(SimpleTestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_an_image_is_painted_with_its_detections_and_said_to_the_preview(self):
        source = os.path.join(self.folder, 'in.png')
        cv2.imwrite(source, _stripes())
        seen = []
        frames = {0: [dets.detection(box=[8, 8, 40, 40], label='face')]}
        written = dets.render_media(
            source, frames, lambda image, found: blur_detections(image, found, blur_ratio=15),
            os.path.join(self.folder, 'out', 'in_blurred.png'),
            on_frame=lambda i, original, painted, found: seen.append((i, len(found))))
        self.assertTrue(written.endswith('in_blurred.png'))
        out = cv2.imread(written)
        self.assertFalse((out[16:32, 16:32] == _stripes()[16:32, 16:32]).all())
        self.assertTrue((out[50:, 50:] == _stripes()[50:, 50:]).all())
        self.assertEqual([(0, 1)], seen)

    def test_an_image_without_detection_is_written_as_is(self):
        source = os.path.join(self.folder, 'in.png')
        cv2.imwrite(source, _stripes())
        painted = []
        written = dets.render_media(source, {}, lambda image, found: painted.append(1) or image,
                                    os.path.join(self.folder, 'same.png'))
        self.assertEqual([], painted, 'no detection : no paint')
        self.assertTrue((cv2.imread(written) == _stripes()).all())

    def test_an_unreadable_image_says_so(self):
        source = os.path.join(self.folder, 'broken.png')
        with open(source, 'wb') as out:
            out.write(b'not an image')
        with self.assertRaises(RuntimeError):
            dets.render_media(source, {}, lambda image, found: image,
                              os.path.join(self.folder, 'x.png'))
