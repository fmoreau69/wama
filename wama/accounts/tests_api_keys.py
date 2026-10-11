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
        from wama.model_manager.tests.tests_cloud_models import _sync_cloud_seul
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

    def test_the_second_axis_starts_at_sovereign_without_metered_consent(self):
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(('sovereign', False), (profile.cloud_hosting_max, profile.cloud_metered_auto))

    def test_the_ceiling_and_the_metered_consent_are_saved_by_the_same_route(self):
        url = reverse('accounts:profile-cloud-policy')
        ok = self.client.post(url, data=json.dumps({'cloud_hosting_max': 'third_party',
                                                    'cloud_metered_auto': True}),
                              content_type='application/json')
        self.assertEqual(200, ok.status_code)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(('third_party', True, 'local_only'),
                         (profile.cloud_hosting_max, profile.cloud_metered_auto, profile.cloud_policy))

    def test_an_invalid_ceiling_saves_nothing_at_all(self):
        url = reverse('accounts:profile-cloud-policy')
        ko = self.client.post(url, data=json.dumps({'cloud_policy': 'cloud_allowed',
                                                    'cloud_hosting_max': 'the_moon'}),
                              content_type='application/json')
        self.assertEqual(400, ko.status_code)
        self.assertEqual('local_only', UserProfile.objects.get(user=self.user).cloud_policy)
        self.assertEqual(400, self.client.post(url, data='{}',
                                               content_type='application/json').status_code)


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


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class HuggingFaceKeyTest(TestCase):
    """The HuggingFace token is set in the profile like any personal key (2026-09-27)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('cle_hf', password='x')
        self.client.force_login(self.user)

    def test_the_profile_offers_the_huggingface_token(self):
        self.assertIn('huggingface', {row['slug'] for row in api_keys.listing(self.user)})

    def test_saving_it_does_not_run_the_model_discovery_of_llm_providers(self):
        """`<address>/models` is an HTML page at HuggingFace: reading it as JSON made the save
        answer 500. The discovery belongs to model providers (`llm`) only."""
        with mock.patch('wama.model_manager.services.cloud_models.refresh_key') as refresh:
            r = self.client.post(reverse('accounts:profile-api-key-save', args=['huggingface']),
                                 data=json.dumps({'api_key': 'hf_abc'}),
                                 content_type='application/json')
        self.assertEqual(200, r.status_code, r.content)
        refresh.assert_not_called()
        self.assertEqual('hf_abc', api_keys.key_for(self.user, 'huggingface'))


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class ProfileKeySaveStaysFastTest(TestCase):
    """2026-10-02: the profile's « Enregistrer » ran the full catalogue sync in the request (over
    two minutes, nothing visible). The view now asks for the background update."""

    def test_the_view_asks_for_the_catalogue_update_in_the_background(self):
        user = get_user_model().objects.create_user('fast_key_save', password='x')
        self.client.force_login(user)
        with mock.patch('wama.model_manager.services.cloud_models.refresh_key',
                        return_value=(3, '')) as refresh:
            r = self.client.post(reverse('accounts:profile-api-key-save', args=['albert']),
                                 data=json.dumps({'api_key': CLAIR}),
                                 content_type='application/json')
        self.assertEqual(3, r.json()['models_count'])
        self.assertTrue(refresh.call_args.kwargs.get('background'))


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class InstanceKeyTest(TestCase):
    """2026-10-07 (decision of Fabien): the INSTANCE key of a source is set by an admin on the
    « Sources externes » page. It beats the `.env` one, and — for a source declaring itself
    `shareable` (application keys: ILaaS) — the admin may share it with every account that has
    not set its own. A source whose quota is per person (Albert) never shares."""

    URL = '/common/sources/{}/instance-key/'

    def setUp(self):
        from django.contrib.auth.models import Group
        User = get_user_model()
        self.admin = User.objects.create_user('instance_key_admin', password='x')
        self.admin.groups.add(Group.objects.get_or_create(name='admin')[0])
        self.user = User.objects.create_user('instance_key_user', password='x')
        refresh = mock.patch('wama.model_manager.services.cloud_models.refresh_key',
                             return_value=(2, ''))
        self.refresh = refresh.start()
        self.addCleanup(refresh.stop)

    def _post(self, source, body, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post(self.URL.format(source), data=json.dumps(body),
                                content_type='application/json')

    def test_a_stored_instance_key_beats_the_env_one_which_stays_the_fallback(self):
        from wama.common import external_sources
        with mock.patch.dict(os.environ, {'ILAAS_API_KEY': 'from-env'}):
            self.assertEqual('from-env', external_sources.api_key('ilaas'))
            self.assertEqual('env', external_sources.api_key_origin('ilaas'))
            self.assertEqual(200, self._post('ilaas', {'api_key': 'from-page'}).status_code)
            self.assertEqual('from-page', external_sources.api_key('ilaas'))
            self.assertEqual('stored', external_sources.api_key_origin('ilaas'))
            self._post('ilaas', {'api_key': ''})
            self.assertEqual('from-env', external_sources.api_key('ilaas'))

    def test_the_key_is_encrypted_and_records_who_set_it(self):
        from wama.accounts.models import InstanceApiKey
        r = self._post('ilaas', {'api_key': CLAIR})
        self.assertEqual(2, r.json()['models_count'])
        row = InstanceApiKey.objects.get(source='ilaas')
        self.assertNotIn(CLAIR, _colonne_brute(InstanceApiKey, row.pk))
        self.assertEqual(self.admin, row.updated_by)
        self.assertTrue(self.refresh.call_args.kwargs.get('background'))

    def test_only_an_admin_sets_an_instance_key(self):
        from wama.accounts.models import InstanceApiKey
        self.assertEqual(403, self._post('ilaas', {'api_key': CLAIR}, user=self.user).status_code)
        self.assertFalse(InstanceApiKey.objects.exists())

    def test_a_shared_key_serves_accounts_without_their_own_and_a_personal_one_wins(self):
        self._post('ilaas', {'api_key': 'shared-key'})
        self.assertEqual('', api_keys.key_for(self.user, 'ilaas'), 'not shared yet')
        self.assertTrue(self._post('ilaas', {'shared': True}).json()['shared'])
        self.assertEqual('shared-key', api_keys.key_for(self.user, 'ilaas'))
        ilaas = next(p for p in api_keys.listing(self.user) if p['slug'] == 'ilaas')
        self.assertTrue(ilaas['shared_available'])
        self.assertFalse(ilaas['has_key'])
        UserApiKey.objects.create(user=self.user, source='ilaas', api_key='personal-key')
        self.assertEqual('personal-key', api_keys.key_for(self.user, 'ilaas'))

    def test_a_source_with_quotas_per_account_never_shares_its_instance_key(self):
        from wama.accounts.models import InstanceApiKey
        self._post('albert', {'api_key': 'instance-albert'})
        self.assertEqual(400, self._post('albert', {'shared': True}).status_code)
        # Even a row forced to `shared` lends nothing: the source does not declare it.
        InstanceApiKey.objects.filter(source='albert').update(shared=True)
        self.assertEqual('', api_keys.key_for(self.user, 'albert'))
        self.assertEqual('instance-albert', api_keys.key_for(None, 'albert'))

    def test_sharing_needs_a_stored_key(self):
        self.assertEqual(400, self._post('ilaas', {'shared': True}).status_code)

    def test_a_shared_key_opens_its_models_to_an_account_allowed_to_use_the_cloud(self):
        from wama.accounts.models import InstanceApiKey
        from wama.model_manager.services.cloud_models import allowed_cloud_keys
        InstanceApiKey.objects.create(source='ilaas', api_key='k', shared=True,
                                      open_models=['ilaas:mistral-small-4-119b'])
        UserProfile.objects.filter(user=self.user).update(cloud_policy='cloud_allowed')
        self.user.refresh_from_db()
        self.assertIn('ilaas:mistral-small-4-119b', allowed_cloud_keys(self.user, automatic=False))
        # « 100 % local » closes it, shared or not.
        UserProfile.objects.filter(user=self.user).update(cloud_policy='local_only')
        self.user.refresh_from_db()
        self.assertEqual(set(), allowed_cloud_keys(self.user, automatic=False))

    def test_the_sources_page_shows_the_key_panel_to_an_admin_only(self):
        self.client.force_login(self.admin)
        self.assertIn('wama-key-field.js', self.client.get('/common/sources/').content.decode())
        self.client.force_login(self.user)
        self.assertNotIn('wama-key-field.js', self.client.get('/common/sources/').content.decode())

    def test_the_models_an_instance_key_opens_enter_the_catalogue_discovery(self):
        """Silent if broken: the catalogue would simply miss the models of the shared key."""
        from wama.accounts.models import InstanceApiKey
        from wama.model_manager.services.cloud_models import cloud_model_infos
        InstanceApiKey.objects.create(source='ilaas', api_key='k', remote_listing=[
            {'id': 'gemma-4-31b', 'name': 'gemma-4-31b', 'type': 'text-generation', 'aliases': []}])
        self.assertIn('ilaas:gemma-4-31b', cloud_model_infos())

    def test_the_nightly_refresh_rereads_the_instance_key_too(self):
        from wama.accounts.models import InstanceApiKey
        from wama.model_manager.services import cloud_models
        row = InstanceApiKey.objects.create(source='ilaas', api_key='k')
        with mock.patch.object(cloud_models, 'refresh_key', return_value=(0, '')) as refresh:
            cloud_models.refresh_all_keys()
        self.assertIn(row, [call.args[0] for call in refresh.call_args_list])


class RemovedKeyRetiresItsModelsTest(TestCase):
    """2026-10-11: removing a key (profile or « Sources externes » page) marks unavailable the
    remote models NO remaining key opens. Silent if broken: the nightly refresh only rereads the
    keys that are left, so once the last key of a source was gone its models stayed offered to
    every selector, and no one could call them."""

    def setUp(self):
        from django.contrib.auth.models import Group

        from wama.model_manager.models import AIModel
        User = get_user_model()
        self.admin = User.objects.create_user('removed_key_admin', password='x')
        self.admin.groups.add(Group.objects.get_or_create(name='admin')[0])
        self.user = User.objects.create_user('removed_key_user', password='x')
        for model_key in ('albert:only-mine', 'albert:also-elsewhere', 'ilaas:instance-only'):
            source, name = model_key.split(':')
            AIModel.objects.create(model_key=model_key, name=name, model_type='llm',
                                   source=source, execution='cloud', is_available=True,
                                   capabilities={'completion': True})

    def _available(self, model_key):
        from wama.model_manager.models import AIModel
        return AIModel.objects.get(model_key=model_key).is_available

    def test_removing_a_personal_key_retires_only_what_no_other_key_opens(self):
        other = get_user_model().objects.create_user('removed_key_other', password='x')
        UserApiKey.objects.create(user=self.user, source='albert', api_key='k1',
                                  open_models=['albert:only-mine', 'albert:also-elsewhere'])
        UserApiKey.objects.create(user=other, source='albert', api_key='k2',
                                  open_models=['albert:also-elsewhere'])
        self.client.force_login(self.user)
        r = self.client.post(reverse('accounts:profile-api-key-save', args=['albert']),
                             data=json.dumps({'api_key': ''}), content_type='application/json')
        self.assertEqual(200, r.status_code)
        self.assertFalse(self._available('albert:only-mine'))
        self.assertTrue(self._available('albert:also-elsewhere'), 'still opened by another key')

    def test_removing_the_instance_key_retires_its_models(self):
        from wama.accounts.models import InstanceApiKey
        InstanceApiKey.objects.create(source='ilaas', api_key='k',
                                      open_models=['ilaas:instance-only'])
        self.client.force_login(self.admin)
        r = self.client.post('/common/sources/ilaas/instance-key/',
                             data=json.dumps({'api_key': ''}), content_type='application/json')
        self.assertEqual(200, r.status_code)
        self.assertFalse(self._available('ilaas:instance-only'))
        self.assertTrue(self._available('albert:only-mine'), 'another source is left alone')

    def test_a_key_of_a_source_that_is_not_a_model_provider_touches_no_model(self):
        self.assertEqual(0, api_keys.forget_opened_models('huggingface'))
        self.assertEqual(0, api_keys.forget_opened_models('no-such-source'))


class InstanceAddressTest(TestCase):
    """2026-10-10 (request of Fabien): the ADDRESS of a source declaring `address_editable` is set
    by an admin on the « Sources externes » page, in the same instance row as its key, and beats
    the Django setting and the `.env` — which stay the fallback."""

    URL = '/common/sources/{}/instance-address/'

    def setUp(self):
        from django.contrib.auth.models import Group
        User = get_user_model()
        self.admin = User.objects.create_user('instance_address_admin', password='x')
        self.admin.groups.add(Group.objects.get_or_create(name='admin')[0])
        self.user = User.objects.create_user('instance_address_user', password='x')

    def _post(self, source, address, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post(self.URL.format(source), data=json.dumps({'base_url': address}),
                                content_type='application/json')

    def test_a_stored_address_beats_the_env_one_which_stays_the_fallback(self):
        from wama.common import external_sources as es
        with mock.patch.dict(os.environ, {'ILAAS_API_BASE': 'https://from-env.example.org/v1'}):
            self.assertEqual(('env', 'https://from-env.example.org/v1'),
                             (es.address_origin('ilaas'), es.base_url('ilaas')))
            r = self._post('ilaas', 'https://from-page.example.org/v1/')
            self.assertEqual('https://from-page.example.org/v1', r.json()['url'])
            self.assertEqual('stored', es.address_origin('ilaas'))
            self._post('ilaas', '')
            self.assertEqual('https://from-env.example.org/v1', es.base_url('ilaas'))

    def test_a_source_not_declaring_it_never_takes_an_address_from_the_page(self):
        from wama.accounts.models import InstanceApiKey
        from wama.common import external_sources as es
        self.assertEqual(404, self._post('ollama', 'http://elsewhere:11434').status_code)
        # Even a row forced in base is ignored: Ollama is read by its own resolver.
        InstanceApiKey.objects.create(source='ollama', base_url='http://elsewhere:11434')
        self.assertNotEqual('http://elsewhere:11434', es.base_url('ollama'))

    def test_only_an_admin_sets_an_address_and_it_must_be_one(self):
        from wama.accounts.models import InstanceApiKey
        self.assertEqual(403, self._post('nextcloud', 'https://cloud.example.org',
                                         user=self.user).status_code)
        for wrong in ('cloud.example.org', 'ftp://cloud.example.org', 'https://a b.org'):
            self.assertEqual(400, self._post('nextcloud', wrong).status_code, wrong)
        self.assertFalse(InstanceApiKey.objects.exists())

    def test_a_required_address_leaves_the_source_unconfigured_and_unprobed_until_set(self):
        from wama.common import external_sources as es
        with mock.patch.dict(os.environ, {'WAMA_NEXTCLOUD_URL': ''}):
            self.assertFalse(es.is_configured('nextcloud'))
            with mock.patch('requests.get') as get:
                self.assertIn('adresse à poser', es.probe('nextcloud')['error'])
            get.assert_not_called()
            self._post('nextcloud', 'https://cloud.example.org')
            self.assertTrue(es.is_configured('nextcloud'))

    def test_removing_the_key_keeps_the_address_and_removing_both_drops_the_row(self):
        from wama.accounts.models import InstanceApiKey
        self._post('ilaas', 'https://from-page.example.org/v1')
        InstanceApiKey.objects.filter(source='ilaas').update(open_models=['ilaas:m'])
        self.client.post('/common/sources/ilaas/instance-key/', data=json.dumps({'api_key': ''}),
                         content_type='application/json')
        row = InstanceApiKey.objects.get(source='ilaas')
        self.assertEqual(('https://from-page.example.org/v1', []), (row.base_url, row.open_models))
        self._post('ilaas', '')
        self.assertFalse(InstanceApiKey.objects.exists())

    def test_the_filemanager_offers_a_declared_cloud_once_its_address_is_set(self):
        with mock.patch.dict(os.environ, {'WAMA_NEXTCLOUD_URL': ''}):
            self.client.force_login(self.user)
            self.assertEqual([], self.client.get('/filemanager/api/mounts/').json()['clouds'])
            self._post('nextcloud', 'https://cloud.example.org')
            self.client.force_login(self.user)
            clouds = self.client.get('/filemanager/api/mounts/').json()['clouds']
        self.assertEqual([('nextcloud', 'https://cloud.example.org')],
                         [(c['key'], c['url']) for c in clouds])


class ProviderOriginInTheProfileTest(TestCase):
    """2026-10-10: the profile says, under each provider, where the data goes and what it costs —
    the same computation as the model selectors (`external_sources.remote_origin_label`)."""

    def test_each_remote_provider_says_its_hosting_and_cost(self):
        user = get_user_model().objects.create_user('origin_profile', password='x')
        rows = {row['slug']: row['origin'] for row in api_keys.listing(user)}
        self.assertEqual('Cloud souverain · gratuit (quota)', rows['albert'])
        self.assertEqual("Cloud commercial · facturé à l'usage", rows['openrouter'])
        # Counter-check: a key that is not a remote model provider says nothing.
        self.assertEqual('', rows['huggingface'])
