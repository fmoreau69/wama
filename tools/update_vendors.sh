#!/usr/bin/env bash
# =============================================================================
# Met à jour les assets front vendorés en LOCAL (Bootstrap / Font Awesome / jsTree / three /
# TalkingHead / FullCalendar / gridstack / abcjs / Roboto Flex / MediaPipe Tasks Vision / uPlot).
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
# L'ÉTIQUETTE amont d'où se tirent les modules (2026-10-28). La branche `main` était lue jusque-là :
# une montée de version pouvait passer sans qu'on la décide. Mesuré le jour même : les huit modules
# vendorisés le 2026-08-21 sont identiques à l'octet à `v1.8.2` (et à `v1.8.0`) — le dossier garde
# son nom `1.7`, que l'importmap commune cite.
TALKINGHEAD_TAG=v1.8.2
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
# uPlot (MIT) — les COURBES dans le temps (brique `timeseries_chart`, 2026-10-29 : les premiers
# plugins graphiques du monde Data, sur le face_analyzer). Le candidat retenu par `WAMA_DATA_WORLD`
# (« Position sur les BIBLIOTHÈQUES ») : une bibliothèque qui DESSINE, faite pour les longues séries,
# jamais une qui décide de la mise en page. Build IIFE (global `uPlot`) + sa feuille.
UPLOT_VER=1.6.32
# SpessaSynth (Apache-2.0) — la LECTURE MIDI d'une partition dans le navigateur, sans générer
# d'audio (2026-11-08, décision de Fabien : « SpessaSynth », le meilleur rendu côté client de la
# veille, `PROSPECTION_PIPELINE §Session du 2026-11-08`). Module ES + processeur AudioWorklet ; le
# module importe par leur NOM `spessasynth_core`, qui importe `fflate` (MIT) et `stb-vorbis`
# (Apache-2.0) — d'où quatre paquets épinglés ENSEMBLE, résolus par l'importmap de la brique
# (`wama-midi-player.js`). `spessasynth_lib` 4.4.7 exige `spessasynth_core` ^4.4.9.
SPESSASYNTH_LIB_VER=4.4.7
SPESSASYNTH_CORE_VER=4.4.9
FFLATE_VER=0.8.3
STB_VORBIS_VER=0.0.7
# Les BANQUES DE SONS que SpessaSynth (et FluidSynth, côté serveur) jouent — deux, à COMPARER à
# l'écoute (décision de Fabien, même jour : « tester les 2 pour voir ce qui sonne le mieux »).
# GITIGNORÉES comme l'avatar GLB (32 et 40 Mo de binaire). GeneralUser GS (licence permissive de son
# auteur, `documentation/LICENSE.txt`), épinglée au COMMIT de son dépôt — elle se charge aussi en
# ligne (`raw.githubusercontent.com` sert l'en-tête CORS), la copie locale en secours ;
# MuseScore_General (MIT, `MuseScore_General_License.md`), en SF3 compressé, du miroir OSUOSL — sans
# en-tête CORS, donc en local seulement.
GENERALUSER_GS_COMMIT=97049183643d5fc5a9322a69c5b09efb667c6c3a
MUSESCORE_GENERAL_BASE=https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General

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
# ⚠ `playback-worklet.js` non plus (2026-10-28) : le MODE FLUX (`streamStart`, la voix de
# l'assistant au fil de l'eau) le charge par `audioWorklet.addModule(new URL('./playback-worklet.js',
# import.meta.url))` — absent, la voix en flux échoue au premier mot (« Failed to initialize
# streaming speech »), et rien d'autre ne le dit.
mkdir -p "$V/talkinghead-$TALKINGHEAD_VER"
for m in talkinghead.mjs retargeter.mjs dynamicbones.mjs playback-worklet.js \
         lipsync-fr.mjs lipsync-en.mjs lipsync-de.mjs lipsync-fi.mjs lipsync-lt.mjs; do
  dl "https://raw.githubusercontent.com/met4citizen/TalkingHead/$TALKINGHEAD_TAG/modules/$m" "$V/talkinghead-$TALKINGHEAD_VER/$m"
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

if want uplot; then
echo "== uPlot $UPLOT_VER (build IIFE + css) =="
mkdir -p "$V/uplot-$UPLOT_VER"
dl "https://cdn.jsdelivr.net/npm/uplot@$UPLOT_VER/dist/uPlot.iife.min.js" "$V/uplot-$UPLOT_VER/uPlot.iife.min.js"
dl "https://cdn.jsdelivr.net/npm/uplot@$UPLOT_VER/dist/uPlot.min.css"     "$V/uplot-$UPLOT_VER/uPlot.min.css"
dl "https://cdn.jsdelivr.net/npm/uplot@$UPLOT_VER/LICENSE"                "$V/uplot-$UPLOT_VER/LICENSE"
fi

if want spessasynth; then
echo "== SpessaSynth $SPESSASYNTH_LIB_VER (+ core $SPESSASYNTH_CORE_VER, fflate $FFLATE_VER, stb-vorbis $STB_VORBIS_VER) =="
D="$V/spessasynth-$SPESSASYNTH_LIB_VER"
mkdir -p "$D/lib" "$D/core" "$D/fflate" "$D/stb-vorbis"
NPM=https://cdn.jsdelivr.net/npm
dl "$NPM/spessasynth_lib@$SPESSASYNTH_LIB_VER/dist/index.js"                     "$D/lib/index.js"
dl "$NPM/spessasynth_lib@$SPESSASYNTH_LIB_VER/dist/spessasynth_processor.min.js" "$D/lib/spessasynth_processor.min.js"
dl "$NPM/spessasynth_lib@$SPESSASYNTH_LIB_VER/LICENSE"                           "$D/lib/LICENSE"
dl "$NPM/spessasynth_core@$SPESSASYNTH_CORE_VER/dist/index.js"                   "$D/core/index.js"
dl "$NPM/spessasynth_core@$SPESSASYNTH_CORE_VER/LICENSE"                         "$D/core/LICENSE"
dl "$NPM/fflate@$FFLATE_VER/esm/browser.js"                                      "$D/fflate/browser.js"
dl "$NPM/fflate@$FFLATE_VER/LICENSE"                                             "$D/fflate/LICENSE"
dl "$NPM/stb-vorbis@$STB_VORBIS_VER/dist/index.js"                               "$D/stb-vorbis/index.js"
# Les imports NOMMÉS (`from "spessasynth_core"`…) réécrits vers les copies voisines : un navigateur
# ne résout pas un nom de paquet sans importmap, et une importmap injectée à chaud dépend de
# l'ordre de chargement des modules de la page. Le processeur AudioWorklet, lui, est autonome.
sed -i 's#from "spessasynth_core"#from "../core/index.js"#g' "$D/lib/index.js"
sed -i -e 's#from "fflate"#from "../fflate/browser.js"#g' -e 's#from "stb-vorbis"#from "../stb-vorbis/index.js"#g' "$D/core/index.js"
if grep -q 'from "[a-z_-]*"' "$D/lib/index.js" "$D/core/index.js"; then
  echo "  ECHEC: un import nommé reste à résoudre dans SpessaSynth"; exit 1
fi
fi

if want soundfonts; then
echo "== Banques de sons (GeneralUser GS @${GENERALUSER_GS_COMMIT:0:7}, MuseScore_General SF3) — NON COMMITÉES =="
mkdir -p "$V/soundfonts"
GU="https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/$GENERALUSER_GS_COMMIT"
dl "$GU/GeneralUser-GS.sf2"                     "$V/soundfonts/GeneralUser-GS.sf2"
dl "$GU/documentation/LICENSE.txt"              "$V/soundfonts/GeneralUser-GS_LICENSE.txt"
dl "$MUSESCORE_GENERAL_BASE/MuseScore_General.sf3"         "$V/soundfonts/MuseScore_General.sf3"
dl "$MUSESCORE_GENERAL_BASE/MuseScore_General_License.md"  "$V/soundfonts/MuseScore_General_License.md"
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
