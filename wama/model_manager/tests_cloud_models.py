"""
Modèles DISTANTS au catalogue — ROADMAP §8d Phase 3, étape 4b (2026-09-15).

⚠ CE QUE CES GARDES PROTÈGENT :
- NON-RÉGRESSION : sans autorisation (`cloud_keys`), le tirage et les listes sont IDENTIQUES à
  ceux d'avant le verrou levé — même quand un modèle distant a une bien meilleure note ;
- la synchronisation du disque ne supprime JAMAIS une ligne distante ;
- un utilisateur n'a au tirage que ce que SA clé ouvre, et selon SON niveau cloud ;
- l'assistant appelle Albert avec la clé de l'utilisateur, jamais celle du `.env`.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from wama.model_manager.models import AIModel
from wama.model_manager.services import cloud_models
from wama.model_manager.services.model_selector import get_registry_models, select_model

CLE_A = 'a' * 50

#: Échantillon de ce que rend le FOURNISSEUR (`GET /v1/models` d'Albert) — pas une déclaration
#: WAMA. Un test qui vérifie la lecture d'un protocole tiers doit fixer la forme qu'il lit ; ces
#: identifiants imitent une API, ils ne décrivent rien du catalogue.
ALBERT_MODELS = [
    {'id': 'openai/gpt-oss-120b', 'type': 'text-generation', 'aliases': ['openweight-large']},
    {'id': 'gemma-4-31b-it', 'type': 'image-text-to-text', 'aliases': ['google/gemma-4-31B-it']},
    {'id': 'whisper-large-v3', 'type': 'automatic-speech-recognition', 'aliases': []},
    {'id': 'bge-m3', 'type': 'text-embeddings-inference', 'aliases': ['BAAI/bge-m3']},
    {'id': 'bge-reranker-v2-m3', 'type': 'text-classification', 'aliases': []},
]


def _local_llm(key='ollama:petit:4b', quality=10.0):
    return AIModel.objects.create(model_key=key, name=key, model_type='llm', source='ollama',
                                  is_downloaded=True, vram_gb=4.0, quality_index=quality,
                                  capabilities={'completion': True})


class TypesDistantsTest(TestCase):

    def test_chaque_type_d_albert_trouve_sa_categorie_ou_n_entre_pas(self):
        attendu = {
            'text-generation': ('text-generation', 'llm'),
            # Un modèle de chat qui accepte des images est rangé comme Ollama range les siens :
            # `llm` + `vision`, jamais `captioning` (mesuré le 16/09 — cf. `_CHAT_MULTIMODAL`).
            'image-text-to-text': ('text-generation', 'llm'),
            'automatic-speech-recognition': ('transcription', 'speech'),
            'text-embeddings-inference': ('feature-extraction', 'embedding'),
            'text-classification': (None, None),
        }
        for remote, couple in attendu.items():
            self.assertEqual(couple, cloud_models.task_and_type(remote), remote)


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class DecouverteTest(TestCase):

    def setUp(self):
        from wama.accounts.models import UserApiKey
        self.user = get_user_model().objects.create_user('decouverte_cloud', password='x')
        self.row = UserApiKey.objects.create(user=self.user, source='albert', api_key='sk-test')

    @mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS)
    def test_la_cle_ouvre_les_modeles_rangeables_et_les_garde(self, _):
        count, error = cloud_models.refresh_key(self.row)
        self.assertEqual((4, ''), (count, error))
        self.row.refresh_from_db()
        self.assertEqual(4, len(self.row.open_models))
        m = AIModel.objects.get(model_key='albert:openai/gpt-oss-120b')
        self.assertEqual(('cloud', False, 0, 'albert', 'free'),
                         (m.execution, m.is_downloaded, m.vram_gb, m.source, m.cost_tier))
        self.assertEqual({'engine': 'albert'}, m.composition['runtime'])
        self.assertTrue(m.capabilities.get('completion'))
        self.assertFalse(AIModel.objects.filter(model_key='albert:bge-reranker-v2-m3').exists())

    def test_une_famille_distante_declaree_impose_sa_tache(self):
        """Albert sert `lightonocr` en `image-text-to-text` (« chat qui voit ») — c'est un OCR.
        Même règle que pour Ollama : la tâche est DÉCLARÉE, et la catégorie en dérive."""
        # La déclaration porte sur la FAMILLE : une version que WAMA n'a jamais vue doit être
        # reconnue, sinon la table serait à retoucher à chaque publication du fournisseur.
        annonces = [
            {'id': 'lightonocr-2-1b', 'type': 'image-text-to-text', 'aliases': []},
            {'id': 'lightonocr-9-42b-inedit', 'type': 'image-text-to-text', 'aliases': []},
            {'id': 'gemma-4-31b-it', 'type': 'image-text-to-text', 'aliases': []},
        ]
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=annonces):
            cloud_models.refresh_key(self.row)
        for cle in ('albert:lightonocr-2-1b', 'albert:lightonocr-9-42b-inedit'):
            ocr = AIModel.objects.get(model_key=cle)
            self.assertEqual(('ocr', 'ocr'), (ocr.model_type, ocr.capabilities['task']), cle)
        chat = AIModel.objects.get(model_key='albert:gemma-4-31b-it')
        self.assertEqual(('llm', True), (chat.model_type, chat.capabilities.get('vision')))

    def test_le_moteur_distant_n_est_pas_juge_sans_backend(self):
        from wama.common.backends.manager import backend_missing
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS):
            cloud_models.refresh_key(self.row)
        self.assertIsNone(backend_missing(AIModel.objects.get(model_key='albert:bge-m3')))

    def test_un_echec_garde_la_liste_precedente_et_se_dit(self):
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS):
            cloud_models.refresh_key(self.row)
        with mock.patch.object(cloud_models, 'list_remote_models',
                               side_effect=cloud_models.CloudDiscoveryError('clé refusée')):
            count, error = cloud_models.refresh_key(self.row)
        self.row.refresh_from_db()
        self.assertEqual((0, 'clé refusée'), (count, error))
        self.assertEqual(4, len(self.row.open_models))

    def test_le_niveau_cloud_du_profil_gouverne_l_autorisation(self):
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS):
            cloud_models.refresh_key(self.row)
        profile = self.user.profile
        self.assertEqual(set(), cloud_models.allowed_cloud_keys(self.user))
        self.assertEqual(set(), cloud_models.allowed_cloud_keys(self.user, automatic=False))
        profile.cloud_policy = 'cloud_when_saturated'
        profile.save()
        self.assertEqual(set(), cloud_models.allowed_cloud_keys(self.user))
        self.assertEqual(4, len(cloud_models.allowed_cloud_keys(self.user, automatic=False)))
        profile.cloud_policy = 'cloud_allowed'
        profile.save()
        self.assertEqual(4, len(cloud_models.allowed_cloud_keys(self.user)))


class ProtocolesTest(TestCase):
    """Chaque fournisseur parle SON protocole — déclaré sur la source, jamais deviné."""

    def _appel(self, source, data):
        reponse = mock.Mock(status_code=200, ok=True, json=mock.Mock(return_value={'data': data}))
        with mock.patch('requests.get', return_value=reponse) as get:
            modeles = cloud_models.list_remote_models(source, 'secret')
        return get.call_args.kwargs['headers'], modeles

    def test_albert_bearer_et_type_annonce(self):
        entetes, modeles = self._appel('albert', [{'id': 'm', 'type': 'text-generation'}])
        self.assertEqual('Bearer secret', entetes['Authorization'])
        self.assertEqual('text-generation', modeles[0]['type'])

    def test_anthropic_x_api_key_et_type_declare_par_la_source(self):
        entetes, modeles = self._appel('anthropic', [
            {'id': 'claude-x', 'type': 'model', 'display_name': 'Claude X'}])
        self.assertEqual('secret', entetes['x-api-key'])
        self.assertIn('anthropic-version', entetes)
        self.assertNotIn('Authorization', entetes)
        self.assertEqual(('image-text-to-text', 'Claude X'), (modeles[0]['type'], modeles[0]['name']))

    @override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
    def test_l_abonnement_n_a_pas_de_liste_et_ne_s_en_plaint_pas(self):
        """Mesuré le 15/09 : le jeton d'abonnement est refusé par `/v1/models` mais fait tourner
        le CLI. Aucun appel, aucune erreur affichée au profil."""
        from wama.accounts.models import UserApiKey
        user = get_user_model().objects.create_user('abo_liste', password='x')
        row = UserApiKey.objects.create(user=user, source='claude_code', api_key='jeton')
        with mock.patch('requests.get') as get:
            self.assertEqual((1, ''), cloud_models.refresh_key(row))
        get.assert_not_called()
        # Une ligne DÉCLARÉE entre au catalogue : sans elle, l'abonnement n'existerait pas pour
        # le sélecteur commun et demanderait un chemin à part.
        row.refresh_from_db()
        self.assertEqual(['claude_code:default'], row.open_models)
        declaree = AIModel.objects.get(model_key='claude_code:default')
        self.assertEqual(('cloud', 'subscription', True),
                         (declaree.execution, declaree.cost_tier, declaree.extra_info['declared']))


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class AbonnementPersonnelTest(TestCase):
    """Un utilisateur consomme SON abonnement : jamais celui de la machine."""

    def setUp(self):
        self.dev = get_user_model().objects.create_user('dev_abo', password='x', is_superuser=True)
        self.dev.profile.cloud_policy = 'cloud_allowed'
        self.dev.profile.save()

    def test_en_100_pour_cent_local_l_abonnement_n_est_pas_lance(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import claude_code
        UserApiKey.objects.create(user=self.dev, source='claude_code', api_key='jeton-perso')
        self.dev.profile.cloud_policy = 'local_only'
        self.dev.profile.save()
        with mock.patch('subprocess.run') as run:
            res = claude_code.demander('bonjour', user=self.dev)
        self.assertIn('100 % local', res['error'])
        run.assert_not_called()

    OPTIONS = '/model-manager/api/models/options/?model_type=llm,vlm&cloud=1'

    def _options(self, user):
        self.client.force_login(user)
        groupes = self.client.get(self.OPTIONS).json()['groups'][0]['options']
        return [(o[0] if isinstance(o, list) else o['value']) for o in groupes]

    def test_le_selecteur_commun_propose_les_modeles_ouverts_et_pas_ceux_des_autres(self):
        """Le sélecteur de l'assistant est celui des apps : c'est l'ENDPOINT commun qui décide,
        avec les clés de CET utilisateur et son niveau cloud."""
        from wama.accounts.models import UserApiKey
        AIModel.objects.create(model_key='ollama:local', name='local', model_type='llm',
                               source='ollama', is_downloaded=True,
                               capabilities={'completion': True})
        AIModel.objects.create(model_key='albert:chat', name='chat', model_type='llm',
                               source='albert', execution='cloud',
                               capabilities={'completion': True})
        UserApiKey.objects.create(user=self.dev, source='albert', api_key='sk',
                                  open_models=['albert:chat'])
        ids = self._options(self.dev)
        self.assertIn('albert:chat', ids)
        self.assertIn('ollama:local', ids)
        # Un autre compte, sans clé : le distant n'existe pas pour lui.
        autre = get_user_model().objects.create_user('sans_cle', password='x')
        autre.profile.cloud_policy = 'cloud_allowed'
        autre.profile.save()
        self.assertNotIn('albert:chat', self._options(autre))
        # En « 100 % local », il disparaît aussi pour son propriétaire.
        self.dev.profile.cloud_policy = 'local_only'
        self.dev.profile.save()
        self.assertNotIn('albert:chat', self._options(self.dev))

    def test_le_jeton_n_est_propose_qu_aux_developpeurs(self):
        from wama.accounts.api_keys import llm_sources
        ordinaire = get_user_model().objects.create_user('ordinaire_abo', password='x')
        self.assertNotIn('claude_code', [s.key for s in llm_sources(ordinaire)])
        self.assertIn('claude_code', [s.key for s in llm_sources(self.dev)])
        self.assertIn('anthropic', [s.key for s in llm_sources(ordinaire)])

    def test_sans_jeton_personnel_le_cli_n_est_pas_lance(self):
        from wama.common.services import claude_code
        with mock.patch('subprocess.run') as run:
            res = claude_code.demander('bonjour', user=self.dev)
        self.assertFalse(res['success'])
        run.assert_not_called()

    def test_le_jeton_personnel_est_transmis_au_cli_et_pas_celui_du_env(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import claude_code
        UserApiKey.objects.create(user=self.dev, source='claude_code', api_key='jeton-perso')
        fini = mock.Mock(returncode=0, stdout='{"result": "ok"}', stderr='')
        with mock.patch.object(claude_code, 'chemin_cli', return_value='/bin/claude'), \
             mock.patch('subprocess.run', return_value=fini) as run, \
             mock.patch.dict('os.environ', {'CLAUDE_CODE_OAUTH_TOKEN': 'jeton-machine'}):
            claude_code.demander('bonjour', user=self.dev)
        self.assertEqual('jeton-perso', run.call_args.kwargs['env']['CLAUDE_CODE_OAUTH_TOKEN'])


class NonRegressionTest(TestCase):
    """Sans autorisation, un modèle distant bien mieux noté ne change RIEN."""

    def setUp(self):
        self.local = _local_llm()
        self.cloud = AIModel.objects.create(
            model_key='albert:grand', name='grand', model_type='llm', source='albert',
            execution='cloud', is_downloaded=False, vram_gb=0, quality_index=95.0,
            capabilities={'completion': True}, composition={'runtime': {'engine': 'albert'}})

    def _tirage(self, **kw):
        return select_model(model_type='llm', candidates=[self.local.model_key, self.cloud.model_key],
                            prefer_loaded=False, vram_budget_gb=24.0, quality_intent=100, **kw)

    def test_sans_autorisation_le_tirage_ignore_le_distant(self):
        self.assertEqual(self.local, self._tirage())
        self.assertEqual(self.local, self._tirage(downloaded_only=False))

    def test_avec_autorisation_le_distant_concourt(self):
        self.assertEqual(self.cloud, self._tirage(cloud_keys={self.cloud.model_key}))

    def test_les_listes_n_exposent_pas_le_distant_sans_autorisation(self):
        ids = [d['id'] for d in get_registry_models(model_type='llm')[1]]
        self.assertIn(self.local.model_key, ids)
        self.assertNotIn(self.cloud.model_key, ids)
        ids = [d['id'] for d in get_registry_models(model_type='llm',
                                                    cloud_keys={self.cloud.model_key})[1]]
        self.assertIn(self.cloud.model_key, ids)

    def test_la_synchronisation_du_disque_ne_supprime_pas_le_distant(self):
        from wama.model_manager.services.model_sync import ModelSyncService
        service = ModelSyncService()
        service._registry = mock.Mock(_models={}, discovery_errors=[],
                                      discover_all_models=mock.Mock(return_value={}))
        service.full_sync(delete_missing=True)
        self.assertFalse(AIModel.objects.filter(pk=self.local.pk).exists(),
                         "contre-épreuve : un local absent du disque est bien supprimé")
        self.assertTrue(AIModel.objects.filter(pk=self.cloud.pk).exists())

    def test_un_distant_ne_se_desinstalle_pas(self):
        from wama.model_manager.services.model_installer import uninstall_model
        res = uninstall_model(self.cloud.model_key)
        self.assertFalse(res['ok'])


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class CleDeLAssistantTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('assistant_cle', password='x')
        self.user.profile.cloud_policy = 'cloud_allowed'
        self.user.profile.save()

    def test_en_100_pour_cent_local_le_distant_est_refuse_meme_avec_une_cle(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import assistant_engine
        UserApiKey.objects.create(user=self.user, source='albert', api_key='sk-perso')
        self.user.profile.cloud_policy = 'local_only'
        self.user.profile.save()
        with mock.patch('wama.common.utils.llm_utils.llm_chat') as chat:
            text, err = assistant_engine._llm_call([], None, 'albert', user=self.user)
        self.assertEqual((None, 403), (text, err['status']))
        chat.assert_not_called()

    def test_un_modele_que_la_cle_n_ouvre_pas_est_refuse(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import assistant_engine
        UserApiKey.objects.create(user=self.user, source='albert', api_key='sk-perso',
                                  open_models=['albert:ouvert'])
        with mock.patch('wama.common.utils.llm_utils.llm_chat', return_value=('ok', None)) as chat:
            _, err = assistant_engine._llm_call([], 'ferme', 'albert', user=self.user)
            self.assertEqual(403, err['status'])
            text, _ = assistant_engine._llm_call([], 'ouvert', 'albert', user=self.user)
        self.assertEqual('ok', text)
        self.assertEqual(1, chat.call_count)

    def test_sans_cle_personnelle_l_assistant_refuse_sans_se_replier_sur_le_env(self):
        from wama.common.services import assistant_engine
        with mock.patch('wama.common.utils.llm_utils.llm_chat') as chat, \
             mock.patch.dict('os.environ', {'ALBERT_API_KEY': 'cle-instance'}):
            text, err = assistant_engine._llm_call([], None, 'albert', user=self.user)
        self.assertIsNone(text)
        self.assertEqual(400, err['status'])
        chat.assert_not_called()

    def test_le_fournisseur_claude_prend_la_cle_anthropic_du_profil(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import assistant_engine
        UserApiKey.objects.create(user=self.user, source='anthropic', api_key='sk-ant-perso')
        with mock.patch('wama.common.utils.llm_utils.llm_chat', return_value=('ok', None)) as chat:
            assistant_engine._llm_call([], None, 'claude', user=self.user)
        self.assertEqual('sk-ant-perso', chat.call_args.kwargs['api_key'])
        self.assertEqual('anthropic', chat.call_args.kwargs['provider'])

    def test_avec_cle_personnelle_l_assistant_l_utilise(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import assistant_engine
        UserApiKey.objects.create(user=self.user, source='albert', api_key='sk-perso')
        with mock.patch('wama.common.utils.llm_utils.llm_chat', return_value=('ok', None)) as chat:
            text, _ = assistant_engine._llm_call([], None, 'albert', user=self.user)
        self.assertEqual('ok', text)
        self.assertEqual('sk-perso', chat.call_args.kwargs['api_key'])
