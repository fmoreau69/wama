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
import subprocess
import tempfile

import cv2
import numpy as np
from django.test import SimpleTestCase

from wama.common.tests.helpers import frame_times, media_streams, video_with_sound
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

    def test_nothing_is_deduced_beyond_the_setting_or_after_the_last(self):
        doc = self._doc((0, [0, 0, 10, 10], 'm0:1'), (10, [40, 0, 50, 10], 'm0:1'))
        self.assertEqual([0, 10], sorted(dets.by_frame(doc, interpolate=True, max_gap=5)),
                         'a 9-frame gap is above the setting')
        self.assertEqual(list(range(11)), sorted(dets.by_frame(doc, interpolate=True, max_gap=9)))
        self.assertEqual([0, 10], sorted(dets.by_frame(doc)), 'off : only what was seen')

    def test_detections_WITHOUT_a_track_are_linked_by_their_place(self):
        """Card #1026 (2026-10-05) : the tracker gives an id to CONFIRMED objects only — 82
        detections out of 533 had none, and their gaps were never filled."""
        doc = self._doc((20, [0, 0, 10, 10], None), (23, [3, 0, 13, 10], None))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5)
        self.assertEqual([20, 21, 22, 23], sorted(frames))
        self.assertEqual([1, 0, 11, 10], frames[21][0]['box'])

    def test_a_small_fast_object_is_followed_but_a_far_jump_is_not(self):
        """8-px faces moving 6 px per frame no longer overlap after three frames : the allowed
        shift grows with the frames elapsed. A face that appears elsewhere is another face."""
        doc = self._doc((0, [100, 100, 108, 108], None), (3, [119, 95, 127, 103], None),
                        (6, [300, 20, 308, 28], None))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5)
        self.assertEqual([0, 1, 2, 3, 6], sorted(frames))

    def test_the_closest_candidate_is_the_successor(self):
        doc = self._doc((0, [0, 0, 10, 10], None),
                        (2, [30, 0, 40, 10], None), (2, [4, 0, 14, 10], None))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5)
        self.assertEqual([2, 0, 12, 10], frames[1][0]['box'])

    def test_two_tracks_never_mix(self):
        doc = self._doc((0, [0, 0, 10, 10], 'm0:1'), (2, [90, 90, 99, 99], 'm1:1'),
                        (4, [40, 0, 50, 10], 'm0:1'))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5)
        deduced = [d for f in frames.values() for d in f if d.get('interpolated')]
        self.assertTrue(all(d['track'] == 'm0:1' for d in deduced))

    def test_an_object_slowing_down_in_a_gap_keeps_its_arrival_speed_first(self):
        # Arrives at 10 px per frame, leaves at 2 : the curve of the common gap filler (the one
        # of the cam_analyzer's ghosts) slows down along the gap, a straight line would not.
        doc = self._doc((0, [0, 0, 10, 10], None), (1, [10, 0, 20, 10], None),
                        (5, [34, 0, 44, 10], None), (6, [36, 0, 46, 10], None))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5)
        self.assertEqual([[19, 0, 29, 10], [26, 0, 36, 10], [31, 0, 41, 10]],
                         [frames[i][0]['box'] for i in (2, 3, 4)],
                         'straight line : [16…], [22…], [28…]')

    def _moving(self, frame_count=10):
        doc = dets.new_document(media='video', width=100, height=100, fps=30,
                                frame_count=frame_count)
        dets.add(doc, 4, [dets.detection(box=[20, 0, 30, 10], label='face')])
        dets.add(doc, 5, [dets.detection(box=[30, 0, 40, 10], label='face')])
        return doc

    def test_an_object_is_prolonged_before_its_first_and_after_its_last_detection(self):
        frames = dets.by_frame(self._moving(), max_extrapolation=2)
        self.assertEqual({2: [0, 0, 10, 10], 3: [10, 0, 20, 10], 6: [40, 0, 50, 10],
                          7: [50, 0, 60, 10]},
                         {i: f[0]['box'] for i, f in frames.items() if i not in (4, 5)},
                         'at its own speed, backward and forward ; no interpolation asked')
        prolonged = frames[7][0]
        self.assertEqual((True, True), (prolonged['interpolated'], prolonged['extrapolated']),
                         'deduced : the blur brings it back into the image')

    def test_prolonging_stops_at_the_ends_of_the_video_and_zero_means_never(self):
        frames = dets.by_frame(self._moving(frame_count=7), max_extrapolation=10)
        self.assertEqual([0, 1, 2, 3, 4, 5, 6], sorted(frames))
        self.assertEqual([4, 5], sorted(dets.by_frame(self._moving(), max_extrapolation=0)))

    def test_a_lone_detection_is_held_still_and_a_gap_end_is_not_doubled(self):
        doc = self._doc((3, [40, 40, 50, 50], None))      # length unknown : no bound after
        frames = dets.by_frame(doc, max_extrapolation=1)
        self.assertEqual([[40, 40, 50, 50]] * 2, [frames[2][0]['box'], frames[4][0]['box']])
        # Inside a FILLED gap nothing is prolonged : only the two ends of the object are.
        doc = self._doc((0, [0, 0, 10, 10], None), (4, [12, 0, 22, 10], None))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5, max_extrapolation=1)
        self.assertEqual([1, 1, 1, 1], [len(frames[i]) for i in (1, 2, 3, 5)])

    def test_a_jittery_arrival_is_read_over_several_frames_not_the_last_one(self):
        # The centre moves 10, 5, then 15 px : 10 per frame over the three, 15 on the last link
        # alone — a speed that would make the curve bulge, hence a straight line.
        doc = self._doc((0, [0, 0, 10, 10], None), (1, [10, 0, 20, 10], None),
                        (2, [15, 0, 25, 10], None), (3, [30, 0, 40, 10], None),
                        (7, [54, 0, 64, 10], None), (8, [56, 0, 66, 10], None))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5)
        self.assertEqual([39, 0, 49, 10], frames[4][0]['box'], 'last link only : [36…]')

    def test_the_setting_is_the_limit_with_no_hidden_ceiling(self):
        """Until 2026-10-05 the setting was capped at half a second without a word : 50 frames
        meant 7 at 15 frames per second (card #1026)."""
        self.assertEqual(50, dets.max_gap_for(15, 50))
        self.assertEqual(0, dets.max_gap_for(30, None))


class SegmentedShapesOverGapsTest(SimpleTestCase):
    """Card #1034 (SAM3, 2026-10-05) : no track, flickering objects — the gaps linked two
    different plates up to 26 sizes apart, and every deduced detection was a RECTANGLE."""

    def _doc(self, *seen):
        doc = dets.new_document(media='video', width=400, height=100, fps=25)
        for index, box, polygons in seen:
            dets.add(doc, index, [dets.detection(box=box, label='plate', polygons=polygons)])
        return doc

    def test_a_deduced_detection_keeps_the_shape_of_the_nearest_seen_one(self):
        # 3 px per frame : the shape moves with the box, taken from the NEAREST seen frame.
        triangle = [[[0, 0], [10, 0], [5, 10]]]
        moved = [[[12, 0], [22, 0], [17, 10]]]
        doc = self._doc((0, [0, 0, 10, 10], triangle), (4, [12, 0, 22, 10], moved))
        frames = dets.by_frame(doc, interpolate=True, max_gap=5, max_extrapolation=1)
        self.assertEqual([[[3, 0], [13, 0], [8, 10]]], frames[1][0]['polygons'], 'from frame 0')
        self.assertEqual([[[9, 0], [19, 0], [14, 10]]], frames[3][0]['polygons'], 'from frame 4')
        self.assertEqual([[[15, 0], [25, 0], [20, 10]]], frames[5][0]['polygons'],
                         'prolonged : the shape too')

    def test_an_object_that_vanishes_is_not_linked_to_another_one_far_away(self):
        # 20 frames later : the old tolerance (one size per missing frame) accepted 20.5 sizes.
        doc = self._doc((0, [0, 0, 10, 10], None), (1, [0, 0, 10, 10], None),
                        (21, [170, 0, 180, 10], None))
        frames = dets.by_frame(doc, interpolate=True, max_gap=25)
        self.assertEqual([0, 1, 21], sorted(frames), 'a plate 17 sizes away is another plate')

    def test_two_sizes_far_apart_are_not_the_same_object(self):
        doc = self._doc((0, [0, 0, 10, 10], None), (2, [2, 0, 32, 30], None))
        self.assertEqual([0, 2], sorted(dets.by_frame(doc, interpolate=True, max_gap=5)))


class BlurShapeTest(SimpleTestCase):
    """The blur of SEGMENTED detections (`blur_shapes`, 2026-10-05) : the whole image was blurred
    for each detection, and the finishes were ignored on a shape."""

    SQUARE = [[[20, 20], [40, 20], [40, 40], [20, 40]]]

    def _blur(self, shapes=None, **finish):
        from wama.common.utils.blur_utils import blur_shapes
        return blur_shapes(_stripes(), shapes or [self.SQUARE], blur_ratio=9, **finish)

    def test_two_neighbour_shapes_are_blurred_at_once_not_one_over_the_other(self):
        left = [[[4, 4], [20, 4], [20, 20], [4, 20]]]
        right = [[[24, 4], [40, 4], [40, 20], [24, 20]]]
        image = _stripes()
        mask = dets.polygons_to_mask(left + right, image.shape) > 0
        out = self._blur([left, right])
        self.assertTrue((out[mask] == cv2.GaussianBlur(image, (9, 9), 0)[mask]).all(),
                        'both exactly as one blur of the image — no cascade')

    def test_without_finishes_it_is_the_whole_image_blur_inside_the_shape(self):
        image = _stripes()
        mask = dets.polygons_to_mask(self.SQUARE, image.shape) > 0
        expected = image.copy()
        expected[mask] = cv2.GaussianBlur(image, (9, 9), 0)[mask]
        self.assertTrue((self._blur() == expected).all(), 'cropped = whole image, to the pixel')

    def test_enlargement_and_edges_widen_the_blurred_zone(self):
        untouched = _stripes()
        plain = (self._blur() != untouched).any(axis=2)
        for finish in ({'roi_enlargement': 2.0}, {'rounded_edges': 4}):
            wider = (self._blur(**finish) != untouched).any(axis=2)
            self.assertGreater(wider.sum(), plain.sum(), finish)
            self.assertTrue(wider[plain].all(), f'{finish} : never less than the shape')

    def test_a_reduction_narrows_the_blurred_zone_of_a_shape_and_of_a_box(self):
        """2026-10-06 (Fabien) : l'agrandissement RÉDUIT aussi (0,75–1,25)."""
        from wama.common.utils.blur_utils import blur_detection
        untouched = _stripes()
        plain = (self._blur() != untouched).any(axis=2).sum()
        narrow = (self._blur(roi_enlargement=0.75) != untouched).any(axis=2).sum()
        self.assertLess(narrow, plain, 'a shape')
        box = [20, 20, 40, 40]
        whole = (blur_detection(_stripes(), box, 'plate', 9, 0, 0, 1.0) != untouched).any(axis=2).sum()
        less = (blur_detection(_stripes(), box, 'plate', 9, 0, 0, 0.75) != untouched).any(axis=2).sum()
        self.assertLess(less, whole, 'a box')

    def test_a_shape_is_enlarged_like_a_box_around_its_centre_even_at_the_edge(self):
        """2026-10-06 (revérification « rien réinventé ») : la forme s'agrandit par le geste du
        rectangle (`Bounds.scale`), NON borné à l'image — la forme garde ses proportions, ce qui
        déborde de l'image n'est simplement pas dessiné."""
        from wama.common.utils.bounds import Bounds
        scaled = Bounds(0, 20, 20, 40).scale(None, 4.0)
        self.assertEqual((-10, 10, 30, 50), (scaled.x_min, scaled.y_min, scaled.x_max, scaled.y_max))
        edge = [[[0, 20], [20, 20], [20, 40], [0, 40]]]
        untouched = _stripes()
        wide = (self._blur([edge], roi_enlargement=4.0) != untouched).any(axis=2)
        columns, rows = np.where(wide.any(axis=0))[0], np.where(wide.any(axis=1))[0]
        self.assertEqual((0, 30), (columns.min(), columns.max()), 'twice as wide, from its centre')
        self.assertEqual((10, 50), (rows.min(), rows.max()), 'twice as tall, from its centre')

    def test_the_progressive_blur_fades_outward_and_keeps_the_shape_fully_blurred(self):
        image = _stripes()
        mask = dets.polygons_to_mask(self.SQUARE, image.shape) > 0
        soft = self._blur(progressive_blur=9)
        self.assertTrue((soft[mask] == cv2.GaussianBlur(image, (9, 9), 0)[mask]).all(),
                        'the shape itself : fully blurred')
        outside = (soft != image).any(axis=2) & ~mask
        self.assertTrue(outside.any(), 'the fade spreads outside the shape')


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


class RewriteMediaTest(SimpleTestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_an_image_is_painted_with_its_detections_and_said_to_the_preview(self):
        source = os.path.join(self.folder, 'in.png')
        cv2.imwrite(source, _stripes())
        seen = []
        frames = {0: [dets.detection(box=[8, 8, 40, 40], label='face')]}
        written = dets.rewrite_media(
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
        written = dets.rewrite_media(source, {}, lambda image, found: painted.append(1) or image,
                                    os.path.join(self.folder, 'same.png'))
        self.assertEqual([], painted, 'no detection : no paint')
        self.assertTrue((cv2.imread(written) == _stripes()).all())

    def test_an_unreadable_image_says_so(self):
        source = os.path.join(self.folder, 'broken.png')
        with open(source, 'wb') as out:
            out.write(b'not an image')
        with self.assertRaises(RuntimeError):
            dets.rewrite_media(source, {}, lambda image, found: image,
                              os.path.join(self.folder, 'x.png'))


class RewriteVideoTest(SimpleTestCase):
    """A VIDEO is re-written frame by frame, in ONE encoding into the container of the output
    path (2026-10-28 — it was an MJPEG intermediate, then H.264 into a forced `.mp4`) — only the
    frames that carry detections are painted."""

    def setUp(self):
        import shutil as _shutil
        if not _shutil.which('ffmpeg'):
            self.skipTest('ffmpeg absent')
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.source = os.path.join(self.folder, 'clip.mp4')
        writer = cv2.VideoWriter(self.source, cv2.VideoWriter_fourcc(*'mp4v'), 10, (64, 64))
        for _ in range(10):
            writer.write(_stripes())
        writer.release()

    def test_each_frame_is_painted_with_ITS_detections_in_the_container_asked(self):
        painted, seen = [], []
        frames = {3: [dets.detection(box=[8, 8, 40, 40], label='face')]}

        def paint(image, found):
            painted.append(len(found))
            return blur_detections(image, found, blur_ratio=15)

        written = dets.rewrite_media(
            self.source, frames, paint, os.path.join(self.folder, 'out', 'clip_blurred.mp4'),
            on_frame=lambda i, original, out, found: seen.append(i),
            progress=lambda done, total: None)
        self.assertTrue(written.endswith('clip_blurred.mp4') and os.path.isfile(written))
        self.assertEqual([1], painted, 'only frame 3 carries a detection')
        self.assertEqual(list(range(10)), seen)
        self.assertEqual(['clip_blurred.mp4'], os.listdir(os.path.join(self.folder, 'out')),
                         'no intermediate left behind')
        capture = cv2.VideoCapture(written)
        self.assertEqual(10, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        capture.release()

    def test_a_container_outside_the_table_comes_out_as_mp4(self):
        written = dets.rewrite_media(self.source, {}, lambda image, found: image,
                                     os.path.join(self.folder, 'clip_blurred.flv'))
        self.assertTrue(written.endswith('clip_blurred.mp4') and os.path.isfile(written))


class RewriteVideoKeepsItsSoundTest(SimpleTestCase):
    """The blurred video keeps the ORIGINAL format and its sound IN PHASE (2026-10-28, Fabien :
    « un fichier vidéo avec un audio doit bien être rendu avec son audio en sortie sans désynchro »).
    Real ffmpeg, real streams : the container of the deposited file, its audio stream COPIED (no
    re-encoding), and an audio as long as the video — a variable frame rate included, which the
    nominal rate read by OpenCV used to stretch or shrink."""

    def setUp(self):
        from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe
        self.ffmpeg = get_ffmpeg_exe()
        if not self.ffmpeg:
            self.skipTest('ffmpeg absent')
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def _source(self, name, audio_codec, video_filter=None):
        return video_with_sound(self.folder, name, audio_codec, video_filter)

    _streams = staticmethod(media_streams)

    def _rewrite(self, source, name):
        return dets.rewrite_media(source, {5: [dets.detection(box=[4, 4, 30, 30], label='face')]},
                                  lambda image, found: blur_detections(image, found, blur_ratio=9),
                                  os.path.join(self.folder, 'out', name))

    def _assert_in_phase(self, source, written):
        _, before = self._streams(source)
        _, after = self._streams(written)
        self.assertAlmostEqual(float(before['video']['duration']),
                               float(after['video']['duration']), delta=0.12)
        self.assertAlmostEqual(float(after['video']['duration']),
                               float(after['audio']['duration']), delta=0.12,
                               msg='the sound lasts as long as the picture')

    def test_an_mp4_stays_an_mp4_and_its_aac_audio_is_copied(self):
        source = self._source('talk.mp4', 'aac')
        written = self._rewrite(source, 'talk_blurred.mp4')
        container, streams = self._streams(written)
        self.assertIn('mp4', container)
        self.assertEqual('aac', streams['audio']['codec_name'])
        self._assert_in_phase(source, written)

    def test_a_matroska_keeps_its_container_and_its_opus_audio(self):
        source = self._source('talk.mkv', 'libopus')
        written = self._rewrite(source, 'talk_blurred.mkv')
        container, streams = self._streams(written)
        self.assertIn('matroska', container)
        self.assertEqual('opus', streams['audio']['codec_name'])
        self._assert_in_phase(source, written)

    _frame_times = staticmethod(frame_times)

    def test_a_variable_frame_rate_keeps_EVERY_frame_at_its_time(self):
        """Measured 2026-10-28 : on a variable-rate MATROSKA, OpenCV and `avg_frame_rate` both say
        20 frames/s for 45 frames in 3 s — rewritten at a constant rate, the video lasted 2.25 s
        for 3 s of sound ; an AVERAGE rate fixes the end, not the middle. Each frame is now
        written at ITS time (Fabien : « le son ne doit pas être étiré ») — compared frame by frame."""
        # 3 s of picture and sound : 20 frames/s for 1.5 s, then every other frame (10 frames/s).
        source = self._source('phone.mkv', 'libopus',
                              video_filter="select='lt(n\\,30)+not(mod(n\\,2))'")
        before = self._frame_times(source)
        self.assertEqual(45, len(before))
        capture = cv2.VideoCapture(source)
        nominal = capture.get(cv2.CAP_PROP_FPS)
        capture.release()
        # Counter-proof : a constant rate — the one OpenCV reads — misplaces the middle frames.
        self.assertGreater(max(abs(t - (before[0] + i / nominal)) for i, t in enumerate(before)),
                           0.4, 'the fixture must defeat a constant rate')
        written = self._rewrite(source, 'phone_blurred.mkv')
        after = self._frame_times(written)
        self.assertEqual(len(before), len(after))
        self.assertLess(max(abs(a - b) for a, b in zip(before, after)), 0.002,
                        'every frame at its original time')
        self._assert_in_phase(source, written)

    def test_the_frames_of_an_mp4_keep_their_times_and_the_audio_its_start(self):
        source = self._source('cfr.mp4', 'aac')
        written = self._rewrite(source, 'cfr_blurred.mp4')
        before, after = self._frame_times(source), self._frame_times(written)
        self.assertEqual(len(before), len(after))
        self.assertLess(max(abs(a - b) for a, b in zip(before, after)), 0.002)

    def test_an_audio_the_container_cannot_hold_is_encoded_at_its_own_times(self):
        """A `.mov` carries PCM audio ; rewritten into `.mp4` (a caller asking another container),
        PCM is not accepted as is : it is ENCODED (AAC), never stretched — its length is kept."""
        source = self._source('studio.mov', 'pcm_s16le')
        written = self._rewrite(source, 'studio_blurred.mp4')
        _, before = self._streams(source)
        _, after = self._streams(written)
        self.assertEqual('aac', after['audio']['codec_name'])
        self.assertAlmostEqual(float(before['audio']['duration']),
                               float(after['audio']['duration']), delta=0.05)
        self._assert_in_phase(source, written)

    def test_an_avi_is_written_with_the_mpeg4_codec_of_its_family(self):
        source = self._source('old.avi', 'libmp3lame')
        written = self._rewrite(source, 'old_blurred.avi')
        container, streams = self._streams(written)
        self.assertIn('avi', container)
        self.assertEqual('mpeg4', streams['video']['codec_name'])
        self.assertEqual('mp3', streams['audio']['codec_name'], 'its mp3 audio copied')

    def test_a_video_without_sound_stays_silent_and_does_not_fail(self):
        path = os.path.join(self.folder, 'mute.mp4')
        subprocess.run([self.ffmpeg, '-y', '-loglevel', 'error', '-f', 'lavfi',
                        '-i', 'testsrc=size=64x48:rate=20:duration=1', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', path], check=True)
        written = self._rewrite(path, 'mute_blurred.mp4')
        self.assertNotIn('audio', self._streams(written)[1])


class CorrectionsTest(SimpleTestCase):
    """Human corrections live APART from the detector's document (2026-10-10) and are re-applied
    at every blur : a removal takes the detection it overlaps, even moved a few pixels by a new
    detection run ; an addition enters as manual ; the detector's document is left untouched."""

    def _doc(self):
        doc = dets.new_document(media='image', width=100, height=100)
        dets.add(doc, 0, [dets.detection(box=[10, 10, 30, 30], label='face', conf=0.9),
                          dets.detection(box=[60, 60, 80, 80], label='face', conf=0.4)])
        return doc

    def test_a_removal_survives_a_box_moved_by_a_new_detection(self):
        doc = self._doc()
        fixed = dets.apply_corrections(doc, {'removed': [{'i': 0, 'box': [62, 61, 81, 82]}]})
        self.assertEqual([[10, 10, 30, 30]], [d['box'] for d in fixed['frames'][0]['d']])
        self.assertEqual(2, len(doc['frames'][0]['d']), "the detector's document is untouched")

    def test_an_addition_enters_as_manual_and_a_neighbour_is_not_removed(self):
        fixed = dets.apply_corrections(self._doc(), {
            'added': [{'i': 0, 'box': [40, 5, 50, 15], 'label': 'face'}],
            'removed': [{'i': 0, 'box': [0, 0, 12, 12]}]})       # barely touches the first face
        boxes = {tuple(d['box']): d.get('manual', False) for d in fixed['frames'][0]['d']}
        self.assertEqual({(10, 10, 30, 30): False, (60, 60, 80, 80): False,
                          (40, 5, 50, 15): True}, boxes)
        self.assertEqual({'added': 1, 'removed': 1}, fixed['corrected'])

    def test_no_correction_returns_the_document_itself(self):
        doc = self._doc()
        self.assertIs(doc, dets.apply_corrections(doc, {}))


class AgreementTest(SimpleTestCase):
    """`boxes_at` + `support` — l'accord géométrique entre sorties (M2/M6, 2026-10-16)."""

    def test_a_document_taken_four_times_larger_is_read_at_the_original_width(self):
        doc = dets.new_document(media='image', width=2320, height=1304)
        dets.add(doc, 0, [dets.detection(box=[400, 80, 440, 120], conf=0.8)])
        dets.add(doc, 3, [dets.detection(box=[0, 0, 8, 8])])
        self.assertEqual([([100.0, 20.0, 110.0, 30.0], 0.8)], dets.boxes_at(doc, width=580))
        self.assertEqual([([400, 80, 440, 120], 0.8)], dets.boxes_at(doc))

    def test_the_support_of_an_object_names_every_output_that_saw_it(self):
        groups = dets.support([('a', [10, 10, 20, 20]), ('b', [11, 10, 21, 20]),
                               ('c', [100, 100, 110, 110]), ('b', [10, 11, 20, 21])])
        self.assertEqual([{'a', 'b'}, {'c'}], [g['keys'] for g in groups])

    def test_a_shifted_box_below_the_overlap_opens_another_object(self):
        # Contre-épreuve : un voisin dans une foule n'est pas le même visage.
        groups = dets.support([('a', [10, 10, 20, 20]), ('b', [18, 10, 28, 20])])
        self.assertEqual(2, len(groups))
        self.assertEqual(1, len(dets.support([('a', [10, 10, 20, 20]), ('b', [18, 10, 28, 20])],
                                             iou=0.1)))
