"""The common quota brick of external services (ROADMAP §8d step 3, 2026-10-14).

Before it, five places handled a rate limit (HTTP 429) each its own way and none COUNTED: a limit
was found by hitting it. The brick counts every served call per (source, key scope, model), reads
the ceilings DECLARED on the source (`ExternalSource.quotas`), LEARNS the ceiling at the first real
refusal, and the automatic draw leaves out a model whose quota is reached — before the refusal.
"""
import os
import tempfile
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from wama.common import external_sources
from wama.common.external_sources import Quota
from wama.common.services import source_quota as q

#: A fixed instant at the START of a minute (1 000 000 020 = 16 666 667 minutes exactly): the
#: sliding estimate then reads the current window alone.
T0 = 1_000_000_020.0


class QuotaTestCase(SimpleTestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()


class CountTest(QuotaTestCase):

    def test_a_served_call_is_counted_for_its_key_and_its_model(self):
        q.record('albert', 'user:1', 'chat', now=T0)
        q.record('albert', 'user:1', 'chat', now=T0)
        self.assertEqual(2, q.used('albert', 'user:1', 'm:chat', q.REQUESTS, q.MINUTE, T0))
        # Counter-tests: another key, another model are not concerned.
        self.assertEqual(0, q.used('albert', 'instance', 'm:chat', q.REQUESTS, q.MINUTE, T0))
        self.assertEqual(0, q.used('albert', 'user:1', 'm:other', q.REQUESTS, q.MINUTE, T0))

    def test_tokens_are_counted_apart_from_requests(self):
        q.record('albert', 'user:1', 'chat', tokens=150, now=T0)
        self.assertEqual(150, q.used('albert', 'user:1', 'm:chat', q.TOKENS, q.MINUTE, T0))
        self.assertEqual(1, q.used('albert', 'user:1', 'm:chat', q.REQUESTS, q.MINUTE, T0))

    def test_the_count_slides_over_the_window_boundary(self):
        """Just after the boundary, the calls of the previous minute still weigh: a provider that
        counts by sliding window would refuse there, and a fixed count would read 0."""
        start = (T0 // 60) * 60                     # a minute boundary
        for _ in range(10):
            q.record('albert', 'user:1', 'chat', now=start + 50)
        self.assertEqual(9, q.used('albert', 'user:1', 'm:chat', q.REQUESTS, q.MINUTE, start + 66))
        self.assertEqual(0, q.used('albert', 'user:1', 'm:chat', q.REQUESTS, q.MINUTE, start + 130))


class DeclaredQuotaTest(QuotaTestCase):

    def test_the_free_models_of_openrouter_share_one_counter(self):
        """Declared on the source: 20 requests a minute for ALL the `:free` models together."""
        self.assertIn(Quota(20, 60, models=':free'), external_sources.get('openrouter').quotas)
        for i in range(20):
            q.record('openrouter', 'user:1', f'vendor/model-{i % 2}:free', now=T0)
        self.assertEqual(q.QUOTA_REACHED, q.exhausted('openrouter', 'user:1', 'vendor/model-0:free', T0))
        self.assertEqual(q.QUOTA_REACHED, q.exhausted('openrouter', 'user:1', 'other/x:free', T0))
        # Counter-test: a paid model of the same source is outside that group.
        self.assertEqual('', q.exhausted('openrouter', 'user:1', 'vendor/model', T0))

    def test_a_per_model_quota_counts_each_model_alone(self):
        quota = Quota(2, 60, per_model=True)
        with mock.patch.object(q, '_declared', return_value=(quota,)):
            q.record('albert', 'user:1', 'a', now=T0)
            q.record('albert', 'user:1', 'a', now=T0)
            q.record('albert', 'user:1', 'b', now=T0)
            self.assertEqual(q.QUOTA_REACHED, q.exhausted('albert', 'user:1', 'a', T0))
            self.assertEqual('', q.exhausted('albert', 'user:1', 'b', T0))

    def test_a_source_that_announces_nothing_is_never_blocked_by_the_count(self):
        """ILaaS, measured on 2026-10-14: no limit header, no `/me/info`. Nothing declared."""
        self.assertEqual((), external_sources.get('ilaas').quotas)
        for _ in range(500):
            q.record('ilaas', 'instance', 'mistral', now=T0)
        self.assertEqual('', q.exhausted('ilaas', 'instance', 'mistral', T0))


class LearnedCeilingTest(QuotaTestCase):

    def test_the_first_real_refusal_teaches_the_ceiling(self):
        for _ in range(10):
            q.record('ilaas', 'instance', 'mistral', now=T0)
        self.assertEqual(10, q.learn_from_refusal('ilaas', 'instance', 'mistral', now=T0))
        self.assertEqual(q.QUOTA_REACHED, q.exhausted('ilaas', 'instance', 'mistral', T0))
        # Two minutes later the window is empty again: the model comes back.
        self.assertEqual('', q.exhausted('ilaas', 'instance', 'mistral', T0 + 120))

    def test_a_long_wait_means_the_daily_limit_was_hit(self):
        for _ in range(4):
            q.record('albert', 'user:1', 'chat', now=T0)
        q.learn_from_refusal('albert', 'user:1', 'chat', retry_after_s=3600, now=T0)
        # Still out an hour later: it is the day that is used up, not the minute.
        self.assertEqual(q.QUOTA_REACHED, q.exhausted('albert', 'user:1', 'chat', T0 + 3600))

    def test_the_last_refusal_decides_never_the_lowest(self):
        """A ceiling that could only go down would end at 1."""
        for _ in range(3):
            q.record('albert', 'user:1', 'chat', now=T0)
        q.learn_from_refusal('albert', 'user:1', 'chat', now=T0)
        for _ in range(8):
            q.record('albert', 'user:1', 'chat', now=T0 + 600)
        self.assertEqual(8, q.learn_from_refusal('albert', 'user:1', 'chat', now=T0 + 600))

    def test_nothing_served_teaches_nothing(self):
        self.assertEqual(0, q.learn_from_refusal('albert', 'user:1', 'chat', now=T0))
        self.assertEqual('', q.exhausted('albert', 'user:1', 'chat', T0))


class UnavailableKeysTest(QuotaTestCase):

    def test_the_draw_leaves_out_a_noted_source_and_a_used_up_model(self):
        q.note_saturation('anthropic', scope=q.ALL_KEYS, seconds=60, reason='indisponible')
        for _ in range(5):
            q.record('albert', 'user:1', 'chat')
        q.learn_from_refusal('albert', 'user:1', 'chat')
        out = q.unavailable_keys(['albert:chat', 'albert:other', 'anthropic:claude', 'ilaas:m'],
                                 lambda source: 'user:1')
        self.assertEqual({'albert:chat': q.QUOTA_REACHED, 'anthropic:claude': 'indisponible'}, out)


class SearchEngineQuotaTest(QuotaTestCase):
    """A search engine that refuses (429) is noted by the same brick, and the next search goes to
    the next usable engine while the note lasts — there was no fallback at all before."""

    class _Resp:
        def __init__(self, status, payload=None):
            self.status_code, self._payload, self.headers = status, payload or {}, {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            pass

    def _engine_for(self):
        from wama.common.search_engines import registry
        with mock.patch.object(registry, 'preferred_slug', return_value='exa'), \
                mock.patch.object(registry, 'usable_slugs', return_value=['exa', 'staan']), \
                mock.patch.object(registry, 'key_for', return_value='k'):
            return registry.engine_for(None).slug

    def test_a_refusal_hands_the_next_search_to_the_next_engine(self):
        from wama.common.search_engines import SearchEngineUnavailable, get_engine
        self.assertEqual('exa', self._engine_for())
        engine = get_engine('exa', api_key='k')
        with mock.patch('requests.post', return_value=self._Resp(429)):
            with self.assertRaises(SearchEngineUnavailable):
                engine.search('monstera')
        self.assertEqual('staan', self._engine_for())

    def test_a_served_search_is_counted(self):
        from wama.common.search_engines import get_engine
        engine = get_engine('exa', api_key='k', scope='user:2')
        with mock.patch('requests.post', return_value=self._Resp(200, {'results': []})):
            engine.search('monstera')
        self.assertEqual(1, q.used('exa', 'user:2', 'm:', q.REQUESTS, q.MINUTE))


class AlbertTranscriptionCountsTest(QuotaTestCase):
    """The speech recognition of Albert has its own wait on 429: it now counts and notes through
    the same brick, so the dictation and the draw see its refusals."""

    def setUp(self):
        super().setUp()
        from wama.common.backends.albert_asr_backend import AlbertTranscriptionBackend
        self.folder = tempfile.mkdtemp()
        self.audio = os.path.join(self.folder, 'a.wav')
        with open(self.audio, 'wb') as fh:
            fh.write(b'RIFF')
        self.backend = AlbertTranscriptionBackend()
        self.backend.authorize('key', scope='user:3')

    def _post(self, *statuses):
        responses = [mock.MagicMock(status_code=s, headers={}, json=lambda: {'text': ''})
                     for s in statuses]
        with mock.patch('requests.post', side_effect=responses), mock.patch('time.sleep'):
            try:
                self.backend._post(self.audio, {'model': 'whisper'}, retries=len(statuses) - 1)
            except Exception:
                pass

    def test_a_served_transcription_is_counted_for_the_key(self):
        self._post(200)
        self.assertEqual(1, q.used('albert', 'user:3', 'm:whisper', q.REQUESTS, q.MINUTE))

    def test_a_refusal_is_noted_for_the_key(self):
        self._post(429)
        self.assertEqual('limite de débit', q.saturated_sources({'albert': 'user:3'}).get('albert'))
        # Counter-test: another key is not concerned.
        self.assertEqual({}, q.saturated_sources({'albert': 'user:4'}))
