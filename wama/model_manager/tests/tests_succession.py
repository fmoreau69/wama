"""A new VERSION replaces the old one wherever the old one was chosen (2026-10-29, Fabien: « quand
on a une montée de version, il faudrait que le remplacement se fasse le plus naturellement
possible à tous les endroits où le modèle plus ancien était »).

Lived case: olmOCR-2, installed from its successor proposal, sat NEXT to olmOCR v1 — the Reader
still listed v1, a card or a remembered setting could still name it. The places that name a model
are DERIVED from the declarations (catalogue settings of the app schemas × declared element models,
remembered settings, batch settings) — never listed by hand.
"""
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common.models import BatchSettings, UserAppSetting
from wama.model_manager.models import WITHDRAWN_SUPERSEDED, AIModel, withdrawn_q
from wama.model_manager.services import succession as s

OLD, NEW = 'reader:olmocr', 'huggingface:allenai/olmOCR-2-7B-1025'


def _rows():
    for key, source in ((OLD, 'reader'), (NEW, 'huggingface')):
        AIModel.objects.create(model_key=key, name=key, model_type='ocr', source=source,
                               is_downloaded=True, capabilities={'task': 'ocr'})


class TheReferencingPlacesAreDerivedTest(TestCase):

    def test_the_reader_engine_column_is_found_and_its_history_column_is_not(self):
        from wama.reader.models import ReadingItem
        fields = {(model, field) for _surface, model, field, _src in s.model_reference_fields()}
        self.assertIn((ReadingItem, 'backend'), fields)
        self.assertNotIn((ReadingItem, 'used_backend'), fields, 'history is not a choice')

    def test_every_app_with_a_catalogue_setting_is_covered(self):
        apps = {model._meta.app_label for _s, model, _f, _src in s.model_reference_fields()}
        self.assertTrue({'reader', 'transcriber', 'imager'} <= apps, apps)


class SupersedeTest(TestCase):

    def setUp(self):
        _rows()
        self.user = get_user_model().objects.create_user('succession', password='x')

    def _card(self, **fields):
        from wama.reader.models import ReadingItem
        item = ReadingItem.objects.create(user=self.user, backend='auto')
        ReadingItem.objects.filter(pk=item.pk).update(**fields)
        return item

    def test_cards_settings_and_batches_follow_the_successor(self):
        from wama.reader.models import ReadingItem
        full = self._card(backend=OLD, used_backend=OLD)
        bare = self._card(backend='olmocr')
        other = self._card(backend='reader:doctr')
        UserAppSetting.objects.create(user=self.user, app='reader', name='backend', value=OLD)
        UserAppSetting.objects.create(user=self.user, app='reader', name='backend2', value='x')
        BatchSettings.objects.create(app='reader', batch_type='ReadingBatch', batch_id='1',
                                     settings={'backend': 'olmocr', 'mode': 'printed'})
        res = s.supersede(OLD, NEW)
        self.assertEqual({'reader.backend': 2}, {k: v for k, v in res['cards'].items()
                                                 if k.startswith('reader.')})
        values = dict(ReadingItem.objects.values_list('pk', 'backend'))
        self.assertEqual((NEW, NEW, 'reader:doctr'), (values[full.pk], values[bare.pk],
                                                      values[other.pk]))
        self.assertEqual(OLD, ReadingItem.objects.get(pk=full.pk).used_backend,
                         'what ran stays what ran')
        self.assertEqual(NEW, UserAppSetting.objects.get(name='backend').value)
        self.assertEqual({'backend': NEW, 'mode': 'printed'},
                         BatchSettings.objects.get(batch_id='1').settings)
        old = AIModel.objects.get(model_key=OLD)
        self.assertFalse(old.is_available)
        self.assertEqual((WITHDRAWN_SUPERSEDED, NEW), (old.extra_info['exclusion']['by'],
                                                       old.extra_info['exclusion']['superseded_by']))
        self.assertTrue(AIModel.objects.filter(withdrawn_q(), model_key=OLD).exists())
        self.assertTrue(old.is_downloaded, 'its weights stay: going back stays possible')

    def test_a_setting_kept_under_its_panel_field_id_follows_too(self):
        # `read_panel_settings` keeps a setting under its `panel_dom_id` by default.
        UserAppSetting.objects.create(user=self.user, app='reader', name='backendSelect',
                                      value='olmocr')
        s.supersede(OLD, NEW)
        self.assertEqual(NEW, UserAppSetting.objects.get(name='backendSelect').value)

    def test_a_value_of_another_setting_is_not_a_reference(self):
        # Counter-check: the bare id only counts under the name of a catalogue setting.
        UserAppSetting.objects.create(user=self.user, app='reader', name='mode', value='olmocr')
        s.supersede(OLD, NEW)
        self.assertEqual('olmocr', UserAppSetting.objects.get(name='mode').value)

    def test_the_dry_run_counts_and_writes_nothing(self):
        from wama.reader.models import ReadingItem
        card = self._card(backend=OLD)
        res = s.supersede(OLD, NEW, apply=False)
        self.assertEqual(1, res['cards']['reader.backend'])
        self.assertEqual(OLD, ReadingItem.objects.get(pk=card.pk).backend)
        self.assertTrue(AIModel.objects.get(model_key=OLD).is_available)

    def test_a_human_exclusion_of_the_old_row_keeps_its_reason(self):
        human = {'date': '2026-08-12', 'raison': 'mesuré faux'}
        AIModel.objects.filter(model_key=OLD).update(is_available=False,
                                                     extra_info={'exclusion': human})
        s.supersede(OLD, NEW)
        self.assertEqual(human, AIModel.objects.get(model_key=OLD).extra_info['exclusion'])

    def test_an_unknown_row_is_refused(self):
        self.assertIn('error', s.supersede(OLD, 'reader:nowhere'))
        self.assertIn('error', s.supersede(OLD, OLD))


class StoredFormTest(SimpleTestCase):

    def test_a_bare_value_stays_bare_when_the_successor_lives_in_the_same_source(self):
        self.assertEqual('v2', s._stored_form('reader:v2', 'reader', 'v1'))
        self.assertEqual('huggingface:org/v2', s._stored_form('huggingface:org/v2', 'reader', 'v1'))
        self.assertEqual('reader:v2', s._stored_form('reader:v2', 'reader', 'reader:v1'))


class TheInstallOfAnUpdateTriggersItTest(TestCase):

    def _candidate(self, kind='update'):
        return AIModel.objects.create(
            model_key='proposed:reader:olmocr', name='olmOCR-2-7B-1025', model_type='ocr',
            source='huggingface', is_proposed=True, proposal_kind=kind,
            extra_info={'prospect': {'origin_key': OLD, 'spec': {
                'kind': 'hf', 'ref': 'allenai/olmOCR-2-7B-1025', 'category': 'ocr'}}})

    def test_installing_a_successor_supersedes_the_row_it_targets(self):
        from wama.model_manager.services import model_installer as mi
        _rows()
        cand = self._candidate()
        installed = {'ok': True, 'provenance': {'models': [{'model': NEW}]}}
        with mock.patch.object(mi, 'install_from_spec', return_value=installed):
            out = mi.install_candidate(cand)
        self.assertTrue(out['ok'])
        self.assertEqual(NEW, out['superseded']['new'])
        self.assertFalse(AIModel.objects.get(model_key=OLD).is_available)

    def test_a_new_model_supersedes_nothing(self):
        # Counter-check: only an UPDATE proposal names what it replaces.
        _rows()
        self.assertIsNone(s.supersede_after_install(self._candidate('new'), [NEW]))
        self.assertTrue(AIModel.objects.get(model_key=OLD).is_available)

    def test_several_installed_rows_are_not_guessed(self):
        _rows()
        self.assertIsNone(s.supersede_after_install(self._candidate(), [NEW, 'reader:doctr']))

    def test_the_installed_keys_are_those_given_their_identity(self):
        self.assertEqual([NEW], s.installed_keys({'provenance': {'models': [{'model': NEW}]}}))
        self.assertEqual([], s.installed_keys(SimpleNamespace() and {}))
