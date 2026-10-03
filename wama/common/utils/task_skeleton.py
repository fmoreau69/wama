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
  - `ctx.app_id` : le label de l'app qui EXÉCUTE — à passer aux briques qui prennent une app
                   (`process_prompt_for`, `app_media_dir`, `clear_partial`…), jamais écrit en
                   dur : une jumelle de bac à sable (`writer_01`) n'a pas le label de son
                   manifeste (`writer`). Ajouté le 2026-10-01 : la glu du Writer passait
                   `'writer'` à la pipeline de prompts, qui ne trouvait aucune cible et rendait
                   la consigne intacte — document de référence ignoré, sans un message.
  - retour : {'fields': {champs modèle à persister au succès — des RÉSULTATS, jamais un RÉGLAGE :
                         écrire le modèle tiré dans le champ `model` remplacerait le choix
                         « auto » de l'utilisateur (relance figée, curseur masqué). Le modèle
                         EMPLOYÉ va dans `models`, ci-dessous ; 2026-10-01},
              'eta':    (clé, taille, unité) pour `record_run` — optionnel,
              'label':  nom lisible du résultat (console ✓ + notification) — optionnel,
              'instruction': ce qui a été demandé pour obtenir ce résultat (prompt de
                             modification) — gardé dans la RÉVISION de l'élément ; optionnel,
              'models': [clés de catalogue des modèles employés] — attribuent le résultat
                        (signal `produit` de RunOutcome, révision) ; une clé `auto` se rend
                        RÉSOLUE. Ajouté au contrat le 2026-10-01 : la 1ʳᵉ génération réelle de
                        l'Editor avait une révision SANS modèle — la clé n'était écrite nulle part
                        dans ce contrat, donc dans la matière du rôle `codegen` ; optionnel,
              'console_success': ligne ✓ personnalisée (remplace « ✓ Terminé : <label> ») — optionnel,
              'output_ref': chemin (relatif à MEDIA_ROOT) de CE QUE LE PROCESS A RENDU — gardé sur
                            sa ligne d'exécution ; c'est ce qui permet à un aval de se savoir
                            périmé quand cette sortie est remplacée (2026-10-02) ; optionnel,
              'output_fingerprint': empreinte d'une sortie qui n'est PAS un fichier (texte, lignes
                            en base) — même rôle qu'`output_ref` pour la péremption de l'aval
                            (2026-10-03, transcriber) ; optionnel}
  - Un process `optional` qui LÈVE ne fait pas échouer la card : sa ligne passe en échec, la
    console le dit, les process suivants sont joués (règle d'agrégation 4.4).
  - `ctx.step` : clé du process en cours quand la card en porte plusieurs (None sinon) ;
    `ctx.reset_progress()` : barre de la card à zéro, hors de la part du process en cours.
    La glu peut retourner À TOUT MOMENT (ex. chemin court PDF natif du reader) : le retour
    déclenche le flux de succès standard.
  - une exception = FAILURE (message tronqué dans `error_field`, console ✗, notification
    d'échec). Le nettoyage spécifique d'échec (fichiers temporaires…) reste DANS la glu
    (try/finally ou except-reraise) — le squelette ne connaît pas ses artefacts.
  Hors contrat (volontaire) : les tâches d'ENRICHISSEMENT à la demande (reader `analyze`,
  transcriber `enrich`) — elles ne pilotent PAS le cycle de vie de l'item (ni statut ni
  progress) ; les faire passer ici corromprait l'état (FAILURE sur un item déjà SUCCESS).
  ⏳ Précisé le 2026-09-15 (WAMA_APP_GENERATION_ROUTE.md §10.6 4.7) : ces enrichissements
  deviendront des process `optional` avec leur propre ligne d'exécution — l'état de la card
  étant DÉDUIT de ses process, ils ne corrompront plus rien.

Le squelette pose, dans l'ordre de la convention : `close_old_connections`, chargement de
l'item (`select_related('user')`), `refuse_crash_redelivery` (garde anti-boucle-de-crash),
progress 0, `ensure_local_input` (no-op sans `WAMA_INGEST`), chrono, puis au succès
SUCCESS + progress 100 + `processing_seconds` (si le modèle les porte), `record_run` et
`notify_job` en best-effort. Vocabulaire de statuts canonique : SUCCESS / FAILURE.
(Précisé le 2026-09-15 → WAMA_APP_GENERATION_ROUTE.md §10.6 4.2 : vocabulaire commun = les 5 états
JOB_* de `wama.common.models`, AWAITING_RESOURCES compris, + STALE ; ce squelette devient une pièce
du moteur commun de pipeline, 4.5.)
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
        #: Process en cours quand la card en porte plusieurs (clé du `ProcessSpec`) ; None pour
        #: une app à un seul process.
        self.step = None
        self._window = (0.0, 100.0)

    def enter_step(self, step, start_pct: float, end_pct: float) -> None:
        """Le squelette entre dans un process d'un pipeline : la glu continue d'annoncer 0-100
        pour SON travail, la card reçoit la part de barre qui lui revient."""
        self.step = step
        self._window = (float(start_pct), float(end_pct))

    def reset_progress(self) -> None:
        """Barre de la CARD remise à zéro (un échec relançable) — hors de toute part de process :
        `progress(0)` dans un pipeline ne ramène qu'au début du process en cours."""
        self._window = (0.0, 100.0)
        self.progress(0)

    def progress(self, pct: int, msg: str = None) -> None:
        if self._window != (0.0, 100.0):
            low, high = self._window
            pct = low + (high - low) * max(0.0, min(100.0, float(pct))) / 100.0
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


def _signal(item, app_id: str, signal: str, model_keys=None, detail=None):
    """Signal d'exécution, best-effort — comme `_notify`, il ne doit jamais faire échouer une
    tâche qui a par ailleurs abouti. Rend la ligne écrite (ou None) : la révision s'y rattache."""
    try:
        from wama.common.services.run_outcome import record
        return record(app_id, item, signal, model_keys=model_keys, detail=detail)
    except Exception:
        return None


def _revision(model, item_id: int, app_id: str, outcome, res: dict) -> None:
    """Révision de l'élément au succès (marche 8a, `WAMA_COLLABORATION §7.1`), best-effort.
    L'élément est RELU : les champs de résultat viennent d'être écrits par `update()`, que
    l'instance chargée au départ ne voit pas."""
    try:
        from wama.common.services.revisions import record_revision
        fresh = model.objects.filter(pk=item_id).first()
        if fresh is not None:
            # Les sorties = ce que la glu vient d'écrire, pas tous les fichiers de l'élément.
            record_revision(app_id, fresh, outcome=outcome, model_keys=res.get('models'),
                            instruction=res.get('instruction') or '',
                            output_fields=list(res.get('fields') or {}))
    except Exception:
        pass


def _notify(item, label: str, nom: str, ok: bool, detail: str = None) -> None:
    try:
        from wama.common.utils.notifications import notify_job, notify_job_collaborators
        notify_job(getattr(item, 'user', None), label, nom, ok, detail=detail)
        # E3 (2026-10-03) : ceux qui collaborent sur la card sont prévenus aussi.
        notify_job_collaborators(item, label, nom, ok, detail=detail or '')
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


#: Délai entre deux re-livraisons d'un item qui attend des ressources. L'attente elle-même est
#: ILLIMITÉE depuis le 2026-09-20 (décision Fabien : la tâche se lancera quand les ressources
#: seront là ; ce qui ne tiendra JAMAIS est refusé d'emblée, ce n'est pas une attente). Le
#: plafond « 40 × 45 s ≈ 30 min puis échec » d'avant est retiré : il rendait un échec pour une
#: charge durable légitime, alors que la durée max porte sur UN traitement, pas sur l'attente.
DIFFEREMENT_DELAI_S = 45
#: ⚠ « Sans plafond » ne s'écrit PAS `max_retries=None` dans `task.retry()` : pour Celery, `None`
#: en argument veut dire « le défaut de la tâche » — 3 (`celery/app/task.py:720`, `max_retries = 3`
#: à la classe). Mesuré le 2026-10-02 sur la 1ʳᵉ vraie attente (composer #282) : à la 3ᵉ
#: re-livraison, `MaxRetriesExceededError`, et l'élément est resté « en attente de ressources »
#: sans tâche, pour toujours. L'attente illimitée se dit par un plafond que personne n'atteint.
WAIT_RETRIES_UNLIMITED = 10 ** 9


class TaskTimeLimitExceeded(Exception):
    """Le traitement a dépassé sa durée max (`resource_governor.task_time_limit_s`)."""


def _grant_honoured(grant, item) -> bool:
    """Un accord de libération vaut s'il vient du PROPRIÉTAIRE de l'item ou d'un admin — le
    gouverneur enregistre qui a accordé, le squelette (qui connaît l'item) tranche."""
    uid = (grant or {}).get('user')
    if uid is None:
        return False
    if uid == getattr(item, 'user_id', None):
        return True
    try:
        from django.contrib.auth import get_user_model
        return get_user_model().objects.filter(pk=uid, is_staff=True).exists()
    except Exception:
        return False


def _differer_faute_de_vram(task, ctx, item, model, item_id, app_id, besoin_gb,
                            error_field, write_line: bool = True):
    """Trois cas (Fabien, 20/09), jamais un échec muet. Rend True si l'item ne part pas.

    (a) `besoin_gb` ne tient pas sur la carte VIDE → REFUS immédiat et dit : aucune attente ne
        changera la taille de la carte (le filtre du tirage l'écarte en amont ; ici c'est la garde
        d'un choix manuel).
    (b) tient seul, pas maintenant → `AWAITING_RESOURCES`, re-livraison dans
        `DIFFEREMENT_DELAI_S`, SANS plafond ; la card dit qui tient quoi (`holders_summary`).
    (c) l'utilisateur a ACCORDÉ la libération de toute la carte (`grant_release`, bouton de la
        card) → demande aux tenants (`obtain_vram`), et l'item part dès que la sonde le permet ;
        l'accord sert une fois. Jamais de déchargement d'office.

    ⚠ Pourquoi pas `wait_for_free_vram()` ici : elle DORT dans la tâche, donc elle immobilise
    un worker Celery — N items en attente = N workers bloqués. On rend le worker : l'attente
    devient VISIBLE sur la card et annulable.
    ⚠ Un `retry` Celery publie un NOUVEAU message : il ne porte pas le drapeau `redelivered`,
    la garde anti-boucle-de-crash (`refuse_crash_redelivery`) ne s'en émeut pas (vérifié).
    `write_line=False` pour une app à PIPELINE : avant le tirage on ne sait pas quel process
    partira le premier, et une ligne « main » n'est pas un de ses process — l'attente est alors
    portée par l'ÉLÉMENT seul (`AWAITING_RESOURCES`), qui reste ce que l'interface lit.
    """
    from celery.exceptions import MaxRetriesExceededError
    from wama.common.models import JOB_AWAITING_RESOURCES
    from wama.common.services import process_runs
    from wama.common.services import resource_governor as gov

    try:
        libre = gov.effective_free_gb()
    except Exception:
        return False                      # sonde indisponible → on tente, comme avant
    if libre >= besoin_gb:
        return False

    if gov.fits_alone(besoin_gb) is False:
        total = gov.total_vram_gb()
        msg = (f"Ce traitement demande {besoin_gb:.1f} Go de VRAM et la carte en a {total:.1f} : "
               f"il ne tiendra jamais, même seul — choisir un modèle plus léger ou baisser "
               f"l'exigence de qualité.")
        champs = {'status': 'FAILURE'}
        if _has_field(model, error_field):
            champs[error_field] = msg
        model.objects.filter(pk=item_id).update(**champs)
        if write_line:
            process_runs.safely(process_runs.fail, item, message=msg, process_key=app_id)
        ctx.console(f"✗ {msg}", level='error')
        _notify(item, app_id.title(), _item_label(item, item_id), False, detail=msg)
        return True

    grant = gov.release_granted(app_id, item_id)
    if grant and _grant_honoured(grant, item):
        ctx.console(f"Libération de la carte accordée : {besoin_gb:.1f} Go requis, "
                    f"{libre:.1f} libres — demande envoyée aux services…", level='info')
        ok, libre = gov.obtain_vram(besoin_gb, requester=gov.tenant_id(),
                                    reason=f"{app_id} #{item_id}", console=ctx.console)
        gov.revoke_grant(app_id, item_id)
        if ok:
            return False

    who = gov.holders_summary()
    msg = (f"En attente de ressources : {libre:.1f} Go libres, {besoin_gb:.1f} Go requis"
           + (f" — {who}" if who else '')
           + f" (nouvelle tentative dans {DIFFEREMENT_DELAI_S} s)")
    champs = {'status': JOB_AWAITING_RESOURCES}
    if _has_field(model, error_field):
        champs[error_field] = ''          # ce n'est pas une erreur : on n'en laisse pas la trace
    model.objects.filter(pk=item_id).update(**champs)
    if write_line:
        process_runs.safely(process_runs.await_resources, item, process_key=app_id,
                            task_id=getattr(getattr(task, 'request', None), 'id', '') or '')
    ctx.console(msg, level='info')
    logger.info("[%s] item #%s différé — %s", app_id, item_id, msg)
    try:
        raise task.retry(countdown=DIFFEREMENT_DELAI_S, max_retries=WAIT_RETRIES_UNLIMITED)
    except MaxRetriesExceededError:
        # Filet : une attente qui ne peut plus être re-livrée est un ÉCHEC DIT, jamais un élément
        # abandonné « en attente de ressources » sans tâche derrière lui.
        msg = (f"Attente de ressources interrompue après {_deliveries_so_far(task)} re-livraisons : "
               f"relancer quand la carte sera libre.")
        champs = {'status': 'FAILURE'}
        if _has_field(model, error_field):
            champs[error_field] = msg
        model.objects.filter(pk=item_id).update(**champs)
        if write_line:
            process_runs.safely(process_runs.fail, item, message=msg, process_key=app_id)
        ctx.console(f"✗ {msg}", level='error')
        _notify(item, app_id.title(), _item_label(item, item_id), False, detail=msg)
        return True


def _deliveries_so_far(task) -> int:
    return int(getattr(getattr(task, 'request', None), 'retries', 0) or 0)


class _time_guard:
    """Garde-temps d'UN traitement (Fabien, 16/09 : 30 min par défaut, réglable). Mesuré le
    20/09 : `--pool=solo` n'honore AUCUNE limite Celery (`concurrency/solo.py:29`). La tâche du
    worker gpu tourne dans le THREAD PRINCIPAL du process : un `SIGALRM` y lève
    `TaskTimeLimitExceeded` au prochain pas Python — le même geste que prefork dans ses
    enfants. Hors thread principal ou sans `SIGALRM` (Windows, pool prefork où Celery garde la
    main) : sans effet, à dessein. Arrêt PROPRE : l'exception remonte dans le squelette, qui
    pose l'échec relançable, rend la ligne « tâche en cours » et notifie."""

    def __init__(self, limit_s: float):
        self.limit_s = float(limit_s or 0)
        self._previous = None
        self._armed = False

    def __enter__(self):
        import signal
        import threading
        if self.limit_s <= 0 or not hasattr(signal, 'SIGALRM') \
                or threading.current_thread() is not threading.main_thread():
            return self

        def _expire(signum, frame):
            raise TaskTimeLimitExceeded(self.limit_s)

        self._previous = signal.signal(signal.SIGALRM, _expire)
        signal.setitimer(signal.ITIMER_REAL, self.limit_s)
        self._armed = True
        return self

    def __exit__(self, *exc):
        if self._armed:
            import signal
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._previous or signal.SIG_DFL)
        return False


def _measure_against_reference(app_id: str, model, item_id: int, ctx) -> None:
    """Mesure l'item contre sa RÉFÉRENCE s'il en porte une (`result_evaluation`) — APRÈS le
    SUCCESS, jamais dans la glu.

    ⚠ Déplacé ici le 2026-09-29 : le transcriber mesurait À LA FIN DE SA GLU, donc AVANT que ce
    squelette ne pose SUCCESS — et sa lecture du résultat refuse, à raison, un item non terminé.
    Depuis son passage au squelette (25/09), aucune transcription ne se mesurait plus en fin de
    tâche, SANS le moindre signal (la mesure est best-effort). Vu sur le lot SUMM-RE : card
    réussie, référence posée, zéro ligne `ResultEvaluation`. Ici, l'ordre est garanti pour toute
    app qui déclare une évaluation, et l'item est RELU (la glu a écrit en base, pas dans `item`).
    """
    try:
        from wama.common.services.result_evaluation import evaluate, evaluation_spec
        spec = evaluation_spec(app_id)
        if spec is None:
            return
        fresh = model.objects.get(pk=item_id)
        if not getattr(fresh, spec.reference_field, None):
            return
        if evaluate(app_id, fresh):
            ctx.console("Évaluation contre la référence enregistrée ✓", level='info')
    except Exception as exc:          # une mesure manquée ne fait jamais échouer un succès
        logger.warning("[%s] mesure contre la référence de #%s impossible : %s",
                       app_id, item_id, exc)


def _record_eta(eta, seconds: float, item) -> None:
    """ETA d'UN process (`(clé, taille, unité)` rendu par sa glu), best-effort."""
    if not eta:
        return
    try:
        from wama.model_manager.services.eta_estimator import record_run
        key, size, unit = eta
        record_run(key, size=size, unit=unit, process_seconds=seconds, load_seconds=None,
                   user=getattr(item, 'user', None))
    except Exception:
        pass


def _line_summary(res: dict):
    """Ce que la ligne d'exécution retient du retour d'une glu : son nom lisible, et l'EMPREINTE
    de sa sortie quand ce n'est pas un fichier (`output_fingerprint` — le texte d'une
    transcription : c'est ce qui périme l'aval quand cette sortie est remplacée)."""
    summary = {}
    if res.get('label'):
        summary['label'] = res['label']
    if res.get('output_fingerprint'):
        summary['fingerprint'] = str(res['output_fingerprint'])
    return summary or None


def _selected_steps(app_id, item, process, pipeline, processes, resolved_key, only=None) -> list:
    """Les process que CE lancement joue : `[(nœud, clé de process, glu, spec|None)]`.

    Une app à un seul process : sa glu, sur le nœud `main`. Une app qui DÉCLARE un pipeline
    (`process_pipeline.AppPipeline`) : les process qui ne sont pas à jour et leur aval, dans
    l'ordre du graphe — un résultat encore valable n'est pas rejoué ; `only` borne le lancement
    à UN process et ses amonts périmés (▶ par process, P5)."""
    from wama.common.services import process_runs
    if pipeline is None:
        return [(process_runs.MAIN_NODE, app_id, process, None)]
    specs = pipeline.steps_to_run(item, resolved_key, only=only)
    if not specs:
        raise RuntimeError("aucun process à jouer pour cet élément")
    missing = [spec.key for spec in specs if spec.key not in (processes or {})]
    if missing:
        raise RuntimeError(f"process sans glu : {', '.join(missing)}")
    return [(spec.key, pipeline.function_key(spec), processes[spec.key], spec) for spec in specs]


def run_item_task(task, *, app_id: str, model, item_id: int, process=None,
                  vram_needed=None, model_key=None,
                  error_field: str = 'error_message', ingest_derive=None,
                  notify_label: str = None, progress_fn=None,
                  pipeline=None, processes=None, only: str = None):
    """Exécute la glu `process` dans le squelette conventionnel. Voir le contrat en tête de
    module. `task` = la tâche Celery liée (bind=True) — requis par la garde de redélivrance.

    PLUSIEURS PROCESS (ROUTE §10.6, marche P3 palier B — 2026-10-02) : une app qui déclare un
    pipeline passe `pipeline=` (son `AppPipeline`) et `processes={clé: glu}` à la place de
    `process`. Chaque glu garde le MÊME contrat ; le squelette joue celles que le lancement
    retient (`pipeline.steps_to_run`), l'une après l'autre dans cette tâche, et tient une ligne
    d'exécution par process. Les `fields` d'un process sont écrits dès qu'il a rendu — la glu
    suivante les lit sur `item` — et sa sortie se nomme par la clé `output_ref` du retour.
    `only` (▶ par process) borne le lancement à ce process et à ses amonts périmés."""
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
    # Placé ICI, avant tout geste de traitement : un item différé ne doit jamais avoir été
    # « en cours ». `vram_needed` est OPTIONNEL — une app qui ne le déclare pas garde
    # exactement le comportement d'avant (aucune des 10 ne bouge tant qu'elle ne l'a pas
    # déclaré).
    # ⚠ Corrigé le 2026-09-14 : ce commentaire disait « avant `ctx.progress(0)` qui bascule
    # l'item en RUNNING » — faux, `TaskContext.progress` n'écrit que le cache et `progress`.
    # RUNNING est posé par les VUES de lancement, avant `.delay()`.
    from wama.common.models import JOB_AWAITING_RESOURCES, JOB_RUNNING
    essais = int(getattr(getattr(task, 'request', None), 'retries', 0) or 0)
    if essais and getattr(item, 'status', None) not in (JOB_AWAITING_RESOURCES, JOB_RUNNING):
        # RE-LIVRAISON d'un report (`task.retry`, seul retry du squelette) alors que l'item
        # n'attend plus : l'utilisateur l'a annulé, supprimé de la file ou relancé autrement
        # entre-temps. Le traiter quand même ferait tourner ce qu'il a arrêté.
        logger.info("[%s] item #%s : report abandonné (statut %s, plus en attente de ressources)",
                    app_id, item_id, getattr(item, 'status', None))
        return
    besoin = None
    if vram_needed is not None:
        try:
            besoin = vram_needed(item) if callable(vram_needed) else float(vram_needed)
        except Exception as exc:
            logger.warning("[%s] besoin VRAM illisible (%s) — on tente sans différer",
                           app_id, exc)
            besoin = None
        if besoin and _differer_faute_de_vram(task, ctx, item, model, item_id, app_id,
                                              float(besoin), error_field,
                                              write_line=pipeline is None):
            return

    # Un item RE-LIVRÉ après un report ne repasse par aucune vue de lancement : sans ce geste,
    # il resterait affiché « En attente de ressources » pendant tout son traitement. Seul ce
    # cas bascule — un item PENDING n'est jamais mis en cours ici.
    if getattr(item, 'status', None) == JOB_AWAITING_RESOURCES:
        model.objects.filter(pk=item_id, status=JOB_AWAITING_RESOURCES).update(status=JOB_RUNNING)
        item.status = JOB_RUNNING

    ctx.progress(0)

    # ── Premier lancement : PRÉVENIR du téléchargement des poids (2026-09-08) ────────────
    # `model_key` est OPTIONNEL et se déclare comme `vram_needed` : une chaîne, ou un callable
    # qui la tire de l'item (le champ varie — `model`, `ai_model`, `backend`, `tts_model` : la
    # convention n'existe pas, on ne la devine donc pas). Placé APRÈS `progress(0)` : la tâche
    # est réellement partie, l'attente qu'on annonce commence maintenant.
    resolved_key = None
    if model_key is not None:
        try:
            resolved_key = model_key(item) if callable(model_key) else str(model_key)
            from wama.common.utils.model_readiness import warn_if_weights_missing
            warn_if_weights_missing(resolved_key, console=ctx.console)
        except Exception as exc:      # prévenir est un confort, jamais une condition
            logger.debug('[%s] annonce de téléchargement impossible : %s', app_id, exc)

    try:
        from wama.common.utils.source_ingest import ensure_local_input
        ensure_local_input(item, console=ctx.console, derive=ingest_derive)
    except Exception as exc:
        logger.warning(f"[{app_id}] ensure_local_input({item_id}) : {exc}")

    t0 = time.time()
    label_app = notify_label or app_id.title()
    # La TÂCHE EN COURS se déclare au gouverneur (B1, 2026-09-20) : jusque-là « une tâche GPU
    # tourne » ne se lisait que dans les statuts RUNNING des tables d'app — invisible du
    # gouverneur, donc de l'attente des autres. La ligne expire avec la durée max du traitement.
    from wama.common.services import resource_governor as gov
    # Le MODÈLE peut porter sa durée max (réglée au model manager, 2026-09-24) : une vidéo longue
    # dépasse légitimement le défaut de 30 min.
    limit_s = gov.task_time_limit_s(app_id, getattr(item, 'user', None), model_key=resolved_key)
    token = gov.task_started(app_id, item_id, besoin or 0.0, max_s=limit_s)
    # LIGNE D'EXÉCUTION du process (ROUTE §10.6 4.1, marche P3 — 2026-10-02) : une app du
    # squelette a UN process, donc une ligne. Elle porte ce que l'élément ne disait pas pendant
    # le traitement : le modèle EMPLOYÉ quand le réglage est resté « auto ». L'élément reste la
    # vérité lue par l'interface ; la ligne est écrite aux mêmes instants que lui.
    # Avec PLUSIEURS process (palier B), la boucle ci-dessous tient une ligne par process joué ;
    # `node` est le process EN COURS — c'est sa ligne qu'un échec referme.
    from wama.common.services import process_runs
    task_ref = getattr(getattr(task, 'request', None), 'id', '') or ''
    node = process_runs.MAIN_NODE if pipeline is None else None
    process_key = app_id
    try:
        with _time_guard(limit_s):
            steps = _selected_steps(app_id, item, process, pipeline, processes, resolved_key,
                                    only=only)
            total_share = sum(spec.share if spec is not None else 1 for *_x, spec in steps) or 1
            done_share, written, used, carried_label = 0, {}, [], None
            for index, (node, process_key, glue, spec) in enumerate(steps):
                share = spec.share if spec is not None else 1
                if spec is not None:
                    ctx.enter_step(spec.key, 100.0 * done_share / total_share,
                                   100.0 * (done_share + share) / total_share)
                process_runs.safely(
                    process_runs.start, item, node, process_key=process_key,
                    kind='app' if spec is None else 'function',
                    settings_snapshot=pipeline.snapshot(spec, item) if spec is not None else None,
                    model_key=resolved_key or '', task_id=task_ref)
                t_step = time.time()
                try:
                    res = glue(item, ctx) or {}
                except TaskTimeLimitExceeded:
                    raise
                except Exception as exc:
                    if spec is None or spec.degree != process_runs.OPTIONAL:
                        raise
                    # Un process OPTIONNEL en échec ne fait pas échouer la card (règle 4.4) : sa
                    # ligne le dit, la console aussi, et la suite continue. C'est ce que le
                    # transcriber avalait (résumé en échec, élément en succès, aucune trace sur
                    # la card) — la card « reste à compléter », ▶ ne rejouera que lui.
                    logger.warning("[%s] item #%s : process optionnel « %s » en échec : %s",
                                   app_id, item_id, spec.key, exc)
                    process_runs.safely(process_runs.fail, item, node, str(exc)[:500],
                                        process_key=process_key)
                    ctx.console(f"Avertissement : « {spec.label or spec.key} » a échoué ({exc}) — "
                                f"le reste du traitement continue.", level='warning')
                    done_share += share
                    res, node = {}, None      # rien à refermer en succès pour ce process
                    continue
                used += [k for k in (res.get('models') or []) if k and k not in used]
                written.update(res.get('fields') or {})
                if res.get('label'):
                    carried_label = res['label']
                if index == len(steps) - 1:
                    break             # le DERNIER process rend la card : flux de succès ci-dessous
                # Un process INTERMÉDIAIRE a rendu : ses champs sont écrits tout de suite (la glu
                # suivante les lit sur `item`, et ils survivent à l'échec d'un aval), sa ligne
                # passe en succès, son ETA s'apprend — sans attendre la fin de la card.
                if res.get('fields'):
                    model.objects.filter(pk=item_id).update(**res['fields'])
                    for name, value in res['fields'].items():
                        setattr(item, name, value)
                process_runs.safely(
                    process_runs.succeed, item, node, process_key=process_key,
                    output_ref=res.get('output_ref') or '',
                    model_key=(res.get('models') or [None])[0],
                    output_summary=_line_summary(res))
                _record_eta(res.get('eta'), time.time() - t_step, item)
                if res.get('label'):
                    ctx.console(res.get('console_success') or f"✓ {res['label']}", level='info')
                done_share += share
        last_model = next((k for k in (res.get('models') or []) if k), None)
        last_summary = _line_summary(res)
        # Ce que la CARD a produit = ce que tous ses process joués ont écrit et employé ; son nom
        # lisible est le dernier qu'un process a donné (le dernier process peut ne rien nommer).
        res = dict(res, fields=written, models=used or res.get('models'))
        if not res.get('label') and carried_label:
            res['label'] = carried_label
        fields = dict(written)
        fields['status'] = 'SUCCESS'
        if _has_field(model, 'progress'):
            fields['progress'] = 100
        if _has_field(model, 'processing_seconds'):
            fields['processing_seconds'] = round(time.time() - t0, 1)
        model.objects.filter(pk=item_id).update(**fields)
        if node is not None:          # None : le dernier process, optionnel, a échoué (ligne déjà dite)
            process_runs.safely(process_runs.succeed, item, node, process_key=process_key,
                                output_ref=res.get('output_ref') or '',
                                model_key=last_model, output_summary=last_summary)
        ctx.enter_step(None, 0, 100)
        ctx.progress(100)
        _measure_against_reference(app_id, model, item_id, ctx)
        nom = res.get('label') or _item_label(item, item_id)
        ctx.console(res.get('console_success') or f"✓ Terminé : {nom}", level='info')
        logger.info(f"=== {app_id} task DONE | item={item_id} ===")
        _record_eta(res.get('eta'), time.time() - t_step, item)
        # Signal d'exécution (RunOutcome, §16.7) : la LIGNE DE BASE de toute boucle
        # d'auto-amélioration — sans elle, un « corrigé » ou un « supprimé » plus tard ne se
        # rattache à aucune production. Posée ici, dans le squelette commun, elle couvre d'un
        # coup toutes les apps qui l'ont adopté. La glu DÉCLARE les modèles qu'elle a employés
        # via `models` (même motif que `eta`) ; sans déclaration on enregistre quand même le
        # fait, avec une liste vide — un signal sans attribution vaut mieux qu'aucun signal.
        outcome = _signal(item, app_id, 'produit', res.get('models'),
                          {'secondes': round(time.time() - t0, 1)})
        # RÉVISION (marche 8a) : l'état que ce résultat donne à l'élément, rattaché au fait
        # `produit` — posée ici, elle vaut pour toutes les apps du squelette sans une ligne par app.
        _revision(model, item_id, app_id, outcome, res)
        _notify(item, label_app, nom, True)
    except TaskTimeLimitExceeded:
        # Arrêt PROPRE à la durée max : échec RELANÇABLE, dit avec la sortie possible (le plafond
        # se règle dans le profil), rien de classé comme une erreur du modèle.
        minutes = round(limit_s / 60)
        msg = (f"Durée maximale atteinte ({minutes} min) : traitement arrêté — relancer, ou "
               f"relever la durée max dans votre profil.")
        logger.warning(f"{app_id} task TIME LIMIT | item={item_id}: {minutes} min")
        fields = {'status': 'FAILURE'}
        if _has_field(model, error_field):
            fields[error_field] = msg
        model.objects.filter(pk=item_id).update(**fields)
        if node is not None:
            process_runs.safely(process_runs.fail, item, node, msg, process_key=process_key)
        nom = _item_label(item, item_id)
        ctx.console(f"✗ {msg}", level='error')
        _signal(item, app_id, 'echec', None, {'erreur': 'duree_max'})
        _notify(item, label_app, nom, False, detail=msg)
    except Exception as exc:
        msg = str(exc)[:500]
        logger.exception(f"{app_id} task ERROR | item={item_id}: {exc}")
        fields = {'status': 'FAILURE'}
        if _has_field(model, error_field):
            fields[error_field] = msg
        model.objects.filter(pk=item_id).update(**fields)
        if node is not None:
            process_runs.safely(process_runs.fail, item, node, msg, process_key=process_key)
        nom = _item_label(item, item_id)
        ctx.console(f"✗ Erreur ({nom}) : {msg}", level='error')
        # Un échec est un fait aussi informatif qu'un succès : un modèle qui échoue souvent sur
        # un type d'entrée doit finir par se voir. On garde le message tel quel, sans le classer.
        _signal(item, app_id, 'echec', None, {'erreur': msg[:200]})
        _notify(item, label_app, nom, False, detail=msg)
    finally:
        gov.task_finished(token)
