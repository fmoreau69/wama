"""OFFICIAL tables as benchmark sources (2026-10-29, Fabien: « pour 2, les tableaux officiels » —
« compléter la mesure à priori depuis les sources externes du mieux que l'on peut pour débloquer
la sélection auto des modèles »).

Measured that day: 111 installed models without a score. Their authors' tables (Ultralytics docs,
the olmOCR-2 card) and a single-harness French leaderboard (Linagora) score 30 of them. A row is
tied to OUR model by an EXACT identity only — the weight file of a GitHub repository, or a Hub
repository — never by a resemblance: a face fine-tune of YOLOv8 is not YOLOv8 on COCO.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services import benchmark_sync as b

ULTRA_PAGE = """
!!! tip "Performance"

    === "Detection (COCO)"

        See [Detection Docs](../tasks/detect.md) for usage examples.

        | Model                                       | size<br><sup>(pixels)</sup> | mAP<sup>val<br>50-95</sup> | Speed<br><sup>CPU ONNX<br>(ms)</sup> |
        | ------------------------------------------- | --------------------------- | -------------------------- | ------------------------------------ |
        | [YOLO11n](https://platform.ultralytics.com/x) | 640                       | 39.5                       | **56.1 ± 0.8**                       |
        | [YOLO11x](https://platform.ultralytics.com/y) | 640                       | **54.7**                   | 462.8 ± 6.7                          |

    === "Segmentation (COCO)"

        | Model                                           | size<br><sup>(pixels)</sup> | mAP<sup>box<br>50-95</sup> | mAP<sup>mask<br>50-95</sup> |
        | ----------------------------------------------- | --------------------------- | -------------------------- | --------------------------- |
        | [YOLO11n-seg](https://platform.ultralytics.com/z) | 640                       | 38.9                       | 32.0                        |
"""

CARD_PAGE = """
## olmOCR-Bench Scores

<table>
  <thead><tr><th align="left"><strong>Model</strong></th><th>ArXiv</th><th>Overall</th></tr></thead>
  <tbody>
    <tr><td align="left">olmOCR pipeline v0.4.0 with olmOCR-2-7B-1025</td><td>82.9</td><td>82.3 ± 1.1</td></tr>
    <tr><td align="left">olmOCR pipeline v0.4.0 with olmOCR-2-7B-1025-FP8</td><td>83.0</td><td>82.4 ± 1.1</td></tr>
  </tbody>
</table>
"""


def _spec(**kw):
    base = {'format': 'markdown', 'after': '=== "Detection (COCO)"', 'column': 'mAP<sup>val'}
    return {**base, **kw}


class TableRowsTest(SimpleTestCase):

    def test_a_markdown_table_after_its_anchor_gives_names_and_the_declared_column(self):
        self.assertEqual([('YOLO11n', 39.5), ('YOLO11x', 54.7)], b.table_rows(ULTRA_PAGE, _spec()))
        seg = _spec(after='=== "Segmentation (COCO)"', column='mAP<sup>mask')
        self.assertEqual([('YOLO11n-seg', 32.0)], b.table_rows(ULTRA_PAGE, seg),
                         'the mask column, not the box column next to it')

    def test_an_html_table_gives_the_overall_cell(self):
        spec = {'format': 'html', 'after': '## olmOCR-Bench Scores', 'column': 'Overall'}
        self.assertEqual([('olmOCR pipeline v0.4.0 with olmOCR-2-7B-1025', 82.3),
                          ('olmOCR pipeline v0.4.0 with olmOCR-2-7B-1025-FP8', 82.4)],
                         b.table_rows(CARD_PAGE, spec))

    def test_a_moved_table_gives_nothing_never_another_column(self):
        self.assertEqual([], b.table_rows(ULTRA_PAGE, _spec(after='=== "Pose (COCO)"')))
        self.assertEqual([], b.table_rows(ULTRA_PAGE, _spec(column='mAP<sup>test')))


class ExactIdentityTest(SimpleTestCase):

    def test_a_github_weight_is_its_repository_and_its_file(self):
        row = AIModel(model_key='anonymizer:yolo:yolo11n.pt', platform_ref='github:ultralytics/assets')
        self.assertIn('ultralytics/assets/yolo11n.pt', b._local_repos(row))
        # Counter-check: a fine-tune of another origin has its own identity, not COCO's.
        face = AIModel(model_key='anonymizer:yolo:yolov8n_face_plate_720p.pt', platform_ref='')
        self.assertFalse({r for r in b._local_repos(face) if r.startswith('ultralytics/')})

    def test_the_github_repository_accessor(self):
        from wama.common.external_sources import github_repo
        self.assertEqual('ultralytics/assets', github_repo('github:ultralytics/assets'))
        self.assertEqual('Phhofm/models', github_repo('github:Phhofm/models/releases/tag/4x'))
        self.assertEqual('', github_repo('huggingface:org/model'))


def _response(text='', payload=None, status=200):
    return SimpleNamespace(text=text, status_code=status, json=lambda: payload,
                           raise_for_status=lambda: None)


class LoadPublishedTablesTest(SimpleTestCase):

    def test_rows_become_entries_with_their_exact_identity(self):
        specs = (
            {'table': 'ultra', 'host': 'published_tables', 'path': 'u.md', 'format': 'markdown',
             'after': '=== "Detection (COCO)"', 'column': 'mAP<sup>val', 'category': 'detect-coco',
             'scale': 'coco_box_map50_95', 'asset_repo': 'ultralytics/assets'},
            {'table': 'card', 'host': 'huggingface', 'path': 'c.md', 'format': 'html',
             'after': '## olmOCR-Bench Scores', 'column': 'Overall',
             'category': 'ocr-olmocr-bench', 'scale': 'hf_bench:allenai/olmOCR-bench:overall',
             'rows': {'olmOCR pipeline v0.4.0 with olmOCR-2-7B-1025': 'allenai/olmOCR-2-7B-1025'}},
        )
        pages = {'u.md': ULTRA_PAGE, 'c.md': CARD_PAGE}
        with mock.patch.object(b, 'PUBLISHED_TABLES', specs), \
                mock.patch('requests.get', side_effect=lambda url, **kw: _response(
                    pages[url.rsplit('/', 1)[-1]])):
            by_category, _ = b.load_published_tables()
        self.assertEqual(['ultralytics/assets/yolo11n.pt', 'ultralytics/assets/yolo11x.pt'],
                         [e['repo'] for e in by_category['detect-coco']])
        ocr = by_category['ocr-olmocr-bench']
        self.assertEqual([('allenai/olmocr-2-7b-1025', 82.3)], [(e['repo'], e['value']) for e in ocr],
                         'only the DECLARED row — the FP8 row is not our weight')
        self.assertEqual(b.PROVENANCE_SELF_DECLARED, ocr[0]['provenance'])


class LoadLinagoraTest(SimpleTestCase):

    def _run(self, runs):
        tree = {'tree': [{'path': f'benchmarks/sota/results/{name}/metadata.json'} for name in runs]}

        def session_get(url, **kw):
            run = url.split('/results/')[1].split('/')[0]
            repo, wer, missing = runs[run]
            if url.endswith('metadata.json'):
                return _response(payload={'model_info': {'hf': repo}})
            dataset = url.rsplit('/', 1)[-1][:-5]
            if dataset == missing:
                return _response(status=404)
            return _response(payload={'wer_nocasepunc': {'wer': wer}})

        session = SimpleNamespace(get=session_get)
        with mock.patch('requests.get', return_value=_response(payload=tree)), \
                mock.patch('requests.Session', return_value=session):
            return b.load_linagora_asr()[0]['speech-to-text-fr-linagora']

    def test_the_mean_of_the_seven_datasets_the_best_decoder_and_the_author_s_own(self):
        entries = self._run({
            'kyutai': ('kyutai/stt-1b-en_fr-trfs', 19.0, None),
            'linto-ctc': ('linagora/linto_stt_fr_fastconformer_pc', 14.0, None),
            'linto-rnnt': ('linagora/linto_stt_fr_fastconformer_pc', 13.0, None),
            'partial': ('someone/partial-asr', 5.0, 'SUMM-RE_max30'),
        })
        by_repo = {e['repo']: e for e in entries}
        self.assertEqual(19.0, by_repo['kyutai/stt-1b-en_fr-trfs']['value'])
        self.assertEqual(13.0, by_repo['linagora/linto_stt_fr_fastconformer_pc']['value'],
                         'one model, two decoders: the best')
        self.assertNotIn('someone/partial-asr', by_repo, 'without the seven datasets: no score')
        self.assertEqual(b.PROVENANCE_INDEPENDENT, by_repo['kyutai/stt-1b-en_fr-trfs']['provenance'])
        self.assertEqual(b.PROVENANCE_SELF_DECLARED,
                         by_repo['linagora/linto_stt_fr_fastconformer_pc']['provenance'])


class MatchingTest(SimpleTestCase):

    def test_a_yolo_row_gets_its_author_s_value_and_a_face_fine_tune_does_not(self):
        sources = {'published_tables': {'detect-coco': [
            {'name': 'YOLO11n', 'slug': 'YOLO11n', 'repo': 'ultralytics/assets/yolo11n.pt',
             'identity': None, 'value': 39.5, 'scale': 'coco_box_map50_95',
             'provenance': b.PROVENANCE_SELF_DECLARED}]}}
        yolo = AIModel(model_key='anonymizer:yolo:yolo11n.pt', name='yolo11n.pt',
                       platform_ref='github:ultralytics/assets', capabilities={'task': 'detect'})
        self.assertEqual(['detect-coco'], b._local_categories(yolo))
        bench, _ = b._benchmark_for_category(yolo, 'detect-coco', None, sources)
        self.assertEqual((39.5, 'coco_box_map50_95', 'repo'),
                         (bench['value'], bench['scale'], bench['matched_by']))
        self.assertIsNone(bench['percentile_rank'], 'an author table never gives a rank')
        face = AIModel(model_key='anonymizer:yolo:yolov8n_face_plate_720p.pt',
                       name='yolov8n_face_plate_720p.pt', capabilities={'task': 'detect'})
        self.assertIsNone(b._benchmark_for_category(face, 'detect-coco', None, sources)[0])

    def test_french_transcription_keeps_open_asr_first_and_linagora_second(self):
        self.assertEqual(('speech-to-text-fr', 'speech-to-text-fr-linagora', 'speech-to-text'),
                         b.TASK_TO_BENCH_CATEGORY['transcription'])

    def test_author_tables_are_not_a_discovery_source(self):
        loaded = []
        with mock.patch.object(b, '_load_source',
                               side_effect=lambda s, cache='read': loaded.append(s['key']) or ({}, {})):
            b.leaderboard_repos()
        self.assertNotIn('published_tables', loaded)
        self.assertIn('linagora_asr', loaded, 'a single-harness leaderboard does rank a population')
