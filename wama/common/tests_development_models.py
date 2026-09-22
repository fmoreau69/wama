"""
Le bridage « niveau développement » (2026-09-22, décision de Fabien après un test réel où le 4b
sans réflexion inventait des jumelles) — un seul domicile, `development_models`, lu par
l'assistant et par les rôles wama-dev-ai.

⚠ CE QUE CES GARDES PROTÈGENT :
  1. la règle est une MESURE (score coding du banc ≥ plancher) plus une déclaration explicite
     pour l'unique modèle non mesuré ; un petit modèle n'est jamais de niveau dev ;
  2. un choix manuel sous le plancher est REMPLACÉ, un choix au niveau est respecté ;
  3. les distants SOUVERAINS entrent au tirage dev dès « cloud si saturé », les tiers non ;
  4. en domaine dev l'assistant demande la réflexion et étiquette le tour « · dev » ; charger la
     compétence dev en cours de tour fait basculer la SUITE du tour ; le fil s'en souvient ;
  5. sans modèle de niveau dev : REFUS lisible, jamais un repli silencieux.
"""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.services import assistant_engine, development_models as dm
from wama.model_manager.models import AIModel

USAGE = {'input_tokens': 0, 'output_tokens': 0}


def _model(key, coding=None, execution='local', source='ollama', downloaded=True, vram=8.0):
    meta = {'family_scores': {'coding': coding}} if coding is not None else {}
    return AIModel.objects.create(model_key=key, name=key, model_type='llm', source=source,
                                  execution=execution, is_downloaded=downloaded, vram_gb=vram,
                                  capabilities={'completion': True}, benchmark_meta=meta)


class DevelopmentGradeTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('dev_grade', password='x')
        self.small = _model('ollama:small:4b', coding=22.6, vram=3.4)
        self.big = _model('ollama:big:8b', coding=58.2, vram=17.0)
        vram = mock.patch('wama.model_manager.services.model_selector.get_free_vram_gb',
                          return_value=24.0)
        vram.start()
        self.addCleanup(vram.stop)

    def test_the_floor_is_a_measure_and_the_unscored_exception_is_declared(self):
        self.assertTrue(dm.is_development_grade(self.big))
        self.assertFalse(dm.is_development_grade(self.small))
        unscored = _model('albert:gpt-oss-120b', execution='cloud', source='albert', downloaded=False, vram=0)
        other_unscored = _model('albert:mystery', execution='cloud', source='albert', downloaded=False, vram=0)
        self.assertTrue(dm.is_development_grade(unscored))
        self.assertFalse(dm.is_development_grade(other_unscored))

    def test_a_manual_choice_below_the_floor_is_replaced_and_one_at_the_floor_is_kept(self):
        self.assertEqual('ollama:big:8b', dm.development_model(self.user, requested='ollama:small:4b'))
        self.assertEqual('ollama:big:8b', dm.development_model(self.user, requested='ollama:big:8b'))
        self.assertEqual('ollama:big:8b', dm.development_model(self.user))

    def test_without_any_development_grade_model_there_is_no_fallback(self):
        self.big.delete()
        self.assertIsNone(dm.development_model(self.user))
        self.assertIn('niveau développement', dm.development_refusal(self.user))

    def test_sovereign_cloud_is_admitted_from_the_saturation_level_but_third_party_is_not(self):
        from wama.accounts.models import UserApiKey
        _model('albert:gpt-oss-120b', execution='cloud', source='albert', downloaded=False, vram=0)
        _model('anthropic:claude-x', coding=90, execution='cloud', source='anthropic', downloaded=False, vram=0)
        self.user.profile.cloud_policy = 'cloud_when_saturated'
        self.user.profile.save()
        with mock.patch('wama.common.utils.secret_crypto.storage_available', return_value=True):
            UserApiKey.objects.create(user=self.user, source='albert', api_key='k',
                                      open_models=['albert:gpt-oss-120b'])
            UserApiKey.objects.create(user=self.user, source='anthropic', api_key='k',
                                      open_models=['anthropic:claude-x'])
        keys = dm.dev_cloud_keys(self.user)
        self.assertIn('albert:gpt-oss-120b', keys)
        self.assertNotIn('anthropic:claude-x', keys)
        self.assertIn('albert:gpt-oss-120b', dm.development_candidates(self.user))
        # Contre-épreuve : « 100 % local » reste 100 % local.
        self.user.profile.cloud_policy = 'local_only'
        self.user.profile.save()
        self.assertEqual(set(), dm.dev_cloud_keys(get_user_model().objects.get(pk=self.user.pk)))


class AssistantDevelopmentBridleTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('dev_bridle', password='x')
        self.small = _model('ollama:small:4b', coding=22.6, vram=3.4)
        self.big = _model('ollama:big:8b', coding=58.2, vram=17.0)
        vram = mock.patch('wama.model_manager.services.model_selector.get_free_vram_gb',
                          return_value=24.0)
        vram.start()
        self.addCleanup(vram.stop)

    def _turn(self, llm, **kw):
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=llm) as call:
            result = assistant_engine.run_assistant_turn(self.user, 'améliore le reader', **kw)
        return result, call

    def test_the_dev_domain_takes_the_development_model_with_reflection_and_says_so(self):
        from wama.common.utils.user_settings import save_user_app_settings
        save_user_app_settings(self.user, 'assistant', {'model': 'ollama:small:4b', 'quality_intent': 15})
        result, call = self._turn(lambda *a, **k: ('ok', USAGE), domain='dev')
        self.assertEqual('big:8b', call.call_args.args[1])
        self.assertIs(True, call.call_args.kwargs['think'])
        self.assertTrue(result['model'].endswith('· dev'), result['model'])

    def test_a_general_turn_is_not_bridled(self):
        from wama.common.utils.user_settings import save_user_app_settings
        save_user_app_settings(self.user, 'assistant', {'model': 'ollama:small:4b', 'quality_intent': 15})
        result, call = self._turn(lambda *a, **k: ('ok', USAGE))
        self.assertEqual('small:4b', call.call_args.args[1])
        self.assertIs(False, call.call_args.kwargs['think'])
        self.assertNotIn('· dev', result['model'])

    def test_loading_the_dev_competence_switches_the_rest_of_the_turn(self):
        from wama.common.utils.user_settings import save_user_app_settings
        save_user_app_settings(self.user, 'assistant', {'model': 'ollama:small:4b'})

        def llm(messages, *a, **k):
            if len(messages) == 2:
                return ('{"tool": "charger_competence", "args": {"domaine": "dev"}}', USAGE)
            return 'suite', USAGE
        result, call = self._turn(llm)
        first, second = call.call_args_list
        self.assertEqual('small:4b', first.args[1])
        self.assertEqual('big:8b', second.args[1])
        self.assertIs(True, second.kwargs['think'])
        self.assertTrue(result['model'].endswith('· dev'))

    def test_the_thread_remembers_the_dev_domain_for_the_next_turn(self):
        from wama.common.services import conversation_store
        fil = conversation_store.thread(self.user, surface='web')
        conversation_store.record_exchange(fil, 'q', {
            'response': 'r', 'model': 'x',
            'tool_steps': [{'tool': 'charger_competence', 'args': {'domaine': 'dev'}, 'result': {}}]})
        self.assertEqual('dev', conversation_store.last_loaded_domain(fil))
        with mock.patch.object(assistant_engine, 'run_assistant_turn',
                               return_value={'success': True, 'response': 'r', 'model': 'm',
                                             'tool_steps': []}) as engine:
            assistant_engine.conversation_turn(self.user, 'et ensuite', surface='web')
        self.assertEqual('dev', engine.call_args.kwargs['domain'])
        # Contre-épreuve : un autre domaine chargé ne colle pas.
        fil2 = conversation_store.thread(self.user, surface='api')
        conversation_store.record_exchange(fil2, 'q', {
            'response': 'r', 'model': 'x',
            'tool_steps': [{'tool': 'charger_competence', 'args': {'domaine': 'science'}, 'result': {}}]})
        with mock.patch.object(assistant_engine, 'run_assistant_turn',
                               return_value={'success': True, 'response': 'r', 'model': 'm',
                                             'tool_steps': []}) as engine:
            assistant_engine.conversation_turn(self.user, 'et ensuite', surface='api')
        self.assertIsNone(engine.call_args.kwargs['domain'])

    def test_without_a_development_model_the_dev_turn_is_refused_legibly(self):
        self.big.delete()
        result, call = self._turn(lambda *a, **k: ('ok', USAGE), domain='dev')
        call.assert_not_called()
        self.assertEqual(503, result['status'])
        self.assertIn('niveau développement', result['error'])
