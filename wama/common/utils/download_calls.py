"""Ce qui, dans du CODE, télécharge des poids ou lance pip — lu par l'AST, jamais exécuté.

La lecture vivait dans le contrôle de la route d'installation (`tests_install_route`, 2026-10-16),
qui l'applique au code de WAMA : tout site hors de la route est une dérive. Elle en sort le
2026-11-08 pour un second lecteur de même nature — le rôle `backend`, à qui il faut dire où le
code VENDORISÉ d'un moteur télécharge lui-même (ACE-Step 1.5 : `snapshot_download` derrière
`initialize_service`), pour que le backend qu'il écrit n'atteigne jamais ces chemins. Une lecture,
deux lecteurs : le contrôle de la route et la matière du rôle disent les mêmes sites.
"""
import ast
import functools
from pathlib import Path

#: Téléchargements directs de poids et exécutions de pip, par le nom appelé.
DOWNLOAD_CALLS = {'download_asset', 'urlretrieve', 'load_state_dict_from_url',
                  'download_url_to_file', 'hf_hub_download', 'snapshot_download',
                  'pip_install_packages'}


def called_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ''


def writes_a_response_body(node) -> bool:
    """Un corps de réponse HTTP ÉCRIT dans un fichier (2026-11-06) — en flux (`for chunk in
    r.iter_content(…): f.write(chunk)`) ou entier (`f.write(r.content)`). Les appels nommés
    ci-dessus ne le voyaient pas : l'anonymizer tirait ainsi des poids YOLO officiels au premier
    usage, à côté de la route. Un envoi copié par `chunks()` et un corps lu en mémoire ne sont ni
    l'un ni l'autre."""
    if isinstance(node, ast.For) and isinstance(node.iter, ast.Call) \
            and called_name(node.iter) == 'iter_content' and isinstance(node.target, ast.Name):
        loop_var = node.target.id
        return any(isinstance(n, ast.Call) and called_name(n) in ('write', 'write_bytes')
                   and any(isinstance(a, ast.Name) and a.id == loop_var for a in n.args)
                   for statement in node.body for n in ast.walk(statement))
    return (isinstance(node, ast.Call) and called_name(node) in ('write', 'write_bytes')
            and any(isinstance(a, ast.Attribute) and a.attr == 'content' for a in node.args))


def runs_pip(call: ast.Call) -> bool:
    """Un sous-processus dont la liste d'arguments nomme `pip` et `install`."""
    for arg in call.args:
        if isinstance(arg, (ast.List, ast.Tuple)):
            words = {e.value for e in arg.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if 'pip' in words and 'install' in words:
                return True
    return False


def is_download_site(node) -> bool:
    """Le nœud télécharge-t-il un poids ou lance-t-il pip ?"""
    return ((isinstance(node, ast.Call) and (called_name(node) in DOWNLOAD_CALLS or runs_pip(node)))
            or writes_a_response_body(node))


def download_sites(tree) -> list:
    """`[(ligne, fonction englobante, ce qui est appelé)]` des sites d'un module analysé."""
    sites = []

    def visit(node, function):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            if is_download_site(child):
                what = called_name(child) if isinstance(child, ast.Call) else 'corps de réponse écrit'
                sites.append((child.lineno, function, what))
            visit(child, inner)
    visit(tree, '')
    return sorted(sites)


def _modules(root, skipped):
    """`[(fichier relatif, arbre)]` des modules Python sous `root` (fichiers de test exclus)."""
    base, out = Path(root), []
    if not base.is_dir():
        return out
    for path in sorted(base.rglob('*.py')):
        rel = path.relative_to(base)
        if set(skipped) & set(rel.parts[:-1]) or rel.name.startswith('test') \
                or rel.name.endswith('_test.py'):
            continue
        try:
            out.append((rel.as_posix(), ast.parse(path.read_text(encoding='utf-8', errors='replace'))))
        except (SyntaxError, ValueError):
            continue
    return out


def code_download_sites(root, skipped=('tests',)) -> dict:
    """`{fichier relatif: [(ligne, fonction, appel)]}` sous `root` (fichiers de test exclus)."""
    found = {}
    for rel, tree in _modules(root, skipped):
        sites = download_sites(tree)
        if sites:
            found[rel] = sites
    return found


def functions_reaching_download(root) -> dict:
    """`{fonction: 'fichier:ligne'}` — les fonctions du code sous `root` qui TÉLÉCHARGENT, ou qui
    appellent (de proche en proche) une fonction qui télécharge. Par le NOM des fonctions
    appelées, sans résolution d'import : une lecture, pas une exécution — un homonyme est compté,
    un excès qui ne cache rien. Un backend écrit sur ce moteur n'en appelle aucune : les poids
    sont déjà installés par la route (2026-11-08, ACE-Step : `initialize_service` y mène par
    `_ensure_models_present`). Mémoïsé par dossier, comme les noms du code d'un clone
    (`vendor_installer._code_names`) ; une installation vendorisée l'oublie."""
    return dict(_reaching(str(root)))


@functools.lru_cache(maxsize=32)
def _reaching(root: str) -> tuple:
    modules = _modules(root, ('tests',))
    defined, calls = {}, {}
    for rel, tree in modules:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and not node.name.startswith('test_'):
                defined.setdefault(node.name, f'{rel}:{node.lineno}')
                calls.setdefault(node.name, set()).update(
                    called_name(n) for n in ast.walk(node) if isinstance(n, ast.Call))
    reaching = {function for _, tree in modules for _, function, _ in download_sites(tree)
                if function in defined}
    grown = True
    while grown:
        added = {name for name, called in calls.items() if name not in reaching and called & reaching}
        reaching |= added
        grown = bool(added)
    return tuple((name, defined[name]) for name in sorted(reaching))
