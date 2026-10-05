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

Module PUR : lecture de fichiers JSON, aucun import Django.
"""
from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4] / 'manifests'
#: Clé du process « Sortie » COMMUN (`output_process.OUTPUT_KEY`, recopiée pour garder ce module
#: pur — l'égalité est tenue par `tests_codegen_from_scratch`). Ce process n'est pas une glu
#: d'app : `function_specs` le déclare par `output_spec`, sa glu est `output_step`.
OUTPUT_PROCESS_KEY = 'output'
_PLACES = (('pipelines', 'functions'), ('app_drafts/pipelines', 'app_drafts/functions'))


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def declared_pipeline(app_key: str, root: Path = None):
    """(manifeste `pipeline`, {clé de fonction: manifeste `function`}) de l'app, ou (None, {}).

    Le premier lieu qui porte le pipeline fournit AUSSI ses fonctions : un brouillon ne se
    complète pas par le corpus (deux sources pour un même pipeline divergeraient)."""
    base = root or _ROOT
    for pipelines_dir, functions_dir in _PLACES:
        pipeline = _read(base / pipelines_dir / f'{app_key}.json')
        if not pipeline or pipeline.get('manifest_kind') != 'pipeline':
            continue
        functions = {}
        for path in sorted((base / functions_dir).glob(f'{app_key}.*.json')):
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
        if node.get('kind', 'function') != 'function' or not node.get('id'):
            continue
        params = node.get('params') or {}
        out.append({
            'key': node['id'],
            'function': node.get('function') or '',
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


def process_function(spec: dict, functions: dict) -> dict:
    """Le manifeste `function` d'un process (clé déclarée au nœud), ou {}."""
    return functions.get(spec.get('function') or '') or {}


def input_ports(spec: dict, functions: dict) -> list:
    """Ports d'ENTRÉE FICHIER du process (`travail` / `reference`, jamais le prompt)."""
    body = process_function(spec, functions).get('body') or {}
    return [p for p in body.get('inputs') or []
            if p.get('key') and p.get('data_type') != 'prompt'
            and p.get('group', 'travail') in ('travail', 'reference')]
