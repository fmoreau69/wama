"""
Tâches Celery transverses (app `common`).
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


#: Clé de cache partagée entre la tâche (écrit l'avancement) et la vue de progression
#: (le lit). Passer par le cache plutôt que par l'AsyncResult permet de retrouver une
#: sauvegarde en cours après un simple F5 — le navigateur n'a plus le task_id.
#: Même motif que `model_manager.tasks.BACKUP_ALL_CACHE_KEY`, clé DISTINCTE : les deux
#: sauvegardes peuvent tourner en même temps sans écraser mutuellement leur avancement.
BACKUP_MEDIA_CACHE_KEY = 'common:backup_media'
BACKUP_MEDIA_TTL = 24 * 3600


@shared_task(bind=True, name='common.backup_media')
def backup_media_task(self, overwrite: bool = False):
    """
    Miroir incrémental des médias utilisateurs vers l'espace distant. Quotidien (beat)
    et à la demande (bouton « Backup Médias »).

    SENS UNIQUE : rien n'est jamais supprimé à distance — le dossier `~Archives` du NAS,
    qui n'existe pas en local, est préservé par construction (voir `media_backup`).

    Planifiée AVANT la purge de rétention de 04:00 : les médias sur le point d'expirer
    sont ainsi archivés avant disparition, ce qui est précisément l'intérêt d'un distant
    cumulatif.
    """
    from wama.common.services.media_backup import backup_all_media
    from wama.common.services.mirror_sync import run_mirror_job

    return run_mirror_job(
        lambda progress_cb: backup_all_media(overwrite=overwrite, progress_cb=progress_cb),
        cache_key=BACKUP_MEDIA_CACHE_KEY,
        task_id=self.request.id,
        label='backup_media',
        ttl=BACKUP_MEDIA_TTL,
    )


@shared_task(name='common.backup_config')
def backup_config_task(keep: int = 10):
    """
    Sauvegarde des secrets d'installation (`.env`) vers le NAS. Quotidienne.

    Pas d'enveloppe `run_mirror_job` ici, et c'est volontaire : il s'agit d'un fichier de
    quelques kilo-octets, sans avancement à afficher — lui coller une barre de progression
    et une clé de cache serait de la cérémonie sans usage.

    Ne fait rien tant que le contenu n'a pas changé (comparaison SHA-256), donc la tâche est
    quasi gratuite les jours où `.env` est stable.
    """
    from wama.common.services.config_backup import backup_config

    result = backup_config(keep=keep)
    if result['errors']:
        logger.warning("[backup_config] %s", result['errors'])
    return result


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


@shared_task(name='common.rafraichir_registre')
def rafraichir_registre(cle: str):
    """Actualise UN registre catalogué, hors du processus web.

    Générique par construction : la tâche ne connaît aucun catalogue, elle exécute celui que la
    clé désigne. Ajouter un catalogue n'ajoute donc pas de tâche — c'est tout l'intérêt du registre
    keyé, et la raison pour laquelle il n'y a pas ici de `sync_models_task` bis.

    ⚠ Ne convient QU'aux registres dont l'état est PARTAGÉ (base, fichier de rapport). Un registre
    en mémoire actualisé ici rechargerait les modules de CE worker, pas ceux des processus qui
    servent les pages — `registries.enregistrer()` refuse d'ailleurs cette combinaison.

    Mesuré le 2026-08-22, et c'est ce qui a motivé la tâche : en synchrone dans gunicorn, `apps`
    bloquait un worker 31,2 s et `modeles` 20,6 s, sur 8 requêtes concurrentes au total.
    """
    from .registries import rafraichir
    res = rafraichir(cle)
    return res.en_dict()


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

