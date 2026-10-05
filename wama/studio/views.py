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
    """
    from wama.common.app_registry import APP_CATALOG, studio_node_ports
    try:
        from wama.accounts.permissions import accessible
    except Exception:
        accessible = None
    nodes = {}
    for app_id, meta in APP_CATALOG.items():
        ports = studio_node_ports(app_id)
        if not ports:
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
    # ailleurs). Fonctions `pure` ET `app`-bound ; une privée ne sort pas (visibilité).
    from wama.common.catalog import function_catalog as fc
    from wama.common.catalog.data_types import known_types      # accesseur unique (2026-09-16)
    from wama.common.manifests.builtin.pipeline import FUNCTION_NODE_PREFIX
    fc.load_all()
    for key, spec in sorted(fc.FUNCTION_CATALOG.items()):
        if spec.visibility != 'public':
            continue
        # Un process RATTACHÉ suit l'accès de son app, comme le nœud de l'app ci-dessus
        # (2026-10-05 : les process d'une jumelle dev-only et ceux d'une app non ouverte au
        # compte s'affichaient à tous).
        if (spec.binding == fc.Binding.APP and spec.app and accessible
                and not accessible(request.user, 'app', spec.app)):
            continue
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
    return JsonResponse({'nodes': nodes, 'data_types': sorted(known_types())})


_FUNCTION_ICONS = {
    'transform': 'fas fa-wand-magic-sparkles', 'enricher': 'fas fa-layer-group',
    'detector': 'fas fa-bolt', 'indicator': 'fas fa-gauge', 'resampler': 'fas fa-wave-square',
    'join': 'fas fa-code-merge', 'aggregate': 'fas fa-chart-column',
}


def function_node_params_specs():
    """Specs de params des nœuds FONCTION (forme des `params_spec` du runner générique) :
    `ParamSpec` → champ ; pour une fonction `app`-bound, les arguments OBLIGATOIRES de sa
    tâche `impl` (ex. `session_id`) s'ajoutent en tête — par introspection, jamais par app."""
    from wama.common.catalog import function_catalog as fc
    from wama.common.manifests.builtin.pipeline import FUNCTION_NODE_PREFIX
    from wama.studio.tasks import app_function_job_kwargs
    fc.load_all()
    specs = {}
    for key, spec in fc.FUNCTION_CATALOG.items():
        entries = []
        if spec.binding == fc.Binding.APP and spec.impl:
            try:
                required = app_function_job_kwargs(spec.impl)
            except ValueError:
                required = []
            entries += [{'name': n, 'label': n, 'type': 'text',
                         'placeholder': f'requis par {spec.impl.split(":")[-1]}'} for n in required]
        for p in spec.params:
            e = {'name': p.key, 'label': p.description or p.key}
            if p.type == 'enum' and p.choices:
                e['type'] = 'select'
                e['options'] = [{'value': c, 'label': str(c)} for c in p.choices]
            elif p.type == 'bool':
                e['type'] = 'select'
                e['options'] = [{'value': '', 'label': 'Non'}, {'value': '1', 'label': 'Oui'}]
            else:
                e['type'] = 'text'
                if p.min is not None or p.max is not None or p.unit:
                    e['placeholder'] = f"{p.min if p.min is not None else ''}–" \
                                       f"{p.max if p.max is not None else ''} {p.unit}".strip(' –')
            if p.default is not None:
                e['default'] = p.default
            entries.append(e)
        specs[f'{FUNCTION_NODE_PREFIX}{key}'] = entries
    return specs


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
    """GET : liste des pipelines sauvegardés. POST : sauvegarde (upsert par nom)."""
    from django.views.decorators.http import require_http_methods  # noqa: F401 (doc)
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
    pipes = StudioPipeline.objects.filter(user=request.user)
    return JsonResponse({'pipelines': [
        {'id': p.pk, 'name': p.name, 'updated_at': p.updated_at.strftime('%d/%m %H:%M'),
         'nodes': len(p.graph.get('nodes', []))}
        for p in pipes
    ]})


@login_required
def api_pipeline_detail(request, pk):
    """GET : charge un pipeline (graphe). DELETE : le supprime."""
    from .models import StudioPipeline
    try:
        pipe = StudioPipeline.objects.get(pk=pk, user=request.user)
    except StudioPipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline introuvable'}, status=404)
    if request.method == 'DELETE':
        pipe.delete()
        return JsonResponse({'deleted': pk})
    return JsonResponse({'id': pipe.pk, 'name': pipe.name, 'graph': pipe.graph})


# ── Pipelines DÉCLARÉS par les apps (registre de code) — les ouvrir au studio ─────────
# ROUTE §10.6 2.2 : « tout ce qui s'exécute dans une file doit pouvoir s'ouvrir au studio ».
# Source : les pipelines inscrits par `register_pipeline_source` (le kind ne connaît pas ses
# producteurs), rendus sous la forme canvas par `body_to_graph`. Lecture seule côté code : les
# modifier au studio puis sauvegarder en fait un pipeline PERSONNEL (StudioPipeline).

def _declared_pipeline(key):
    from wama.common.manifests.builtin.pipeline import PIPELINE_SOURCES, registered_pipeline_keys
    if key not in registered_pipeline_keys():
        return None
    m = PIPELINE_SOURCES[key]()
    return m if m and m.get('visibility', 'public') == 'public' else None


@login_required
def api_declared_pipelines(request):
    """GET : les pipelines déclarés par les apps (clé, nom, monde, nombre de nœuds)."""
    from wama.common.manifests.builtin.pipeline import registered_pipeline_keys
    out = []
    for key in registered_pipeline_keys():
        m = _declared_pipeline(key)
        if m:
            out.append({'key': key, 'name': m.get('name') or key, 'world': m.get('world'),
                        'nodes': len((m.get('body') or {}).get('nodes') or [])})
    return JsonResponse({'pipelines': out})


@login_required
def api_declared_pipeline_detail(request, key):
    """GET : le graphe CANVAS d'un pipeline déclaré (disposition automatique s'il n'en a pas)."""
    from wama.common.manifests.builtin.pipeline import body_to_graph
    m = _declared_pipeline(key)
    if not m:
        return JsonResponse({'error': 'Pipeline déclaré introuvable'}, status=404)
    return JsonResponse({'key': key, 'name': m.get('name') or key, 'declared': True,
                         'description': m.get('description', ''),
                         'graph': body_to_graph(m.get('body') or {})})


@login_required
def api_run_options(request):
    """Options d'exécution métadonnée-driven : params_spec par app exécutable +
    listes dynamiques (galerie d'avatars)."""
    from .services.runners import runner_for
    from .services.generic_runner import GENERIC_APPS
    specs = {app: runner_for(app)['params_spec'] for app in GENERIC_APPS}   # source unique : params.py
    # Nœuds intégrés (cards d'entrée / de sortie) — configurables dans l'inspecteur
    specs['text_input'] = [
        {'name': 'text', 'label': 'Texte', 'type': 'textarea',
         'placeholder': 'Texte / prompt envoyé au nœud aval…'},
    ]
    specs['media_import'] = [
        {'name': 'asset_path', 'label': 'Média (médiathèque)', 'type': 'media_picker'},
    ]
    from wama.common.catalog.data_types import DataType, known_types
    specs['dataset_input'] = [
        {'name': 'asset_path', 'label': 'Fichier tabulaire (médiathèque)', 'type': 'media_picker'},
        {'name': 'data_type', 'label': 'Type de donnée', 'type': 'select',
         'options': sorted(known_types()),
         'default': DataType.TABLE},
    ]
    specs.update(function_node_params_specs())   # D13 : nœuds fonction
    specs['studio_output'] = [
        {'name': 'asset_name', 'label': 'Nom dans la médiathèque', 'type': 'text',
         'placeholder': '(défaut : nom du fichier produit)'},
        {'name': 'asset_type', 'label': "Type d'asset", 'type': 'select',
         'options': ['video', 'image', 'voice', 'audio_music', 'audio_sfx', 'document'],
         'default': 'video'},
    ]
    # Galerie d'avatars — MÊME SOURCE que l'app avatarizer, et c'est maintenant vrai au sens
    # fort : la médiathèque. Ce bloc RECOPIAIT le parcours de dossier de `avatarizer.views`
    # (deux scans pour une seule galerie) ; les deux lisent désormais `SystemAsset`, donc ils
    # ne peuvent plus diverger. Le studio n'a besoin que des NOMS pour sa liste d'options.
    # 2026-09-29 : la liste est celle que l'utilisateur VOIT (les siens, les partagés, le système)
    # — la même que la card de l'avatarizer ; le nom choisi se résout par `designate_named_avatar`.
    # 2026-09-30 : + les avatars 3D (objets 3D au visage ARKit, moteur TalkingHead de l'avatarizer)
    # — filtrés sur l'attribut MESURÉ, pas sur toute la nature : un maillage TripoSR ne parle pas.
    from wama.media_library.services import visible_asset_names
    gallery = (visible_asset_names(request.user, 'avatar')
               + visible_asset_names(request.user, 'object3d', attributes={'face_rig': 'arkit'}))
    gallery = list(dict.fromkeys(gallery))
    return JsonResponse({'params_specs': specs, 'options': {'avatar_gallery': gallery}})


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
