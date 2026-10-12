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
        return Media.objects.create(user=self.user, file='anonymizer/x/input/sample.png',
                                    model_to_use=model)

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
