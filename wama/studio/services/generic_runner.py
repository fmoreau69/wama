"""
Studio — runner GÉNÉRIQUE piloté par le CONTRAT d'app (STUDIO_VISION « principe directeur »,
2026-07-12). Zéro logique par app : tout vient des sources uniques.

Une app est éligible quand sa triade est NORMALISÉE :
  1. `wama.tool_api.add_to_<app>(user, file_path, **params)` → `{'item_id': int, ...}`
     (les params sont FILTRÉS sur la signature réelle — introspection, pas d'encodage) ;
  2. `wama.tool_api.start_<app>(user, item_id)` ;
  3. adapter DETAIL enregistré (clés canoniques `status`/`result_file`,
     INSPECTOR_DETAIL_FIELDS.md) + champ `progress` canonique du modèle (CONV §2) ;
  4. `params.py` (…PARAMS_JSON) = source UNIQUE des paramètres de nœud — `params_attr`
     est un POINTEUR vers ce schéma, jamais une copie.

Déclarer une app ici = 4 lignes de manifeste. Le shim `runners.py` se vide en miroir.
"""
from __future__ import annotations

import inspect


# Manifeste des apps NORMALISÉES (contrat rempli). L'ordre d'input_kinds = priorité de
# résolution quand plusieurs entrées typées arrivent sur le nœud.
GENERIC_APPS = {
    'transcriber': {
        'input_kinds': ('audio', 'video'),
        'params_module': 'wama.transcriber.params',
        'params_attr': 'PARAMS_JSON',
        'output_type': 'text',
    },
    'describer': {
        'input_kinds': ('image', 'video', 'audio', 'document'),
        'params_module': 'wama.describer.params',
        'params_attr': 'PARAMS_JSON',
        'output_type': 'text',
    },
    'reader': {
        'input_kinds': ('document', 'image'),
        'params_module': 'wama.reader.params',
        'params_attr': 'PARAMS_JSON',
        'output_type': 'text',
    },
    'enhancer': {
        'input_kinds': ('image', 'video'),
        'params_module': 'wama.enhancer.params',
        'params_attr': 'MEDIA_PARAMS_JSON',
        'output_type': 'auto',
    },
}


def _coerce(value, ptype):
    if ptype == 'toggle':
        return str(value).lower() in ('1', 'true', 'on', 'oui')
    if ptype == 'range':
        try:
            f = float(value)
            return int(f) if f == int(f) else f
        except (TypeError, ValueError):
            return value
    return value


def _params_json(conf):
    import importlib
    mod = importlib.import_module(conf['params_module'])
    return getattr(mod, conf['params_attr'])


def _node_params_spec(conf):
    """Schéma params.py → spec de nœud studio (mapping de FORME, pas de contenu)."""
    spec = []
    for p in _params_json(conf):
        if 'item' not in (p.get('contexts') or []):
            continue
        entry = {'name': p['name'], 'label': p.get('label') or p['name']}
        ptype = p.get('type')
        if ptype == 'select' and p.get('choices'):
            entry['type'] = 'select'
            entry['options'] = [{'value': c[0], 'label': c[1]} for c in p['choices']]
        elif ptype == 'toggle':
            entry['type'] = 'select'
            entry['options'] = [{'value': '', 'label': 'Non'}, {'value': '1', 'label': 'Oui'}]
        else:   # range / texte
            entry['type'] = 'text'
            if p.get('min') is not None or p.get('max') is not None:
                entry['placeholder'] = f"{p.get('min', '')}–{p.get('max', '')} {p.get('unit', '')}".strip()
        if p.get('default') is not None:
            entry['default'] = p['default']
        spec.append(entry)
    return spec


def build_generic_runner(app_id):
    conf = GENERIC_APPS[app_id]

    def create(user, inputs, params):
        from wama import tool_api
        fn = getattr(tool_api, f'add_to_{app_id}', None)
        if fn is None:
            raise ValueError(f"{app_id} : add_to_{app_id} absent du registre central (contrat).")
        file_path = next((inputs[k] for k in conf['input_kinds'] if inputs.get(k)), '')
        if not file_path:
            raise ValueError(f"Nœud {app_id} : aucune entrée "
                             f"({' / '.join(conf['input_kinds'])}).")
        # Filtre des params sur la signature RÉELLE + coercition par type du schéma
        sig = inspect.signature(fn)
        types_by_name = {p['name']: p.get('type') for p in _params_json(conf)}
        kwargs = {k: _coerce(v, types_by_name.get(k))
                  for k, v in (params or {}).items()
                  if k in sig.parameters and v not in (None, '')}
        res = fn(user, file_path, **kwargs)
        if 'error' in res:
            raise ValueError(f"{app_id} : {res['error']}")
        if 'item_id' not in res:
            raise ValueError(f"{app_id} : retour non conforme au contrat (clé item_id absente) "
                             f"— normaliser la triade dans wama/tool_api.py.")
        return res['item_id']

    def start(user, item_id):
        from wama import tool_api
        fn = getattr(tool_api, f'start_{app_id}', None)
        if fn is None:
            raise ValueError(f"{app_id} : start_{app_id} absent du registre central (contrat).")
        res = fn(user, item_id)
        if isinstance(res, dict) and res.get('error'):
            raise ValueError(f"{app_id} : {res['error']}")

    def poll(user, item_id):
        from wama.common.utils.detail_registry import DetailRegistry
        entry = DetailRegistry.get(app_id)
        if not entry:
            raise ValueError(f"{app_id} : pas d'adapter detail (contrat) — porter l'app.")
        instance = entry['model'].objects.get(pk=item_id, user=user)
        d = entry['adapter'](instance) or {}
        is_text = conf.get('output_type') == 'text'
        if is_text:
            result = d.get('result_text') or ''
        else:
            result = d.get('result_file') or ''
            if result.startswith('/media/'):
                result = result[len('/media/'):]
        return {
            'status': d.get('status') or getattr(instance, 'status', ''),
            'progress': getattr(instance, 'progress', 0) or 0,
            'output': result,
            'is_text': is_text,
            'error': getattr(instance, 'error_message', '') or '',
        }

    return {
        'create': create,
        'start': start,
        'poll': poll,
        'output_type': conf.get('output_type', 'auto'),
        'params_spec': _node_params_spec(conf),
        'generic': True,
    }
