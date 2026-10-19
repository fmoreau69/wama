"""
Studio — canvas d'édition de PIPELINES (corrigé le 2026-09-15) : nœuds de tous types — entrées,
apps (ports typés depuis APP_CATALOG + app_modes), fonctions du catalogue (depuis le 2026-09-09),
sortie — les connexions étant validées par compatibilité de types (« typage par connexion »).
L'ancienne formule « chaque nœud = une app » est périmée. Vocabulaire process / pipeline / nœud /
card : WAMA_APP_GENERATION_ROUTE.md §10.6 ; vision : STUDIO_VISION.md.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render


@login_required
def index(request):
    """Canvas du studio. (Corrigé le 2026-09-15 : l'exécution réelle existe depuis le
    2026-07-11 — `api_run` → `services/launch.launch_graph` → `tasks.run_pipeline_task`.)"""
    return render(request, 'studio/index.html')


@login_required
def api_nodes(request):
    """
    Catalogue des nœuds du studio (métadonnée-driven) : label/icône/couleur + description + PORTS
    typés (entrée travail/prompt/référence, sortie) — nœuds APP dérivés d'APP_CATALOG + app_modes,
    et nœuds FONCTION du catalogue de fonctions (depuis le 2026-09-09, bloc D13 ci-dessous).
    Vocabulaire unifié en catégories média → « typage par connexion » cohérent côté JS. Filtré par
    accès. ⚠ (précisé le 2026-09-15 → WAMA_APP_GENERATION_ROUTE.md §10.6 5.4) : les pipelines
    SAUVEGARDÉS n'y figurent pas (ils passent par `api_pipelines`) ; cible = un « Catalogue » en
    sections qui les inclut.

    RÉGLAGES servis avec le catalogue (`schemas`, ROUTE §10.6 3.3bis, R2 — 2026-10-18) : le schéma
    `Param` de chaque nœud servi ici (`node_params.node_schema`), sous le MÊME filtre d'accès. Ils
    vivaient sur une route à part (`api_run_options`, REMOVAL_LEDGER R143), arrivée 10 à 15 s
    après le catalogue : tant qu'elle n'était pas là, un nœud sélectionné ne montrait AUCUN
    réglage, sans rien dire — et elle servait les nœuds de toutes les apps, accès ou non.

    Seul un nœud d'app EXÉCUTABLE est offert (`runners.runner_for`, la règle du lancement) : une
    jumelle sans outil de création (`generic_runner._twin_can_create`) apparaissait à la palette,
    sans réglages, et le lancement la refusait dès qu'on la reliait.
    """
    from wama.common.app_registry import APP_CATALOG, studio_node_ports
    from wama.common.manifests.builtin.pipeline import builtin_nodes
    from .services.node_params import node_schema
    from .services.runners import runner_for
    try:
        from wama.accounts.permissions import accessible
    except Exception:
        accessible = None
    # Les nœuds INTÉGRÉS — cards d'entrée et de sortie — que les mondes déclarent au registre
    # commun (R2, 2026-10-18), sous la même forme qu'un nœud d'app. La palette les écrivait en
    # JavaScript (`BUILTINS`, avec un « Batch de prompts » que rien n'exécutait).
    nodes = {key: {'label': b.label, 'icon': b.icon, 'color': b.color,
                   'description': b.description, **b.ports(), 'kind': b.role}
             for key, b in builtin_nodes().items()}
    for app_id, meta in APP_CATALOG.items():
        ports = studio_node_ports(app_id)
        if not ports or runner_for(app_id) is None:
            continue
        if accessible and not accessible(request.user, 'app', app_id):
            continue
        nodes[app_id] = {
            'label': meta.get('label', app_id),
            'icon':  meta.get('icon', 'fas fa-cube'),
            'color': meta.get('color', '#6ea8fe'),
            'description': meta.get('description', '') or meta.get('description_long', ''),
            'inputs': ports['inputs'],
            'output': ports['output'],
        }
    # D13 — nœuds FONCTION : le catalogue de fonctions par le MÊME accesseur de forme que les
    # apps (`function_node_ports` ≡ `studio_node_ports`). Le JS ne connaît qu'un identifiant
    # de palette : `function:<clé>` (lu par `pipeline.node_kind`/`function_key`, nulle part
    # ailleurs). Fonctions `pure` ET `app`-bound.
    from wama.common.catalog import function_catalog as fc
    from wama.common.catalog.data_types import known_types      # accesseur unique (2026-09-16)
    from wama.common.manifests.builtin.pipeline import FUNCTION_NODE_PREFIX
    fc.load_all()
    # Une fonction suit l'accès de l'app qui la PORTE, comme le nœud de l'app ci-dessus
    # (2026-10-05 : les process d'une jumelle dev-only et ceux d'une app non ouverte au compte
    # s'affichaient à tous) — et c'est aussi sa provenance (`ROADMAP §29` étape 4) : la lecture
    # de `spec.visibility` qui la précédait est retirée avec le champ.
    for spec in sorted(fc.accessible_specs(request.user, fc.FUNCTION_CATALOG.values()),
                       key=lambda s: s.key):
        key = spec.key
        ports = fc.function_node_ports(key)
        nodes[f'{FUNCTION_NODE_PREFIX}{key}'] = {
            'label': spec.name or key,
            'icon': _FUNCTION_ICONS.get(spec.category, 'fas fa-square-root-variable'),
            'color': '#9ad0ec' if spec.binding == fc.Binding.PURE else '#c9b5e8',
            'description': spec.description,
            'inputs': ports['inputs'],
            'output': ports['output'],
            'kind': 'function',
            'binding': spec.binding,
            'app': spec.app,
            'category': spec.category,
        }
    schemas = {node: schema for node in nodes if (schema := node_schema(node)) is not None}
    return JsonResponse({'nodes': nodes, 'schemas': schemas, 'data_types': sorted(known_types())})


_FUNCTION_ICONS = {
    'transform': 'fas fa-wand-magic-sparkles', 'enricher': 'fas fa-layer-group',
    'detector': 'fas fa-bolt', 'indicator': 'fas fa-gauge', 'resampler': 'fas fa-wave-square',
    'join': 'fas fa-code-merge', 'aggregate': 'fas fa-chart-column',
}


# ─────────────────────────────────────────────────────────────────────────────
# Persistance + exécution (2026-07-11 — PROJECT_STATUS §15 : les 2 ⏳ du studio)
# ─────────────────────────────────────────────────────────────────────────────

def _json_body(request):
    import json
    try:
        return json.loads(request.body or b'{}')
    except (ValueError, TypeError):
        return {}


@login_required
def api_pipelines(request):
    """GET : liste des pipelines sauvegardés — les siens et ceux qu'on lui partage (`listable_by`,
    `ROADMAP §29` étape 4). POST : sauvegarde (upsert par nom) — toujours le SIEN : enregistrer
    un pipeline partagé en fait sa copie (`WAMA_COLLABORATION §3.5`)."""
    from django.views.decorators.http import require_http_methods  # noqa: F401 (doc)
    from wama.common.utils.scoping import listable_by
    from .models import StudioPipeline
    if request.method == 'POST':
        data = _json_body(request)
        name = (data.get('name') or '').strip()[:120]
        graph = data.get('graph') or {}
        if not name:
            return JsonResponse({'error': 'Nom de pipeline requis'}, status=400)
        if not graph.get('nodes'):
            return JsonResponse({'error': 'Graphe vide — rien à sauvegarder'}, status=400)
        pipe, created = StudioPipeline.objects.update_or_create(
            user=request.user, name=name, defaults={'graph': graph})
        return JsonResponse({'id': pipe.pk, 'name': pipe.name, 'created': created})
    pipes = listable_by(StudioPipeline.objects.all(), request.user)
    return JsonResponse({'pipelines': [
        {'id': p.pk, 'name': p.name, 'updated_at': p.updated_at.strftime('%d/%m %H:%M'),
         'nodes': len(p.graph.get('nodes', []))}
        for p in pipes
    ]})


@login_required
def api_pipeline_detail(request, pk):
    """GET : charge un pipeline qu'on voit (`visible_or_404`). DELETE : supprime le SIEN
    (`owned_or_404`) — un pipeline partagé ne se supprime que chez son auteur."""
    from django.http import Http404
    from wama.common.utils.scoping import owned_or_404, visible_or_404
    from .models import StudioPipeline
    try:
        if request.method == 'DELETE':
            owned_or_404(StudioPipeline, request.user, pk=pk).delete()
            return JsonResponse({'deleted': pk})
        pipe = visible_or_404(StudioPipeline, request.user, pk=pk)
    except Http404:
        return JsonResponse({'error': 'Pipeline introuvable'}, status=404)
    return JsonResponse({'id': pipe.pk, 'name': pipe.name, 'graph': pipe.graph})


# ── Pipelines DÉCLARÉS par les apps (registre de code) — les ouvrir au studio ─────────
# ROUTE §10.6 2.2 : « tout ce qui s'exécute dans une file doit pouvoir s'ouvrir au studio ».
# Source : les pipelines inscrits par `register_pipeline_source` (le kind ne connaît pas ses
# producteurs), rendus sous la forme canvas par `body_to_graph`. Lecture seule côté code : les
# modifier au studio puis sauvegarder en fait un pipeline PERSONNEL (StudioPipeline).

def _declared_pipelines(user, keys):
    """Les pipelines déclarés que `user` peut ouvrir, `{clé: manifeste}`.

    Un pipeline du code n'a pas d'auteur à lui : il suit ce qu'il fait tourner (`ROADMAP §29`
    étape 4). Chacun de ses nœuds — fonction, ou app — doit être accessible au compte, par les
    règles de la palette (`accessible_specs`, `accessible_apps`) : le pipeline d'une jumelle est
    donc à son créateur, comme ses process. La lecture de `visibility` dans le manifeste, qui
    disait « public » pour tous, est retirée."""
    from wama.accounts.permissions import accessible_apps
    from wama.common.catalog import function_catalog as fc
    from wama.common.manifests.builtin.pipeline import (PIPELINE_SOURCES, function_key,
                                                        node_kind, registered_pipeline_keys)
    known = set(registered_pipeline_keys())
    manifests = {key: m for key in keys if key in known and (m := PIPELINE_SOURCES[key]())}
    nodes = [n for m in manifests.values() for n in (m.get('body') or {}).get('nodes') or []]
    fc.load_all()
    specs = [s for n in nodes if node_kind(n) == 'function' and (s := fc.get(function_key(n)))]
    # Une fonction que le catalogue ne connaît pas n'a pas d'app : rien ne la restreint (la même
    # règle que `accessible`) — c'est le lancement qui la refusera, en la nommant.
    closed = {s.key for s in specs} - {s.key for s in fc.accessible_specs(user, specs)}
    app_ids = sorted({n.get('app') for n in nodes if node_kind(n) == 'app' and n.get('app')})
    closed_apps = set(app_ids) - set(accessible_apps(user, app_ids))

    def opens(node):
        kind = node_kind(node)
        if kind == 'function':
            return function_key(node) not in closed
        return kind != 'app' or node.get('app') not in closed_apps
    return {key: m for key, m in manifests.items()
            if all(opens(n) for n in (m.get('body') or {}).get('nodes') or [])}


@login_required
def api_declared_pipelines(request):
    """GET : les pipelines déclarés par les apps (clé, nom, monde, nombre de nœuds)."""
    from wama.common.manifests.builtin.pipeline import registered_pipeline_keys
    out = []
    for key, m in _declared_pipelines(request.user, registered_pipeline_keys()).items():
        if m:
            out.append({'key': key, 'name': m.get('name') or key, 'world': m.get('world'),
                        'nodes': len((m.get('body') or {}).get('nodes') or [])})
    return JsonResponse({'pipelines': out})


@login_required
def api_declared_pipeline_detail(request, key):
    """GET : le graphe CANVAS d'un pipeline déclaré (disposition automatique s'il n'en a pas)."""
    from wama.common.manifests.builtin.pipeline import body_to_graph
    m = _declared_pipelines(request.user, [key]).get(key)
    if not m:
        return JsonResponse({'error': 'Pipeline déclaré introuvable'}, status=404)
    return JsonResponse({'key': key, 'name': m.get('name') or key, 'declared': True,
                         'description': m.get('description', ''),
                         'graph': body_to_graph(m.get('body') or {})})


@login_required
def api_node_context(request):
    """POST `{graph, node}` : ce que REÇOIT le nœud — la nature de ce qui lui est branché, le texte
    d'une saisie, les valeurs que porte l'élément d'une étape (`services/graph_flow.node_context`,
    ROUTE §10.6 3.3bis règle 5 — 2026-10-18). L'inspecteur les pose SOUS les réglages du nœud :
    conditions d'affichage, listes d'options et champs fournis par un lien s'en déduisent, comme
    sur une card. Rien n'est enregistré."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requis'}, status=405)
    from .services.graph_flow import node_context
    data = _json_body(request)
    return JsonResponse(node_context(data.get('graph') or {}, data.get('node'), request.user))


@login_required
def api_run(request):
    """POST : lance l'exécution du graphe (Celery). Validation + dispatch = brique PARTAGÉE
    `services.launch.launch_graph` (même contrat que l'outil assistant `run_studio_pipeline`)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requis'}, status=405)
    from .services.launch import launch_graph
    data = _json_body(request)
    run, err = launch_graph(request.user, data.get('graph') or {},
                            pipeline_id=data.get('pipeline_id') or None)
    if err:
        return JsonResponse({'error': err}, status=400)
    return JsonResponse({'run_id': run.pk})


@login_required
def api_run_status(request, pk):
    """GET : état d'un run (statuts par nœud pour colorer le canvas)."""
    from .models import StudioRun
    try:
        run = StudioRun.objects.get(pk=pk, user=request.user)
    except StudioRun.DoesNotExist:
        return JsonResponse({'error': 'Run introuvable'}, status=404)
    return JsonResponse({
        'id': run.pk,
        'status': run.status,
        'node_states': run.node_states,
        'error': run.error_message,
        'processing_display': run.processing_display,
    })
