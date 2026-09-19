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

`--seed-candidate` : écrit AUSSI le manifeste en candidat de prospection (`write_candidate`,
via `prospector.seed_candidate_from_manifest`) — c'est ce qui le rend installable par le
bouton, avec les capacités jugées ici plutôt que redécouvertes à l'installation. Un candidat
reste une PROPOSITION : visible sur la page, rejetable d'un clic (2026-09-19).

Usage (racine du repo, venv_linux) :
    python wama-dev-ai/run_scout.py --hf MiniMaxAI/MiniMax-Music3 --dry-run
    python wama-dev-ai/run_scout.py --hf audio-cpp/MiniMax-Music3-GGUF --seed-candidate
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

from role_utils import (  # noqa: E402
    REPO_ROOT, add_llm_arguments, call_llm, extract_json, fetch, manifest_examples,
    resolve_model, write_output)

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

    # ACCÈS au dépôt — fait MÉCANIQUE, pas un jugement (2026-09-07). HF distingue deux
    # régimes que la prose confondait (« nécessite un token HuggingFace ») :
    #   'auto'   — on accepte les conditions en ligne, l'accès est immédiat ;
    #   'manual' — un humain chez l'éditeur approuve, le délai n'est pas maîtrisé ;
    #   False    — libre.
    # La différence est opérationnelle : `facebook/sam3` est 'manual', `pyannote/…-3.1`
    # est 'auto' (mesuré ce jour). Écrire « il faut un token » pour les deux fait croire
    # qu'un jeton suffit là où il faut une autorisation accordée.
    # Vocabulaire NORMALISE, identique a celui du registre (`AIModel.GATED_*`) : HF rend
    # `False` la ou WAMA ecrit 'no'. Laisser passer le booleen ferait deux vocabulaires pour
    # un seul fait, et la moitie manifeste ne se projetterait jamais sur la moitie registre.
    brut = getattr(info, 'gated', None)
    gated = 'no' if brut in (None, False) else str(brut)

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
                'gated': gated,              # ← mécanique : 'no' | 'auto' | 'manual'
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
    add_llm_arguments(ap, role='dev')
    ap.add_argument('--dry-run', action='store_true',
                    help='Squelette + contexte seulement, AUCUN appel LLM (test sans GPU)')
    ap.add_argument('--seed-candidate', action='store_true',
                    help="Écrit aussi le manifeste en CANDIDAT de prospection (proposition "
                         "visible et rejetable) — c'est ce qui le rend installable par le "
                         "bouton, avec ses capacités jugées")
    args = ap.parse_args()

    base, inventaire = squelette(args.hf)

    from wama.model_manager.models import ModelType
    taxonomie = ', '.join(sorted(ModelType.values))
    # Exemple(s) de MÊME NATURE que la cible — un dépôt HuggingFace —, et de forme COMPOSÉE
    # quand la cible porte plusieurs fichiers de poids : c'est alors `composition` qu'il faut
    # montrer. Avant le 2026-09-19 c'était `sorted(glob)[:1]`, donc le premier par ordre
    # ALPHABÉTIQUE : `albert__bge-m3.json`, un modèle CLOUD servi par une API, sans poids, sans
    # composition et sans moteur — l'exemple le moins ressemblant du corpus.
    nb_poids = sum(1 for ligne in inventaire.splitlines()
                   if ligne.strip().lower().endswith(_EXT_POIDS))
    exemples = manifest_examples(EXEMPLES_DIR, prefer_source='huggingface__',
                                 want_composed=nb_poids > 1, limit=2)
    user_msg = (f'TAXONOMIE model_type (fermée) : {taxonomie}\n\n'
                f'EXEMPLE de manifeste `model` valide :\n{exemples}\n\n'
                f'SQUELETTE mécanique (à COMPLÉTER, jamais contredire) :\n'
                f'{json.dumps(base, ensure_ascii=False, indent=1)}\n\n'
                f'FICHIERS DE POIDS du dépôt :\n{inventaire}\n\n'
                f'CARTE (extrait) :\n{_readme(args.hf)}\n\n'
                'Complète le manifeste (model_type, description(s), capabilities, '
                'composition si multi-composants). Réponds {"manifest": …, "concerns": […]}.')

    if args.dry_run:
        print(f"[scout] exemples : {len(exemples)} caractères, forme "
              f"{'COMPOSÉE' if nb_poids > 1 else 'simple'} ({nb_poids} fichier(s) de poids)")
        print('[scout] DRY-RUN — squelette mécanique :')
        print(json.dumps(base, ensure_ascii=False, indent=2))
        print(f'[scout] contexte LLM : {len(user_msg)} caractères, inventaire :')
        print(inventaire)
        return

    model = resolve_model(args.provider, 'dev', args.model)
    print(f'[scout] {args.provider} / {model} | dépôt : {args.hf}')
    reponse = extract_json(call_llm(args.provider, model, PROMPT, user_msg))
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
        'provider': args.provider, 'model': model, 'provenance': f'huggingface:{args.hf}',
        'validation_errors': erreurs, 'concerns': concerns, 'manifest': manifest,
    })
    print(f'[scout] → {sortie.relative_to(REPO_ROOT)}')
    print(f'[scout] validation : {len(erreurs)} erreur(s)'
          + (f' — {erreurs[:3]}' if erreurs else ' — manifeste VALIDE'))
    if concerns:
        print(f'[scout] concerns : {concerns[:3]}')

    # ── Vers la route commune (2026-09-19) : le manifeste devient un CANDIDAT, donc quelque
    # chose que le bouton « Installer » sait installer — avec les capacités JUGÉES ici, au
    # lieu de les laisser mourir dans `outputs/` et de les redécouvrir à l'installation.
    # Jamais sur un manifeste invalide : un candidat sans catégorie n'est pas installable.
    if args.seed_candidate:
        if erreurs:
            print('[scout] ⚠ candidat NON écrit : le manifeste ne valide pas')
        else:
            from wama.model_manager.services.prospector import seed_candidate_from_manifest
            pose = seed_candidate_from_manifest(manifest)
            print(f"[scout] candidat : {pose.get('model_key') or pose.get('error')}"
                  + (' (créé)' if pose.get('created') else ' (rafraîchi)' if pose.get('ok')
                     else ''))


if __name__ == '__main__':
    main()
