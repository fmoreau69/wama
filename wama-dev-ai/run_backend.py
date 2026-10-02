#!/usr/bin/env python3
"""
Rôle « backend » — le LLM de la MARCHE B2 (ROUTE §10.3) : écrit le backend WAMA d'un modèle
installé dont le moteur n'a pas encore d'exécutant.

La route le prévoyait depuis le 03/09 — « le LLM de la marche B doit piocher dans le vivier
pour s'inspirer du plus approchant » (`backend_inventory`, écrit pour lui) — sans que rien ne
l'implémente : les trois backends B2 livrés (Table Transformer, Audio8, Qwen3-TTS) ont été écrits
à la main. Premier essai d'autonomie décidé par Fabien le 2026-09-29, sur l'intégration de
modèles, avant les apps média.

Pilote BORNÉ (même discipline que les cinq autres rôles) :
  1. matière MÉCANIQUE : manifeste du modèle (anatomie + moteur — sans eux, REFUS), source du
     CONTRAT dérivé de la tâche, extrait du contrat commun, 1-2 VOISINS tirés du vivier (même
     contrat, même moteur), inventaire du snapshot et code d'inférence PUBLIÉ avec le modèle ;
  2. UN appel LLM (bridé au niveau développement, `role_utils.resolve_model`) ;
  3. contrôles MÉCANIQUES (`backend_proposals.check_source`), résolution SIMULÉE par
     l'inventaire, smoke CPU PAR CONTRAT (`backend_proposals.SMOKES` : génération d'images, ou
     transcription d'un extrait de parole réelle face à sa référence — 2026-10-02) ;
  4. écrit la proposition dans `outputs/` (PENDING_HUMAN_VALIDATION). L'ÉCRITURE dans
     `wama/common/backends/` est le geste « Valider » du model manager, jamais ce script.

Usage (racine du repo, venv_linux) :
    python wama-dev-ai/run_backend.py --catalog huggingface:Bartholomheow/Supra2-IMG-ONNX
    python wama-dev-ai/run_backend.py --catalog … --dry-run      # matière seule, aucun LLM
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402

django.setup()

from role_utils import add_llm_arguments, call_llm, resolve_model, write_output  # noqa: E402

PROMPT = (Path(__file__).parent / 'prompts' / 'backend.txt').read_text(encoding='utf-8')
CONTRACT_CHARS = 9000
BASE_CHARS = 7000
NEIGHBOUR_CHARS = 7000
MODEL_CHARS = 16000
MAX_FILES = 60
#: Fichiers d'inférence qu'un dépôt publie à côté des poids — la recette à reproduire.
INFERENCE_FILES = ('example_inference.py', 'inference.py', 'pipeline_config.json',
                   'config.json', 'model_index.json', 'README.md')


def _read(path: Path, limit: int) -> str:
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    return text if len(text) <= limit else text[:limit] + '\n# … [tronqué]\n'


def base_excerpt() -> str:
    """La classe `BaseModelBackend` jusqu'à ses méthodes abstraites : les attributs déclaratifs
    (ENGINE, REQUIRED_PACKAGES…) et leur sens — pas les 600 lignes du module."""
    from wama.common.services.backend_proposals import backends_dir
    text = (backends_dir() / 'base.py').read_text(encoding='utf-8')
    start = text.find('class BaseModelBackend')
    return text[start:start + BASE_CHARS] if start >= 0 else ''


def task_engines(task: str) -> set:
    """Moteurs des modèles du catalogue qui font la MÊME tâche — ceux dont l'app appelle déjà le
    backend avec la signature qu'elle attend (le composer : `generate(model_id, prompt, …)`)."""
    from wama.common.services.backend_inventory import resolvable_entries
    from wama.model_manager.models import AIModel
    if not task:
        return set()
    engines = {((m.composition or {}).get('runtime') or {}).get('engine')
               for m in AIModel.objects.filter(capabilities__task=task)} - {None, ''}
    # Un moteur PARTAGÉ ne dit rien de la tâche : `transformers` sert plusieurs backends
    # (profondeur, légendes…) — le compter donnait le bonus de tâche à tous, et les plus courts
    # gagnaient. Seul un moteur servi par UN module désigne le backend de la tâche.
    modules = {}
    for e in resolvable_entries():
        modules.setdefault(e.engine, set()).add(e.module)
    return {e for e in engines if len(modules.get(e) or ()) == 1}


def neighbours(engine: str, contract: tuple, task: str = '', limit: int = 2) -> list:
    """Backends du vivier les plus proches : même TÂCHE d'abord (l'app les appelle déjà, ils
    portent la signature qu'elle attend), puis même contrat ET même moteur — le plus court à
    lire en premier (un exemple long noie la consigne).

    ⚠ La tâche est entrée le 2026-10-01 (YuE2, text-to-music) : sur le contrat COMMUN, que
    presque tous les backends héritent, le classement rendait les deux fichiers les plus courts
    du vivier — profondeur et visages — au lieu des backends musicaux que le composer appelle."""
    from wama.common.services.backend_inventory import _file_classes, resolvable_entries
    from wama.common.services.backend_proposals import backends_dir
    same_task = task_engines(task)
    scored, seen = [], set()
    for e in resolvable_entries():
        if not e.module.startswith('wama.common.backends.') or e.module in seen:
            continue
        seen.add(e.module)
        path = backends_dir() / f"{e.module.rsplit('.', 1)[-1]}.py"
        classes, _ = _file_classes(path)
        same_contract = any(contract[1] in c['bases'] for c in classes.values())
        score = 4 * (e.engine in same_task) + 2 * same_contract + (e.engine == engine)
        if score:
            scored.append((-score, path.stat().st_size, path))
    return [p for _, _, p in sorted(scored)[:limit]]


#: Budget de la matière lue dans le code VENDORISÉ du moteur.
VENDOR_CHARS = 14000


def vendor_material(engine: str, hf_id: str) -> str:
    """La recette d'un moteur VENDORISÉ (route library, voie vendor) : le fichier qui charge le
    modèle par défaut (`from_pretrained`) et l'usage du README du clone. Sans elle, le rôle ne
    voyait que le snapshot des POIDS — et devait inventer l'API du moteur (2026-10-01, YuE2)."""
    from django.conf import settings
    from role_utils import vendor_loader_defaults
    root = Path(settings.BACKEND_VENDOR_DIR) / engine
    if not root.is_dir():
        return ''
    # Le GESTE d'import du contrat commun, dit en clair : le base.py servi au rôle est un extrait
    # tronqué qui n'atteint pas `import_vendored` (vécu le 2026-10-01 : `from yue2… import` nu).
    src = 'src' if (root / 'src').is_dir() else ''
    packages = sorted(p.parent.name for p in (root / src if src else root).glob('*/__init__.py'))
    from wama.common.services.backend_proposals import _vendored_code_caps_process_vram
    parts = [f"===== MOTEUR VENDORISÉ « {engine} » — À RESPECTER =====\n"
             f"Code cloné sous settings.BACKEND_VENDOR_DIR/{engine}/ (jamais installé dans le venv).\n"
             f"Déclarer `VENDORED = True` et `ENGINE = '{engine}'`, puis importer UNIQUEMENT par\n"
             f"`self.import_vendored('<paquet>.<module>'{', subdir=' + repr(src) if src else ''})` "
             f"(méthode de classe du contrat commun) — paquet(s) : {packages or '?'} ; un module "
             f"d'un paquet s'importe par son nom COMPLET (ses imports sont relatifs).\n"
             "Les poids se rangent sous le dossier DÉCLARÉ du modèle (catalogue) : passer "
             "`cache_dir=` à `from_pretrained`, ne jamais muter HF_HUB_CACHE/HF_HOME. Les "
             "composants « dépôt frère » (composition `repo`, absents de component_paths) se "
             "lisent par `wama.common.utils.model_components.component_repos(clé)` → "
             "{rôle: (dépôt HF, cache_dir)} : passer l'identifiant ET ce cache_dir."
             + ("\n⚠ Ce moteur plafonne la VRAM de TOUT le processus "
                "(`torch.cuda.set_per_process_memory_fraction`) : la rendre par "
                "`torch.cuda.set_per_process_memory_fraction(1.0)` dans unload()."
                if _vendored_code_caps_process_vram(engine) else '')]
    if vendor_loader_defaults(root, hf_id):
        for path in sorted(root.rglob('*.py')):
            if 'tests' in path.parts:
                continue
            text = _read(path, VENDOR_CHARS)
            if 'def from_pretrained' in text and hf_id in text:
                parts.append(f'===== CODE VENDORISÉ : {path.relative_to(root)} =====\n{text}')
                break
    readme = root / 'README.md'
    if readme.is_file():
        parts.append(f'===== README DU MOTEUR VENDORISÉ =====\n{_read(readme, VENDOR_CHARS // 2)}')
    return '\n\n'.join(parts)


def model_material(row) -> str:
    """Inventaire du snapshot + fichiers d'inférence publiés (README en DERNIER : il déborde)."""
    from wama.common.utils.model_components import snapshot_dir
    root = snapshot_dir(row)
    if root is None:
        raise SystemExit(f"[backend] poids introuvables pour {row.model_key}")
    files = sorted((p for p in root.rglob('*') if p.is_file()),
                   key=lambda p: p.stat().st_size, reverse=True)[:MAX_FILES]
    parts = ['===== INVENTAIRE DU SNAPSHOT =====\n' + '\n'.join(
        f'{p.relative_to(root)}  ({p.stat().st_size / 1e6:.1f} Mo)' for p in files)]
    for name in INFERENCE_FILES:
        found = next(iter(sorted(root.rglob(name))), None)
        if found is not None:
            parts.append(f'===== {found.relative_to(root)} =====\n{_read(found, MODEL_CHARS)}')
    return '\n\n'.join(parts)[:MODEL_CHARS * 2]


def module_name(model_key: str) -> str:
    stem = re.sub(r'[^a-z0-9]+', '_', model_key.rsplit(':', 1)[-1].split('/')[-1].lower())
    return f"{stem.strip('_')}_backend"


def extract_code(text: str) -> str:
    m = re.search(r'```(?:python)?\s*\n(.*?)```', text, re.S)
    return (m.group(1) if m else text).strip() + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--catalog', required=True, help="Clé AIModel du modèle INSTALLÉ")
    ap.add_argument('--dry-run', action='store_true', help='Matière seule, aucun appel LLM')
    ap.add_argument('--no-smoke', action='store_true', help='Sauter le smoke CPU')
    add_llm_arguments(ap, role='dev')
    args = ap.parse_args()

    from wama.common.manifests.builtin.model import extract_model
    import wama.common.services.backend_proposals as bp
    from wama.model_manager.models import AIModel

    row = AIModel.objects.filter(model_key=args.catalog).first()
    if row is None:
        raise SystemExit(f"[backend] {args.catalog!r} absent du catalogue")
    manifest = extract_model(args.catalog)
    compo = (manifest.get('body') or {}).get('composition') or {}
    engine = (compo.get('runtime') or {}).get('engine') or ''
    if not engine or not compo.get('components'):
        raise SystemExit(
            f"[backend] REFUS : {args.catalog} ne déclare pas son anatomie et son moteur "
            "(composition.components + runtime.engine). Rôle `model` d'abord, puis Valider au "
            "model manager — un backend ne s'écrit pas sur une anatomie devinée.")
    task = (row.capabilities or {}).get('task') or ''
    contract = bp.contract_for_task(task)
    model_id = bp.model_id_of(args.catalog)
    module = module_name(args.catalog)
    near = neighbours(engine, contract, task)
    print(f'[backend] {args.catalog} | tâche {task or "?"} | moteur {engine} | contrat '
          f'{contract[1]} | module {module} | voisins {[p.name for p in near]}')

    material = model_material(row)
    vendored = vendor_material(engine, row.hf_id or '')
    if vendored:
        print(f'[backend] moteur VENDORISÉ : {len(vendored)} caractères de code/README du clone')
    user_msg = '\n\n'.join([
        f"CLÉ CATALOGUE : {args.catalog}\nIDENTIFIANT DU MODÈLE (clé de SUPPORTED_MODELS) : "
        f"{model_id}\nMOTEUR (ENGINE) : {engine}\nCONTRAT : {contract[1]} "
        f"(from .{contract[0]} import {contract[1]})\nMÉTHODES À IMPLÉMENTER : "
        f"{sorted(bp.required_methods(contract))}",
        f"===== MANIFESTE DU MODÈLE =====\n{json.dumps(manifest.get('body'), ensure_ascii=False, indent=1)[:6000]}",
        f"===== CONTRAT : {contract[0]}.py =====\n{_read(bp.backends_dir() / f'{contract[0]}.py', CONTRACT_CHARS)}",
        f"===== CONTRAT COMMUN (extrait de base.py) =====\n{base_excerpt()}",
        *[f"===== VOISIN : {p.name} =====\n{_read(p, NEIGHBOUR_CHARS)}" for p in near],
        f"===== SOURCES DU MODÈLE =====\n{material}",
        *([vendored] if vendored else []),
        "Écris le module de backend (un seul bloc ```python).",
    ])
    print(f'[backend] matière : {len(user_msg)} caractères')
    if args.dry_run:
        print('[backend] --dry-run : aucun appel LLM')
        return

    model = resolve_model(args.provider, 'dev', args.model)
    keep_alive = None
    if args.provider == 'ollama':
        from wama.common.services.resource_governor import pipeline_keep_alive
        keep_alive = pipeline_keep_alive()
    print(f'[backend] {args.provider} / {model}')
    reply = call_llm(args.provider, model, PROMPT, user_msg, num_ctx=32768,
                     keep_alive=keep_alive, timeout=1800)
    code = extract_code(reply)

    checks = bp.check_source(code, engine=engine, model_id=model_id, contract=contract)
    resolution = (bp.simulate_resolution(code, module=module, engine=engine, model_id=model_id,
                                         task=task)
                  if checks['ok'] else None)
    smoke = None
    if checks['ok'] and not args.no_smoke:
        smoke = bp.smoke(code, module=module, model_key=args.catalog, contract=contract,
                         out_dir=REPO_ROOT / 'wama-dev-ai' / 'outputs')
    out = write_output('backend', args.catalog, {
        'model_key': args.catalog, 'module': module, 'engine': engine,
        'contract': list(contract), 'provider': args.provider, 'model': model,
        'neighbours': [p.name for p in near], 'checks': checks, 'resolution': resolution,
        'smoke': smoke, 'code': code})
    print(f'[backend] → {out.relative_to(REPO_ROOT)}')
    print(f"[backend] contrôles : {'OK' if checks['ok'] else checks['errors']}"
          + (f" | avertissements : {checks['warnings']}" if checks['warnings'] else ''))
    if resolution:
        print(f"[backend] résolution simulée : {'CE backend' if resolution['resolved'] else resolution}")
    if smoke:
        print(f'[backend] smoke : {smoke}')
    print('[backend] à valider au model manager (section « Propositions »)')


if __name__ == '__main__':
    main()
