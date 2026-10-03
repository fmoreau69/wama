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
            task=self.task,
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

    def test_batch_start_can_build_its_reset_from_the_request(self):
        """enhancer audio : ▶ de lot PORTE des réglages (moteur, mode…) postés avec le démarrage —
        `start_reset_for(request)` fabrique la remise à zéro depuis la requête."""
        from wama.converter.models import ConversionBatch, ConversionJob
        def _factory(request):
            fmt = request.POST.get('output_format', '')
            def _reset(job):
                job.output_format = fmt
            return _reset
        views = make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            task=_FakeTask(), batch_attr='batch', row_field='batch_row_index',
            start_reset_for=_factory)
        req = self.rf.post('/x/', {'output_format': 'flac'})
        req.user = self.u
        views['batch_start'](req, self.lot.pk)
        self.a.refresh_from_db()
        self.assertEqual((self.a.status, self.a.output_format), ('RUNNING', 'flac'))

    def test_batch_start_skips_the_items_a_declared_filter_rejects_and_does_not_count_them(self):
        """converter : un job sans `output_format` n'est ni lancé ni compté — il se règle par la
        modale de lot. Déclaré par `startable`, en plus de `start_only_pending`."""
        from wama.converter.models import ConversionBatch, ConversionJob
        self.a.output_format = 'mp3'
        self.a.save(update_fields=['output_format'])
        task = _FakeTask()
        views = make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            task=task, batch_attr='batch', row_field='batch_row_index',
            start_only_pending=True, startable=lambda j: bool(j.output_format))
        req = self.rf.post('/x/')
        req.user = self.u
        data = json.loads(views['batch_start'](req, self.lot.pk).content)
        self.assertEqual((task.calls, data['count'], data['success']), ([self.a.id], 1, True))
        self.b.refresh_from_db()
        self.assertEqual(self.b.status, 'PENDING', 'le job sans format reste en attente')

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

    # ── `apply_settings` : la fonction de réglage de l'APP, celle de sa route d'élément ──────

    def _views_applying(self, apply_settings, **kw):
        from wama.converter.models import ConversionBatch, ConversionJob
        return make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            batch_attr='batch', row_field='batch_row_index', apply_settings=apply_settings, **kw)

    def _update(self, views, data):
        req = self.rf.post('/x/', data)
        req.user = self.u
        return views['batch_update'](req, self.lot.pk)

    def test_the_app_function_is_called_for_each_element_that_is_not_running(self):
        self.a.status = 'RUNNING'
        self.a.save(update_fields=['status'])
        seen = []

        def apply(job, data):
            seen.append((job.pk, data.get('output_format')))
            job.output_format = data['output_format']
            return ['output_format']

        r = self._update(self._views_applying(apply), {'output_format': 'ogg'})
        self.assertEqual(json.loads(r.content)['updated'], 1)
        self.assertEqual(seen, [(self.b.pk, 'ogg')], 'un élément EN COURS ne passe pas par la fonction')
        self.b.refresh_from_db()
        self.assertEqual(self.b.output_format, 'ogg')

    def test_a_refused_setting_answers_400_and_writes_no_element_at_all(self):
        """DEUX TEMPS : la 1re fille est acceptée, la 2e refusée — aucune des deux n'est écrite."""
        def apply(job, data):
            if job.pk == self.a.pk:              # `a` porte la ligne 1 : elle passe en SECOND
                raise ValueError('format refusé')
            job.output_format = 'ogg'
            return ['output_format']

        r = self._update(self._views_applying(apply), {'output_format': 'ogg'})
        self.assertEqual((r.status_code, json.loads(r.content)['error']), (400, 'format refusé'))
        self.b.refresh_from_db()
        self.assertNotEqual(self.b.output_format, 'ogg', 'la fille acceptée AVANT le refus a été écrite')

    def test_none_means_the_whole_element_is_saved(self):
        def apply(job, _data):
            job.output_format = 'ogg'
            job.error_message = 'derived'
            return None

        self._update(self._views_applying(apply), {'output_format': 'ogg'})
        self.a.refresh_from_db()
        self.assertEqual((self.a.output_format, self.a.error_message), ('ogg', 'derived'))

    def test_an_element_the_function_did_not_touch_is_not_counted(self):
        r = self._update(self._views_applying(lambda job, data: []), {'output_format': 'ogg'})
        self.assertEqual(json.loads(r.content)['updated'], 0)

    def test_a_schema_that_depends_on_the_element_is_read_per_element(self):
        """imager : image ou vidéo — le posté est coercé au schéma de CHAQUE élément."""
        asked, got = [], {}

        def schema(job):
            asked.append(job.pk)
            kind = 'toggle' if job.pk == self.a.pk else 'text'
            return [{'name': 'flag', 'type': kind}]

        def apply(job, data):
            got[job.pk] = data.get('flag')
            return []

        self._update(self._views_applying(apply, schema=schema), {'flag': 'true'})
        self.assertEqual(sorted(asked), sorted([self.a.pk, self.b.pk]))
        self.assertEqual((got[self.a.pk], got[self.b.pk]), (True, 'true'))


class PromotionBetweenChildAndMotherTest(TestCase):
    """↑ promouvoir / ↓ réaligner (`MODES_QUEUE_UX §5ter`, `ROUTE §10.6` 5.3 — 2026-10-03), sur la
    forme à FK directe. La mère RETIENT une référence (`common/services/batch_settings.py`) ;
    les trois gestes (⚙, ↑, ↓) écrivent par le même chemin que la ⚙ de lot."""

    def setUp(self):
        from wama.converter.models import ConversionBatch, ConversionJob
        self.u = _user()
        self.rf = RequestFactory()
        self.lot = ConversionBatch.objects.create(user=self.u, total=2)
        self.a = ConversionJob.objects.create(user=self.u, input_filename='a.mp4', batch=self.lot,
                                              batch_row_index=1, output_format='mp4')
        self.b = ConversionJob.objects.create(user=self.u, input_filename='b.mp4', batch=self.lot,
                                              batch_row_index=0, output_format='webm')
        self.views = self._views(promote_payload=lambda j: {'output_format': j.output_format})

    def _views(self, **kw):
        from wama.converter.models import ConversionBatch, ConversionJob
        return make_batch_views(
            work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda r: self.u,
            params_fields=('output_format',), batch_attr='batch', row_field='batch_row_index',
            batch_extra=lambda lot: {'media_type': lot.media_type}, **kw)

    def _post(self, name, data=None, views=None):
        req = self.rf.post('/x/', data or {})
        req.user = self.u
        return (views or self.views)[name](req, self.lot.pk)

    def test_promoting_a_child_writes_its_settings_on_its_sisters_and_the_mother_remembers_them(self):
        from wama.common.models import BatchSettings
        from wama.common.services import batch_settings
        r = self._post('batch_promote', {'source': self.b.pk})
        payload = json.loads(r.content)
        self.assertEqual((r.status_code, payload['updated'], payload['source']), (200, 1, self.b.pk))
        self.a.refresh_from_db()
        self.assertEqual(self.a.output_format, 'webm', 'la sœur a reçu les réglages de la fille promue')
        self.assertEqual(batch_settings.stored(self.lot), {'output_format': 'webm'})
        row = BatchSettings.objects.get(**batch_settings.address(self.lot))
        self.assertEqual(row.source_object_id, str(self.b.pk), 'la mère sait QUI a servi de référence')
        self.assertEqual(batch_settings.references_for(type(self.lot), [self.lot.pk]),
                         {self.lot.pk: str(self.b.pk)}, 'ce que la page de file lit, en une requête')

    def test_by_default_a_child_promotes_the_settings_of_its_app_schema(self):
        """Sans `promote_payload`, la charge utile vient du SCHÉMA de l'app (règle de la
        révision) — jamais d'une liste de champs écrite dans la fabrique."""
        r = self._post('batch_promote', {'source': self.b.pk}, views=self._views())
        payload = json.loads(r.content)
        self.assertEqual(r.status_code, 200, payload)
        self.assertEqual(payload['settings'].get('output_format'), 'webm')
        self.a.refresh_from_db()
        self.assertEqual(self.a.output_format, 'webm')

    def test_what_belongs_to_the_card_alone_is_not_promoted(self):
        """Measured in the browser (2026-10-03): the composer `prompt` (context `item` only)
        overwrote the sisters'. The baseline of a batch is what its ⚙ would set — the settings
        declared for the `batch` context ; without any such declaration, the item ones stay."""
        from wama.common.services import batch_settings
        split = [{'name': 'output_format', 'contexts': ['item']},
                 {'name': 'media_type', 'contexts': ['item', 'batch']}]
        self.assertNotIn('output_format', batch_settings.settings_of(self.b, split))
        flat = [{'name': 'output_format', 'contexts': ['item']}]
        self.assertEqual(batch_settings.settings_of(self.b, flat), {'output_format': 'webm'})
        from wama.composer.models import ComposerGeneration
        from wama.composer.params import PARAMS_JSON
        song = ComposerGeneration(user=self.u, prompt='only mine', duration=20)
        promoted = batch_settings.settings_of(song, PARAMS_JSON)
        self.assertNotIn('prompt', promoted, 'the prompt is what tells the cards of a batch apart')
        self.assertEqual(promoted.get('duration'), 20)

    def test_a_card_outside_the_batch_cannot_be_promoted(self):
        from wama.common.services import batch_settings
        from wama.converter.models import ConversionJob
        other = ConversionJob.objects.create(user=self.u, input_filename='z.mp4', output_format='ogg')
        r = self._post('batch_promote', {'source': other.pk})
        self.assertEqual(r.status_code, 400)
        self.assertIn('appartient', json.loads(r.content)['error'])
        self.assertIsNone(batch_settings.stored(self.lot))
        self.a.refresh_from_db()
        self.assertEqual(self.a.output_format, 'mp4')

    def test_realigning_without_a_reference_says_so(self):
        r = self._post('batch_realign')
        self.assertEqual(r.status_code, 400)
        self.assertIn('référence', json.loads(r.content)['error'])

    def test_the_mother_settings_become_the_reference_and_realign_erases_individual_changes(self):
        from wama.common.services import batch_settings
        self._post('batch_update', {'output_format': 'ogg'})
        self.assertEqual(batch_settings.stored(self.lot), {'output_format': 'ogg'},
                         'la ⚙ de la mère EST une pose de référence')
        self.a.output_format = 'mkv'                       # écart individuel sur une fille
        self.a.save(update_fields=['output_format'])
        r = self._post('batch_realign')
        self.assertEqual(json.loads(r.content)['updated'], 2)
        self.a.refresh_from_db()
        self.assertEqual(self.a.output_format, 'ogg', "l'écart individuel est effacé")

    def test_a_running_sister_is_left_alone(self):
        self.a.status = 'RUNNING'
        self.a.save(update_fields=['status'])
        r = self._post('batch_promote', {'source': self.b.pk})
        self.assertEqual(json.loads(r.content)['updated'], 0)
        self.a.refresh_from_db()
        self.assertEqual(self.a.output_format, 'mp4', 'une card EN COURS ne se modifie pas')

    def test_a_refused_setting_leaves_the_reference_untouched(self):
        from wama.common.services import batch_settings

        def apply(job, data):
            raise ValueError('format refusé')

        r = self._post('batch_promote', {'source': self.b.pk},
                       views=self._views(apply_settings=apply,
                                         promote_payload=lambda j: {'output_format': j.output_format}))
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(batch_settings.stored(self.lot), 'un refus ne pose pas de référence')

    def test_the_reference_follows_duplication_and_leaves_with_deletion(self):
        from wama.common.services import batch_settings
        from wama.converter.models import ConversionBatch
        self._post('batch_update', {'output_format': 'ogg'})
        new_id = json.loads(self._post('batch_duplicate').content)['batch_id']
        self.assertEqual(batch_settings.stored(ConversionBatch.objects.get(pk=new_id)),
                         {'output_format': 'ogg'}, 'la copie du lot hérite de sa référence')
        self._post('batch_delete')
        self.assertIsNone(batch_settings.stored(self.lot), 'la référence part avec le lot')


class BatchCardReferenceRenderTest(TestCase):
    """La card mère porte les deux coordonnées des gestes (`_batch_card.html`) : ↓ désactivé tant
    que le lot n'a pas de référence, `data-batch-promote-url` sur l'en-tête pour ses filles."""

    def _render(self, reference):
        from django.template.loader import render_to_string
        from wama.converter.models import ConversionBatch
        lot = ConversionBatch.objects.create(user=_user(), total=2)
        info = {'obj': lot, 'items': [], 'success_count': 0, 'running_count': 0,
                'failure_count': 0, 'has_success': False, 'evaluation': None,
                'agreement': None, 'reference': reference}
        return render_to_string('common/_batch_card.html',
                                {'batch_info': info, 'app': 'converter', 'actions_communes': True})

    def test_without_a_reference_the_realign_button_is_disabled_and_says_what_to_do(self):
        html = self._render(None)
        self.assertRegex(html, r'data-batch-promote-url="[^"]*/batch/\d+/promote/"')
        self.assertRegex(html, r'data-batch-realign-url="[^"]*/batch/\d+/realign/"')
        self.assertRegex(html, r'batch-realign-btn[^>]*\bdisabled\b')
        self.assertIn('Aucun réglage de référence', html)

    def test_with_a_reference_the_realign_button_is_live(self):
        html = self._render({'source': ''})
        self.assertNotRegex(html, r'batch-realign-btn[^>]*\bdisabled\b')
        self.assertIn('Réaligner toutes les cards du lot', html)


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

    def test_hooks_can_name_after_the_link_row_that_carries_each_element(self):
        """synthesizer / composer : le nom du fichier et le libellé viennent de la LIGNE DE
        LIAISON (`output_filename`), pas de l'élément — `batch_elements` pose `batch_link` sur
        chaque élément, et `item_label`/`item_extra` la lisent. Mesuré ici sur `row_index`, le
        seul champ de ligne que l'imager porte."""
        from wama.imager.models import GenerationBatch, GenerationBatchItem, ImageGeneration
        seen = []
        views = make_batch_views(
            work_model=ImageGeneration, batch_model=GenerationBatch, get_user=lambda r: self.u,
            item_model=GenerationBatchItem, fk_name='generation',
            item_label=lambda g: f'row-{g.batch_link.row_index}',
            item_extra=lambda new, old: seen.append(old.batch_link.row_index) or {})
        req = self.rf.get('/x/')
        req.user = self.u
        data = json.loads(views['batch_status'](req, self.lot.pk).content)
        self.assertEqual([i['filename'] for i in data['items']], ['row-0', 'row-1'])
        req = self.rf.post('/x/')
        req.user = self.u
        views['batch_duplicate'](req, self.lot.pk)
        self.assertEqual(seen, [0, 1])


class TextResultBatchDownloadTest(TestCase):
    """`output_text` (2026-09-24): an app whose declared result is TEXT (`RESULT = {'kind':
    'text', 'field': 'result_text'}`, describer) gets a batch ZIP of `.txt` entries — the
    generated twin answered 404 before, the brick only knew a file column."""

    def setUp(self):
        from wama.describer.models import BatchDescription, BatchDescriptionItem, Description
        self.u = _user()
        self.rf = RequestFactory()
        self.lot = BatchDescription.objects.create(user=self.u, total=2)
        done = Description.objects.create(user=self.u, status='SUCCESS', result_text='a text',
                                          input_file='describer/in/photo.png')
        failed = Description.objects.create(user=self.u, status='FAILURE', result_text='')
        BatchDescriptionItem.objects.create(batch=self.lot, description=done, row_index=0)
        BatchDescriptionItem.objects.create(batch=self.lot, description=failed, row_index=1)
        self.views = make_batch_views(
            work_model=Description, batch_model=BatchDescription, get_user=lambda r: self.u,
            item_model=BatchDescriptionItem, fk_name='description', output_text='result_text')

    def test_the_zip_holds_one_txt_per_successful_element_named_by_the_common_rule(self):
        import io
        import zipfile
        req = self.rf.get('/x/')
        req.user = self.u
        r = self.views['batch_download'](req, self.lot.pk)
        self.assertEqual(200, r.status_code)
        archive = zipfile.ZipFile(io.BytesIO(b''.join(r.streaming_content)))
        names = archive.namelist()
        self.assertEqual(1, len(names), names)            # the failed element is left out
        self.assertTrue(names[0].startswith('photo') and names[0].endswith('.txt'), names)
        self.assertEqual(b'a text', archive.read(names[0]))


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


class LateBindingBatchDownloadTest(TestCase):
    """The batch ZIP of an app whose format is chosen AT DOWNLOAD (`export_binding='late'`) comes
    from the factory, read off the two DECLARATIONS the ⬇ button already uses on the card and on
    the queue bar: the formats declared in the catalogue, the renderer the app registered
    (2026-10-02).

    Before: three `batch_download` views copied in describer, reader and transcriber, each with
    its formats written by hand and its own query spelling (`?fmt=`). Generic: every late-binding
    queue app of the catalogue is exercised through its REAL route, none is named — a fourth one
    is covered without touching this test. The registered renderer is replaced by a stand-in
    (what a renderer produces is each app's own test)."""

    from wama.common.tests import tests_queue_delete_contract as _contract
    _account_for = _contract.SuppressionDansChaqueAppTest._compte_pour

    def _fleet(self):
        """(surface, account, element model, declared formats) of each late-binding queue app.

        A GENERATOR, on purpose: `_account_for` logs the client in as the account that passes the
        surface's gate (a sandbox twin needs the developer account), so it must run right before
        the surface is exercised — built as a list, the last surface's login served them all."""
        from wama.common.utils.export_formats import entries_for_app, is_late_binding
        from wama.common.utils.preview_registry import PreviewRegistry
        for surface, _delete_route, _card_route in self._contract._surfaces():
            if not is_late_binding(surface):
                continue
            declared = [e['value'] for e in entries_for_app(surface)]
            yield (surface, self._account_for(surface),
                   PreviewRegistry.get_model(surface), declared)

    def _zip(self, surface, lot, query):
        import io
        import zipfile
        from django.urls import reverse
        response = self.client.get(reverse(f'{surface}:batch_download', args=[lot.pk]), query)
        self.assertEqual(200, response.status_code, f'{surface} {query}')
        archive = zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)))
        return archive.namelist(), response['Content-Disposition']

    def _lot_with_one_success(self, model, account):
        lot, (done, _pending) = self._contract._lot_de(model, account, 2)
        model.objects.filter(pk=done.pk).update(status='SUCCESS')
        return lot

    @staticmethod
    def _stand_in(surface):
        return {surface: lambda item, fmt: (fmt, fmt.encode())}

    def test_the_fleet_is_measured_and_every_app_registered_its_renderer(self):
        """Non-vacuity — and the pairing the factory relies on: declared late ⇒ a renderer."""
        from wama.common.utils.export_formats import export_builder_for
        fleet = list(self._fleet())
        self.assertGreaterEqual(len(fleet), 3, [s for s, *_ in fleet])
        for surface, _account, _model, declared in fleet:
            with self.subTest(surface=surface):
                self.assertTrue(declared, 'late-binding without declared formats')
                self.assertTrue(callable(export_builder_for(surface)), 'no renderer registered')

    def test_each_declared_format_gives_a_zip_of_that_format(self):
        from unittest import mock
        from wama.common.utils import export_formats
        for surface, account, model, declared in self._fleet():
            lot = self._lot_with_one_success(model, account)
            with mock.patch.dict(export_formats._BUILDERS, self._stand_in(surface)):
                for fmt in declared:
                    with self.subTest(surface=surface, fmt=fmt):
                        names, disposition = self._zip(surface, lot, {'format': fmt})
                        self.assertEqual(1, len(names), 'only the successful element is rendered')
                        self.assertTrue(names[0].endswith('.' + fmt), names)
                        self.assertNotIn('/', names[0], 'an entry name must not open a folder')
                        self.assertIn(f'_{fmt}_', disposition)

    def test_an_unknown_or_missing_format_falls_back_to_the_first_declared(self):
        from unittest import mock
        from wama.common.utils import export_formats
        for surface, account, model, declared in self._fleet():
            lot = self._lot_with_one_success(model, account)
            with mock.patch.dict(export_formats._BUILDERS, self._stand_in(surface)), \
                    self.subTest(surface=surface):
                for query in ({}, {'format': 'exe'}):
                    names, _disposition = self._zip(surface, lot, query)
                    self.assertTrue(names[0].endswith('.' + declared[0]), (query, names))

    def test_the_old_query_spelling_of_the_batch_menus_is_still_read(self):
        from unittest import mock
        from wama.common.utils import export_formats
        for surface, account, model, declared in self._fleet():
            lot = self._lot_with_one_success(model, account)
            with mock.patch.dict(export_formats._BUILDERS, self._stand_in(surface)), \
                    self.subTest(surface=surface):
                names, _disposition = self._zip(surface, lot, {'fmt': declared[-1]})
                self.assertTrue(names[0].endswith('.' + declared[-1]), names)

    def test_no_app_keeps_a_batch_download_view_of_its_own(self):
        """The copy must not come back: a late-binding app's `batch_download` IS the factory's."""
        from importlib import import_module
        for surface, _account, model, _declared in self._fleet():
            with self.subTest(surface=surface):
                views = import_module(f'{model.__module__.rsplit(".", 1)[0]}.views')
                self.assertEqual('wama.common.utils.batch_views', views.batch_download.__module__)


class BatchViewsCriterionTest(TestCase):
    """The grid criterion `batch_views_common` sees a local batch view under EVERY spelling.

    Measured on 2026-10-02: the synthesizer kept its batch settings view under the name
    `batch_update_settings` — the pattern only knew `batch_update`, so the app was green with a
    hand-written view. Measured on FICTIVE apps; the real fleet is read by `check_app_conformity`.
    """

    def _verdict(self, views):
        from wama.common.tests.tests_queue_delete_contract import CriteresDeLaGrilleTest
        f, cc = CriteresDeLaGrilleTest._app(self, {'views.py': views})
        return next(c for c in cc.CRITERIA if c.key == 'batch_views_common').fn(f)

    def test_the_factory_alone_is_green(self):
        state, _evidence = self._verdict("_bv = make_batch_views(work_model=X)\n"
                                         "batch_update_settings = _bv['batch_update']\n")
        self.assertIs(state, True)

    def test_a_local_settings_view_is_partial_under_both_spellings(self):
        for name in ('batch_update', 'batch_update_settings'):
            with self.subTest(name=name):
                state, evidence = self._verdict(
                    f"_bv = make_batch_views(work_model=X)\ndef {name}(request, pk):\n    pass\n")
                self.assertEqual(state, 'partial')
                self.assertIn('views.py:2', evidence)

    def test_other_batch_routes_are_not_batch_views(self):
        """`batch_template`, `batch_preview`, `batch_list` belong to the import, not to the six."""
        state, _evidence = self._verdict(
            "_bv = make_batch_views(work_model=X)\ndef batch_template(request):\n    pass\n"
            "def batch_list(request):\n    pass\n")
        self.assertIs(state, True)
