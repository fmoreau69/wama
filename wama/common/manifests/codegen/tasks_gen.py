"""
Gabarit `tasks.py` (palier A2b, route §10.3) — fichier MINCE : squelette commun + trou de glu.

Depuis A2a, le squelette conventionnel vit dans la brique `task_skeleton.run_item_task` : un
`tasks.py` conforme se réduit à « une tâche = 5 lignes + une fonction de glu ». Le gabarit
rend exactement cela, la glu étant un TROU marqué (`NotImplementedError`) que la marche B
(rôle LLM `codegen`) remplira — le juge complet de ce gabarit est donc le pilote B, pas le
harnais strip (un tasks.py existant est de la GLU réelle : jamais strippé, jamais comparé).

Deux rôles :
  - `app_tasks(app_id)` : tâches RÉELLES lues par AST de tasks.py/workers.py (fichier, pas
    import) — {function, task_name, file, lifecycle}. `lifecycle` distingue les tâches à
    cycle de vie d'item (adopteront `run_item_task`) des ENRICHISSEMENTS à la demande
    (transcriber `enrich` — hors contrat brique, cf. task_skeleton ; l'`analyze` du reader
    est un process de son pipeline depuis le 2026-10-13, joué par `run_item_task`).
    Heuristique : segment source contenant `run_item_task`, ou 'SUCCESS' ET 'FAILURE' — ou une
    fonction du MÊME module qu'elle appelle et qui atteint `run_item_task` (le transcriber passe
    par `_run_transcription`, 2026-10-20 : ses tâches se lisaient « non lifecycle », rien n'était
    généré et les vues générées importaient un module absent).
  - `render_tasks(manifest)` : rend le fichier mince pour les tâches lifecycle déclarées.
    Requiert `processing.tasks` + `processing.item_model` (extraits par la facette).
"""
from __future__ import annotations

import ast
from pathlib import Path


def tasks_file_path(app_id: str) -> Path:
    import wama
    return Path(wama.__file__).parent / app_id / 'tasks.py'


def app_tasks(app_id: str) -> list:
    """Tâches Celery réelles de l'app, par AST des fichiers (déterministe, jamais d'import)."""
    import wama
    base = Path(wama.__file__).parent / app_id
    out = []
    for fname in ('tasks.py', 'workers.py'):
        p = base / fname
        if not p.is_file():
            continue
        src = p.read_text(encoding='utf-8')
        tree = ast.parse(src)
        reaches_skeleton = _functions_reaching_skeleton(tree)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decore, task_name = False, None
            for d in node.decorator_list:
                cible = d.func if isinstance(d, ast.Call) else d
                nom = getattr(cible, 'attr', None) or getattr(cible, 'id', None)
                if nom in ('shared_task', 'task'):
                    decore = True
                    if isinstance(d, ast.Call):
                        for kw in d.keywords:
                            if kw.arg == 'name' and isinstance(kw.value, ast.Constant):
                                task_name = kw.value.value
            if not decore:
                continue
            seg = ast.get_source_segment(src, node) or ''
            lifecycle = (node.name in reaches_skeleton
                         or ("'SUCCESS'" in seg and "'FAILURE'" in seg))
            out.append({'function': node.name, 'task_name': task_name,
                        'file': fname, 'lifecycle': lifecycle})
    return out


def _functions_reaching_skeleton(tree) -> set:
    """Les fonctions de niveau module qui appellent le squelette commun (`run_item_task`), ou une
    fonction du même module qui l'appelle — transitivement. Le seul signal propagé est la BRIQUE :
    une aide qui écrit 'SUCCESS' ne fait pas d'une tâche une tâche d'élément. Seuls comptent les
    appels par NOM NU (`_run_transcription(...)`) : un appel d'attribut homonyme
    (`backend.transcribe(...)`) n'est pas la fonction du module."""
    calls = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls[node.name] = {n.func.id for n in ast.walk(node)
                                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    reaching = {name for name, called in calls.items() if 'run_item_task' in called}
    grew = True
    while grew:
        grew = False
        for name, called in calls.items():
            if name not in reaching and called & reaching:
                reaching.add(name)
                grew = True
    return reaching


def model_route(manifest: dict):
    """Ce qu'il faut pour composer un corps routé par MODÈLE (saveur « modèle », 2026-10-08), ou
    None : le select de catalogue du schéma principal et sa TÂCHE, le contrat de cette tâche, le
    PORT de travail de l'app (`body.ports.inputs`, groupe `travail`) que la méthode du contrat
    reçoit sous son nom, le champ fichier d'entrée de l'élément et un champ de résultat TEXTE
    déclaré. Tout se lit dans le manifeste, dans `TASK_CONTRACTS` et sur la signature du contrat
    — rien d'écrit pour une app, rien de déclaré à côté."""
    body = manifest.get('body') or {}
    params = body.get('params') or {}
    primary = params.get('primary') or ''
    schema = (params.get('schemas') or {}).get(primary) or []
    select = next((p for p in schema if isinstance(p, dict) and p.get('options_source') == 'catalog'
                   and ((p.get('options_query') or {}).get('task'))), None)
    if select is None:
        return None
    tasks = [t.strip() for t in str(select['options_query']['task']).split(',') if t.strip()]
    if len(tasks) != 1:
        return None                     # plusieurs tâches = plusieurs contrats : pas un corps unique
    import importlib
    from wama.common.services.backend_inventory import TASK_CONTRACTS
    spec = TASK_CONTRACTS.get(tasks[0])
    if not spec:
        return None
    try:
        contract = getattr(importlib.import_module(f'wama.common.backends.{spec[0]}'), spec[1])
    except Exception:
        return None
    port = next((p.get('id') for p in ((body.get('ports') or {}).get('inputs') or [])
                 if isinstance(p, dict) and p.get('group') == 'travail' and p.get('id')), '')
    from wama.common.backends.manager import work_method_accepts
    if not port or not work_method_accepts(contract, port):
        return None
    proc = body.get('processing') or {}
    item = ((proc.get('model_spec') or {}).get('item') or {})
    input_field = item.get('input_field') or ''
    from .models_gen import declared_result_fields
    text_field = next((n for n, kind in declared_result_fields(body, input_field)
                       if kind == 'text'), '')
    if not (input_field and text_field and primary):
        return None
    return {'param': select['name'], 'task': tasks[0], 'schema': primary,
            'domain': dict(select['options_query']), 'port': port,
            'input_field': input_field, 'result_field': text_field,
            'params_fields': list(item.get('params_fields') or [])}


def _instant_hole(manifest: dict, mark: str) -> list:
    """Le TROU DE GLU du résultat instantané, quand la route `instant` est déclarée (2026-10-16,
    capacité `instant_preview`) : la vue générée l'appelle sur un élément NON enregistré."""
    endpoints = (((manifest.get('body') or {}).get('processing') or {}).get('endpoints') or [])
    if 'instant' not in endpoints:
        return []
    return [
        '',
        '',
        'def instant_result(item) -> str:',
        f'    """TROU DE GLU {mark} — résultat INSTANTANÉ de la saisie, marche B.',
        '',
        '    `item` n\'est PAS enregistré (aucun id, aucun fichier) : rendre le texte du résultat à',
        '    partir de ses champs (la saisie, ses réglages), vite — la card l\'appelle pendant la',
        '    frappe. Une exception = son message affiché dans la zone de la card (502). Pas de',
        '    `ctx` ici : le label de l\'app est `item._meta.app_label`."""',
        f"    raise NotImplementedError('{mark} résultat instantané non généré (marche B)')",
    ]


#: Les fonctions qu'une AUTRE déclaration désigne PAR CHAÎNE dans le module de tâches de l'app —
#: rôle → (signature, la déclaration qui la nomme, l'appelant dont la docstring FAIT le contrat).
#: Elles ne sont pas des tâches : rien ne les importe, un chemin pointé les résout à l'exécution.
#: Un `tasks.py` généré qui ne les porte pas laisse ces déclarations pointer dans le vide (vécu le
#: 2026-10-18 sur `converter_01`, `tests_source_ingest`). Le contrat n'est pas recopié ici : il vit
#: chez son appelant, et une copie dériverait de lui.
_DECLARED_GLUE = {
    'derive': ('inst, path, fname', "`WAMA_INGEST['derive']`",
               'wama.common.utils.source_ingest.ensure_local_input'),
    'eta': ('item', '`ProcessSpec.eta`', 'wama.common.services.process_runs.process_eta'),
    'result': ('item', '`ProcessSpec.result`',
               'wama.common.services.process_pipeline.AppPipeline.declared_result'),
}


def superseded_task_files(manifest: dict, fname: str = 'tasks.py') -> list:
    """Les modules de tâches COPIÉS que le `tasks.py` GÉNÉRÉ remplace, dans l'ordre du manifeste.

    Le manifeste déclare où vit chaque tâche de l'app (`processing.tasks[].file`) : quatre apps
    la logent dans `workers.py`, et `wama/celery.py` autodécouvre LES DEUX noms (`tasks` et
    `workers`). Une jumelle qui garde sa copie de `workers.py` à côté du `tasks.py` généré
    enregistre donc la MÊME tâche deux fois — et sa copie importe des symboles des vues
    COPIÉES (`detect_type_from_extension`) que les vues GÉNÉRÉES n'exposent pas. Mesuré le
    2026-09-22 sur `describer_01` : la substitution de `views` était refusée pour un import
    d'un module que plus rien n'appelait. Porter, c'est REMPLACER : le généré retire la copie
    (`app_sandbox substitute`), et les déclarations générées qui le désignaient le suivent
    (`generated_task_path`)."""
    proc = (manifest.get('body') or {}).get('processing') or {}
    seen, out = set(), []
    for t in (proc.get('tasks') or []):
        f = str((t or {}).get('file') or '').strip()
        if f and f != fname and f.endswith('.py') and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _task_modules(manifest: dict) -> set:
    """Les modules de tâches de l'app, au nom de module : `tasks` et ceux qu'il remplace."""
    return {'tasks'} | {f[:-3] for f in superseded_task_files(manifest)}


def split_declared_path(path: str) -> tuple:
    """`(module sans « wama. », nom, séparateur)` d'une déclaration par chaîne — chemin pointé
    (`wama.<app>.tasks._fn`, `WAMA_INGEST`) ou `module:attribut` (`<app>.tasks:fn`,
    `ProcessSpec.eta`). La seule lecture de ces deux formes côté génération : les générateurs
    et le juge de substitution d'`app_sandbox` la partagent."""
    path = str(path or '').strip()
    sep = ':' if ':' in path else '.'
    module, _, name = path.rpartition(sep)
    return (module[len('wama.'):] if module.startswith('wama.') else module), name, sep


def generated_task_path(manifest: dict, path):
    """`path` re-ciblé sur le `tasks.py` GÉNÉRÉ quand il désigne un module de tâches que le
    généré remplace (`<app>.workers:fn` → `<app>.tasks:fn`), tel quel sinon. La règle de
    `sandbox._retarget`, pour les déclarations que les GÉNÉRATEURS écrivent (`function_specs`,
    `models`) : un générateur n'émet jamais de `workers.py`."""
    if not isinstance(path, str):
        return path
    app_id = manifest.get('key') or ''
    module, name, sep = split_declared_path(path)
    old = {f'{app_id}.{m}' for m in _task_modules(manifest) - {'tasks'}}
    if module not in old:
        return path
    prefix = 'wama.' if path.strip().startswith('wama.') else ''
    return f'{prefix}{app_id}.tasks{sep}{name}'


def declared_glue(manifest: dict, steps: list, modules=None) -> list:
    """`[(nom, rôle)]` des fonctions que le manifeste et le pipeline déclarent dans le module de
    tâches de l'app : le `derive` de l'ingest, l'`eta` et le `result` de chaque process.
    `modules` (noms de module de l'app) en vise un autre : `function_specs_gen` y lit les lectures
    de résultat qu'un pipeline loge dans `function_specs` (describer, reader — 2026-10-20)."""
    app_id = manifest.get('key') or ''
    proc = (manifest.get('body') or {}).get('processing') or {}
    modules = {f'{app_id}.{m}' for m in (modules or _task_modules(manifest))}
    declared = [((proc.get('ingest') or {}).get('derive'), 'derive')]
    declared += [(s.get(role), role) for s in steps for role in ('eta', 'result')]
    out = []
    for path, role in declared:
        module, name, _ = split_declared_path(path)
        if module in modules and name.isidentifier() and name not in {n for n, _ in out}:
            out.append((name, role))
    return out


def declared_glue_holes(manifest: dict, steps: list, mark: str, emitted: set,
                        modules=None) -> list:
    """Le TROU DE GLU de chaque fonction déclarée par chaîne (`declared_glue`) que le fichier
    n'émet pas déjà — même marque que les autres trous : le geste `app_sandbox glue` le remplit."""
    lines = []
    for name, role in declared_glue(manifest, steps, modules):
        if name in emitted:
            continue
        params, declaration, caller = _DECLARED_GLUE[role]
        lines += [
            '',
            '',
            f'def {name}({params}):',
            f'    """TROU DE GLU {mark} — fonction DÉCLARÉE par chaîne ({declaration}), marche B.',
            '',
            f'    Contrat : la docstring de son appelant, `{caller}`."""',
            f"    raise NotImplementedError('{mark} {role} `{name}` non généré (marche B)')",
        ]
    return lines


def render_tasks(manifest: dict) -> tuple:
    """(source, raison) — fichier mince complet, ou (None, raison) si la facette ne porte pas
    de quoi le rendre (tasks lifecycle + item_model). Jamais de fichier partiel."""
    from ..builtin.app import _GEN_MARK
    app_id = manifest.get('key')
    proc = (manifest.get('body') or {}).get('processing') or {}
    item_model = proc.get('item_model')
    taches = [t for t in (proc.get('tasks') or []) if t.get('lifecycle')]
    if not item_model:
        return None, 'processing.item_model absent (DetailRegistry non renseigné ?)'
    if not taches:
        return None, 'aucune tâche lifecycle déclarée (processing.tasks)'

    mark = _GEN_MARK.format(app_id=app_id)
    label = manifest.get('name') or app_id.title()
    lignes = [
        '"""',
        f"{mark} — tasks.py GÉNÉRÉ par write_back_app (facette processing, gabarit A2b).",
        '',
        'Fichier MINCE : le squelette (gardes, progress, chrono, statuts, ETA, console,',
        'notifications) vient de la brique commune task_skeleton ; la GLU de chaque tâche est',
        'un TROU à remplir (marche B — corps de backend depuis le manifeste composé).',
        'Ne pas éditer le squelette à la main : rejouer write_back après modification du',
        'manifeste ; remplir uniquement les corps `_process_*`.',
        '"""',
        'from celery import shared_task',
        '',
        f'from .models import {item_model}',
        '',
    ]
    # ── Marche B1 (2026-09-02) : le corps se COMPOSE quand le manifeste route ─────────────
    # `processing.backend_routes` (déclaré `backends/__init__.ROUTES` de l'app source) donne
    # nature → chemin du callable au CONTRAT COMMUN. Le corps généré n'écrit RIEN à la main :
    # résolution du backend par la nature de l'item, valeurs effectives par la brique commune
    # (modèle événementiel §23.2quater : la tâche lit les COLONNES). Sans routes déclarées,
    # le stub NotImplementedError demeure (marche B non applicable à cette app — un trou
    # marqué vaut mieux qu'une invention).
    #
    # DEUX SAVEURS depuis le 2026-09-03 (2ᵉ app routée : describer), déclarées par
    # `processing.backend_result` (← `backends/__init__.RESULT` de l'app source) :
    #   'file' (défaut — pilote converter) : le backend ÉCRIT output_path, la tâche range le
    #        chemin dans output_file, sortie au domicile de l'utilisateur (`app_media_dir`) ;
    #   'text' (describer) : le backend REND le texte, la tâche le persiste dans la colonne
    #        `field` déclarée, et publie l'aperçu PARTIEL (during_preview) au fil de l'eau.
    routes = (proc.get('backend_routes') or {})
    schema_symbole = ((manifest.get('body') or {}).get('params') or {}).get('primary') or ''
    spec_item = ((proc.get('model_spec') or {}).get('item') or {})
    params_fields = list(spec_item.get('params_fields') or [])
    result_decl = proc.get('backend_result') or {'kind': 'file'}
    result_kind = result_decl.get('kind') or 'file'
    result_field = result_decl.get('field') or ''
    nature_champ = (proc.get('backend_nature_field')
                    or ('media_type' if 'media_type' in params_fields else ''))
    compose = bool(routes and schema_symbole and nature_champ
                   and (result_kind == 'file' or result_field))
    # Saveur « MODÈLE » (2026-10-08) : sans ROUTES, une app dont le schéma choisit un modèle du
    # catalogue PAR TÂCHE (`options_query.task`) se compose sur la porte commune — tirage « auto »
    # dans le domaine déclaré, backend dérivé de la clé (`backend_instance_for_key`, modèles
    # distants compris), méthode de travail du contrat (`run_contract`). Sa glu n'est plus que
    # le backend lui-même.
    by_model = None if routes else model_route(manifest)

    # ── App à PLUSIEURS process (2026-10-05, patron composer — décision n°11, ROUTE §10.6) ──
    # Le pipeline se lit par la CLÉ de l'app (`pipeline_decl`, jamais une facette du manifeste
    # `app`). Une tâche, des glus : `run_item_task(pipeline=, processes=, only=)` joue les process
    # retenus, `process=` borne le lancement (▶ d'un process, `steps_to_run(only=)`) — défaut
    # `None` : un worker en service qui ne connaît pas l'argument reste compatible.
    from wama.common.manifests.codegen.pipeline_decl import declared_pipeline, process_specs
    _pipeline, _functions = declared_pipeline(app_id)
    _steps = process_specs(_pipeline) if _pipeline else []
    if len(_steps) >= 2 and len(taches) == 1:
        fn = taches[0]['function']
        name_kw = f", name='{taches[0]['task_name']}'" if taches[0].get('task_name') else ''
        glus = ', '.join(f"'{s['key']}': _process_{fn}_{s['key']}" for s in _steps)
        lignes += [
            '',
            f'@shared_task(bind=True{name_kw})',
            f'def {fn}(self, item_id: int, process: str | None = None):',
            '    """Tâche de la card : joue son PIPELINE (`function_specs.PIPELINE`). `process` : ▶ d\'UN',
            '    process — lui et ses seuls amonts périmés (`steps_to_run(only=)`)."""',
            '    from wama.common.utils.task_skeleton import run_item_task',
            '    from .function_specs import PIPELINE',
            f"    run_item_task(self, app_id='{app_id}', model={item_model}, item_id=item_id,",
            f'                  pipeline=PIPELINE, processes={{{glus}}},',
            f"                  only=process, notify_label='{label}')",
        ]
        from wama.common.manifests.codegen.pipeline_decl import OUTPUT_PROCESS_KEY
        for s in _steps:
            outputs = ', '.join(s['outputs']) or '(aucune déclarée)'
            ups = ', '.join(s['depends_on']) or 'aucun'
            if s['key'] == OUTPUT_PROCESS_KEY:
                # Process « Sortie » COMMUN : sa glu est la brique `output_step` — le trou ne
                # demande que le champ du rendu et son domaine, jamais un traitement réécrit.
                lignes += [
                    '',
                    '',
                    f'def _process_{fn}_{s["key"]}(item, ctx):',
                    f'    """TROU DE GLU {mark} — process COMMUN « Sortie » (amont : {ups}), marche B.',
                    '',
                    '    Sa glu est la brique `output_process.output_step(<champ du rendu>, domain=…,',
                    '    app_id=ctx.app_id)(item, ctx)` : réglages de sortie (format, qualité,',
                    '    agrandissement) appliqués à l\'original que l\'amont a écrit. Rien d\'autre."""',
                    f"    raise NotImplementedError('{mark} process {s['key']} non généré (marche B)')",
                ]
                continue
            lignes += [
                '',
                '',
                f'def _process_{fn}_{s["key"]}(item, ctx):',
                f'    """TROU DE GLU {mark} — process `{s["key"]}` ({s["label"] or s["key"]}), marche B.',
                '',
                f'    Amont(s) : {ups}. Sortie(s) DÉCLARÉE(S) : {outputs} — un FICHIER de la card,',
                '    rendu sous `fields` ET sous `output_ref` (le chemin relatif) : c\'est son empreinte',
                '    qui périme l\'aval quand cette sortie est remplacée. Contrat `task_skeleton` :',
                '    ctx.progress/ctx.console/ctx.app_id ; retour {fields, output_ref, label, models} ;',
                '    une exception = FAILURE de la card."""',
                f"    raise NotImplementedError('{mark} process {s['key']} non généré (marche B)')",
            ]
        emitted = {fn} | {f'_process_{fn}_{s["key"]}' for s in _steps}
        lignes.extend(declared_glue_holes(manifest, _steps, mark, emitted))
        lignes.extend(_instant_hole(manifest, mark))
        lignes.append('')
        return '\n'.join(lignes), None

    for t in taches:
        fn = t['function']
        name_kw = f", name='{t['task_name']}'" if t.get('task_name') else ''
        lignes += [
            '',
            f'@shared_task(bind=True{name_kw})',
            f'def {fn}(self, item_id: int):',
            '    from wama.common.utils.task_skeleton import run_item_task',
            f"    run_item_task(self, app_id='{app_id}', model={item_model}, item_id=item_id,",
            f"                  process=_process_{fn}, notify_label='{label}')",
            '',
            '',
        ]
        if compose and result_kind == 'text':
            lignes += [
                f'def _process_{fn}(item, ctx):',
                f'    """CORPS COMPOSÉ {mark} — marche B1, saveur TEXTE : routage nature→backend',
                '    du MANIFESTE (processing.backend_routes ← backends/__init__.ROUTES), appel au',
                '    CONTRAT COMMUN « texte » — le backend REND le texte, la tâche le persiste',
                '    dans la colonne déclarée (processing.backend_result). Import RELATIF AU',
                '    PAQUET : la jumelle résout SES copies de backends/ sans citer aucun nom',
                '    d\'app. La tâche lit les COLONNES (modèle événementiel §23.2quater)."""',
                '    from wama.common.backends.manager import route_for_nature',
                '    from wama.common.utils.param_schema import effective_settings',
                '    from wama.common.utils.preview_utils import publish_partial_text',
                f'    from .params import {schema_symbole} as _SCH',
                '',
                f'    routes = {routes!r}',
                f"    nature = (getattr(item, '{nature_champ}', '') or '').strip()",
                '    backend = route_for_nature(__package__, nature, routes=routes)',
                '    fonc = backend.__name__',
                '',
                '    posees = {}',
                f'    for _n in {params_fields!r}:',
                '        _v = getattr(item, _n, None)',
                "        if _v not in (None, '', False):",
                '            posees[_n] = _v',
                f"    opts = effective_settings(_SCH, posees=posees, contexte={{'{nature_champ}': nature}})",
                '',
                f'    ctx.console(f"Traitement ({{fonc}}) : {{nature}}")',
                '    texte = backend(item.input_file.path, options=opts,',
                '                    progress_callback=ctx.progress,',
                f"                    partial_callback=lambda t: publish_partial_text('{app_id}', item.pk, t),",
                '                    console=ctx.console)',
                f"    return {{'fields': {{'{result_field}': texte}}}}",
            ]
        elif by_model:
            r = by_model
            lignes += [
                f'def _process_{fn}(item, ctx):',
                f'    """CORPS COMPOSÉ {mark} — marche B1, saveur MODÈLE : le select `{r["param"]}`',
                f'    choisit un modèle du catalogue pour la tâche `{r["task"]}` ; « auto » tire dans ce',
                '    domaine déclaré, la porte commune dérive le backend de la clé (modèles distants',
                '    compris) et appelle la méthode de travail de son CONTRAT avec les réglages de',
                f'    l\'élément par leur nom, et son fichier par celui de son PORT (`{r["port"]}`). La',
                '    tâche lit les COLONNES (modèle événementiel §23.2quater)."""',
                '    from wama.common.backends.manager import backend_instance_for_key, run_contract',
                '    from wama.common.utils.auto_model import resolve_model_choice',
                '    from wama.common.utils.param_schema import effective_settings',
                '    from wama.common.utils.preview_utils import publish_partial_text',
                f'    from .params import {r["schema"]} as _SCH',
                '',
                '    given = {}',
                f'    for _n in {r["params_fields"]!r}:',
                '        _v = getattr(item, _n, None)',
                "        if _v not in (None, '', False):",
                '            given[_n] = _v',
                '    opts = effective_settings(_SCH, posees=given)',
                # Le DOMAINE du select utilisé (`spec=`), comme l'enhancer et le composer : une app
                # à deux selects n'en tire jamais un dans le domaine de l'autre.
                f"    key = resolve_model_choice(opts.pop('{r['param']}', ''), app_id={app_id!r},",
                f"                               spec={r['domain']!r}, item=item)",
                '    if not key:',
                f'        raise ValueError("aucun modèle de la tâche « {r["task"]} » au catalogue")',
                '',
                '    ctx.console(f"Modèle : {key}")',
                # Absent : la ROUTE l'installe et la tâche attend (`ctx.ensure_model`, 2026-10-18).
                '    ctx.ensure_model(key)',
                '    engine = backend_instance_for_key(key, user=item.user)',
                f'    text = run_contract(engine, {r["port"]}=item.{r["input_field"]}.path,',
                '                        progress_callback=ctx.progress,',
                f"                        on_partial=lambda t: publish_partial_text('{app_id}', item.pk, t),",
                '                        **opts)',
                '    if not isinstance(text, str):',
                '        raise TypeError(f"{type(engine).__name__} ne rend pas de texte")',
                f"    return {{'fields': {{'{r['result_field']}': text}}, 'models': [key]}}",
            ]
        elif compose:
            lignes += [
                f'def _process_{fn}(item, ctx):',
                f'    """CORPS COMPOSÉ {mark} — marche B1 : routage nature→backend du MANIFESTE',
                '    (processing.backend_routes ← backends/__init__.ROUTES), appel au CONTRAT',
                '    COMMUN des backends. Import RELATIF AU PAQUET : la jumelle résout SES',
                '    copies de backends/ sans citer aucun nom d\'app. La tâche lit les COLONNES',
                '    (modèle événementiel §23.2quater) — le preset s\'écrit au clic, pas ici."""',
                '    from wama.common.backends.manager import route_for_nature',
                '    from wama.common.utils.param_schema import effective_settings',
                f'    from .params import {schema_symbole} as _SCH',
                '',
                f'    routes = {routes!r}',
                f"    nature = (getattr(item, '{nature_champ}', '') or '').strip()",
                '    backend = route_for_nature(__package__, nature, routes=routes)',
                '    fonc = backend.__name__',
                "    fmt = (getattr(item, 'output_format', '') or '').strip().lower()",
                '    if not fmt:',
                '        raise ValueError("format de sortie manquant — régler la card avant de lancer")',
                '',
                '    posees = {}',
                f'    for _n in {params_fields!r}:',
                '        _v = getattr(item, _n, None)',
                "        if _v not in (None, '', False):",
                '            posees[_n] = _v',
                f"    opts = effective_settings(_SCH, posees=posees, contexte={{'{nature_champ}': nature}})",
                '',
                # La PLACE et le NOM de la sortie viennent de la brique du squelette
                # (`ctx.output_place` : domicile de l'app, règle commune de nommage), comme dans
                # les glues des apps réelles (2026-10-22). Ce gabarit émettait d'abord
                # `f"<app>/{item.user_id}/output/"` (l'ancien domicile, relevé le 2026-09-22), puis
                # `app_media_dir` + `compose_output_name` à la main (relevé le 2026-10-07).
                '    rel, path = ctx.output_place(fmt, source_name=item.input_filename)',
                '',
                f'    ctx.console(f"Conversion : {{item.input_filename}} → .{{fmt}} ({{fonc}})")',
                '    backend(item.input_file.path, path, fmt,',
                '            options=opts, progress_callback=ctx.progress)',
                "    return {'fields': {'output_file': rel},",
                '            \'label\': f".{fmt}"}',
            ]
        else:
            lignes += [
                f'def _process_{fn}(item, ctx):',
                f'    """TROU DE GLU {mark} — corps de backend à générer (marche B).',
                '',
                '    Contrat (task_skeleton) : ctx.progress/ctx.console ; retour {fields, eta,',
                '    label} ; une exception = FAILURE ; nettoyage d\'échec ici.',
                '',
                '    ⚠ Les VALEURS de réglage se lisent par la brique commune (2026-09-01) :',
                '        from wama.common.utils.param_schema import effective_settings',
                '        opts = effective_settings(PARAMS_JSON, posees=…, preset=…, contexte=…)',
                '    — défauts du schéma ← preset ← réglages POSÉS. Ne PAS relire un défaut en dur',
                '    dans le corps (`opts.get(\'x\', 12)`) : c\'est la 3ᵉ copie du même défaut, et',
                '    c\'est exactement ce que cette brique vient de résorber (ROADMAP §23.2bis)."""',
                f"    raise NotImplementedError('{mark} corps de backend non généré (marche B)')",
            ]
    emitted = {n for t in taches for n in (t['function'], f"_process_{t['function']}")}
    lignes.extend(declared_glue_holes(manifest, _steps, mark, emitted))
    lignes.extend(_instant_hole(manifest, mark))
    lignes.append('')
    return '\n'.join(lignes), None
