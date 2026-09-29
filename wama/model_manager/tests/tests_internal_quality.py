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
    """Q3 « en lecture d'abord »: the note must not reach selection — it is never written to
    the catalogue fields that `_quality_scalars` reads."""

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
