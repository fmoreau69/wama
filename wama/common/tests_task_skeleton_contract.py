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

from wama.common.tests_queue_delete_contract import _instance


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
