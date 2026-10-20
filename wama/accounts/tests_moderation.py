"""
Modération à la première connexion (`PROFILES_PERMISSIONS.md §1.8`, corrigée le 2026-10-20).

Vécu : un collègue s'est connecté par l'annuaire, a lu « Wrong ID or password », et personne n'a
reçu de demande. Son compte EXISTAIT, inactif. Le formulaire disait « mauvais identifiants » pour
toute erreur, la demande ne partait que par un email qui ne partait pas, et la tentative suivante
n'était journalisée nulle part. Aucun test ne couvrait ce chemin : ces gardes tiennent ce qu'on ne
voit qu'en se connectant avec un compte NEUF de l'annuaire.

Sans annuaire : le moteur LDAP est simulé au point exact où il rend la main (`authenticate` rend le
compte, `get_or_build_user` le construit) ; le reste — formulaire, vue, gabarit, signaux,
notifications, journal — est le vrai.
"""
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from wama.accounts import moderation
from wama.accounts.ldap_backend import WamaLDAPBackend
from wama.accounts.models import AccessLog
from wama.common.models import Notification

BROWSER = {'REMOTE_ADDR': '10.1.2.3', 'HTTP_USER_AGENT': 'Mozilla/5.0'}


@override_settings(WAMA_MODERATOR_EMAILS=['moderation@test.local'])
class FirstLoginModerationTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user('the.admin', password='x', email='admin@test.local')
        self.admin.groups.add(Group.objects.get_or_create(name='admin')[0])
        self.root = User.objects.create_superuser('the.root', password='x', email='root@test.local')
        self.dev = User.objects.create_user('the.dev', password='x')
        self.dev.groups.add(Group.objects.get_or_create(name='dev')[0])

    def _first_login(self, username='new.colleague'):
        """Ce que fait le moteur LDAP pour un nom inconnu de WAMA : il construit le compte, que
        `WamaLDAPBackend` rend inactif, puis django_auth_ldap l'enregistre."""
        built = User(username=username, email=f'{username}@test.local')
        with mock.patch('django_auth_ldap.backend.LDAPBackend.get_or_build_user',
                        return_value=(built, True)):
            user, created = WamaLDAPBackend().get_or_build_user(username, None)
        self.assertTrue(created)
        user.save()
        return user

    def _pending(self, user):
        return Notification.objects.filter(kind=moderation.ACCOUNT_PENDING_KIND,
                                           object_type='User', object_id=str(user.pk))

    def test_a_first_ldap_login_creates_an_inactive_account_and_asks_inside_wama_and_by_email(self):
        user = self._first_login()
        self.assertFalse(User.objects.get(pk=user.pk).is_active)
        self.assertEqual({self.admin, self.root}, {n.recipient for n in self._pending(user)})
        self.assertEqual(reverse('accounts:user-management'), self._pending(user).first().url)
        self.assertEqual(1, len(mail.outbox))
        self.assertEqual(['moderation@test.local'], mail.outbox[0].to)

    def test_the_request_goes_only_to_those_who_can_activate(self):
        user = self._first_login()
        self.assertNotIn(self.dev, {n.recipient for n in self._pending(user)})
        from wama.accounts.views import is_admin
        self.assertEqual({u for u in User.objects.filter(is_active=True) if is_admin(u)},
                         set(moderation.account_moderators()))

    def test_the_pending_account_learns_it_waits_instead_of_a_password_error(self):
        user = self._first_login()
        with mock.patch.object(WamaLDAPBackend, 'authenticate', return_value=user):
            page = self.client.post(reverse('accounts:login'),
                                    {'username': user.username, 'password': 'ldap-ok'}, **BROWSER)
        self.assertEqual(200, page.status_code)
        self.assertContains(page, 'en attente de validation par un administrateur')
        self.assertNotContains(page, 'Wrong ID or password')
        self.assertNotIn('Invalid credentials.', [str(m) for m in page.context['messages']])
        self.assertFalse(page.wsgi_request.user.is_authenticated)
        row = AccessLog.objects.filter(event='login_denied').latest('pk')
        self.assertEqual((user.username, 'inactive'), (row.username, row.reason))

    def test_a_wrong_password_still_reads_wrong_id_or_password(self):
        """Contre-épreuve : un compte inactif LOCAL n'a rien prouvé (`ModelBackend` le refuse
        avant le formulaire) — il ne doit pas apprendre que le compte existe."""
        User.objects.create_user('local.pending', password='right', is_active=False)
        page = self.client.post(reverse('accounts:login'),
                                {'username': 'local.pending', 'password': 'right'}, **BROWSER)
        self.assertContains(page, 'Wrong ID or password')
        self.assertNotContains(page, 'en attente de validation')

    def test_a_retry_does_not_ask_twice_but_a_read_request_is_asked_again(self):
        user = self._first_login()
        self.assertEqual({'in_app': 0, 'email': False}, moderation.request_moderation(user))
        self.assertEqual(2, self._pending(user).count())
        self.assertEqual(1, len(mail.outbox))
        # Lue sans être traitée : le compte qui retente la remet sous les yeux des modérateurs.
        from django.utils import timezone
        self._pending(user).update(read_at=timezone.now())
        moderation.pending_login(user)
        self.assertEqual(2, self._pending(user).filter(read_at__isnull=True).count())

    def test_an_account_created_before_the_fix_is_asked_for_at_its_next_attempt(self):
        """Les comptes qui attendaient sans que personne le sache (13 et 15/10) : leur prochaine
        tentative repose la demande, qu'aucune notification n'attendait."""
        waiting = User.objects.create_user('waiting.since', password='x', is_active=False)
        self.assertFalse(self._pending(waiting).exists())
        moderation.pending_login(waiting)
        self.assertEqual(2, self._pending(waiting).count())
