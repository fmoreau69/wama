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


@override_settings(CACHES=LOCMEM)
class LoopResultsTest(SimpleTestCase):
    """2026-11-16 : a loop never writes the item — it leaves RESULTS that the page reads from an
    index (the transcriber wrote that in its task and view ; the second loop put it here)."""

    def test_results_are_numbered_and_read_from_an_index(self):
        from wama.common.services.playhead_follow import append_result, results_since
        cache.clear()
        channel = Channel('test_results', 3)
        self.assertEqual({'next': 0, 'running': False, 'results': []}, results_since(channel, -1))
        self.assertEqual(0, append_result(channel, {'x': 'a'})['id'])
        self.assertEqual(1, append_result(channel, {'x': 'b'})['id'])
        self.assertEqual([], results_since(channel, -1)['results'], 'a page that opens replays nothing')
        self.assertEqual(['a', 'b'], [r['x'] for r in results_since(channel, 0)['results']])
        self.assertEqual((2, ['b']), (results_since(channel, 1)['next'],
                                      [r['x'] for r in results_since(channel, '1')['results']]))
        self.assertEqual([], results_since(channel, 'nonsense')['results'])


class ObjectTrackingSlicesTest(SimpleTestCase):
    """2026-11-16 (`services/object_tracking`) : a designated object is followed slice by slice —
    forward first, each slice from the last box seen, then backward from the box found on the
    designated frame ; a direction ends at an edge of the medium or when the object is lost."""

    WINDOW = 10

    def _engine(self, total, lost_from=None):
        """A stand-in for `track_object` on a medium of `total` frames ; the object is no longer
        seen from frame `lost_from` on."""
        calls = []

        def track(frame, *, count, reverse=False, point=None, box=None):
            calls.append((frame, 'point' if point is not None else 'box', reverse))
            spanned = (range(frame, max(frame - count, -1), -1) if reverse
                       else range(frame, min(frame + count, total)))
            return [{'i': i, 'box': None if (lost_from is not None and i >= lost_from)
                     else [i, 0, i + 5, 5]} for i in spanned]
        return track, calls

    def _follow(self, track, target):
        from wama.common.services import object_tracking as tracking
        progress, frames, turns = {}, [], 0
        while (planned := tracking.next_slice(progress, target)) is not None:
            direction, frame, designation = planned
            found = track(frame, count=self.WINDOW, reverse=direction == tracking.BACKWARD,
                          **designation)
            frames += tracking.advance(progress, direction, found, self.WINDOW)
            turns += 1
            self.assertLess(turns, 50, 'a tracking always ends')
        self.assertTrue(tracking.finished(progress, target))
        return frames

    def test_both_directions_cover_the_medium_once(self):
        track, calls = self._engine(total=27)
        frames = self._follow(track, {'id': 'a', 'i': 12, 'point': [3, 3]})
        self.assertEqual(sorted(range(27)), sorted(f['i'] for f in frames), 'every frame, once')
        self.assertEqual((12, 'point', False), calls[0], 'the point designates the first slice only')
        self.assertTrue(all(kind == 'box' for _f, kind, _r in calls[1:]))
        self.assertEqual([12, 21], [f for f, _k, reverse in calls if not reverse])
        self.assertEqual([12, 3], [f for f, _k, reverse in calls if reverse],
                         'a slice starts again where the one before stopped')

    def test_a_lost_object_ends_its_direction(self):
        track, calls = self._engine(total=200, lost_from=30)
        frames = self._follow(track, {'id': 'a', 'i': 25, 'point': [3, 3]})
        self.assertEqual(list(range(25, 30)), sorted(f['i'] for f in frames if f['i'] >= 25))
        self.assertLessEqual(len([c for c in calls if not c[2]]), 2, 'no slice after the loss')
        self.assertEqual(0, min(f['i'] for f in frames), 'the other direction goes to its edge')

    def test_an_object_not_seen_where_it_was_designated_gives_nothing(self):
        track, calls = self._engine(total=40, lost_from=0)
        self.assertEqual([], self._follow(track, {'id': 'a', 'i': 5, 'point': [3, 3]}))
        self.assertEqual(1, len(calls), 'nothing to follow backward from')

    def test_a_still_image_is_its_only_frame(self):
        track, _calls = self._engine(total=1)
        self.assertEqual([{'i': 0, 'box': [0, 0, 5, 5]}],
                         self._follow(track, {'id': 'a', 'i': 0, 'point': [3, 3]}))

    def test_targets_are_cleaned_and_capped(self):
        from wama.common.services import object_tracking as tracking
        cleaned = tracking.clean_targets([{'id': 7, 'i': '4', 'point': ['10', 20.5]}] * 20)
        self.assertEqual(tracking.MAX_TARGETS, len(cleaned))
        self.assertEqual({'id': '7', 'i': 4, 'point': [10.0, 20.5]}, cleaned[0])
        for bad in ([{'id': 1, 'i': 0, 'point': [1]}], [{'id': 1, 'i': 0, 'point': [-1, 2]}],
                    [{'id': 1, 'point': [1, 2]}]):
            with self.assertRaises((ValueError, KeyError, TypeError)):
                tracking.clean_targets(bad)
