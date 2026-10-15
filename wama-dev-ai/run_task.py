#!/usr/bin/env python3
"""
Rôle « task » — une tâche de DÉVELOPPEMENT en clair, bornée à des fichiers NOMMÉS : en lecture
seule (réponse dont chaque affirmation cite sa ligne) ou en ajustement de code (édits PROPOSÉS).

Décision de Fabien, 2026-10-15 : la règle « wama-dev-ai ne touche pas au code » tenait tant que
seuls de petits modèles locaux étaient branchés ; avec un modèle souverain de niveau
développement (ILaaS), on la lève PROGRESSIVEMENT — lecture seule, puis petits ajustements, sous
supervision. Ce rôle est la seconde voie de la surface de développement, à côté des rôles de
GÉNÉRATION et d'INTÉGRATION (codegen, backend, model…) : on ne les mélange pas.

Pilote BORNÉ, comme les autres rôles :
  1. contexte MÉCANIQUE : les seuls fichiers nommés (`chemin` ou `chemin:début-fin`), numérotés ;
     un chemin hors dépôt, un secret, un venv, une migration sont REFUSÉS avant tout appel ;
  2. un seul appel LLM (modèle tiré pour le compte par la surface, garde GPU commune) ;
  3. contrôles MÉCANIQUES : en lecture, chaque citation doit désigner une ligne réelle qui porte le
     texte cité ; en écriture, chaque `old` doit exister UNE fois, le fichier résultant doit se
     compiler (Python), se lire (JSON) ou se parser (JS, V8 embarqué) — et le diff est calculé ;
  4. écrit dans `outputs/` avec PENDING_HUMAN_VALIDATION — n'applique JAMAIS rien.

APPLIQUER est un geste SÉPARÉ (`--apply <sortie>`), que la surface de développement n'expose pas :
il refait tous les contrôles sur les fichiers tels qu'ils sont À CET INSTANT et n'écrit rien si un
seul échoue. Il ne commite pas.

Usage (racine du repo, venv_linux) :
    python wama-dev-ai/run_task.py --task "Où est calculée la VRAM d'un modèle ?" \
        --files wama/common/utils/auto_model.py --dry-run
    python wama-dev-ai/run_task.py --write --task "…" --files wama/x.py:100-220,wama/y.py
    python wama-dev-ai/run_task.py --apply wama-dev-ai/outputs/task_….json
"""
import argparse
import ast
import difflib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os  # noqa: E402
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402
django.setup()

from role_utils import (  # noqa: E402
    REPO_ROOT, add_llm_arguments, call_llm, consigne_role, extract_json, local_llm_guard,
    resolve_model, write_output)

PROMPT = consigne_role('task')

#: Plafonds du contexte : un fichier entier au-delà se demande par tranche (`chemin:début-fin`).
MAX_FILES = 8
MAX_FILE_CHARS = 60000
MAX_CONTEXT_CHARS = 160000

#: Jamais LU (secrets, poids, données) — le modèle peut être distant.
NEVER_READ = (re.compile(r'(^|/)\.env'), re.compile(r'(^|/)\.git/'), re.compile(r'^venv_'),
              re.compile(r'^AI-models/'), re.compile(r'^media/'),
              re.compile(r'\.(pem|key|p12|pfx|sqlite3|db)$'),
              re.compile(r'(^|/)(secrets?|credentials?)[^/]*$', re.I))
#: Lisible, jamais ÉCRIT par une proposition : une migration se génère, `staticfiles/` est une
#: COPIE servie (on corrige la source), les sorties des rôles ne s'éditent pas.
NEVER_WRITE = (re.compile(r'(^|/)migrations/'), re.compile(r'^staticfiles/'),
               re.compile(r'^wama-dev-ai/outputs/'), re.compile(r'^patches/'))

_RANGE = re.compile(r'^(?P<path>.+?):(?P<start>\d+)-(?P<end>\d+)$')


class TaskRefused(SystemExit):
    """Refus LISIBLE, avant tout appel au modèle."""


def parse_scope(spec: str) -> list:
    """`a.py,b.py:10-80` → `[{'path', 'start', 'end'}]` ; refuse ce qui sort du périmètre."""
    scope = []
    for raw in [s.strip() for s in (spec or '').split(',') if s.strip()]:
        m = _RANGE.match(raw)
        path, start, end = (m['path'], int(m['start']), int(m['end'])) if m else (raw, None, None)
        rel = path.replace('\\', '/').removeprefix('./')
        full = (REPO_ROOT / rel).resolve()
        if REPO_ROOT.resolve() not in full.parents:
            raise TaskRefused(f"[task] REFUS : {path!r} sort du dépôt")
        if any(p.search(rel) for p in NEVER_READ):
            raise TaskRefused(f"[task] REFUS : {rel!r} n'est jamais lu (secret, poids ou données)")
        if not full.is_file():
            raise TaskRefused(f"[task] REFUS : {rel!r} n'est pas un fichier du dépôt")
        if start is not None and (start < 1 or end < start):
            raise TaskRefused(f"[task] REFUS : tranche {start}-{end} invalide pour {rel!r}")
        scope.append({'path': rel, 'start': start, 'end': end})
    if not scope:
        raise TaskRefused("[task] REFUS : aucun fichier nommé (--files)")
    if len(scope) > MAX_FILES:
        raise TaskRefused(f"[task] REFUS : {len(scope)} fichiers, {MAX_FILES} au plus")
    return scope


def read_text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding='utf-8')


def numbered(entry: dict) -> str:
    """Le fichier (ou sa tranche) numéroté — refuse un fichier entier trop long."""
    lines = read_text(entry['path']).splitlines()
    start = entry['start'] or 1
    end = min(entry['end'] or len(lines), len(lines))
    body = '\n'.join(f'{n:>5}| {lines[n - 1]}' for n in range(start, end + 1))
    if len(body) > MAX_FILE_CHARS:
        raise TaskRefused(f"[task] REFUS : {entry['path']} fait {len(body)} caractères numérotés "
                          f"(> {MAX_FILE_CHARS}) — nommer une tranche `chemin:début-fin`")
    span = f" (lignes {start}-{end} sur {len(lines)})" if entry['start'] else ''
    return f"=== {entry['path']}{span} ===\n{body}"


def check_citations(proposal: dict, scope: list) -> list:
    """Chaque citation désigne une ligne RÉELLE d'un fichier montré, qui porte le texte cité."""
    concerns, shown = [], {e['path'] for e in scope}
    for c in proposal.get('citations') or []:
        path, line, quote = c.get('path'), c.get('line'), (c.get('quote') or '').strip()
        if path not in shown:
            concerns.append(f"citation hors des fichiers montrés : {path!r}")
            continue
        lines = read_text(path).splitlines()
        if not isinstance(line, int) or not 1 <= line <= len(lines):
            concerns.append(f"{path}:{line} — ligne inexistante")
        elif quote and quote not in lines[line - 1]:
            concerns.append(f"{path}:{line} — la ligne ne porte pas le texte cité {quote[:60]!r}")
    if not proposal.get('citations'):
        concerns.append("aucune citation : la réponse n'est adossée à aucune ligne")
    return concerns


def syntax_error(path: str, text: str) -> str:
    """'' si le fichier résultant se lit dans son langage ; sinon l'erreur."""
    try:
        if path.endswith('.py'):
            compile(ast.parse(text), path, 'exec')
        elif path.endswith('.json'):
            json.loads(text)
        elif path.endswith('.js'):
            from py_mini_racer import MiniRacer
            # Parse SANS exécuter (AGENTS.md §JS) : vaut aussi pour un module qui touche au DOM.
            MiniRacer().eval('(function(){' + text + '\n})')
    except ImportError:
        return ''
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    return ''


def check_edits(proposal: dict, scope: list) -> tuple:
    """`(concerns, {path: (avant, après)})` — les édits appliqués EN MÉMOIRE, dans l'ordre."""
    concerns, results, shown = [], {}, {e['path'] for e in scope}
    edits = proposal.get('edits') or []
    if not edits:
        concerns.append("aucun édit proposé")
    for i, edit in enumerate(edits, 1):
        path, old, new = edit.get('path'), edit.get('old') or '', edit.get('new')
        if path not in shown:
            concerns.append(f"édit {i} : fichier non montré {path!r}")
            continue
        if any(p.search(path) for p in NEVER_WRITE):
            concerns.append(f"édit {i} : {path} ne s'écrit pas par proposition")
            continue
        if new is None or old == '':
            concerns.append(f"édit {i} : `old` vide ou `new` absent")
            continue
        before, current = results.get(path, (read_text(path),) * 2)
        count = current.count(old)
        if count != 1:
            concerns.append(f"édit {i} ({path}) : `old` trouvé {count} fois, il faut exactement 1")
            continue
        results[path] = (before, current.replace(old, new, 1))
    for path, (before, after) in results.items():
        err = syntax_error(path, after)
        if err:
            concerns.append(f"{path} ne se lit plus après les édits : {err}")
    return concerns, results


def unified(results: dict) -> str:
    return ''.join(
        ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                     f'a/{path}', f'b/{path}'))
        for path, (before, after) in results.items())


def apply_output(output: str) -> None:
    """Applique une proposition VALIDÉE — contrôles refaits sur les fichiers d'aujourd'hui."""
    out_path = Path(output)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / output
    data = json.loads(out_path.read_text(encoding='utf-8'))
    if data.get('role') != 'task' or data.get('mode') != 'write':
        raise TaskRefused(f"[task] REFUS : {output} n'est pas une proposition d'écriture du rôle task")
    if data.get('status') != 'PENDING_HUMAN_VALIDATION':
        raise TaskRefused(f"[task] REFUS : statut {data.get('status')!r} (déjà appliquée ?)")
    scope = parse_scope(','.join(e['path'] for e in data['files']))
    concerns, results = check_edits(data['proposal'], scope)
    if concerns:
        raise TaskRefused("[task] REFUS d'appliquer — contrôles refaits :\n  " + '\n  '.join(concerns))
    for path, (_, after) in results.items():
        (REPO_ROOT / path).write_text(after, encoding='utf-8')
        print(f'[task] écrit : {path}')
    data['status'] = 'APPLIED'
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print('[task] appliquée — rien n\'est commité ; relancer les tests du périmètre.')


def slug_of(task: str) -> str:
    words = re.findall(r'[a-z0-9]+', task.lower().encode('ascii', 'ignore').decode())
    return '-'.join(words[:6]) or 'task'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', help='La tâche de développement, en clair')
    ap.add_argument('--files', help='Fichiers montrés au modèle : chemin ou chemin:début-fin, '
                                    'séparés par des virgules')
    ap.add_argument('--write', action='store_true',
                    help='Proposer des édits (sinon : lecture seule, réponse citée)')
    ap.add_argument('--apply', metavar='SORTIE',
                    help="Appliquer une proposition validée (jamais exposé à l'assistant)")
    add_llm_arguments(ap, role='dev')
    ap.add_argument('--dry-run', action='store_true',
                    help='Contexte seulement, AUCUN appel LLM')
    args = ap.parse_args()

    if args.apply:
        return apply_output(args.apply)
    if not args.task:
        raise TaskRefused("[task] REFUS : --task vide")
    scope = parse_scope(args.files)
    mode = 'write' if args.write else 'read'
    context = '\n\n'.join(numbered(e) for e in scope)
    if len(context) > MAX_CONTEXT_CHARS:
        raise TaskRefused(f"[task] REFUS : contexte de {len(context)} caractères "
                          f"(> {MAX_CONTEXT_CHARS}) — nommer des tranches")
    user_msg = f"MODE {mode}\n\nTASK:\n{args.task}\n\nFILES:\n{context}\n"

    if args.dry_run:
        print(f'[task] DRY-RUN — mode {mode}, {len(scope)} fichier(s), '
              f'{len(user_msg)} caractères de contexte')
        print(user_msg[:3000])
        return

    model = resolve_model(args.provider, 'dev', args.model)
    print(f'[task] {args.provider} / {model} | mode {mode} | {", ".join(e["path"] for e in scope)}')
    keep_alive = local_llm_guard(args.provider, model, force=args.force, wait_max=args.wait_max,
                                 log=lambda m: print(f'[task] {m}'))
    raw = call_llm(args.provider, model, PROMPT, user_msg, keep_alive=keep_alive, timeout=900)
    try:
        proposal = extract_json(raw)
    except ValueError as e:
        proposal, checks = {'raw': raw[:20000]}, [f"réponse illisible : {e}"]
    else:
        if mode == 'read':
            checks = check_citations(proposal, scope)
            diff = ''
        else:
            checks, results = check_edits(proposal, scope)
            diff = unified(results)

    payload = {'mode': mode, 'task': args.task, 'files': scope,
               'provider': args.provider, 'model': model,
               'mechanical_checks': checks,
               'verdict': 'clean' if not checks else 'concerns',
               'proposal': proposal}
    if mode == 'write' and 'raw' not in proposal:
        payload['diff'] = diff
    out = write_output('task', slug_of(args.task), payload)
    print(f'[task] → {out.relative_to(REPO_ROOT)}')
    print(f"[task] verdict : {payload['verdict']}")
    for c in checks:
        print(f'[task] ⚠ {c}')
    if mode == 'read' and 'answer' in proposal:
        print(f"[task] réponse : {proposal['answer'][:1500]}")
    elif payload.get('diff'):
        # Le NOMBRE d'édits d'abord, et la troncature DITE : le 2026-10-15, un superviseur a lu
        # ce journal coupé à 4000 caractères et conclu à 5 oublis qui n'en étaient pas.
        print(f"[task] {len(proposal.get('edits') or [])} édit(s) — diff complet dans {out.name}")
        print(payload['diff'][:4000])
        if len(payload['diff']) > 4000:
            print(f"[task] … diff TRONQUÉ ici ({len(payload['diff'])} caractères) : lire la sortie")


if __name__ == '__main__':
    main()
