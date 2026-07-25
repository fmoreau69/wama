"""
Contrôle de process COMMUN — brique transversale (cf. memory project_process_button_lifecycle).

Fournit l'action **Stop** (annulation d'un traitement en cours) de façon uniforme à toutes les apps,
support du bouton de cycle ▶/⏹/↻ : un item RUNNING peut être stoppé → il revient dans un état
**relançable** (le bouton repasse en ↻ Relancer).

`stop_instance()` révoque la tâche Celery et remet l'item au propre. C'est aussi le socle du « hard
reset » (débloquer un item coincé) : stopper un RUNNING fantôme le ramène à un état relançable.

Détection AUTOMATIQUE des items bloqués (heartbeat/timeout → bascule en échec) = Phase 2, volontairement
PAS ici : sans champ d'horodatage/heartbeat fiable, conclure « bloqué » risque de faire échouer à tort
des tâches légitimement EN FILE (Celery PENDING = en attente, pas mort). À concevoir avec un délai de
grâce + progression observée. Voir `reconcile_if_stuck` (signature posée, NON activée par défaut).

RÈGLE DE CONCEPTION de la réconciliation (`reconcile_orphaned_running`) : ne basculer un item en échec
que sur PREUVE POSITIVE de mort. L'absence d'information n'est pas une preuve — un worker qui ne répond
pas est le plus souvent un worker OCCUPÉ par la tâche qu'on s'apprête à déclarer morte (pool `solo`).
"""
from __future__ import annotations


def begin_processing(model, pk, *, user=None, reset=None,
                     status_field: str = "status", task_field: str = "task_id",
                     running_value: str = "RUNNING"):
    """
    Démarrage ANTI-RACE d'un item (pattern obligatoire CLAUDE.md — généralise describer
    ``start()``, seule implémentation conforme à l'audit 2026-07-06) : transaction +
    ``select_for_update`` (refuse le double-clic Start), révocation de l'éventuelle tâche
    Celery encore en file, resets d'app, passage à RUNNING.

    L'appelant complète le pattern APRÈS la transaction (lancement + persistance task_id) :

        obj, err = begin_processing(Transcript, pk, user=user,
                                    reset={'progress': 0, 'error_message': ''})
        if err:
            return JsonResponse({'error': err}, status=404 if err == 'not_found' else 400)
        task = my_task.delay(obj.id)
        obj.task_id = task.id
        obj.save(update_fields=[task_field])

    Args:
        user  : si fourni, ``get(pk=pk, user=user)`` (isolation par utilisateur).
        reset : dict champ→valeur OU callable(instance) — remise à zéro spécifique d'app,
                appliquée SOUS le verrou.

    Returns:
        (instance, None) si OK ; (None, 'not_found') ; (None, 'already_running').
    """
    from django.db import transaction
    with transaction.atomic():
        try:
            qs = model.objects.select_for_update()
            instance = qs.get(pk=pk, user=user) if user is not None else qs.get(pk=pk)
        except model.DoesNotExist:
            return None, 'not_found'
        if getattr(instance, status_field, None) == running_value:
            return None, 'already_running'
        old_task = getattr(instance, task_field, "") or ""
        if old_task:
            try:
                from celery import current_app
                # terminate=False : on empêche seulement une tâche EN FILE de démarrer après coup.
                current_app.control.revoke(old_task, terminate=False)
            except Exception:
                pass
        setattr(instance, status_field, running_value)
        setattr(instance, task_field, "")
        if callable(reset):
            reset(instance)
        elif reset:
            for field, value in reset.items():
                setattr(instance, field, value)
        instance.save()
    return instance, None


def stop_instance(instance, *, status_field: str = "status", task_field: str = "task_id",
                  to_status: str = "FAILURE", error_field: str | None = None,
                  error_message: str = "Interrompu par l'utilisateur") -> str:
    """
    Stoppe le traitement d'un item : révoque la tâche Celery (SIGTERM) et le remet dans un état
    relançable. Idempotent (sans tâche → ne fait que normaliser le statut). Retourne le nouveau statut.

    Args:
        instance      : l'objet modèle (Transcript, Conversion, …).
        status_field  : nom du champ statut (défaut 'status').
        task_field    : nom du champ task_id Celery (défaut 'task_id').
        to_status     : statut après stop (défaut 'FAILURE' → card rouge + bouton ↻ Relancer).
        error_field   : champ message d'erreur optionnel à renseigner (pour distinguer « interrompu »).
        error_message : message si error_field fourni.
    """
    task_id = getattr(instance, task_field, "") or ""
    if task_id:
        try:
            from celery import current_app
            # terminate=True : tue le worker en cours d'exécution de CETTE tâche (interruption immédiate).
            current_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        except Exception:
            pass  # broker indisponible / tâche déjà finie : on normalise quand même le statut en base.

    setattr(instance, status_field, to_status)
    setattr(instance, task_field, "")
    fields = [status_field, task_field]
    if error_field:
        setattr(instance, error_field, error_message)
        fields.append(error_field)
    try:
        instance.save(update_fields=fields)
    except Exception:
        instance.save()  # repli si update_fields incompatible
    return to_status


def is_task_dead(task_id: str) -> bool:
    """
    True si la tâche Celery est dans un état terminal (finie/échouée/révoquée). NE classe PAS PENDING
    comme mort (PENDING = en file OU inconnu — ambigu). À utiliser avec un délai de grâce côté appelant.
    """
    if not task_id:
        return True
    try:
        from celery import current_app
        from celery.result import AsyncResult
        state = AsyncResult(task_id, app=current_app).state
    except Exception:
        return False  # incertitude → ne rien conclure
    return state in {"SUCCESS", "FAILURE", "REVOKED"}


def _mark_reconciled(instance, status_field, task_field, to_status, error_field, error_message):
    """Bascule un item vers `to_status` (relançable) + message optionnel. Save minimal."""
    setattr(instance, status_field, to_status)
    fields = [status_field]
    if error_field:
        setattr(instance, error_field, error_message)
        fields.append(error_field)
    try:
        instance.save(update_fields=fields)
    except Exception:
        instance.save()


def reconcile_if_stuck(instance, *, status_field: str = "status", task_field: str = "task_id",
                       running_value: str = "RUNNING", to_status: str = "FAILURE",
                       error_field: str | None = None,
                       error_message: str = "Tâche interrompue") -> bool:
    """
    Si l'item est RUNNING mais que sa tâche Celery est dans un état TERMINAL
    (SUCCESS/FAILURE/REVOKED), le bascule en échec (relançable). NE traite PAS le cas
    PENDING (faux positifs sur la file). Retourne True si une réconciliation a eu lieu.

    Ne couvre PAS le crash worker (la tâche reste STARTED, jamais terminale) :
    pour ça, voir `reconcile_orphaned_running` (signal = absente des workers actifs).
    """
    if getattr(instance, status_field, None) != running_value:
        return False
    if not is_task_dead(getattr(instance, task_field, "") or ""):
        return False
    _mark_reconciled(instance, status_field, task_field, to_status, error_field, error_message)
    return True


def collect_worker_snapshot(timeout: float = 2.0):
    """
    Photo de la flotte Celery en UNE interrogation :

        {'workers':  {noms des workers AYANT RÉPONDU},
         'task_ids': {task_id actifs + réservés SUR CES workers}}

    Renvoie None si aucun worker ne répond (broker injoignable / flotte à l'arrêt) :
    incertitude totale → l'appelant NE réconcilie rien.

    ⚠ La photo est PARTIELLE par nature : `inspect()` est un broadcast, seuls les workers
    disponibles répondent dans le délai imparti. Un worker `--pool=solo` (chez nous : le
    worker `gpu`) exécute la tâche DANS son thread principal et ne peut donc PAS répondre
    tant qu'elle tourne — c'est-à-dire exactement quand sa tâche est bien vivante.

    Conséquence, à ne jamais oublier : **`task_ids` ne prouve JAMAIS une absence.** Seul
    `workers` dit de qui la photo est fiable. Voir `is_task_orphaned`.
    """
    try:
        from celery import current_app
        insp = current_app.control.inspect(timeout=timeout)
        active = insp.active()
        reserved = insp.reserved()
    except Exception:
        return None
    if active is None and reserved is None:
        return None
    workers, ids = set(), set()
    for group in (active or {}, reserved or {}):
        for worker, tasks in group.items():
            workers.add(worker)
            for t in (tasks or []):
                tid = t.get("id") if isinstance(t, dict) else None
                if tid:
                    ids.add(tid)
    return {'workers': workers, 'task_ids': ids}


def task_owner(task_id: str) -> str | None:
    """
    Nom du worker qui exécute la tâche (ex. ``'gpu@fbro-20-026'``), ou None si inconnu.

    Celery écrit ``{'pid', 'hostname'}`` dans le meta de l'état ``STARTED`` (nécessite
    ``CELERY_TASK_TRACK_STARTED = True``, cf. settings). Les noms de nœud sont STABLES
    entre redémarrages (``--hostname=gpu@%h``), ce qui permet de savoir si le worker
    propriétaire a répondu à `collect_worker_snapshot`.
    """
    try:
        from celery import current_app
        from celery.result import AsyncResult
        meta = AsyncResult(task_id, app=current_app).result
    except Exception:
        return None
    return meta.get('hostname') if isinstance(meta, dict) else None


def is_task_orphaned(task_id: str, snapshot) -> bool:
    """
    True SEULEMENT si l'on a une PREUVE POSITIVE que la tâche est morte : elle a démarré
    (`STARTED`), son worker propriétaire A RÉPONDU, et il ne l'a ni active ni réservée
    → il a redémarré sans elle (crash worker / machine).

    Ne conclut RIEN (False) dans tous les autres cas — notamment quand le propriétaire
    n'a pas répondu (worker solo occupé PAR cette tâche, ou pas encore relancé après un
    crash). Asymétrie VOULUE : laisser une card zombie en RUNNING coûte un rechargement,
    tuer une transcription de 2 h vivante coûte 2 h.

    Historique — régression du 2026-07-25 : la version initiale concluait « orpheline »
    dès que la tâche était absente de la photo, sans vérifier QUI avait répondu. Le worker
    `gpu` (solo) ne répondant pas pendant qu'il travaille, toute tâche longue était
    déclarée morte ~5 s après son lancement, alors qu'elle tournait (item basculé en
    FAILURE, polling arrêté côté front, card rouge figée).
    """
    if not task_id or not snapshot:
        return False
    if task_id in snapshot.get('task_ids', ()):
        return False
    try:
        from celery import current_app
        from celery.result import AsyncResult
        state = AsyncResult(task_id, app=current_app).state
    except Exception:
        return False
    if state != "STARTED":
        return False           # PENDING = en file légitime ; terminal = is_task_dead
    owner = task_owner(task_id)
    # Propriétaire inconnu ou muet → aucune preuve de mort → on ne touche à rien.
    return bool(owner) and owner in snapshot.get('workers', ())


def reconcile_orphaned_running(instances, *, snapshot=None,
                               status_field: str = "status", task_field: str = "task_id",
                               running_value: str = "RUNNING", to_status: str = "FAILURE",
                               error_field: str | None = None,
                               error_message: str = "Traitement interrompu (worker arrêté)") -> int:
    """
    Réconcilie une liste d'items RUNNING dont la tâche Celery est TERMINÉE (is_task_dead)
    OU ORPHELINE (worker propriétaire relancé sans elle). Chaque item concerné bascule en
    échec RELANÇABLE. Renvoie le nombre d'items réconciliés.

    Un SEUL `inspect()` par appel (via `snapshot`). Ne touche à rien si aucun worker ne
    répond, ni si la preuve de mort n'est pas positive (cf. `is_task_orphaned`). Ignore
    les items sans task_id (peut-être tout juste démarrés — task_id pas encore persisté,
    cf. begin_processing).
    """
    running = [i for i in instances if getattr(i, status_field, None) == running_value]
    if not running:
        return 0
    if snapshot is None:
        snapshot = collect_worker_snapshot()
    if snapshot is None:
        return 0
    n = 0
    for inst in running:
        tid = getattr(inst, task_field, "") or ""
        if not tid:
            continue
        if is_task_dead(tid) or is_task_orphaned(tid, snapshot):
            _mark_reconciled(inst, status_field, task_field, to_status, error_field, error_message)
            n += 1
    return n
