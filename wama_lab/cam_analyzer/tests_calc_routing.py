"""L'étage CALCULS du cam_analyzer tourne sur la file `default`, à côté des traitements GPU.

Constat de Fabien (2026-09-29) : « les calculs ne passent pas car il y a des tâches GPU en cours
dans le Transcriber ». Toutes les tâches du cam_analyzer étaient routées sur `gpu` (worker solo) ;
les passes de calcul — CPU pur — attendaient derrière chaque transcription. La liste des routes
`default` (settings.CELERY_TASK_ROUTES) est JUMELLE du registre `pass_tracking.PASSES` : ce test
échoue si une passe de calcul est ajoutée au registre sans sa route, ou l'inverse.
"""
import fnmatch

from django.conf import settings
from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils.pass_tracking import PASSES

PREFIX = 'wama_lab.cam_analyzer.tasks.'


def queue_of(task_name):
    """File Celery d'une tâche, comme le résout le routeur : nom EXACT d'abord, puis motifs."""
    routes = getattr(settings, 'CELERY_TASK_ROUTES', None) or {}
    if task_name in routes:
        return routes[task_name].get('queue')
    for pattern, route in routes.items():
        if '*' in pattern and fnmatch.fnmatchcase(task_name, pattern):
            return route.get('queue')
    return 'celery'


class CalcRoutingTest(SimpleTestCase):
    def setUp(self):
        if not getattr(settings, 'CELERY_TASK_ROUTES', None):
            self.skipTest('Celery désactivé dans ces réglages')

    def test_cpu_calculation_passes_run_beside_the_gpu_queue(self):
        for p in PASSES:
            if p.task and p.stage == 'calcul' and not p.gpu:
                self.assertEqual(queue_of(PREFIX + p.task), 'default', p.key)

    def test_gpu_passes_stay_on_the_gpu_queue(self):
        for p in PASSES:
            if p.task and p.gpu:
                self.assertEqual(queue_of(PREFIX + p.task), 'gpu', p.key)

    def test_the_chain_release_follows_the_calculations(self):
        self.assertEqual(queue_of(PREFIX + 'release_calc_chain_task'), 'default')

    def test_no_default_route_names_a_task_that_does_not_exist(self):
        from wama_lab.cam_analyzer import tasks
        for name, route in settings.CELERY_TASK_ROUTES.items():
            if name.startswith(PREFIX) and '*' not in name:
                self.assertTrue(hasattr(tasks, name[len(PREFIX):]), name)
