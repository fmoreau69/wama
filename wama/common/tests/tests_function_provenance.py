"""À QUI EST une fonction — l'étape 4 du chantier PROVENANCE (`ROADMAP §29`, 2026-10-19).

CE QUE CES GARDES TIENNENT :
  1. une fonction du CODE n'a pas d'auteur à elle : elle suit l'app qui la PORTE
     (`function_catalog.spec_app`) — système dans une app réelle, à son créateur dans une
     jumelle. La décision unique (`accessible(user, 'function', clé)`), la liste
     (`accessible_specs`), la palette du Studio, la page du catalogue, le lancement d'un graphe
     et les pipelines déclarés en code disent la MÊME chose ;
  2. une fonction d'UTILISATEUR suit sa ligne : son auteur et l'administrateur la voient
     (décision c), personne d'autre ;
  3. promouvoir le manifeste d'une fonction d'utilisateur ne vide pas sa ligne : son
     propriétaire est obligatoire, sa promotion la fait entrer au catalogue CODE.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from wama.accounts.models import AppAccessPolicy, UserProfile
from wama.accounts.permissions import GROUP_PREFIX, accessible
from wama.common.catalog import function_catalog as fc
from wama.common.models import UserFunction

TWIN = 'provtwin_01'
TWIN_FUNCTION = f'{TWIN}.process'
SYSTEM_FUNCTION = 'calc_derivative'          # fonction pure du monde Data (`wama_data`)
USER_FUNCTION = 'provenance_user_function'
CREATOR = 'fprov_creator'


def _account(username, tier, *roles):
    user = get_user_model().objects.create_user(username, password='x')
    UserProfile.objects.update_or_create(user=user, defaults={'account_tier': tier})
    for role in roles:
        user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
    return get_user_model().objects.get(pk=user.pk)


class _TwinAndAccounts(TestCase):
    """Une jumelle comme celles du bac à sable : réservée aux développeurs (politique mesurée le
    2026-10-19 sur les 14 jumelles), son créateur y accède quel que soit son profil."""

    @classmethod
    def setUpTestData(cls):
        policy = AppAccessPolicy.objects.create(app_id=TWIN, min_tier='developpeur')
        policy.roles.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}ingenierie')[0])
        cls.creator = _account(CREATOR, 'utilisateur', 'communication')
        cls.other = _account('fprov_other', 'utilisateur', 'communication')
        cls.dev = _account('fprov_dev', 'developpeur', 'communication')
        cls.admin = _account('fprov_admin', 'admin')
        cls.user_function = UserFunction.objects.create(
            key=USER_FUNCTION, name='Fonction privée', owner=cls.creator, visibility='private')

    def setUp(self):
        fc.load_all()
        self.spec = fc.FunctionSpec(key=TWIN_FUNCTION, name='Process de jumelle',
                                    description='', category='transform',
                                    binding=fc.Binding.APP, app=TWIN, impl='x.tasks:run')
        fc.FUNCTION_CATALOG[TWIN_FUNCTION] = self.spec
        self.addCleanup(fc.FUNCTION_CATALOG.pop, TWIN_FUNCTION, None)
        registry = [{'label': TWIN, 'created_by': CREATOR}]
        for target, value in (('load_registry', mock.Mock(return_value=registry)),
                              ('twin_owner', lambda label: CREATOR if label == TWIN else '')):
            patcher = mock.patch(f'wama.common.sandbox.{target}', value)
            patcher.start()
            self.addCleanup(patcher.stop)


class ACodeFunctionFollowsTheAppThatCarriesItTest(_TwinAndAccounts):

    def test_the_app_of_a_function_is_the_one_it_names_or_the_one_holding_its_code(self):
        self.assertEqual(TWIN, fc.spec_app(self.spec))
        self.assertEqual('wama_data', fc.spec_app(fc.get(SYSTEM_FUNCTION)))

    def test_the_decision_and_the_list_say_the_same_thing(self):
        specs = [self.spec, fc.get(SYSTEM_FUNCTION)]
        for user, sees_twin in ((self.creator, True), (self.dev, True), (self.admin, True),
                                (self.other, False)):
            self.assertEqual(sees_twin, accessible(user, 'function', TWIN_FUNCTION), user)
            self.assertTrue(accessible(user, 'function', SYSTEM_FUNCTION), user)
            listed = {s.key for s in fc.accessible_specs(user, specs)}
            self.assertEqual({SYSTEM_FUNCTION} | ({TWIN_FUNCTION} if sees_twin else set()),
                             listed, user)

    def test_an_unknown_key_is_restricted_by_nothing(self):
        self.assertTrue(accessible(self.other, 'function', 'no.such_function'))

    def test_a_code_function_has_no_provenance_fields_of_its_own(self):
        self.assertNotIn('visibility', self.spec.to_dict())
        self.assertNotIn('owner', self.spec.to_dict())

    def test_the_studio_palette_and_the_catalogue_page_list_the_same_code_functions(self):
        import json
        for user, sees in ((self.creator, True), (self.other, False)):
            self.client.force_login(user)
            nodes = self.client.get(reverse('studio:api_nodes')).json()['nodes']
            self.assertEqual(sees, f'function:{TWIN_FUNCTION}' in nodes, user)
            self.assertIn(f'function:{SYSTEM_FUNCTION}', nodes)
            page = self.client.get(reverse('model_manager:functions_catalog'))
            listed = {f['key'] for f in json.loads(page.context['functions_json'])}
            self.assertEqual(sees, TWIN_FUNCTION in listed, user)
            self.assertIn(SYSTEM_FUNCTION, listed)

    def test_launching_a_graph_rejects_a_function_the_account_may_not_see(self):
        from wama.studio.services.launch import launch_graph
        graph = {'nodes': [{'id': 1, 'app': f'function:{TWIN_FUNCTION}', 'params': {}}],
                 'links': []}
        run, err = launch_graph(self.other, graph)
        self.assertIsNone(run)
        self.assertIn(TWIN_FUNCTION, err)
        self.assertIn('non accessible', err)
        with mock.patch('wama.studio.tasks.run_pipeline_task') as task:
            task.delay.return_value.id = 'task-id'
            run, err = launch_graph(self.creator, graph)
        self.assertIsNone(err)
        self.assertEqual(self.creator, run.user)

    def test_a_pipeline_declared_by_a_twin_opens_for_who_may_run_it(self):
        from wama.common.manifests.builtin.pipeline import PIPELINE_SOURCES, register_pipeline_source
        from wama.studio.views import _declared_pipelines
        manifest = {'manifest_kind': 'pipeline', 'key': TWIN, 'name': TWIN, 'owner': None,
                    'visibility': 'public',
                    'body': {'nodes': [{'id': 'a', 'kind': 'function',
                                        'function': TWIN_FUNCTION}], 'links': []}}
        register_pipeline_source(TWIN, lambda: manifest)
        self.addCleanup(PIPELINE_SOURCES.pop, TWIN, None)
        self.assertIn(TWIN, _declared_pipelines(self.creator, [TWIN]))
        self.assertNotIn(TWIN, _declared_pipelines(self.other, [TWIN]))
        self.client.force_login(self.other)
        url = reverse('studio:api_declared_pipeline_detail', args=[TWIN])
        self.assertEqual(404, self.client.get(url).status_code)


class AUserFunctionFollowsItsRowTest(_TwinAndAccounts):

    def test_the_author_and_the_admin_see_it_nobody_else(self):
        for user, sees in ((self.creator, True), (self.admin, True), (self.other, False),
                           (self.dev, False)):
            self.assertEqual(sees, accessible(user, 'function', USER_FUNCTION), user)

    def test_the_catalogue_page_lists_it_by_account(self):
        import json
        for user, sees in ((self.creator, True), (self.admin, True), (self.other, False)):
            self.client.force_login(user)
            page = self.client.get(reverse('model_manager:functions_catalog'))
            listed = {f['key'] for f in json.loads(page.context['functions_json'])}
            self.assertEqual(sees, USER_FUNCTION in listed, user)

    def test_promoting_its_manifest_leaves_the_row_to_its_author(self):
        from wama.common.manifests.ingest import extract, ingest, promote
        from wama.common.manifests.ownership import promote_row
        self.assertEqual(0, promote_row('function', USER_FUNCTION))
        obj = ingest(extract('function', USER_FUNCTION), user=self.creator, strict=False)
        promote(obj, by=self.admin)
        self.user_function.refresh_from_db()
        self.assertEqual((self.creator, 'private'),
                         (self.user_function.owner, self.user_function.visibility))
