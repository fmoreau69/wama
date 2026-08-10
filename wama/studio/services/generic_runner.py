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



# Manifeste des apps NORMALISÉES (contrat rempli). Depuis 2026-08-11 (route §10.1), les E/S
# (`input_kinds`/`primary_input`/`output_type`) sont DÉRIVÉES des ports (`studio_node_ports`,
# accesseur unique) par `_fill_io_from_ports()` ci-dessous — fin de la double saisie qui avait
# dérivé (converter avait perdu `archive`). L'ordre du port travail = priorité de résolution
# quand plusieurs entrées typées arrivent sur le nœud (ordre d'APP_CATALOG.input_types, préservé).
#
# Déclarer une E/S ici reste possible mais devient un OVERRIDE : un nœud volontairement plus
# étroit que l'app le DIT via `io_scope` (spécificité déclarée). Sans `io_scope`, une E/S
# déclarée à la main est traitée comme une DÉRIVE par studio_redundancy.
GENERIC_APPS = {
    'synthesizer': {
        'params_module': 'wama.synthesizer.params',
        'params_attr': 'PARAMS_JSON',
    },
    'composer': {
        'params_module': 'wama.composer.params',
        'params_attr': 'PARAMS_JSON',
    },
    'imager': {
        'primary_input': 'prompt',
        'io_scope': "nœud V1 = txt2img : prompt seul, le port image (i2i/référence) de la card "
                    "n'est pas exposé au nœud",
        'params_module': 'wama.imager.params',
        'params_attr': 'IMAGE_PARAMS_JSON',
    },
    'transcriber': {
        'params_module': 'wama.transcriber.params',
        'params_attr': 'PARAMS_JSON',
    },
    'describer': {
        'params_module': 'wama.describer.params',
        'params_attr': 'PARAMS_JSON',
    },
    'reader': {
        'params_module': 'wama.reader.params',
        'params_attr': 'PARAMS_JSON',
    },
    'enhancer': {
        'input_kinds': ('image', 'video'),
        'io_scope': "nœud = domaine média (image+vidéo) ; le domaine audio de l'app n'est pas "
                    "exposé au studio",
        'params_module': 'wama.enhancer.params',
        'params_attr': 'MEDIA_PARAMS_JSON',
    },
    'converter': {
        'params_module': 'wama.converter.params',
        'params_attr': 'PARAMS_JSON',
        'auto_start': True,   # convert_file dispatche à la création (déclaré)
    },
    'avatarizer': {
        'input_kinds': ('audio',),
        'io_scope': "nœud V1 = audio seul ; l'avatar vient de la galerie (fixed_kwargs), "
                    "pas du port image de la card",
        'input_kwarg': 'audio_path',                    # signature historique (déclaré)
        'fixed_kwargs': {'mode': 'standalone', 'avatar_source': 'gallery'},
        'params_module': 'wama.avatarizer.params',
        'params_attr': 'PARAMS_JSON',
        # L'avatar n'est PAS (encore) dans le params.py de l'app → spec additionnelle
        # déclarée ici ; à résorber en l'ajoutant au schéma d'app (options_source).
        'extra_params_spec': [
            {'name': 'avatar_gallery_name', 'label': 'Avatar', 'type': 'select',
             'options_source': 'avatar_gallery'},
        ],
    },
    'anonymizer': {
        'params_module': 'wama.anonymizer.params',
        'params_attr': 'PARAMS_JSON',
    },
}


def _derive_io_from_ports(app_id):
    """E/S du nœud depuis l'accesseur UNIQUE de ports (route §10.1 — fin de la double saisie).

    L'ordre des types du port `travail` est PRÉSERVÉ : c'est la priorité de résolution de
    l'entrée primaire (cf. `create()`), héritée de l'ordre d'APP_CATALOG.input_types. Ne pas
    trier — la variante manifeste (`projection.derive_io_from_ports`) trie, elle, parce
    qu'elle ne sert qu'à une comparaison insensible à l'ordre.
    """
    from wama.common.app_registry import studio_node_ports
    ports = studio_node_ports(app_id) or {}
    io = {}
    for p in ports.get('inputs', []):
        grp = p.get('group')
        if grp == 'travail' and 'input_kinds' not in io:
            kinds = tuple(t for t in (p.get('types') or []) if t and t != 'prompt')
            if kinds:
                io['input_kinds'] = kinds
        elif grp == 'prompt':
            io['primary_input'] = 'prompt'
    out_types = [t for t in ((ports.get('output') or {}).get('types') or []) if t]
    io['output_type'] = out_types[0] if len(out_types) == 1 else ('auto' if out_types else None)
    return io


def _fill_io_from_ports():
    """Complète à l'import les E/S manquantes de chaque entrée depuis les ports.

    Une entrée SANS côté entrée déclaré reçoit `input_kinds` (prioritaire) ou
    `primary_input` ; une entrée sans `output_type` le reçoit des ports. Les clés remplies
    sont tracées dans `_io_derived` — `studio_redundancy` s'en sert pour distinguer
    « dérivé » (concordance par construction) / « rétréci déclaré » (`io_scope`) / « dérive ».
    """
    for app_id, conf in GENERIC_APPS.items():
        derived = _derive_io_from_ports(app_id)
        filled = []
        if 'input_kinds' not in conf and 'primary_input' not in conf:
            if derived.get('input_kinds'):
                conf['input_kinds'] = derived['input_kinds']
                filled.append('input_kinds')
            elif derived.get('primary_input'):
                conf['primary_input'] = derived['primary_input']
                filled.append('primary_input')
        if 'output_type' not in conf and derived.get('output_type') is not None:
            conf['output_type'] = derived['output_type']
            filled.append('output_type')
        conf['_io_derived'] = tuple(filled)


_fill_io_from_ports()


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
