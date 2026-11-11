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

    def test_a_generic_hub_snapshot_reinstalls_where_it_lived(self):
        """2026-11-11 (preuve du retrait d'ACE-Step) : une ligne installée par la PROSPECTION n'a
        pas d'`install_dir` ; désinstallée, ni une tâche ni « Installer » ne savaient la réinstaller
        (« poids absents, annonce faite »). Son dossier de famille est le parent de celui de ses
        poids. Contre-épreuve : un dossier qui ne porte pas le nom du dépôt ne désigne rien."""
        with tempfile.TemporaryDirectory() as tmp, override_settings(AI_MODELS_DIR=Path(tmp)):
            row = _installed(Path(tmp), platform_ref='huggingface:Org/Old')
            _uninstall(Path(tmp), row.model_key)
            row.refresh_from_db()
            self.assertNotIn('install_dir', row.extra_info)
            spec = mi.spec_for_catalog_row(row)
            self.assertEqual(('hf', 'Org/Old', 'ocr', 'Fam'),
                             (spec['kind'], spec['ref'], spec['category'], spec['family']))
            self.assertTrue(row.is_installable)
            AIModel.objects.filter(pk=row.pk).update(local_path=str(Path(tmp) / 'models' / 'ocr' / 'Fam'))
            row.refresh_from_db()
            self.assertIsNone(mi.spec_for_catalog_row(row))

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


class ABackboneReinstalledForAnotherModelStaysWithdrawnTest(TestCase):
    """2026-11-11 (Fabien : « il faut que la route permette le retrait d'un modèle mais la reprise
    de la dorsale […] il ne faut pas laisser de piège ») : la turbo d'ACE-Step désinstallée, une
    génération SFT réinstalle sa dorsale par la route — et la remettait dans les CHOIX
    (`restore_withdrawn`, deux fois : demande et fin d'installation). Réinstallée comme dorsale,
    elle reste retirée ; « Installer » sur la ligne, geste explicite, l'y rend."""

    def _withdrawn_backbone(self, tmp):
        row = _installed(Path(tmp), key='reader:base', platform_ref='huggingface:Org/Base')
        _uninstall(Path(tmp), row.model_key)
        AIModel.objects.filter(pk=row.pk).update(extra_info={
            **AIModel.objects.get(pk=row.pk).extra_info,
            'install_dir': str(Path(tmp) / 'models' / 'ocr' / 'Fam')})
        return row

    def _request(self, tmp, key, via):
        with override_settings(AI_MODELS_DIR=Path(tmp)), \
                mock.patch.object(mi, 'dispatch_install', return_value=SimpleNamespace(id='t')), \
                mock.patch.object(mi, 'disk_space_guard', return_value=None):
            return mi.request_install(key, via=via)

    def test_the_route_reinstalls_the_backbone_without_giving_it_back(self):
        from wama.model_manager.services.provenance import record_after_install
        with tempfile.TemporaryDirectory() as tmp:
            row = self._withdrawn_backbone(tmp)
            self.assertTrue(self._request(tmp, row.model_key, mi.VIA_BACKBONE)['started'])
        with mock.patch('wama.model_manager.services.provenance.identity_for_spec',
                        return_value={'platform_ref': 'huggingface:Org/Base'}), \
                mock.patch('wama.model_manager.services.provenance.set_identity',
                           return_value={'model': row.model_key}):
            record_after_install({'kind': 'hf', 'ref': 'Org/Base', 'category': 'ocr'}, [])
        row.refresh_from_db()
        self.assertFalse(row.is_available, "réinstallée comme dorsale : toujours hors des choix")

    def test_installer_on_the_present_row_gives_it_back(self):
        """Contre-épreuve : ses poids revenus, le geste explicite la rend aux choix."""
        with tempfile.TemporaryDirectory() as tmp:
            row = self._withdrawn_backbone(tmp)
            self._request(tmp, row.model_key, mi.VIA_BACKBONE)
            AIModel.objects.filter(pk=row.pk).update(is_downloaded=True)
            out = self._request(tmp, row.model_key, 'model_manager')
        self.assertTrue(out.get('restored'), out)
        row.refresh_from_db()
        self.assertTrue(row.is_available)

    def test_the_corpus_follows_both_the_mark_and_its_lifting(self):
        """Vécu le 2026-11-11 : rendue aux choix sans téléchargement, la ligne gardait au corpus
        l'exclusion levée en base (`manifest_export --check` : « 1 PERTE »)."""
        with tempfile.TemporaryDirectory() as tmp:
            row = self._withdrawn_backbone(tmp)
            with mock.patch.object(mi, 'forget_in_corpus') as follow:
                mi.keep_out_of_choices([row.model_key])
                follow.assert_called_with([row.model_key])
                mi.restore_withdrawn([row.model_key], explicit=True)
                follow.assert_called_with([row.model_key], lifted=mi.LIFTED_EXCLUSION)
                self.assertEqual(2, follow.call_count)

    def test_the_page_and_the_assistant_offer_and_play_the_gesture_that_gives_it_back(self):
        """2026-11-11 : « Installer » ne vise qu'une ligne ABSENTE — la turbo réinstallée comme
        dorsale n'avait aucun bouton pour revenir, et la vue lisait un `task_id` qu'un retour aux
        choix n'a pas (500). La ligne se dit `restorable`, la page offre « Rendre aux choix », la
        vue et l'outil de l'assistant rendent `restored`. Contre-épreuve : une exclusion HUMAINE
        n'est pas `restorable`."""
        from django.urls import reverse

        from wama import tool_api
        with tempfile.TemporaryDirectory() as tmp:
            row = self._withdrawn_backbone(tmp)
            self._request(tmp, row.model_key, mi.VIA_BACKBONE)
            AIModel.objects.filter(pk=row.pk).update(is_downloaded=True)
            row.refresh_from_db()
            self.assertTrue(row.is_restorable)
            self.assertTrue(row.to_dict()['restorable'])
            admin = get_user_model().objects.create_superuser('restore_admin', password='x')
            self.client.force_login(admin)
            page = self.client.get(reverse('model_manager:index'))
            self.assertContains(page, 'Rendre aux choix')
            answer = self.client.post(reverse('model_manager:api_prospect_install'),
                                      {'catalog_key': row.model_key}, content_type='application/json')
            self.assertEqual((200, True), (answer.status_code, answer.json().get('restored')))
            row.refresh_from_db()
            self.assertTrue(row.is_available)
            self.assertFalse(row.is_restorable)
            mi.withdraw_from_choices([row], '2026-11-11T00:00:00')
            told = tool_api.install_model(admin, row.model_key)
            self.assertTrue(told.get('restored'), told)
            self.assertNotIn('next_step', told, "rien ne se télécharge : aucun suivi annoncé")
        human = AIModel.objects.create(model_key='reader:human', name='h', model_type='ocr',
                                       source='reader', is_downloaded=True, is_available=False,
                                       extra_info={'exclusion': dict(HUMAN)})
        self.assertFalse(human.is_restorable)

    def test_a_task_asks_the_backbone_by_its_own_way(self):
        """`ensure_installed` demande la DORSALE par la voie `backbone`, le modèle par la sienne."""
        from wama.common.utils import model_readiness
        asked = []
        with mock.patch.object(model_readiness, '_with_backbone', return_value=['base', 'variant']), \
                mock.patch.object(model_readiness, '_ensure_one',
                                  side_effect=lambda key, **kw: asked.append((key, kw['via']))), \
                mock.patch.object(model_readiness, 'contract_optional_models', return_value=()):
            model_readiness.ensure_installed('variant', via='task')
        self.assertEqual([('base', mi.VIA_BACKBONE), ('variant', 'task')], asked)


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
