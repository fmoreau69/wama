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
import json
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
    #: Ce que le CATALOGUE déclare distant (`AIModel.execution`) — la règle lit lui, pas un nom.
    REMOTE = {'claude_code:opus', 'albert:x', 'albert:y', 'ilaas:z'}

    def _lanes(self, lot, count, provider='ollama', model='a', council=False):
        user = User.objects.create(username=f'wave_lanes_{User.objects.count()}')
        with mock.patch('wama.common.services.development_models.agent_candidates',
                        return_value=lot), \
                mock.patch('wama.model_manager.services.cloud_models.allowed_cloud_keys',
                           return_value=set()), \
                mock.patch('wama.model_manager.services.cloud_models.is_cloud_key',
                           side_effect=lambda key: key in self.REMOTE), \
                mock.patch('wama.common.utils.auto_model.resolve_model_choice',
                           side_effect=lambda *a, candidates, **k: candidates[0]):
            return assistant_engine._sub_agent_lanes(user, provider, model, count, council=council)

    def test_a_council_leaves_the_local_out_when_remotes_suffice(self):
        # Décision de Fabien (29/10) : le couloir local faisait toute la durée du council.
        self.assertEqual([('albert', 'x'), ('ilaas', 'z'), ('albert', 'y')],
                         self._lanes(self.LOT, 3, council=True))

    def test_a_council_takes_one_local_lane_only_when_remotes_run_out(self):
        self.assertEqual([('albert', 'x'), ('ollama', 'a')],
                         self._lanes(['ollama:a', 'ollama:b', 'albert:x'], 3, council=True))
        # Tour distant : son modèle d'abord, puis le local tiré quand plus aucun distant ne reste.
        self.assertEqual([('albert', 'x'), ('ollama', 'b')],
                         self._lanes(['ollama:b', 'albert:x'], 2, provider='albert', model='x',
                                     council=True))

    def test_local_or_remote_is_read_from_the_catalogue_not_from_a_server_name(self):
        # Un serveur distant déclaré `local` au catalogue ne compte pas comme distant.
        self.REMOTE = {'ilaas:z'}
        self.assertEqual([('ilaas', 'z'), ('ollama', 'a')],
                         self._lanes(['albert:x', 'ilaas:z'], 3, council=True))

    def test_independent_tasks_keep_their_local_lane(self):
        self.assertEqual([('ollama', 'a'), ('albert', 'x'), ('ilaas', 'z')],
                         self._lanes(self.LOT, 3, council=False))

    def test_one_lane_per_server_drawn_without_the_subscription(self):
        self.assertEqual([('ollama', 'a'), ('albert', 'x'), ('ilaas', 'z')],
                         self._lanes(self.LOT, 3))
        self.assertEqual([('ollama', 'a'), ('albert', 'x')], self._lanes(self.LOT, 2))

    def test_beyond_the_servers_another_remote_model_never_a_second_local(self):
        # Étape 4 : cinq agents sur trois serveurs — un autre modèle d'Albert, jamais `ollama:b`.
        self.assertEqual([('ollama', 'a'), ('albert', 'x'), ('ilaas', 'z'), ('albert', 'y')],
                         self._lanes(self.LOT, 5))

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
        from wama.common.services.assistant_engine import MAX_DELEGATIONS_PER_TURN
        many = MAX_DELEGATIONS_PER_TURN - 1
        call = json.dumps({'tool': 'delegate', 'args': {'tasks': [{'task': f't{i}'}
                                                                  for i in range(many)]}})
        with mock.patch.object(assistant_engine, '_sub_agent_lanes',
                               side_effect=lambda user, provider, model, count, **k: [(provider, model)]), \
                mock.patch.object(assistant_engine, '_delegate',
                                  return_value=({'report': 'r'}, [], {})) as delegate:
            result, _, _ = _turn(parent=(call, call), can_delegate=True)
        self.assertEqual(MAX_DELEGATIONS_PER_TURN, delegate.call_count)
        steps = result['tool_steps']
        self.assertEqual([many, 1], [len(step['sub_agents']) for step in steps])
        self.assertIn('Plafond', steps[1]['result']['not_run'])


class CouncilTest(TestCase):
    """Étape 4 : un council n'est pas un mode, c'est une COMPOSITION — des agents du registre (de 1
    à n, sur la même question), puis une façon de conclure : un vote déterministe ou un décideur."""

    def _wave(self, args, reports, budget=6, decider_answer='Synthèse.'):
        user = User.objects.create(username=f'council_{User.objects.count()}')
        lanes = [('ollama', 'a'), ('albert', 'x'), ('ilaas', 'z'), ('albert', 'y'), ('ilaas', 'w')]
        answers = iter(reports)

        def delegate(user, task_args, *, provider, llm_model, **k):
            self.asked.append(task_args)
            return {'report': next(answers), 'model': f'{provider}:{llm_model}'}, [], {}

        self.asked = []
        with mock.patch.object(assistant_engine, '_sub_agent_lanes',
                               side_effect=lambda user, provider, model, count, **k: lanes[:count]), \
                mock.patch.object(assistant_engine, '_delegate', side_effect=delegate), \
                mock.patch.object(assistant_engine, '_decider_lane',
                                  return_value=('ilaas', 'decider-model')) as decider_lane, \
                mock.patch.object(assistant_engine, 'run_assistant_turn',
                                  return_value={'success': True, 'response': decider_answer,
                                                'model': 'ilaas (decider-model)'}) as decider:
            result = assistant_engine._delegate_wave(user, args, provider='ollama', llm_model='a',
                                                     depth=0, deadline=None, budget=budget)
        return result, decider, decider_lane

    def test_the_same_question_goes_to_each_named_agent(self):
        self._wave({'task': 'Q ?', 'agents': ['science', 'critique', 'methodology']}, ['r'] * 3)
        self.assertEqual([('Q ?', 'science'), ('Q ?', 'critique'), ('Q ?', 'methodology')],
                         [(a['task'], a['domain']) for a in self.asked])

    def test_a_vote_is_counted_from_the_verdict_lines(self):
        (result, _, _), _, _ = self._wave(
            {'task': 'Q ?', 'agents': ['general'] * 3, 'decide': 'vote', 'options': ['oui', 'non']},
            ['bla\nVERDICT: oui', 'VERDICT : `Oui`', 'pour moi\nVERDICT: non'])
        decision = result['decision']
        self.assertEqual(({'oui': 2, 'non': 1}, 'oui', 0.67, 0),
                         (decision['counts'], decision['winner'], decision['agreement'],
                          decision['abstentions']))
        self.assertIn('VERDICT', self.asked[0]['task'])          # chaque votant sait quoi écrire

    def test_a_tie_or_an_off_list_answer_is_said_not_settled(self):
        (result, _, _), _, _ = self._wave(
            {'task': 'Q ?', 'agents': ['general'] * 3, 'decide': 'vote', 'options': ['oui', 'non']},
            ['VERDICT: oui', 'VERDICT: non', 'VERDICT: peut-être'])
        self.assertIsNone(result['decision']['winner'])
        self.assertEqual(1, result['decision']['abstentions'])

    def test_a_vote_needs_options_and_decide_has_two_modes(self):
        for args in ({'task': 'Q', 'agents': ['general'], 'decide': 'vote'},
                     {'task': 'Q', 'agents': ['general'], 'decide': 'juge'}):
            (result, trace, _), _, _ = self._wave(args, ['r'])
            self.assertIn('error', result)
            self.assertEqual([], self.asked)

    def test_the_decider_reads_anonymous_reports_without_tools(self):
        (result, trace, _), decider, decider_lane = self._wave(
            {'task': 'Q ?', 'agents': ['science', 'critique'], 'decide': 'synthesis'},
            ['avis UN', 'avis DEUX'])
        message, kwargs = decider.call_args.args[1], decider.call_args.kwargs
        self.assertIn('[A]', message)
        self.assertIn('avis UN', message)
        self.assertNotIn('albert', message)                         # aucun modèle nommé
        self.assertEqual((frozenset(), 1, 'ilaas', 'decider-model'),
                         (kwargs['allowed_tools'], kwargs['depth'], kwargs['provider'],
                          kwargs['model']))
        self.assertEqual({'ollama:a', 'albert:x'}, decider_lane.call_args.args[3])
        self.assertTrue(callable(kwargs['on_event']))                # en flux, lui aussi
        self.assertEqual('Synthèse.', result['decision']['text'])
        self.assertEqual('decider', trace[-1]['role'])
        self.assertEqual({0, 1}, set(trace[-1]['letters'].values()))

    def test_the_decider_takes_its_place_under_the_cap(self):
        (result, trace, _), _, _ = self._wave(
            {'task': 'Q ?', 'agents': ['general'] * 3, 'decide': 'synthesis'}, ['r'] * 3, budget=3)
        self.assertEqual(2, len(self.asked))
        self.assertEqual(3, len(trace))                             # deux avis + le décideur
        self.assertIn('Plafond', result['not_run'])

    def test_the_decider_is_drawn_outside_the_agents(self):
        user = User.objects.create(username='council_decider')
        with mock.patch.object(assistant_engine, '_sub_agent_candidates',
                               return_value=(['albert:x', 'ilaas:z', 'albert:y'], set())), \
                mock.patch('wama.common.utils.auto_model.resolve_model_choice',
                           side_effect=lambda *a, candidates, quality_intent, **k: candidates[0]):
            lane = assistant_engine._decider_lane(user, 'ollama', 'a', {'albert:x'})
        self.assertEqual(('ilaas', 'z'), lane)

    def test_review_mode_cross_ranks_then_the_decider_reads_the_ranking(self):
        """Le LLM Council de Karpathy : chaque agent classe les avis anonymes, le classement
        s'agrège, le décideur le lit."""
        from wama.common.services.assistant_engine import _REVIEW_BRIEF
        user = User.objects.create(username='council_review')
        lanes = [('ollama', 'a'), ('albert', 'x'), ('ilaas', 'z')]
        calls = []

        def turn(user, message, *, provider, model, **k):
            calls.append((message, provider, k))
            if message.startswith(_REVIEW_BRIEF[:40]):
                return {'response': 'A bien, B moins.\nCLASSEMENT FINAL:\n1. Avis A\n2. Avis B\n'
                                    '3. Avis C', 'model': provider}
            return {'response': 'Décision.', 'model': 'decider'}

        with mock.patch.object(assistant_engine, '_sub_agent_lanes', return_value=lanes), \
                mock.patch.object(assistant_engine, '_delegate',
                                  side_effect=lambda user, t, provider, **k: (
                                      {'report': f"avis {t['domain']}", 'model': provider}, [], {})), \
                mock.patch.object(assistant_engine, '_decider_lane', return_value=('ilaas', 'd')), \
                mock.patch.object(assistant_engine, 'run_assistant_turn', side_effect=turn):
            result, trace, _ = assistant_engine._delegate_wave(
                user, {'task': 'Q ?', 'agents': ['science', 'critique', 'methodology'],
                       'decide': 'review'},
                provider='ollama', llm_model='a', depth=0, deadline=None, budget=6)
        reviews = [c for c in calls if c[0].startswith(_REVIEW_BRIEF[:40])]
        self.assertEqual(['albert', 'ilaas', 'ollama'], sorted(c[1] for c in reviews))
        self.assertTrue(all(c[2]['allowed_tools'] == frozenset() for c in reviews))
        decider_message = calls[-1][0]
        self.assertIn('Relectures croisées', decider_message)
        self.assertIn('Classement agrégé', decider_message)
        self.assertNotIn('albert', decider_message)                 # toujours anonyme
        self.assertEqual('review', result['decision']['mode'])
        self.assertEqual(3, len(result['decision']['ranking']))
        self.assertEqual(['agent'] * 3 + ['reviewer'] * 3 + ['decider'],
                         [entry.get('role', 'agent') for entry in trace])

    def test_a_ranking_is_read_after_its_mark_without_duplicates_or_strangers(self):
        text = ("L'avis B est solide.\nCLASSEMENT FINAL:\n1. Avis [C]\n2. **Avis A**\n3. Avis C\n"
                "4. Avis Z")
        self.assertEqual(['C', 'A'], assistant_engine._parse_ranking(text, {'A', 'B', 'C'}))
        self.assertEqual(['B', 'A'], assistant_engine._parse_ranking('Avis B puis Avis A',
                                                                     {'A', 'B'}))

    def test_the_aggregate_is_the_mean_rank_without_one_s_own_answer(self):
        rankings = [['A', 'B', 'C'], ['A', 'C', 'B'], ['B', 'A', 'C']]
        rows = assistant_engine._aggregate_rankings(rankings, ['A', 'B', 'C'], ['A', 'B', 'C'])
        self.assertEqual([('B', 1.0), ('A', 1.5), ('C', 2.0)],
                         [(row['letter'], row['average_rank']) for row in rows])

    def test_reviewers_do_not_count_as_sub_agents_under_the_cap(self):
        from wama.common.services.assistant_engine import MAX_DELEGATIONS_PER_TURN
        council = json.dumps({'tool': 'delegate', 'args': {
            'task': 'Q', 'agents': ['general', 'critique'], 'decide': 'review'}})
        more = json.dumps({'tool': 'delegate', 'args': {
            'tasks': [{'task': f't{i}'} for i in range(MAX_DELEGATIONS_PER_TURN)]}})
        reviewer = {'role': 'reviewer', 'steps': [], 'model': 'm'}
        with mock.patch.object(assistant_engine, '_sub_agent_lanes',
                               side_effect=lambda user, provider, model, count, **k: [(provider, model)]), \
                mock.patch.object(assistant_engine, '_delegate',
                                  return_value=({'report': 'r'}, [], {})), \
                mock.patch.object(assistant_engine, '_peer_review',
                                  return_value=([], [reviewer, reviewer], {})), \
                mock.patch.object(assistant_engine, '_synthesise',
                                  return_value=({'text': 'd'}, {'role': 'decider', 'steps': []}, {})):
            result, _, _ = _turn(parent=(council, more), can_delegate=True)
        second = result['tool_steps'][1]
        # 2 agents + 1 décideur pris ; les 2 relectures ne comptent pas.
        self.assertEqual(MAX_DELEGATIONS_PER_TURN - 3, len(second['sub_agents']))

    def test_the_decider_prefers_a_remote_model(self):
        user = User.objects.create(username='council_decider_remote')
        with mock.patch.object(assistant_engine, '_sub_agent_candidates',
                               return_value=(['ollama:big', 'ilaas:z'], set())), \
                mock.patch('wama.model_manager.services.cloud_models.is_cloud_key',
                           side_effect=lambda key: key == 'ilaas:z'), \
                mock.patch('wama.common.utils.auto_model.resolve_model_choice',
                           side_effect=lambda *a, candidates, quality_intent, **k: candidates[0]):
            self.assertEqual(('ilaas', 'z'),
                             assistant_engine._decider_lane(user, 'ollama', 'a', set()))

    def test_only_a_council_asks_for_remote_lanes(self):
        user = User.objects.create(username='council_flag')
        for args, expected in (({'task': 'Q', 'agents': ['general', 'critique']}, True),
                               ({'tasks': [{'task': 'a'}, {'task': 'b'}], 'decide': 'synthesis'},
                                True),
                               ({'tasks': [{'task': 'a'}, {'task': 'b'}]}, False)):
            with mock.patch.object(assistant_engine, '_sub_agent_lanes',
                                   return_value=[('ollama', 'a')]) as lanes, \
                    mock.patch.object(assistant_engine, '_delegate',
                                      return_value=({'report': 'r'}, [], {})), \
                    mock.patch.object(assistant_engine, '_synthesise',
                                      return_value=({'text': 'd'}, {'role': 'decider'}, {})), \
                    mock.patch.object(assistant_engine, '_decider_lane',
                                      return_value=('ollama', 'a')):
                assistant_engine._delegate_wave(user, args, provider='ollama', llm_model='a',
                                                depth=0, deadline=None, budget=6)
            self.assertIs(expected, lanes.call_args.kwargs['council'], args)

    def test_the_specialised_agents_are_declared_roles(self):
        from wama.common.utils.assistant_skills import (
            competences_announcement, resolve_domain, role_instructions,
        )
        line, spec = assistant_engine._delegate_tool()
        for key in ('critique', 'methodology'):
            self.assertEqual(key, resolve_domain(key).key)
            self.assertTrue(role_instructions(key))
            self.assertIn(key, spec['function']['parameters']['properties']['agents']['items']['enum'])
            # Postures d'AGENT : nommées par `delegate`, pas annoncées à chaque tour principal.
            self.assertNotIn(f'`{key}`', competences_announcement())


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
        # EN FLUX : une requête muette est coupée vers 165-175 s chez ILaaS (mesuré le 29/10).
        self.assertTrue(callable(kwargs['on_event']))

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
