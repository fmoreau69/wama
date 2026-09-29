"""The common « follow the playhead » loop (`services/playhead_follow`) — each guard it inherited."""
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from wama.common.services.playhead_follow import Channel, follow, post_cursor

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'playhead-follow-tests'}}


class _Clock:
    """A clock that only moves when the loop sleeps."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@override_settings(CACHES=LOCMEM)
class PlayheadFollowTest(SimpleTestCase):

    def setUp(self):
        cache.clear()
        self.channel = Channel('test_live', 7)
        self.spawned = []

    def _spawn(self):
        self.spawned.append(1)

    def test_the_cache_keys_are_the_ones_the_cam_analyzer_wrote_by_hand(self):
        self.assertEqual('cam_live_lock_abc', Channel('cam_live', 'abc').key('lock'))
        self.assertEqual('cam_live_cursor_abc', Channel('cam_live', 'abc').key('cursor'))

    def test_repeated_cursors_spawn_one_task_only(self):
        """The 2026-07-19 case: every cursor post stacked a task while the GPU queue was busy."""
        for t in range(5):
            answer = post_cursor(self.channel, {'t': t}, self._spawn)
        self.assertEqual(1, len(self.spawned))
        self.assertEqual({'running': True, 'started': False}, answer)
        self.assertEqual({'t': 4}, cache.get(self.channel.key('cursor')))

    def test_disabling_stops_a_running_loop_at_once(self):
        cache.set(self.channel.key('lock'), 'task', 30)
        self.assertEqual({'running': True, 'started': False}, post_cursor(self.channel, None, self._spawn))
        self.assertEqual('user', cache.get(self.channel.key('stop')))
        self.assertIsNone(cache.get(self.channel.key('cursor')))

    def test_disabling_with_nothing_running_leaves_no_stop_order_behind(self):
        post_cursor(self.channel, None, self._spawn)
        self.assertIsNone(cache.get(self.channel.key('stop')))

    def test_the_loop_follows_the_cursor_then_stops_when_idle(self):
        clock, seen = _Clock(), []
        cache.set(self.channel.key('cursor'), {'t': 3.0}, 120)

        def step(cursor):
            seen.append(cursor['t'])
            if len(seen) == 2:
                cache.delete(self.channel.key('cursor'))       # the listener went away
            clock.now += 1
            return True

        reason = follow(self.channel, 'task', step, clock=clock, sleep=clock.sleep)
        self.assertEqual('idle', reason)
        self.assertEqual([3.0, 3.0], seen)
        self.assertIsNone(cache.get(self.channel.key('lock')), 'the lock dies with its loop')

    def test_model_loading_happens_only_once_the_lock_is_held(self):
        cache.set(self.channel.key('lock'), 'other', 30)
        loaded = []
        self.assertEqual('already_running', follow(self.channel, 'task', lambda c: True,
                                                   on_start=lambda: loaded.append(1)))
        self.assertEqual([], loaded)

    def test_a_stop_order_ends_the_loop_with_its_reason(self):
        cache.set(self.channel.key('cursor'), {'t': 0}, 120)
        cache.set(self.channel.key('stop'), 'user', 120)
        self.assertEqual('user', follow(self.channel, 'task', lambda c: True))
        self.assertIsNone(cache.get(self.channel.key('stop')))

    def test_a_priority_job_takes_the_gpu_back_and_a_cooldown_drains_the_backlog(self):
        cache.set(self.channel.key('cursor'), {'t': 0}, 120)
        self.assertEqual('preempt', follow(self.channel, 'task', lambda c: True,
                                           should_yield=lambda: True))
        self.assertEqual('cooldown', follow(self.channel, 'task', lambda c: True),
                         'a task stacked meanwhile leaves silently')

    def test_starting_lifts_the_spawn_lock(self):
        cache.set(self.channel.key('spawn'), 1, 15)
        follow(self.channel, 'task', lambda c: True, idle_seconds=0, sleep=lambda s: None)
        self.assertIsNone(cache.get(self.channel.key('spawn')))

    def test_an_error_in_a_step_propagates_and_frees_the_lock(self):
        cache.set(self.channel.key('cursor'), {'t': 0}, 120)

        def boom(cursor):
            raise RuntimeError('model crashed')

        with self.assertRaises(RuntimeError):
            follow(self.channel, 'task', boom)
        self.assertIsNone(cache.get(self.channel.key('lock')))
