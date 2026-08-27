#!/usr/bin/env python3
"""
Rôle « scout » — dépôt de MODÈLE (HuggingFace) → manifeste `model` (pendant du librarian,
qui traduit les librairies ; trou « aucun rôle scout modèles » consigné le 2026-08-04,
PROSPECTION_PIPELINE.md).

Pilote BORNÉ (leçons wama-dev-ai) :
  1. SQUELETTE MÉCANIQUE d'abord : identité/licence/auteur (API HF), taille disque,
     inventaire des fichiers de poids — les faits ne passent pas par le LLM ;
  2. un seul appel Ollama : le LLM COMPLÈTE (model_type, capacités, composition
     multi-composants) sans jamais contredire le squelette ;
  3. validation MÉCANIQUE (`ingest.validate`) + re-pose des faits mécaniques par-dessus
     la réponse (le LLM propose, les faits tranchent) ;
  4. écrit dans `outputs/` avec PENDING_HUMAN_VALIDATION — n'ingère JAMAIS en base.

`--dry-run` : construit et affiche le squelette + le contexte SANS appel LLM (aucune
charge sur l'Ollama hôte — c'est le mode de test des sessions Claude ; la passe LLM
réelle se lance sur décision humaine, comme la passe de confiance).

Usage (racine du repo, venv_linux) :
    python wama-dev-ai/run_scout.py --hf MiniMaxAI/MiniMax-Music3 --dry-run
    python wama-dev-ai/run_scout.py --hf audio-cpp/MiniMax-Music3-GGUF
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django
django.setup()

from role_utils import REPO_ROOT, call_ollama, extract_json, fetch, write_output  # noqa: E402

PROMPT = (Path(__file__).parent / 'prompts' / 'scout.txt').read_text(encoding='utf-8')
EXEMPLES_DIR = REPO_ROOT / 'manifests' / 'models'
_EXT_POIDS = ('.gguf', '.safetensors', '.bin', '.pt', '.pth', '.onnx')


def squelette(hf_id: str) -> tuple[dict, str]:
    """(squelette mécanique du manifeste, inventaire texte des fichiers) — ZÉRO LLM ici."""
    from huggingface_hub import HfApi
    info = HfApi().model_info(hf_id, files_metadata=True)

    fichiers = [(s.rfilename, s.size or 0) for s in (info.siblings or [])]
    poids = [(n, t) for n, t in fichiers if n.lower().endswith(_EXT_POIDS)]
    disk_gb = round(sum(t for _, t in fichiers) / 1024 ** 3, 1)

    licence = ''
    try:
        carte = info.card_data
        licence = (carte.to_dict().get('license') if carte else None) or ''
    except Exception:
        pass
    auteur = getattr(info, 'author', '') or hf_id.partition('/')[0]

    manifeste = {
        'manifest_kind': 'model',
        'key': f'huggingface:{hf_id}',
        'schema_version': '1.0',
        'name': hf_id.split('/')[-1],
        'description': '',
        'world': 'transverse',
        'visibility': 'public',
        'projects': [],
        'source': {'type': 'extract', 'ref': f'scout:huggingface:{hf_id}'},
        'body': {
            'identity': {
                'model_type': None,          # ← jugement LLM (taxonomie fermée)
                'source': 'huggingface',
                'hf_id': hf_id,
                'license': str(licence)[:64] or None,
                'author': str(auteur)[:200] or None,
                'platform_ref': f'huggingface:{hf_id}',
                'description_short': None,   # ← jugement LLM
            },
            'resources': {'disk_gb': disk_gb},
            'formats': {},
            'capabilities': {},              # ← jugement LLM (task/modalities)
            'provenance': {'is_proposed': False},
            'extra_info': {'downloads': getattr(info, 'downloads', None),
                           'pipeline_tag': getattr(info, 'pipeline_tag', None)},
        },
    }
    inventaire = '\n'.join(f'  {t / 1024 ** 3:7.2f} Go  {n}' for n, t in
                           sorted(poids, key=lambda x: -x[1])[:60])
    autres = [n for n, _ in fichiers if not n.lower().endswith(_EXT_POIDS)][:40]
    inventaire += '\nFichiers non-poids : ' + (', '.join(autres) or '(aucun)')
    return manifeste, inventaire


def _readme(hf_id: str, limit: int = 8000) -> str:
    try:
        return fetch(f'https://huggingface.co/{hf_id}/raw/main/README.md')[:limit]
    except Exception:
        return '(README indisponible)'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hf', required=True, help='Dépôt HuggingFace org/nom')
    ap.add_argument('--model', default=None, help='Modèle Ollama (défaut : rôle dev)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Squelette + contexte seulement, AUCUN appel LLM (test sans GPU)')
    args = ap.parse_args()

    base, inventaire = squelette(args.hf)

    from wama.model_manager.models import ModelType
    taxonomie = ', '.join(sorted(ModelType.values))
    exemples = '\n\n'.join(f.read_text(encoding='utf-8')
                           for f in sorted(EXEMPLES_DIR.glob('*.json'))[:1])
    user_msg = (f'TAXONOMIE model_type (fermée) : {taxonomie}\n\n'
                f'EXEMPLE de manifeste `model` valide :\n{exemples}\n\n'
                f'SQUELETTE mécanique (à COMPLÉTER, jamais contredire) :\n'
                f'{json.dumps(base, ensure_ascii=False, indent=1)}\n\n'
                f'FICHIERS DE POIDS du dépôt :\n{inventaire}\n\n'
                f'CARTE (extrait) :\n{_readme(args.hf)}\n\n'
                'Complète le manifeste (model_type, description(s), capabilities, '
                'composition si multi-composants). Réponds {"manifest": …, "concerns": […]}.')

    if args.dry_run:
        print('[scout] DRY-RUN — squelette mécanique :')
        print(json.dumps(base, ensure_ascii=False, indent=2))
        print(f'[scout] contexte LLM : {len(user_msg)} caractères, inventaire :')
        print(inventaire)
        return

    from config import select_model_for_role
    model = args.model or select_model_for_role('dev')[1].ollama_id
    print(f'[scout] modèle : {model} | dépôt : {args.hf}')
    reponse = extract_json(call_ollama(model, PROMPT, user_msg))
    manifest = reponse.get('manifest') or {}
    concerns = reponse.get('concerns') or []

    # ── Les FAITS mécaniques re-priment sur la réponse (le LLM propose, les faits tranchent).
    for chemin, valeur in (
        (('key',), base['key']),
        (('body', 'identity', 'hf_id'), base['body']['identity']['hf_id']),
        (('body', 'identity', 'source'), 'huggingface'),
        (('body', 'identity', 'license'), base['body']['identity']['license']),
        (('body', 'identity', 'author'), base['body']['identity']['author']),
        (('body', 'identity', 'platform_ref'), base['body']['identity']['platform_ref']),
        (('body', 'resources', 'disk_gb'), base['body']['resources']['disk_gb']),
    ):
        cible = manifest
        for k in chemin[:-1]:
            cible = cible.setdefault(k, {})
        cible[chemin[-1]] = valeur

    from wama.common.manifests.ingest import validate
    erreurs = list(validate(manifest) or [])

    sortie = write_output('scout', args.hf, {
        'model': model, 'provenance': f'huggingface:{args.hf}',
        'validation_errors': erreurs, 'concerns': concerns, 'manifest': manifest,
    })
    print(f'[scout] → {sortie.relative_to(REPO_ROOT)}')
    print(f'[scout] validation : {len(erreurs)} erreur(s)'
          + (f' — {erreurs[:3]}' if erreurs else ' — manifeste VALIDE'))
    if concerns:
        print(f'[scout] concerns : {concerns[:3]}')


if __name__ == '__main__':
    main()
