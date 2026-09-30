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
# passes sont déjà des `FunctionSpec` app-bound (`function_specs.py`) ; ce registre S'EXPORTE en
# manifeste `pipeline` à nœuds `function` depuis le 2026-09-09 (`pipeline_manifest()` ci-dessous —
# corrigé le 2026-09-15, la mention « quand le kind les acceptera » était périmée).
# ⏳ Ce registre et `AnalysisPass` sont le MODÈLE du moteur commun de pipeline (photo des réglages,
# péremption STALE, cascade, lancement ciblé) — WAMA_APP_GENERATION_ROUTE.md §10.6, marche P3.
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
    # Recalage ortho 2b (2026-09-28, ex-bouton du panneau Calibration seul) : REGARDE l'orthophoto
    # (SAM3, GPU + réseau) et l'apparie aux passages piétons caméra agrégés en monde
    # (`marking_world`). Elle les agrège ELLE-MÊME depuis le 2026-09-29 : elle dépendait de
    # `global_tracking` pour cela seul, et cette dépendance d'une ANALYSE envers un CALCUL
    # empêchait de chaîner les deux étages en sous-pipelines (ROUTE §10.6 3.4).
    Pass('ortho_recalage', 'analyse', depends_on=('sam3_markings', 'intersection_windows'),
         task='compute_ortho_recalage_task', gpu=True),
    # ── CALCUL (dérivation, CPU, rejouable) ─────────────────────────────────────
    Pass('lane_events', 'calcul', depends_on=('yolo_detect', 'yolopv2_lanes'),
         task='compute_lane_events_task'),
    Pass('temporal_segments', 'calcul', depends_on=('yolo_detect', 'intersection_windows'),
         watched=('target_classes', 'confidence'), task='compute_temporal_segments_task'),
    Pass('distance', 'calcul', depends_on=('lane_events',), task='compute_distance_task'),
    Pass('depth_calc', 'calcul', depends_on=('depth',), task='compute_depth_calc_task'),
    # Recalage voie + carte (2026-09-28) : lit les lignes YOLOPv2 et la BD TOPO (réseau IGN),
    # écrit une correction de POSE navette — déclarée AVANT le tracking pour que le ▶ Calculs
    # la joue avant lui (ordre topologique stable). Pas de dépendance déclarée du tracking vers
    # elle : son effet passe par ⚑ lane_map_recalage (OFF par défaut) ; en faire une amont
    # rendrait PÉRIMÉ le tracking de toute session qui ne l'a jamais jouée.
    Pass('lane_map_recalage', 'calcul', depends_on=('yolopv2_lanes',),
         task='compute_lane_map_recalage_task'),
    # Champ des caméras MESURÉ (2026-09-30) : relit les VIDÉOS avant/arrière (CPU, OpenCV) aux
    # virages de la trace. Appliqué sous ⚑ measured_camera_fov (défaut OFF) — pas de dépendance
    # déclarée depuis l'aval, même raison que `lane_map_recalage`.
    Pass('camera_intrinsics', 'calcul', depends_on=('extraction',),
         task='compute_camera_intrinsics_task'),
    # Cap VISUEL (2026-09-30) : rotation vue par la caméra avant quand la navette roule — exige la
    # focale mesurée. Appliquée au filtre navette sous ⚑ visual_heading (défaut OFF).
    Pass('visual_yaw', 'calcul', depends_on=('camera_intrinsics',), task='compute_visual_yaw_task'),
    # Correction ortho (calcul pur + masque satellite BD TOPO) : ancres tirées de la MESURE
    # `ortho_recalage`, appliquées par ⚑ ortho_correction. Avant le tracking, même raison que
    # `lane_map_recalage` (et même absence de dépendance déclarée du tracking vers elle).
    Pass('ortho_correction', 'calcul', depends_on=('ortho_recalage',),
         task='compute_ortho_correction_task'),
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


def pipeline_graph(stage: str = None) -> dict:
    """Le registre sous la forme CANVAS du Studio (`{nodes, links}`) : une passe = un nœud
    `function` (clé du catalogue), une dépendance = un lien. C'est la forme que `graph_to_body`
    traduit en manifeste et que le Studio sait charger (« UNE représentation, DEUX éditeurs »,
    `WAMA_DATA_WORLD §9undecies`). Les `params` d'un nœud portent ce qui est propre à la passe
    et n'existe pas dans le `FunctionSpec` : étage, par-caméra, GPU, paramètres surveillés.
    `stage` restreint à un ÉTAGE (sous-pipeline, ROUTE §10.6 3.4) : ses passes et ses seuls
    liens internes — les amonts de l'autre étage sont ses ENTRÉES, pas des nœuds."""
    from wama.common.manifests.builtin.pipeline import FUNCTION_NODE_PREFIX
    kept = [p for p in PASSES if stage is None or p.stage == stage]
    keys = {p.key for p in kept}
    nodes = [{'id': p.key, 'app': f'{FUNCTION_NODE_PREFIX}{p.function_key}',
              'params': {'stage': p.stage, 'per_camera': p.per_camera, 'gpu': p.gpu,
                         'watched': list(p.watched), 'task': p.task}}
             for p in kept]
    links = [{'from': d, 'to': p.key, 'to_port': None}
             for p in kept for d in p.depends_on if d in keys]
    return {'nodes': nodes, 'links': links}


#: Les pipelines déclarés par le registre : le complet et ses deux étages (ROUTE §10.6 3.4).
#: ⏳ Le complet deviendra DEUX nœuds `pipeline` chaînés quand ce type de nœud existera
#: (§10.6 3.1) ; en attendant il reste à plat.
PIPELINES = {
    'cam_analyzer': (None, 'Cam Analyzer — chaîne complète'),
    'cam_analyzer.analyse': ('analyse', "Cam Analyzer — analyse d'image (perception)"),
    'cam_analyzer.calcul': ('calcul', 'Cam Analyzer — calculs (dérivation)'),
}


def pipeline_manifest(key: str = 'cam_analyzer') -> dict:
    """Manifeste `pipeline` du registre sous la clé `key` (le complet ou un étage, cf.
    `PIPELINES`) — inscrit par `function_specs.py` (`register_pipeline_source`), exporté par
    `manifest_export --kind pipeline` vers `manifests/pipelines/`. Le nom compte les passes
    (il disait « 13 passes » en dur, 16 depuis le 2026-09-28)."""
    from wama.common.manifests.builtin.pipeline import graph_to_body
    stage, label = PIPELINES[key]
    body = graph_to_body(pipeline_graph(stage))
    what = ("étage ANALYSE (perception, GPU) puis CALCUL (dérivation CPU rejouable)" if stage is None
            else f"étage {stage.upper()} seul — ses amonts de l'autre étage sont ses entrées")
    return {
        'manifest_kind': 'pipeline',
        'key': key,
        'schema_version': '1.0',
        'name': f"{label} ({len(body['nodes'])} passes)",
        'description': f"Pipeline déclaré en code (`pass_tracking.PASSES`) : {what} ; chaque "
                       "passe est un nœud `function` du catalogue, chaque dépendance un lien.",
        'world': 'lab',
        'owner': None,
        'visibility': 'public',
        'projects': ['ENA'],
        'source': {'type': 'extract', 'ref': 'cam_analyzer.utils.pass_tracking:PASSES'
                                              + (f'[stage={stage}]' if stage else '')},
        'body': body,
    }


def calc_chain_key(session_id) -> str:
    """Clé de cache du verrou « une chaîne ▶ Calculs est en file ou en cours » pour cette session :
    posé par `views.run_passes` au lancement, retiré par `tasks.release_calc_chain_task` en fin de
    chaîne (ou sur erreur), expiré au pire après `CALC_CHAIN_TTL_S`. Mesuré le 2026-09-29 : deux
    clics à 19 s d'intervalle, la 1re chaîne attendant derrière une autre tâche du worker GPU —
    aucune passe « running » donc aucun refus, et deux chaînes entrelacées (chaque passe jouée
    deux fois)."""
    return f"cam_analyzer_calc_chain_{session_id}"


CALC_CHAIN_TTL_S = 4 * 3600


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


def calc_queue_key(session_id) -> str:
    """File des passes de calcul demandées pendant qu'une chaîne tourne (même session)."""
    return f'cam_analyzer_calc_queue:{session_id}'


def queued_calc_passes(session_id) -> list:
    from django.core.cache import cache
    return list(cache.get(calc_queue_key(session_id)) or [])


def _start_calc_chain(session_id, keys) -> list:
    """Lance `keys` (déjà ordonnées) en CHAÎNE, verrou posé/rafraîchi, libération en fin ET sur
    échec. Signatures IMMUABLES (`.si`) : chaque tâche reçoit la session, jamais le retour de la
    précédente. Rend les noms de tâches lancées."""
    from celery import chain
    from django.core.cache import cache
    from wama_lab.cam_analyzer.tasks import release_calc_chain_task
    table = dispatch_table()
    tasks = [table[k] for k in keys]
    names = [t.__name__ for t in tasks]
    sid = str(session_id)
    cache.set(calc_chain_key(sid), names, timeout=CALC_CHAIN_TTL_S)
    release = release_calc_chain_task.si(sid)
    result = chain(*[t.si(sid) for t in tasks], release).apply_async(link_error=release)
    cache.set(f"cam_analyzer_task_{sid}", result.id, timeout=86400)
    return names


def launch_calc_passes(session_id, pass_keys) -> dict:
    """Point de lancement UNIQUE des passes de CALCUL (`run_passes`, entrées héritées) — elles
    s'EMPILENT et se DÉPILENT, comme partout dans WAMA (demande de Fabien, 2026-09-30).

    Une seule chaîne à la fois par session : deux chaînes simultanées s'entrelaçaient sur le worker
    `default` (prefork) et jouaient chaque passe deux fois (2026-09-29). Mais une demande pendant
    qu'une chaîne tourne n'est plus REFUSÉE (c'était un 409) : ses passes rejoignent la file de la
    session, et `release_calc_chain_task` la dépile à la fin de la chaîne courante (ou sur son
    échec). Verrou pris par `cache.add` (atomique) : deux clics simultanés ne lancent pas deux
    chaînes. Rend `{'launched': [noms de tâches], 'queued': [passes mises en file]}`."""
    from django.core.cache import cache
    table = dispatch_table()
    keys = [k for k in topological_order(set(pass_keys)) if table.get(k) is not None]
    if not keys:
        return {'launched': [], 'queued': []}
    sid = str(session_id)
    if cache.add(calc_chain_key(sid), keys, timeout=CALC_CHAIN_TTL_S):
        return {'launched': _start_calc_chain(sid, keys), 'queued': []}
    pending = queued_calc_passes(sid)
    new = [k for k in keys if k not in pending]
    cache.set(calc_queue_key(sid), pending + new, timeout=CALC_CHAIN_TTL_S)
    return {'launched': [], 'queued': new}


def dequeue_calc_passes(session_id) -> list:
    """Fin d'une chaîne (`release_calc_chain_task`) : lance la chaîne suivante avec les passes en
    FILE (ordonnées par dépendances), ou lève le verrou s'il n'y a plus rien. Le verrou n'est jamais
    levé entre deux chaînes : `reconcile_interrupted_calc_passes` ne voit pas de trou."""
    from django.core.cache import cache
    sid = str(session_id)
    pending = queued_calc_passes(sid)
    cache.delete(calc_queue_key(sid))
    if pending:
        keys = [k for k in topological_order(set(pending)) if dispatch_table().get(k) is not None]
        if keys:
            return _start_calc_chain(sid, keys)
    cache.delete(calc_chain_key(sid))
    return []


INTERRUPTED_MESSAGE = ("Interrompue : la chaîne de calculs qui la portait est terminée sans elle "
                       "(worker arrêté ou redémarré) — relançable.")


def reconcile_interrupted_calc_passes(session) -> int:
    """Passes de CALCUL restées RUNNING alors que plus aucune chaîne de calculs ne tourne → FAILED
    relançable. Rend le nombre de passes réconciliées.

    PREUVE POSITIVE, pas une supposition (règle de `common.utils.process_control`) : une passe de
    calcul ne s'exécute QUE dans une chaîne posée sous le verrou `calc_chain_key` — tout passe par
    `launch_calc_passes` —, et ce verrou n'est levé qu'à la FIN de la dernière chaîne de la file
    (`release_calc_chain_task` → `dequeue_calc_passes`, lien de succès ET d'échec) ou à
    l'expiration de `CALC_CHAIN_TTL_S`. Plus de verrou = plus de chaîne : une passe encore RUNNING
    a perdu son exécutant. Vécu le 2026-09-29 : worker `default` arrêté à 21:18:22 pendant les
    Indicateurs, verrou libéré à 21:19:24 par le lien d'échec, passe RUNNING à vie et bouton ⏳
    bloqué — la relance était impossible depuis le panneau.
    Les passes d'ANALYSE (GPU) ne sont pas concernées : elles n'ont pas cette preuve."""
    from django.core.cache import cache
    from django.utils import timezone
    from wama_lab.cam_analyzer.models import AnalysisPass
    if cache.get(calc_chain_key(session.id)):
        return 0
    calc = [p.key for p in PASSES if p.stage == 'calcul']
    return AnalysisPass.objects.filter(
        session=session, status=AnalysisPass.Status.RUNNING, pass_type__in=calc,
    ).update(status=AnalysisPass.Status.FAILED, error_message=INTERRUPTED_MESSAGE,
             completed_at=timezone.now())


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
