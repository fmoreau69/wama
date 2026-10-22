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
  - `ctx.output_place(ext, nature='', model='', source_name='')` : (chemin relatif, chemin
                   absolu) du fichier d'une SORTIE de la card — dossier de sortie de l'app au
                   domicile de l'utilisateur, nom par la règle commune (2026-10-21) ; le chemin
                   relatif va dans `fields` et `output_ref`.
  - `ctx.ensure_model(clé)` : AVANT de charger un modèle, au moment où la glu connaît sa clé de
                   catalogue — absent, la ROUTE l'installe, la card le dit, la tâche attend
                   (`ServiceNotReady`) ; rend la clé. Le modèle de la CARD, déclaré
                   (`model_key=`), est demandé par le squelette lui-même (2026-10-18).
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
    console le dit, les process suivants sont joués (règle d'agrégation 4.4). Une ATTENTE
    (`ServiceNotReady`) n'est pas un échec, optionnel ou non : la tâche revient.
  - `ctx.step` : clé du process en cours quand la card en porte plusieurs (None sinon) ;
    `ctx.reset_progress()` : barre de la card à zéro, hors de la part du process en cours.
  - `ctx.snapshot` / `ctx.previous_snapshot` (pipeline, 2026-10-13) : la photo de ce que le process
    SURVEILLE maintenant (réglages, fichiers, empreinte de sortie de ses amonts sous `@upstream`)
    et celle de son dernier RENDU — None s'il n'avait jamais réussi. Ce qui permet à une glu de
    savoir si seul son amont a changé (la forme demandée, non) et d'AJUSTER son résultat au lieu de
    le refaire (`document_sections.adjustment_basis`, la mise en forme du Writer).
    La glu peut retourner À TOUT MOMENT (ex. chemin court PDF natif du reader) : le retour
    déclenche le flux de succès standard.
  - une exception = FAILURE (message tronqué dans `error_field`, console ✗, notification
    d'échec). Le nettoyage spécifique d'échec (fichiers temporaires…) reste DANS la glu
    (try/finally ou except-reraise) — le squelette ne connaît pas ses artefacts.
  Hors contrat (volontaire) : les tâches d'ENRICHISSEMENT à la demande (transcriber `enrich`)
  — elles ne pilotent PAS le cycle de vie de l'item (ni statut ni progress) ; les faire passer
  ici corromprait l'état (FAILURE sur un item déjà SUCCESS).
  ⏳ Précisé le 2026-09-15 (WAMA_APP_GENERATION_ROUTE.md §10.6 4.7) : ces enrichissements
  deviendront des process `optional` avec leur propre ligne d'exécution — l'état de la card
  étant DÉDUIT de ses process, ils ne corrompront plus rien. ✅ L'`analyze` du reader l'est
  devenu le 2026-10-13 (process `analyze` de son pipeline).

Le gouverneur au grain du PROCESS (2026-10-14, `ROUTE §10.6` 4.5) : avant chaque process qui
sollicite la carte (`ProcessSpec.gpu`), le squelette le joue sur la file GPU (re-livraison
`task.retry(queue=…)` si la tâche est ailleurs — un process sans GPU, lui, part sur la file par
défaut), attend sa VRAM (`_vram_need`, `_differer_faute_de_vram`) et le déclare « en cours » au
gouverneur le temps de sa glu. Une glu sans déclaration (`process=`, sans pipeline) garde la règle
d'avant : comptée GPU, sur la file de sa tâche.
Un process qui emploie LE modèle de la card (`ProcessSpec.card_model`, et toute glu sans
déclaration) ne tient pas la carte quand ce modèle est tiré DISTANT (`ROADMAP §8d` étape 4,
2026-10-14) : ni file GPU, ni attente de VRAM, ni déclaration au gouverneur.

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


class LaunchSuperseded(BaseException):
    """Le lancement n'est plus celui de l'élément : l'utilisateur l'a ARRÊTÉ (⏹ — l'élément n'est
    plus en cours) ou l'a RELANCÉ (l'élément porte une autre tâche — `process_control.
    grant_replace`, 2026-10-22). La tâche se retire sans rien écrire : ni statut, ni ligne, ni
    notification, qui seraient ceux d'un traitement que l'utilisateur a remplacé.
    `BaseException` et non `Exception` : une glu qui attrape `Exception` (un process optionnel, un
    repli) ne doit pas l'avaler. L'arrêt est COOPÉRATIF parce qu'un worker `--pool=solo` (la file
    GPU) ne peut pas être tué en cours de tâche : `revoke(terminate=True)` n'y fait rien."""


#: Intervalle minimal entre deux vérifications « suis-je toujours le lancement ? » faites depuis
#: la progression — une lecture en base, pas à chaque pourcent d'une longue transcription.
CURRENT_CHECK_S = 2.0


_ACTIVE = ('RUNNING', 'AWAITING_RESOURCES')


def _superseded(model, item_id, launch: str, seen: dict) -> bool:
    """L'élément a-t-il quitté ce lancement ? Vrai s'il n'existe plus, si la tâche qu'il portait
    — la nôtre, vue une fois — a été effacée ou remplacée (⏹ et `begin_processing` l'effacent, la
    relance en pose une autre), ou s'il est sorti de « en cours » alors qu'il y était au début du
    lancement. Tant que notre tâche n'a pas été vue, une autre ne prouve rien : la vue de
    lancement pose la nôtre juste APRÈS `.delay()`, et une vue qui ne l'efface pas avant laisse
    lire l'ancienne (un lancement encore EN FILE que l'on remplace est révoqué, lui). Un statut
    qui n'était pas « en cours » au départ ne prouve rien non plus. Faux hors worker (aucun
    identifiant de lancement) et en cas de doute.
    `seen` garde, d'une vérification à l'autre : `ours` (notre tâche vue sur l'élément) et
    `started_active` (l'élément était en cours au départ)."""
    if not launch:
        return False
    fields = ['status'] + (['task_id'] if _has_field(model, 'task_id') else [])
    try:
        row = model.objects.filter(pk=item_id).values(*fields).first()
    except Exception:
        return False
    if row is None:
        return True
    current = row.get('task_id') or ''
    if current == launch:
        seen['ours'] = True
    elif seen.get('ours'):
        return True
    if 'started_active' not in seen:
        seen['started_active'] = row.get('status') in _ACTIVE
        return False
    return seen['started_active'] and row.get('status') not in _ACTIVE


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
        #: Photo de ce que le process en cours surveille maintenant, et celle de son dernier rendu
        #: réussi (None s'il n'en a jamais eu) — cf. le contrat en tête de module.
        self.snapshot = None
        self.previous_snapshot = None
        self._window = (0.0, 100.0)
        #: La tâche revient-elle d'une attente (re-livraison) ? Posé par le squelette ; lu par
        #: `ensure_model`.
        self.redelivered = False
        #: L'identité du LANCEMENT (l'id de la tâche, que `task.retry` garde) et le modèle qu'il a
        #: retenu — posés par le squelette, gardés d'une livraison à l'autre (`remember`).
        self.launch = ''
        self.model_key = None
        #: Ce que la vérification « suis-je toujours le lancement ? » a déjà vu (`_superseded`).
        self._seen = {}
        self._checked_at = 0.0

    # ── La MÉMOIRE DU LANCEMENT (2026-10-21, transcriber #2522) ─────────────────────────────
    # Le squelette RE-LIVRE la tâche quand un process change de file (`_hand_over_to`) ou attend
    # une ressource : le process suivant se joue dans un AUTRE worker, dont la mémoire est vide.
    # Mesuré : une transcription distante (Albert, file par défaut) suivie des locuteurs (file
    # GPU) nivelait l'audio DEUX fois (~110 s chacune sur 141 min), et un modèle « auto » se
    # retirait à chaque livraison. Ce qu'un lancement décide pour ses process suivants se garde
    # ici — au cache, sous l'id du lancement — et s'oublie à sa fin RÉELLE (succès, échec, durée
    # max), jamais à une re-livraison. Un FICHIER qu'un process prépare pour le suivant n'y a pas
    # sa place : c'est une sortie de process, déclarée (`ProcessSpec.outputs`) et gardée sur la
    # card — l'audio nivelé du transcriber, qui vivait ici le matin du 2026-10-21 (`keep_file`,
    # retiré le jour même : `REMOVAL_LEDGER`).

    def _launch_entry(self) -> dict:
        kept = cache.get(_launch_key(self.app_id, self.item.pk)) or {}
        return kept if self.launch and kept.get('task') == self.launch else {}

    def recall(self, name: str, default=None):
        """Ce qu'une livraison précédente de CE lancement a gardé sous `name`."""
        return (self._launch_entry().get('facts') or {}).get(name, default)

    def remember(self, name: str, value) -> None:
        if not self.launch:
            return                       # hors worker (appel direct) : rien à reprendre
        entry = self._launch_entry() or {'task': self.launch, 'facts': {}}
        entry['facts'][name] = value
        cache.set(_launch_key(self.app_id, self.item.pk), entry, timeout=LAUNCH_TTL_S)

    def output_place(self, ext: str, *, nature: str = '', model: str = '',
                     source_name: str = '', folder: str = 'output', index: int = None,
                     total: int = 1, card_id: bool = True) -> tuple:
        """(chemin relatif à MEDIA_ROOT, chemin absolu) d'une SORTIE de cette card — le geste d'un
        process qui écrit un fichier déclaré dans ses `outputs` : le dossier de sortie de l'app au
        domicile de l'utilisateur (`app_media_dir`, créé), le nom par la règle commune
        (`compose_output_name` : `nature` quand la sortie n'est pas celle de l'app — `score`,
        `audio` —, `model` le nom du modèle qui l'a rendue). Le chemin relatif est ce que la glu
        rend dans `fields` et `output_ref`. `ext` vide : celle de `source_name`.

        Les variantes que les glues écrivaient à la main (relevé du 2026-10-22, en les portant) :
        `folder` — le sous-dossier de la sortie quand l'app en range plusieurs natures
        (`output/media` et `output/audio` de l'enhancer, `output/image` et `output/video` de
        l'imager) ; `index`/`total` — une série de fichiers pour une card (les images de l'imager) ;
        `card_id=False` — la famille FICHIER sans l'identifiant de la card, quand la souche d'une
        entrée déposée suffit à l'unicité (l'enhancer : ses noms ne changent pas au portage).

        Écrit dans le composer (`_output_place`, 2026-10-02) et recopié par chaque glu qui range
        un fichier ; porté ici le 2026-10-21, quand la préparation audio du transcriber en devenait
        une de plus. `ctx.app_id`, jamais un label en dur : une jumelle a le sien."""
        import os
        from django.conf import settings
        from wama.common.utils.media_paths import app_media_dir
        from wama.common.utils.output_naming import compose_output_name
        rel_dir = app_media_dir(self.app_id, self.user_id, folder)
        abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
        os.makedirs(abs_dir, exist_ok=True)
        name = compose_output_name(app=self.app_id, model=model, ext=ext, nature=nature,
                                   source_name=source_name,
                                   item_id=self.item.pk if card_id else None,
                                   index=index, total=total)
        return f'{rel_dir}/{name}', os.path.join(abs_dir, name)

    def ensure_model(self, model_key: str) -> str:
        """Le modèle que la glu va employer est-il installé ? Sinon la ROUTE l'installe, la card
        le dit et la tâche attend (`model_readiness.ensure_installed`, décision de Fabien du
        2026-10-16) — le geste de la glu qui tire un modèle autre que celui de la card (un
        process d'un pipeline, un modèle secondaire), au moment où elle connaît sa clé. Rend la
        clé, pour s'écrire en ligne : `key = ctx.ensure_model(asr_key(item))`."""
        from wama.common.utils.model_readiness import ensure_installed
        ensure_installed(model_key, user=getattr(self.item, 'user', None), console=self.console,
                         redelivered=self.redelivered)
        return model_key

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

    def check_current(self, force: bool = False) -> None:
        """Lève `LaunchSuperseded` si l'élément a quitté ce lancement (arrêté, relancé) — au plus
        toutes les `CURRENT_CHECK_S` secondes, sauf `force`. Appelé par la progression, donc au
        rythme de chaque glu, et par le squelette avant chaque process et avant le succès."""
        now = time.monotonic()
        if not force and self._checked_at and now - self._checked_at < CURRENT_CHECK_S:
            return
        self._checked_at = now
        if not self._seen and self.launch:
            # Une RE-LIVRAISON reprend ce que la livraison précédente avait vu : sans cela, la
            # tâche d'une relance, posée pendant l'attente, ne prouverait rien au worker suivant.
            self._seen = dict(self.recall('current_seen') or {})
        before = dict(self._seen)
        superseded = _superseded(self._model, self.item.pk, self.launch, self._seen)
        if self._seen != before:
            self.remember('current_seen', dict(self._seen))
        if superseded:
            raise LaunchSuperseded()

    def progress(self, pct: int, msg: str = None) -> None:
        self.check_current()
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


def _notify(item, label: str, nom: str, ok: bool, detail: str = None, *, app_id: str = '') -> None:
    # La fin de tâche COMMUNE (propriétaire : e-mail + dans WAMA ; collaborateurs, E3) — `app_id`
    # fait désigner l'élément par la notification, que relève la passerelle de canaux.
    try:
        from wama.common.utils.notifications import notify_job_end
        notify_job_end(item, app_id, label, nom, ok, detail=detail or '')
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


class ServiceNotReady(Exception):
    """Ce dont le traitement DÉPEND n'est pas encore prêt — un service qui charge (le service TTS
    à son démarrage) : ce n'est pas un échec. La glue la lève, le squelette rend le worker et
    RE-LIVRE la tâche après `countdown` secondes, `max_attempts` fois au plus ; la card reste
    « en cours » et dit qu'elle attend. Au-delà : échec DIT (`gave_up`).

    Extrait le 2026-10-03 (P6) : synthesizer et avatarizer tenaient chacun cette politique
    (60 × 10 s) à la main autour de `self.retry()` — et avec `exc=` passé à `retry`, Celery
    relève l'exception d'ORIGINE à l'épuisement, pas `MaxRetriesExceededError` : la branche
    « abandon » n'était jamais prise, l'élément restait « en cours » pour toujours."""

    def __init__(self, message: str, *, countdown: int = 10, max_attempts: int = 60,
                 gave_up: str = ''):
        super().__init__(message)
        self.countdown = int(countdown)
        self.max_attempts = int(max_attempts)
        self.gave_up = gave_up

    def abandon_message(self) -> str:
        """Ce que dit l'échec quand l'attente s'épuise — le squelette et `redeliver_later`."""
        return self.gave_up or f"{self} : abandon après {self.max_attempts} tentatives."


def redeliver_later(task, wait: ServiceNotReady):
    """HORS squelette (une tâche Celery qui n'est pas celle d'une card : nœud du studio, analyse du
    cam_analyzer) : la politique du squelette — la tâche est re-livrée après `wait.countdown`, et
    l'attente épuisée échoue en DISANT pourquoi (`abandon_message`).

    Extrait le 2026-10-18 (revérification) : studio et cam_analyzer recopiaient
    `raise task.retry(...)` autour de `ServiceNotReady`, sans la branche d'abandon — l'échec disait
    alors « Can't retry <tâche>[…] » (`MaxRetriesExceededError`), jamais le motif."""
    from celery.exceptions import MaxRetriesExceededError
    try:
        raise task.retry(countdown=wait.countdown, max_retries=wait.max_attempts)
    except MaxRetriesExceededError:
        raise RuntimeError(wait.abandon_message()) from None


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
        from wama.accounts.permissions import is_admin_tier
        # « un admin » = le NIVEAU du profil (2026-10-21) — il lisait le drapeau `is_staff`.
        user = get_user_model().objects.filter(pk=uid).first()
        return user is not None and is_admin_tier(user)
    except Exception:
        return False


#: Durée de vie de la mémoire d'un lancement au cache — elle se retire à sa fin réelle ; la durée
#: ne sert qu'au lancement interrompu sans fin (worker tué), que le suivant nettoie aussi.
LAUNCH_TTL_S = 24 * 3600


def _launch_key(app_id: str, item_id) -> str:
    return f"wama:launch:{app_id}:{item_id}"


def _close_launch(app_id: str, item_id, launch: str = None) -> None:
    """Fin d'un lancement : sa mémoire s'oublie. `launch` : ne fermer que CE lancement (une tâche
    finissante ne ferme jamais celle d'un lancement plus récent) ; None : quel qu'il soit (le
    reste d'un lancement interrompu)."""
    key = _launch_key(app_id, item_id)
    entry = cache.get(key) or {}
    if not entry or (launch is not None and entry.get('task') != launch):
        return
    cache.delete(key)


class _HandOver(Exception):
    """La tâche se RE-LIVRE (`task.retry`) : attente de VRAM, ou process suivant sur une autre file.
    Porte le signal de Celery jusqu'à la sortie du squelette — sans quoi le filet « une exception
    = FAILURE » le prendrait pour un échec du process."""

    def __init__(self, signal):
        super().__init__(str(signal))
        self.signal = signal


def _retry(task, **options):
    """`task.retry(...)`, levé ENVELOPPÉ (`_HandOver`) — le signal de Celery traverse la boucle
    des process sans être compté comme un échec."""
    try:
        raise task.retry(**options)
    except _HandOver:
        raise
    except Exception as signal:
        raise _HandOver(signal) from None


def queue_of(spec, gpu: bool = None) -> str | None:
    """La FILE Celery où se joue ce process : la file GPU pour un process qui sollicite la carte
    (`ProcessSpec.gpu`), la file par défaut sinon (2026-10-14, décision de Fabien : une conversion
    CPU ne réserve pas la file GPU, un post-traitement IA ne la contourne pas). None pour une glu
    sans déclaration (`spec` None, app à un seul process sans pipeline) : rien ne se déplace.
    `gpu` : ce que le squelette a décidé pour CE lancement (`_holds_the_card`) — le drapeau
    déclaré sinon."""
    if spec is None:
        return None
    from django.conf import settings
    from wama.common.services.global_queue import GPU_QUEUE
    gpu = spec.gpu if gpu is None else gpu
    return GPU_QUEUE if gpu else getattr(settings, 'CELERY_TASK_DEFAULT_QUEUE', 'default')


def _holds_the_card(spec, card_remote: bool) -> bool:
    """CE process tient-il la carte, pour CE lancement ? Le drapeau déclaré (`ProcessSpec.gpu` ;
    une glu sans déclaration compte GPU), sauf quand il emploie le modèle de la card
    (`card_model` — une glu sans déclaration l'emploie par définition) et que ce modèle a été
    tiré DISTANT (`ROADMAP §8d` étape 4, décision de Fabien du 2026-10-14 : « si la tâche est
    prévue en distant, il ne faut pas réserver de créneau »)."""
    declared = spec is None or spec.gpu
    uses_card_model = spec is None or spec.card_model
    return declared and not (uses_card_model and card_remote)


def _delivered_on(task) -> str:
    """La file d'où vient CETTE livraison ('' hors worker : appel direct, test)."""
    info = getattr(getattr(task, 'request', None), 'delivery_info', None) or {}
    return str(info.get('routing_key') or '')


def _hand_over_to(task, app_id: str, queue: str, ctx) -> None:
    """Re-livre la tâche sur `queue`, tout de suite : le process suivant se joue là-bas. Même
    geste que l'attente de VRAM (`task.retry`, même identifiant de tâche) — les process déjà
    rendus ne se rejouent pas (`steps_to_run`), leurs lignes portent la tâche (`plan`).

    La PRIORITÉ est celle que le gouverneur donne à l'app — la source même des routes Celery
    (`settings.CELERY_TASK_ROUTES`, `_prio(<app>)`), lue sur le label de l'app du modèle
    (l'audio de l'enhancer y est `enhancer`, comme sa route). Jamais celle de la livraison :
    MESURÉ sur un worker jetable (2026-10-14, celery 5.5.3), un message envoyé SANS priorité se
    relit `priority: 0` — le palier le plus prioritaire. La reprendre ferait entrer un message
    du converter (file par défaut, sans priorité) devant toute la file GPU. Une option passée
    l'emporte sur celle de la livraison (`app/task.py:629-651`, `canvas.py:341`, mesuré aussi)."""
    from wama.common.services.resource_governor import celery_priority_for
    priority = celery_priority_for(ctx.item._meta.app_label)
    ctx.console(f"Étape suivante sur la file « {queue} ».", level='info')
    logger.info("[%s] item #%s : re-livré sur la file %s", app_id, ctx.item.pk, queue)
    _retry(task, queue=queue, priority=priority, countdown=0,
           max_retries=WAIT_RETRIES_UNLIMITED)


def _vram_need(item, vram_needed, model_key):
    """Besoin VRAM du process GPU qui va partir : celui que l'app DÉCLARE (`vram_needed`), sinon
    celui de son modèle au catalogue (`auto_model.vram_needed_gb`, la cascade commune — mesurée,
    source, déclarée, preset), MOINS ce que ce worker en tient déjà (`resident_here_gb`) : un
    process qui suit un autre sur le même modèle ne le redemande pas. None : rien à attendre.

    Le besoin DÉRIVÉ de `model_key` est du 2026-10-14 : le composer et l'enhancer le déclaraient
    à la main, à l'identique (`vram_needed_gb(model_key(élément))`) ; les autres apps qui disent
    leur modèle (transcriber, imager) n'attendaient rien. ⚠ C'est le modèle de la CARD : un
    process qui en charge un autre (la diarisation après la transcription) se le voit appliquer
    — le décompte de ce que le worker tient en retire l'essentiel."""
    need = None
    if vram_needed is not None:
        try:
            need = vram_needed(item) if callable(vram_needed) else float(vram_needed)
        except Exception as exc:
            logger.warning("besoin VRAM illisible (%s) — on tente sans différer", exc)
            return None
    elif model_key:
        from wama.common.utils.auto_model import vram_needed_gb
        need = vram_needed_gb(model_key)
    if not need:
        return None
    if model_key:
        from wama.common.services.resource_governor import resident_here_gb
        need = float(need) - resident_here_gb(model_key)
    return float(need) if need > 0 else None


def _launch_done(pipeline, item, task_ref: str, steps) -> tuple[int, float, list]:
    """Ce que CE lancement a déjà rendu lors d'une livraison PRÉCÉDENTE (re-livraison vers une
    autre file, attente de VRAM au milieu du pipeline) : `(parts de barre, secondes mesurées,
    modèles employés)`. Les lignes le disent — un process rendu porte la tâche du lancement
    (`plan`), et Celery garde l'identifiant d'une tâche à travers ses re-livraisons. Sans ce
    report, la barre repartirait de zéro à chaque changement de file, `processing_seconds` (les
    durées que lit la file globale) ne compterait que la dernière livraison, et le signal
    `produit` perdrait les modèles des process déjà joués."""
    from wama.common.models import JOB_SUCCESS
    if pipeline is None or not task_ref:
        return 0, 0.0, []
    playing = {spec.key for *_x, spec in steps if spec is not None}
    shares, seconds, models = 0, 0.0, []
    rows = pipeline.rows(item)
    for spec in pipeline.ordered():
        row = rows.get(spec.key)
        if (spec.key not in playing and row is not None and row.task_id == task_ref
                and row.status == JOB_SUCCESS):
            shares += spec.share
            seconds += float(row.duration_s or 0.0)
            if row.model_key and row.model_key not in models:
                models.append(row.model_key)
    return shares, seconds, models


def _differer_faute_de_vram(task, ctx, item, model, item_id, app_id, besoin_gb,
                            error_field, *, node=None, process_key=''):
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
    Depuis le 2026-10-14 l'attente se décide AU PROCESS (le squelette l'appelle avant chaque
    process GPU) : `node` / `process_key` désignent sa ligne, qui dit l'attente. Jusque-là elle
    se décidait avant le premier process, et une card à pipeline n'écrivait aucune ligne — « on
    ne sait pas quel process partira le premier ».
    """
    from celery.exceptions import MaxRetriesExceededError
    from wama.common.models import JOB_AWAITING_RESOURCES
    from wama.common.services import process_runs
    from wama.common.services import resource_governor as gov

    node = node or process_runs.MAIN_NODE
    process_key = process_key or app_id
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
        process_runs.safely(process_runs.fail, item, node, msg, process_key=process_key)
        ctx.console(f"✗ {msg}", level='error')
        _notify(item, app_id.title(), _item_label(item, item_id), False, detail=msg, app_id=app_id)
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
    process_runs.safely(process_runs.await_resources, item, node, process_key=process_key,
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
        process_runs.safely(process_runs.fail, item, node, msg, process_key=process_key)
        ctx.console(f"✗ {msg}", level='error')
        _notify(item, app_id.title(), _item_label(item, item_id), False, detail=msg, app_id=app_id)
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
    """ETA d'UN process (`(clé, taille, unité[, modèle chargé])` rendu par sa glu — la forme que
    lit aussi la vue de progression), best-effort."""
    if not eta:
        return
    try:
        from wama.model_manager.services.eta_estimator import record_run
        key, size, unit = eta[:3]
        record_run(key, size=size, unit=unit, process_seconds=seconds, load_seconds=None,
                   user=getattr(item, 'user', None))
    except Exception:
        pass


def _line_summary(res: dict, spec=None, item=None):
    """Ce que la ligne d'exécution retient du retour d'une glu : son nom lisible, et l'EMPREINTE
    de sa sortie quand ce n'est pas un fichier (`output_fingerprint` — le texte d'une
    transcription : c'est ce qui périme l'aval quand cette sortie est remplacée)."""
    summary = {}
    if res.get('label'):
        summary['label'] = res['label']
    if res.get('output_fingerprint'):
        summary['fingerprint'] = str(res['output_fingerprint'])
    # La TAILLE sur laquelle la durée de la ligne est mesurée (2026-10-05) — celle de l'ETA que la
    # glu apprend, sinon celle que DÉCLARE le process (`ProcessSpec.eta`, lue sur l'élément tel que
    # la glu le laisse : une glu qui apprend elle-même, chargement à part, ne rend pas d'`eta`).
    # C'est ce qui met cette durée à l'échelle quand le process est relancé sur une taille
    # différente (`process_runs.row_eta_seconds`, règle des passes du cam_analyzer).
    from wama.common.services import process_runs
    eta = res.get('eta')
    if not eta and spec is not None and item is not None:
        eta = process_runs.process_eta(spec, item)
    if eta and len(eta) >= 2 and eta[1]:
        summary[process_runs.ETA_SIZE_KEY] = round(float(eta[1]), 3)
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
                  error_field: str = 'error_message',
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

    # ── Ressources : AU GRAIN DU PROCESS (2026-10-14) ────────────────────────────────────
    # L'attente de VRAM, la déclaration « tâche GPU en cours » et la FILE se décident désormais
    # avant chaque process, selon ce qu'il est (`ProcessSpec.gpu`) — plus avant la card entière.
    # Décision de Fabien : une conversion CPU ne réserve pas la carte, un post-traitement IA ne
    # la contourne pas ; « contrôler chaque process individuellement ». C'est la route écrite
    # (`ROUTE §10.6` 4.5 : « attente de ressources (gouverneur), ETA par process » ; nuance du
    # 15/09 : `vram_needed` « à déclarer au grain du process »), dont seule l'ETA était livrée.
    # ⚠ Corrigé le 2026-09-14 : un commentaire disait « avant `ctx.progress(0)` qui bascule
    # l'item en RUNNING » — faux, `TaskContext.progress` n'écrit que le cache et `progress`.
    # RUNNING est posé par les VUES de lancement, avant `.delay()`.
    from wama.common.models import JOB_AWAITING_RESOURCES, JOB_RUNNING
    essais = int(getattr(getattr(task, 'request', None), 'retries', 0) or 0)
    if essais and getattr(item, 'status', None) not in (JOB_AWAITING_RESOURCES, JOB_RUNNING):
        # RE-LIVRAISON (`task.retry` : attente de VRAM, ou process suivant sur une autre file)
        # alors que l'item n'attend plus et ne tourne plus : l'utilisateur l'a annulé, supprimé
        # de la file ou relancé autrement entre-temps. Le traiter quand même ferait tourner ce
        # qu'il a arrêté.
        logger.info("[%s] item #%s : report abandonné (statut %s, plus en attente de ressources)",
                    app_id, item_id, getattr(item, 'status', None))
        return

    # Un item RE-LIVRÉ après un report ne repasse par aucune vue de lancement : sans ce geste,
    # il resterait affiché « En attente de ressources » pendant tout son traitement. Seul ce
    # cas bascule — un item PENDING n'est jamais mis en cours ici.
    if getattr(item, 'status', None) == JOB_AWAITING_RESOURCES:
        model.objects.filter(pk=item_id, status=JOB_AWAITING_RESOURCES).update(status=JOB_RUNNING)
        item.status = JOB_RUNNING

    ctx.launch = getattr(getattr(task, 'request', None), 'id', '') or ''
    try:
        # Un élément SUPPRIMÉ ou déjà quitté par ce lancement (re-livraison) ne redémarre pas.
        ctx.check_current(force=True)
    except LaunchSuperseded:
        logger.info("[%s] item #%s : lancement %s remplacé ou arrêté avant de démarrer",
                    app_id, item_id, ctx.launch)
        return
    if not essais:
        # Une RE-LIVRAISON garde sa barre : ce que le lancement a déjà rendu y est compté
        # (`_launch_done`), elle ne repart pas de zéro à chaque changement de file.
        ctx.progress(0)
        # Un NOUVEAU lancement : le reste d'un lancement interrompu sans fin (worker tué) part.
        stale = cache.get(_launch_key(app_id, item_id)) or {}
        if stale and stale.get('task') != ctx.launch:
            _close_launch(app_id, item_id)

    # ── Le MODÈLE de la card : installé PAR LA ROUTE avant de servir (2026-10-16) ────────────
    # `model_key` est OPTIONNEL et se déclare comme `vram_needed` : une chaîne, ou un callable
    # qui la tire de l'item (le champ varie — `model`, `ai_model`, `backend`, `tts_model` : la
    # convention n'existe pas, on ne la devine donc pas). L'installation elle-même se joue dans
    # le `try` ci-dessous (`model_readiness.ensure_installed`) : son attente et son refus y ont
    # leur traitement commun. Ici, on ne fait que lire la clé.
    # Re-livrée, la tâche garde le modèle que SON lancement a retenu : un « auto » retiré à chaque
    # livraison pourrait en tirer un autre — et en décider autrement des process qui en dépendent.
    resolved_key = ctx.recall('model_key') if essais else None
    if resolved_key is None and model_key is not None:
        try:
            resolved_key = model_key(item) if callable(model_key) else str(model_key)
        except Exception as exc:
            logger.debug('[%s] clé de modèle illisible : %s', app_id, exc)
        if resolved_key is not None:
            ctx.remember('model_key', resolved_key)
    ctx.model_key = resolved_key
    #: Une glu qui tire un modèle SECONDAIRE (celui d'un process) appelle la même brique avec ce
    #: drapeau : une installation échouée se dit au retour d'une attente au lieu d'être relancée.
    ctx.redelivered = bool(essais)

    # L'entrée d'une card créée avec une URL est téléchargée DÈS LA CRÉATION (`source_ingest`,
    # 2026-10-13) ; ici, le rattrapage : un téléchargement échoué est retenté, un téléchargement
    # en cours est ATTENDU. Les champs propres à l'app viennent du `derive` déclaré par la spec.
    try:
        from wama.common.utils.source_ingest import ensure_local_input
        ensure_local_input(item, console=ctx.console)
    except Exception as exc:
        logger.warning(f"[{app_id}] ensure_local_input({item_id}) : {exc}")

    t0 = time.time()
    label_app = notify_label or app_id.title()
    # La TÂCHE EN COURS se déclare au gouverneur (B1, 2026-09-20) : jusque-là « une tâche GPU
    # tourne » ne se lisait que dans les statuts RUNNING des tables d'app — invisible du
    # gouverneur, donc de l'attente des autres. La ligne expire avec la durée max du traitement.
    # Depuis le 2026-10-14 elle se pose autour de chaque process GPU (`token`, dans la boucle).
    from wama.common.services import resource_governor as gov
    # Le MODÈLE peut porter sa durée max (réglée au model manager, 2026-09-24) : une vidéo longue
    # dépasse légitimement le défaut de 30 min.
    limit_s = gov.task_time_limit_s(app_id, getattr(item, 'user', None), model_key=resolved_key)
    token = None
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
    #: Le lancement CONTINUE ailleurs (re-livraison) : sa mémoire et ses fichiers restent.
    continues = False
    try:
        # Le modèle de la card absent : la ROUTE l'installe (garde d'espace, journal, jeton), la
        # card le dit, la tâche rend son worker et revient (`ServiceNotReady`) — décision de Fabien
        # du 2026-10-16, `model_readiness`. HORS du garde de durée : un téléchargement de 20 Go
        # n'est pas du temps de traitement.
        ctx.ensure_model(resolved_key)
        with _time_guard(limit_s):
            if pipeline is not None and only is None:
                # Relance COMPLÈTE : ce qu'un process désactivé avait rendu quitte la card, libéré
                # et annoncé (`AppPipeline.release_absent`, décision de Fabien du 2026-10-22).
                process_runs.safely(pipeline.release_absent, item)
            steps = _selected_steps(app_id, item, process, pipeline, processes, resolved_key,
                                    only=only)
            # Ce que chaque process avait RENDU, lu AVANT que le plan ne repasse ses lignes en
            # attente : la photo de son dernier succès (ou d'un succès devenu périmé), offerte à
            # sa glu (`ctx.previous_snapshot`) pour qu'elle sache ce qui a changé depuis. Après une
            # re-livraison, le plan de la 1ʳᵉ livraison est déjà posé : `rendered_before` reconnaît
            # les lignes que CE lancement a annoncées (2026-10-14, mesuré sur le live).
            prior = ({key: row for key, row in pipeline.rows(item).items()
                      if process_runs.rendered_before(row, task_ref)}
                     if pipeline is not None else {})
            if pipeline is not None:
                # Le PLAN du lancement sur les lignes (2026-10-05) : chaque process retenu passe
                # `PENDING` (« son tour n'est pas venu ») et porte cette tâche. C'est ce qui dit,
                # pendant le traitement, ce que joue CE lancement — un ▶ borné n'en joue qu'une
                # partie — et donc ce que la vue de progression additionne (ETA par process).
                process_runs.safely(process_runs.plan, item,
                                    [(node_, key_, 'function') for node_, key_, *_r in steps],
                                    task_id=task_ref)
            # Ce que le lancement a déjà rendu lors d'une livraison précédente : sa part de barre
            # et ses secondes restent comptées (`_launch_done`).
            done_share, done_seconds, used = _launch_done(pipeline, item, task_ref, steps)
            total_share = (done_share
                           + sum(spec.share if spec is not None else 1 for *_x, spec in steps)) or 1
            written, carried_label = {}, None
            # Le modèle de la card a-t-il été tiré DISTANT ? (étape 4 de `ROADMAP §8d`)
            from wama.model_manager.services.cloud_models import is_cloud_key
            card_remote = is_cloud_key(resolved_key)
            for index, (node, process_key, glue, spec) in enumerate(steps):
                ctx.check_current(force=True)     # arrêté ou relancé entre deux process
                share = spec.share if spec is not None else 1
                # ── Le process sur SA file, avec SA VRAM, déclaré s'il tient la carte ────────
                # Une glu sans déclaration (`spec` None) garde la règle d'avant : elle est
                # comptée GPU, et ne change pas de file.
                gpu = _holds_the_card(spec, card_remote)
                queue = queue_of(spec, gpu)
                delivered = _delivered_on(task)
                if queue and delivered and delivered != queue:
                    _hand_over_to(task, app_id, queue, ctx)
                # Le besoin VRAM est celui du modèle de la card : un process qui n'emploie PAS ce
                # modèle, quand il est distant, n'en hérite pas (son propre besoin n'est pas
                # déclaré — reste nommé à `ROUTE §10.6` 4.5).
                foreign = card_remote and spec is not None and not spec.card_model
                need = (_vram_need(item, None if foreign else vram_needed,
                                   None if foreign else resolved_key) if gpu else None)
                if need:
                    try:
                        refused = _differer_faute_de_vram(
                            task, ctx, item, model, item_id, app_id, need, error_field,
                            node=node, process_key=process_key)
                    except Exception as signal:       # le report : `task.retry`
                        raise _HandOver(signal) from None
                    if refused:
                        return
                if gpu:
                    token = gov.task_started(app_id, item_id, need or 0.0, max_s=limit_s,
                                             process=spec.key if spec is not None else '')
                if spec is not None:
                    ctx.enter_step(spec.key, 100.0 * done_share / total_share,
                                   100.0 * (done_share + share) / total_share)
                    ctx.snapshot = pipeline.snapshot(spec, item)
                    ctx.previous_snapshot = (dict(prior[spec.key].settings_snapshot or {})
                                             if spec.key in prior else None)
                process_runs.safely(
                    process_runs.start, item, node, process_key=process_key,
                    kind='app' if spec is None else 'function',
                    settings_snapshot=ctx.snapshot if spec is not None else None,
                    model_key=resolved_key or '', task_id=task_ref)
                t_step = time.time()
                try:
                    res = glue(item, ctx) or {}
                except (TaskTimeLimitExceeded, ServiceNotReady):
                    # Une ATTENTE n'est pas un échec, même d'un process optionnel : la tâche
                    # revient (2026-10-18 — un modèle qu'un résumé tire s'installait, et la card
                    # l'aurait lu comme un résumé en échec).
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
                finally:
                    # Le process a rendu (ou levé) : il ne tient plus la carte.
                    if token:
                        gov.task_finished(token)
                        token = None
                used += [k for k in (res.get('models') or []) if k and k not in used]
                written.update(res.get('fields') or {})
                if res.get('label'):
                    carried_label = res['label']
                if index == len(steps) - 1:
                    break             # le DERNIER process rend la card : flux de succès ci-dessous
                # Ce que rend un lancement remplacé n'est plus celui de la card : rien ne s'écrit.
                ctx.check_current(force=True)
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
                    output_summary=_line_summary(res, spec, item),
                    # La photo des réglages telle que la glu les LAISSE (elle a pu en ajuster un).
                    settings_snapshot=pipeline.snapshot(spec, item) if spec is not None else None)
                _record_eta(res.get('eta'), time.time() - t_step, item)
                if res.get('label'):
                    ctx.console(res.get('console_success') or f"✓ {res['label']}", level='info')
                done_share += share
        last_model = next((k for k in (res.get('models') or []) if k), None)
        last_summary = _line_summary(res, spec, item)
        last_fields = dict(res.get('fields') or {})
        # Ce que la CARD a produit = ce que tous ses process joués ont écrit et employé ; son nom
        # lisible est le dernier qu'un process a donné (le dernier process peut ne rien nommer).
        res = dict(res, fields=written, models=used or res.get('models'))
        if not res.get('label') and carried_label:
            res['label'] = carried_label
        ctx.check_current(force=True)         # le succès d'un lancement remplacé ne s'écrit pas
        fields = dict(written)
        fields['status'] = 'SUCCESS'
        if _has_field(model, 'progress'):
            fields['progress'] = 100
        if _has_field(model, 'processing_seconds'):
            fields['processing_seconds'] = round(done_seconds + time.time() - t0, 1)
        model.objects.filter(pk=item_id).update(**fields)
        if node is not None:          # None : le dernier process, optionnel, a échoué (ligne déjà dite)
            final_snapshot = None
            if spec is not None:
                for name, value in (last_fields or {}).items():
                    setattr(item, name, value)
                final_snapshot = pipeline.snapshot(spec, item)
            process_runs.safely(process_runs.succeed, item, node, process_key=process_key,
                                output_ref=res.get('output_ref') or '',
                                model_key=last_model, output_summary=last_summary,
                                settings_snapshot=final_snapshot)
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
                          {'secondes': round(done_seconds + time.time() - t0, 1)})
        # RÉVISION (marche 8a) : l'état que ce résultat donne à l'élément, rattaché au fait
        # `produit` — posée ici, elle vaut pour toutes les apps du squelette sans une ligne par app.
        _revision(model, item_id, app_id, outcome, res)
        _notify(item, label_app, nom, True, app_id=app_id)
    except LaunchSuperseded:
        # L'utilisateur a ARRÊTÉ ou RELANCÉ l'élément (`process_control.begin_processing`, après
        # confirmation) : ce lancement se retire sans rien écrire — le statut, les lignes et la
        # barre appartiennent désormais à celui qui l'a remplacé, ou à l'arrêt qui les a posés.
        logger.info("[%s] item #%s : lancement %s remplacé ou arrêté — retiré sans rien écrire",
                    app_id, item_id, ctx.launch)
        ctx.console("Traitement précédent arrêté : il a été remplacé ou interrompu.", level='info')
    except _HandOver as handover:
        # La tâche est RE-LIVRÉE (attente de VRAM, ou process suivant sur l'autre file) : rien
        # n'a échoué. Le signal de Celery sort tel quel — c'est lui qui dit au worker « réessayé ».
        continues = True
        raise handover.signal from None
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
        _notify(item, label_app, nom, False, detail=msg, app_id=app_id)
    except ServiceNotReady as wait:
        # Pas un échec : on rend le worker et on reviendra. La card reste « en cours » (le
        # lanceur l'y a mise) et son message dit l'attente ; la ligne du process, elle, attend.
        from celery.exceptions import MaxRetriesExceededError
        attempt = _deliveries_so_far(task) + 1
        msg = (f"{wait} — nouvelle tentative dans {wait.countdown} s "
               f"({attempt}/{wait.max_attempts})")
        if _has_field(model, error_field):
            model.objects.filter(pk=item_id).update(**{error_field: msg})
        if node is not None:
            process_runs.safely(process_runs.await_resources, item, node,
                                process_key=process_key, task_id=task_ref)
        ctx.console(msg, level='warning')
        logger.info("[%s] item #%s : %s", app_id, item_id, msg)
        try:
            continues = True
            raise task.retry(countdown=wait.countdown, max_retries=wait.max_attempts)
        except MaxRetriesExceededError:
            continues = False
            msg = wait.abandon_message()
            fields = {'status': 'FAILURE'}
            if _has_field(model, error_field):
                fields[error_field] = msg
            model.objects.filter(pk=item_id).update(**fields)
            if node is not None:
                process_runs.safely(process_runs.fail, item, node, msg, process_key=process_key)
            ctx.console(f"✗ {msg}", level='error')
            _signal(item, app_id, 'echec', None, {'erreur': 'service_indisponible'})
            _notify(item, label_app, _item_label(item, item_id), False, detail=msg, app_id=app_id)
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
        _notify(item, label_app, nom, False, detail=msg, app_id=app_id)
    finally:
        if token:                     # un process GPU interrompu hors de sa glu (durée max)
            gov.task_finished(token)
        if not continues:
            _close_launch(app_id, item_id, ctx.launch)
