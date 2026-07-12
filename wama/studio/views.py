"""
Studio — méta-app : canvas où chaque nœud = une app (ports typés depuis APP_CATALOG + app_modes),
les connexions étant validées par compatibilité de types (« typage par connexion »).
Voir STUDIO_VISION.md / MODES_QUEUE_UX.md (§ méta-app).
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render


@login_required
def index(request):
    """Canvas du studio. Pas d'exécution à ce stade — valide card + connecteurs sur du réel."""
    return render(request, 'studio/index.html')


@login_required
def api_nodes(request):
    """
    Catalogue des nœuds-app du studio (métadonnée-driven) : label/icône/couleur + description + PORTS
    typés (entrée travail/prompt/référence, sortie) dérivés d'APP_CATALOG + app_modes. Vocabulaire
    unifié en catégories média → « typage par connexion » cohérent côté JS. Filtré par accès.
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
        if accessible and not accessible(request.user, app_id):
            continue
        nodes[app_id] = {
            'label': meta.get('label', app_id),
            'icon':  meta.get('icon', 'fas fa-cube'),
            'color': meta.get('color', '#6ea8fe'),
            'description': meta.get('description', '') or meta.get('description_long', ''),
            'inputs': ports['inputs'],
            'output': ports['output'],
        }
    return JsonResponse({'nodes': nodes})


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


@login_required
def api_run_options(request):
    """Options d'exécution métadonnée-driven : params_spec par app exécutable +
    listes dynamiques (galerie d'avatars)."""
    from .services.runners import RUNNERS
    specs = {app: r['params_spec'] for app, r in RUNNERS.items()}
    # Nœuds intégrés (cards d'entrée / de sortie) — configurables dans l'inspecteur
    specs['text_input'] = [
        {'name': 'text', 'label': 'Texte', 'type': 'textarea',
         'placeholder': 'Texte / prompt envoyé au nœud aval…'},
    ]
    specs['media_import'] = [
        {'name': 'asset_path', 'label': 'Média (médiathèque)', 'type': 'media_picker'},
    ]
    specs['studio_output'] = [
        {'name': 'asset_name', 'label': 'Nom dans la médiathèque', 'type': 'text',
         'placeholder': '(défaut : nom du fichier produit)'},
        {'name': 'asset_type', 'label': "Type d'asset", 'type': 'select',
         'options': ['video', 'image', 'voice', 'audio_music', 'audio_sfx', 'document'],
         'default': 'video'},
    ]
    # Galerie d'avatars (même source que l'app avatarizer : media/avatarizer/gallery/)
    import os
    from django.conf import settings
    gallery = []
    gdir = os.path.join(settings.MEDIA_ROOT, 'avatarizer', 'gallery')
    if os.path.isdir(gdir):
        gallery = sorted(f for f in os.listdir(gdir)
                         if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')))
    return JsonResponse({'params_specs': specs, 'options': {'avatar_gallery': gallery}})


@login_required
def api_run(request):
    """POST : lance l'exécution du graphe (Celery). Valide runners + acyclicité AVANT dispatch."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requis'}, status=405)
    from .models import StudioRun
    from .services.runners import runner_for
    from .tasks import run_pipeline_task, topo_order
    data = _json_body(request)
    graph = data.get('graph') or {}
    nodes = graph.get('nodes', [])
    if not nodes:
        return JsonResponse({'error': 'Graphe vide'}, status=400)
    try:
        topo_order(graph)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    from .tasks import SOURCE_HANDLERS
    links = graph.get('links', [])

    def _executable(app):
        return runner_for(app) is not None or app in SOURCE_HANDLERS or app == 'studio_output'

    for n in nodes:
        if not _executable(n['app']) and any(l['to'] == n['id'] for l in links):
            return JsonResponse(
                {'error': f"Nœud « {n['app']} » : app non exécutable dans un pipeline "
                          f"(V1 : synthesizer, avatarizer, converter + nœuds Texte/Médiathèque/Sortie)."},
                status=400)
    if not any(runner_for(n['app']) for n in nodes):
        return JsonResponse({'error': 'Aucun nœud-app exécutable dans le graphe '
                                      '(V1 : synthesizer, avatarizer, converter).'}, status=400)
    run = StudioRun.objects.create(user=request.user, graph=graph,
                                   pipeline_id=data.get('pipeline_id') or None)
    task = run_pipeline_task.delay(run.pk)
    run.task_id = task.id
    run.save(update_fields=['task_id'])
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
