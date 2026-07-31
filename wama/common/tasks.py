"""
Tâches Celery transverses (app `common`).
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='common.enrich_prompt_at_ingest')
def enrich_prompt_at_ingest_task(app_label, model_name, pk):
    """
    Enrichit le prompt d'un objet DÈS SON DÉPÔT — pour TOUTE app, sans code par app.

    Déclenchée par le récepteur générique ([[prompt_ingest]]) sur les modèles dont l'app déclare
    `enrich=True` dans `PROMPT_TARGETS`. Les champs traités viennent de la DÉCLARATION.

    ASYNCHRONE volontairement : la passe LLM coûte ~1,3 s à chaud mais ~12 s à froid — inacceptable
    dans la requête HTTP de dépôt. La card apparaît tout de suite, le prompt enrichi arrive juste
    après. Si la tâche de traitement démarre avant, la pipeline l'enrichit au lancement : il n'y a
    pas de fenêtre où un prompt non enrichi partirait.

    Tâche LÉGÈRE et SANS GPU (une passe Ollama, pas une génération) → ne prend pas le verrou de
    ressources et ne bloque pas la file.
    """
    from django.apps import apps as django_apps

    from wama.common.utils.app_metadata import enrich_instance_prompts

    try:
        model = django_apps.get_model(app_label, model_name)
        obj = model.objects.get(pk=pk)
    except Exception as exc:
        logger.debug(f"[prompt_ingest] {app_label}.{model_name}#{pk} introuvable ({exc})")
        return {'enriched': [], 'reason': 'introuvable'}

    # Course avec un lancement immédiat : si le traitement est parti, la pipeline s'en charge —
    # ne pas réécrire le prompt sous ses pieds.
    if getattr(obj, 'status', 'PENDING') not in ('PENDING', '', None):
        return {'enriched': [], 'reason': f"statut {getattr(obj, 'status', '?')}"}

    done = enrich_instance_prompts(app_label, obj, user=getattr(obj, 'user', None))
    return {'enriched': done}


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

