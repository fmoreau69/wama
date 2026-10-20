"""
Vues de liaison de canal du profil (confirmation d'appariement, déliaison) — 2026-09-15.

⚠ POURQUOI CES GARDES : `_champ` lisait une variable `nom` inexistante depuis un renommage partiel
du 2026-08-30. Les deux vues répondaient 500 à CHAQUE appel, et rien ne le voyait : aucun test ne
les appelait. Un parcours cassé qui ne produit qu'une erreur dans un navigateur n'est pas gardé.
On vérifie ce que la vue RÉPOND, en JSON comme en formulaire — sans rien lier pour de vrai.
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class VuesDeLiaisonDeCanalTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('liaison_canal', password='x')
        self.client.force_login(self.user)

    def test_un_code_invalide_rend_une_erreur_lisible_et_non_une_500(self):
        r = self.client.post(reverse('accounts:channel-link'),
                             data=json.dumps({'code': 'FAUX-CODE'}),
                             content_type='application/json')
        self.assertEqual(400, r.status_code)
        self.assertIn('error', r.json())

    def test_le_code_est_lu_aussi_en_formulaire(self):
        r = self.client.post(reverse('accounts:channel-link'), data={'code': 'FAUX-CODE'})
        self.assertEqual(400, r.status_code, "le formulaire doit suivre le même chemin que le JSON")

    def test_la_deliaison_d_une_liaison_inexistante_rend_404(self):
        r = self.client.post(reverse('accounts:channel-unlink'),
                             data=json.dumps({'channel': 'discord', 'external_id': '123'}),
                             content_type='application/json')
        self.assertEqual(404, r.status_code)
        self.assertIn('error', r.json())
