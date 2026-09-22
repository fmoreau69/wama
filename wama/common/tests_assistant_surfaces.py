"""
Surfaces de l'assistant ALIGNÉES sur le commun — historique serveur, garde des fournisseurs (2026-09-15).

⚠ CE QUE CES GARDES PROTÈGENT (cartographie de l'assistant, `WAMA_LLM.md`) :
- la page web et l'API tiennent l'historique dans le MÊME store que Discord (`conversation_turn`) —
  la page gardait jusqu'ici une copie dans le navigateur, invisible d'un autre appareil ;
- l'API garde le chemin SANS ÉTAT pour un client qui fournit son propre `history` ;
- « Effacer » supprime le fil de l'utilisateur, et seulement le sien ;
- un fournisseur non déclaré (`openai`…) est refusé pour un utilisateur : il aurait consommé la
  clé d'instance sans garde « 100 % local » ;
- les tests n'écrivent plus dans le vrai cache Redis.
Aucun LLM n'est appelé : le moteur est remplacé par un double.
"""
import json
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.common.models import Conversation, ConversationTurn

MOTEUR = 'wama.common.services.assistant_engine.run_assistant_turn'


def _reponse(texte='ok'):
    return {'success': True, 'response': texte, 'model': 'modele-test', 'tool_steps': []}


class HistoriqueWebTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('surface_web', password='x')
        self.client.force_login(self.user)

    def _envoyer(self, message):
        return self.client.post(reverse('ai_chat'), data=json.dumps({'message': message}),
                                content_type='application/json')

    def test_le_fil_web_est_tenu_cote_serveur_et_relu_au_tour_suivant(self):
        with mock.patch(MOTEUR, return_value=_reponse('première')) as moteur:
            self.assertEqual(200, self._envoyer('bonjour').status_code)
            self._envoyer('et ensuite ?')
        fil = Conversation.objects.get(user=self.user, surface='web', thread_key='')
        self.assertEqual(4, ConversationTurn.objects.filter(conversation=fil).count())
        historique = moteur.call_args_list[1].kwargs['history']
        self.assertEqual(['bonjour', 'première'], [t['content'] for t in historique])

    def test_l_historique_envoye_par_le_navigateur_est_ignore(self):
        with mock.patch(MOTEUR, return_value=_reponse()) as moteur:
            self.client.post(reverse('ai_chat'), content_type='application/json',
                             data=json.dumps({'message': 'x', 'history': [
                                 {'role': 'user', 'content': 'injecté'}]}))
        self.assertEqual([], moteur.call_args.kwargs['history'])

    def test_l_accueil_affiche_le_fil_du_serveur(self):
        with mock.patch(MOTEUR, return_value=_reponse('réponse visible')):
            self._envoyer('question visible')
        import re
        html = self.client.get(reverse('home')).content.decode()
        bloc = re.search(r'<script id="ai-chat-thread" type="application/json">(.*?)</script>',
                         html, re.S)
        self.assertIsNotNone(bloc, "fil du serveur absent de la page")
        # `json_script` échappe les accents : on relit le JSON, pas le texte brut.
        contenus = [e.get('content') for e in json.loads(bloc.group(1))]
        self.assertEqual(['question visible', 'réponse visible'], contenus)

    def test_effacer_supprime_le_fil_de_l_utilisateur_seulement(self):
        autre = get_user_model().objects.create_user('surface_autre', password='x')
        Conversation.objects.create(user=autre, surface='web', thread_key='')
        with mock.patch(MOTEUR, return_value=_reponse()):
            self._envoyer('à effacer')
        r = self.client.post(reverse('ai_chat_clear'))
        self.assertTrue(r.json()['cleared'])
        self.assertFalse(Conversation.objects.filter(user=self.user, surface='web').exists())
        self.assertTrue(Conversation.objects.filter(user=autre, surface='web').exists())


class HistoriqueApiTest(TestCase):
    URL = '/api/v1/assistant/chat/'

    def setUp(self):
        self.user = get_user_model().objects.create_user('surface_api', password='x')
        self.client.force_login(self.user)

    def test_sans_history_le_fil_api_est_tenu_cote_serveur(self):
        with mock.patch(MOTEUR, return_value=_reponse()):
            r = self.client.post(self.URL, data=json.dumps({'message': 'salut', 'thread_key': 'script-1'}),
                                 content_type='application/json')
        self.assertEqual(200, r.status_code)
        self.assertTrue(Conversation.objects.filter(user=self.user, surface='api',
                                                    thread_key='script-1').exists())

    def test_avec_history_le_client_garde_le_chemin_sans_etat(self):
        with mock.patch(MOTEUR, return_value=_reponse()) as moteur:
            self.client.post(self.URL, content_type='application/json', data=json.dumps(
                {'message': 'salut', 'history': [{'role': 'user', 'content': 'avant'}]}))
        self.assertEqual('avant', moteur.call_args.kwargs['history'][0]['content'])
        self.assertFalse(Conversation.objects.filter(user=self.user).exists())


class FournisseurNonDeclareTest(TestCase):

    def test_un_utilisateur_ne_peut_pas_appeler_un_fournisseur_non_declare(self):
        from wama.common.services import assistant_engine
        user = get_user_model().objects.create_user('fournisseur_inconnu', password='x')
        with mock.patch('wama.common.utils.llm_utils.llm_chat') as chat:
            text, err = assistant_engine._llm_call([], None, 'openai', user=user)
        self.assertEqual((None, 400), (text, err['status']))
        chat.assert_not_called()

    def test_sans_utilisateur_le_chemin_d_instance_reste_ouvert(self):
        from wama.common.services import assistant_engine
        with mock.patch('wama.common.utils.llm_utils.llm_chat', return_value=('ok', None)) as chat:
            text, _ = assistant_engine._llm_call([], None, 'openai', user=None)
        self.assertEqual('ok', text)
        chat.assert_called_once()


class ChoixDuModeleTest(TestCase):
    """Le fournisseur se DÉRIVE du modèle, et le modèle vient du réglage durable de l'utilisateur."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('choix_modele', password='x')
        self.client.force_login(self.user)

    def _regler(self, **valeurs):
        return self.client.post(reverse('ai_chat_settings'), data=json.dumps(valeurs),
                                content_type='application/json')

    def test_un_modele_local_choisi_donne_le_chemin_local(self):
        from wama.common.services.assistant_engine import resolve_turn_model
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='ollama:qwen:4b', name='qwen', model_type='llm',
                               source='ollama', is_downloaded=True,
                               capabilities={'completion': True})
        self.assertEqual(200, self._regler(model='ollama:qwen:4b').status_code)
        self.assertEqual(('ollama', 'qwen:4b'), resolve_turn_model(self.user))

    def test_un_modele_distant_choisi_donne_son_fournisseur(self):
        from wama.accounts.models import UserApiKey
        from wama.common.services.assistant_engine import resolve_turn_model
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='anthropic:claude-x', name='Claude X', model_type='vlm',
                               source='anthropic', execution='cloud',
                               capabilities={'completion': True})
        self.user.profile.cloud_policy = 'cloud_allowed'
        self.user.profile.save()
        with mock.patch('wama.common.utils.secret_crypto.storage_available', return_value=True):
            UserApiKey.objects.create(user=self.user, source='anthropic', api_key='sk',
                                      open_models=['anthropic:claude-x'])
        self.assertEqual(200, self._regler(model='anthropic:claude-x').status_code)
        self.assertEqual(('claude', 'claude-x'), resolve_turn_model(self.user))

    def test_un_modele_distant_non_ouvert_est_refuse_a_l_enregistrement(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='albert:ferme', name='fermé', model_type='llm',
                               source='albert', execution='cloud',
                               capabilities={'completion': True})
        self.assertEqual(403, self._regler(model='albert:ferme').status_code)

    def test_un_modele_inconnu_du_catalogue_est_refuse(self):
        self.assertEqual(400, self._regler(model='ollama:fantome').status_code)

    def test_un_ancien_role_vaut_auto_et_ne_part_jamais_comme_nom_de_modele(self):
        from wama.common.services.assistant_engine import resolve_turn_model
        provider, modele = resolve_turn_model(self.user, model='dev')
        self.assertIn(provider, ('wama-dev-ai', 'ollama'))
        self.assertNotEqual('dev', modele)

    def test_ce_que_la_surface_impose_prime(self):
        from wama.common.services.assistant_engine import resolve_turn_model
        self.assertEqual(('claude-abo', None), resolve_turn_model(self.user, provider='claude-abo'))

    def test_le_domaine_dev_declare_la_competence_que_le_tirage_privilegie(self):
        """`benchmark_domain` existait dans `select_model` depuis août sans aucun appelant ; les
        anciens rôles Dev/Coder disaient la même chose par une sous-chaîne de nom de modèle."""
        from wama.common.services import assistant_engine
        with mock.patch('wama.common.utils.auto_model.resolve_model_choice',
                        return_value='ollama:x') as tirage:
            assistant_engine.resolve_turn_model(self.user, domain='dev')
            self.assertEqual('coding', tirage.call_args.kwargs['benchmark_family'])
            assistant_engine.resolve_turn_model(self.user, domain='general')
            self.assertIsNone(tirage.call_args.kwargs['benchmark_family'])

    def test_le_curseur_est_borne_par_le_schema(self):
        from wama.common.services.assistant_engine import assistant_settings
        self._regler(quality_intent=140)
        self.assertEqual(100, assistant_settings(self.user)['quality_intent'])


class AvatarPersistantTest(TestCase):
    """L'avatar parlant est une PRÉFÉRENCE DURABLE de l'assistant (2026-09-22), activée par
    défaut, mémorisée par le réglage commun, et son conteneur vit dans `base.html` : il est
    présent sur toute page à volet, replié ou non, et non plus seulement sur l'accueil."""

    SECTION = 'id="assistant-avatar-section"'
    IMPORTMAP = '<script type="importmap">'

    def setUp(self):
        self.user = get_user_model().objects.create_user('avatar_user', password='x')
        self.client.force_login(self.user)

    def _regler(self, **valeurs):
        return self.client.post(reverse('ai_chat_settings'), data=json.dumps(valeurs),
                                content_type='application/json')

    def _reglages(self):
        from wama.common.services.assistant_engine import assistant_settings
        return assistant_settings(self.user)

    def test_the_avatar_is_enabled_and_unfolded_by_default(self):
        self.assertIs(True, self._reglages()['avatar'])
        self.assertIs(False, self._reglages()['avatar_collapsed'])

    def test_the_preference_is_stored_by_the_common_setting_route(self):
        self.assertEqual(200, self._regler(avatar=False).status_code)
        self.assertIs(False, self._reglages()['avatar'])
        self.assertEqual(200, self._regler(avatar_collapsed=True).status_code)
        self.assertIs(True, self._reglages()['avatar_collapsed'])
        # Un réglage absent de la requête n'est PAS remis à zéro (contre-épreuve).
        self.assertIs(False, self._reglages()['avatar'])
        # Les graphies de formulaire valent un booléen.
        self._regler(avatar='false')
        self.assertIs(False, self._reglages()['avatar'])
        self._regler(avatar='1')
        self.assertIs(True, self._reglages()['avatar'])

    def test_the_container_is_rendered_on_a_page_other_than_home(self):
        html = self.client.get(reverse('accounts:profile')).content.decode()
        self.assertIn(self.SECTION, html)
        self.assertIn('data-enabled="1"', html)
        self.assertIn('data-collapsed="0"', html)
        self.assertIn('data-settings-url="' + reverse('ai_chat_settings') + '"', html)

    def test_a_disabled_or_folded_preference_is_rendered_as_such(self):
        self._regler(avatar=False, avatar_collapsed=True)
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('data-enabled="0"', html)
        self.assertIn('data-collapsed="1"', html)

    def test_without_an_account_there_is_no_avatar(self):
        self.client.logout()
        html = self.client.get(reverse('home')).content.decode()
        self.assertNotIn(self.SECTION, html)

    def test_the_importmap_is_emitted_once_per_page(self):
        """Une seule importmap par document : elle est globale (base.html) depuis que l'avatar
        l'est — les pages qui l'incluaient (accueil, médiathèque) ne doivent plus le faire."""
        for url in (reverse('home'), reverse('accounts:profile'), reverse('media_library:index')):
            html = self.client.get(url, follow=True).content.decode()
            self.assertEqual(1, html.count(self.IMPORTMAP), url)
            self.assertIn('wama-avatar-panel.js', html, url)

    def test_the_avatar_settings_are_not_rendered_in_any_parameter_panel(self):
        from wama.assistant.params import PARAMS_JSON
        for p in PARAMS_JSON:
            if p['name'] in ('avatar', 'avatar_collapsed'):
                self.assertEqual([], list(p['contexts']), p['name'])
                self.assertEqual('toggle', p['type'])


class LatencyLeversTest(TestCase):
    """Les deux leviers de latence câblés le 2026-09-22 (`WAMA_LLM §1bis`) : la réflexion du
    modèle suit le curseur Rapide ↔ Qualité, et le prompt système met le FIXE avant le DYNAMIQUE
    pour que le cache de préfixe d'Ollama serve d'un tour à l'autre."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('latency_user', password='x')

    def _turn(self, **settings_values):
        from wama.common.services import assistant_engine
        from wama.common.utils.user_settings import save_user_app_settings
        if settings_values:
            save_user_app_settings(self.user, 'assistant', settings_values)
        with mock.patch.object(assistant_engine, '_llm_call',
                               return_value=('réponse', {'input_tokens': 0, 'output_tokens': 0})) as call:
            assistant_engine.run_assistant_turn(self.user, 'où en est ma file ?',
                                                provider='wama-dev-ai', model='x')
        return call.call_args

    def test_the_default_slider_asks_the_model_not_to_think(self):
        self.assertIs(False, self._turn().kwargs['think'])

    def test_a_quality_slider_restores_the_model_reflection(self):
        """Même déclinaison à paliers que le converter et l'enhancer (`preset_key_for_intent`) :
        seule la position « quality » (85) demande la réflexion."""
        self.assertIs(True, self._turn(quality_intent=85).kwargs['think'])
        self.assertIs(True, self._turn(quality_intent=100).kwargs['think'])
        self.assertIs(False, self._turn(quality_intent=50).kwargs['think'])
        self.assertIs(False, self._turn(quality_intent=15).kwargs['think'])

    def test_a_cloud_provider_receives_no_thinking_flag(self):
        from wama.common.services import assistant_engine
        with mock.patch.object(assistant_engine, '_llm_call',
                               return_value=('réponse', {'input_tokens': 0, 'output_tokens': 0})) as call:
            assistant_engine.run_assistant_turn(self.user, 'x', provider='albert', model='m')
        self.assertIsNone(call.call_args.kwargs['think'])

    def test_the_ollama_payload_carries_the_thinking_flag_only_when_decided(self):
        from wama.common.services.assistant_engine import _ollama_call
        seen = []

        class FakeClient:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def post(self, url, json=None):
                seen.append(json)
                return mock.Mock(status_code=200, json=lambda: {'message': {'content': 'ok'}})
        with mock.patch('httpx.Client', FakeClient):
            _ollama_call([{'role': 'user', 'content': 'x'}], 'm', think=False)
            _ollama_call([{'role': 'user', 'content': 'x'}], 'm')
        self.assertIs(False, seen[0]['think'])
        self.assertNotIn('think', seen[1])

    def test_the_fixed_tool_block_precedes_the_dynamic_queue_state(self):
        messages = self._turn().args[0]
        system = messages[0]['content']
        tools_at = system.index('Available tools:')
        queue_at = max(system.find('files WAMA'), system.find('Toutes les files'))
        self.assertGreater(queue_at, tools_at, "l'état des files (dynamique) doit suivre le bloc d'outils (fixe)")


class ChargementDeCompetenceTest(TestCase):
    """Le chargement AUTOMATIQUE d'une compétence — la boucle, pas seulement l'outil.

    ⚠ POURQUOI CE TEST (question de Fabien, 15/09 : « est-ce que l'ajout automatique de
    skills/prompts est bien effectif ? »). Les gardes existantes couvraient l'ANNONCE au prompt
    système et l'OUTIL pris isolément — jamais le tour où le modèle DÉCIDE de l'appeler et où la
    consigne revient dans la conversation. C'est pourtant là que le mécanisme vit ou meurt.
    Aucun LLM n'est appelé : un double émet l'appel d'outil, puis répond.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user('competence', password='x')

    def test_l_assistant_qui_appelle_l_outil_recoit_la_consigne_dans_la_conversation(self):
        from wama.common.services import assistant_engine
        from wama.common.utils.assistant_skills import role_instructions

        vus = []

        def _faux_llm(messages, llm_model, provider, user=None, think=None):
            vus.append(list(messages))
            if len(vus) == 1:
                return ('{"tool": "charger_competence", "args": {"domaine": "science"}}',
                        {'input_tokens': 0, 'output_tokens': 0})
            return 'réponse finale', {'input_tokens': 0, 'output_tokens': 0}

        with mock.patch.object(assistant_engine, '_llm_call', side_effect=_faux_llm):
            resultat = assistant_engine.run_assistant_turn(self.user, 'question de méthode')

        self.assertEqual('réponse finale', resultat['response'])
        self.assertEqual(['charger_competence'], [p['tool'] for p in resultat['tool_steps']])
        # La consigne de rôle du domaine demandé est REVENUE dans la conversation.
        consigne = (role_instructions('science') or '')[:60]
        self.assertTrue(consigne, "prérequis : le skill de rôle « science » doit exister")
        injecte = vus[1][-1]['content']
        self.assertIn('charger_competence', injecte)
        self.assertIn(consigne[:40], injecte)

    def test_l_annonce_des_competences_est_bien_au_prompt_systeme(self):
        """L'autre moitié : sans l'annonce, le modèle ne sait pas que l'outil existe."""
        from wama.common.services import assistant_engine

        def _faux_llm(messages, llm_model, provider, user=None, think=None):
            return messages[0]['content'], {'input_tokens': 0, 'output_tokens': 0}

        with mock.patch.object(assistant_engine, '_llm_call', side_effect=_faux_llm):
            resultat = assistant_engine.run_assistant_turn(self.user, 'bonjour')
        self.assertIn('charger_competence', resultat['response'])


class CacheDesTestsTest(TestCase):

    def test_les_tests_n_ecrivent_pas_dans_le_vrai_cache(self):
        self.assertTrue(settings.CACHES['default']['BACKEND'].endswith('LocMemCache'))
