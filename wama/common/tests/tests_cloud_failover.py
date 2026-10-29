"""Failover of an assistant turn when its cloud provider is saturated (ROADMAP §8d step 2).

Measured on 2026-10-12: a free OpenRouter model answering 429 cost 83.8 s — the minute's wait,
one more try on the SAME provider, then the error. Since 2026-10-13 a failure that says the
provider is saturated NOTES it (`llm_chat` → `source_quota.note_saturation`), and:
  - a DRAWN model (« auto ») switches at once: the common draw is replayed — the note already
    leaves the provider out of the admission — and the switch is SAID;
  - a CHOSEN model does not switch on its own (Fabien's decision, 13/10): the relay is PROPOSED,
    with the catalog key a click resends the message with.
`_llm_call` is replaced: what is held here is the turn's decision, not the network.
"""
import json
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from wama.common.services import assistant_engine
from wama.common.services import source_quota

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
                source_quota.note_saturation(assistant_engine._provider_source(provider),
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


#: Le strict nécessaire du DOM pour rendre une bulle d'erreur et cliquer son bouton (V8).
FAKE_DOM = r"""
var window = this;
function element() {
  return { children: [], textContent: '', appendChild: function (c) { this.children.push(c); },
           addEventListener: function (type, fn) { this['on' + type] = fn; } };
}
var document = { readyState: 'complete', querySelectorAll: function () { return []; },
                 cookie: '', createElement: element };
var bodies = [];
function fetch(url, options) { bodies.push(options.body); return new Promise(function () {}); }
"""


class ProposedRelayInTheChatTest(SimpleTestCase):
    """Côté chat web (`wama-assistant-chat.js`, fichier SERVI) : le relais PROPOSÉ pour un modèle
    choisi devient un bouton, et le clic renvoie le même message avec ce modèle, pour ce message
    seul. Un bouton qui renverrait sans le modèle retomberait sur le modèle saturé — un défaut
    qu'aucun test Python ne voit."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(FAKE_DOM + source)
        ctx.eval("var chat = Object.create(WamaAssistantChat._Chat.prototype);"
                 "chat.bubble = function () { return element(); };"
                 "var sent = []; chat.send = function (relay) { sent.push(relay); };")
        return ctx

    def test_the_proposed_relay_resends_the_message_with_its_model(self):
        ctx = self._ctx()
        ctx.eval("var line = chat.errorBubble({error: 'saturé', fallback: {model_key: "
                 "'ilaas:mistral', label: 'ILaaS · mistral'}}, 'bonjour');"
                 "line.children[0].onclick();")
        self.assertEqual('Répondre avec ILaaS · mistral', ctx.eval("line.children[0].textContent"))
        self.assertEqual({'message': 'bonjour', 'model': 'ilaas:mistral'},
                         json.loads(ctx.eval("JSON.stringify(sent[0])")))

    def test_an_error_without_relay_has_no_button(self):
        ctx = self._ctx()
        self.assertEqual(0, ctx.eval("chat.errorBubble({error: 'clé refusée'}, 'bonjour')"
                                     ".children.length"))

    def test_the_model_rides_with_this_message_only(self):
        ctx = self._ctx()
        ctx.eval("chat.cfg = {chatUrl: '/chat/'}; chat.signal = function () { return null; };"
                 "chat.sendBlocking('bonjour', 'ilaas:mistral'); chat.sendBlocking('merci', null);")
        self.assertEqual([{'message': 'bonjour', 'model': 'ilaas:mistral'}, {'message': 'merci'}],
                         [json.loads(b) for b in ctx.eval("bodies")])


class RoleRelayIsTracedTest(SimpleTestCase):
    """A wama-dev-ai role relayed to another provider (`role_utils._relay`) writes its output
    under the provider and model that ANSWERED — 2026-10-29: a glue written by local qwen3.8, ILaaS
    being down, was recorded and announced as mistral-small's."""

    def test_the_output_names_who_answered_and_keeps_the_request(self):
        import tempfile
        from wama.common.tests.tests_dev_ai_bridge import _charger
        role_utils = _charger('role_utils')
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(role_utils, 'OUTPUTS', Path(folder)), \
                mock.patch.object(role_utils, 'RELAYS', [
                    {'from': 'ilaas', 'provider': 'ollama', 'model': 'qwen3.8:latest',
                     'reason': 'indisponible'}]):
            out = json.loads(role_utils.write_output(
                'codegen', 'x', {'provider': 'ilaas', 'model': 'mistral-small'}).read_text(
                    encoding='utf-8'))
            self.assertEqual(('ollama', 'qwen3.8:latest'), (out['provider'], out['model']))
            self.assertEqual({'provider': 'ilaas', 'model': 'mistral-small'}, out['requested'])
        # Counter-proof : without a relay, the output is written as requested.
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(role_utils, 'OUTPUTS', Path(folder)), \
                mock.patch.object(role_utils, 'RELAYS', []):
            out = json.loads(role_utils.write_output(
                'codegen', 'x', {'provider': 'ilaas', 'model': 'mistral-small'}).read_text(
                    encoding='utf-8'))
            self.assertEqual(('ilaas', 'mistral-small'), (out['provider'], out['model']))
            self.assertNotIn('requested', out)
