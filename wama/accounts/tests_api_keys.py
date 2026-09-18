"""
Clés d'API personnelles et volet droit du profil — ROADMAP §8d Phase 3, étape 4a (2026-09-15).

⚠ CE QUE CES GARDES PROTÈGENT :
- une clé enregistrée est CHIFFRÉE en base (la colonne ne contient jamais le clair) et relue en
  clair par l'ORM ;
- un utilisateur n'utilise que SA clé : pas de repli sur la clé d'instance du `.env` (quotas
  répartis, décision de Fabien) ;
- une rotation de `SECRET_KEY` RECHIFFRE les clés stockées : sans elle, une clé devient illisible
  à la 4ᵉ rotation, sans erreur ;
- tout ce qui touche aux clés est rendu dans la section Paramètres du volet droit.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from wama.accounts import api_keys
from wama.accounts.models import UserApiKey, UserProfile

CLE_A = 'a' * 50
CLE_B = 'b' * 50
CLAIR = 'sk-test-albert-0123456789'


def _colonne_brute(model, pk, colonne='api_key'):
    """La valeur telle que la BASE la stocke — sans passer par le champ qui déchiffre."""
    with connection.cursor() as cur:
        cur.execute(f'SELECT {colonne} FROM {model._meta.db_table} WHERE id = %s', [pk])
        return cur.fetchone()[0]


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class ClesLlmTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('cles_llm', password='x')
        self.client.force_login(self.user)
        # Aucun appel réseau : la découverte des modèles est testée dans model_manager.
        decouverte = mock.patch('wama.model_manager.services.cloud_models.list_remote_models',
                                return_value=[])
        decouverte.start()
        self.addCleanup(decouverte.stop)
        # Et aucune découverte du disque : `refresh_key` passe par la synchronisation commune
        # (2026-09-18) — on la réduit à sa source cloud, comme dans les tests du model_manager.
        from wama.model_manager.tests_cloud_models import _sync_cloud_seul
        _sync_cloud_seul(self)

    def _enregistrer(self, slug='albert', cle=CLAIR):
        return self.client.post(reverse('accounts:profile-api-key-save', args=[slug]),
                                data=json.dumps({'api_key': cle}), content_type='application/json')

    def test_la_liste_expose_albert_sans_jamais_la_cle(self):
        self._enregistrer()
        r = self.client.get(reverse('accounts:profile-api-keys'))
        albert = next(p for p in r.json()['providers'] if p['slug'] == 'albert')
        self.assertTrue(albert['has_key'])
        self.assertTrue(albert['api_key_help_url'])
        self.assertNotIn(CLAIR, r.content.decode())

    def test_la_cle_est_chiffree_en_base_et_relue_en_clair(self):
        self.assertEqual(200, self._enregistrer().status_code)
        row = UserApiKey.objects.get(user=self.user, source='albert')
        self.assertNotIn(CLAIR, _colonne_brute(UserApiKey, row.pk))
        self.assertEqual(CLAIR, row.api_key)
        self.assertEqual(CLAIR, api_keys.key_for(self.user, 'albert'))

    def test_une_cle_vide_efface(self):
        self._enregistrer()
        r = self._enregistrer(cle='')
        self.assertFalse(r.json()['has_key'])
        self.assertFalse(UserApiKey.objects.filter(user=self.user).exists())

    def test_un_fournisseur_inconnu_rend_404(self):
        self.assertEqual(404, self._enregistrer(slug='inconnu').status_code)

    @override_settings(SECRET_KEY='django-insecure-dev-only-CHANGE-ME')
    def test_une_cle_de_serveur_non_sure_refuse_d_enregistrer(self):
        # La session signée par l'autre clé serait refusée : on se reconnecte sous celle-ci.
        self.client.force_login(self.user)
        r = self._enregistrer()
        self.assertEqual(503, r.status_code)
        self.assertIn('error', r.json())
        self.assertFalse(UserApiKey.objects.filter(user=self.user).exclude(api_key='').exists())

    def test_pas_de_repli_sur_la_cle_d_instance_pour_un_utilisateur(self):
        with mock.patch.dict(os.environ, {'ALBERT_API_KEY': 'cle-instance'}):
            self.assertEqual('', api_keys.key_for(self.user, 'albert'))
            self.assertEqual('cle-instance', api_keys.key_for(None, 'albert'))

    def test_la_cle_d_un_autre_utilisateur_ne_se_lit_pas(self):
        self._enregistrer()
        autre = get_user_model().objects.create_user('cles_llm_autre', password='x')
        self.assertEqual('', api_keys.key_for(autre, 'albert'))

    def test_une_cle_illisible_se_lit_vide_sans_faire_tomber_la_page(self):
        self._enregistrer()
        with override_settings(SECRET_KEY=CLE_B, SECRET_KEY_FALLBACKS=[]):
            self.assertEqual('', UserApiKey.objects.get(user=self.user).api_key)
            self.client.force_login(self.user)          # session signée par la clé courante
            self.assertEqual(200, self.client.get(reverse('accounts:profile')).status_code)


class NiveauCloudTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('niveau_cloud', password='x')
        self.client.force_login(self.user)

    def test_cent_pour_cent_local_par_defaut(self):
        self.assertEqual('local_only', UserProfile.objects.get(user=self.user).cloud_policy)

    def test_un_niveau_valide_s_enregistre_et_un_invalide_est_refuse(self):
        url = reverse('accounts:profile-cloud-policy')
        ok = self.client.post(url, data=json.dumps({'cloud_policy': 'cloud_allowed'}),
                              content_type='application/json')
        self.assertEqual(200, ok.status_code)
        self.assertEqual('cloud_allowed', UserProfile.objects.get(user=self.user).cloud_policy)
        ko = self.client.post(url, data=json.dumps({'cloud_policy': 'partout'}),
                              content_type='application/json')
        self.assertEqual(400, ko.status_code)


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class ClesMediathequeTest(TestCase):
    """Les clés des connecteurs de la médiathèque étaient stockées en CLAIR jusqu'au 2026-09-15."""

    def test_la_cle_d_un_connecteur_est_chiffree(self):
        from wama.media_library.models import MediaProvider, UserProviderConfig
        user = get_user_model().objects.create_user('cles_media', password='x')
        self.client.force_login(user)
        MediaProvider.objects.create(slug='connecteur-test', name='Connecteur test')
        r = self.client.post(reverse('media_library:api_provider_key_save', args=['connecteur-test']),
                             data=json.dumps({'api_key': CLAIR}), content_type='application/json')
        self.assertEqual(200, r.status_code)
        cfg = UserProviderConfig.objects.get(user=user)
        self.assertNotIn(CLAIR, _colonne_brute(UserProviderConfig, cfg.pk))
        self.assertEqual(CLAIR, cfg.api_key)


class RotationRechiffreTest(TestCase):

    def test_apres_rotation_la_seule_nouvelle_cle_lit_les_cles_stockees(self):
        user = get_user_model().objects.create_user('rotation_cles', password='x')
        with override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[]):
            UserApiKey.objects.create(user=user, source='albert', api_key=CLAIR)
            with tempfile.TemporaryDirectory() as dossier:
                env = Path(dossier) / '.env'
                env.write_text(f"DJANGO_SECRET_KEY='{CLE_A}'\n", encoding='utf-8')
                with mock.patch.dict(os.environ, {'DJANGO_SECRET_KEY': CLE_A,
                                                  'DJANGO_SECRET_KEY_FALLBACKS': ''}), \
                     mock.patch('wama.common.management.commands.rotate_secrets._log_rotation'):
                    # ⚠ `encoding='utf-8'` OBLIGATOIRE, mesuré le 2026-09-18 : sous Windows,
                    # `open(chemin, 'w')` ouvre en mode texte avec l'encodage de la LOCALE
                    # (cp1252 ici), pas en UTF-8. Rediriger vers `devnull` ne protégeait donc de
                    # rien — `rotate_secrets` écrit des accents et une flèche `→`, et le test
                    # mourait en `UnicodeEncodeError` DANS la suite complète (1814 tests), là où
                    # il passe en isolé sur une console qui, elle, tolère. Les 14 autres appels
                    # de `call_command` du dépôt passent un `StringIO()` : immunisés par
                    # construction, puisqu'un flux mémoire n'encode rien.
                    call_command('rotate_secrets', secret_key=True, yes=True, env_file=str(env),
                                 stdout=open(os.devnull, 'w', encoding='utf-8'),
                                 stderr=open(os.devnull, 'w', encoding='utf-8'))
                ligne = next(l for l in env.read_text(encoding='utf-8').splitlines()
                             if l.startswith('DJANGO_SECRET_KEY='))
                nouvelle = ligne.split('=', 1)[1].strip("'")
        self.assertNotEqual(CLE_A, nouvelle)
        # L'ancienne clé ABSENTE des fallbacks : c'est le cas qui perdrait la donnée sans rechiffrement.
        with override_settings(SECRET_KEY=nouvelle, SECRET_KEY_FALLBACKS=[]):
            self.assertEqual(CLAIR, UserApiKey.objects.get(user=user).api_key)


class VoletDuProfilTest(TestCase):

    def test_les_cles_sont_dans_la_section_parametres_du_volet(self):
        user = get_user_model().objects.create_user('volet_profil', password='x')
        self.client.force_login(user)
        html = self.client.get(reverse('accounts:profile')).content.decode()
        self.assertIn('id="settings-section"', html)
        self.assertNotIn('id="media-section"', html)
        self.assertNotIn('id="actions-section"', html)
        debut_volet = html.index('id="settings-section"')
        for marqueur in ('id="tokenInput"', 'id="llmKeysList"', 'id="providersList"'):
            self.assertIn(marqueur, html)
            self.assertGreater(html.index(marqueur), debut_volet,
                               f"{marqueur} rendu hors du volet droit")
        self.assertIn('id="cloudPolicySelect"', html)
