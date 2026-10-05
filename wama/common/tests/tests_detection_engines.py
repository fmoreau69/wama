"""The two engines of the anonymizer DETECT and return a `detections` document (2026-10-04) —
they no longer blur nor write. Held here without any model loaded : YOLO keeps only the asked
classes (aliases included) above the threshold, prefixes each track with the rank of its model,
turns segmentation contours into polygons, and joins the passes of several models per frame ;
SAM3 turns its masks into polygons labelled by their concept, under its confidence threshold.
"""
import os
import shutil
import tempfile
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np
import torch
from django.test import SimpleTestCase

from wama.common.utils import detections as dets


def _box(xyxy, cls, conf, track=None):
    return SimpleNamespace(xyxy=torch.tensor([xyxy], dtype=torch.float32),
                           cls=torch.tensor(cls), conf=torch.tensor(conf),
                           id=None if track is None else torch.tensor(track))


def _result(boxes, names, contours=None, image=None):
    return SimpleNamespace(boxes=boxes, names=names,
                           masks=SimpleNamespace(xy=contours) if contours is not None else None,
                           orig_img=image if image is not None else np.zeros((64, 64, 3), np.uint8))


class YoloDetectorTest(SimpleTestCase):

    def _engine(self, models):
        from wama.common.backends.anonymize import Anonymize
        engine = Anonymize.__new__(Anonymize)
        engine.models, engine.model = models, models[0]['yolo'] if models else None
        engine.model_name = models[0]['name'] if models else None
        engine.task, engine.ret_mask, engine.device, engine.conf = 'detect', False, 'cpu', 0.25
        engine.input_path, engine.classes2blur = None, ['face']
        return engine

    def test_only_the_asked_classes_above_the_threshold_with_their_track_and_contour(self):
        engine = self._engine([])
        entry = {'classes': None, 'seg': True}
        result = _result([_box([1, 2, 30, 40], 0, 0.9, track=3), _box([5, 5, 9, 9], 1, 0.95),
                          _box([0, 0, 20, 20], 0, 0.1)],
                         names={0: 'Face', 1: 'car'},
                         contours=[np.array([[2, 3], [29, 3], [29, 39], [2, 39]], np.float32),
                                   np.zeros((0, 2)), np.zeros((0, 2))])
        found = list(engine._frame_detections(2, entry, result, ['face'], 0.25))
        self.assertEqual(1, len(found), 'the car and the face under the threshold are dropped')
        face = found[0]
        self.assertEqual(('Face', 'm2:3', [1, 2, 30, 40]), (face['label'], face['track'], face['box']))
        self.assertEqual(1, len(face['polygons']))

    def test_an_alias_of_the_asked_class_is_accepted(self):
        engine = self._engine([])
        result = _result([_box([1, 1, 20, 20], 0, 0.8)], names={0: 'License_Plate'})
        found = list(engine._frame_detections(0, {'classes': None, 'seg': False}, result,
                                              ['plate'], 0.25))
        self.assertEqual(['License_Plate'], [d['label'] for d in found])
        self.assertNotIn('track', found[0], 'no tracker id : no track')
        self.assertNotIn('polygons', found[0], 'a detector draws no contour')

    def test_the_passes_of_two_models_are_joined_per_frame_on_an_image(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        source = os.path.join(folder, 'street.png')
        cv2.imwrite(source, np.zeros((48, 64, 3), np.uint8))
        faces = mock.Mock()
        faces.predict.return_value = [_result([_box([1, 1, 20, 20], 0, 0.9)], {0: 'face'})]
        plates = mock.Mock()
        plates.predict.return_value = [_result([_box([30, 30, 60, 40], 0, 0.8)], {0: 'plate'})]
        engine = self._engine([
            {'yolo': faces, 'name': 'faces.pt', 'classes': ['face'], 'seg': False,
             'class_list': ['face']},
            {'yolo': plates, 'name': 'plates.pt', 'classes': ['plate'], 'seg': False,
             'class_list': ['plate']}])
        shown = []
        with mock.patch.object(type(engine), '_reessayer',
                               lambda self, op, replier_sur_cpu=None: op()):
            doc = engine.detect(media_path=source, classes2blur=['face', 'plate'],
                                on_frame=lambda i, image, found: shown.append(len(found)))
        self.assertEqual(('image', 64, 48, 'yolo', 'multi-model'),
                         (doc['media'], doc['width'], doc['height'], doc['engine'], doc['tag']))
        self.assertEqual([0], [f['i'] for f in doc['frames']])
        self.assertEqual(['face', 'plate'], [d['label'] for d in doc['frames'][0]['d']])
        self.assertEqual([1, 2], shown, 'the preview of the 2nd pass shows both models')

    def test_a_model_that_covers_none_of_the_asked_classes_is_not_run(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        source = os.path.join(folder, 'street.png')
        cv2.imwrite(source, np.zeros((8, 8, 3), np.uint8))
        cars = mock.Mock()
        engine = self._engine([{'yolo': cars, 'name': 'cars.pt', 'classes': None, 'seg': False,
                                'class_list': ['car']}])
        doc = engine.detect(media_path=source, classes2blur=['face'])
        cars.predict.assert_not_called()
        self.assertEqual(0, dets.count(doc))


class Sam3DetectorTest(SimpleTestCase):

    def test_masks_become_polygons_labelled_by_concept_under_the_threshold(self):
        from wama.common.backends.sam3_processor import SAM3Processor
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        source = os.path.join(folder, 'street.png')
        cv2.imwrite(source, np.zeros((40, 40, 3), np.uint8))
        face = np.zeros((40, 40), np.float32)
        face[5:20, 5:20] = 1.0
        weak = np.zeros((40, 40), np.float32)
        weak[25:35, 25:35] = 1.0
        engine = SAM3Processor.__new__(SAM3Processor)
        engine.text_prompt, engine.input_path, engine.confidence_threshold = '', None, 0.3
        with mock.patch.object(SAM3Processor, '_ensure_image_model'), \
                mock.patch.object(SAM3Processor, '_segment',
                                  return_value=([face, weak], [0.9, 0.1], ['face', 'face'])):
            doc = engine.detect(media_path=source, sam3_prompt='face')
        self.assertEqual(('sam3', 'image', 'face', 'sam3'),
                         (doc['engine'], doc['media'], doc['prompt'], doc['tag']))
        found = doc['frames'][0]['d']
        self.assertEqual(1, len(found), 'the mask under the confidence threshold is dropped')
        self.assertEqual('face', found[0]['label'])
        x1, y1, x2, y2 = found[0]['box']
        self.assertTrue(4 <= x1 <= 6 and 18 <= x2 <= 20 and 4 <= y1 <= 6 and 18 <= y2 <= 20)
        self.assertTrue(found[0]['polygons'])

    def test_a_prompt_is_required(self):
        from wama.common.backends.sam3_processor import SAM3Processor
        engine = SAM3Processor.__new__(SAM3Processor)
        engine.text_prompt, engine.input_path = '', None
        with self.assertRaises(ValueError):
            engine.detect(media_path='/nowhere.png', sam3_prompt='  ')


class VideoDetectionTest(SimpleTestCase):
    """On a VIDEO both engines walk the frames : YOLO in a stream (`track(stream=True)` — no
    frame kept), SAM3 frame by frame ; the document says the video (fps, frame count) and keeps
    only the frames that carry a detection."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.source = os.path.join(self.folder, 'clip.mp4')
        writer = cv2.VideoWriter(self.source, cv2.VideoWriter_fourcc(*'mp4v'), 10, (64, 48))
        for _ in range(5):
            writer.write(np.zeros((48, 64, 3), np.uint8))
        writer.release()

    def test_yolo_streams_the_video_and_keeps_its_tracks(self):
        from wama.common.backends.anonymize import Anonymize
        faces = mock.Mock()
        faces.track.return_value = iter(
            [_result([_box([1, 1, 20, 20], 0, 0.9, track=7)] if i % 2 == 0 else [], {0: 'face'})
             for i in range(5)])
        engine = Anonymize.__new__(Anonymize)
        engine.models = [{'yolo': faces, 'name': 'faces.pt', 'classes': ['face'], 'seg': False,
                          'class_list': ['face']}]
        engine.model, engine.model_name = faces, 'faces.pt'
        engine.task, engine.ret_mask, engine.device, engine.conf = 'detect', False, 'cpu', 0.25
        engine.input_path, engine.classes2blur = None, ['face']
        done = []
        with mock.patch.object(Anonymize, '_reessayer', lambda self, op, replier_sur_cpu=None: op()):
            doc = engine.detect(media_path=self.source, classes2blur=['face'],
                                progress=lambda d, t: done.append((d, t)))
        self.assertTrue(faces.track.call_args.kwargs['stream'], 'no frame kept in memory')
        faces.predict.assert_not_called()
        self.assertEqual(('video', 10.0, 5), (doc['media'], doc['fps'], doc['frame_count']))
        self.assertEqual([0, 2, 4], [f['i'] for f in doc['frames']])
        self.assertEqual({'m0:7'}, {d['track'] for f in doc['frames'] for d in f['d']})
        self.assertEqual((5, 5), done[-1])

    def test_sam3_walks_the_frames_and_one_failing_frame_does_not_stop_the_media(self):
        from wama.common.backends.sam3_processor import SAM3Processor
        mask = np.zeros((48, 64), np.float32)
        mask[5:20, 5:20] = 1.0
        calls = []

        def segment(self_, pil):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('one frame fails')
            return [mask], [0.9], ['face']
        engine = SAM3Processor.__new__(SAM3Processor)
        engine.text_prompt, engine.input_path, engine.confidence_threshold = '', None, 0.3
        with mock.patch.object(SAM3Processor, '_ensure_image_model'), \
                mock.patch.object(SAM3Processor, '_segment', segment):
            doc = engine.detect(media_path=self.source, sam3_prompt='face')
        self.assertEqual(('video', 5), (doc['media'], doc['frame_count']))
        self.assertEqual([0, 2, 3, 4], [f['i'] for f in doc['frames']],
                         'the failing frame has no detection, the others go on')
