"""Detection by an ENSEMBLE of models (2026-10-10) — held without any model loaded.

A frame detector writes only `detect_frames` : the common loop keeps the asked classes above
its threshold and builds the document ; documents of several detectors are joined ; ultralytics
models go through `Anonymize`, any other through its own backend ; the coverage adds models per
class and ranks them by their MEASURED miss rate when the whole lot is measured ; the recall
bench counts containers.
"""
import os
import shutil
import tempfile
from unittest import mock

import cv2
import numpy as np
from django.test import SimpleTestCase, TestCase

from wama.common.utils import detections as dets


def _doc(engine, models, frames, tag=None):
    doc = dets.new_document(media='video', width=64, height=48, fps=10, frame_count=5,
                            engine=engine, models=models, classes=['plate'])
    for index, found in frames.items():
        dets.add(doc, index, found)
    if tag:
        doc['tag'] = tag
    return doc


class MergeTest(SimpleTestCase):

    def test_frames_of_several_documents_are_joined_and_their_models_listed(self):
        a = _doc('yolo', ['faces.pt'], {0: [dets.detection(box=[1, 1, 9, 9], label='face')]})
        b = _doc('egoblur', ['anonymizer:egoblur-lp-gen1'],
                 {0: [dets.detection(box=[20, 20, 30, 25], label='license_plate')],
                  3: [dets.detection(box=[2, 2, 8, 8], label='license_plate')]})
        union = dets.merge([a, b])
        self.assertEqual(('yolo+egoblur', 'multi-model'), (union['engine'], union['tag']))
        self.assertEqual(['faces.pt', 'anonymizer:egoblur-lp-gen1'], union['models'])
        by_frame = {f['i']: [d['label'] for d in f['d']] for f in union['frames']}
        self.assertEqual({0: ['face', 'license_plate'], 3: ['license_plate']}, by_frame)

    def test_a_single_document_is_returned_as_is(self):
        a = _doc('yolo', ['x.pt'], {}, tag='yolo11n')
        self.assertIs(a, dets.merge([a]))


class _FakeDetector:
    """Built lazily : the base class lives behind the backend package import."""

    @staticmethod
    def make(results, batch=1):
        from wama.common.backends.detection_base import FrameDetectionBackend

        class Fake(FrameDetectionBackend):
            ENGINE = 'fake'
            name = 'fake'
            BATCH_SIZE = batch
            calls = []

            def load(self, model=None):
                self._on = True
                return True

            @property
            def is_loaded(self):
                return getattr(self, '_on', False)

            def unload(self):
                self._on = False

            def detect_frames(self, images, threshold):
                Fake.calls.append(len(images))
                return [results(len(Fake.calls) - 1, k) for k in range(len(images))]
        return Fake()


class FrameDetectionLoopTest(SimpleTestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.video = os.path.join(self.folder, 'clip.mp4')
        writer = cv2.VideoWriter(self.video, cv2.VideoWriter_fourcc(*'mp4v'), 10, (64, 48))
        for _ in range(5):
            writer.write(np.zeros((48, 64, 3), np.uint8))
        writer.release()

    def test_only_the_asked_classes_above_the_threshold_are_kept_by_batch(self):
        def results(call, k):
            return [dets.detection(box=[1, 1, 9, 9], label='License_Plate', conf=0.9),
                    dets.detection(box=[1, 1, 9, 9], label='car', conf=0.9),
                    dets.detection(box=[1, 1, 9, 9], label='plate', conf=0.1)]
        detector = _FakeDetector.make(results, batch=2)
        done = []
        doc = detector.detect(media_path=self.video, classes2blur=['plate'],
                              detection_threshold=0.25, progress=lambda d, t: done.append(d))
        self.assertEqual([2, 2, 1], type(detector).calls, 'frames go by batches of BATCH_SIZE')
        self.assertEqual([0, 1, 2, 3, 4], [f['i'] for f in doc['frames']])
        self.assertEqual({'License_Plate'}, {d['label'] for f in doc['frames'] for d in f['d']},
                         'the alias is kept, the car and the weak plate are dropped')
        self.assertEqual(('fake', 'video', 5, 'fake'),
                         (doc['engine'], doc['media'], doc['frame_count'], doc['tag']))
        self.assertEqual(5, done[-1])

    def test_a_failing_batch_leaves_its_frames_empty_and_the_media_goes_on(self):
        def results(call, k):
            if call == 1:
                raise RuntimeError('one batch fails')
            return [dets.detection(box=[1, 1, 9, 9], label='plate', conf=0.9)]
        detector = _FakeDetector.make(results, batch=2)
        doc = detector.detect(media_path=self.video, classes2blur=['plate'])
        self.assertEqual([0, 1, 4], [f['i'] for f in doc['frames']])


class EnsembleRoutingTest(SimpleTestCase):
    """Ultralytics models go TOGETHER through `Anonymize` ; every other model through ITS
    backend, with its own classes ; the documents are joined."""

    def test_each_model_goes_through_its_own_engine(self):
        from wama.common.services import detection_ensemble
        yolo = mock.Mock()
        yolo.return_value.detect.return_value = _doc(
            'yolo', ['faces.pt'], {0: [dets.detection(box=[1, 1, 9, 9], label='face')]})
        other = mock.Mock()
        other.detect.return_value = _doc(
            'egoblur', ['anonymizer:egoblur-lp-gen1'],
            {1: [dets.detection(box=[2, 2, 9, 9], label='license_plate')]})
        engines = {'anonymizer:yolo:faces.pt': 'ultralytics',
                   'anonymizer:egoblur-lp-gen1': 'torchscript'}
        with mock.patch.object(detection_ensemble, 'engine_of', side_effect=engines.get), \
                mock.patch('wama.common.backends.anonymize.Anonymize', yolo), \
                mock.patch('wama.common.backends.manager.backend_instance_for_key',
                           return_value=other) as door:
            doc = detection_ensemble.detect_with_models(
                [{'model_key': 'anonymizer:yolo:faces.pt', 'path': '/w/faces.pt',
                  'classes': ['face']},
                 {'model_key': 'anonymizer:egoblur-lp-gen1', 'classes': ['plate']}],
                media_path='/in/clip.mp4', classes2blur=['face', 'plate'])
        loaded = yolo.return_value.load_model.call_args.kwargs['models']
        self.assertEqual(['anonymizer:yolo:faces.pt'], [m['model_key'] for m in loaded])
        door.assert_called_once_with('anonymizer:egoblur-lp-gen1', None)
        self.assertEqual(['plate'], other.detect.call_args.kwargs['classes2blur'])
        self.assertEqual([0, 1], [f['i'] for f in doc['frames']])


class EnsembleCoverageTest(TestCase):
    """`models_per_class` adds models for the covered classes ; within a class whose whole lot
    is measured, the lowest MEASURED miss rate wins — before the specialisation proxy."""

    def setUp(self):
        from wama.model_manager.models import AIModel
        self.rows = {}
        for key, classes, vram in (('anonymizer:yolo:yolov8m-plates.pt', ['plate'], 0.4),
                                   ('anonymizer:egoblur-lp-gen1', ['license_plate'], 2.0),
                                   ('anonymizer:rtdetr-v2-license-plate', ['license_plate'], 1.0),
                                   ('anonymizer:yolo:faces.pt', ['face'], 0.2)):
            self.rows[key] = AIModel.objects.create(
                model_key=key, name=key.rsplit(':', 1)[-1], model_type='vision',
                source='anonymizer', is_downloaded=True, is_available=True, vram_gb=vram,
                capabilities={'task': 'detect', 'classes': classes})

    def _measure(self, key, miss):
        from wama.common.models import ResultEvaluation
        from wama.common.services.model_coverage import miss_metric
        ResultEvaluation.objects.create(
            app='model_manager', object_type='DetectionBench', object_id=self.rows[key].pk,
            model_key=key, metric=miss_metric('plate'), value=miss, direction='lower',
            protocol='containment_v1', reference_sha256='ref',
            detail={'errors': round(miss * 100), 'reference_length': 100, 'unit': 'object'})

    def _plates(self, **options):
        from wama.common.services.model_coverage import couvrir_classes
        result = couvrir_classes(['face', 'plate'], source='anonymizer',
                                 strategie='specialisation', **options)
        return [m['model_key'] for m in result['modeles'] if 'plate' in m['classes']]

    def test_one_model_per_class_by_default(self):
        self.assertEqual(1, len(self._plates()))

    def test_the_measured_lot_ranks_the_plate_detectors(self):
        self._measure('anonymizer:yolo:yolov8m-plates.pt', 0.87)
        self._measure('anonymizer:egoblur-lp-gen1', 0.40)
        self._measure('anonymizer:rtdetr-v2-license-plate', 0.60)
        self.assertEqual(['anonymizer:egoblur-lp-gen1', 'anonymizer:rtdetr-v2-license-plate'],
                         self._plates(models_per_class=2, taille_preferee='m'),
                         'the preferred size does not beat a measured recall')

    def test_a_lot_measured_in_part_is_not_ranked_by_measure(self):
        self._measure('anonymizer:egoblur-lp-gen1', 0.40)
        self.assertEqual('anonymizer:yolo:yolov8m-plates.pt',
                         self._plates(taille_preferee='m')[0],
                         'one unmeasured candidate : the old order holds')


class ContainmentCountsTest(SimpleTestCase):

    def test_a_near_container_is_found_when_a_detection_centre_falls_in_it(self):
        from wama.model_manager.services.bench import containment_counts
        ref = {'min_height': 45, 'containers': [
            [[0, 0, 100, 60], [200, 0, 260, 30]],       # near, far
            [[0, 0, 100, 60]]]}
        doc = _doc('x', [], {0: [dets.detection(box=[40, 40, 50, 46], label='plate'),
                                 dets.detection(box=[300, 100, 310, 104], label='plate')]})
        self.assertEqual({'near': 2, 'found': 1, 'missed': 1, 'detections': 2, 'inside': 1},
                         containment_counts(doc, ref))


class FrameDetectorResolutionTest(TestCase):
    """The two catalogue keys reach their backend by the common door (declared engine ↔
    `ENGINE`, served model)."""

    def test_the_declared_engines_resolve_to_their_backends(self):
        from wama.common.backends.manager import backend_for_key
        from wama.model_manager.models import AIModel
        for key, engine, expected in (
                ('anonymizer:egoblur-lp-gen1', 'torchscript', 'EgoBlurBackend'),
                ('anonymizer:rtdetr-v2-license-plate', 'transformers',
                 'HFObjectDetectionBackend')):
            AIModel.objects.create(model_key=key, name=key, model_type='vision',
                                   source='anonymizer', composition={'runtime': {'engine': engine}},
                                   capabilities={'task': 'detect', 'classes': ['license_plate']})
            with self.subTest(key=key):
                cls = backend_for_key(key)
                self.assertEqual(expected, getattr(cls, '__name__', None))
