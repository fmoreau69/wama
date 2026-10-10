"""Prospection sources that name a model by QUALITY or by its AUTHOR (2026-10-10).

Measured that day: the Hugging Face prospection searched by TAG and sorted by POPULARITY. On
olmOCR-Bench, 6 of the 7 best OCR models publish `image-text-to-text` — a tag the OCR sweep never
reads — and the third had 386 downloads. Two sources answer it, each guarded here:
  • the LEADERBOARDS (`seed_benchmark_candidates`): the bench gives the task and the rank;
  • the SUCCESSORS (`seed_hf_successors`): the author names the next version on the card
    (`new_version`), as `allenai/olmOCR-7B-0225-preview` → `…-0825` → `olmOCR-2-7B-1025`.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services import benchmark_sync as bs
from wama.model_manager.services import prospector as p


def _info(repo, tags=('image-text-to-text', 'ocr'), pipeline='image-text-to-text',
          new_version=None, license='mit'):
    card = {'license': license}
    if new_version:
        card['new_version'] = new_version
    return SimpleNamespace(id=repo, card_data=card, tags=list(tags), pipeline_tag=pipeline,
                           downloads=10, likes=1)


class _FakeApi:
    """`HfApi` stand-in: `model_info` answers from a table, raises for an unknown repository."""

    def __init__(self, infos):
        self.infos = {k.lower(): v for k, v in infos.items()}
        self.calls = []

    def model_info(self, repo):
        self.calls.append(repo)
        try:
            return self.infos[repo.lower()]
        except KeyError:
            raise RuntimeError(f'{repo}: not found') from None


def _entry(repo, rank, value, population=4):
    return {'repo': repo.lower(), 'name': repo, 'value': value, 'direction': 'higher',
            'scale': 'hf_bench:allenai/olmOCR-bench:overall', 'source': 'hf_bench',
            'source_label': 'Hub', 'provenance': 'self_declared', 'rank': rank,
            'population': population}


class OcrVisionLanguageModelTaskTest(TestCase):

    def test_a_vlm_that_tags_ocr_is_an_ocr_model(self):
        self.assertEqual(('ocr', 'ocr'), p.hf_task_to_wama('image-text-to-text', ['ocr']))

    def test_a_conversational_vlm_stays_captioning(self):
        # Counter-check: without the author's `ocr` tag nothing changes.
        self.assertEqual(('captioning', 'vlm'),
                         p.hf_task_to_wama('image-text-to-text', ['conversational']))


class LeaderboardReposTest(TestCase):

    def _load(self, source, cache='off'):
        if source['key'] == 'hf_bench':
            return {'ocr-olmocr-bench': [
                {'name': 'Org/Worse', 'repo': 'org/worse', 'value': 10.0, 'lower_is_better': True},
                {'name': 'Org/Better', 'repo': 'org/better', 'value': 3.0, 'lower_is_better': True},
            ]}, {}
        if source['key'] == 'aa':
            # A source that names no repository designates nothing installable.
            return {'text-to-image': [{'name': 'Some Model', 'value': 1200.0}]}, {}
        raise bs.SourceUnavailable('offline')

    def test_a_board_is_ranked_in_the_direction_of_its_scale_and_carries_its_task(self):
        with patch.object(bs, '_load_source', side_effect=self._load):
            boards, reasons = bs.leaderboard_repos()
        board = boards['ocr-olmocr-bench']
        self.assertEqual('ocr', board['task'])
        self.assertEqual([('org/better', 1, 2), ('org/worse', 2, 2)],
                         [(e['repo'], e['rank'], e['population']) for e in board['entries']])
        self.assertNotIn('text-to-image', boards)
        self.assertIn('open_asr', reasons)

    def test_the_task_of_a_category_is_read_back_from_the_task_table(self):
        self.assertEqual('transcription', bs.category_task('speech-to-text-fr'))
        self.assertEqual('feature-extraction', bs.category_task('embedding'))
        self.assertIsNone(bs.category_task('no-such-bench'))


@patch.object(p, 'analyze_license', return_value=None)
@patch.object(p, '_repo_weight_gb', return_value=2.0)
@patch.object(p, '_gpu_total_gb', return_value=24.0)
class LeaderboardCandidatesTest(TestCase):
    CAT = 'ocr-olmocr-bench'

    def _seed(self, entries, infos, **kw):
        board = {self.CAT: {'task': 'ocr', 'entries': entries}}
        with patch.object(bs, 'leaderboard_repos', return_value=(board, {})), \
                patch('huggingface_hub.HfApi', return_value=_FakeApi(infos)):
            return p.seed_benchmark_candidates(**kw)

    def test_the_bench_gives_the_task_and_the_rank(self, *_):
        self._seed([_entry('lightonai/LightOnOCR-3-1B', 1, 85.5)],
                   {'lightonai/lightonocr-3-1b': _info('lightonai/LightOnOCR-3-1B',
                                                       tags=('conversational',))})
        cand = AIModel.objects.get(model_key='proposed:hf:lightonai/LightOnOCR-3-1B')
        # The tag alone would say `captioning`: the leaderboard says what was measured.
        self.assertEqual(('ocr', 'ocr'), (cand.capabilities['task'], cand.model_type))
        prospect = cand.extra_info['prospect']
        self.assertEqual(f'bench:{self.CAT}', prospect['role'])
        self.assertEqual((1, 4), (prospect['leaderboard']['rank'],
                                  prospect['leaderboard']['population']))
        self.assertEqual('ocr', prospect['spec']['task'])

    def test_an_installed_repository_is_skipped_and_the_next_one_taken(self, *_):
        AIModel.objects.create(model_key='albert:lightonocr', name='LightOnOCR', model_type='ocr',
                               source='albert', is_downloaded=True,
                               hf_id='lightonai/LightOnOCR-2-1B')
        r = self._seed([_entry('lightonai/LightOnOCR-2-1B', 1, 90.0),
                        _entry('datalab-to/chandra-ocr-2', 2, 85.8)],
                       {'datalab-to/chandra-ocr-2': _info('datalab-to/chandra-ocr-2')},
                       per_category=1)
        self.assertEqual(1, r['total'])
        self.assertTrue(AIModel.objects.filter(
            model_key='proposed:hf:datalab-to/chandra-ocr-2').exists())

    def test_a_model_too_large_even_quantized_is_not_proposed(self, *_):
        with patch.object(p, '_repo_weight_gb', return_value=360.0):
            r = self._seed([_entry('final-bench/Darwin-180B', 1, 83.6)],
                           {'final-bench/darwin-180b': _info('final-bench/Darwin-180B')})
        self.assertEqual(0, r['total'])

    def test_an_unreachable_repository_is_skipped(self, *_):
        # Open ASR names API services the same way (`microsoft/azure-speech-…`): no repository.
        r = self._seed([_entry('microsoft/azure-speech', 1, 3.1)], {})
        self.assertEqual(0, r['total'])

    def test_a_board_not_read_this_pass_purges_nothing(self, *_):
        self._seed([_entry('org/kept', 1, 80.0)], {'org/kept': _info('org/kept')})
        with patch.object(bs, 'leaderboard_repos', return_value=({}, {'hf_bench': 'offline'})), \
                patch('huggingface_hub.HfApi', return_value=_FakeApi({})):
            p.seed_benchmark_candidates()
        self.assertTrue(AIModel.objects.filter(model_key='proposed:hf:org/kept').exists())

    def test_a_board_read_again_purges_what_left_its_top(self, *_):
        # Counter-check of the previous test: the same board, read, drops the candidate.
        self._seed([_entry('org/old', 1, 80.0)], {'org/old': _info('org/old')})
        self._seed([_entry('org/new', 1, 81.0)], {'org/new': _info('org/new')})
        self.assertFalse(AIModel.objects.filter(model_key='proposed:hf:org/old').exists())
        self.assertTrue(AIModel.objects.filter(model_key='proposed:hf:org/new').exists())


class SuccessorChainTest(TestCase):

    def test_the_chain_follows_the_author_to_the_latest_version(self):
        api = _FakeApi({
            'allenai/olmocr-7b-0225-preview': _info('allenai/olmOCR-7B-0225-preview',
                                                    new_version='allenai/olmOCR-7B-0825'),
            'allenai/olmocr-7b-0825': _info('allenai/olmOCR-7B-0825',
                                            new_version='allenai/olmocr-2-7b-1025'),
            'allenai/olmocr-2-7b-1025': _info('allenai/olmOCR-2-7B-1025')})
        chain, info = p.hf_successor('allenai/olmOCR-7B-0225-preview', api=api)
        # The canonical spelling of the last link is the one the Hub returns.
        self.assertEqual(['allenai/olmOCR-7B-0825', 'allenai/olmOCR-2-7B-1025'], chain)
        self.assertEqual('allenai/olmOCR-2-7B-1025', info.id)

    def test_a_loop_stops_the_chain(self):
        api = _FakeApi({'a/one': _info('a/one', new_version='a/two'),
                        'a/two': _info('a/two', new_version='a/one')})
        self.assertEqual(['a/two'], p.hf_successor('a/one', api=api)[0])

    def test_a_card_without_new_version_has_no_successor(self):
        self.assertEqual(([], None), p.hf_successor('a/one', api=_FakeApi({'a/one': _info('a/one')})))


@patch.object(p, 'analyze_license', return_value=None)
@patch.object(p, '_repo_weight_gb', return_value=16.0)
class SuccessorCandidatesTest(TestCase):

    def setUp(self):
        self.src = AIModel.objects.create(
            model_key='reader:olmocr', name='olmOCR', model_type='ocr', source='reader',
            is_downloaded=True, hf_id='allenai/olmOCR-7B-0225-preview',
            capabilities={'task': 'ocr'})
        self.api = _FakeApi({
            'allenai/olmocr-7b-0225-preview': _info('allenai/olmOCR-7B-0225-preview',
                                                    new_version='allenai/olmOCR-2-7B-1025'),
            'allenai/olmocr-2-7b-1025': _info('allenai/olmOCR-2-7B-1025', tags=('conversational',))})

    def _seed(self, api=None):
        with patch('huggingface_hub.HfApi', return_value=api or self.api):
            return p.seed_hf_successors(workers=1)

    def test_the_successor_is_proposed_as_an_update_of_the_installed_row(self, *_):
        self._seed()
        cand = AIModel.objects.get(model_key='proposed:reader:olmocr')
        prospect = cand.extra_info['prospect']
        self.assertEqual(('update', 0.9), (cand.proposal_kind, cand.confidence))
        self.assertEqual(('reader:olmocr', 'allenai/olmOCR-2-7B-1025', 'successeur'),
                         (prospect['origin_key'], prospect['cible'], prospect['maj']))
        # Same job as the row it replaces, whatever the successor's tag says.
        self.assertEqual(('ocr', 'ocr'), (cand.capabilities['task'], cand.model_type))
        self.assertEqual({'kind': 'hf', 'ref': 'allenai/olmOCR-2-7B-1025'},
                         {k: prospect['spec'][k] for k in ('kind', 'ref')})

    def test_an_installed_successor_is_not_proposed(self, *_):
        AIModel.objects.create(model_key='huggingface:allenai/olmOCR-2-7B-1025', name='olmOCR-2',
                               model_type='ocr', source='huggingface', is_downloaded=True,
                               hf_id='allenai/olmOCR-2-7B-1025')
        self.assertEqual(0, self._seed()['total'])

    def test_an_unreachable_hub_purges_nothing(self, *_):
        self._seed()
        self._seed(api=_FakeApi({}))
        self.assertTrue(AIModel.objects.filter(model_key='proposed:reader:olmocr').exists())

    def test_installing_a_successor_frees_no_space(self, *_):
        from wama.model_manager.services.model_installer import replaced_model
        self._seed()
        cand = AIModel.objects.get(model_key='proposed:reader:olmocr')
        self.assertEqual((None, 0.0), replaced_model(cand))

    def test_an_ollama_successor_still_frees_the_old_model(self, *_):
        # Counter-check: the guard reads the descriptor; Ollama replacements are unchanged.
        from wama.model_manager.services.model_installer import replaced_model
        AIModel.objects.create(model_key='ollama:qwen3.5:9b', name='qwen3.5:9b', model_type='llm',
                               source='ollama', is_downloaded=True, disk_gb=6.6)
        cand = AIModel.objects.create(
            model_key='proposed:ollama:qwen3.5:9b', name='qwen3.6:27b', model_type='llm',
            source='ollama', is_proposed=True, proposal_kind='update',
            extra_info={'prospect': {'origin_key': 'ollama:qwen3.5:9b', 'cible': 'qwen3.6:27b'}})
        self.assertEqual(('qwen3.5:9b', 6.6), replaced_model(cand))


class ProspectVerbTest(TestCase):
    """« Prospecter » (2026-10-10): the assistant's `prospect_models` and the page's button share
    ONE body (`run_prospection`) — the assistant takes the same verbs as the page."""

    SUMMARY = {'created': 1, 'updated': 2, 'removed': 0, 'total': 9,
               'hf_successors': {'created': 1, 'updated': 0, 'removed': 0, 'total': 1},
               'hf': {'error': 'indisponible'},
               'benchmarks': {'created': 5, 'updated': 0, 'removed': 1, 'total': 5,
                              'boards_ok': ['ocr-olmocr-bench']},
               'benchmarks_enqueued': True, 'assess_enqueued': False}

    def test_the_tool_runs_the_shared_body_and_reports_each_source(self):
        from django.contrib.auth import get_user_model
        from wama import tool_api
        user = get_user_model().objects.create_user('prospect_verb', password='x')
        with patch.object(p, 'run_prospection', return_value=dict(self.SUMMARY)) as run:
            out = tool_api.prospect_models(user)
        run.assert_called_once_with()
        self.assertEqual(9, out['total'])
        self.assertEqual({'error': 'indisponible'}, out['sources']['hf'])
        self.assertEqual(5, out['sources']['benchmarks']['created'])
        self.assertEqual({'created': 1, 'updated': 2, 'removed': 0}, out['sources']['ollama'])

    def test_the_button_runs_the_same_body(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_superuser('prospect_button', password='x')
        self.client.force_login(user)
        with patch.object(p, 'run_prospection', return_value=dict(self.SUMMARY)) as run:
            r = self.client.post('/model-manager/api/prospect/ollama/', '{}',
                                 content_type='application/json')
        self.assertEqual(200, r.status_code, r.content[:200])
        run.assert_called_once_with()
        self.assertEqual(9, r.json()['summary']['total'])

    def test_one_failing_source_does_not_stop_the_others(self):
        with patch('wama.model_manager.services.prospect_ollama.prospect_ollama',
                   return_value={'created': 0, 'updated': 0, 'removed': 0, 'total': 0}), \
                patch.object(p, 'seed_hf_successors', side_effect=RuntimeError('offline')), \
                patch.object(p, 'seed_hf_candidates', return_value={'total': 2}), \
                patch.object(p, 'seed_benchmark_candidates', return_value={'total': 3}), \
                patch.object(p, 'enqueue_after_prospection',
                             return_value={'benchmarks_enqueued': True, 'assess_enqueued': False}):
            out = p.run_prospection()
        self.assertEqual({'error': 'indisponible'}, out['hf_successors'])
        self.assertEqual(5, out['total'])


class _RateLimited(Exception):
    """What `huggingface_hub` raises on a 429: an HTTP error carrying its response."""

    def __init__(self):
        super().__init__('429 Client Error: Too Many Requests')
        self.response = SimpleNamespace(status_code=429, headers={'Retry-After': '2'})


class _RateLimitedApi(_FakeApi):
    """Answers from the table until `fail_after` calls, then refuses everything with a 429."""

    def __init__(self, infos, fail_after=0):
        super().__init__(infos)
        self.fail_after = fail_after

    def model_info(self, repo):
        if len(self.calls) >= self.fail_after:
            self.calls.append(repo)
            raise _RateLimited()
        return super().model_info(repo)


@patch('time.sleep')
class HubRateLimitTest(TestCase):
    """Measured 2026-10-10: the full prospection run by the assistant got 429 on EVERY leaderboard
    repository, right after the task sweep — skipped silently, and the board counted as read, so
    its purge would have emptied the candidates of a previous pass."""

    def test_one_retry_after_the_wait_the_hub_asks_for(self, sleep):
        class Once(_FakeApi):
            def model_info(self, repo):
                self.calls.append(repo)
                if len(self.calls) == 1:
                    raise _RateLimited()
                return _info(repo)
        self.assertEqual('a/b', p._hub_model_info(Once({}), 'a/b').id)
        sleep.assert_called_once_with(2.0)

    def test_a_persistent_refusal_stops_the_pass(self, sleep):
        with self.assertRaises(p.HubRateLimited):
            p._hub_model_info(_RateLimitedApi({}), 'a/b')

    @patch.object(p, 'analyze_license', return_value=None)
    @patch.object(p, '_repo_weight_gb', return_value=2.0)
    @patch.object(p, '_gpu_total_gb', return_value=24.0)
    def test_an_interrupted_board_purges_nothing(self, *_):
        board = {'ocr-olmocr-bench': {'task': 'ocr', 'entries': [_entry('org/kept', 1, 80.0)]}}
        with patch.object(bs, 'leaderboard_repos', return_value=(board, {})), \
                patch('huggingface_hub.HfApi', return_value=_FakeApi({'org/kept': _info('org/kept')})):
            p.seed_benchmark_candidates()
        other = {'ocr-olmocr-bench': {'task': 'ocr', 'entries': [_entry('org/new', 1, 81.0)]}}
        with patch.object(bs, 'leaderboard_repos', return_value=(other, {})), \
                patch('huggingface_hub.HfApi', return_value=_RateLimitedApi({})):
            out = p.seed_benchmark_candidates()
        self.assertTrue(out['rate_limited'])
        self.assertEqual([], out['boards_ok'])
        self.assertTrue(AIModel.objects.filter(model_key='proposed:hf:org/kept').exists())

    @patch.object(p, 'analyze_license', return_value=None)
    @patch.object(p, '_repo_weight_gb', return_value=16.0)
    def test_a_successor_that_could_not_be_read_again_keeps_its_candidate(self, *_):
        AIModel.objects.create(model_key='reader:olmocr', name='olmOCR', model_type='ocr',
                               source='reader', is_downloaded=True,
                               hf_id='allenai/olmOCR-7B-0225-preview', capabilities={'task': 'ocr'})
        AIModel.objects.create(model_key='transcriber:other', name='other', model_type='speech',
                               source='transcriber', is_downloaded=True, hf_id='org/other')
        infos = {'allenai/olmocr-7b-0225-preview': _info('allenai/olmOCR-7B-0225-preview',
                                                         new_version='allenai/olmOCR-2-7B-1025'),
                 'allenai/olmocr-2-7b-1025': _info('allenai/olmOCR-2-7B-1025'),
                 'org/other': _info('org/other')}
        with patch('huggingface_hub.HfApi', return_value=_FakeApi(infos)):
            p.seed_hf_successors(workers=1)
        # Second pass: `org/other` is read (so the source counts as reached), olmOCR is refused.
        class Partial(_FakeApi):
            def model_info(self, repo):
                if 'olmocr' in repo.lower():
                    raise _RateLimited()
                return super().model_info(repo)
        with patch('huggingface_hub.HfApi', return_value=Partial(infos)):
            out = p.seed_hf_successors(workers=1)
        self.assertTrue(out['rate_limited'])
        self.assertTrue(AIModel.objects.filter(model_key='proposed:reader:olmocr').exists())
