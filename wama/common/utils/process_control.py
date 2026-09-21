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
    Démarrage ANTI-RACE d'un item (pattern obligatoire AGENTS.md — généralise describer
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


#: Au-delà, on ne lit pas une file du broker en entier : incertitude → aucune conclusion.
_BROKER_SCAN_MAX = 10000


def _broker_channel():
    """Canal kombu du broker Redis (client + `sep` + clé `unacked`), ou None."""
    from celery import current_app
    conn = current_app.connection_for_read()
    try:
        ch = conn.default_channel
        return conn, ch
    except Exception:
        conn.release()
        raise


def _known_worker_nodes(client, sep: str) -> set | None:
    """Noms de nœud des workers ENREGISTRÉS auprès du broker (liaisons `pidbox`).

    Chaque worker lie sa file de contrôle `<nœud>.celery.pidbox` : la liste survit à un crash
    et les noms sont stables (`--hostname=gpu@%h`). Une liaison écrite sous un AUTRE séparateur
    (configuration antérieure à `sep=':'`) est ignorée — elle ne désigne aucun worker actuel.
    Une liaison périmée au séparateur courant (hôte renommé) empêche toute conclusion : c'est le
    sens sûr.
    """
    members = client.smembers('_kombu.binding.celery.pidbox')
    nodes = set()
    for raw in members or ():
        value = raw.decode() if isinstance(raw, bytes) else str(raw)
        parts = value.split(sep)
        if len(parts) == 3 and parts[2].endswith('.celery.pidbox'):
            nodes.add(parts[2][:-len('.celery.pidbox')])
    return nodes or None


def _broker_holds(task_id: str):
    """Le broker détient-il un message de cette tâche ? True / False, ou None si on ne sait pas.

    Parcourt les files (listes Redis, paliers de priorité compris : `gpu`, `gpu:3`…) et la
    table `unacked` (messages délivrés à un worker, réservés ou à échéance différée).
    """
    try:
        conn, ch = _broker_channel()
    except Exception:
        return None
    try:
        client = ch.client
        needle = task_id.encode()
        for key in client.scan_iter(_type='list', count=500):
            if client.llen(key) > _BROKER_SCAN_MAX:
                return None
            if any(needle in m for m in client.lrange(key, 0, -1)):
                return True
        unacked_key = getattr(ch, 'unacked_key', 'unacked')
        for _field, m in client.hscan_iter(unacked_key, count=500):
            if needle in m:
                return True
        return False
    except Exception:
        return None
    finally:
        conn.release()


def is_task_lost(task_id: str, snapshot) -> bool:
    """
    True SEULEMENT si la tâche n'est PLUS NULLE PART : état Celery `PENDING`, aucun message
    dans le broker (files + `unacked`), et TOUS les workers enregistrés ont répondu à la photo
    sans l'avoir active ni réservée.

    Le cas couvert — trou consigné le 2026-08-28, vécu le 2026-09-21 (transcription #525) :
    après un crash de l'HÔTE ENTIER, Redis repart de son dernier instantané et la méta `STARTED`
    est perdue → l'état retombe `PENDING`, et `is_task_orphaned` (qui exige `STARTED`) ne peut
    structurellement plus rien prouver. La card restait RUNNING à vie.

    Pourquoi chaque condition est nécessaire :
      - `PENDING` + absent du broker SEUL serait le signal inversé du 2026-07-25 : un worker
        `--pool=solo` occupé ne répond pas, et une tâche qu'il exécute a été acquittée (donc
        hors broker). D'où l'exigence que TOUS les nœuds connus aient répondu : un worker muet
        est le plus souvent un worker occupé — par cette tâche peut-être.
      - une tâche en file (non préchargée) est `PENDING` aussi : elle est dans une liste du
        broker, on la voit.
      - l'état est relu APRÈS le parcours du broker : une tâche prise entre-temps par un worker
        est passée `STARTED` (`CELERY_TASK_TRACK_STARTED`).
    """
    if not task_id or not snapshot:
        return False
    if task_id in snapshot.get('task_ids', ()):
        return False
    try:
        from celery import current_app
        from celery.result import AsyncResult
        if AsyncResult(task_id, app=current_app).state != "PENDING":
            return False
        conn, ch = _broker_channel()
        try:
            nodes = _known_worker_nodes(ch.client, getattr(ch, 'sep', ':'))
        finally:
            conn.release()
    except Exception:
        return False
    if not nodes or not nodes <= set(snapshot.get('workers', ())):
        return False           # un nœud muet → aucune preuve
    if _broker_holds(task_id) is not False:
        return False           # présent, ou broker illisible
    try:
        return AsyncResult(task_id, app=current_app).state == "PENDING"
    except Exception:
        return False


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
        if not (is_task_dead(tid) or is_task_orphaned(tid, snapshot)
                or is_task_lost(tid, snapshot)):
            continue
        # ⚠⚠ UNE TÂCHE QUI A RÉUSSI N'EST PAS UNE TÂCHE MORTE — défaut RÉEL, trouvé le
        # 2026-09-07 par le scénario nocturne `<app>.batch_processing`.
        #
        # `is_task_dead()` répond True pour l'état Celery `SUCCESS` (son nom dit « terminal »,
        # pas « morte » — et sa docstring PRÉVIENT : « à utiliser avec un délai de grâce côté
        # appelant »). Ici il n'y avait aucun délai. Conséquence mesurée sur le converter : un
        # lot de deux conversions de 0,3 s partait en « Traitement interrompu (worker arrêté) »
        # alors que le journal du worker disait « ✓ Terminé » pour les DEUX. L'utilisateur
        # voyait deux cards ROUGES et des fichiers parfaitement convertis à côté.
        #
        # La course : la tâche publie son état `SUCCESS` au broker et écrit le statut de son
        # item — deux écritures, deux instants. Un rechargement de page tombé entre les deux
        # (et « Démarrer tout » RECHARGE, par contrat) lisait l'item encore RUNNING et la tâche
        # déjà terminée, puis ÉCRASAIT le succès en échec.
        #
        # Deux gardes, et aucune n'est de trop :
        #   1. l'état `SUCCESS` ne justifie JAMAIS un échec — le travail a été fait ; seuls
        #      `FAILURE`/`REVOKED` (is_task_dead) et l'orphelinat prouvé le justifient ;
        #   2. on RELIT la ligne avant d'écrire : si le statut a bougé depuis la photo, la
        #      tâche a fini son travail entre-temps et nous n'avons rien à dire.
        if _tache_reussie(tid):
            continue
        if not _statut_inchange(inst, status_field, running_value):
            continue
        _mark_reconciled(inst, status_field, task_field, to_status, error_field, error_message)
        n += 1
    return n


def _tache_reussie(task_id: str) -> bool:
    """La tâche s'est-elle terminée en SUCCÈS ? (≠ « morte » — cf. `reconcile_orphaned_running`)"""
    try:
        from celery import current_app
        from celery.result import AsyncResult
        return AsyncResult(task_id, app=current_app).state == "SUCCESS"
    except Exception:
        return False        # incertitude → on ne protège pas, les autres gardes jouent


def _statut_inchange(instance, status_field: str, running_value: str) -> bool:
    """Relit la ligne : le statut est-il TOUJOURS celui de la photo ?

    Ferme la fenêtre entre la lecture et l'écriture — c'est elle qui laissait un `FAILURE`
    écraser un `SUCCESS` écrit une fraction de seconde plus tôt par la tâche elle-même.
    """
    try:
        frais = type(instance).objects.filter(pk=instance.pk).values_list(
            status_field, flat=True).first()
    except Exception:
        return True         # pas de relecture possible → comportement d'avant
    return frais == running_value


def refuse_crash_redelivery(task, instance, *,
                            status_field: str = "status", task_field: str = "task_id",
                            to_status: str = "FAILURE", error_field: str | None = None,
                            error_message: str = ("Interrompu par un arrêt brutal du worker "
                                                  "(crash machine) — relancer manuellement.")) -> bool:
    """
    Garde ANTI-BOUCLE-DE-CRASH pour les tâches lourdes (GPU) — à appeler EN TÊTE
    d'une tâche ``bind=True``.

    Si le message broker de l'exécution courante est marqué ``redelivered`` — worker
    mort SANS acquitter (freeze machine, kill -9) —, ne PAS ré-exécuter aveuglément :
    c'est précisément cette exécution qui a tué le worker. Sans cette garde, Redis
    re-livre le message à CHAQUE démarrage du worker et la machine re-gèle en boucle
    (vécu 23-25/07/2026 : diarisation pyannote du transcriber).

    Les messages en file jamais préchargés ne portent pas le flag ``redelivered`` :
    un batch en attente survit normalement à un restart. Seul cas de faux positif :
    message préchargé puis requeué par un arrêt propre (rare avec
    ``--prefetch-multiplier=1``) → l'item passe en échec relançable, pas de perte.

    Renvoie True si l'exécution doit être abandonnée (l'item est déjà basculé en
    échec relançable) ; l'appelant fait simplement ``return``.
    """
    try:
        info = getattr(getattr(task, "request", None), "delivery_info", None) or {}
        redelivered = bool(info.get("redelivered"))
    except Exception:
        redelivered = False
    if not redelivered:
        return False
    _mark_reconciled(instance, status_field, task_field, to_status, error_field, error_message)
    return True
