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
    args = ap.parse_args()

    from PIL import Image, ImageDraw

    img = Image.open(args.image).convert("RGB")
    print(f"Image {img.size}, tâche={args.task}, mode={args.mode}, prompt={args.prompt!r}")

    t0 = time.perf_counter()
    # LocateAnythingWorker vient du code remote du repo HF (trust_remote_code).
    try:
        from transformers import AutoModel
        model = AutoModel.from_pretrained(
            MODEL_ID, cache_dir=str(WEIGHTS_DIR), trust_remote_code=True,
        )
        worker = getattr(model, "worker", None)
        if worker is None:
            # Chemin documenté sur la carte : classe utilitaire exposée par le code remote.
            from transformers.dynamic_module_utils import get_class_from_dynamic_module
            LocateAnythingWorker = get_class_from_dynamic_module(
                "inference.LocateAnythingWorker", MODEL_ID, cache_dir=str(WEIGHTS_DIR),
            )
            worker = LocateAnythingWorker(MODEL_ID)
    except Exception as exc:  # noqa: BLE001 — PoC : diagnostic verbeux voulu
        print(f"[PoC] Chargement via AutoModel/worker KO ({exc}).")
        print("[PoC] Adapter ce script au README du snapshot téléchargé "
              f"({WEIGHTS_DIR}/models--nvidia--LocateAnything-3B/) — la carte HF fournit "
              "la classe LocateAnythingWorker avec detect()/ground_single()/point().")
        return 1
    t_load = time.perf_counter() - t0
    print(f"Chargement : {t_load:.1f}s")

    t0 = time.perf_counter()
    fn = getattr(worker, args.task)
    result = fn(img, args.prompt) if args.task != "detect" else fn(
        img, args.prompt, generation_mode=args.mode)
    t_inf = time.perf_counter() - t0
    print(f"Inférence : {t_inf:.2f}s")
    print("Résultat brut :", result)

    # Boîtes en coordonnées normalisées 0-1000 → pixels, image annotée pour lecture humaine.
    boxes = result if isinstance(result, list) else result.get("boxes", []) if isinstance(result, dict) else []
    if boxes:
        draw = ImageDraw.Draw(img)
        w, h = img.size
        for det in boxes:
            bb = det.get("box") or det.get("bbox") if isinstance(det, dict) else det
            if not bb or len(bb) < 4:
                continue
            x1, y1, x2, y2 = (bb[0] * w / 1000, bb[1] * h / 1000,
                              bb[2] * w / 1000, bb[3] * h / 1000)
            draw.rectangle([x1, y1, x2, y2], outline="red", width=3)
            if isinstance(det, dict) and det.get("label"):
                draw.text((x1 + 2, y1 + 2), str(det["label"]), fill="red")
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
