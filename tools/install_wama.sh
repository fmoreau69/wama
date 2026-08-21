#!/usr/bin/env bash
# =============================================================================
# INSTALLATION DE WAMA — orchestrateur des étapes du README §Initial setup.
#
# POURQUOI CE SCRIPT. Jusqu'ici l'installation était une procédure EN PROSE : sept étapes
# recopiées à la main depuis le README, plus trois setups éparpillés qu'aucun texte ne reliait
# (`tools/update_vendors.sh`, `wama/avatarizer/setup_avatarizer.sh`, `patches/apply_patches.py`).
# Rien ne disait dans quel ORDRE les lancer — or l'ordre compte : requirements_torch AVANT
# requirements_linux (le second rétablit le pin setuptools<81), et les patches APRÈS pip (ils
# corrigent des fichiers que pip vient d'écrire).
#
# CE QU'IL FAIT / NE FAIT PAS
#   • il ORCHESTRE — il ne réimplémente aucun setup : chaque étape délègue au script qui en est
#     déjà le domicile. Ajouter une dépendance = la mettre dans SON script, pas ici.
#   • il est IDEMPOTENT : relançable sans dégât sur une install existante (venv conservé,
#     migrations déjà appliquées = no-op, assets réécrits à l'identique).
#   • il NE crée PAS le superutilisateur (`createsuperuser` est interactif) et NE remplit PAS
#     le `.env` à votre place : ces deux gestes demandent une décision humaine. Ils sont
#     rappelés à la fin.
#
# ⚠ RÉSEAU REQUIS. Contrairement au démarrage (`start_wama_*.sh`), qui doit rester utilisable
# hors-ligne, l'installation suppose une connexion : pip, git clone, téléchargement des assets.
# C'est la raison pour laquelle `update_vendors.sh` refuse d'être branché au restart mais a
# toute sa place ICI (cf. son en-tête).
#
# USAGE
#   bash tools/install_wama.sh [options]
#     --dry-run            n'exécute rien, affiche le plan (pour vérifier avant de se lancer)
#     --skip-venv          venv et pip déjà faits — passe aux étapes suivantes
#     --skip-vendors       ne retélécharge pas les assets front
#     --with-avatarizer    ajoute MuseTalk + CodeFormer (LOURD : clones git + pip, plusieurs Go)
#     --help
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DRY=0; SKIP_VENV=0; SKIP_VENDORS=0; WITH_AVATARIZER=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)         DRY=1 ;;
    --skip-venv)       SKIP_VENV=1 ;;
    --skip-vendors)    SKIP_VENDORS=1 ;;
    --with-avatarizer) WITH_AVATARIZER=1 ;;
    --help|-h)         sed -n '2,33p' "$0"; exit 0 ;;
    *) echo "Option inconnue : $arg (voir --help)"; exit 2 ;;
  esac
done

VENV="$ROOT/venv_linux"
PY="$VENV/bin/python"

etape=0
titre() { etape=$((etape+1)); echo; echo "── [$etape] $* ──────────────────────────────────"; }
lancer() {
  if [ "$DRY" = "1" ]; then echo "    (dry-run) $*"; else "$@"; fi
}

echo "============================================================"
echo " Installation WAMA — racine : $ROOT"
[ "$DRY" = "1" ] && echo " MODE DRY-RUN : rien ne sera exécuté."
echo "============================================================"

# ── 1. Contrôles préalables ─────────────────────────────────────────────────
# Échouer ICI avec un message clair vaut mieux qu'un pip qui casse trois étapes plus loin.
titre "Contrôles préalables"
if ! command -v python3.12 >/dev/null 2>&1 && [ ! -x "$PY" ]; then
  echo "  ✖ python3.12 introuvable. WAMA cible Python 3.12 (venv_linux)."
  echo "    Sous WSL2 : sudo apt install python3.12 python3.12-venv"
  exit 1
fi
echo "  ✔ python3.12 disponible"
if [ ! -f "$ROOT/.env" ]; then
  echo "  ⚠ .env ABSENT — il sera créé depuis .env.example, mais DEVRA être complété"
  echo "    (DJANGO_SECRET_KEY, WAMA_DB_PASSWORD) avant que Django démarre."
else
  echo "  ✔ .env présent"
fi

# ── 2. Environnement Python ─────────────────────────────────────────────────
# ORDRE CRITIQUE : requirements_torch.txt d'ABORD (pins +cu128), requirements_linux.txt
# ENSUITE — il rétablit le pin setuptools<81 dont mmengine/mmpose ont besoin. Inverser les
# deux donne un environnement qui s'installe sans erreur mais casse à l'import.
titre "Environnement Python (venv_linux)"
if [ "$SKIP_VENV" = "1" ]; then
  echo "  → ignoré (--skip-venv)"
else
  if [ ! -d "$VENV" ]; then
    echo "  Création du venv…"
    lancer python3.12 -m venv "$VENV"
  else
    echo "  ✔ venv_linux existe déjà — réutilisé (pip mettra à jour ce qui doit l'être)"
  fi
  lancer "$PY" -m pip install --quiet --upgrade pip
  echo "  Installation de PyTorch GPU (requirements_torch.txt) — long…"
  lancer "$PY" -m pip install -r "$ROOT/requirements_torch.txt"
  echo "  Installation des dépendances applicatives (requirements_linux.txt)…"
  lancer "$PY" -m pip install -r "$ROOT/requirements_linux.txt"
fi

# ── 3. Variables d'environnement ────────────────────────────────────────────
titre "Fichier .env"
if [ ! -f "$ROOT/.env" ]; then
  lancer cp "$ROOT/.env.example" "$ROOT/.env"
  echo "  ✔ .env créé depuis .env.example — À COMPLÉTER (voir le récapitulatif final)"
else
  echo "  ✔ .env déjà présent — laissé INTACT (jamais écrasé : il porte vos secrets)"
fi

# ── 4. Patches de compatibilité ─────────────────────────────────────────────
# APRÈS pip, et à relancer après tout `pip install --upgrade` : ces correctifs portent sur des
# fichiers DU VENV, que pip réécrit. Cf. règle CLAUDE.md « patches/apply_patches.py ».
titre "Patches de compatibilité des dépendances"
lancer "$PY" "$ROOT/patches/apply_patches.py"

# ── 5. Assets front vendorés ────────────────────────────────────────────────
# Délègue à update_vendors.sh (domicile unique des versions épinglées : Bootstrap, Font
# Awesome, jsTree, three.js, TalkingHead + l'avatar GLB non commité).
titre "Assets front vendorés (local-first, aucun CDN au runtime)"
if [ "$SKIP_VENDORS" = "1" ]; then
  echo "  → ignoré (--skip-vendors)"
else
  lancer bash "$ROOT/tools/update_vendors.sh"
fi

# ── 6. Base de données ──────────────────────────────────────────────────────
# `migrate` est idempotent ; `init_wama` pose les données initiales (rôles, catalogue…).
titre "Base de données (migrations + données initiales)"
lancer "$PY" "$ROOT/manage.py" migrate
lancer "$PY" "$ROOT/manage.py" init_wama

# ── 7. Fichiers statiques ───────────────────────────────────────────────────
titre "Collecte des fichiers statiques"
lancer "$PY" "$ROOT/manage.py" collectstatic --noinput

# ── 8. Setups optionnels (lourds) ───────────────────────────────────────────
# Hors du chemin par défaut : plusieurs Go de clones git + pip. Une install de base doit
# pouvoir aboutir sans eux — les apps concernées signalent proprement leur indisponibilité.
titre "Setups optionnels"
if [ "$WITH_AVATARIZER" = "1" ]; then
  echo "  Avatarizer (MuseTalk + CodeFormer) — LOURD…"
  lancer bash "$ROOT/wama/avatarizer/setup_avatarizer.sh"
else
  echo "  → avatarizer NON installé (--with-avatarizer pour l'ajouter)"
fi

# ── 9. Contrôles de bonne fin ───────────────────────────────────────────────
# Une installation « sans erreur » n'est pas une installation qui MARCHE : on le vérifie.
titre "Contrôles de bonne fin"
if [ "$DRY" = "1" ]; then
  echo "    (dry-run) manage.py check + migrate --check"
else
  "$PY" "$ROOT/manage.py" check && echo "  ✔ manage.py check"
  "$PY" "$ROOT/manage.py" migrate --check >/dev/null 2>&1 \
    && echo "  ✔ aucune migration en attente" \
    || echo "  ⚠ des migrations restent à appliquer"
fi

cat <<'FIN'

============================================================
 ✔ Installation terminée.

 RESTE À FAIRE À LA MAIN (gestes qui demandent une décision) :
   1. Compléter .env  →  DJANGO_SECRET_KEY et WAMA_DB_PASSWORD
        python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
   2. Créer le compte administrateur (interactif) :
        venv_linux/bin/python manage.py createsuperuser

 DÉMARRER :
   bash start_wama_dev.sh     (développement)
   bash start_wama_prod.sh    (production)
============================================================
FIN
