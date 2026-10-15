#!/usr/bin/env python3
"""
Mesure des lenteurs WAMA EN PROCESSUS, sur la base réelle, pour un compte — skill `/audit-lenteurs`.

Ce qui est mesuré : les PAGES déclarées (apps du catalogue, surfaces, pages de compte) et, avec
`--polled`, les adresses sans argument INTERROGÉES EN CONTINU (progression, statut, console,
pied de page) — mesuré le 2026-10-03 : c'est là que se cachait le pire.
Pour chacune : deux passes à chaud (la 1ʳᵉ après relance réchauffe les caches par worker), puis
une passe profilée → durée, nombre de requêtes SQL, requêtes RÉPÉTÉES (signal N+1), et les
fonctions du DÉPÔT les plus coûteuses (`tottime`), avec leur tranche `chemin:début-fin` — la forme
qu'attend `--files` du rôle `task` de wama-dev-ai.

LECTURE SEULE : chaque requête tourne dans une transaction ANNULÉE (rien n'est écrit en base, aucun
`on_commit` ne part). Seuls des GET. Ce qui sort de la base (fil de fond, fichier) n'est pas annulé :
ne pas ajouter d'adresse qui déclenche un traitement.

Usage (WSL, racine du dépôt) :
    venv_linux/bin/python .claude/skills/audit-lenteurs/measure_pages.py --user <login> [--polled]
        [--only transcriber,imager] [--slow 0.3] [--json logs/perf_audit.json]
"""
import argparse
import ast
import cProfile
import json
import os
import pstats
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402
django.setup()

from django.db import connection, transaction  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.urls import NoReverseMatch, reverse  # noqa: E402

#: Noms d'adresses interrogées en boucle par les pages (`WamaApp.Poller`).
POLLED_NAME = re.compile(r'(progress|status|console|stats|poll|notifications|queue_state)', re.I)
#: Racines du dépôt dont on rapporte les fonctions chaudes (le reste = Django, librairies).
REPO_ROOTS = ('wama/', 'wama_lab/', 'wama_data/')
TOP_FUNCTIONS = 8
REPEATED_MIN = 5


def page_urls():
    """(étiquette, adresse) des pages DÉCLARÉES — la source est le registre, pas une liste écrite ici."""
    from wama.common.app_registry import APP_CATALOG, account_pages, surfaces
    seen, out = set(), []
    names = [(app, (spec or {}).get('url_name')) for app, spec in APP_CATALOG.items()
             if not (spec or {}).get('sandbox')]
    names += [(s.get('app_id') or s.get('label'), s.get('url_name')) for s in surfaces()]
    names += [(p.get('key'), p.get('url_name')) for p in account_pages()]
    for label, name in names:
        if not name:
            continue
        try:
            url = reverse(name)
        except NoReverseMatch:
            continue
        if url not in seen:
            seen.add(url)
            out.append((label, url))
    return out


def polled_urls():
    from wama.common.tests.tests_endpoints import _parameterless_routes
    out = []
    for namespace, name in _parameterless_routes():
        if POLLED_NAME.search(name):
            try:
                out.append((f'{namespace}:{name}', reverse(f'{namespace}:{name}')))
            except NoReverseMatch:
                continue
    return out


def _function_range(path: str, first_line: int) -> str:
    """`chemin:début-fin` de la fonction qui commence à `first_line` (AST), sinon 60 lignes."""
    try:
        tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    node.lineno == first_line:
                return f'{path}:{first_line}-{node.end_lineno}'
    except (OSError, SyntaxError):
        pass
    return f'{path}:{first_line}-{first_line + 60}'


def hot_functions(profile: cProfile.Profile) -> list:
    stats = pstats.Stats(profile)
    rows = []
    for (filename, line, func), (_, ncalls, tottime, cumtime, _) in stats.stats.items():
        rel = Path(filename).resolve().as_posix()
        root = ROOT.resolve().as_posix() + '/'
        if not rel.startswith(root):
            continue
        rel = rel[len(root):]
        if not rel.startswith(REPO_ROOTS) or '/tests' in rel:
            continue
        rows.append({'function': func, 'where': f'{rel}:{line}', 'calls': ncalls,
                     'tottime': round(tottime, 4), 'cumtime': round(cumtime, 4),
                     'range': _function_range(rel, line)})
    rows.sort(key=lambda r: r['cumtime'], reverse=True)
    return rows[:TOP_FUNCTIONS]


def _rolled_back_get(client, url):
    with transaction.atomic():
        response = client.get(url)
        transaction.set_rollback(True)
    return response


def measure(client, label, url) -> dict:
    for _ in range(2):                         # réchauffe : caches par processus
        _rolled_back_get(client, url)
    timings = []
    for _ in range(2):
        start = time.perf_counter()
        response = _rolled_back_get(client, url)
        timings.append(time.perf_counter() - start)
    profile = cProfile.Profile()
    with CaptureQueriesContext(connection) as queries:
        profile.enable()
        _rolled_back_get(client, url)
        profile.disable()
    normalized = Counter(re.sub(r'\b\d+\b', 'N', q['sql'])[:300] for q in queries)
    repeated = [{'count': n, 'sql': sql[:200]} for sql, n in normalized.most_common(5)
                if n >= REPEATED_MIN]
    return {'label': label, 'url': url, 'status': response.status_code,
            'seconds': round(min(timings), 3), 'queries': len(queries),
            'repeated_queries': repeated, 'hot_functions': hot_functions(profile)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--user', required=True, help='Compte dont on mesure les pages (ses données)')
    ap.add_argument('--polled', action='store_true', help='Ajouter les adresses interrogées en boucle')
    ap.add_argument('--only', default='', help='Filtre sur les étiquettes, séparées par des virgules')
    ap.add_argument('--slow', type=float, default=0.3, help='Seuil « lent » en secondes (défaut 0,3)')
    ap.add_argument('--json', default='', help='Écrire le relevé complet dans ce fichier')
    args = ap.parse_args()

    from django.contrib.auth import get_user_model
    user = get_user_model().objects.get(username=args.user)
    client = Client()
    client.force_login(user)

    targets = page_urls() + (polled_urls() if args.polled else [])
    if args.only:
        wanted = {w.strip() for w in args.only.split(',') if w.strip()}
        targets = [t for t in targets if any(w in t[0] for w in wanted)]
    results = []
    for label, url in targets:
        try:
            results.append(measure(client, label, url))
        except Exception as e:                  # une page en erreur est un résultat, pas une casse
            results.append({'label': label, 'url': url, 'error': f'{type(e).__name__}: {e}'})
    results.sort(key=lambda r: r.get('seconds', -1), reverse=True)

    print(f"{'s':>7} {'SQL':>5}  {'HTTP':>4}  page")
    for r in results:
        if 'error' in r:
            print(f"{'ERR':>7} {'':>5}  {'':>4}  {r['label']} {r['url']} — {r['error'][:120]}")
            continue
        flag = ' ◀' if r['seconds'] >= args.slow else ''
        print(f"{r['seconds']:>7.3f} {r['queries']:>5}  {r['status']:>4}  {r['label']} {r['url']}{flag}")
    for r in [r for r in results if r.get('seconds', 0) >= args.slow]:
        print(f"\n── {r['label']} {r['url']} — {r['seconds']} s, {r['queries']} requêtes")
        for q in r['repeated_queries']:
            print(f"   ×{q['count']} {q['sql'][:140]}")
        for f in r['hot_functions']:
            print(f"   {f['cumtime']:>7.3f} cum {f['tottime']:>7.3f} tot ×{f['calls']:<5} "
                  f"{f['function']}  {f['range']}")
    if args.json:
        out = ROOT / args.json
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({'user': args.user, 'slow': args.slow, 'results': results},
                                  ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'\n→ {args.json}')


if __name__ == '__main__':
    main()
