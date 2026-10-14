"""Étage 3 — la mesure INTERNE d'un modèle, rabattue à la lecture (`services/internal_quality`).

Mesures SEMÉES directement dans `ResultEvaluation` : le calcul se juge sur des comptes connus,
pas sur ce que le parc a mesuré ce jour-là.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from wama.common.models import ResultEvaluation
from wama.model_manager.services.internal_quality import internal_scores, scale_name


def _measure(object_id, model_key, errors, words, reference='ref-a', value=None, metric='wer'):
    return ResultEvaluation.objects.create(
        app='transcriber', object_type='Transcript', object_id=object_id, model_key=model_key,
        metric=metric, value=value if value is not None else (errors / words if words else None),
        direction='lower', protocol='text_v1', reference_sha256=reference,
        detail={'errors': errors, 'reference_length': words})


class InternalScoreTest(TestCase):

    def test_the_rate_is_the_CORPUS_rate_not_a_mean_of_rates(self):
        """3 errors on 3 words + 0 on 97: 3 %, not the 50 % a mean of rates would give."""
        _measure(1, 'transcriber:whisper', 3, 3)
        _measure(2, 'transcriber:whisper', 0, 97, reference='ref-b')
        scale = internal_scores()['transcriber:whisper'][0]
        self.assertEqual(0.03, scale['value'])
        self.assertEqual((2, 2, 100), (scale['items'], scale['references'], scale['reference_words']))
        self.assertEqual(scale_name('wer', 'text_v1'), scale['scale'])
        self.assertEqual('lower', scale['direction'])

    def test_models_are_ranked_only_among_those_measured_on_the_SAME_references(self):
        _measure(1, 'transcriber:whisper', 1, 10)
        _measure(2, 'transcriber:vibevoice-asr', 3, 10)
        _measure(3, 'transcriber:qwen3-asr-1.7b', 0, 10, reference='another-audio')
        scores = internal_scores()
        self.assertEqual((1, 2), (scores['transcriber:whisper'][0]['rank'],
                                  scores['transcriber:whisper'][0]['population']))
        self.assertEqual(2, scores['transcriber:vibevoice-asr'][0]['rank'])
        qwen = scores['transcriber:qwen3-asr-1.7b'][0]
        self.assertEqual((None, 1), (qwen['rank'], qwen['population']),
                         'alone on its references: a rank would compare different corpora')

    def test_external_results_and_undefined_rates_have_no_score(self):
        _measure(1, 'external:autre_outil', 0, 10)
        _measure(2, '', 0, 10)
        _measure(3, 'transcriber:whisper', 0, 0, value=None)
        self.assertEqual({}, internal_scores())

    def test_each_metric_is_its_own_scale(self):
        _measure(1, 'transcriber:whisper', 1, 10)
        _measure(1, 'transcriber:whisper', 2, 40, metric='cer')
        scales = internal_scores()['transcriber:whisper']
        self.assertEqual(['internal_cer_text_v1', 'internal_wer_text_v1'], [s['scale'] for s in scales])

    def test_the_filter_keeps_only_the_requested_models(self):
        _measure(1, 'transcriber:whisper', 1, 10)
        _measure(2, 'transcriber:vibevoice-asr', 1, 10)
        self.assertEqual(['transcriber:whisper'], list(internal_scores(['transcriber:whisper'])))


class ReadOnlyByConstructionTest(TestCase):
    """The note is never WRITTEN to the catalogue fields (`benchmark_*`, which `sync_benchmarks`
    replaces whole). Since 2026-10-14 (Q3) selection READS it at sort time instead
    (`InternalStageInSelectionTest` below) — a read, still not a write."""

    def test_the_catalogue_list_carries_the_note_without_touching_the_model_row(self):
        from wama.model_manager.models import AIModel
        model = AIModel.objects.create(model_key='transcriber:whisper', name='Whisper',
                                       source='transcriber')
        _measure(1, 'transcriber:whisper', 1, 10)
        user = User.objects.create_user('internal_quality_reader', password='x')
        self.client.force_login(user)
        rows = self.client.get('/model-manager/api/models/db/?source=transcriber').json()['models']
        row = next(r for r in rows if r['model_key'] == 'transcriber:whisper')
        self.assertEqual(0.1, row['internal_quality'][0]['value'])
        model.refresh_from_db()
        self.assertIsNone(model.benchmark_index)
        self.assertNotIn('internal', model.benchmark_meta or {})


def _upscaler(key, vram_gb):
    from wama.model_manager.models import AIModel
    return AIModel.objects.create(
        model_key=key, name=key.split(':')[1], model_type='upscaling', source='enhancer',
        vram_gb=vram_gb, is_available=True, is_downloaded=True, is_proposed=False,
        capabilities={'task': 'upscale', 'scale': 4})


def _bench_row(object_id, model_key, value, *, metric='lpips', direction='lower',
               reference='div2k-val'):
    return ResultEvaluation.objects.create(
        app='model_manager', object_type='UpscaleBench', object_id=object_id, model_key=model_key,
        metric=metric, value=value, direction=direction, protocol='bicubic_x4_v1',
        reference_sha256=reference, detail={'errors': value * 100, 'reference_length': 100,
                                            'unit': 'image'})


class InternalStageInSelectionTest(TestCase):
    """Q3 settled by Fabien on 2026-10-14 — « étage 3 générique »: what WAMA measured itself on a
    reference comes FIRST in the ladder (`model_selector._internal_values`). Seeded on upscalers,
    whose catalogue carried no quality at all: the slider drew the same model at 0 and at 100."""

    def setUp(self):
        _upscaler('enhancer:big', 0.3)
        _upscaler('enhancer:small', 0.1)
        _upscaler('enhancer:mid', 0.2)

    def _drawn(self, intent=100):
        from wama.model_manager.services.model_selector import select_model
        return select_model(model_type='upscaling', quality_intent=intent).model_key

    def test_without_a_measure_quality_is_only_the_size(self):
        self.assertEqual('enhancer:big', self._drawn())

    def test_the_measured_quality_drives_the_slider(self):
        _bench_row(1, 'enhancer:big', 0.30)
        _bench_row(2, 'enhancer:small', 0.20)
        _bench_row(3, 'enhancer:mid', 0.25)
        self.assertEqual('enhancer:small', self._drawn(100),
                         'the lowest LPIPS is the best, whatever its size')

    def test_a_lone_measured_model_does_not_win_by_default(self):
        _bench_row(2, 'enhancer:small', 0.20)
        self.assertEqual('enhancer:big', self._drawn())

    def test_models_measured_on_different_references_do_not_compare(self):
        _bench_row(1, 'enhancer:big', 0.30, reference='div2k-val')
        _bench_row(2, 'enhancer:small', 0.20, reference='another-set')
        self.assertEqual('enhancer:big', self._drawn())

    def test_two_comparable_scales_abstain_rather_than_pick_one(self):
        """LPIPS says « small », PSNR says « big »: which one counts is not ours to choose."""
        _bench_row(1, 'enhancer:big', 0.30)
        _bench_row(2, 'enhancer:small', 0.20)
        _bench_row(1, 'enhancer:big', 32.0, metric='psnr', direction='higher')
        _bench_row(2, 'enhancer:small', 29.0, metric='psnr', direction='higher')
        self.assertEqual('enhancer:big', self._drawn(),
                         'the stage abstains: the ladder goes down to the size, as before')
