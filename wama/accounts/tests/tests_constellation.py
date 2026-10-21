"""La constellation des utilisateurs (`accounts.constellation`, page `accounts:user-constellation`).

Ce que ces tests tiennent : la page est réservée à l'administration ET atteignable depuis la gestion
des utilisateurs ; chaque fait qu'elle montre est LU de sa brique — l'arbre des unités avec ses
ancêtres, l'unité que seul le profil porte (marquée comme telle), les projets, les partages EN
VIGUEUR orientés de celui qui partage vers celui qui reçoit, et le journal agrégé, qui doit rendre
exactement ce que rend `compter_par_app` compte par compte.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.common.models import ObjectGrant, OrgUnit, Project, ProjectMembership

User = get_user_model()


class ConstellationAccessTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('constellation_admin', password='x')
        cls.member = User.objects.create_user('constellation_member', password='x')

    def test_the_page_and_its_facts_are_reserved_to_administrators(self):
        self.client.force_login(self.member)
        for name in ('accounts:user-constellation', 'accounts:user-constellation-data'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertNotIn('/constellation', response.url)

    def test_an_administrator_reaches_it_from_the_user_management_page(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('accounts:user-management')).content.decode()
        self.assertIn(reverse('accounts:user-constellation'), html)
        page = self.client.get(reverse('accounts:user-constellation'))
        self.assertEqual(page.status_code, 200)
        # La page ne porte aucune donnée : elle désigne l'adresse de ses faits.
        self.assertIn(reverse('accounts:user-constellation-data'), page.content.decode())
        data = self.client.get(reverse('accounts:user-constellation-data')).json()
        for key in ('users', 'units', 'projects', 'shares', 'apps', 'worlds', 'tiers', 'roles',
                    'levels', 'scopes', 'account_kinds', 'families', 'uncarried_families'):
            self.assertIn(key, data)

    def test_the_embedded_page_drops_the_bar_and_masks_names_by_default(self):
        self.client.force_login(self.admin)
        url = reverse('accounts:user-constellation')
        full = self.client.get(url).content.decode()
        embedded = self.client.get(url + '?embed=1').content.decode()
        self.assertIn('class="top_nav"', full)
        self.assertNotIn('class="top_nav"', embedded)
        self.assertIn('data-embed="1"', embedded)
        self.assertNotIn('data-embed', full)
        # La couche « Noms » : allumée sur la page, éteinte dans la présentation.
        self.assertRegex(full, r'class="wc-chip on" data-layer="names"')
        self.assertRegex(embedded, r'class="wc-chip" data-layer="names"')

    def test_the_page_is_the_common_scene_page_mounted_by_the_users_adapter(self):
        # Premier consommateur de la brique commune des constellations (2026-10-21) : la page est
        # celle de toute scène, l'adaptateur des utilisateurs la monte.
        self.client.force_login(self.admin)
        response = self.client.get(reverse('accounts:user-constellation'))
        self.assertTemplateUsed(response, 'common/constellation.html')
        html = response.content.decode()
        self.assertIn('accounts/js/user-constellation.js', html)
        self.assertIn('id="wc-users-spec"', html)
        self.assertNotIn('data-generic', html)

    def test_the_presentation_embeds_it_for_an_administrator_only(self):
        embed = reverse('accounts:user-constellation') + '?embed=1'
        self.client.force_login(self.admin)
        html = self.client.get(reverse('presentation')).content.decode()
        self.assertIn('id="constellation"', html)
        self.assertIn(f'data-src="{embed}"', html)
        self.client.logout()
        html = self.client.get(reverse('presentation')).content.decode()
        self.assertIn('id="constellation"', html)
        self.assertNotIn(embed, html)
        self.assertIn('embed-closed', html)


class ConstellationFactsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        lab = OrgUnit.objects.create(code='UC-LAB', name='Labo témoin', unit_type='labo')
        cls.team = OrgUnit.objects.create(code='UC-TEAM', name='Équipe témoin', unit_type='equipe',
                                          parent=lab)
        cls.lab = lab
        OrgUnit.objects.create(code='UC-ELSEWHERE', name='Sans membre', unit_type='service')
        cls.alice = User.objects.create_user('uc_alice', password='x', first_name='Alice')
        cls.bob = User.objects.create_user('uc_bob', password='x')
        cls.carol = User.objects.create_user('uc_carol', password='x')
        for user, code, name in ((cls.alice, 'UC-TEAM', ''), (cls.bob, 'UC-LAB', ''),
                                 (cls.carol, 'UC-NOT-SYNCED', 'Service hors arbre')):
            profile = user.profile
            profile.org_entity_code, profile.org_entity_name = code, name
            profile.save()
        cls.project = Project.objects.create(code='UC-P', name='Projet témoin', lead=cls.alice)
        ProjectMembership.objects.create(project=cls.project, user=cls.alice, role='lead')
        ProjectMembership.objects.create(project=cls.project, user=cls.carol, role='partner')
        common = dict(object_type='common.Fake', state=ObjectGrant.STATE_GRANTED)
        ObjectGrant.objects.create(object_id=1, beneficiary=cls.bob, granted_by=cls.alice,
                                   level=ObjectGrant.LEVEL_READ, **common)
        ObjectGrant.objects.create(object_id=2, beneficiary=cls.bob, granted_by=cls.alice,
                                   level=ObjectGrant.LEVEL_COLLABORATE, **common)
        # Ni un droit retiré, ni une promotion au système ne relient deux personnes.
        ObjectGrant.objects.create(object_id=3, beneficiary=cls.carol, granted_by=cls.alice,
                                   level=ObjectGrant.LEVEL_READ, object_type='common.Fake',
                                   state=ObjectGrant.STATE_REVOKED)
        ObjectGrant.objects.create(object_id=4, beneficiary=cls.carol, granted_by=cls.carol,
                                   level=ObjectGrant.LEVEL_SYSTEM, **common)
        # Partage à une PORTÉE : la mémoire datée sans bénéficiaire (`sharing._record_scope_share`).
        ObjectGrant.objects.create(object_id=5, visibility='unit', scope_org_unit=lab,
                                   granted_by=cls.bob, level=ObjectGrant.LEVEL_READ, **common)

    def setUp(self):
        from wama.accounts.constellation import constellation
        self.data = constellation()
        self.by_name = {u['username']: u for u in self.data['users']}

    def test_a_member_is_placed_in_their_unit_and_its_ancestors(self):
        units = {str(u['id']): u for u in self.data['units']}
        self.assertEqual(self.by_name['uc_alice']['units'], [self.team.id])
        self.assertIn(str(self.team.id), units)
        self.assertEqual(units[str(self.team.id)]['parent'], self.lab.id)
        self.assertIn(str(self.lab.id), units)
        self.assertNotIn('UC-ELSEWHERE', [u['code'] for u in self.data['units']])

    def test_an_entity_only_the_profile_carries_is_shown_and_marked(self):
        carol = self.by_name['uc_carol']
        declared = [u for u in self.data['units'] if u['source'] == 'profile']
        self.assertEqual([(u['code'], u['name']) for u in declared],
                         [('UC-NOT-SYNCED', 'Service hors arbre')])
        self.assertEqual(carol['units'], [declared[0]['id']])

    def test_projects_carry_their_members_and_roles(self):
        project = next(p for p in self.data['projects'] if p['code'] == 'UC-P')
        self.assertEqual(project['lead'], self.alice.id)
        self.assertEqual(sorted((m['user'], m['role']) for m in project['members']),
                         sorted([(self.alice.id, 'lead'), (self.carol.id, 'partner')]))

    def test_shares_in_force_go_from_the_sharer_to_the_recipient(self):
        edges = [e for e in self.data['shares']
                 if {e['from'], e['to']} <= {self.alice.id, self.bob.id, self.carol.id}]
        self.assertEqual(edges, [{'from': self.alice.id, 'to': self.bob.id, 'count': 2,
                                  'levels': {'read': 1, 'collaborate': 1}}])
        self.assertEqual(self.by_name['uc_bob']['scope_shares'],
                         [{'visibility': 'unit', 'unit': self.lab.id, 'project': None, 'count': 1}])

    def test_rights_and_profile_come_from_the_access_decision(self):
        from wama.accounts.permissions import accessible
        alice = self.by_name['uc_alice']
        self.assertEqual(alice['kind'], 'person')
        self.assertEqual(alice['name'], 'Alice')
        app_ids = [a['id'] for a in self.data['apps']]
        self.assertEqual(alice['apps'], [a for a in app_ids if accessible(self.alice, 'app', a)])

    def test_families_without_an_author_are_named_not_hidden(self):
        from wama.common.registries import REGISTRIES, TO_CARRY
        self.assertEqual({f['key'] for f in self.data['uncarried_families']},
                         {r.key for r in REGISTRIES.values() if r.provenance == TO_CARRY})


class CountByAppPerUserTest(TestCase):
    """L'agrégat du journal rend, compte par compte, ce que rend `compter_par_app`."""

    def test_it_matches_the_per_user_count(self):
        from wama.avatarizer.models import AvatarJob
        from wama.composer.models import ComposerGeneration
        from wama.common.services.journal import compter_par_app, count_by_app_per_user
        busy, other, idle = (User.objects.create_user(f'uc_journal_{i}', password='x')
                             for i in range(3))
        for i in range(3):
            ComposerGeneration.objects.create(user=busy, prompt=f'témoin {i}')
        AvatarJob.objects.create(user=busy)
        ComposerGeneration.objects.create(user=other, prompt='témoin')
        aggregated = count_by_app_per_user()
        totals = {row['app']: row['total'] for row in aggregated[busy.id]}
        self.assertEqual((totals.get('composer'), totals.get('avatarizer')), (3, 1))
        for user in (busy, other, idle):
            self.assertEqual(aggregated.get(user.id, []), compter_par_app(user))
