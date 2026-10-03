"""The OUTCOME of an element's task through the common skeleton — ONE contract, every adopter.

Contract 4 of `WAMA_VERIFICATION §8` (2026-09-26). `run_item_task` was tested for redelivery
only, on the synthesizer's model; the outcome was checked per app (transcriber, enhancer). Here,
for EVERY app whose item task is on the skeleton (grid criterion `task_skeleton`, measured on the
code), on THAT app's element model, with a stand-in glue:

  * the glue returns → SUCCESS, progress 100 and processing time (when the model has them);
  * the glue raises → FAILURE carrying the message in the error field.

What each app's glue does inside stays its own test — here only what the skeleton promises.
"""
from unittest import mock

from django.test import TestCase

from wama.common.tests.tests_queue_delete_contract import _instance


def _adopters():
    """(app, element model) of every app whose item task goes through `run_item_task`."""
    from wama.common.app_registry import APP_CATALOG
    from wama.common.services import conformity_checker as cc
    from wama.common.utils.preview_registry import PreviewRegistry
    out = []
    for app, spec in APP_CATALOG.items():
        if (spec or {}).get('sandbox'):
            continue
        state, _proof = cc._task_skeleton(cc._AppFiles(app))
        model = PreviewRegistry.get_model(app)
        if state is True and model is not None:
            out.append((app, model))
    return out


def _task():
    class _T:
        class request:
            id = 'tache-contrat'
            retries = 0
            delivery_info = {}
    return _T


class TaskSkeletonOutcomeContractTest(TestCase):

    def _run(self, app, model, glue):
        from django.contrib.auth import get_user_model
        from wama.common.utils.task_skeleton import run_item_task
        user = get_user_model().objects.create_user(f'skeleton_{app}_{id(glue)}', password='x')
        item = _instance(model, user)
        if hasattr(item, 'status'):
            model.objects.filter(pk=item.pk).update(status='RUNNING')
        # `close_old_connections()` opens the skeleton: inside a TestCase it would close the
        # test's connection (cf. tests_task_skeleton_redelivery).
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=app, model=model, item_id=item.pk, process=glue)
        return model.objects.get(pk=item.pk)

    def test_the_fleet_is_measured(self):
        adopters = _adopters()
        self.assertGreaterEqual(len(adopters), 4, [a for a, _ in adopters])

    def test_a_glue_that_returns_ends_in_success(self):
        for app, model in _adopters():
            with self.subTest(app=app):
                item = self._run(app, model, lambda item, ctx: {})
                self.assertEqual('SUCCESS', item.status)
                if hasattr(item, 'progress'):
                    self.assertEqual(100, item.progress)
                # What the skeleton promises (`task_skeleton.py:40`): the processing time, when
                # the model carries it. An app's own end stamp (`finished_at`…) is its glue's.
                if hasattr(item, 'processing_seconds'):
                    self.assertIsNotNone(item.processing_seconds, 'processing time not recorded')

    def test_a_success_gives_the_element_a_revision_tied_to_the_produced_fact(self):
        """Marche 8a (`WAMA_COLLABORATION §7.1`): every result becomes a numbered revision of the
        element, attached to the `produit` fact of `RunOutcome` — one journal, not two — and
        carrying what the glue says was asked. A second success is revision 2 of the SAME item."""
        from wama.common.models import ItemRevision, RunOutcome
        for app, model in _adopters():
            with self.subTest(app=app):
                item = self._run(app, model, lambda item, ctx: {'instruction': 'plus court'})
                revisions = ItemRevision.objects.filter(
                    app=app, object_type=model.__name__, object_id=item.pk)
                self.assertEqual([1], [r.number for r in revisions])
                revision = revisions.get()
                self.assertEqual('plus court', revision.instruction)
                self.assertIsNotNone(revision.outcome, 'revision not tied to the journal')
                self.assertEqual('produit', revision.outcome.signal)
                self.assertTrue(RunOutcome.objects.filter(pk=revision.outcome_id,
                                                          object_id=item.pk).exists())

                from wama.common.utils.task_skeleton import run_item_task
                model.objects.filter(pk=item.pk).update(status='RUNNING')
                with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
                    run_item_task(_task(), app_id=app, model=model, item_id=item.pk,
                                  process=lambda item, ctx: {})
                self.assertEqual([2, 1], [r.number for r in ItemRevision.objects.filter(
                    app=app, object_type=model.__name__, object_id=item.pk)
                    .order_by('-number')])

    def test_a_revision_names_as_outputs_only_what_the_glue_wrote(self):
        """The element's other files (its INPUTS) are not outputs — measured on the Writer's
        1st real revision, which named its reference document and not the document produced."""
        from django.db.models import FileField
        from wama.common.models import ItemRevision
        for app, model in _adopters():
            file_fields = [f.name for f in model._meta.get_fields() if isinstance(f, FileField)]
            if not file_fields:
                continue

            def glue(item, ctx, model=model, file_fields=file_fields):
                model.objects.filter(pk=item.pk).update(**{f: 'users/some.bin' for f in file_fields})
                return {}
            with self.subTest(app=app):
                item = self._run(app, model, glue)
                revision = ItemRevision.objects.get(app=app, object_type=model.__name__,
                                                    object_id=item.pk)
                self.assertEqual([], revision.outputs)

    def test_a_failure_gives_no_revision(self):
        """A revision is a state a RESULT gave; a failure produced none."""
        from wama.common.models import ItemRevision

        def glue(item, ctx):
            raise RuntimeError('pas de résultat')
        for app, model in _adopters():
            with self.subTest(app=app):
                item = self._run(app, model, glue)
                self.assertFalse(ItemRevision.objects.filter(
                    app=app, object_type=model.__name__, object_id=item.pk).exists())

    def test_an_element_with_a_reference_is_measured_once_it_is_a_success(self):
        """The measurement against the reference reads a FINISHED element. Until 2026-09-29 the
        transcriber measured inside its glue, before the skeleton set SUCCESS: its result reader
        refused the element, and no transcription measured itself — silently, for four days."""
        from wama.common.services.result_evaluation import evaluation_spec
        measured = []
        adopters = [(a, m) for a, m in _adopters() if evaluation_spec(a) is not None]
        self.assertTrue(adopters, 'no skeleton adopter declares an evaluation')
        for app, model in adopters:
            spec = evaluation_spec(app)

            def glue(item, ctx, model=model, field=spec.reference_field):
                model.objects.filter(pk=item.pk).update(**{field: 'reference.srt'})
                return {}
            with self.subTest(app=app), mock.patch(
                    'wama.common.services.result_evaluation.evaluate',
                    side_effect=lambda surface, item: measured.append(
                        (surface, item.status)) or []):
                self._run(app, model, glue)
                self.assertIn((app, 'SUCCESS'), measured)

    def test_a_glue_that_raises_ends_in_failure_with_its_message(self):
        def glue(item, ctx):
            raise RuntimeError('panne du contrat')
        for app, model in _adopters():
            with self.subTest(app=app):
                item = self._run(app, model, glue)
                self.assertEqual('FAILURE', item.status)
                message = getattr(item, 'error_message', None)
                if message is not None:
                    self.assertIn('panne du contrat', message)


class _Redelivered(Exception):
    """What the stand-in task raises in place of Celery's `Retry`."""


class ServiceNotReadyContractTest(TestCase):
    """A glue whose SERVICE is not ready yet (the TTS service still loading) is not a failure:
    the skeleton gives the worker back and has the task delivered again — extracted on 2026-10-03
    from the synthesizer and the avatarizer, which each held this policy around `self.retry()`."""

    def _run(self, app, model, retry):
        from django.contrib.auth import get_user_model
        from wama.common.utils.task_skeleton import ServiceNotReady, run_item_task
        user = get_user_model().objects.create_user(f'not_ready_{app}_{id(retry)}', password='x')
        item = _instance(model, user)
        model.objects.filter(pk=item.pk).update(status='RUNNING')
        task = _task()
        task.retry = staticmethod(retry)

        def glue(element, ctx):
            raise ServiceNotReady('Service TTS en chargement', countdown=10, max_attempts=60,
                                  gave_up='Service TTS non disponible après 10 minutes')
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            try:
                run_item_task(task, app_id=app, model=model, item_id=item.pk, process=glue)
            except _Redelivered as again:
                return model.objects.get(pk=item.pk), again
        return model.objects.get(pk=item.pk), None

    def test_the_task_is_delivered_again_and_the_card_stays_running_saying_it_waits(self):
        asked = {}

        def retry(**kw):
            asked.update(kw)
            return _Redelivered()
        for app, model in _adopters()[:2]:
            with self.subTest(app=app):
                item, again = self._run(app, model, retry)
                self.assertIsNotNone(again, 'the worker was not given back')
                self.assertEqual({'countdown': 10, 'max_retries': 60}, asked)
                self.assertEqual('RUNNING', item.status, 'waiting for a service is not a failure')
                message = getattr(item, 'error_message', None)
                if message is not None:
                    self.assertIn('Service TTS en chargement', message)
                    self.assertIn('1/60', message)

    def test_past_the_last_attempt_the_failure_is_stated(self):
        from celery.exceptions import MaxRetriesExceededError
        app, model = _adopters()[0]
        item, again = self._run(app, model, lambda **kw: MaxRetriesExceededError("Can't retry"))
        self.assertIsNone(again)
        self.assertEqual('FAILURE', item.status)
        message = getattr(item, 'error_message', None)
        if message is not None:
            self.assertIn('non disponible après 10 minutes', message)
