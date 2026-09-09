"""
AnalysisPass helpers — register, complete, fail, and detect stale passes.

A pass is "stale" when its parameter snapshot no longer matches the
profile's current value of the watched parameters. When a pass becomes
stale, downstream passes (per the dependency graph) are also flipped to
stale so the UI shows the cascade clearly.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

# ── LE REGISTRE DES PASSES — déclaration UNIQUE du pipeline (2026-09-07) ──────────────
# Avant ce registre, le même graphe était écrit SIX fois : `PassType.choices` (models),
# `_WATCHED`, `_STAGE`, `_DEPENDS_ON`, `_PER_CAMERA_PASSES` (ici), la liste `order` en dur de
# `get_passes_status`, et `views.run_passes.dispatch_map`. Six copies qui ne pouvaient que
# diverger (`depth`/`depth_calc` avaient un étage mais aucune dépendance déclarée). Patron :
# `features.FEATURES` — un registre, des dérivés. `PassType` reste la source des LIBELLÉS et
# des valeurs persistées ; `tests_pass_registry` atteste que les deux ensembles coïncident.
#
# C'est aussi la marche ① vers D13 (`WAMA_DATA_WORLD §9undecies.2`, tranchée le 24/08) : les
# passes sont déjà des `FunctionSpec` app-bound (`function_specs.py`) ; ce registre est ce qui
# s'exportera en manifeste `pipeline` à nœuds `function` quand le kind les acceptera.
#
# Champs :
#   stage       'analyse' (perception : REGARDE les images, GPU) | 'calcul' (DÉRIVE des données
#               stockées, CPU, rejouable) — scinde le volet droit et pilote les ▶ d'étage ;
#   depends_on  amont dont la péremption (STALE/FAILED/absent) se propage à cette passe, et
#               ordre de la chaîne de lancement ;
#   watched     paramètres du PROFIL dont le changement rend la passe STALE (yolo_detect ne
#               surveille PAS target_classes/confidence : l'inférence stocke tout à conf ≥ 0,10,
#               le filtre est à la lecture) ;
#   per_camera  une ligne par caméra dans le panneau (et une passe par caméra en base) ;
#   task        attribut de `cam_analyzer.tasks` dispatché SEUL par `run_passes` — '' quand la
#               passe est portée par `process_session_task` (yolo/yolopv2/lane_events/distance
#               y sont enchaînés) ou synchrone (`intersection_windows`, `extraction` = panneau
#               RTMaps) ;
#   gpu         charge GPU (un ▶ d'étage Analyse le dit à l'utilisateur ; le ▶ Calculs jamais) ;
#   function    clé `FUNCTION_CATALOG` de la passe quand elle diffère de `cam_analyzer.<key>`
#               (`depth` → `cam_analyzer.depth_analysis`) — c'est le nœud `function` que le
#               registre devient au manifeste `pipeline` (D13, `pipeline_manifest()` ci-dessous).
from dataclasses import dataclass, field as _field


@dataclass(frozen=True)
class Pass:
    key: str
    stage: str
    depends_on: tuple = ()
    watched: tuple = ()
    per_camera: bool = False
    task: str = ''
    gpu: bool = False
    function: str = ''

    @property
    def function_key(self) -> str:
        return self.function or f'cam_analyzer.{self.key}'


PASSES: tuple = (
    # ── ANALYSE (perception) ────────────────────────────────────────────────────
    Pass('extraction', 'analyse'),
    Pass('intersection_windows', 'analyse', depends_on=('extraction',), watched=('intersections',)),
    Pass('yolo_detect', 'analyse', depends_on=('extraction',),
         watched=('model_path', 'iou_threshold', 'tracker'), per_camera=True, gpu=True),
    Pass('yolopv2_lanes', 'analyse', depends_on=('extraction',),
         watched=('road_model_path',), per_camera=True, gpu=True),
    Pass('sam3_markings', 'analyse', depends_on=('extraction', 'intersection_windows'),
         watched=('sam3_markings_enabled', 'sam3_markings_prompts', 'sam3_as_road_fallback'),
         per_camera=True, task='analyze_sam3_only_task', gpu=True),
    # Profondeur (Depth Pro) : lit les bbox (profondeur de contact) → dépend de la détection.
    Pass('depth', 'analyse', depends_on=('yolo_detect',), task='compute_depth_task', gpu=True,
         function='cam_analyzer.depth_analysis'),
    # ── CALCUL (dérivation, CPU, rejouable) ─────────────────────────────────────
    Pass('lane_events', 'calcul', depends_on=('yolo_detect', 'yolopv2_lanes'),
         task='compute_lane_events_task'),
    Pass('temporal_segments', 'calcul', depends_on=('yolo_detect', 'intersection_windows'),
         watched=('target_classes', 'confidence'), task='compute_temporal_segments_task'),
    Pass('distance', 'calcul', depends_on=('lane_events',), task='compute_distance_task'),
    Pass('depth_calc', 'calcul', depends_on=('depth',), task='compute_depth_calc_task'),
    Pass('global_tracking', 'calcul', depends_on=('yolo_detect', 'distance'),
         task='compute_global_tracking_task'),
    Pass('indicators', 'calcul', depends_on=('global_tracking', 'distance'),
         task='compute_indicators_task'),
    Pass('conflicts', 'calcul', depends_on=('lane_events', 'distance'),
         task='compute_conflict_events_task'),
)

#: Ordre de DÉCLARATION = ordre d'affichage du panneau (ex-liste `order` de get_passes_status).
ORDER: tuple = tuple(p.key for p in PASSES)
_BY_KEY: dict = {p.key: p for p in PASSES}

# Dérivés — mêmes noms qu'avant pour les consommateurs existants (recompute_stale, views…).
_WATCHED: dict[str, list[str]] = {p.key: list(p.watched) for p in PASSES}
_STAGE: dict[str, str] = {p.key: p.stage for p in PASSES}
_DEPENDS_ON: dict[str, list[str]] = {p.key: list(p.depends_on) for p in PASSES}


def stage_keys(stage: str) -> list:
    """Clés des passes d'un étage, dans l'ordre de déclaration."""
    return [p.key for p in PASSES if p.stage == stage]


def dispatch_table():
    """{clé: tâche Celery} des passes que `run_passes` dispatche SEULES — dérivé de `task`.

    Import paresseux (les tâches importent des modèles) ; une clé dont l'attribut n'existe
    pas lève : mieux vaut casser au premier appel que dispatcher dans le vide.
    """
    from wama_lab.cam_analyzer import tasks as _tasks
    return {p.key: getattr(_tasks, p.task) for p in PASSES if p.task}


def pipeline_graph() -> dict:
    """Le registre sous la forme CANVAS du Studio (`{nodes, links}`) : une passe = un nœud
    `function` (clé du catalogue), une dépendance = un lien. C'est la forme que `graph_to_body`
    traduit en manifeste et que le Studio sait charger (« UNE représentation, DEUX éditeurs »,
    `WAMA_DATA_WORLD §9undecies`). Les `params` d'un nœud portent ce qui est propre à la passe
    et n'existe pas dans le `FunctionSpec` : étage, par-caméra, GPU, paramètres surveillés."""
    from wama.common.manifests.builtin.pipeline import FUNCTION_NODE_PREFIX
    nodes = [{'id': p.key, 'app': f'{FUNCTION_NODE_PREFIX}{p.function_key}',
              'params': {'stage': p.stage, 'per_camera': p.per_camera, 'gpu': p.gpu,
                         'watched': list(p.watched), 'task': p.task}}
             for p in PASSES]
    links = [{'from': d, 'to': p.key, 'to_port': None} for p in PASSES for d in p.depends_on]
    return {'nodes': nodes, 'links': links}


def pipeline_manifest() -> dict:
    """Manifeste `pipeline` complet du registre — inscrit sous la clé `cam_analyzer` par
    `function_specs.py` (`register_pipeline_source`), exporté par `manifest_export --kind
    pipeline` vers `manifests/pipelines/`."""
    from wama.common.manifests.builtin.pipeline import graph_to_body
    return {
        'manifest_kind': 'pipeline',
        'key': 'cam_analyzer',
        'schema_version': '1.0',
        'name': 'Cam Analyzer — chaîne d’analyse (13 passes)',
        'description': "Pipeline déclaré en code (`pass_tracking.PASSES`) : étage ANALYSE "
                       "(perception, GPU) puis CALCUL (dérivation CPU rejouable) ; chaque passe "
                       "est un nœud `function` du catalogue, chaque dépendance un lien.",
        'world': 'lab',
        'owner': None,
        'visibility': 'public',
        'projects': ['ENA'],
        'source': {'type': 'extract', 'ref': 'cam_analyzer.utils.pass_tracking:PASSES'},
        'body': graph_to_body(pipeline_graph()),
    }


def topological_order(keys) -> list:
    """Sous-ensemble `keys` trié pour que tout amont précède son aval (Kahn, STABLE : à égalité,
    l'ordre de déclaration). Les amonts ABSENTS de `keys` sont ignorés — on ordonne ce qu'on
    lance, on ne complète pas la demande.

    Raison d'être (2026-09-07) : `run_passes` lançait les passes de calcul en PARALLÈLE (un
    `.delay()` chacune) alors que `_DEPENDS_ON` les ordonne — `conflicts` pouvait partir avant
    `distance`. Une chaîne Celery bâtie sur cet ordre corrige ça pour tous les appelants.
    """
    wanted = [k for k in ORDER if k in set(keys)]
    remaining = list(wanted)
    done, out = set(), []
    while remaining:
        progressed = False
        for k in list(remaining):
            deps = [d for d in _DEPENDS_ON.get(k, []) if d in wanted]
            if all(d in done for d in deps):
                out.append(k); done.add(k); remaining.remove(k); progressed = True
        if not progressed:                      # cycle : impossible par construction, mais on
            out.extend(remaining); break        # préfère un ordre dégradé à une boucle infinie
    return out


def _profile_snapshot(profile, watched_keys: list[str]) -> dict:
    """Capture the watched fields from the profile."""
    if profile is None:
        return {}
    return {k: getattr(profile, k, None) for k in watched_keys}


def mark_started(session, pass_type: str, profile=None, camera=None) -> None:
    """Insert/update the pass row at status RUNNING and reset any prior error.

    camera : when provided, the pass is scoped to that camera (per-camera
    granularity, e.g. yolo_detect_front). When None, the pass is session-wide
    (e.g. intersection_windows, temporal_segments).
    """
    from wama_lab.cam_analyzer.models import AnalysisPass

    snapshot = _profile_snapshot(profile, _WATCHED.get(pass_type, []))
    obj, _ = AnalysisPass.objects.update_or_create(
        session=session,
        pass_type=pass_type,
        camera=camera,
        defaults={
            'status': AnalysisPass.Status.RUNNING,
            'parameters': snapshot,
            'started_at': timezone.now(),
            'completed_at': None,
            'duration_s': None,
            'error_message': '',
        },
    )
    return obj


def mark_completed(session, pass_type: str, *, output_summary: dict | None = None,
                   camera=None) -> None:
    from wama_lab.cam_analyzer.models import AnalysisPass

    try:
        obj = AnalysisPass.objects.get(session=session, pass_type=pass_type, camera=camera)
    except AnalysisPass.DoesNotExist:
        # mark_started may not have been called (e.g. legacy task path) —
        # create the row directly with whatever we have.
        obj = AnalysisPass(session=session, pass_type=pass_type, camera=camera)
        obj.started_at = timezone.now()
    now = timezone.now()
    obj.status = AnalysisPass.Status.COMPLETED
    obj.completed_at = now
    if obj.started_at:
        obj.duration_s = round((now - obj.started_at).total_seconds(), 2)
    if output_summary is not None:
        obj.output_summary = output_summary
    obj.error_message = ''
    obj.save()


def mark_failed(session, pass_type: str, error_message: str, camera=None) -> None:
    from wama_lab.cam_analyzer.models import AnalysisPass

    AnalysisPass.objects.update_or_create(
        session=session,
        pass_type=pass_type,
        camera=camera,
        defaults={
            'status': AnalysisPass.Status.FAILED,
            'error_message': str(error_message)[:2000],
            'completed_at': timezone.now(),
        },
    )


def recompute_stale(session) -> int:
    """
    Recompute STALE flags for all passes of a session by comparing each
    pass's parameter snapshot to the profile's current values, then
    propagating staleness through the dependency graph.

    Returns the number of passes flipped (for logging).
    """
    from wama_lab.cam_analyzer.models import AnalysisPass

    profile = session.profile
    passes = list(AnalysisPass.objects.filter(session=session))
    # Group by type — for per-camera types, the cascade considers a type
    # "available" if AT LEAST ONE camera-row is COMPLETED.
    by_type_any_completed: dict = {}
    for p in passes:
        cur = by_type_any_completed.get(p.pass_type)
        if cur is None or p.status == AnalysisPass.Status.COMPLETED:
            by_type_any_completed[p.pass_type] = p

    flipped = 0

    # First pass: direct snapshot mismatch on watched params.
    for p in passes:
        if p.status != AnalysisPass.Status.COMPLETED:
            continue
        watched = _WATCHED.get(p.pass_type, [])
        if not watched:
            continue
        current = _profile_snapshot(profile, watched)
        if current != (p.parameters or {}):
            p.status = AnalysisPass.Status.STALE
            p.save(update_fields=['status'])
            flipped += 1

    # Cascade: if upstream is STALE/FAILED/missing, downstream becomes stale.
    # Iterate until fixpoint (graph is small, max ~5 levels).
    changed = True
    while changed:
        changed = False
        for p in passes:
            if p.status != AnalysisPass.Status.COMPLETED:
                continue
            for dep_type in _DEPENDS_ON.get(p.pass_type, []):
                dep = by_type_any_completed.get(dep_type)
                if dep is None or dep.status in (AnalysisPass.Status.STALE,
                                                   AnalysisPass.Status.FAILED):
                    p.status = AnalysisPass.Status.STALE
                    p.save(update_fields=['status'])
                    flipped += 1
                    changed = True
                    break
    return flipped


# Passes that are *per-camera* (one row per camera). Others are session-wide. Dérivé du registre.
_PER_CAMERA_PASSES = {p.key for p in PASSES if p.per_camera}


def get_passes_status(session) -> list[dict]:
    """Return a serialisable list of pass status dicts for the UI.

    For per-camera pass types, one entry is emitted per active camera (the
    UI groups them under the same label with sub-rows). Session-wide passes
    get a single entry."""
    from wama_lab.cam_analyzer.models import AnalysisPass

    passes = list(AnalysisPass.objects.filter(session=session).select_related('camera'))
    # Index: (pass_type, camera_position_or_None) → pass row
    by_key = {(p.pass_type, p.camera.position if p.camera_id else None): p for p in passes}

    cameras = list(session.cameras.all().order_by('position'))
    # Positions réellement traitées par le pipeline (les autres sont ignorées).
    analyzed = list(getattr(getattr(session, 'profile', None), 'analyzed_positions', []) or [])
    if not analyzed:
        analyzed = ['front', 'rear']
    # yolo_detect = toutes les vues. yolopv2_lanes = front-only par défaut, 4 vues si
    # profile.yolopv2_all_views (Phase C 360°). SAM3 = front-only (tâche mono-caméra).
    _SAM3_POSITIONS = {'front'}
    _yolopv2_all = bool(getattr(getattr(session, 'profile', None), 'yolopv2_all_views', False))
    out = []
    # Ordre d'affichage = ordre de déclaration du registre (plus de liste en dur ici).
    order = [AnalysisPass.PassType(k) for k in ORDER]
    label_map = dict(AnalysisPass.PassType.choices)
    for pt in order:
        if pt.value in _PER_CAMERA_PASSES:
            if pt.value == 'sam3_markings':
                relevant = [c for c in cameras if c.position in _SAM3_POSITIONS]
            elif pt.value == 'yolopv2_lanes' and not _yolopv2_all:
                # yolopv2 front-only par défaut (toggle OFF).
                relevant = [c for c in cameras if c.position == 'front']
            else:
                # yolo_detect (toutes vues) + yolopv2 si all_views activé — ligne
                # « non faite » (+ bouton lancer) conservée pour left/right.
                relevant = cameras
            for cam in relevant:
                p = by_key.get((pt.value, cam.position))
                # Repli sur la passe de NIVEAU SESSION (camera=None) UNIQUEMENT pour les
                # caméras réellement traitées (analyzed_positions) — compat des analyses
                # enregistrées avant le suivi par caméra, sans cocher left/right à tort.
                if p is None and cam.position in analyzed:
                    p = by_key.get((pt.value, None))
                if p is None:
                    out.append({
                        'pass_type': pt.value,
                        'label': pt.label,
                        'camera': cam.position,
                        'status': 'never',
                        'parameters': {},
                        'output_summary': {},
                        'completed_at': None,
                        'duration_s': None,
                        'error_message': '',
                    })
                else:
                    out.append({
                        'pass_type': p.pass_type,
                        'label': label_map.get(p.pass_type, p.pass_type),
                        'camera': cam.position,
                        'status': p.status,
                        'parameters': p.parameters or {},
                        'output_summary': p.output_summary or {},
                        'completed_at': p.completed_at.isoformat() if p.completed_at else None,
                        'duration_s': p.duration_s,
                        'error_message': p.error_message or '',
                    })
        else:
            p = by_key.get((pt.value, None))
            if p is None:
                out.append({
                    'pass_type': pt.value,
                    'label': pt.label,
                    'camera': None,
                    'status': 'never',
                    'parameters': {},
                    'output_summary': {},
                    'completed_at': None,
                    'duration_s': None,
                    'error_message': '',
                })
            else:
                out.append({
                    'pass_type': p.pass_type,
                    'label': label_map.get(p.pass_type, p.pass_type),
                    'camera': None,
                    'status': p.status,
                    'parameters': p.parameters or {},
                    'output_summary': p.output_summary or {},
                    'completed_at': p.completed_at.isoformat() if p.completed_at else None,
                    'duration_s': p.duration_s,
                    'error_message': p.error_message or '',
                })
    # Étage d'affichage (analyse / calcul) — scinde visuellement le pipeline dans le volet droit.
    for d in out:
        d['stage'] = _STAGE.get(d.get('pass_type'), 'analyse')
    return out
