"""The Celery worker supervision stays coherent with the startup scripts (2026-09-24/26).

`scripts/wama_services.sh` is the ONE definition of the runtime environment and of the worker
launches; `start_wama_prod.sh`, `start_wama_dev.sh` and `scripts/worker_watchdog.sh` call it. The
day it was written, a manual restart had copied the environment and forgotten three variables:
these guards keep a second copy from coming back, and keep the supervision's traps closed.
"""
import re
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)
SERVICES = BASE / 'scripts' / 'wama_services.sh'
WATCHDOG = BASE / 'scripts' / 'worker_watchdog.sh'
STARTERS = [BASE / 'start_wama_prod.sh', BASE / 'start_wama_dev.sh']


def _read(path):
    return path.read_text(encoding='utf-8')


class WorkerSupervisionScriptsTest(SimpleTestCase):

    def test_the_start_scripts_launch_workers_only_through_the_shared_definition(self):
        for path in STARTERS:
            src = _read(path)
            self.assertIn('source $PROJECT_DIR/scripts/wama_services.sh', src, path.name)
            self.assertIn('wama_worker_env', src, path.name)
            self.assertIn('start_celery_worker "$w"', src, path.name)
            self.assertNotRegex(src, r'(?m)^\s*celery -A wama (worker|beat)',
                                f'{path.name}: a second copy of a worker launch')
            self.assertIn('scripts/worker_watchdog.sh', src, f'{path.name}: no supervision')

    def test_the_supervision_is_stopped_before_the_workers_are_killed(self):
        """Left alive, it would relaunch the workers the restart is stopping."""
        for path in STARTERS:
            src = _read(path)
            stop_watchdog = src.index('pkill -f "scripts/[w]orker_watchdog.sh"')
            self.assertLess(stop_watchdog, src.index('pkill -f "celery"'), path.name)

    def test_death_is_read_on_the_process_never_on_a_ping(self):
        """The solo gpu worker does not answer `inspect ping` while it works: a ping would take a
        busy worker for a dead one (the inverted signal of 2026-07-25)."""
        src = _read(WATCHDOG)
        self.assertIn('celery_worker_alive', src)
        self.assertNotRegex(src, r'(?m)^[^#]*inspect\s+ping')
        self.assertIn('source "$PROJECT_DIR/scripts/wama_services.sh"', src)

    def test_every_outcome_the_supervision_reports_is_known_to_the_command(self):
        from wama.common.management.commands.worker_died import OUTCOMES
        passed = set(re.findall(r'\breport "\$w" "?(\w+)"?', _read(WATCHDOG)))
        passed |= set(re.findall(r'\boutcome=(\w+)', _read(WATCHDOG)))
        self.assertTrue(passed)
        self.assertLessEqual(passed, set(OUTCOMES), passed - set(OUTCOMES))

    def test_the_higgs_export_stays_in_the_prod_start_script(self):
        """`patches/apply_patches.py` (patch 4) checks it THERE — moving the environment into
        the shared file must not carry it away."""
        self.assertIn('HIGGS_DISABLE_CUDA_GRAPHS', _read(BASE / 'start_wama_prod.sh'))


class WorkerSupervisionShellTest(SimpleTestCase):
    """Executed by bash — skipped where bash is absent (Windows venv)."""

    def setUp(self):
        self.bash = shutil.which('bash')
        if not self.bash or not Path('/proc/version').exists():
            self.skipTest('bash (Linux) required')

    def _bash(self, script):
        return subprocess.run([self.bash, '-c', script], capture_output=True, text=True,
                              cwd=str(BASE), timeout=30)

    def test_the_three_scripts_parse(self):
        for path in [SERVICES, WATCHDOG] + STARTERS:
            r = self._bash(f'bash -n "{path}"')
            self.assertEqual(0, r.returncode, f'{path.name}: {r.stderr}')

    def test_every_pattern_is_bracketed_and_an_unknown_worker_is_never_alive(self):
        """A bracketed pattern never matches its own command line; an EMPTY pattern would make
        `pgrep` match every process — an unknown worker would read as alive."""
        r = self._bash(f'PROJECT_DIR="{BASE}" LOG_DIR=/tmp; source "{SERVICES}"; '
                       'for w in $WAMA_CELERY_WORKERS; do celery_worker_pattern $w; done; '
                       'celery_worker_alive bogus && echo BOGUS_ALIVE || echo BOGUS_DEAD')
        lines = r.stdout.split()
        self.assertIn('BOGUS_DEAD', lines)
        patterns = [l for l in r.stdout.splitlines() if l and not l.startswith('BOGUS')]
        self.assertEqual(4, len(patterns), r.stdout)
        for pattern in patterns:
            self.assertRegex(pattern, r'\[\w\]', pattern)

    def test_the_default_worker_pool_is_declared_not_duplicated(self):
        r = self._bash(f'PROJECT_DIR="{BASE}" LOG_DIR=/tmp; source "{SERVICES}"; '
                       'celery() { echo "$*"; }; start_celery_worker default; '
                       'WAMA_DEFAULT_WORKER_POOL=solo start_celery_worker default')
        prod, dev = r.stdout.strip().splitlines()
        self.assertIn('--pool=prefork', prod)
        self.assertIn('--autoscale=4,1', prod)
        self.assertIn('--pool=solo', dev)
