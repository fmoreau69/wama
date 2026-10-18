"""À QUI EST un modèle — l'étape 3 du chantier PROVENANCE (`ROADMAP §29`, 2026-10-18).

CE QUE CES GARDES TIENNENT :
  1. un modèle privé n'est vu que de son auteur et de l'administrateur (décision c), par CHAQUE
     lecteur qui liste ou tire pour un compte : le select d'une app, le tirage automatique, la page
     du catalogue, l'assistant, la décision unique `accessible(user, 'model', clé)` ;
  2. la provenance naît au geste d'installation : un développeur garde le modèle qu'il fait
     naître, un administrateur l'installe pour le système, et une ligne qui existait avant le
     geste ne change jamais de main ;
  3. le manifeste LIT la provenance de la ligne, sans rien changer pour un modèle système ; un
     modèle privé n'est pas une cible du corpus versionné ; promouvoir le manifeste rend la ligne
     au système.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.accounts.models import UserProfile
from wama.accounts.permissions import accessible
from wama.model_manager.models import AIModel

SYSTEM_KEY = 'ollama:provenance-system-llm'
PRIVATE_KEY = 'ollama:provenance-private-llm'


def _account(username, tier):
    user = get_user_model().objects.create_user(username, password='x')
    UserProfile.objects.update_or_create(user=user, defaults={'account_tier': tier})
    return get_user_model().objects.get(pk=user.pk)      # profil relu, pas celui du cache


def _row(key, **fields):
    return AIModel.objects.create(model_key=key, name=key.split(':', 1)[1], model_type='llm',
                                  source='ollama', is_downloaded=True, is_available=True,
                                  capabilities={'task': 'text-generation'}, **fields)


class _Accounts(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.author = _account('provenance_author', 'developpeur')
        cls.other = _account('provenance_other', 'utilisateur')
        cls.admin = _account('provenance_admin', 'admin')
        cls.system = _row(SYSTEM_KEY)
        cls.private = _row(PRIVATE_KEY, owner=cls.author, visibility='private')


class EachReaderSeesOnlyWhatTheAccountMaySeeTest(_Accounts):

    def _listed(self, user):
        from wama.model_manager.services.model_selector import get_registry_models
        return {i for i, _ in get_registry_models('ollama', user=user)[0]}

    def test_a_private_model_is_listed_for_its_author_and_the_admin_only(self):
        mine, sysid = PRIVATE_KEY.split(':', 1)[1], SYSTEM_KEY.split(':', 1)[1]
        for user, sees in ((self.author, True), (self.admin, True), (self.other, False),
                           (None, False)):
            listed = self._listed(user)
            self.assertIn(sysid, listed, user)
            self.assertEqual(sees, mine in listed, user)

    def test_a_new_row_is_a_system_model_seen_by_every_account(self):
        self.assertTrue(self.system.is_system)
        self.assertEqual('public', self.system.visibility)
        self.assertFalse(self.private.is_system)

    def test_the_automatic_draw_never_picks_another_accounts_private_model(self):
        from wama.model_manager.services.model_selector import select_model
        with mock.patch('wama.common.backends.manager.backend_missing', return_value=''):
            def draw(user):
                return select_model('ollama', model_type='llm', candidates=[PRIVATE_KEY],
                                    vram_budget_gb=1000, prefer_loaded=False, user=user)
            self.assertEqual(self.private, draw(self.author))
            self.assertIsNone(draw(self.other))
            self.assertIsNone(draw(None))

    def test_the_app_draw_passes_the_account_of_the_item(self):
        from wama.common.utils.auto_model import resolve_model_choice
        seen = {}

        def fake_select(source, **kwargs):
            seen.update(kwargs)
            return 'x'
        with mock.patch('wama.model_manager.services.select_model_id', side_effect=fake_select):
            resolve_model_choice('auto', spec={'source': 'ollama'}, user=self.author)
        self.assertEqual(self.author, seen.get('user'))

    def test_the_catalogue_page_lists_by_account(self):
        url = reverse('model_manager:api_models_db')
        for user, sees in ((self.author, True), (self.other, False), (self.admin, True)):
            self.client.force_login(user)
            keys = {m.get('model_key') or m.get('key') for m in self.client.get(url).json()['models']}
            self.assertIn(SYSTEM_KEY, keys)
            self.assertEqual(sees, PRIVATE_KEY in keys, user)

    def test_the_assistant_neither_lists_nor_reads_another_accounts_private_model(self):
        from wama import tool_api
        for user, sees in ((self.author, True), (self.other, False)):
            listed = {m['key'] for m in tool_api.list_ai_models(user, limit=200)['models']}
            self.assertEqual(sees, PRIVATE_KEY in listed, user)
            self.assertEqual(sees, 'error' not in tool_api.get_ai_model(user, PRIVATE_KEY), user)

    def test_accessible_decides_a_model_by_its_provenance(self):
        self.assertTrue(accessible(self.author, 'model', PRIVATE_KEY))
        self.assertTrue(accessible(self.admin, 'model', PRIVATE_KEY))
        self.assertFalse(accessible(self.other, 'model', PRIVATE_KEY))
        self.assertTrue(accessible(self.other, 'model', SYSTEM_KEY))
        # Sans ligne, un élément n'est à personne : rien ne le restreint.
        self.assertTrue(accessible(self.other, 'model', 'ollama:no-such-model'))


class ProvenanceIsBornAtInstallTest(_Accounts):

    def test_an_admin_installs_for_the_system_a_developer_keeps_the_model(self):
        from wama.model_manager.services.model_installer import install_owner
        self.assertIsNone(install_owner(self.admin.pk))
        self.assertIsNone(install_owner(None))
        self.assertEqual(self.author, install_owner(self.author.pk))

    def test_only_a_row_the_install_made_appear_gets_an_author(self):
        from wama.model_manager.services import provenance
        appeared = _row('ollama:provenance-appeared', platform_ref='ollama:provenance-appeared')
        with mock.patch.object(provenance, 'identity_for_spec',
                               return_value={'platform_ref': 'ollama:provenance-appeared'}), \
                mock.patch.object(provenance, 'set_identity',
                                  side_effect=lambda key, *a, **k: {'model': key}):
            out = provenance.record_after_install({'kind': 'ollama', 'ref': 'x'},
                                                  [appeared.model_key], owner=self.author)
        appeared.refresh_from_db()
        self.assertEqual((self.author, 'private'), (appeared.owner, appeared.visibility))
        self.assertEqual([appeared.model_key], out['owner'])

    def test_a_reinstalled_system_model_stays_a_system_model(self):
        from wama.model_manager.services import provenance
        self.system.platform_ref = SYSTEM_KEY
        self.system.save(update_fields=['platform_ref'])
        with mock.patch.object(provenance, 'identity_for_spec',
                               return_value={'platform_ref': SYSTEM_KEY}), \
                mock.patch.object(provenance, 'set_identity',
                                  side_effect=lambda key, *a, **k: {'model': key}):
            # Rien n'est apparu : le repli vise la ligne existante, qui ne change pas de main.
            provenance.record_after_install({'kind': 'ollama', 'ref': 'x'}, [],
                                            owner=self.author)
        self.system.refresh_from_db()
        self.assertTrue(self.system.is_system)

    def test_without_identity_the_appeared_rows_still_get_their_author(self):
        from wama.model_manager.services import provenance
        appeared = _row('ollama:provenance-anonymous')
        with mock.patch.object(provenance, 'identity_for_spec', return_value=None):
            provenance.record_after_install({'kind': 'ollama', 'ref': 'x'},
                                            [appeared.model_key], owner=self.author)
        appeared.refresh_from_db()
        self.assertEqual(self.author, appeared.owner)


class TheManifestReadsTheRowTest(_Accounts):

    def test_the_manifest_carries_the_provenance_and_a_system_one_is_unchanged(self):
        from wama.common.manifests.ingest import extract
        mine = extract('model', PRIVATE_KEY)
        self.assertEqual(('provenance_author', 'private'), (mine['owner'], mine['visibility']))
        system = extract('model', SYSTEM_KEY)
        self.assertEqual('public', system['visibility'])
        for absent in ('owner', 'scope_org_unit', 'scope_project'):
            self.assertNotIn(absent, system)

    def test_a_private_model_is_not_a_corpus_target(self):
        from wama.common.management.commands.manifest_export import _model_keys
        keys = _model_keys()
        self.assertIn(SYSTEM_KEY, keys)
        self.assertNotIn(PRIVATE_KEY, keys)

    def test_promoting_the_manifest_gives_the_row_to_the_system(self):
        from wama.common.manifests.ingest import extract, ingest, promote
        obj = ingest(extract('model', PRIVATE_KEY), user=self.author, strict=False)
        promote(obj, by=self.admin)
        self.private.refresh_from_db()
        self.assertEqual((None, 'public'), (self.private.owner, self.private.visibility))
        self.assertEqual('provenance_author', obj.source.get('proposed_by'))
