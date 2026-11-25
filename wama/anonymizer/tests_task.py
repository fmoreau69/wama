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
            target_mode='classes',   # said : the description is the default since 2026-11-24
            file=f"{app_media_dir('anonymizer', self.user.id, 'input')}/street.png")
        #: Ce que rend la couverture COMMUNE des classes (`needs_parallel_detection`) : un
        #: détecteur qui couvre `face`. Jusqu'au 2026-10-12 elle rendait VIDE ici, et ces tests ne
        #: passaient que par le repli écrit en dur que R117 a retiré.
        self.cover = {'parallel': False, 'unsupported_classes': [],
                      'models': [{'id': 'detect/yolo11n.pt', 'path': '/models/yolo11n.pt',
                                  'model_key': 'anonymizer:yolo:yolo11n.pt', 'name': 'yolo11n.pt',
                                  'classes': ['face']}]}

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
                                  return_value=self.cover), \
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

    def test_an_auto_card_nothing_covers_stops_and_names_the_classes(self):
        """R117 (2026-10-12) : the old single-model selector fell back on a model written in the
        task (`yolov8m_faces&plates_720p.pt`) ; nothing installed covers the classes → the card
        fails and says which, no detector is guessed."""
        self.cover = {'parallel': False, 'models': [], 'unsupported_classes': ['face']}
        _outcome, detected = self._run(model_to_use='')
        self.assertEqual('FAILURE', self.media.status)
        self.assertIn('Aucun modèle installé ne détecte : face', self.media.error_message)
        detected.assert_not_called()

    def test_a_pointed_card_is_read_where_its_file_is(self):
        """Une card DÉSIGNÉE pointe son fichier (`media_paths.reference_or_copy`) : l'entrée vit
        dans `temp/`, rien n'est copié dans `anonymizer/input/`. Mesuré le 2026-10-05 (Discord,
        card #1036) : la tâche reconstruisait le chemin dans `input/` — « Input file not found »,
        puis « Image illisible ». La détection ET le floutage lisent le fichier de la card."""
        temp = get_app_media_path('anonymizer', self.user.id, 'input').parent.parent / 'temp'
        temp.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.input), str(temp / 'street.png'))
        Media.objects.filter(pk=self.media.pk).update(file=f'users/{self.user.id}/temp/street.png')
        outcome, detected = self._run()
        self.assertEqual('SUCCESS', self.media.status, self.media.error_message)
        self.assertEqual(str(temp / 'street.png'), self.engine_kwargs['media_path'])
        self.assertTrue(self.media.output_file.name.endswith(
            f'street_blurred_yolo11n_{self.media.pk}.png'), self.media.output_file.name)

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

    def test_a_render_mode_and_the_inversion_blur_again_without_detecting(self):
        """2026-11-25 (`ROADMAP §17quater` C) : a plain mask, then all but the selection — the
        settings reach the blur, which alone runs again."""
        self._run()
        before, original = self._started(), cv2.imread(str(self.input))
        inside = (slice(BOX[1] + 4, BOX[3] - 4), slice(BOX[0] + 4, BOX[2] - 4))
        _outcome, detected = self._run(blur_mode='mask', progressive_blur=0, rounded_edges=0)
        detected.assert_not_called()
        self.assertEqual(before['detect'], self._started()['detect'])
        self.assertTrue((self._output_pixels()[inside] == 0).all(), 'the face is masked')
        self._run(blur_invert=True)
        painted = self._output_pixels()
        self.assertTrue((painted[inside] == original[inside]).all(), 'the face stays sharp')
        self.assertTrue((painted[50:, 50:] == 0).all(), 'all the rest is masked')

    def test_a_qualified_card_blurs_from_the_qualified_objects_and_a_colour_can_stay_sharp(self):
        """2026-11-24 (`ROADMAP §17quater` B) : with the qualification on, each object gets its
        attributes, the blur reads THAT document (the nearest upstream, `upstream_output`) ;
        unticking the colour found blurs again only, and leaves the zone sharp."""
        outcome, _detected = self._run(qualify_objects=True)
        self.assertEqual('SUCCESS', self.media.status, self.media.error_message)
        self.assertEqual({'detect': 'SUCCESS', 'qualify': 'SUCCESS', 'blur': 'SUCCESS',
                          'output': 'SUCCESS'}, self._states())
        qualified = detections.read(os.path.join(self.root, self.media.qualified_file.name))
        attrs = qualified['frames'][0]['d'][0]['attrs']
        self.assertIn(attrs['color'], detections.colors(qualified))
        self.assertEqual([attrs['size']], detections.sizes(qualified))
        before = self._started()
        self._run(blur_skip_colors=[attrs['color']])
        after = self._started()
        self.assertEqual((before['detect'], before['qualify']), (after['detect'], after['qualify']),
                         'neither detected nor qualified again')
        self.assertNotEqual(before['blur'], after['blur'])
        original, blurred = cv2.imread(str(self.input)), self._output_pixels()
        self.assertTrue((original == blurred).all(), 'the colour unticked stays sharp')

    def test_a_description_asking_a_colour_qualifies_and_blurs_only_that_colour(self):
        """2026-11-25 (`ROADMAP §17quater` B) : « red face » understood — the dedicated detector
        looks for the face, the launch switches the qualification on BEFORE it chooses its steps,
        and the face found (black and white stripes) is not the one asked : it stays sharp. Asked
        « black face », the same face is blurred. The description was never understood before :
        it is understood at the start of the task, so the FIRST ▶ qualifies."""
        def understood(text, original=None):
            return {'prompt': text, 'original': original or text, 'enriched': True,
                    'translated': False}

        Media.objects.filter(pk=self.media.pk).update(
            target_mode='description', sam3_prompt='le visage rouge', sam3_prompt_processed='')
        with mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                        return_value=understood('red face', 'le visage rouge')), \
                mock.patch.object(tasks, 'check_sam3_installed', return_value=False):
            self._run()
        self.assertEqual('SUCCESS', self.media.status, self.media.error_message)
        self.assertEqual((True, False), (self.media.qualify_objects, self.media.qualify_depth),
                         'the request switches the qualification on, no plane asked : no depth')
        self.assertEqual('red face', self.media.sam3_prompt_processed, 'understood and kept')
        self.assertEqual({'detect': 'SUCCESS', 'qualify': 'SUCCESS', 'blur': 'SUCCESS',
                          'output': 'SUCCESS'}, self._states())
        doc = detections.read(os.path.join(self.root, self.media.detections_file.name))
        self.assertEqual([{'concept': 'face', 'by': ['anonymizer:yolo:yolo11n.pt'],
                           'attrs': {'color': 'red'}}], doc['plan'])
        original = cv2.imread(str(self.input))
        self.assertTrue((original == self._output_pixels()).all(), 'no red face : nothing blurred')
        Media.objects.filter(pk=self.media.pk).update(sam3_prompt_processed='black face')
        with mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                        return_value=understood('black face')), \
                mock.patch.object(tasks, 'check_sam3_installed', return_value=False):
            self._run()
        inside = (slice(BOX[1] + 4, BOX[3] - 4), slice(BOX[0] + 4, BOX[2] - 4))
        self.assertGreater(np.abs(original[inside].astype(int) - self._output_pixels()[inside]).mean(),
                           20, 'the black face asked is blurred')

    def test_a_relation_blurs_the_face_of_the_described_person_and_never_the_person(self):
        """2026-11-25 (`ROADMAP §17quater` B, relations) : « face of red person » — the person is
        looked for too, qualified (black and white stripes), and the face it holds is not the one
        asked : nothing is blurred. « face of black person » : the face only — the person, searched
        to relate, stays sharp around it."""
        def understood(text):
            return {'prompt': text, 'original': text, 'enriched': True, 'translated': False}

        def people(**kwargs):
            self.engine_kwargs = kwargs
            doc = _document()
            doc['frames'][0]['d'].append(detections.detection(box=[0, 0, 64, 64], label='person',
                                                              conf=0.9))
            return doc

        self.cover = {**self.cover, 'models': [{**self.cover['models'][0],
                                                'classes': ['face', 'person']}]}
        original = cv2.imread(str(self.input))
        inside = (slice(BOX[1] + 4, BOX[3] - 4), slice(BOX[0] + 4, BOX[2] - 4))
        for asked, face_blurred in (('face of red person', False), ('face of black person', True)):
            Media.objects.filter(pk=self.media.pk).update(
                target_mode='description', sam3_prompt=asked, sam3_prompt_processed=asked)
            with self.subTest(asked), \
                    mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                               return_value=understood(asked)), \
                    mock.patch.object(tasks, 'check_sam3_installed', return_value=False):
                self._run(engine=people)
                self.assertEqual('SUCCESS', self.media.status, self.media.error_message)
                self.assertTrue(self.media.qualify_objects, "the owner's colour is measured")
                blurred = self._output_pixels()
                self.assertEqual(face_blurred,
                                 np.abs(original[inside].astype(int) - blurred[inside]).mean() > 20)
                self.assertTrue((original[50:, 50:] == blurred[50:, 50:]).all(),
                                'the person, searched to relate, is never blurred')

    def test_a_detection_setting_detects_again(self):
        self._run()
        outcome, detected = self._run(precision_level=90)
        detected.assert_called_once()
        self.assertEqual({'detect': 'SUCCESS', 'blur': 'SUCCESS', 'output': 'SUCCESS'},
                         self._states())

    def test_the_detection_runs_at_the_floor_and_a_threshold_only_blurs_again(self):
        """2026-11-25 (Fabien : « tout détecter, filtrer à l'affichage », a threshold per class next
        to « Ce qu'on floute ») : the detector is asked the common floor whatever the card's
        threshold ; raising a class's own threshold above the face's 0.9 leaves it sharp without
        detecting again, and the common threshold applies to the other classes."""
        from wama.common.utils.detections import DETECTION_FLOOR
        original = cv2.imread(str(self.input))
        inside = (slice(BOX[1] + 4, BOX[3] - 4), slice(BOX[0] + 4, BOX[2] - 4))
        outcome, detected = self._run(detection_threshold=0.6)
        self.assertEqual(DETECTION_FLOOR, detected.call_args.kwargs['detection_threshold'])
        self.assertGreater(np.abs(original[inside].astype(int) - self._output_pixels()[inside]).mean(), 20,
                           'the face (0.9) is above the common 0.6 : blurred')
        outcome, detected = self._run(blur_class_thresholds={'human face': 0.95})
        detected.assert_not_called()
        self.assertEqual({'detect': 'SUCCESS', 'blur': 'SUCCESS', 'output': 'SUCCESS'}, self._states())
        self.assertTrue((original[inside] == self._output_pixels()[inside]).all(),
                        'its own threshold, under another name of the class, leaves it sharp')
        outcome, detected = self._run(blur_class_thresholds={'plate': 0.95})
        self.assertGreater(np.abs(original[inside].astype(int) - self._output_pixels()[inside]).mean(), 20,
                           "counter-proof : another class's threshold does not touch the face")

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

    def test_the_prolonging_setting_replays_the_blur_not_the_detection(self):
        """`max_extrapolation_frames` (2026-10-05) is read when blurring, from the detections
        already found : changing it never re-detects."""
        from wama.anonymizer.function_specs import PIPELINE
        self._run()
        Media.objects.filter(pk=self.media.pk).update(max_extrapolation_frames=12)
        self.media.refresh_from_db()
        stale = PIPELINE.refresh(self.media)
        self.assertIn('blur', stale)
        self.assertNotIn('detect', stale)

    def _blur_reading(self, media_kind, **settings):
        """The arguments the blur gives the common reading of the detections."""
        def engine(**kwargs):
            doc = _document()
            doc['media'] = media_kind
            return doc
        with mock.patch.object(detections, 'by_frame', wraps=detections.by_frame) as reading:
            self._run(engine=engine, **settings)
        self.assertEqual('SUCCESS', self.media.status, self.media.error_message)
        return reading.call_args.kwargs

    def test_a_video_blur_passes_the_card_interpolation_and_prolonging(self):
        """Wiring that no error would reveal : a lost setting only blurs less."""
        kwargs = self._blur_reading('video', interpolate_detections=True,
                                    max_interpolation_frames=20, max_extrapolation_frames=7)
        self.assertEqual((True, 20, 7), (kwargs['interpolate'], kwargs['max_gap'],
                                         kwargs['max_extrapolation']))

    def test_an_image_is_never_interpolated_nor_prolonged(self):
        kwargs = self._blur_reading('image', interpolate_detections=True,
                                    max_interpolation_frames=20, max_extrapolation_frames=7)
        self.assertEqual((False, 0), (bool(kwargs['interpolate']), kwargs['max_extrapolation']))


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

    def test_the_original_format_is_the_deposited_one_and_nothing_is_kept_twice(self):
        """« Original » is the format of the DEPOSITED file, which the blur writes itself
        (2026-10-28) : nothing to convert, no original kept twice — the rule of every app."""
        self._run()
        self.assertTrue(self.media.output_file.name.endswith('.png'))
        self.assertEqual([], self.media.native_outputs)
        self.assertFalse(hasattr(tasks, '_output_format_for'),
                         'no resolution of its own : the common output settings')

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
                                      precision_level=90)
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
        """The queue launcher is the common one since 2026-10-29 (`item_views.start_queue`, the
        batch chain `process_user_media_batch` retired) — through the app's own declaration."""
        from wama.anonymizer.models import Media
        from wama.common.utils.item_views import declaration_for, start_queue
        sent = mock.Mock(id='queue-task-1')
        with mock.patch.object(tasks.process_single_media, 'delay', return_value=sent) as delay:
            start_queue(declaration_for(Media), self.user)
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

    def _route(self, *, installed=True, valid=True, sam3_raises=False, use_sam3=True,
               model_path='/models/yolo11n.pt'):
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
            # Le repli YOLO arrive préparé par la tâche (la couverture commune, R117).
            doc = tasks.detect_media(media_path='/in/x.png', use_sam3=use_sam3,
                                     sam3_prompt='face', classes2blur=['face'], user_id=None,
                                     model_path=model_path)
        return doc['tag'], processor, yolo, console

    def test_a_failed_sam3_without_a_covering_detector_says_so(self):
        """No fallback model is invented any more (R117) : the failure names the classes."""
        with self.assertRaisesRegex(ValueError, 'SAM3 not installed .*face'):
            self._route(installed=False, model_path=None)

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


class SegmentationNoteTest(TestCase):
    """Card #1026 (2026-10-05) : slider at 50, faces blurred as RECTANGLES, nothing said — the
    only face segmentation model of the catalogue was not installed. The note names it."""

    def setUp(self):
        from wama.model_manager.models import AIModel
        self.user = get_user_model().objects.create_user('anonymizer_seg_note', password='x')
        AIModel.objects.create(model_key='anonymizer:face_yolov8m-seg_60.pt',
                               name='face_yolov8m-seg_60', model_type='vision', source='anonymizer',
                               is_available=False,
                               capabilities={'task': 'segment', 'classes': ['face']})

    def _note(self, polygons=None, **settings):
        media = Media(user=self.user, classes2blur=['face'], **settings)
        doc = _document()
        if polygons:
            doc['frames'][0]['d'][0]['polygons'] = polygons
        return tasks._segmentation_note(media, doc)

    def test_asked_and_missed_it_names_the_model_to_install(self):
        note = self._note(precision_level=60, use_segmentation=False)
        self.assertIn('face_yolov8m-seg_60.pt', note)
        self.assertIn('rectangulaires', note)

    def test_nothing_is_said_when_it_was_not_asked_or_took_place(self):
        self.assertEqual('', self._note(precision_level=30, use_segmentation=False))
        self.assertEqual('', self._note(precision_level=60, polygons=[[[8, 8], [40, 8], [40, 40]]]))


class Sam3StatusWithoutImportTest(TestCase):
    """The SAM3 chip of the panel asks its status on EVERY anonymizer page (`sam3/status/`), and
    the model discovery asks it too. `import sam3` cost 57 s (torch included, measured on
    2026-10-13): a fresh gunicorn worker hung on it, the page never reached network idle and
    five browser gestures of the anonymizer went red. The status reads the venv, never imports."""

    def _status_importing(self):
        import builtins
        from wama.anonymizer.utils import sam3_manager
        real_import, imported = builtins.__import__, []

        def spy(name, *args, **kwargs):
            if name == 'sam3' or name.startswith('sam3.'):
                imported.append(name)
            return real_import(name, *args, **kwargs)
        with mock.patch('builtins.__import__', spy):
            status = sam3_manager.get_sam3_status()
        return status, imported

    def test_the_status_never_imports_the_package(self):
        status, imported = self._status_importing()
        self.assertEqual([], imported, 'the status must read the venv, not import sam3')
        self.assertIn('installed', status)

    def test_installed_follows_the_venv_and_the_version_its_metadata(self):
        import importlib.util
        from wama.anonymizer.utils import sam3_manager
        present = importlib.util.find_spec('sam3') is not None
        status, _ = self._status_importing()
        self.assertEqual(present, status['installed'])
        if present:
            from importlib.metadata import version
            self.assertEqual(version('sam3'), status['version'])
        with mock.patch('importlib.util.find_spec', return_value=None):
            absent = sam3_manager.get_sam3_status()
        self.assertFalse(absent['installed'])
        self.assertFalse(absent['ready'])
        self.assertTrue(absent['error'])


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                       'LOCATION': 'anonymizer-track-tests'}})
class DesignatedObjectTrackingTest(TestCase):
    """2026-11-16 : an object the detection missed is DESIGNATED by a click and followed by the
    common loop (`playhead_follow`), slice by slice (`object_tracking`), by the tracking engine of
    the catalogue — the server leaves PROPOSALS, it never writes the corrections."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user('anonymizer_tracking', password='x')
        self.other = get_user_model().objects.create_user('anonymizer_tracking_other', password='x')
        # Les routes de l'app passent le portier d'accès : le rôle qui ouvre l'anonymizer.
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX
        role = Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0]
        self.user.groups.add(role)
        self.other.groups.add(role)
        self.media = Media.objects.create(user=self.user, file_ext='.mp4', media_type='video',
                                          status='SUCCESS', file='users/0/anonymizer/input/clip.mp4')
        self.cursor = f'/anonymizer/track/{self.media.pk}/cursor/'
        self.results = f'/anonymizer/track/{self.media.pk}/results/'

    def _post(self, payload):
        import json
        return self.client.post(self.cursor, json.dumps(payload), content_type='application/json')

    def test_the_cursor_is_posted_and_the_loop_spawned_once(self):
        self.client.force_login(self.user)
        target = {'id': 'a', 'i': 3, 'point': [10, 12]}
        with mock.patch.object(tasks.live_track_task, 'delay') as delay:
            first = self._post({'targets': [target]}).json()
            second = self._post({'targets': [target]}).json()
            self.assertEqual(400, self._post({'targets': [{'id': 'a', 'i': 0, 'point': [1]}]}).status_code)
            self.assertEqual(400, self._post({'targets': []}).status_code)
        self.assertEqual((True, True, False), (first['ok'], first['started'], second['started']))
        delay.assert_called_once_with(self.media.pk)
        self.assertEqual({'targets': [{'id': 'a', 'i': 3, 'point': [10.0, 12.0]}]},
                         cache.get(tasks.track_channel(self.media.pk).key('cursor')))
        self.assertEqual({'next': 0, 'running': False, 'results': []},
                         self.client.get(self.results).json())
        self.client.force_login(self.other)
        self.assertEqual(404, self._post({'targets': [target]}).status_code)
        self.assertEqual(404, self.client.get(self.results).status_code)

    def test_the_loop_follows_slice_by_slice_and_leaves_proposals_only(self):
        from wama.common.services import playhead_follow
        channel = tasks.track_channel(self.media.pk)
        total, window = 200, 90

        class Engine:
            supports_object_tracking = True
            TRACK_WINDOW = window
            calls, loaded, unloaded = [], [], []

            def load_model(self, kind):
                self.loaded.append(kind)

            def unload(self):
                self.unloaded.append(1)

            def track_object(self, path, frame, *, count, reverse=False, point=None, box=None):
                self.calls.append((frame, reverse))
                spanned = (range(frame, max(frame - count, -1), -1) if reverse
                           else range(frame, min(frame + count, total)))
                found = [{'i': i, 'box': [i, 0, i + 4, 4]} for i in spanned]
                if reverse:                               # the last slice : the page stops the loop
                    cache.set(channel.key('stop'), 'user', timeout=60)
                return found

        playhead_follow.post_cursor(channel, {'targets': [{'id': 'a', 'i': 50, 'point': [5.0, 5.0]}]},
                                    lambda: None)
        with mock.patch('wama.common.backends.manager.backend_for_key', return_value=Engine), \
                mock.patch.object(tasks, 'check_sam3_installed', return_value=True), \
                mock.patch.object(tasks, 'close_old_connections'):
            outcome = tasks.live_track_task.apply(args=[self.media.pk]).get()
        self.assertEqual({'ok': True, 'reason': 'user'}, outcome)
        self.assertEqual((['tracker'], [1]), (Engine.loaded, Engine.unloaded), 'loaded once, released')
        self.assertEqual([(50, False), (139, False), (50, True)], Engine.calls)
        results = playhead_follow.results_since(channel, 0)['results']
        self.assertEqual([False, False, True], [r['done'] for r in results])
        seen = [f['i'] for r in results for f in r['frames']]
        self.assertEqual(sorted(range(total)), sorted(seen), 'every frame proposed once')
        self.media.refresh_from_db()
        self.assertFalse(self.media.detection_corrections, 'the server writes no correction')

    def test_an_engine_that_cannot_track_says_so_in_the_results(self):
        from wama.common.services import playhead_follow
        channel = tasks.track_channel(self.media.pk)
        playhead_follow.post_cursor(channel, {'targets': [{'id': 'a', 'i': 0, 'point': [1.0, 1.0]}]},
                                    lambda: None)
        with mock.patch.object(tasks, 'check_sam3_installed', return_value=False), \
                mock.patch.object(tasks, 'close_old_connections'):
            outcome = tasks.live_track_task.apply(args=[self.media.pk]).get()
        self.assertFalse(outcome['ok'])
        self.assertIn('SAM3', playhead_follow.results_since(channel, 0)['results'][0]['error'])
