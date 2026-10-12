"""
Studio — orchestration d'un pipeline (tâche Celery).

Exécution : ordre TOPOLOGIQUE d'un graphe acyclique (corrigé le 2026-09-15). Chaque nœud
`app` est traité par son runner — `studio/services/runners.py` n'est plus qu'une façade de
`generic_runner.py` (`GENERIC_APPS`) : create → start → poll (le traitement lui-même tourne
dans le Celery de l'app cible). Les nœuds-SOURCE `text_input`, `media_import` et
`dataset_input` SONT exécutés, par `SOURCE_HANDLERS` (ci-dessous) ; le nœud-sortie
`studio_output` range le résultat. (L'ancienne mention « nœuds-source non exécutables en V1 »
et le nœud `prompt_batch`, qui n'existe pas, étaient périmés.)

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

ÉTATS (marche P2 de `WAMA_APP_GENERATION_ROUTE.md §10.6 4.2`) — ✅ fait le 2026-09-17 : les états
ne s'écrivent plus ici en littéraux, ils VIENNENT du vocabulaire commun (`common/models.py`), et
l'état rendu par le runner de l'app cible est TRADUIT par la table d'alias unique
(`normalize_job_status`) au lieu d'être comparé à une chaîne brute. Les VALEURS sont inchangées —
`node_states` est un JSON persisté, donc une donnée : on la source, on ne la renomme pas.

✅ 2026-10-03 — LIGNES D'EXÉCUTION : chaque nœud app ou fonction écrit sa ligne `ProcessRun`
(`process_runs.start/succeed/fail`, adressée par le run), comme un process de card dans une file ;
le nœud fautif passe `FAILURE` dans `node_states` (il restait « en cours »).

✅ 2026-10-04 — `AWAITING_RESOURCES` : un nœud `app` MONTRE l'attente de son élément (c'est la
tâche de l'app cible qui passe par le gouverneur de ressources ; le studio la RELAIE au canvas au
lieu d'afficher « en cours »), et cette attente ne compte pas dans le délai du nœud.

⏳ Ce qui RESTE, et qui n'est pas un oubli : cet exécuteur ne PRODUIT pas `STALE` (il faudrait
rejouer un run nœud par nœud — la règle de péremption du suivi de passes, 4.3). L'agrégation « état de la card
déduit de ses process » est la décision OUVERTE n°4. Cet exécuteur devient alors une pièce du
MOTEUR COMMUN (avec le squelette de tâche et le suivi de passes de cam_analyzer), qui exécutera
le pipeline porté par une card dans n'importe quelle file (4.5).
"""
import time

from celery import shared_task

from wama.common.models import (JOB_AWAITING_RESOURCES, JOB_FAILURE, JOB_RUNNING, JOB_SUCCESS,
                                normalize_job_status)
from wama.common.utils.console_utils import push_console_line

POLL_INTERVAL_S = 3
NODE_TIMEOUT_S = 30 * 60


def _console(user_id, message, level='info'):
    try:
        push_console_line(user_id, message, level=level, app='studio')
    except Exception:
        pass


# L'ordre topologique vit avec le graphe (`manifests/builtin/pipeline.py`) depuis le 2026-10-02 :
# le moteur à plusieurs process d'une app ordonne par le même tri. Le nom reste importable d'ici
# (`services/launch.py` et les tests du studio le lisent à cette adresse).
from wama.common.manifests.builtin.pipeline import topo_order  # noqa: E402,F401


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
    # Une CATÉGORIE (`'audio'`) devient sa nature par défaut ; un alias n'entre plus en base
    # (A′, `natures.resolve_asset_type` — le puits écrivait la valeur telle quelle jusqu'au 13/09).
    from wama.media_library.natures import resolve_asset_type
    asset_type = resolve_asset_type(params.get('asset_type') or 'document', f"{base}.txt")
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
    from wama.common.catalog.data_types import known_types      # accesseur unique (2026-09-16)
    connus = known_types()
    if dtype not in connus:
        raise ValueError(f"Nœud « Jeu de données » : type '{dtype}' inconnu de la taxonomie.")
    import pandas as pd
    try:
        df = pd.read_csv(path, sep=None, engine='python')
    except Exception as exc:
        raise ValueError(f"Nœud « Jeu de données » : lecture impossible ({exc}).")
    return dtype, TypedFrame(df, dtype, meta={'source': rel})


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
    """Nœud « Base connectée » (Connector, `WAMA_DATA_WORLD §11.5`) : une base déjà constituée
    (`.wdat`, `.trip`…) ou un dossier de bases, branché SANS copie. Rend des LOTS
    (`wama_data/functions/io/connector.ConnectedLot`) dont rien n'est encore lu : c'est le
    consommateur qui demande ses flux."""
    from wama_data.functions.io.connector import connect
    path = _readable_path(user, params, 'path', 'Base connectée')
    try:
        return 'dataset', connect(path)
    except ValueError as exc:
        raise ValueError(f"Nœud « Base connectée » : {exc}")


SOURCE_HANDLERS = {
    'text_input': _source_text,
    'media_import': _source_media,
    'dataset_input': _source_dataset,
    'data_connector': _source_connector,
}


def _is_lot_list(value) -> bool:
    """La valeur d'un nœud Connector : une liste de bases connectées (`ConnectedLot`)."""
    return isinstance(value, list) and bool(value) and all(hasattr(v, 'frames') and
                                                           hasattr(v, 'streams') for v in value)


def _lots_summary(lots) -> str:
    return f"{len(lots)} base(s) connectée(s) : " + ', '.join(lot.summary() for lot in lots[:5]) \
        + (' …' if len(lots) > 5 else '')


def _sink_data_export(user, lots, params):
    """Nœud « Export de données » (Exporter en NŒUD DE SORTIE, `WAMA_DATA_WORLD §11.8 ⑨`) : ses
    `Declaration`s appliquées aux bases reçues. Destination : le dossier CHOISI, sinon celui d'où
    viennent les données (règle de Fabien, §11.1) — jamais le dépôt."""
    import json
    from pathlib import Path
    from wama_data.functions.io.export import export_lots, grouping_from_dict
    label = 'Export de données'
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


# ── Nœud FONCTION (D13) ──────────────────────────────────────────────────────
def _frame_summary(frame) -> str:
    try:
        return f"{frame.data_type} · {len(frame.df)} ligne(s) · {', '.join(map(str, frame.fields))}"
    except Exception:
        return repr(frame)


def builtin_node_values(node) -> dict:
    """Les réglages d'un nœud INTÉGRÉ (entrée, sortie) passés par la porte commune — typés,
    bornés, refusés s'ils ne sont pas applicables (`param_schema.checked_values`), contre le
    schéma que l'inspecteur a rendu (`node_params.node_schema`). Avant le 2026-10-12, ces nœuds
    lisaient leurs réglages bruts : un interrupteur arrivait en `'1'`/`''`."""
    from wama.common.utils.param_schema import checked_values
    from wama.studio.services.node_params import node_label, node_schema
    raw = node.get('params') or {}
    schema = node_schema(node['app'])
    if schema is None:
        return dict(raw)
    try:
        return checked_values(schema['params'], raw)
    except ValueError as exc:
        raise ValueError(f"Nœud « {node_label(node['app'])} » : {exc}")


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
    # Les réglages passent par LA porte de la fonction (`FunctionSpec.call_params` : le pont vers
    # `Param`, puis `checked_values`) — types ET bornes, refus nommés. L'ancienne coercition locale
    # ne connaissait que les types : une borne déclarée n'était tenue nulle part au lancement.
    result = spec.fn(positional, **keywords, **spec.call_params(params))
    if not isinstance(result, TypedFrame):
        raise ValueError(f"la fonction n'a pas rendu un TypedFrame ({type(result).__name__}) — "
                         f"contrat `pure` non honoré (noyau branché à la place du wrapper ?)")
    return result


def _impl_callable(impl: str):
    """`module.chemin:attribut` → objet — par le résolveur COMMUN du catalogue (écrit ici, remonté
    le 2026-10-05 : les process d'app désignent leur ETA par la même forme)."""
    from wama.common.catalog.function_catalog import resolve_impl
    return resolve_impl(impl)


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


def _run_app_function(spec, params: dict, save_state, deadline_s: float, inputs: dict | None = None,
                      console=None):
    """Fonction `app`-bound = un JOB : `impl` (tâche Celery) lancée avec les params du nœud,
    puis POLLÉE comme un nœud-app. Sans `.delay` (fonction ordinaire), appel direct.

    `inputs` (2026-09-13, §17ter trou 4) : les FICHIERS reçus de l'amont, par PORT (`{'image':
    'users/…/x.png'}`) — une fonction média (`studio.image_to_3d`) reçoit ainsi l'image du nœud
    précédent, là où les passes du cam_analyzer ne prenaient que des params (`session_id`).
    Un port qui n'est pas un paramètre de la tâche n'est pas passé : l'introspection décide —
    et depuis le 2026-10-05 `console(message)` le DIT (`ROUTE §10.6`, position commune : un nœud
    rattaché lance la tâche ENTIÈRE de son app, pas le process nommé ; une entrée d'amont que
    cette tâche ne prend pas était jetée sans un mot)."""
    target = _impl_callable(spec.impl)
    required = app_function_job_kwargs(spec.impl)
    kwargs = {k: v for k, v in (params or {}).items() if v not in (None, '')}
    if inputs:
        import inspect
        fn = getattr(target, 'run', None) or getattr(target, '__wrapped__', None) or target
        try:
            acceptes = set(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            acceptes = set(inputs)
        kwargs.update({k: v for k, v in inputs.items() if k in acceptes and v not in (None, '')})
        dropped = sorted(k for k, v in inputs.items() if k not in acceptes and v not in (None, ''))
        if dropped and console:
            console(f"{spec.key} : entrée(s) d'amont NON transmise(s) — {', '.join(dropped)} : "
                    f"la tâche `{spec.impl}` ne les prend pas (un nœud rattaché lance la tâche "
                    f"entière de son app ; le lancement d'un process seul n'est pas encore câblé).")
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
    from wama.media_library.natures import resolve_asset_type
    asset_type = resolve_asset_type(params.get('asset_type') or 'document', f"{base}.csv")
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
    # Catégorie → nature (A′) ; l'extension du fichier rangé départage dans la catégorie.
    from wama.media_library.natures import resolve_asset_type
    asset_type = resolve_asset_type(params.get('asset_type') or 'video', os.path.basename(value))
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
    run.status = JOB_RUNNING
    run.save(update_fields=['status'])
    _console(user.id, f"Studio run #{run.pk} : démarrage")

    states = dict(run.node_states or {})

    # LIGNES D'EXÉCUTION (ROUTE §10.6 4.1, alignement du 2026-10-03) : chaque nœud qui EST un
    # process — app ou fonction — écrit la même ligne `ProcessRun` qu'un process de card dans une
    # file (adressée par le RUN : `studio/StudioRun/<pk>`, nœud = id du nœud). `node_states` reste
    # ce que le canvas lit (un JSON persisté, donc une donnée) ; les lignes sont ce que le moteur
    # commun lit : UNE table d'exécution pour les files ET le studio. Entrées et sorties ne sont
    # pas des process : elles n'ont pas de ligne. Best-effort (`safely`) : une ligne qui ne
    # s'écrit pas ne fait jamais échouer un run.
    from wama.common.services import process_runs
    process_nodes = {}      # id de nœud -> (kind, clé du process) des nœuds qui sont des process
    current = {'node': None}

    def _write_line(node_id, kw):
        ref, status = process_nodes.get(node_id), kw.get('status')
        if ref is None or status is None:
            return
        kind, key = ref
        if status == JOB_RUNNING:
            process_runs.safely(process_runs.start, run, node_id, process_key=key, kind=kind,
                                task_id=getattr(self.request, 'id', None) or '')
        elif status == JOB_SUCCESS:
            import os
            from django.conf import settings
            out = kw.get('output')
            is_file = (isinstance(out, str) and out and '\n' not in out
                       and os.path.isfile(os.path.join(settings.MEDIA_ROOT, out)))
            process_runs.safely(process_runs.succeed, run, node_id, process_key=key,
                                output_ref=out if is_file else '',
                                output_summary={'label': str(out)[:200]} if out else None)
        elif status == JOB_FAILURE:
            process_runs.safely(process_runs.fail, run, node_id, kw.get('error') or '',
                                process_key=key)

    def _save_state(node_id, **kw):
        states.setdefault(node_id, {})
        states[node_id].update(kw)
        run.node_states = states
        run.save(update_fields=['node_states'])
        _write_line(node_id, kw)

    try:
        from wama.common.manifests.builtin.pipeline import node_kind, function_key
        order = topo_order(run.graph)
        links = run.graph.get('links', [])
        outputs = {}   # node_id -> {'type': 'audio'|..., 'value': chemin MEDIA relatif | TypedFrame}

        for node in order:
            nid, app = node['id'], node['app']
            current['node'] = nid

            # Nœud SOURCE (card d'entrée) : produit sa valeur depuis ses params.
            if app in SOURCE_HANDLERS:
                _save_state(nid, status=JOB_RUNNING)
                out_type, value = SOURCE_HANDLERS[app](user, builtin_node_values(node))
                is_frame = hasattr(value, 'df') and hasattr(value, 'data_type')
                is_lots = _is_lot_list(value)
                outputs[nid] = {'type': out_type, 'value': value, 'is_frame': is_frame,
                                'is_lots': is_lots}
                _save_state(nid, status=JOB_SUCCESS,
                            output=(_frame_summary(value) if is_frame
                                    else _lots_summary(value) if is_lots else value))
                continue

            # Nœud de SORTIE DATA (Exporter) : ses déclarations appliquées aux bases reçues.
            if app == 'data_export':
                _save_state(nid, status=JOB_RUNNING)
                incoming = [outputs[l['from']] for l in links
                            if l['to'] == nid and l['from'] in outputs]
                lots = [lot for up in incoming if up.get('is_lots') for lot in up['value']]
                if not lots:
                    raise ValueError("Nœud « Export de données » : aucune base reçue (connectez "
                                     "un nœud « Base connectée »).")
                note = _sink_data_export(user, lots, builtin_node_values(node))
                _save_state(nid, status=JOB_SUCCESS, output=note)
                _console(user.id, f"Studio run #{run.pk} : export écrit — {note}")
                continue

            # Nœud de SORTIE (card de sortie) : range la valeur reçue de l'amont.
            if app == 'studio_output':
                _save_state(nid, status=JOB_RUNNING)
                incoming = [outputs[l['from']] for l in links
                            if l['to'] == nid and l['from'] in outputs]
                if not incoming:
                    raise ValueError("Nœud « Sortie » : aucune entrée reçue (connectez un nœud amont).")
                if incoming[0].get('is_lots'):
                    raise ValueError("Nœud « Sortie » : une base connectée ne se range pas en "
                                     "médiathèque — passez par un nœud « Export de données ».")
                sink_params = builtin_node_values(node)
                if incoming[0].get('is_frame'):
                    note = _sink_frame_to_media_library(user, incoming[0]['value'],
                                                        sink_params, run.pk)
                elif incoming[0].get('is_text'):
                    note = _sink_text_to_media_library(user, incoming[0]['value'],
                                                       sink_params, run.pk)
                else:
                    note = _sink_media_library(user, incoming[0]['value'], sink_params)
                _save_state(nid, status=JOB_SUCCESS, output=note)
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
                process_nodes[nid] = ('function', key)
                _save_state(nid, status=JOB_RUNNING, progress=0)
                _console(user.id, f"Studio run #{run.pk} : fonction {key} ({spec.binding})")
                if spec.binding == fc.Binding.PURE:
                    frames = {}
                    ports_connus = {p.key for p in spec.inputs}
                    first_port = spec.inputs[0].key if spec.inputs else None
                    for l in links:
                        if l['to'] != nid or l['from'] not in outputs:
                            continue
                        up = outputs[l['from']]
                        if up.get('is_lots'):
                            # ⏳ Choisir le flux d'une base qui entre dans une fonction : c'est le
                            # geste de la card du Data Analyzer (P7), pas encore écrit.
                            raise ValueError(
                                f"Nœud fonction « {key} » : une base connectée n'entre pas encore "
                                f"directement dans une fonction (choix du flux à venir).")
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
                    _save_state(nid, status=JOB_SUCCESS, progress=100, output=_frame_summary(result))
                    _console(user.id, f"Studio run #{run.pk} : fonction {key} ✔ → {_frame_summary(result)}")
                else:
                    # Les FICHIERS de l'amont, par port (une fonction média — image→3D — les
                    # reçoit ; les passes du cam_analyzer, à params seuls, les ignorent).
                    fichiers = {}
                    ports_connus = [p.key for p in spec.inputs]
                    for l in links:
                        if l['to'] != nid or l['from'] not in outputs:
                            continue
                        up = outputs[l['from']]
                        if up.get('is_frame') or up.get('is_text') or up.get('is_lots'):
                            continue
                        port = l.get('to_port')
                        if port not in ports_connus:
                            port = ports_connus[0] if ports_connus else None
                        if port:
                            fichiers[port] = up['value']
                    # Les réglages DÉCLARÉS de la fonction passent par sa porte (types, bornes,
                    # refus nommés) ; les autres — arguments de la tâche, comme `session_id` —
                    # restent tels quels : c'est la signature de la tâche qui les juge.
                    params_noeud = dict(node.get('params') or {})
                    try:
                        params_noeud.update(spec.call_params(params_noeud))
                    except ValueError as exc:
                        raise ValueError(f"Nœud fonction « {key} » : {exc}")
                    params_noeud.setdefault('user_id', user.pk)
                    res = _run_app_function(spec, params_noeud,
                                            lambda **kw: _save_state(nid, **kw), NODE_TIMEOUT_S,
                                            inputs=fichiers,
                                            console=lambda m: _console(
                                                user.id, f"Studio run #{run.pk} : {m}",
                                                level='warning'))
                    otype = spec.outputs[0].data_type if spec.outputs else 'scalar'
                    # Un résultat qui EST un fichier média (chemin relatif sous MEDIA_ROOT) se
                    # transmet comme tel — le nœud « Sortie » le range en médiathèque avec ses
                    # attributs lus du fichier ; un texte reste un texte.
                    import os as _os
                    from django.conf import settings as _settings
                    est_media = (isinstance(res, str) and res and '\n' not in res
                                 and _os.path.isfile(_os.path.join(_settings.MEDIA_ROOT, res)))
                    if est_media:
                        outputs[nid] = {'type': otype, 'value': res}
                    else:
                        outputs[nid] = {'type': otype, 'value': str(res)[:2000], 'is_text': True}
                    _save_state(nid, status=JOB_SUCCESS, progress=100, output=str(res)[:2000])
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
                _save_state(nid, status=JOB_SUCCESS, note='source non exécutée (V1)')
                continue

            # Entrées = sorties des nœuds amont, indexées par type de port
            inputs = {}
            for l in links:
                if l['to'] == nid and l['from'] in outputs:
                    up = outputs[l['from']]
                    inputs[l.get('to_port') or up['type']] = up['value']
                    inputs[up['type']] = up['value']

            process_nodes[nid] = ('app', app)
            _save_state(nid, status=JOB_RUNNING, progress=0)
            _console(user.id, f"Studio run #{run.pk} : nœud {app} — création")
            item_id = runner['create'](user, inputs, node.get('params') or {})
            _save_state(nid, item_id=item_id)
            runner['start'](user, item_id)

            deadline = time.time() + NODE_TIMEOUT_S
            shown = JOB_RUNNING
            while True:
                time.sleep(POLL_INTERVAL_S)
                st = runner['poll'](user, item_id)
                _save_state(nid, progress=st.get('progress', 0))
                # Le runner rend l'état de l'app CIBLE : on le TRADUIT par la table unique
                # (`normalize_job_status`, 2ᵉ pièce de P2) au lieu de comparer une chaîne
                # brute — une app qui répondrait `DONE`/`ERROR` faisait tourner cette boucle
                # jusqu'au délai de 30 min sans que rien ne le dise.
                state = normalize_job_status(st.get('status'))
                # L'élément ATTEND des ressources (sa tâche a rendu le worker, le gouverneur la
                # rappellera) : le canvas le dit, et l'attente ne compte pas dans le délai du
                # nœud. La ligne d'exécution du nœud, elle, reste ouverte : il n'a pas échoué.
                if state == JOB_AWAITING_RESOURCES:
                    deadline += POLL_INTERVAL_S
                if state in (JOB_AWAITING_RESOURCES, JOB_RUNNING) and state != shown:
                    shown = state
                    states[nid]['status'] = state
                    run.node_states = states
                    run.save(update_fields=['node_states'])
                if state == JOB_SUCCESS:
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
                    _save_state(nid, status=JOB_SUCCESS, progress=100, output=st['output'])
                    _console(user.id, f"Studio run #{run.pk} : nœud {app} ✔ → {st['output']}")
                    break
                if state == JOB_FAILURE:
                    raise ValueError(f"Nœud {app} : échec — {st.get('error') or 'sans détail'}")
                if time.time() > deadline:
                    raise ValueError(f"Nœud {app} : délai dépassé ({NODE_TIMEOUT_S // 60} min).")

        run.status = JOB_SUCCESS
        run.processing_seconds = time.time() - t0
        run.save(update_fields=['status', 'processing_seconds', 'node_states'])
        _console(user.id, f"Studio run #{run.pk} : pipeline terminé ✔")
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(user, 'Studio', f"pipeline #{run.pk}", True)
        except Exception:
            pass
        return {'run': run.pk, 'status': JOB_SUCCESS}

    except Exception as exc:
        # Le nœud FAUTIF le dit (canvas : `run-failure` sur lui, plus seulement sur le run ;
        # ligne d'exécution : `FAILURE` avec le message) — avant, il restait « en cours ».
        failed = current['node']
        if failed is not None:
            states.setdefault(failed, {}).update(status=JOB_FAILURE, error=str(exc)[:500])
            run.node_states = states
            _write_line(failed, {'status': JOB_FAILURE, 'error': str(exc)})
        process_runs.safely(process_runs.close_open, run, JOB_FAILURE, str(exc))
        run.status = JOB_FAILURE
        run.error_message = str(exc)[:2000]
        run.processing_seconds = time.time() - t0
        run.save(update_fields=['status', 'error_message', 'processing_seconds', 'node_states'])
        _console(user.id, f"Studio run #{run.pk} : ÉCHEC — {exc}", level='error')
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(user, 'Studio', f"pipeline #{run.pk}", False, detail=str(exc))
        except Exception:
            pass
        return {'run': run.pk, 'status': JOB_FAILURE, 'error': str(exc)}
