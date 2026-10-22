"""Relaunching a card WHILE it runs (2026-10-22, decision of Fabien).

« On accepte l'enregistrement des réglages pendant un traitement et on permet de relancer le job
complet ou par étapes, à condition que l'arrêt de la tâche en cours soit bien géré et la relance
soit bien gérée aussi. Il faut aussi demander confirmation à l'utilisateur. »

Four pieces, one test class each:
  * the task skeleton stops COOPERATIVELY — a `--pool=solo` worker cannot be killed mid-task —:
    a launch the element no longer carries (relaunched, stopped) withdraws and writes nothing
    (`task_skeleton.LaunchSuperseded`);
  * `begin_processing` replaces a running launch only with the user's CONFIRMED grant
    (`process_control.grant_replace`, consumed once, by that user only);
  * the common view that records the grant (`common:api_replace_grant`) and every app's settings
    route, which now accept a running element without rewriting what its task writes
    (`batch_views.columns_changed`);
  * the confirmation itself, in the common card actions (`queue-actions.js`), run in V8.
"""
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.utils import task_skeleton
from wama.common.utils.process_control import begin_processing, grant_replace
from wama.common.utils.task_skeleton import run_item_task


def _task(task_id, retries=0):
    class _T:
        class request:
            id = task_id
            delivery_info = {}
    _T.request.retries = retries
    return _T


class _SynthesisCase(TestCase):
    """A witness element of an app that runs on the skeleton (the synthesizer)."""

    def setUp(self):
        from wama.synthesizer.models import VoiceSynthesis
        self.user = get_user_model().objects.create_user('relaunch_owner', password='x')
        self.model = VoiceSynthesis
        self.item = VoiceSynthesis.objects.create(user=self.user, text_content='bonjour',
                                                  status='RUNNING', task_id='launch-a')
        cache.delete(task_skeleton._launch_key('synthesizer', self.item.pk))

    def _row(self):
        return self.model.objects.values('status', 'task_id', 'error_message').get(pk=self.item.pk)

    def _run(self, glue, task_id='launch-a', retries=0):
        # `close_old_connections()` would close the TestCase connection (see the redelivery tests).
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(task_id, retries), app_id='synthesizer', model=self.model,
                          item_id=self.item.pk, process=glue)


class ASupersededLaunchWritesNothingTest(_SynthesisCase):

    def test_a_relaunched_element_is_left_to_its_new_launch(self):
        def glue(item, ctx):
            # what `begin_processing` then the launching view do while this task runs
            self.model.objects.filter(pk=item.pk).update(task_id='launch-b')
            return {'fields': {'text_content': 'written by the replaced launch'}}
        self._run(glue)
        row = self._row()
        self.assertEqual(('RUNNING', 'launch-b'), (row['status'], row['task_id']),
                         'the replaced launch wrote its end over the new one')
        self.assertEqual('bonjour', self.model.objects.get(pk=self.item.pk).text_content,
                         'the replaced launch wrote its result')

    def test_a_stopped_element_stays_stopped(self):
        """⏹ (`stop_instance`) clears the task and leaves « en cours »: the task cannot be killed
        on a solo worker, it must not then write SUCCESS over the stop."""
        def glue(item, ctx):
            self.model.objects.filter(pk=item.pk).update(status='FAILURE', task_id='',
                                                         error_message="Interrompu par l'utilisateur")
            return {}
        self._run(glue)
        self.assertEqual('FAILURE', self._row()['status'])
        self.assertEqual("Interrompu par l'utilisateur", self._row()['error_message'])

    def test_the_glue_is_stopped_at_its_next_progress(self):
        reached = []

        def glue(item, ctx):
            self.model.objects.filter(pk=item.pk).update(task_id='launch-b')
            ctx.progress(40)
            reached.append('after progress')
            return {}
        with mock.patch.object(task_skeleton, 'CURRENT_CHECK_S', 0.0):
            self._run(glue)
        self.assertEqual([], reached, 'the glue went on after its launch was replaced')
        self.assertEqual('RUNNING', self._row()['status'])

    def test_a_launch_that_is_still_current_ends_as_before(self):
        """Counter-proof: nothing changed under the task, it ends in SUCCESS."""
        self._run(lambda item, ctx: ctx.progress(50) or {})
        self.assertEqual('SUCCESS', self._row()['status'])

    def test_a_task_id_never_seen_proves_nothing(self):
        """The launching view writes the task id just AFTER `.delay()`: until the task has seen
        its own, another id (the previous launch's) is not a replacement."""
        self.model.objects.filter(pk=self.item.pk).update(task_id='previous-launch')
        self._run(lambda item, ctx: {})
        self.assertEqual('SUCCESS', self._row()['status'])

    def test_a_redelivered_launch_remembers_what_it_had_seen(self):
        """Re-delivered to another worker after a wait, the launch keeps what it had seen: a
        relaunch posed during the wait is a replacement there too."""
        cache.set(task_skeleton._launch_key('synthesizer', self.item.pk),
                  {'task': 'launch-a', 'facts': {'current_seen': {'ours': True,
                                                                  'started_active': True}}},
                  timeout=600)
        self.model.objects.filter(pk=self.item.pk).update(task_id='launch-b')
        ran = []
        self._run(lambda item, ctx: ran.append(1) or {}, retries=1)
        self.assertEqual([], ran, 'a replaced launch ran again at its redelivery')
        self.assertEqual(('RUNNING', 'launch-b'), (self._row()['status'], self._row()['task_id']))

    def test_outside_a_worker_nothing_is_checked(self):
        """A direct call (no launch id) keeps the behaviour every test of the apps relies on."""
        def glue(item, ctx):
            self.model.objects.filter(pk=item.pk).update(task_id='')
            return {}
        self._run(glue, task_id='')
        self.assertEqual('SUCCESS', self._row()['status'])


class ReplacingARunningLaunchTest(_SynthesisCase):

    def test_without_a_grant_a_running_element_is_refused(self):
        self.assertEqual((None, 'already_running'),
                         begin_processing(self.model, self.item.pk, user=self.user))

    def test_the_grant_of_its_user_replaces_it_once(self):
        grant_replace(self.model, self.item.pk, self.user)
        item, err = begin_processing(self.model, self.item.pk, user=self.user)
        self.assertIsNone(err)
        self.assertEqual(('RUNNING', ''), (item.status, item.task_id))
        self.assertEqual((None, 'already_running'),
                         begin_processing(self.model, self.item.pk, user=self.user),
                         'a grant is for ONE relaunch')

    def test_the_grant_of_another_user_is_not_taken(self):
        other = get_user_model().objects.create_user('relaunch_other', password='x')
        grant_replace(self.model, self.item.pk, other)
        self.assertEqual((None, 'already_running'),
                         begin_processing(self.model, self.item.pk, user=self.user))

    def test_the_open_lines_of_the_replaced_launch_are_closed(self):
        from wama.common.services import process_runs
        process_runs.start(self.item, process_runs.MAIN_NODE, process_key='synthesizer',
                           task_id='launch-a')
        grant_replace(self.model, self.item.pk, self.user)
        begin_processing(self.model, self.item.pk, user=self.user)
        (line,) = process_runs.lines(self.item)
        self.assertEqual('FAILURE', line.status)


class TheReplaceGrantViewTest(_SynthesisCase):

    def _post(self, pk):
        return self.client.post(reverse('common:api_replace_grant'),
                                {'surface': 'synthesizer', 'pk': pk})

    def test_a_running_card_of_its_user_is_granted(self):
        self.client.force_login(self.user)
        r = self._post(self.item.pk)
        self.assertEqual((200, True), (r.status_code, r.json()['granted']))
        _item, err = begin_processing(self.model, self.item.pk, user=self.user)
        self.assertIsNone(err, 'the grant recorded by the view was not consumed by the launch')

    def test_a_card_that_does_not_run_needs_no_grant(self):
        self.model.objects.filter(pk=self.item.pk).update(status='SUCCESS')
        self.client.force_login(self.user)
        self.assertFalse(self._post(self.item.pk).json()['granted'])

    def test_someone_who_cannot_edit_the_card_gets_nothing(self):
        other = get_user_model().objects.create_user('relaunch_stranger', password='x')
        self.client.force_login(other)
        self.assertEqual(404, self._post(self.item.pk).status_code)
        self.assertEqual((None, 'already_running'),
                         begin_processing(self.model, self.item.pk, user=self.user))


class SettingsSavedDuringTheRunTest(TestCase):
    """Every app's settings route accepts a RUNNING element (the 8 refusals are gone), and a
    settings view writes only what it changed (`columns_changed`)."""

    def test_every_settings_route_accepts_a_running_element(self):
        from wama.common.tests.tests_item_settings_contract import (
            ItemSettingsRouteContractTest, _posted, _surfaces, _writable_fields)
        from wama.common.tests.tests_queue_delete_contract import _instance
        login = ItemSettingsRouteContractTest._login_for
        surfaces = _surfaces()
        self.assertGreaterEqual(len(surfaces), 8)
        for app, model, schema in surfaces:
            fields = _writable_fields(model, schema)
            with self.subTest(app=app):
                user = login(self, app)
                item = _instance(model, user)
                model.objects.filter(pk=item.pk).update(status='RUNNING', task_id='running-task')
                item.refresh_from_db()
                name, values = fields[0]
                target = next(v for v in values if v != getattr(item, name))
                r = self.client.post(reverse(f'{app}:update_settings', args=[item.pk]),
                                     {name: _posted(target)})
                self.assertEqual(200, r.status_code, r.content[:300])
                item.refresh_from_db()
                self.assertEqual(target, getattr(item, name), 'setting refused while running')
                self.assertEqual(('RUNNING', 'running-task'), (item.status, item.task_id),
                                 'saving the settings touched the running launch')

    def test_only_the_changed_columns_are_saved(self):
        from wama.common.utils.batch_views import columns_changed, columns_snapshot
        from wama.synthesizer.models import VoiceSynthesis
        user = get_user_model().objects.create_user('relaunch_columns', password='x')
        item = VoiceSynthesis.objects.create(user=user, text_content='a', status='RUNNING')
        view_copy = VoiceSynthesis.objects.get(pk=item.pk)
        before = columns_snapshot(view_copy)
        # the task ends while the settings view holds its copy
        VoiceSynthesis.objects.filter(pk=item.pk).update(status='SUCCESS', progress=100)
        view_copy.text_content = 'b'
        changed = columns_changed(view_copy, before)
        self.assertEqual(['text_content'], changed)
        view_copy.save(update_fields=changed)
        item.refresh_from_db()
        self.assertEqual(('SUCCESS', 100, 'b'), (item.status, item.progress, item.text_content))

    def test_a_json_changed_in_place_is_seen(self):
        from wama.common.utils.batch_views import columns_changed, columns_snapshot
        from wama.synthesizer.models import VoiceSynthesis
        json_fields = [f.name for f in VoiceSynthesis._meta.concrete_fields
                       if f.get_internal_type() == 'JSONField']
        if not json_fields:
            self.skipTest('no JSON column on the witness model')
        user = get_user_model().objects.create_user('relaunch_json', password='x')
        item = VoiceSynthesis.objects.create(user=user, text_content='a')
        before = columns_snapshot(item)
        value = getattr(item, json_fields[0])
        if isinstance(value, dict):
            value['wama_contract'] = 1
        elif isinstance(value, list):
            value.append('wama_contract')
        else:
            setattr(item, json_fields[0], {'wama_contract': 1})
        self.assertIn(json_fields[0], columns_changed(item, before))

    def test_counter_proof_a_full_save_rewrites_the_end_of_the_task(self):
        """What the narrowed saves prevent: the view's copy put RUNNING back over SUCCESS."""
        from wama.synthesizer.models import VoiceSynthesis
        user = get_user_model().objects.create_user('relaunch_full', password='x')
        item = VoiceSynthesis.objects.create(user=user, text_content='a', status='RUNNING')
        view_copy = VoiceSynthesis.objects.get(pk=item.pk)
        VoiceSynthesis.objects.filter(pk=item.pk).update(status='SUCCESS')
        view_copy.text_content = 'b'
        view_copy.save()
        item.refresh_from_db()
        self.assertEqual('RUNNING', item.status)


#: A fake browser, just enough for `queue-actions.js`: listeners in registration order (capture
#: first at dispatch), elements that answer `closest` from the selectors they are declared to
#: match, a `fetch` that grants, and the two common globals the block reads.
FAKE_BROWSER = r"""
var window = this;
var listeners = [];
var document = {
  cookie: '', documentElement: {},
  addEventListener: function (t, fn, cap) { listeners.push({ t: t, fn: fn, cap: !!cap }); },
  querySelector: function () { return null; },
  querySelectorAll: function () { return []; },
};
var fetched = [];
function fetch(url) {
  fetched.push(url);
  return Promise.resolve({ status: 200, ok: true,
                           json: function () { return Promise.resolve({ granted: true }); } });
}
function FormData() { this.parts = {}; }
FormData.prototype.append = function (k, v) { this.parts[k] = v; };
var asked = [], answer = true;
var WamaShare = { coordonnees: function (card) { return { surface: 'synthesizer', pk: card.dataset.id }; } };
var WamaApp = { ask: function (o) { asked.push(o.text); return Promise.resolve({ ok: answer }); } };
function node(selectors, dataset, parent, classes) {
  var n = { sels: selectors, dataset: dataset || {}, parent: parent || null, isConnected: true,
            classList: { contains: function (c) { return (classes || []).indexOf(c) !== -1; } } };
  n.closest = function (sel) {
    var wanted = sel.split(',').map(function (s) { return s.trim(); });
    for (var cur = n; cur; cur = cur.parent) {
      for (var i = 0; i < wanted.length; i++) if (cur.sels.indexOf(wanted[i]) !== -1) return cur;
    }
    return null;
  };
  n.click = function () { dispatch(n); };
  return n;
}
function dispatch(target) {
  var stopped = false;
  var e = { target: target, preventDefault: function () {},
            stopPropagation: function () {}, stopImmediatePropagation: function () { stopped = true; } };
  var ordered = listeners.filter(function (l) { return l.t === 'click' && l.cap; })
      .concat(listeners.filter(function (l) { return l.t === 'click' && !l.cap; }));
  for (var i = 0; i < ordered.length && !stopped; i++) ordered[i].fn(e);
}
var launched = [];
"""

SCENE = r"""
var card = node(['.wama-card'], { id: '7', status: STATUS });
var play = node(['.wama-cycle-btn[data-cycle-action="start"]'], { process: 'level' }, card);
document.addEventListener('click', function (e) { if (e.target === play) launched.push('start'); });
play.click();
"""


class TheConfirmationIsCommonTest(SimpleTestCase):
    """V8, on the SERVED file: a relaunch of a RUNNING card asks, records the grant, then lets the
    very same gesture through; a card that does not run is never stopped."""

    def _ctx(self, status, answer=True):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'queue-actions.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(FAKE_BROWSER + source)
        ctx.eval(f'answer = {"true" if answer else "false"};')
        ctx.eval(SCENE.replace('STATUS', repr(status)))
        return ctx

    def _state(self, ctx):
        return (ctx.eval('JSON.stringify(launched)'), ctx.eval('asked.length'),
                ctx.eval('JSON.stringify(fetched)'))

    def test_a_running_card_is_relaunched_after_confirmation(self):
        launched, asked, fetched = self._state(self._ctx('RUNNING'))
        self.assertEqual(1, asked)
        self.assertEqual('["/common/api/replace-grant/"]', fetched)
        self.assertEqual('["start"]', launched, 'the gesture was not replayed after the grant')

    def test_a_refusal_launches_nothing(self):
        launched, asked, fetched = self._state(self._ctx('RUNNING', answer=False))
        self.assertEqual((1, '[]', '[]'), (asked, launched, fetched))

    def test_a_card_that_does_not_run_is_not_asked(self):
        launched, asked, fetched = self._state(self._ctx('SUCCESS'))
        self.assertEqual((0, '["start"]', '[]'), (asked, launched, fetched))

    def test_the_route_of_the_grant_is_the_one_the_block_posts_to(self):
        self.assertEqual('/common/api/replace-grant/', reverse('common:api_replace_grant'))
