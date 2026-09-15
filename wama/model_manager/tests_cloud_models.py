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
            'image-text-to-text': ('captioning', 'vlm'),
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

    def test_sans_cle_personnelle_l_assistant_refuse_sans_se_replier_sur_le_env(self):
        from wama.common.services import assistant_engine
        with mock.patch('wama.common.utils.llm_utils.llm_chat') as chat, \
             mock.patch.dict('os.environ', {'ALBERT_API_KEY': 'cle-instance'}):
            text, err = assistant_engine._llm_call([], None, 'albert', user=self.user)
        self.assertIsNone(text)
        self.assertEqual(400, err['status'])
        chat.assert_not_called()

    def test_avec_cle_personnelle_l_assistant_l_utilise(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import assistant_engine
        UserApiKey.objects.create(user=self.user, source='albert', api_key='sk-perso')
        with mock.patch('wama.common.utils.llm_utils.llm_chat', return_value=('ok', None)) as chat:
            text, _ = assistant_engine._llm_call([], None, 'albert', user=self.user)
        self.assertEqual('ok', text)
        self.assertEqual('sk-perso', chat.call_args.kwargs['api_key'])
