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


def _pilots(cond, out):
    """Les champs que lit une condition d'affichage (`show_if`) — forme texte ou dict."""
    if isinstance(cond, str) and cond:
        out.add(cond)
    elif isinstance(cond, dict) and cond.get('field'):
        out.add(cond['field'])


def step_carriers(pipeline, process, app_schema=None) -> list:
    """Les PORTEURS cachés (`type='hidden'`) du schéma de l'app que lisent les conditions des
    réglages de l'étape `process` — ce que l'élément porte et que la ⚙ de l'étape ne règle pas
    (le `media_type` du converter). Lu par le schéma du nœud et par son contexte (`graph_flow`)."""
    from wama.common.utils.param_schema import schema_for_app
    app_schema = app_schema if app_schema is not None else schema_for_app(pipeline.app)
    names = set(pipeline.watched_of(process))
    pilots = set()
    for p in app_schema:
        if p.get('name') in names:
            _pilots(p.get('show_if'), pilots)
    return [p['name'] for p in app_schema
            if p.get('type') == 'hidden' and p.get('name') in pilots]


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
            from wama.common.utils.param_schema import schema_for_app
            names = set(pipeline.watched_of(process))
            app_schema = schema_for_app(pipeline.app)
            watched = [p for p in app_schema if p.get('name') in names]
            # Les PILOTES des conditions de ces réglages, qui ne sont pas des réglages de l'étape
            # (2026-10-18) — sans eux, une condition n'est jamais satisfaite et le réglage reste
            # masqué pour toujours (`summary_type` sous `transcriber.summarize`, `media_type` sous
            # `converter.convert` : 2 réglages visibles sur 17) :
            #   • l'INTERRUPTEUR de l'étape (`ProcessSpec.toggle`) : vrai par construction, lancer
            #     l'étape c'est l'activer ;
            #   • les PORTEURS cachés de l'app (`media_type`) : l'élément désigné les porte, le
            #     contexte du nœud les lit sur lui (`graph_flow._step_carriers`).
            carriers = step_carriers(pipeline, process, app_schema)
            hidden = [p for p in app_schema if p.get('name') in carriers]
            if process.toggle and process.toggle not in names:
                hidden.append(schema_to_dicts([Param(name=process.toggle, type='hidden',
                                                     default=True)])[0])
            watched = hidden + watched
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
