"""
La fin d'une tâche racontée dans le fil WEB de l'assistant (2026-10-18).

LE DÉFAUT, constaté par Fabien : *« l'assistant ne semble pas recevoir de trigger quand un travail
est terminé, alors qu'une notification arrive »*. La passerelle racontait les fins de tâche dans le
fil Discord d'où elles venaient depuis le 2026-10-06 ; le fil web, rien. Ce qui ne dépend pas de la
surface est sorti de `gateway/core.py` dans la brique `common/services/job_follow_ups.py`, que les
deux surfaces lisent. Ces tests jouent la chaîne réelle : vraie card, vrai fil, vraie notification,
vrai outil de statut — et, dans V8, la relève de la cloche que le chat écoute.
"""
import json
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


class WebThreadTellsTheEndOfItsTasksTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        from wama.common.services import conversation_store as store
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.describer.models import Description
        self.root = tempfile.mkdtemp()
        media_root = override_settings(MEDIA_ROOT=self.root)
        media_root.enable()
        self.addCleanup(media_root.disable)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = store
        self.user = User.objects.create_user('web_follow_up', password='x')
        # Le rôle que le describer EXIGE, et rien de plus : l'outil de statut passe la porte F7.
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)
        _lot, (self.card,) = _lot_de(Description, self.user, 1)

    def _launched_from(self, surface='web'):
        conversation = self.store.thread(self.user, surface=surface)
        self.store.record_exchange(conversation, 'décris ce fichier', {
            'response': 'Lancé.', 'tool_steps': [{'tool': 'add_to_describer',
                                                  'args': {'file_path': 'x.png'},
                                                  'result': {'item_id': self.card.pk}}]})
        return conversation

    def _end(self, success=True):
        from wama.common.models import Notification
        from wama.common.utils.notifications import notify_job_end
        notify_job_end(self.card, 'describer', 'Describer', 'témoin', success)
        return Notification.objects.filter(recipient=self.user).latest('pk')

    def _relay(self, *ids):
        r = self.client.post(reverse('ai_chat_follow_ups'), data=json.dumps({'ids': list(ids)}),
                             content_type='application/json')
        self.assertEqual(200, r.status_code)
        return r.json()['follow_ups']

    def test_a_task_launched_from_the_web_thread_ends_in_it(self):
        conversation = self._launched_from('web')
        note = self._end()
        (told,) = self._relay(note.pk)
        self.assertTrue(told['response'].startswith('✅ Describer — « témoin » terminé'))
        self.assertEqual('get_describer_status', told['tool_steps'][0]['tool'])
        # Enregistrée AU FIL : l'historique resservi au modèle porte un « terminé » appuyé sur
        # un outil réellement joué.
        last = conversation.turns.order_by('-pk').first()
        self.assertEqual('assistant', last.role)
        self.assertEqual('get_describer_status', last.tool_steps[0]['tool'])

    def test_each_end_is_told_once_whatever_the_number_of_tabs(self):
        self._launched_from('web')
        note = self._end()
        self.assertEqual(1, len(self._relay(note.pk)))
        self.assertEqual([], self._relay(note.pk), 'un second onglet ne la raconte pas deux fois')

    def test_a_task_that_ended_before_its_turn_was_recorded_is_still_told(self):
        """2026-10-18, mesuré (anonymizer 1436) : fin à 10:49:18, tour enregistré à 10:49:19 — un
        tour s'enregistre à la FIN de sa réponse, et la borne « tours antérieurs » l'écartait."""
        note = self._end()
        self._launched_from('web')
        self.assertEqual(1, len(self._relay(note.pk)))

    def test_the_turn_tells_the_ends_that_arrived_during_it(self):
        """La cloche relève PENDANT le tour (rien au fil, rien à raconter) et ne reverra plus cette
        notification : c'est la réponse du tour qui la porte, enregistrée une fois."""
        from unittest import mock

        from wama.common.services.job_follow_ups import web_follow_ups
        bell = {}

        def turn(user, message, **kwargs):
            bell['note'] = self._end()
            bell['during'] = web_follow_ups(user, [bell['note'].pk])
            return {'response': 'Lancé.', 'tool_steps': [{'tool': 'add_to_describer', 'args': {},
                                                          'result': {'item_id': self.card.pk}}]}

        with mock.patch('wama.common.services.resource_governor.release_in_progress',
                        return_value=False), \
                mock.patch('wama.common.services.assistant_engine.run_assistant_turn',
                           side_effect=turn):
            r = self.client.post(reverse('ai_chat'), data=json.dumps({'message': 'décris'}),
                                 content_type='application/json')
        self.assertEqual(200, r.status_code, r.content)
        self.assertEqual([], bell['during'])
        (told,) = r.json()['follow_ups']
        self.assertTrue(told['response'].startswith('✅ Describer — « témoin » terminé'))
        self.assertNotIn('job_notices', r.json())
        self.assertEqual([], self._relay(bell['note'].pk), 'racontée une fois')

    def test_the_api_contract_does_not_carry_the_internal_notice_ids(self):
        """L'API v1 rend le dict du tour : la clé interne `job_notices` n'y sort pas."""
        from unittest import mock
        with mock.patch('wama.common.services.assistant_engine.conversation_turn',
                        return_value={'response': 'Lancé.', 'job_notices': [1]}):
            r = self.client.post('/api/v1/assistant/chat/', data=json.dumps({'message': 'x'}),
                                 content_type='application/json')
        self.assertEqual(200, r.status_code, r.content)
        self.assertEqual({'response': 'Lancé.'}, r.json())

    def test_a_turn_only_carries_the_ends_of_what_it_designated(self):
        """Contre-épreuve : une fin d'un autre élément, ou d'avant le tour, n'est pas la sienne."""
        from django.utils import timezone

        from wama.common.services.job_follow_ups import notices_of_turn
        before = self._end()
        since = timezone.now()
        steps = [{'tool': 'add_to_describer', 'args': {}, 'result': {'item_id': self.card.pk}}]
        self.assertEqual([], notices_of_turn(self.user, steps, since))
        during = self._end()
        self.assertEqual([during.pk], notices_of_turn(self.user, steps, since))
        other = [{'tool': 'add_to_describer', 'args': {}, 'result': {'item_id': self.card.pk + 999}}]
        self.assertEqual([], notices_of_turn(self.user, other, since))
        self.assertNotEqual(before.pk, during.pk)

    def test_a_task_not_launched_by_the_assistant_is_left_to_the_bell(self):
        """Contre-épreuve : une card lancée depuis sa page n'a pas de fil d'origine."""
        note = self._end()
        self.assertEqual([], self._relay(note.pk))

    def test_a_task_launched_from_a_channel_is_not_told_on_the_web(self):
        """Contre-épreuve : son fil est celui du canal — la passerelle l'y raconte."""
        self._launched_from('discord')
        note = self._end()
        self.assertEqual([], self._relay(note.pk))

    def test_a_task_from_another_web_thread_is_told_there_not_in_the_chat(self):
        """Le chat montre LE fil web (clé vide) : une tâche lancée d'un fil de vérification y est
        enregistrée, sans s'afficher dans une conversation où elle n'a pas été demandée."""
        conversation = self.store.thread(self.user, surface='web', thread_key='verif-api')
        self.store.record_exchange(conversation, 'décris', {
            'response': 'Lancé.', 'tool_steps': [{'tool': 'add_to_describer', 'args': {},
                                                  'result': {'item_id': self.card.pk}}]})
        note = self._end()
        self.assertEqual([], self._relay(note.pk))
        self.assertEqual('get_describer_status',
                         conversation.turns.order_by('-pk').first().tool_steps[0]['tool'])

    def test_someone_else_s_notification_is_never_told(self):
        self._launched_from('web')
        note = self._end()
        other = User.objects.create_user('web_follow_up_other', password='x')
        self.client.force_login(other)
        self.assertEqual([], self._relay(note.pk))

    def test_the_produced_file_is_a_link_the_chat_can_follow(self):
        """Le chat ne fait des liens que des adresses http(s) : la sortie part en URL absolue."""
        from unittest import mock
        self._launched_from('web')
        note = self._end()
        with mock.patch('wama.common.services.job_follow_ups.declared_output_urls',
                        return_value=['/media/describer/1/output/témoin.txt']):
            (told,) = self._relay(note.pk)
        self.assertIn('[témoin.txt](http://testserver/media/describer/1/output/t', told['response'])


FAKE_BROWSER = r"""
var window = this;
var listeners = {};
var document = { readyState: 'complete', querySelectorAll: function () { return []; },
                 cookie: '', addEventListener: function (name, fn) { listeners[name] = fn; } };
var posted = [];
function fetch(url, options) {
  posted.push({ url: url, body: JSON.parse(options.body) });
  return Promise.resolve({ ok: true, json: function () {
    return Promise.resolve({ follow_ups: [{ notification_id: 7, response: '✅ fini', tool_steps: [] }] });
  } });
}
var told = [];
function fakeChat(name, url) {
  return { cfg: { followUpsUrl: url },
           tellFollowUp: function (f, speak) { told.push([name, f.response, speak]); } };
}
"""


class ChatListensToTheBellTest(SimpleTestCase):
    """La cloche annonce chaque relève (`wama:notifications`) ; le chat y poste les fins de tâche,
    UNE fois par relève, et les fait raconter par tous ses chats — un seul les dit (V8, fichier
    SERVI)."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(FAKE_BROWSER + source)
        ctx.eval("WamaAssistantChat.instances.push(fakeChat('accueil', '/api/ai-chat/follow-ups/'),"
                 " fakeChat('volet', '/api/ai-chat/follow-ups/'));")
        return ctx

    def _ring(self, ctx, items):
        ctx.eval("listeners['wama:notifications']({ detail: { items: %s } });" % json.dumps(items))

    @staticmethod
    def _read(ctx, name):
        return json.loads(ctx.eval('JSON.stringify(%s)' % name))

    def test_the_ends_of_tasks_are_posted_once_and_told_by_every_chat(self):
        ctx = self._ctx()
        self._ring(ctx, [{'id': 7, 'kind': 'job_done'}, {'id': 8, 'kind': 'share'},
                         {'id': 9, 'kind': 'job_failed'}])
        self.assertEqual([{'url': '/api/ai-chat/follow-ups/', 'body': {'ids': [7, 9]}}],
                         self._read(ctx, 'posted'))
        self.assertEqual([['accueil', '✅ fini', True], ['volet', '✅ fini', False]],
                         self._read(ctx, 'told'))

    def test_the_ends_carried_by_a_reply_are_written_after_it_and_said_with_it(self):
        """Fin de tâche rendue avec la réponse du tour : écrite à sa suite, sans voix propre (elle
        couperait la réponse), et son texte rendu pour être dit APRÈS la réponse."""
        ctx = self._ctx()
        ctx.eval("""
            var chat = Object.create(WamaAssistantChat._Chat.prototype);
            chat.tellFollowUp = function (f, speak) { told.push(['tour', f.response, speak]); };
            var said = chat.tellTurnFollowUps([{ response: '✅ fini' }]);
        """)
        self.assertEqual([['tour', '✅ fini', False]], self._read(ctx, 'told'))
        self.assertEqual(['✅ fini'], self._read(ctx, 'said'))
        self.assertEqual([], json.loads(ctx.eval('JSON.stringify(chat.tellTurnFollowUps(undefined))')))

    def test_a_turn_in_error_still_shows_the_ends_already_told(self):
        """Racontées au fil par la vue avant son test d'erreur : la bulle d'erreur ne les cache pas."""
        ctx = self._ctx()
        ctx.eval("""
            fetch = function () { return Promise.resolve({ json: function () {
              return Promise.resolve({ error: 'délai dépassé', follow_ups: [{ response: '✅ fini' }] });
            } }); };
            var chat = Object.create(WamaAssistantChat._Chat.prototype);
            chat.cfg = { chatUrl: '/api/ai-chat/' }; chat.lastFiles = [];
            chat.signal = function () {}; chat.stopWaiting = function () {};
            chat.feed = { appendChild: function () {} };
            chat.errorBubble = function () { return {}; };
            chat.tellFollowUp = function (f, speak) { told.push(['erreur', f.response, speak]); };
            chat.sendBlocking('x', null);
        """)
        self.assertEqual([['erreur', '✅ fini', False]], self._read(ctx, 'told'))

    def test_a_relay_without_any_end_of_task_asks_nothing(self):
        """Contre-épreuve : un partage, une alerte — rien à demander au serveur."""
        ctx = self._ctx()
        self._ring(ctx, [{'id': 8, 'kind': 'share'}])
        self.assertEqual([], self._read(ctx, 'posted'))
