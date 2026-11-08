"""The libraries page gets the model's fiche AND its gestures (Fabien's decision, 2026-11-07,
`WAMA_VOLETS §2` point 2) — simulate / install / uninstall, by ONE request body
(`model_installer.request_library_action`) that the page and the assistant's tools both call, run
in a task by the command-line drivers (`install_library` / `uninstall_library`), never a third path.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.models import Library
from wama.model_manager import tasks
from wama.model_manager.services import model_installer as mi


def _account(username, tier):
    from wama.accounts.models import UserProfile
    user = get_user_model().objects.create_user(username, password='x')
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.account_tier = tier
    profile.save()
    return get_user_model().objects.get(pk=user.pk)


def _dispatched():
    """The task's `delay`, replaced : nothing leaves for a worker."""
    return mock.patch.object(tasks.library_action_task, 'delay',
                             side_effect=lambda *a: SimpleNamespace(id='task-%d' % len(a)))


class OneRequestBodyTest(TestCase):

    def setUp(self):
        cache.delete(tasks.LIBRARY_CACHE_PREFIX + 'probe-lib')
        self.lib = Library.objects.create(key='probe-lib', name='probe-lib',
                                          pip_spec='probe-lib==1.0.0')
        self.admin = _account('lib_admin', 'admin')
        self.dev = _account('lib_dev', 'developpeur')

    def test_a_developer_may_simulate_but_not_write_the_environment(self):
        with _dispatched() as delay:
            self.assertEqual('forbidden', mi.request_library_action(
                'probe-lib', 'install', user=self.dev)['reason'])
            self.assertEqual('forbidden', mi.request_library_action(
                'probe-lib', 'uninstall', user=self.dev)['reason'])
            delay.assert_not_called()
            res = mi.request_library_action('probe-lib', 'plan', user=self.dev, via='model_manager')
        self.assertTrue(res['started'])
        delay.assert_called_once_with('probe-lib', 'plan', self.dev.pk, 'model_manager')
        self.lib.refresh_from_db()
        self.assertFalse(self.lib.is_allowed, 'a simulation decides nothing')

    def test_an_administrators_install_request_is_the_human_decision(self):
        with _dispatched():
            res = mi.request_library_action('probe-lib', 'install', user=self.admin)
        self.assertTrue(res['started'])
        self.lib.refresh_from_db()
        self.assertTrue(self.lib.is_allowed)

    def test_a_second_request_joins_the_running_task(self):
        with _dispatched() as delay, \
                mock.patch('wama.common.utils.task_progress.progression_en_cours',
                           side_effect=[None, {'state': 'RUNNING', 'action': 'plan'}]):
            mi.request_library_action('probe-lib', 'plan', user=self.admin)
            again = mi.request_library_action('probe-lib', 'install', user=self.admin)
        self.assertTrue(again['already_running'])
        self.assertEqual(1, delay.call_count)

    def test_unknown_gesture_and_unknown_library_are_refused(self):
        with _dispatched() as delay:
            self.assertEqual('unknown_action', mi.request_library_action(
                'probe-lib', 'pip install x', user=self.admin)['reason'])
            self.assertEqual('not_found', mi.request_library_action(
                'not-in-registry', 'plan', user=self.admin)['reason'])
        delay.assert_not_called()


class TheTaskRunsTheCommandLineDriversTest(TestCase):

    def setUp(self):
        cache.delete(tasks.LIBRARY_CACHE_PREFIX + 'probe-lib')

    def test_each_gesture_calls_its_driver_and_publishes_the_issue(self):
        cases = {'plan': ('install_library', {'apply': False}),
                 'install': ('install_library', {'apply': True}),
                 'uninstall': ('uninstall_library', {'apply': True})}
        for action, (driver, kwargs) in cases.items():
            with self.subTest(action=action), \
                    mock.patch.object(mi, driver, return_value={'ok': True, 'plan': {}}) as called:
                tasks.library_action_task.apply(args=('probe-lib', action, None, 'model_manager'))
                called.assert_called_once_with('probe-lib', via='model_manager', **kwargs)
                state = cache.get(tasks.LIBRARY_CACHE_PREFIX + 'probe-lib')
                self.assertEqual(('SUCCESS', action), (state['state'], state['action']))

    def test_a_refusal_of_the_driver_is_published_as_a_failure(self):
        refused = {'ok': False, 'error': 'encore requise : manifests/apps/x.json'}
        with mock.patch.object(mi, 'uninstall_library', return_value=refused):
            tasks.library_action_task.apply(args=('probe-lib', 'uninstall', None, ''))
        state = mi.library_action_state('probe-lib')
        self.assertEqual('FAILURE', state['state'])
        self.assertIn('encore requise', state['error'])

    def test_a_running_state_whose_task_is_dead_reads_interrupted(self):
        cache.set(tasks.LIBRARY_CACHE_PREFIX + 'probe-lib',
                  {'state': 'RUNNING', 'task_id': 'dead', 'action': 'install'}, 60)
        with mock.patch('wama.common.utils.task_progress.progression_en_cours', return_value=None):
            state = mi.library_action_state('probe-lib')
        self.assertEqual('FAILURE', state['state'])
        self.assertIn('interrompue', state['error'])


class ThePageAndTheToolsTest(TestCase):

    def setUp(self):
        Library.objects.create(key='probe-lib', name='probe-lib', pip_spec='probe-lib==1.0.0',
                               license='MIT', constraints={'pip': ['numpy==2.3.5']})

    def test_the_served_page_carries_the_fiche_and_the_rights_of_the_account(self):
        self.client.force_login(_account('page_admin', 'admin'))
        page = self.client.get(reverse('model_manager:libraries_catalog'))
        self.assertContains(page, 'data-can-install="1"')
        self.assertContains(page, 'model_manager/js/library-catalog.js')
        self.assertContains(page, 'id="libraryActionButtons"')
        details = json.loads(page.content.decode().split('id="library-details" type="application/json">', 1)[1]
                            .split('</script>', 1)[0])
        detail = next(d for d in details if d['key'] == 'probe-lib')
        self.assertEqual(('1.0.0', 'pip', ['numpy==2.3.5'], 'MIT'),
                         (detail['declared_version'], detail['route'], detail['constraints_pip'],
                          detail['license']))

    def test_a_developer_simulates_and_an_ordinary_account_has_no_actions(self):
        self.client.force_login(_account('page_dev', 'developpeur'))
        page = self.client.get(reverse('model_manager:libraries_catalog'))
        self.assertContains(page, 'data-can-plan="1" data-can-install="0"')
        self.client.force_login(_account('page_user', 'utilisateur'))
        page = self.client.get(reverse('model_manager:libraries_catalog'))
        self.assertEqual(200, page.status_code)
        self.assertNotContains(page, 'id="libraryActionButtons"')

    def test_the_view_says_a_refusal_in_http(self):
        self.client.force_login(_account('view_dev', 'developpeur'))
        with _dispatched():
            r = self.client.post(reverse('model_manager:api_library_action'),
                                 json.dumps({'key': 'probe-lib', 'action': 'install'}),
                                 content_type='application/json')
        self.assertEqual(403, r.status_code)

    def test_the_assistants_tools_take_the_same_body(self):
        from wama import tool_api as T
        self.assertEqual('forbidden', T.install_library(_account('tool_user', 'utilisateur'),
                                                        'probe-lib')['error'])
        admin = _account('tool_admin', 'admin')
        with mock.patch.object(mi, 'request_library_action',
                               return_value={'ok': True, 'started': True}) as body:
            self.assertTrue(T.install_library(admin, 'probe-lib', simulate=True)['started'])
            T.uninstall_library(admin, 'probe-lib')
        self.assertEqual([('probe-lib', 'plan'), ('probe-lib', 'uninstall')],
                         [c.args for c in body.call_args_list])
        self.assertEqual({'install_library': 'write', 'uninstall_library': 'destroy',
                          'get_library_action': 'read'},
                         {n: T.effect_of(n)['effect'] for n in
                          ('install_library', 'uninstall_library', 'get_library_action')})


class ServedPageScriptTest(SimpleTestCase):
    """The SERVED file (V8) : the gestures each account is offered, and the plan said in clear."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        ctx = MiniRacer()
        ctx.eval("""var window = this; var document = {readyState: 'complete',
                    querySelector: function () { return null; },
                    getElementById: function () { return null; },
                    addEventListener: function () {}};""")
        served = Path(settings.BASE_DIR) / 'staticfiles' / 'model_manager' / 'js' / 'library-catalog.js'
        ctx.eval(served.read_text(encoding='utf-8'))
        return ctx

    def _offered(self, ctx, can, detail):
        return ctx.eval("""(function () {
            var s = WamaLibraryCatalog.actionSchema(%s, function () {});
            var f = %s;
            return s.filter(function (a) { return a.when(f); }).map(function (a) { return a.label; });
        })()""" % (json.dumps(can), json.dumps(detail)))

    def test_the_gestures_follow_the_account_and_the_library(self):
        ctx = self._ctx()
        absent = {'route': 'pip', 'live_version': '', 'drift': False}
        installed = {'route': 'pip', 'live_version': '1.0.0', 'drift': True}
        vendored = {'route': 'vendor', 'live_version': 'abc', 'drift': False}
        self.assertEqual(['Simuler l’installation'],
                         list(self._offered(ctx, {'plan': True, 'install': False}, installed)))
        self.assertEqual(['Simuler l’installation', 'Installer'],
                         list(self._offered(ctx, {'plan': True, 'install': True}, absent)))
        self.assertEqual(['Simuler l’installation', 'Aligner sur la version déclarée', 'Désinstaller'],
                         list(self._offered(ctx, {'plan': True, 'install': True}, installed)))
        # Contre-épreuve : une librairie vendorisée n'a pas de retrait par la route.
        self.assertNotIn('Désinstaller',
                         list(self._offered(ctx, {'plan': True, 'install': True}, vendored)))

    def test_the_plan_says_what_pip_would_move_and_escapes_it(self):
        ctx = self._ctx()
        html = ctx.eval('WamaLibraryCatalog.stateHtml(%s)' % json.dumps({
            'state': 'SUCCESS', 'ok': True, 'action': 'plan',
            'plan': {'simulation': {'ok': True, 'would_install': ['<b>x-1</b>'],
                                    'retrogradations': [{'paquet': 'torch', 'installee': '2.9.1',
                                                         'deviendrait': '2.2.2'}]}}}))
        self.assertIn('Déplacerait torch : 2.9.1 → 2.2.2', html)
        self.assertIn('&lt;b&gt;x-1&lt;/b&gt;', html)
        self.assertNotIn('<b>x-1</b>', html)
