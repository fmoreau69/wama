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
# 3. Dépendances pip
# =============================================================================
echo "--- [3/5] Installation des dépendances pip ---"

# Mettre à jour pip/setuptools/wheel en premier (évite les erreurs de build sur Python 3.12)
echo "Mise à jour pip/setuptools/wheel..."
pip install --quiet --upgrade pip "setuptools>=68.0" wheel

# Pré-installer numpy compatible Python 3.12 AVANT les requirements.txt
# (évite l'erreur pkgutil.ImpImporter si requirements.txt pin une vieille version)
echo "Pré-installation numpy compatible Python 3.12..."
pip install --quiet "numpy>=1.26.0,<2.0"

# MuseTalk requirements (numpy déjà installé, sera ignoré)
if [ -f "$AVATARIZER_DIR/musetalk/requirements.txt" ]; then
    echo "Installation requirements MuseTalk..."
    pip install -r "$AVATARIZER_DIR/musetalk/requirements.txt" --quiet || {
        echo "Tentative sans isolation de build (fallback Python 3.12)..."
        pip install -r "$AVATARIZER_DIR/musetalk/requirements.txt" --quiet --no-build-isolation || true
    }
else
    echo "requirements.txt MuseTalk non trouvé — installation manuelle des essentiels"
    pip install --quiet \
        diffusers==0.27.2 \
        accelerate \
        imageio \
        imageio-ffmpeg \
        moviepy \
        facenet-pytorch \
        mmpose \
        mmdet \
        mmengine \
        openmim
    pip install --quiet mmcv==2.1.0 -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html || \
    pip install --quiet mmcv==2.1.0 || true
fi

# CodeFormer requirements
if [ -f "$AVATARIZER_DIR/codeformer/requirements.txt" ]; then
    echo "Installation requirements CodeFormer..."
    pip install -r "$AVATARIZER_DIR/codeformer/requirements.txt" --quiet || {
        pip install -r "$AVATARIZER_DIR/codeformer/requirements.txt" --quiet --no-build-isolation || true
    }
fi

# Dépendances communes
pip install --quiet basicsr facexlib gfpgan pyyaml

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
