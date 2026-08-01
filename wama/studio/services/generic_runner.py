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

Déclarer une app ici = quelques lignes de manifeste. Vocabulaire optionnel (spécificités
DÉCLARÉES, pas codées) : `primary_input='prompt'` (entrée = texte) ; `input_kwarg`
(l'entrée primaire part dans ce kwarg au lieu du 2e positionnel) ; `fixed_kwargs`
(constantes de création, ex. mode standalone) ; `auto_start` (le créateur dispatche
déjà — start = no-op) ; `extra_params_spec` (params de nœud ABSENTS du schéma d'app —
à résorber en les ajoutant au params.py de l'app). Le shim `runners.py` se vide en miroir.
"""
from __future__ import annotations



# Manifeste des apps NORMALISÉES (contrat rempli). L'ordre d'input_kinds = priorité de
# résolution quand plusieurs entrées typées arrivent sur le nœud.
GENERIC_APPS = {
    'synthesizer': {
        'primary_input': 'prompt',
        'params_module': 'wama.synthesizer.params',
        'params_attr': 'PARAMS_JSON',
        'output_type': 'audio',
    },
    'composer': {
        'primary_input': 'prompt',
        'params_module': 'wama.composer.params',
        'params_attr': 'PARAMS_JSON',
        'output_type': 'audio',
    },
    'imager': {
        'primary_input': 'prompt',
        'params_module': 'wama.imager.params',
        'params_attr': 'IMAGE_PARAMS_JSON',   # nœud imager V1 = génération d'IMAGE (txt2img)
        'output_type': 'auto',
    },
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
    'converter': {
        'input_kinds': ('image', 'video', 'audio', 'document'),
        'params_module': 'wama.converter.params',
        'params_attr': 'PARAMS_JSON',
        'output_type': 'auto',
        'auto_start': True,   # convert_file dispatche à la création (déclaré)
    },
    'avatarizer': {
        'input_kinds': ('audio',),
        'input_kwarg': 'audio_path',                    # signature historique (déclaré)
        'fixed_kwargs': {'mode': 'standalone', 'avatar_source': 'gallery'},
        'params_module': 'wama.avatarizer.params',
        'params_attr': 'PARAMS_JSON',
        'output_type': 'video',
        # L'avatar n'est PAS (encore) dans le params.py de l'app → spec additionnelle
        # déclarée ici ; à résorber en l'ajoutant au schéma d'app (options_source).
        'extra_params_spec': [
            {'name': 'avatar_gallery_name', 'label': 'Avatar', 'type': 'select',
             'options_source': 'avatar_gallery'},
        ],
    },
    'anonymizer': {
        'input_kinds': ('image', 'video'),
        'params_module': 'wama.anonymizer.params',
        'params_attr': 'PARAMS_JSON',
        'output_type': 'auto',
    },
}


def _error_text(res):
    """Texte LISIBLE d'un retour d'outil en erreur : `detail` s'il existe, sinon `error`.

    Les refus de permission renvoient {'error': 'forbidden', 'detail': '<phrase>'} (forme
    partagée avec `AppAccessMiddleware._deny`) — sans ça, le run afficherait « forbidden ».
    """
    return res.get('detail') or res.get('error')


def _node_params_spec(app_id, conf):
    """Schéma params.py → spec de nœud studio (mapping de FORME, pas de contenu)."""
    from wama.common.utils.param_schema import schema_for_app
    spec = []
    for p in schema_for_app(app_id):
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
    spec.extend(conf.get('extra_params_spec') or [])
    return spec


def build_generic_runner(app_id):
    conf = GENERIC_APPS[app_id]

    def create(user, inputs, params):
        # Passe par execute_tool : MÊME point d'exécution que l'assistant IA et l'API REST
        # (gating d'app, coercition par schéma, filtre de signature). Le studio n'ajoute que
        # ce qui relève du GRAPHE : d'où vient l'entrée principale, et les kwargs figés.
        from wama.tool_api import execute_tool, primary_arg_name
        tool = f'add_to_{app_id}'
        if conf.get('primary_input') == 'prompt':
            primary = (inputs.get('prompt') or inputs.get('text')
                       or (params or {}).get('prompt') or (params or {}).get('text')
                       or (params or {}).get('text_content') or '').strip()
            if not primary:
                raise ValueError(f"Nœud {app_id} : aucun prompt (connectez un nœud Texte "
                                 f"ou renseignez le paramètre).")
        else:
            primary = next((inputs[k] for k in conf['input_kinds'] if inputs.get(k)), '')
            if not primary:
                raise ValueError(f"Nœud {app_id} : aucune entrée "
                                 f"({' / '.join(conf['input_kinds'])}).")
        # Params du nœud : on écarte ceux qui ont SERVI à construire l'entrée principale, et
        # les valeurs vides (un champ de formulaire non renseigné arrive à '' — il ne doit pas
        # écraser le défaut de la fonction). Le typage/bornage, lui, est fait par execute_tool.
        consumed = {'prompt', 'text', 'text_content'} if conf.get('primary_input') == 'prompt' else set()
        call_args = {k: v for k, v in (params or {}).items()
                     if k not in consumed and v not in (None, '')}
        call_args.update(conf.get('fixed_kwargs') or {})

        # L'entrée principale est passée PAR NOM : déclaré (`input_kwarg`) ou dérivé de la
        # signature. Plus de position à deviner, et l'appel devient un appel d'outil normal.
        kwarg = conf.get('input_kwarg') or primary_arg_name(tool)
        if not kwarg:
            raise ValueError(f"{app_id} : {tool} n'expose aucun paramètre d'entrée (contrat).")
        call_args[kwarg] = primary

        res = execute_tool(tool, call_args, user)
        if not isinstance(res, dict):
            raise ValueError(f"{app_id} : {tool} n'a pas renvoyé de dict (contrat).")
        if 'error' in res:
            raise ValueError(f"{app_id} : {_error_text(res)}")
        if 'item_id' not in res:
            raise ValueError(f"{app_id} : retour non conforme au contrat (clé item_id absente) "
                             f"— normaliser la triade dans wama/tool_api.py.")
        return res['item_id']

    def start(user, item_id):
        if conf.get('auto_start'):
            return   # le créateur a déjà dispatché (déclaré au manifeste)
        from wama.tool_api import execute_tool, primary_arg_name
        tool = f'start_{app_id}'
        kwarg = primary_arg_name(tool)
        if not kwarg:
            raise ValueError(f"{app_id} : {tool} absent du registre central (contrat).")
        res = execute_tool(tool, {kwarg: item_id}, user)
        if isinstance(res, dict) and res.get('error'):
            raise ValueError(f"{app_id} : {_error_text(res)}")

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
        'params_spec': _node_params_spec(app_id, conf),
        'generic': True,
    }
