"""Le frein de connexion, l'adresse du client et la fiche d'un compte (2026-11-06, audit de
sécurité — chaque garde a été rouge avant son correctif) :

  - un identifiant qui accumule les échecs est refusé, même avec le bon mot de passe, par le
    formulaire comme par le jeton d'API (`LoginBrakeBackend`, en tête des moteurs) ;
  - l'adresse du client est la DERNIÈRE de `X-Forwarded-For` (`moderation.client_address`) ;
  - `/accounts/users/<pk>/` : la sienne, ou toutes pour un administrateur, rien sans session.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from wama.accounts import moderation

User = get_user_model()
PASSWORD = 'Zx9!brake-long-pass-42'


@override_settings(WAMA_LOGIN_FAILURES_LIMIT=3, WAMA_LOGIN_BRAKE_SECONDS=60)
class LoginBrakeTest(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user('wama_brake_user', password=PASSWORD)

    def _form_login(self, password):
        return Client().post(reverse('accounts:login'),
                             {'username': 'wama_brake_user', 'password': password})

    def _token(self, password):
        return Client().post('/api/v1/auth/token/',
                             {'username': 'wama_brake_user', 'password': password})

    def test_the_good_password_passes_before_the_limit(self):
        self._form_login('wrong-1')
        self.assertEqual(self._token(PASSWORD).status_code, 200)

    def test_after_the_limit_even_the_good_password_is_refused_on_every_surface(self):
        for i in range(3):
            self._form_login(f'wrong-{i}')
        self.assertTrue(moderation.login_braked('wama_brake_user'))
        self.assertEqual(self._token(PASSWORD).status_code, 400)
        reply = self._form_login(PASSWORD)
        self.assertNotIn('_auth_user_id', reply.wsgi_request.session)

    def test_the_brake_is_per_identifier_and_case_insensitive(self):
        for i in range(3):
            self._token(f'wrong-{i}')
        self.assertTrue(moderation.login_braked('WAMA_Brake_User'))
        self.assertFalse(moderation.login_braked('someone_else'))

    def test_a_successful_login_resets_the_count(self):
        self._form_login('wrong-1')
        self._form_login('wrong-2')
        self.assertEqual(self._token(PASSWORD).status_code, 200)   # le jeton ne connecte pas
        client = Client()
        client.post(reverse('accounts:login'), {'username': 'wama_brake_user', 'password': PASSWORD})
        self.assertFalse(moderation.login_braked('wama_brake_user'))
        self._form_login('wrong-3')
        self.assertFalse(moderation.login_braked('wama_brake_user'), 'le compte est reparti de zéro')

    def test_a_session_opened_without_a_named_backend_still_reads_the_account(self):
        # Le frein est PREMIER : `force_login` l'inscrit dans la session, il doit la relire.
        client = Client()
        client.force_login(self.user)
        self.assertEqual(client.get(reverse('accounts:profile')).status_code, 200)


class ClientAddressTest(TestCase):

    def test_the_last_forwarded_address_is_the_one_the_proxy_added(self):
        request = RequestFactory().get('/', HTTP_X_FORWARDED_FOR='6.6.6.6, 10.1.2.3',
                                       REMOTE_ADDR='127.0.0.1')
        self.assertEqual(moderation.client_address(request), '10.1.2.3')

    def test_without_proxy_header_the_socket_address(self):
        request = RequestFactory().get('/', REMOTE_ADDR='10.9.9.9')
        self.assertEqual(moderation.client_address(request), '10.9.9.9')

    def test_the_visitor_brake_reads_the_same_address(self):
        from wama.accounts.visitors import _address
        request = RequestFactory().get('/', HTTP_X_FORWARDED_FOR='1.1.1.1, 10.1.2.3')
        self.assertEqual(_address(request), '10.1.2.3')


class UserPageTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import set_account_tier
        self.member = User.objects.create_user('wama_page_member', email='member@example.org')
        self.other = User.objects.create_user('wama_page_other', email='other@example.org')
        self.admin = User.objects.create_user('wama_page_admin')
        set_account_tier(self.admin, 'admin')

    def _get(self, viewer, target):
        client = Client()
        if viewer is not None:
            client.force_login(viewer)
        return client.get(reverse('accounts:user-page', args=[target.pk]))

    def test_a_visitor_reads_no_account(self):
        reply = self._get(None, self.member)
        self.assertNotEqual(reply.status_code, 200)
        self.assertNotIn(b'member@example.org', reply.content)

    def test_a_member_reads_only_his_own(self):
        self.assertEqual(self._get(self.member, self.member).status_code, 200)
        self.assertEqual(self._get(self.member, self.other).status_code, 404)

    def test_an_administrator_reads_any(self):
        self.assertEqual(self._get(self.admin, self.other).status_code, 200)
