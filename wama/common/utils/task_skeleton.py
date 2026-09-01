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
  - `ctx.progress(pct, msg=None)` : progression 0-100 (défaut : cache `<app>_progress_<pk>`
                                    entier + champ `progress` du modèle s'il existe ; `msg`
                                    ignoré). Une app dont le front attend un AUTRE format
                                    (ex. reader : dict {'pct','msg'}) DÉCLARE
                                    `progress_fn(item, pct, msg)` — la brique ne code aucun cas.
  - `ctx.console(msg, level=None)` : ligne console utilisateur (niveau auto si None), best-effort
  - retour : {'fields': {champs modèle à persister au succès},
              'eta':    (clé, taille, unité) pour `record_run` — optionnel,
              'label':  nom lisible du résultat (console ✓ + notification) — optionnel,
              'console_success': ligne ✓ personnalisée (remplace « ✓ Terminé : <label> ») — optionnel}
    La glu peut retourner À TOUT MOMENT (ex. chemin court PDF natif du reader) : le retour
    déclenche le flux de succès standard.
  - une exception = FAILURE (message tronqué dans `error_field`, console ✗, notification
    d'échec). Le nettoyage spécifique d'échec (fichiers temporaires…) reste DANS la glu
    (try/finally ou except-reraise) — le squelette ne connaît pas ses artefacts.
  Hors contrat (volontaire) : les tâches d'ENRICHISSEMENT à la demande (reader `analyze`,
  transcriber `enrich`) — elles ne pilotent PAS le cycle de vie de l'item (ni statut ni
  progress) ; les faire passer ici corromprait l'état (FAILURE sur un item déjà SUCCESS).

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

    def progress(self, pct: int, msg: str = None) -> None:
        if self._progress_fn is not None:
            self._progress_fn(self.item, pct, msg or '')
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


def _signal(item, app_id: str, signal: str, model_keys=None, detail=None) -> None:
    """Signal d'exécution, best-effort — comme `_notify`, il ne doit jamais faire échouer une
    tâche qui a par ailleurs abouti."""
    try:
        from wama.common.services.run_outcome import record
        record(app_id, item, signal, model_keys=model_keys, detail=detail)
    except Exception:
        pass


def _notify(item, label: str, nom: str, ok: bool, detail: str = None) -> None:
    try:
        from wama.common.utils.notifications import notify_job
        notify_job(getattr(item, 'user', None), label, nom, ok, detail=detail)
    except Exception:
        pass


def _item_label(item, item_id: int) -> str:
    """Nom lisible de l'item pour console/notification — conventions de nommage du spine
    (converter: input_filename, reader: filename, composer/synthesizer: title), repli #id."""
    for attr in ('input_filename', 'filename', 'title', 'name'):
        v = getattr(item, attr, None)
        if v:
            return str(v)
    return f"#{item_id}"


#: Combien de fois on re-programme un item faute de VRAM avant de renoncer EN LE DISANT.
#: Borné à dessein : une attente non bornée est un blocage silencieux, pas de la patience.
#: 40 essais × 45 s ≈ 30 min — au-delà, ce n'est plus un pic d'occupation, c'est une charge
#: durable, et l'utilisateur doit pouvoir décider (baisser l'exigence, ou relancer plus tard).
DIFFEREMENTS_MAX = 40
DIFFEREMENT_DELAI_S = 45


def _differer_faute_de_vram(task, ctx, item, model, item_id, app_id, besoin_gb,
                            error_field):
    """Re-programme l'item au lieu d'ATTENDRE dans le worker. Rend True si on a différé.

    ⚠ Pourquoi pas `wait_for_free_vram()` ici : elle DORT dans la tâche, donc elle immobilise
    un worker Celery. Pour un hoquet de 180 s c'est acceptable (son seul appelant de
    production est le mode dépannage GPU du composer, qui reste inchangé) ; pour « la tâche
    se lancera quand les ressources seront disponibles », c'est une famine de workers :
    N items en attente = N workers bloqués, et la file GPU s'arrête — y compris pour les
    tâches légères qui, elles, passeraient.

    On rend donc le worker : statut `AWAITING_RESOURCES`, message explicite, nouvelle
    livraison dans `DIFFEREMENT_DELAI_S`. Trois bénéfices d'un coup — le worker reste libre,
    l'attente devient VISIBLE sur la card, et elle devient annulable (l'utilisateur peut
    baisser l'exigence de qualité et relancer immédiatement).

    ⚠ Un `retry` Celery publie un NOUVEAU message : il ne porte donc pas le drapeau
    `redelivered`, et la garde anti-boucle-de-crash (`refuse_crash_redelivery`) ne s'en émeut
    pas. Vérifié avant d'écrire ceci — c'est exactement le genre d'interaction qui se paie
    trois semaines plus tard.
    """
    from wama.common.models import JOB_AWAITING_RESOURCES
    from wama.common.services.resource_governor import effective_free_gb

    try:
        libre = effective_free_gb()
    except Exception:
        return False                      # sonde indisponible → on tente, comme avant
    if libre >= besoin_gb:
        return False

    essais = int(getattr(getattr(task, 'request', None), 'retries', 0) or 0)
    if essais >= DIFFEREMENTS_MAX:
        # On renonce EN LE DISANT — jamais un échec muet, jamais un repli silencieux vers un
        # modèle plus léger : ce serait décider à la place de l'utilisateur ce qu'il a
        # justement demandé de ne pas faire en choisissant la qualité.
        attendu = round(DIFFEREMENTS_MAX * DIFFEREMENT_DELAI_S / 60)
        msg = (f"Ressources GPU insuffisantes depuis ~{attendu} min "
               f"({libre:.1f} Go libres, {besoin_gb:.1f} Go requis) — "
               f"réduire l'exigence de qualité pour lancer maintenant, ou relancer plus tard.")
        champs = {'status': 'FAILURE'}
        if _has_field(model, error_field):
            champs[error_field] = msg
        model.objects.filter(pk=item_id).update(**champs)
        ctx.console(f"✗ {msg}", level='error')
        _notify(item, app_id.title(), _item_label(item, item_id), False, detail=msg)
        return True

    msg = (f"En attente de ressources : {libre:.1f} Go libres, {besoin_gb:.1f} Go requis "
           f"(nouvelle tentative dans {DIFFEREMENT_DELAI_S} s)")
    champs = {'status': JOB_AWAITING_RESOURCES}
    if _has_field(model, error_field):
        champs[error_field] = ''          # ce n'est pas une erreur : on n'en laisse pas la trace
    model.objects.filter(pk=item_id).update(**champs)
    ctx.console(msg, level='info')
    logger.info("[%s] item #%s différé — %s", app_id, item_id, msg)
    raise task.retry(countdown=DIFFEREMENT_DELAI_S, max_retries=DIFFEREMENTS_MAX)


def run_item_task(task, *, app_id: str, model, item_id: int, process,
                  vram_needed=None,
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

    # RELANCE (RunOutcome, §16.7) — un item DÉJÀ en SUCCESS qu'on relance est le signal négatif
    # le plus net que WAMA produise : l'utilisateur avait un résultat et il en redemande un.
    # Détecté ici, avant que le statut ne repasse à RUNNING : c'est le seul instant où
    # l'information existe encore, et le détecter dans le squelette la capte pour TOUTES les
    # apps sans une ligne par app. Capture implicite au sens strict — aucun geste ajouté.
    if getattr(item, 'status', None) == 'SUCCESS':
        _signal(item, app_id, 'relance', None, {})

    ctx = TaskContext(app_id, model, item, progress_fn=progress_fn)

    # ── Ressources AVANT de se déclarer en cours (2026-09-01) ────────────────────────────
    # Placé ICI, avant `ctx.progress(0)` qui bascule l'item en RUNNING : un item différé ne
    # doit jamais avoir été « en cours ». `vram_needed` est OPTIONNEL — une app qui ne le
    # déclare pas garde exactement le comportement d'avant (aucune des 10 ne bouge tant
    # qu'elle ne l'a pas déclaré).
    if vram_needed is not None:
        try:
            besoin = vram_needed(item) if callable(vram_needed) else float(vram_needed)
        except Exception as exc:
            logger.warning("[%s] besoin VRAM illisible (%s) — on tente sans différer",
                           app_id, exc)
            besoin = None
        if besoin and _differer_faute_de_vram(task, ctx, item, model, item_id, app_id,
                                              float(besoin), error_field):
            return

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
        nom = res.get('label') or _item_label(item, item_id)
        ctx.console(res.get('console_success') or f"✓ Terminé : {nom}", level='info')
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
        # Signal d'exécution (RunOutcome, §16.7) : la LIGNE DE BASE de toute boucle
        # d'auto-amélioration — sans elle, un « corrigé » ou un « supprimé » plus tard ne se
        # rattache à aucune production. Posée ici, dans le squelette commun, elle couvre d'un
        # coup toutes les apps qui l'ont adopté. La glu DÉCLARE les modèles qu'elle a employés
        # via `models` (même motif que `eta`) ; sans déclaration on enregistre quand même le
        # fait, avec une liste vide — un signal sans attribution vaut mieux qu'aucun signal.
        _signal(item, app_id, 'produit', res.get('models'),
                {'secondes': round(time.time() - t0, 1)})
        _notify(item, label_app, nom, True)
    except Exception as exc:
        msg = str(exc)[:500]
        logger.exception(f"{app_id} task ERROR | item={item_id}: {exc}")
        fields = {'status': 'FAILURE'}
        if _has_field(model, error_field):
            fields[error_field] = msg
        model.objects.filter(pk=item_id).update(**fields)
        nom = _item_label(item, item_id)
        ctx.console(f"✗ Erreur ({nom}) : {msg}", level='error')
        # Un échec est un fait aussi informatif qu'un succès : un modèle qui échoue souvent sur
        # un type d'entrée doit finir par se voir. On garde le message tel quel, sans le classer.
        _signal(item, app_id, 'echec', None, {'erreur': msg[:200]})
        _notify(item, label_app, nom, False, detail=msg)
