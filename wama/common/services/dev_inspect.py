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

LECTURE SEULE : aucune écriture, aucun SQL libre, aucune jointure. Chaque appel est journalisé
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


# ── Base de données ──────────────────────────────────────────────────────────────────────────

def _model_for(table: str):
    label = (table or '').strip()
    if label.count('.') != 1:
        raise DevToolError("table attendue sous la forme « app.Model »")
    try:
        model = apps.get_model(label)
    except LookupError:
        raise DevToolError(f"table inconnue : {label!r}")
    if model.__module__.split('.')[0] not in ALLOWED_APP_PREFIXES or label.lower() in DENIED_MODELS:
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

    table : « app.Model » (wama*, hors comptes et clés). filter : champ__opérateur="valeur"
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
            raise DevToolError(f"colonne inconnue : {name!r}")
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
def dev_db_schema(user, table: str) -> dict:
    """Colonnes d'une table du projet WAMA (nom, type, nullité, défaut, relation) — mêmes tables que dev_db_query — ADMIN."""
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

@admin_only
def dev_read_log(user, path: str, grep: str = '', lines: int = 100, start_line: int = 0,
                 end_line: int = 0) -> dict:
    """Lit la fin d'un journal de logs/ (fichiers .log et rotations .log.N) — ADMIN.

    path : relatif à logs/ (gunicorn.log…). lines : les N dernières lignes (1..2000) ;
    start_line/end_line (1-based, dans la fenêtre lue) les remplacent. grep : sous-chaîne qui
    filtre les lignes retenues. Les jetons et mots de passe sont masqués.
    """
    p = _inside(base_dir() / 'logs', path)
    if not p.is_file() or not LOG_NAME.search(p.name):
        raise DevToolError(f"journal introuvable dans logs/ : {path!r}")
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


@admin_only
def dev_list_code(user, path: str = '.', pattern: str = '*', limit: int = 100) -> dict:
    """Liste les fichiers d'un dossier du dépôt (mêmes refus que dev_read_code) — ADMIN.

    pattern : glob sur le nom (« *.py »), ou sur le chemin relatif au dossier avec ** pour
    descendre (« **/tasks.py »). limit : 1..100.
    """
    if '..' in (pattern or '') or (pattern or '').startswith('/'):
        raise DevToolError("motif refusé")
    root = base_dir().resolve()
    base = _code_path(path)
    if not base.is_dir():
        raise DevToolError(f"dossier introuvable : {path!r}")
    recursive = '**' in pattern
    cap = _clamp(limit, 1, MAX_LIST, MAX_LIST)
    found = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames
                             if not _refused_code_path(Path(dirpath, d).relative_to(root)))
        for name in sorted(filenames):
            full = Path(dirpath, name)
            rel_root = full.relative_to(root)
            rel_base = str(full.relative_to(base))
            if _refused_code_path(rel_root):
                continue
            if recursive:
                tail = pattern.removeprefix('**/')       # « **/tasks.py » vaut aussi à la racine
                hit = fnmatch.fnmatch(rel_base, pattern) or ('/' not in tail
                                                             and fnmatch.fnmatch(name, tail))
            else:
                hit = fnmatch.fnmatch(name, pattern)
            if hit:
                found.append(str(rel_root))
                if len(found) >= cap:
                    return {'paths': found, 'truncated': True}
        if not recursive:
            break
    return {'paths': found, 'truncated': False}


# En PIED de module : `dev_tools` importe ce module pour remplir DEV_TOOLS, et ces deux noms ne
# servent qu'à l'appel — l'ordre d'import (l'un ou l'autre en premier) est donc indifférent.
from wama.common.services.dev_tools import DevToolError, base_dir  # noqa: E402
