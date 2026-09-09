"""
Studio — orchestration d'un pipeline (tâche Celery).

Exécution V1 : ordre TOPOLOGIQUE d'un graphe acyclique ; chaque nœud-app est traité par
son runner (studio/services/runners.py) : create → start → poll (le traitement lui-même
tourne dans le Celery de l'app cible — le studio ne fait qu'orchestrer et chaîner les
sorties). Les nœuds-source intégrés (prompt_batch, media_import) ne sont pas exécutables
en V1 : les entrées initiales viennent des params de nœud (ex. « Texte » du synthesizer).

D13 — nœud `function` (2026-09-09, `WAMA_DATA_WORLD §9undecies.2`) : le dispatch se fait
ICI, sur le kind du nœud (`manifests.builtin.pipeline.node_kind`), jamais dans le schéma :
  • `app`      → job de file ASYNCHRONE (runner : create/start/poll), sortie = fichier ;
  • `function` → `pure` : transformation typée SYNCHRONE, `spec.fn(TypedFrame, **params)`
                 dans ce process, sortie = `TypedFrame` porteur de la facette estimateur de
                 son port (`port_estimate_meta`) ; `app`-bound : `impl` est une tâche Celery
                 lancée puis POLLÉE comme un job (session_id… viennent des params du nœud).
Un `TypedFrame` circule EN MÉMOIRE entre deux nœuds fonction d'un même run ; `node_states`
n'en garde qu'un résumé (type, lignes, colonnes). La porte d'ingestion d'un fichier Data vers
un nœud fonction est le nœud-source `dataset_input` (marche E : l'importeur de manifeste
de process en sera la seconde entrée).
"""
import time

from celery import shared_task

from wama.common.utils.console_utils import push_console_line

POLL_INTERVAL_S = 3
NODE_TIMEOUT_S = 30 * 60


def _console(user_id, message, level='info'):
    try:
        push_console_line(user_id, message, level=level, app='studio')
    except Exception:
        pass


def topo_order(graph):
    """Ordre topologique des nœuds ({id: [ids amont]}) ; lève ValueError si cycle."""
    nodes = {n['id']: n for n in graph.get('nodes', [])}
    incoming = {nid: set() for nid in nodes}
    for l in graph.get('links', []):
        if l['from'] in nodes and l['to'] in nodes:
            incoming[l['to']].add(l['from'])
    order, ready = [], [nid for nid, deps in incoming.items() if not deps]
    pending = {nid: set(deps) for nid, deps in incoming.items() if deps}
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for other, deps in list(pending.items()):
            deps.discard(nid)
            if not deps:
                del pending[other]
                ready.append(other)
    if pending:
        raise ValueError('Le graphe contient un cycle — exécution impossible.')
    return [nodes[nid] for nid in order]


# ── Nœuds SOURCE (cards d'entrée) : produisent une valeur depuis leurs params ──
def _source_text(user, params):
    text = (params.get('text') or '').strip()
    if not text:
        raise ValueError("Nœud « Texte » : renseignez le texte dans les paramètres du nœud.")
    return 'prompt', text


def _source_media(user, params):
    import os
    from django.conf import settings
    rel = (params.get('asset_path') or '').strip().lstrip('/')
    if rel.startswith('media/'):
        rel = rel[len('media/'):]
    if not rel:
        raise ValueError("Nœud « Médiathèque » : choisissez un média dans les paramètres du nœud.")
    if not os.path.exists(os.path.join(settings.MEDIA_ROOT, rel)):
        raise ValueError(f"Nœud « Médiathèque » : fichier introuvable ({rel}).")
    from wama.common.app_registry import category_of_path
    return (params.get('asset_category') or category_of_path(rel)), rel


def _sink_text_to_media_library(user, text, params, run_id):
    """Variante TEXTE du nœud Sortie : écrit un .txt et le range en médiathèque (document)."""
    import io
    from django.core.files.base import ContentFile
    from wama.media_library.models import UserAsset
    base = (params.get('asset_name') or '').strip() or f"studio-run-{run_id}"
    asset_type = params.get('asset_type') or 'document'
    name, k = base, 2
    while UserAsset.objects.filter(user=user, name=name, asset_type=asset_type).exists():
        name = f"{base} ({k})"
        k += 1
    asset = UserAsset(user=user, name=name, asset_type=asset_type, mime_type='text/plain')
    asset.file.save(f"{base}.txt", ContentFile(text.encode('utf-8')), save=False)
    try:
        asset.file_size = asset.file.size
    except Exception:
        pass
    asset.save()
    return f"médiathèque : « {name} » (texte, {len(text)} car.)"


def _source_dataset(user, params):
    """Nœud « Jeu de données » : un fichier tabulaire (CSV) de la médiathèque → `TypedFrame`
    du `data_type` choisi. C'est la CARD D'ENTRÉE de `WAMA_DATA_FUNCTION_CARDS §5` (source +
    type déclaré → port typé), pas un contournement du pivot taxonomique (marche B) : le type
    est DIT par l'utilisateur, jamais deviné d'une extension."""
    import os
    from django.conf import settings
    from wama.common.catalog.data_types import DataType, TypedFrame, normalize_type
    rel = (params.get('asset_path') or '').strip().lstrip('/')
    if rel.startswith('media/'):
        rel = rel[len('media/'):]
    if not rel:
        raise ValueError("Nœud « Jeu de données » : choisissez un fichier dans les paramètres du nœud.")
    path = os.path.join(settings.MEDIA_ROOT, rel)
    if not os.path.exists(path):
        raise ValueError(f"Nœud « Jeu de données » : fichier introuvable ({rel}).")
    dtype = normalize_type((params.get('data_type') or DataType.TABLE).strip())
    connus = {v for k, v in vars(DataType).items() if not k.startswith('_') and isinstance(v, str)}
    if dtype not in connus:
        raise ValueError(f"Nœud « Jeu de données » : type '{dtype}' inconnu de la taxonomie.")
    import pandas as pd
    try:
        df = pd.read_csv(path, sep=None, engine='python')
    except Exception as exc:
        raise ValueError(f"Nœud « Jeu de données » : lecture impossible ({exc}).")
    return dtype, TypedFrame(df, dtype, meta={'source': rel})


SOURCE_HANDLERS = {
    'text_input': _source_text,
    'media_import': _source_media,
    'dataset_input': _source_dataset,
}


# ── Nœud FONCTION (D13) ──────────────────────────────────────────────────────
def _frame_summary(frame) -> str:
    try:
        return f"{frame.data_type} · {len(frame.df)} ligne(s) · {', '.join(map(str, frame.fields))}"
    except Exception:
        return repr(frame)


def _coerce_params(spec, params: dict) -> dict:
    """Params de nœud (formulaire : chaînes) → types des `ParamSpec` ; vide = défaut de la
    fonction (on ne passe rien, comme le runner générique)."""
    out = {}
    declared = {p.key: p for p in spec.params}
    for k, v in (params or {}).items():
        if v in (None, ''):
            continue
        ps = declared.get(k)
        if ps is None:
            continue          # un param inconnu de la fonction ne lui est pas passé
        try:
            if ps.type == 'float':
                v = float(v)
            elif ps.type == 'int':
                v = int(float(v))
            elif ps.type == 'bool':
                v = str(v).strip().lower() in ('1', 'true', 'oui', 'on', 'yes')
        except (TypeError, ValueError):
            raise ValueError(f"paramètre `{k}` : valeur {v!r} non convertible en {ps.type}")
        out[k] = v
    return out


def _run_pure_function(spec, frames_by_port: dict, params: dict):
    """`spec.fn(premier port, <autres ports par mot-clé>, **params)` — le contrat que
    `wama_data/view.py::apply` applique déjà (premier port positionnel) étendu aux fonctions
    à plusieurs entrées (`gps_map_match(track, road_map)` : ports suivants par NOM de port).
    Un port `many` reçoit la liste des frames amont."""
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
    result = spec.fn(positional, **keywords, **_coerce_params(spec, params))
    if not isinstance(result, TypedFrame):
        raise ValueError(f"la fonction n'a pas rendu un TypedFrame ({type(result).__name__}) — "
                         f"contrat `pure` non honoré (noyau branché à la place du wrapper ?)")
    return result


def _impl_callable(impl: str):
    """`module.chemin:attribut` → objet (tâche Celery ou fonction)."""
    import importlib
    if ':' not in impl:
        raise ValueError(f"impl `{impl}` : forme attendue `module:attribut`")
    mod, attr = impl.split(':', 1)
    for candidate in (mod, f'wama_lab.{mod}', f'wama.{mod}'):
        try:
            return getattr(importlib.import_module(candidate), attr)
        except (ImportError, AttributeError):
            continue
    raise ValueError(f"impl `{impl}` introuvable")


def app_function_job_kwargs(impl: str) -> list:
    """Noms des paramètres OBLIGATOIRES de la tâche `impl` (hors `self`) — ce que le nœud
    doit fournir dans ses params (ex. `session_id`). Introspection, jamais une liste par app."""
    import inspect
    target = _impl_callable(impl)
    fn = getattr(target, 'run', None) or getattr(target, '__wrapped__', None) or target
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return []
    return [n for n, p in sig.parameters.items()
            if n != 'self' and p.default is inspect.Parameter.empty
            and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)]


def _run_app_function(spec, params: dict, save_state, deadline_s: float):
    """Fonction `app`-bound = un JOB : `impl` (tâche Celery) lancée avec les params du nœud,
    puis POLLÉE comme un nœud-app. Sans `.delay` (fonction ordinaire), appel direct."""
    target = _impl_callable(spec.impl)
    required = app_function_job_kwargs(spec.impl)
    kwargs = {k: v for k, v in (params or {}).items() if v not in (None, '')}
    missing = [k for k in required if k not in kwargs]
    if missing:
        raise ValueError(f"paramètre(s) requis manquant(s) pour {spec.key} : {', '.join(missing)}")
    if not hasattr(target, 'apply_async'):
        return target(**kwargs)
    async_result = target.apply_async(kwargs=kwargs)
    save_state(item_id=async_result.id)
    deadline = time.time() + deadline_s
    while not async_result.ready():
        if time.time() > deadline:
            raise ValueError(f"{spec.key} : délai dépassé ({int(deadline_s) // 60} min).")
        time.sleep(POLL_INTERVAL_S)
    if async_result.failed():
        raise ValueError(f"{spec.key} : échec — {async_result.result}")
    return async_result.result


# ── Nœud de SORTIE (card de sortie) : range le résultat final ──
def _sink_frame_to_media_library(user, frame, params, run_id):
    """Variante DONNÉES du nœud Sortie : un `TypedFrame` (sortie d'un nœud fonction) écrit
    en CSV et rangé en médiathèque (`document`) — la même porte que le texte."""
    from django.core.files.base import ContentFile
    from wama.media_library.models import UserAsset
    base = (params.get('asset_name') or '').strip() or f"studio-run-{run_id}-{frame.data_type}"
    asset_type = params.get('asset_type') or 'document'
    name, k = base, 2
    while UserAsset.objects.filter(user=user, name=name, asset_type=asset_type).exists():
        name = f"{base} ({k})"
        k += 1
    asset = UserAsset(user=user, name=name, asset_type=asset_type, mime_type='text/csv')
    csv = frame.df.to_csv(index=False)
    asset.file.save(f"{base}.csv", ContentFile(csv.encode('utf-8')), save=False)
    try:
        asset.file_size = asset.file.size
    except Exception:
        pass
    asset.save()
    return f"médiathèque : « {name} » ({frame.data_type}, {len(frame.df)} ligne(s))"


def _sink_media_library(user, value, params):
    """Copie la sortie dans la MÉDIATHÈQUE (UserAsset) — fichier DUPLIQUÉ (la sortie
    d'app reste dans sa file ; l'asset est autonome, supprimable indépendamment)."""
    import os
    from django.conf import settings
    from django.core.files import File
    from wama.common.utils.mime_utils import guess_mime_type
    from wama.media_library.models import UserAsset
    src_abs = os.path.join(settings.MEDIA_ROOT, value)
    if not os.path.exists(src_abs):
        raise ValueError(f"Nœud « Sortie » : fichier à ranger introuvable ({value}).")
    asset_type = params.get('asset_type') or 'video'
    base = (params.get('asset_name') or '').strip() or os.path.splitext(os.path.basename(value))[0]
    name, k = base, 2
    while UserAsset.objects.filter(user=user, name=name, asset_type=asset_type).exists():
        name = f"{base} ({k})"
        k += 1
    asset = UserAsset(user=user, name=name, asset_type=asset_type,
                      mime_type=guess_mime_type(value) or '')
    with open(src_abs, 'rb') as fh:
        asset.file.save(os.path.basename(value), File(fh), save=False)
    try:
        asset.file_size = asset.file.size
    except Exception:
        pass
    asset.save()
    return f"médiathèque : « {name} » ({asset_type})"


@shared_task(bind=True)
def run_pipeline_task(self, run_id):
    from django.contrib.auth import get_user_model
    from .models import StudioRun
    from .services.runners import runner_for

    run = StudioRun.objects.get(pk=run_id)
    user = run.user
    t0 = time.time()
    run.status = 'RUNNING'
    run.save(update_fields=['status'])
    _console(user.id, f"Studio run #{run.pk} : démarrage")

    states = dict(run.node_states or {})

    def _save_state(node_id, **kw):
        states.setdefault(node_id, {})
        states[node_id].update(kw)
        run.node_states = states
        run.save(update_fields=['node_states'])

    try:
        from wama.common.manifests.builtin.pipeline import node_kind, function_key
        order = topo_order(run.graph)
        links = run.graph.get('links', [])
        outputs = {}   # node_id -> {'type': 'audio'|..., 'value': chemin MEDIA relatif | TypedFrame}

        for node in order:
            nid, app = node['id'], node['app']

            # Nœud SOURCE (card d'entrée) : produit sa valeur depuis ses params.
            if app in SOURCE_HANDLERS:
                _save_state(nid, status='RUNNING')
                out_type, value = SOURCE_HANDLERS[app](user, node.get('params') or {})
                is_frame = hasattr(value, 'df') and hasattr(value, 'data_type')
                outputs[nid] = {'type': out_type, 'value': value, 'is_frame': is_frame}
                _save_state(nid, status='SUCCESS',
                            output=_frame_summary(value) if is_frame else value)
                continue

            # Nœud de SORTIE (card de sortie) : range la valeur reçue de l'amont.
            if app == 'studio_output':
                _save_state(nid, status='RUNNING')
                incoming = [outputs[l['from']] for l in links
                            if l['to'] == nid and l['from'] in outputs]
                if not incoming:
                    raise ValueError("Nœud « Sortie » : aucune entrée reçue (connectez un nœud amont).")
                if incoming[0].get('is_frame'):
                    note = _sink_frame_to_media_library(user, incoming[0]['value'],
                                                        node.get('params') or {}, run.pk)
                elif incoming[0].get('is_text'):
                    note = _sink_text_to_media_library(user, incoming[0]['value'],
                                                       node.get('params') or {}, run.pk)
                else:
                    note = _sink_media_library(user, incoming[0]['value'], node.get('params') or {})
                _save_state(nid, status='SUCCESS', output=note)
                _console(user.id, f"Studio run #{run.pk} : sortie rangée — {note}")
                continue

            # Nœud FONCTION (D13) : dispatch sur le kind, ICI et nulle part ailleurs.
            if node_kind(node) == 'function':
                from wama.common.catalog import function_catalog as fc
                from wama.common.catalog.function_catalog import port_estimate_meta
                fc.load_all()
                key = function_key(node)
                spec = fc.get(key)
                if spec is None:
                    raise ValueError(f"Nœud fonction « {key} » : absent du catalogue.")
                _save_state(nid, status='RUNNING', progress=0)
                _console(user.id, f"Studio run #{run.pk} : fonction {key} ({spec.binding})")
                if spec.binding == fc.Binding.PURE:
                    frames = {}
                    ports_connus = {p.key for p in spec.inputs}
                    first_port = spec.inputs[0].key if spec.inputs else None
                    for l in links:
                        if l['to'] != nid or l['from'] not in outputs:
                            continue
                        up = outputs[l['from']]
                        if not up.get('is_frame'):
                            raise ValueError(
                                f"Nœud fonction « {key} » : l'amont « {l['from']} » ne produit pas "
                                f"une donnée typée (fichier {up.get('type')}) — passez par un "
                                f"nœud « Jeu de données » ou une autre fonction.")
                        # `to_port` désigne un port PAR SON ID depuis le 2026-09-09. Un lien qui
                        # n'en nomme aucun — ou qui en nomme un que cette fonction n'a pas —
                        # entre par le PREMIER port. Deux cas réels, et le second est celui qui
                        # se perdait en silence : un graphe sauvegardé AVANT cette date porte le
                        # RÔLE du port (`travail`), et les ports intégrés du JS (Sortie, Jeu de
                        # données) n'ont pas d'id du tout. Sans ce repli, la donnée était rangée
                        # sous une clé que `_run_pure_function` ne lit jamais, et le port requis
                        # ressortait « non alimenté » — un message qui accuse le graphe alors que
                        # c'est le nom du lien qui a vieilli.
                        port = l.get('to_port')
                        if port not in ports_connus:
                            port = first_port
                        frames.setdefault(port, []).append(up['value'])
                    frames = {p: (v if len(v) > 1 else v[0]) for p, v in frames.items()}
                    try:
                        result = _run_pure_function(spec, frames, node.get('params') or {})
                    except ValueError as exc:
                        raise ValueError(f"Nœud fonction « {key} » : {exc}")
                    # La facette estimateur du port VOYAGE avec la donnée : c'est ce que
                    # `fuse_estimates` lit en aval (et rien d'autre).
                    if spec.outputs:
                        facet = port_estimate_meta(spec.outputs[0])
                        if facet and 'estimate' not in result.meta:
                            result.meta['estimate'] = {**facet, 'name': key}
                    outputs[nid] = {'type': result.data_type, 'value': result, 'is_frame': True}
                    _save_state(nid, status='SUCCESS', progress=100, output=_frame_summary(result))
                    _console(user.id, f"Studio run #{run.pk} : fonction {key} ✔ → {_frame_summary(result)}")
                else:
                    res = _run_app_function(spec, node.get('params') or {},
                                            lambda **kw: _save_state(nid, **kw), NODE_TIMEOUT_S)
                    otype = spec.outputs[0].data_type if spec.outputs else 'scalar'
                    outputs[nid] = {'type': otype, 'value': str(res)[:2000], 'is_text': True}
                    _save_state(nid, status='SUCCESS', progress=100, output=str(res)[:2000])
                    _console(user.id, f"Studio run #{run.pk} : fonction {key} ✔ (job)")
                continue

            # Gating d'app au RUN (§F7, trou #7) : plus rien à faire ICI — le runner passe
            # par `execute_tool`, qui applique `tool_accessible()` sur create ET start. Un
            # seul point de décision, partagé avec l'assistant IA et l'API REST.
            runner = runner_for(app)
            if runner is None:
                # Nœud non exécutable : toléré s'il n'a PAS d'amont — sinon erreur claire.
                if any(l['to'] == nid for l in links):
                    raise ValueError(f"Nœud « {app} » : app non exécutable dans un pipeline (V1).")
                _save_state(nid, status='SUCCESS', note='source non exécutée (V1)')
                continue

            # Entrées = sorties des nœuds amont, indexées par type de port
            inputs = {}
            for l in links:
                if l['to'] == nid and l['from'] in outputs:
                    up = outputs[l['from']]
                    inputs[l.get('to_port') or up['type']] = up['value']
                    inputs[up['type']] = up['value']

            _save_state(nid, status='RUNNING', progress=0)
            _console(user.id, f"Studio run #{run.pk} : nœud {app} — création")
            item_id = runner['create'](user, inputs, node.get('params') or {})
            _save_state(nid, item_id=item_id)
            runner['start'](user, item_id)

            deadline = time.time() + NODE_TIMEOUT_S
            while True:
                time.sleep(POLL_INTERVAL_S)
                st = runner['poll'](user, item_id)
                _save_state(nid, progress=st.get('progress', 0))
                if st['status'] == 'SUCCESS':
                    if not st.get('output'):
                        raise ValueError(f"Nœud {app} : terminé mais aucune sortie.")
                    otype = runner.get('output_type')
                    if otype in (None, 'auto'):
                        if 'output_type_fn' in runner:
                            otype = runner['output_type_fn'](node.get('params') or {})
                        else:
                            from wama.common.app_registry import category_of_path
                            otype = category_of_path(st['output'])
                    outputs[nid] = {'type': otype, 'value': st['output'],
                                    'is_text': bool(st.get('is_text'))}
                    _save_state(nid, status='SUCCESS', progress=100, output=st['output'])
                    _console(user.id, f"Studio run #{run.pk} : nœud {app} ✔ → {st['output']}")
                    break
                if st['status'] == 'FAILURE':
                    raise ValueError(f"Nœud {app} : échec — {st.get('error') or 'sans détail'}")
                if time.time() > deadline:
                    raise ValueError(f"Nœud {app} : délai dépassé ({NODE_TIMEOUT_S // 60} min).")

        run.status = 'SUCCESS'
        run.processing_seconds = time.time() - t0
        run.save(update_fields=['status', 'processing_seconds', 'node_states'])
        _console(user.id, f"Studio run #{run.pk} : pipeline terminé ✔")
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(user, 'Studio', f"pipeline #{run.pk}", True)
        except Exception:
            pass
        return {'run': run.pk, 'status': 'SUCCESS'}

    except Exception as exc:
        run.status = 'FAILURE'
        run.error_message = str(exc)[:2000]
        run.processing_seconds = time.time() - t0
        run.save(update_fields=['status', 'error_message', 'processing_seconds', 'node_states'])
        _console(user.id, f"Studio run #{run.pk} : ÉCHEC — {exc}", level='error')
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(user, 'Studio', f"pipeline #{run.pk}", False, detail=str(exc))
        except Exception:
            pass
        return {'run': run.pk, 'status': 'FAILURE', 'error': str(exc)}
