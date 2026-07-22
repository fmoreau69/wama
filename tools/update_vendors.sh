#!/usr/bin/env bash
# =============================================================================
# Met à jour les assets front vendorés en LOCAL (Bootstrap / Font Awesome / jsTree).
#
# WAMA est LOCAL-FIRST (cf. memory/reference_offline_assets_local) : aucune dépendance
# CDN au runtime → fonctionne hors-ligne. Ce script garde les liens de récupération et
# permet de mettre à jour EN UNE COMMANDE quand on a internet.
#
# ⚠️ À lancer À LA DEMANDE — PAS au restart du serveur, PAS en cron :
#   - dépendre du réseau au démarrage réintroduirait la fragilité hors-ligne qu'on évite ;
#   - une nouvelle version peut casser l'UI → une montée de version se TESTE puis se committe.
#
# Procédure de montée de version :
#   1) ajuster les versions ci-dessous
#   2) bash tools/update_vendors.sh        (proxy UGE par défaut ; voir PROXY plus bas)
#   3) python manage.py collectstatic --noinput
#   4) si une VERSION a changé : mettre à jour les chemins {% static 'vendors/...' %} de
#      wama/templates/base.html (les dossiers sont versionnés)
#   5) vérifier l'UI, puis committer les assets.
# =============================================================================
set -euo pipefail

# ── Versions épinglées ───────────────────────────────────────────────────────
BOOTSTRAP_VER=5.3.0
FA_VER=6.4.0
JSTREE_VER=3.3.16

# ── Proxy (optionnel) : aucun par défaut. Derrière un proxy réseau, exporter avant l'appel :
#     PROXY=http://<host>:<port> bash tools/update_vendors.sh
#   (voir .env / .env.example — ne PAS coder l'IP en dur : dépôt public.) ──
PROXY="${PROXY-${HTTP_PROXY-${http_proxy-}}}"
CURL=(curl -fsSL)
[ -n "$PROXY" ] && CURL+=(-x "$PROXY")

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V="$ROOT/wama/static/vendors"

dl() { "${CURL[@]}" "$1" -o "$2" && echo "  OK   $(du -h "$2" | cut -f1)  ${2#"$ROOT"/}" \
       || { echo "  ECHEC: $1"; exit 1; }; }

echo "== Bootstrap $BOOTSTRAP_VER =="
mkdir -p "$V/bootstrap-$BOOTSTRAP_VER/css" "$V/bootstrap-$BOOTSTRAP_VER/js"
dl "https://cdn.jsdelivr.net/npm/bootstrap@$BOOTSTRAP_VER/dist/css/bootstrap.min.css"      "$V/bootstrap-$BOOTSTRAP_VER/css/bootstrap.min.css"
dl "https://cdn.jsdelivr.net/npm/bootstrap@$BOOTSTRAP_VER/dist/js/bootstrap.bundle.min.js" "$V/bootstrap-$BOOTSTRAP_VER/js/bootstrap.bundle.min.js"

echo "== Font Awesome $FA_VER (css + webfonts) =="
mkdir -p "$V/font-awesome-$FA_VER/css" "$V/font-awesome-$FA_VER/webfonts"
dl "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/$FA_VER/css/all.min.css" "$V/font-awesome-$FA_VER/css/all.min.css"
for f in fa-solid-900 fa-regular-400 fa-brands-400 fa-v4compatibility; do
  dl "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/$FA_VER/webfonts/$f.woff2" "$V/font-awesome-$FA_VER/webfonts/$f.woff2"
done

echo "== jsTree $JSTREE_VER (css default-dark + images + js) =="
mkdir -p "$V/jstree-$JSTREE_VER/themes/default-dark"
dl "https://cdnjs.cloudflare.com/ajax/libs/jstree/$JSTREE_VER/themes/default-dark/style.min.css" "$V/jstree-$JSTREE_VER/themes/default-dark/style.min.css"
for img in 32px.png 40px.png throbber.gif; do
  dl "https://cdnjs.cloudflare.com/ajax/libs/jstree/$JSTREE_VER/themes/default-dark/$img" "$V/jstree-$JSTREE_VER/themes/default-dark/$img"
done
dl "https://cdnjs.cloudflare.com/ajax/libs/jstree/$JSTREE_VER/jstree.min.js" "$V/jstree-$JSTREE_VER/jstree.min.js"

echo
echo "✔ Assets vendorés mis à jour. Étapes suivantes :"
echo "    python manage.py collectstatic --noinput"
echo "    (si une VERSION a changé : ajuster les {% static 'vendors/...' %} de wama/templates/base.html)"
echo "    vérifier l'UI puis committer."
