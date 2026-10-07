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
        'io_scope': "nœud V1 = audio seul ; l'avatar est NOMMÉ (réglage du nœud, avatars "
                    "de la médiathèque que l'utilisateur voit), pas relié au port image",
        'input_kwarg': 'audio_path',                    # signature historique (déclaré)
        # `mode` n'est plus figé (2026-08-28) : il se DÉRIVE des entrées dans tool_api —
        # un nœud alimenté en audio sort standalone tout seul.
        'fixed_kwargs': {'avatar_source': 'gallery'},
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


def _twin_can_create(label: str) -> bool:
    """Un nœud studio CRÉE l'élément par l'outil `add_to_<app>` : une jumelle sans cet outil
    afficherait un nœud qui ne peut pas tourner. Elle n'entre donc au registre que s'il existe —
    le manque est celui du GÉNÉRATEUR (l'outil de création n'est pas encore produit depuis le
    manifeste), il ne se maquille pas ici."""
    from wama.tool_api import TOOL_REGISTRY
    return f'add_to_{label}' in TOOL_REGISTRY


# Les JUMELLES du bac à sable : le nœud de leur source, module de params re-ciblé sur leur paquet
# (décision de Fabien, 2026-10-06 — `sandbox.inject_sandbox_registry`), AVANT la dérivation des E/S.
from wama.common.sandbox import inject_sandbox_registry  # noqa: E402
inject_sandbox_registry(GENERIC_APPS, runnable=_twin_can_create)


def _derive_io_from_ports(app_id):
    """E/S du nœud depuis l'accesseur UNIQUE de ports (route §10.1 — fin de la double saisie).

    L'ordre des types du port `travail` est PRÉSERVÉ : c'est la priorité de résolution de
    l'entrée primaire (cf. `create()`), héritée de l'ordre d'APP_CATALOG.input_types. Ne pas
    trier — la variante manifeste (`projection.derive_io_from_ports`) trie, elle, parce
    qu'elle ne sert qu'à une comparaison insensible à l'ordre.
    """
    from wama.common.app_registry import app_input_ports, app_own_input_ports, studio_node_ports
    ports = studio_node_ports(app_id) or {}
    # Un port déclaré « l'un OU l'autre » avec le prompt (`one_of`, ex. le fichier de travail du
    # synthesizer) n'est PAS l'entrée principale : c'est le prompt qui l'est, et ce port arrive en
    # argument nommé (`port_arguments`). Sans cette lecture, ajouter le fichier de travail au nœud
    # aurait fait du synthesizer un nœud à DOCUMENT obligatoire (mesuré le 2026-09-30).
    known = app_own_input_ports(app_id) + app_input_ports(app_id)
    alternatives = {p['id'] for p in known if 'prompt' in (p.get('one_of') or [])}
    # Même règle pour un port de travail que AUCUN modèle n'exige, à côté d'un prompt que TOUS
    # exigent (2026-10-03) : l'entrée principale est ce que les modèles EXIGENT. Cas réel : le
    # morceau à reprendre du composer (`work_audio` de MusicGen Melody, `work_score` de YuE2),
    # devenu port de TRAVAIL — sans cette lecture, le nœud composer exigeait un audio et une
    # chaîne « Texte → Composer » échouait (mesuré sur le catalogue réel).
    required = {p['id']: bool(p.get('required')) for p in known}
    prompt_required = required.get('prompt', False)
    io = {}
    for p in ports.get('inputs', []):
        grp = p.get('group')
        if p.get('id') in alternatives:
            continue
        if grp == 'travail' and prompt_required and not required.get(p.get('id')):
            continue
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
        elif ptype == 'select' and p.get('options_source') == 'catalog':
            # Select tiré du CATALOGUE (route F4b, 2026-10-07) : il tombait dans le cas texte —
            # un champ libre au lieu de la liste que l'app propose (7 nœuds sur 8, mesuré :
            # synthesizer, composer, imager, transcriber, enhancer, avatarizer ×2, anonymizer).
            # Ici, la DÉCLARATION seule : ce spec est mis en cache par `runner_for` ; les options
            # se résolvent à chaque requête (`with_catalog_options`), comme l'endpoint de l'app.
            entry['type'] = 'select'
            entry['options_source'] = 'catalog'
            entry['options_query'] = dict(p.get('options_query') or {})
            entry['options_auto'] = bool(p.get('options_auto'))
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


def with_catalog_options(spec) -> list:
    """Copie de `spec` dont les selects de CATALOGUE reçoivent leurs options MAINTENANT, par LA
    lecture commune (`param_schema.catalog_options` — celle du volet, de l'endpoint, de la
    validation à la création). Le spec d'entrée (en cache) n'est jamais modifié."""
    from wama.common.utils.param_schema import catalog_options
    return [{**entry, 'options': [{'value': v, 'label': l} for v, l in catalog_options(entry)]}
            if entry.get('options_source') == 'catalog' else entry
            for entry in spec]


# ── Les PORTS du nœud → les arguments de l'outil (2026-09-30) ──────────────────────────────────
# Constat de Fabien : « le studio utilise les apps en tant que card ; si l'app déclare ses
# capacités, le studio en hérite, c'est tout ». Mesuré le même jour : le nœud AFFICHAIT tous les
# ports de l'app (`studio_node_ports`, dérivés des modèles) mais le runner n'en transmettait
# qu'UN — l'entrée principale ; les autres liens étaient ignorés sans un mot (synthesizer : voix de
# référence ; composer : mélodie ; avatarizer : image, objet 3D…). La règle est désormais une
# convention, pas une table : **un port arrive dans l'argument DU MÊME NOM de l'outil**
# (`add_to_<app>`). Une app qui lit un port de plus l'ajoute à sa signature — rien ici ne change.
# Un port que l'outil ne lit pas encore est une ERREUR DITE au lancement ; la liste de ces ports
# est tenue par un test qui ne peut que descendre (`studio/tests_node_ports.py`).

def _node_ports(app_id):
    from wama.common.app_registry import studio_node_ports
    return (studio_node_ports(app_id) or {}).get('inputs', [])


def primary_ports(app_id) -> set:
    """Les ports par lesquels arrive l'ENTRÉE PRINCIPALE du nœud (transmise par `create`)."""
    conf = GENERIC_APPS[app_id]
    ports = _node_ports(app_id)
    if conf.get('primary_input') == 'prompt':
        return {'prompt'} | {p['id'] for p in ports if p.get('group') == 'prompt'}
    kinds = set(conf.get('input_kinds') or ())
    return {p['id'] for p in ports
            if p.get('group') == 'travail' and kinds & set(p.get('types') or [])}


def unwired_ports(app_id) -> list:
    """Les ports du nœud que l'outil de l'app ne LIT pas encore — le portage qui reste."""
    from wama.tool_api import tool_arg_names
    accepted = tool_arg_names(f'add_to_{app_id}')
    primary = primary_ports(app_id)
    return sorted(p['id'] for p in _node_ports(app_id)
                  if p['id'] not in primary and p['id'] not in accepted)


#: Ports AFFICHÉS au nœud que l'outil de l'app ne lit pas encore — le portage qui reste, MESURÉ
#: sur le catalogue réel le 2026-09-30 (`ROUTE §10.6`, « on finit le port, jamais de colle côté
#: studio »). Ne peut que DESCENDRE : une app qui lit un port de plus retire sa ligne ; un port non
#: lu qui n'y figure pas fait échouer le geste nocturne `studio.node_ports_wired`.
#: ⚠ Ne jamais AJOUTER une ligne pour faire passer un port neuf : c'est l'outil qu'on complète.
UNWIRED_PORTS_BUDGET = {
    # composer soldé le 2026-10-03 : l'audio du morceau à reprendre (`work_audio`, ex-`reference_melody`)
    # est lu par `compose_music`, comme la partition (`work_score`).
    'imager': ['work_image'],
    'transcriber': ['reference_result', 'work_result'],
    'enhancer': ['work_audio'],
    'avatarizer': ['prompt', 'work_image', 'work_object3d'],
    'anonymizer': ['prompt'],
}


def unwired_ports_report(measure=None):
    """(ok, détail) — la liste MESURÉE des ports non lus confrontée au budget, dans les deux
    sens : un port non lu hors budget (ajout), une ligne de budget soldée mais pas retirée."""
    measure = measure or unwired_ports
    measured = {app: measure(app) for app in GENERIC_APPS}
    grown = {app: [p for p in ports if p not in UNWIRED_PORTS_BUDGET.get(app, [])]
             for app, ports in measured.items()}
    grown = {app: ports for app, ports in grown.items() if ports}
    solved = {app: [p for p in ports if p not in measured.get(app, [])]
              for app, ports in UNWIRED_PORTS_BUDGET.items()}
    solved = {app: ports for app, ports in solved.items() if ports}
    total = sum(len(p) for p in measured.values())
    if grown:
        return False, (f'port(s) du nœud NON LUS par l’outil, hors budget : {grown} — compléter '
                       f'`add_to_<app>` (argument du même nom que le port), jamais le budget')
    if solved:
        return False, f'port(s) désormais lus : retirer du budget (il ne peut que descendre) : {solved}'
    return True, f'{total} port(s) restant à porter, conformes au budget'


def port_arguments(app_id, inputs) -> dict:
    """Les liens reçus sur les ports NON principaux, en arguments nommés de l'outil.
    Lève `ValueError` si un lien arrive sur un port que l'app ne lit pas encore."""
    primary, unwired = primary_ports(app_id), set(unwired_ports(app_id))
    args = {}
    for port in _node_ports(app_id):
        pid = port['id']
        if pid in primary or not inputs.get(pid):
            continue
        if pid in unwired:
            raise ValueError(f"Nœud {app_id} : le port « {port.get('label') or pid} » est branché, "
                             f"mais l'app ne le lit pas encore (portage en cours) — débranchez-le.")
        args[pid] = inputs[pid]
    return args


def build_generic_runner(app_id):
    conf = GENERIC_APPS[app_id]

    def create(user, inputs, params):
        # Passe par execute_tool : MÊME point d'exécution que l'assistant IA et l'API REST
        # (gating d'app, coercition par schéma, filtre de signature). Le studio n'ajoute que
        # ce qui relève du GRAPHE : d'où vient l'entrée principale, et les kwargs figés.
        from wama.tool_api import execute_tool, primary_arg_name
        tool = f'add_to_{app_id}'
        # Les AUTRES ports branchés (voix de référence, fichier de travail, résultat existant…)
        # arrivent dans l'argument DU MÊME NOM de l'outil (2026-09-30). Avant, seule l'entrée
        # principale était transmise : un port branché était IGNORÉ en silence.
        extra = port_arguments(app_id, inputs)
        if conf.get('primary_input') == 'prompt':
            primary = (inputs.get('prompt') or inputs.get('text')
                       or (params or {}).get('prompt') or (params or {}).get('text')
                       or (params or {}).get('text_content') or '').strip()
            # « L'un OU l'autre » (ex. synthesizer : le texte OU un fichier de travail) : un
            # prompt vide n'est une erreur que si aucun autre port n'apporte l'entrée.
            if not primary and not extra:
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
        call_args.update(extra)
        if primary:
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
        # Textualité LUE DU RÉEL, plus déduite de la nature (piège n°1 du retrait de `text`,
        # 2026-08-30) : `output_type` est DÉRIVÉ des ports et vaut désormais 'document' pour
        # describer/reader/transcriber — l'ancien `== 'text'` aurait rendu leur sortie VIDE
        # dans tout pipeline, sans exception ni log. L'adapter detail dit ce qu'il a : un
        # `result_text` non vide EST la sortie texte ; sinon, le fichier.
        texte = d.get('result_text') or ''
        is_text = bool(texte)
        if is_text:
            result = texte
        else:
            # `result_file` est une URL (`FieldFile.url`) : elle est ENCODÉE. Sans `unquote`, un
            # nom accentué (`étudie` → `%C3%A9tudie`) arrivait au nœud suivant sous un chemin qui
            # n'existe pas — mesuré le 2026-09-25 sur synthesizer → transcriber : « Fichier
            # introuvable », alors que le fichier était bien produit.
            from urllib.parse import unquote
            result = unquote(d.get('result_file') or '')
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
