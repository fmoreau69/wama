"""
Studio — le schéma de réglages d'un NŒUD, sous UNE forme (`Param`) quel que soit le nœud.

`WAMA_APP_GENERATION_ROUTE.md §10.6` point 3.3bis (marche R1, 2026-10-12). Jusque-là, un nœud du
Studio recevait ses réglages par TROIS projections vers un format propre au Studio
(`params_spec`), rendues par un TROISIÈME moteur de rendu (`renderNodeParams`) :
  • app      — `generic_runner._node_params_spec` : contexte `item` seul, un curseur devenait un
               champ texte, un interrupteur un select Oui/Non ; conditions, groupes, aides,
               bornes par capacité et formats d'affichage PERDUS ;
  • fonction — `studio/views.function_node_params_specs` : la description en guise de libellé,
               chaque nombre en champ texte, bornes ignorées à la coercition ;
  • intégré  — des listes écrites à la main dans `studio/views.api_run_options`.

Désormais un nœud EXPOSE son schéma `Param`, et le Studio le rend par `WamaParams` — la modale ⚙
d'une card, le volet et l'inspecteur du Studio rendent le MÊME champ, avec les mêmes bornes,
depuis la même déclaration :
  • app      — son schéma d'app ENTIER (`schema_for_app`, rendu au contexte `item` : un nœud est
               un élément) et ses groupes (`groups_for_app`), plus les réglages propres au nœud
               que l'app DÉCLARE au runner (`extra_params_spec`, déjà sous forme `Param`) ;
  • fonction — le pont `ParamSpec → Param` (`FunctionSpec.param_schema`) ; une fonction
               rattachée à une app reçoit en tête les arguments OBLIGATOIRES de sa tâche
               (`app_function_job_kwargs`, par introspection) ;
  • intégré  — `BUILTIN_NODE_PARAMS` ci-dessous.

⏳ R2 (même point) : un nœud intégré sera déclaré UNE fois, par son monde — palette, rôle,
réglages et exécuteur lus au même registre. D'ici là ses réglages vivent ici, sous la forme
`Param` qu'ils garderont ; les nœuds du monde Data y citent encore `wama_data` (défaut daté du
2026-10-11, que R2 retire).
"""
from __future__ import annotations

from wama.common.utils.param_schema import Param, schema_to_dicts


def _builtin_nodes() -> dict:
    """Nœuds INTÉGRÉS (cartes d'entrée et de sortie) : `{id: {'label', 'params'}}`. Le libellé
    est celui que l'utilisateur lit au canvas — un refus de réglage nomme le nœud par lui. Calculés
    à l'appel : les types de donnée viennent de la taxonomie, les formats d'export du monde Data.
    ⏳ Le libellé est encore écrit aussi dans la palette (`wama-studio.js`, `BUILTINS`) : R2 fait
    lire les deux au même registre."""
    from wama.common.catalog.data_types import DataType, known_types
    from wama_data.core.export import writable_formats
    no_stale = ()      # un nœud intégré n'est pas un process : rien à périmer
    return {
        'text_input': {'label': 'Texte', 'params': [
            Param(name='text', type='textarea', label='Texte', stales=no_stale,
                  help='Texte ou prompt envoyé au nœud aval.'),
        ]},
        'media_import': {'label': 'Médias importés', 'params': [
            Param(name='asset_path', type='media_picker', label='Média (médiathèque)',
                  stales=no_stale),
        ]},
        'dataset_input': {'label': 'Jeu de données', 'params': [
            Param(name='asset_path', type='media_picker', label='Fichier tabulaire (médiathèque)',
                  stales=no_stale),
            Param(name='data_type', type='select', label='Type de donnée', stales=no_stale,
                  help='Le type est DIT, jamais deviné de l’extension — la taxonomie des '
                       'types de donnée.',
                  choices=[(t, t) for t in sorted(known_types())], default=DataType.TABLE),
        ]},
        # Monde Data (2026-10-11) : l'ENTRÉE Connector et la SORTIE Exporter. ⏳ Les déclarations
        # d'export se saisissent ici en JSON (forme `Declaration.to_dict`) : leur éditeur —
        # famille, tables, colonnes ordonnées, aperçu (`WAMA_DATA_WORLD §11.1`) — est une surface
        # de la card du Data Analyzer.
        'data_connector': {'label': 'Base connectée', 'params': [
            Param(name='path', type='text', label='Base ou dossier de bases', stales=no_stale,
                  help='Chemin du gestionnaire de fichiers (mounts/<id>/… pour un dossier '
                       'connecté).'),
        ]},
        'data_export': {'label': 'Export de données', 'params': [
            Param(name='declarations', type='textarea', label="Déclarations d'export (JSON)",
                  stales=no_stale,
                  help='[{"name": "situations", "colonnes": [{"stream": "…", "field": "…"}], '
                       '"identite": ["trip_id"], "format": "' + '|'.join(writable_formats())
                       + '"}]'),
            Param(name='destination', type='text', label='Dossier de destination',
                  stales=no_stale, help="Vide : le dossier d'où viennent les données."),
            Param(name='concat_lots', type='toggle', label='Concaténer les bases',
                  default=False, stales=no_stale),
            Param(name='concat_declarations', type='toggle', label='Concaténer les déclarations',
                  default=False, stales=no_stale),
            Param(name='overwrite', type='toggle', label='Remplacer un fichier existant',
                  default=False, stales=no_stale),
        ]},
        'studio_output': {'label': 'Sortie', 'params': [
            Param(name='asset_name', type='text', label='Nom dans la médiathèque',
                  stales=no_stale, help='Vide : le nom du fichier produit.'),
            Param(name='asset_type', type='select', label="Type d'asset", stales=no_stale,
                  choices=[(t, t) for t in ('video', 'image', 'voice', 'audio_music',
                                            'audio_sfx', 'document')],
                  default='video'),
        ]},
    }


def builtin_node_ids() -> tuple:
    """Les nœuds intégrés qui ont des réglages."""
    return tuple(_builtin_nodes())


def node_label(app: str) -> str:
    """Le nom d'un nœud tel que l'utilisateur le lit — libellé d'un nœud intégré, sinon son
    identifiant. Ce que dit un refus."""
    return (_builtin_nodes().get(app) or {}).get('label') or app


def _function_schema(spec) -> list:
    """Schéma d'un nœud FONCTION : arguments obligatoires de sa tâche (fonction rattachée à une
    app), puis ses `ParamSpec` par le pont."""
    from wama.common.catalog import function_catalog as fc
    params = []
    if spec.binding == fc.Binding.APP and spec.impl:
        from wama.studio.tasks import app_function_job_kwargs
        try:
            required = app_function_job_kwargs(spec.impl)
        except ValueError:
            required = []
        task = spec.impl.split(':')[-1]
        params += [Param(name=n, type='text', label=n, help=f'Requis par la tâche {task}.')
                   for n in required]
    return params + spec.param_schema()


def node_schema(app: str):
    """`{'params': [Param en dict], 'groups': [ParamGroup en dict]}` du nœud `app` (identifiant de
    palette : une app, `function:<clé>`, ou un nœud intégré), ou `None` s'il n'a pas de réglages
    connus. LE lieu où le Studio apprend les réglages d'un nœud — l'inspecteur, la validation au
    lancement et l'exécution le lisent."""
    from wama.common.manifests.builtin.pipeline import FUNCTION_NODE_PREFIX
    if app.startswith(FUNCTION_NODE_PREFIX):
        from wama.common.catalog import function_catalog as fc
        fc.load_all()
        spec = fc.get(app[len(FUNCTION_NODE_PREFIX):])
        return None if spec is None else {'params': schema_to_dicts(_function_schema(spec)),
                                          'groups': []}
    builtins = _builtin_nodes()
    if app in builtins:
        return {'params': schema_to_dicts(builtins[app]['params']), 'groups': []}
    from wama.studio.services.generic_runner import GENERIC_APPS
    if app in GENERIC_APPS:
        from wama.common.utils.param_schema import groups_for_app, schema_for_app
        # Les réglages propres au nœud sont des `Param` réduits à leurs champs déclarés (le
        # registre est un littéral écrit par le manifeste) : complétés ici de leurs défauts.
        extras = [Param(**entry) for entry in GENERIC_APPS[app].get('extra_params_spec') or []]
        return {'params': schema_for_app(app) + schema_to_dicts(extras),
                'groups': groups_for_app(app)}
    return None


def offered_node_schemas() -> dict:
    """Le schéma de chaque nœud que le Studio sait exécuter — servi à l'inspecteur."""
    from wama.common.catalog import function_catalog as fc
    from wama.common.manifests.builtin.pipeline import FUNCTION_NODE_PREFIX
    from wama.studio.services.generic_runner import GENERIC_APPS
    fc.load_all()
    ids = (list(GENERIC_APPS) + list(builtin_node_ids())
           + [f'{FUNCTION_NODE_PREFIX}{key}' for key in sorted(fc.FUNCTION_CATALOG)])
    return {app: schema for app in ids if (schema := node_schema(app)) is not None}
