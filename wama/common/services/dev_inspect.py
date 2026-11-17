"""
Outils d'INSPECTION réservés aux administrateurs — lire un log, interroger la base, lire le code,
sans déléguer à Claude Code (lent, coûteux) pour un simple diagnostic.

Ils s'enregistrent dans `dev_tools.DEV_TOOLS` et suivent son contrat : une fonction `(user, …)`
qui rend un dict, `DevToolError` pour un refus lisible. Ils arrivent à l'assistant web par le canal
existant (`mcp_client.dev_tools_for` → surface MCP « wama-dev »), jamais chargés dans le process de
production (ROADMAP §16).

DROITS : `accounts.permissions.is_admin_tier`, vérifié ICI dans le corps de chaque outil
(`@admin_only`) ET par `dev_tools.ADMIN_ONLY` à l'annonce et à l'appel. Un développeur non
administrateur ne les voit pas et ne peut pas les appeler.

LECTURE SEULE : aucune écriture, aucun SQL libre, aucune jointure — sauf `dev_run_operation`, qui
lance UNE opération d'exploitation déclarée (`common/operations.py` : des contrôles, et un test
ciblé par le lanceur de WAMA), en tâche de fond. Chaque appel est journalisé
(qui, quoi) — les messages de l'assistant contiennent les conversations d'autres comptes.
"""
from __future__ import annotations

import fnmatch
import functools
import logging
import os
import re
from pathlib import Path

from django.apps import apps

logger = logging.getLogger(__name__)

MAX_CHARS = 50_000
MAX_ROWS = 50
MAX_CELL_CHARS = 500
MAX_LIST = 100
#: Fenêtre lue en fin de log (octets) : un log pèse parfois des dizaines de Mo.
LOG_WINDOW_BYTES = 4 * 1024 * 1024
MAX_CODE_BYTES = 1024 * 1024
DEFAULT_CODE_LINES = 400
MAX_MATCHES = 100
MAX_MATCH_CHARS = 240

#: Familles d'apps dont les tables sont interrogeables : le projet WAMA, pas Django.
ALLOWED_APP_PREFIXES = ('wama', 'wama_lab', 'wama_data')
#: Modèles WAMA qui portent des clés ou des jetons : jamais lus, même colonnes filtrées.
DENIED_MODELS = {'accounts.userprofile', 'accounts.providerkey', 'accounts.userapikey',
                 'accounts.instanceapikey', 'common.calendarfeed'}
#: Une colonne dont le nom contient l'un de ces mots est retirée du retour ET refusée en filtre
#: (sinon `champ__startswith` devient un oracle de fuite caractère par caractère).
SENSITIVE_COLUMN = re.compile(r'password|token|secret|key|hash', re.I)
FILTER_OPERATORS = ('exact', 'gt', 'gte', 'lt', 'lte', 'contains', 'icontains', 'startswith',
                    'in', 'isnull')

LOG_NAME = re.compile(r'\.log(\.\d+)?$')
LOG_SECRET = re.compile(r'(Bearer\s+|token=|password=|api_key=)\S+', re.I)
DENIED_PARTS = {'.git', 'venv_linux', 'venv_win', 'AI-models', 'media', 'staticfiles', 'logs',
                '__pycache__', 'node_modules'}
DENIED_SUFFIXES = {'.pem', '.key', '.sqlite3'}


def admin_only(fn):
    """La garde dans le CORPS de l'outil : aucune retouche du registre ne la lève, et un appel
    direct (test, autre module) reste gardé."""
    @functools.wraps(fn)
    def guarded(user, *args, **kwargs):
        from wama.accounts.permissions import is_admin_tier
        if not is_admin_tier(user):
            return {'error': 'forbidden', 'detail': "Outil réservé aux administrateurs."}
        logger.info("[dev_inspect] %s par %s args=%s", fn.__name__, getattr(user, 'username', '?'),
                    {k: v for k, v in kwargs.items()} or args)
        return fn(user, *args, **kwargs)
    return guarded


def _clip(text: str) -> str:
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n[… tronqué]"


def _inside(root: Path, rel: str) -> Path:
    """`rel` résolu sous `root` — `..` ET liens symboliques résolus AVANT le test."""
    root = root.resolve()
    p = (root / (rel or '.')).resolve()
    if p != root and root not in p.parents:
        raise DevToolError("chemin hors périmètre")
    return p


def _clamp(value, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


#: Ressemblance minimale (`difflib`) d'un nom deviné avec un nom réel pour que le refus le cite.
NEAR_CUTOFF = 0.4
NEAR_LIMIT = 8


def _unknown(what: str, given: str, names, way: str, core=lambda name: name) -> DevToolError:
    """LE refus d'un nom deviné, pour tout ce que ces outils lisent par nom (table, colonne,
    journal) : il cite les noms RÉELS proches et dit la voie qui les liste. Proches : ceux dont le
    CŒUR contient le cœur deviné (`wama.Model` → `model_manager.AIModel`, `gunicorn.log` →
    `gunicorn-error.log`), puis les ressemblants. Une seule lecture depuis le 2026-11-17 : les
    tables et les journaux en avaient chacun une, à seuils différents."""
    import difflib
    names = list(names)
    wanted = core(given).lower()
    near = [n for n in names if wanted and wanted in core(n).lower()]
    by_lower = {n.lower(): n for n in names}
    near += [by_lower[c] for c in difflib.get_close_matches(given.lower(), list(by_lower),
                                                            n=NEAR_LIMIT, cutoff=NEAR_CUTOFF)
             if by_lower[c] not in near]
    return DevToolError(f"{what} : {given!r} — "
                        + (f"proches : {', '.join(near[:NEAR_LIMIT])} ; " if near else '') + way)


# ── Base de données ──────────────────────────────────────────────────────────────────────────

def _queryable(model) -> bool:
    """Une table que les outils de base lisent : du projet WAMA, hors comptes et clés."""
    return (model.__module__.split('.')[0] in ALLOWED_APP_PREFIXES
            and model._meta.label_lower not in DENIED_MODELS)


#: Ce qui suit un refus de nom de table : la voie, la même que celle des journaux (lister).
TABLES_HINT = "dev_db_schema sans `table` liste celles qu'on peut lire"


def _model_for(table: str):
    label = (table or '').strip()
    # Le refus dit la VOIE (2026-11-17, relevé de `tool_usage` : 3 appels sur 3 en échec le
    # 30/10, `wama.Model`, `wama.ModelItem`, `django_migrations` — puis le diagnostic abandonné).
    if label.count('.') != 1:
        raise DevToolError(f"table attendue sous la forme « app.Model » : {TABLES_HINT}")
    try:
        model = apps.get_model(label)
    except LookupError:
        raise _unknown('table inconnue', label,
                       sorted(m._meta.label for m in apps.get_models() if _queryable(m)),
                       TABLES_HINT, core=lambda name: name.rsplit('.', 1)[-1])
    if not _queryable(model):
        raise DevToolError(f"table non interrogeable : {label!r}")
    return model


def _local_fields(model) -> dict:
    return {f.name: f for f in model._meta.concrete_fields}


def _cell(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_CELL_CHARS]


def _parse_filter(model, text: str) -> dict:
    """`champ__op="valeur", autre=3` → kwargs ORM. Jamais d'`eval`, jamais de traversée de relation."""
    fields = _local_fields(model)
    kwargs = {}
    for m in re.finditer(r'\s*(\w+)\s*=\s*("[^"]*"|[^,]*?)\s*(?:,|$)', text or ''):
        key, raw = m.group(1), m.group(2).strip()
        if not key:
            continue
        parts = key.split('__')
        op = 'exact'
        if len(parts) > 1 and parts[-1] in FILTER_OPERATORS:
            op = parts.pop()
        if len(parts) != 1 or parts[0] not in fields:
            raise DevToolError(f"filtre refusé : {key!r} (champ local du modèle seulement)")
        if SENSITIVE_COLUMN.search(parts[0]):
            raise DevToolError(f"filtre refusé : colonne sensible {parts[0]!r}")
        value = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw
        if op == 'in':
            value = [v for v in value.split('|') if v != '']
        elif op == 'isnull':
            value = value.lower() in ('1', 'true', 'oui')
        kwargs[f'{parts[0]}__{op}'] = value
    if (text or '').strip() and not kwargs:
        raise DevToolError('filtre illisible : attendu champ__opérateur="valeur", séparés par des virgules')
    return kwargs


@admin_only
def dev_db_query(user, table: str, filter: str = '', fields: str = '', limit: int = 20,
                 order_by: str = '') -> dict:
    """Lit des lignes d'une table du projet WAMA (SELECT seul, 50 lignes au plus, pas de SQL libre, pas de jointure) — ADMIN.

    table : « app.Model » (wama*, hors comptes et clés ; dev_db_schema sans table les liste). filter : champ__opérateur="valeur"
    séparés par des virgules (opérateurs exact, gt, gte, lt, lte, contains, icontains, startswith,
    in avec | entre les valeurs, isnull) ; champs locaux seulement. fields : noms séparés par des
    virgules (vide = toutes les colonnes). order_by : un champ local, préfixe - pour décroissant.
    Les colonnes password/token/secret/key/hash ne sont jamais rendues.
    """
    model = _model_for(table)
    columns = _local_fields(model)
    wanted = [f.strip() for f in (fields or '').split(',') if f.strip()]
    for name in wanted:
        if name not in columns:
            raise _unknown('colonne inconnue', name, columns,
                           f"dev_db_schema table={table} les donne")
    shown = [n for n in (wanted or list(columns)) if not SENSITIVE_COLUMN.search(n)]
    if not shown:
        raise DevToolError("aucune colonne lisible")
    qs = model._default_manager.filter(**_parse_filter(model, filter))
    if order_by:
        key = order_by.lstrip('-')
        if key not in columns or SENSITIVE_COLUMN.search(key):
            raise DevToolError(f"tri refusé : {order_by!r}")
        qs = qs.order_by(order_by)
    rows = [{k: _cell(v) for k, v in row.items()}
            for row in qs.values(*shown)[:_clamp(limit, 1, MAX_ROWS, 20)]]
    return {'table': table, 'count': len(rows), 'rows': rows}


@admin_only
def dev_db_schema(user, table: str = '') -> dict:
    """Colonnes d'une table du projet WAMA (nom, type, nullité, défaut, relation), ou LISTE les tables quand `table` est vide — mêmes tables que dev_db_query — ADMIN.

    table : « app.Model » ; vide = la liste des tables qu'on peut lire (libellé, nom lisible) —
    ne jamais deviner un nom.
    """
    if not (table or '').strip():
        return {'tables': sorted(({'table': m._meta.label, 'name': str(m._meta.verbose_name)}
                                  for m in apps.get_models() if _queryable(m)),
                                 key=lambda row: row['table'])}
    model = _model_for(table)
    columns = []
    for f in model._meta.concrete_fields:
        default = f.default if f.has_default() else None
        columns.append({
            'name': f.name, 'type': f.get_internal_type(), 'null': f.null,
            'default': None if default is None or callable(default) else _cell(default),
            'relation': f.related_model._meta.label if f.is_relation and f.related_model else None,
            'redacted': bool(SENSITIVE_COLUMN.search(f.name)),
        })
    return {'table': table, 'columns': columns}


# ── Fichiers ─────────────────────────────────────────────────────────────────────────────────

def _journals() -> list:
    """Les journaux de `logs/` (premier niveau), le plus récemment écrit d'abord."""
    from datetime import datetime
    root = base_dir() / 'logs'
    found = [p for p in root.iterdir() if p.is_file() and LOG_NAME.search(p.name)] \
        if root.is_dir() else []
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{'name': p.name, 'bytes': p.stat().st_size,
             'modified': datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec='seconds')}
            for p in found[:MAX_LIST]]


@admin_only
def dev_read_log(user, path: str = '', grep: str = '', lines: int = 100, start_line: int = 0,
                 end_line: int = 0) -> dict:
    """Lit la fin d'un journal de logs/, ou LISTE les journaux quand `path` est vide — ADMIN. Premier geste d'un diagnostic : lister, puis lire le journal le plus récemment écrit (erreurs du serveur web : gunicorn-error.log et django-errors.log ; tâches : celery-*.log).

    path : relatif à logs/ ; vide = la liste (nom, taille, dernière écriture), ne jamais deviner
    un nom. lines : les N dernières lignes (1..2000) ; start_line/end_line (1-based, dans la
    fenêtre lue) les remplacent. grep : sous-chaîne qui filtre les lignes retenues. Les jetons et
    mots de passe sont masqués.
    """
    if not (path or '').strip():
        return {'journals': _journals()}
    p = _inside(base_dir() / 'logs', path)
    if not p.is_file() or not LOG_NAME.search(p.name):
        # Le refus dit ce qui EXISTE (2026-11-12 : l'assistant a demandé « gunicorn.log », que
        # l'aide de cet outil citait en exemple et qui n'existe pas — il a renoncé au diagnostic).
        raise _unknown('journal introuvable dans logs/', Path(path).name,
                       [j['name'] for j in _journals()], "dev_read_log sans `path` les liste",
                       core=lambda name: name.split('.')[0])
    size = p.stat().st_size
    with open(p, 'rb') as fh:
        if size > LOG_WINDOW_BYTES:
            fh.seek(size - LOG_WINDOW_BYTES)
        text = fh.read().decode('utf-8', errors='replace')
    all_lines = text.splitlines()
    if size > LOG_WINDOW_BYTES:
        all_lines = all_lines[1:]            # première ligne coupée au milieu
    total = len(all_lines)
    if start_line or end_line:
        start = max(int(start_line or 1), 1)
        end = int(end_line) if end_line else total
        picked = all_lines[start - 1:end]
    else:
        picked = all_lines[-_clamp(lines, 1, 2000, 100):]
    if grep:
        picked = [ln for ln in picked if grep in ln]
    out = LOG_SECRET.sub(lambda m: m.group(1) + '***', _clip('\n'.join(picked)))
    return {'path': str(p.relative_to(base_dir().resolve())), 'text': out, 'total_lines': total,
            'truncated': size > LOG_WINDOW_BYTES}


def _refused_code_path(rel: Path) -> bool:
    return any(part in DENIED_PARTS or part.startswith('.env') for part in rel.parts) \
        or rel.suffix in DENIED_SUFFIXES


def _code_path(path: str) -> Path:
    root = base_dir().resolve()
    p = _inside(root, path)
    if _refused_code_path(p.relative_to(root)):
        raise DevToolError(f"chemin refusé : {path!r}")
    return p


@admin_only
def dev_read_code(user, path: str, start_line: int = 0, end_line: int = 0) -> dict:
    """Lit un fichier texte du dépôt, lignes numérotées (hors .env, .git, venvs, modèles, médias, logs, clés) — ADMIN.

    path : relatif à la racine du dépôt. start_line/end_line : tranche 1-based (vide = 400
    premières lignes).
    """
    p = _code_path(path)
    if not p.is_file():
        raise DevToolError(f"fichier introuvable : {path!r}")
    if p.stat().st_size > MAX_CODE_BYTES:
        raise DevToolError("fichier trop gros — demande une tranche d'un fichier plus petit")
    raw = p.read_bytes()
    if b'\x00' in raw[:4096]:
        raise DevToolError("fichier binaire refusé")
    all_lines = raw.decode('utf-8', errors='replace').splitlines()
    start = max(int(start_line or 1), 1)
    end = int(end_line) if end_line else start + DEFAULT_CODE_LINES - 1
    body = '\n'.join(f"{n:>5}\t{ln}" for n, ln in enumerate(all_lines[start - 1:end], start))
    return {'path': str(p.relative_to(base_dir().resolve())), 'total_lines': len(all_lines),
            'text': _clip(body)}


def _file_pattern(pattern: str, default: str) -> str:
    """Le motif de fichier d'un outil de code, refusé s'il sort du dossier de départ."""
    pattern = (pattern or '').strip() or default
    if '..' in pattern or pattern.startswith('/'):
        raise DevToolError("motif refusé : il se lit depuis le dossier `path`, sans « .. » ni « / » "
                           "de tête")
    return pattern


def _pattern_hit(name: str, rel: str, pattern: str) -> bool:
    """LA lecture d'un motif de fichier des outils de code (lister, chercher) : sur le NOM
    (« *.py »), ou, dès qu'il porte un « / », sur le chemin relatif au dossier de départ
    (« tests/*.py ») — un « **/ » de tête valant aussi au premier niveau (« **/tasks.py »).

    POURQUOI UNE SEULE (2026-11-17, relevé de `tool_usage`) : `dev_list_code` lisait déjà
    « **/tasks.py », `dev_search_code` refusait tout motif à « / » — 4 de ses 7 appels réels
    (`**/*.py`, `composer/**/*.py`), la forme qu'un modèle écrit comme il l'écrit à ripgrep."""
    if '/' not in pattern:
        return fnmatch.fnmatch(name, pattern)
    if fnmatch.fnmatch(rel, pattern):
        return True
    return pattern.startswith('**/') and _pattern_hit(name, rel, pattern[3:])


def _code_files(base: Path, recursive: bool = True):
    """Les fichiers LISIBLES sous `base`, triés : `(chemin, chemin relatif au dépôt)` — LE parcours
    des outils de code (lister, chercher), avec les refus de `_refused_code_path` appliqués aux
    dossiers comme aux fichiers. `recursive=False` : le seul dossier `base`."""
    root = base_dir().resolve()
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames
                             if not _refused_code_path(Path(dirpath, d).relative_to(root)))
        for name in sorted(filenames):
            full = Path(dirpath, name)
            rel = full.relative_to(root)
            if not _refused_code_path(rel):
                yield full, rel
        if not recursive:
            break


@admin_only
def dev_list_code(user, path: str = '.', pattern: str = '*', limit: int = 100) -> dict:
    """Liste les fichiers d'un dossier du dépôt (mêmes refus que dev_read_code) — ADMIN.

    pattern : glob sur le nom (« *.py »), ou sur le chemin relatif au dossier dès qu'il porte un
    « / » (« **/tasks.py » descend partout, « tests/*.py »). limit : 1..100.
    """
    pattern = _file_pattern(pattern, '*')
    base = _code_path(path)
    if not base.is_dir():
        raise DevToolError(f"dossier introuvable : {path!r}")
    cap = _clamp(limit, 1, MAX_LIST, MAX_LIST)
    found = []
    for full, rel_root in _code_files(base, recursive='/' in pattern):
        if _pattern_hit(full.name, full.relative_to(base).as_posix(), pattern):
            found.append(str(rel_root))
            if len(found) >= cap:
                return {'paths': found, 'truncated': True}
    return {'paths': found, 'truncated': False}


@admin_only
def dev_search_code(user, pattern: str, path: str = '.', glob: str = '*.py', regex: bool = False,
                    limit: int = 50) -> dict:
    """Cherche un texte dans les fichiers du dépôt et rend « chemin:ligne: texte » (mêmes refus que dev_read_code) — ADMIN. Pour trouver d'où vient un message d'erreur, où une fonction est définie ou appelée, avant de lire le fichier avec dev_read_code.

    pattern : le texte cherché (sous-chaîne, casse respectée) ; regex=true le lit comme une
    expression régulière. path : dossier de départ, relatif au dépôt. glob : motif sur le NOM des
    fichiers (« *.py », « *.html », « *.js », « * »), ou, avec un « / », sur leur chemin relatif à
    `path` (« **/*.py », « tests/*.py ») — le même que dev_list_code. limit : 1..100 correspondances.
    """
    if not (pattern or '').strip():
        raise DevToolError("« pattern » vide : donner le texte à chercher")
    glob = _file_pattern(glob, '*')
    try:
        matcher = re.compile(pattern if regex else re.escape(pattern))
    except re.error as e:
        raise DevToolError(f"expression régulière illisible : {e}")
    root = base_dir().resolve()
    base = _code_path(path)
    if not base.is_dir():
        raise DevToolError(f"dossier introuvable : {path!r}")
    cap = _clamp(limit, 1, MAX_MATCHES, 50)
    matches, scanned = [], 0
    for full, rel in _code_files(base):
            if not _pattern_hit(full.name, full.relative_to(base).as_posix(), glob) \
                    or full.is_symlink():
                continue
            try:
                if full.stat().st_size > MAX_CODE_BYTES:
                    continue
                raw = full.read_bytes()
            except OSError:
                continue
            if b'\x00' in raw[:4096]:
                continue
            scanned += 1
            for n, line in enumerate(raw.decode('utf-8', errors='replace').splitlines(), 1):
                if matcher.search(line):
                    matches.append(f"{rel.as_posix()}:{n}: {line.strip()[:MAX_MATCH_CHARS]}")
                    if len(matches) >= cap:
                        return {'matches': matches, 'files_scanned': scanned, 'truncated': True}
    out = {'matches': matches, 'files_scanned': scanned, 'truncated': False}
    if not scanned:
        # Aucune correspondance parce qu'aucun FICHIER n'a été lu se dit : sans cela, « rien
        # trouvé » se lirait « le texte n'existe pas » (`composer/**/*.py` depuis la racine).
        out['note'] = (f"aucun fichier lisible ne correspond à glob={glob!r} sous path={path!r} "
                       "(le motif à « / » se lit depuis path)")
    return out


#: Préfixe du nom de tâche d'une opération d'exploitation (`operation:check_docs`) : ce par quoi la
#: page « Exploitation » retrouve les siennes parmi les tâches de développement.
OPERATION_TOOL = 'operation:'


@admin_only
def dev_list_operations(user) -> dict:
    """Les OPÉRATIONS d'exploitation qu'on peut lancer (contrôles de la doc, des manifestes, de la conformité, tests ciblés) : leur clé, ce qu'elles font, l'argument qu'elles prennent — ADMIN. À lire avant dev_run_operation."""
    from wama.common.operations import operations
    return {'operations': operations()}


@admin_only
def dev_run_operation(user, operation: str, argument: str = '') -> dict:
    """Lance UNE opération d'exploitation de WAMA en TÂCHE DE FOND (manage.py, arguments figés) — ADMIN : check_docs, doc_facts, manifest_export, manifest_roundtrip, conformity, identifier_language, ou tests (un module ou une classe de tests, jamais la suite entière). La fin du journal donne le verdict ; la même opération se lance depuis la page « Exploitation ».

    operation : sa clé (dev_list_operations les décrit). argument : pour `tests` seulement, le
    chemin pointé du module ou de la classe (wama.common.tests.tests_user_settings).
    """
    import sys
    from wama.common.operations import command
    try:
        argv = command((operation or '').strip(), argument)
    except ValueError as refusal:
        raise DevToolError(str(refusal))
    return start_job(user, OPERATION_TOOL + operation.strip(),
                     [sys.executable, str(base_dir() / 'manage.py'), *argv])


# En PIED de module : `dev_tools` importe ce module pour remplir DEV_TOOLS, et ces deux noms ne
# servent qu'à l'appel — l'ordre d'import (l'un ou l'autre en premier) est donc indifférent.
from wama.common.services.dev_tools import DevToolError, base_dir, start_job  # noqa: E402
