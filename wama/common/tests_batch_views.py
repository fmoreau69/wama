"""La fabrique COMMUNE des vues de lot (`batch_views.make_batch_views`, 2026-09-22 — ROUTE §11 #36).

Mesurée sur les DEUX formes de rattachement du dépôt, comme `tests_sharing` : le converter (FK
directe, `ConversionJob.batch`) et l'imager (liaison `GenerationBatchItem`). Les vues sont
appelées par `RequestFactory` — ce qui se teste ici est le CONTRAT (ordre des lignes, purge du
lot par requête, sorties vidées à la duplication, réglages coercés), pas le routage.
"""
import json
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from wama.common.utils.batch_views import (apply_item_settings, make_batch_views,
                                           read_settings_payload)


class _FakeTask:
    """Une tâche Celery de test : `.delay(id)` rend un objet à `.id`, et se souvient."""

    def __init__(self):
        self.calls = []

    def delay(self, item_id):
        self.calls.append(item_id)
        return SimpleNamespace(id=f'task-{item_id}')


def _user():
    return User.objects.create_user('lot_views', password='x')


class DirectFormBatchViewsTest(TestCase):
    """Forme à FK DIRECTE — converter."""

    def setUp(self):
        from wama.converter.models import ConversionBatch, ConversionJob
        self.u = _user()
        self.rf = RequestFactory()
        self.task = _FakeTask()
        self.lot = ConversionBatch.objects.create(user=self.u, total=2)
        self.a = ConversionJob.objects.create(user=self.u, input_filename='a.mp4', batch=self.lot,
                                              batch_row_index=1)
        self.b = ConversionJob.objects.create(user=self.u, input_filename='b.mp4', batch=self.lot,
                                              batch_row_index=0)
        self.views = make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            task=self.task, file_fields=('input_file', 'output_file'),
            output_fields=('output_file',), params_fields=('output_format',),
            batch_attr='batch', row_field='batch_row_index',
            batch_extra=lambda lot: {'media_type': lot.media_type})

    def _post(self, name, pk, data=None, as_json=False):
        if as_json:
            req = self.rf.post(f'/x/{pk}/', data=json.dumps(data or {}), content_type='application/json')
        else:
            req = self.rf.post(f'/x/{pk}/', data=data or {})
        req.user = self.u
        return self.views[name](req, pk)

    def test_batch_start_follows_row_order_and_uses_begin_processing(self):
        r = self._post('batch_start', self.lot.pk)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.task.calls, [self.b.id, self.a.id], 'ordre des LIGNES, pas des ids')
        self.a.refresh_from_db()
        self.assertEqual((self.a.status, self.a.task_id), ('RUNNING', f'task-{self.a.id}'))
        # Idempotent : plus rien en PENDING → rien relancé.
        self.assertEqual(json.loads(self._post('batch_start', self.lot.pk).content)['count'], 0)

    def test_batch_update_skips_running_items_and_coerces_by_schema(self):
        self.a.status = 'RUNNING'
        self.a.save(update_fields=['status'])
        r = self._post('batch_update', self.lot.pk, {'output_format': 'webm'})
        self.assertEqual(json.loads(r.content), {'updated': 1})
        self.b.refresh_from_db()
        self.a.refresh_from_db()
        self.assertEqual(self.b.output_format, 'webm')
        self.assertNotEqual(self.a.output_format, 'webm', 'un élément EN COURS ne se modifie pas')

    def test_batch_delete_removes_the_items_and_the_batch_without_the_stale_instance(self):
        from wama.converter.models import ConversionBatch, ConversionJob
        r = self._post('batch_delete', self.lot.pk)
        self.assertEqual(json.loads(r.content)['deleted'], True)
        self.assertFalse(ConversionJob.objects.filter(pk__in=[self.a.pk, self.b.pk]).exists())
        self.assertFalse(ConversionBatch.objects.filter(pk=self.lot.pk).exists(),
                         'le lot vidé est purgé (signal ou requête), jamais laissé')

    def test_batch_delete_purges_an_empty_batch_by_query(self):
        from wama.converter.models import ConversionBatch
        vide = ConversionBatch.objects.create(user=self.u, total=0)
        self._post('batch_delete', vide.pk)
        self.assertFalse(ConversionBatch.objects.filter(pk=vide.pk).exists())

    def test_batch_duplicate_keeps_row_order_clears_outputs_and_carries_batch_extra(self):
        from wama.converter.models import ConversionBatch, ConversionJob
        self.lot.media_type = 'video'
        self.lot.save(update_fields=['media_type'])
        r = json.loads(self._post('batch_duplicate', self.lot.pk).content)
        new_b = ConversionBatch.objects.get(pk=r['id'])
        self.assertEqual((new_b.total, new_b.media_type), (2, 'video'))
        rows = list(ConversionJob.objects.filter(batch=new_b).order_by('batch_row_index'))
        self.assertEqual([j.input_filename for j in rows], ['b.mp4', 'a.mp4'])
        self.assertTrue(all(j.status == 'PENDING' and not j.output_file for j in rows))

    def test_batch_status_reports_counts_and_an_overall_state(self):
        self.a.status = 'SUCCESS'
        self.a.save(update_fields=['status'])
        req = self.rf.get('/x/')
        req.user = self.u
        data = json.loads(self.views['batch_status'](req, self.lot.pk).content)
        self.assertEqual((data['status'], data['total'], data['counts']['success_count']),
                         ('PENDING', 2, 1))
        self.assertEqual([i['id'] for i in data['items']], [self.b.id, self.a.id])


class LinkFormBatchViewsTest(TestCase):
    """Forme à LIAISON — imager (`GenerationBatchItem`)."""

    def setUp(self):
        from wama.imager.models import GenerationBatch, GenerationBatchItem, ImageGeneration
        self.u = _user()
        self.rf = RequestFactory()
        self.lot = GenerationBatch.objects.create(user=self.u, total=2)
        self.g1 = ImageGeneration.objects.create(user=self.u, prompt='un')
        self.g2 = ImageGeneration.objects.create(user=self.u, prompt='deux')
        GenerationBatchItem.objects.create(batch=self.lot, generation=self.g1, row_index=1)
        GenerationBatchItem.objects.create(batch=self.lot, generation=self.g2, row_index=0)
        self.views = make_batch_views(
            work_model=ImageGeneration, batch_model=GenerationBatch, get_user=lambda r: self.u,
            task=_FakeTask(), params_fields=('prompt',),
            item_model=GenerationBatchItem, fk_name='generation')

    def test_duplicate_creates_link_rows_in_row_order(self):
        from wama.imager.models import GenerationBatch, GenerationBatchItem
        req = self.rf.post('/x/')
        req.user = self.u
        r = json.loads(self.views['batch_duplicate'](req, self.lot.pk).content)
        new_b = GenerationBatch.objects.get(pk=r['id'])
        liens = list(GenerationBatchItem.objects.filter(batch=new_b).order_by('row_index'))
        self.assertEqual([l.generation.prompt for l in liens], ['deux', 'un'])
        self.assertEqual(new_b.total, 2)

    def test_delete_removes_elements_links_and_batch(self):
        from wama.imager.models import GenerationBatch, GenerationBatchItem, ImageGeneration
        req = self.rf.post('/x/')
        req.user = self.u
        self.views['batch_delete'](req, self.lot.pk)
        self.assertFalse(ImageGeneration.objects.filter(pk__in=[self.g1.pk, self.g2.pk]).exists())
        self.assertFalse(GenerationBatchItem.objects.filter(batch_id=self.lot.pk).exists())
        self.assertFalse(GenerationBatch.objects.filter(pk=self.lot.pk).exists())

    def test_download_without_an_output_field_answers_404_json(self):
        req = self.rf.get('/x/')
        req.user = self.u
        r = self.views['batch_download'](req, self.lot.pk)
        self.assertEqual(r.status_code, 404)


class SettingsPayloadTest(TestCase):
    """Les deux helpers partagés par `update` (élément) et `batch_update` (lot)."""

    SCHEMA = [{'name': 'steps', 'type': 'number', 'min': 1, 'max': 100},
              {'name': 'upscale', 'type': 'toggle'}]

    def test_form_payload_is_coerced_and_empty_schema_fields_are_dropped(self):
        req = RequestFactory().post('/x/', {'steps': '30', 'upscale': 'true', 'note': '', 'steps2': ''})
        data = read_settings_payload(req, self.SCHEMA, ('steps', 'upscale', 'note'))
        self.assertEqual(data['steps'], 30)
        self.assertIs(data['upscale'], True)
        self.assertNotIn('note', data, "un champ du schéma laissé vide veut dire « ne pas toucher »")
        self.assertIn('steps2', data, 'un champ HORS schéma passe tel quel')

    def test_json_payload_is_read_from_the_body(self):
        req = RequestFactory().post('/x/', data=json.dumps({'steps': 5}), content_type='application/json')
        self.assertEqual(read_settings_payload(req, self.SCHEMA, ('steps',)), {'steps': 5})

    def test_apply_writes_columns_and_routes_extras_into_the_options_container(self):
        item = SimpleNamespace(steps=1, options={'keep': 1})
        touched = apply_item_settings(item, {'steps': 7, 'gif_fps': 12, 'ignored': 3},
                                      params_fields=('steps',), options_field='options',
                                      extra_names=('gif_fps',))
        self.assertEqual(touched, ['steps', 'options'])
        self.assertEqual((item.steps, item.options), (7, {'keep': 1, 'gif_fps': 12}))
