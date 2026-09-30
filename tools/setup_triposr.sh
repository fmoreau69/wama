#!/usr/bin/env bash
# Vendorise le CODE de TripoSR (MIT) pour le backend image → 3D — ROADMAP §17ter trou 4.
#
#   bash tools/setup_triposr.sh          # route library, voie vendor ; idempotent
#
# ⚠ RÉÉCRIT LE 2026-09-30 (ROADMAP D-a) : ce script clonait lui-même et réappliquait ses deux
# retouches par des blocs Python. Elles sont désormais DÉCLARÉES — manifeste
# `manifests/libraries/triposr.json` (dépôt, commit épinglé) + correctif versionné
# `patches/triposr_pymcubes_lazy_rembg.diff` — et c'est la route `library` qui clone au commit,
# applique, constate l'état et refuse d'écraser une modification non déclarée.
#
# Les deux retouches, et pourquoi (le venv est la RÉFÉRENCE — la lib s'y adapte, jamais l'inverse) :
#   1. tsr/models/isosurface.py : `torchmcubes` (extension CUDA à compiler, pip par git+ — que la
#      route `library` REFUSE, ROADMAP §16.7) → `mcubes` (PyMCubes, wheel). Le marching cubes
#      tourne sur CPU ; la permutation d'axes `[2, 1, 0]` du code amont est CONSERVÉE — ⚠ à
#      VÉRIFIER sur le premier maillage (orientation des faces / normales).
#   2. tsr/utils.py : `import rembg` (onnxruntime, ~300 Mo) devient PARESSEUX — le détourage est
#      optionnel (le cas nominal est une image DÉJÀ détourée par le detector / SAM3).
#
# ⚠ Lancer ce script EST la décision humaine qu'exige la route (`--allow`, allowlist
# `Library.is_allowed`) : il n'autorise que TripoSR.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python manage.py apply_manifests --kind library --apply
python manage.py install_library triposr --allow --apply

echo "  Paquets pip à autoriser par la route library (décision humaine, --allow --apply) :"
echo "    trimesh==5.1.0  PyMCubes==0.1.6   (omegaconf, einops, huggingface_hub : déjà dans venv_linux)"
echo "  Premier run GPU : AVEC Fabien (règle crashs hôte) — vérifier l'orientation des faces."
