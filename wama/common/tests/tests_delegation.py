"""
La DÉLÉGATION — l'assistant confie une tâche à un sous-agent (`WAMA_HARNESS §7.4` étape 2,
2026-10-29).

CE QUE CETTE GARDE TIENT :
  1. `delegate` est un verbe de la BOUCLE, pas un outil du registre : MCP et `/api/v1/tools/` ne
     peuvent pas le servir ;
  2. il n'est annoncé (prompt et déclaration native) qu'à un tour qui peut l'exécuter : demandé
     (`can_delegate`), sous la profondeur maximale, hors abonnement ;
  3. le sous-agent est un tour de la même boucle : contexte neuf, profondeur 1 (lecture seule),
     ses propres bornes, même fournisseur et même modèle ;
  4. le parent ne lit que le RAPPORT — les résultats d'outils du sous-agent vont à la trace
     (`sub_steps`), jamais au modèle du parent — et l'usage s'additionne ;
  5. (étape 3) l'interrupteur est un réglage déclaré de l'assistant, éteint par défaut, que
     `conversation_turn` lit pour toutes les surfaces ; le nombre de sous-agents d'un tour est
     plafonné ; la trace dit la durée de chacun.
"""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from wama.common.services import assistant_engine
from wama.common.services.assistant_engine import (
    _SUB_AGENT_BRIEF, DELEGATE_TOOL, SUB_AGENT_MAX_ITERATIONS, SUB_AGENT_SECONDS,
)

DELEGATE = '{"tool": "delegate", "args": {"task": "Trouve la date de la conférence X", "domain": "investigation"}}'
SEARCH = '{"tool": "search_web", "args": {"query": "conférence X"}}'
SUB_RESULT = {'results': [{'url': 'https://example.org/x', 'snippet': 'SUB_RESULT_BODY'}]}


def _is_sub_agent(messages) -> bool:
    return any(str(m.get('content', '')).startswith(_SUB_AGENT_BRIEF) for m in messages)


def _turn(*, parent=(DELEGATE,), sub=(SEARCH,), **kwargs):
    """Un tour où le parent appelle `parent` puis répond, et le sous-agent appelle `sub` puis rend
    son rapport. Rend (résultat, messages vus par appel avec leur agent, outils exécutés)."""
    seen, executed, counts = [], [], {'parent': 0, 'sub': 0}

    def llm(messages, llm_model, *a, **k):
        agent = 'sub' if _is_sub_agent(messages) else 'parent'
        seen.append((agent, [dict(m) for m in messages], k))
        script = sub if agent == 'sub' else parent
        index = counts[agent]
        counts[agent] += 1
        if index < len(script):
            return script[index], {'input_tokens': 10, 'output_tokens': 1}
        answer = ('Rapport : la conférence a lieu le 3 mars, https://example.org/x'
                  if agent == 'sub' else 'Réponse finale.')
        return answer, {'input_tokens': 10, 'output_tokens': 1}

    def run(name, args, user):
        executed.append(name)
        return SUB_RESULT

    user = User.objects.create(username=f'delegation_{User.objects.count()}')
    with mock.patch.object(assistant_engine, '_llm_call', side_effect=llm), \
            mock.patch('wama.tool_api.execute_tool', side_effect=run):
        result = assistant_engine.run_assistant_turn(user, 'Quand a lieu la conférence X ?',
                                                     provider='ollama', model='m', **kwargs)
    return result, seen, executed


def _system(seen, agent='parent') -> str:
    return next(messages for who, messages, _ in seen if who == agent)[0]['content']


class DelegateIsALoopVerbTest(TestCase):

    def test_it_is_not_in_the_registry_served_by_mcp_and_the_api(self):
        from wama.tool_api import TOOL_REGISTRY
        self.assertNotIn(DELEGATE_TOOL, TOOL_REGISTRY)

    def test_it_is_off_by_default(self):
        with mock.patch.object(assistant_engine, '_delegate') as delegate:
            _, seen, _ = _turn()
        delegate.assert_not_called()
        self.assertNotIn('- delegate(', _system(seen))

    def test_a_sub_agent_cannot_delegate_again(self):
        _, seen, _ = _turn(parent=(), depth=1, can_delegate=True)
        self.assertNotIn('- delegate(', _system(seen))

    def test_it_is_not_offered_on_the_subscription(self):
        user = User.objects.create(username='delegation_abo')
        with mock.patch('wama.common.services.claude_code.subscription_allowed', return_value=True), \
                mock.patch.object(assistant_engine, '_llm_call', return_value=('ok', {})) as llm:
            assistant_engine.run_assistant_turn(user, 'q', provider='claude-abo', can_delegate=True)
        self.assertNotIn('- delegate(', llm.call_args.args[0][0]['content'])

    def test_the_native_declaration_carries_it(self):
        declared = [{'type': 'function', 'function': {'name': 'search_docs'}}]
        with mock.patch.object(assistant_engine, '_native_tool_specs', return_value=declared):
            _, seen, _ = _turn(parent=(), can_delegate=True)
        names = [spec['function']['name'] for spec in seen[0][2]['tools']]
        self.assertEqual(['search_docs', DELEGATE_TOOL], names)


class SubAgentRunTest(TestCase):

    def setUp(self):
        self.result, self.seen, self.executed = _turn(can_delegate=True)

    def test_the_parent_reads_the_report_and_nothing_else(self):
        last_parent = [messages for who, messages, _ in self.seen if who == 'parent'][-1]
        tool_message = last_parent[-1]['content']
        self.assertIn('Rapport : la conférence a lieu le 3 mars', tool_message)
        self.assertNotIn('SUB_RESULT_BODY', tool_message)
        self.assertEqual('Réponse finale.', self.result['response'])

    def test_the_sub_agent_starts_fresh_and_read_only(self):
        sub_messages = next(messages for who, messages, _ in self.seen if who == 'sub')
        self.assertEqual(2, len(sub_messages))                     # système + tâche : pas d'historique
        self.assertNotIn('Quand a lieu la conférence X', sub_messages[1]['content'])
        system = sub_messages[0]['content']
        self.assertIn('- search_web(', system)
        self.assertNotIn('- delete_item(', system)
        self.assertNotIn('- delegate(', system)

    def test_the_trace_keeps_the_sub_agent_steps(self):
        step = self.result['tool_steps'][0]
        self.assertEqual(DELEGATE_TOOL, step['tool'])
        agent = step['sub_agents'][0]
        self.assertEqual(['search_web'], [s['tool'] for s in agent['steps']])
        self.assertEqual(SUB_RESULT, agent['steps'][0]['result'])
        self.assertEqual('Trouve la date de la conférence X', agent['task'])
        self.assertEqual(['search_web'], self.executed)

    def test_the_usage_adds_up(self):
        # Parent : 2 appels ; sous-agent : 2 appels — 10 jetons d'entrée chacun.
        self.assertEqual(40, self.result['usage']['input_tokens'])

    def test_a_link_found_by_the_sub_agent_can_be_cited(self):
        result, _, _ = _turn(can_delegate=True)
        self.assertNotIn('retiré', result['tool_steps'][0]['result']['reports'][0]['report'])


class GuardrailsTest(TestCase):
    """Étape 3 : l'interrupteur déclaré, le plafond d'appels, le journal."""

    def _conversation_turn(self, settings):
        user = User.objects.create(username=f'delegation_switch_{User.objects.count()}')
        with mock.patch.object(assistant_engine, 'assistant_settings', return_value=settings), \
                mock.patch.object(assistant_engine, 'run_assistant_turn',
                                  return_value={'success': True, 'response': 'r'}) as turn:
            assistant_engine.conversation_turn(user, 'q', surface='api')
        return turn.call_args.kwargs['can_delegate']

    def test_the_switch_is_a_declared_setting_off_by_default(self):
        from wama.assistant.params import PARAMS, USER_SETTINGS_DEFAULTS
        self.assertIn('sub_agents', {p.name for p in PARAMS})
        self.assertIs(False, USER_SETTINGS_DEFAULTS['sub_agents'])

    def test_the_switch_drives_the_delegation_on_every_surface(self):
        self.assertIs(False, self._conversation_turn({}))
        self.assertIs(True, self._conversation_turn({'sub_agents': True}))

    def test_the_switch_is_served_and_saved_both_ways(self):
        """Sur la PAGE servie (le schéma du volet de l'accueil) et par la route de réglage, que la
        modale ⚙ poste en formulaire — `false` compris, sinon on ne pourrait plus l'éteindre."""
        from django.urls import reverse

        from wama.assistant.params import PARAMS_JSON, SURFACES
        switch = next(p for p in PARAMS_JSON if p['name'] == 'sub_agents')
        self.assertEqual(list(SURFACES), list(switch['contexts']))       # volet ET modale ⚙
        user = User.objects.create(username='delegation_page')
        self.client.force_login(user)
        self.assertIn('ai-sub-agents', self.client.get(reverse('home')).content.decode())
        for posted, expected in (('true', True), ('false', False)):
            self.assertEqual(200, self.client.post(reverse('ai_chat_settings'),
                                                   {'sub_agents': posted}).status_code)
            self.assertIs(expected, assistant_engine.assistant_settings(user)['sub_agents'])

    def test_the_number_of_sub_agents_per_turn_is_capped(self):
        from wama.common.services.assistant_engine import MAX_DELEGATIONS_PER_TURN
        calls = MAX_DELEGATIONS_PER_TURN + 1
        with mock.patch.object(assistant_engine, '_delegate',
                               return_value=({'report': 'r'}, [], {})) as delegate:
            result, _, _ = _turn(parent=(DELEGATE,) * calls, can_delegate=True)
        self.assertEqual(MAX_DELEGATIONS_PER_TURN, delegate.call_count)
        self.assertIn('Plafond', result['tool_steps'][-1]['result']['error'])

    def test_the_trace_says_how_long_each_sub_agent_took(self):
        result, _, _ = _turn(can_delegate=True)
        self.assertIsInstance(result['tool_steps'][0]['sub_agents'][0]['seconds'], float)


class ParallelWaveTest(TestCase):
    """Étape 2 bis : un couloir par SERVEUR, tiré par le tirage commun ; les couloirs tournent en
    même temps, les tâches d'un couloir l'une après l'autre ; le plafond compte des sous-agents."""

    LOT = ['ollama:a', 'ollama:b', 'claude_code:opus', 'albert:x', 'albert:y', 'ilaas:z']

    def _lanes(self, lot, count, provider='ollama', model='a'):
        user = User.objects.create(username=f'wave_lanes_{User.objects.count()}')
        with mock.patch('wama.common.services.development_models.agent_candidates',
                        return_value=lot), \
                mock.patch('wama.model_manager.services.cloud_models.allowed_cloud_keys',
                           return_value=set()), \
                mock.patch('wama.common.utils.auto_model.resolve_model_choice',
                           side_effect=lambda *a, candidates, **k: candidates[0]):
            return assistant_engine._sub_agent_lanes(user, provider, model, count)

    def test_one_lane_per_server_drawn_without_the_subscription(self):
        self.assertEqual([('ollama', 'a'), ('albert', 'x'), ('ilaas', 'z')],
                         self._lanes(self.LOT, 5))
        self.assertEqual([('ollama', 'a'), ('albert', 'x')], self._lanes(self.LOT, 2))

    def test_a_local_only_profile_has_a_single_lane(self):
        self.assertEqual([('ollama', 'a')], self._lanes(['ollama:a', 'ollama:b'], 3))

    def _wave(self, tasks, lanes, delegate, budget=3):
        user = User.objects.create(username=f'wave_{User.objects.count()}')
        with mock.patch.object(assistant_engine, '_sub_agent_lanes', return_value=lanes), \
                mock.patch.object(assistant_engine, '_delegate', side_effect=delegate):
            return assistant_engine._delegate_wave(
                user, {'tasks': tasks}, provider='ollama', llm_model='a', depth=0, deadline=None,
                budget=budget)

    def test_the_lanes_run_at_the_same_time_each_on_its_server(self):
        import threading
        barrier = threading.Barrier(3, timeout=10)      # séquentiel : la barrière casse
        served = {}

        def delegate(user, task_args, *, provider, llm_model, depth, deadline):
            barrier.wait()
            served[task_args['task']] = provider
            return {'report': f"rapport {task_args['task']}", 'model': provider}, [], {}

        result, trace, _ = self._wave(['t1', 't2', 't3'],
                                      [('ollama', 'a'), ('albert', 'x'), ('ilaas', 'z')], delegate)
        self.assertNotIn('error', result)
        self.assertEqual(['rapport t1', 'rapport t2', 'rapport t3'],
                         [r['report'] for r in result['reports']])
        self.assertEqual({'t1': 'ollama', 't2': 'albert', 't3': 'ilaas'}, served)
        self.assertEqual(['t1', 't2', 't3'], [agent['task'] for agent in trace])

    def test_tasks_share_a_lane_one_after_the_other(self):
        order = []

        def delegate(user, task_args, *, provider, **k):
            order.append((task_args['task'], provider))
            return {'report': 'r'}, [], {}

        self._wave(['t1', 't2', 't3'], [('ollama', 'a')], delegate)
        self.assertEqual([('t1', 'ollama'), ('t2', 'ollama'), ('t3', 'ollama')], order)

    def test_tasks_beyond_the_budget_do_not_run(self):
        delegate = mock.Mock(return_value=({'report': 'r'}, [], {}))
        result, trace, _ = self._wave(['t1', 't2', 't3'], [('ollama', 'a')], delegate, budget=2)
        self.assertEqual(2, delegate.call_count)
        self.assertEqual(2, len(trace))
        self.assertIn('Plafond', result['not_run'])

    def test_a_failing_sub_agent_does_not_bring_the_turn_down(self):
        def delegate(user, task_args, **k):
            if task_args['task'] == 't2':
                raise RuntimeError('panne')
            return {'report': 'r'}, [], {}

        result, _, _ = self._wave(['t1', 't2'], [('ollama', 'a'), ('albert', 'x')], delegate)
        self.assertNotIn('error', result)
        self.assertIn('panne', result['reports'][1]['error'])

    def test_the_tool_announces_the_parallel_form(self):
        line, spec = assistant_engine._delegate_tool()
        self.assertIn('tasks', line)
        self.assertEqual('array', spec['function']['parameters']['properties']['tasks']['type'])

    def test_the_cap_counts_sub_agents_not_calls(self):
        two = '{"tool": "delegate", "args": {"tasks": [{"task": "a"}, {"task": "b"}]}}'
        with mock.patch.object(assistant_engine, '_sub_agent_lanes',
                               side_effect=lambda user, provider, model, count: [(provider, model)]), \
                mock.patch.object(assistant_engine, '_delegate',
                                  return_value=({'report': 'r'}, [], {})) as delegate:
            result, _, _ = _turn(parent=(two, two), can_delegate=True)
        self.assertEqual(3, delegate.call_count)                    # 2 + 1 : le plafond est 3
        steps = result['tool_steps']
        self.assertEqual([2, 1], [len(step['sub_agents']) for step in steps])
        self.assertIn('Plafond', steps[1]['result']['not_run'])


class DelegateCallTest(TestCase):

    def _delegate(self, args, deadline=None):
        user = User.objects.create(username=f'delegation_call_{User.objects.count()}')
        with mock.patch.object(assistant_engine, 'run_assistant_turn',
                               return_value={'success': True, 'response': 'r', 'tool_steps': []}) as sub:
            result = assistant_engine._delegate(user, args, provider='albert', llm_model='gpt-oss',
                                                depth=0, deadline=deadline)
        return result, sub

    def test_the_sub_agent_gets_its_own_bounds_and_the_parent_model(self):
        _, sub = self._delegate({'task': 't', 'domain': 'investigation'})
        kwargs = sub.call_args.kwargs
        self.assertEqual(('albert', 'gpt-oss'), (kwargs['provider'], kwargs['model']))
        self.assertEqual((1, SUB_AGENT_MAX_ITERATIONS, []),
                         (kwargs['depth'], kwargs['max_iterations'], kwargs['history']))
        self.assertEqual('investigation', kwargs['domain'])

    def test_the_parent_deadline_bounds_the_sub_agent(self):
        _, sub = self._delegate({'task': 't'}, deadline=0.0)
        self.assertEqual(0.0, sub.call_args.kwargs['deadline'])
        _, sub = self._delegate({'task': 't'})
        self.assertGreater(sub.call_args.kwargs['deadline'], SUB_AGENT_SECONDS / 2)

    def test_a_development_domain_falls_back_to_the_default(self):
        _, sub = self._delegate({'task': 't', 'domain': 'dev'})
        self.assertIsNone(sub.call_args.kwargs['domain'])

    def test_a_missing_task_runs_nothing(self):
        (result, _, _), sub = self._delegate({'domain': 'science'})
        self.assertIn('task', result['error'])
        sub.assert_not_called()
