"""
Celery tasks for Model Manager.

Provides background sync capabilities and periodic tasks.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='model_manager.sync_models')
def sync_models_task(self, clean: bool = False):
    """
    Background task to sync models.
    Can be scheduled via Celery Beat for periodic sync.

    Args:
        clean: If True, mark models not found as unavailable

    Returns:
        Dict with sync results
    """
    from .services.model_sync import get_sync_service

    logger.info("Starting background model sync")

    sync_service = get_sync_service()
    result = sync_service.full_sync(remove_missing=clean)

    logger.info(
        f"Model sync complete: +{result.added}, ~{result.updated}, -{result.removed}"
    )

    return {
        'success': result.success,
        'added': result.added,
        'updated': result.updated,
        'removed': result.removed,
        'errors': result.errors[:10] if result.errors else [],
    }


@shared_task(name='model_manager.sync_ollama')
def sync_ollama_models():
    """
    Periodic task to check Ollama models status.
    Run this less frequently as it calls external service.

    Returns:
        Dict with sync count
    """
    from .models import AIModel, ModelSource, ModelType
    from .services.model_registry import ModelRegistry
    from django.utils import timezone

    logger.info("Checking Ollama models")

    try:
        # Use registry to discover Ollama models
        registry = ModelRegistry()
        registry._models.clear()
        registry._discover_ollama_models()

        ollama_models = {
            k: v for k, v in registry._models.items()
            if k.startswith('ollama:')
        }

        # Sync to database
        synced = 0
        for model_key, model_info in ollama_models.items():
            obj, created = AIModel.objects.update_or_create(
                model_key=model_key,
                defaults={
                    'name': model_info.name,
                    'model_type': ModelType.LLM,
                    'source': ModelSource.OLLAMA,
                    'description': model_info.description or '',
                    'ram_gb': model_info.ram_gb or 0,
                    'is_downloaded': True,
                    'is_available': True,
                    'last_synced_at': timezone.now(),
                    'extra_info': model_info.extra_info or {},
                }
            )
            synced += 1

        logger.info(f"Synced {synced} Ollama models")
        return {'synced': synced}

    except Exception as e:
        logger.error(f"Error syncing Ollama models: {e}")
        return {'error': str(e), 'synced': 0}


#: Clé de cache partagée entre la tâche (écrit l'avancement) et la vue de progression
#: (le lit). Passer par le cache plutôt que par l'AsyncResult permet de retrouver un
#: backup en cours après un simple F5 sur la page — le navigateur n'a plus le task_id.
BACKUP_ALL_CACHE_KEY = 'model_manager:backup_all_models'
BACKUP_ALL_TTL = 24 * 3600


@shared_task(bind=True, name='model_manager.backup_all_models')
def backup_all_models_task(self, overwrite: bool = False):
    """
    Sauvegarde globale AI-models/models/ → espace distant (incrémentale, sens unique).

    Ne supprime JAMAIS rien côté distant : celui-ci est une archive cumulative (il garde
    les formats d'origine que le local a pu retirer après conversion).

    Opération de plusieurs minutes à plusieurs heures selon le delta : d'où la tâche
    Celery. L'avancement est publié dans le cache Django (Redis) sous
    BACKUP_ALL_CACHE_KEY, lu par api_backup_models_progress.
    """
    from wama.common.services.mirror_sync import run_mirror_job

    from .services.remote_backup import get_backup_service

    # Publication de l'avancement, journalisation et gestion d'échec : `run_mirror_job`
    # (brique commune). Cette tâche ne décrit plus que CE qu'elle sauvegarde.
    return run_mirror_job(
        lambda progress_cb: get_backup_service().backup_all_models(
            overwrite=overwrite, progress_cb=progress_cb,
        ),
        cache_key=BACKUP_ALL_CACHE_KEY,
        task_id=self.request.id,
        label='backup_models',
        ttl=BACKUP_ALL_TTL,
    )


@shared_task(name='model_manager.backup_db')
def backup_db_task(keep: int = 10):
    """
    Sauvegarde quotidienne de la base (pg_dump) + copie NAS. Planifiée par Celery beat.

    Pendant PLANIFIÉ du bouton « Backup DB » (`api_backup_db`) et de
    `manage.py backup_db`, qui restent les entrées À LA DEMANDE. Toute la logique
    (dump, copie distante, rotation `keep` des deux côtés, vérification de taille)
    vit dans la commande : on l'APPELLE, on ne la réimplémente pas.

    Motif (2026-08-10) : la brique existait depuis le 27/07 mais n'était câblée à
    AUCUN ordonnanceur — ni cron, ni systemd, ni beat, ni tâche Windows. Résultat
    mesuré : un seul dump, celui du 29/07, alors que l'hôte a subi 7 coupures
    d'alimentation entre-temps.

    Queue `default` : pg_dump est CPU/IO pur, jamais de GPU — la règle « pas de job
    GPU nocturne » (crashs hôte) reste respectée.
    """
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    out = StringIO()
    try:
        call_command('backup_db', keep=keep, stdout=out, stderr=out)
    except CommandError as exc:
        # NAS injoignable n'arrive PAS ici : la commande dégrade proprement (dump
        # local conservé, avertissement). Un CommandError = pg_dump absent ou en
        # échec, donc aucune sauvegarde du tout → doit remonter en échec Celery.
        logger.error("[backup_db] échec : %s", exc)
        raise

    report = out.getvalue().strip()
    logger.info("[backup_db] %s", report.replace("\n", " | "))
    return report


#: Avancement d'une installation de candidat de prospection — clé PAR modèle (deux
#: installations peuvent coexister), lue par `api_prospect_install_progress`. Même motif
#: que BACKUP_ALL_CACHE_KEY : le cache survit au F5 (le navigateur perd le task_id).
INSTALL_CACHE_PREFIX = 'model_manager:prospect_install:'
INSTALL_TTL = 6 * 3600

#: Avancement de la passe d'évaluation LLM des candidats (confiance).
ASSESS_CACHE_KEY = 'model_manager:assess_proposed'
ASSESS_TTL = 6 * 3600


@shared_task(bind=True, name='model_manager.install_proposed')
def install_proposed_task(self, model_key: str):
    """
    Installe un candidat de prospection Ollama EN TÂCHE DE FOND — remplace le corps
    synchrone de `api_prospect_install` (2026-08-18). Motif : un pull de 18 Go dans la
    requête dépassait le timeout du proxy Apache → le navigateur recevait une page HTML
    d'erreur pendant que le worker continuait en aveugle, et un re-clic ouvrait une
    requête CONCURRENTE au lieu de rejoindre celle en cours.

    La garde d'espace disque reste dans la VUE (réponse immédiate 507/force) ; ici on
    n'exécute que la séquence longue (`install_candidate`), en publiant l'avancement
    du pull (avec %) dans le cache Redis.
    """
    from wama.common.utils.task_progress import publier_progression

    from .models import AIModel
    from .services.model_installer import install_candidate

    cache_key = INSTALL_CACHE_PREFIX + model_key

    def publier(state: str, payload: dict):
        publier_progression(cache_key, self.request.id, state, payload, INSTALL_TTL)

    cand = AIModel.objects.filter(model_key=model_key, is_proposed=True).first()
    if not cand:
        publier('FAILURE', {'error': 'Candidat introuvable (déjà installé ou rejeté ?)'})
        return {'ok': False, 'error': 'Candidat introuvable'}

    publier('RUNNING', {'status': 'démarrage…', 'name': cand.name})
    try:
        res = install_candidate(
            cand, progress=lambda s: publier('RUNNING', {'status': s, 'name': cand.name}))
    except Exception as exc:
        logger.exception("[install_proposed] échec inattendu pour %s", model_key)
        publier('FAILURE', {'error': f"{type(exc).__name__}: {exc}", 'name': cand.name})
        raise
    publier('SUCCESS' if res.get('ok') else 'FAILURE', dict(res, name=cand.name))
    logger.info("[install_proposed] %s → %s", model_key,
                'installé' if res.get('ok') else res.get('error'))
    return res


@shared_task(bind=True, name='model_manager.install_catalog')
def install_catalog_task(self, model_key: str):
    """
    Installe un modèle DU CATALOGUE (non téléchargé, hf_id + install_dir déclarés) — le
    pendant de `install_proposed_task` pour les modèles d'app (2026-08-27, cas
    musicgen-melody). Spec dérivé côté serveur (`spec_for_catalog_row`), même cache de
    progression que les candidats → l'UI réutilise le même suivi.
    """
    from wama.common.utils.task_progress import publier_progression

    from .models import AIModel
    from .services.model_installer import install_from_spec, spec_for_catalog_row

    cache_key = INSTALL_CACHE_PREFIX + model_key

    def publier(state: str, payload: dict):
        publier_progression(cache_key, self.request.id, state, payload, INSTALL_TTL)

    model = AIModel.objects.filter(model_key=model_key, is_proposed=False).first()
    if model is None:
        publier('FAILURE', {'error': 'Modèle introuvable au catalogue'})
        return {'ok': False, 'error': 'Modèle introuvable'}
    spec = spec_for_catalog_row(model)
    if spec is None:
        publier('FAILURE', {'error': "Ce modèle ne déclare pas d'emplacement d'installation "
                                     "(hf_id/install_dir) — installation au premier usage "
                                     "seulement.", 'name': model.name})
        return {'ok': False, 'error': 'spec non dérivable'}

    publier('RUNNING', {'status': f"téléchargement {spec['ref']}…", 'name': model.name})
    try:
        res = install_from_spec(spec)
    except Exception as exc:
        logger.exception("[install_catalog] échec inattendu pour %s", model_key)
        publier('FAILURE', {'error': f"{type(exc).__name__}: {exc}", 'name': model.name})
        raise
    publier('SUCCESS' if res.get('ok') else 'FAILURE', dict(
        {k: v for k, v in res.items() if k != 'provenance'}, name=model.name))
    logger.info("[install_catalog] %s → %s", model_key,
                'installé' if res.get('ok') else res.get('error'))
    return {k: v for k, v in res.items() if k != 'provenance'}


#: Avancement de la mesure de PERFORMANCE (bancs tiers) — pendant de ASSESS_CACHE_KEY.
BENCH_CACHE_KEY = 'model_manager:sync_benchmarks'
BENCH_TTL = 6 * 3600


@shared_task(bind=True, name='model_manager.sync_benchmarks')
def sync_benchmarks_task(self):
    """
    Mesure de PERFORMANCE du catalogue par bancs TIERS (Artificial Analysis + Arena).

    ⚠ À NE PAS CONFONDRE avec `assess_proposed_task` — c'est la confusion qui a coûté à
    Fabien des semaines de blocage (2026-08-31) : le seul bouton de l'écran, « Évaluer la
    confiance », déclenche le JURY LLM, qui charge un modèle sur l'Ollama hôte et fait
    tomber la machine (montée VRAM, cf. `INFRA_WSL_VS_WINDOWS`). La mesure de performance,
    elle, n'avait **aucun déclencheur d'écran** — d'où « je n'ai jamais pu compléter une
    recherche benchmark ». Or elle est **purement RÉSEAU** : API Artificial Analysis + jeu
    Arena sur HuggingFace, aucun GPU, aucun modèle chargé. D'où la file `default`.

    Les trois indicateurs restent DISTINCTS (cf. `WAMA_APP_GENERATION_ROUTE §F4b`) :
    confiance de la PROPOSITION (jury), complexité d'INTÉGRATION, performance TIERCE (ici).
    """
    from wama.common.utils.task_progress import publier_progression

    from .services.benchmark_sync import SourceIndisponible, synchroniser

    def publier(state: str, payload: dict):
        publier_progression(BENCH_CACHE_KEY, self.request.id, state, payload, BENCH_TTL)

    publier('RUNNING', {'status': 'interrogation des bancs tiers…'})
    try:
        r = synchroniser(dry_run=False)
    except SourceIndisponible as exc:
        # Pas un échec : aucune source joignable (clé absente / réseau) — même sémantique
        # que le code retour 3 de la commande, qui vaut SKIP côté nocturne.
        publier('SUCCESS', {'status': 'aucune source joignable', 'skipped': True,
                            'raison': str(exc)})
        return {'ok': True, 'skipped': True, 'raison': str(exc)}
    except Exception as exc:
        logger.exception("[sync_benchmarks] échec")
        publier('FAILURE', {'error': f"{type(exc).__name__}: {exc}"})
        raise

    resume = {'ok': True, 'apparies': len(r['apparies']),
              'non_apparies': len(r['non_apparies']),
              'sans_identite': len(r['sans_identite']),
              'inversions': len(r['inversions']),
              'indisponibles': sorted(r['indisponibles']),
              'sans_categorie': r['sans_categorie']}
    publier('SUCCESS', resume)
    logger.info("[sync_benchmarks] %s", resume)
    return resume


@shared_task(bind=True, name='model_manager.assess_proposed')
def assess_proposed_task(self, max_assess: int = 10, chainer: bool = True):
    """
    Passe d'évaluation LLM des candidats de prospection `new` (confiance) — déclenchée
    sur ACTION EXPLICITE uniquement (bouton « Évaluer la confiance » / CLI
    `assess_models --proposed`), JAMAIS auto depuis le 2026-08-19 (crash hôte, pattern
    « Ollama hôte enchaîné »). Gouvernée : routée file `gpu` --pool=solo palier `basse`
    (settings.CELERY_TASK_ROUTES) → sérialisée derrière les traitements utilisateur ;
    la passe elle-même passe par le gouverneur (garde `effective_free_gb` + réservation,
    cf. `assess_proposed`). Incrémentale : `max_assess` candidats par passe.

    CHAÎNAGE AUTOMATIQUE (2026-08-19, demande Fabien) : tant qu'il reste des candidats sans
    confiance, la passe suivante est RÉ-ENFILÉE. Un seul clic suffit donc à traiter la file
    entière, sans revenir aux 6 clics qu'imposait le lot de 10.

    ⚠ POURQUOI RÉ-ENFILER PLUTÔT QUE BOUCLER DANS LA TÂCHE. Fabien a raison sur la VRAM :
    la passe est séquentielle, un seul modèle chargé, boucler n'en consommerait pas plus.
    Le vrai enjeu est la FILE : le worker `gpu` est en `--pool=solo`, donc une tâche qui
    tourne 30 min immobilise le seul exécutant GPU et un traitement utilisateur (palier
    supérieur) attend la fin. En ré-enfilant, le worker se libère entre deux lots : la file
    reprend la main, la garde de ressources est réévaluée, et un échec ne perd qu'un lot.

    Arrêts du chaînage — jamais de boucle folle :
      • plus de candidat sans confiance (`remaining == 0`) ;
      • aucun verdict obtenu (`assessed == 0`, agents injoignables) — sinon on ré-enfilerait
        indéfiniment une passe qui n'avance pas ;
      • passe REPORTÉE par le gouverneur (GPU occupé) : on s'arrête et on le dit.
    """
    from wama.common.utils.task_progress import publier_progression

    from .services.prospect_agents import assess_proposed

    def publier(p, state='RUNNING'):
        publier_progression(ASSESS_CACHE_KEY, self.request.id, state, p, ASSESS_TTL)

    try:
        res = assess_proposed(max_assess=max_assess, progress=publier)
    except Exception as exc:
        logger.exception("[assess_proposed] échec de la passe")
        publier({'error': str(exc)}, state='FAILURE')
        raise

    restants = res.get('remaining') or 0
    suite = bool(chainer and restants and res.get('assessed') and not res.get('deferred'))
    if suite:
        # L'état RESTE `RUNNING` : l'UI ne doit pas annoncer « terminé » alors que le lot
        # suivant est déjà en file (le poller s'arrêterait au premier lot).
        publier(dict(res, chained=True), state='RUNNING')
        assess_proposed_task.apply_async(
            kwargs={'max_assess': max_assess, 'chainer': True}, countdown=5)
        logger.info("[assess_proposed] lot terminé (%s évalué(s)), %s restant(s) — "
                    "passe suivante enfilée", res.get('assessed'), restants)
    else:
        publier(res, state='SUCCESS')
    return res


@shared_task(name='model_manager.update_loaded_status')
def update_loaded_status_task(model_key: str, is_loaded: bool):
    """
    Update the loaded status of a model.
    Called when models are loaded/unloaded.

    Args:
        model_key: The model identifier
        is_loaded: Whether the model is loaded

    Returns:
        Dict with success status
    """
    from .services.model_sync import get_sync_service

    sync_service = get_sync_service()
    success = sync_service.update_loaded_status(model_key, is_loaded)

    return {'success': success, 'model_key': model_key, 'is_loaded': is_loaded}
