"""À QUI EST un pipeline enregistré — l'étape 4 du chantier PROVENANCE (`ROADMAP §29`, 2026-10-19).

Un pipeline du Studio est un objet de TRAVAIL, comme une card (décision de Fabien) : le mécanisme
commun du partage (`WAMA_COLLABORATION §4.7`), et lui seul.

CE QUE CES GARDES TIENNENT :
  1. il naît privé à son auteur ; LIRE (la liste, le détail, l'assistant) suit sa portée —
     `listable_by` / `visible_or_404` — et l'administrateur n'y voit pas tout ;
  2. SUPPRIMER reste à son auteur (`owned_or_404`) ; enregistrer sous son nom en fait la copie de
     celui qui enregistre ;
  3. le lancement refuse un pipeline enregistré que le compte ne voit pas ; l'assistant lance,
     par son nom, le SIEN d'abord ;
  4. son manifeste lit propriétaire et portée sur la ligne.
"""
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from wama.accounts.models import UserProfile
from wama.accounts.permissions import GROUP_PREFIX
from wama.studio.models import StudioPipeline

GRAPH = {'nodes': [{'id': 1, 'app': 'function:calc_derivative', 'params': {}}], 'links': []}


def _account(username, tier='utilisateur'):
    user = get_user_model().objects.create_user(username, password='x')
    UserProfile.objects.update_or_create(user=user, defaults={'account_tier': tier})
    user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}communication')[0])
    return get_user_model().objects.get(pk=user.pk)


class _Pipelines(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.author = _account('pprov_author')
        cls.other = _account('pprov_other')
        cls.admin = _account('pprov_admin', 'admin')
        cls.private = StudioPipeline.objects.create(user=cls.author, name='Privé', graph=GRAPH)
        cls.shared = StudioPipeline.objects.create(user=cls.author, name='Partagé', graph=GRAPH,
                                                   visibility='public')


class ReadingFollowsTheScopeTest(_Pipelines):

    def test_a_new_pipeline_is_born_private(self):
        self.assertEqual('private',
                         StudioPipeline.objects.create(user=self.other, name='n', graph=GRAPH)
                         .visibility)

    def test_the_list_shows_ones_own_and_what_is_shared_and_nothing_more(self):
        url = reverse('studio:api_pipelines')
        for user, expected in ((self.author, {'Privé', 'Partagé'}), (self.other, {'Partagé'}),
                               (self.admin, {'Partagé'})):
            self.client.force_login(user)
            names = {p['name'] for p in self.client.get(url).json()['pipelines']}
            self.assertEqual(expected, names, user)

    def test_the_detail_opens_what_the_account_sees(self):
        self.client.force_login(self.other)
        detail = lambda p: reverse('studio:api_pipeline_detail', args=[p.pk])
        self.assertEqual(200, self.client.get(detail(self.shared)).status_code)
        self.assertEqual(404, self.client.get(detail(self.private)).status_code)

    def test_the_assistant_lists_and_runs_by_the_same_scope(self):
        from wama import tool_api
        names = {p['name'] for p in tool_api.list_studio_pipelines(self.other)['pipelines']}
        self.assertEqual({'Partagé'}, names)
        launched = []

        def fake_launch(user, graph, *, pipeline_id=None):
            launched.append(pipeline_id)
            return SimpleNamespace(pk=1), None
        with mock.patch('wama.studio.services.launch.launch_graph', side_effect=fake_launch):
            self.assertIn('error', tool_api.run_studio_pipeline(self.other,
                                                                pipeline_id=self.private.pk))
            mine = StudioPipeline.objects.create(user=self.other, name='Partagé', graph=GRAPH)
            # Le partagé est le plus RÉCENT : seul l'ordre « le sien d'abord » choisit le sien.
            StudioPipeline.objects.filter(pk=self.shared.pk).update(
                updated_at=mine.updated_at + timedelta(minutes=1))
            tool_api.run_studio_pipeline(self.other, pipeline_name='Partagé')
        self.assertEqual([mine.pk], launched)


class OnlyTheAuthorDeletesTest(_Pipelines):

    def test_a_shared_pipeline_is_deleted_by_its_author_only(self):
        url = reverse('studio:api_pipeline_detail', args=[self.shared.pk])
        self.client.force_login(self.other)
        self.assertEqual(404, self.client.delete(url).status_code)
        self.assertTrue(StudioPipeline.objects.filter(pk=self.shared.pk).exists())
        self.client.force_login(self.author)
        self.assertEqual(200, self.client.delete(url).status_code)
        self.assertFalse(StudioPipeline.objects.filter(pk=self.shared.pk).exists())

    def test_saving_under_its_name_makes_ones_own_copy(self):
        self.client.force_login(self.other)
        self.client.post(reverse('studio:api_pipelines'),
                         data={'name': 'Partagé', 'graph': GRAPH}, content_type='application/json')
        self.assertEqual(1, StudioPipeline.objects.filter(user=self.other, name='Partagé').count())
        self.shared.refresh_from_db()
        self.assertEqual(self.author, self.shared.user)


class LaunchingAndTheManifestTest(_Pipelines):

    def test_launching_rejects_a_saved_pipeline_the_account_does_not_see(self):
        from wama.studio.services.launch import launch_graph
        run, err = launch_graph(self.other, GRAPH, pipeline_id=self.private.pk)
        self.assertEqual((None, 'Pipeline introuvable'), (run, err))

    def test_the_manifest_reads_owner_and_scope_on_the_row(self):
        from wama.common.manifests.ingest import extract
        private = extract('pipeline', str(self.private.pk))
        self.assertEqual(('pprov_author', 'private'), (private['owner'], private['visibility']))
        self.assertEqual('public', extract('pipeline', str(self.shared.pk))['visibility'])
