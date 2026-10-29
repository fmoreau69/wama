"""The ▶ of a card, the ▶ and the 🗑 of the queue — the common view factory
(`item_views.make_item_views`, `WAMA_APP_GENERATION_ROUTE.md §11 #39`, 2026-10-29).

Thirty hand-written copies in ten apps, and a fourth copy of the ▶ in the assistant's
`start_<app>` tool whose « start all » had drifted from the button in five apps. What is held
here, once for all of them : the reset is applied under the lock and the progress of the previous
run is purged ; a card already running answers 409 and is not sent twice ; someone else's card is
not found ; a card that cannot start says why ; « start all » launches what the app declares and
applies the posted settings to each card only once all of them accepted them ; « clear all »
releases the files of every card that is not running and drops the emptied batches ; and the
assistant's tool launches through the SAME declaration as the button.

The element is a real one (an avatar job) ; the task is a stand-in.
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from wama.avatarizer.models import AvatarJob, BatchAvatarJob, BatchAvatarJobItem
from wama.common.utils import item_views
from wama.common.utils.item_views import ItemStart, make_item_views, start_queue

User = get_user_model()


class _Task:
    """A Celery task stand-in that records what it was sent."""

    def __init__(self):
        self.sent = []

    def delay(self, pk):
        self.sent.append(pk)
        return SimpleNamespace(id=f'task-{pk}')


class _ItemViewsFixture(TestCase):
    """A real avatar job owner, a stand-in task and the factory's three views."""

    def setUp(self):
        self.user = User.objects.create_user('item_views_owner', password='x')
        self.task = _Task()
        self.views = make_item_views(
            work_model=AvatarJob, app_id='avatarizer', task=self.task,
            get_user=lambda request: request.user,
            reset_on_start={'progress': 0, 'error_message': ''})

    def _job(self, **kw):
        values = dict(user=self.user, mode='pipeline', text_content='Bonjour.',
                      avatar_source='upload', avatar_upload='x/face.png', progress=40,
                      error_message='old failure')
        values.update(kw)
        return AvatarJob.objects.create(**values)

    def _post(self, view, *args, user=None, data=None):
        request = RequestFactory().post('/x/', data=json.dumps(data or {}),
                                        content_type='application/json')
        request.user = user or self.user
        response = view(request, *args)
        return response.status_code, json.loads(response.content)


class ItemViewsTest(_ItemViewsFixture):

    def test_start_resets_under_the_lock_purges_the_old_progress_and_sends_the_task(self):
        job = self._job()
        cache.set(f'avatarizer_progress_{job.pk}', 87)
        code, body = self._post(self.views['start'], job.pk)
        self.assertEqual((200, 'RUNNING', f'task-{job.pk}'), (code, body['status'], body['task_id']))
        self.assertEqual([job.pk], self.task.sent)
        self.assertIsNone(cache.get(f'avatarizer_progress_{job.pk}'), 'progress of the last run')
        job.refresh_from_db()
        self.assertEqual(('RUNNING', f'task-{job.pk}', 0, ''),
                         (job.status, job.task_id, job.progress, job.error_message))

    def test_a_card_already_running_answers_409_and_is_not_sent_twice(self):
        job = self._job(status='RUNNING')
        code, body = self._post(self.views['start'], job.pk)
        self.assertEqual((409, []), (code, self.task.sent))
        self.assertIn('en cours', body['error'])

    def test_the_card_of_someone_else_is_not_found(self):
        job = self._job()
        stranger = User.objects.create_user('item_views_stranger', password='x')
        code, _body = self._post(self.views['start'], job.pk, user=stranger)
        self.assertEqual((404, []), (code, self.task.sent))
        job.refresh_from_db()
        self.assertEqual('PENDING', job.status)

    def test_a_card_that_cannot_start_says_why_and_start_all_skips_it(self):
        views = make_item_views(
            work_model=AvatarJob, app_id='avatarizer', task=self.task,
            get_user=lambda request: request.user, startable=lambda j: bool(j.text_content),
            unstartable_message='Texte manquant')
        empty, ready = self._job(text_content=''), self._job()
        code, body = self._post(views['start'], empty.pk)
        self.assertEqual((400, 'Texte manquant', []), (code, body['error'], self.task.sent))
        code, body = self._post(views['start_all'])
        self.assertEqual((200, [ready.pk], [empty.pk]), (code, body['started'], body['skipped']))

    def test_a_task_that_cannot_be_sent_gives_the_card_back_to_the_queue(self):
        broken = SimpleNamespace(delay=mock.Mock(side_effect=ConnectionError('broker down')))
        views = make_item_views(work_model=AvatarJob, app_id='avatarizer', task=broken,
                                get_user=lambda request: request.user)
        job = self._job()
        code, body = self._post(views['start'], job.pk)
        self.assertEqual(503, code, body)
        job.refresh_from_db()
        self.assertEqual('PENDING', job.status)

    def test_start_all_launches_what_the_app_declares_and_answers_the_common_vocabulary(self):
        waiting, failed = self._job(), self._job(status='FAILURE')
        done, running = self._job(status='SUCCESS'), self._job(status='RUNNING')
        code, body = self._post(self.views['start_all'])
        self.assertEqual((200, True, [waiting.pk], 1, []),
                         (code, body['success'], body['started'], body['count'], body['errors']))
        views = make_item_views(
            work_model=AvatarJob, app_id='avatarizer', task=self.task,
            get_user=lambda request: request.user, pending={},
            pending_exclude={'status__in': ['RUNNING', 'SUCCESS']})
        code, body = self._post(views['start_all'])
        self.assertEqual([failed.pk], body['started'])
        statuses = dict(AvatarJob.objects.filter(user=self.user).values_list('pk', 'status'))
        self.assertEqual({waiting.pk: 'RUNNING', failed.pk: 'RUNNING', done.pk: 'SUCCESS',
                          running.pk: 'RUNNING'}, statuses)

    def test_start_all_applies_the_posted_settings_only_once_every_card_accepted_them(self):
        def apply(job, data):
            if data.get('quality_mode') == 'impossible':
                raise ValueError('mode refusé')
            job.quality_mode = data['quality_mode']

        views = make_item_views(
            work_model=AvatarJob, app_id='avatarizer', task=self.task,
            get_user=lambda request: request.user,
            queue_settings=lambda request, user: json.loads(request.body),
            apply_settings=apply)
        first, second = self._job(), self._job()
        code, body = self._post(views['start_all'], data={'quality_mode': 'impossible'})
        self.assertEqual((400, 'mode refusé', []), (code, body['error'], self.task.sent))
        self.assertEqual({'PENDING'}, set(AvatarJob.objects.values_list('status', flat=True)))
        code, body = self._post(views['start_all'], data={'quality_mode': 'quality'})
        self.assertEqual(sorted([first.pk, second.pk]), sorted(body['started']))
        self.assertEqual({'quality'}, set(AvatarJob.objects.values_list('quality_mode', flat=True)))

    def test_clear_all_keeps_the_running_cards_and_drops_the_emptied_batches(self):
        batch = BatchAvatarJob.objects.create(user=self.user, total=2)
        waiting, running = self._job(), self._job(status='RUNNING')
        for row, job in enumerate((waiting, running)):
            BatchAvatarJobItem.objects.create(batch=batch, job=job, row_index=row)
        lone_batch = BatchAvatarJob.objects.create(user=self.user, total=0)
        cache.set(f'avatarizer_progress_{waiting.pk}', 12)
        seen = []
        views = make_item_views(work_model=AvatarJob, app_id='avatarizer', task=self.task,
                                get_user=lambda request: request.user,
                                on_delete=lambda j: seen.append(j.pk), batch_model=BatchAvatarJob)
        released = []
        with mock.patch('wama.common.utils.queue_duplication.release_card_files',
                        side_effect=lambda obj: released.append((type(obj).__name__, obj.pk))):
            code, body = self._post(views['clear_all'])
        self.assertEqual((200, 1, [waiting.pk]), (code, body['deleted'], seen))
        self.assertEqual([('AvatarJob', waiting.pk), ('BatchAvatarJob', lone_batch.pk)], released,
                         'the card, then the file of the batch that held nothing')
        self.assertEqual([running.pk], list(AvatarJob.objects.values_list('pk', flat=True)))
        self.assertIsNone(cache.get(f'avatarizer_progress_{waiting.pk}'))
        remaining = set(BatchAvatarJob.objects.values_list('pk', flat=True))
        self.assertIn(batch.pk, remaining, 'the batch still holds the running card')
        self.assertNotIn(lone_batch.pk, remaining, 'an empty batch goes with the queue')


class QueueScopesTest(_ItemViewsFixture):
    """The ▾ menu of « start all » and « clear all » (2026-10-29, Fabien : « un menu déroulant pour
    que l'utilisateur précise son choix ») : the main click keeps the app's rule, a scope narrows or
    widens it, an unknown scope is refused, and nothing in flight is ever launched or removed."""

    def _post_scope(self, view, scope, user=None):
        request = RequestFactory().post(f'/x/?scope={scope}', data='{}',
                                        content_type='application/json')
        request.user = user or self.user
        response = view(request)
        return response.status_code, json.loads(response.content)

    def test_each_start_scope_launches_its_share_of_the_queue(self):
        waiting, failed = self._job(), self._job(status='FAILURE')
        done = self._job(status='SUCCESS')
        self._job(status='AWAITING_RESOURCES')                      # in flight : never relaunched
        expected = {'pending': [waiting.pk], 'failed': [failed.pk],
                    'unfinished': [waiting.pk, failed.pk], 'all': [waiting.pk, failed.pk, done.pk]}
        for scope, pks in expected.items():
            with self.subTest(scope=scope):
                AvatarJob.objects.filter(pk__in=[waiting.pk, failed.pk, done.pk]).update(
                    status='PENDING')
                AvatarJob.objects.filter(pk=failed.pk).update(status='FAILURE')
                AvatarJob.objects.filter(pk=done.pk).update(status='SUCCESS')
                code, body = self._post_scope(self.views['start_all'], scope)
                self.assertEqual((200, sorted(pks)), (code, sorted(body['started'])))

    def test_an_unknown_scope_is_refused_and_nothing_starts(self):
        self._job()
        code, body = self._post_scope(self.views['start_all'], 'everything')
        self.assertEqual((400, []), (code, self.task.sent))
        self.assertIn('périmètre inconnu', body['error'])
        code, _body = self._post_scope(self.views['clear_all'], 'everything')
        self.assertEqual(400, code)
        self.assertEqual(1, AvatarJob.objects.count())

    def test_a_clear_scope_removes_only_its_share_and_never_what_is_in_flight(self):
        done, failed = self._job(status='SUCCESS'), self._job(status='FAILURE')
        waiting, awaiting = self._job(), self._job(status='AWAITING_RESOURCES')
        with mock.patch('wama.common.utils.queue_duplication.release_card_files'):
            code, body = self._post_scope(self.views['clear_all'], 'success')
            self.assertEqual((200, 1), (code, body['deleted']))
            self.assertEqual({failed.pk, waiting.pk, awaiting.pk},
                             set(AvatarJob.objects.values_list('pk', flat=True)))
            code, body = self._post(self.views['clear_all'])           # main click : the queue
        self.assertEqual([awaiting.pk], list(AvatarJob.objects.values_list('pk', flat=True)))

    def test_the_menu_entries_come_from_the_factory_tables(self):
        from wama.common.utils.item_views import CLEAR_SCOPES, START_SCOPES, queue_scopes
        self.assertEqual(list(START_SCOPES), [s['key'] for s in queue_scopes('start')])
        self.assertEqual(list(CLEAR_SCOPES), [s['key'] for s in queue_scopes('clear')])

    def test_the_queue_counters_name_every_menu_counter(self):
        """Each entry is greyed by a counter the queue bar publishes (`queue_progress`) : a
        counter the payload does not carry would leave an entry enabled on an empty share."""
        from wama.common.utils.item_views import queue_scopes
        from wama.common.utils.progress_views import queue_progress
        counters = set(queue_progress([('PENDING', 0)]))
        for action in ('start', 'clear'):
            for scope in queue_scopes(action):
                self.assertIn(scope['counter'], counters, scope)


class EveryQueuePageShowsTheScopeMenusTest(TestCase):
    """On the SERVED page of every app, the queue bar carries both menus, each entry addressing
    its action with `?scope=` and naming the counter that greys it — the visible half of the
    factory, measured where the user sees it."""

    def test_each_app_page_renders_both_menus(self):
        from django.urls import NoReverseMatch, reverse
        from wama.common.app_registry import APP_CATALOG
        from wama.common.tests.tests_endpoints import EveryEndpointAnswersTest
        checked = []
        for app, spec in sorted(APP_CATALOG.items()):
            if (spec or {}).get('sandbox'):
                continue
            try:
                page = reverse(f'{app}:index')
                reverse(f'{app}:start_all')
            except NoReverseMatch:
                continue
            with self.subTest(app=app):
                self.client.force_login(EveryEndpointAnswersTest._account_for(self, app))
                html = self.client.get(page).content.decode()
                self.assertIn('scope=all', html, 'menu of « start all » missing')
                self.assertIn('scope=success', html, 'menu of « clear all » missing')
                self.assertIn('data-queue-scope="relaunchable"', html)
                checked.append(app)
        self.assertGreaterEqual(len(checked), 10, checked)


class ClearPreviewFollowsTheScopeTest(TestCase):
    """The confirmation of « clear all » announces the files that THIS clear frees : the same
    selection as the view (`ItemStart.to_clear`, scope included), not the whole queue."""

    def test_the_preview_reads_the_scope(self):
        from django.urls import reverse
        user = User.objects.create_user('item_views_preview', password='x')
        self.client.force_login(user)
        base = dict(user=user, mode='pipeline', text_content='a', avatar_source='upload')
        AvatarJob.objects.create(avatar_upload='x/done.png', status='SUCCESS', **base)
        AvatarJob.objects.create(avatar_upload='x/failed.png', status='FAILURE', **base)
        seen = []

        def freed(instances):
            seen.append(sorted(getattr(i, 'status', 'lot') for i in instances))
            return []
        with mock.patch('wama.common.services.released_files.freed_by', side_effect=freed):
            url = reverse('common:api_released_files_preview')
            self.client.get(url, {'surface': 'avatarizer', 'nature': 'queue', 'scope': 'success'})
            self.client.get(url, {'surface': 'avatarizer', 'nature': 'queue'})
            refused = self.client.get(url, {'surface': 'avatarizer', 'nature': 'queue',
                                            'scope': 'everything'})
        self.assertEqual(['SUCCESS'], seen[0])
        self.assertEqual(['FAILURE', 'SUCCESS'], seen[1])
        self.assertEqual(400, refused.status_code)


class EveryAppRoutesItsQueueGesturesThroughTheFactoryTest(TestCase):
    """Generic over the catalogue : the ▶ of a card, « start all » and « clear all » of every app
    come from the factory — a new app cannot write them by hand again, nor an old one keep them.
    The exemptions are NAMED, with their reason, and can only shrink : an exemption that is no
    longer needed fails too."""

    ROUTES = ('start', 'start_all', 'clear_all')
    #: (app, route) still written in the app — and why. EMPTY since 2026-10-29 : the anonymizer's
    #: batch chain (`ProcessView`) was retired once its « relaunch everything » became the « Tout
    #: relancer » entry of the menu (Fabien's decision). Keep it empty.
    EXEMPT = set()

    def _view(self, app, route):
        from django.urls import NoReverseMatch, resolve, reverse
        from wama.common.manifests.codegen.urls_gen import ROUTE_ALIASES
        for name in (route,) + tuple(ROUTE_ALIASES.get(route, ())):
            try:
                url = reverse(f'{app}:{name}', args=[1] if route == 'start' else [])
            except NoReverseMatch:
                continue
            view = resolve(url).func
            while hasattr(view, '__wrapped__'):
                view = view.__wrapped__
            return view
        return None

    def test_every_app_starts_and_clears_its_queue_through_the_factory(self):
        from wama.common.app_registry import APP_CATALOG
        apps = [a for a, spec in APP_CATALOG.items() if not (spec or {}).get('sandbox')]
        checked, still_needed = [], set()
        for app in sorted(apps):
            for route in self.ROUTES:
                view = self._view(app, route)
                if view is None:
                    continue
                with self.subTest(app=app, route=route):
                    from_factory = view.__module__ == 'wama.common.utils.item_views'
                    if (app, route) in self.EXEMPT:
                        if not from_factory:
                            still_needed.add((app, route))
                        continue
                    self.assertTrue(from_factory, f'{app}:{route} écrit à la main')
                    checked.append((app, route))
        self.assertGreaterEqual(len(checked), 25, checked)
        self.assertEqual(self.EXEMPT, still_needed, 'an exemption is no longer needed')


class TheAssistantLaunchesThroughTheButtonDeclarationTest(TestCase):
    """`start_<app>` reads what the app DECLARES to its factory — the selection, the task and the
    reset of the button, not a second copy of them in `TRIAD_SPECS`."""

    def test_the_tool_uses_the_registered_declaration(self):
        from wama import tool_api as T
        user = User.objects.create_user('item_views_tool', password='x')
        task = _Task()
        failed = AvatarJob.objects.create(user=user, mode='pipeline', text_content='a',
                                          avatar_source='upload', avatar_upload='x/f.png',
                                          status='FAILURE')
        declared = ItemStart(work_model=AvatarJob, app_id='avatarizer', task=task, pending={},
                             pending_exclude={'status__in': ['RUNNING', 'SUCCESS']})
        with mock.patch.dict(item_views._DECLARATIONS, {AvatarJob: declared}):
            result = T.start_avatarizer(user)
        self.assertEqual(([failed.pk], [failed.pk]), (result['ids'], task.sent))

    def test_start_queue_is_the_gesture_of_both_doors(self):
        """The tool and the view call the same function : nothing to launch is not an error of
        the gesture, the door says it (the view answers count 0, the tool its empty message)."""
        user = User.objects.create_user('item_views_empty', password='x')
        declared = ItemStart(work_model=AvatarJob, app_id='avatarizer', task=_Task())
        self.assertEqual(([], [], []), start_queue(declared, user))
