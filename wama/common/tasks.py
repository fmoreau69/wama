"""
Tâches Celery transverses (app `common`).
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='common.run_nightly_tests')
def run_nightly_tests_task(app=None, stage=None):
    """
    Joue la suite de tests fonctionnels nocturnes (sérialisée, VRAM-aware).
    Planifiée par Celery beat la nuit (entrée gated par NIGHTLY_TESTS_ENABLED dans settings).
    Filtrable par `app` / `stage`. Retourne le résumé.
    """
    from wama.common.services.nightly_tests import REGISTRY, run_all

    scenarios = [
        s for s in REGISTRY
        if s.enabled
        and (not app or s.app == app)
        and (not stage or s.stage == stage)
    ]
    report = run_all(scenarios)
    logger.info("[nightly] %s", report.get('summary'))
    return report.get('summary')
