"""
Squelette COMMUN des tâches Celery d'item (brique F5 — marche A2 de la route §10.3).

Extrait de la convention MESURÉE sur les 10 apps (cadrage A0) : le même enchaînement vivait en
10 exemplaires avec dérive (tâches secondaires sans gardes chez anonymizer/reader/transcriber).
L'app ne fournit plus que sa GLU (`process`) ; tout le reste — gardes, progress, chrono,
statuts canoniques, seeding ETA, console, notifications — est ici, UNE fois.

    @shared_task(bind=True)
    def convert_media_task(self, job_id: int):
        run_item_task(self, app_id='converter', model=ConversionJob, item_id=job_id,
                      process=_convert, notify_label='Converter')

Contrat de la glu `process(item, ctx) -> dict | None` :
  - `ctx.progress(pct)`          : progression 0-100 (cache `<app>_progress_<pk>` + champ
                                   `progress` du modèle s'il existe)
  - `ctx.console(msg, level=None)` : ligne console utilisateur (niveau auto si None), best-effort
  - retour : {'fields': {champs modèle à persister au succès},
              'eta':    (clé, taille, unité) pour `record_run` — optionnel,
              'label':  nom lisible du résultat (console ✓ + notification) — optionnel}
  - une exception = FAILURE (message tronqué dans `error_field`, console ✗, notification
    d'échec). Le nettoyage spécifique d'échec (fichiers temporaires…) reste DANS la glu
    (try/finally ou except-reraise) — le squelette ne connaît pas ses artefacts.

Le squelette pose, dans l'ordre de la convention : `close_old_connections`, chargement de
l'item (`select_related('user')`), `refuse_crash_redelivery` (garde anti-boucle-de-crash),
progress 0, `ensure_local_input` (no-op sans `WAMA_INGEST`), chrono, puis au succès
SUCCESS + progress 100 + `processing_seconds` (si le modèle les porte), `record_run` et
`notify_job` en best-effort. Vocabulaire de statuts canonique : SUCCESS / FAILURE.
"""
import logging
import time

from django.core.cache import cache
from django.db import close_old_connections

logger = logging.getLogger(__name__)


def _has_field(model, name: str) -> bool:
    return any(getattr(f, 'name', None) == name for f in model._meta.get_fields())


class TaskContext:
    """Poignées offertes à la glu : progress + console. `progress_fn` permet à une app de
    substituer son écriture de progression (ex. throttle du transcriber) sans réécrire le
    squelette — la spécificité se DÉCLARE, elle ne se code pas dans la brique."""

    def __init__(self, app_id: str, model, item, progress_fn=None):
        self.app_id = app_id
        self._model = model
        self.item = item
        self.user_id = getattr(item, 'user_id', None)
        self._progress_fn = progress_fn

    def progress(self, pct: int) -> None:
        if self._progress_fn is not None:
            self._progress_fn(self.item, pct)
            return
        pct = max(0, min(100, int(pct)))
        cache.set(f"{self.app_id}_progress_{self.item.pk}", pct, timeout=3600)
        if _has_field(self._model, 'progress'):
            self._model.objects.filter(pk=self.item.pk).update(progress=pct)

    def console(self, message: str, level: str = None) -> None:
        try:
            if level is None:
                bas = message.lower()
                if any(w in bas for w in ('error', 'failed', 'erreur', '✗')):
                    level = 'error'
                elif any(w in bas for w in ('warning', 'attention')):
                    level = 'warning'
                else:
                    level = 'info'
            from wama.common.utils.console_utils import push_console_line
            push_console_line(self.user_id, message, level=level, app=self.app_id)
        except Exception:
            pass


def _notify(item, label: str, nom: str, ok: bool, detail: str = None) -> None:
    try:
        from wama.common.utils.notifications import notify_job
        notify_job(getattr(item, 'user', None), label, nom, ok, detail=detail)
    except Exception:
        pass


def run_item_task(task, *, app_id: str, model, item_id: int, process,
                  error_field: str = 'error_message', ingest_derive=None,
                  notify_label: str = None, progress_fn=None):
    """Exécute la glu `process` dans le squelette conventionnel. Voir le contrat en tête de
    module. `task` = la tâche Celery liée (bind=True) — requis par la garde de redélivrance."""
    close_old_connections()
    logger.info(f"=== {app_id} task START | item={item_id} task={task.request.id} ===")
    try:
        item = model.objects.select_related('user').get(pk=item_id)
    except model.DoesNotExist:
        logger.error(f"[{app_id}] item #{item_id} introuvable")
        return

    from wama.common.utils.process_control import refuse_crash_redelivery
    if refuse_crash_redelivery(task, item, error_field=error_field):
        logger.warning(f"[{app_id}] item #{item_id} : reprise après crash refusée — "
                       f"relancer manuellement.")
        return

    ctx = TaskContext(app_id, model, item, progress_fn=progress_fn)
    ctx.progress(0)

    try:
        from wama.common.utils.source_ingest import ensure_local_input
        ensure_local_input(item, console=ctx.console, derive=ingest_derive)
    except Exception as exc:
        logger.warning(f"[{app_id}] ensure_local_input({item_id}) : {exc}")

    t0 = time.time()
    label_app = notify_label or app_id.title()
    try:
        res = process(item, ctx) or {}
        fields = dict(res.get('fields') or {})
        fields['status'] = 'SUCCESS'
        if _has_field(model, 'progress'):
            fields['progress'] = 100
        if _has_field(model, 'processing_seconds'):
            fields['processing_seconds'] = round(time.time() - t0, 1)
        model.objects.filter(pk=item_id).update(**fields)
        ctx.progress(100)
        nom = res.get('label') or getattr(item, 'input_filename', None) or f"#{item_id}"
        ctx.console(f"✓ Terminé : {nom}", level='info')
        logger.info(f"=== {app_id} task DONE | item={item_id} ===")
        eta = res.get('eta')
        if eta:
            try:
                from wama.model_manager.services.eta_estimator import record_run
                cle, taille, unite = eta
                record_run(cle, size=taille, unit=unite,
                           process_seconds=time.time() - t0, load_seconds=None)
            except Exception:
                pass
        _notify(item, label_app, nom, True)
    except Exception as exc:
        msg = str(exc)[:500]
        logger.exception(f"{app_id} task ERROR | item={item_id}: {exc}")
        fields = {'status': 'FAILURE'}
        if _has_field(model, error_field):
            fields[error_field] = msg
        model.objects.filter(pk=item_id).update(**fields)
        ctx.console(f"✗ Erreur : {msg}", level='error')
        _notify(item, label_app, f"#{item_id}", False, detail=msg)
