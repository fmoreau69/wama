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
from wama.common.services import source_quota
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


def _decouverte_cloud_seule(self):
    """La découverte du registre réduite à sa source CLOUD : ni disque, ni Ollama, ni apps.
    Remplace `ModelRegistry.discover_all_models` dans les tests qui passent par la
    synchronisation commune (`refresh_key` → `register_after_install`)."""
    self._models = {}
    self.discovery_errors = []
    self._discover_cloud_models()
    return self._models


def _sync_cloud_seul(test):
    """Branche la découverte cloud seule et neutralise l'écriture du corpus pour la durée du test."""
    from wama.model_manager.services.model_registry import ModelRegistry
    for p in (mock.patch.object(ModelRegistry, 'discover_all_models', _decouverte_cloud_seule),
              mock.patch('django.core.management.call_command')):
        p.start()
        test.addCleanup(p.stop)


class TypesDistantsTest(TestCase):

    def test_each_albert_type_maps_to_a_category_or_is_excluded(self):
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
        _sync_cloud_seul(self)

    def _relire(self, annonces, row=None):
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=annonces):
            return cloud_models.refresh_key(row or self.row)

    def test_key_opens_classifiable_models_and_persists_them(self):
        count, error = self._relire(ALBERT_MODELS)
        self.assertEqual((4, ''), (count, error))
        self.row.refresh_from_db()
        self.assertEqual(4, len(self.row.open_models))
        self.assertEqual(ALBERT_MODELS, self.row.remote_listing,
                         "la liste du fournisseur est GARDÉE : la découverte du registre la relit")
        m = AIModel.objects.get(model_key='albert:openai/gpt-oss-120b')
        self.assertEqual(('cloud', False, 0, 'albert', 'free'),
                         (m.execution, m.is_downloaded, m.vram_gb, m.source, m.cost_tier))
        self.assertEqual({'engine': 'albert'}, m.composition['runtime'])
        self.assertTrue(m.capabilities.get('completion'))
        self.assertFalse(AIModel.objects.filter(model_key='albert:bge-reranker-v2-m3').exists())

    def test_remote_row_goes_through_common_synchronization(self):
        """Plus d'écriture à part : c'est `_sync_model` qui crée la ligne, donc les mêmes règles
        de fusion que pour un modèle Ollama (une capacité posée par un manifeste survit)."""
        self._relire(ALBERT_MODELS)
        m = AIModel.objects.get(model_key='albert:gemma-4-31b-it')
        m.capabilities = {**m.capabilities, 'languages': ['fr', 'en']}
        m.save(update_fields=['capabilities'])
        self._relire(ALBERT_MODELS)
        m.refresh_from_db()
        self.assertEqual(['fr', 'en'], m.capabilities.get('languages'))
        self.assertTrue(m.capabilities.get('vision'))

    def test_remote_embedding_carries_embedding_flag_and_repo(self):
        """`requires=['embedding']` doit voir `albert:bge-m3` comme il voit `ollama:bge-m3`
        (mesuré le 18/09 : le drapeau manquait). Et le dépôt servi devient son identité, par
        la provenance — la même que celle d'une installation."""
        self._relire(ALBERT_MODELS)
        m = AIModel.objects.get(model_key='albert:bge-m3')
        self.assertTrue(m.capabilities.get('embedding'))
        self.assertNotIn('completion', m.capabilities)
        self.assertEqual(('BAAI/bge-m3', 'huggingface:BAAI/bge-m3'), (m.hf_id, m.platform_ref))

    def test_renamed_identifier_marks_old_row_unavailable_without_deleting(self):
        """Albert a renommé `openai/gpt-oss-120b` en `gpt-oss-120b` (18/09) : la ligne d'avant
        est MARQUÉE indisponible (elle porte l'historique), la nouvelle prend sa place — et si
        le fournisseur re-liste l'ancien identifiant, la ligne redevient disponible."""
        self._relire(ALBERT_MODELS)
        renommee = [dict(ALBERT_MODELS[0], id='gpt-oss-120b')] + ALBERT_MODELS[1:]
        self._relire(renommee)
        ancienne = AIModel.objects.get(model_key='albert:openai/gpt-oss-120b')
        self.assertFalse(ancienne.is_available)
        self.assertTrue(AIModel.objects.get(model_key='albert:gpt-oss-120b').is_available)
        self.row.refresh_from_db()
        self.assertNotIn('albert:openai/gpt-oss-120b', self.row.open_models)
        self._relire(ALBERT_MODELS)
        ancienne.refresh_from_db()
        self.assertTrue(ancienne.is_available)

    def test_row_stays_available_while_another_key_opens_it(self):
        """L'union se fait sur TOUTES les clés de la source : une clé qui n'ouvre pas un modèle
        ne prouve pas que le fournisseur l'a retiré."""
        from wama.accounts.models import UserApiKey
        autre = get_user_model().objects.create_user('autre_cle', password='x')
        row2 = UserApiKey.objects.create(user=autre, source='albert', api_key='sk-2')
        self._relire(ALBERT_MODELS, row2)
        self._relire(ALBERT_MODELS[1:])            # cette clé n'ouvre pas gpt-oss
        self.assertTrue(AIModel.objects.get(model_key='albert:openai/gpt-oss-120b').is_available)
        self.row.refresh_from_db()
        self.assertNotIn('albert:openai/gpt-oss-120b', self.row.open_models)

    def test_declared_remote_family_imposes_its_task(self):
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

    def test_remote_engine_is_not_flagged_without_backend(self):
        from wama.common.backends.manager import backend_missing
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS):
            cloud_models.refresh_key(self.row)
        self.assertIsNone(backend_missing(AIModel.objects.get(model_key='albert:bge-m3')))

    def test_failure_keeps_previous_list_and_reports_error(self):
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS):
            cloud_models.refresh_key(self.row)
        with mock.patch.object(cloud_models, 'list_remote_models',
                               side_effect=cloud_models.CloudDiscoveryError('clé refusée')):
            count, error = cloud_models.refresh_key(self.row)
        self.row.refresh_from_db()
        self.assertEqual((0, 'clé refusée'), (count, error))
        self.assertEqual(4, len(self.row.open_models))

    def test_profile_cloud_policy_governs_authorization(self):
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

    def test_albert_uses_bearer_auth_and_announced_type(self):
        entetes, modeles = self._appel('albert', [{'id': 'm', 'type': 'text-generation'}])
        self.assertEqual('Bearer secret', entetes['Authorization'])
        self.assertEqual('text-generation', modeles[0]['type'])

    def test_anthropic_uses_x_api_key_and_source_declared_type(self):
        entetes, modeles = self._appel('anthropic', [
            {'id': 'claude-x', 'type': 'model', 'display_name': 'Claude X'}])
        self.assertEqual('secret', entetes['x-api-key'])
        self.assertIn('anthropic-version', entetes)
        self.assertNotIn('Authorization', entetes)
        self.assertEqual(('image-text-to-text', 'Claude X'), (modeles[0]['type'], modeles[0]['name']))

    @override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
    def test_subscription_without_list_produces_no_error(self):
        """Mesuré le 15/09 : le jeton d'abonnement est refusé par `/v1/models` mais fait tourner
        le CLI. Aucun appel, aucune erreur affichée au profil."""
        from wama.accounts.models import UserApiKey
        user = get_user_model().objects.create_user('abo_liste', password='x')
        row = UserApiKey.objects.create(user=user, source='claude_code', api_key='jeton')
        _sync_cloud_seul(self)
        from wama.common import external_sources
        declared = [f'claude_code:{m[0]}' for m in external_sources.get('claude_code').declared_models]
        with mock.patch('requests.get') as get:
            self.assertEqual((len(declared), ''), cloud_models.refresh_key(row))
        get.assert_not_called()
        # Les lignes DÉCLARÉES entrent au catalogue : sans elles, l'abonnement n'existerait pas
        # pour le sélecteur commun et demanderait un chemin à part. Une seule (`default`)
        # jusqu'au 2026-10-04 ; depuis, celles que la SOURCE déclare (les alias du CLI).
        row.refresh_from_db()
        self.assertEqual(declared, row.open_models)
        self.assertIn('claude_code:default', declared)
        declaree = AIModel.objects.get(model_key='claude_code:default')
        self.assertEqual(('cloud', 'subscription', True),
                         (declaree.execution, declaree.cost_tier, declaree.extra_info['declared']))


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class AbonnementPersonnelTest(TestCase):
    """Un utilisateur consomme SON abonnement : jamais celui de la machine."""

    def setUp(self):
        self.dev = get_user_model().objects.create_user('dev_abo', password='x', is_superuser=True)
        self.dev.profile.cloud_policy = 'cloud_allowed'
        # L'abonnement est un hébergeur TIERS : il faut l'avoir admis (plafond, 2026-10-03).
        self.dev.profile.cloud_hosting_max = 'third_party'
        self.dev.profile.save()

    def test_local_only_policy_prevents_subscription_launch(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import claude_code
        UserApiKey.objects.create(user=self.dev, source='claude_code', api_key='sk-ant-oat01-jeton-perso')
        self.dev.profile.cloud_policy = 'local_only'
        self.dev.profile.save()
        with mock.patch('subprocess.run') as run:
            res = claude_code.demander('bonjour', user=self.dev)
        self.assertIn('100 % local', res['error'])
        run.assert_not_called()

    OPTIONS = '/model-manager/api/models/options/?model_type=llm,vlm&cloud=1'

    def _options(self, user):
        self.client.force_login(user)
        # Toutes les options, quel que soit leur groupe : la liste est rangée par ORIGINE
        # depuis le 2026-10-05 (« WAMA local », « Albert API »…).
        groupes = [o for g in self.client.get(self.OPTIONS).json()['groups']
                   for o in g['options']]
        return [(o[0] if isinstance(o, list) else o['value']) for o in groupes]

    def test_common_selector_shows_own_open_models_not_others(self):
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

    def test_token_is_only_offered_to_developers(self):
        from wama.accounts.api_keys import llm_sources
        ordinaire = get_user_model().objects.create_user('ordinaire_abo', password='x')
        self.assertNotIn('claude_code', [s.key for s in llm_sources(ordinaire)])
        self.assertIn('claude_code', [s.key for s in llm_sources(self.dev)])
        self.assertIn('anthropic', [s.key for s in llm_sources(ordinaire)])

    def test_without_personal_token_cli_is_not_launched(self):
        from wama.common.services import claude_code
        with mock.patch('subprocess.run') as run:
            res = claude_code.demander('bonjour', user=self.dev)
        self.assertFalse(res['success'])
        run.assert_not_called()

    def test_personal_token_is_passed_to_cli_not_env_one(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import claude_code
        UserApiKey.objects.create(user=self.dev, source='claude_code', api_key='sk-ant-oat01-jeton-perso')
        fini = mock.Mock(returncode=0, stdout='{"result": "ok"}', stderr='')
        with mock.patch.object(claude_code, 'chemin_cli', return_value='/bin/claude'), \
             mock.patch('subprocess.run', return_value=fini) as run, \
             mock.patch.dict('os.environ', {'CLAUDE_CODE_OAUTH_TOKEN': 'jeton-machine'}):
            claude_code.demander('bonjour', user=self.dev)
        self.assertEqual('sk-ant-oat01-jeton-perso', run.call_args.kwargs['env']['CLAUDE_CODE_OAUTH_TOKEN'])


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

    def test_without_authorization_draw_ignores_remote(self):
        self.assertEqual(self.local, self._tirage())
        self.assertEqual(self.local, self._tirage(downloaded_only=False))

    def test_with_authorization_remote_is_considered(self):
        self.assertEqual(self.cloud, self._tirage(cloud_keys={self.cloud.model_key}))

    def test_lists_do_not_expose_remote_without_authorization(self):
        ids = [d['id'] for d in get_registry_models(model_type='llm')[1]]
        self.assertIn(self.local.model_key, ids)
        self.assertNotIn(self.cloud.model_key, ids)
        ids = [d['id'] for d in get_registry_models(model_type='llm',
                                                    cloud_keys={self.cloud.model_key})[1]]
        self.assertIn(self.cloud.model_key, ids)

    def test_sync_reconciles_remote_like_local(self):
        """Depuis le 18/09 la découverte cloud relit les clés d'API : une ligne qu'une clé
        ouvre survit à la réconciliation, une ligne que plus aucune clé n'ouvre est traitée
        comme un local absent du disque — une seule règle, pas deux."""
        from wama.accounts.models import UserApiKey
        from wama.model_manager.services.model_sync import ModelSyncService
        _sync_cloud_seul(self)
        with override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[]):
            cle = UserApiKey.objects.create(
                user=get_user_model().objects.create_user('cle_sync', password='x'),
                source='albert', api_key='sk',
                remote_listing=[{'id': 'grand', 'type': 'text-generation', 'aliases': []}])
        ModelSyncService().full_sync(delete_missing=True)
        self.assertFalse(AIModel.objects.filter(pk=self.local.pk).exists(),
                         "contre-épreuve : un local absent du disque est bien supprimé")
        self.assertTrue(AIModel.objects.filter(pk=self.cloud.pk).exists())
        cle.delete()
        ModelSyncService().full_sync(delete_missing=True)
        self.assertFalse(AIModel.objects.filter(pk=self.cloud.pk).exists(),
                         "plus aucune clé ne l'ouvre : réconcilié comme un local disparu")

    def test_remote_model_cannot_be_uninstalled(self):
        from wama.model_manager.services.model_installer import uninstall_model
        res = uninstall_model(self.cloud.model_key)
        self.assertFalse(res['ok'])


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class AssistantPersonalKeyTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('assistant_cle', password='x')
        self.user.profile.cloud_policy = 'cloud_allowed'
        # Ces tests appellent aussi l'API Anthropic, hébergeur TIERS (plafond, 2026-10-03).
        self.user.profile.cloud_hosting_max = 'third_party'
        self.user.profile.save()

    def test_local_only_policy_rejects_remote_even_with_key(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import assistant_engine
        UserApiKey.objects.create(user=self.user, source='albert', api_key='sk-perso')
        self.user.profile.cloud_policy = 'local_only'
        self.user.profile.save()
        with mock.patch('wama.common.utils.llm_utils.llm_chat') as chat:
            text, err = assistant_engine._llm_call([], None, 'albert', user=self.user)
        self.assertEqual((None, 403), (text, err['status']))
        chat.assert_not_called()

    def test_model_not_opened_by_key_is_rejected(self):
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

    def test_without_personal_key_assistant_refuses_without_falling_back_to_env(self):
        from wama.common.services import assistant_engine
        with mock.patch('wama.common.utils.llm_utils.llm_chat') as chat, \
             mock.patch.dict('os.environ', {'ALBERT_API_KEY': 'cle-instance'}):
            text, err = assistant_engine._llm_call([], None, 'albert', user=self.user)
        self.assertIsNone(text)
        self.assertEqual(400, err['status'])
        chat.assert_not_called()

    def test_claude_provider_uses_anthropic_key_from_profile(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import assistant_engine
        UserApiKey.objects.create(user=self.user, source='anthropic', api_key='sk-ant-perso')
        with mock.patch('wama.common.utils.llm_utils.llm_chat', return_value=('ok', None)) as chat:
            assistant_engine._llm_call([], None, 'claude', user=self.user)
        self.assertEqual('sk-ant-perso', chat.call_args.kwargs['api_key'])
        self.assertEqual('anthropic', chat.call_args.kwargs['provider'])

    def test_with_personal_key_assistant_uses_it(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services import assistant_engine
        UserApiKey.objects.create(user=self.user, source='albert', api_key='sk-perso')
        with mock.patch('wama.common.utils.llm_utils.llm_chat', return_value=('ok', None)) as chat:
            text, _ = assistant_engine._llm_call([], None, 'albert', user=self.user)
        self.assertEqual('ok', text)
        self.assertEqual('sk-perso', chat.call_args.kwargs['api_key'])


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class CatalogueUpdateInTheBackgroundTest(TestCase):
    """2026-10-02 — saving a key on the profile ran the FULL catalogue sync inside the request:
    over two minutes, a button that seemed dead, a double submission. The provider's listing stays
    immediate (it tells how many models the key opens); the catalogue update leaves the request."""

    def setUp(self):
        from wama.accounts.models import UserApiKey
        self.user = get_user_model().objects.create_user('background_cloud', password='x')
        self.row = UserApiKey.objects.create(user=self.user, source='albert', api_key='sk-test')
        _sync_cloud_seul(self)

    def _refresh_in_background(self):
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS), \
                mock.patch('wama.model_manager.tasks.register_cloud_key_task.delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            result = cloud_models.refresh_key(self.row, background=True)
        return result, delay

    def test_the_count_is_immediate_and_the_catalogue_update_is_queued(self):
        (count, error), delay = self._refresh_in_background()
        self.assertEqual((4, ''), (count, error))
        # Second argument (2026-10-07): the key is a USER key, not the instance one.
        delay.assert_called_once_with(self.row.pk, False)
        self.assertFalse(AIModel.objects.filter(model_key='albert:gemma-4-31b-it').exists(),
                         'the catalogue is not touched inside the request')

    def test_the_queued_task_registers_what_the_key_opens(self):
        from wama.model_manager.tasks import register_cloud_key_task
        self._refresh_in_background()
        self.assertEqual({'registered': True, 'source': 'albert', 'open_models': 4},
                         register_cloud_key_task(self.row.pk))
        self.assertTrue(AIModel.objects.filter(model_key='albert:gemma-4-31b-it').exists())

    def test_the_catalogue_update_never_runs_the_full_discovery(self):
        """A key only changes REMOTE models: the full discovery (disks, Ollama, apps) took ~5 min
        for that (measured 2026-10-02). The cloud-only sync writes the same rows."""
        from wama.model_manager.services.model_registry import ModelRegistry
        from wama.model_manager.tasks import register_cloud_key_task
        self._refresh_in_background()
        with mock.patch.object(ModelRegistry, 'discover_all_models',
                               side_effect=AssertionError('full discovery')):
            self.assertTrue(register_cloud_key_task(self.row.pk)['registered'])
        self.assertTrue(AIModel.objects.filter(model_key='albert:gemma-4-31b-it').exists())

    def test_a_key_removed_before_the_task_runs_is_not_an_error(self):
        from wama.model_manager.tasks import register_cloud_key_task
        pk = self.row.pk
        self.row.delete()
        self.assertEqual({'registered': False}, register_cloud_key_task(pk))


#: Shape of ILaaS's `GET /v1/models`, read with the real key on 2026-10-12: no `type`, no
#: aliases — only `id`, `object`, `owned_by`. Fixes the form the parser reads, describes nothing.
ILAAS_LISTING = [{'id': model_id, 'object': 'model', 'owned_by': model_id}
                 for model_id in ('gemma-4-31b', 'llama-3.1-8b', 'mistral-small-4-119b')]


def _listing_answers(*listings, status=200):
    """`requests.get` answers, one per call: the provider's `data` for each read."""
    return [mock.Mock(status_code=status, ok=status < 400,
                      json=mock.Mock(return_value={'object': 'list', 'data': list(data)}))
            for data in listings]


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class EmptyListingTest(TestCase):
    """2026-10-12 — ILaaS answers `{"data": []}` with HTTP 200 to about one read in two (9 of 20
    measured, same key, same headers; its chat answers 10 times out of 10). Taken as a list, the
    empty answer emptied the instance key of its models and `retire_unlisted` withdrew their
    catalogue rows — on the « Save » gesture and at the nightly probe alike, with no error shown."""

    def setUp(self):
        from wama.accounts.models import InstanceApiKey
        _sync_cloud_seul(self)
        self.row = InstanceApiKey.objects.create(source='ilaas', api_key='sk-ilaas', shared=True)

    def _list(self, *listings, status=200):
        with mock.patch('requests.get', side_effect=_listing_answers(*listings, status=status)) as get:
            try:
                return get, cloud_models.list_remote_models('ilaas', 'sk-ilaas'), None
            except cloud_models.CloudDiscoveryError as exc:
                return get, None, exc

    def _refresh(self, *listings):
        with mock.patch('requests.get', side_effect=_listing_answers(*listings)):
            return cloud_models.refresh_key(self.row)

    def test_an_empty_answer_is_read_again_until_the_list_comes(self):
        get, models, error = self._list([], [], ILAAS_LISTING)
        self.assertIsNone(error)
        self.assertEqual(3, get.call_count)
        self.assertEqual([m['id'] for m in ILAAS_LISTING], [m['id'] for m in models])
        # No `type` in the listing: the type DECLARED by the source applies.
        self.assertEqual({'text-generation'}, {m['type'] for m in models})

    def test_a_list_that_stays_empty_is_a_discovery_error(self):
        get, models, error = self._list(*([[]] * cloud_models.LISTING_ATTEMPTS))
        self.assertIsNone(models)
        self.assertEqual(cloud_models.LISTING_ATTEMPTS, get.call_count)
        self.assertIn("n'a rendu aucun modèle", str(error))

    def test_a_full_list_is_read_once(self):
        # Counter-check: a provider that answers is not called again.
        get, models, _ = self._list(ILAAS_LISTING)
        self.assertEqual((1, 3), (get.call_count, len(models)))

    def test_a_refused_key_is_not_read_again(self):
        # Counter-check: a refusal is an answer, not an empty list — reading again would only
        # repeat it (and hammer a provider that counts refused calls).
        get, models, error = self._list([], status=401)
        self.assertEqual(1, get.call_count)
        self.assertIn('clé refusée', str(error))

    def test_the_key_keeps_its_models_and_the_catalogue_its_rows(self):
        self.assertEqual((3, ''), self._refresh(ILAAS_LISTING))
        row = AIModel.objects.get(model_key='ilaas:gemma-4-31b')
        self.assertTrue(row.is_available)
        count, error = self._refresh(*([[]] * cloud_models.LISTING_ATTEMPTS))
        self.assertEqual(0, count)
        self.row.refresh_from_db()
        self.assertEqual(error, self.row.discovery_error, 'the error is SAID on the key row')
        self.assertEqual(3, len(self.row.open_models), 'the previous list is kept')
        self.assertEqual([m['id'] for m in ILAAS_LISTING],
                         [m['id'] for m in self.row.remote_listing])
        row.refresh_from_db()
        self.assertTrue(row.is_available, 'the catalogue row is not withdrawn')

    def test_saving_the_key_on_the_sources_page_says_the_empty_answer(self):
        """The gesture of the « Sources externes » page (`store_key`): an empty answer read
        again gives the models; one that stays empty is said, and the key stays saved."""
        from wama.accounts.api_keys import store_key
        with mock.patch('requests.get', side_effect=_listing_answers([], ILAAS_LISTING)):
            result = store_key(self.row, 'sk-ilaas-2')
        self.assertEqual((200, 3, ''),
                         (result['status'], result['models_count'], result['discovery_error']))
        with mock.patch('requests.get',
                        side_effect=_listing_answers(*([[]] * cloud_models.LISTING_ATTEMPTS))):
            result = store_key(self.row, 'sk-ilaas-3')
        self.assertEqual((200, True), (result['status'], result['has_key']))
        self.assertIn("n'a rendu aucun modèle", result['discovery_error'])
        self.row.refresh_from_db()
        self.assertEqual(('sk-ilaas-3', 3), (self.row.api_key, len(self.row.open_models)))

    def test_the_nightly_probe_keeps_the_list_and_reports_the_empty_answer(self):
        self._refresh(ILAAS_LISTING)
        with mock.patch('requests.get',
                        side_effect=_listing_answers(*([[]] * cloud_models.LISTING_ATTEMPTS))):
            summary = cloud_models.refresh_all_keys()
        self.assertIn("n'a rendu aucun modèle", summary['errors']['ilaas'])
        self.assertEqual({}, summary['removed'])
        self.row.refresh_from_db()
        self.assertEqual(3, len(self.row.open_models))


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class HostingCeilingTest(TestCase):
    """SECOND AXE du cloud (2026-10-03) : le niveau dit QUAND, le plafond dit JUSQU'OÙ, et un
    modèle facturé à l'usage n'entre au tirage automatique que sur consentement.

    Mesuré avant : « cloud autorisé » + une clé d'API Anthropic faisaient rendre au tirage
    un modèle facturé au jeton aux curseurs 0, 50 et 100.
    """

    def setUp(self):
        from wama.accounts.models import UserApiKey
        self.user = get_user_model().objects.create_user('hosting_ceiling', password='x')
        self.profile = self.user.profile
        self.profile.cloud_policy = 'cloud_allowed'
        self.profile.save()
        UserApiKey.objects.create(user=self.user, source='albert', api_key='sk',
                                  open_models=['albert:chat'])
        UserApiKey.objects.create(user=self.user, source='anthropic', api_key='sk',
                                  open_models=['anthropic:claude-x'])

    def _keys(self, automatic=True):
        return cloud_models.allowed_cloud_keys(get_user_model().objects.get(pk=self.user.pk),
                                               automatic=automatic)

    def _set(self, **values):
        for name, value in values.items():
            setattr(self.profile, name, value)
        self.profile.save()

    def test_a_new_profile_stops_at_the_sovereign_cloud(self):
        self.assertEqual({'albert:chat'}, self._keys())
        self.assertEqual({'albert:chat'}, self._keys(automatic=False))

    def test_a_commercial_ceiling_opens_the_manual_choice_but_not_the_metered_draw(self):
        self._set(cloud_hosting_max='third_party')
        self.assertEqual({'albert:chat', 'anthropic:claude-x'}, self._keys(automatic=False))
        self.assertEqual({'albert:chat'}, self._keys())

    def test_the_metered_consent_opens_the_automatic_draw(self):
        self._set(cloud_hosting_max='third_party', cloud_metered_auto=True)
        self.assertEqual({'albert:chat', 'anthropic:claude-x'}, self._keys())

    def test_the_metered_consent_does_not_lift_the_ceiling(self):
        """Contre-épreuve : consentir au payant ne rouvre pas un hébergement refusé."""
        self._set(cloud_metered_auto=True)
        self.assertEqual({'albert:chat'}, self._keys())

    def test_a_private_ceiling_admits_no_source_yet(self):
        """Aucune source ne se déclare « privée » aujourd'hui : le plafond le plus bas ferme tout."""
        self._set(cloud_hosting_max='private')
        self.assertEqual(set(), self._keys(automatic=False))

    def test_the_refusal_names_the_ceiling_and_spares_an_admitted_source(self):
        user = get_user_model().objects.get(pk=self.user.pk)
        self.assertIn('souverain', cloud_models.cloud_refusal(user, 'anthropic'))
        self.assertEqual('', cloud_models.cloud_refusal(user, 'albert'))
        with self.assertRaises(cloud_models.CloudAccessRefused):
            cloud_models.cloud_access(user, 'anthropic', 'claude-x')

    def test_the_scale_is_ordered_and_an_undeclared_hosting_is_never_admitted(self):
        from wama.common import external_sources as es
        self.assertTrue(es.hosting_within('private', 'sovereign'))
        self.assertTrue(es.hosting_within('sovereign', 'sovereign'))
        self.assertFalse(es.hosting_within('third_party', 'sovereign'))
        self.assertFalse(es.hosting_within('', 'third_party'))
        # Toute source LLM déclare un hébergement de l'échelle — sinon elle n'ouvrirait rien.
        for source in es.SOURCES:
            if source.kind == 'llm':
                self.assertIn(source.hosting, es.HOSTING_SCALE, source.key)
                # Le dernier cran est un PLAFOND, jamais un hébergement déclaré.
                self.assertNotEqual(es.DATA_REUSE_CEILING, source.hosting, source.key)
        # Chaque cran tient dans la colonne du profil (pas de `choices=`, donc rien d'autre ne le
        # vérifie : un 1ᵉʳ nom de 17 caractères y a échoué le 2026-10-12).
        from wama.accounts.models import UserProfile
        width = UserProfile._meta.get_field('cloud_hosting_max').max_length
        for level in es.HOSTING_SCALE:
            self.assertLessEqual(len(level), width, level)

    def test_a_ceiling_says_what_the_level_is_never_a_provider(self):
        """2026-10-13 (Fabien) : « Albert en dur… pas homogène avec les autres choix » — ILaaS est
        souverain lui aussi. Un cran DÉCRIT l'hébergement ; nommer une source la périme à la
        suivante. Parcours des sources DÉCLARÉES, pas une liste de noms."""
        from wama.common import external_sources as es
        names = {s.key.split('_')[0].lower() for s in es.SOURCES if s.kind == 'llm'}
        names |= {s.label.split()[0].lower() for s in es.SOURCES
                  if s.kind == 'llm' and s.label.split()[0].lower() != 'api'}
        self.assertIn('albert', names)
        self.assertIn('ilaas', names)
        for level, label in es.HOSTING_CEILING_LABELS.items():
            words = set(label.lower().replace('(', ' ').replace(')', ' ').split())
            self.assertFalse(words & names, f'{level} : {label}')

    def test_only_the_last_rung_accepts_data_reuse_and_it_still_admits_every_source(self):
        """2026-10-12 (Fabien) : la règle de collecte suit le plafond. Le dernier cran admet tout
        ce qu'admet « commercial », et seul lui accepte qu'un hébergeur garde les requêtes."""
        user = get_user_model().objects.get(pk=self.user.pk)
        self.assertFalse(cloud_models.data_reuse_accepted(user))         # défaut : souverain
        self._set(cloud_hosting_max='third_party')
        self.assertFalse(cloud_models.data_reuse_accepted(get_user_model().objects.get(pk=self.user.pk)))
        self._set(cloud_hosting_max='third_party_all')
        user = get_user_model().objects.get(pk=self.user.pk)
        self.assertTrue(cloud_models.data_reuse_accepted(user))
        self.assertEqual({'albert:chat', 'anthropic:claude-x'}, self._keys(automatic=False))
        self.assertFalse(cloud_models.data_reuse_accepted(None))


class FreeModelsOfAMeteredSourceTest(TestCase):
    """2026-10-12: the cost is read PER MODEL. OpenRouter is a metered source carrying free
    models; the metered filter read the SOURCE's tier, so none ever entered the automatic draw.
    And its free models are served only to who accepts training on the requests (measured:
    404 « Free model training » under `data_collection: deny`) — so the draw takes them only at
    the last rung of the ceiling."""

    FREE, PAID = 'openrouter:vendor/model:free', 'openrouter:vendor/model'

    _keys = HostingCeilingTest._keys
    _set = HostingCeilingTest._set

    def setUp(self):
        HostingCeilingTest.setUp(self)
        from wama.accounts.models import UserApiKey
        UserApiKey.objects.create(user=self.user, source='openrouter', api_key='sk',
                                  open_models=[self.FREE, self.PAID])
        for key, tier in ((self.FREE, 'free'), (self.PAID, 'metered')):
            AIModel.objects.create(model_key=key, name=key, model_type='llm', source='openrouter',
                                   execution='cloud', cost_tier=tier)

    def test_the_last_rung_lets_the_free_models_into_the_draw_and_not_the_paid_ones(self):
        self._set(cloud_hosting_max='third_party_all')
        self.assertEqual({'albert:chat', self.FREE}, self._keys())

    def test_below_the_last_rung_the_draw_skips_free_models_bound_to_fail(self):
        self._set(cloud_hosting_max='third_party')
        self.assertEqual({'albert:chat'}, self._keys())

    def test_the_metered_consent_adds_the_paid_ones_only(self):
        self._set(cloud_hosting_max='third_party', cloud_metered_auto=True)
        self.assertEqual({'albert:chat', 'anthropic:claude-x', self.PAID}, self._keys())

    def test_the_manual_choice_is_not_filtered(self):
        """Counter-test: naming a model is a consent — the manual list keeps both."""
        self._set(cloud_hosting_max='third_party')
        self.assertEqual({'albert:chat', 'anthropic:claude-x', self.FREE, self.PAID},
                         self._keys(automatic=False))


class SaturatedSourceOutOfTheDrawTest(TestCase):
    """2026-10-13 (ROADMAP §8d step 2): a provider noted saturated is left out of the AUTOMATIC
    draw while the note lasts — for every caller, since they all read this admission. A rate
    limit belongs to the KEY; an outage to the provider, for everyone."""

    _keys = HostingCeilingTest._keys
    _set = HostingCeilingTest._set

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        HostingCeilingTest.setUp(self)
        self._set(cloud_hosting_max='third_party', cloud_metered_auto=True)

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

    def test_a_rate_limited_key_leaves_its_source_out_of_the_draw(self):
        self.assertEqual({'albert:chat', 'anthropic:claude-x'}, self._keys())
        user = get_user_model().objects.get(pk=self.user.pk)
        self.assertEqual(f'user:{self.user.pk}', source_quota.saturation_scope(user, 'albert'))
        source_quota.note_saturation('albert', scope=f'user:{self.user.pk}', seconds=60,
                                    reason='limite de débit')
        self.assertEqual({'anthropic:claude-x'}, self._keys())
        self.assertEqual('limite de débit', source_quota.saturation_reason(user, 'albert'))

    def test_the_manual_choice_keeps_a_saturated_source(self):
        """Counter-test: naming a model is a consent — the caller proposes a relay instead."""
        source_quota.note_saturation('albert', scope=source_quota.ALL_KEYS, seconds=60,
                                    reason='indisponible')
        self.assertEqual({'albert:chat', 'anthropic:claude-x'}, self._keys(automatic=False))

    def test_another_keys_limit_does_not_concern_this_user(self):
        source_quota.note_saturation('albert', scope='instance', seconds=60, reason='x')
        source_quota.note_saturation('albert', scope='user:0', seconds=60, reason='x')
        self.assertEqual({'albert:chat', 'anthropic:claude-x'}, self._keys())

    def test_an_outage_is_out_of_the_draw_for_every_key(self):
        source_quota.note_saturation('anthropic', scope=source_quota.ALL_KEYS, seconds=60,
                                    reason='indisponible')
        self.assertEqual({'albert:chat'}, self._keys())


class QuotaOutOfTheDrawTest(TestCase):
    """2026-10-14 (ROADMAP §8d step 3): a model whose quota is reached leaves the AUTOMATIC draw
    BEFORE the provider refuses — the count is the common brick `source_quota`. Declared here:
    the free models of OpenRouter share 20 requests a minute."""

    FREE, PAID = FreeModelsOfAMeteredSourceTest.FREE, FreeModelsOfAMeteredSourceTest.PAID
    _keys = HostingCeilingTest._keys
    _set = HostingCeilingTest._set

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        FreeModelsOfAMeteredSourceTest.setUp(self)
        self._set(cloud_hosting_max='third_party_all', cloud_metered_auto=True)

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

    def test_the_free_models_leave_the_draw_once_their_shared_quota_is_used(self):
        self.assertIn(self.FREE, self._keys())
        for _ in range(20):
            source_quota.record('openrouter', f'user:{self.user.pk}', 'other/model:free')
        keys = self._keys()
        self.assertNotIn(self.FREE, keys)
        # Counter-tests: the paid model of the same source, and the other sources, stay.
        self.assertEqual({'albert:chat', 'anthropic:claude-x', self.PAID}, keys)

    def test_the_manual_choice_is_not_filtered_by_the_count(self):
        for _ in range(20):
            source_quota.record('openrouter', f'user:{self.user.pk}', 'other/model:free')
        self.assertIn(self.FREE, self._keys(automatic=False))


@override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
class NightlyRefreshTest(TestCase):
    """La sonde NOCTURNE relit les modèles de chaque clé (2026-10-04) : la liste n'était relue
    qu'au geste du profil, donc figée — un modèle publié depuis n'existait pas pour WAMA."""

    def setUp(self):
        from wama.accounts.models import UserApiKey
        _sync_cloud_seul(self)
        self.user = get_user_model().objects.create_user('nightly_cloud', password='x')
        self.albert = UserApiKey.objects.create(user=self.user, source='albert', api_key='sk',
                                                open_models=['albert:bge-m3'])
        self.subscription = UserApiKey.objects.create(user=self.user, source='claude_code',
                                                      api_key='jeton', open_models=['claude_code:default'])

    def test_a_newly_published_model_enters_and_a_withdrawn_one_leaves(self):
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS) as listing:
            summary = cloud_models.refresh_all_keys()
        self.albert.refresh_from_db()
        # Deux clés relues : celle d'Albert (réseau), et celle de l'abonnement, dont la
        # déclaration a grandi depuis qu'elle a été posée (aucun appel pour elle).
        self.assertEqual(2, summary['keys'])
        self.assertIn('albert:whisper-large-v3', summary['added']['albert'])
        self.assertIn('albert:whisper-large-v3', self.albert.open_models)
        self.assertIsNotNone(self.albert.discovered_at)
        # Contre-épreuve : relu sans changement, la sonde ne signale rien.
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS):
            again = cloud_models.refresh_all_keys()
        self.assertEqual(({}, {}), (again['added'], again['removed']))
        # Le fournisseur retire un modèle : il sort de la liste ouverte.
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS[:1]):
            shrunk = cloud_models.refresh_all_keys()
        self.assertIn('albert:whisper-large-v3', shrunk['removed']['albert'])
        self.assertEqual(1, listing.call_count)

    def test_a_provider_without_a_model_list_is_never_called_but_follows_its_declaration(self):
        """L'abonnement n'a pas de liste à relire : aucun appel réseau pour lui. Mais sa clé suit
        la DÉCLARATION de la source — posée quand il n'y avait qu'une ligne, elle reçoit les
        modèles déclarés depuis ; inchangée, elle n'est plus touchée."""
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS) as listing:
            first = cloud_models.refresh_all_keys()
        self.assertEqual(['albert'], [call.args[0] for call in listing.call_args_list])
        self.subscription.refresh_from_db()
        self.assertIn('claude_code:opus', self.subscription.open_models)
        self.assertIn('claude_code:opus', first['added']['claude_code'])
        stamp = self.subscription.discovered_at
        with mock.patch.object(cloud_models, 'list_remote_models', return_value=ALBERT_MODELS):
            again = cloud_models.refresh_all_keys()
        self.subscription.refresh_from_db()
        self.assertEqual(stamp, self.subscription.discovered_at, 'déclaration inchangée : non relue')
        self.assertNotIn('claude_code', again['added'])

    def test_a_provider_outage_keeps_the_previous_list_and_is_reported(self):
        with mock.patch.object(cloud_models, 'list_remote_models',
                               side_effect=cloud_models.CloudDiscoveryError('injoignable')):
            summary = cloud_models.refresh_all_keys()
        self.albert.refresh_from_db()
        self.assertEqual({'albert': 'injoignable'}, summary['errors'])
        self.assertEqual(['albert:bge-m3'], self.albert.open_models)

    def test_the_probe_is_scheduled_every_night(self):
        from django.conf import settings
        entry = settings.CELERY_BEAT_SCHEDULE['cloud-models-refresh']
        self.assertEqual('model_manager.refresh_cloud_keys', entry['task'])


class RenamedModelTest(TestCase):
    """Un fournisseur qui RENOMME un modèle ne fait pas un modèle de plus (2026-10-22, vérifié en
    direct chez Albert) : l'ancien nom — même id à la casse près, ou alias déclaré du vivant — se
    SUPPRIME ; un modèle vraiment retiré, ou qui porte un historique, reste marqué."""

    def setUp(self):
        from wama.accounts.models import UserApiKey
        user = get_user_model().objects.create_user('renamed_cloud', password='x')
        UserApiKey.objects.create(user=user, source='albert', api_key='sk',
                                  open_models=['albert:coder-a3b', 'albert:gpt-x'])
        row = {'model_type': 'llm', 'source': 'albert', 'execution': 'cloud'}
        AIModel.objects.create(model_key='albert:coder-a3b', name='a', **row)
        AIModel.objects.create(model_key='albert:gpt-x', name='g', extra_info={'aliases': ['org/gpt-x']},
                               **row)
        for key in ('albert:coder-A3b', 'albert:org/gpt-x', 'albert:gone', 'albert:CODER-A3B-tracked'):
            AIModel.objects.create(model_key=key, name=key, is_available=False, **row)

    def test_an_old_name_goes_a_withdrawn_model_stays(self):
        retired = cloud_models.retire_unlisted('albert')
        keys = set(AIModel.objects.filter(source='albert').values_list('model_key', flat=True))
        # `coder-A3b` (même id à la casse près) et `org/gpt-x` (alias déclaré) sont partis ;
        # `gone` (vraiment retiré) et `CODER-A3B-tracked` (un AUTRE id) restent, marqués.
        self.assertEqual({'albert:coder-a3b', 'albert:gpt-x', 'albert:gone', 'albert:CODER-A3B-tracked'},
                         keys)
        self.assertEqual(0, retired)                       # rien de vivant n'a été retiré

    def test_a_row_with_a_runtime_history_is_never_deleted(self):
        from wama.model_manager.models import ModelRuntimeStat
        from wama.model_manager.services.eta_estimator import hardware_fingerprint
        # Un ancien nom qui porte une durée APPRISE : il reste. L'empreinte est la vraie (celle de
        # cette machine, sous laquelle l'ETA range TOUTE durée, distante comprise) — la règle ne lit
        # que la clé.
        ModelRuntimeStat.objects.create(model_key='albert:coder-A3b',
                                        hardware_fingerprint=hardware_fingerprint())
        dropped = cloud_models.drop_renamed('albert')
        self.assertNotIn('albert:coder-A3b', dropped)
        self.assertTrue(AIModel.objects.filter(model_key='albert:coder-A3b').exists())
        # Contre-épreuve : l'autre ancien nom, sans historique, part.
        self.assertEqual(['albert:org/gpt-x'], dropped)


class OriginLabelTest(TestCase):
    """L'ORIGINE d'un modèle se DÉRIVE de sa ligne (exécution, source, hébergement, coût) —
    affichée sous les sélecteurs de modèle (`WamaModelHelp`)."""

    def _row(self, key, **fields):
        return AIModel(model_key=key, name=key, model_type='llm', source=key.split(':')[0], **fields)

    def test_each_origin_is_said_in_plain_words(self):
        self.assertEqual('WAMA local · Ollama', self._row('ollama:x').origin_label)
        self.assertEqual('WAMA local', self._row('imager:x').origin_label)
        self.assertEqual('Cloud souverain · Albert API (DINUM) · gratuit (quota)',
                         self._row('albert:x', execution='cloud', cost_tier='free').origin_label)
        self.assertEqual("Cloud commercial · API Anthropic (Claude) · facturé à l'usage",
                         self._row('anthropic:x', execution='cloud', cost_tier='metered').origin_label)
        # « (abonnement) » n'est plus dans le NOM de la source (2026-10-10) : dit une seule fois.
        self.assertEqual('Cloud commercial · Claude Code · abonnement',
                         self._row('claude_code:x', execution='cloud', cost_tier='subscription').origin_label)

    def test_a_row_without_its_own_cost_says_the_cost_of_its_source(self):
        # 2026-10-10: the cost is always said — the model's if it declares one, else the source's.
        self.assertEqual('Cloud souverain · Albert API (DINUM) · gratuit (quota)',
                         self._row('albert:x', execution='cloud').origin_label)
        self.assertEqual('Cloud commercial · OpenRouter · gratuit (quota)',
                         self._row('openrouter:m:free', execution='cloud',
                                   cost_tier='free').origin_label)

    def test_the_catalogue_api_carries_the_origin(self):
        self.assertEqual('WAMA local · Ollama', self._row('ollama:x').to_dict()['origin'])

    def test_the_ring_is_also_a_key_and_a_rank(self):
        # 2026-10-16: the model manager filter bar filters on the key and sorts on the rank.
        local = self._row('ollama:x').to_dict()
        albert = self._row('albert:x', execution='cloud', cost_tier='free').to_dict()
        anthropic = self._row('anthropic:x', execution='cloud', cost_tier='metered').to_dict()
        self.assertEqual(['local', 'sovereign', 'third_party'],
                         [d['hosting'] for d in (local, albert, anthropic)])
        self.assertLess(local['origin_rank'], albert['origin_rank'])
        self.assertLess(albert['origin_rank'], anthropic['origin_rank'])

    def test_an_undeclared_remote_source_has_no_ring(self):
        self.assertEqual('', self._row('nowhere:x', execution='cloud').hosting)


class FilterBarForMeTest(TestCase):
    """The catalogue list says, for the user who reads it, which models his profile OPENS and
    which the automatic draw may take — read from the common admission rule, never re-derived
    (2026-10-16, « Pour moi » filter of the model manager)."""

    def setUp(self):
        for key, execution in (('imager:x', 'local'), ('albert:a', 'cloud'),
                               ('openrouter:paid', 'cloud'), ('anthropic:closed', 'cloud')):
            AIModel.objects.create(model_key=key, name=key, model_type='llm',
                                   source=key.split(':')[0], execution=execution,
                                   is_available=True)
        self.user = get_user_model().objects.create_user('filter_bar_reader', password='x')
        self.client.force_login(self.user)

    def _rows(self):
        with mock.patch('wama.model_manager.services.cloud_models.allowed_cloud_keys',
                        side_effect=lambda user, automatic=True:
                        {'albert:a'} if automatic else {'albert:a', 'openrouter:paid'}) as rule:
            rows = self.client.get('/model-manager/api/models/db/').json()['models']
        self.assertEqual({self.user.pk}, {c.args[0].pk for c in rule.call_args_list})
        return {r['model_key']: (r['open_to_me'], r['drawn_for_me']) for r in rows}

    def test_a_paid_model_is_open_by_hand_but_not_drawn(self):
        rows = self._rows()
        self.assertEqual((True, True), rows['albert:a'])
        self.assertEqual((True, False), rows['openrouter:paid'])

    def test_a_remote_model_beyond_the_profile_is_neither_open_nor_drawn(self):
        self.assertEqual((False, False), self._rows()['anthropic:closed'])

    def test_a_local_model_is_always_open(self):
        self.assertEqual((True, True), self._rows()['imager:x'])

    def test_a_list_without_remote_models_does_not_ask_the_rule(self):
        # The app selectors read this API on every page (`?source=`): the rule is not paid there.
        with mock.patch('wama.model_manager.services.cloud_models.allowed_cloud_keys') as rule:
            rows = self.client.get('/model-manager/api/models/db/?source=imager').json()['models']
        rule.assert_not_called()
        self.assertEqual([(True, True)], [(r['open_to_me'], r['drawn_for_me']) for r in rows])

    def test_the_bar_offers_the_rings_and_costs_of_the_registry(self):
        from wama.common import external_sources
        admin = get_user_model().objects.create_superuser('filter_bar_admin', password='x')
        self.client.force_login(admin)
        page = self.client.get('/model-manager/')
        self.assertEqual(200, page.status_code)
        html = page.content.decode()
        for label in (external_sources.LOCAL_ORIGIN_LABEL,
                      *external_sources.CLOUD_ORIGIN_LABELS.values()):
            self.assertIn(f'>{label}</option>', html)
        for key, _label in external_sources.COST_TIERS:
            self.assertIn(f'<option value="{key}">', html)
        self.assertIn('id="filter-mine"', html)


class OpenRouterListingTest(TestCase):
    """OpenRouter (2026-10-10): its list publishes no `type` but the MODALITIES of each model, and
    the repository it serves for open models. Shape fixed from the real `GET /api/v1/models`."""

    LISTING = [
        {'id': 'meta-llama/llama-3.3-70b-instruct:free', 'name': 'Llama 3.3 70B (free)',
         'architecture': {'input_modalities': ['text'], 'output_modalities': ['text']},
         'pricing': {'prompt': '0', 'completion': '0'},
         'hugging_face_id': 'meta-llama/Llama-3.3-70B-Instruct'},
        {'id': 'google/gemini-x', 'name': 'Gemini X',
         'architecture': {'input_modalities': ['text', 'image', 'file'],
                          'output_modalities': ['text']},
         'pricing': {'prompt': '0.0000003', 'completion': '0.0000025'}, 'hugging_face_id': ''},
        {'id': 'google/gemini-x-image', 'name': 'Gemini X Image',
         'architecture': {'input_modalities': ['image', 'text'],
                          'output_modalities': ['image', 'text']},
         'pricing': {'prompt': '0.0000003', 'completion': '0.0000025'}},
    ]

    def _list(self):
        response = mock.Mock(status_code=200, ok=True,
                             json=mock.Mock(return_value={'data': self.LISTING}))
        with mock.patch('requests.get', return_value=response) as get:
            models = cloud_models.list_remote_models('openrouter', 'secret')
        return get, {m['id']: m for m in models}

    def test_the_modalities_give_the_type(self):
        get, models = self._list()
        self.assertEqual('Bearer secret', get.call_args.kwargs['headers']['Authorization'])
        self.assertEqual('text-generation', models['meta-llama/llama-3.3-70b-instruct:free']['type'])
        self.assertEqual('image-text-to-text', models['google/gemini-x']['type'])

    def test_a_model_that_answers_with_an_image_does_not_enter_the_catalogue(self):
        # No engine runs it through `llm_chat`: filed as `text-to-image`, the imager would offer it.
        _, models = self._list()
        self.assertEqual('', models['google/gemini-x-image']['type'])
        self.assertIsNone(cloud_models.model_info_for('openrouter', models['google/gemini-x-image']))

    def test_the_served_repository_and_the_free_price_are_kept(self):
        _, models = self._list()
        free = models['meta-llama/llama-3.3-70b-instruct:free']
        self.assertEqual(['meta-llama/Llama-3.3-70B-Instruct'], free['aliases'])
        info = cloud_models.model_info_for('openrouter', free)
        self.assertEqual(('free', 'meta-llama/Llama-3.3-70B-Instruct'), (info.cost_tier, info.hf_id))
        paid = cloud_models.model_info_for('openrouter', models['google/gemini-x'])
        # Counter-check: an id with a « / » is not a repository, and a paid model keeps the
        # source's tier.
        self.assertEqual(('metered', None), (paid.cost_tier, paid.hf_id))

    def test_a_listing_without_modalities_still_reads_its_type(self):
        # Counter-check: Albert's shape (a `type`, no `architecture`) is unchanged.
        response = mock.Mock(status_code=200, ok=True, json=mock.Mock(return_value={'data': [
            {'id': 'bge-m3', 'type': 'text-embeddings-inference', 'aliases': ['BAAI/bge-m3']}]}))
        with mock.patch('requests.get', return_value=response):
            model, = cloud_models.list_remote_models('albert', 'secret')
        self.assertEqual(('text-embeddings-inference', ['BAAI/bge-m3']),
                         (model['type'], model['aliases']))
        self.assertNotIn('cost_tier', model)
