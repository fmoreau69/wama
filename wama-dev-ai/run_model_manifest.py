#!/usr/bin/env python3
"""
Rôle « model » — dépôt de modèle (HuggingFace) ou snapshot INSTALLÉ → manifeste `model`
(SPEC §7.4, kind `model`).

3ᵉ rôle producteur de manifestes après `librarian` (kind `library`) et `scout`. Il comble
le trou constaté le 2026-09-03 en montant les backends B2 : la chaîne savait faire écrire
un manifeste de LIBRAIRIE par l'agent, pas un manifeste de MODÈLE — c'est pourtant là que
vit la déclaration qui manque à chaque modèle installé sans backend
(`composition.runtime.engine`, `capabilities`), et elle finissait donc écrite à la main.

Pilote BORNÉ (mêmes leçons que librarian) :
  1. rassemble les SOURCES BRUTES (README + config.json + inventaire de fichiers) — jamais
     l'extraction mécanique : la lui donner ferait recopier au lieu de traduire, et le
     contrôle du §3 ne prouverait plus rien ;
  2. sert les VOCABULAIRES depuis le code (tâches, clés canoniques, ModelType/ModelSource,
     moteurs déjà servis) — l'agent ne les invente pas, il choisit dedans ;
  3. un seul appel LLM (Ollama local, ou `--provider albert` — la garde GPU ci-dessous ne
     vaut alors plus), avec le corpus `manifests/models/` en exemple (un COMPOSÉ + un
     simple, choisis mécaniquement) ;
  4. sortie jugée comme « Valider » la jugera (`proposals.judge` : la forme, puis l'anatomie
     contre les fichiers du dépôt), UNE reprise par le modèle quand le juge refuse, puis DIFFÉE
     contre la vérité terrain (`extract_model`) sur les seuls champs que la découverte MESURE ;
  5. écrit dans `outputs/` avec PENDING_HUMAN_VALIDATION et DÉPOSE la proposition au magasin
     en bac à sable (`manifests.proposals.propose`, 2026-09-29) — ne PROJETTE jamais. La
     projection est le geste « Valider » du model manager (`proposals.apply`).

⚠ GARDE GPU — le rôle COOPÈRE avec le mode dépannage, il ne s'y dérobe pas (recadrage
Fabien, 2026-09-03) : `WAMA_GPU_SAFE_MODE` est un interrupteur de CONDITIONS (« réduire la
SUPERPOSITION de charges »), pas une interdiction de charger. Sa parade est outillée par le
gouverneur, et c'est elle qu'on emploie : `wait_for_free_vram()` avant l'appel (on ne
s'empile pas sur une charge en cours — l'attente laisse les résidences expirer) et
`pipeline_keep_alive()` → `keep_alive='0'` (le modèle est déchargé SITÔT la réponse rendue,
au lieu de ~5 min de résidence). Refuser en bloc, comme le faisait la 1ʳᵉ version de ce
pilote, aurait rendu le rôle inutilisable pendant tout le mode dépannage — l'excès inverse
du triage VLM qui, lui, ignorait la parade et a crashé l'hôte deux fois le 02/09.
`--force` saute l'ATTENTE (jamais le keep_alive) pour un GO explicite.
Depuis le 2026-10-13, cette garde est `role_utils.local_llm_guard`, partagée par les six rôles.

Usage (depuis la racine du repo, venv_linux) :
    python wama-dev-ai/run_model_manifest.py --catalog huggingface:Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
    python wama-dev-ai/run_model_manifest.py --hf Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402

django.setup()

from role_utils import (  # noqa: E402
    add_llm_arguments, call_llm, card_languages, enforce_adapter_parent, enforce_category_facts,
    enforce_component_facts, enforce_engine_facts, enforce_engine_read_anatomy,
    enforce_identity,
    enforce_language_facts, enforce_modality_facts, enforce_owned_elsewhere,
    enforce_resolution_facts, enforce_task_facts, enforce_vendor_engine, extract_json,
    fetch as _fetch,
    local_llm_guard, manifest_examples, model_vocabularies, resolve_model, write_output)

PROMPT = (Path(__file__).parent / 'prompts' / 'model.txt').read_text(encoding='utf-8')
EXEMPLES_DIR = REPO_ROOT / 'manifests' / 'models'
MAX_SOURCE_CHARS = 20000   # tâche étroite : on tronque plutôt que de faire dériver
MAX_FICHIERS = 60          # inventaire : de quoi voir l'anatomie, pas un dump de dépôt


# ── Sources (matière BRUTE, jamais l'extraction mécanique) ───────────────────────
def _snapshot_dir(depot: Path):
    """Dernière révision d'un dépôt HF sur disque (`models--org--nom/snapshots/<rev>`)."""
    racine = depot / 'snapshots'
    if not racine.is_dir():
        return depot if depot.is_dir() else None
    revs = sorted((d for d in racine.iterdir() if d.is_dir()),
                  key=lambda d: d.stat().st_mtime)
    return revs[-1] if revs else None


def sources_catalog(model_key):
    """Snapshot INSTALLÉ : README + config.json + inventaire des fichiers (avec tailles).

    L'inventaire est ce qui permet de proposer `composition.components` (motifs de
    fichiers) : sans lui, l'anatomie d'un modèle composé est indevinable.
    """
    from wama.model_manager.models import AIModel
    row = AIModel.objects.filter(model_key=model_key).first()
    if row is None:
        raise SystemExit(f"Aucun AIModel de clé {model_key!r} — `sync_models` d'abord, "
                         "ou utiliser --hf pour un modèle non installé.")
    chemin = (row.extra_info or {}).get('path') or row.local_path or ''
    depot = _snapshot_dir(Path(chemin)) if chemin else None
    if depot is None or not depot.is_dir():
        raise SystemExit(f"Poids introuvables sur disque pour {model_key!r} (chemin : {chemin!r}).")

    # ⚠ ORDRE : structuré d'ABORD, README en DERNIER — la leçon de `librarian.sources_dist`,
    # mesurée à nouveau ici le 03/09 : un README de modèle pèse 60 k caractères, il DÉBORDE
    # seul le budget de troncature et emportait l'INVENTAIRE placé après lui. Or l'inventaire
    # est ce qui révèle l'anatomie (mesuré sur Qwen3-TTS : model.safetensors 3,8 Go +
    # speech_tokenizer/model.safetensors 682 Mo = modèle COMPOSÉ) : le tronquer, c'est
    # garantir un `composition.components` vide.
    parts = []
    fichiers = sorted((p for p in depot.rglob('*') if p.is_file()),
                      key=lambda p: p.stat().st_size, reverse=True)[:MAX_FICHIERS]
    inventaire = '\n'.join(f'{p.relative_to(depot)}  ({p.stat().st_size / 1e6:.1f} Mo)'
                           for p in fichiers)
    parts.append(f'===== INVENTAIRE DES FICHIERS (snapshot) =====\n{inventaire}')
    for nom in ('config.json', 'generation_config.json', 'preprocessor_config.json', 'README.md'):
        f = depot / nom
        if f.is_file():
            parts.append(f'===== {nom} =====\n{f.read_text(encoding="utf-8", errors="replace")}')
    return f'snapshot:{depot}', '\n\n'.join(parts)


def sources_hf(repo_id):
    """Dépôt HuggingFace non installé : README + config.json depuis le Hub (via proxy)."""
    parts = []
    for nom in ('config.json', 'generation_config.json', 'README.md'):   # README EN DERNIER
        try:
            txt = _fetch(f'https://huggingface.co/{repo_id}/raw/main/{nom}')
            parts.append(f'===== {nom} =====\n{txt}')
        except Exception:
            continue
    if not parts:
        raise SystemExit(f"Aucune source récupérable pour {repo_id} (réseau/proxy ? dépôt gated ?).")
    return f'https://huggingface.co/{repo_id}', '\n\n'.join(parts)


# Vocabulaires SERVIS par le code : `role_utils.model_vocabularies` (partagé avec le scout).

def exemples() -> str:
    """Deux manifestes du corpus : un COMPOSÉ (montre `composition`) et un simple.

    Le choix PAR NATURE vit dans `role_utils.manifest_examples` depuis le 2026-09-19 : le
    scout en avait besoin aussi (il prenait, lui, le premier fichier par ordre alphabétique),
    et un few-shot choisi au hasard enseigne la mauvaise forme.
    """
    return manifest_examples(EXEMPLES_DIR, limit=2)


# ── Contrôles mécaniques (le LLM propose, la chaîne d'ingest juge) ───────────────
#: Champs que la DÉCOUVERTE mesure ou tient : le manifeste ne doit pas les contredire.
CHEMINS_DIFF = (
    ('body', 'identity', 'license'),
    ('body', 'identity', 'author'),
    ('body', 'identity', 'model_type'),
    ('body', 'identity', 'source'),
    ('body', 'formats', 'format'),
)


def _lire(d, chemin):
    for k in chemin:
        d = (d or {}).get(k)
    return d


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--catalog', help='Clé AIModel d\'un modèle INSTALLÉ (huggingface:org/nom)')
    g.add_argument('--hf', help='Dépôt HuggingFace org/nom (non installé)')
    add_llm_arguments(ap, role='dev')     # porte aussi --force et --wait-max (garde GPU commune)
    args = ap.parse_args()

    provenance, matiere = (sources_catalog(args.catalog) if args.catalog
                           else sources_hf(args.hf))
    # Les sources COMPLÈTES servent aux contrôles mécaniques ; seul le LLM lit la version tronquée.
    full_sources = matiere
    matiere = matiere[:MAX_SOURCE_CHARS]

    # Le modèle vient du tirage du NIVEAU DÉVELOPPEMENT, comme les cinq autres rôles (2026-10-13).
    # Ce rôle-ci prenait, en local, la chaîne de `config.py` (`select_model_for_role('dev')`) :
    # il ÉCHAPPAIT au bridage que le README annonçait global, et son besoin VRAM était celui de la
    # table de `config.py`. Le besoin se lit désormais au catalogue, dans la garde commune.
    model = resolve_model(args.provider, 'dev', args.model)
    print(f'[model] {args.provider} / {model} | provenance : {provenance}')
    # ── Coopération avec le mode dépannage GPU (cf. docstring) : la garde COMMUNE ──
    keep_alive = local_llm_guard(args.provider, model, force=args.force, wait_max=args.wait_max,
                                 log=lambda m: print(f'[model] {m}'))

    user_msg = (f'EXEMPLES de manifestes `model` valides :\n{exemples()}\n\n'
                f'VOCABULAIRES AUTORISÉS (choisir dedans, ne rien inventer) :\n{model_vocabularies()}\n\n'
                f'SOURCES du modèle à traduire :\n{matiere}\n\n'
                f'Produis le manifeste `model` de ce modèle (JSON seul).')
    reponse = call_llm(args.provider, model, PROMPT, user_msg, keep_alive=keep_alive)
    manifest = extract_json(reponse)
    concerns = enforce_facts(manifest, args, provenance, full_sources)
    for c in concerns:
        print(f'[model] {c}')

    # Le JUGE de « Valider » (forme, puis ce que seul le réel peut dire — l'anatomie contre les
    # fichiers du dépôt), et UNE reprise quand il refuse (2026-11-07, ACE-Step par l'assistant) :
    # le rôle ne jugeait que la forme, se disait « VALIDE » d'une anatomie que « Valider »
    # refusait (l'encodeur de texte oublié), et la chaîne s'arrêtait dans la file. Le verdict est
    # rendu au modèle mot pour mot ; les faits mécaniques se rejouent sur sa reprise. La reprise
    # n'est gardée que si elle est moins refusée — sinon la première, avec son verdict.
    from wama.common.manifests.proposals import judge
    errors = judge(manifest)
    if errors:
        print(f'[model] « Valider » refuserait : {errors} — une reprise')
        reprise = (f'{user_msg}\n\nTA PROPOSITION :\n{json.dumps(manifest, ensure_ascii=False)}\n\n'
                   '« Valider » la REFUSERAIT :\n' + '\n'.join(f'- {e}' for e in errors)
                   + '\n\nCorrige ce qui est refusé, garde le reste, et rends le manifeste '
                     'complet (JSON seul).')
        try:
            second = extract_json(call_llm(args.provider, model, PROMPT, reprise,
                                           keep_alive=keep_alive))
        except (RuntimeError, ValueError) as e:
            second = None
            print(f'[model] reprise sans manifeste lisible ({e}) : la première est gardée')
        if second is not None:
            second_concerns = enforce_facts(second, args, provenance, full_sources)
            second_errors = judge(second)
            kept = len(second_errors) < len(errors)
            print(f'[model] reprise : {len(second_errors)} refus contre {len(errors)} — '
                  + ('gardée' if kept else 'écartée'))
            if kept:
                manifest, concerns, errors = second, second_concerns, second_errors
                for c in concerns:
                    print(f'[model] (reprise) {c}')

    cle = manifest.get('key') or args.catalog or ''
    divergences = {}
    try:
        from wama.common.manifests.builtin.model import extract_model
        verite = extract_model(cle)
    except Exception:
        verite = None
    if verite:
        for chemin in CHEMINS_DIFF:
            a, b = _lire(manifest, chemin), _lire(verite, chemin)
            if (a or None) != (b or None):
                divergences['.'.join(chemin)] = {'llm': a, 'mecanique': b}

    sortie = write_output('model', cle or 'inconnu', {
        'provider': args.provider,
        'model': model,
        'provenance': provenance,
        'validation_errors': errors,
        'divergences_vs_mecanique': divergences,
        'concerns': concerns,
        'manifest': manifest,
    })

    print(f'[model] → {sortie.relative_to(REPO_ROOT)}')
    # La proposition entre au MAGASIN, en bac à sable (2026-09-29) : c'est là que le geste
    # « Valider » du model manager la trouve (plan, puis application). Le fichier d'`outputs/`
    # reste la trace brute du rôle ; il n'est plus le seul endroit où la proposition existe.
    if cle:
        from wama.common.manifests.proposals import propose
        obj = propose(manifest, origin=str(sortie.relative_to(REPO_ROOT)))
        print(f'[model] proposition en attente de validation : {obj.manifest_kind}:{obj.key}'
              + (f' ({len(obj.errors)} erreur(s))' if obj.errors else ''))
    print(f'[model] « Valider » : {len(errors)} refus'
          + (f' — {errors[:3]}' if errors else ' — manifeste VALIDE'))
    if verite:
        print(f'[model] divergences vs extraction mécanique : {len(divergences)}'
              + (f' — {list(divergences)}' if divergences else ' — accord total'))
    else:
        print('[model] pas de vérité terrain (modèle non catalogué) — validation humaine seule')
    moteur = ((manifest.get('body') or {}).get('composition') or {}).get('runtime') or {}
    if moteur.get('engine'):
        print(f"[model] moteur proposé : {moteur['engine']} — à valider au model manager "
              "(section « Propositions »)")


def enforce_facts(manifest, args, provenance, full_sources) -> list:
    """Les FAITS MÉCANIQUES posés sur le manifeste du modèle, dans leur ordre ; rend les
    remarques. Rejoués sur une reprise : un fait ne dépend jamais de la réponse qui l'a précédé."""
    concerns = []
    # L'IDENTITÉ d'abord : c'est d'elle que dépendent tous les faits mécaniques qui suivent
    # (2026-10-01 : une clé d'un autre modèle a fait retirer un moteur valide).
    if args.catalog:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.get(model_key=args.catalog)
        enforce_identity(manifest, args.catalog,
                         row.hf_repo or args.catalog.split(':', 1)[-1], concerns, row.platform_ref)
    else:
        enforce_identity(manifest, f'huggingface:{args.hf}', args.hf, concerns)
    # Fait mécanique sur le moteur (partagé avec le scout) : `diffusers` doit être PROUVÉ.
    # Le dépôt se lit sur `platform_ref` (2026-10-27, `identity.hf_id` retiré du formalisme).
    from wama.common.external_sources import hf_repo
    repo_id = hf_repo(_lire(manifest, ('body', 'identity', 'platform_ref')))
    # Les langues que la FICHE déclare (le snapshot installé d'abord) — 2026-10-01, Kyutai.
    snapshot = provenance.split('snapshot:', 1)[1] if provenance.startswith('snapshot:') else None
    enforce_language_facts(manifest, card_languages(repo_id, snapshot), concerns)
    if repo_id:
        # La TÂCHE que la classe du config.json prouve (2026-10-06, Swin2SR) : AVANT la
        # résolution, qui ne s'applique pas à une tâche dont la sortie suit l'entrée.
        enforce_task_facts(manifest, repo_id, concerns)
        enforce_engine_facts(manifest, repo_id, concerns)
        enforce_resolution_facts(manifest, repo_id, concerns)
        # Moteur VENDORISÉ cité par les sources (2026-10-01, YuE2) : APRÈS le retrait d'un
        # moteur non prouvé, pour que le fait remplace la conjecture.
        enforce_vendor_engine(manifest, repo_id, full_sources, concerns)
        # L'anatomie d'un modèle SIMPLE, APRÈS le moteur (le format retenu peut en dépendre).
        enforce_component_facts(manifest, repo_id, concerns)
        # Le PARENT d'un adaptateur (2026-10-03, SheetSage2) : APRÈS l'anatomie, qu'il complète.
        enforce_adapter_parent(manifest, repo_id, concerns)
    if args.catalog:
        # Les poids que le code du moteur LIT sont des composants (2026-11-07, ACE-Step) : APRÈS
        # le moteur, sur l'inventaire même que « Valider » confronte (`anatomy_inventory`).
        from wama.model_manager.services.model_installer import anatomy_inventory
        enforce_engine_read_anatomy(manifest, anatomy_inventory(row), concerns)
    # La catégorie suit la tâche, quelle que soit la source (2026-10-07, garde partagée avec le
    # scout) — APRÈS `enforce_task_facts`, qui peut avoir corrigé la tâche. Les modalités aussi.
    enforce_category_facts(manifest, concerns)
    enforce_modality_facts(manifest, concerns)
    # Ce que d'autres processus possèdent — ressources, description — ne se propose pas.
    enforce_owned_elsewhere(manifest, concerns)
    return concerns


if __name__ == '__main__':
    main()
