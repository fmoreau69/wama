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
  • intégré  — le registre commun des nœuds intégrés (`manifests/builtin/pipeline.BuiltinNode`).

✅ R2 (même point, 2026-10-18) : un nœud intégré est déclaré UNE fois, par son monde — palette,
rôle, réglages et exécuteur lus au même registre. Ses réglages vivaient ici, et les nœuds du monde
Data y citaient `wama_data` (défaut daté du 2026-10-11) : ils sont partis chez leur monde.
"""
from __future__ import annotations

from wama.common.utils.param_schema import Param, schema_to_dicts


def builtin_node_ids() -> tuple:
    """Les nœuds INTÉGRÉS (cards d'entrée et de sortie) de tous les mondes — le registre commun
    (`manifests/builtin/pipeline.builtin_nodes`, R2 du 2026-10-18), plus aucune liste écrite ici."""
    from wama.common.manifests.builtin.pipeline import builtin_nodes
    return tuple(builtin_nodes())


def node_label(app: str) -> str:
    """Le nom d'un nœud tel que l'utilisateur le lit — libellé d'un nœud intégré, sinon son
    identifiant. Ce que dit un refus."""
    from wama.common.manifests.builtin.pipeline import builtin_node
    builtin = builtin_node(app)
    return builtin.label if builtin else app


def step_schema(pipeline, process) -> list:
    """Le schéma de la ⚙ de l'étape `process` — celle que montre la card (`scoped_names`, jumeau
    serveur de `scopedSchema`). Lu par le nœud d'étape, par son contexte (`graph_flow`) et par
    son exécuteur (`tasks._run_app_process`, qui écrit sur l'élément ce que le nœud a décidé)."""
    from wama.common.utils.param_schema import schema_for_app, scoped_names
    app_schema = schema_for_app(pipeline.app)
    kept = set(scoped_names(app_schema, pipeline.watched_of(process)))
    return [p for p in app_schema if p.get('name') in kept]


def _function_schema(spec) -> list:
    """Schéma d'un nœud FONCTION, en dicts : arguments obligatoires de sa tâche (fonction rattachée
    à une app), puis — pour une ÉTAPE de card (process d'un pipeline d'app) — les réglages de la ⚙
    de cette étape, puis ses `ParamSpec` par le pont.

    Les réglages d'une étape sont ceux que la card montre à sa ⚙ (D2, 2026-10-18) : les réglages
    de l'app qui la PÉRIMENT (`AppPipeline.watched_of`, lus au schéma de l'app — la même
    déclaration, au même endroit). L'exécuteur les écrit sur l'élément avant de lancer l'étape
    (`tasks._run_app_process`)."""
    from wama.common.catalog import function_catalog as fc
    params = []
    watched = []
    if spec.binding == fc.Binding.APP and spec.impl:
        from wama.common.services.process_pipeline import process_of_function
        from wama.studio.tasks import app_function_job_kwargs
        try:
            required = app_function_job_kwargs(spec.impl)
        except ValueError:
            required = []
        pipeline, process = process_of_function(spec.key)
        task = spec.impl.split(':')[-1]
        if process is not None:
            step = process.label or process.key
            params += [Param(name=n, type='text', label='Élément',
                             help=f'Le numéro de la card dont lancer l’étape « {step} ».')
                       for n in required]
            # La ⚙ de l'étape, par la règle de la card (`param_schema.scoped_names`, jumeau de
            # `wama-params.js::scopedSchema`) : ce qu'elle surveille, le champ qui COMMANDE la
            # condition d'un réglage retenu (l'interrupteur du résumé, sans lequel le type de
            # résumé restait masqué pour toujours), et les porteurs cachés (`media_type`, que
            # l'élément désigné porte — `graph_flow._step_carriers`).
            watched = step_schema(pipeline, process)
        else:
            params += [Param(name=n, type='text', label=n, help=f'Requis par la tâche {task}.')
                       for n in required]
    return schema_to_dicts(params) + watched + schema_to_dicts(spec.param_schema())


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
        return None if spec is None else {'params': _function_schema(spec), 'groups': []}
    from wama.common.manifests.builtin.pipeline import builtin_node
    builtin = builtin_node(app)
    if builtin is not None:
        return {'params': schema_to_dicts(builtin.params()), 'groups': []}
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
