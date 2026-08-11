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
            f'def _process_{fn}(item, ctx):',
            f'    """TROU DE GLU {mark} — corps de backend à générer (marche B).',
            '',
            '    Contrat (task_skeleton) : ctx.progress/ctx.console ; retour {fields, eta,',
            '    label} ; une exception = FAILURE ; nettoyage d\'échec ici."""',
            f"    raise NotImplementedError('{mark} corps de backend non généré (marche B)')",
        ]
    lignes.append('')
    return '\n'.join(lignes), None
