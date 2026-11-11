"""Le process FONCTION qu'une card ajoute à son pipeline — commun à tous les mondes.

`WAMA_APP_GENERATION_ROUTE §10.6` 3.2bis, marche 3 (2026-11-11), livrée avec la marche 2 : une
card qui porte des process AJOUTÉS (`card_pipelines`) les joue par le squelette de tâche comme
les autres, et chacun reçoit ICI sa glu — le même contrat que toute glu (`glu(item, ctx) -> dict`,
cf. `output_process.output_step`).

CE QUE LA GLU FAIT
  • elle joue la fonction du catalogue par la MÊME porte que l'exécuteur du Studio
    (`run_pure_function`, écrite dans `studio/tasks.py` et remontée ici telle quelle : premier port
    positionnel, ports suivants par nom, réglages par `FunctionSpec.call_params`) ;
  • un MÉTA-PROCESS (nœud `pipeline`, un module du monde Data) joue ses membres dans l'ordre de
    son sous-graphe déployé, leurs données en mémoire d'un membre à l'autre ;
  • ses entrées : ce que ses amonts ont RANGÉ (`read_upstreams`) — une sortie d'amont qui n'est
    pas une donnée typée (un média) n'alimente aucun port, et un port requis non alimenté est un
    refus nommé ;
  • sa sortie va dans le FICHIER DE TRAVAIL de la card, jamais dans la base de WAMA : les données
    de l'utilisateur TRANSITENT par WAMA le temps des process, elles n'y entrent pas (décision de
    Fabien du 2026-11-11, `WAMA_DATA_WORLD §11.8 ⑩.2`). La ligne d'exécution n'en garde que
    l'ADRESSE (`output_ref` = le fichier, `output_summary['table']` = la table) et l'empreinte du
    contenu (`output_fingerprint`) — le fichier contient les sorties de tous les process de la
    card, son empreinte ne dirait rien d'un seul.

QUI RANGE. Le substrat ne cite aucun monde : le FORMAT du fichier de travail est celui du monde qui
sait ranger une donnée typée — le monde Data y inscrit son `.wdat` transitoire
(`register_work_store`, depuis `wama_data/apps.py`), comme il inscrit sa sonde d'import et ses
nœuds d'entrée. Le substrat ne décide que de l'EMPLACEMENT : un fichier par card, dans le dossier
temporaire de son propriétaire (`work_file`). Sans monde inscrit, le process est refusé en le
disant.

Un process ajouté qui n'est pas une fonction PURE (une fonction rattachée à une app, une passe du
Lab) n'a pas de glu ici : le lancement le refuse en le nommant (« process sans glu »,
`task_skeleton._selected_steps`).
"""
from __future__ import annotations

import os

#: Sous-dossier du dossier TEMPORAIRE de l'utilisateur qui reçoit les fichiers de travail.
WORK_FOLDER = 'work'

_STORE = None


def register_work_store(store) -> None:
    """Le monde qui RANGE une donnée typée s'inscrit (idempotent : le dernier inscrit gagne). Le
    rangement porte `extension` (celle du fichier de travail), `write(chemin absolu, nom, cadre)
    -> {'table', 'fingerprint'}` (le nom d'une table rejouée la REMPLACE) et `read(chemin absolu,
    table) -> TypedFrame`."""
    global _STORE
    _STORE = store


def work_store():
    """Le rangement inscrit, ou None (aucun monde ne range de donnée typée dans ce processus)."""
    return _STORE


def run_pure_function(spec, frames_by_port: dict, params: dict):
    """`spec.fn(premier port, <autres ports par mot-clé>, **params)` — le contrat que
    `wama_data/view.py::apply` applique déjà (premier port positionnel) étendu aux fonctions
    à plusieurs entrées (`gps_map_match(track, road_map)` : ports suivants par NOM de port).
    Un port `many` reçoit la liste des frames amont.

    Écrite dans l'exécuteur du Studio (`studio/tasks.py`), remontée au moteur le 2026-11-11 : la
    glu commune d'un process ajouté à une card joue la fonction par la MÊME porte."""
    from wama.common.catalog.data_types import TypedFrame
    positional, keywords = None, {}
    for i, port in enumerate(spec.inputs):
        got = frames_by_port.get(port.key)
        if got is None:
            if port.optional:
                continue
            raise ValueError(f"port « {port.key} » ({port.data_type}) non alimenté — "
                             f"connectez un nœud amont typé")
        if port.cardinality != 'many' and isinstance(got, list):
            got = got[-1]
        if i == 0:
            positional = got
        else:
            keywords[port.key] = got
    if positional is None:
        raise ValueError("aucune entrée")
    # Les réglages passent par LA porte de la fonction (`FunctionSpec.call_params` : le pont vers
    # `Param`, puis `checked_values`) — types ET bornes, refus nommés. L'ancienne coercition locale
    # ne connaissait que les types : une borne déclarée n'était tenue nulle part au lancement.
    result = spec.fn(positional, **keywords, **spec.call_params(params))
    if not isinstance(result, TypedFrame):
        raise ValueError(f"la fonction n'a pas rendu un TypedFrame ({type(result).__name__}) — "
                         f"contrat `pure` non honoré (noyau branché à la place du wrapper ?)")
    # La facette estimateur du port VOYAGE avec la donnée : c'est ce que `fuse_estimates` lit en
    # aval (et rien d'autre). Posée par l'exécuteur du Studio jusqu'au 2026-11-11, ICI depuis : la
    # porte commune la pose pour tout appelant, membre d'un méta-process compris.
    if spec.outputs:
        from wama.common.catalog.function_catalog import port_estimate_meta
        facet = port_estimate_meta(spec.outputs[0])
        if facet and 'estimate' not in result.meta:
            result.meta['estimate'] = {**facet, 'name': spec.key}
    return result


def work_file(item, extension: str) -> str:
    """L'emplacement (relatif à `MEDIA_ROOT`) du fichier de travail de CETTE card : un par card,
    dans le dossier temporaire de son propriétaire, sous la règle de conservation du dossier
    temporaire (`retention.purge_expired_temp`). Lève `ValueError` pour une card sans propriétaire."""
    owner = getattr(item, 'user_id', None)
    if owner is None:
        raise ValueError("cette card n'a pas de propriétaire : son fichier de travail n'a pas de "
                         "dossier")
    meta = item._meta
    name = f'{meta.app_label}_{meta.model_name}_{item.pk}{extension}'
    return f'users/{owner}/temp/{WORK_FOLDER}/{name}'


def _absolute(rel: str) -> str:
    from django.conf import settings
    return os.path.join(settings.MEDIA_ROOT, rel)


def _required_store():
    store = work_store()
    if store is None:
        raise RuntimeError("aucun monde ne range de donnée typée ici : le process ajouté n'a pas de "
                           "fichier de travail où écrire")
    return store


def is_pure(pipeline, spec) -> bool:
    """Le process ajouté a-t-il une glu ici ? Une fonction PURE du catalogue, ou un méta-process
    dont tous les membres le sont."""
    from wama.common.catalog import function_catalog as fc
    from wama.common.manifests.builtin.pipeline import function_key
    if spec.pipeline:
        members = (pipeline.metas.get(spec.key) or {}).get('nodes') or []
        keys = [function_key(m) for m in members]
    else:
        keys = [pipeline.function_key(spec)]
    found = [fc.get(k) for k in keys]
    return bool(found) and all(f is not None and f.binding == fc.Binding.PURE for f in found)


def with_added_glues(pipeline, processes) -> dict:
    """Les glus de l'app, plus celle de chaque process que la card AJOUTE et qui a une glu ici
    (`is_pure`). Un process ajouté sans glu reste absent : le lancement le refuse en le nommant."""
    added = getattr(pipeline, 'added', frozenset())
    out = dict(processes or {})
    for key in added:
        if key not in out and is_pure(pipeline, pipeline.spec(key)):
            out[key] = function_step(pipeline, key)
    return out


def upstream_frames(pipeline, spec, item, store) -> list:
    """Les données TYPÉES que les amonts LUS du process (`read_upstreams`) ont rangées dans le
    fichier de travail de la card, dans l'ordre de leurs liens. Un amont qui n'a rien rangé (un
    process d'app : sa sortie est un fichier de la card) n'en donne pas."""
    rows = pipeline.rows(item)
    frames = []
    for upstream in pipeline.read_upstreams(spec, item):
        row = rows.get(upstream)
        table = ((row.output_summary or {}).get('table') if row is not None else '') or ''
        if row is not None and row.output_ref and table:
            frames.append(store.read(_absolute(row.output_ref), table))
    return frames


def frames_by_port(function, frames, taken=()) -> dict:
    """`{port: cadre(s)}` — chaque cadre va au premier port d'entrée dont le type l'ACCEPTE
    (`data_types.is_compatible`), un port `many` les recevant tous ; les ports de `taken` (déjà
    alimentés par un lien qui les nomme) sont passés. Le lien d'une card ne nomme pas son port
    (ses amonts sont des process) : c'est le type qui décide, comme `_resolve_to_port` au Studio
    pour un lien qui n'en précise pas."""
    from wama.common.catalog.data_types import is_compatible
    out, used = {}, set()
    for port in function.inputs:
        if port.key in taken:
            continue
        fitting = [i for i, frame in enumerate(frames)
                   if i not in used and is_compatible(frame.data_type, port.data_type)]
        if not fitting:
            continue
        if port.cardinality == 'many':
            out[port.key] = [frames[i] for i in fitting]
            used |= set(fitting)
        else:
            out[port.key] = frames[fitting[0]]
            used.add(fitting[0])
    return out


def _summary(frame) -> str:
    try:
        return f"{frame.data_type} · {len(frame.df)} ligne(s)"
    except Exception:
        return str(getattr(frame, 'data_type', ''))


def _member_inputs(function, incoming, produced) -> dict:
    """Les entrées d'un membre de méta-process depuis ses liens internes : un lien qui NOMME un port
    de la fonction y entre — la règle de l'exécuteur du Studio pour le même sous-graphe —, les
    autres vont au port que leur type accepte (`frames_by_port`)."""
    known = {p.key for p in function.inputs}
    named, loose = {}, []
    for link in incoming:
        port = link.get('to_port')
        if port in known:
            named.setdefault(port, []).append(produced[link['from']])
        else:
            loose.append(produced[link['from']])
    named = {p: (v if len(v) > 1 else v[0]) for p, v in named.items()}
    return {**frames_by_port(function, loose, taken=named), **named}


def _run_meta(pipeline, spec, frames, write) -> tuple:
    """Les membres d'un méta-process, dans l'ordre de son sous-graphe : un membre sans amont
    interne reçoit les données de la card, les autres celles de leurs amonts internes. Chaque
    sortie est rangée (`write`) ; rend `(table de sortie, empreinte, résumé)` — la sortie du
    membre TERMINAL quand il est unique, sinon aucune (plusieurs sorties : l'aval ne saurait
    laquelle lire, et la ligne les nomme toutes)."""
    from wama.common.catalog import function_catalog as fc
    from wama.common.manifests.builtin.pipeline import function_key, topo_order
    deployed = pipeline.metas.get(spec.key) or {}
    links = deployed.get('links') or []
    produced, written, outs = {}, {}, []
    for member in topo_order(deployed):
        mid = member['id']
        incoming = [l for l in links if l.get('to') == mid and l['from'] in produced]
        function = fc.get(function_key(member))
        inputs = (_member_inputs(function, incoming, produced) if incoming
                  else frames_by_port(function, frames))
        produced[mid] = run_pure_function(function, inputs, member.get('params') or {})
        written[mid] = write(mid, produced[mid])
    terminals = [m for m in produced if not any(l.get('from') == m for l in links)]
    outs = [f"{t} : {_summary(produced[t])}" for t in terminals]
    if len(terminals) == 1:
        done = written[terminals[0]]
        return done['table'], done['fingerprint'], '; '.join(outs)
    return '', '', '; '.join(outs)


def function_step(pipeline, key: str):
    """La GLU commune du process ajouté `key` de `pipeline`, au contrat du squelette."""

    def step(item, ctx):
        from wama.common.catalog import function_catalog as fc
        store = _required_store()
        spec = pipeline.spec(key)
        rel = work_file(item, store.extension)
        path = _absolute(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        frames = upstream_frames(pipeline, spec, item, store)
        ctx.progress(10)
        if spec.pipeline:
            table, fingerprint, label = _run_meta(
                pipeline, spec, frames, lambda name, frame: store.write(path, name, frame))
        else:
            function = fc.get(pipeline.function_key(spec))
            frame = run_pure_function(function, frames_by_port(function, frames),
                                      pipeline.added_params.get(key) or {})
            done = store.write(path, key, frame)
            table, fingerprint, label = done['table'], done['fingerprint'], _summary(frame)
        return {'output_ref': rel, 'output_table': table, 'output_fingerprint': fingerprint,
                'label': f"{spec.label or key} — {label}"}

    return step


def release_work_file(item) -> bool:
    """La card est RETIRÉE : son fichier de travail est libéré et annoncé (`released_files`), jamais
    effacé en silence — il vit ensuite sous la règle du dossier temporaire. Rend True s'il y en
    avait un. Ne lève jamais."""
    store = work_store()
    if store is None or getattr(item, 'user_id', None) is None:
        return False
    try:
        from wama.common.services.released_files import release_path
        rel = work_file(item, store.extension)
        return release_path(rel, getattr(item, 'user', None),
                            origin=f'{item._meta.label}#{item.pk} · fichier de travail') is not None
    except Exception:
        return False
