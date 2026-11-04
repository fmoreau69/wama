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
        a batch, played by the assistant, gives each launched child the line a card launched alone
        gets — in the surface its domain declares (`audio_enhancer` for an audio batch of the
        enhancer, whose cards are not `enhancer` ones), and its end is told in the thread."""
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
        self.assertEqual([('audio_enhancer', audio_card.pk), ('describer', self.card.pk)],
                         [(j['family'], j['id']) for j in turn_jobs(self.user, steps)])
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
