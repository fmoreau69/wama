"""Les données d'annuaire s'ajoutent AVEC la personne, et un rôle métier se demande
(`accounts/directory_consent.py`, `accounts/role_requests.py`, `PROFILES_PERMISSIONS.md §1.12`,
2026-11-25).

L'annuaire est celui, inventé, de `tests_directory` : la liaison est un faux qui ne rend que ce
qu'on lui réclame, la fiche d'une personne est simulée au point où la librairie la charge.
"""
import html
import json
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from wama.accounts import directory, directory_consent, role_requests
from wama.accounts import ldap as account_ldap
from wama.accounts.ldap_backend import WamaLDAPBackend
from wama.accounts.models import AccessGrant
from wama.accounts.permissions import GROUP_PREFIX, set_account_tier, user_roles
from wama.common.models import Notification

from .tests_directory import DIRECTORY_SETTINGS, FakeDirectory, _directory_people


class DirectoryDataShapeTests(SimpleTestCase):
    """Ce que la connexion lit et ce que la personne choisit sont la même liste."""

    def test_every_field_read_from_the_directory_belongs_to_exactly_one_choice(self):
        read = set(account_ldap._parse_org({}))
        chosen = [field for datum in directory_consent.DIRECTORY_DATA.values()
                  for field in datum['fields']]
        self.assertEqual(sorted(read), sorted(chosen),
                         "un champ lu de l'annuaire sans pastille ne s'écrirait jamais ; "
                         "un champ sous deux pastilles se choisirait deux fois")
        self.assertLessEqual(set(account_ldap.MINIMUM_FIELDS), read)

    def test_the_status_falls_back_on_every_quality_when_no_main_one_is_given(self):
        both = account_ldap._parse_org({'eduPersonPrimaryAffiliation': ['staff'],
                                        'eduPersonAffiliation': ['member', 'staff']})
        self.assertEqual('staff', both['ldap_affiliation'])
        only_all = account_ldap._parse_org({'eduPersonAffiliation': ['member', 'researcher']})
        self.assertEqual('member, researcher', only_all['ldap_affiliation'])

    def test_what_a_sign_in_reads_is_inside_the_closed_list_of_the_settings(self):
        from django.conf import settings
        allowed = getattr(settings, 'AUTH_LDAP_USER_ATTRLIST', None)
        if not allowed:
            self.skipTest("aucune liste d'attributs réglée sur cette instance")
        self.assertLessEqual(set(account_ldap.ORG_ATTRIBUTES), set(allowed))


@override_settings(**DIRECTORY_SETTINGS)
class DirectoryConsentTests(TestCase):
    """Le minimum à la création, rien de neuf sans accord, une donnée retirée ne revient pas."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('the.admin', password='x', email='admin@test.local')
        set_account_tier(cls.admin, 'admin')

    def setUp(self):
        people = _directory_people()
        people.start()
        self.addCleanup(people.stop)
        connect = mock.patch.object(directory, 'connect', side_effect=FakeDirectory)
        connect.start()
        self.addCleanup(connect.stop)

    def _sign_in_again(self, username):
        """Ce que la librairie fait à chaque connexion : relire la fiche, remplir le compte."""
        return WamaLDAPBackend().populate_user(username)

    def _profile(self, username):
        return User.objects.get(username=username).profile

    def _came(self, username):
        """Un compte activé, comme après la validation d'un administrateur."""
        user = self._sign_in_again(username)
        User.objects.filter(pk=user.pk).update(is_active=True)
        return User.objects.get(pk=user.pk)

    def _post(self, payload):
        return self.client.post(reverse('accounts:directory-consent'), data=json.dumps(payload),
                                content_type='application/json')

    # ── Ce que la connexion écrit ───────────────────────────────────────────────────────────

    def test_a_new_account_gets_the_minimum_and_a_later_sign_in_adds_nothing_unasked(self):
        self._sign_in_again('zoe.martin')
        self._sign_in_again('zoe.martin')
        profile = self._profile('zoe.martin')
        self.assertEqual(('LAB-A', [], '', ''),
                         (profile.org_entity_code, profile.org_affiliations, profile.establishment,
                          profile.ldap_affiliation))
        self.assertTrue(directory_consent.pending(profile.user))

    def test_an_added_datum_is_refreshed_and_a_removed_one_never_comes_back(self):
        zoe = self._came('zoe.martin')
        legacy = zoe.profile
        legacy.org_affiliations = ['LAB-A', 'OLD-A']        # ce qu'un profil d'avant portait
        legacy.save()
        rows = directory_consent.decide(zoe, accept=['status'], decline=['main_unit'])
        self.assertEqual({'main_unit': 'declined', 'establishment': 'undecided', 'status': 'accepted'},
                         {row['key']: row['choice'] for row in rows})
        profile = self._profile('zoe.martin')
        # Ajoutée : lue de l'annuaire à l'instant. Retirée : effacée — le nom, la hiérarchie et
        # les anciens codes de rattachement avec elle.
        self.assertEqual('member, researcher', profile.ldap_affiliation)
        self.assertEqual(('', '', [], []), (profile.org_entity_code, profile.org_entity_name,
                                            profile.org_hierarchy, profile.org_affiliations))
        self.assertFalse(directory_consent.pending(zoe))
        profile.ldap_affiliation = 'stale'
        profile.save()
        self._sign_in_again('zoe.martin')
        profile = self._profile('zoe.martin')
        self.assertEqual('member, researcher', profile.ldap_affiliation, "ajoutée : tenue à jour")
        self.assertEqual(('', ''), (profile.org_entity_code, profile.establishment),
                         "retirée : ne revient pas ; sans choix : toujours pas ajoutée")

    def test_an_account_from_before_keeps_what_it_holds_until_its_holder_chooses(self):
        """Aucun compte existant ne perd rien : ce que le profil portait reste tenu à jour."""
        zoe = self._came('zoe.martin')
        profile = zoe.profile
        profile.org_affiliations, profile.establishment = ['STALE'], '{UAI}OLD'
        profile.save()
        self._sign_in_again('zoe.martin')
        profile = self._profile('zoe.martin')
        self.assertEqual(('{UAI}0000000X', ''), (profile.establishment, profile.ldap_affiliation))
        # Les autres codes de la fiche ne se lisent plus : ce qu'un profil en portait reste tel
        # quel (rien n'est effacé sans la personne), et plus rien ne s'en sert.
        self.assertEqual(['STALE'], profile.org_affiliations)
        rows = {row['key']: row for row in directory_consent.state(zoe, proposed={})}
        self.assertEqual(('undecided', True), (rows['establishment']['choice'], rows['establishment']['stored']))
        self.assertEqual(('undecided', False), (rows['status']['choice'], rows['status']['stored']))

    # ── Ce que la personne choisit ──────────────────────────────────────────────────────────

    def test_a_value_always_comes_from_the_directory_never_from_the_browser(self):
        zoe = self._came('zoe.martin')
        directory_consent.decide(zoe, decline=['main_unit'])
        self.client.force_login(zoe)
        done = self._post({'accept': ['main_unit'], 'org_entity_code': 'LAB-B',
                           'value': 'LAB-B', 'main_unit': 'LAB-B'})
        self.assertTrue(done.json()['success'])
        self.assertEqual('LAB-A', self._profile('zoe.martin').org_entity_code)
        self.assertEqual(400, self._post({'accept': ['no_such_datum']}).status_code)
        self.assertEqual(400, self._post({'accept': ['status'], 'decline': ['status']}).status_code)
        self.assertEqual(400, self.client.post(reverse('accounts:directory-consent'), data='nope',
                                               content_type='application/json').status_code)

    def test_the_panel_reads_each_choice_what_is_kept_and_what_the_directory_offers(self):
        zoe = self._came('zoe.martin')
        self.client.force_login(zoe)
        told = self.client.get(reverse('accounts:directory-consent')).json()
        rows = {row['key']: row for row in told['data']}
        self.assertEqual(list(directory_consent.DIRECTORY_DATA), [row['key'] for row in told['data']])
        self.assertEqual(('undecided', True, 'LAB-A'),
                         tuple(rows['main_unit'][k] for k in ('choice', 'stored', 'value')))
        self.assertEqual(('undecided', False, '', '0000000X'),
                         tuple(rows['establishment'][k] for k in ('choice', 'stored', 'value', 'offer')))
        self.assertEqual({'main_unit', 'establishment', 'status'}, set(rows),
                         "une seule appartenance : les autres codes d'une fiche ne se proposent pas")
        self.assertEqual('member, researcher', rows['status']['offer'])
        self.assertTrue(all(row['opens'] for row in told['data']))
        self.assertFalse(told['answered'])
        self.assertEqual(set(role_requests.ROLES), {role['key'] for role in told['roles']})
        # « Terminer » sans rien changer : la personne a vu, le panneau ne revient plus.
        seen = self._post({'acknowledge': True}).json()
        self.assertTrue(seen['answered'])
        self.assertEqual({}, self._profile('zoe.martin').directory_consent)

    def test_a_silent_directory_keeps_the_choice_and_the_value_comes_at_the_next_sign_in(self):
        zoe = self._came('zoe.martin')
        with mock.patch.object(directory, 'connect',
                               side_effect=directory.DirectoryUnavailable('muet')):
            rows = {row['key']: row for row in directory_consent.decide(zoe, accept=['establishment'])}
        self.assertEqual(('accepted', False), (rows['establishment']['choice'],
                                               rows['establishment']['stored']))
        self._sign_in_again('zoe.martin')
        self.assertEqual('{UAI}0000000X', self._profile('zoe.martin').establishment)

    def test_only_a_directory_account_has_directory_data(self):
        local = User.objects.create_user('local.person', password='x')
        self.assertFalse(directory_consent.applies(local))
        self.assertFalse(directory_consent.pending(local))
        self.client.force_login(local)
        self.assertEqual(400, self.client.get(reverse('accounts:directory-consent')).status_code)
        page = self.client.get(reverse('accounts:profile')).content.decode()
        self.assertNotIn('data-directory-consent', page)
        self.client.logout()
        self.assertEqual(302, self.client.get(reverse('accounts:directory-consent')).status_code)

    # ── Le panneau d'accueil ────────────────────────────────────────────────────────────────

    def _login(self, user, **extra):
        with mock.patch.object(WamaLDAPBackend, 'authenticate', return_value=user):
            return self.client.post(reverse('accounts:login'),
                                    {'username': user.username, 'password': 'directory-ok', **extra},
                                    REMOTE_ADDR='10.1.2.3', HTTP_USER_AGENT='Mozilla/5.0')

    def test_a_first_sign_in_lands_on_the_welcome_panel_and_then_goes_where_it_was_going(self):
        zoe = self._came('zoe.martin')
        landed = self._login(zoe, next='/converter/')
        self.assertEqual(f"{reverse('accounts:profile')}?welcome=1&next=%2Fconverter%2F", landed['Location'])
        page = self.client.get(landed['Location']).content.decode()
        self.assertIn('id="directoryWelcomeModal"', page)
        self.assertIn('data-next="/converter/"', page)
        self.assertEqual(2, page.count('data-directory-consent'), "la carte du profil et le panneau")
        self.assertIn('accounts/js/directory-consent.js', page)
        # Une adresse du dehors glissée dans `next` ne sort pas de l'instance.
        forged = self.client.get(reverse('accounts:profile'), {'welcome': 1, 'next': 'https://evil.example/'})
        self.assertIn('data-next=""', forged.content.decode())
        self._post({'acknowledge': True})
        self.client.logout()
        again = self._login(User.objects.get(pk=zoe.pk), next='/converter/')
        self.assertEqual('/converter/', again['Location'])
        calm = self.client.get(reverse('accounts:profile'), {'welcome': 1}).content.decode()
        self.assertNotIn('id="directoryWelcomeModal"', calm)
        self.assertEqual(1, calm.count('data-directory-consent'))

    # ── Un rôle métier se demande ───────────────────────────────────────────────────────────

    def _requests_to(self, user):
        return Notification.objects.filter(recipient=user, kind='access_request')

    def test_a_person_asks_for_a_role_and_an_administrator_gives_it(self):
        zoe = self._came('zoe.martin')
        self.assertEqual(set(), set(user_roles(zoe)), "aucun rôle par défaut")
        self.client.force_login(zoe)
        asked = self.client.post(reverse('accounts:role-request'), {'role': 'recherche'}).json()
        self.assertTrue(asked['done'])
        again = self.client.post(reverse('accounts:role-request'), {'role': 'recherche'}).json()
        self.assertEqual(asked['id'], again['id'], "une demande en attente n'est pas refaite")
        self.assertEqual(1, self._requests_to(self.admin).count())
        self.assertFalse(self.client.post(reverse('accounts:role-request'),
                                          {'role': 'no_such_role'}).json()['done'])
        grant = AccessGrant.objects.get(pk=asked['id'])
        self.assertEqual((role_requests.KIND_ROLE, 'recherche', AccessGrant.STATE_REQUESTED),
                         (grant.kind, grant.element_id, grant.state))
        # La demandeuse voit sa demande ; elle ne peut pas y répondre.
        own = html.unescape(
            self.client.get(reverse('accounts:app-access-page', args=[grant.pk])).content.decode())
        self.assertIn('Le rôle métier « Recherche »', own)
        self.assertIn("attend la réponse d'un administrateur", own)
        self.assertFalse(self.client.post(reverse('accounts:app-access-answer', args=[grant.pk]),
                                          {'accept': '1'}).json()['done'])
        self.assertEqual(set(), set(user_roles(User.objects.get(pk=zoe.pk))))

        self.client.force_login(self.admin)
        page = self.client.get(reverse('accounts:app-access-page', args=[grant.pk])).content.decode()
        self.assertIn('data-request-answer="1"', page)
        done = self.client.post(reverse('accounts:app-access-answer', args=[grant.pk]), {'accept': '1'})
        self.assertEqual({'done': True, 'state': 'granted'}, done.json())
        self.assertEqual({'recherche'}, set(user_roles(User.objects.get(pk=zoe.pk))))
        self.assertTrue(Notification.objects.filter(recipient=zoe, kind='access_granted').exists())
        with self.assertRaises(role_requests.RoleRequestRefused):
            role_requests.request_role(User.objects.get(pk=zoe.pk), 'recherche')

    def test_a_role_asked_for_can_be_turned_down_and_a_third_person_sees_nothing(self):
        zoe, lea = self._came('zoe.martin'), self._came('lea.roux')
        grant = role_requests.request_role(zoe, 'communication', 'je fais les affiches')
        self.client.force_login(lea)
        self.assertEqual(404, self.client.get(reverse('accounts:app-access-page', args=[grant.pk])).status_code)
        self.client.force_login(self.admin)
        done = self.client.post(reverse('accounts:app-access-answer', args=[grant.pk]), {'accept': '0'})
        self.assertEqual('refused', done.json()['state'])
        self.assertEqual(set(), set(user_roles(User.objects.get(pk=zoe.pk))))
        self.assertTrue(Notification.objects.filter(recipient=zoe, kind='access_request_refused').exists())
        self.assertFalse(self.client.post(reverse('accounts:app-access-answer', args=[grant.pk]),
                                          {'accept': '1'}).json()['done'], "déjà répondue")

    def test_setting_the_role_by_hand_on_the_accounts_page_answers_the_pending_request(self):
        zoe = self._came('zoe.martin')
        grant = role_requests.request_role(zoe, 'ingenierie')
        self.client.force_login(self.admin)
        page = self.client.get(reverse('accounts:user-management')).content.decode()
        self.assertIn(reverse('accounts:app-access-page', args=[grant.pk]), page)
        badge = 'ms-1 role-requested text-decoration-none'      # la pastille « demandé » de la ligne
        self.assertIn(badge, page)
        done = self.client.post(reverse('accounts:user-toggle-metier-role', args=[zoe.pk]),
                                data=json.dumps({'role': 'ingenierie', 'enabled': True}),
                                content_type='application/json')
        self.assertTrue(done.json()['success'])
        grant.refresh_from_db()
        self.assertEqual((AccessGrant.STATE_GRANTED, self.admin), (grant.state, grant.granted_by))
        self.assertTrue(zoe.groups.filter(name=GROUP_PREFIX + 'ingenierie').exists())
        self.assertEqual({}, role_requests.pending_by_user())
        self.assertNotIn(badge, self.client.get(reverse('accounts:user-management')).content.decode())

    def test_a_request_for_a_sandbox_app_still_reads_and_answers_as_before(self):
        """Contre-épreuve de la page commune : la famille d'une ligne décide de ce qu'elle dit."""
        from wama.accounts import app_access
        grant = AccessGrant.objects.create(subject_type=AccessGrant.SUBJECT_USER,
                                           subject_id=self.admin.pk, kind=app_access.KIND_APP,
                                           element_id='writer_99')
        summary = app_access.request_summary(grant)
        self.assertIn("l'app du bac à sable", summary['what'])
        self.assertIn('writer_99', summary['what'])
        from wama.accounts.views import _grant_family
        self.assertIs(app_access, _grant_family(grant))
        self.assertIs(role_requests, _grant_family(AccessGrant(kind=role_requests.KIND_ROLE)))
        self.assertIsNone(_grant_family(AccessGrant(kind='something_else')))

    # ── Les mêmes gestes par l'assistant ────────────────────────────────────────────────────

    def test_the_assistant_reads_and_changes_only_the_caller_own_directory_data(self):
        from wama import tool_api
        zoe = self._came('zoe.martin')
        told = tool_api.get_my_directory_data(zoe)
        self.assertEqual({'main_unit': 'undecided', 'establishment': 'undecided', 'status': 'undecided'},
                         {row['key']: row['choice'] for row in told['data']})
        self.assertNotIn('offer', told['data'][0], "l'outil dit ce que WAMA garde, il n'interroge pas l'annuaire")
        done = tool_api.set_my_directory_data(zoe, add=['establishment'], remove=['main_unit'])
        self.assertEqual({'main_unit': 'declined', 'establishment': 'accepted'},
                         {row['key']: row['choice'] for row in done['data']
                          if row['key'] in ('main_unit', 'establishment')})
        self.assertEqual(('', '{UAI}0000000X'), (self._profile('zoe.martin').org_entity_code,
                                                 self._profile('zoe.martin').establishment))
        self.assertIn('error', tool_api.set_my_directory_data(zoe, add=['no_such_datum']))
        self.assertIn('error', tool_api.set_my_directory_data(zoe))
        self.assertIn('error', tool_api.get_my_directory_data(self.admin), "compte local")
        self.assertIn('error', tool_api.get_my_directory_data(None))

    def test_the_assistant_asks_for_a_role_and_only_an_administrator_answers(self):
        from wama import tool_api
        zoe, lea = self._came('zoe.martin'), self._came('lea.roux')
        asked = tool_api.request_role(zoe, 'administratif', 'gestion')
        self.assertTrue(asked['requested'])
        self.assertIn('error', tool_api.request_role(zoe, 'no_such_role'))
        self.assertEqual([asked['request_id']], [row['id'] for row in tool_api.list_role_requests(zoe)['mine']])
        self.assertEqual([], tool_api.list_role_requests(zoe)['to_answer'])
        self.assertEqual([asked['request_id']],
                         [row['id'] for row in tool_api.list_role_requests(self.admin)['to_answer']])
        self.assertIn('administrateur', tool_api.answer_role_request(lea, asked['request_id'], True)['error'])
        self.assertEqual(set(), set(user_roles(User.objects.get(pk=zoe.pk))))
        done = tool_api.answer_role_request(self.admin, asked['request_id'], True)
        self.assertEqual((True, 'granted'), (done['answered'], done['state']))
        self.assertEqual({'administratif'}, set(user_roles(User.objects.get(pk=zoe.pk))))
        self.assertIn('error', tool_api.answer_role_request(self.admin, 999999, True))
        for name in ('get_my_directory_data', 'set_my_directory_data', 'request_role',
                     'list_role_requests', 'answer_role_request'):
            self.assertIn(name, tool_api.TOOL_REGISTRY)
        self.assertTrue(Group.objects.filter(name=GROUP_PREFIX + 'administratif').exists())
