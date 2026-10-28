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
        _lot, (self.card,) = _lot_de(Description, self.user, 1)
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

    def test_the_turn_reply_carries_its_jobs_while_they_run(self):
        reply = {'response': 'Lancé.', 'tool_steps': self.steps, 'model': 'test'}
        self._set('RUNNING', 10)
        with mock.patch('wama.common.services.assistant_engine.conversation_turn',
                        return_value=dict(reply)):
            data = self.client.post(reverse('ai_chat'), data=json.dumps({'message': 'go'}),
                                    content_type='application/json').json()
        self.assertEqual([('describer', self.card.pk)], [(j['family'], j['id']) for j in data['jobs']])
        # Counter-check: a job already over has its end told by the relay, not a bar.
        self._set('SUCCESS', 100)
        with mock.patch('wama.common.services.assistant_engine.conversation_turn',
                        return_value=dict(reply)):
            data = self.client.post(reverse('ai_chat'), data=json.dumps({'message': 'go'}),
                                    content_type='application/json').json()
        self.assertNotIn('jobs', data)

    def test_the_jobs_endpoint_reads_each_item_of_the_user_only(self):
        self._set('PENDING')
        r = self.client.get(reverse('ai_chat_jobs'),
                            {'items': f'describer:{self.card.pk},describer:999999,nope:1,bad'})
        self.assertEqual(200, r.status_code)
        self.assertEqual([self.card.pk], [j['id'] for j in r.json()['jobs']])
        self.client.logout()
        self.assertEqual(401, self.client.get(reverse('ai_chat_jobs')).status_code)

    def test_the_thread_gives_back_the_bar_of_a_job_still_running(self):
        from wama.views import _chat_thread
        conversation = self.store.thread(self.user, surface='web')
        self.store.record_exchange(conversation, 'décris ce fichier',
                                   {'response': 'Lancé.', 'tool_steps': self.steps})
        self._set('RUNNING', 20)
        (answer,) = [e for e in _chat_thread(self.user) if e['type'] == 'assistant']
        self.assertEqual([self.card.pk], [j['id'] for j in answer['jobs']])
        self._set('FAILURE')
        (answer,) = [e for e in _chat_thread(self.user) if e['type'] == 'assistant']
        self.assertNotIn('jobs', answer)


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
var checked = 0, stopped = [], started = [];
window.WamaApp = {
  checkNotifications: function () { checked++; },
  statusLabel: function (s) { return 'label:' + s; },
  statusBadge: function (s) { return 'badge:' + s; },
  Poller: function () {
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

    def test_an_item_no_longer_served_stops_and_says_so(self):
        ctx = self._ctx()
        ctx.eval("""chat.updateJobs('1', [
            {family: 'describer', id: 1, status: 'SUCCESS', progress: 100, terminal: true, ok: true}]);""")
        self.assertEqual('Introuvable', self._read(ctx, "b.parts['.status-badge'].textContent"))
        self.assertEqual(['1'], self._read(ctx, 'stopped'))
