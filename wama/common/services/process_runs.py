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
  • écrit la ligne d'un process : `start`, `await_resources`, `succeed`, `fail` ;
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


def line(item, node_id: str = MAIN_NODE, instance_key: str = ''):
    """La ligne d'un nœud, ou None s'il n'a jamais été lancé."""
    return lines(item).filter(node_id=node_id, instance_key=instance_key).first()


def snapshot(settings, watched) -> dict:
    """Photo des réglages SURVEILLÉS : `{clé: valeur}` pour chaque clé de `watched`, lue d'un
    dict ou des attributs d'un objet (élément, profil). Un réglage non surveillé n'y entre pas."""
    if settings is None:
        return {}
    if isinstance(settings, dict):
        return {key: plain(settings.get(key)) for key in watched}
    return {key: plain(getattr(settings, key, None)) for key in watched}


def plain(value):
    """Une valeur de réglage sous sa forme ÉCRITE en JSON — la photo est relue de la base avant
    d'être comparée, les deux côtés doivent donc avoir la même forme : un champ fichier devient
    son chemin, un tuple une liste, tout ce que JSON ne porte pas sa représentation texte."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [plain(entry) for entry in value]
    if isinstance(value, dict):
        return {str(key): plain(entry) for key, entry in value.items()}
    name = getattr(value, 'name', None)          # FieldFile : son chemin relatif, '' si vide
    if hasattr(value, 'storage'):
        return name or ''
    return str(value)


def _write(item, node_id, instance_key, defaults):
    from wama.common.models import ProcessRun
    run, _created = ProcessRun.objects.update_or_create(
        **address(item), node_id=node_id, instance_key=instance_key, defaults=defaults)
    return run


def start(item, node_id: str = MAIN_NODE, *, process_key: str = '', kind: str = 'app',
          version: str = '', instance_key: str = '', settings_snapshot: dict | None = None,
          model_key: str = '', task_id: str = ''):
    """Le process PART : la ligne passe `RUNNING`, sa photo de réglages est prise, l'erreur et
    la sortie de l'exécution précédente sont effacées.

    La durée de l'exécution PRÉCÉDENTE survit sous `output_summary['previous_duration_s']`
    (c'est ce qui permet d'annoncer une durée pendant que le process tourne — repris de
    `pass_tracking.mark_started`).
    """
    previous = line(item, node_id, instance_key)
    summary = {}
    if previous is not None and previous.duration_s:
        summary['previous_duration_s'] = previous.duration_s
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
            process_key: str = ''):
    """Le process a RENDU son résultat : `SUCCESS`, durée mesurée depuis `start`."""
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


# ── Péremption (point 4.3) ───────────────────────────────────────────────────────────────────

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
        if state == JOB_SUCCESS and node in current and current[node] != (snapshots.get(node) or {}):
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
