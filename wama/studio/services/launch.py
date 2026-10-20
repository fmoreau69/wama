"""
Lancement d'un graphe studio — brique PARTAGÉE vue ⟷ tool_api (assistant IA).

Extraite d'`api_run` (2026-08-11) au moment d'exposer le studio à l'assistant :
la validation (acyclicité, nœuds exécutables) et le dispatch doivent être LES MÊMES
quelle que soit la surface d'appel — les dupliquer aurait créé deux contrats divergents.
"""

from __future__ import annotations


def diagnostiquer_chainage(graph) -> list:
    """Diagnostic des LIENS d'un graphe : type ET champs, avec les champs ACCUMULÉS.

    Rend `[{lien, verdict, raison}]`, `verdict ∈ {'refus', 'abstention'}` — les liens sains ne
    sont pas rapportés. **Ne bloque RIEN** : c'est la passe de MESURE qui doit précéder toute
    mise en application (2026-09-09). `launch_graph` ne l'appelle pas encore ; le jour où on
    active, c'est une ligne ici et non un second contrôle ailleurs — la validation et le
    dispatch doivent rester LES MÊMES (cf. l'en-tête de ce module).

    CE QUE LE CANVAS FAIT DÉJÀ, ET CE QU'IL NE FAIT PAS : côté navigateur, un lien en cours de
    glissement est marqué compatible/incompatible par INTERSECTION DE TYPES. La satisfaction
    des CHAMPS (`required_fields`) n'est vérifiée nulle part — `can_connect` l'implémente
    depuis toujours et n'était appelée que par des tests.

    ⚠⚠ POURQUOI L'ACCUMULATION EST LA CONDITION, pas un raffinement : alimenter le contrôle
    avec les seuls `produced_fields` de l'amont REFUSE `calc_rolling → calc_per_segment`
    (« champs manquants : ['time'] ») — une connexion que la suite déclare VALIDE. Un
    enrichisseur ne « produit » pas les colonnes qu'il laisse passer. Mesuré le 2026-09-09.

    ⚠ INCONNU N'EST PAS VIDE. Un amont qui n'est pas un nœud fonction (app, source, sortie)
    ne déclare aucun `PortSpec` : ses champs sont INCONNUS. On s'ABSTIENT alors, on ne refuse
    pas — `can_connect(available_fields=None)` saute déjà le contrôle des champs, le contrat
    portait donc l'inconnu depuis le début. Même doctrine que `AIModel.gated` : le vide veut
    dire « jamais mesuré », jamais « libre ».
    """
    from wama.common.catalog import function_catalog as fc
    from wama.common.catalog.function_catalog import can_connect
    from wama.common.manifests.builtin.pipeline import node_kind, function_key
    from wama.studio.services.graph_flow import node_flows
    from wama.studio.tasks import topo_order

    graph = graph or {}
    liens = graph.get('links', []) or []
    par_id = {n.get('id'): n for n in (graph.get('nodes', []) or [])}
    fc.load_all()

    def _spec(nid):
        n = par_id.get(nid)
        if n is None or node_kind(n) != 'function':
            return None
        return fc.get(function_key(n))

    constats = []
    #: `champs[nid]` : jeu de champs disponible EN SORTIE du nœud. `None` = inconnu (non mesurable).
    #: Calculé par LE parcours du graphe (`graph_flow.node_flows`, 2026-10-18) — il vivait ici,
    #: seul ; il porte désormais aussi les types et le texte que lit l'inspecteur du Studio.
    champs = {nid: flow['fields'] for nid, flow in node_flows(graph).items()}
    # ⚠ `topo_order` rend les NŒUDS (dicts) en ordre topologique, pas leurs identifiants
    # (`return [nodes[nid] for nid in order]`) — vérifié, pas supposé.
    for noeud in topo_order(graph):
        nid = noeud.get('id')
        spec = _spec(nid)
        entrants = [l for l in liens if l.get('to') == nid]

        # ⚠⚠ LE CONTRÔLE NE VAUT QU'ENTRE NŒUDS QUI SE PASSENT UNE DONNÉE (mesuré 2026-09-09).
        # Une fonction `app`-bound est lancée par `_run_app_function(spec, node['params'], …)` :
        # l'exécuteur ne lui transmet AUCUNE frame amont. Ses liens sont donc de l'ORDRE
        # d'exécution, pas un flux typé. Appliquer le contrat de flux à ces arêtes rendait
        # 10 refus sur les 18 liens du SEUL pipeline réel du corpus (`cam_analyzer`, dont les
        # 13 nœuds sont app-bound) — un pipeline qui tourne. C'étaient des FAUX POSITIFS.
        # *Un lien ne dit pas toujours « ceci coule vers cela ».*
        pure = spec is not None and spec.binding == fc.Binding.PURE

        if spec is not None and not pure:
            for l in entrants:
                constats.append({'lien': l, 'verdict': 'abstention',
                                 'raison': f"aval « {spec.key} » est {spec.binding}-bound — le "
                                           f"lien ordonne, il ne transporte pas de donnée"})

        if pure:
            premier = spec.inputs[0].key if spec.inputs else None
            par_cle = {p.key: p for p in spec.inputs}
            for l in entrants:
                amont = _spec(l.get('from'))
                if amont is None or not amont.outputs:
                    constats.append({'lien': l, 'verdict': 'abstention',
                                     'raison': "amont sans ports déclarés (nœud app, source ou "
                                               "sortie) — champs inconnus, donc non vérifiables"})
                    continue
                if amont.binding != fc.Binding.PURE:
                    # L'exécuteur range la sortie d'un app-bound en TEXTE (`is_text`), pas en
                    # frame — et refuse déjà ce lien À L'EXÉCUTION (« l'amont ne produit pas une
                    # donnée typée »). Le dire STATIQUEMENT est un gain réel, pas un doublon.
                    constats.append({'lien': l, 'verdict': 'refus',
                                     'raison': f"amont « {amont.key} » est {amont.binding}-bound : "
                                               f"sa sortie n'est pas une donnée typée, or "
                                               f"« {spec.key} » est une fonction pure"})
                    continue
                cible = par_cle.get(l.get('to_port') or premier)
                if cible is None:
                    constats.append({'lien': l, 'verdict': 'refus',
                                     'raison': f"port d'entrée « {l.get('to_port') or premier} » "
                                               f"absent de « {spec.key} »"})
                    continue
                ok, raison = can_connect(amont.outputs[0], cible,
                                         available_fields=champs.get(l.get('from')))
                if not ok:
                    constats.append({'lien': l, 'verdict': 'refus', 'raison': raison})
        # Les champs en sortie de chaque nœud — accumulés si l'amont est connu, INCONNUS sinon
        # (l'inconnu se propage, il ne devient jamais un ensemble vide) — sont ceux du parcours
        # commun, calculés plus haut par la même règle.
    return constats


def launch_graph(user, graph, *, pipeline_id=None):
    """Valide puis lance un graphe studio. Retourne (run, None) ou (None, message_d_erreur).

    Validation AVANT dispatch (contrat historique d'`api_run`, aligné sur le code le 2026-09-15) :
      - graphe non vide et ACYCLIQUE (`topo_order`) ;
      - tout nœud CONNECTÉ doit être exécutable (app du runner générique, fonction du
        catalogue, ou nœud intégré — card d'entrée ou de sortie — du registre commun) ;
      - tout nœud, relié ou non, doit figurer dans la PALETTE du compte (`palette.palette_nodes`,
        2026-10-19) : sinon il est refusé en le nommant — non accessible, app non exécutable, ou
        inconnu de WAMA (`palette.unavailable_reason`, la raison que le canvas affiche sur le nœud) ;
      - au moins un nœud app OU fonction exécutable dans le graphe — OU une entrée reliée à une
        sortie : ✅ depuis le 2026-10-11, un pipeline SANS process (entrée → sortie, export seul)
        est accepté, comme le modèle du 2026-09-15 le veut (WAMA_APP_GENERATION_ROUTE.md §10.6
        3.6, §11 #35) ;
      - les réglages de chaque nœud sont applicables (porte commune, 2026-10-12) ;
      - le LOT d'une card d'entrée se déplie en éléments, un run enfant chacun (2026-10-20).
    """
    from wama.studio.models import StudioRun
    from wama.studio.services.runners import runner_for
    from wama.studio.services.generic_runner import GENERIC_APPS
    from wama.studio.tasks import run_pipeline_task, topo_order
    from wama.common.manifests.builtin.pipeline import builtin_nodes, node_kind
    from wama.common.catalog import function_catalog as fc

    graph = graph or {}
    nodes = graph.get('nodes', [])
    if not nodes:
        return None, 'Graphe vide'
    try:
        topo_order(graph)
    except ValueError as exc:
        return None, str(exc)
    links = graph.get('links', [])
    fc.load_all()

    # D13 : un nœud fonction est exécutable ssi sa clé est au catalogue — et l'exécutabilité d'un
    # nœud se lit avec la palette (`palette.executable`), la règle de sa raison quand il manque.
    from wama.studio.services.palette import executable as _executable
    from wama.studio.services.palette import is_function_node as _is_function

    # Les nœuds INTÉGRÉS (cards d'entrée et de sortie) sont ceux que les mondes déclarent au
    # registre commun (R2, 2026-10-18) : exécutabilité ET libellés du refus s'y lisent — la
    # liste « Texte/Médiathèque/… » était recopiée ici.
    builtins = builtin_nodes()
    sources = {key for key, b in builtins.items() if b.role == 'source'}

    runnable = ', '.join(sorted(GENERIC_APPS.keys()))
    builtin_labels = '/'.join(b.label for b in builtins.values())
    for n in nodes:
        # Un nœud non exécutable ne peut être CONNECTÉ ni en amont ni en aval : il ne
        # produira aucune sortie et ne peut rien consommer (validation AVANT dispatch).
        if not _executable(n) and any(
                l['to'] == n['id'] or l['from'] == n['id'] for l in links):
            return None, (f"Nœud « {n['app']} » : non exécutable dans un pipeline "
                          f"(apps : {runnable} + fonctions du catalogue + nœuds "
                          f"{builtin_labels}).")
    # Ce que la PALETTE du compte n'offre pas ne se lance pas (`palette.palette_nodes`, la règle de
    # ce qu'il peut poser — 2026-10-19, `ROADMAP §16.11` piste 4). Une FONCTION y suit l'accès de
    # l'app qui la porte, et c'est aussi sa provenance (une jumelle est à son créateur — `ROADMAP
    # §29` étape 4) ; une APP fermée au compte n'était refusée qu'au run, par `execute_tool`, au
    # milieu de l'exécution. Le canvas GARDE désormais à l'ouverture le nœud qu'il ne connaît pas
    # (réglages et liens intacts, marqué indisponible) : c'est ici qu'il est refusé, en le nommant,
    # relié ou non. La raison est celle que le canvas affiche SUR le nœud (`unavailable_reason`).
    from wama.studio.services.palette import palette_nodes, unavailable_reason
    offered = palette_nodes(user)
    for n in nodes:
        reason = unavailable_reason(user, n, offered)
        if reason:
            return None, reason['message']
    # Le pipeline ENREGISTRÉ dont on lance le graphe doit être visible du compte : le run le
    # nomme (`StudioRun.__str__`), au journal et au calendrier.
    if pipeline_id:
        from wama.common.utils.scoping import listable_by
        from wama.studio.models import StudioPipeline
        if not listable_by(StudioPipeline.objects.filter(pk=pipeline_id), user).exists():
            return None, 'Pipeline introuvable'
    # Un pipeline SANS process est valide s'il relie une ENTRÉE à une SORTIE — l'export sans
    # traitement (« je connecte une base et j'en extrais les tables », ROUTE §10.6 3.6, §11 #35 ;
    # forme précisée par Fabien le 2026-09-15). Ce qui reste refusé : un graphe qui ne ferait RIEN.
    by_id = {n['id']: n for n in nodes}
    feeds_a_sink = any(node_kind(by_id.get(l['to'], {})) == 'sink'
                       and by_id.get(l['from'], {}).get('app') in sources for l in links)
    if not (any(runner_for(n['app']) or _is_function(n) for n in nodes) or feeds_a_sink):
        return None, (f'Rien à exécuter : aucun nœud-app ni nœud fonction, et aucune entrée '
                      f'reliée à une sortie (apps : {runnable}).')
    # Les RÉGLAGES de chaque nœud passent la porte commune AVANT le dispatch (2026-10-12) : un
    # choix hors liste, un nombre illisible ou hors de sa grille se refusent ici, en le nommant,
    # contre le schéma que l'inspecteur a rendu (`node_params.node_schema`) — au lieu d'échouer au
    # milieu d'un run, ou d'être remplacés en silence par un défaut.
    from wama.common.utils.param_schema import describe_refusals, schema_refusals
    from wama.studio.services.node_params import node_label, node_schema
    for n in nodes:
        schema = node_schema(n['app'])
        refusals = schema_refusals(schema['params'], n.get('params') or {}) if schema else {}
        if refusals:
            return None, (f"Nœud « {node_label(n['app'])} » : réglage(s) refusé(s) — "
                          f"{describe_refusals(refusals)}")

    # Le LOT (2026-10-20, `STUDIO_VISION §Entrées du Studio`) : plusieurs fichiers de travail ou un
    # fichier de lot = un lot, et le pipeline tourne une fois par élément. Déplié ICI, avant le
    # dispatch : un fichier de lot illisible, une colonne sans port, deux lots dans un pipeline ou
    # un réglage de ligne inconnu de l'app se refusent en le nommant, sans rien lancer. Chaque
    # élément est un run enfant du run lancé (une card mère et ses filles) ; un fichier de lot
    # d'UNE ligne n'en fait qu'un, joué à la place du graphe.
    from wama.studio.services.entries import lot_graphs
    try:
        elements = lot_graphs(user, graph)
    except ValueError as exc:
        return None, str(exc)
    if len(elements) == 1:
        graph, elements = elements[0], []
    run = StudioRun.objects.create(user=user, graph=graph, pipeline_id=pipeline_id)
    for element in elements:
        StudioRun.objects.create(user=user, graph=element, pipeline_id=pipeline_id, parent=run)
    task = run_pipeline_task.delay(run.pk)
    run.task_id = task.id
    run.save(update_fields=['task_id'])
    return run, None
