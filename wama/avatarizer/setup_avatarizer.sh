#!/bin/bash
# =============================================================================
# WAMA Avatarizer — Script d'installation
# Pipeline : MuseTalk v1.5 + CodeFormer
#
# Usage :
#   cd /mnt/d/WAMA/web-app-for-media-automation
#   source venv_linux/bin/activate
#   bash wama/avatarizer/setup_avatarizer.sh
#
# Ce script :
#   1. Clone MuseTalk dans wama/avatarizer/musetalk/
#   2. Clone CodeFormer dans wama/avatarizer/codeformer/
#   3. Installe les dépendances pip dans le venv courant
#   4. Télécharge les checkpoints MuseTalk vers AI-models/models/avatarizer/musetalk/
#   5. Télécharge les checkpoints CodeFormer vers AI-models/models/avatarizer/codeformer/
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
AVATARIZER_DIR="$SCRIPT_DIR"
MODELS_DIR="$PROJECT_DIR/AI-models/models/avatarizer"

echo "=== WAMA Avatarizer Setup ==="
echo "Project  : $PROJECT_DIR"
echo "App dir  : $AVATARIZER_DIR"
echo "Models   : $MODELS_DIR"
echo ""

# Vérifier que le venv est activé
if [ -z "$VIRTUAL_ENV" ]; then
    echo "ERREUR : Activez d'abord le venv : source venv_linux/bin/activate"
    exit 1
fi

mkdir -p "$MODELS_DIR/musetalk"
mkdir -p "$MODELS_DIR/codeformer"

# =============================================================================
# 1. MuseTalk v1.5
# =============================================================================
echo "--- [1/5] Clone MuseTalk ---"
if [ ! -d "$AVATARIZER_DIR/musetalk/.git" ]; then
    git clone https://github.com/TMElyralab/MuseTalk.git "$AVATARIZER_DIR/musetalk"
else
    echo "MuseTalk déjà cloné, mise à jour..."
    git -C "$AVATARIZER_DIR/musetalk" pull --ff-only || true
fi

# =============================================================================
# 2. CodeFormer
# =============================================================================
echo "--- [2/5] Clone CodeFormer ---"
if [ ! -d "$AVATARIZER_DIR/codeformer/.git" ]; then
    git clone https://github.com/sczhou/CodeFormer.git "$AVATARIZER_DIR/codeformer"
else
    echo "CodeFormer déjà cloné, mise à jour..."
    git -C "$AVATARIZER_DIR/codeformer" pull --ff-only || true
fi

# =============================================================================
# 3. Dépendances pip — VÉRIFIÉES, jamais imposées
# =============================================================================
# ⚠⚠ RÉÉCRIT LE 2026-09-07. Cette section INSTALLAIT les `requirements.txt` de MuseTalk et
# CodeFormer dans le venv PRINCIPAL, plus un pin `numpy>=1.26.0,<2.0`. Mesuré :
#
#     musetalk/requirements.txt épingle  numpy==1.23.5, transformers==4.39.2,
#                                        tensorflow==2.12.0, diffusers==0.30.2
#     le venv porte                      numpy 2.3.5, transformers 4.57.6,
#                                        tensorflow 2.21.0, diffusers 0.37.0
#
# Les appliquer aurait rétrogradé QUATRE dépendances partagées — dont `transformers`, sur
# lequel reposent les 9 patches boson_multimodal, et `diffusers`, moteur des 8 backends de
# l'imager. Sur une installation qui marche, ce script la cassait.
#
# Et ils sont PROUVÉS inutiles : les 18 dépendances de MuseTalk sont déjà présentes en versions
# plus récentes, et l'avatarizer tourne ainsi (4 jobs SUCCESS au catalogue). C'est la doctrine
# du dépôt : le venv est la RÉFÉRENCE, la lib vendorisée s'y adapte — et si elle ne le peut
# pas, le correctif est un patch (`patches/apply_patches.py`), jamais un retour en arrière.
#
# Cette section VÉRIFIE donc, et n'installe que ce qui MANQUE VRAIMENT — en `--no-deps`, pour
# qu'un pin d'amont ne puisse jamais entraîner le venv avec lui.
echo "--- [3/5] Vérification des dépendances (le venv fait référence) ---"

manquants=""
for mod in diffusers accelerate numpy cv2 soundfile transformers huggingface_hub \
           librosa einops omegaconf moviepy basicsr facexlib; do
    python -c "import $mod" >/dev/null 2>&1 || manquants="$manquants $mod"
done

if [ -z "$manquants" ]; then
    echo "  ✔ toutes les dépendances sont présentes — rien à installer."
else
    echo "  Modules absents :$manquants"
    echo "  Installation en --no-deps (un pin d'amont ne doit pas rétrograder le venv) :"
    # Nom d'IMPORT ≠ nom pip pour deux d'entre eux.
    for mod in $manquants; do
        case "$mod" in
            cv2) paquet="opencv-python" ;;
            huggingface_hub) paquet="huggingface-hub" ;;
            *) paquet="$mod" ;;
        esac
        pip install --quiet --no-deps "$paquet" || echo "    ⚠ $paquet : échec, à traiter à la main"
    done
    echo "  ⚠ En --no-deps, pip ne comble pas les manques transitifs : relancer les contrôles"
    echo "    de bonne fin de tools/install_wama.sh après cette étape."
fi

# =============================================================================
# 4. Checkpoints MuseTalk
# =============================================================================
echo "--- [4/5] Téléchargement checkpoints MuseTalk ---"

# MuseTalk utilise huggingface_hub pour télécharger ses modèles au premier lancement.
# On peut pré-télécharger en utilisant huggingface-cli ou le script fourni par MuseTalk.

if [ -f "$AVATARIZER_DIR/musetalk/scripts/download_weights.py" ]; then
    echo "Téléchargement via script MuseTalk..."
    python "$AVATARIZER_DIR/musetalk/scripts/download_weights.py" \
        --save_dir "$MODELS_DIR/musetalk" || \
    echo "Script MuseTalk non disponible — les modèles se téléchargeront au premier lancement."
elif python -c "import huggingface_hub" 2>/dev/null; then
    echo "Téléchargement MuseTalk v1.5 depuis HuggingFace..."
    python -c "
from huggingface_hub import snapshot_download
import os
os.makedirs('$MODELS_DIR/musetalk', exist_ok=True)
snapshot_download(
    repo_id='TMElyralab/MuseTalk',
    local_dir='$MODELS_DIR/musetalk',
    ignore_patterns=['*.md', '*.gitattributes'],
)
print('MuseTalk checkpoints téléchargés.')
" || echo "Téléchargement HF échoué — les modèles se téléchargeront au premier lancement."
else
    echo "ATTENTION : huggingface_hub non disponible."
    echo "Les checkpoints MuseTalk se téléchargeront automatiquement au premier lancement."
    echo "Ou téléchargez manuellement depuis : https://huggingface.co/TMElyralab/MuseTalk"
fi

# =============================================================================
# 5. Checkpoints CodeFormer
# =============================================================================
echo "--- [5/5] Téléchargement checkpoints CodeFormer ---"

if [ -f "$AVATARIZER_DIR/codeformer/scripts/download_pretrained_models.py" ]; then
    python "$AVATARIZER_DIR/codeformer/scripts/download_pretrained_models.py" all || \
    echo "Script CodeFormer non disponible — téléchargement manuel requis."
else
    echo "Téléchargement checkpoints CodeFormer..."
    python -c "
from basicsr.utils.download_util import load_file_from_url
import os

save_dir = '$MODELS_DIR/codeformer'
os.makedirs(save_dir, exist_ok=True)

# CodeFormer weights
load_file_from_url(
    url='https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth',
    model_dir=save_dir, progress=True, file_name='codeformer.pth'
)
# GFPGAN weights (used by CodeFormer for alignment)
load_file_from_url(
    url='https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth',
    model_dir=save_dir, progress=True
)
print('CodeFormer checkpoints téléchargés.')
" || echo "ATTENTION : Téléchargement CodeFormer échoué. Téléchargez manuellement depuis : https://github.com/sczhou/CodeFormer"
fi

# =============================================================================
# Créer les dossiers media nécessaires
# =============================================================================
echo "--- Création des dossiers media ---"
mkdir -p "$PROJECT_DIR/media/avatarizer/gallery"
echo "Galerie créée : $PROJECT_DIR/media/avatarizer/gallery/"
echo "Ajoutez vos images d'avatars dans ce dossier (JPG, PNG)."

# =============================================================================
# Appliquer la migration Django
# =============================================================================
echo "--- Migration Django ---"
cd "$PROJECT_DIR"
python manage.py migrate avatarizer || echo "Migration ignorée (appliquez manuellement : python manage.py migrate avatarizer)"

# =============================================================================
# Résumé
# =============================================================================
echo ""
echo "=== Installation terminée ==="
echo ""
echo "Structure :"
echo "  wama/avatarizer/musetalk/     : $([ -d "$AVATARIZER_DIR/musetalk" ] && echo 'OK' || echo 'MANQUANT')"
echo "  wama/avatarizer/codeformer/   : $([ -d "$AVATARIZER_DIR/codeformer" ] && echo 'OK' || echo 'MANQUANT')"
echo "  AI-models/.../musetalk/       : $(ls "$MODELS_DIR/musetalk" 2>/dev/null | wc -l) fichier(s)"
echo "  AI-models/.../codeformer/     : $(ls "$MODELS_DIR/codeformer" 2>/dev/null | wc -l) fichier(s)"
echo ""
echo "Ajoutez vos avatars dans : media/avatarizer/gallery/"
echo "Puis redémarrez WAMA et accédez à /avatarizer/"
