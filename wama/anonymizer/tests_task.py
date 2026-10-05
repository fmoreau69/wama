"""The anonymizer task runs through the COMMON skeleton (`run_item_task`) as a pipeline of three
processes — « Détection » → « Floutage » → « Sortie » (`function_specs.PIPELINE`) : step P6 of
`WAMA_APP_GENERATION_ROUTE §10.6` (2026-10-03), detection and blur separated on 2026-10-04
(Fabien : « on sépare détection/segmentation et floutage »).

What is held here : the detection writes a `detections` document on the card and the blur reads
it ; a blur setting blurs again WITHOUT detecting ; a format setting replays the output alone ; a
detection setting, or a lost document, detects again ; a detection replayed alone keeps the
original the output process holds. The detector is a stand-in (`detect_media`) ; the blur is the
REAL one, on a small image.
"""
import os
import shutil
import tempfile
from unittest import mock

import cv2
import numpy as np
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from wama.anonymizer import tasks
from wama.anonymizer.models import Media
from wama.common.services import process_runs
from wama.common.tests.helpers import INLINE_CONVERSION, stand_in_conversion
from wama.common.utils import detections
from wama.common.utils.media_paths import app_media_dir, get_app_media_path

BOX = [8, 8, 40, 40]


def _street(path):
    """A real image : sharp vertical stripes, so that a blur shows."""
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[:, ::4] = 255
    cv2.imwrite(str(path), image)


def _document(box=BOX, tag='yolo11n'):
    doc = detections.new_document(media='image', width=64, height=64, engine='yolo',
                                  models=['yolo11n.pt'], classes=['face'])
    detections.add(doc, 0, [detections.detection(box=box, label='face', conf=0.9)])
    doc['tag'] = tag
    return doc


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                       'LOCATION': 'anonymizer-task-tests'}})
class AnonymizerTaskOnSkeletonTest(TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        media_root = override_settings(MEDIA_ROOT=self.root)
        media_root.enable()
        self.addCleanup(media_root.disable)
        self.addCleanup(shutil.rmtree, self.root, True)
        cache.clear()
        self.user = get_user_model().objects.create_user('anonymizer_skeleton', password='x')
        folder = get_app_media_path('anonymizer', self.user.id, 'input')
        folder.mkdir(parents=True, exist_ok=True)
        _street(folder / 'street.png')
        self.input = folder / 'street.png'
        self.media = Media.objects.create(
            user=self.user, file_ext='.png', status='PENDING', classes2blur=['face'],
            file=f"{app_media_dir('anonymizer', self.user.id, 'input')}/street.png")

    def _detected(self, **kwargs):
        self.engine_kwargs = kwargs
        return _document()

    _convert = staticmethod(stand_in_conversion)

    def _states(self):
        return {line.node_id: line.status for line in process_runs.lines(self.media)}

    def _started(self):
        return {line.node_id: line.started_at for line in process_runs.lines(self.media)}

    def _run(self, engine=None, process=None, **settings):
        if settings:
            Media.objects.filter(pk=self.media.pk).update(status='RUNNING', **settings)
        with mock.patch.object(tasks, 'detect_media', side_effect=engine or self._detected) as detected, \
                mock.patch(INLINE_CONVERSION, side_effect=self._convert), \
                mock.patch.object(tasks, 'needs_parallel_detection',
                                  return_value={'parallel': False, 'models': []}), \
                mock.patch('wama.anonymizer.utils.model_selector.select_model_by_precision',
                           return_value=None), \
                mock.patch('wama.anonymizer.utils.yolo_utils.get_model_path',
                           side_effect=lambda name, *a, **kw: f'/models/{name}'), \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            outcome = tasks.process_single_media.run(self.media.pk, process=process)
        self.media.refresh_from_db()
        return outcome, detected

    def _output_pixels(self):
        path = os.path.join(self.root, self.media.output_file.name)
        if path.endswith('.webp'):
            path = os.path.join(self.root, self.media.native_outputs[0])
        return cv2.imread(path)

    def test_the_detection_writes_its_document_and_the_blur_reads_it(self):
        outcome, detected = self._run()
        self.assertEqual({'processed': self.media.pk}, outcome)
        self.assertEqual(('SUCCESS', 100), (self.media.status, self.media.blur_progress))
        self.assertEqual({'detect': 'SUCCESS', 'blur': 'SUCCESS', 'output': 'SUCCESS'},
                         self._states())
        self.assertEqual(['face'], self.engine_kwargs['classes2blur'])
        self.assertTrue(self.media.detections_file.name.endswith(
            f'street_detections_yolo11n_{self.media.pk}.json'), self.media.detections_file.name)
        doc = detections.read(os.path.join(self.root, self.media.detections_file.name))
        self.assertEqual(1, detections.count(doc))
        self.assertTrue(self.media.output_file.name.endswith(
            f'street_blurred_yolo11n_{self.media.pk}.png'), self.media.output_file.name)
        original, blurred = cv2.imread(str(self.input)), self._output_pixels()
        inside = (slice(BOX[1] + 4, BOX[3] - 4), slice(BOX[0] + 4, BOX[2] - 4))
        self.assertGreater(np.abs(original[inside].astype(int) - blurred[inside]).mean(), 20,
                           'the detected zone is blurred')
        self.assertTrue((original[50:, 50:] == blurred[50:, 50:]).all(), 'nothing else is')
        self.assertEqual(self.media.detections_file.name,
                         process_runs.line(self.media, 'detect').output_ref)
        self.assertEqual([], self.media.native_outputs, 'nothing transformed : a single file')

    def test_a_blur_setting_blurs_again_without_detecting(self):
        self._run()
        before, first = self._started(), self._output_pixels()
        outcome, detected = self._run(blur_ratio=3)
        self.assertEqual('SUCCESS', self.media.status, self.media.error_message)
        detected.assert_not_called()
        after = self._started()
        self.assertEqual(before['detect'], after['detect'], 'the detection was up to date')
        self.assertNotEqual(before['blur'], after['blur'])
        self.assertFalse((first == self._output_pixels()).all(), 'a lighter blur is written')

    def test_a_detection_setting_detects_again(self):
        self._run()
        outcome, detected = self._run(detection_threshold=0.6)
        detected.assert_called_once()
        self.assertEqual(0.6, detected.call_args.kwargs['detection_threshold'])
        self.assertEqual({'detect': 'SUCCESS', 'blur': 'SUCCESS', 'output': 'SUCCESS'},
                         self._states())

    def test_a_display_setting_makes_nothing_stale(self):
        """What the preview shows (`show_*`) changes no file : no process goes stale — a launch
        then would replay everything only because the user asks for the result again."""
        from wama.anonymizer.function_specs import PIPELINE
        self._run()
        Media.objects.filter(pk=self.media.pk).update(show_boxes=False, show_labels=False,
                                                      show_preview=False)
        self.media.refresh_from_db()
        self.assertEqual(set(), PIPELINE.refresh(self.media))
        Media.objects.filter(pk=self.media.pk).update(blur_ratio=5)
        self.media.refresh_from_db()
        stale = PIPELINE.refresh(self.media)
        self.assertIn('blur', stale, 'counter-proof : a blur setting does')
        self.assertNotIn('detect', stale)

    def test_changing_the_format_replays_the_output_alone_and_keeps_the_blurred_original(self):
        self._run()
        before = self._started()
        outcome, detected = self._run(output_format='webp')
        self.assertEqual('SUCCESS', self.media.status, self.media.error_message)
        detected.assert_not_called()
        self.assertEqual(before['blur'], self._started()['blur'], 'the media was NOT blurred again')
        self.assertTrue(self.media.output_file.name.endswith('.webp'), self.media.output_file.name)
        self.assertTrue(self.media.native_outputs[0].endswith('.native.png'))
        outcome, detected = self._run(output_format='original')
        detected.assert_not_called()
        self.assertTrue(self.media.output_file.name.endswith('.png'))
        self.assertEqual([], self.media.native_outputs)

    def test_the_format_of_the_input_is_resolved_by_the_app(self):
        """« input » is not a format : the app resolves it — here the blur already wrote a PNG
        for a PNG source, so nothing is transformed and nothing is kept twice."""
        self._run()
        outcome, detected = self._run(output_format='input')
        detected.assert_not_called()
        self.assertTrue(self.media.output_file.name.endswith('.png'))
        self.assertEqual([], self.media.native_outputs)
        self.assertEqual('webp', tasks._output_format_for(
            mock.Mock(output_format='input', file_ext='.webp'), '/x/street_blurred.png'))

    def test_a_lost_detection_document_detects_again(self):
        self._run()
        os.remove(os.path.join(self.root, self.media.detections_file.name))
        Media.objects.filter(pk=self.media.pk).update(status='RUNNING')
        outcome, detected = self._run()
        detected.assert_called_once()
        self.assertTrue(os.path.exists(os.path.join(self.root, self.media.detections_file.name)))

    def test_the_detection_replayed_alone_keeps_the_original_of_the_output(self):
        """`drop_previous_outputs(natives=False)` : the document of the detection is ITS file ;
        the blurred original the output process keeps is not, and stays."""
        self._run(output_format='webp')
        kept = os.path.join(self.root, self.media.native_outputs[0])
        self.assertTrue(os.path.exists(kept))
        Media.objects.filter(pk=self.media.pk).update(status='RUNNING')
        outcome, detected = self._run(process='detect')
        detected.assert_called_once()
        self.assertTrue(os.path.exists(kept))

    def test_another_engine_replaces_the_previous_document(self):
        self._run()
        old = os.path.join(self.root, self.media.detections_file.name)
        outcome, detected = self._run(engine=lambda **kw: _document(tag='sam3'),
                                      detection_threshold=0.5)
        self.assertIn('detections_sam3', self.media.detections_file.name)
        self.assertFalse(os.path.exists(old))

    def test_a_blur_without_its_document_fails_and_says_why(self):
        self._run()
        Media.objects.filter(pk=self.media.pk).update(status='RUNNING', detections_file='')
        self.media.refresh_from_db()
        outcome, detected = self._run(process='blur')
        self.assertEqual('FAILURE', self.media.status)
        self.assertIn('aucune détection', self.media.error_message)

    def test_the_whole_queue_launcher_sets_running_and_the_task_id_before_sending(self):
        sent = mock.Mock(id='queue-task-1')
        with mock.patch.object(tasks.process_single_media, 'delay', return_value=sent) as delay, \
                mock.patch.object(tasks, 'close_old_connections'):
            tasks.process_user_media_batch.run(self.user.id)
        self.media.refresh_from_db()
        delay.assert_called_once_with(self.media.pk)
        self.assertEqual(('RUNNING', 'queue-task-1'), (self.media.status, self.media.task_id))

    def test_a_stale_redelivered_message_leaves_a_finished_media_untouched(self):
        """Card #741 (2026-09-29) : the media was relaunched under ANOTHER task and succeeded ; the
        old message, redelivered later, must not put it back « running » for ever."""
        Media.objects.filter(pk=self.media.pk).update(status='SUCCESS', task_id='the-relaunch')
        task = tasks.process_single_media
        task.push_request(id='the-old-message', retries=0, delivery_info={'redelivered': True})
        self.addCleanup(task.pop_request)
        with mock.patch.object(tasks, 'detect_media') as detected, \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            task.run(self.media.pk)
        self.media.refresh_from_db()
        detected.assert_not_called()
        self.assertEqual(('SUCCESS', 'the-relaunch'), (self.media.status, self.media.task_id))

    def test_a_failure_is_stated_on_the_media_and_the_locks_are_released(self):
        def broken(**kwargs):
            raise RuntimeError('the detector crashed')
        outcome, _ = self._run(broken)
        self.assertEqual('FAILURE', self.media.status)
        self.assertIn('the detector crashed', self.media.error_message)
        # Ce que le lancement avait PRÉVU et qui n'a pas joué reste « son tour n'est pas venu »
        # (`process_runs.plan`, 2026-10-05) — jamais « réussi » sous un process en échec.
        self.assertEqual({'detect': 'FAILURE', 'blur': 'PENDING', 'output': 'PENDING'},
                         self._states())
        self.assertIsNone(cache.get(f'anon_task_owner:media:{self.media.pk}'))
        self.assertIsNone(cache.get(f'anon_lock:media:{self.media.pk}'))

    def test_a_media_owned_by_another_task_is_skipped(self):
        cache.set(f'anon_task_owner:media:{self.media.pk}', 'another-task', timeout=60)
        outcome, detected = self._run()
        self.assertEqual('duplicate', outcome['reason'])
        detected.assert_not_called()
        self.assertEqual('PENDING', self.media.status)
        self.assertEqual('another-task', cache.get(f'anon_task_owner:media:{self.media.pk}'))

    def test_a_stop_asked_by_the_user_is_honoured_before_any_processing(self):
        tasks.stop_process(self.user.id)
        outcome, detected = self._run()
        self.assertEqual({'stopped': self.media.pk}, outcome)
        detected.assert_not_called()
        self.assertEqual('PENDING', self.media.status)
        self.assertIsNone(cache.get(f'anon_task_owner:media:{self.media.pk}'))

    def test_a_media_without_file_fails_and_says_why(self):
        Media.objects.filter(pk=self.media.pk).update(file='')
        outcome, detected = self._run()
        detected.assert_not_called()
        self.assertEqual('FAILURE', self.media.status)
        self.assertIn('sans fichier', self.media.error_message)


class DetectMediaRoutingTest(TestCase):
    """`detect_media` chooses the detector : SAM3 for a DESCRIPTION when it is installed and the
    prompt valid, otherwise — or when SAM3 fails — the YOLO detector, said in the console. Both
    return the document ; neither blurs."""

    def _route(self, *, installed=True, valid=True, sam3_raises=False, use_sam3=True):
        sam3_doc, yolo_doc = _document(tag='sam3'), _document(tag='yolo11n')
        processor = mock.Mock()
        processor.return_value.detect.side_effect = (
            RuntimeError('cuda out of memory') if sam3_raises else (lambda **kw: sam3_doc))
        yolo = mock.Mock()
        yolo.return_value.detect.return_value = yolo_doc
        with mock.patch.object(tasks, 'check_sam3_installed', return_value=installed), \
                mock.patch.object(tasks, 'validate_sam3_prompt',
                                  return_value=(valid, None if valid else 'empty')), \
                mock.patch('wama.common.backends.manager.backend_for_key', return_value=processor), \
                mock.patch.object(tasks.anonymize, 'Anonymize', yolo), \
                mock.patch.object(tasks, '_console') as console:
            doc = tasks.detect_media(media_path='/in/x.png', use_sam3=use_sam3,
                                     sam3_prompt='face', classes2blur=['face'], user_id=None)
        return doc['tag'], processor, yolo, console

    def test_a_description_goes_to_sam3(self):
        tag, processor, yolo, _ = self._route()
        self.assertEqual('sam3', tag)
        processor.return_value.load_model.assert_called_once_with('auto')
        yolo.assert_not_called()

    def test_without_sam3_or_with_an_invalid_prompt_yolo_detects(self):
        for kwargs in ({'installed': False}, {'valid': False}, {'sam3_raises': True}):
            with self.subTest(**kwargs):
                tag, _processor, yolo, _ = self._route(**kwargs)
                self.assertEqual('yolo11n', tag)
                yolo.return_value.load_model.assert_called_once()

    def test_classes_go_to_yolo_without_touching_sam3(self):
        tag, processor, yolo, _ = self._route(use_sam3=False)
        self.assertEqual('yolo11n', tag)
        processor.assert_not_called()
