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
    (reader `analyze`, transcriber `enrich` — hors contrat brique, cf. task_skeleton).
    Heuristique : segment source contenant `run_item_task`, ou 'SUCCESS' ET 'FAILURE'.
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
        for node in ast.parse(src).body:
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
            lifecycle = ('run_item_task' in seg
                         or ("'SUCCESS'" in seg and "'FAILURE'" in seg))
            out.append({'function': node.name, 'task_name': task_name,
                        'file': fname, 'lifecycle': lifecycle})
    return out


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
    #        chemin dans output_file, sortie à la convention {app}/{user}/output/ ;
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
                '    from importlib import import_module',
                '    from wama.common.utils.param_schema import effective_settings',
                '    from wama.common.utils.preview_utils import publish_partial_text',
                f'    from .params import {schema_symbole} as _SCH',
                '',
                f'    routes = {routes!r}',
                f"    nature = (getattr(item, '{nature_champ}', '') or '').strip()",
                '    chemin = routes.get(nature)',
                '    if not chemin:',
                '        raise ValueError(f"nature {nature!r} sans backend déclaré "',
                '                         "(processing.backend_routes du manifeste)")',
                '    mod, fonc = chemin.rsplit(\'.\', 1)',
                "    backend = getattr(import_module('.' + mod, __package__), fonc)",
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
        elif compose:
            lignes += [
                f'def _process_{fn}(item, ctx):',
                f'    """CORPS COMPOSÉ {mark} — marche B1 : routage nature→backend du MANIFESTE',
                '    (processing.backend_routes ← backends/__init__.ROUTES), appel au CONTRAT',
                '    COMMUN des backends. Import RELATIF AU PAQUET : la jumelle résout SES',
                '    copies de backends/ sans citer aucun nom d\'app. La tâche lit les COLONNES',
                '    (modèle événementiel §23.2quater) — le preset s\'écrit au clic, pas ici."""',
                '    from importlib import import_module',
                '    from pathlib import Path as _P',
                '    from django.conf import settings as _s',
                '    from wama.common.utils.param_schema import effective_settings',
                f'    from .params import {schema_symbole} as _SCH',
                '',
                f'    routes = {routes!r}',
                f"    nature = (getattr(item, '{nature_champ}', '') or '').strip()",
                '    chemin = routes.get(nature)',
                '    if not chemin:',
                '        raise ValueError(f"nature {nature!r} sans backend déclaré "',
                '                         "(processing.backend_routes du manifeste)")',
                "    fmt = (getattr(item, 'output_format', '') or '').strip().lower()",
                '    if not fmt:',
                '        raise ValueError("format de sortie manquant — régler la card avant de lancer")',
                '    mod, fonc = chemin.rsplit(\'.\', 1)',
                "    backend = getattr(import_module('.' + mod, __package__), fonc)",
                '',
                '    posees = {}',
                f'    for _n in {params_fields!r}:',
                '        _v = getattr(item, _n, None)',
                "        if _v not in (None, '', False):",
                '            posees[_n] = _v',
                f"    opts = effective_settings(_SCH, posees=posees, contexte={{'{nature_champ}': nature}})",
                '',
                f"    rel_dir = f\"{app_id}/{{item.user_id}}/output/\"",
                '    out_dir = _P(_s.MEDIA_ROOT) / rel_dir',
                '    out_dir.mkdir(parents=True, exist_ok=True)',
                '    nom = f"{_P(item.input_filename).stem}_{item.id}.{fmt}"',
                '',
                f'    ctx.console(f"Conversion : {{item.input_filename}} → .{{fmt}} ({{fonc}})")',
                '    backend(item.input_file.path, str(out_dir / nom), fmt,',
                '            options=opts, progress_callback=ctx.progress)',
                "    return {'fields': {'output_file': rel_dir + nom},",
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
    lignes.append('')
    return '\n'.join(lignes), None
