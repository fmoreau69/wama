"""The anonymizer's model select on route F4b step ⑤ (2026-10-07): it lists by TASK and stores
catalogue KEYS — the pattern of the enhancer (`enhancer.tests.CatalogueKeysTest`).

Measured before switching: once document layout and open-vocabulary detection left `detect`
(`9c2b2e8e`), the task domain gives the same 32 models as the old `source='anonymizer'` one, all
served. A model of another source may still enter it tomorrow: the launch refuses what nothing
serves, with the reason.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase

from wama.anonymizer.models import Media

User = get_user_model()
YOLO_KEY = 'anonymizer:yolo:yolo11n.pt'
OTHER_SOURCE_KEY = 'huggingface:org/detr'


def _catalogue_rows():
    from wama.model_manager.models import AIModel
    for key, task in ((YOLO_KEY, 'detect'), ('anonymizer:sam3', 'segment'),
                      (OTHER_SOURCE_KEY, 'detect')):
        AIModel.objects.update_or_create(model_key=key, defaults=dict(
            name=key, model_type='vision', source=key.split(':')[0], is_downloaded=True,
            capabilities={'task': task, 'inputs_required': ['work_file']}))


class DeclaredDomainTest(SimpleTestCase):

    def test_the_select_lists_by_the_declared_tasks_and_carries_no_static_list(self):
        from wama.anonymizer.params import PARAMS_JSON
        from wama.anonymizer.utils.model_config import DETECTION_TASKS, MODEL_SPEC
        field = next(p for p in PARAMS_JSON if p['name'] == 'model_to_use')
        self.assertEqual(MODEL_SPEC, field['options_query'])
        self.assertNotIn('source', field['options_query'], 'a domain by source hides installed models')
        self.assertFalse(field.get('choices'), 'a static list would bring the bare-id key space back')
        self.assertEqual(','.join(DETECTION_TASKS), MODEL_SPEC['task'])

    def test_the_auto_coverage_reads_the_same_declaration(self):
        # ONE declaration: the select, the « auto » coverage and the view read the same object.
        from wama.anonymizer.utils import model_config, model_selector
        self.assertIs(model_config.DETECTION_TASKS, model_selector.DETECTION_TASKS)


class CatalogueKeyReadingTest(TestCase):

    def setUp(self):
        _catalogue_rows()

    def test_every_form_of_before_reads_as_its_key(self):
        from wama.anonymizer.utils.yolo_utils import catalogue_key_for
        for given, key in ((YOLO_KEY, YOLO_KEY), ('yolo:yolo11n.pt', YOLO_KEY),
                           ('detect/faces/yolo11n.pt', YOLO_KEY), ('sam3_vit_h', 'anonymizer:sam3'),
                           (OTHER_SOURCE_KEY, OTHER_SOURCE_KEY)):
            with self.subTest(given=given):
                self.assertEqual(key, catalogue_key_for(given))
        # Counter-check: what designates no catalogued model reads as « auto ».
        for given in ('auto', '', None, 'ghost.pt', 'default'):
            with self.subTest(given=given):
                self.assertEqual('', catalogue_key_for(given))

    def test_the_identifier_is_the_key_without_its_source(self):
        from wama.anonymizer.utils.yolo_utils import catalogue_id_for
        self.assertEqual('yolo:yolo11n.pt', catalogue_id_for(YOLO_KEY))
        self.assertEqual('org/detr', catalogue_id_for(OTHER_SOURCE_KEY))

    def test_the_task_helper_no_longer_rebuilds_a_key_of_its_own(self):
        # `tasks._catalogue_key` recomposed `anonymizer:<id>` — wrong for another source.
        from wama.anonymizer.tasks import _catalogue_key
        self.assertEqual(OTHER_SOURCE_KEY, _catalogue_key(OTHER_SOURCE_KEY))
        self.assertEqual(YOLO_KEY, _catalogue_key('/weights/detect/yolo11n.pt'))
        self.assertIsNone(_catalogue_key('ghost.pt'))


class WritersAndReadersTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        _catalogue_rows()
        self.user = User.objects.create_user('anon_keys', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])

    def _media(self, model):
        # The classes mode, said : the description is the default since 2026-11-24.
        return Media.objects.create(user=self.user, file='anonymizer/x/input/sample.png',
                                    model_to_use=model, target_mode='classes')

    def test_every_writer_stores_a_catalogue_key(self):
        for given, stored in (('yolo:yolo11n.pt', YOLO_KEY), (YOLO_KEY, YOLO_KEY),
                              ('sam3', 'anonymizer:sam3'), ('auto', 'auto'), (None, None)):
            with self.subTest(given=given):
                media = self._media(given)
                self.assertEqual(stored, Media.objects.get(pk=media.pk).model_to_use)

    def test_the_item_modal_gets_the_key_its_options_carry(self):
        from django.urls import reverse
        self.client.force_login(self.user)
        media = Media.objects.create(user=self.user, file='anonymizer/x/input/sample.png')
        Media.objects.filter(pk=media.pk).update(model_to_use='yolo:yolo11n.pt')   # row of before
        data = self.client.get(reverse('anonymizer:get_media_settings', args=[media.pk])).json()
        self.assertEqual(YOLO_KEY, data['values']['model_to_use'])

    def test_the_launch_rejects_a_model_nothing_serves_with_the_reason(self):
        from wama.anonymizer import tasks
        media = self._media(OTHER_SOURCE_KEY)
        with mock.patch('wama.common.backends.manager.backend_for_key', return_value=None), \
                mock.patch.object(tasks, '_console'):
            with self.assertRaisesRegex(ValueError, OTHER_SOURCE_KEY):
                tasks._detection_kwargs(media, self.user)

    def test_a_served_model_is_the_one_that_runs(self):
        # Counter-check: the refusal is about what nothing serves, not about the key form.
        from wama.anonymizer import tasks
        media = self._media(YOLO_KEY)
        with mock.patch('wama.common.backends.manager.backend_for_key', return_value=object), \
                mock.patch('wama.anonymizer.utils.yolo_utils.model_path_for',
                           return_value='/weights/yolo11n.pt') as path_for, \
                mock.patch.object(tasks, '_console'):
            kwargs = tasks._detection_kwargs(media, self.user)
        self.assertEqual('/weights/yolo11n.pt', (kwargs[0] if isinstance(kwargs, tuple)
                                                 else kwargs)['model_path'])
        self.assertEqual('yolo:yolo11n.pt', path_for.call_args.args[0])


class DesignatedModelAgainstCoverageTest(TestCase):
    """2026-10-15 — a card asking for « face » with a designated face model ran the coverage's
    ENSEMBLE instead (yolov9c + yolov9e), silently: four detectors compared on batch #685, one
    single ensemble executed. The designated model runs when it covers the requested classes; the
    coverage decides only when it does not (a COCO model does not see faces)."""

    ENSEMBLE = {'parallel': True, 'coverage': 1.0, 'unsupported_classes': [], 'models': [
        {'id': 'yolo:a-face.pt', 'path': '/w/a-face.pt', 'name': 'a', 'classes': ['face'],
         'model_key': 'anonymizer:yolo:a-face.pt'},
        {'id': 'yolo:b-face.pt', 'path': '/w/b-face.pt', 'name': 'b', 'classes': ['face'],
         'model_key': 'anonymizer:yolo:b-face.pt'}]}

    def setUp(self):
        _catalogue_rows()
        self.user = User.objects.create_user('anon_designated', password='x')

    def _kwargs(self, model_classes, key=YOLO_KEY, wanted=('face',)):
        """The designated model's classes are the CATALOGUE's (what the discovery of its engine
        read in its weights) — the question the task asks, like the page and the coverage."""
        from wama.anonymizer import tasks
        from wama.model_manager.models import AIModel
        AIModel.objects.update_or_create(model_key=key, defaults=dict(
            name=key, model_type='vision', source=key.split(':')[0], is_downloaded=True,
            capabilities={'task': 'detect', 'classes': list(model_classes)}))
        media = Media.objects.create(user=self.user, file='anonymizer/x/input/sample.png',
                                     model_to_use=key, classes2blur=list(wanted),
                                     target_mode='classes')
        with mock.patch('wama.common.backends.manager.backend_for_key', return_value=object), \
                mock.patch('wama.anonymizer.utils.yolo_utils.model_path_for',
                           return_value='/weights/chosen.pt'), \
                mock.patch.object(tasks, 'needs_parallel_detection',
                                  return_value=self.ENSEMBLE) as coverage, \
                mock.patch.object(tasks, '_console'):
            kwargs = tasks._detection_kwargs(media, self.user)
        return (kwargs[0] if isinstance(kwargs, tuple) else kwargs), coverage

    def test_a_designated_model_that_sees_faces_runs_alone(self):
        kwargs, coverage = self._kwargs(['Face'])
        self.assertEqual('/weights/chosen.pt', kwargs.get('model_path'))
        self.assertEqual(YOLO_KEY, kwargs.get('model_key'))
        self.assertNotIn('models', kwargs, 'the ensemble replaced the designated model')
        coverage.assert_not_called()

    def test_a_designated_model_blind_to_faces_lets_the_coverage_choose(self):
        kwargs, coverage = self._kwargs(['person', 'car'])
        coverage.assert_called_once()
        self.assertEqual(['anonymizer:yolo:a-face.pt', 'anonymizer:yolo:b-face.pt'],
                         [m['model_key'] for m in kwargs.get('models') or []])

    def test_a_designated_plate_detector_runs_alone_under_its_own_class_name(self):
        """2026-11-07 : the plate box is `plate`, the plate detectors declare `license_plate` —
        and EgoBlur or RT-DETR do not open by YOLO, which the former reading used. Every designated
        plate detector was judged blind and replaced by the coverage, the card naming another
        model than the one that ran. The question is now the page's and the coverage's: the
        catalogue classes, the common alias matching (`model_coverage.classes_couvertes`)."""
        key = 'anonymizer:rtdetr-v2-license-plate'
        kwargs, coverage = self._kwargs(['license_plate'], key=key, wanted=['plate'])
        self.assertEqual(key, kwargs.get('model_key'))
        self.assertNotIn('models', kwargs, 'the coverage replaced the designated plate detector')
        coverage.assert_not_called()


class PromptModelTest(TestCase):
    """2026-11-19 — LocateAnything was installed and unreachable : the description mode ran SAM3
    whatever the card designated. A designated model that READS a description (the rule the menu
    applies, `app_modes.mode_model_filter`) runs through the common ensemble, the processed
    description for its demand ; one left over from the classes mode does not, and SAM3 runs."""

    LOCATE = 'huggingface:nvidia/LocateAnything-3B'

    def setUp(self):
        from wama.model_manager.models import AIModel
        _catalogue_rows()
        self.user = User.objects.create_user('anon_description', password='x')
        AIModel.objects.update_or_create(model_key=self.LOCATE, defaults=dict(
            name='LocateAnything-3B', model_type='vision', source='huggingface',
            is_downloaded=True, capabilities={'task': 'zero-shot-object-detection',
                                              'inputs_required': ['work_file', 'prompt']}))
        AIModel.objects.update_or_create(model_key=YOLO_KEY, defaults=dict(
            name=YOLO_KEY, model_type='vision', source='anonymizer', is_downloaded=True,
            capabilities={'task': 'detect', 'inputs_required': ['work_file'],
                          'classes': ['face']}))

    def _kwargs(self, key):
        from wama.anonymizer import tasks
        media = Media.objects.create(user=self.user, file='anonymizer/x/input/sample.png',
                                     model_to_use=key, target_mode='description',
                                     sam3_prompt='logo, street sign')
        with mock.patch('wama.common.backends.manager.backend_for_key', return_value=object), \
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           side_effect=lambda app, field, text, **kw: (
                               {'prompt': text, 'original': text} if kw.get('full') else text)), \
                mock.patch.object(tasks, 'needs_parallel_detection',
                                  return_value={'parallel': False, 'models': []}), \
                mock.patch.object(tasks, '_console'):
            return tasks._detection_kwargs(media, self.user)

    def test_a_chosen_prompt_model_is_the_one_that_runs(self):
        kwargs, used = self._kwargs(self.LOCATE)
        self.assertEqual([self.LOCATE], [m['model_key'] for m in kwargs['models']])
        self.assertFalse(kwargs['use_sam3'], 'SAM3 does not run in its place')
        self.assertEqual('logo, street sign', kwargs['sam3_prompt'])
        self.assertEqual([self.LOCATE], used)

    def test_a_classes_model_left_over_lets_sam3_run(self):
        """A model left over from the classes mode reads no description : the card is read as
        « auto » (2026-11-24 : the concept router), SAM3 looking for what nothing else covers."""
        from wama.anonymizer import tasks
        with mock.patch.object(tasks, 'check_sam3_installed', return_value=True), \
                mock.patch.object(tasks, 'validate_sam3_prompt', return_value=(True, '')):
            kwargs, used = self._kwargs(YOLO_KEY)
        self.assertEqual([tasks.SAM3_KEY], used)
        self.assertEqual('logo, street sign', kwargs['models'][0]['prompt'])
        self.assertNotIn(self.LOCATE, [m.get('model_key') for m in kwargs.get('models') or []])

    def test_under_auto_each_concept_goes_to_who_covers_it_and_what_was_understood_is_kept(self):
        """2026-11-24 (A.2, decision 1) : under « auto » a described face goes to the face
        detectors the coverage picks — measured recall, slider, as in the classes mode —, the
        rest to SAM3 alone ; what the pipeline understood is KEPT on the media (shown in its
        two-state field), and the next launch reuses it without a second LLM pass."""
        from wama.anonymizer import tasks
        media = Media.objects.create(user=self.user, file='anonymizer/x/input/sample.png',
                                     model_to_use='auto', target_mode='description',
                                     sam3_prompt='les visages et les logos')
        cover = {'parallel': False, 'unsupported_classes': ['logo'], 'models': [
            {'id': 'yolo:face.pt', 'path': '/w/face.pt', 'name': 'face', 'classes': ['human face'],
             'model_key': YOLO_KEY}]}
        understood = {'prompt': 'human face, logo', 'original': 'les visages et les logos',
                      'enriched': True, 'translated': True}
        with mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                        return_value=understood) as pipeline, \
                mock.patch.object(tasks, 'needs_parallel_detection', return_value=cover), \
                mock.patch.object(tasks, 'check_sam3_installed', return_value=True), \
                mock.patch.object(tasks, 'validate_sam3_prompt', return_value=(True, '')), \
                mock.patch.object(tasks, '_console'):
            kwargs, used = tasks._detection_kwargs(media, self.user)
            media.refresh_from_db()
            again = tasks._detection_kwargs(media, self.user)
        self.assertEqual([YOLO_KEY, tasks.SAM3_KEY], used)
        self.assertFalse(kwargs['use_sam3'], 'SAM3 runs inside the ensemble, for its part only')
        self.assertEqual('logo', kwargs['models'][1]['prompt'])
        self.assertEqual([('human face', [YOLO_KEY]), ('logo', [tasks.SAM3_KEY])],
                         [(s['concept'], s['by']) for s in kwargs['plan']])
        self.assertEqual('human face, logo', media.sam3_prompt_processed)
        self.assertEqual('les visages et les logos', media.sam3_prompt, 'the typed text is kept')
        self.assertIs(False, pipeline.call_args_list[1].kwargs['enrich'],
                      'understood once : the next launch does not ask the LLM again')
        self.assertEqual(used, again[1])
        # What the modal shows under the field (« Compris : concept → modèles ») : the SAME router,
        # read without the LLM, the catalogue names in place of the keys.
        with mock.patch.object(tasks, 'needs_parallel_detection', return_value=cover), \
                mock.patch.object(tasks, 'check_sam3_installed', return_value=True), \
                mock.patch('wama.common.utils.app_metadata.process_prompt_for') as no_llm:
            shown = tasks.description_plan(media)
        no_llm.assert_not_called()
        self.assertEqual([('human face', [YOLO_KEY]), ('logo', [tasks.SAM3_KEY])],
                         [(s['concept'], s['by']) for s in shown])
        media.target_mode = 'classes'
        self.assertEqual([], tasks.description_plan(media), 'nothing to show in the classes mode')

    def test_a_new_card_describes_the_offered_targets_and_shows_them_understood(self):
        """2026-11-24 (A.5, decision of Fabien : description by default, offered targets
        checked) : a new card is born in the description mode with the targets the field
        declares ; before any launch nor LLM, the modal already shows who will look for each."""
        from wama.anonymizer import tasks
        from wama.common.utils.app_metadata import default_prompt
        media = Media.objects.create(user=self.user, file='anonymizer/x/input/sample.png')
        self.assertEqual(('description', default_prompt('anonymizer', 'sam3_prompt')),
                         (media.target_mode, media.sam3_prompt))
        cover = {'parallel': True, 'unsupported_classes': [], 'models': [
            {'id': 'yolo:face.pt', 'path': '/w/face.pt', 'name': 'face',
             'classes': ['face', 'license plate'], 'model_key': YOLO_KEY}]}
        with mock.patch.object(tasks, 'needs_parallel_detection', return_value=cover), \
                mock.patch.object(tasks, 'check_sam3_installed', return_value=True), \
                mock.patch('wama.common.utils.prompt_pipeline.process_prompt') as no_llm:
            shown = {s['concept']: s['by'] for s in tasks.description_plan(media)}
        no_llm.assert_not_called()
        self.assertEqual([YOLO_KEY], shown['face'])
        self.assertEqual([YOLO_KEY], shown['license plate'])
        self.assertEqual([tasks.SAM3_KEY], shown['logo'])
        media.sam3_prompt = 'visages, la voiture rouge'
        with mock.patch.object(tasks, 'check_sam3_installed', return_value=True):
            self.assertEqual([], tasks.description_plan(media),
                             'a free text is shown once understood, never half guessed')


class OfferedClassesTest(SimpleTestCase):
    """2026-11-24 (A.1) — the classes the edit page offers for an added zone : the ASKED ones in the
    classes mode only (in the description mode « face » came from the list's default), then the
    FOUND ones, all under their common name (`License_Plate` and `license plate` were two offers)."""

    def test_asked_then_found_under_one_name_and_nothing_asked_in_the_prompt_mode(self):
        from types import SimpleNamespace
        from wama.anonymizer import surfaces
        found = ['license plate', 'face', 'logo']      # `detections.labels` : common names already
        with mock.patch.object(surfaces, '_found_labels', return_value=['logo']):
            by_classes = surfaces._offered_classes(SimpleNamespace(
                target_mode='classes', classes2blur=['face', 'License_Plate', 'false']))
        with mock.patch.object(surfaces, '_found_labels', return_value=found):
            by_prompt = surfaces._offered_classes(SimpleNamespace(
                target_mode='description', classes2blur=['face']))
        self.assertEqual(['face', 'license plate', 'logo'], by_classes,
                         'asked under their common name, then found ; a saved « false » dropped')
        self.assertEqual(found, by_prompt, 'the default classes of the list are not asked')


class ModelKeysMigrationTest(SimpleTestCase):
    """`0036_model_to_use_catalog_keys`: PURE prefixing, `default` (which never designated a
    model) becomes « auto », a path of before is left for the reader."""

    def _run(self, name, rows):
        import importlib
        from wama.common.tests.helpers import run_data_migration
        module = importlib.import_module('wama.anonymizer.migrations.0036_model_to_use_catalog_keys')
        return run_data_migration(getattr(module, name), 'model_to_use', rows)

    def test_forward(self):
        self.assertEqual(
            {1: YOLO_KEY, 2: 'auto', 3: 'auto', 4: 'anonymizer:sam3', 5: 'detect/faces/x.pt', 6: None},
            self._run('to_catalog_keys', {1: 'yolo:yolo11n.pt', 2: 'auto', 3: 'default',
                                          4: 'anonymizer:sam3', 5: 'detect/faces/x.pt', 6: None}))

    def test_backward_strips_only_its_own_prefix(self):
        self.assertEqual({1: 'yolo:yolo11n.pt', 2: OTHER_SOURCE_KEY, 3: 'auto'},
                         self._run('to_bare_ids', {1: YOLO_KEY, 2: OTHER_SOURCE_KEY, 3: 'auto'}))


class NothingIsFetchedBesideTheRouteTest(TestCase):
    """2026-11-06 : the anonymizer fetched official YOLO weights itself — at a page opening (the
    class choices loaded `yolov8n.pt`) and at first use (`get_model_path`) — by a fixed address,
    without a fingerprint. The class choices are read in the catalogue; the designated model is
    installed by the route BEFORE it is read; a path is resolved, never downloaded."""

    def setUp(self):
        _catalogue_rows()
        self.user = User.objects.create_user('anon_route', password='x')

    def test_the_class_choices_are_read_in_the_catalogue_without_loading_a_model(self):
        from wama.anonymizer.utils.yolo_utils import get_all_class_choices
        from wama.model_manager.models import AIModel
        AIModel.objects.update_or_create(model_key='anonymizer:yolo:yolov8n.pt', defaults=dict(
            name='yolov8n.pt', model_type='vision', source='anonymizer', is_downloaded=False,
            capabilities={'task': 'detect', 'classes': ['person', 'car']}))
        self.assertEqual([('face', 'Face'), ('plate', 'Plate'), ('Person', 'Person'),
                          ('Car', 'Car')], get_all_class_choices())

    def test_the_designated_model_is_installed_before_it_is_read(self):
        from wama.anonymizer import tasks
        from wama.model_manager.models import AIModel
        AIModel.objects.filter(model_key=YOLO_KEY).update(
            capabilities={'task': 'detect', 'classes': ['face'], 'inputs_required': ['work_file']})
        order = []
        media = Media.objects.create(user=self.user, file='anonymizer/x/input/sample.png',
                                     model_to_use=YOLO_KEY, classes2blur=['face'],
                                     target_mode='classes')
        with mock.patch('wama.common.backends.manager.backend_for_key', return_value=object), \
                mock.patch('wama.anonymizer.utils.yolo_utils.model_path_for',
                           side_effect=lambda value: order.append('path') or '/w/yolo11n.pt'), \
                mock.patch.object(tasks, '_console'):
            kwargs, _used = tasks._detection_kwargs(
                media, self.user, ensure_model=lambda key: order.append(('route', key)))
        self.assertEqual([('route', YOLO_KEY), 'path'], order)
        self.assertEqual('/w/yolo11n.pt', kwargs['model_path'], 'the designated model runs')

    def test_a_missing_weight_resolves_to_a_path_and_downloads_nothing(self):
        import tempfile

        from wama.anonymizer.utils import yolo_utils
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(yolo_utils, 'MODELS_ROOT', tmp), \
                mock.patch('requests.get', side_effect=AssertionError('a download')):
            self.assertTrue(yolo_utils.get_model_path('yolo11n.pt').startswith(tmp))
            self.assertTrue(yolo_utils.get_model_path('detect/yolo11n.pt').startswith(tmp))
