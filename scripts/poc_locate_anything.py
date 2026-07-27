#!/usr/bin/env python3
"""PoC standalone LocateAnything-3B (NVIDIA) — détection open-vocabulary par prompt texte.

ROADMAP §17 étape 1. À lancer dans WSL2 avec le venv_linux :
    venv_linux/bin/python scripts/poc_locate_anything.py --image /chemin/img.jpg --prompt "screen, badge, document"

Valide : qualité des détections sur cas anonymizer (écrans/badges/documents), latence réelle RTX 4090,
compatibilité transformers 4.57.6 (pin officielle 4.57.1 — si échec, venv isolé, voir §17).

⚠ Licence NVIDIA non-commerciale — usage recherche uniquement (ROADMAP §17).
Premier lancement : télécharge ~8 Go dans AI-models/models/vision/locate-anything/.
"""
import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEIGHTS_DIR = REPO_ROOT / "AI-models" / "models" / "vision" / "locate-anything"

# ── CRITIQUE : env HF AVANT tout import transformers (règle CLAUDE.md ajout modèle) ──
WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["HF_HUB_CACHE"] = str(WEIGHTS_DIR)
os.environ["HUGGINGFACE_HUB_CACHE"] = str(WEIGHTS_DIR)

MODEL_ID = "nvidia/LocateAnything-3B"


def main() -> int:
    ap = argparse.ArgumentParser(description="PoC LocateAnything-3B")
    ap.add_argument("--image", required=True, help="Image d'entrée")
    ap.add_argument("--prompt", required=True,
                    help="Catégories à détecter, en anglais, séparées par des virgules")
    ap.add_argument("--mode", default="hybrid", choices=["fast", "slow", "hybrid"],
                    help="generation_mode (hybrid recommandé par la carte modèle)")
    ap.add_argument("--task", default="detect",
                    choices=["detect", "ground_single", "ground_multi", "point", "detect_text"],
                    help="Tâche (ground_* = referring expression dans --prompt)")
    ap.add_argument("--out", default=None, help="Image annotée de sortie (défaut: <image>_la.jpg)")
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"],
                    help="cpu = test de chargement sans toucher la pile GPU WSL2")
    ap.add_argument("--load-only", action="store_true",
                    help="Charger le modèle, imprimer RAM/VRAM, sortir (pas d'inférence)")
    args = ap.parse_args()

    from PIL import Image, ImageDraw

    img = Image.open(args.image).convert("RGB")
    print(f"Image {img.size}, tâche={args.task}, mode={args.mode}, prompt={args.prompt!r}")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from locate_anything_worker import LocateAnythingWorker

    t0 = time.perf_counter()
    worker = LocateAnythingWorker(MODEL_ID, device=args.device)
    t_load = time.perf_counter() - t0
    print(f"Chargement ({args.device}) : {t_load:.1f}s", flush=True)

    if args.load_only:
        import resource
        peak_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
        print(f"Pic RAM process : {peak_gb:.1f} Go")
        if args.device == "cuda":
            import torch
            print(f"VRAM allouée : {torch.cuda.max_memory_allocated() / 1e9:.1f} Go")
        print("LOAD-ONLY OK")
        return 0

    t0 = time.perf_counter()
    if args.task == "detect":
        result = worker.detect(img, [c.strip() for c in args.prompt.split(",")],
                               generation_mode=args.mode, verbose=False)
    else:
        result = getattr(worker, args.task)(img, args.prompt,
                                            generation_mode=args.mode, verbose=False)
    t_inf = time.perf_counter() - t0
    print(f"Inférence : {t_inf:.2f}s")
    print("Réponse brute :", result.get("answer", "")[:2000])

    w, h = img.size
    if args.task == "point":
        boxes = []
        for p in LocateAnythingWorker.parse_points(result["answer"], w, h):
            print(f"  point ({p['x']:.0f}, {p['y']:.0f})")
    else:
        boxes = LocateAnythingWorker.parse_boxes(result["answer"], w, h)
    if boxes:
        draw = ImageDraw.Draw(img)
        for bb in boxes:
            draw.rectangle([bb["x1"], bb["y1"], bb["x2"], bb["y2"]], outline="red", width=3)
        out = args.out or str(Path(args.image).with_suffix("")) + "_la.jpg"
        img.save(out)
        print(f"{len(boxes)} détection(s) → {out}")

    try:
        import torch
        if torch.cuda.is_available():
            print(f"VRAM pic : {torch.cuda.max_memory_allocated() / 1e9:.1f} Go")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
