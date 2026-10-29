"""
Les BORNES d'un tour de l'assistant — le socle des sous-agents (`WAMA_HARNESS §7.4` étape 1,
2026-10-29).

Un sous-agent est un tour de LA boucle (`run_assistant_turn`), pas une seconde boucle : il en
reçoit des bornes — outils permis, nombre d'itérations, échéance, profondeur. CE QUE CETTE GARDE
TIENT :
  1. sans bornes, le tour de l'utilisateur est celui d'avant (liste entière, relais de dev) ;
  2. un tour borné n'annonce QUE ses outils (prompt et déclaration native) et n'exécute rien
     d'autre — un outil hors bornes est refusé avant la porte `execute_tool` ;
  3. les itérations et l'échéance finissent la boucle par le dernier appel sans outil ;
  4. un sous-agent (profondeur ≥ 1) est en LECTURE SEULE par construction, et la profondeur est
     bornée dans le code ;
  5. la reprise d'un tour inventé (`_invented_turn`) garde les bornes.
"""
import inspect
import itertools
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from wama import tool_api
from wama.common.services import assistant_engine
from wama.common.services.assistant_engine import (
    _DEADLINE_PROMPT, _TOOL_LIMIT_PROMPT, MAX_AGENT_DEPTH, MAX_TOOL_ITERATIONS,
)


def _turn(calls=(), answer='Réponse.', **bounds):
    """Un tour local : le modèle appelle `calls` dans l'ordre, puis répond. Rend (résultat,
    messages vus à chaque appel du modèle, outils réellement exécutés)."""
    seen, executed = [], []

    def llm(messages, llm_model, *a, **k):
        seen.append([dict(m) for m in messages])
        index = len(seen) - 1
        if index < len(calls):
            return '{"tool": "%s", "args": {"q": "x"}}' % calls[index], {}
        return answer, {}

    def run(name, args, user):
        executed.append(name)
        return {'ok': True}

    user = User.objects.create(username=f'bounds_{User.objects.count()}')
    with mock.patch.object(assistant_engine, '_llm_call', side_effect=llm), \
            mock.patch('wama.tool_api.execute_tool', side_effect=run):
        result = assistant_engine.run_assistant_turn(user, 'question', provider='ollama',
                                                     model='m', **bounds)
    return result, seen, executed


def _system(seen) -> str:
    return seen[0][0]['content']


class UnboundedTurnTest(TestCase):

    def test_the_defaults_leave_the_user_turn_as_it_was(self):
        params = inspect.signature(assistant_engine.run_assistant_turn).parameters
        self.assertIsNone(params['allowed_tools'].default)
        self.assertEqual(MAX_TOOL_ITERATIONS, params['max_iterations'].default)
        self.assertIsNone(params['deadline'].default)
        self.assertEqual(0, params['depth'].default)
        _, seen, _ = _turn()
        self.assertIn(tool_api.build_tools_list(), _system(seen))
        self.assertIn('charger_competence', _system(seen))

    def test_the_development_relay_is_offered_only_to_an_unbounded_turn(self):
        from wama.common.services import mcp_client
        with mock.patch.object(mcp_client, 'dev_tools_for', return_value=[]) as relay:
            _turn()
        relay.assert_called_once()
        with mock.patch.object(mcp_client, 'dev_tools_for', return_value=[]) as relay:
            _turn(allowed_tools={'search_docs'})
        relay.assert_not_called()


class AllowedToolsTest(TestCase):

    def test_only_the_allowed_tools_are_announced(self):
        _, seen, _ = _turn(allowed_tools={'search_docs'})
        system = _system(seen)
        self.assertIn('- search_docs(', system)
        self.assertNotIn('- delete_item(', system)
        # L'annonce des compétences suppose l'outil qui les charge.
        self.assertNotIn('charger_competence', system)

    def test_a_tool_outside_the_bounds_never_reaches_the_gate(self):
        result, _, executed = _turn(['delete_item', 'search_docs'], allowed_tools={'search_docs'})
        self.assertEqual(['search_docs'], executed)
        self.assertIn('non permis', result['tool_steps'][0]['result']['error'])
        self.assertIn('delete_item', result['response'])        # le refus est DIT, par la trace

    def test_the_bounded_list_is_cut_from_the_built_one(self):
        tool_api._TOOLS_LIST_CACHE.clear()
        self.addCleanup(tool_api._TOOLS_LIST_CACHE.clear)
        with mock.patch.object(tool_api, 'tool_descriptions',
                               wraps=tool_api.tool_descriptions) as built:
            full = tool_api.build_tools_list()
            bounded = tool_api.build_tools_list({'search_docs', 'no_such_tool'})
        self.assertEqual(1, built.call_count)
        line = next(l for l in full.splitlines() if l.startswith('- search_docs('))
        self.assertEqual(['Available tools:', line], bounded.splitlines())

    def test_the_native_declaration_follows_the_bounds(self):
        user = User.objects.create(username='bounds_native')
        names = {s['function']['name']
                 for s in assistant_engine.native_tool_list(user, names={'search_docs'})}
        self.assertEqual({'search_docs'}, names)
        self.assertGreater(len(assistant_engine.native_tool_list(user)), 1)


class LoopEndTest(TestCase):

    def test_max_iterations_ends_the_loop_with_a_call_without_tools(self):
        _, seen, executed = _turn(['search_docs'] * 5, max_iterations=2)
        self.assertEqual(['search_docs', 'search_docs'], executed)
        self.assertEqual(3, len(seen))
        self.assertEqual(_TOOL_LIMIT_PROMPT, seen[-1][-1]['content'])

    def test_a_passed_deadline_stops_before_the_next_tool(self):
        # Horloge : 0 au premier passage (l'outil part), 5 ensuite (l'échéance 1 est passée).
        clock = mock.Mock()
        clock.monotonic.side_effect = itertools.chain([0], itertools.repeat(5))
        with mock.patch.object(assistant_engine, 'time', clock):
            _, seen, executed = _turn(['search_docs'] * 3, deadline=1)
        self.assertEqual(['search_docs'], executed)
        self.assertEqual(_DEADLINE_PROMPT, seen[-1][-1]['content'])

    def test_without_deadline_nothing_reads_the_clock_in_the_loop(self):
        clock = mock.Mock()
        with mock.patch.object(assistant_engine, 'time', clock):
            _turn(['search_docs'])
        clock.monotonic.assert_not_called()


class SubAgentDepthTest(TestCase):

    def test_a_sub_agent_is_given_the_read_tools_only(self):
        _, seen, _ = _turn(depth=1)
        system = _system(seen)
        self.assertIn('- search_docs(', system)
        self.assertNotIn('- delete_item(', system)
        self.assertNotIn('- add_to_anonymizer(', system)

    def test_a_write_tool_asked_for_a_sub_agent_is_dropped(self):
        _, seen, executed = _turn(['delete_item'], depth=1,
                                  allowed_tools={'delete_item', 'search_docs'})
        self.assertEqual([], executed)
        self.assertNotIn('- delete_item(', _system(seen))

    def test_depth_is_bounded_in_the_code(self):
        user = User.objects.create(username='bounds_depth')
        with self.assertRaises(ValueError):
            assistant_engine.run_assistant_turn(user, 'q', provider='ollama', model='m',
                                                depth=MAX_AGENT_DEPTH + 1)


class SubscriptionPathTest(TestCase):
    """L'abonnement Claude Code tourne SA boucle, avec tous les outils du compte par MCP : un tour
    borné n'y tiendrait pas ses bornes — il est arrêté avant tout appel au modèle."""

    def _turn(self, **bounds):
        user = User.objects.create(username=f'bounds_abo_{User.objects.count()}')
        with mock.patch('wama.common.services.claude_code.subscription_allowed', return_value=True), \
                mock.patch.object(assistant_engine, '_llm_call', return_value=('ok', {})) as llm:
            result = assistant_engine.run_assistant_turn(user, 'q', provider='claude-abo', **bounds)
        return result, llm

    def test_a_sub_agent_never_runs_on_the_subscription(self):
        result, llm = self._turn(depth=1)
        self.assertIn('abonnement', result.get('error', ''))
        llm.assert_not_called()

    def test_the_user_turn_still_does(self):
        result, llm = self._turn()
        self.assertNotIn('error', result)
        llm.assert_called()


class InventedTurnRetryTest(TestCase):

    def test_the_retry_of_an_invented_turn_keeps_the_bounds(self):
        bounds = {'allowed_tools': frozenset({'search_docs'}), 'max_iterations': 3,
                  'deadline': 12.5, 'depth': 1}
        with mock.patch('wama.common.services.development_models.escalation_model',
                        return_value='ollama:big'), \
                mock.patch.object(assistant_engine, 'run_assistant_turn',
                                  return_value={'success': True, 'response': 'r'}) as retry:
            assistant_engine._invented_turn(
                None, 'q', provider='ollama', llm_model='m', local=True, etiquette='e',
                total_usage={}, history=[], domain=None, surface='web', on_event=None,
                escalated_from=None, bounds=bounds)
        self.assertEqual(bounds, {k: retry.call_args.kwargs[k] for k in bounds})
