"""
La PALETTE du studio pour un compte : les nœuds qu'il peut POSER — et donc les seuls qu'il peut
LANCER (2026-10-19, `ROADMAP §16.11` piste 4).

Extraite d'`api_nodes` le jour où le lancement en a eu besoin : la règle « ce qu'un compte voit
dans la palette » (accès à l'app, nœud d'app exécutable, fonction de l'app qui la porte) vivait
dans la vue seule. Un nœud gardé à l'ouverture d'un pipeline sans figurer dans la palette — app
fermée au compte, fonction disparue du catalogue — ne s'exécute pas ; le lancement le refuse en
le nommant, par CETTE règle, au lieu d'échouer au milieu d'un run.

La RAISON d'un nœud absent (`unavailable_reason`) se lit ici aussi, une fois : le lancement la
rend en refusant, et le canvas l'affiche SUR le nœud gardé dès l'ouverture (décision de Fabien,
2026-10-19) — sans attendre qu'on lance pour l'apprendre.
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


#: Pourquoi un nœud n'est pas dans la palette d'un compte — la raison COURTE que le canvas pose sur
#: le nœud ; la phrase entière (`message`) est celle que le lancement rend en le refusant.
REASONS = {
    'inaccessible': 'non accessible à ce compte',
    'not_executable': 'app non exécutable dans un pipeline',
    'unknown': 'inconnu de WAMA',
}


def is_function_node(node: dict) -> bool:
    """Un nœud fonction s'exécute ssi sa clé est au catalogue de fonctions (D13)."""
    from wama.common.catalog import function_catalog as fc
    from wama.common.manifests.builtin.pipeline import function_key, node_kind
    fc.load_all()
    return node_kind(node) == 'function' and fc.get(function_key(node)) is not None


def executable(node: dict) -> bool:
    """Le nœud sait-il s'exécuter, quel que soit le compte : app du runner, nœud intégré (card
    d'entrée ou de sortie du registre commun), ou fonction du catalogue."""
    from wama.common.manifests.builtin.pipeline import builtin_nodes
    from .runners import runner_for
    app = node.get('app') or ''
    return runner_for(app) is not None or app in builtin_nodes() or is_function_node(node)


def unavailable_reason(user, node: dict, offered=None):
    """`None` si la palette de `user` offre le nœud ; sinon `{code, label, message}` — `code` une
    clé de `REASONS`, `label` sa forme courte, `message` la phrase du refus au lancement.

    `offered` : la palette déjà construite (`palette_nodes(user)`), pour ne pas la refaire à
    chaque nœud d'un graphe."""
    from wama.common.app_registry import APP_CATALOG
    from wama.common.manifests.builtin.pipeline import function_key, node_kind
    if offered is None:
        offered = palette_nodes(user)
    app = node.get('app') or ''
    if app in offered:
        return None
    if executable(node):
        code = 'inaccessible'
        what = f"fonction « {function_key(node)} »" if is_function_node(node) else f"« {app} »"
        message = f"Nœud {what} : non accessible à ce compte."
    elif node_kind(node) == 'app' and app in APP_CATALOG:
        code = 'not_executable'
        message = (f"Nœud « {app} » : app non exécutable dans un pipeline — "
                   f"retirez-la du graphe pour lancer.")
    else:
        code = 'unknown'
        message = (f"Nœud « {function_key(node) or app} » : inconnu de WAMA (absent du "
                   f"catalogue) — retirez-le du graphe pour lancer.")
    return {'code': code, 'label': REASONS[code], 'message': message}
