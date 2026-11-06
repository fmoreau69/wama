"""Une contre-épreuve LOCALE AU PROCESSUS : la mutation n'est jamais écrite sur le disque.

Pourquoi (SKILL.md §4, vécu le 2026-10-29 puis le 2026-11-06) : l'arbre est partagé avec d'autres
instances qui lancent leurs tests — une mutation par ÉDITION, même restaurée à l'octet, est vue par
leurs suites ; et un `.js` SERVI réécrit part à tous les comptes. Ici :
  • un module Python est chargé, dans CE processus seulement, depuis son texte muté (un chercheur
    d'import en tête de `sys.meta_path`) — ce que `mock.patch` n'atteint pas : une ligne À
    L'INTÉRIEUR d'une fonction (une condition, un argument, un appel retiré) ;
  • le TEXTE du fichier visé est muté à sa LECTURE (`Path.read_text`), toujours : le `.js` qu'un
    banc V8 lit, la source qu'un test inspecte — pour un `.py`, en plus de son import (vécu le
    2026-11-06 : une garde qui relisait la source d'un module restait verte sur le seul import).
Les tests passent ensuite par le lanceur WAMA (`execute_from_command_line`, AGENTS.md) ; le code de
sortie est celui de `manage.py test` (non nul = ROUGE).

Usage, depuis la racine du dépôt :
    PYTHONPATH=. python .claude/skills/contre-epreuve/mutate_in_process.py <mutation.json>
<mutation.json> = {"path": "wama/…/x.py", "old": "<texte exact, une occurrence>", "new": "…",
                   "labels": ["wama.….tests_x.UnTest"], "args": ["--keepdb"]}
"""
import importlib.abc
import importlib.util
import json
import os
import pathlib
import sys

ROOT = pathlib.Path.cwd()
spec = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
target = (ROOT / spec['path']).resolve()
original = target.read_text(encoding='utf-8')
count = original.count(spec['old'])
if count != 1:
    sys.exit(f"motif absent ou multiple ({count}) dans {spec['path']} — rien n'est muté")
mutated = original.replace(spec['old'], spec['new'])

if target.suffix == '.py':
    module_name = '.'.join(target.relative_to(ROOT).with_suffix('').parts)

    class _Loader(importlib.abc.Loader):
        def create_module(self, module_spec):
            return None

        def exec_module(self, module):
            exec(compile(mutated, str(target), 'exec'), module.__dict__)

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target_module=None):
            if fullname != module_name:
                return None
            return importlib.util.spec_from_loader(fullname, _Loader(), origin=str(target))

    sys.meta_path.insert(0, _Finder())

# Le TEXTE aussi, toujours : une garde qui lit le fichier (un `.js` servi, la source d'un module
# qu'un test inspecte) voit la mutation — pour un `.py`, en plus de son import.
_read_text = pathlib.Path.read_text


def read_text(self, *args, **kwargs):
    if pathlib.Path(self).resolve() == target:
        return mutated
    return _read_text(self, *args, **kwargs)


pathlib.Path.read_text = read_text

sys.path.insert(0, str(ROOT))
# AVANT le chargement des réglages : c'est la ligne de commande qui fait de ce processus un
# `manage.py test` (`runtime_side` : cache et Celery en mémoire ; `media_guard` le vérifie).
sys.argv = ['manage.py', 'test', *spec['labels'], *spec.get('args', ['--keepdb'])]
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
from django.core.management import execute_from_command_line  # noqa: E402
execute_from_command_line(sys.argv)
