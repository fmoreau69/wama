"""
io/ — les nœuds INTÉGRÉS du monde Data, inscrits au registre commun des nœuds du pipeline.

ROUTE §10.6 point 3.3bis, marche R2 (2026-10-18). Le registre (`manifests/builtin/pipeline.py`,
`register_builtin_node`) ne connaît pas ses producteurs : le monde Data y inscrit ici son ENTRÉE
Connector et sa SORTIE Exporter (`WAMA_DATA_WORLD §11.5`, `§11.8 ⑨`, ROUTE §10.6 3.6) — une base
déjà constituée (`.wdat`, `.trip`…) branchée sans copie, et un nœud de sortie qui porte ses
`Declaration`s d'export. Ni l'un ni l'autre n'est un process : un pipeline qui ne contient qu'eux
(« je connecte une base et j'en extrais les tables ») est valide.

Leurs exécuteurs vivaient dans l'exécuteur du Studio (`studio/tasks.py`) et leurs réglages dans
`studio/services/node_params.py` : le substrat citait donc le monde Data en dur. Déplacés ici tels
quels — c'est désormais le Studio qui ne sait rien du monde Data.
"""
from __future__ import annotations

from wama.common.manifests.builtin.pipeline import BuiltinNode, register_builtin_node
from wama.common.utils.param_schema import Param

#: Un nœud intégré n'est pas un process : aucun réglage n'en périme un.
NO_STALE = ()


def _readable_path(user, params, key, label):
    """Un chemin du gestionnaire de fichiers (relatif à MEDIA_ROOT, ou `mounts/<id>/…` pour un
    dossier connecté), LISIBLE par cet utilisateur — par la garde commune, jamais une seconde."""
    from wama.filemanager.services import resoudre_chemin_lisible
    raw = (params.get(key) or '').strip()
    if not raw:
        raise ValueError(f"Nœud « {label} » : renseignez le chemin dans les paramètres du nœud.")
    path, error = resoudre_chemin_lisible(user, raw)
    if error:
        raise ValueError(f"Nœud « {label} » : {error[0]} ({raw}).")
    return path


def _source_connector(user, params):
    """Nœud « Base connectée » (Connector) : une base déjà constituée ou un dossier de bases,
    branché SANS copie. Rend des LOTS (`connector.ConnectedLot`) dont rien n'est encore lu :
    c'est le consommateur qui demande ses flux."""
    from .connector import connect
    path = _readable_path(user, params, 'path', 'Base connectée')
    try:
        return 'dataset', connect(path)
    except ValueError as exc:
        raise ValueError(f"Nœud « Base connectée » : {exc}")


def _sink_data_export(user, incoming, params, run_id):
    """Nœud « Export de données » (Exporter en NŒUD DE SORTIE) : ses `Declaration`s appliquées
    aux bases reçues. Destination : le dossier CHOISI, sinon celui d'où viennent les données
    (règle de Fabien, `WAMA_DATA_WORLD §11.1`) — jamais le dépôt."""
    import json
    from pathlib import Path
    from .export import export_lots, grouping_from_dict
    label = 'Export de données'
    lots = [lot for up in incoming if up.get('is_lots') for lot in up['value']]
    if not lots:
        raise ValueError(f"Nœud « {label} » : aucune base reçue (connectez un nœud « Base "
                         f"connectée »).")
    raw = params.get('declarations') or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else []
        except ValueError as exc:
            raise ValueError(f"Nœud « {label} » : déclarations illisibles (JSON attendu) — {exc}")
    if isinstance(raw, dict):
        raw = [raw]
    if params.get('destination'):
        folder = _readable_path(user, params, 'destination', label)
        if not Path(folder).is_dir():
            raise ValueError(f"Nœud « {label} » : la destination doit être un dossier ({folder}).")
    else:
        folder = lots[0].home
    grouping = grouping_from_dict({'lots': params.get('concat_lots'),
                                   'declarations': params.get('concat_declarations')})
    try:
        written = export_lots(raw, lots, folder, grouping=grouping,
                              overwrite=str(params.get('overwrite') or '') in ('1', 'true', 'True'))
    except (ValueError, FileExistsError) as exc:
        raise ValueError(f"Nœud « {label} » : {exc}")
    return f"{len(written)} fichier(s) dans « {folder} » : " + ', '.join(p.name for p in written)


def _export_params():
    from ...core.export import writable_formats
    # ⏳ Les déclarations d'export se saisissent ici en JSON (forme `Declaration.to_dict`) : leur
    # éditeur — famille, tables, colonnes ordonnées, aperçu (`WAMA_DATA_WORLD §11.1`) — est une
    # surface de la card du Data Analyzer.
    return [
        Param(name='declarations', type='textarea', label="Déclarations d'export (JSON)",
              stales=NO_STALE,
              help='[{"name": "situations", "colonnes": [{"stream": "…", "field": "…"}], '
                   '"identite": ["trip_id"], "format": "' + '|'.join(writable_formats()) + '"}]'),
        Param(name='destination', type='text', label='Dossier de destination', stales=NO_STALE,
              help="Vide : le dossier d'où viennent les données."),
        Param(name='concat_lots', type='toggle', label='Concaténer les bases', default=False,
              stales=NO_STALE),
        Param(name='concat_declarations', type='toggle', label='Concaténer les déclarations',
              default=False, stales=NO_STALE),
        Param(name='overwrite', type='toggle', label='Remplacer un fichier existant',
              default=False, stales=NO_STALE),
    ]


register_builtin_node(BuiltinNode(
    key='data_connector', role='source', label='Base connectée', icon='fas fa-database',
    color='#9ad0ec', world='data',
    description='Source : une base déjà constituée (.wdat, .trip…) ou un dossier de bases, '
                'branché SANS copie.',
    run=_source_connector, port_label='Bases', port_types=lambda: ['dataset'],
    params=lambda: [Param(name='path', type='text', label='Base ou dossier de bases',
                          stales=NO_STALE,
                          help='Chemin du gestionnaire de fichiers (mounts/<id>/… pour un dossier '
                               'connecté).')]))

register_builtin_node(BuiltinNode(
    key='data_export', role='sink', label='Export de données', icon='fas fa-file-export',
    color='#e78fb3', world='data',
    description='Écrit les tables déclarées (colonnes ordonnées, identité, format) dans le dossier '
                'choisi, ou à côté des données.',
    run=_sink_data_export, port_label='Bases', port_types=lambda: ['dataset'],
    params=_export_params))
