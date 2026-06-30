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
"""
from __future__ import annotations


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


def reconcile_if_stuck(instance, *, status_field: str = "status", task_field: str = "task_id",
                       running_value: str = "RUNNING", to_status: str = "FAILURE",
                       error_field: str | None = None,
                       error_message: str = "Tâche interrompue") -> bool:
    """
    PHASE 2 (non activée par défaut). Si l'item est RUNNING mais que sa tâche Celery est dans un état
    terminal, le bascule en échec (relançable). NE traite PAS le cas PENDING (faux positifs sur la file).
    À n'appeler que derrière un délai de grâce. Retourne True si une réconciliation a eu lieu.
    """
    if getattr(instance, status_field, None) != running_value:
        return False
    if not is_task_dead(getattr(instance, task_field, "") or ""):
        return False
    setattr(instance, status_field, to_status)
    fields = [status_field]
    if error_field:
        setattr(instance, error_field, error_message)
        fields.append(error_field)
    try:
        instance.save(update_fields=fields)
    except Exception:
        instance.save()
    return True
