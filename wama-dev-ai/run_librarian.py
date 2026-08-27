#!/usr/bin/env python3
"""
Rôle « librarian » — projet GitHub / paquet Python → manifeste `library` (SPEC §7.4-4).

Pilote BORNÉ (leçons wama-dev-ai : tâche étroite, one-shot, jamais d'auto-application) :
  1. rassemble les SOURCES (README + pyproject d'un dépôt GitHub, ou métadonnées du
     paquet installé) ;
  2. un seul appel Ollama, avec le corpus `manifests/libraries/` en exemple ;
  3. la sortie est validée MÉCANIQUEMENT (`ingest.validate`) et, si la lib est installée,
     diffée contre la vérité terrain (`extract_library`) ;
  4. écrit dans `outputs/` avec PENDING_HUMAN_VALIDATION — n'ingère JAMAIS en base.

Usage (depuis la racine du repo, venv_linux) :
    python wama-dev-ai/run_librarian.py --dist faster-whisper           # offline (installé)
    python wama-dev-ai/run_librarian.py --repo SYSTRAN/faster-whisper   # depuis GitHub
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django
django.setup()

from config import select_model_for_role  # noqa: E402 (wama-dev-ai/config.py)
# Helpers COMMUNS aux rôles (extraits d'ici le 2026-08-27 à la naissance de scout/integrator).
from role_utils import call_ollama, extract_json, fetch as _fetch  # noqa: E402

PROMPT = (Path(__file__).parent / 'prompts' / 'librarian.txt').read_text(encoding='utf-8')
EXEMPLES_DIR = REPO_ROOT / 'manifests' / 'libraries'
OUTPUTS = Path(__file__).parent / 'outputs'
MAX_SOURCE_CHARS = 20000   # tâche étroite : on tronque plutôt que de faire dériver


def sources_repo(repo):
    """README + pyproject/setup d'un dépôt GitHub (branche par défaut main puis master)."""
    parts = []
    for branch in ('main', 'master'):
        # Métadonnées d'ABORD, README en DERNIER : c'est lui qui déborde du budget de
        # troncature, pas l'inverse (vécu : requirements/LICENSE n'atteignaient pas le prompt).
        for fname in ('pyproject.toml', 'setup.py', 'setup.cfg', 'requirements.txt',
                      'LICENSE', 'LICENSE.txt', 'README.md'):
            try:
                txt = _fetch(f'https://raw.githubusercontent.com/{repo}/{branch}/{fname}')
                parts.append(f'===== {fname} ({branch}) =====\n{txt}')
            except Exception:
                continue
        if parts:
            break
    if not parts:
        raise SystemExit(f"Aucune source récupérable pour {repo} (réseau/proxy ?).")
    return f'https://github.com/{repo}', '\n\n'.join(parts)


def sources_dist(dist_name):
    """Métadonnées du paquet INSTALLÉ, présentées comme matériau brut (pas pré-mâché)."""
    import importlib.metadata as im
    d = im.distribution(dist_name)
    # PAS str(d.metadata) : le repli d'en-têtes email lève HeaderParseError sur les
    # valeurs longues. On sérialise les items nous-mêmes (+ le README en payload).
    meta = '\n'.join(f'{k}: {str(v)[:500]}' for k, v in d.metadata.items())
    try:
        payload = d.metadata.get_payload()
        if payload:
            meta += f'\n\n===== README (payload) =====\n{payload[:6000]}'
    except Exception:
        pass
    eps = '\n'.join(f'{ep.group}: {ep.name} = {ep.value}' for ep in d.entry_points)
    deps = '\n'.join(d.requires or [])
    return (f'importlib.metadata:{d.name}=={d.version}',
            f'===== PKG-INFO =====\n{meta}\n\n===== entry_points =====\n{eps}'
            f'\n\n===== requires =====\n{deps}')


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--repo', help='Dépôt GitHub owner/name')
    g.add_argument('--dist', help='Distribution Python installée')
    ap.add_argument('--model', default=None, help='Modèle Ollama (défaut : rôle dev)')
    args = ap.parse_args()

    provenance, matiere = (sources_repo(args.repo) if args.repo
                           else sources_dist(args.dist))
    matiere = matiere[:MAX_SOURCE_CHARS]

    exemples = '\n\n'.join(f.read_text(encoding='utf-8')
                           for f in sorted(EXEMPLES_DIR.glob('*.json'))[:2])
    model = args.model or select_model_for_role('dev')[1].ollama_id
    print(f'[librarian] modèle : {model} | provenance : {provenance}')

    user_msg = (f'EXEMPLE(S) de manifeste `library` valide :\n{exemples}\n\n'
                f'SOURCES du projet à traduire :\n{matiere}\n\n'
                f'Produis le manifeste `library` de ce projet (JSON seul).')
    reponse = call_ollama(model, PROMPT, user_msg)
    manifest = extract_json(reponse)

    # ── Contrôles MÉCANIQUES (le LLM propose, la chaîne d'ingest juge) ──────────
    from wama.common.manifests.ingest import validate
    erreurs = list(validate(manifest) or [])

    divergences = {}
    cle = manifest.get('key') or ''
    try:
        from wama.common.manifests.builtin.library import extract_library
        verite = extract_library(cle)
    except Exception:
        verite = None
    if verite:
        for chemin in (('body', 'identity', 'version'), ('body', 'identity', 'license'),
                       ('body', 'identity', 'repository'), ('body', 'install', 'pip')):
            a, b = manifest, verite
            for k in chemin:
                a = (a or {}).get(k)
                b = (b or {}).get(k)
            if (a or None) != (b or None):
                divergences['.'.join(chemin)] = {'llm': a, 'mecanique': b}

    OUTPUTS.mkdir(exist_ok=True)
    horodatage = datetime.now().strftime('%Y-%m-%d_%H-%M')
    sortie = OUTPUTS / f'library_{(cle or "inconnu").replace("/", "_")}_{horodatage}.json'
    sortie.write_text(json.dumps({
        'status': 'PENDING_HUMAN_VALIDATION',
        'role': 'librarian',
        'model': model,
        'provenance': provenance,
        'validation_errors': erreurs,
        'divergences_vs_mecanique': divergences,
        'manifest': manifest,
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'[librarian] → {sortie.relative_to(REPO_ROOT)}')
    print(f'[librarian] validation : {len(erreurs)} erreur(s)'
          + (f' — {erreurs[:3]}' if erreurs else ' — manifeste VALIDE'))
    if verite:
        print(f'[librarian] divergences vs extraction mécanique : {len(divergences)}'
              + (f' — {list(divergences)[:4]}' if divergences else ' — accord total'))
    else:
        print('[librarian] pas de vérité terrain (lib non installée) — validation humaine seule')


if __name__ == '__main__':
    main()
