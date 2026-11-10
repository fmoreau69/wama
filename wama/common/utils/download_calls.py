"""Ce qui, dans du CODE, télécharge des poids ou lance pip — lu par l'AST, jamais exécuté.

La lecture vivait dans le contrôle de la route d'installation (`tests_install_route`, 2026-10-16),
qui l'applique au code de WAMA : tout site hors de la route est une dérive. Elle en sort le
2026-11-08 pour un second lecteur de même nature — le rôle `backend`, à qui il faut dire où le
code VENDORISÉ d'un moteur télécharge lui-même (ACE-Step 1.5 : `snapshot_download` derrière
`initialize_service`), pour que le backend qu'il écrit n'atteigne jamais ces chemins. Une lecture,
deux lecteurs : le contrôle de la route et la matière du rôle disent les mêmes sites.
"""
import ast
import builtins
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


def _sites(tree, is_site) -> list:
    """`[(ligne, fonction englobante, nœud)]` des nœuds de `tree` que `is_site` retient."""
    sites = []

    def visit(node, function):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            if is_site(child):
                sites.append((child.lineno, function, child))
            visit(child, inner)
    visit(tree, '')
    return sites


def download_sites(tree) -> list:
    """`[(ligne, fonction englobante, ce qui est appelé)]` des sites d'un module analysé."""
    return sorted((line, function,
                   called_name(node) if isinstance(node, ast.Call) else 'corps de réponse écrit')
                  for line, function, node in _sites(tree, is_download_site))


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


#: Écritures de FICHIER, par le module qui les fait (`shutil.copy2(…)`, `torch.save(…)`) ou par la
#: méthode d'un chemin (`….write_text(…)`) — `copy`/`move` nus restent dehors : `dict.copy()`.
WRITE_MODULE_CALLS = {('shutil', 'copy'), ('shutil', 'copy2'), ('shutil', 'copyfile'),
                      ('shutil', 'copytree'), ('shutil', 'move'), ('torch', 'save')}
WRITE_METHOD_CALLS = {'write_text', 'write_bytes', 'copy2', 'copyfile', 'copytree'}


def is_write_site(node) -> bool:
    """Le nœud ÉCRIT-il un fichier ? Une copie ou un déplacement (`shutil`), une sauvegarde
    (`torch.save`), une écriture de chemin, un `open` en écriture. Le dossier des poids est en
    LECTURE SEULE pour un backend (2026-11-10, ACE-Step : `_sync_model_code_if_needed` y recopie le
    code du modèle, sans rien télécharger)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in WRITE_METHOD_CALLS or (
            isinstance(func.value, ast.Name) and (func.value.id, func.attr) in WRITE_MODULE_CALLS)
    if isinstance(func, ast.Name) and func.id in WRITE_METHOD_CALLS:
        return True                                   # `from shutil import copy2`
    if isinstance(func, ast.Name) and func.id == 'open':
        mode = node.args[1] if len(node.args) > 1 else next(
            (k.value for k in node.keywords if k.arg == 'mode'), None)
        return isinstance(mode, ast.Constant) and isinstance(mode.value, str) \
            and any(c in mode.value for c in 'wax')
    return False


def functions_reaching_download(root) -> dict:
    """`{fonction: 'fichier:ligne'}` — les fonctions du code sous `root` qui TÉLÉCHARGENT, ou qui
    appellent (de proche en proche) une fonction qui télécharge. Par le NOM des fonctions
    appelées, sans résolution d'import : une lecture, pas une exécution — un homonyme est compté,
    un excès qui ne cache rien. Un backend écrit sur ce moteur n'en appelle aucune : les poids
    sont déjà installés par la route (2026-11-08, ACE-Step : `initialize_service` y mène par
    `_ensure_models_present`). Mémoïsé par dossier, comme les noms du code d'un clone
    (`vendor_installer._code_names`) ; une installation vendorisée l'oublie."""
    return dict(_reaching(str(root), 'download'))


def functions_reaching_write(root) -> dict:
    """`{fonction: 'fichier:ligne'}` — les fonctions du code sous `root` qui ÉCRIVENT un fichier
    (`is_write_site`), ou qui y mènent ; même lecture que `functions_reaching_download`."""
    return dict(_reaching(str(root), 'write'))


def entry_loaders(root, entry: str) -> dict:
    """Ce qu'une ENTRÉE du code sous `root` appelle directement, parmi les fonctions de ce code :
    `{'loaders': {…}, 'downloads': {…}, 'writes': {…}}`, chacune `{fonction: 'fichier:ligne'}`.
    `loaders` : celles qui ne téléchargent ni n'écrivent — ce qu'un backend appelle À LA PLACE de
    l'entrée, sur les chemins installés. Né le 2026-11-10 : le refus de `initialize_service`
    (ACE-Step) disait ce qu'il ne fallait pas appeler, jamais quoi appeler, et deux modèles
    successifs ont rappelé l'entrée. Les appels lus sont ceux qui se RÉSOLVENT vers le code
    (`_graph`, appels résolus) : `os.environ.get` n'est pas la méthode `get` d'un module du clone.
    `owners` : la CLASSE de l'entrée et de ceux de ses appelés qui sont des méthodes — un modèle
    qui ne lisait que `fichier:ligne` a appelé `_resolve_initialize_device` comme une fonction du
    module, alors que c'est une méthode de l'objet qui porte l'entrée (2026-11-10)."""
    defined, _, resolved, _ = _graph(str(root))
    owners = dict(_owners(str(root)))
    downloads, writes = functions_reaching_download(root), functions_reaching_write(root)
    callees = sorted(resolved.get(entry, set()) & set(defined) - {entry})
    return {'loaders': {n: defined[n] for n in callees if n not in downloads and n not in writes},
            'downloads': {n: defined[n] for n in callees if n in downloads},
            'writes': {n: defined[n] for n in callees if n in writes and n not in downloads},
            'owners': {n: owners[n] for n in [entry, *callees] if n in owners},
            'heirs': _heirs(str(root), owners.get(entry, ''))}


def _heirs(root: str, cls: str) -> dict:
    """`{classe: 'fichier:ligne'}` des classes du code sous `root` qui héritent de `cls` (une
    classe mixin n'est jamais instanciée : c'est son héritière qui porte ses méthodes)."""
    if not cls:
        return {}
    classes = {}
    for rel, tree in _graph(root)[3]:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.setdefault(node.name, (f'{rel}:{node.lineno}', {
                    b.id if isinstance(b, ast.Name) else getattr(b, 'attr', '')
                    for b in node.bases}))
    # De proche en proche : un mixin hérité par un mixin (ACE-Step : InitServiceOrchestratorMixin
    # → InitServiceMixin → AceStepHandler, la classe qu'on instancie).
    heirs, grown = {}, True
    while grown:
        added = {name: where for name, (where, bases) in classes.items()
                 if name not in heirs and bases & ({cls} | set(heirs))}
        heirs.update(added)
        grown = bool(added)
    return heirs


def forget_readings() -> None:
    """Oublie les lectures mémoïsées — le code d'un clone a changé (installation vendorisée)."""
    _graph.cache_clear()
    _reaching.cache_clear()
    _owners.cache_clear()


@functools.lru_cache(maxsize=32)
def _owners(root: str) -> tuple:
    """`((méthode, classe), …)` des méthodes du code sous `root` — la première classe qui définit
    ce nom, comme `_graph` garde la première définition."""
    owners = {}
    for _, tree in _graph(root)[3]:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        owners.setdefault(item.name, node.name)
    return tuple(owners.items())


#: Noms qu'un appel NU désigne d'abord dans Python lui-même (`str(…)`, `open(…)`) : un homonyme du
#: clone (une méthode `str` d'un analyseur) n'est pas ce qu'ils appellent.
_BUILTIN_NAMES = frozenset(dir(builtins))


def code_packages(root, modules: bool = True) -> set:
    """Noms de premier niveau importables du code sous `root` (racine ou `src/`) : ses paquets,
    et ses modules si `modules` — ce qu'un `import` désigne dans le clone plutôt que dans le venv.
    La lecture que font aussi le contrôle des paquets requis d'un backend
    (`backend_proposals._vendored_top_packages`) et la matière du rôle (`run_backend`)."""
    names, root = set(), Path(root)
    for base in (root, root / 'src'):
        if base.is_dir():
            names |= {p.parent.name for p in base.glob('*/__init__.py')}
            if modules:
                names |= {p.stem for p in base.glob('*.py')}
    return names


def _code_aliases(tree, packages: set) -> set:
    """Noms qu'un module lie à du code du clone par ses imports (relatifs, ou d'un paquet du
    clone) : un appel `alias.f()` se résout vers le clone."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split('.')[0] in packages:
                    aliases.add(a.asname or a.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or '').split('.')[0] in packages:
                aliases |= {a.asname or a.name for a in node.names}
    return aliases


def _resolved_name(call: ast.Call, aliases: set) -> str:
    """Le nom appelé si l'appel se RÉSOUT vers le code du clone, '' sinon : un nom nu (hors
    noms natifs de Python), une méthode de `self`/`cls`/`super()`, une fonction d'un module
    importé du clone."""
    func = call.func
    if isinstance(func, ast.Name):
        return '' if func.id in _BUILTIN_NAMES and func.id not in aliases else func.id
    if not isinstance(func, ast.Attribute):
        return ''
    base = func.value
    while isinstance(base, ast.Attribute):
        base = base.value
    if isinstance(base, ast.Name) and (base.id in ('self', 'cls') or base.id in aliases):
        return func.attr
    if isinstance(base, ast.Call) and getattr(base.func, 'id', '') == 'super':
        return func.attr
    return ''


@functools.lru_cache(maxsize=32)
def _graph(root: str) -> tuple:
    """`(définies {nom: 'fichier:ligne'}, appels {nom: {noms}}, appels résolus {nom: {noms}},
    modules)` du code sous `root`. Les APPELS sont lus par le nom seul — la lecture des
    téléchargements, dont l'excès ne fait que refuser davantage. Les appels RÉSOLUS ne gardent que
    ceux qui désignent le clone (`_resolved_name`) — la lecture des écritures et des chargeurs,
    où un homonyme de bibliothèque cacherait tout : par le nom seul, `torch.load` menait à une
    fonction `load` du clone qui chiffre un secret, et 307 fonctions d'ACE-Step « écrivaient »
    (mesuré le 2026-11-10)."""
    modules = _modules(root, ('tests',))
    packages = code_packages(root)
    defined, calls, resolved = {}, {}, {}
    for rel, tree in modules:
        aliases = _code_aliases(tree, packages)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))                     and not node.name.startswith('test_'):
                defined.setdefault(node.name, f'{rel}:{node.lineno}')
                inner = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
                calls.setdefault(node.name, set()).update(called_name(n) for n in inner)
                resolved.setdefault(node.name, set()).update(
                    filter(None, (_resolved_name(n, aliases) for n in inner)))
    return defined, calls, resolved, modules


@functools.lru_cache(maxsize=64)
def _reaching(root: str, kind: str) -> tuple:
    defined, calls, resolved, modules = _graph(root)
    is_site, graph = ((is_download_site, calls) if kind == 'download'
                      else (is_write_site, resolved))
    reaching = {function for _, tree in modules for _, function, _ in _sites(tree, is_site)
                if function in defined}
    grown = True
    while grown:
        added = {name for name, called in graph.items() if name not in reaching and called & reaching}
        reaching |= added
        grown = bool(added)
    return tuple((name, defined[name]) for name in sorted(reaching))
