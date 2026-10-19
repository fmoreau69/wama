"""
La PALETTE du studio pour un compte : les nœuds qu'il peut POSER — et donc les seuls qu'il peut
LANCER (2026-10-19, `ROADMAP §16.11` piste 4).

Extraite d'`api_nodes` le jour où le lancement en a eu besoin : la règle « ce qu'un compte voit
dans la palette » (accès à l'app, nœud d'app exécutable, fonction de l'app qui la porte) vivait
dans la vue seule. Un nœud gardé à l'ouverture d'un pipeline sans figurer dans la palette — app
fermée au compte, fonction disparue du catalogue — ne s'exécute pas ; le lancement le refuse en
le nommant, par CETTE règle, au lieu d'échouer au milieu d'un run.
"""


_FUNCTION_ICONS = {
    'transform': 'fas fa-wand-magic-sparkles', 'enricher': 'fas fa-layer-group',
    'detector': 'fas fa-bolt', 'indicator': 'fas fa-gauge', 'resampler': 'fas fa-wave-square',
    'join': 'fas fa-code-merge', 'aggregate': 'fas fa-chart-column',
}


def palette_nodes(user) -> dict:
    """`{identifiant de palette: description du nœud}` offerts à `user` — label/icône/couleur,
    description, PORTS typés, `kind`. Nœuds intégrés, nœuds d'app, nœuds fonction (D13)."""
    from wama.common.app_registry import APP_CATALOG, studio_node_ports
    from wama.common.manifests.builtin.pipeline import builtin_nodes
    from .runners import runner_for
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
        if accessible and not accessible(user, 'app', app_id):
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
    from wama.common.manifests.builtin.pipeline import FUNCTION_NODE_PREFIX
    fc.load_all()
    # Une fonction suit l'accès de l'app qui la PORTE, comme le nœud de l'app ci-dessus
    # (2026-10-05 : les process d'une jumelle dev-only et ceux d'une app non ouverte au compte
    # s'affichaient à tous) — et c'est aussi sa provenance (`ROADMAP §29` étape 4) : la lecture
    # de `spec.visibility` qui la précédait est retirée avec le champ.
    for spec in sorted(fc.accessible_specs(user, fc.FUNCTION_CATALOG.values()),
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
    return nodes
