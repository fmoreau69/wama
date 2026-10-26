"""Modifier un compte depuis la page des utilisateurs (`accounts.views.user_edit`, 2026-10-26).

Un administrateur met à jour le prénom, le nom, l'email — et le mot de passe d'un compte LOCAL —
sans se connecter à ce compte. Un compte sans mot de passe local (annuaire) n'en reçoit jamais :
`ModelBackend` l'accepterait à côté du LDAP.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from wama.accounts.permissions import set_account_tier

STRONG = 'Plume-de-heron-2026!'


class UserEditTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('edit_admin', password=STRONG)
        set_account_tier(self.admin, 'admin')
        self.local = User.objects.create_user('edit_local', email='local@example.org',
                                              password=STRONG, first_name='Ancien')
        self.directory = User.objects.create_user('edit_directory', email='dir@example.org')
        self.directory.set_unusable_password()
        self.directory.save()
        self.client.force_login(self.admin)

    def post(self, user, **data):
        return self.client.post(f'/accounts/users/{user.pk}/edit/', data)

    def test_an_admin_updates_another_accounts_identity(self):
        response = self.post(self.local, first_name=' Nouveau ', last_name='Nom', email='new@example.org')
        self.assertTrue(response.json()['success'], response.content)
        self.local.refresh_from_db()
        self.assertEqual((self.local.first_name, self.local.last_name, self.local.email),
                         ('Nouveau', 'Nom', 'new@example.org'))
        self.assertTrue(self.local.check_password(STRONG))      # mot de passe vide : inchangé

    def test_a_non_admin_cannot_edit_an_account(self):
        self.client.force_login(self.local)
        self.post(self.directory, first_name='Pirate')
        self.directory.refresh_from_db()
        self.assertEqual(self.directory.first_name, '')

    def test_an_email_held_by_another_account_is_refused(self):
        response = self.post(self.local, email='dir@example.org')
        self.assertEqual(response.status_code, 400)
        self.local.refresh_from_db()
        self.assertEqual(self.local.email, 'local@example.org')

    def test_an_invalid_email_is_refused(self):
        response = self.post(self.local, email='pas-un-email')
        self.assertEqual(response.status_code, 400)

    def test_a_local_account_receives_a_new_validated_password(self):
        self.assertEqual(self.post(self.local, password='123').status_code, 400)
        self.local.refresh_from_db()
        self.assertTrue(self.local.check_password(STRONG))
        response = self.post(self.local, first_name='Ancien', email='local@example.org',
                             password='Aile-de-martinet-77')
        self.assertTrue(response.json()['success'], response.content)
        self.local.refresh_from_db()
        self.assertTrue(self.local.check_password('Aile-de-martinet-77'))

    def test_an_account_without_local_password_cannot_receive_one(self):
        response = self.post(self.directory, email='dir@example.org', password=STRONG)
        self.assertEqual(response.status_code, 400)
        self.directory.refresh_from_db()
        self.assertFalse(self.directory.has_usable_password())

    def test_the_anonymous_account_is_not_editable(self):
        anonymous = User.objects.create_user('anonymous')
        self.assertEqual(self.post(anonymous, first_name='X').status_code, 400)

    def test_an_admin_changing_their_own_password_stays_logged_in(self):
        self.post(self.admin, password='Aile-de-martinet-77')
        self.assertEqual(self.client.get('/accounts/users/').status_code, 200)

    def test_adding_an_account_refuses_a_weak_password(self):
        response = self.client.post('/accounts/users/new/', {'username': 'edit_new', 'password': '123'})
        self.assertFalse(response.json()['success'])
        self.assertFalse(User.objects.filter(username='edit_new').exists())

    def test_adding_an_account_refuses_a_password_resembling_its_username(self):
        response = self.client.post('/accounts/users/new/',
                                    {'username': 'heronplume', 'password': 'heronplume1'})
        self.assertFalse(response.json()['success'])

    def test_adding_an_account_accepts_a_valid_password_or_none(self):
        response = self.client.post('/accounts/users/new/', {'username': 'edit_new', 'password': STRONG})
        self.assertTrue(response.json()['success'], response.content)
        self.assertTrue(User.objects.get(username='edit_new').check_password(STRONG))
        self.client.post('/accounts/users/new/', {'username': 'edit_nopw'})
        self.assertFalse(User.objects.get(username='edit_nopw').has_usable_password())

    def test_the_page_offers_the_pen_on_each_account_but_anonymous(self):
        User.objects.get_or_create(username='anonymous')
        html = self.client.get('/accounts/users/').content.decode()
        self.assertEqual(html.count('edit-user-btn"'), User.objects.exclude(username='anonymous').count())
        self.assertIn(f'data-user-id="{self.local.pk}"', html)
        self.assertIn('id="editUserModal"', html)
