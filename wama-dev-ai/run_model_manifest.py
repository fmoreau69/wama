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
  3. un seul appel Ollama, avec le corpus `manifests/models/` en exemple (un COMPOSÉ + un
     simple, choisis mécaniquement) ;
  4. sortie validée MÉCANIQUEMENT (`ingest.validate`) puis DIFFÉE contre la vérité terrain
     (`extract_model`) sur les seuls champs que la découverte MESURE ;
  5. écrit dans `outputs/` avec PENDING_HUMAN_VALIDATION — n'ingère JAMAIS en base.
     La projection reste le geste explicite `ingest.write_back(apply=True)`.

⚠ GARDE GPU (même famille que le triage VLM du smoke, `ui_smoke._vlm_triage`) : l'appel
Ollama charge un modèle dans la VRAM de l'hôte — le geste qui a tué la machine deux fois
le 2026-09-02. Le rôle consulte `WAMA_GPU_SAFE_MODE` et REFUSE de partir quand il est
actif ; `--force` reste possible pour un GO explicite. *Une garde se pose avec ses jumeaux.*

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

from config import select_model_for_role  # noqa: E402 (wama-dev-ai/config.py)
from role_utils import call_ollama, extract_json, fetch as _fetch, write_output  # noqa: E402

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


def sources_hf(hf_id):
    """Dépôt HuggingFace non installé : README + config.json depuis le Hub (via proxy)."""
    parts = []
    for nom in ('config.json', 'generation_config.json', 'README.md'):   # README EN DERNIER
        try:
            txt = _fetch(f'https://huggingface.co/{hf_id}/raw/main/{nom}')
            parts.append(f'===== {nom} =====\n{txt}')
        except Exception:
            continue
    if not parts:
        raise SystemExit(f"Aucune source récupérable pour {hf_id} (réseau/proxy ? dépôt gated ?).")
    return f'https://huggingface.co/{hf_id}', '\n\n'.join(parts)


# ── Vocabulaires SERVIS par le code (l'agent choisit dedans, il n'invente pas) ───
def vocabulaires() -> str:
    from wama.common.backends.manager import known_engines
    from wama.common.utils.model_capabilities import CANONICAL_CAPABILITIES
    from wama.model_manager.models import ModelSource, ModelTask, ModelType

    moteurs = sorted(known_engines())
    return (
        f"capabilities.task — valeurs autorisées : {', '.join(sorted(ModelTask.values))}\n"
        f"identity.model_type — valeurs autorisées : {', '.join(sorted(ModelType.values))}\n"
        f"identity.source — valeurs autorisées : {', '.join(sorted(ModelSource.values))}\n"
        f"clés canoniques de `capabilities` : {', '.join(sorted(CANONICAL_CAPABILITIES))}\n"
        f"composition.runtime.engine — moteurs DÉJÀ SERVIS par un backend : "
        f"{', '.join(moteurs) or '(aucun)'}\n"
    )


def exemples() -> str:
    """Deux manifestes du corpus : un COMPOSÉ (montre `composition`) et un simple."""
    compose, simple = None, None
    for f in sorted(EXEMPLES_DIR.glob('*.json')):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        if ((d.get('body') or {}).get('composition') or {}).get('runtime'):
            compose = compose or f
        else:
            simple = simple or f
        if compose and simple:
            break
    choisis = [f for f in (compose, simple) if f]
    return '\n\n'.join(f.read_text(encoding='utf-8') for f in choisis)


# ── Contrôles mécaniques (le LLM propose, la chaîne d'ingest juge) ───────────────
#: Champs que la DÉCOUVERTE mesure ou tient : le manifeste ne doit pas les contredire.
CHEMINS_DIFF = (
    ('body', 'identity', 'license'),
    ('body', 'identity', 'author'),
    ('body', 'identity', 'hf_id'),
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
    ap.add_argument('--model', default=None, help='Modèle Ollama (défaut : rôle dev)')
    ap.add_argument('--force', action='store_true',
                    help='Passer outre WAMA_GPU_SAFE_MODE (GO explicite)')
    args = ap.parse_args()

    # Garde GPU — cf. docstring (l'appel Ollama charge un modèle sur l'hôte).
    from wama.common.services.resource_governor import gpu_safe_mode
    if gpu_safe_mode() and not args.force:
        raise SystemExit(
            "[model] REFUS : WAMA_GPU_SAFE_MODE est actif — un appel Ollama charge un "
            "modèle dans la VRAM de l'hôte (le geste qui a crashé la machine le 02/09). "
            "Relancer avec --force sur GO explicite, ou lever le mode dépannage.")

    provenance, matiere = (sources_catalog(args.catalog) if args.catalog
                           else sources_hf(args.hf))
    matiere = matiere[:MAX_SOURCE_CHARS]

    model = args.model or select_model_for_role('dev')[1].ollama_id
    print(f'[model] modèle : {model} | provenance : {provenance}')

    user_msg = (f'EXEMPLES de manifestes `model` valides :\n{exemples()}\n\n'
                f'VOCABULAIRES AUTORISÉS (choisir dedans, ne rien inventer) :\n{vocabulaires()}\n\n'
                f'SOURCES du modèle à traduire :\n{matiere}\n\n'
                f'Produis le manifeste `model` de ce modèle (JSON seul).')
    reponse = call_ollama(model, PROMPT, user_msg)
    manifest = extract_json(reponse)

    from wama.common.manifests.ingest import validate
    erreurs = list(validate(manifest) or [])

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
        'model': model,
        'provenance': provenance,
        'validation_errors': erreurs,
        'divergences_vs_mecanique': divergences,
        'manifest': manifest,
    })

    print(f'[model] → {sortie.relative_to(REPO_ROOT)}')
    print(f'[model] validation : {len(erreurs)} erreur(s)'
          + (f' — {erreurs[:3]}' if erreurs else ' — manifeste VALIDE'))
    if verite:
        print(f'[model] divergences vs extraction mécanique : {len(divergences)}'
              + (f' — {list(divergences)}' if divergences else ' — accord total'))
    else:
        print('[model] pas de vérité terrain (modèle non catalogué) — validation humaine seule')
    moteur = ((manifest.get('body') or {}).get('composition') or {}).get('runtime') or {}
    if moteur.get('engine'):
        print(f"[model] moteur proposé : {moteur['engine']} — projeter avec "
              "`ingest.write_back(manifest, apply=True)` APRÈS validation humaine")


if __name__ == '__main__':
    main()
