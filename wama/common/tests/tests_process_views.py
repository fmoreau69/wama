"""The ▶ of ONE process — the common view factory (`process_views.make_process_start_view`).

`WAMA_APP_GENERATION_ROUTE.md §10.6` 5.1, `§11 #38` (2026-10-04) : the view `start/<pk>/<process>/`
was written by hand in six apps, with three shapes of refusal. What is held here, once for all of
them : an unknown process and a process without object for this card are refused and NOTHING is
sent ; a card already running answers 409 ; someone else's card is not found ; the task receives
the process ; the reset is applied under the lock ; a model known only at launch leaves the
decision to the task.

The element is a real one (an avatar job : its pipeline has a process that does not always take
place) ; the task is a stand-in.
"""
import json
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import RequestFactory, TestCase

from wama.avatarizer.models import AvatarJob
from wama.common.services.process_pipeline import APP_PIPELINES, AppPipeline, pipeline_of
from wama.common.utils.process_views import make_process_start_view

User = get_user_model()


class ProcessStartViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('process_start_owner', password='x')
        self.sent = []
        task = SimpleNamespace(apply_async=lambda **kw: self.sent.append(kw)
                               or SimpleNamespace(id='task-1'))
        self.view = make_process_start_view(
            work_model=AvatarJob, task_for=lambda job: task, get_user=lambda request: request.user,
            reset_on_start={'progress': 0, 'error_message': ''})

    def _job(self, **kw):
        values = dict(user=self.user, mode='pipeline', text_content='Bonjour.',
                      avatar_source='upload', avatar_upload='x/face.png', progress=40,
                      error_message='old failure')
        values.update(kw)
        return AvatarJob.objects.create(**values)

    def _post(self, view, job, process, user=None):
        request = RequestFactory().post(f'/start/{job.pk}/{process}/')
        request.user = user or self.user
        response = view(request, pk=job.pk, process=process)
        return response.status_code, json.loads(response.content)

    def test_a_known_process_is_sent_bounded_and_the_card_is_reset_under_the_lock(self):
        job = self._job()
        code, body = self._post(self.view, job, 'animate')
        self.assertEqual((200, 'animate', 'RUNNING', 'task-1'),
                         (code, body['process'], body['status'], body['task_id']))
        self.assertEqual([{'args': (job.pk,), 'kwargs': {'process': 'animate'}}], self.sent)
        job.refresh_from_db()
        self.assertEqual(('RUNNING', 'task-1', 0, ''),
                         (job.status, job.task_id, job.progress, job.error_message))

    def test_an_unknown_process_is_refused_and_nothing_is_sent(self):
        job = self._job()
        code, body = self._post(self.view, job, 'mix')
        self.assertEqual(400, code)
        self.assertIn('process inconnu', body['error'])
        job.refresh_from_db()
        self.assertEqual(('PENDING', [], 40), (job.status, self.sent, job.progress))

    def test_a_process_without_object_for_this_card_is_refused(self):
        """A card that brings its audio has no voice to synthesize."""
        job = self._job(mode='standalone', text_content='', audio_input='x/voice.wav')
        code, body = self._post(self.view, job, 'speak')
        self.assertEqual(400, code)
        self.assertIn("n'a pas lieu", body['error'])
        self.assertEqual([], self.sent)

    def test_a_card_already_running_answers_409_and_is_not_sent_twice(self):
        job = self._job(status='RUNNING')
        code, body = self._post(self.view, job, 'animate')
        self.assertEqual((409, []), (code, self.sent))
        self.assertIn('en cours', body['error'])

    def test_the_card_of_someone_else_is_not_found(self):
        job = self._job()
        stranger = User.objects.create_user('process_start_stranger', password='x')
        with self.assertRaises(Http404):
            self._post(self.view, job, 'animate', user=stranger)
        job.refresh_from_db()
        self.assertEqual(('PENDING', []), (job.status, self.sent))

    def test_a_reset_that_depends_on_the_process_receives_it(self):
        seen = []
        view = make_process_start_view(
            work_model=AvatarJob, task_for=lambda job: SimpleNamespace(
                apply_async=lambda **kw: SimpleNamespace(id='task-2')),
            get_user=lambda request: request.user,
            reset_for_process=lambda job, process: seen.append((job.pk, process)))
        job = self._job()
        self.assertEqual(200, self._post(view, job, 'animate')[0])
        self.assertEqual([(job.pk, 'animate')], seen)

    def test_a_model_known_only_at_launch_leaves_the_decision_to_the_task(self):
        """Under « auto » the composer does not know which processes take place before the task
        draws the model (`requested_model` gives None) : the view does not refuse on a guess."""
        real = pipeline_of(self._job())
        undecided = AppPipeline('avatarizer', real.specs, label='Demo', model_of=lambda job: None)
        APP_PIPELINES['avatarizer'] = undecided
        self.addCleanup(APP_PIPELINES.__setitem__, 'avatarizer', real)
        job = self._job(mode='standalone', text_content='', audio_input='x/voice.wav')
        code, body = self._post(self.view, job, 'speak')
        self.assertEqual((200, 'speak'), (code, body['process']))


class BatchStepRunTest(TestCase):
    """The ▶ of ONE step on every card of a BATCH (2026-11-18, decision of Fabien : « le plus simple
    pour permettre de relancer un sous-process sur toutes les cards filles ») — the ▶ of the step
    of each card (`start_one_process`), never a second launch : a card where the step does not
    take place, a running card and a card of someone else are skipped and SAID, the others start
    with the process ; the mother card's band reads its rows from the cards' own rows."""

    def setUp(self):
        from unittest import mock

        from wama.avatarizer.models import BatchAvatarJob, BatchAvatarJobItem
        self.user = User.objects.create_user('batch_step_owner', password='x')
        self.sent = []
        task = SimpleNamespace(apply_async=lambda **kw: self.sent.append(kw)
                               or SimpleNamespace(id=f'task-{len(self.sent)}'))
        declared = SimpleNamespace(task_of=lambda job: task, reset_on_start=None)
        for target, value in (('wama.common.utils.item_views.declaration_for', declared),
                              ('wama.common.utils.process_views.process_reset_for', None)):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.batch = BatchAvatarJob.objects.create(user=self.user, total=3)
        self.spoken = self._job()
        self.recorded = self._job(mode='standalone', text_content='', audio_input='x/voice.wav')
        self.running = self._job(status='RUNNING')
        for row, job in enumerate((self.spoken, self.recorded, self.running)):
            BatchAvatarJobItem.objects.create(batch=self.batch, job=job, row_index=row)

    def _job(self, **kw):
        values = dict(user=self.user, mode='pipeline', text_content='Bonjour.',
                      avatar_source='upload', avatar_upload='x/face.png')
        values.update(kw)
        return AvatarJob.objects.create(**values)

    def _post(self, process, user=None):
        from wama.common.views import api_process_on_batch
        request = RequestFactory().post('/')
        request.user = user or self.user
        response = api_process_on_batch(request, surface='avatarizer', pk=self.batch.pk,
                                        process=process)
        return response.status_code, json.loads(response.content)

    def test_each_card_where_the_step_takes_place_runs_it_and_the_others_are_said(self):
        code, body = self._post('speak')
        self.assertEqual((200, [self.spoken.pk]), (code, body['started']))
        self.assertEqual([{'args': (self.spoken.pk,), 'kwargs': {'process': 'speak'}}], self.sent)
        reasons = {row['id']: row['reason'] for row in body['skipped']}
        self.assertEqual({self.recorded.pk, self.running.pk}, set(reasons))
        self.assertIn("n'a pas lieu", reasons[self.recorded.pk])
        self.assertIn('en cours', reasons[self.running.pk])
        self.spoken.refresh_from_db()
        self.assertEqual('RUNNING', self.spoken.status)

    def test_a_batch_where_no_card_starts_answers_400_with_the_reasons(self):
        AvatarJob.objects.filter(pk=self.spoken.pk).update(status='RUNNING')
        code, body = self._post('speak')
        self.assertEqual((400, []), (code, self.sent))
        self.assertIn("n'a pas lieu", body['error'])

    def test_the_batch_of_someone_else_is_not_found(self):
        stranger = User.objects.create_user('batch_step_stranger', password='x')
        with self.assertRaises(Http404):
            self._post('animate', user=stranger)
        self.assertEqual([], self.sent)

    def test_the_mother_card_band_counts_each_step_on_the_cards_where_it_takes_place(self):
        from django.template.loader import render_to_string
        from wama.common.services.process_pipeline import decorate_cards
        from wama.common.templatetags.wama_actions import batch_process_rows
        jobs = decorate_cards([self.spoken, self.recorded, self.running])
        info = {'obj': self.batch, 'items': [SimpleNamespace(elem=job) for job in jobs]}
        rows = {row['key']: row for row in batch_process_rows('avatarizer', None, info)}
        self.assertEqual((2, 3), (rows['speak']['active'], rows['animate']['active']))
        # A step's state is read from its runs, not from the card : nothing ran yet.
        self.assertEqual(('PENDING', 0), (rows['animate']['status'], rows['animate']['done']))
        self.assertEqual(f'/common/api/batch/avatarizer/{self.batch.pk}/process/speak/',
                         rows['speak']['url'])
        html = render_to_string('common/_batch_processes.html',
                                {'app': 'avatarizer', 'domain': None, 'batch_info': info})
        self.assertIn(f'data-batch-process-url="{rows["animate"]["url"]}"', html)


class EveryPipelineAppExposesTheRunButtonTest(TestCase):
    """Generic over the fleet : every app that DECLARES a pipeline routes `start/<pk>/<process>/`
    through the factory — a new pipeline app cannot forget the ▶ of a process, nor write its own."""

    def test_each_declared_pipeline_has_the_route_and_the_factory_view(self):
        from django.urls import NoReverseMatch, reverse
        from django.urls import resolve
        from wama.common.catalog.function_catalog import load_all
        load_all()
        self.assertGreaterEqual(len(APP_PIPELINES), 7, sorted(APP_PIPELINES))
        for app in sorted(APP_PIPELINES):
            if app.startswith('demo'):
                continue
            with self.subTest(app=app):
                try:
                    url = reverse(f'{app}:start_process', args=[1, 'x'])
                except NoReverseMatch:
                    self.fail(f"{app} déclare un pipeline sans route `start_process`")
                view = resolve(url).func
                while hasattr(view, '__wrapped__'):
                    view = view.__wrapped__
                self.assertEqual('wama.common.utils.process_views', view.__module__,
                                 f"{app} : ▶ d'un process écrit à la main")
