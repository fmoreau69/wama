"""The LIFE CYCLE of an element through its views — ONE contract, every app.

Contract 2 of `WAMA_VERIFICATION §8` (2026-09-26); the ownership half lives in
`tests_endpoints.AnotherUsersElementTest`. Only `synthesizer/tests.py` checked this, for itself.
For every app of the catalogue, on a witness element built by the generic factory:

  * ▶ `<app>:start` (task dispatch mocked) either starts it — RUNNING and a task id recorded —
    or REFUSES it by saying so (4xx with a message), never a silent 200 that changes nothing;
  * `<app>:progress` answers JSON the queue can read.
"""
import json
from unittest import mock

from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from wama.common.tests_queue_delete_contract import _instance


def _surfaces(route):
    from wama.common.app_registry import APP_CATALOG
    from wama.common.sandbox import twins_with_copied_views
    from wama.common.utils.preview_registry import PreviewRegistry
    copied = twins_with_copied_views()
    out = []
    for app, spec in APP_CATALOG.items():
        if app in copied or (spec or {}).get('sandbox'):
            continue
        try:
            reverse(f'{app}:{route}', args=[1])
        except NoReverseMatch:
            continue
        model = PreviewRegistry.get_model(app)
        if model is not None:
            out.append((app, model))
    return out


class ItemLifecycleContractTest(TestCase):

    def _login_for(self, app):
        from wama.common.tests_endpoints import EveryEndpointAnswersTest
        user = EveryEndpointAnswersTest._account_for(self, app)
        self.client.force_login(user)
        return user

    def test_start_starts_or_says_why_not(self):
        surfaces = _surfaces('start')
        self.assertGreaterEqual(len(surfaces), 8, [a for a, _ in surfaces])
        started, refused = [], []
        for app, model in surfaces:
            with self.subTest(app=app):
                item = _instance(model, self._login_for(app))
                with mock.patch('celery.app.task.Task.apply_async',
                                return_value=mock.Mock(id='tache-de-test')) as dispatch:
                    r = self.client.post(reverse(f'{app}:start', args=[item.pk]))
                item.refresh_from_db()
                if r.status_code == 200 and dispatch.called:
                    self.assertEqual('RUNNING', getattr(item, 'status', 'RUNNING'))
                    if hasattr(item, 'task_id'):
                        self.assertEqual('tache-de-test', item.task_id, 'task id not recorded')
                    started.append(app)
                else:
                    refused.append(f'{app} ({r.status_code})')
                    self.assertGreaterEqual(r.status_code, 400,
                                            f'200 without starting anything: {r.content[:200]!r}')
                    body = r.content.decode(errors='replace')
                    self.assertTrue(body.strip(), 'a refusal must say why')
        # Non-vacuity: a witness refused everywhere would make the contract a list of refusals.
        self.assertGreaterEqual(len(started), 5, f'started {started}, refused {refused}')

    def test_progress_answers_json_the_queue_can_read(self):
        surfaces = _surfaces('progress')
        self.assertGreaterEqual(len(surfaces), 5, [a for a, _ in surfaces])
        for app, model in surfaces:
            with self.subTest(app=app):
                item = _instance(model, self._login_for(app))
                r = self.client.get(reverse(f'{app}:progress', args=[item.pk]))
                self.assertEqual(200, r.status_code, r.content[:200])
                data = json.loads(r.content)
                self.assertTrue({'progress', 'status'} & set(data), data)
