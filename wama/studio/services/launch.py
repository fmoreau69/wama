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
    from wama.common.catalog.function_catalog import can_connect, champs_apres
    from wama.common.manifests.builtin.pipeline import node_kind, function_key
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
    champs: dict = {}
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

        # Champs en sortie : accumulés si l'amont était connu, inconnus sinon — l'inconnu se
        # PROPAGE, il ne se convertit pas en ensemble vide (ce qui refuserait la suite à tort).
        # ⚠ Seule une fonction PURE rend une donnée typée : l'exécuteur range la sortie d'un
        # app-bound en TEXTE. Ses champs sont donc inconnus, pas vides.
        if not pure or not spec.outputs:
            champs[nid] = None
            continue
        amonts = [champs.get(l.get('from')) for l in entrants]
        avant = set()
        for a in amonts:
            if a is None:
                avant = None
                break
            avant |= a
        champs[nid] = None if (entrants and avant is None) else champs_apres(
            spec.outputs[0], spec.key, avant or set())
    return constats


def launch_graph(user, graph, *, pipeline_id=None):
    """Valide puis lance un graphe studio. Retourne (run, None) ou (None, message_d_erreur).

    Validation AVANT dispatch (contrat historique d'`api_run`) :
      - graphe non vide et ACYCLIQUE (`topo_order`) ;
      - tout nœud CONNECTÉ doit être exécutable (app du runner générique, source
        Texte/Médiathèque, ou sortie `studio_output`) ;
      - au moins un nœud-app exécutable dans le graphe.
    """
    from wama.studio.models import StudioRun
    from wama.studio.services.runners import runner_for
    from wama.studio.services.generic_runner import GENERIC_APPS
    from wama.studio.tasks import run_pipeline_task, topo_order, SOURCE_HANDLERS
    from wama.common.manifests.builtin.pipeline import node_kind, function_key
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

    def _is_function(n):
        # D13 : un nœud fonction est exécutable ssi sa clé est au catalogue.
        return node_kind(n) == 'function' and fc.get(function_key(n)) is not None

    def _executable(n):
        app = n['app']
        return (runner_for(app) is not None or app in SOURCE_HANDLERS
                or app == 'studio_output' or _is_function(n))

    runnable = ', '.join(sorted(GENERIC_APPS.keys()))
    for n in nodes:
        # Un nœud non exécutable ne peut être CONNECTÉ ni en amont ni en aval : il ne
        # produira aucune sortie et ne peut rien consommer (validation AVANT dispatch).
        if not _executable(n) and any(
                l['to'] == n['id'] or l['from'] == n['id'] for l in links):
            return None, (f"Nœud « {n['app']} » : non exécutable dans un pipeline "
                          f"(apps : {runnable} + fonctions du catalogue + nœuds "
                          f"Texte/Médiathèque/Jeu de données/Sortie).")
    if not any(runner_for(n['app']) or _is_function(n) for n in nodes):
        return None, (f'Aucun nœud-app ni nœud fonction exécutable dans le graphe '
                      f'(apps : {runnable}).')

    run = StudioRun.objects.create(user=user, graph=graph, pipeline_id=pipeline_id)
    task = run_pipeline_task.delay(run.pk)
    run.task_id = task.id
    run.save(update_fields=['task_id'])
    return run, None
