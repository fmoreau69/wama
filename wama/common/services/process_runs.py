"""
Lignes d'exécution des process — la pièce du MOTEUR COMMUN de pipeline qui dit « tel process,
pour telle card, dans tel état ». Doc : `WAMA_APP_GENERATION_ROUTE.md §10.6` points 4.1 à 4.5
(marche P3).

D'OÙ ÇA VIENT. La sémantique est celle du suivi de passes du cam_analyzer
(`wama_lab/cam_analyzer/utils/pass_tracking.py` : `mark_started`, `mark_completed`,
`mark_failed`, `recompute_stale`), généralisée : la « session » devient n'importe quel ÉLÉMENT
porté par une card, la « passe » un NŒUD de son pipeline, la « caméra » la clé d'instance, le
« profil » les réglages que le process surveille.

CE QUE CE MODULE FAIT
  • annonce les process d'un lancement : `plan` (leurs lignes passent `PENDING`, « son tour
    n'est pas venu », avec la tâche qui les jouera) ;
  • écrit la ligne d'un process : `start`, `await_resources`, `succeed`, `fail` ;
  • estime la durée d'un process d'après ses lignes : `row_eta_seconds`, `last_duration` (règle
    reprise de `pass_tracking`, l'ETA par process du cam_analyzer, 2026-10-01), et celle d'un
    LANCEMENT : `launch_eta`, la somme de ses process (`ProcessSpec.eta`, 2026-10-05) ;
  • referme les lignes ouvertes d'un élément stoppé ou réconcilié : `close_open` ;
  • dit ce qui est périmé : `stale_nodes` (réglage surveillé changé, puis cascade vers l'aval) ;
  • déduit l'état d'une card de ses process : `aggregate` (règle du point 4.4).

CE QU'IL NE FAIT PAS. Il ne lance rien et n'ordonne rien : l'exécution reste au squelette de
tâche (`common/utils/task_skeleton.py`) et, pour plusieurs process, au moteur. Il ne décide pas
non plus de l'état AFFICHÉ d'une card à un seul process : tant que l'élément porte ses colonnes
`status` / `progress`, c'est lui que l'interface lit (cf. `ProcessRun`).

⚠ BEST-EFFORT POUR LES ÉCRIVAINS DU CYCLE DE VIE. Le squelette et `process_control` passent par
`safely()` : une ligne qui ne s'écrit pas ne doit jamais faire échouer un traitement ni un arrêt
— mais elle se DIT (journal, niveau avertissement), elle ne s'avale pas.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from wama.common.models import (JOB_AWAITING_RESOURCES, JOB_FAILURE, JOB_PENDING, JOB_RUNNING,
                                JOB_STALE, JOB_SUCCESS)

logger = logging.getLogger(__name__)

#: Nœud d'une card à UN seul process — le cas normal d'une app Médias aujourd'hui.
MAIN_NODE = 'main'

#: États d'une ligne « ouverte » : le process est parti (ou attend son tour), rien n'est rendu.
OPEN_STATES = frozenset({JOB_RUNNING, JOB_AWAITING_RESOURCES})

#: Degrés de liberté d'un process dans son pipeline (point 3.2).
REQUIRED = 'required'
OPTIONAL = 'optional'


def address(item) -> dict:
    """Adresse d'un élément : `{app, object_type, object_id}` — dérivée de l'élément SEUL, pour
    que tout écrivain (squelette, arrêt, réconciliation, moteur) désigne la même ligne."""
    meta = item._meta
    return {'app': meta.app_label, 'object_type': meta.object_name, 'object_id': str(item.pk)}


def lines(item):
    """Les lignes d'exécution d'un élément (une requête, ordonnée par nœud)."""
    from wama.common.models import ProcessRun
    return ProcessRun.objects.filter(**address(item))


def lines_by_item(items) -> dict:
    """`{pk (texte): [lignes]}` des éléments d'UN même modèle — UNE requête pour toute une page
    de file (la bande des process de chaque card ne doit pas coûter une requête par card)."""
    items = [item for item in items if item is not None]
    if not items:
        return {}
    from wama.common.models import ProcessRun
    meta = items[0]._meta
    grouped = {str(item.pk): [] for item in items}
    for row in ProcessRun.objects.filter(app=meta.app_label, object_type=meta.object_name,
                                         object_id__in=list(grouped)):
        grouped[row.object_id].append(row)
    return grouped


def line(item, node_id: str = MAIN_NODE, instance_key: str = ''):
    """La ligne d'un nœud, ou None s'il n'a jamais été lancé."""
    return lines(item).filter(node_id=node_id, instance_key=instance_key).first()


def snapshot(settings, watched) -> dict:
    """Photo des réglages SURVEILLÉS : `{clé: valeur}` pour chaque clé de `watched`, lue d'un
    dict ou des attributs d'un objet (élément, profil). Un réglage non surveillé n'y entre pas."""
    # Les valeurs sont écrites sous la forme qu'un JSONField gardera (la photo est relue de la
    # base avant d'être comparée : un champ fichier devient son chemin, un tuple une liste) —
    # par la règle que la RÉVISION applique déjà à ses réglages, pas par une seconde.
    from wama.common.services.revisions import json_safe
    if settings is None:
        return {}
    if isinstance(settings, dict):
        return {key: json_safe(settings.get(key)) for key in watched}
    return {key: json_safe(getattr(settings, key, None)) for key in watched}


def _write(item, node_id, instance_key, defaults):
    from wama.common.models import ProcessRun
    run, _created = ProcessRun.objects.update_or_create(
        **address(item), node_id=node_id, instance_key=instance_key, defaults=defaults)
    return run


def plan(item, steps, *, task_id: str = '') -> int:
    """Le lancement ANNONCE les process qu'il va jouer : leurs lignes passent `PENDING` — « son
    tour n'est pas venu », la table des états de `ROUTE §10.6` — et portent la tâche qui les
    jouera. C'est ce qui dit, PENDANT le traitement, ce que fait CE lancement : un ▶ borné à un
    process n'y inscrit que lui et ses amonts périmés (`AppPipeline.steps_to_run(only=)`).

    `steps` : `[(nœud, clé de process, nature)]`. Ce que la ligne a rendu la fois d'avant (durée,
    taille, sortie, photo) est GARDÉ : `start` en relit la durée, la péremption la sortie. Seule
    l'erreur d'un échec passé est effacée — il ne décrit plus le lancement. Une ligne `PENDING`
    n'est pas « ouverte » (`OPEN_STATES`) : un arrêt la laisse telle quelle, « pas encore
    lancée ». Rend le nombre de lignes écrites."""
    written = 0
    for node_id, process_key, kind in steps:
        defaults = {'status': JOB_PENDING, 'task_id': task_id or '', 'error_message': ''}
        if line(item, node_id) is None:
            defaults.update({'process_key': process_key or item._meta.app_label,
                             'process_kind': kind})
        _write(item, node_id, '', defaults)
        written += 1
    return written


def start(item, node_id: str = MAIN_NODE, *, process_key: str = '', kind: str = 'app',
          version: str = '', instance_key: str = '', settings_snapshot: dict | None = None,
          model_key: str = '', task_id: str = ''):
    """Le process PART : la ligne passe `RUNNING`, sa photo de réglages est prise, l'erreur et
    la sortie de l'exécution précédente sont effacées.

    La durée de l'exécution PRÉCÉDENTE survit sous `output_summary['previous_duration_s']`
    (c'est ce qui permet d'annoncer une durée pendant que le process tourne — repris de
    `pass_tracking.mark_started`), avec la TAILLE sur laquelle elle a été mesurée quand le
    process la déclare (`eta_size_s`) : sans elle, cette durée ne se met pas à l'échelle d'un
    run de taille différente — mesuré le 2026-10-04, quand les passes du cam_analyzer, qui la
    déclarent, sont passées sur ces lignes.
    """
    previous = line(item, node_id, instance_key)
    summary = {}
    if previous is not None and previous.duration_s:
        summary['previous_duration_s'] = previous.duration_s
        size = (previous.output_summary or {}).get(ETA_SIZE_KEY)
        if size:
            summary[ETA_SIZE_KEY] = size
    return _write(item, node_id, instance_key, {
        'process_kind': kind,
        'process_key': process_key or item._meta.app_label,
        'process_version': version,
        'status': JOB_RUNNING,
        'settings_snapshot': dict(settings_snapshot or {}),
        'model_key': model_key or '',
        'output_ref': '',
        'output_summary': summary,
        'started_at': timezone.now(),
        'finished_at': None,
        'duration_s': None,
        'error_message': '',
        'task_id': task_id or '',
    })


def await_resources(item, node_id: str = MAIN_NODE, *, process_key: str = '',
                    instance_key: str = '', task_id: str = ''):
    """Le tour du process est venu, la VRAM libre ne suffit pas : la ligne le dit, sans effacer
    ce que l'exécution précédente avait rendu."""
    existing = line(item, node_id, instance_key)
    defaults = {'status': JOB_AWAITING_RESOURCES, 'error_message': '', 'task_id': task_id or ''}
    if existing is None:
        defaults['process_key'] = process_key or item._meta.app_label
    return _write(item, node_id, instance_key, defaults)


def succeed(item, node_id: str = MAIN_NODE, *, instance_key: str = '', output_ref: str = '',
            output_summary: dict | None = None, model_key: str | None = None,
            process_key: str = '', settings_snapshot: dict | None = None):
    """Le process a RENDU son résultat : `SUCCESS`, durée mesurée depuis `start`.

    `settings_snapshot` : la photo des réglages surveillés À LA FIN du process, quand l'appelant
    la donne — elle remplace celle du départ. Une glu peut AJUSTER un réglage qu'elle surveille
    (le composer plafonne la durée à ce que le modèle sait rendre) : gardée telle qu'au départ,
    la photo rendrait le process périmé par son propre résultat (mesuré le 2026-10-03)."""
    existing = line(item, node_id, instance_key)
    now = timezone.now()
    summary = dict((existing.output_summary or {}) if existing else {})
    summary.update(output_summary or {})
    defaults = {'status': JOB_SUCCESS, 'finished_at': now, 'error_message': '',
                'output_ref': output_ref or '', 'output_summary': summary}
    if existing is not None and existing.started_at:
        defaults['duration_s'] = round((now - existing.started_at).total_seconds(), 2)
    if existing is None:
        # `start` n'a pas été appelé (chemin d'exécution ancien) : la ligne naît terminée.
        defaults.update({'process_key': process_key or item._meta.app_label, 'started_at': now})
    if model_key is not None:
        defaults['model_key'] = model_key
    if settings_snapshot is not None:
        defaults['settings_snapshot'] = dict(settings_snapshot)
    return _write(item, node_id, instance_key, defaults)


def fail(item, node_id: str = MAIN_NODE, message: str = '', *, instance_key: str = '',
         process_key: str = ''):
    """Le process a ÉCHOUÉ — le message est gardé sur la ligne ; la sortie précédente, elle,
    n'est pas effacée (un échec ne détruit rien)."""
    existing = line(item, node_id, instance_key)
    defaults = {'status': JOB_FAILURE, 'finished_at': timezone.now(),
                'error_message': str(message or '')[:2000]}
    if existing is None:
        defaults['process_key'] = process_key or item._meta.app_label
    return _write(item, node_id, instance_key, defaults)


def close_open(item, to_status: str = JOB_FAILURE, message: str = '') -> int:
    """Referme les lignes OUVERTES d'un élément qu'on arrête ou qu'on réconcilie : une tâche
    stoppée ou morte ne rendra plus rien, sa ligne ne doit pas rester « en cours ».

    Appelée par les écrivains d'état de `process_control` (`stop_instance`, réconciliations).
    Sans effet pour un élément sans ligne ouverte. Rend le nombre de lignes refermées.
    """
    return lines(item).filter(status__in=OPEN_STATES).update(
        status=to_status, finished_at=timezone.now(),
        error_message=str(message or '')[:2000], task_id='')


def forget(item) -> int:
    """Retire les lignes d'un élément qu'on SUPPRIME (une ligne sans élément ne se lit plus
    jamais). Rend le nombre de lignes retirées."""
    deleted, _detail = lines(item).delete()
    return deleted


def safely(writer, *args, **kwargs):
    """Appelle un écrivain de ce module SANS jamais lever : le cycle de vie d'un traitement ne
    dépend pas de sa ligne. L'échec est DIT (avertissement au journal), jamais avalé.

    L'écriture est faite sous un point de sauvegarde : si elle échoue DANS une transaction de
    l'appelant (une vue d'arrêt, un lanceur), elle seule est annulée — sans cela PostgreSQL
    refuserait toutes les requêtes suivantes de cette transaction.
    """
    from django.db import transaction
    try:
        with transaction.atomic():
            return writer(*args, **kwargs)
    except Exception:
        logger.warning("[process_runs] %s : ligne d'exécution non écrite", writer.__name__,
                       exc_info=True)
        return None


# ── Durée d'un process (ETA par process) ─────────────────────────────────────────────────────
# Reprise TELLE QUELLE de `pass_tracking` (cam_analyzer, 2026-10-01), qui la tenait pour ses
# passes : le moteur commun a désormais des process dans sept apps.

#: Clé de `output_summary` qui porte la TAILLE sur laquelle la durée d'une ligne a été mesurée
#: (dans l'unité de l'ETA du process) — `start` la garde avec `previous_duration_s`.
ETA_SIZE_KEY = 'eta_size_s'


def row_eta_seconds(size, last_duration, last_size, learned_seconds):
    """Durée estimée d'un process : sa DERNIÈRE durée sur cet élément (le meilleur prédicteur
    d'une relance), mise à l'échelle si la taille a changé ; sinon l'appris du service commun ;
    sinon None — pas d'a priori générique, dont l'ordre de grandeur serait faux ici."""
    if not size:
        return None
    if last_duration:
        return float(last_duration) * (size / last_size) if last_size else float(last_duration)
    return float(learned_seconds) if learned_seconds else None


def last_duration(row) -> tuple:
    """`(durée, taille)` de la dernière exécution connue d'une ligne : sa durée mesurée, sinon
    celle que `start` a gardée de l'exécution précédente ; la taille sur laquelle elle l'a été
    (`ETA_SIZE_KEY`), ou None. `(None, None)` sans ligne ni durée."""
    if row is None:
        return None, None
    if isinstance(row, dict):         # une ligne déjà SÉRIALISÉE (panneau du cam_analyzer)
        summary = row.get('output_summary') or {}
        duration = row.get('duration_s')
    else:
        summary = row.output_summary or {}
        duration = row.duration_s
    return duration or summary.get('previous_duration_s'), summary.get(ETA_SIZE_KEY)


def process_eta(spec, item):
    """L'ETA DÉCLARÉE d'un process pour cet élément (`ProcessSpec.eta`) : `(clé, taille, unité,
    modèle chargé, a priori de l'app)`, ou None — process sans déclaration, ou déclaration
    illisible (dite au journal, jamais levée : une estimation ne casse pas une vue).

    La fonction déclarée rend `(clé, taille, unité[, modèle chargé[, a priori]])` : les trois
    premiers sont ceux que la glu apprend (`record_run`) ; « modèle chargé » vaut vrai par défaut
    (celui de la fabrique des vues de progression) ; l'a priori est le `fallback_seconds` de
    `eta_estimator.estimate` — l'estimation PROPRE à l'app avant tout apprentissage."""
    declared = getattr(spec, 'eta', None)
    if not declared:
        return None
    try:
        if isinstance(declared, str):
            from wama.common.catalog.function_catalog import resolve_impl
            declared = resolve_impl(declared)
        triplet = declared(item)
    except Exception:
        logger.warning("[process_runs] ETA du process « %s » illisible", spec.key, exc_info=True)
        return None
    if not triplet:
        return None
    key, size, unit = triplet[:3]
    return (key, size, unit, triplet[3] if len(triplet) > 3 else True,
            triplet[4] if len(triplet) > 4 else None)


def step_eta_seconds(spec, item, row) -> float | None:
    """Durée estimée d'UN process de la card : la règle de `row_eta_seconds` (sa dernière durée
    sur cet élément, mise à l'échelle, sinon l'appris), puis — démarrage à froid — l'a priori :
    celui de l'app quand elle le déclare, sinon celui du service commun (par modèle puis par
    domaine) — la règle de `eta_estimator.estimate`. Un process sans ETA déclarée ne vaut que sa
    dernière durée connue."""
    last, last_size = last_duration(row)
    eta = process_eta(spec, item)
    if eta is None:
        return float(last) if last else None
    key, size, unit, loaded, prior = eta
    from wama.model_manager.services.eta_estimator import estimate
    learned = estimate(key, size=size, unit=unit, model_loaded=loaded, fallback_seconds=0.0)
    seconds = row_eta_seconds(size, last, last_size, learned)
    if seconds is None:
        seconds = estimate(key, size=size, unit=unit, model_loaded=loaded,
                           fallback_seconds=prior) or None
    return seconds


def launch_eta(item) -> float | None:
    """Durée TOTALE estimée du lancement d'une card à process : la somme de ses process — ceux
    que CE lancement joue (`plan` les a marqués de sa tâche ; avant qu'il ne tourne, ceux que
    `steps_to_run` retiendrait). Un process déjà rendu pendant ce lancement compte sa durée
    MESURÉE. C'est un total, la graine de `WamaEta` (`seedSeconds`) : le front le ramène au
    restant par la progression de la card, que le squelette pondère des mêmes process (`share`).

    None quand l'app n'a pas de pipeline, qu'aucun de ses process ne déclare d'ETA (la vue garde
    alors l'estimation de l'app, `make_progress_views(eta_for=…)`), ou que rien n'est estimable."""
    from wama.common.services.process_pipeline import pipeline_of
    pipeline = pipeline_of(item)
    if pipeline is None or not any(getattr(spec, 'eta', None) for spec in pipeline.specs):
        return None
    rows = pipeline.rows(item)
    task_id = getattr(item, 'task_id', '') or ''
    planned = []
    if task_id and getattr(item, 'status', None) in OPEN_STATES:
        planned = [spec for spec in pipeline.ordered()
                   if spec.key in rows and rows[spec.key].task_id == task_id]
    if not planned:
        try:
            planned = pipeline.steps_to_run(item, pipeline.requested_model(item))
        except ValueError:
            return None
    total = 0.0
    for spec in planned:
        row = rows.get(spec.key)
        if (row is not None and task_id and row.task_id == task_id
                and row.status == JOB_SUCCESS and row.duration_s):
            total += float(row.duration_s)
            continue
        total += step_eta_seconds(spec, item, row) or 0.0
    return total if total > 0 else None


# ── Péremption (point 4.3) ───────────────────────────────────────────────────────────────────

def _watched_changed(taken: dict, now: dict) -> bool:
    """Un réglage surveillé a-t-il changé entre la photo du lancement et aujourd'hui ?

    On compare les réglages surveillés AUX DEUX dates : un réglage ajouté à `watched` après le
    lancement (ou retiré) ne périme rien — il n'a pas changé, c'est la surveillance qui a changé.
    Sans cela, ajouter un réglage surveillé périmait d'un coup TOUTES les cards déjà rendues de
    l'app (2026-10-04 : la voix et les paroles du composer). Les clés en `@` (empreintes d'amont,
    `process_pipeline.UPSTREAM_KEY`) ne sont pas des réglages : elles se comparent toujours. Une
    photo VIDE (ligne d'avant les photos) garde la règle d'origine."""
    if not taken:
        return taken != now
    keys = (set(taken) & set(now)) | {k for k in set(taken) | set(now) if k.startswith('@')}
    return any(taken.get(k) != now.get(k) for k in keys)


def stale_nodes(states: dict, depends_on: dict, snapshots: dict | None = None,
                current: dict | None = None) -> set:
    """Nœuds à passer `STALE`, parmi ceux qui sont en `SUCCESS`.

    `states`     : `{nœud: état}` — l'état connu de chaque nœud (absent = jamais lancé) ;
    `depends_on` : `{nœud: [amonts]}` — le graphe du pipeline ;
    `snapshots`  : `{nœud: photo prise au lancement}` ; `current` : `{nœud: réglages surveillés
                   aujourd'hui}`. Un nœud absent de `current` ne surveille rien.

    Deux causes, dans cet ordre (repris de `pass_tracking.recompute_stale`) :
      1. un réglage SURVEILLÉ a changé depuis le lancement ;
      2. un amont est périmé, en échec ou n'a jamais tourné — la péremption se propage en
         cascade jusqu'à point fixe.
    Un process en échec, en cours ou jamais lancé n'est pas « périmé » : il n'a rien rendu.
    """
    snapshots, current = snapshots or {}, current or {}
    live = dict(states)
    stale = set()
    for node, state in live.items():
        if state == JOB_SUCCESS and node in current and _watched_changed(snapshots.get(node) or {},
                                                                        current[node]):
            stale.add(node)
            live[node] = JOB_STALE
    changed = True
    while changed:
        changed = False
        for node, state in list(live.items()):
            if state != JOB_SUCCESS:
                continue
            for upstream in depends_on.get(node, ()):
                if live.get(upstream) in (None, JOB_STALE, JOB_FAILURE):
                    stale.add(node)
                    live[node] = JOB_STALE
                    changed = True
                    break
    return stale


def mark_stale(item, node_ids) -> int:
    """Passe `STALE` les lignes `SUCCESS` des nœuds donnés. Rend le nombre de lignes changées."""
    node_ids = list(node_ids)
    if not node_ids:
        return 0
    return lines(item).filter(node_id__in=node_ids, status=JOB_SUCCESS).update(status=JOB_STALE)


# ── Agrégation (point 4.4) ───────────────────────────────────────────────────────────────────

def aggregate(processes) -> str:
    """État d'une CARD déduit de ses process — la règle du point 4.4, validée telle quelle le
    2026-09-17.

    `processes` : une suite de `(état, degré)` pour chaque process ACTIVÉ du pipeline (un
    `optional` désactivé n'y figure pas ; un process jamais lancé y figure en `PENDING`).

      un process en cours                     → `RUNNING`
      sinon un process en attente de VRAM     → `AWAITING_RESOURCES`
      sinon un process REQUIS en échec        → `FAILURE`
      sinon au moins un process périmé        → `STALE`
      sinon tous les process en succès        → `SUCCESS`
      sinon (rien à lancer, reste à lancer)   → `PENDING`

    ⚠ Un process OPTIONNEL en échec ne rend pas la card `FAILURE` (la règle ne le dit que du
    requis) mais l'empêche d'être `SUCCESS` : elle reste `PENDING`, « reste à compléter » —
    c'est le cas que le transcriber avalait (résumé en échec, élément en succès).
    """
    processes = [(state, degree) for state, degree in processes]
    states = [state for state, _degree in processes]
    if JOB_RUNNING in states:
        return JOB_RUNNING
    if JOB_AWAITING_RESOURCES in states:
        return JOB_AWAITING_RESOURCES
    if any(state == JOB_FAILURE and degree == REQUIRED for state, degree in processes):
        return JOB_FAILURE
    if JOB_STALE in states:
        return JOB_STALE
    if states and all(state == JOB_SUCCESS for state in states):
        return JOB_SUCCESS
    return JOB_PENDING
