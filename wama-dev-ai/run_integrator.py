#!/usr/bin/env python3
"""
Rôle « integrator » — manifeste `model` (+ besoin éventuel) → décision d'intégration :
une app WAMA EXISTANTE porte-t-elle déjà la tâche, ou faut-il GÉNÉRER une app ?
(Étape 4 de la route PROSPECTION_PIPELINE — « matching besoin↔capacités à écrire »,
consigné depuis le 2026-07-17. Le rôle `architect` existant est AUTRE CHOSE : conseil
d'architecture de code générique.)

Pilote BORNÉ :
  1. contexte MÉCANIQUE : catalogue d'apps réel (`APP_CATALOG` + descriptions longues,
     types d'entrée/sortie) + référentiel des modèles installés du même type ;
  2. un seul appel Ollama → recommandation JSON (app existante | génération) ;
  3. contrôles MÉCANIQUES : l'app recommandée doit exister au catalogue ; `new_app`
     renvoie vers la route de génération (WAMA_APP_GENERATION_ROUTE.md), jamais exécutée ;
  4. écrit dans `outputs/` avec PENDING_HUMAN_VALIDATION — ne décide JAMAIS seul.

`--dry-run` : contexte seulement, AUCUN appel LLM (test sans charge sur l'Ollama hôte).

La source du manifeste est soit un FICHIER (`--manifest`), soit une LIGNE de la base
(`--candidate <clé>`) : un candidat de prospection est déjà un manifeste `model`, et c'est
lui que le bouton « Installer » installera — juger la ligne plutôt qu'un fichier déposé à
côté garantit que le jugement porte sur l'objet réel (2026-09-19).

Usage (racine du repo, venv_linux) :
    python wama-dev-ai/run_integrator.py --candidate proposed:hf:nvidia/canary-1b-v2 --dry-run
    python wama-dev-ai/run_integrator.py --manifest manifests/models/composer__minimax-music3.json --dry-run
    python wama-dev-ai/run_integrator.py --manifest wama-dev-ai/outputs/scout_… .json --besoin "générer des chansons avec paroles"
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
    REPO_ROOT, add_llm_arguments, call_llm, extract_json, resolve_model, write_output)

PROMPT = (Path(__file__).parent / 'prompts' / 'integrator.txt').read_text(encoding='utf-8')


def contexte_apps() -> str:
    """Le catalogue d'apps RÉEL, compacté pour le juge — capacités déclarées, rien d'inventé."""
    from wama.common.app_registry import APP_CATALOG
    lignes = []
    for app_id, cfg in sorted(APP_CATALOG.items()):
        lignes.append(
            f"- {app_id} ({cfg.get('label', app_id)}) : {cfg.get('description', '')} "
            f"| entrées: {', '.join(cfg.get('input_types', ()) or ('?',))} "
            f"| sorties: {', '.join(str(t) for t in (cfg.get('output_types', ()) or ('?',)))}"
            + (f"\n    {cfg['description_long']}" if cfg.get('description_long') else ''))
    return '\n'.join(lignes)


def referentiel(model_type: str) -> str:
    """Modèles installés du même type — ce que WAMA sait DÉJÀ faire sur ce terrain."""
    if not model_type:
        return '(type inconnu)'
    from wama.model_manager.models import AIModel
    lignes = [f"- {m.model_key} ({m.name}) task={m.capabilities.get('task', '?')}"
              for m in AIModel.objects.filter(model_type=model_type, is_proposed=False,
                                              is_available=True)[:15]]
    return '\n'.join(lignes) or '(aucun modèle installé de ce type)'


def main():
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument('--manifest',
                        help='Manifeste model (corpus manifests/models/ ou sortie du scout)')
    source.add_argument('--candidate',
                        help="Clé d'une ligne du catalogue ou d'un CANDIDAT de prospection "
                             "(proposed:hf:org/nom) — son manifeste est EXTRAIT de la base")
    ap.add_argument('--besoin', default='', help="Besoin utilisateur (texte libre, optionnel)")
    add_llm_arguments(ap, role='dev')
    ap.add_argument('--dry-run', action='store_true',
                    help='Contexte seulement, AUCUN appel LLM (test sans GPU)')
    args = ap.parse_args()

    # Le candidat de prospection EST DÉJÀ un manifeste `model` (`extract_model` en extrait
    # identité, capacités et provenance : is_proposed / proposal_kind / confidence). Lire la
    # LIGNE plutôt qu'un fichier d'`outputs/` (2026-09-19, alignement des routes) : l'objet
    # jugé est alors le même que celui que le bouton installera — un fichier déposé à côté se
    # périme dès que le candidat est rafraîchi, réévalué ou rejeté.
    if args.candidate:
        from wama.common.manifests.builtin.model import extract_model
        manifeste = extract_model(args.candidate)
        if manifeste is None:
            raise SystemExit(f"{args.candidate} : aucune ligne de catalogue ni candidat "
                             "de prospection sous cette clé")
        origine = f"candidate:{args.candidate}"
    else:
        brut = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        manifeste = brut.get('manifest', brut)   # sortie de scout OU fichier corpus direct
        origine = str(args.manifest)
    if manifeste.get('manifest_kind') != 'model':
        raise SystemExit(f"{origine} : kind {manifeste.get('manifest_kind')!r}, "
                         "attendu 'model'")
    body = manifeste.get('body') or {}
    mtype = (body.get('identity') or {}).get('model_type') or ''

    user_msg = (
        f"CATALOGUE des apps WAMA (capacités déclarées) :\n{contexte_apps()}\n\n"
        f"MODÈLES déjà installés du type '{mtype}' :\n{referentiel(mtype)}\n\n"
        f"MANIFESTE du modèle candidat :\n"
        f"{json.dumps(manifeste, ensure_ascii=False, indent=1)[:8000]}\n\n"
        + (f"BESOIN utilisateur : {args.besoin}\n\n" if args.besoin else '')
        + "Décide : app existante (laquelle) ou génération d'app ? Réponds le JSON du contrat.")

    if args.dry_run:
        print('[integrator] DRY-RUN — contexte :')
        print(user_msg[:4000])
        print(f'[integrator] contexte total : {len(user_msg)} caractères')
        return

    model = resolve_model(args.provider, 'dev', args.model)
    print(f'[integrator] {args.provider} / {model} | manifeste : {origine}')
    verdict = extract_json(call_llm(args.provider, model, PROMPT, user_msg))

    # ── Contrôles MÉCANIQUES : jamais d'app imaginée, new_app = route existante.
    from wama.common.app_registry import APP_CATALOG
    controles = []
    app = verdict.get('app')
    if verdict.get('decision') == 'existing_app' and app not in APP_CATALOG:
        controles.append(f"app recommandée inconnue du catalogue : {app!r}")
    if verdict.get('decision') == 'new_app':
        controles.append("génération d'app = route WAMA_APP_GENERATION_ROUTE.md, "
                         "sur validation humaine uniquement")

    sortie = write_output('integrator', manifeste.get('key', 'inconnu'), {
        'provider': args.provider, 'model': model,
        'manifest_source': origine, 'besoin': args.besoin,
        'mechanical_checks': controles, 'verdict': verdict,
    })
    print(f'[integrator] → {sortie.relative_to(REPO_ROOT)}')
    print(f"[integrator] décision : {verdict.get('decision')} → {verdict.get('app')} "
          f"(confiance {verdict.get('confidence')})")
    for c in controles:
        print(f'[integrator] ⚠ {c}')


if __name__ == '__main__':
    main()
