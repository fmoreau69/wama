"""A name READ in a module must be BOUND somewhere in that module (2026-09-27).

Why this exists: two latent `NameError`s lived for months, each hidden in a branch that local runs
never took.
- `wama/describer/views.py` lost its `logger = logging.getLogger(__name__)` on 2026-07-22 (a
  function moved to `url_ingest`, the line went with it): the NINE `logger.*` calls of the module
  raised — the URL import path on its very first line.
- `wama_lab/cam_analyzer/tasks.py` read `_use_sam3_fallback`, defined nowhere (CHANGELOG G2),
  inside an inline SAM3 block that could never run (SAM3 runs as a chained task).
No compiler sees either: Python resolves a name only when the line executes. And no linter runs
here (pyflakes is in neither venv).

The check is deliberately COARSE: a name counts as bound if it is bound ANYWHERE in the module
(assignment, import, def, class, argument, `except … as`, `global`…), whatever the scope. It
therefore misses a name bound in one function and read in another — but it has no false positive
on the tracked code (qualified on 2026-09-27: on the tree before the fix it found exactly the two
defects above, and nothing else once the module dunders are counted as bound).
Vendored third-party code (`vendor/` directories) is out of scope: it is not ours to fix, and it
does carry such names (musetalk's demo app, 13 of them).
"""
import ast
import builtins
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOTS = ('wama', 'wama_lab', 'wama_data')
SKIPPED_DIRS = {'vendor', 'migrations', 'static', 'staticfiles', 'templates', '__pycache__', 'node_modules'}
MODULE_DUNDERS = {'__file__', '__path__', '__name__', '__doc__', '__spec__', '__loader__',
                  '__package__', '__builtins__', '__annotations__', '__dict__', '__module__',
                  '__qualname__', '__class__'}


def unbound_names(source):
    """(name, line) of every name read in `source` that nothing in it binds."""
    tree = ast.parse(source)
    bound = set(dir(builtins)) | MODULE_DUNDERS
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.alias):
            bound.add((node.asname or node.name).split('.')[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
    return sorted({(n.id, n.lineno) for n in ast.walk(tree)
                   if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in bound})


def project_modules():
    base = Path(settings.BASE_DIR)
    for root in ROOTS:
        for path in (base / root).rglob('*.py'):
            if SKIPPED_DIRS.isdisjoint(path.relative_to(base).parts):
                yield path


class UnboundNamesTest(SimpleTestCase):
    maxDiff = None

    def test_no_module_reads_a_name_it_never_binds(self):
        found = []
        for path in project_modules():
            try:
                source = path.read_text(encoding='utf-8')
                names = unbound_names(source)
            except (SyntaxError, UnicodeDecodeError):
                continue   # not this check's business — py_compile / the import tests see it
            found += [f'{path.relative_to(settings.BASE_DIR)}:{line} {name}' for name, line in names]
        self.assertEqual([], found, 'name read but never bound — a NameError the day the line runs')

    def test_the_check_sees_the_two_defects_it_was_written_for(self):
        """Counter-check: both historical shapes are caught, and their fixes are clean."""
        self.assertEqual([('logger', 3)], unbound_names(
            'import logging\ndef view():\n    logger.info("x")\n'))
        self.assertEqual([], unbound_names(
            'import logging\nlogger = logging.getLogger(__name__)\ndef view():\n    logger.info("x")\n'))
        self.assertEqual([('_use_sam3_fallback', 3)], unbound_names(
            'def task(windows, t):\n    inside = any(a <= t <= b for a, b in windows)\n'
            '    if inside or _use_sam3_fallback:\n        pass\n'))
