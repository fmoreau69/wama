#!/usr/bin/env python3
"""
Rôle « codegen » — corps de GLU d'une tâche d'app depuis le MANIFESTE COMPOSÉ (marche B).

Pilote BORNÉ, sur le patron de `run_librarian.py` (tâche étroite, one-shot, jamais
d'auto-application) :
  1. rassemble la MATIÈRE : contrat de la brique `task_skeleton` (docstring = le contrat),
     fichier mince rendu par le gabarit A2b (le trou à remplir, nom imposé), manifeste de
     l'app + manifestes RÉSOLUS de ses `requires` (modèles + librairies), 2 glus RÉELLES en
     few-shot (converter `_convert`, reader `_read` — extraites par AST, jamais recopiées) ;
  2. un seul appel Ollama (rôle `codegen`, chaîne de repli dans config.py) ;
  3. la sortie est contrôlée MÉCANIQUEMENT : compile(), fonction au nom imposé de signature
     (item, ctx), drapeaux d'interdits (écriture de statut/progress, import HF avant
     HF_HUB_CACHE, imports lourds en tête de bloc) ;
  4. écrit dans `outputs/` avec PENDING_HUMAN_VALIDATION — n'écrit JAMAIS dans wama/.
     Le juge profond reste le harnais C (`app_regen_check`) dans le worktree, après
     application HUMAINE de la glu.

Usage (racine du repo) :
    python wama-dev-ai/run_codegen.py --app converter --task convert_media_task \
        --truth wama.converter.tasks:_convert          # banc : vérité terrain jointe
    python wama-dev-ai/run_codegen.py --app reader --task read_document_task --model gemma4:26b
"""
import argparse
import ast
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django
django.setup()

from config import OLLAMA_HOST, select_model_for_role  # noqa: E402 (wama-dev-ai/config.py)

PROMPT = (Path(__file__).parent / 'prompts' / 'codegen.txt').read_text(encoding='utf-8')
OUTPUTS = Path(__file__).parent / 'outputs'
MAX_MATTER_CHARS = 60000   # tâche étroite : tronquer plutôt que faire dériver
FEWSHOT = (('converter', 'wama/converter/tasks.py', ('convert_media_task', '_convert')),
           ('reader', 'wama/reader/tasks.py', ('read_document_task', '_read')))


def _ollama_host():
    """Sous WSL2, 127.0.0.1 n'atteint PAS l'Ollama de l'hôte Windows : gateway obligatoire."""
    host = OLLAMA_HOST
    if '127.0.0.1' in host or 'localhost' in host:
        try:
            if 'microsoft' in Path('/proc/version').read_text().lower():
                import subprocess
                gw = subprocess.run(['sh', '-c', "ip route | awk '/default/ {print $3; exit}'"],
                                    capture_output=True, text=True).stdout.strip()
                if gw:
                    host = re.sub(r'127\.0\.0\.1|localhost', gw, host)
        except OSError:
            pass
    return host


# Ollama (gateway) SANS proxy — le proxy UGE avalerait 172.x.
_OPENER_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _source_de(path: Path, noms: tuple) -> str:
    """Segments source des fonctions demandées, par AST (le code réel, jamais recopié)."""
    src = path.read_text(encoding='utf-8')
    morceaux = []
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in noms:
            morceaux.append(ast.get_source_segment(src, node) or '')
    return '\n\n'.join(morceaux)


def matiere_manifeste(app_id: str) -> tuple:
    """(manifeste app compacté, manifestes des requires résolus) — extraction LIVE."""
    from wama.common.manifests.ingest import extract
    man = extract('app', app_id)
    if not man:
        raise SystemExit(f"app inconnue : {app_id}")
    body = man.get('body') or {}
    # Compaction : la glu n'a pas besoin des facettes UI (modes/studio/inspector/tool_api).
    garde = {k: body[k] for k in ('identity', 'params', 'processing', 'models',
                                  'capabilities', 'ports') if k in body}
    compact = {k: v for k, v in man.items() if k != 'body'} | {'body': garde}
    resolus = []
    for r in man.get('requires') or []:
        try:
            m = extract(r.get('kind'), r.get('key'))
            if m:
                resolus.append(m)
        except Exception:
            continue
    return compact, resolus


def call_ollama(model, system, user_msg):
    payload = {
        'model': model,
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': user_msg}],
        'stream': False,
        'options': {'temperature': 0.2, 'num_ctx': 32768},
    }
    req = urllib.request.Request(
        f'{_ollama_host()}/api/chat', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with _OPENER_DIRECT.open(req, timeout=900) as r:
        return json.loads(r.read())['message']['content']


def extract_code(text: str) -> str:
    """Premier bloc ```python de la réponse ; à défaut, le texte brut (modèle discipliné)."""
    m = re.search(r'```(?:python)?\s*\n(.*?)```', text, re.S)
    return (m.group(1) if m else text).strip()


def controles(code: str, nom_impose: str) -> dict:
    """Contrôles mécaniques du bloc généré — le LLM propose, la chaîne juge."""
    out = {'compile_ok': False, 'signature_ok': False, 'warnings': []}
    try:
        arbre = ast.parse(code)
        out['compile_ok'] = True
    except SyntaxError as e:
        out['warnings'].append(f'SyntaxError: {e}')
        return out

    fonctions = [n for n in arbre.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    cible = next((f for f in fonctions if f.name == nom_impose), None)
    if cible is None:
        out['warnings'].append(f"fonction imposée `{nom_impose}` absente "
                               f"(reçues : {[f.name for f in fonctions]})")
    else:
        args = [a.arg for a in cible.args.args]
        out['signature_ok'] = args[:2] == ['item', 'ctx']
        if not out['signature_ok']:
            out['warnings'].append(f'signature {args} ≠ (item, ctx)')
    autres = [n for n in arbre.body
              if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Import,
                                    ast.ImportFrom))]
    if autres:
        out['warnings'].append(f'{len(autres)} nœud(s) top-level hors fonctions/imports')
    for n in arbre.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            noms = [a.name for a in n.names] + [getattr(n, 'module', '') or '']
            lourds = [x for x in noms if any(h in (x or '') for h in
                      ('torch', 'transformers', 'diffusers', 'huggingface'))]
            if lourds:
                out['warnings'].append(f'import lourd en tête de bloc (règle 3) : {lourds}')

    # Interdits textuels (règle 2) — la glu ne pilote pas le cycle de vie.
    for motif, raison in ((r'item\.status\s*=', 'écrit item.status (règle 2)'),
                          (r'item\.progress\s*=', 'écrit item.progress (règle 2)'),
                          (r'\.update\(\s*status\s*=', 'update(status=…) (règle 2)'),
                          (r"['\"](RUNNING|SUCCESS|FAILURE)['\"]\s*\)?\s*$",
                           None)):   # lecture tolérée — pas de warning
        if raison and re.search(motif, code):
            out['warnings'].append(raison)
    # Ordre HF_HUB_CACHE vs import HF (règle 3) — positions textuelles dans le bloc.
    pose = code.find('HF_HUB_CACHE')
    for m in re.finditer(r'(?:from|import)\s+(transformers|diffusers|huggingface_hub)', code):
        if pose < 0 or m.start() < pose:
            out['warnings'].append(f'import {m.group(1)} avant HF_HUB_CACHE (règle 3)')
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--app', required=True, help="App cible (ex. converter).")
    ap.add_argument('--task', default=None,
                    help='Fonction de tâche lifecycle (défaut : la seule déclarée).')
    ap.add_argument('--model', default=None, help='Modèle Ollama (défaut : rôle codegen).')
    ap.add_argument('--truth', default=None,
                    help="Vérité terrain jointe à la revue : 'module.dotted:fonction'.")
    args = ap.parse_args()

    man, resolus = matiere_manifeste(args.app)
    proc = (man.get('body') or {}).get('processing') or {}
    lifecycle = [t['function'] for t in (proc.get('tasks') or []) if t.get('lifecycle')]
    task = args.task or (lifecycle[0] if len(lifecycle) == 1 else None)
    if not task:
        raise SystemExit(f"--task requis (lifecycle déclarées : {lifecycle})")
    nom_impose = f'_process_{task}'

    # Fichier mince du gabarit A2b : montre au modèle le wrapper et le trou EXACTS.
    from wama.common.manifests.codegen.tasks_gen import render_tasks
    mince, raison = render_tasks({**man, 'body': {**man['body'],
                                  'processing': {**proc, 'tasks': [
                                      t for t in proc.get('tasks') or []
                                      if t.get('function') == task]}}})
    if mince is None:
        raise SystemExit(f'gabarit tasks non rendable : {raison}')

    contrat = ast.get_docstring(ast.parse(
        (REPO_ROOT / 'wama/common/utils/task_skeleton.py').read_text(encoding='utf-8')))
    fewshot = '\n\n'.join(
        f'===== GLU RÉELLE ({app}) =====\n{_source_de(REPO_ROOT / chemin, noms)}'
        for app, chemin, noms in FEWSHOT if app != args.app)

    corps = json.dumps(man, ensure_ascii=False, indent=1)
    jambes = '\n'.join(json.dumps(m, ensure_ascii=False) for m in resolus)
    user_msg = (
        f'CONTRAT de la brique run_item_task (docstring de task_skeleton.py) :\n{contrat}\n\n'
        f'EXEMPLES — glus réelles d\'apps WAMA existantes :\n{fewshot}\n\n'
        f'MANIFESTE de l\'app `{args.app}` :\n{corps}\n\n'
        f'MANIFESTES RÉSOLUS de ses requires (modèles + librairies) :\n{jambes}\n\n'
        f'FICHIER MINCE généré (le wrapper appelle ta glu) :\n{mince}\n\n'
        f'Écris la fonction `{nom_impose}(item, ctx)` qui remplit ce trou '
        f'(bloc ```python seul).')[:MAX_MATTER_CHARS]

    model = args.model or select_model_for_role('codegen')[1].ollama_id
    print(f'[codegen] modèle : {model} | app : {args.app} | glu : {nom_impose}')
    reponse = call_ollama(model, PROMPT, user_msg)
    code = extract_code(reponse)
    verif = controles(code, nom_impose)

    verite = None
    if args.truth:
        module, _, fn = args.truth.partition(':')
        chemin = REPO_ROOT.joinpath(*module.split('.')).with_suffix('.py')
        verite = {'ref': args.truth, 'source': _source_de(chemin, (fn,))}

    OUTPUTS.mkdir(exist_ok=True)
    horodatage = datetime.now().strftime('%Y-%m-%d_%H-%M')
    sortie = OUTPUTS / f'codegen_{args.app}_{task}_{horodatage}.json'
    sortie.write_text(json.dumps({
        'status': 'PENDING_HUMAN_VALIDATION',
        'role': 'codegen',
        'model': model,
        'app': args.app, 'task': task, 'function': nom_impose,
        'checks': verif,
        'code': code,
        'truth': verite,
        'matter_chars': len(user_msg),
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'[codegen] → {sortie.relative_to(REPO_ROOT)}')
    print(f"[codegen] compile={verif['compile_ok']} signature={verif['signature_ok']} "
          f"warnings={len(verif['warnings'])}"
          + (f' — {verif["warnings"][:3]}' if verif['warnings'] else ''))
    print('[codegen] juge profond = harnais C après application HUMAINE (worktree).')


if __name__ == '__main__':
    main()
