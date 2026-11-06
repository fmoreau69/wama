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

    def test_the_corpus_follows_the_withdrawn_row_and_its_dry_run_does_not(self):
        """2026-11-02: the old row's sheet carries its exclusion, and the apps that proposed it no
        longer do — through the corpus door that uninstalling uses (`forget_in_corpus`)."""
        with mock.patch('wama.model_manager.services.model_installer.forget_in_corpus') as follow:
            s.supersede(OLD, NEW, apply=False)
            follow.assert_not_called()
            s.supersede(OLD, NEW)
        follow.assert_called_once_with([OLD])

    def test_an_unknown_row_is_refused(self):
        self.assertIn('error', s.supersede(OLD, 'reader:nowhere'))
        self.assertIn('error', s.supersede(OLD, OLD))


class RekeyTest(TestCase):
    """The SAME weights under a new key (2026-11-06: `yolo11l_face_plate_signs.pt` renamed to the
    name its repository publishes, `yolo11l_panoramax.pt`, same sha256). Not a succession: the old
    row has no file left, there is no going back to keep, and what was MEASURED of these weights
    holds for the new key."""

    def setUp(self):
        _rows()
        AIModel.objects.filter(model_key=OLD).update(
            license='etalab-2.0', author='Panoramax',
            composition={'components': [{'role': 'model', 'pattern': 'old.pt'}],
                         'runtime': {'engine': 'x'}})
        AIModel.objects.filter(model_key=NEW).update(
            composition={'components': [{'role': 'model', 'pattern': 'new.pt'}],
                         'runtime': {'engine': 'x'}})
        self.user = get_user_model().objects.create_user('rekey', password='x')
        follow = mock.patch('wama.model_manager.services.model_installer.forget_in_corpus')
        self.corpus = follow.start()
        self.addCleanup(follow.stop)

    def _evaluation(self, key):
        from wama.common.models import ResultEvaluation
        return ResultEvaluation.objects.create(app='reader', object_type='ReadingItem', object_id=1,
                                               model_key=key, metric='cer', value=0.1,
                                               protocol='v1', reference_sha256='0' * 64)

    def test_choices_measures_and_curated_facts_follow_and_the_old_row_leaves(self):
        from wama.common.models import ResultEvaluation
        from wama.model_manager.models import ModelRuntimeStat
        from wama.reader.models import ReadingItem
        card = ReadingItem.objects.create(user=self.user, backend='auto')
        ReadingItem.objects.filter(pk=card.pk).update(backend=OLD, used_backend=OLD)
        ModelRuntimeStat.objects.create(model_key=OLD, hardware_fingerprint='gpu', samples=4)
        self._evaluation(OLD)
        res = s.rekey(OLD, NEW)
        self.assertEqual((1, 1), (res['runtime_stats'], res['evaluations']))
        self.assertEqual((NEW, OLD), tuple(ReadingItem.objects.filter(pk=card.pk)
                                           .values_list('backend', 'used_backend')[0]),
                         'the choice follows, what ran stays what ran')
        self.assertTrue(ModelRuntimeStat.objects.filter(model_key=NEW, samples=4).exists())
        self.assertEqual(NEW, ResultEvaluation.objects.get().model_key)
        new = AIModel.objects.get(model_key=NEW)
        self.assertEqual(('etalab-2.0', 'Panoramax'), (new.license, new.author))
        self.assertFalse(AIModel.objects.filter(model_key=OLD).exists())
        self.corpus.assert_called_once_with([OLD, NEW])

    def test_the_new_rows_own_anatomy_is_never_replaced(self):
        s.rekey(OLD, NEW)
        self.assertEqual('new.pt', AIModel.objects.get(model_key=NEW)
                         .composition['components'][0]['pattern'])

    def test_a_measure_already_taken_under_the_new_key_stays_and_the_old_one_is_named(self):
        from wama.model_manager.models import ModelRuntimeStat
        ModelRuntimeStat.objects.create(model_key=OLD, hardware_fingerprint='gpu', samples=4)
        ModelRuntimeStat.objects.create(model_key=NEW, hardware_fingerprint='gpu', samples=9)
        res = s.rekey(OLD, NEW)
        self.assertEqual((0, ['gpu']), (res['runtime_stats'], res['runtime_stats_kept_apart']))
        self.assertEqual(9, ModelRuntimeStat.objects.get(model_key=NEW).samples)

    def test_the_dry_run_counts_and_writes_nothing(self):
        self._evaluation(OLD)
        res = s.rekey(OLD, NEW, apply=False)
        self.assertEqual(1, res['evaluations'])
        self.assertTrue(AIModel.objects.filter(model_key=OLD).exists())
        self.assertEqual('', AIModel.objects.get(model_key=NEW).license)
        self.corpus.assert_not_called()

    def test_two_present_copies_or_other_weights_are_no_key_change(self):
        import tempfile
        with tempfile.NamedTemporaryFile() as present:
            AIModel.objects.filter(model_key=OLD).update(extra_info={'path': present.name})
            self.assertIn('supersede', s.rekey(OLD, NEW)['error'])
        AIModel.objects.filter(model_key=OLD).update(extra_info={'size_bytes': 5},
                                                     platform_ref='huggingface:a/b')
        AIModel.objects.filter(model_key=NEW).update(extra_info={'size_bytes': 6})
        self.assertIn('tailles', s.rekey(OLD, NEW)['error'])
        AIModel.objects.filter(model_key=NEW).update(platform_ref='huggingface:c/d')
        self.assertIn('provenances', s.rekey(OLD, NEW)['error'])
        self.assertIn('error', s.rekey(OLD, OLD))
        self.assertTrue(AIModel.objects.filter(model_key=OLD).exists())


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
