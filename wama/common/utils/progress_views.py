"""
WAMA Common — Les VUES DE PROGRESSION : fabrique commune (`make_progress_views`).

Deux vues par app, écrites à la main dans les dix jusqu'au 2026-10-03 (`ROUTE §11 #37`) :

  - `progress(request, pk)` — le suivi d'UNE card : même squelette partout (lecture par
    `visible_or_404`, progression du cache `<app>_progress_<id>` sinon de la base, statut, erreur,
    ETA par `eta_estimator.estimate`), autour duquel chaque app ajoutait ses clés propres ;
  - `global_progress(request)` — la barre de file : chacune recomptait total / en cours /
    terminés / échoués avec TROIS formules de progression d'ensemble et QUATRE vocabulaires de
    clés (`done`/`success`, `failed`/`failure`/`error`), que le JS commun
    `wama-global-progress.js` absorbait en acceptant toutes les graphies.

La fabrique rend UNE formule et un payload au vocabulaire COMPLET ; les spécificités d'app sont
des crochets (le modèle de `make_batch_views`, `ROUTE §11 #36`, dont elle reprend `progress_of`).

UNE FORMULE de progression d'ensemble — celle du CONTRAT de la barre commune, pas une neuve :
`wama-global-progress.js` dérive `done / total` quand l'endpoint ne la donne pas, et sa ligne de
stats sépare « terminé » et « échoué ». Un élément RÉUSSI compte 100, un élément EN COURS sa
progression vivante (cache puis base), tout autre élément 0 — un échec n'est pas terminé. C'est
la formule de l'app de référence (describer) ; les écarts mesurés le 2026-10-03 (un échec compté
100 par le composer, ou à sa progression par d'autres) étaient des dérives, pas des choix.

Usage (views.py de l'app) :
    from wama.common.utils.progress_views import make_progress_views
    _pv = make_progress_views(work_model=Description, get_user=get_user, app_id='describer',
                              eta_for=_eta_triplet, extra=_progress_extra)
    progress, global_progress = _pv['progress'], _pv['global_progress']
"""
from django.core.cache import cache
from django.http import JsonResponse

#: Ce qui reçoit une estimation de durée (un élément terminé n'a plus rien à estimer).
IN_FLIGHT = ('PENDING', 'RUNNING')


def _bounded(value) -> int:
    try:
        return max(0, min(100, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def queue_progress(rows) -> dict:
    """Les compteurs d'une file et sa progression d'ensemble, au vocabulaire COMPLET.
    `rows` : itérable de `(statut, progression vivante)`."""
    total = pending = running = success = failure = 0
    acc = 0
    for status, live in rows:
        total += 1
        if status == 'SUCCESS':
            success += 1
            acc += 100
        elif status == 'FAILURE':
            failure += 1
        elif status == 'RUNNING':
            running += 1
            acc += live
        else:
            pending += 1
    return {
        'total': total, 'pending': pending, 'running': running,
        'success': success, 'failure': failure,
        # Alias du contrat de `wama-global-progress.js` (`done`/`failed`) : les deux graphies
        # sont ÉMISES, le JS n'a plus à en deviner une.
        'done': success, 'failed': failure,
        'overall_progress': int(acc / total) if total else 0,
    }


def request_user(request):
    """L'utilisateur d'une requête de file : le compte connecté, sinon le compte anonyme partagé
    — la règle des dix apps (chacune la réécrivait dans son `_get_user`) et du générateur."""
    if request.user.is_authenticated:
        return request.user
    from wama.accounts.views import get_or_create_anonymous_user
    return get_or_create_anonymous_user()


def make_progress_views(*, work_model, app_id: str, get_user=request_user,
                        progress_field: str = 'progress',
                        progress_of=None, error_field: str = 'error_message', eta_for=None,
                        eta_fallback=None, extra=None, pipeline_model=None, queryset=None,
                        domains=None, read_lookup=None):
    """Les deux vues de progression d'une app : `{'progress': vue(request, pk),
    'global_progress': vue(request)}`.

    Args:
        work_model     : le modèle de l'élément de file (porte `status`, la progression, l'erreur).
        get_user       : callable(request) -> utilisateur ; défaut `request_user` (connecté, sinon
                         anonyme). Le converter passe `request.user` (vues `@login_required`).
        app_id         : préfixe de la clé de cache publiée par le squelette de tâche
                         (`<app>_progress_<pk>`, `task_skeleton.TaskContext.progress`).
        progress_field : champ de progression ENREGISTRÉE (anonymizer : `blur_progress`).
        progress_of    : callable(élément) -> progression VIVANTE, quand elle n'est pas au cache
                         `<app>_progress_<pk>` sous forme d'entier — même crochet que
                         `make_batch_views` (reader : un dict `{'pct': …}` ; anonymizer : la clé
                         `media_progress_<pk>`). Reçoit l'élément, ou pour la barre de file une
                         ligne qui porte `pk`, `id` et le champ enregistré.
        error_field    : champ du message d'échec.
        eta_for        : callable(élément) -> `(clé, taille, unité)` ou `(clé, taille, unité,
                         modèle_chargé)` — le triplet que l'app passe à `eta_estimator.estimate`,
                         déclaré une fois. Absent ou `None` rendu : pas d'estimation.
                         ⚠ Une card à process dont les process déclarent leur ETA
                         (`ProcessSpec.eta`) est estimée par `process_runs.launch_eta` — la
                         somme de ce que joue le lancement ; `eta_for` ne sert plus qu'aux apps à
                         un seul process.
        eta_fallback   : callable(élément) -> secondes, quand l'estimation apprise est vide
                         (composer : durée × `gen_factor` du catalogue + surcoût).
        extra          : callable(élément) -> dict — les clés PROPRES que le JS de l'app lit
                         (URLs de résultat, texte partiel, réglages affichés…). Fusionnées en
                         dernier : elles complètent le payload commun.
        pipeline_model : à ne passer que pour s'ÉCARTER du modèle déclaré par le pipeline de
                         l'app (`register_app_pipeline(model_of=…)`, lu par défaut) :
                         callable(élément) -> clé de modèle passée à `card_view`. Sans pipeline,
                         ni `processes` ni `shown_state`.
        queryset       : callable(user) -> les éléments que compte la barre de file ; défaut :
                         ceux de l'utilisateur (`filter(user=user)`).
        domains        : dict `{nom: callable(queryset) -> queryset}` — barres PAR DOMAINE
                         (imager : image / vidéo). Le payload porte chaque domaine sous son nom,
                         et le PREMIER à plat (les clés historiques de la page).
        read_lookup    : callable(user, pk) -> élément, quand la lecture n'est pas
                         `visible_or_404(work_model, user, pk=pk)`.
    """

    def _live(item):
        if progress_of is not None:
            try:
                return _bounded(progress_of(item))
            except Exception:
                pass
        cached = cache.get(f'{app_id}_progress_{item.pk}')
        return _bounded(cached if cached is not None else getattr(item, progress_field, 0))

    def _estimate(item):
        # Une card à PROCESS dont les process déclarent leur ETA (`ProcessSpec.eta`) : la somme
        # de ceux que ce lancement joue (2026-10-05). Un seul triplet par app donnait au rendu
        # seul du composer la durée d'une partition + d'un rendu, et à une transcription
        # diarisée celle de la seule transcription.
        from wama.common.services.process_runs import launch_eta
        try:
            seconds = launch_eta(item) or 0.0
        except Exception:
            seconds = 0.0
        if seconds:
            return seconds
        if eta_for is not None:
            try:
                triplet = eta_for(item)
            except Exception:
                triplet = None
            if triplet:
                from wama.model_manager.services.eta_estimator import estimate
                key, size, unit = triplet[:3]
                loaded = triplet[3] if len(triplet) > 3 else True
                try:
                    seconds = float(estimate(key, size=size, unit=unit, model_loaded=loaded) or 0)
                except Exception:
                    seconds = 0.0
        if not seconds and eta_fallback is not None:
            try:
                seconds = float(eta_fallback(item) or 0)
            except Exception:
                seconds = 0.0
        return seconds if seconds > 0 else None

    def _pipeline(item):
        from wama.common.services.process_pipeline import card_view, pipeline_of
        if pipeline_of(item) is None:
            return None
        if pipeline_model is None:
            return card_view(item)          # le modèle DÉCLARÉ par le pipeline de l'app
        try:
            model_key = pipeline_model(item)
        except Exception:
            model_key = None
        return card_view(item, model_key)

    def _read(request, pk):
        user = get_user(request)
        if read_lookup is not None:
            return read_lookup(user, pk)
        from wama.common.utils.scoping import visible_or_404
        return visible_or_404(work_model, user, pk=pk)   # LECTURE : le sien, ou reçu (F7)

    def progress(request, pk):
        item = _read(request, pk)
        failed = item.status == 'FAILURE'
        message = (getattr(item, error_field, '') or '') if failed else ''
        data = {
            'id': item.pk,
            'status': item.status,
            'progress': _live(item),
            # Les deux graphies d'avant (`error` / `error_message`), toujours présentes, vides
            # hors échec : un message d'un échec PASSÉ ne se montre pas sur une card relancée.
            'error': message,
            'error_message': message,
        }
        if item.status in IN_FLIGHT:
            seconds = _estimate(item)
            if seconds is not None:
                data['estimated_seconds'] = seconds
        view = _pipeline(item)
        if view is not None:
            # Les PROCESS bougent pendant le traitement (`WamaApp.updateProcessRows`) ; `status`
            # reste celui de l'ÉLÉMENT — c'est lui qui dit « en vol » au front.
            data['processes'], data['shown_state'] = view[0], view[1]
        if extra is not None:
            data.update(extra(item) or {})
        return JsonResponse(data)

    def _counts(qs):
        # UNE requête sur trois colonnes : la barre interroge toutes les 2 à 3 s, et charger
        # chaque élément entier a coûté jusqu'à 0,7 s par appel (transcriber, 2026-10-03).
        rows = qs.values_list('pk', 'status', progress_field)
        return queue_progress(
            (status, _live(_Row(pk, stored, progress_field)) if status == 'RUNNING' else 0)
            for pk, status, stored in rows)

    def global_progress(request):
        user = get_user(request)
        qs = queryset(user) if queryset is not None else work_model.objects.filter(user=user)
        if not domains:
            return JsonResponse(_counts(qs))
        payload, first = {}, None
        for name, narrow in domains.items():
            payload[name] = _counts(narrow(qs))
            first = first or payload[name]
        return JsonResponse({**first, **payload})

    progress.__name__, global_progress.__name__ = 'progress', 'global_progress'
    return {'progress': progress, 'global_progress': global_progress}


class _Row:
    """Ce que la progression vivante lit d'un élément, pour une ligne de `values_list` (aucune
    instance chargée) : `pk`, `id` et le champ de progression enregistrée."""

    def __init__(self, pk, stored, field):
        self.pk = self.id = pk
        setattr(self, field, stored)
