"""Benchmarks made reliable at the source (2026-10-10) — the chain, the identity, the provenance.

Measured that day on the real catalogue (dry-run synchronisation): 27 of ~160 installed or remote
models had a benchmark. Three structural holes, each guarded here:
  • the CHAIN — an installed model got its benchmark only at the next FULL synchronisation (button
    or prospection), never scheduled: `queue_benchmarks`, the nightly entry, the source cache;
  • the IDENTITY — matching needed « family + version », an LLM rule: 20 media models (`kokoro`,
    `canary-1b-v2`, `vibevoice-asr`…) could never be named, though sources publish their exact
    repository and our rows carry their `hf_id`;
  • the PROVENANCE — who produced a value (independent bench / verified / self-declared) and how
    it was attached to the model, now written with the benchmark.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings

from wama.model_manager.models import AIModel
from wama.model_manager.services import benchmark_sync as bs

from .tests import _SourcesFactices


def _row(key, name, hf_id='', task='text-to-image', **extra):
    return AIModel.objects.create(model_key=key, name=name, model_type='diffusion',
                                  source=key.split(':')[0], is_downloaded=True, hf_id=hf_id,
                                  capabilities={'task': task}, **extra)


class RepositoryIdentityTest(_SourcesFactices, TestCase):

    def _entry(self, name, identity=None, repo='', value=42.0):
        return {'name': name, 'slug': name, 'identity': identity, 'repo': repo,
                'value': value, 'scale': 'aa_elo_text_to_image'}

    def test_a_model_without_family_and_version_is_matched_by_its_repository(self):
        _row('transcriber:canary-1b-v2', 'canary-1b-v2', hf_id='nvidia/canary-1b-v2')
        with self._sources({'text-to-image': [self._entry('nvidia/canary-1b-v2',
                                                          repo='nvidia/canary-1b-v2')]}):
            r = bs.synchronize(dry_run=False)
        self.assertEqual(['transcriber:canary-1b-v2'], [k for k, *_ in r['matched']])
        meta = AIModel.objects.get(model_key='transcriber:canary-1b-v2').benchmark_meta
        self.assertEqual(('repo', 'independent'), (meta['matched_by'], meta['provenance']))

    def test_another_repository_is_not_ours(self):
        # Counter-check: equality, not resemblance — and a model named by its repository is
        # « absent from the benches », never « without identity ».
        _row('transcriber:canary-1b-v2', 'canary-1b-v2', hf_id='nvidia/canary-1b-v2')
        with self._sources({'text-to-image': [self._entry('nvidia/canary-1b-flash',
                                                          repo='nvidia/canary-1b-flash')]}):
            r = bs.synchronize(dry_run=True)
        self.assertEqual([], r['matched'])
        self.assertEqual(['transcriber:canary-1b-v2 [text-to-image]'], r['unmatched'])
        self.assertEqual([], r['without_identity'])

    def test_the_repository_wins_over_a_family_match_in_the_same_source(self):
        _row('imager:hunyuan', 'HunyuanImage 2.1', hf_id='tencent/HunyuanImage-2.1')
        same_family = self._entry('HunyuanImage 2.1 Pro', ('hunyuanimage', (2, 1), None),
                                  value=1200.0)
        exact = self._entry('tencent/HunyuanImage-2.1', ('hunyuanimage', (2, 1), None),
                            repo='tencent/hunyuanimage-2.1', value=1077.0)
        with self._sources({'text-to-image': [same_family, exact]}):
            bs.synchronize(dry_run=False)
        row = AIModel.objects.get(model_key='imager:hunyuan')
        self.assertEqual((1077.0, 'repo'), (row.benchmark_index, row.benchmark_meta['matched_by']))

    def test_the_family_and_version_rule_is_unchanged_without_a_repository(self):
        _row('imager:hunyuan', 'HunyuanImage 2.1')
        with self._sources({'text-to-image': [self._entry('HunyuanImage 2.1',
                                                          ('hunyuanimage', (2, 1), None))]}):
            bs.synchronize(dry_run=False)
        self.assertEqual('identity',
                         AIModel.objects.get(model_key='imager:hunyuan').benchmark_meta['matched_by'])

    def test_the_repositories_a_row_states(self):
        row = AIModel(model_key='proposed:hf:zai-org/GLM-OCR', hf_id='',
                      platform_ref='huggingface:Org/Other')
        self.assertEqual({'zai-org/glm-ocr', 'org/other'}, bs._local_repos(row))
        # A name is never a repository.
        self.assertEqual(set(), bs._local_repos(AIModel(model_key='synthesizer:kokoro')))

    def test_open_asr_keeps_an_entry_named_only_by_its_repository(self):
        """`nvidia/parakeet-tdt-0.6b-v3` has no « family + version » (version after the size):
        the loader dropped it, so no repository match could ever happen."""
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / 'fr.csv'
            csv.write_text('model,RTFx,FLEURS WER,MCV WER\n'
                           'nvidia/parakeet-tdt-0.6b-v3,3000,5.0,7.0\n', encoding='utf-8')
            with patch('huggingface_hub.hf_hub_download', return_value=str(csv)), \
                    patch.dict(bs.CATEGORIES, {'speech-to-text-fr': {'open_asr': 'multilingual_fr',
                                                                     'open_asr_value': None}},
                               clear=True):
                by_category, _ = bs.load_open_asr()
        entry = by_category['speech-to-text-fr'][0]
        self.assertEqual(('nvidia/parakeet-tdt-0.6b-v3', None, 6.0),
                         (entry['repo'], entry['identity'], entry['wer']))


class HubBenchmarkLeaderboardsTest(TestCase):
    """The leaderboards of the Hub's OFFICIAL benchmark datasets: exact repository, direction,
    `verified` flag and source per row — declared values, written as such."""

    ROWS = [
        {'modelId': 'lightonai/LightOnOCR-2-1B', 'value': 83.2, 'verified': False,
         'lower_is_better': False, 'source': {'name': 'LightOnOCR technical report',
                                              'url': 'https://huggingface.co/papers/2601.14251'}},
        {'modelId': 'zai-org/GLM-OCR', 'value': 75.2, 'verified': True,
         'lower_is_better': False, 'source': {'name': 'GLM-OCR API evaluation'}},
        {'modelId': 'no-repository', 'value': 99.0},
    ]

    def _get(self, rows):
        class _Response:
            def raise_for_status(self):
                pass

            def json(self):
                return rows
        return patch('requests.get', return_value=_Response())

    def test_the_loader_keeps_repository_value_direction_and_provenance(self):
        with self._get(self.ROWS), \
                patch.dict(bs.CATEGORIES, {'ocr-olmocr-bench':
                                           {'hf_bench': ('allenai/olmOCR-bench', 'overall')}},
                           clear=True):
            by_category, _ = bs.load_hf_benchmarks()
        entries = {e['repo']: e for e in by_category['ocr-olmocr-bench']}
        self.assertEqual({'lightonai/lightonocr-2-1b', 'zai-org/glm-ocr'}, set(entries),
                         'a row without a readable repository is not kept')
        self.assertEqual(('self_declared', None),
                         (entries['lightonai/lightonocr-2-1b']['provenance'],
                          entries['lightonai/lightonocr-2-1b']['identity']))
        self.assertEqual('verified', entries['zai-org/glm-ocr']['provenance'])

    def test_an_ocr_model_gets_its_declared_value_without_a_percentile(self):
        _row('albert:lightonocr-2-1b', 'LightOnOCR 2 1B', hf_id='lightonai/LightOnOCR-2-1B',
             task='ocr', execution='cloud', is_available=True)
        board = {'ocr-olmocr-bench': [
            {'name': 'lightonai/LightOnOCR-2-1B', 'slug': 'lightonai/LightOnOCR-2-1B',
             'repo': 'lightonai/lightonocr-2-1b', 'identity': None, 'value': 83.2,
             'lower_is_better': False, 'provenance': 'self_declared',
             'source_name': 'LightOnOCR technical report', 'source_url': ''},
            {'name': 'zai-org/GLM-OCR', 'slug': 'zai-org/GLM-OCR', 'repo': 'zai-org/glm-ocr',
             'identity': None, 'value': 75.2, 'lower_is_better': False,
             'provenance': 'self_declared', 'source_name': '', 'source_url': ''}]}
        source = dict(next(s for s in bs.SOURCES if s['key'] == 'hf_bench'),
                      loader=lambda: (board, {}))
        with patch.object(bs, 'SOURCES_BY_PRIORITY', (source,)):
            bs.synchronize(dry_run=False)
        row = AIModel.objects.get(model_key='albert:lightonocr-2-1b')
        meta = row.benchmark_meta
        self.assertEqual(83.2, row.benchmark_index)
        self.assertEqual(('hf_bench:allenai/olmOCR-bench:overall', 'higher', 'self_declared',
                          'repo'),
                         (meta['scale'], meta['direction'], meta['provenance'], meta['matched_by']))
        # A declared value does not enter the inter-scale stage of the selection.
        self.assertIsNone(meta['percentile_rank'])

    def test_a_lower_is_better_board_is_read_the_right_way(self):
        source = next(s for s in bs.SOURCES if s['key'] == 'hf_bench')
        self.assertEqual('lower', bs._direction(source, {'lower_is_better': True}))
        self.assertEqual('higher', bs._direction(source, {'lower_is_better': False}))

    def test_the_declared_bench_kinds(self):
        self.assertEqual(('document', 'ocr-olmocr-bench', 'ocr-mdpbench',
                          'ocr-real5-omnidocbench', 'ocr-parsebench'),
                         bs.TASK_TO_BENCH_CATEGORY['ocr'])
        self.assertEqual(('music-with-vocals', 'music-instrumental'),
                         bs.TASK_TO_BENCH_CATEGORY['text-to-music'])
        # AA's free speech-to-text index takes 4 values (measured 2026-10-10): not a source.
        self.assertNotIn('aa', bs.CATEGORIES['speech-to-text'])


class ScopeAndSourceCacheTest(_SourcesFactices, TestCase):

    def _entry(self):
        return self._entree('HunyuanImage 2.1', ('hunyuanimage', (2, 1), None))

    def test_a_synchronisation_can_be_bounded_to_the_installed_models(self):
        _row('imager:hunyuan', 'HunyuanImage 2.1')
        _row('imager:hunyuan-copy', 'HunyuanImage 2.1')
        with self._sources({'text-to-image': [self._entry()]}):
            r = bs.synchronize(dry_run=True, keys=['imager:hunyuan'])
        self.assertEqual(['imager:hunyuan'], [k for k, *_ in r['matched']])

    def test_the_cache_is_read_only_when_asked_and_keeps_identities_comparable(self):
        _row('imager:hunyuan', 'HunyuanImage 2.1')
        calls = []
        source = dict(bs.SOURCES_BY_PRIORITY[0],
                      loader=lambda: calls.append(1) or ({'text-to-image': [self._entry()]}, {}))
        with tempfile.TemporaryDirectory() as tmp, override_settings(BASE_DIR=Path(tmp)), \
                patch.object(bs, 'SOURCES_BY_PRIORITY', (source,)):
            bs.synchronize(dry_run=True, cache='off')
            self.assertFalse((Path(tmp) / 'logs/benchmarks/source_aa.json').exists(),
                             '`off` writes nothing — the default, tests included')
            bs.synchronize(dry_run=True, cache='read')       # nothing fresh: loader, then written
            r = bs.synchronize(dry_run=True, cache='read')   # fresh: from disk
            self.assertEqual(2, len(calls))
            # Identities come back from JSON as lists; matching compares tuples.
            self.assertEqual(['imager:hunyuan'], [k for k, *_ in r['matched']])
            bs.synchronize(dry_run=True, cache='refresh')
            self.assertEqual(3, len(calls))

    def test_a_stale_cache_is_reloaded(self):
        source = dict(bs.SOURCES_BY_PRIORITY[0],
                      loader=lambda: ({'text-to-image': [self._entry()]}, {}))
        with tempfile.TemporaryDirectory() as tmp, override_settings(BASE_DIR=Path(tmp)):
            path = bs._source_cache_path('aa')
            path.write_text(json.dumps({'at': 0, 'by_category': {}, 'reasons': {}}),
                            encoding='utf-8')
            by_category, _ = bs._load_source(source, 'read')
        self.assertIn('text-to-image', by_category)

    def test_an_unknown_cache_mode_is_refused(self):
        with self.assertRaises(ValueError):
            bs.synchronize(dry_run=True, cache='always')


class InstallationQueuesItsBenchmarkTest(TestCase):

    def test_the_models_that_received_their_identity_are_queued(self):
        from wama.model_manager.services.model_installer import queue_benchmarks
        res = {'provenance': {'models': [{'model': 'huggingface:Org/X', 'applied': True}]}}
        with patch('wama.model_manager.tasks.sync_benchmarks_task.delay') as delay:
            queue_benchmarks(res, ['huggingface:Org/X', 'huggingface:Org/Partial'])
        delay.assert_called_once_with(keys=['huggingface:Org/X'], cache='read')
        self.assertEqual(['huggingface:Org/X'], res['benchmarks_queued'])

    def test_without_identity_the_created_rows_are_queued(self):
        from wama.model_manager.services.model_installer import queue_benchmarks
        res = {'provenance': {'identity': {}}}
        with patch('wama.model_manager.tasks.sync_benchmarks_task.delay') as delay:
            queue_benchmarks(res, ['ollama:new:latest'])
        delay.assert_called_once_with(keys=['ollama:new:latest'], cache='read')

    def test_a_queueing_failure_never_fails_the_installation(self):
        from wama.model_manager.services.model_installer import queue_benchmarks
        res = {}
        with patch('wama.model_manager.tasks.sync_benchmarks_task.delay',
                   side_effect=RuntimeError('broker down')):
            queue_benchmarks(res, ['huggingface:Org/X'])
        self.assertNotIn('benchmarks_queued', res)

    def test_both_installation_paths_queue_it(self):
        """`record_provenance` is the single body of `install_from_spec` and of the Ollama
        branch: the benchmark is queued there, after the identity."""
        from wama.model_manager.services import model_installer as mi
        from wama.model_manager.services.model_sync import SyncResult
        with patch.object(mi, 'pull_hf_model', return_value={'ok': True, 'path': '/p'}), \
                patch.object(mi, 'register_after_install',
                             return_value=SyncResult(success=True, added=1,
                                                     added_keys=['huggingface:Org/X'])), \
                patch('wama.model_manager.services.provenance.record_after_install',
                      return_value={'identity': {'hf_id': 'Org/X'},
                                    'models': [{'model': 'huggingface:Org/X'}]}), \
                patch('wama.model_manager.tasks.sync_benchmarks_task.delay') as delay:
            res = mi.install_from_spec({'kind': 'hf', 'ref': 'Org/X', 'category': 'vision'})
        self.assertTrue(res['ok'])
        delay.assert_called_once_with(keys=['huggingface:Org/X'], cache='read')

    def test_the_benchmarks_are_refreshed_every_night(self):
        entry = settings.CELERY_BEAT_SCHEDULE['benchmarks-refresh']
        self.assertEqual(('model_manager.sync_benchmarks', 'default'),
                         (entry['task'], entry['options']['queue']))
