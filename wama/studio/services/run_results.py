"""
Studio — les RÉSULTATS d'une exécution, et leur ZIP (2026-10-20, passe acceptée par Fabien le
2026-10-18 : « des résultats de natures différentes : l'option ZIP pour tout télécharger »).

Rien de neuf à écrire : un run produit des CARDS dans les files des apps (le nœud d'app en crée
une, le nœud d'étape lance l'étape d'une card), et ce que la file sait télécharger d'une card, le
ZIP d'un run le reprend tel quel — l'écrivain du « ⬇ Télécharger tout » (`batch_views.
ResultArchive.add_elements` : rendu au format demandé d'une app late-binding, sorties DÉCLARÉES de
la card, noms déclarés). Le Studio ne fait que DÉSIGNER les cards, lues par l'accesseur du runner
(`DetailRegistry.get(app)['model']`).

Ce qu'est un résultat : le bout de chaque BRANCHE — un nœud qui est un process (app ou fonction)
et dont rien ne part, sinon vers une sortie (médiathèque, export). Les résultats intermédiaires
restent sur leur card. Un bout qui n'est pas une card se prend si sa ligne d'exécution
(`process_runs`, adressée par le run) désigne un FICHIER que le compte peut lire (`filemanager.services.resoudre_chemin_lisible`, la règle de l'assistant et de l'API :
sortie d'une fonction rattachée, image → 3D) ; une donnée calculée en mémoire (fonction pure) ne
survit pas au run : elle est NOMMÉE comme non conservée, jamais tue.
"""
from __future__ import annotations


def branch_ends(graph) -> list:
    """Les nœuds au bout d'une branche : des process dont aucun lien ne part, sinon vers une
    sortie."""
    from wama.common.manifests.builtin.pipeline import builtin_node
    nodes = graph.get('nodes') or []
    app_of = {n['id']: n.get('app') for n in nodes}
    succ = {}
    for link in graph.get('links') or []:
        succ.setdefault(link.get('from'), []).append(link.get('to'))

    def is_sink(nid):
        builtin = builtin_node(app_of.get(nid))
        return builtin is not None and builtin.role == 'sink'
    return [n for n in nodes if builtin_node(n.get('app')) is None
            and all(is_sink(t) for t in succ.get(n['id'], ()))]


def _element_app(node):
    """L'app dont le nœud produit une CARD : la sienne (nœud d'app), celle de l'étape (nœud
    d'étape de card) — `None` pour une fonction qui n'est pas une étape."""
    from wama.common.manifests.builtin.pipeline import function_key, node_kind
    if node_kind(node) == 'app':
        return node.get('app')
    from wama.common.services.process_pipeline import process_of_function
    pipeline, process = process_of_function(function_key(node))
    return pipeline.app if process is not None else None


def run_results(run, user) -> tuple:
    """`(résultats, non_conservés)` : chaque résultat `{'node', 'label', 'model', 'item'}` (une
    card) ou `{'node', 'label', 'path'}` (un fichier), plus `name` quand la ligne de lot de son
    élément porte un `-o` ; chaque non conservé `{'node', 'label', 'reason'}`. Seuls les bouts
    RÉUSSIS comptent ; une card se lit par la règle de lecture commune (`visible_or_404`)."""
    from django.http import Http404
    from wama.common.models import JOB_SUCCESS
    from wama.common.services import process_runs
    from wama.common.utils.detail_registry import DetailRegistry
    from wama.common.utils.scoping import visible_or_404
    from wama.filemanager.services import resoudre_chemin_lisible
    from .node_params import node_label
    from .entries import element_output
    # Un run de LOT (2026-10-20) : les résultats de chacun de ses éléments, dans leur ordre. Le
    # `-o` de la ligne d'un élément (2026-10-21) nomme ses résultats (`name`), comme il nomme
    # l'entrée du ZIP d'un lot d'app.
    elements = list(run.elements.order_by('pk')) if run.pk else []
    if elements:
        results, missing = [], []
        for index, element in enumerate(elements, start=1):
            got, lost = run_results(element, user)
            name = element_output(element.graph)
            results += [dict(r, name=name) if name else r for r in got]
            said = f"élément {index}" + (f" ({name})" if name else '')
            missing += [dict(m, label=f"{said} · {m['label']}") for m in lost]
        return results, missing
    states = run.node_states or {}
    results, missing = [], []
    for node in branch_ends(run.graph or {}):
        state = states.get(node['id']) or {}
        if state.get('status') != JOB_SUCCESS:
            continue
        label = node_label(node.get('app'))
        app = _element_app(node)
        if app is not None:
            entry = DetailRegistry.get(app)
            try:
                item = visible_or_404(entry['model'], user, pk=int(state.get('item_id')))
            except (TypeError, ValueError, KeyError, Http404):
                missing.append({'node': node['id'], 'label': label,
                                'reason': 'card introuvable (supprimée, ou non visible)'})
                continue
            results.append({'node': node['id'], 'label': label, 'model': entry['model'],
                            'item': item})
            continue
        # La sortie FICHIER du nœud est celle de sa LIGNE d'exécution (`output_ref`, posé par
        # l'exécuteur quand la sortie est un fichier sous MEDIA_ROOT) — la table que le moteur
        # commun lit ; `node_states` n'en garde qu'un libellé.
        row = process_runs.line(run, node['id'])
        path = None
        if row is not None and row.output_ref:
            path, _refused = resoudre_chemin_lisible(user, row.output_ref)
        if path is not None and path.is_file():
            results.append({'node': node['id'], 'label': label, 'path': path})
        else:
            missing.append({'node': node['id'], 'label': label,
                            'reason': "donnée calculée pendant l'exécution, non conservée — "
                                      "reliez une Sortie pour la garder"})
    return results, missing


def run_archive(run, user, request):
    """Le ZIP des résultats d'un run — `(archive, non_conservés)` ; l'archive est vide quand
    aucun bout n'a de fichier à servir."""
    from wama.common.utils.batch_views import ResultArchive
    archive = ResultArchive()
    results, missing = run_results(run, user)
    for result in results:
        if 'item' in result:
            archive.add_elements(result['model'], [result['item']], request,
                                 name=result.get('name', ''))
        else:
            archive.add_file(result['path'], archive.named(result.get('name', ''),
                                                           result['path'].suffix))
    return archive, missing
