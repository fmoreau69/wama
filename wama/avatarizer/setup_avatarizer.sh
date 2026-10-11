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
#   1-2. Installe MuseTalk et CodeFormer par la route `library` (voie vendor) : clone AU COMMIT
#        déclaré dans manifests/libraries/{musetalk,codeformer}.json + correctif de patches/
#   3. Vérifie les dépendances pip du venv courant
#   4. Télécharge les checkpoints MuseTalk vers AI-models/models/lipsync/musetalk/
#   5. Installe les poids CodeFormer par le catalogue (`pull_model avatarizer:codeformer`)
#
# ⚠ Lancer ce script EST la décision humaine qu'exige la route (`--allow`, allowlist
# `Library.is_allowed`, ROADMAP §16.7) : il autorise les deux moteurs qu'il installe, rien d'autre.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
AVATARIZER_DIR="$SCRIPT_DIR"
# Code tiers des moteurs : racine DECLAREE (settings.BACKEND_VENDOR_DIR), gitignoree.
VENDOR_DIR="$PROJECT_DIR/wama/common/backends/vendor"
# Poids : settings.MODEL_PATHS['lipsync'] (ce script visait models/avatarizer/, que rien ne lit).
MODELS_DIR="$PROJECT_DIR/AI-models/models/lipsync"

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

mkdir -p "$VENDOR_DIR"
mkdir -p "$MODELS_DIR/musetalk"
mkdir -p "$MODELS_DIR/codeformer"

# =============================================================================
# 1-2. MuseTalk v1.5 + CodeFormer — route `library`, voie vendor (ROADMAP D-a)
# =============================================================================
# ⚠⚠ RÉÉCRIT LE 2026-09-30. Ces deux étapes clonaient `main` SANS épingle et faisaient
# `git pull --ff-only` sur un clone existant — qui portait des correctifs LOCAUX (MuseTalk,
# 7 fichiers) que rien ne réappliquait. La route, elle, clone au commit déclaré, applique le
# correctif versionné, CONSTATE l'état, et REFUSE d'écraser une modification non déclarée.
echo "--- [1-2/5] MuseTalk + CodeFormer (route library, voie vendor) ---"
cd "$PROJECT_DIR"
python manage.py apply_manifests --kind library --apply
for moteur in musetalk codeformer; do
    python manage.py install_library "$moteur" --allow --apply
done

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

# ⚠⚠ RÉÉCRIT LE 2026-10-11. Cette étape appelait un `scripts/download_weights.py` qui n'existe pas
# (le dépôt vendorisé a `download_weights.sh`) ; son repli tirait le dépôt `TMElyralab/MuseTalk`
# ENTIER (v1.0 comprise) et rien des six autres sources que l'inférence lit — et « les modèles se
# téléchargeront au premier lancement » était faux : rien ne les télécharge.
# Les poids passent par la route du CATALOGUE, comme CodeFormer : l'app DÉCLARE les onze fichiers
# que l'inférence lit, chacun avec son origine et son empreinte (`AVATARIZER_MODELS
# ['musetalk-v1.5']['files']` : quatre dépôts du Hub figés à leur commit, pytorch.org, le site de
# face-alignment, un miroir du Hub pour BiSeNet). Le lien `vendor/musetalk/models` est créé par
# le backend au premier lancement.
cd "$PROJECT_DIR"
python manage.py sync_models >/dev/null      # la ligne `avatarizer:musetalk-v1.5` existe ensuite
python manage.py pull_model avatarizer:musetalk-v1.5 || \
    echo "ATTENTION : poids MuseTalk non demandés — bouton « Installer » du model manager, ou : python manage.py pull_model avatarizer:musetalk-v1.5"

# =============================================================================
# 5. Checkpoints CodeFormer
# =============================================================================
echo "--- [5/5] Téléchargement checkpoints CodeFormer ---"

# ⚠⚠ RÉÉCRIT LE 2026-10-10. Les deux branches d'ici étaient fausses, chacune à sa manière :
#   • le script de CodeFormer (`download_pretrained_models.py all`) écrit dans `./weights/`
#     relatif au RÉPERTOIRE COURANT — ici la racine du dépôt (`cd` de l'étape 1-2) — et tire
#     aussi les poids d'ENTRAÎNEMENT et dlib, que rien ne lit ;
#   • le repli `basicsr` posait `codeformer.pth` À PLAT (la découverte le cherche sous
#     `CodeFormer/`), prenait la détection chez facexlib, et omettait `parsing_parsenet.pth`
#     et `RealESRGAN_x2plus.pth`.
# Les poids passent désormais par la route du CATALOGUE : l'app DÉCLARE les quatre fichiers
# que le code vendorisé lit (`AVATARIZER_MODELS['codeformer']['files']`, version
# sczhou/CodeFormer v0.1.0, empreintes épinglées), sa découverte pose le dossier
# (`MODEL_PATHS['lipsync']['codeformer']`), et `pull_model <clé>` fait la DEMANDE du bouton
# « Installer » (`request_install` : garde d'espace disque, tâche Celery suivie au model
# manager, journal ; pilote `files`). Déjà installé → rien à faire. ⚠ La tâche s'exécute dans
# un worker Celery : il doit tourner (sinon elle attend en file).
cd "$PROJECT_DIR"
python manage.py sync_models >/dev/null      # la ligne `avatarizer:codeformer` existe ensuite
python manage.py pull_model avatarizer:codeformer || \
    echo "ATTENTION : poids CodeFormer non demandés — bouton « Installer » du model manager, ou : python manage.py pull_model avatarizer:codeformer"

# (La galerie d'avatars n'est plus un dossier media/avatarizer/gallery/ : les avatars — photos
#  et objets 3D — se cherchent et s'importent par la médiathèque, source « Avatars 3D » comprise.)

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
echo "  common/backends/vendor/musetalk/   : $([ -d "$VENDOR_DIR/musetalk" ] && echo 'OK' || echo 'MANQUANT')"
echo "  common/backends/vendor/codeformer/ : $([ -d "$VENDOR_DIR/codeformer" ] && echo 'OK' || echo 'MANQUANT')"
echo "  AI-models/.../musetalk/       : $(ls "$MODELS_DIR/musetalk" 2>/dev/null | wc -l) fichier(s)"
echo "  AI-models/.../codeformer/     : $(ls "$MODELS_DIR/codeformer" 2>/dev/null | wc -l) fichier(s)"
echo ""
echo "Avatars : médiathèque (photos, objets 3D) — puis redémarrez WAMA et accédez à /avatarizer/"
