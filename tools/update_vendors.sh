#!/usr/bin/env bash
# =============================================================================
# Met à jour les assets front vendorés en LOCAL (Bootstrap / Font Awesome / jsTree / three /
# TalkingHead / FullCalendar / gridstack / abcjs / Roboto Flex / MediaPipe Tasks Vision).
# ⚠ Leaflet (cam_analyzer) n'y est pas encore.
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
#      bash tools/update_vendors.sh roboto-flex abcjs   → ces seules sections (clés des `want`)
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
# three 0.180.0 = la version qu'exige l'importmap de l'exemple TalkingHead. Une autre n'est
# PAS garantie compatible : ne pas la monter sans revérifier l'exemple en amont.
THREE_VER=0.180.0
TALKINGHEAD_VER=1.7
# FullCalendar (MIT) — le calendrier de WAMA (WAMA_MEMORY §9bis.1). Le paquet `fullcalendar`
# regroupe cœur + daygrid + timegrid + list + interaction ; ses plugins PREMIUM (resource,
# timeline) sont sous licence commerciale : ne pas les ajouter.
FULLCALENDAR_VER=6.1.15
# gridstack (MIT) — la grille des SURFACES (pages d'édition, `common/surfaces.py`). Vendorisé à la
# main le 2026-10-10, rattaché ici le 2026-10-15 (fichiers identiques à l'octet, vérifié par `cmp`).
GRIDSTACK_VER=13.3.0
# abcjs (MIT) — la gravure des partitions ABC (brique `score_view`, 2026-10-15). Le build
# « basic » suffit : la page n'en tire ni synthé ni éditeur (le son est celui du rendu, le texte
# s'édite par la brique commune) — pas de police de sons à vendoriser.
ABCJS_VER=6.4.4
# Roboto Flex (SIL OFL 1.1) — la police de La Suite numérique (`ROADMAP §28`, thèmes `lasuite` et
# `lasuite-dark`), paquet Fontsource que Cunningham importe lui-même : axe de graisse seul
# (`index.css`, famille « Roboto Flex Variable »), les six sous-ensembles qu'il déclare. Le
# navigateur ne télécharge une fonte que sous un thème qui la demande.
ROBOTO_FLEX_VER=5.3.0
# MediaPipe Tasks Vision (Apache-2.0, Google) — les MAINS qui pilotent les scènes 3D (brique
# `wama-hands.js`, 2026-10-22) : reconnaissance des gestes DANS LE NAVIGATEUR, aucune image ne part
# au serveur. Le paquet npm ne joint pas de LICENSE : celle du dépôt MediaPipe l'accompagne. Ses
# moteurs WebAssembly (~13 Mo chacun) sont GITIGNORÉS, comme l'avatar GLB : ce script les tire.
# Le MODÈLE des gestes n'est pas ici : c'est une ligne du catalogue (`common/hand_gestures.py`).
# ⚠ À chaque montée de version : la librairie envoie une télémétrie d'usage à Google
# (`odml.pa.googleapis.com`), coupée par `wama-hands.js` — rejouer le scénario `common.scene.*.ui`,
# qui refuse tout POST, avant de committer.
MEDIAPIPE_TASKS_VER=1.1.1

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V="$ROOT/wama/static/vendors"

# ── Proxy (optionnel) — priorité : env explicite > .env > HTTP_PROXY > aucun. ──
#   Override ponctuel :  PROXY=http://host:port bash tools/update_vendors.sh
#   Sinon, la clé PROXY du .env (non commité) est utilisée automatiquement.
#   NB : on n'exécute PAS le .env (valeurs à caractères spéciaux) — on extrait la
#   seule ligne PROXY= par sed, en retirant d'éventuels guillemets.
if [ -z "${PROXY:-}" ] && [ -f "$ROOT/.env" ]; then
  PROXY="$(sed -n 's/^[[:space:]]*PROXY=//p' "$ROOT/.env" | tail -n1 | sed -e 's/^["'\'']//' -e 's/["'\'']$//')"
fi
PROXY="${PROXY:-${HTTP_PROXY:-${http_proxy:-}}}"
# Sections demandées en arguments (aucun = toutes) : on ne retélécharge que ce qu'on monte.
ONLY=("$@")
want() { [ ${#ONLY[@]} -eq 0 ] && return 0; local s; for s in "${ONLY[@]}"; do [ "$s" = "$1" ] && return 0; done; return 1; }

CURL=(curl -fsSL)
[ -n "$PROXY" ] && CURL+=(-x "$PROXY")

dl() { "${CURL[@]}" "$1" -o "$2" && echo "  OK   $(du -h "$2" | cut -f1)  ${2#"$ROOT"/}" \
       || { echo "  ECHEC: $1"; exit 1; }; }

if want bootstrap; then
echo "== Bootstrap $BOOTSTRAP_VER =="
mkdir -p "$V/bootstrap-$BOOTSTRAP_VER/css" "$V/bootstrap-$BOOTSTRAP_VER/js"
dl "https://cdn.jsdelivr.net/npm/bootstrap@$BOOTSTRAP_VER/dist/css/bootstrap.min.css"      "$V/bootstrap-$BOOTSTRAP_VER/css/bootstrap.min.css"
dl "https://cdn.jsdelivr.net/npm/bootstrap@$BOOTSTRAP_VER/dist/js/bootstrap.bundle.min.js" "$V/bootstrap-$BOOTSTRAP_VER/js/bootstrap.bundle.min.js"
fi

if want font-awesome; then
echo "== Font Awesome $FA_VER (css + webfonts) =="
mkdir -p "$V/font-awesome-$FA_VER/css" "$V/font-awesome-$FA_VER/webfonts"
dl "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/$FA_VER/css/all.min.css" "$V/font-awesome-$FA_VER/css/all.min.css"
for f in fa-solid-900 fa-regular-400 fa-brands-400 fa-v4compatibility; do
  dl "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/$FA_VER/webfonts/$f.woff2" "$V/font-awesome-$FA_VER/webfonts/$f.woff2"
done
fi

if want jstree; then
echo "== jsTree $JSTREE_VER (css default-dark + images + js) =="
mkdir -p "$V/jstree-$JSTREE_VER/themes/default-dark"
dl "https://cdnjs.cloudflare.com/ajax/libs/jstree/$JSTREE_VER/themes/default-dark/style.min.css" "$V/jstree-$JSTREE_VER/themes/default-dark/style.min.css"
for img in 32px.png 40px.png throbber.gif; do
  dl "https://cdnjs.cloudflare.com/ajax/libs/jstree/$JSTREE_VER/themes/default-dark/$img" "$V/jstree-$JSTREE_VER/themes/default-dark/$img"
done
dl "https://cdnjs.cloudflare.com/ajax/libs/jstree/$JSTREE_VER/jstree.min.js" "$V/jstree-$JSTREE_VER/jstree.min.js"
fi

if want three; then
echo "== three.js $THREE_VER (module + addons) =="
# ⚠ LISTE ISSUE D'UNE FERMETURE TRANSITIVE DES IMPORTS, pas des seuls addons cités par
# TalkingHead. Partir de ses 7 imports aurait manqué fflate (tiré par FBXLoader),
# BufferGeometryUtils et les NURBS* : la page casse alors DANS LE NAVIGATEUR, au premier
# import — rien côté Django ne le signale. À toute montée de version : REVÉRIFIER la liste
# (relancer une résolution récursive des `from '...'` relatifs), ne pas la supposer stable.
THREE_ADDONS=(
  controls/OrbitControls.js
  loaders/GLTFLoader.js
  loaders/DRACOLoader.js
  loaders/FBXLoader.js
  libs/meshopt_decoder.module.js
  libs/stats.module.js
  libs/fflate.module.js
  environments/RoomEnvironment.js
  utils/BufferGeometryUtils.js
  curves/NURBSCurve.js
  curves/NURBSUtils.js
)
mkdir -p "$V/three-$THREE_VER/build"
# ⚠ DEUX fichiers de build depuis r170 : `three.module.js` n'est qu'une FAÇADE qui fait
# `import './three.core.js'`. Ce script n'en tirait qu'un ; le cœur a manqué du 21/08 au
# 13/09 — tout import de `three` (TalkingHead, aperçu 3D) tombait en 404 dans le navigateur,
# et la garde de vendoring ne demandait que la façade. La fermeture transitive vaut aussi
# pour le BUILD, pas seulement pour les addons.
dl "https://cdn.jsdelivr.net/npm/three@$THREE_VER/build/three.module.js" "$V/three-$THREE_VER/build/three.module.js"
dl "https://cdn.jsdelivr.net/npm/three@$THREE_VER/build/three.core.js"   "$V/three-$THREE_VER/build/three.core.js"
dl "https://cdn.jsdelivr.net/npm/three@$THREE_VER/LICENSE"               "$V/three-$THREE_VER/LICENSE"
for a in "${THREE_ADDONS[@]}"; do
  mkdir -p "$V/three-$THREE_VER/addons/$(dirname "$a")"
  dl "https://cdn.jsdelivr.net/npm/three@$THREE_VER/examples/jsm/$a" "$V/three-$THREE_VER/addons/$a"
done
fi

if want talkinghead; then
echo "== TalkingHead $TALKINGHEAD_VER (modules ES6) =="
# ⚠ Les `lipsync-<lang>.mjs` ne sont PAS des imports statiques : `lipsyncGetProcessor()` fait un
# `import()` DYNAMIQUE, chemin par défaut "./" — donc résolu À CÔTÉ de talkinghead.mjs. Ils sont
# invisibles d'une analyse des imports statiques, et leur absence ne casse rien au chargement :
# elle casse À LA PREMIÈRE PHRASE PRONONCÉE. Le module `fr` est justement ce qui rend cette
# voie intéressante pour un labo français (lip-sync à visèmes avec règles françaises).
mkdir -p "$V/talkinghead-$TALKINGHEAD_VER"
for m in talkinghead.mjs retargeter.mjs dynamicbones.mjs \
         lipsync-fr.mjs lipsync-en.mjs lipsync-de.mjs lipsync-fi.mjs lipsync-lt.mjs; do
  dl "https://raw.githubusercontent.com/met4citizen/TalkingHead/main/modules/$m" "$V/talkinghead-$TALKINGHEAD_VER/$m"
done
fi

if want fullcalendar; then
echo "== FullCalendar $FULLCALENDAR_VER (bundle global + locale fr) =="
mkdir -p "$V/fullcalendar-$FULLCALENDAR_VER/locales"
dl "https://cdn.jsdelivr.net/npm/fullcalendar@$FULLCALENDAR_VER/index.global.min.js"           "$V/fullcalendar-$FULLCALENDAR_VER/index.global.min.js"
dl "https://cdn.jsdelivr.net/npm/@fullcalendar/core@$FULLCALENDAR_VER/locales/fr.global.min.js" "$V/fullcalendar-$FULLCALENDAR_VER/locales/fr.global.min.js"
dl "https://cdn.jsdelivr.net/npm/fullcalendar@$FULLCALENDAR_VER/LICENSE.md"                      "$V/fullcalendar-$FULLCALENDAR_VER/LICENSE.md"
fi

if want gridstack; then
echo "== gridstack $GRIDSTACK_VER (bundle + css) =="
mkdir -p "$V/gridstack-$GRIDSTACK_VER"
dl "https://cdn.jsdelivr.net/npm/gridstack@$GRIDSTACK_VER/dist/gridstack-all.js"  "$V/gridstack-$GRIDSTACK_VER/gridstack-all.js"
dl "https://cdn.jsdelivr.net/npm/gridstack@$GRIDSTACK_VER/dist/gridstack.min.css" "$V/gridstack-$GRIDSTACK_VER/gridstack.min.css"
dl "https://cdn.jsdelivr.net/npm/gridstack@$GRIDSTACK_VER/LICENSE"                "$V/gridstack-$GRIDSTACK_VER/LICENSE"
fi

if want abcjs; then
echo "== abcjs $ABCJS_VER (build basic) =="
mkdir -p "$V/abcjs-$ABCJS_VER"
dl "https://cdn.jsdelivr.net/npm/abcjs@$ABCJS_VER/dist/abcjs-basic-min.js" "$V/abcjs-$ABCJS_VER/abcjs-basic-min.js"
dl "https://cdn.jsdelivr.net/npm/abcjs@$ABCJS_VER/LICENSE.md"              "$V/abcjs-$ABCJS_VER/LICENSE.md"
fi

if want roboto-flex; then
echo "== Roboto Flex $ROBOTO_FLEX_VER (axe de graisse, 6 sous-ensembles) =="
RF="https://cdn.jsdelivr.net/npm/@fontsource-variable/roboto-flex@$ROBOTO_FLEX_VER"
mkdir -p "$V/roboto-flex-$ROBOTO_FLEX_VER/files"
dl "$RF/index.css" "$V/roboto-flex-$ROBOTO_FLEX_VER/index.css"
dl "$RF/LICENSE"   "$V/roboto-flex-$ROBOTO_FLEX_VER/LICENSE"
for sub in latin latin-ext cyrillic cyrillic-ext greek vietnamese; do
  dl "$RF/files/roboto-flex-$sub-wght-normal.woff2" "$V/roboto-flex-$ROBOTO_FLEX_VER/files/roboto-flex-$sub-wght-normal.woff2"
done
fi

if want mediapipe; then
echo "== MediaPipe Tasks Vision $MEDIAPIPE_TASKS_VER (bundle ES + moteurs WebAssembly) =="
MP="https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@$MEDIAPIPE_TASKS_VER"
D="$V/mediapipe-tasks-vision-$MEDIAPIPE_TASKS_VER"
mkdir -p "$D/wasm"
dl "$MP/vision_bundle.mjs" "$D/vision_bundle.mjs"
# Le moteur SIMD (tout navigateur récent) et son repli sans SIMD, que `FilesetResolver` choisit.
for f in vision_wasm_internal vision_wasm_nosimd_internal; do
  dl "$MP/wasm/$f.js"   "$D/wasm/$f.js"
  dl "$MP/wasm/$f.wasm" "$D/wasm/$f.wasm"
done
dl "https://raw.githubusercontent.com/google-ai-edge/mediapipe/master/LICENSE" "$D/LICENSE"
fi

if want avatar; then
echo "== Avatar de test (GLB) — NON COMMITÉ =="
# 4,7 Mo de binaire : téléchargé comme MuseTalk l'est par setup_avatarizer.sh, PAS versionné
# (git ne compresse pas un GLB : chaque révision pèserait à nouveau 4,7 Mo dans l'historique).
# Le dossier est gitignoré. Licence CC BY-NC 4.0 — usage recherche, acceptable au labo.
mkdir -p "$V/avatars"
dl "https://raw.githubusercontent.com/met4citizen/TalkingHead/main/avatars/brunette.glb" "$V/avatars/brunette.glb"
fi

echo
echo "✔ Assets vendorés mis à jour. Étapes suivantes :"
echo "    python manage.py collectstatic --noinput"
echo "    (si une VERSION a changé : ajuster les {% static 'vendors/...' %} de wama/templates/base.html)"
echo "    vérifier l'UI puis committer."
