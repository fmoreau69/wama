"""
Le fil `?next=` du login — la maille qui porte la trajectoire du QR d'appariement.

Mesuré le 2026-08-31 : le champ caché des gabarits de login valait `request.path` (la page
de login ELLE-MÊME), jamais le `?next=` reçu — aucun lien profond n'était donc honoré après
connexion : un `@login_required` renvoyait bien vers `/?next=…`, puis tout se perdait à la
maille suivante. Le QR d'appariement (ROADMAP §19.1) encode précisément un lien profond
(`/accounts/profile/?link_code=…`) : ces tests verrouillent la réparation, et la garde
anti-redirection ouverte posée dans le MÊME geste (une garde se pose avec ses jumeaux —
ouvrir le fil `next` sans la garde aurait créé le redirecteur ouvert au moment même où on
se met à faire circuler des liens profonds par QR).

Lancer : `python manage.py test wama.accounts.tests_login_next` (venv WSL).
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class LoginNextTests(TestCase):

    def setUp(self):
        User.objects.create_user('alice', password='s3cret-de-test')

    def _login(self, **extra):
        return self.client.post(reverse('accounts:login'),
                                {'username': 'alice', 'password': 's3cret-de-test', **extra})

    def test_un_lien_profond_est_honore_apres_connexion(self):
        cible = '/accounts/profile/?link_code=K7M2P9QR'
        reponse = self._login(next=cible)
        self.assertRedirects(reponse, cible, fetch_redirect_response=False)

    def test_sans_next_la_destination_historique_est_conservee(self):
        reponse = self._login()
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(reponse.url, reverse('anonymizer:upload'))

    def test_un_next_externe_est_refuse(self):
        # Sans la garde, un lien forgé `?next=https://…` déposerait l'utilisateur ailleurs
        # juste APRÈS qu'il s'est authentifié — le moment où il se méfie le moins.
        reponse = self._login(next='https://evil.example/phishing')
        self.assertEqual(reponse.url, reverse('anonymizer:upload'))

    def test_un_next_protocol_relative_est_refuse(self):
        # `//evil.example/…` : pas de schéma, mais un HÔTE — le piège classique des
        # validations qui ne regardent que le début de la chaîne.
        reponse = self._login(next='//evil.example/phishing')
        self.assertEqual(reponse.url, reverse('anonymizer:upload'))
