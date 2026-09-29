"""
Qui met une tâche Celery en file — `common/services/runtime_side.py` (2026-09-29).

Règle de Fabien : *« tout doit passer côté WSL, rien côté Windows, sauf les tests à la demande »*.
Mesuré le 28/09 : 1 872 messages jamais consommés dans le Redis que joint Windows, et des tâches
de TEST reçues par les vrais workers depuis WSL (`tests_registries` → `refresh_registry`).
"""
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from wama.common.services.runtime_side import running_tests, tasks_dispatched


class DispatchRuleTest(SimpleTestCase):

    def test_only_a_wsl_process_outside_tests_dispatches(self):
        cases = {
            (('manage.py', 'runserver'), 'posix'): True,        # gunicorn, shell WSL
            (('celery', '-A', 'wama', 'beat'), 'posix'): True,  # beat, workers
            (('manage.py', 'test', 'wama'), 'posix'): False,    # tests depuis WSL (suite nocturne)
            (('manage.py', 'test'), 'nt'): False,               # tests à la demande sous Windows
            (('manage.py', 'check'), 'nt'): False,              # tout processus Windows
        }
        for (argv, os_name), expected in cases.items():
            with self.subTest(argv=argv, os=os_name):
                self.assertEqual(tasks_dispatched(list(argv), os_name), expected)

    def test_this_test_process_never_reaches_the_real_broker(self):
        from wama.celery import app
        self.assertTrue(running_tests())
        self.assertFalse(settings.WAMA_TASKS_DISPATCHED)
        self.assertEqual(settings.CELERY_BROKER_URL, 'memory://')
        self.assertTrue(str(app.conf.broker_url).startswith('memory://'),
                        'l’application Celery elle-même doit parler au broker en mémoire')
        with app.connection_for_write() as conn:
            self.assertEqual(conn.transport.driver_type, 'memory')

    def test_a_dispatch_during_tests_goes_nowhere(self):
        # Le cas mesuré : `launch()` d'un registre Celery met sa tâche en file. Elle doit
        # rester dans le processus — rien n'atteint un Redis.
        from wama.common.registries import CELERY, DERIVED, REGISTRIES, execution_of, launch
        key = next(k for k, r in REGISTRIES.items()
                   if execution_of(r) == CELERY and r.nature != DERIVED)
        with mock.patch('redis.connection.Connection.connect',
                        side_effect=AssertionError('Redis touché pendant un test')):
            result = launch(key)
        self.assertTrue(result.get('ok'), result)
        self.assertTrue(result.get('async'), 'le registre doit bien passer par une mise en file')


class StartupSyncTest(SimpleTestCase):
    """La synchro du catalogue au démarrage ne part que du côté autorisé."""

    def _ready(self, dispatched):
        from django.apps import apps
        config = apps.get_app_config('model_manager')
        with override_settings(WAMA_TASKS_DISPATCHED=dispatched), \
                mock.patch('sys.argv', ['manage.py', 'runserver']), \
                mock.patch('django.core.cache.cache.add', return_value=True), \
                mock.patch('wama.model_manager.tasks.sync_models_task.apply_async') as dispatch, \
                mock.patch.object(type(config), '_start_file_watcher'):
            config.ready()
        return dispatch

    def test_no_startup_sync_outside_the_allowed_side(self):
        self._ready(dispatched=False).assert_not_called()

    def test_counter_proof_the_allowed_side_still_syncs(self):
        self._ready(dispatched=True).assert_called_once()


class CacheSideTest(SimpleTestCase):
    """Le CACHE suit la même règle : hors du côté autorisé, en mémoire du process (2026-09-29).

    Un `manage.py` Windows hors tests écrivait dans le Redis WINDOWS (db1, clés `user_N_*`), que
    WAMA ne lit pas. Les settings sont relus dans un sous-processus hors tests (`manage.py shell`),
    la DÉCISION de `runtime_side` imposée — forcer `os.name` casserait `pathlib` sous Linux.
    """

    def _backend(self, dispatched):
        import subprocess
        import sys
        code = ("import os, sys; sys.argv = ['manage.py', 'shell']; "
                "import wama.common.services.runtime_side as side; "
                "side.tasks_dispatched = lambda *a, **k: %r; "
                "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings'); "
                "from django.conf import settings; "
                "print(settings.CACHES['default']['BACKEND'])" % dispatched)
        out = subprocess.run([sys.executable, '-c', code], cwd=str(settings.BASE_DIR),
                             capture_output=True, text=True, timeout=120)
        return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[-300:]

    def test_a_process_outside_the_allowed_side_keeps_its_cache_in_memory(self):
        self.assertIn('LocMemCache', self._backend(False))

    def test_counter_proof_the_allowed_side_keeps_the_shared_redis(self):
        self.assertIn('RedisCache', self._backend(True))

    def test_this_test_process_uses_a_private_cache(self):
        self.assertIn('LocMemCache', settings.CACHES['default']['BACKEND'])
