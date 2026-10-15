#!/usr/bin/env python3
"""
Chaîne « dépôt → app » en UNE tâche — `librarian` → `app` → naissance au bac à sable.

POURQUOI UNE CHAÎNE (2026-10-15, demande de Fabien : « que l'assistant gère ça tout seul »). Les
rôles sont des tâches de fond ; leur fin est ANNONCÉE dans le fil (`notify_finished_jobs` →
`gateway.core._dev_job_follow_up`), elle ne RELANCE pas l'assistant. Lancée rôle par rôle, la
route attendait un « continue » humain à chaque marche. Ici les marches s'enchaînent de façon
DÉTERMINISTE — chacune est le rôle existant, lancé tel quel, avec ses propres contrôles ; ce
pilote n'ajoute aucun jugement, il passe la sortie de l'un à l'entrée du suivant.

Ce qu'il ne fait pas, délibérément :
  - VALIDER ou INSTALLER la librairie : c'est le geste « Valider » du model manager puis la route
    `install_library` (verrous `ROADMAP §16.7`) — la chaîne le DIT, et n'attend pas : le brouillon
    d'app ne dépend que du manifeste, seule la glu attendra la brique ;
  - le rôle `integrator` : il ne juge que des manifestes `model` (`run_integrator.py`) — le
    catalogue d'apps est montré au rôle `app`, qui dit dans `concerns` si une app existante fait déjà
    le besoin ;
  - promouvoir l'app hors du bac à sable, ni écrire sa glu (rôle `codegen`, ensuite).

Un fournisseur DISTANT qui coupe une marche (vécu le 2026-10-15 : ILaaS coupe vers 3 min 30 une
tâche de réflexion) est rejoué UNE fois en local — par le rôle lui-même (`role_utils.call_llm`).

Usage (racine du repo, venv_linux) :
    python wama-dev-ai/run_repo_app.py --repo LibreTranslate/LibreTranslate --key translator \
        --need "traduire des textes et des documents" --like reader
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEV_AI = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(DEV_AI))

import os  # noqa: E402
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402
django.setup()

from role_utils import REPO_ROOT, write_output  # noqa: E402

_OUTPUT = re.compile(r'^\[(?:librarian|app)\] → (?P<path>\S+\.json)\s*$', re.M)
_BORN = re.compile(r'App DE ZÉRO : \S+ → wama/(?P<label>\w+)')
_HOLES = re.compile(r'(\d+) trou\(s\) de glu')
STEP_TIMEOUT_S = 1800


def run(argv: list) -> tuple:
    """`(code de retour, sortie)` d'une marche — jamais d'exception."""
    try:
        proc = subprocess.run(argv, cwd=str(REPO_ROOT), capture_output=True, text=True,
                              timeout=STEP_TIMEOUT_S)
        return proc.returncode, (proc.stdout or '') + (proc.stderr or '')
    except subprocess.TimeoutExpired as exc:
        return 124, f'marche interrompue après {STEP_TIMEOUT_S} s : {exc}'


def run_role(script: str, args: list, provider: str, model: str, log: list) -> tuple:
    """Une marche-rôle. Une coupure d'un fournisseur distant est rejouée en local DANS le rôle
    (`role_utils.call_llm`, 2026-10-16) — la chaîne la rejouait elle-même la veille, et le rôle
    `app` lancé seul par l'assistant n'en avait aucune."""
    llm = (['--provider', provider] if provider else []) + (['--model', model] if model else [])
    rc, out = run([sys.executable, str(DEV_AI / script), *args, *llm])
    log.append({'step': script, 'provider': provider or 'ollama', 'rc': rc,
                'tail': out.strip().splitlines()[-12:]})
    return rc, out


def output_of(stdout: str) -> dict:
    """Le premier rapport annoncé par une marche (`[role] → chemin.json`), lu ; {} sinon."""
    for m in _OUTPUT.finditer(stdout):
        if not m['path'].endswith('.manifest.json'):
            try:
                return json.loads((REPO_ROOT / m['path']).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return {}
    return {}


def validated_library(repo: str) -> str:
    """La clé d'une librairie DÉJÀ inscrite au registre pour ce dépôt, ou ''.

    Relancer le `librarian` sur un dépôt validé redéposerait sa proposition, et `propose()` remet
    un manifeste en visibilité PRIVÉE (`manifests/proposals.py`) : la validation humaine serait
    défaite en silence (relevé le 2026-10-16, après la validation de `library:libretranslate`)."""
    from django.db.models import Q
    from wama.common.models import Library
    lib = (Library.objects.filter(Q(vendor__repo=repo)
                                  | Q(repository__iexact=f'https://github.com/{repo}'))
           .order_by('key').first())
    return lib.key if lib else ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True, help='Dépôt GitHub owner/name')
    ap.add_argument('--key', required=True, help="Clé de l'app neuve (underscore_case)")
    ap.add_argument('--need', required=True, help="Ce que l'app doit faire, en clair")
    ap.add_argument('--like', default='', help='App existante la plus proche')
    ap.add_argument('--provider', default='')
    ap.add_argument('--model', default='')
    ap.add_argument('--no-sandbox', action='store_true',
                    help="S'arrêter au brouillon, sans faire naître l'app")
    args = ap.parse_args()

    log, summary = [], {'repo': args.repo, 'key': args.key, 'need': args.need,
                        'like': args.like}

    # 1. La brique librairie — réutilisée si elle est déjà inscrite, jamais reproposée.
    lib_key = validated_library(args.repo)
    if lib_key:
        log.append({'step': 'run_librarian.py', 'rc': 0,
                    'tail': [f'librairie {lib_key} déjà inscrite au registre — réutilisée']})
        summary['library'] = {'key': lib_key, 'reused': True}
    else:
        rc, out = run_role('run_librarian.py', ['--repo', args.repo], args.provider, args.model,
                           log)
        library = output_of(out)
        lib_key = (library.get('manifest') or {}).get('key') or ''
        summary['library'] = {'key': lib_key,
                              'validation_errors': library.get('validation_errors'),
                              'install_channel_notes': library.get('install_channel_notes')}
        if rc != 0 or not lib_key:
            return finish(args, summary, log,
                          f"marche librarian en échec (rc={rc}) — rien d'autre lancé")

    # 2. Le brouillon du manifeste `app`.
    app_args = ['--key', args.key, '--need', args.need, '--requires', f'library:{lib_key}']
    if args.like:
        app_args += ['--like', args.like]
    rc, out = run_role('run_app_manifest.py', app_args, args.provider, args.model, log)
    draft = output_of(out)
    summary['draft'] = {k: draft.get(k) for k in ('verdict', 'manifest_file', 'mechanical_checks',
                                                  'pending_bricks', 'decisions', 'concerns')}
    if rc != 0 or draft.get('verdict') != 'clean':
        return finish(args, summary, log,
                      f"brouillon {draft.get('verdict') or 'absent'} (rc={rc}) — l'app ne naît pas")
    if args.no_sandbox:
        return finish(args, summary, log, 'brouillon prêt — naissance non demandée (--no-sandbox)')

    # 3. La naissance au bac à sable, puis le rechargement qui la sert.
    from wama.common.services.development_models import role_user
    user = role_user()
    born = [sys.executable, str(REPO_ROOT / 'manage.py'), 'app_sandbox', 'create',
            '--from-manifest', draft['manifest_file']]
    if user is not None:
        born += ['--owner', user.username]
    rc, out = run(born)
    log.append({'step': 'app_sandbox create', 'rc': rc, 'tail': out.strip().splitlines()[-15:]})
    match = _BORN.search(out)
    label = match['label'] if match else ''
    summary['sandbox'] = {'rc': rc, 'label': label,
                          'glue_holes': sum(int(n) for n in _HOLES.findall(out))}
    if rc != 0 or 'ÉCHEC' in out:
        return finish(args, summary, log, f"naissance en échec — `app_sandbox remove {label}` "
                                          "pour tout retirer, la raison est dans `steps`")
    from wama.common.services.dev_tools import dev_reload_web
    summary['reload'] = dev_reload_web(user)
    return finish(args, summary, log, f'app née au bac à sable : /{label}/ (dev seulement)')


def finish(args, summary: dict, log: list, outcome: str):
    summary['outcome'] = outcome
    out = write_output('repo_app', args.key, {**summary, 'steps': log})
    print(f'[repo_app] → {out.relative_to(REPO_ROOT)}')
    print(f'[repo_app] {outcome}')
    lib = summary.get('library') or {}
    if lib.get('key') and not lib.get('reused'):
        print(f"[repo_app] librairie {lib['key']} : à VALIDER (model manager, « Propositions ») "
              "puis à installer par la route WAMA avant la glu")
    elif lib.get('key'):
        print(f"[repo_app] librairie {lib['key']} : déjà inscrite — réutilisée, pas reproposée")
    for brick in (summary.get('draft') or {}).get('pending_bricks') or []:
        print(f'[repo_app] ⏳ brique en attente : {brick}')
    return None


if __name__ == '__main__':
    main()
