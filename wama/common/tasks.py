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


@shared_task(name='common.purge_expired_media')
def purge_expired_media_task(dry_run=False):
    """
    Purge des médias expirés selon la rétention par utilisateur. Planifiée par Celery beat (quotidien).
    Avant la purge, envoie un pré-avis aux utilisateurs dont des médias expirent sous peu.
    """
    from wama.common.services.retention import purge_expired_media, upcoming_expirations
    from django.conf import settings

    # Pré-avis (J-N) — réutilise la brique notifications.
    try:
        notice_days = int(getattr(settings, 'WAMA_RETENTION_NOTICE_DAYS', 3) or 0)
        if notice_days > 0 and not dry_run:
            _send_retention_notices(upcoming_expirations(notice_days), notice_days)
    except Exception as e:  # pragma: no cover
        logger.debug("retention notice a échoué : %s", e)

    res = purge_expired_media(dry_run=dry_run)
    logger.info("[retention] %s", res)
    return res


def _send_retention_notices(upcoming, days):
    from django.contrib.auth.models import User
    from wama.common.utils.notifications import notify_user
    for user_id, items in (upcoming or {}).items():
        try:
            user = User.objects.get(pk=user_id)
            prof = getattr(user, 'profile', None)
            if prof is None or not prof.notify_email:
                continue
            total = sum(n for _, n in items)
            if not total:
                continue
            body = (
                f"Bonjour {user.username},\n\n"
                f"{total} de vos médias seront supprimés dans {days} jour(s) (rétention de "
                f"{prof.effective_retention_days()} j).\n\n"
                "Téléchargez ce que vous souhaitez conserver, ou augmentez votre durée de "
                "conservation dans votre profil.\n\n— WAMA"
            )
            notify_user(user, "[WAMA] Médias bientôt supprimés", body)
        except Exception:  # pragma: no cover
            continue

