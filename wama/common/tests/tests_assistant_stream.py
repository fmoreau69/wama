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

    def test_a_tool_call_announced_by_a_sentence_is_cut_at_the_call(self):
        """Mesuré le 2026-10-04 sur un modèle distant : il écrit une phrase PUIS l'appel. La
        phrase passe, le JSON non — y compris coupé au milieu de son ouverture."""
        output = _gate_output(['Je vérifie vos fichiers. ', '{"to', 'ol": "list_user_files"',
                               ', "args": {}}'])
        self.assertEqual('Je vérifie vos fichiers. ', output)
        self.assertEqual('Un instant.\n', _gate_output(['Un instant.\n{ "tool" : "x", "args": {}}']))

    def test_an_ordinary_brace_in_an_answer_still_goes_through(self):
        """Contre-épreuve : une accolade n'est pas un appel d'outil."""
        text = 'En JSON : {"clef": 1} ou {x}. Fin {'
        self.assertEqual(text, _gate_output(list(text)))


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


class CloudStreamTest(SimpleTestCase):
    """Le flux d'un fournisseur DÉCLARÉ (Albert) — 2026-10-04. Mesuré : premier texte à ~0,5 s,
    fin à 1 à 2 s ; sans flux l'écran et la voix attendaient la fin."""

    @staticmethod
    def _chunk(content=None, reasoning=None):
        delta = mock.Mock(content=content, reasoning_content=reasoning)
        return mock.Mock(choices=[mock.Mock(delta=delta)])

    def _fake_litellm(self, chunks, sent):
        def completion(**kwargs):
            sent.update(kwargs)
            if kwargs.get('stream'):
                return iter(chunks)
            message = mock.Mock(content='entier')
            return mock.Mock(choices=[mock.Mock(message=message)])
        return mock.Mock(completion=completion)

    def test_text_fragments_are_handed_over_and_the_reflection_is_not(self):
        import sys
        from wama.common.utils import llm_utils
        sent, seen = {}, []
        chunks = [self._chunk(reasoning='je pèse le pour'), self._chunk('Bon'),
                  self._chunk('jour'), mock.Mock(choices=[])]
        with mock.patch.dict(sys.modules, {'litellm': self._fake_litellm(chunks, sent)}):
            text, error = llm_utils.llm_chat([{'role': 'user', 'content': 'x'}], model='m',
                                             provider='anthropic', api_key='k',
                                             on_delta=seen.append)
        self.assertIsNone(error)
        self.assertEqual('Bonjour', text)
        self.assertEqual(['Bon', 'jour'], seen)
        self.assertIs(True, sent['stream'])

    def test_without_a_callback_no_stream_is_asked_of_the_provider(self):
        """Contre-épreuve : les apps et les rôles qui appellent `llm_chat` ne changent pas."""
        import sys
        from wama.common.utils import llm_utils
        sent = {}
        with mock.patch.dict(sys.modules, {'litellm': self._fake_litellm([], sent)}):
            text, _ = llm_utils.llm_chat([{'role': 'user', 'content': 'x'}], model='m',
                                         provider='anthropic', api_key='k')
        self.assertEqual('entier', text)
        self.assertNotIn('stream', sent)

    def test_the_turn_hands_its_gate_to_a_declared_provider(self):
        seen = []
        with mock.patch('wama.common.utils.llm_utils.chat_with_source',
                        return_value=('ok', None)) as chat:
            assistant_engine._llm_call([{'role': 'user', 'content': 'x'}], 'm', 'albert',
                                       user=None, on_delta=seen.append)
        self.assertIs(chat.call_args.kwargs['on_delta'].__self__, seen)


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
        # `model` ouvre le tour depuis le 2026-10-04 : le moteur dit quel modèle il a retenu
        # (`conversation_turn` s'en sert pour annoncer l'attente, et ne le relaie pas).
        self.assertEqual(['model', 'step', 'delta', 'delta'], types)
        self.assertEqual('ollama:m', events[0]['model_key'])
        self.assertEqual('list_user_files', events[1]['step']['tool'])
        # L'appel d'outil de la 1ʳᵉ itération n'a PAS été montré : seul le texte final passe.
        self.assertEqual('Vos fichiers.', ''.join(e['text'] for e in events if e['type'] == 'delta'))
        self.assertEqual('Vos fichiers.', result['response'])

    def test_a_remote_turn_streams_through_the_same_gate(self):
        """Le portier n'est plus réservé au local : un fournisseur distant qui diffuse voit son
        appel d'outil filtré de la même façon."""
        def fake_llm(messages, llm_model, provider, user=None, think=None, on_delta=None):
            self.assertIsNotNone(on_delta)
            on_delta('Réponse ')
            on_delta('distante.')
            return 'Réponse distante.', dict(USAGE)

        events = []
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=fake_llm):
            assistant_engine.run_assistant_turn(self.user, 'x', provider='albert', model='m',
                                                history=[], on_event=events.append)
        self.assertEqual('Réponse distante.',
                         ''.join(e['text'] for e in events if e['type'] == 'delta'))

    def test_without_a_listener_the_turn_is_the_one_that_already_existed(self):
        with mock.patch.object(assistant_engine, '_llm_call',
                               return_value=('réponse', dict(USAGE))) as call:
            result = assistant_engine.run_assistant_turn(
                self.user, 'x', provider='wama-dev-ai', model='m', history=[])
        self.assertIsNone(call.call_args.kwargs['on_delta'])
        self.assertEqual('réponse', result['response'])


class TurnWaitTest(TestCase):
    """La durée d'un tour : MESURÉE, écrite, apprise par l'ETA commune, puis ANNONCÉE au tour
    suivant (2026-10-04 — idée de Fabien : un décompte tiré du temps moyen par modèle)."""

    KEY = 'albert:some-model'

    def setUp(self):
        self.user = get_user_model().objects.create_user('turn_wait', password='x')

    def _turn(self, user=None, listen=True, deltas=('Bon', 'jour')):
        def fake_engine(u, message, on_event=None, **kwargs):
            if on_event is not None:
                on_event({'type': 'model', 'model_key': self.KEY, 'label': 'albert (some-model)'})
                for piece in deltas:
                    on_event({'type': 'delta', 'text': piece})
            return {'success': True, 'response': 'Bonjour', 'model': 'albert (some-model)',
                    'tool_steps': []}
        events = []
        with mock.patch.object(assistant_engine, 'run_assistant_turn', side_effect=fake_engine):
            result = assistant_engine.conversation_turn(
                user or self.user, 'salut', on_event=(events.append if listen else None))
        return result, events

    def test_nothing_is_announced_before_anything_was_measured(self):
        self.assertEqual(0.0, assistant_engine.expected_wait(self.KEY))
        _, events = self._turn()
        self.assertEqual(['delta', 'delta'], [e['type'] for e in events])

    def test_the_internal_model_event_never_reaches_the_surface(self):
        _, events = self._turn()
        self.assertNotIn('model', [e['type'] for e in events])

    def test_the_measured_wait_is_written_on_the_turn_and_learnt(self):
        from wama.common.models import ConversationTurn
        from wama.model_manager.models import ModelRuntimeStat
        result, _ = self._turn()
        turn = ConversationTurn.objects.filter(role='assistant').latest('pk')
        self.assertIsNotNone(turn.seconds_to_first_text)
        self.assertGreaterEqual(turn.seconds_total, turn.seconds_to_first_text)
        self.assertEqual(result['timing']['total'], turn.seconds_total)
        stat = ModelRuntimeStat.objects.get(model_key=assistant_engine.TURN_ETA_PREFIX + self.KEY)
        self.assertEqual(1, stat.samples)
        # La clé du MODÈLE (son débit au jeton, appris par le banc) n'est pas touchée.
        self.assertFalse(ModelRuntimeStat.objects.filter(model_key=self.KEY).exists())

    def test_a_learnt_wait_is_announced_as_a_countdown_before_the_text(self):
        assistant_engine._learn_wait(self.KEY, 6.0, self.user)
        self.assertAlmostEqual(6.0, assistant_engine.expected_wait(self.KEY))
        _, events = self._turn()
        self.assertEqual(['eta', 'delta', 'delta'], [e['type'] for e in events])
        self.assertEqual(6.0, events[0]['seconds'])

    def test_a_wait_too_short_to_read_is_not_announced(self):
        assistant_engine._learn_wait(self.KEY, 0.8, self.user)
        self.assertEqual(0.0, assistant_engine.expected_wait(self.KEY))

    def test_a_test_account_teaches_nothing(self):
        from wama.common.services.nightly_tests import TEST_USERNAME
        from wama.model_manager.models import ModelRuntimeStat
        tester = get_user_model().objects.create_user(TEST_USERNAME, password='x')
        self._turn(user=tester)
        self.assertFalse(ModelRuntimeStat.objects.filter(
            model_key=assistant_engine.TURN_ETA_PREFIX + self.KEY).exists())

    def test_without_a_listener_nothing_is_plugged_into_the_engine(self):
        """Contre-épreuve : un écouteur demanderait le flux au modèle pour une surface (API,
        passerelle) qui ne l'affiche pas."""
        from wama.common.models import ConversationTurn
        with mock.patch.object(assistant_engine, 'run_assistant_turn',
                               return_value={'success': True, 'response': 'ok', 'model': 'm',
                                             'tool_steps': []}) as engine:
            assistant_engine.conversation_turn(self.user, 'salut')
        self.assertIsNone(engine.call_args.kwargs['on_event'])
        turn = ConversationTurn.objects.filter(role='assistant').latest('pk')
        self.assertEqual(turn.seconds_total, turn.seconds_to_first_text)

    def test_the_catalogue_key_of_a_turn(self):
        key = assistant_engine.turn_model_key
        self.assertEqual('ollama:qwen3.5:4b', key('wama-dev-ai', 'qwen3.5:4b'))
        self.assertEqual('albert:some-model', key('albert', 'some-model'))
        self.assertEqual('anthropic:claude-x', key('claude', 'claude-x'))
        self.assertEqual('claude_code:opus', key('claude-abo', 'opus'))
        self.assertEqual('', key('albert', None))


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
