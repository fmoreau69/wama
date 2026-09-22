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
        # Ce qui TOURNE n'est pas relancé (`begin_processing` le refuse) → rien de plus.
        self.assertEqual(json.loads(self._post('batch_start', self.lot.pk).content)['count'], 0)

    def test_batch_start_relaunches_failed_and_finished_items_by_default(self):
        """Idiome MESURÉ (describer, reader, transcriber, avatarizer) : ▶ de lot relance tout ce
        qui ne tourne pas — un échec se relance, un succès se refait. `start_only_pending=True`
        (composer : « créer ≠ démarrer ») ne lance que les PENDING."""
        from wama.converter.models import ConversionBatch, ConversionJob
        self.a.status = 'FAILURE'
        self.a.save(update_fields=['status'])
        self.b.status = 'SUCCESS'
        self.b.save(update_fields=['status'])
        self.assertEqual(json.loads(self._post('batch_start', self.lot.pk).content)['count'], 2)
        pending_only = make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            task=_FakeTask(), batch_attr='batch', row_field='batch_row_index',
            start_only_pending=True)
        for j in (self.a, self.b):
            j.status = 'FAILURE'
            j.save(update_fields=['status'])
        req = self.rf.post('/x/')
        req.user = self.u
        self.assertEqual(json.loads(pending_only['batch_start'](req, self.lot.pk).content)['count'], 0)

    def test_batch_update_applies_the_declared_derived_fields_after_the_settings(self):
        """avatarizer : `quality_mode` se DÉDUIT de `use_enhancer` — déclaré par `after_update`,
        le champ dérivé est sauvé avec les réglages."""
        from wama.converter.models import ConversionBatch, ConversionJob
        views = make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            params_fields=('output_format',), batch_attr='batch', row_field='batch_row_index',
            after_update=lambda j: [setattr(j, 'error_message', 'derived:' + j.output_format), 'error_message'][1:])
        req = self.rf.post('/x/', {'output_format': 'ogg'})
        req.user = self.u
        views['batch_update'](req, self.lot.pk)
        self.a.refresh_from_db()
        self.assertEqual((self.a.output_format, self.a.error_message), ('ogg', 'derived:ogg'))

    def test_batch_update_skips_running_items_and_coerces_by_schema(self):
        self.a.status = 'RUNNING'
        self.a.save(update_fields=['status'])
        r = self._post('batch_update', self.lot.pk, {'output_format': 'webm'})
        payload = json.loads(r.content)
        self.assertEqual((payload['success'], payload['updated']), (True, 1))
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
        # La FORME mesurée sur les cinq apps : `counts` minuscules, `items` avec `filename`.
        self.assertEqual((data['status'], data['total'], data['counts']),
                         ('PENDING', 2, {'success': 1, 'running': 0, 'pending': 1, 'failure': 0}))
        self.assertEqual([(i['id'], i['filename']) for i in data['items']],
                         [(self.b.id, 'b.mp4'), (self.a.id, 'a.mp4')])

    def test_batch_status_reads_progress_and_label_through_the_declared_hooks(self):
        from wama.converter.models import ConversionBatch, ConversionJob
        views = make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            batch_attr='batch', row_field='batch_row_index',
            progress_of=lambda j: 42, item_label=lambda j: f'L-{j.input_filename}')
        req = self.rf.get('/x/')
        req.user = self.u
        data = json.loads(views['batch_status'](req, self.lot.pk).content)
        self.assertEqual([(i['filename'], i['progress']) for i in data['items']],
                         [('L-b.mp4', 42), ('L-a.mp4', 42)])

    def test_batch_delete_calls_the_declared_hook_before_each_deletion(self):
        from wama.converter.models import ConversionBatch, ConversionJob
        seen = []
        views = make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            batch_attr='batch', row_field='batch_row_index',
            on_delete=lambda j: seen.append(j.input_filename))
        req = self.rf.post('/x/')
        req.user = self.u
        views['batch_delete'](req, self.lot.pk)
        self.assertEqual(seen, ['b.mp4', 'a.mp4'])

    def test_batch_start_picks_the_task_per_item_when_task_for_is_declared(self):
        """transcriber : avec ou sans pré-traitement selon `preprocess_audio` — la tâche se
        choisit PAR élément, déclarée par `task_for` (prime sur `task`)."""
        from wama.converter.models import ConversionBatch, ConversionJob
        fast, slow = _FakeTask(), _FakeTask()
        views = make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            task=fast, task_for=lambda j: slow if j.input_filename == 'a.mp4' else fast,
            batch_attr='batch', row_field='batch_row_index')
        req = self.rf.post('/x/')
        req.user = self.u
        views['batch_start'](req, self.lot.pk)
        self.assertEqual((fast.calls, slow.calls), ([self.b.id], [self.a.id]))

    def test_batch_start_accepts_a_callable_reset_applied_under_the_lock(self):
        from wama.converter.models import ConversionBatch, ConversionJob
        def _reset(job):
            job.error_message = 'reset-callable'
        views = make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            task=_FakeTask(), batch_attr='batch', row_field='batch_row_index',
            reset_on_start=_reset)
        req = self.rf.post('/x/')
        req.user = self.u
        views['batch_start'](req, self.lot.pk)
        self.a.refresh_from_db()
        self.assertEqual((self.a.status, self.a.error_message), ('RUNNING', 'reset-callable'))


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

    def test_duplicate_writes_the_declared_extra_on_each_link_row(self):
        """composer : `output_filename` de la ligne d'origine recopié sur la ligne de la copie —
        déclaré par `item_extra(copie, original)`. Mesuré sur un champ de liaison que l'imager
        n'a pas : on vérifie l'APPEL, la valeur passant par `attach_to_batch`."""
        from unittest import mock
        from wama.imager.models import GenerationBatch, GenerationBatchItem, ImageGeneration
        seen = []
        views = make_batch_views(
            work_model=ImageGeneration, batch_model=GenerationBatch, get_user=lambda r: self.u,
            item_model=GenerationBatchItem, fk_name='generation',
            item_extra=lambda new, old: seen.append((new.prompt, old.prompt)) or {})
        req = self.rf.post('/x/')
        req.user = self.u
        views['batch_duplicate'](req, self.lot.pk)
        self.assertEqual(seen, [('deux', 'deux'), ('un', 'un')])

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

    def test_a_declared_field_keeps_its_empty_value(self):
        """reader : `language` vide = auto-détection voulue (leçon du 17/08 : test de présence,
        jamais `or`) — déclaré par `empty_is_value`, `''` traverse ; les autres vides tombent."""
        req = RequestFactory().post('/x/', {'language': '', 'note': ''})
        data = read_settings_payload(req, [{'name': 'language', 'type': 'text'}, {'name': 'note', 'type': 'text'}],
                                     ('language', 'note'), empty_is_value=('language',))
        self.assertEqual(data, {'language': ''})

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
