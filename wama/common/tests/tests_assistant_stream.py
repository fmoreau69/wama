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

    def test_without_a_callback_the_stream_is_still_asked_and_the_whole_text_returned(self):
        """Sans flux, le délai de 180 s du client plafonnait la génération ENTIÈRE : la passerelle
        Discord mourait à 3 min pile sur un tour local avec réflexion (fil #43, 2026-10-12), pendant
        que le web, en flux, n'était coupé que par 180 s de silence. Cette garde disait l'inverse
        jusqu'à ce jour (« aucune raison de payer un flux qu'on n'affiche pas »)."""
        sent = {}
        lines = [json.dumps({'message': {'content': 'o'}}),
                 json.dumps({'message': {'content': 'k'}, 'done': True})]
        stream_client = self._fake_stream(lines)

        class RecordingClient(stream_client):
            def stream(self, method, url, json=None, **k):
                sent.update(json or {})
                return super().stream(method, url, json=json, **k)
        with mock.patch('httpx.Client', RecordingClient):
            text, _ = assistant_engine._ollama_call([{'role': 'user', 'content': 'x'}], 'm')
        self.assertIs(True, sent['stream'])
        self.assertEqual('ok', text)


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

        def fake_llm(messages, llm_model, provider, user=None, think=None, on_delta=None,
                     **_settings):            # la température du tour, entre autres (2026-10-21)
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
        def fake_llm(messages, llm_model, provider, user=None, think=None, on_delta=None,
                     tools=None, **_settings):
            self.assertIsNotNone(on_delta)
            # gpt-oss est déclaré `native_tools` chez Albert : la déclaration native accompagne
            # l'appel (2026-10-11) — elle vaut pour ce modèle mesuré, pas pour toute la source.
            self.assertTrue(tools)
            on_delta('Réponse ')
            on_delta('distante.')
            return 'Réponse distante.', dict(USAGE)

        events = []
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=fake_llm):
            assistant_engine.run_assistant_turn(self.user, 'x', provider='albert',
                                                model='gpt-oss-120b', history=[],
                                                on_event=events.append)
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
        # Depuis le 2026-10-13 l'assistant est un outil de la politique d'accès : le visiteur est
        # arrêté AVANT la vue, par la garde commune, qui lui dit de se connecter (403 +
        # `login_required`) — le même refus que pour toute app non publique.
        refused = self.client.post(reverse('ai_chat_stream'), data=json.dumps({'message': 'x'}),
                                   content_type='application/json')
        self.assertEqual(403, refused.status_code)
        self.assertTrue(refused.json()['login_required'])


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


class CloudRateLimitTest(SimpleTestCase):
    """Une limite de débit (HTTP 429) d'un fournisseur LLM ATTEND puis recommence (2026-10-10).

    Mesuré au rejeu du fil web n° 37 : Albert accorde 10 requêtes par minute et par clé, un tour
    d'assistant à huit outils en fait neuf — le 429 finissait le tour par son message brut.
    """

    class RateLimitError(Exception):
        status_code = 429

        def __init__(self):
            super().__init__('10 requests per minute exceeded')
            self.response = mock.Mock(headers={'retry-after': '3'})

    def _llm(self, outcomes):
        import sys
        from wama.common.utils import llm_utils
        outcomes = iter(outcomes)

        def completion(**kwargs):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return mock.Mock(choices=[mock.Mock(message=mock.Mock(content=outcome))])
        with mock.patch.dict(sys.modules, {'litellm': mock.Mock(completion=completion)}), \
                mock.patch('time.sleep') as sleep:
            result = llm_utils.llm_chat([{'role': 'user', 'content': 'x'}], model='m',
                                        provider='anthropic', api_key='k')
        return result, sleep

    def test_the_call_waits_what_the_provider_asks_then_answers(self):
        (text, error), sleep = self._llm([self.RateLimitError(), 'Bonjour'])
        self.assertEqual(('Bonjour', None), (text, error))
        sleep.assert_called_once_with(3.0)

    def test_the_wait_is_capped_and_a_lasting_refusal_is_said(self):
        from wama.common.utils import llm_utils
        refusals = [self.RateLimitError() for _ in range(llm_utils.RATE_LIMIT_RETRIES + 1)]
        (text, error), sleep = self._llm(refusals)
        self.assertIsNone(text)
        self.assertIn('10 requests per minute', error)
        self.assertEqual(llm_utils.RATE_LIMIT_RETRIES, sleep.call_count)

    def test_another_error_is_not_retried(self):
        """Contre-épreuve : seule la limite de débit attend."""
        (text, error), sleep = self._llm([ValueError('clé refusée')])
        self.assertEqual((None, 'clé refusée'), (text, error))
        sleep.assert_not_called()


class NativeToolCallTest(SimpleTestCase):
    """Les outils DÉCLARÉS au fournisseur (`tools=`, 2026-10-11) : gpt-oss (Albert) appelle par un
    canal à part ; non déclarés, l'appel arrivait sans nom dans le raisonnement (réponse vide ~2
    fois sur 3). L'appel natif revient dans la forme texte que la boucle lit déjà."""

    TOOLS = [{'type': 'function', 'function': {'name': 'get_install_options',
                                               'parameters': {'type': 'object'}}}]

    @staticmethod
    def _function(name, arguments):
        fn = mock.Mock(arguments=arguments)
        fn.name = name                  # `Mock(name=…)` nommerait le double, pas l'attribut
        return fn

    def _call(self, name, arguments):
        return mock.Mock(function=self._function(name, arguments))

    def _chat(self, completion, **kwargs):
        import sys
        from wama.common.utils import llm_utils
        with mock.patch.dict(sys.modules, {'litellm': mock.Mock(completion=completion)}):
            return llm_utils.llm_chat([{'role': 'user', 'content': 'x'}], model='m',
                                      provider='anthropic', api_key='k', **kwargs)

    def test_a_named_call_comes_back_as_the_loop_reads_it(self):
        sent = {}

        def completion(**kwargs):
            sent.update(kwargs)
            call = self._call('get_install_options', '{"model_key": "proposed:hf:a/b"}')
            return mock.Mock(choices=[mock.Mock(message=mock.Mock(content='', tool_calls=[call]))])
        text, error = self._chat(completion, tools=self.TOOLS)
        self.assertIsNone(error)
        self.assertEqual({'tool': 'get_install_options', 'args': {'model_key': 'proposed:hf:a/b'}},
                         assistant_engine._parse_tool_call(text))
        self.assertEqual(self.TOOLS, sent['tools'])

    def test_a_streamed_call_is_reassembled_and_never_shown(self):
        shown = []
        parts = [mock.Mock(index=0, function=self._function('get_install_options', '{"model_key": ')),
                 mock.Mock(index=0, function=self._function(None, '"k"}'))]
        chunks = [mock.Mock(choices=[mock.Mock(delta=mock.Mock(content=None, tool_calls=[p]))])
                  for p in parts]
        text, _ = self._chat(lambda **kw: iter(chunks), tools=self.TOOLS, on_delta=shown.append)
        self.assertEqual({'tool': 'get_install_options', 'args': {'model_key': 'k'}},
                         json.loads(text))
        self.assertEqual([], shown)

    def test_without_tools_nothing_is_sent_and_text_is_unchanged(self):
        """Contre-épreuve : un appelant qui ne déclare rien garde l'appel d'avant."""
        sent = {}

        def completion(**kwargs):
            sent.update(kwargs)
            return mock.Mock(choices=[mock.Mock(message=mock.Mock(content='Bonjour'))])
        self.assertEqual(('Bonjour', None), self._chat(completion))
        self.assertNotIn('tools', sent)

    def test_only_a_source_that_states_it_receives_the_tools(self):
        user = mock.Mock(pk=1, is_authenticated=True)
        tool = mock.Mock(description='d', inputSchema={'type': 'object', 'properties': {}})
        tool.name = 'get_install_options'
        with mock.patch('wama.common.services.mcp_server.tools_for', return_value=[tool]):
            specs = assistant_engine._native_tool_specs(user, 'albert',
                                                        [{'name': 'dev_x', 'args': ['action']}])
            self.assertEqual(['get_install_options', 'dev_x'],
                             [s['function']['name'] for s in specs])
            self.assertIsNone(assistant_engine._native_tool_specs(user, 'ilaas', []))
            self.assertIsNone(assistant_engine._native_tool_specs(user, 'wama-dev-ai', []))
            self.assertIsNone(assistant_engine._native_tool_specs(None, 'albert', []))

    def test_only_a_measured_model_of_the_source_receives_the_tools(self):
        """PAR MODÈLE (2026-10-11, le soir) : déclarés à toute la source Albert, les outils natifs
        ont rendu deepseek-v4-flash et gemma-4-31b muets — 0 appel sur 3 chacun, contre 3 sur 3
        par la liste du prompt. Seul gpt-oss, mesuré, les reçoit."""
        user = mock.Mock(pk=1, is_authenticated=True)
        tool = mock.Mock(description='d', inputSchema={'type': 'object', 'properties': {}})
        tool.name = 'list_user_files'
        with mock.patch('wama.common.services.mcp_server.tools_for', return_value=[tool]):
            self.assertTrue(assistant_engine._native_tool_specs(user, 'albert', [], 'gpt-oss-120b'))
            for model in ('deepseek-v4-flash-0731', 'gemma-4-31b-it'):
                self.assertIsNone(assistant_engine._native_tool_specs(user, 'albert', [], model),
                                  model)
