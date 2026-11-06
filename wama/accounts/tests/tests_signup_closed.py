"""L'inscription LOCALE est fermée (décision de Fabien du 2026-08-22, appliquée le 2026-11-06).

Audit de sécurité du 2026-11-06, prouvé en test : `/accounts/signup/` acceptait un POST sans session
et créait un compte local ACTIF, hors annuaire et hors modération — le gabarit avait suivi la
décision (plus de formulaire), pas la vue. Ces gardes tiennent la vue, pas le gabarit.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()


class SignupIsClosedTest(TestCase):

    def test_a_post_without_session_creates_no_account(self):
        reply = Client().post(reverse('accounts:signup'), {
            'username': 'self_made', 'email': 'self.made@example.org',
            'password1': 'Zx9!long-enough-pass', 'password2': 'Zx9!long-enough-pass'})
        self.assertEqual(reply.status_code, 403)
        self.assertFalse(User.objects.filter(username='self_made').exists())

    def test_the_page_tells_the_rule_and_offers_the_login_form(self):
        reply = Client().get(reverse('accounts:signup'))
        self.assertEqual(reply.status_code, 200)
        body = reply.content.decode('utf-8')
        self.assertIn('puis validé par un administrateur', body)
        self.assertIn('name="username"', body)
        self.assertNotIn('password2', body, 'aucun formulaire d’inscription ne reste servi')

    def test_the_local_registration_form_is_gone(self):
        from wama.accounts import models
        self.assertFalse(hasattr(models, 'UserRegistrationForm'),
                         'le formulaire retiré ne doit pas revenir : un compte naît de l’annuaire')
