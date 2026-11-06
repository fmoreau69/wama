"""The assistant's COMMANDS — `/concile`, `/effort`, `/competence`… — declared once for every
surface (`common/services/assistant_commands.py`, 2026-11-06).

Fabien: « gère-t-on bien les commandes qui permettent d'expliciter l'usage des skills ou
fonctionnalités de l'assistant comme le concile ? » Only the gateway had commands; the web sent
`/concile` to the model as a sentence. These tests play the real common turn (`conversation_turn`,
the engine replaced by a double), the real web and API views, and, in V8, the served chat.
"""
import json
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

ENGINE = 'wama.common.services.assistant_engine.run_assistant_turn'


def _answer(user, message, **kwargs):
    return {'success': True, 'response': 'réponse', 'model': 'faux:1b', 'tool_steps': []}


def _council_answer(user, message, **kwargs):
    return {'success': True, 'response': 'avis tranché', 'model': 'faux:1b',
            'tool_steps': [{'tool': 'delegate', 'args': {}, 'result': {}}]}


class ParseCommandTest(SimpleTestCase):

    def test_both_prefixes_are_read_and_the_word_is_folded(self):
        from wama.common.services.assistant_commands import parse_command
        self.assertEqual(('/', 'modele', 'auto'), parse_command('/Modèle auto'))
        self.assertEqual(('!', 'concile', 'une question\nsur deux lignes'),
                         parse_command('!concile une question\nsur deux lignes'))

    def test_a_path_or_a_plain_sentence_is_not_a_command(self):
        from wama.common.services.assistant_commands import parse_command, run_command
        self.assertIsNone(parse_command('/media/users/1/out.png est-il prêt ?'))
        self.assertIsNone(parse_command('transcris /media/x.wav'))
        self.assertIsNone(run_command(None, '/inconnue bonjour', surface='web'),
                          'an unknown word goes to the model as it was')

    def test_what_is_typed_is_compared_by_one_common_fold(self):
        """Files, pages and commands each carried the same private `_fold` (the third written the
        day of the commands): they now read the one brick, and none keeps a copy."""
        from wama.common.services import assistant_commands, navigation, user_files
        from wama.common.utils.text_fold import fold
        self.assertEqual('mediatheque', fold('  Médiathèque '))
        for module in (assistant_commands, navigation, user_files):
            self.assertIs(fold, module.fold, module.__name__)
            self.assertFalse(hasattr(module, '_fold'), module.__name__)

    def test_the_help_lists_every_declared_command_with_the_prefix_asked(self):
        from wama.common.services.assistant_commands import COMMANDS, help_text
        for prefix in ('/', '!'):
            text = help_text(prefix)
            for command in COMMANDS:
                self.assertIn(f'`{prefix}{command.name}', text)

    def test_the_effort_help_offers_the_selector_positions(self):
        """Its usage was written by hand at first (`rapide|equilibre|qualite`): a position added
        to the selector would have been accepted but never offered."""
        import importlib
        from wama.common.services import assistant_commands
        presets = (('fast', 'Rapide', 15), ('instant', 'Éclair', 5))
        try:
            with mock.patch('wama.model_manager.services.model_selector.QUALITY_PRESETS', presets):
                importlib.reload(assistant_commands)
                line = next(l for l in assistant_commands.help_text('/').splitlines()
                            if '`/effort' in l)
                reply = assistant_commands._effort(
                    None, '', assistant_commands.CommandContext(surface='web'))['reply']
        finally:
            importlib.reload(assistant_commands)
        for text in (line, reply):
            self.assertIn('eclair', text)
            self.assertNotIn('qualite', text)


class CommandsInTheCommonTurnTest(TestCase):
    """Every surface reaches the commands through `conversation_turn`, after its access guard and
    before its thread."""

    def setUp(self):
        self.user = User.objects.create(username='fabien')

    def _turn(self, text, surface='web', thread_key='', engine=_answer):
        from wama.common.services.assistant_engine import conversation_turn
        with mock.patch(ENGINE, side_effect=engine) as called:
            result = conversation_turn(self.user, text, surface=surface, thread_key=thread_key)
        return result, called

    def _settings(self):
        from wama.common.services.assistant_engine import assistant_settings
        return assistant_settings(self.user)

    def test_effort_writes_the_slider_by_its_named_position_or_its_number(self):
        result, engine = self._turn('/effort qualité')
        engine.assert_not_called()
        self.assertEqual(85, self._settings()['quality_intent'], 'the selector position, not a copy')
        self.assertEqual({'quality_intent': 85}, result['settings'])
        self.assertEqual('effort', result['command'])
        self._turn('!effort 30')
        self.assertEqual(30, self._settings()['quality_intent'])

    def test_a_wrong_effort_is_refused_and_nothing_is_written(self):
        before = self._settings()['quality_intent']
        result, _ = self._turn('/effort maximal')
        self.assertIn('⛔', result['response'])
        self.assertEqual(before, self._settings()['quality_intent'])

    def test_effort_alone_says_the_current_position(self):
        self._turn('/effort rapide')
        result, _ = self._turn('/effort')
        self.assertIn('Rapide', result['response'])
        self.assertIn('15', result['response'])

    def test_council_opens_delegation_for_this_message_whatever_the_setting(self):
        from wama.assistant.params import SUB_AGENTS_NEVER
        from wama.common.utils.user_settings import save_user_app_settings
        save_user_app_settings(self.user, 'assistant', {'sub_agents': SUB_AGENTS_NEVER})
        result, engine = self._turn('/concile faut-il un seul axe de temps ?',
                                    engine=_council_answer)
        kwargs = engine.call_args.kwargs
        self.assertTrue(kwargs['can_delegate'], 'the manual gesture wins over « jamais »')
        message = engine.call_args.args[1]
        self.assertIn('faut-il un seul axe de temps ?', message)
        self.assertTrue(message.startswith('Réunis un concile'), 'the intention is said in words')
        self.assertNotIn('ne s\'est pas réuni', result['response'])
        # The next plain message is back to the setting.
        _, engine = self._turn('bonjour')
        self.assertFalse(engine.call_args.kwargs['can_delegate'])

    def test_a_council_that_did_not_gather_is_said(self):
        result, _ = self._turn('/concile une question ouverte')
        self.assertIn("Le concile ne s'est pas réuni", result['response'])

    def test_a_council_keeps_the_files_dropped_with_it(self):
        from wama.common.services.assistant_engine import message_with_deposits
        _, engine = self._turn(message_with_deposits('/concile que vaut ce protocole ?',
                                                     ['users/1/protocole.pdf']),
                               engine=_council_answer)
        message = engine.call_args.args[1]
        first, _, rest = message.partition('\n')
        self.assertIn('users/1/protocole.pdf', first, 'the deposit header stays first')
        self.assertIn('que vaut ce protocole ?', rest)

    def test_competence_primes_the_turn_with_a_declared_domain(self):
        _, engine = self._turn('/compétence science quel protocole pour ce corpus ?')
        self.assertEqual('science', engine.call_args.kwargs['domain'])
        self.assertEqual('quel protocole pour ce corpus ?', engine.call_args.args[1])

    def test_competence_without_a_known_domain_lists_the_registry(self):
        from wama.common.utils.assistant_skills import DOMAINES
        result, engine = self._turn('/competence astrologie')
        engine.assert_not_called()
        self.assertIn('⛔', result['response'])
        for domain in DOMAINES:
            self.assertIn(f'`{domain.key}`', result['response'])

    def test_forget_erases_the_web_thread_only_and_says_it_to_the_screen(self):
        from wama.common.models import Conversation
        from wama.common.services import conversation_store as store
        web = store.thread(self.user, surface='web', thread_key='')
        store.record_exchange(web, 'statut ?', {'response': 'Terminé.'})
        channel = store.thread(self.user, surface='discord', thread_key='salon-1')
        result, engine = self._turn('/oublier')
        engine.assert_not_called()
        self.assertTrue(result['cleared'])
        self.assertFalse(Conversation.objects.filter(pk=web.pk).exists())
        self.assertTrue(Conversation.objects.filter(pk=channel.pk).exists())

    def test_a_command_that_answers_alone_opens_no_thread_and_records_nothing(self):
        from wama.common.models import Conversation
        result, _ = self._turn('/oublier')
        self.assertIn('rien à effacer', result['response'])
        self._turn('/effort rapide')
        self.assertEqual(0, Conversation.objects.filter(user=self.user).count())

    def test_the_access_guard_comes_before_any_command(self):
        before = self._settings()['quality_intent']
        with mock.patch('wama.accounts.permissions.accessible', return_value=False):
            result, engine = self._turn('/effort rapide')
        self.assertIn('error', result)
        engine.assert_not_called()
        self.assertEqual(before, self._settings()['quality_intent'])

    def test_a_plain_message_reaches_the_model_untouched(self):
        _, engine = self._turn('/inconnue garde ce texte')
        self.assertEqual('/inconnue garde ce texte', engine.call_args.args[1])


class CommandsOnEverySurfaceTest(TestCase):
    """The web chat and the REST API reach the same commands, by the same turn."""

    def setUp(self):
        self.user = User.objects.create(username='fabien')
        self.client.force_login(self.user)

    def test_the_web_chat_answers_a_command_without_the_model(self):
        with mock.patch(ENGINE) as engine:
            response = self.client.post(reverse('ai_chat'), json.dumps({'message': '/effort rapide'}),
                                        content_type='application/json')
        engine.assert_not_called()
        data = response.json()
        self.assertEqual('effort', data['command'])
        self.assertEqual({'quality_intent': 15}, data['settings'])

    def test_the_api_answers_a_command_without_the_model(self):
        with mock.patch(ENGINE) as engine:
            response = self.client.post('/api/v1/assistant/chat/', {'message': '/aide'},
                                        content_type='application/json')
        engine.assert_not_called()
        self.assertIn('/concile', response.json()['response'])


class ChatAppliesACommandTest(SimpleTestCase):
    """The served chat (V8): a cleared thread starts blank, a changed setting re-aligns the panel
    through the settings modal's own event, anything else is left alone."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        from wama.common.tests.tests_assistant_job_progress import FAKE_BROWSER
        ctx = MiniRacer()
        ctx.eval(FAKE_BROWSER)
        ctx.eval("""
            var events = [];
            document.dispatchEvent = function (e) { events.push(e.type); };
            function CustomEvent(type) { this.type = type; }
        """)
        served = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
        ctx.eval((served / 'wama-assistant-chat.js').read_text(encoding='utf-8'))
        ctx.eval("""
            var calls = [];
            var chat = Object.create(WamaAssistantChat._Chat.prototype);
            chat.feed = { innerHTML: '<div>ancien fil</div>' };
            chat.stopAllJobs = function () { calls.push('stopAllJobs'); };
            chat.showGreeting = function () { calls.push('showGreeting'); };
            chat.dropGreeting = function () { calls.push('dropGreeting'); };
            chat.setStatus = function () { calls.push('setStatus'); };
        """)
        return ctx

    def _read(self, ctx, expr):
        return json.loads(ctx.eval('JSON.stringify(%s)' % expr))

    def test_a_forgotten_thread_empties_the_screen_like_the_clear_button(self):
        ctx = self._ctx()
        ctx.eval("chat.applyCommand({command: 'oublier', cleared: true, response: 'effacée'})")
        self.assertEqual('', self._read(ctx, 'chat.feed.innerHTML'))
        self.assertEqual(['stopAllJobs', 'showGreeting', 'setStatus', 'dropGreeting'],
                         self._read(ctx, 'calls'))
        self.assertEqual([], self._read(ctx, 'events'))

    def test_a_changed_setting_sends_the_event_the_panel_listens_to(self):
        ctx = self._ctx()
        ctx.eval("chat.applyCommand({command: 'effort', settings: {quality_intent: 85}})")
        self.assertEqual(['wama:assistant-settings'], self._read(ctx, 'events'))
        self.assertEqual('<div>ancien fil</div>', self._read(ctx, 'chat.feed.innerHTML'))

    def test_an_ordinary_answer_changes_nothing(self):
        ctx = self._ctx()
        ctx.eval("chat.applyCommand({response: 'bonjour', cleared: true, settings: {model: 'x'}})")
        self.assertEqual([[], []], self._read(ctx, '[calls, events]'))
