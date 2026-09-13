#!/usr/bin/env bash
# Vendorise le CODE de TripoSR (MIT) pour le backend image → 3D — ROADMAP §17ter trou 4.
#
#   bash tools/setup_triposr.sh          # clone épinglé + 2 patches ; idempotent
#
# Même patron que setup_avatarizer.sh (MuseTalk, CodeFormer) : le code tiers vit sous
# wama/common/backends/vendor/<moteur>/ (gitignoré), les POIDS sont tirés par le backend
# (`hf_hub_download(cache_dir=MODEL_PATHS['vision']['triposr'])`) au premier chargement.
#
# Deux PATCHES, et pourquoi (le venv est la RÉFÉRENCE — la lib s'y adapte, jamais l'inverse) :
#   1. tsr/models/isosurface.py : `torchmcubes` (extension CUDA à compiler, pip par git+ — que la
#      route `library` REFUSE, ROADMAP §16.7) → `mcubes` (PyMCubes, wheel). Le marching cubes
#      tourne sur CPU (le volume est 256³ float, quelques dizaines de ms) ; la permutation
#      d'axes `[2, 1, 0]` du code amont est CONSERVÉE — ⚠ à VÉRIFIER sur le premier maillage
#      (orientation des faces / normales) : c'est le point non attesté sans GPU.
#   2. tsr/utils.py : `import rembg` (onnxruntime, ~300 Mo) devient PARESSEUX — le détourage est
#      optionnel (le cas nominal est une image DÉJÀ détourée par le detector / SAM3).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/wama/common/backends/vendor/triposr"
REPO="https://github.com/VAST-AI-Research/TripoSR"
PIN="107cefdc244c39106fa830359024f6a2f1c78871"   # main du 2026-06-04 — épinglé, jamais « latest »

mkdir -p "$(dirname "$VENDOR")"
if [ ! -d "$VENDOR/.git" ]; then
  git clone --quiet "$REPO" "$VENDOR"
fi
git -C "$VENDOR" fetch --quiet origin "$PIN" || true
git -C "$VENDOR" checkout --quiet "$PIN"

# ── patch 1 : torchmcubes → PyMCubes ─────────────────────────────────────────────────────
ISO="$VENDOR/tsr/models/isosurface.py"
if grep -q "from torchmcubes import marching_cubes" "$ISO"; then
  python3 - "$ISO" <<'PY'
import io, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()
s = s.replace(
    "from torchmcubes import marching_cubes\n",
    "# WAMA (tools/setup_triposr.sh) : PyMCubes (wheel) a la place de torchmcubes (extension CUDA).\n"
    "import mcubes\n\n\n"
    "def marching_cubes(level, threshold):\n"
    "    v, t = mcubes.marching_cubes(level.detach().cpu().numpy(), float(threshold))\n"
    "    return torch.from_numpy(v.astype('float32')), torch.from_numpy(t.astype('int64'))\n")
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patch 1 applique :', p)
PY
else
  echo "patch 1 deja applique"
fi

# ── patch 2 : rembg paresseux ────────────────────────────────────────────────────────────
UT="$VENDOR/tsr/utils.py"
if grep -q "^import rembg$" "$UT"; then
  python3 - "$UT" <<'PY'
import io, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()
s = s.replace("import rembg\n", "")
s = s.replace("        image = rembg.remove(image, session=rembg_session, **rembg_kwargs)\n",
              "        import rembg  # WAMA : paresseux (optionnel, ~300 Mo d'onnxruntime)\n"
              "        image = rembg.remove(image, session=rembg_session, **rembg_kwargs)\n")
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patch 2 applique :', p)
PY
else
  echo "patch 2 deja applique"
fi

echo "✔ TripoSR vendorise : $VENDOR (commit $PIN, MIT — LICENSE dans le clone)"
echo "  Paquets pip a autoriser par la route library (decision humaine, --allow --apply) :"
echo "    trimesh==5.1.0  PyMCubes==0.1.6   (omegaconf, einops, huggingface_hub : deja dans venv_linux)"
echo "  Premier run GPU : AVEC Fabien (regle crashs hote) — verifier l'orientation des faces."
