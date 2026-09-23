"""Évaluation d'un résultat contre sa référence (`services/result_evaluation.py`) + son endpoint.

⚠ Surface TÉMOIN : on déclare une évaluation sur `composer`, dont l'élément porte déjà un champ
fichier (`melody_reference`), le temps du test — le registre est restauré ensuite. Le texte
« produit » est le prompt : c'est un témoin de mécanique, pas une évaluation de musique.
⚠ `MEDIA_ROOT` temporaire : aucun fichier n'est écrit dans les vrais médias.
"""
import os
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from wama.common.services import result_evaluation as evaluation

SURFACE = 'composer'


def _read_reference(path):
    with open(path, encoding='utf-8') as handle:
        text = handle.read()
    if 'ILLISIBLE' in text:
        raise ValueError('contenu refusé par le lecteur')
    return text, {'format': 'txt'}


def _spec():
    return evaluation.EvaluationSpec(
        surface=SURFACE, reference_field='melody_reference',
        result_text=lambda item: item.prompt or None,
        read_reference=_read_reference,
        model_key=lambda item: f'composer:{item.model}',
        reference_extensions=('.txt',))


class _WitnessSurface(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        previous = evaluation._REGISTRY.get(SURFACE)
        evaluation.register_evaluation(_spec())
        self.addCleanup(lambda: evaluation._REGISTRY.pop(SURFACE, None) if previous is None
                        else evaluation._REGISTRY.__setitem__(SURFACE, previous))
        self.user = User.objects.create_user('evaluation_witness', password='x')

    def _item(self, prompt='le chat dort sur le tapis', model='musicgen-small'):
        from wama.composer.models import ComposerGeneration
        return ComposerGeneration.objects.create(user=self.user, prompt=prompt, model=model)

    def _upload(self, text, name='reference.txt'):
        return SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/plain')


class MeasureTest(_WitnessSurface):

    def test_a_result_is_measured_on_every_declared_metric(self):
        item = self._item('le chien dort le tapis rouge')
        evaluation.attach_reference(SURFACE, [item], self._upload('le chat dort sur le tapis'))
        view = evaluation.item_evaluation(SURFACE, item)
        wer = view['metrics'][0]
        self.assertEqual(['wer', 'cer'], [m['metric'] for m in view['metrics']])
        self.assertEqual((0.5, 1, 1, 1, 6), (wer['value'], wer['substitutions'], wer['deletions'],
                                             wer['insertions'], wer['reference_length']))
        self.assertEqual('composer:musicgen-small', view['model_key'])
        self.assertEqual('reference.txt', view['reference_name'])
        self.assertEqual(64, len(view['reference_sha256']))
        self.assertEqual({'format': 'txt'}, view['reading'])

    def test_a_relaunched_result_REPLACES_its_measure_it_never_piles_up(self):
        from wama.common.models import ResultEvaluation
        item = self._item('autre chose')
        evaluation.attach_reference(SURFACE, [item], self._upload('le chat dort'))
        item.prompt, item.model = 'le chat dort', 'musicgen-large'
        item.save()
        evaluation.evaluate(SURFACE, item)
        rows = ResultEvaluation.objects.filter(object_id=item.pk, app=SURFACE)
        self.assertEqual(2, rows.count(), 'one row per metric, whatever the number of measures')
        self.assertEqual({'composer:musicgen-large'}, set(rows.values_list('model_key', flat=True)))
        self.assertEqual(0.0, rows.get(metric='wer').value)

    def test_no_result_yet_means_no_measure(self):
        item = self._item(prompt='')
        evaluation.attach_reference(SURFACE, [item], self._upload('texte'))
        self.assertTrue(evaluation.item_evaluation(SURFACE, item)['pending'],
                        'the reference is there, the measure waits for a result')

    def test_an_undeclared_surface_measures_nothing(self):
        self.assertEqual([], evaluation.evaluate('surface_absente', self._item()))
        self.assertIsNone(evaluation.item_evaluation('surface_absente', self._item()))

    def test_an_unknown_metric_is_refused_at_declaration(self):
        with self.assertRaisesMessage(ValueError, 'bleu'):
            evaluation.register_evaluation(evaluation.EvaluationSpec(
                surface='x', reference_field='f', result_text=str, read_reference=_read_reference,
                model_key=str, metrics=('wer', 'bleu')))


class ReferenceFileTest(_WitnessSurface):

    def test_one_reference_for_a_whole_batch_is_stored_ONCE(self):
        items = [self._item(), self._item(model='musicgen-large')]
        report = evaluation.attach_reference(SURFACE, items, self._upload('le chat dort'))
        for item in items:
            item.refresh_from_db()
        self.assertEqual(1, len({i.melody_reference.name for i in items}))
        self.assertEqual({'reference_name': 'reference.txt', 'targets': 2, 'measured': 2}, report)

    def test_the_shared_file_survives_until_its_LAST_holder_lets_go(self):
        a, b = self._item(), self._item()
        evaluation.attach_reference(SURFACE, [a, b], self._upload('le chat dort'))
        a.refresh_from_db()
        path = a.melody_reference.path
        evaluation.detach_reference(SURFACE, [a])
        self.assertTrue(os.path.exists(path), 'b still designates the file')
        b.refresh_from_db()
        evaluation.detach_reference(SURFACE, [b])
        self.assertFalse(os.path.exists(path), 'nobody designates it any more')
        self.assertIsNone(evaluation.item_evaluation(SURFACE, b))

    def test_an_unread_format_is_refused_by_name(self):
        with self.assertRaisesMessage(evaluation.ReferenceRefused, '.pdf'):
            evaluation.attach_reference(SURFACE, [self._item()],
                                        self._upload('x', name='reference.pdf'))

    def test_an_unreadable_reference_is_refused_AND_left_nowhere(self):
        item = self._item()
        with self.assertRaisesMessage(evaluation.ReferenceRefused, 'illisible'):
            evaluation.attach_reference(SURFACE, [item], self._upload('ILLISIBLE'))
        item.refresh_from_db()
        self.assertFalse(item.melody_reference.name)


class BatchComparisonTest(_WitnessSurface):

    def test_the_corpus_rate_weighs_every_word_not_every_item(self):
        """3 errors on 3 words and 0 on 97: 3 %, not the 50 % a mean of rates would say."""
        short = self._item('x y z', model='a')
        long = self._item(' '.join(['mot'] * 97), model='a')
        evaluation.attach_reference(SURFACE, [short], self._upload('a b c'))
        evaluation.attach_reference(SURFACE, [long], self._upload(' '.join(['mot'] * 97)))
        summary = evaluation.batch_evaluation(SURFACE, [short, long])
        self.assertEqual(0.03, summary['models'][0]['rates']['wer'])

    def test_models_are_ranked_and_the_comparison_says_when_it_is_fair(self):
        good = self._item('le chat dort', model='bon')
        bad = self._item('le chien court', model='moins_bon')
        evaluation.attach_reference(SURFACE, [good, bad], self._upload('le chat dort'))
        summary = evaluation.batch_evaluation(SURFACE, [good, bad])
        self.assertEqual(['composer:bon', 'composer:moins_bon'],
                         [m['model_key'] for m in summary['models']])
        self.assertTrue(summary['comparable'])
        other = self._item('le chat', model='autre')
        evaluation.attach_reference(SURFACE, [other], self._upload('autre référence'))
        self.assertFalse(evaluation.batch_evaluation(SURFACE, [good, bad, other])['comparable'],
                         'different references: ranking them would compare different corpora')

    def test_a_batch_without_any_measure_has_no_summary(self):
        self.assertIsNone(evaluation.batch_evaluation(SURFACE, [self._item()]))


class EndpointTest(_WitnessSurface):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def _url(self, nature, pk, surface=SURFACE):
        return f'/common/api/result-reference/{surface}/{nature}/{pk}/'

    def test_an_element_receives_reads_and_loses_its_reference(self):
        item = self._item('le chat dort')
        posted = self.client.post(self._url('element', item.pk),
                                  {'file': self._upload('le chat dort')}).json()
        self.assertTrue(posted['ok'])
        self.assertEqual(0.0, posted['item']['metrics'][0]['value'])
        self.assertEqual('reference.txt', self.client.get(self._url('element', item.pk))
                         .json()['item']['reference_name'])
        removed = self.client.post(self._url('element', item.pk), {'action': 'remove'}).json()
        self.assertEqual((1, None), (removed['removed'], removed['item']))

    def test_a_batch_reference_reaches_every_element_and_returns_the_comparison(self):
        from wama.composer.models import ComposerBatch, ComposerBatchItem
        batch = ComposerBatch.objects.create(user=self.user)
        for row, model in enumerate(('a', 'b')):
            ComposerBatchItem.objects.create(batch=batch, row_index=row,
                                             generation=self._item('le chat dort', model=model))
        posted = self.client.post(self._url('lot', batch.pk),
                                  {'file': self._upload('le chat dort')}).json()
        self.assertEqual(2, posted['targets'])
        self.assertEqual(2, len(posted['batch']['models']))

    def test_a_refusal_is_said(self):
        item = self._item()
        answer = self.client.post(self._url('element', item.pk),
                                  {'file': self._upload('x', name='r.pdf')})
        self.assertEqual(400, answer.status_code)
        self.assertIn('.pdf', answer.json()['reason'])

    def test_a_surface_that_does_not_evaluate_and_a_foreign_item_are_404(self):
        item = self._item()
        self.assertEqual(404, self.client.get(self._url('element', item.pk, 'reader')).status_code)
        stranger = User.objects.create_user('evaluation_stranger', password='x')
        self.client.force_login(stranger)
        self.assertEqual(404, self.client.get(self._url('element', item.pk)).status_code)


class CapabilityAndDeclarationGoTogetherTest(TestCase):
    """`has_reference_result` opens a port; `register_evaluation` reads what enters it. One
    without the other is a port that accepts a file nothing reads, or a reader nobody feeds."""

    def test_every_app_declaring_the_capability_has_registered_its_evaluation(self):
        from wama.common.app_registry import APP_CATALOG
        declared = {a for a, c in APP_CATALOG.items() if c.get('has_reference_result')}
        registered = set(evaluation.evaluable_surfaces()) & set(APP_CATALOG)
        self.assertEqual(declared, registered)
