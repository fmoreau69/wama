"""THE ACCESS TO A SANDBOX APP — one rule, and its opening by a grant (2026-11-02, Fabien's decisions):
« une seule règle partout, un dev ne voit que ses propres apps, admin toutes » ; « on est censé
pouvoir surcharger l'accès à une app via le partage » ; « créateur et admin accordent, aux devs
seulement, pour le moment : utiliser/tester ».

What is held :
  1. the decision (`accessible`, the grouped read included) : an administrator, every sandbox app ;
     a developer, the ones they created and the ones opened to them (a grant in force) ; a plain
     user, none — a policy edited in the database does not widen it ;
  2. a developer REQUESTS, the creator and the administrators are told ; a plain user, an
     administrator or someone who already has access cannot request ;
  3. the creator or an administrator GRANTS (a pending request included), answers, REVOKES — at
     once ; another developer cannot, and nobody grants a plain user ;
  4. a grant opens USE only : developing the app (regenerate, revert, remove) stays with its
     creator and the administrators ;
  5. the surfaces : the request page, the apps catalogue (hidden from a plain user, « Demander
     l'accès » for a developer), the « Partages » page, and the assistant's tools.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from wama.accounts import app_access
from wama.accounts.models import AccessGrant, UserProfile
from wama.accounts.permissions import DEFAULT_APP_ACCESS, accessible, accessible_apps

APP = 'notes_01'
CLI_APP = 'clitwin_01'
REGISTRY = [{'label': APP, 'generated_from': '', 'created_by': 'access_creator'},
            {'label': CLI_APP, 'generated_from': 'reader', 'created_by': ''}]


def _account(name, tier='utilisateur'):
    user = get_user_model().objects.create_user(name, password='x')
    UserProfile.objects.update_or_create(user=user, defaults={'account_tier': tier})
    return get_user_model().objects.get(pk=user.pk)


class _Sandbox(TestCase):
    """The sandbox registry is GITIGNORED : posed here, so HEAD measures the rule, not the tree."""

    def setUp(self):
        policy = {'roles': ['ingenierie'], 'min_tier': 'developpeur'}
        # Lecture ET écriture simulées : une écriture du registre (un développeur qui régénère
        # rejoint ses développeurs) ne doit jamais atteindre le vrai fichier (2026-11-02, vécu).
        # Une copie NEUVE à chaque lecture : une écriture d'un test ne déborde pas sur le suivant.
        for patch in (mock.patch('wama.common.sandbox.load_registry',
                                 side_effect=lambda: [dict(e) for e in REGISTRY]),
                      mock.patch('wama.common.sandbox.save_registry'),
                      mock.patch.dict(DEFAULT_APP_ACCESS, {APP: policy, CLI_APP: policy})):
            patch.start()
            self.addCleanup(patch.stop)
        self.creator = _account('access_creator', 'developpeur')
        self.dev = _account('access_dev', 'developpeur')
        self.admin = _account('access_admin', 'admin')
        self.plain = _account('access_plain')


class OneRuleTest(_Sandbox):

    def test_admin_all_developer_their_own_plain_user_none(self):
        for user, own, cli in ((self.admin, True, True), (self.creator, True, False),
                               (self.dev, False, False), (self.plain, False, False)):
            with self.subTest(user=user.username):
                self.assertEqual((own, cli), (accessible(user, 'app', APP),
                                              accessible(user, 'app', CLI_APP)))
                self.assertEqual([a for a in (APP, CLI_APP, 'reader') if accessible(user, 'app', a)],
                                 accessible_apps(user, [APP, CLI_APP, 'reader']),
                                 'the grouped read decides exactly like the unit decision')

    def test_a_grant_in_force_opens_it_an_expired_or_revoked_one_does_not(self):
        grant = app_access.grant_access(self.creator, APP, self.dev)
        self.assertTrue(accessible(self.dev, 'app', APP))
        grant.expires_at = timezone.now() - timedelta(minutes=1)
        grant.save()
        self.assertFalse(accessible(self.dev, 'app', APP))
        grant.expires_at = None
        grant.save()
        app_access.revoke(self.creator, grant)
        self.assertFalse(accessible(self.dev, 'app', APP), 'revoked : at once')

    def test_a_policy_edited_in_the_database_does_not_widen_it(self):
        from wama.accounts.models import AppAccessPolicy
        AppAccessPolicy.objects.create(app_id=APP, public=True)
        self.assertFalse(accessible(self.plain, 'app', APP))
        self.assertFalse(accessible(self.dev, 'app', APP))


class RequestGrantRevokeTest(_Sandbox):

    def test_a_developer_requests_and_the_creator_and_admins_are_told(self):
        from wama.common.models import Notification
        grant = app_access.request_access(self.dev, APP, 'tester le CV')
        self.assertEqual((AccessGrant.STATE_REQUESTED, 'tester le CV'), (grant.state, grant.reason))
        told = set(Notification.objects.filter(kind='access_request').values_list(
            'recipient__username', flat=True))
        self.assertTrue({'access_creator', 'access_admin'} <= told)
        self.assertEqual(grant.pk, app_access.request_access(self.dev, APP).pk, 'not repeated')

    def test_who_cannot_request(self):
        for user, app in ((self.plain, APP), (self.admin, APP), (self.creator, APP),
                          (self.dev, 'reader')):
            with self.subTest(user=user.username, app=app):
                with self.assertRaises(app_access.AppAccessRefused):
                    app_access.request_access(user, app)

    def test_the_creator_accepts_and_the_request_becomes_the_grant(self):
        grant = app_access.request_access(self.dev, APP)
        self.assertEqual({'state': 'granted'}, app_access.answer(self.creator, grant, True))
        grant.refresh_from_db()
        self.assertEqual((AccessGrant.STATE_GRANTED, self.creator), (grant.state, grant.granted_by))
        self.assertTrue(accessible(self.dev, 'app', APP))

    def test_a_refusal_keeps_it_closed(self):
        grant = app_access.request_access(self.dev, APP)
        app_access.answer(self.admin, grant, False)
        self.assertFalse(accessible(self.dev, 'app', APP))
        with self.assertRaises(app_access.AppAccessRefused):
            app_access.answer(self.admin, grant, True)

    def test_only_the_creator_and_admins_grant_and_only_to_developers(self):
        other = _account('access_other', 'developpeur')
        with self.assertRaises(app_access.AppAccessRefused):
            app_access.grant_access(other, APP, self.dev)
        with self.assertRaises(app_access.AppAccessRefused):
            app_access.grant_access(self.creator, APP, self.plain)
        with self.assertRaises(app_access.AppAccessRefused):
            app_access.grant_access(self.creator, CLI_APP, self.dev)   # not its creator
        self.assertEqual(AccessGrant.STATE_GRANTED,
                         app_access.grant_access(self.admin, CLI_APP, self.dev).state)

    def test_another_developer_cannot_revoke(self):
        grant = app_access.grant_access(self.creator, APP, self.dev)
        with self.assertRaises(app_access.AppAccessRefused):
            app_access.revoke(_account('access_other2', 'developpeur'), grant)


class GrantOpensUseOnlyTest(_Sandbox):

    def test_developing_the_app_stays_with_its_creator_and_the_admins(self):
        from wama.common.services import dev_tools
        app_access.grant_access(self.creator, APP, self.dev)
        refused = dev_tools.dev_sandbox(self.dev, 'remove', app=APP)
        self.assertEqual('forbidden', refused.get('error'))
        with mock.patch.object(dev_tools, 'start_job', return_value={'job_id': 'x'}) as job:
            self.assertEqual({'job_id': 'x'}, dev_tools.dev_sandbox(self.creator, 'remove', app=APP))
            dev_tools.dev_sandbox(self.admin, 'substitute', app=APP, target='params')
        self.assertEqual(2, job.call_count)


class SurfacesTest(_Sandbox):

    def test_the_request_page_is_seen_by_the_requester_and_the_deciders_only(self):
        grant = app_access.request_access(self.dev, APP)
        url = reverse('accounts:app-access-page', args=[grant.pk])
        for user, status in ((self.dev, 200), (self.creator, 200), (self.admin, 200),
                             (_account('access_stranger', 'developpeur'), 404)):
            self.client.force_login(user)
            self.assertEqual(status, self.client.get(url).status_code, user.username)
        self.client.force_login(self.creator)
        page = self.client.get(url).content.decode()
        self.assertIn(reverse('accounts:app-access-answer', args=[grant.pk]), page)
        self.assertTrue(self.client.post(reverse('accounts:app-access-answer', args=[grant.pk]),
                                         {'accept': '1'}).json()['done'])
        self.assertTrue(accessible(self.dev, 'app', APP))

    def test_the_catalogue_hides_the_sandbox_from_a_plain_user_and_offers_the_request(self):
        from wama.common.app_registry import APP_CATALOG
        with mock.patch.dict(APP_CATALOG, {APP: {'label': 'Notes', 'sandbox': True,
                                                 'url_name': '', 'description': ''}}):
            self.client.force_login(self.plain)
            names = [a['name'] for a in self.client.get(reverse('common:apps_catalog'))
                     .context['apps_list']]
            self.assertNotIn(APP, names)
            self.client.force_login(self.dev)
            item = next(a for a in self.client.get(reverse('common:apps_catalog'))
                        .context['apps_list'] if a['name'] == APP)
            self.assertEqual((False, APP, False),
                             (item['autorisee'], item['access_request']['app'], item['can_grant']))
            self.client.force_login(self.creator)
            item = next(a for a in self.client.get(reverse('common:apps_catalog'))
                        .context['apps_list'] if a['name'] == APP)
            self.assertEqual((True, None, True),
                             (item['autorisee'], item['access_request'], item['can_grant']))

    def test_the_shares_page_lists_the_opened_app_and_revokes_it(self):
        from wama.common.services.sharing import shares_overview
        grant = app_access.grant_access(self.creator, APP, self.dev)
        shared = [s for s in shares_overview(self.creator)['shared'] if s['nature'] == 'app']
        self.assertEqual([(APP, ['access_dev'])], [(s['app'], [p['name'] for p in s['persons']])
                                                   for s in shared])
        received = [s for s in shares_overview(self.dev)['received'] if s['nature'] == 'app']
        self.assertEqual([(APP, 'access_creator')], [(s['app'], s['owner']) for s in received])
        self.client.force_login(self.creator)
        revoke = shared[0]['persons'][0]['revoke_url']
        self.assertTrue(self.client.post(revoke).json()['done'])
        grant.refresh_from_db()
        self.assertEqual(AccessGrant.STATE_REVOKED, grant.state)

    def test_the_assistant_requests_grants_and_lists(self):
        from wama import tool_api as T
        asked = T.execute_tool('request_app_access', {'app': APP, 'reason': 'test'}, self.dev)
        self.assertTrue(asked.get('requested'), asked)
        listed = T.execute_tool('list_app_access', {}, self.creator)
        self.assertEqual([asked['request_id']], [r['id'] for r in listed['to_answer']])
        answered = T.execute_tool('answer_app_access',
                                  {'request_id': asked['request_id'], 'accept': 'true'}, self.creator)
        self.assertEqual('granted', answered.get('state'), answered)
        refused = T.execute_tool('grant_app_access', {'app': APP, 'username': 'access_plain'},
                                 self.creator)
        self.assertIn('error', refused)
        self.assertIn('error', T.execute_tool('revoke_app_access', {'grant_id': asked['request_id']},
                                              self.dev))
