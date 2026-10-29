"""
WAMA Common — Les vues d'ÉLÉMENT et de FILE : ▶ d'une card, ▶ de la file, 🗑 de la file
(`make_item_views`, `WAMA_APP_GENERATION_ROUTE.md §11 #39`).

Trois vues écrites à la main dans les dix apps jusqu'au 2026-10-29 — trente copies d'un même corps
(`begin_processing`, puis la tâche, puis `task_id`), quatre formes de refus, six vocabulaires de
réponse —, et un QUATRIÈME exemplaire du ▶ dans l'outil `start_<app>` de l'assistant
(`tool_api._triad_fns`), dont la sélection de « tout lancer » avait divergé du bouton dans cinq
apps. Elles sont ici UNE fois, sur le modèle de `make_batch_views` (#36) et de
`make_process_start_view` (#38), dont elles reprennent les crochets et leurs noms.

UN GESTE, DEUX PORTES (la règle du ▶ d'un process, 2026-10-14) : `start_one_item` et
`start_queue` sont le geste ; la vue le traduit en HTTP, l'outil de l'assistant en réponse
d'outil. La fabrique INSCRIT sa déclaration pour le modèle de l'élément (`declaration_for`) :
l'outil la lit au lieu de redire la tâche, la remise à zéro et la sélection — une jumelle générée
qui appelle la fabrique a donc son ▶ d'assistant sans rien déclarer de plus.

Usage (views.py de l'app) :
    from wama.common.utils.item_views import make_item_views
    _iv = make_item_views(work_model=ReadingItem, app_id='reader', task=read_document_task,
                          reset_on_start=_reset_for_relaunch, batch_model=BatchReadingItem)
    start = app_access('reader')(_iv['start'])
    start_all = app_access('reader')(_iv['start_all'])
    clear_all = _iv['clear_all']
"""
import logging
import sys
from dataclasses import dataclass

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from wama.common.utils.progress_views import request_user

logger = logging.getLogger(__name__)

#: Ce que lance « tout lancer » quand l'app ne dit rien : les éléments en attente.
DEFAULT_PENDING = {'status': 'PENDING'}

#: Les éléments EN VOL : en cours, ou déjà partis attendre leurs ressources. « Tout lancer » ne
#: les relance pas, « tout effacer » ne les retire pas (on ne retire pas sous une tâche qui écrit).
IN_FLIGHT = ('RUNNING', 'AWAITING_RESOURCES')

#: Les PÉRIMÈTRES que l'utilisateur choisit au menu ▾ de « tout lancer » (Fabien, 2026-10-29 :
#: « un menu déroulant pour que l'utilisateur précise son choix »). Le clic principal garde la
#: règle que l'app DÉCLARE (`pending` / `pending_exclude`). Clé → (libellé, filtre, exclusion,
#: compteur de la barre de file qui dit combien il en lance — `progress_views.queue_progress`).
START_SCOPES = {
    'pending': ('En attente', {'status': 'PENDING'}, {}, 'pending'),
    'failed': ('Échecs', {'status': 'FAILURE'}, {}, 'failure'),
    'unfinished': ('Non réussis', {}, {'status': 'SUCCESS'}, 'unfinished'),
    'all': ('Tout relancer', {}, {}, 'relaunchable'),
}
#: Les périmètres du menu ▾ de « tout effacer » — le clic principal efface toute la file (hors vol).
CLEAR_SCOPES = {
    'success': ('Terminés', {'status': 'SUCCESS'}, 'success'),
    'failed': ('Échecs', {'status': 'FAILURE'}, 'failure'),
    'pending': ('En attente', {'status': 'PENDING'}, 'pending'),
}


def queue_scopes(action: str) -> list:
    """Les entrées du menu ▾ d'une action de file (`start` | `clear`) : `{key, label, counter}` —
    lues par la barre de file commune (`_queue_actions.html`) ; `counter` est le compteur de la
    barre de progression qui grise une entrée sans objet (`wama-global-progress.js`)."""
    table = START_SCOPES if action == 'start' else CLEAR_SCOPES
    return [{'key': key, 'label': spec[0], 'counter': spec[-1]} for key, spec in table.items()]


@dataclass(frozen=True)
class ItemStart:
    """Ce qu'une app déclare de son ▶ — lu par les vues ET par l'outil de l'assistant."""
    work_model: object
    app_id: str
    task: object = None
    task_for: object = None
    reset_on_start: object = None
    startable: object = None
    unstartable_message: str = ''
    pending: dict = None
    pending_exclude: dict = None
    queryset: object = None
    progress_key: str = ''

    def task_of(self, item):
        return self.task_for(item) if self.task_for is not None else self.task

    def queue(self, user):
        """La FILE de `user` : ce que montre sa barre (`queryset`), sinon ses éléments."""
        if self.queryset is not None:
            return self.queryset(user)
        return self.work_model.objects.filter(user=user)

    def to_start(self, user, scope: str = ''):
        """Ce que lance « tout lancer » : la file, bornée par `pending` / `pending_exclude` — ou par
        le PÉRIMÈTRE choisi au menu (`START_SCOPES`). Jamais un élément en vol."""
        if scope:
            _label, pending, exclude, _counter = START_SCOPES[scope]
        else:
            pending = DEFAULT_PENDING if self.pending is None else self.pending
            exclude = self.pending_exclude or {}
        return (self.queue(user).filter(**pending).exclude(**exclude)
                .exclude(status__in=IN_FLIGHT).order_by('pk'))

    def to_clear(self, user, scope: str = ''):
        """Ce que retire « tout effacer » : la file hors vol, ou le PÉRIMÈTRE choisi (`CLEAR_SCOPES`).
        La MÊME lecture sert la confirmation, qui annonce les fichiers libérés."""
        found = self.queue(user).exclude(status__in=IN_FLIGHT)
        if scope:
            found = found.filter(**CLEAR_SCOPES[scope][1])
        return found.order_by('pk')

    def progress_cache_key(self, pk) -> str:
        return (self.progress_key or f'{self.app_id}_progress_{{pk}}').format(pk=pk)


#: Déclarations inscrites par la fabrique de l'APP, par modèle d'élément.
_DECLARATIONS: dict = {}


def declaration_for(work_model):
    """La déclaration du ▶ de `work_model`, ou None. Inscrite au chargement des vues de son app :
    un processus qui ne les a pas chargées (un worker qui sert l'assistant) les importe ici."""
    found = _DECLARATIONS.get(work_model)
    if found is None:
        import importlib
        try:
            importlib.import_module(f'{work_model._meta.app_config.name}.views')
        except Exception as exc:                  # vues absentes ou cassées : pas de déclaration
            logger.debug('[item_views] vues de %s non chargées : %s', work_model, exc)
        found = _DECLARATIONS.get(work_model)
    return found


def _purge_traces(declaration, pk):
    """Ce qu'un run précédent a laissé au cache : sa progression et son texte partiel — sans
    cette purge, une relance affichait la progression et l'aperçu du run PRÉCÉDENT jusqu'à la
    première écriture de la tâche (purge extraite de la triade du describer, 2026-09-03)."""
    cache.delete(declaration.progress_cache_key(pk))
    try:
        from wama.common.utils.preview_utils import clear_partial
        clear_partial(declaration.app_id, pk)
    except Exception:
        pass


def _reset_with(declaration, settings=None, apply_settings=None, on_queue_settings=None):
    """La remise à zéro du lancement : les réglages postés d'abord (la fonction de réglage de
    l'app, puis ses gestes à effets), puis la remise à zéro qu'elle déclare — sous le verrou de
    `begin_processing`."""
    base = declaration.reset_on_start
    if settings is None or apply_settings is None:
        return base

    def reset(item):
        apply_settings(item, dict(settings))
        if on_queue_settings is not None:
            on_queue_settings(item, dict(settings))
        if callable(base):
            base(item)
        elif base:
            for field, value in base.items():
                setattr(item, field, value)
    return reset


def _launch(declaration, item):
    """Envoie la tâche de l'élément verrouillé et retient son id. Un envoi qui échoue (broker
    absent) rend l'élément à l'attente au lieu de le laisser « en cours » sans tâche."""
    try:
        task = declaration.task_of(item).delay(item.pk)
    except Exception:
        item.status = 'PENDING'
        item.save(update_fields=['status'])
        raise
    item.task_id = task.id
    item.save(update_fields=['task_id'])
    return task


def start_one_item(declaration, pk, *, user, reset=None):
    """Le ▶ d'UN élément : `(élément, tâche, None)`, ou `(None, None, (statut HTTP, message))`.

    Refusé : élément introuvable ou non modifiable par `user` (404) ; non lançable en l'état
    (`startable`, 400, son message) ; déjà en cours (409, la règle du ▶ d'un process)."""
    from wama.common.utils.process_control import begin_processing
    model = declaration.work_model
    if declaration.startable is not None:
        from wama.common.utils.scoping import editable_or_404
        from django.http import Http404
        try:
            current = editable_or_404(model, user, pk=pk)
        except Http404:
            return None, None, (404, 'Élément introuvable')
        if not declaration.startable(current):
            return None, None, (400, declaration.unstartable_message
                                or 'Élément non lançable en l’état')
    item, err = begin_processing(model, pk, user=user,
                                 reset=declaration.reset_on_start if reset is None else reset)
    if err == 'not_found':
        return None, None, (404, 'Élément introuvable')
    if err:
        return None, None, (409, 'Traitement déjà en cours')
    _purge_traces(declaration, item.pk)
    try:
        task = _launch(declaration, item)
    except Exception as exc:
        logger.error('[%s] envoi de la tâche de #%s impossible : %s', declaration.app_id, pk, exc)
        return None, None, (503, 'Tâche non envoyée — le service de traitement est-il lancé ?')
    return item, task, None


def start_queue(declaration, user, *, settings=None, apply_settings=None, on_queue_settings=None,
                scope: str = ''):
    """« Tout lancer » : chaque élément que la déclaration retient, par le geste du ▶.
    `settings` (les réglages postés, posés par `apply_settings`) sont VÉRIFIÉS sur tous les
    éléments avant d'en lancer un seul : un refus (`ValueError`) lève, et rien n'est parti.
    `apply_settings` doit donc rester SANS effet hors de l'élément ; un geste à effets (un fichier
    libéré) passe par `on_queue_settings`, appelé sous le verrou seulement.
    `scope` : le périmètre choisi au menu (`START_SCOPES`) ; vide = la règle que l'app déclare.
    Rend `(lancés, erreurs, sautés)` — sautés : non lançables en l'état (`startable`)."""
    from wama.common.utils.process_control import begin_processing
    candidates = list(declaration.to_start(user, scope))
    skipped = []
    if declaration.startable is not None:
        skipped = [item.pk for item in candidates if not declaration.startable(item)]
        candidates = [item for item in candidates if item.pk not in skipped]
    if settings is not None and apply_settings is not None:
        for item in candidates:                       # sur des copies : rien n'est sauvé ici
            apply_settings(item, dict(settings))
    reset = _reset_with(declaration, settings, apply_settings, on_queue_settings)
    started, errors = [], []
    for candidate in candidates:
        item, err = begin_processing(declaration.work_model, candidate.pk, user=user, reset=reset)
        if err:
            continue                                  # déjà en cours, ou parti entre-temps
        _purge_traces(declaration, item.pk)
        try:
            _launch(declaration, item)
        except Exception as exc:
            errors.append({'id': item.pk, 'error': str(exc)})
            continue
        started.append(item.pk)
    return started, errors, skipped


def discard_element(item, *, progress_key='', on_delete=None):
    """Retirer UN élément de la file : révoquer sa tâche en file, ce que l'app sait de lui
    (`on_delete`), son cache de progression, LIBÉRER ses fichiers, puis la ligne — le geste de
    `batch_delete`, et celui de « tout effacer »."""
    from wama.common.utils.queue_duplication import release_card_files
    task_id = getattr(item, 'task_id', '') or ''
    if task_id:
        try:
            from celery import current_app
            current_app.control.revoke(task_id, terminate=False)
        except Exception:
            pass
    if on_delete is not None:
        on_delete(item)
    if progress_key:
        cache.delete(progress_key.format(pk=item.pk))
    release_card_files(item)
    item.delete()


def make_item_views(*, work_model, app_id: str, task=None, task_for=None,
                    get_user=request_user, reset_on_start=None, startable=None,
                    unstartable_message: str = '', pending=None, pending_exclude=None,
                    queryset=None, progress_key: str = '', queue_settings=None,
                    apply_settings=None, on_queue_settings=None, on_delete=None,
                    batch_model=None, items_related: str = 'items'):
    """Les vues `start(request, pk)`, `start_all(request)` et `clear_all(request)` d'une app.

    Args:
        work_model      : le modèle de l'élément de file.
        app_id          : préfixe de la clé de cache de progression publiée par le squelette de
                          tâche (`<app>_progress_<pk>`), purgée au lancement et au retrait.
        task / task_for : la tâche Celery de l'élément (`.delay(pk)`), ou callable(élément) ->
                          tâche quand elle dépend de l'élément (imager : image ou vidéo) — les
                          crochets de `make_batch_views`.
        get_user        : callable(request) -> utilisateur ; défaut : connecté, sinon anonyme.
        reset_on_start  : dict champ→valeur ou callable(élément) — la remise à zéro du ▶,
                          appliquée SOUS le verrou (`begin_processing`).
        startable       : callable(élément) -> bool — un élément non lançable en l'état
                          (converter : sans format de sortie) ; le ▶ le refuse en 400 avec
                          `unstartable_message`, « tout lancer » le saute.
        pending / pending_exclude : ce que lance « tout lancer » — les noms de `TRIAD_SPECS`.
                          Défaut : les éléments EN ATTENTE. `{}` = toute la file.
        queryset        : callable(user) -> la FILE (converter : sans ses jobs éphémères) — le
                          crochet de `make_progress_views` ; « tout lancer » et « tout effacer »
                          portent sur elle.
        progress_key    : gabarit de la clé de progression quand ce n'est pas
                          `<app>_progress_{pk}` (anonymizer : `media_progress_{pk}`).
        queue_settings  : callable(request, user) -> dict — les réglages que « tout lancer »
                          POSTE et applique à chaque élément lancé (enhancer, synthesizer :
                          « démarrer tout vaut appliquer à tout »), posés par `apply_settings`,
                          LA fonction de réglage de l'élément (celle de `make_batch_views`). Une
                          `ValueError` de l'un ou de l'autre = 400, rien n'est lancé.
                          ⚠ `apply_settings` sert aussi à la VÉRIFICATION préalable : il ne
                          doit rien toucher hors de l'élément.
        on_queue_settings : callable(élément, réglages) — le geste À EFFETS qui accompagne ces
                          réglages (synthesizer : la voix de référence remplacée, l'ancienne
                          LIBÉRÉE), fait sous le verrou seulement, jamais à la vérification.
        on_delete       : callable(élément) appelé avant le retrait (verrous, fichiers hors
                          champ) — le crochet de `make_batch_views`.
        batch_model     : le modèle de lot : « tout effacer » retire aussi les lots devenus vides.

    « Tout effacer » retire la FILE, sauf les éléments EN VOL (`IN_FLIGHT`) : on ne retire pas sous
    une tâche qui écrit encore (elle se stoppe d'abord, ⏹) — la règle du composer, qui la seule
    tenait. Les deux actions de file acceptent un PÉRIMÈTRE (`?scope=`, menu ▾ de la barre
    commune, `START_SCOPES` / `CLEAR_SCOPES`) ; sans lui, la règle de l'app.
    """
    declaration = ItemStart(
        work_model=work_model, app_id=app_id, task=task, task_for=task_for,
        reset_on_start=reset_on_start, startable=startable,
        unstartable_message=unstartable_message, pending=pending,
        pending_exclude=pending_exclude, queryset=queryset, progress_key=progress_key)
    # Seule la fabrique de l'APP inscrit sa déclaration (appelée depuis un module de l'app qui
    # porte le modèle, hors tests) — la règle de `make_batch_views` pour le nommage des ZIP.
    caller = sys._getframe(1).f_globals.get('__name__', '')
    owner = work_model._meta.app_config.name
    if (caller == owner or caller.startswith(owner + '.')) and '.tests' not in caller:
        _DECLARATIONS[work_model] = declaration

    def _refusal(refused):
        status, message = refused
        return JsonResponse({'error': message}, status=status)

    @require_POST
    def start(request, pk):
        item, task_sent, refused = start_one_item(declaration, pk, user=get_user(request))
        if refused:
            return _refusal(refused)
        return JsonResponse({'success': True, 'id': item.pk, 'task_id': task_sent.id,
                             'status': 'RUNNING'})

    def _scope(request, table):
        """Le périmètre choisi au menu ▾ (`?scope=`), '' pour le clic principal ; un périmètre
        inconnu est REFUSÉ (400) plutôt que de retomber en silence sur toute la file."""
        scope = (request.GET.get('scope') or '').strip()
        if scope and scope not in table:
            raise ValueError(f"périmètre inconnu : {scope} — attendus : {', '.join(table)}")
        return scope

    @require_POST
    def start_all(request):
        user = get_user(request)
        settings = None
        try:
            scope = _scope(request, START_SCOPES)
            if queue_settings is not None:
                settings = queue_settings(request, user)
            started, errors, skipped = start_queue(declaration, user, settings=settings,
                                                   apply_settings=apply_settings,
                                                   on_queue_settings=on_queue_settings,
                                                   scope=scope)
        except ValueError as refusal:
            return JsonResponse({'error': str(refusal)}, status=400)
        return JsonResponse({'success': True, 'started': started, 'count': len(started),
                             'errors': errors, 'skipped': skipped})

    @require_POST
    def clear_all(request):
        user = get_user(request)
        try:
            scope = _scope(request, CLEAR_SCOPES)
        except ValueError as refusal:
            return JsonResponse({'error': str(refusal)}, status=400)
        key = progress_key or f'{app_id}_progress_{{pk}}'
        removed = 0
        for item in list(declaration.to_clear(user, scope)):
            discard_element(item, progress_key=key, on_delete=on_delete)
            removed += 1
        if batch_model is not None:
            # Les lots VIDÉS par ce retrait sont purgés par le signal du lot ; restent ceux qui
            # n'avaient aucun élément — retirés comme `batch_delete` retire un lot, fichier compris.
            from wama.common.services import batch_identity, batch_settings
            from wama.common.utils.queue_duplication import release_card_files
            for empty in batch_model.objects.filter(user=user, **{f'{items_related}__isnull': True}):
                batch_settings.forget(empty)
                batch_identity.forget(empty)
                release_card_files(empty)
                empty.delete()
        return JsonResponse({'success': True, 'deleted': removed})

    return {'start': start, 'start_all': start_all, 'clear_all': clear_all}
