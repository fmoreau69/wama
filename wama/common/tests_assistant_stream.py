"""
Le tour d'assistant EN FLUX (levier 5, `WAMA_LLM §1bis`) — 2026-09-26.

⚠ CE QUE CES GARDES PROTÈGENT, et aucun de ces défauts ne lève d'exception :
  1. **ce qui s'affiche** : la réflexion du modèle et les appels d'outils arrivent par le MÊME
     canal que la réponse. Les laisser passer ferait lire du JSON et 7 000 caractères de
     « pensée » à l'utilisateur — un écran faux, jamais une erreur ;
  2. **la décision doit se prendre SANS attendre la fin**, sinon il n'y a plus de flux : le
     portier est donc éprouvé fragment par fragment, y compris coupé au milieu d'une balise ;
  3. **le tour synchrone reste intact** : sans rappel, aucun `stream` n'est demandé à Ollama —
     l'API v1 et la passerelle ne paient pas un flux qu'elles n'affichent pas ;
  4. le flux ne CHANGE PAS le résultat : même texte, même trace, même fil qu'un tour bloquant.
"""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.services import assistant_engine
from wama.common.services.assistant_engine import _TokenGate

USAGE = {'input_tokens': 0, 'output_tokens': 0}


def _gate_output(fragments):
    """Ce que le portier laisse passer pour cette suite de fragments."""
    seen = []
    gate = _TokenGate(seen.append)
    for fragment in fragments:
        gate.feed(fragment)
    gate.close()
    return ''.join(seen)


class TokenGateTest(SimpleTestCase):

    def test_a_plain_answer_goes_through_unchanged(self):
        self.assertEqual('Bonjour Fabien.', _gate_output(['Bonjour ', 'Fabien', '.']))

    def test_the_model_reflection_never_reaches_the_screen(self):
        output = _gate_output(['<think>', 'je réfléchis longuement', '</think>', 'La réponse.'])
        self.assertEqual('La réponse.', output)

    def test_a_reflection_split_across_fragments_is_still_caught(self):
        """Le cas qui casse un filtre naïf : la balise n'arrive pas d'un bloc."""
        self.assertEqual('Réponse.', _gate_output(['<', 'thi', 'nk>', 'bla', '</thi', 'nk>', 'Réponse.']))

    def test_a_tool_call_is_never_displayed(self):
        output = _gate_output(['{"tool"', ': "list_user_files", "args": {}}'])
        self.assertEqual('', output)

    def test_a_tool_call_after_a_reflection_is_not_displayed_either(self):
        self.assertEqual('', _gate_output(['<think>hmm</think>', '{"tool": "x", "args": {}}']))

    def test_leading_whitespace_does_not_decide_anything(self):
        """Un blanc n'est pas un caractère utile : décider dessus ouvrirait le robinet avant
        d'avoir vu le `{` d'un appel d'outil."""
        self.assertEqual('', _gate_output(['\n  ', '{"tool": "x", "args": {}}']))


class OllamaStreamTest(SimpleTestCase):

    def _fake_stream(self, lines):
        """Un faux Ollama en flux : `client.stream(...)` rend les lignes JSON une par une."""
        class FakeResponse:
            status_code = 200

            def iter_lines(self):
                return iter(lines)

            def __enter__(self): return self
            def __exit__(self, *a): return False

        class FakeClient:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def stream(self, *a, **k): return FakeResponse()
        return FakeClient

    def test_fragments_are_handed_over_as_they_arrive_and_the_whole_text_is_returned(self):
        lines = [json.dumps({'message': {'content': 'Bon'}}),
                  json.dumps({'message': {'content': 'jour'}}),
                  json.dumps({'message': {'content': ''}, 'done': True,
                              'prompt_eval_count': 12, 'eval_count': 3})]
        seen = []
        with mock.patch('httpx.Client', self._fake_stream(lines)):
            text, usage = assistant_engine._ollama_call(
                [{'role': 'user', 'content': 'x'}], 'm', on_delta=seen.append)
        self.assertEqual(['Bon', 'jour'], seen)
        self.assertEqual('Bonjour', text)
        self.assertEqual({'input_tokens': 12, 'output_tokens': 3}, usage)

    def test_without_a_callback_no_stream_is_asked_of_ollama(self):
        """Contre-épreuve : c'est ce qui garantit que l'API et la passerelle ne changent pas."""
        sent = {}

        class FakeClient:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False

            def post(self, url, json=None):
                sent.update(json or {})
                return mock.Mock(status_code=200,
                                 json=lambda: {'message': {'content': 'ok'}})
        with mock.patch('httpx.Client', FakeClient):
            assistant_engine._ollama_call([{'role': 'user', 'content': 'x'}], 'm')
        self.assertIs(False, sent['stream'])


class TurnEventsTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('stream_turn', password='x')

    def test_a_turn_emits_its_tool_steps_and_its_text_as_they_happen(self):
        calls = []

        def fake_llm(messages, llm_model, provider, user=None, think=None, on_delta=None):
            calls.append(on_delta)
            if len(calls) == 1:
                if on_delta:
                    on_delta('{"tool": "list_user_files", "args": {}}')
                return '{"tool": "list_user_files", "args": {}}', dict(USAGE)
            if on_delta:
                on_delta('Vos ')
                on_delta('fichiers.')
            return 'Vos fichiers.', dict(USAGE)

        events = []
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=fake_llm), \
             mock.patch('wama.tool_api.execute_tool', return_value={'files': []}):
            result = assistant_engine.run_assistant_turn(
                self.user, 'mes fichiers ?', provider='wama-dev-ai', model='m', history=[],
                on_event=events.append)

        types = [e['type'] for e in events]
        self.assertEqual(['step', 'delta', 'delta'], types)
        self.assertEqual('list_user_files', events[0]['step']['tool'])
        # L'appel d'outil de la 1ʳᵉ itération n'a PAS été montré : seul le texte final passe.
        self.assertEqual('Vos fichiers.', ''.join(e['text'] for e in events if e['type'] == 'delta'))
        self.assertEqual('Vos fichiers.', result['response'])

    def test_without_a_listener_the_turn_is_the_one_that_already_existed(self):
        with mock.patch.object(assistant_engine, '_llm_call',
                               return_value=('réponse', dict(USAGE))) as call:
            result = assistant_engine.run_assistant_turn(
                self.user, 'x', provider='wama-dev-ai', model='m', history=[])
        self.assertIsNone(call.call_args.kwargs['on_delta'])
        self.assertEqual('réponse', result['response'])


class ChatStreamViewTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('stream_view', password='x')
        self.client.force_login(self.user)

    def _events(self, response):
        body = b''.join(response.streaming_content).decode()
        return [json.loads(bloc[5:].strip()) for bloc in body.split('\n\n')
                if bloc.startswith('data:')]

    def test_the_stream_carries_the_steps_then_the_final_result(self):
        def fake_turn(user, message, **kwargs):
            kwargs['on_event']({'type': 'step', 'step': {'tool': 'x', 'result': {}}})
            kwargs['on_event']({'type': 'delta', 'text': 'Salut'})
            return {'success': True, 'response': 'Salut', 'model': 'm', 'tool_steps': []}
        with mock.patch('wama.common.services.assistant_engine.conversation_turn',
                        side_effect=fake_turn):
            response = self.client.post(reverse('ai_chat_stream'),
                                       data=json.dumps({'message': 'salut'}),
                                       content_type='application/json')
        self.assertEqual('text/event-stream', response['Content-Type'])
        events = self._events(response)
        self.assertEqual(['step', 'delta', 'done'], [e['type'] for e in events])
        self.assertEqual('Salut', events[-1]['result']['response'])

    def test_a_failing_turn_becomes_a_readable_event_not_a_trace(self):
        with mock.patch('wama.common.services.assistant_engine.conversation_turn',
                        side_effect=RuntimeError('moteur cassé')):
            response = self.client.post(reverse('ai_chat_stream'),
                                       data=json.dumps({'message': 'x'}),
                                       content_type='application/json')
        events = self._events(response)
        self.assertEqual('error', events[-1]['type'])
        self.assertIn('moteur cassé', events[-1]['error'])

    def test_the_guards_are_the_same_as_the_blocking_turn(self):
        self.assertEqual(400, self.client.post(reverse('ai_chat_stream'),
                                               data=json.dumps({'message': '  '}),
                                               content_type='application/json').status_code)
        self.client.logout()
        self.assertEqual(401, self.client.post(reverse('ai_chat_stream'),
                                               data=json.dumps({'message': 'x'}),
                                               content_type='application/json').status_code)


class HomeUsesTheCommonBrickTest(TestCase):
    """L'accueil ne porte plus SON chat : il déclare celui de tout le monde."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('home_brick', password='x')
        self.client.force_login(self.user)

    def test_the_home_page_declares_the_common_chat_in_full_density(self):
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('data-wama-chat', html)
        self.assertIn('data-density="full"', html)
        self.assertIn('data-stream-url="' + reverse('ai_chat_stream') + '"', html)
        self.assertIn('wama-assistant-chat.js', html)

    def test_the_hand_written_chat_of_the_home_page_is_gone(self):
        """Contre-épreuve du portage : ces identifiants étaient ceux des ~280 lines retirées.
        Sans cette garde, laisser les deux rendus en place passerait inaperçu."""
        html = self.client.get(reverse('home')).content.decode()
        for gone in ('id="ai-chat-messages"', 'id="ai-chat-form"', 'id="ai-chat-input"',
                        'id="ai-chat-submit"'):
            self.assertNotIn(gone, html, gone)

    def test_the_declared_greeting_and_waiting_word_are_still_served(self):
        """Ils VARIENT selon l'état de connexion et sont déclarés côté serveur : le portage ne
        doit pas les avoir figés dans du JavaScript."""
        from wama.common.utils.assistant_skills import greeting
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('data-assistant-greeting', html)
        self.assertIn(str(greeting(self.user)['attente_apres_ms']), html)
