"""Uninstalling a model WITHDRAWS it from the choices of the apps — an option checked by default
(2026-10-29, Fabien: « si on a l'option à la désinstallation, cochée par défaut, on réduit le
risque de traîner des modèles désinstallés dans les applications »).

Lived case: olmOCR v1, uninstalled for v2, stayed in the Reader's list « to download », and the
automatic draw — which does not require an installed model, the route reinstalls on demand —
could have brought it back alone. The withdrawal reuses the EXCLUDED row (`is_available=False` +
`exclusion`, sticky at sync, already read by the lists and the draw), with an origin the next
install lifts; a human exclusion is never lifted silently.
"""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from wama.model_manager.models import WITHDRAWN_BY_UNINSTALL, AIModel, withdrawn_q
from wama.model_manager.services import model_installer as mi

HUMAN = {'date': '2026-08-12', 'raison': 'trouve 0 visage sur une scène de rue'}


def _installed(root: Path, key='huggingface:Org/Old', **extra):
    repo = key.split(':', 1)[1].replace('/', '--')
    snapshot = root / 'models' / 'ocr' / 'Fam' / f'models--{repo}'
    snapshot.mkdir(parents=True)
    (snapshot / 'model.safetensors').write_bytes(b'0' * 16)
    return AIModel.objects.create(model_key=key, name=key.rsplit('/', 1)[-1], model_type='ocr',
                                  source='huggingface', is_downloaded=True,
                                  capabilities={'task': 'ocr'}, local_path=str(snapshot), **extra)


def _uninstall(root, key, **kwargs):
    with override_settings(AI_MODELS_DIR=root), mock.patch.object(mi, 'forget_in_corpus'):
        return mi.uninstall_model(key, **kwargs)


class UninstallWithdrawsFromTheChoicesTest(TestCase):

    def test_by_default_the_row_leaves_the_lists_and_the_draw(self):
        from wama.model_manager.services.model_selector import get_registry_models, select_model
        with tempfile.TemporaryDirectory() as tmp:
            row = _installed(Path(tmp))
            res = _uninstall(Path(tmp), row.model_key)
        self.assertEqual([row.model_key], res['withdrawn'])
        row.refresh_from_db()
        self.assertFalse(row.is_available)
        self.assertEqual(WITHDRAWN_BY_UNINSTALL, row.extra_info['exclusion']['by'])
        choices, _ = get_registry_models(None, task='ocr')
        self.assertNotIn(row.model_key, [k for k, _ in choices])
        with mock.patch('wama.common.backends.manager.backend_missing', return_value=None):
            self.assertIsNone(select_model(model_type='ocr', candidates=[row.model_key]))

    def test_unchecked_the_row_stays_proposed(self):
        # Counter-check: the option is an option — unchecked, the previous behaviour.
        from wama.model_manager.services.model_selector import get_registry_models
        with tempfile.TemporaryDirectory() as tmp:
            row = _installed(Path(tmp))
            res = _uninstall(Path(tmp), row.model_key, withdraw=False)
        self.assertEqual([], res['withdrawn'])
        row.refresh_from_db()
        self.assertTrue(row.is_available)
        self.assertNotIn('exclusion', row.extra_info)
        choices, _ = get_registry_models(None, task='ocr')
        self.assertIn(row.model_key, [k for k, _ in choices])

    def test_a_human_exclusion_keeps_its_reason_and_is_never_lifted(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = _installed(Path(tmp), extra_info={'exclusion': dict(HUMAN)})
            AIModel.objects.filter(pk=row.pk).update(is_available=False)
            _uninstall(Path(tmp), row.model_key)
        row.refresh_from_db()
        self.assertEqual(HUMAN, row.extra_info['exclusion'])
        self.assertEqual([], mi.restore_withdrawn([row.model_key]))
        row.refresh_from_db()
        self.assertFalse(row.is_available)

    def test_the_sync_keeps_the_withdrawal(self):
        # `exclusion` is a sticky key and the sync never sets `is_available` back on a row.
        from wama.model_manager.models import ModelSource, ModelType
        from wama.model_manager.services.model_registry import ModelInfo
        from wama.model_manager.services.model_sync import ModelSyncService
        with tempfile.TemporaryDirectory() as tmp:
            row = _installed(Path(tmp), key='reader:old-ocr')
            _uninstall(Path(tmp), row.model_key)
        info = ModelInfo(id='old-ocr', name='old-ocr', model_type=ModelType('ocr'),
                         source=ModelSource('reader'), description='declared by its app',
                         is_downloaded=False)
        ModelSyncService()._sync_model('reader:old-ocr', info)
        row.refresh_from_db()
        self.assertFalse(row.is_available)
        self.assertEqual(WITHDRAWN_BY_UNINSTALL, row.extra_info['exclusion']['by'])


class ReinstallingGivesItBackTest(TestCase):

    def test_installing_a_withdrawn_catalogue_row_gives_it_back_to_the_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = _installed(Path(tmp), key='reader:old-ocr',
                             platform_ref='huggingface:Org/Old-OCR')
            _uninstall(Path(tmp), row.model_key)
            AIModel.objects.filter(pk=row.pk).update(extra_info={
                **AIModel.objects.get(pk=row.pk).extra_info,
                'install_dir': str(Path(tmp) / 'models' / 'ocr' / 'Fam')})
            with override_settings(AI_MODELS_DIR=Path(tmp)), \
                    mock.patch.object(mi, 'dispatch_install', return_value=SimpleNamespace(id='t')), \
                    mock.patch.object(mi, 'disk_space_guard', return_value=None):
                out = mi.request_install(row.model_key)
        self.assertTrue(out['started'], out)
        row.refresh_from_db()
        self.assertTrue(row.is_available)
        self.assertNotIn('exclusion', row.extra_info)

    def test_the_row_an_install_reaches_comes_back(self):
        # A Hub snapshot re-proposed after its uninstall: its row is reached by its identity.
        from wama.model_manager.services.provenance import record_after_install
        with tempfile.TemporaryDirectory() as tmp:
            row = _installed(Path(tmp), platform_ref='huggingface:Org/Old')
            _uninstall(Path(tmp), row.model_key)
        with mock.patch('wama.model_manager.services.provenance.identity_for_spec',
                        return_value={'platform_ref': 'huggingface:Org/Old'}), \
                mock.patch('wama.model_manager.services.provenance.set_identity',
                           return_value={'model': row.model_key}):
            record_after_install({'kind': 'hf', 'ref': 'Org/Old', 'category': 'ocr'}, [])
        row.refresh_from_db()
        self.assertTrue(row.is_available)


class TheCatalogueStillShowsItTest(TestCase):

    def test_the_model_manager_lists_a_withdrawn_row_not_a_human_exclusion(self):
        withdrawn = AIModel.objects.create(
            model_key='huggingface:Org/Withdrawn', name='Withdrawn', model_type='ocr',
            source='huggingface', is_available=False,
            extra_info={'exclusion': {'date': '2026-10-29', 'by': WITHDRAWN_BY_UNINSTALL}})
        AIModel.objects.create(model_key='anonymizer:excluded', name='Excluded',
                               model_type='detection', source='anonymizer', is_available=False,
                               extra_info={'exclusion': dict(HUMAN)})
        self.assertEqual([withdrawn.model_key],
                         list(AIModel.objects.filter(withdrawn_q()).values_list('model_key',
                                                                                flat=True)))
        admin = get_user_model().objects.create_superuser('withdrawn_listing', password='x')
        self.client.force_login(admin)
        from django.urls import reverse
        listed = self.client.get(reverse('model_manager:api_models_db')).json()
        keys = [m.get('model_key') or m.get('id') for m in listed.get('models', [])]
        self.assertIn('huggingface:Org/Withdrawn', keys)
        self.assertNotIn('anonymizer:excluded', keys)

    def test_the_page_asks_with_the_option_checked(self):
        page = (Path(__file__).resolve().parents[1] / 'templates' / 'model_manager'
                / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="mmUninstallWithdraw" checked', page)
        self.assertIn('withdraw: choice.withdraw', page)
