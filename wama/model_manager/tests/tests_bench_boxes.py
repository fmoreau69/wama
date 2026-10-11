"""The TRUE-BOX bench (2026-10-10) : a published annotation is read in its native format, the
reference only points at it (relative paths — it survives the move of the datasets tree), and
each model is matched greedily at IoU 0.5 — what the dataset marks unusable is neither a miss nor
a false alarm. The detectors are loaded ONCE for the whole set."""
import json
import os
import shutil
import tempfile
from unittest import mock

from django.test import SimpleTestCase

WIDER = """0--Parade/a.jpg
2
10 10 20 20 0 0 0 0 0 0
50 50 8 8 2 0 0 1 0 0
0--Parade/empty.jpg
0
0 0 0 0 0 0 0 0 0 0
1--Handshaking/b.jpg
1
5 5 100 120 0 0 0 0 0 0
"""


class WiderReaderTest(SimpleTestCase):

    def test_the_official_text_is_read_with_its_invalid_faces_set_apart(self):
        from wama.common.utils.dataset_formats import read_wider_face
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, 'gt.txt')
        with open(path, 'w') as f:
            f.write(WIDER)
        entries = read_wider_face(path)
        self.assertEqual(['0--Parade/a.jpg', '0--Parade/empty.jpg', '1--Handshaking/b.jpg'],
                         [e['path'] for e in entries])
        self.assertEqual([[10, 10, 30, 30]], entries[0]['boxes'])
        self.assertEqual([[50, 50, 58, 58]], entries[0]['ignore'], 'invalid = 1 is set apart')
        self.assertEqual(([], []), (entries[1]['boxes'], entries[1]['ignore']),
                         'an image with no face carries one line of zeros, read as nothing')


class MatchTest(SimpleTestCase):

    def test_greedy_matching_by_confidence_with_ignored_objects(self):
        from wama.model_manager.services.bench import match_boxes
        truth = [[0, 0, 10, 10], [100, 100, 140, 140]]
        ignore = [[200, 200, 210, 210]]
        found = [([1, 1, 10, 10], 0.9), ([0, 0, 9, 10], 0.8),      # the second is a duplicate
                 ([201, 201, 210, 210], 0.7),                        # an ignored face : no fault
                 ([300, 300, 320, 320], 0.6)]                        # a false alarm
        counts = match_boxes(found, truth, ignore)
        self.assertEqual((2, 1, 1), (counts['truth'], counts['tp'], counts['fp']),
                         'the duplicate of a found face (two scales, two models) is MERGED : '
                         'neither a second hit nor a false alarm')
        self.assertEqual({'tiny': 1, 'medium': 1}, counts['truth_buckets'])
        self.assertEqual({'tiny': 1}, counts['hit_buckets'])


class ReferenceTest(SimpleTestCase):

    def test_the_reference_points_at_the_native_annotation_by_relative_paths(self):
        from wama.model_manager.services.bench import read_boxes_reference
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, 'sources', 'wider', 'images'))
        with open(os.path.join(root, 'sources', 'wider', 'gt.txt'), 'w') as f:
            f.write(WIDER)
        bench = os.path.join(root, 'benchmarks', 'faces')
        os.makedirs(bench)
        with open(os.path.join(bench, 'reference.json'), 'w') as f:
            json.dump({'class': 'face', 'format': 'wider_face',
                       'images': '../../sources/wider/images',
                       'annotations': '../../sources/wider/gt.txt'}, f)
        # The whole tree MOVES : the reference still resolves.
        moved = root + '_moved'
        shutil.move(root, moved)
        self.addCleanup(shutil.rmtree, moved, True)
        ref = read_boxes_reference(os.path.join(moved, 'benchmarks', 'faces', 'reference.json'))
        self.assertEqual(3, len(ref['entries']))
        self.assertTrue(ref['images'].startswith(moved))


class SpeedClockTest(SimpleTestCase):
    """The CLEAN processing time : the medium is read from a local copy made off the clock, the
    first pass warms the model up and is not counted."""

    def test_only_the_detection_calls_after_the_warm_up_are_counted(self):
        from wama.model_manager.services import bench
        source = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, source, True)
        path = os.path.join(source, 'a.JPG')
        with open(path, 'wb') as f:
            f.write(b'jpeg')
        seen = []
        detectors = mock.Mock()
        detectors.detect.side_effect = lambda **kw: seen.append(kw['media_path']) or {}
        clock = bench._SpeedClock()
        ticks = iter([0.0, 0.25, 1.0, 1.5])            # two counted calls : 0.25 s then 0.5 s
        with mock.patch.object(bench.time, 'perf_counter', side_effect=lambda: next(ticks)):
            for _ in range(2):
                clock.detect(detectors, path, classes2blur=['face'])
        folder = clock.folder
        clock.close()
        self.assertEqual(3, len(seen), 'one warm-up pass, then one pass per image')
        self.assertTrue(all(p.startswith(folder) and p.endswith('.jpg') for p in seen),
                        'the detector reads the LOCAL copy, never the share')
        self.assertEqual((2, 375.0), (clock.count, clock.ms_per_item()))
        self.assertEqual(250.0, clock.ms_per_item(3), 'a video : divided by its images')
        self.assertFalse(os.path.exists(folder))

    def test_the_clean_time_goes_to_the_common_eta_loop(self):
        """No speed store of its own : seconds per image under the CATALOGUE key, like the
        tokens of an LLM bench — where the slider of every app reads it."""
        from wama.model_manager.services import bench
        clock = bench._SpeedClock()
        clock.total, clock.count = 0.75, 2
        with mock.patch('wama.model_manager.services.eta_estimator.record_run') as record:
            self.assertEqual(375.0, clock.record('anonymizer:yolo:f.pt'))
        record.assert_called_once_with('anonymizer:yolo:f.pt', size=2, unit='image',
                                       process_seconds=0.75)
        clock.close()
        empty = bench._SpeedClock()
        with mock.patch('wama.model_manager.services.eta_estimator.record_run') as record:
            self.assertIsNone(empty.record('anonymizer:yolo:f.pt'))
        record.assert_not_called()
        empty.close()


class DetectorSetTest(SimpleTestCase):

    def test_the_models_are_loaded_once_for_many_media(self):
        from wama.common.services import detection_ensemble
        from wama.common.utils import detections as dets
        yolo = mock.Mock()
        yolo.return_value.detect.return_value = dets.new_document(media='image', width=8, height=8)
        with mock.patch.object(detection_ensemble, 'engine_of', return_value='ultralytics'), \
                mock.patch('wama.common.backends.anonymize.Anonymize', yolo):
            detectors = detection_ensemble.DetectorSet([{'model_key': 'anonymizer:yolo:f.pt',
                                                         'path': '/w/f.pt'}])
            for k in range(5):
                detectors.detect(media_path=f'/in/{k}.jpg', classes2blur=['face'])
        self.assertEqual(1, yolo.call_count)
        self.assertEqual(1, yolo.return_value.load_model.call_count)
        self.assertEqual(5, yolo.return_value.detect.call_count)
