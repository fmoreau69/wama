"""Failover of an assistant turn when its cloud provider is saturated (ROADMAP §8d step 2).

Measured on 2026-10-12: a free OpenRouter model answering 429 cost 83.8 s — the minute's wait,
one more try on the SAME provider, then the error. Since 2026-10-13 a failure that says the
provider is saturated NOTES it (`llm_chat` → `cloud_models.note_saturation`), and:
  - a DRAWN model (« auto ») switches at once: the common draw is replayed — the note already
    leaves the provider out of the admission — and the switch is SAID;
  - a CHOSEN model does not switch on its own (Fabien's decision, 13/10): the relay is PROPOSED,
    with the catalog key a click resends the message with.
`_llm_call` is replaced: what is held here is the turn's decision, not the network.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from wama.common.services import assistant_engine
from wama.model_manager.services import cloud_models

USAGE = {'input_tokens': 0, 'output_tokens': 0}
REFUSED = {'error': 'RateLimitError: 429', 'status': 502}


class CloudFailoverTest(TestCase):

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user('cloud_failover', password='x')

    def tearDown(self):
        cache.clear()

    def _turn(self, answers, draws, **kwargs):
        """Runs a turn whose LLM calls play `answers` in order; a `None` answer is a refusal that
        notes its provider saturated, as `llm_chat` does. `draws`: what the draw returns."""
        calls = []
        answers = iter(answers)
        # The request as each call reads it (the turn may rewrite it for a local model).
        self.asked = []

        def fake_llm(messages, llm_model, provider, user=None, **call_kwargs):
            calls.append((provider, llm_model, call_kwargs))
            self.asked.append(messages[1]['content'])
            answer = next(answers)
            if answer is None:
                cloud_models.note_saturation(assistant_engine._provider_source(provider),
                                             scope='instance', seconds=60,
                                             reason='limite de débit')
                return None, dict(REFUSED)
            return answer, dict(USAGE)

        events = []
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=fake_llm), \
                mock.patch.object(assistant_engine, 'resolve_turn_model', side_effect=draws):
            result = assistant_engine.run_assistant_turn(self.user, 'bonjour', history=[],
                                                         on_event=events.append, **kwargs)
        return result, calls, events

    def test_a_drawn_model_switches_at_once_and_says_so(self):
        result, calls, events = self._turn(
            [None, 'Réponse du relais.'],
            [('albert', 'chat'), ('ilaas', 'mistral')])
        self.assertEqual([('albert', 'chat'), ('ilaas', 'mistral')],
                         [(provider, model) for provider, model, _ in calls])
        # No minute's wait: the drawn turn has a relay.
        self.assertIs(False, calls[0][2].get('rate_limit_wait'))
        self.assertEqual('Réponse du relais.', result['response'])
        self.assertIn('relais (albert : limite de débit)', result['model'])
        said = ''.join(e['text'] for e in events if e['type'] == 'delta')
        self.assertIn('albert : limite de débit', said)
        self.assertEqual('ilaas:mistral', [e for e in events if e['type'] == 'model'][-1]['model_key'])

    def test_a_relay_is_never_the_source_already_tried(self):
        """The loop guard: a draw that returns the failed source again ends the turn on its
        error, instead of calling it a second time."""
        result, calls, _events = self._turn([None], [('albert', 'chat'), ('albert', 'other')])
        self.assertEqual(1, len(calls))
        self.assertIn('429', result['error'])

    def test_a_chosen_model_does_not_switch_and_the_relay_is_proposed(self):
        result, calls, _events = self._turn([None], [('albert', 'chat'), ('ilaas', 'mistral')],
                                            model='albert:chat')
        self.assertEqual(1, len(calls))
        # The chosen model keeps the wait it always had.
        self.assertNotIn('rate_limit_wait', calls[0][2])
        self.assertIn('limite de débit', result['error'])
        self.assertEqual('ilaas:mistral', result['fallback']['model_key'])

    def test_a_relay_to_the_local_model_prepares_it_as_a_local_start(self):
        """The relay keeps the turn's messages (same harness) and gets what a local start gets:
        the context window, and the request translated when the local model lacks the language."""
        with mock.patch.object(assistant_engine, '_route_model_by_context',
                               side_effect=lambda model, messages: model) as window, \
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           return_value='hello') as intent:
            result, calls, _events = self._turn(
                [None, 'Réponse locale.'], [('albert', 'chat'), ('ollama', 'gemma')])
        self.assertEqual(['bonjour', 'hello'], self.asked)
        self.assertEqual(1, window.call_count)
        self.assertEqual('gemma', intent.call_args.kwargs['model_id'])
        self.assertEqual(('ollama', 'gemma'), calls[-1][:2])
        self.assertEqual('Réponse locale.', result['response'])

    def test_the_last_call_after_the_tool_limit_switches_too(self):
        tool = '{"tool": "get_status", "args": {}}'
        answers = [tool] * assistant_engine.MAX_TOOL_ITERATIONS + [None, 'Fin par le relais.']
        with mock.patch('wama.tool_api.execute_tool', return_value={'ok': True}):
            result, calls, _events = self._turn(answers, [('albert', 'chat'), ('ilaas', 'mistral')])
        self.assertEqual(('ilaas', 'mistral'), calls[-1][:2])
        self.assertIs(False, calls[-2][2].get('rate_limit_wait'))
        self.assertEqual('Fin par le relais.', result['response'])
        self.assertIn('relais (albert : limite de débit)', result['model'])

    def test_a_chosen_model_ends_on_the_trace_after_the_tool_limit(self):
        """Counter-test: a chosen model does not switch on its own — the last call failing still
        ends on the trace of what was done, as before."""
        tool = '{"tool": "get_status", "args": {}}'
        answers = [tool] * assistant_engine.MAX_TOOL_ITERATIONS + [None]
        with mock.patch('wama.tool_api.execute_tool', return_value={'ok': True}):
            result, calls, _events = self._turn(answers, [('albert', 'chat'), ('ilaas', 'mistral')],
                                                model='albert:chat')
        self.assertEqual(assistant_engine.MAX_TOOL_ITERATIONS + 1, len(calls))
        self.assertNotIn('rate_limit_wait', calls[-1][2])
        self.assertIn('get_status', result['response'])

    def test_a_failure_that_is_not_a_saturation_changes_nothing(self):
        """Counter-test: a refused key or an unknown model notes nothing — no relay, the error
        is returned as before."""
        def fake_llm(messages, llm_model, provider, user=None, **call_kwargs):
            return None, {'error': 'clé refusée', 'status': 401}
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=fake_llm) as call, \
                mock.patch.object(assistant_engine, 'resolve_turn_model',
                                  return_value=('albert', 'chat')):
            result = assistant_engine.run_assistant_turn(self.user, 'bonjour', history=[])
        self.assertEqual(1, call.call_count)
        self.assertEqual('clé refusée', result['error'])
        self.assertNotIn('fallback', result)
