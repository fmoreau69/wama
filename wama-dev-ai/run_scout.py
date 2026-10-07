#!/usr/bin/env python3
"""
Rôle « scout » — dépôt de MODÈLE (HuggingFace, ou VERSION GitHub depuis le 2026-10-07 :
`--github owner/repo:tag [--asset fichier]`) → manifeste `model` (pendant du librarian,
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
    python wama-dev-ai/run_scout.py --github Phhofm/models:4xNomosUni_span_multijpg \
        --asset 4xNomosUni_span_multijpg_fp32_opset17.onnx --provider albert --seed-candidate
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
    REPO_ROOT, add_llm_arguments, call_llm, enforce_category_facts, enforce_component_facts,
    enforce_engine_facts, enforce_resolution_facts, enforce_task_facts, extract_json, fetch,
    manifest_examples, model_vocabularies, resolve_model, write_output)

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


def github_skeleton(ref: str, asset: str = '') -> tuple[dict, str, str]:
    """(squelette, inventaire, carte) d'une VERSION GitHub `owner/repo:tag` — ZÉRO LLM ici.

    Le pendant de `squelette` (2026-10-07, pilote `github`) : la version est lue sur l'API
    GitHub (`prospector.github_release`), la licence est celle que SON texte déclare, le fichier
    retenu devient le composant `model` (une version publie des variantes : fp32/fp16, .pth,
    .safetensors, .onnx). Choisir entre plusieurs fichiers de poids serait deviner : `--asset`
    le dit, sinon l'inventaire est rendu et rien n'est écrit. L'empreinte n'est PAS dans le
    manifeste (le formalisme n'en a pas) : le semis du candidat la relit ou la mesure.
    """
    from wama.model_manager.services.model_installer import github_platform_ref, github_release_of
    from wama.model_manager.services.prospector import (
        github_release, github_release_license, github_release_scale)

    repo, tag = github_release_of(ref)
    if not (repo and tag):
        raise SystemExit(f"[scout] --github attend « owner/repo:tag », reçu {ref!r}")
    release = github_release(ref)
    if release is None:
        raise SystemExit(f"[scout] API GitHub injoignable pour {ref}")
    if not release:
        raise SystemExit(f"[scout] aucune version {tag!r} dans {repo}")
    files = [(a.get('name', ''), int(a.get('size') or 0)) for a in release.get('assets') or []]
    weights = [(n, t) for n, t in files if n.lower().endswith(_EXT_POIDS)]
    inventory = '\n'.join(f'  {t / 1024 ** 2:9.2f} Mo  {n}' for n, t in weights)
    if not asset:
        if len(weights) != 1:
            raise SystemExit(f"[scout] {len(weights)} fichiers de poids dans {ref} — en choisir un "
                             f"par --asset :\n{inventory}")
        asset = weights[0][0]
    if asset not in dict(files):
        raise SystemExit(f"[scout] {asset!r} absent de {ref} :\n{inventory}")
    ext = asset.rsplit('.', 1)[-1].lower()
    manifest = {
        'manifest_kind': 'model',
        'key': f'github:{ref}',
        'schema_version': '1.0',
        'name': tag,
        'description': '',
        'world': 'transverse',
        'visibility': 'public',
        'projects': [],
        'source': {'type': 'extract', 'ref': f'scout:github:{ref}'},
        'body': {
            'identity': {
                'model_type': None,          # ← jugement LLM (taxonomie fermée)
                'source': 'github',
                'license': github_release_license(release) or None,
                'author': repo.partition('/')[0],
                'platform_ref': github_platform_ref(ref),
                'description_short': None,   # ← jugement LLM
            },
            'resources': {'disk_gb': round(dict(files)[asset] / 1024 ** 3, 4)},
            'formats': {},
            # Le fichier RETENU est l'anatomie — un composant, nommé (fait, pas jugement).
            'composition': {'components': [{'role': 'model', 'pattern': asset, 'format': ext}]},
            # ← jugement LLM (task/modalities) ; le facteur, quand la version le DÉCLARE, est un
            # fait (le pendant des `SCALE_KEYS` d'un config.json HF) et re-prime ensuite.
            'capabilities': ({'scale': github_release_scale(release)}
                             if github_release_scale(release) else {}),
            'provenance': {'is_proposed': False},
            'extra_info': {'published_at': release.get('published_at'),
                           'release_assets': [n for n, _ in files]},
        },
    }
    return manifest, inventory, (release.get('body') or '(texte de version vide)')[:8000]


def _readme(hf_id: str, limit: int = 8000) -> str:
    try:
        return fetch(f'https://huggingface.co/{hf_id}/raw/main/README.md')[:limit]
    except Exception:
        return '(README indisponible)'


def main():
    ap = argparse.ArgumentParser()
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument('--hf', help='Dépôt HuggingFace org/nom')
    target.add_argument('--github', help='Version GitHub owner/repo:tag (poids publiés dans '
                                         'une release)')
    ap.add_argument('--asset', default='',
                    help='--github : le fichier de la version à retenir (requis si elle en '
                         'publie plusieurs)')
    add_llm_arguments(ap, role='dev')
    ap.add_argument('--dry-run', action='store_true',
                    help='Squelette + contexte seulement, AUCUN appel LLM (test sans GPU)')
    ap.add_argument('--seed-candidate', action='store_true',
                    help="Écrit aussi le manifeste en CANDIDAT de prospection (proposition "
                         "visible et rejetable) — c'est ce qui le rend installable par le "
                         "bouton, avec ses capacités jugées")
    args = ap.parse_args()

    ref = args.hf or args.github
    if args.github:
        base, inventaire, card = github_skeleton(args.github, args.asset)
    else:
        base, inventaire = squelette(args.hf)
        card = _readme(args.hf)

    # Exemple(s) de MÊME NATURE que la cible — un dépôt HuggingFace —, et de forme COMPOSÉE
    # quand la cible porte plusieurs fichiers de poids : c'est alors `composition` qu'il faut
    # montrer. Avant le 2026-09-19 c'était `sorted(glob)[:1]`, donc le premier par ordre
    # ALPHABÉTIQUE : `albert__bge-m3.json`, un modèle CLOUD servi par une API, sans poids, sans
    # composition et sans moteur — l'exemple le moins ressemblant du corpus.
    nb_poids = sum(1 for ligne in inventaire.splitlines()
                   if ligne.strip().lower().endswith(_EXT_POIDS))
    if args.github:
        # Une version publie des VARIANTES d'un même modèle ; seul le fichier retenu en est le
        # poids — la forme à montrer est la simple.
        nb_poids = len(base['body']['composition']['components'])
    exemples = manifest_examples(EXEMPLES_DIR, prefer_source='huggingface__',
                                 want_composed=nb_poids > 1, limit=2)
    # Les vocabulaires FERMÉS, servis par le code et partagés avec le rôle `model` (2026-09-30) :
    # la taxonomie `model_type` seule ne suffisait pas — sans INPUT_TYPES, qwen3.8 a déclaré
    # `audio`/`image` comme entrées de LongCat-Video-Avatar (manifeste invalide).
    user_msg = (f'VOCABULAIRES AUTORISÉS (choisir dedans, ne rien inventer) :\n'
                f'{model_vocabularies()}\n\n'
                f'EXEMPLE de manifeste `model` valide :\n{exemples}\n\n'
                f'SQUELETTE mécanique (à COMPLÉTER, jamais contredire) :\n'
                f'{json.dumps(base, ensure_ascii=False, indent=1)}\n\n'
                f'FICHIERS DE POIDS du dépôt :\n{inventaire}\n\n'
                f'CARTE (extrait) :\n{card}\n\n'
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
    print(f'[scout] {args.provider} / {model} | dépôt : {ref}')
    reponse = extract_json(call_llm(args.provider, model, PROMPT, user_msg))
    manifest = reponse.get('manifest') or {}
    concerns = reponse.get('concerns') or []

    # ── Les FAITS mécaniques re-priment sur la réponse (le LLM propose, les faits tranchent).
    ident = base['body']['identity']
    facts = [
        (('key',), base['key']),
        (('body', 'identity', 'source'), ident['source']),
        (('body', 'identity', 'license'), ident['license']),
        (('body', 'identity', 'author'), ident['author']),
        (('body', 'identity', 'platform_ref'), ident['platform_ref']),
        (('body', 'resources', 'disk_gb'), base['body']['resources']['disk_gb']),
    ]
    if args.github:
        # Le fichier retenu EST l'anatomie : un fait de la version, pas un jugement.
        facts.append((('body', 'composition', 'components'),
                      base['body']['composition']['components']))
        if base['body']['capabilities'].get('scale'):
            facts.append((('body', 'capabilities', 'scale'),
                          base['body']['capabilities']['scale']))
    else:
        facts.append((('body', 'identity', 'hf_id'), ident['hf_id']))
    for chemin, valeur in facts:
        cible = manifest
        for k in chemin[:-1]:
            cible = cible.setdefault(k, {})
        cible[chemin[-1]] = valeur
    if not args.github:
        enforce_task_facts(manifest, args.hf, concerns)
        enforce_engine_facts(manifest, args.hf, concerns)
        enforce_resolution_facts(manifest, args.hf, concerns)
        # L'anatomie, comme au rôle `model` (2026-10-06) : le candidat qu'on sème porte ce que
        # l'installation tirera — sans elle, toutes les variantes d'un export ONNX.
        enforce_component_facts(manifest, args.hf, concerns)
    else:
        # Les gardes qui valent pour une version : l'inventaire est le fichier retenu (le moteur
        # que son FORMAT prouve, aucune taille fixe pour une tâche dont la sortie suit l'entrée).
        # Les gardes lues dans un `config.json` HF (tâche, anatomie) n'ont rien à lire ici.
        retained = [c['pattern'] for c in base['body']['composition']['components']]
        enforce_engine_facts(manifest, ref, concerns, lister=lambda _ref: retained)
        enforce_resolution_facts(manifest, ref, concerns, lister=lambda _ref: retained)
    # La catégorie suit la tâche (les deux sources) : c'est elle qui range les poids et ancre
    # les requêtes du catalogue par capacité.
    enforce_category_facts(manifest, concerns)

    from wama.common.manifests.ingest import validate
    erreurs = list(validate(manifest) or [])

    sortie = write_output('scout', ref.replace(':', '_'), {
        'provider': args.provider, 'model': model,
        'provenance': f"{'github' if args.github else 'huggingface'}:{ref}",
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
