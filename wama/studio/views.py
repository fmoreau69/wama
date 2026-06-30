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
