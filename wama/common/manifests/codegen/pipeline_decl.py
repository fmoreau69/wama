"""
Le PIPELINE déclaré d'une app, tel que les GÉNÉRATEURS le lisent (2026-10-05, session Writer).

Décision n°11 (`WAMA_APP_GENERATION_ROUTE.md §10.6`) : une app à plusieurs process les déclare
comme le composer — chaque process un `FunctionSpec binding: app`, le registre un manifeste
`pipeline` sous la clé de l'app. **Aucune facette au manifeste `app`** : le pipeline se retrouve
par la CLÉ. Les générateurs (`function_specs_gen`, `tasks_gen`, `models_gen`, `views_gen`) lisent
donc ce module, jamais une clé du manifeste `app`.

D'où viennent les manifestes, dans cet ordre :
  1. le CORPUS (`manifests/pipelines/<clé>.json`, `manifests/functions/<clé>.<process>.json`) —
     ceux qu'une app existante exporte (`manifest_export --kind pipeline|function`) ;
  2. les BROUILLONS (`manifests/app_drafts/pipelines/<clé>.json`,
     `manifests/app_drafts/functions/<clé>.<process>.json`) — ceux d'une app qui n'existe pas
     encore, AUTORÉS à la main comme son manifeste `app` (`app_drafts/<clé>.json`).
Pas de pipeline déclaré = une app à UN process, le cas normal (§10.6 : « un pipeline à un seul
process est normal ») : les générateurs rendent alors ce qu'ils rendaient avant.

Lecture de fichiers JSON seule. Les DOSSIERS du corpus sont ceux de l'export
(`manifest_export.DOSSIERS`) et un nœud se lit par les deux seuls lecteurs de la convention
(`builtin/pipeline.node_kind` / `function_key`) — revérification du 2026-10-05.
"""
from __future__ import annotations

import json
from pathlib import Path

from wama.common.manifests.builtin.pipeline import function_key, node_kind
#: Clé du process « Sortie » COMMUN : il n'est pas une glu d'app — `function_specs` le déclare
#: par `output_spec`, sa glu est `output_step`.
from wama.common.services.output_process import OUTPUT_KEY as OUTPUT_PROCESS_KEY  # noqa: F401

_BASE = Path(__file__).resolve().parents[4]
#: Le dossier des brouillons d'apps nées d'un manifeste (`app_sandbox create --from-manifest`) :
#: leurs manifestes `pipeline` / `function` y suivent l'arborescence du corpus.
DRAFTS_DIR = 'manifests/app_drafts'


def _places(base: Path) -> tuple:
    """(dossier des pipelines, dossier des fonctions) : le corpus, puis les brouillons."""
    from wama.common.management.commands.manifest_export import DOSSIERS
    corpus = (base / DOSSIERS['pipeline'], base / DOSSIERS['function'])
    drafts = tuple(base / DRAFTS_DIR / Path(d).name for d in (DOSSIERS['pipeline'],
                                                              DOSSIERS['function']))
    return corpus, drafts


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def declared_pipeline(app_key: str, root: Path = None):
    """(manifeste `pipeline`, {clé de fonction: manifeste `function`}) de l'app, ou (None, {}).

    Le premier lieu qui porte le pipeline fournit AUSSI ses fonctions : un brouillon ne se
    complète pas par le corpus (deux sources pour un même pipeline divergeraient)."""
    for pipelines_dir, functions_dir in _places(root or _BASE):
        pipeline = _read(pipelines_dir / f'{app_key}.json')
        if not pipeline or pipeline.get('manifest_kind') != 'pipeline':
            continue
        functions = {}
        for path in sorted(functions_dir.glob(f'{app_key}.*.json')):
            m = _read(path)
            if m and m.get('manifest_kind') == 'function' and m.get('key'):
                functions[m['key']] = m
        return pipeline, functions
    return None, {}


def process_specs(pipeline: dict) -> list:
    """Les process du manifeste dans l'ORDRE du registre, à la forme des champs de
    `process_pipeline.ProcessSpec` : {key, function, label, depends_on, watched, degree, gpu,
    share, outputs, toggle, eta}. Les dépendances sont les LIENS (`from` → `to`), comme à l'export."""
    body = (pipeline or {}).get('body') or {}
    links = body.get('links') or []
    out = []
    for node in body.get('nodes') or []:
        if node_kind(node) != 'function' or not node.get('id'):
            continue
        params = node.get('params') or {}
        out.append({
            'key': node['id'],
            'function': function_key(node),
            'label': params.get('label', ''),
            'depends_on': [l['from'] for l in links if l.get('to') == node['id'] and l.get('from')],
            'watched': list(params.get('watched') or []),
            'degree': params.get('degree', 'required'),
            'gpu': bool(params.get('gpu')),
            'share': int(params.get('share') or 1),
            'outputs': list(params.get('outputs') or []),
            'toggle': params.get('toggle', ''),
            'eta': params.get('eta', ''),
        })
    return out


def schema_stales(manifest: dict) -> dict:
    """`{process: [réglages]}` que le schéma du manifeste `app` déclare périmer (`stales`), dans
    l'ordre du schéma — la lecture, côté MANIFESTE, de `process_pipeline.declared_stales`."""
    out, seen = {}, set()
    body = (manifest or {}).get('body') or {}
    for schema in ((body.get('params') or {}).get('schemas') or {}).values():
        for param in schema or []:
            name = param.get('name') if isinstance(param, dict) else None
            if not name or name in seen:
                continue
            seen.add(name)
            for process in param.get('stales') or ():
                out.setdefault(process, []).append(name)
    return out


def watched_of(manifest: dict, spec: dict) -> list:
    """Ce que le process SURVEILLE : les réglages du schéma qui le nomment, puis ses champs hors
    schéma — l'union d'`AppPipeline.watched_of`, lue sur les manifestes."""
    return list(dict.fromkeys(schema_stales(manifest).get(spec['key'], []) + spec['watched']))


def process_function(spec: dict, functions: dict) -> dict:
    """Le manifeste `function` d'un process (clé déclarée au nœud), ou {}."""
    return functions.get(spec.get('function') or '') or {}


def input_ports(spec: dict, functions: dict) -> list:
    """Ports d'ENTRÉE FICHIER du process (`travail` / `reference`, jamais le prompt)."""
    body = process_function(spec, functions).get('body') or {}
    return [p for p in body.get('inputs') or []
            if p.get('key') and p.get('data_type') != 'prompt'
            and p.get('group', 'travail') in ('travail', 'reference')]
