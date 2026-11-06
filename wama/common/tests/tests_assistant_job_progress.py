"""The PROGRESS of a job inside the assistant's exchange (2026-10-20).

Fabien: « add the global progress bar to the assistant, directly in the exchange — the user knows
where the job stands without having to ask again for a long processing ». Nothing new is read: the
server gives each item launched by a turn in the state of its card (`tool_api.job_progress`, the
status gesture's line — live progress, place in the GPU queue), the chat follows it with
`WamaApp.Poller` in the shape of the cards' common block, and the end is told by the existing
relay (`job_follow_ups`). These tests play the real chain (real card, real thread, real views) and,
in V8, the served chat.
"""
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

# A LOCAL cache: a progress key written in the SHARED cache under a test item's id could be the
# key of a real item (`<app>_progress_<pk>`).
LOCAL_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=LOCAL_CACHE)
class JobProgressTest(TestCase):

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
        cache.clear()
        self.store = store
        self.user = User.objects.create_user('job_progress', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)
        self.lot, (self.card,) = _lot_de(Description, self.user, 1)
        self.steps = [{'tool': 'add_to_describer', 'args': {'file_path': 'x.png'},
                       'result': {'item_id': self.card.pk}}]

    def _set(self, status, progress=0):
        type(self.card).objects.filter(pk=self.card.pk).update(status=status, progress=progress)

    def test_a_running_job_is_read_like_its_card(self):
        from wama.tool_api import job_progress
        self._set('RUNNING', 40)
        cache.set(f'describer_progress_{self.card.pk}', 55)      # the live progress wins
        row = job_progress(self.user, 'describer', self.card.pk)
        self.assertEqual(('describer', self.card.pk, 'RUNNING', 55, False, False),
                         (row['family'], row['id'], row['status'], row['progress'],
                          row['terminal'], row['ok']))
        self.assertTrue(row['label'])

    def test_a_card_and_a_followed_family_write_the_same_line(self):
        """2026-11-06 : la ligne d'une card et celle d'une famille suivie (installation, run du
        Studio) s'écrivent UNE fois (`job_families.line`) — une card réussie se lit pleine, comme
        une installation finie, quel que soit le chiffre resté en base."""
        from wama.tool_api import job_progress
        self._set('SUCCESS', 40)
        row = job_progress(self.user, 'describer', self.card.pk)
        self.assertEqual(('SUCCESS', 100, True, True),
                         (row['status'], row['progress'], row['terminal'], row['ok']))

    def test_the_line_carries_the_common_preview_address_of_its_item(self):
        """2026-10-28, chantier ② de l'aperçu : la ligne de l'échange montre les faces de l'élément
        par l'aperçu COMMUN — celui du volet et de la card, jamais une adresse propre au chat."""
        from wama.tool_api import job_progress
        row = job_progress(self.user, 'describer', self.card.pk)
        self.assertEqual(reverse('common:unified_preview', args=['describer', self.card.pk]),
                         row['preview_url'])

    def test_every_followed_family_has_its_common_preview(self):
        """Les familles que l'échange suit (`TRIAD_SPECS`) sont des surfaces de l'aperçu commun :
        une famille hors registre rendrait une adresse vide, et sa ligne n'aurait aucune face."""
        from wama.common.utils.detail_registry import DetailRegistry
        from wama.tool_api import TRIAD_SPECS
        self.assertEqual([], sorted(set(TRIAD_SPECS) - set(DetailRegistry.registered_apps())))

    def test_without_a_declared_name_the_label_is_the_common_readable_name(self):
        """A line that declares no `name` (most declare `filename` or `prompt`): the label is the
        common rule of an element's readable name (`batch_views.element_label`)."""
        from wama import tool_api
        from wama.common.utils.batch_views import element_label
        spec = dict(tool_api.TRIAD_SPECS['describer'])
        spec['status_fields'] = {k: v for k, v in spec['status_fields'].items() if k != 'name'}
        with mock.patch.dict(tool_api.TRIAD_SPECS, {'describer': spec}):
            row = tool_api.job_progress(self.user, 'describer', self.card.pk)
        self.assertTrue(element_label(self.card))
        self.assertEqual(element_label(self.card), row['label'])

    def test_an_item_of_someone_else_or_an_unknown_family_is_not_read(self):
        from wama.tool_api import job_progress
        other = User.objects.create_user('job_progress_other', password='x')
        self.assertIsNone(job_progress(other, 'describer', self.card.pk))
        self.assertIsNone(job_progress(self.user, 'no_such_family', self.card.pk))
        self.assertIsNone(job_progress(self.user, 'describer', 'abc'))

    def test_the_status_gesture_reads_the_same_line(self):
        """The line moved out of `_status` (`_status_row`): the status tool still gives it."""
        from wama.tool_api import execute_tool
        self._set('RUNNING', 30)
        jobs = execute_tool('get_describer_status', {}, self.user)['jobs']
        self.assertEqual([(self.card.pk, 'RUNNING', 30)],
                         [(j['id'], j['status'], j['progress']) for j in jobs])

    def _turn(self, steps):
        reply = {'response': 'Lancé.', 'tool_steps': steps, 'model': 'test'}
        with mock.patch('wama.common.services.assistant_engine.conversation_turn',
                        return_value=dict(reply)):
            return self.client.post(reverse('ai_chat'), data=json.dumps({'message': 'go'}),
                                    content_type='application/json').json()

    def test_the_turn_reply_carries_its_jobs_while_they_run(self):
        self._set('RUNNING', 10)
        data = self._turn(self.steps)
        self.assertEqual([('describer', self.card.pk)], [(j['family'], j['id']) for j in data['jobs']])

    def test_a_job_faster_than_the_reply_keeps_its_line_on_its_output(self):
        """2026-11-04 (Fabien): a job over before the reply ends (an image, a conversion) had no
        line, so no preview at all — the faster the job, the less was seen. Its line is now given,
        terminal, and the chat opens it on the output face."""
        self._set('SUCCESS', 100)
        (job,) = self._turn(self.steps)['jobs']
        self.assertEqual((self.card.pk, True, True), (job['id'], job['terminal'], job['ok']))
        self.assertTrue(job['preview_url'])
        # Counter-check: a status read designates nothing, so it carries no line.
        self.assertNotIn('jobs', self._turn([{'tool': 'get_describer_status', 'args': {},
                                              'result': {'jobs': []}}]))

    @mock.patch('celery.app.task.Task.apply_async', return_value=mock.Mock(id='no-task'))
    def test_a_launched_batch_gives_the_line_of_each_child_card(self, _no_task):
        """2026-11-04 (Fabien: « dérouler le processus pour les cards filles d'un lot ») : the ▶ of
        a batch, played by the assistant, designates its launched children in the surface its
        domain declares (`audio_enhancer` for an audio batch of the enhancer, whose cards are not
        `enhancer` ones), and its end is told in the thread. Since 2026-11-05 a launched batch is
        ONE line, numbered by its batch — this assertion compared it to the child's number and
        held only when both happened to be equal (seen 2026-11-06 in a wider run: lot 7, card 2)."""
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        from wama.common.services.job_follow_ups import origin_conversation, turn_jobs
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.common.utils.preview_registry import PreviewRegistry
        from wama.tool_api import execute_tool
        for role in (DEFAULT_APP_ACCESS.get('enhancer') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        audio_lot, (audio_card,) = _lot_de(PreviewRegistry.get_model('audio_enhancer'), self.user, 1)
        steps = []
        for app, lot in (('describer', self.lot), ('audio_enhancer', audio_lot)):
            args = {'app': app, 'batch_id': lot.pk}
            steps.append({'tool': 'launch_batch', 'args': args,
                          'result': execute_tool('launch_batch', args, self.user)})
            self.assertTrue(steps[-1]['result'].get('ids'), steps[-1])
        self.assertEqual([('batch', 'audio_enhancer', audio_lot.pk), ('batch', 'describer', self.lot.pk)],
                         [(j['kind'], j['family'], j['id']) for j in turn_jobs(self.user, steps)])
        self.assertEqual({audio_card.pk}, {c['id'] for c in turn_jobs(self.user, steps)[0]['items']})
        conversation = self.store.thread(self.user, surface='web')
        self.store.record_exchange(conversation, 'lance mes lots',
                                   {'response': 'Lancés.', 'tool_steps': steps})
        note = mock.Mock(app='audio_enhancer', object_type=type(audio_card).__name__,
                         object_id=str(audio_card.pk), recipient_id=self.user.pk)
        self.assertEqual(conversation.pk, origin_conversation(note, 'web').pk)

    def test_the_jobs_endpoint_reads_each_item_of_the_user_only(self):
        self._set('PENDING')
        r = self.client.get(reverse('ai_chat_jobs'),
                            {'items': f'describer:{self.card.pk},describer:999999,nope:1,bad'})
        self.assertEqual(200, r.status_code)
        self.assertEqual([self.card.pk], [j['id'] for j in r.json()['jobs']])
        self.client.logout()
        self.assertEqual(401, self.client.get(reverse('ai_chat_jobs')).status_code)

    def test_the_thread_gives_back_the_line_of_a_job_running_or_over(self):
        """On reload, a result keeps its line (2026-11-04): before, only a job still running got
        its bar back, and the history showed text where an output had been produced."""
        from wama.views import _chat_thread
        conversation = self.store.thread(self.user, surface='web')
        self.store.record_exchange(conversation, 'décris ce fichier',
                                   {'response': 'Lancé.', 'tool_steps': self.steps})
        self._set('RUNNING', 20)
        (answer,) = [e for e in _chat_thread(self.user) if e['type'] == 'assistant']
        self.assertEqual([(self.card.pk, False)], [(j['id'], j['terminal']) for j in answer['jobs']])
        self._set('FAILURE')
        (answer,) = [e for e in _chat_thread(self.user) if e['type'] == 'assistant']
        self.assertEqual([(self.card.pk, True)], [(j['id'], j['terminal']) for j in answer['jobs']])
        # Counter-check: an item deleted since has no line left.
        type(self.card).objects.filter(pk=self.card.pk).delete()
        (answer,) = [e for e in _chat_thread(self.user) if e['type'] == 'assistant']
        self.assertNotIn('jobs', answer)


@override_settings(CACHES=LOCAL_CACHE)
class LaunchedBatchTest(TestCase):
    """2026-11-05 (Fabien: « mettre à jour la barre de progression de lot et à la fin de chaque card
    fille remplacer la preview par la suivante […] aller jusqu'au bout d'un lot sans surcharger le
    fil de discussion ») : a launched batch is ONE line of the exchange — the state of its batch card,
    its children shown one at a time — and ONE end in the thread, whatever its size."""

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        from wama.common.services import conversation_store as store
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.describer.models import Description
        from wama.tool_api import execute_tool
        self.root = tempfile.mkdtemp()
        media_root = override_settings(MEDIA_ROOT=self.root)
        media_root.enable()
        self.addCleanup(media_root.disable)
        self.addCleanup(shutil.rmtree, self.root, True)
        cache.clear()
        self.store = store
        self.user = User.objects.create_user('batch_progress', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)
        self.lot, self.cards = _lot_de(Description, self.user, 3)
        args = {'app': 'describer', 'batch_id': self.lot.pk}
        with mock.patch('celery.app.task.Task.apply_async', return_value=mock.Mock(id='no-task')):
            self.steps = [{'tool': 'launch_batch', 'args': args,
                           'result': execute_tool('launch_batch', args, self.user)}]
        self.assertTrue(self.steps[0]['result'].get('started'), self.steps)

    def _set(self, card, status, progress=0, error=''):
        type(card).objects.filter(pk=card.pk).update(status=status, progress=progress,
                                                     error_message=error)

    def test_a_launched_batch_is_one_line_carrying_its_children(self):
        from wama.common.services.job_follow_ups import turn_jobs
        one, two, three = self.cards
        self._set(one, 'SUCCESS', 100)
        self._set(two, 'RUNNING', 40)
        self._set(three, 'RUNNING')
        (row,) = turn_jobs(self.user, self.steps)
        self.assertEqual(('batch', 'describer', self.lot.pk), (row['kind'], row['family'], row['id']))
        self.assertEqual([one.pk, two.pk, three.pk], [c['id'] for c in row['items']],
                         'the children, in the order of the lines, and no line of their own')
        self.assertEqual([reverse('common:unified_preview', args=['describer', c.pk]) for c in self.cards],
                         [c['preview_url'] for c in row['items']])
        # The bar of the batch card (`_batch_card.html`): finished / total, not a mean of progress.
        self.assertEqual((1, 3, 33, False), (row['counts']['success'], row['total'], row['progress'],
                                             row['terminal']))
        self.assertTrue(row['label'])
        self.assertTrue(row['download_url'], 'one result: the ZIP of the batch card')
        self.assertEqual('/describer/', row['page_url'])
        # Counter-check: nothing finished yet, no ZIP to give.
        self._set(one, 'RUNNING')
        self.assertEqual('', turn_jobs(self.user, self.steps)[0]['download_url'])

    def test_a_child_never_launched_does_not_hold_the_end_of_the_batch(self):
        from wama.tool_api import batch_progress
        one, two, three = self.cards
        self._set(one, 'SUCCESS', 100)
        self._set(two, 'FAILURE', error='boom')
        self._set(three, 'PENDING')
        row = batch_progress(self.user, 'describer', self.lot.pk)
        self.assertEqual((True, False), (row['terminal'], row['ok']))
        # Counter-check: waiting for the GPU is moving, not over.
        self._set(three, 'AWAITING_RESOURCES')
        self.assertFalse(batch_progress(self.user, 'describer', self.lot.pk)['terminal'])

    def test_the_queue_of_a_family_is_the_page_of_the_app_carrying_it(self):
        """One rule (`journal.family_queue_url`) for the link of a notification and the exchange:
        a surface is a tab of the app carrying its model, a Lab app has its own page — the old
        fallback of the notification (`/<package>/`) linked `/cam_analyzer/`, a page that is not."""
        from django.apps import apps
        from wama.common.services.journal import app_queue_url, family_queue_url
        from wama.common.utils.notifications import _job_url
        self.assertEqual('/enhancer/', family_queue_url('audio_enhancer'))
        lab_model = next(iter(apps.get_app_config('cam_analyzer').get_models()))
        self.assertEqual(app_queue_url('cam_analyzer'), family_queue_url('', lab_model))
        self.assertNotEqual('/cam_analyzer/', family_queue_url('', lab_model))
        self.assertEqual('/describer/', _job_url(self.cards[0], 'describer'))

    def test_the_jobs_endpoint_follows_a_launched_batch_of_the_user_only(self):
        r = self.client.get(reverse('ai_chat_jobs'), {'items': f'batch:describer:{self.lot.pk}'})
        self.assertEqual([('batch', self.lot.pk)], [(j['kind'], j['id']) for j in r.json()['jobs']])
        self.client.force_login(User.objects.create_user('batch_progress_other', password='x'))
        r = self.client.get(reverse('ai_chat_jobs'), {'items': f'batch:describer:{self.lot.pk}'})
        self.assertEqual([], r.json()['jobs'])

    def test_beyond_the_followed_lines_one_line_says_how_many_more(self):
        """1a (2026-11-05): « tout lancer » on a queue of 22 showed 20 lines and was silent on the
        two others — they run, the reply now says so and leads to their queue."""
        from wama.common.services.job_follow_ups import TURN_JOBS_MAX, turn_jobs
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.describer.models import Description
        _lot, cards = _lot_de(Description, self.user, TURN_JOBS_MAX + 2)
        ids = [c.pk for c in cards]
        rows = turn_jobs(self.user, [{'tool': 'start_describer', 'args': {},
                                      'result': {'status': 'started', 'ids': ids}}])
        self.assertEqual(TURN_JOBS_MAX, len([r for r in rows if 'kind' not in r]))
        self.assertEqual([{'kind': 'more', 'family': 'describer', 'count': 2, 'terminal': True,
                           'page_url': '/describer/'}], [r for r in rows if r.get('kind') == 'more'])
        # Counter-check: exactly the followed number, nothing more to say.
        rows = turn_jobs(self.user, [{'tool': 'start_describer', 'args': {},
                                      'result': {'status': 'started', 'ids': ids[:TURN_JOBS_MAX]}}])
        self.assertEqual([], [r for r in rows if r.get('kind') == 'more'])

    def _notice(self, card, ok=True):
        from wama.common.models import Notification
        from wama.common.utils.notifications import notify_in_app
        notify_in_app([self.user], 'job_done' if ok else 'job_failed',
                      f"Describer — « {card.pk} » {'terminé' if ok else 'a échoué'}",
                      app='describer', item=card)
        return Notification.objects.filter(recipient=self.user).latest('pk').pk

    def test_the_end_of_a_launched_batch_is_told_once_when_nothing_moves_any_more(self):
        from wama.common.models import ConversationTurn
        from wama.common.services.job_follow_ups import NOTICE_PREFIX, outputs_to_join, web_follow_ups
        from wama.common.models import Notification
        conversation = self.store.thread(self.user, surface='web')
        self.store.record_exchange(conversation, 'lance le lot',
                                   {'response': 'Lancé.', 'tool_steps': self.steps})
        one, two, three = self.cards
        for card in self.cards:
            self._set(card, 'RUNNING')
        self._set(one, 'SUCCESS', 100)
        notes = [self._notice(one)]
        self.assertEqual([], web_follow_ups(self.user, notes), 'a child ends: the batch still moves')
        self._set(two, 'FAILURE', error='boom')
        notes.append(self._notice(two, ok=False))
        self.assertEqual([], web_follow_ups(self.user, notes[1:]))
        self._set(three, 'SUCCESS', 100)
        notes.append(self._notice(three))
        (told,) = web_follow_ups(self.user, notes[2:])
        self.assertEqual('get_batch_result', told['tool_steps'][0]['tool'],
                         'the end of a batch rests on the tool really played')
        text = told['response']
        self.assertTrue(text.startswith('⚠ Describer — lot «'), text)
        self.assertIn('2 terminé(s), 1 en échec, sur 3.', text)
        self.assertIn(': boom', text, 'the failed child is named with its error')
        self.assertIn('Télécharger le lot (ZIP)](http', text)
        self.assertIn("Ouvrir le lot dans l'app](http", text)
        # Told once, whatever relays the notifications again (another tab, the turn's own end).
        self.assertEqual([], web_follow_ups(self.user, notes))
        self.assertEqual(1, ConversationTurn.objects.filter(
            conversation=conversation, role='user', content__startswith=NOTICE_PREFIX).count())
        # A channel joins no file of the last child to the end of the batch: its ZIP is a link —
        # while the end of an element alone keeps joining its outputs.
        last = Notification.objects.get(pk=notes[2])
        with mock.patch('wama.common.services.job_follow_ups.declared_output_urls',
                        return_value=['/media/out.png']):
            self.assertEqual([], outputs_to_join(last, told['tool_steps'][0]))
            self.assertEqual(['/media/out.png'],
                             outputs_to_join(last, {'tool': 'get_describer_status'}))

    def test_a_child_started_alone_keeps_its_own_end(self):
        """Counter-check: the batch path is taken for a child of a batch LAUNCHED by the turn only —
        a card of a batch started on its own is told as before."""
        from wama.common.services.job_follow_ups import web_follow_ups
        from wama.tool_api import primary_arg_name
        one = self.cards[0]
        conversation = self.store.thread(self.user, surface='web')
        self.store.record_exchange(conversation, 'lance le lot',
                                   {'response': 'Lancé.', 'tool_steps': self.steps})
        self.store.record_exchange(conversation, 'relance la première', {'response': 'Relancée.', 'tool_steps': [
            {'tool': 'start_describer', 'args': {primary_arg_name('start_describer'): one.pk},
             'result': {'status': 'started'}}]})
        self._set(one, 'SUCCESS', 100)
        (told,) = web_follow_ups(self.user, [self._notice(one)])
        self.assertEqual('get_describer_status', told['tool_steps'][0]['tool'])
        self.assertIn(f'« {one.pk} » terminé', told['response'])


#: A served chat without a browser: elements answering the selectors the chat uses, a Poller that
#: records what it follows, and a bell that counts its relays. The states' label and colour are
#: `WamaApp`'s (marked, so that a table written again in the chat shows); the queue chip is the
#: SERVED `wama-schedule.js`'s, loaded after this fake (`document.readyState` 'loading': it does
#: not start reading the queue).
FAKE_BROWSER = r"""
var window = this;
var document = { readyState: 'loading', querySelectorAll: function () { return []; },
                 querySelector: function () { return null; },
                 createElement: function () { return el(); },
                 cookie: '', addEventListener: function () {} };
var checked = 0, stopped = [], started = [], pollerCfg = null;
window.WamaApp = {
  checkNotifications: function () { checked++; },
  statusLabel: function (s) { return 'label:' + s; },
  statusBadge: function (s) { return 'badge:' + s; },
  Poller: function (cfg) {
    pollerCfg = cfg;
    this.start = function (id) { started.push(id); };
    this.stop = function (id) { stopped.push(id); };
    this.stopAll = function () {};
  },
};
function setTimeout(fn) { fn(); }
function setInterval() {}
function el() {
  var classes = {};
  return { className: '', textContent: '', innerHTML: '', style: {}, dataset: {},
           classList: { toggle: function (c, on) { classes[c] = !!on; },
                        remove: function (c) { classes[c] = false; } },
           has: function (c) { return !!classes[c]; } };
}
function fakeRow(key) {
  var row = el();
  row.dataset.jobKey = key;
  row.parts = { '.status-badge': el(), '.progress-text': el(), '.wama-progress-fill': el(),
                '.wama-eta': null, '.wama-queue-chip': null };
  row.querySelector = function (s) { return this.parts[s]; };
  row.appendChild = function (child) {
    var parts = this.parts;
    parts['.wama-queue-chip'] = child;
    child.remove = function () { parts['.wama-queue-chip'] = null; };
  };
  return row;
}
function fakeBlock(rows) {
  return { isConnected: true, dataset: { jobsBlock: '1' },
           querySelector: function (sel) {
             var key = sel.match(/data-job-key="([^"]+)"/)[1];
             return rows.filter(function (r) { return r.dataset.jobKey === key; })[0] || null; },
           querySelectorAll: function (sel) {
             return rows.filter(function (r) {
               return sel.indexOf(':not') === -1 || r.dataset.terminal !== '1'; }); } };
}
"""


def common_paint(served) -> str:
    """The SERVED common painter of a progress block (`WamaApp.paintProgress`,
    `progressBlockHtml` — 2026-11-06, extracted from the chat) grafted onto the fake `WamaApp`: the
    real brick paints, and it still reads the state's label and colour on `WamaApp`, so the fake's
    markers keep proving that no table is written again."""
    return ("var __fake = window.WamaApp;\n"
            + (served / 'wama-app-base.js').read_text(encoding='utf-8')
            + "\n__fake.paintProgress = window.WamaApp.paintProgress;"
              "\n__fake.progressBlockHtml = window.WamaApp.progressBlockHtml;"
              "\nwindow.WamaApp = __fake;")


class ChatFollowsTheJobsTest(SimpleTestCase):
    """The served chat paints each job like its card and stops following once all are over, asking
    the bell for its relay at the moment one ends (V8)."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        served = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
        ctx = MiniRacer()
        ctx.eval(FAKE_BROWSER)
        ctx.eval(common_paint(served))
        for name in ('wama-schedule.js', 'wama-assistant-chat.js'):
            ctx.eval((served / name).read_text(encoding='utf-8'))
        ctx.eval("""
            var chat = Object.create(WamaAssistantChat._Chat.prototype);
            chat.cfg = { jobsUrl: '/api/ai-chat/jobs/' };
            var a = fakeRow('describer:1'), b = fakeRow('describer:2');
            var block = fakeBlock([a, b]);
            chat.followJobs(block);
        """)
        return ctx

    def _read(self, ctx, expr):
        return json.loads(ctx.eval('JSON.stringify(%s)' % expr))

    def test_a_waiting_job_carries_the_queue_chip_of_its_card_and_a_running_one_moves(self):
        ctx = self._ctx()
        ctx.eval("""chat.updateJobs('1', [
            {family: 'describer', id: 1, status: 'PENDING', progress: 0, terminal: false,
             queue: {state: 'queued', ahead: 3, expectedStart: '2026-10-20T10:00:00',
                     expectedEnd: '2026-10-20T10:05:00', durationSource: 'measured'}},
            {family: 'describer', id: 2, status: 'RUNNING', progress: 42, terminal: false,
             queue: {state: 'running', ahead: 0}}]);""")
        # The state's label and colour are WamaApp's, never a table of the chat.
        self.assertEqual(['label:PENDING', 'badge status-badge badge:PENDING'], self._read(
            ctx, "[a.parts['.status-badge'].textContent, a.parts['.status-badge'].className]"))
        chip = self._read(ctx, "a.parts['.wama-queue-chip'] && a.parts['.wama-queue-chip'].innerHTML")
        self.assertIn('En file · 3 tâches avant', chip or '', 'the chip of the card (WamaSchedule)')
        self.assertIsNone(self._read(ctx, "b.parts['.wama-queue-chip']"),
                          'a running entry has no queue chip, like on its card')
        self.assertEqual(['42%', '42%', True], self._read(
            ctx, "[b.parts['.progress-text'].textContent, b.parts['.wama-progress-fill'].style.width,"
                 " b.parts['.wama-progress-fill'].has('active')]"))
        self.assertEqual([], self._read(ctx, 'stopped'), 'still running: still followed')
        self.assertEqual(0, self._read(ctx, 'checked'))
        # Once it runs, its chip goes.
        ctx.eval("""chat.updateJobs('1', [
            {family: 'describer', id: 1, status: 'RUNNING', progress: 5, terminal: false,
             queue: {state: 'running', ahead: 0}}]);""")
        self.assertIsNone(self._read(ctx, "a.parts['.wama-queue-chip']"))

    def test_the_end_of_every_job_stops_the_follow_and_asks_the_bell(self):
        ctx = self._ctx()
        ctx.eval("""chat.updateJobs('1', [
            {family: 'describer', id: 1, status: 'SUCCESS', progress: 100, terminal: true, ok: true},
            {family: 'describer', id: 2, status: 'FAILURE', progress: 12, terminal: true, ok: false}]);""")
        self.assertEqual(['1'], self._read(ctx, 'stopped'))
        self.assertEqual(1, self._read(ctx, 'checked'), 'the relay is asked once, at the end')
        self.assertEqual(['label:SUCCESS', '100%', 'label:FAILURE'], self._read(
            ctx, "[a.parts['.status-badge'].textContent, a.parts['.progress-text'].textContent,"
                 " b.parts['.status-badge'].textContent]"))

    def test_the_follow_never_gives_up_but_stops_for_a_block_gone(self):
        """2026-11-06 : a bar of WAMA never gives up (`wama-global-progress.js`) — with the default
        of ten failed turns, a server restart froze the lines of the exchange for good. A block
        removed from the thread is no longer followed, the server answering or not."""
        ctx = self._ctx()
        self.assertTrue(self._read(ctx, 'pollerCfg.maxFails === Infinity'))
        ctx.eval("pollerCfg.onError('1', new Error('HTTP 502'));")
        self.assertEqual([], self._read(ctx, 'stopped'), 'a server restart is waited out')
        ctx.eval("block.isConnected = false; pollerCfg.onError('1', new Error('HTTP 502'));")
        self.assertEqual(['1'], self._read(ctx, 'stopped'))

    def test_a_job_line_mounts_the_common_face_viewer_at_its_preview_address(self):
        """2026-10-28 (Fabien : « intégrer la preview dans l'échange […] entrée/during/comparaison/
        sortie ») : the line mounts THE face viewer of the side panel (`WamaMediaPreview.faceViewer`),
        never a renderer of its own, and nothing without an address."""
        ctx = self._ctx()
        out = self._read(ctx, """(function () {
            var mounted = [];
            window.WamaMediaPreview = {faceViewer: function (host, url, opts) {
              var v = {host: host, url: url, opts: opts, refreshed: 0};
              v.refresh = function () { v.refreshed++; };
              mounted.push(v); return v; }};
            var row = el(); row.children = [];
            row.appendChild = function (c) { row.children.push(c); };
            row.dataset.jobStatus = 'RUNNING';
            chat.mountFaces(row, {preview_url: '/common/preview/describer/1/'});
            var bare = el(); bare.children = [];
            bare.appendChild = function (c) { bare.children.push(c); };
            chat.mountFaces(bare, {});
            var v = mounted[0];
            return [mounted.length, v.url, v.host.className, row.children.length, v.refreshed,
                    v.opts.compact, v.opts.status(), bare.children.length];
        })()""")
        self.assertEqual([1, '/common/preview/describer/1/', 'wcv3-preview wama-assistant-job-preview',
                          1, 1, True, 'RUNNING', 0], out)

    def test_a_new_job_line_carries_its_faces(self):
        """The line the chat BUILDS for a job mounts the faces (not only the helper called alone)."""
        ctx = self._ctx()
        out = self._read(ctx, """(function () {
            var mounted = [];
            window.WamaMediaPreview = {faceViewer: function (host, url) {
              mounted.push(url); return {refresh: function () {}}; }};
            function part() { var p = el(); p.remove = function () {}; return p; }
            document.createElement = function () {
              var r = el(); r.children = [];
              r.appendChild = function (c) { r.children.push(c); };
              r.querySelector = function () { return part(); };
              return r; };
            var row = chat.jobRow({family: 'describer', id: 3, status: 'RUNNING', progress: 0,
                                   terminal: false, label: 'photo.png',
                                   preview_url: '/common/preview/describer/3/'});
            return [mounted, row.children.length, row.dataset.jobStatus];
        })()""")
        self.assertEqual([['/common/preview/describer/3/'], 1, 'RUNNING'], out)

    def test_every_change_of_state_replays_the_default_face(self):
        """Waiting → running : the PENDING face is followed ; running → done : the output — also for
        an app that publishes nothing while it computes (its follower stops without an end)."""
        ctx = self._ctx()
        out = self._read(ctx, """(function () {
            var refreshed = 0;
            a._faces = {refresh: function () { refreshed++; }};
            var seen = [];
            [['PENDING', false], ['PENDING', false], ['RUNNING', false], ['RUNNING', false],
             ['SUCCESS', true]].forEach(function (s) {
              chat.paintJob(a, {family: 'describer', id: 1, status: s[0], progress: 0,
                                terminal: s[1], ok: s[1]});
              seen.push(refreshed);
            });
            return seen;
        })()""")
        self.assertEqual([0, 0, 1, 1, 2], out, 'the first paint and an unchanged state replay nothing')

    def _block_of(self, ctx, jobs):
        """Builds the block of a reply with the served `jobsBlock`; gives what the Poller started."""
        return self._read(ctx, """(function () {
            started.length = 0;
            function part() { var p = el(); p.remove = function () {}; return p; }
            document.createElement = function () {
              var r = el();
              r.appendChild = function () {};
              r.querySelector = function () { return part(); };
              return r; };
            chat.jobsBlock(%s);
            return started;
        })()""" % json.dumps(jobs))

    def test_a_block_already_over_shows_its_lines_without_following_them(self):
        """2026-11-04: a reply's block may hold items already over (faster than the reply, or a
        reloaded thread). They are shown, and nothing polls the server for them."""
        ctx = self._ctx()
        over = {'family': 'describer', 'id': 4, 'status': 'SUCCESS', 'progress': 100,
                'terminal': True, 'ok': True}
        self.assertEqual([], self._block_of(ctx, [over]))
        running = dict(over, id=5, status='RUNNING', progress=10, terminal=False, ok=False)
        self.assertEqual(1, len(self._block_of(ctx, [over, running])), 'one running: followed')

    def test_the_links_the_reply_checks_are_the_links_it_makes_clickable(self):
        """2026-11-04: the status gives RELATIVE `/media/` addresses, the reply writes them as
        `[📥 Télécharger](/media/…)`, and the chat only linked http(s) — the user read raw
        Markdown. The chat links what `assistant_engine._URL_IN_TEXT` checks, nothing else."""
        ctx = self._ctx()

        def html(text):
            return self._read(ctx, 'WamaAssistantChat._toHtml(%s)' % json.dumps(text))

        self.assertEqual('<a href="/media/users/1/out.png" target="_blank" rel="noopener">📥 Télécharger</a>',
                         html('[📥 Télécharger](/media/users/1/out.png)'))
        self.assertIn('<a href="https://wama.example/media/a.txt"', html('[a](https://wama.example/media/a.txt)'))
        # Counter-checks: an address the check does not see, or one that would leave the attribute.
        self.assertNotIn('<a ', html('[x](/transcriber/download/1/)'))
        self.assertNotIn('<a ', html('[x](javascript:alert(1))'))
        self.assertNotIn('<a ', html('[x](/media/a" onmouseover="alert(1))'))
        self.assertNotIn('<a ', html('[x](https://a.example/" onmouseover="alert(1))'))

    def test_the_chat_links_with_the_address_pattern_of_the_reply_check(self):
        """One list of what an address is, declared by the reply check (`_URL_IN_TEXT`); the chat
        keeps a copy that must stay equal — a laxer copy would link what the check never saw."""
        import re
        from wama.common.services.assistant_engine import _URL_IN_TEXT
        js = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
              / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        copy = re.search(r"var LINK = /\\\[\(\[\^\\\]\]\+\)\\\]\\\(\((.+)\)\\\)/g;", js).group(1)
        self.assertEqual(_URL_IN_TEXT.pattern.replace("\\'", "'"), copy.replace('\\/', '/'))

    def test_an_item_no_longer_served_stops_and_says_so(self):
        ctx = self._ctx()
        ctx.eval("""chat.updateJobs('1', [
            {family: 'describer', id: 1, status: 'SUCCESS', progress: 100, terminal: true, ok: true}]);""")
        self.assertEqual('Introuvable', self._read(ctx, "b.parts['.status-badge'].textContent"))
        self.assertEqual(['1'], self._read(ctx, 'stopped'))


#: A batch line answering the selectors `paintBatch`/`showChild` use, a list whose options are
#: cleared like a real one, and a face viewer that records what it mounts.
FAKE_BATCH = r"""
var mounted = [];
window.WamaMediaPreview = {
  releaseMedia: function () {},
  faceViewer: function (host, url, opts) {
    var v = {url: url, opts: opts, refreshed: 0, stopped: 0};
    v.refresh = function () { v.refreshed++; };
    v.stop = function () { v.stopped++; };
    mounted.push(v); return v; }};
document.createElement = function () { return el(); };
function fakeBatchRow(key) {
  var row = el();
  row.dataset.jobKey = key;
  var list = el();
  list.options = [];
  list.appendChild = function (o) { list.options.push(o); };
  Object.defineProperty(list, 'innerHTML', {set: function () { list.options = []; }, get: function () { return ''; }});
  var parts = {'.wama-assistant-batch-child': list};
  ['.status-badge', '.progress-text', '[data-batch-field="success_count"]', '[data-batch-field="running_count"]',
   '[data-batch-field="failure_count"]', '[data-batch-field="total"]', '.wama-progress-fill', '.wama-eta',
   '.wama-assistant-batch-zip', '.wama-assistant-batch-page', '.wama-assistant-batch-follow',
   '[data-batch-step="-1"]', '[data-batch-step="1"]', '.wama-assistant-job-preview'].forEach(function (s) {
    parts[s] = el(); });
  var shows = ['success_count', 'running_count', 'failure_count'].map(function (k) {
    var s = el(); s.dataset.batchShow = k; return s; });
  row.parts = parts;
  row.querySelector = function (s) { return parts[s]; };
  row.querySelectorAll = function (s) { return s === '[data-batch-show]' ? shows : []; };
  row._batch = {family: 'describer', follow: true, shown: null, children: {}, order: []};
  return row;
}
function child(id, status) {
  return {id: id, label: 'f' + id + '.png', status: status, progress: status === 'SUCCESS' ? 100 : 10,
          terminal: status === 'SUCCESS' || status === 'FAILURE', ok: status === 'SUCCESS',
          preview_url: '/common/preview/describer/' + id + '/'};
}
function batch(statuses, terminal) {
  var items = statuses.map(function (s, i) { return child(i + 1, s); });
  var count = function (s) { return statuses.filter(function (x) { return x === s; }).length; };
  return {kind: 'batch', family: 'describer', id: 9, label: 'Lot', status: terminal ? 'FAILURE' : 'RUNNING',
          terminal: terminal, total: items.length,
          counts: {success: count('SUCCESS'), running: count('RUNNING'), failure: count('FAILURE')},
          progress: Math.round(100 * count('SUCCESS') / items.length), items: items,
          download_url: count('SUCCESS') ? '/describer/batch/9/download/' : '', page_url: '/describer/'};
}
"""


class ChatShowsALaunchedBatchTest(SimpleTestCase):
    """2026-11-05 : the served chat shows a launched batch as ONE line — the bar and counts of its
    batch card, ONE preview (the common face viewer, all its faces) that follows the last child over,
    a list and ◀ ▶ to choose a child, the ZIP and the batch in the app (V8)."""

    _ctx = ChatFollowsTheJobsTest._ctx
    _read = ChatFollowsTheJobsTest._read

    def _batch_ctx(self):
        ctx = self._ctx()
        ctx.eval(FAKE_BATCH)
        served = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
        ctx.eval((served / 'wama-eta.js').read_text(encoding='utf-8'))
        ctx.eval("var row = fakeBatchRow('batch:describer:9'); chat.jobBlocks['1'] = fakeBlock([row]);")
        return ctx

    def test_the_preview_follows_the_last_child_over_until_a_child_is_chosen(self):
        ctx = self._batch_ctx()
        ctx.eval("chat.paintBatch(row, batch(['SUCCESS', 'RUNNING', 'RUNNING'], false));")
        self.assertEqual(['/common/preview/describer/1/'], self._read(ctx, 'mounted.map(function (v) { return v.url; })'),
                         'nothing over yet but the first: its faces')
        # The bar and counts of the batch card; the ETA is the batch ticker's (`data-eta-ids`).
        self.assertEqual(['1/3', '33%', '1', '2', '0', '3', True, 'chat:describer:1,chat:describer:2,chat:describer:3'],
                         self._read(ctx, """[row.parts['.progress-text'].textContent,
                             row.parts['.wama-progress-fill'].style.width,
                             String(row.parts['[data-batch-field="success_count"]'].textContent),
                             String(row.parts['[data-batch-field="running_count"]'].textContent),
                             String(row.parts['[data-batch-field="failure_count"]'].textContent),
                             String(row.parts['[data-batch-field="total"]'].textContent),
                             row.querySelectorAll('[data-batch-show]')[2].hidden,
                             row.parts['.wama-eta'].dataset.etaIds]"""))
        self.assertEqual(['f1.png · label:SUCCESS', 'f2.png · label:RUNNING', 'f3.png · label:RUNNING'],
                         self._read(ctx, "row.parts['.wama-assistant-batch-child'].options.map(function (o) { return o.textContent; })"))
        # A child ends: its preview REPLACES the previous one.
        ctx.eval("chat.updateJobs('1', [batch(['SUCCESS', 'SUCCESS', 'RUNNING'], false)]);")
        self.assertEqual(['/common/preview/describer/1/', '/common/preview/describer/2/'],
                         self._read(ctx, 'mounted.map(function (v) { return v.url; })'))
        self.assertEqual(1, self._read(ctx, 'mounted[0].stopped'), 'the previous viewer stops')
        # The user chooses the first: the follow stops, the next end does not move the preview.
        ctx.eval("chat.showChild(row, 1, false);")
        ctx.eval("chat.updateJobs('1', [batch(['SUCCESS', 'SUCCESS', 'FAILURE'], true)]);")
        self.assertEqual('/common/preview/describer/1/', self._read(ctx, 'mounted[mounted.length - 1].url'))
        self.assertEqual([False, '1'], self._read(
            ctx, "[row.parts['.wama-assistant-batch-follow'].hidden, row.parts['.wama-assistant-batch-child'].value]"))
        # The viewer walks the children like the cards of a queue.
        self.assertEqual({'urls': ['/common/preview/describer/1/', '/common/preview/describer/2/',
                                   '/common/preview/describer/3/'], 'index': 0},
                         self._read(ctx, """(function () { var s = mounted[mounted.length - 1].opts.sequence();
                                            return {urls: s.urls, index: s.index}; })()"""))
        # Over: the follow stops and the bell is asked once — the end of the batch is told then.
        self.assertEqual((['1'], 1), (self._read(ctx, 'stopped'), self._read(ctx, 'checked')))
        self.assertEqual(['/describer/batch/9/download/', False, '/describer/', True, ''], self._read(
            ctx, """[row.parts['.wama-assistant-batch-zip'].href, row.parts['.wama-assistant-batch-zip'].hidden,
                     row.parts['.wama-assistant-batch-page'].href, row.parts['.wama-progress-fill'].has('is-frozen'),
                     row.parts['.wama-eta'].dataset.etaIds]"""))

    def test_the_preview_shows_the_child_that_ended_last_not_the_last_of_the_list(self):
        ctx = self._batch_ctx()
        ctx.eval("chat.paintBatch(row, batch(['RUNNING', 'RUNNING', 'SUCCESS'], false));")
        ctx.eval("chat.paintBatch(row, batch(['SUCCESS', 'RUNNING', 'SUCCESS'], false));")
        self.assertEqual(['/common/preview/describer/3/', '/common/preview/describer/1/'],
                         self._read(ctx, 'mounted.map(function (v) { return v.url; })'))

    def test_the_batch_line_is_played_on_the_served_page_every_night(self):
        """The served chain (the chat, the face viewer, the viewer's sequence) is played in a browser
        by `common.preview_chat_batch` — V8 holds the rules, the gesture holds the wiring."""
        from wama.common.services import nightly_tests
        from wama.common.services.ui_smoke_preview import register_preview_scenarios
        register_preview_scenarios()
        self.assertIn('common.preview_chat_batch', {s.id for s in nightly_tests.REGISTRY})

    def test_the_child_to_follow_is_the_last_over_then_the_one_running(self):
        out = self._read(self._ctx(), """(function () {
            var f = WamaAssistantChat._latestChild;
            function b(st, last) {
              var children = {}, order = [];
              st.forEach(function (s, i) { children[i + 1] = {status: s, terminal: s === 'SUCCESS' || s === 'FAILURE'};
                                            order.push(i + 1); });
              return {children: children, order: order, lastEnded: last};
            }
            return [f(b(['SUCCESS', 'FAILURE', 'RUNNING'])), f(b(['PENDING', 'RUNNING', 'RUNNING'])),
                    f(b(['PENDING', 'PENDING'])), f(b(['SUCCESS', 'SUCCESS'], 1)), f(b([]))];
        })()""")
        self.assertEqual([2, 2, 1, 1, None], out)

    def test_a_block_routes_each_line_by_its_kind(self):
        ctx = self._ctx()
        out = self._read(ctx, """(function () {
            var kinds = [];
            chat.batchRow = function () { kinds.push('batch'); return el(); };
            chat.moreRow = function () { kinds.push('more'); return el(); };
            chat.jobRow = function () { kinds.push('job'); return el(); };
            started.length = 0;
            var block = el(); block.appendChild = function () {};
            document.createElement = function () { return block; };
            chat.jobsBlock([{kind: 'batch', family: 'describer', id: 9, terminal: false},
                            {family: 'describer', id: 1, terminal: true},
                            {kind: 'more', family: 'describer', count: 2, terminal: true}]);
            return [kinds, started.length];
        })()""")
        self.assertEqual([['batch', 'job', 'more'], 1], out)

    def test_the_line_beyond_the_followed_ones_leads_to_their_queue(self):
        ctx = self._ctx()
        out = self._read(ctx, """(function () {
            document.createElement = function () { var e = el(); e.children = [];
              e.appendChild = function (c) { e.children.push(c); }; return e; };
            var row = chat.moreRow({kind: 'more', family: 'describer', count: 2, page_url: '/describer/'});
            return [row.dataset.jobKey === undefined, row.children[0].href, row.children[0].textContent];
        })()""")
        self.assertEqual([True, '/describer/', '+ 2 autres — ouvrir la file'], out,
                         'not followed (no key), a link to the queue')

    def test_the_face_viewer_walks_a_sequence_of_addresses_like_cards(self):
        """The viewer opened from a batch line walks its children (`openSequence`, the gesture of the
        file manager) — the neighbour loaded by ADDRESS on the face being looked at, by the same rule
        as a card's neighbours (`_loadCard`)."""
        from py_mini_racer import MiniRacer
        from .tests_cap_from_js import FAKE_DOM
        served = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js' / 'media-preview.js'
        brick = served.read_text(encoding='utf-8')
        v8 = MiniRacer()
        v8.eval(FAKE_DOM + 'var fetched = []; function fetch(u) { fetched.push(u); '
                           'return {then: function () { return {then: function () {}}; }}; }')
        v8.eval(brick)
        out = json.loads(v8.eval("""JSON.stringify((function () {
            var P = window.WamaMediaPreview, moved = [];
            var walk = P.addressSequence({urls: ['/p/1/', '/p/2/'], index: 1,
                                          onMove: function (i) { moved.push(i); }}, {side: 'output'});
            walk.load(0, 'output');
            walk.onMove(0);
            return [walk.count, walk.index, walk.data.side, fetched, moved,
                    P.addressSequence({urls: ['/p/1/']}, {}), P.addressSequence(null, {})];
        })())"""))
        self.assertEqual([2, 1, 'output', ['/p/1/?side=output'], [0], None, None], out)
        viewer = brick[brick.index('function faceViewer('):]
        opener = viewer[viewer.index('function open()'):viewer.index('function attach(')]
        self.assertIn('if (walk) openSequence(walk);', opener)
        self.assertIn('else openForCard(m, opts.card || null, 0);', opener, 'without a sequence: the cards')
        load_card = brick[brick.index('function _loadCard('):brick.index('function _loadAddress(')]
        self.assertIn('return _loadAddress(', load_card, 'one rule for a card and an address')
