# Cam Analyzer — Journal des modifications (traçabilité & annulation)

> **Règle** : TOUTE modification qui change le comportement (positionnement, cap, distances,
> tracking, affichage) reçoit une entrée ici — quoi / pourquoi / comment annuler / validation.
> **Annulation** : `git revert <commit>` (chaque entrée = 1 commit atomique), puis
> `cp wama_lab/cam_analyzer/static/cam_analyzer/js/index.js staticfiles/cam_analyzer/js/index.js`
> si du JS est touché, et **restart du process WSL2** si du Python est touché.
> Si une régression de qualité est constatée, remonter ce tableau du plus récent au plus
> ancien pour identifier le changement fautif.
>
> Chaîne complète : [`CAM_ANALYZER_CHAINE_TRAITEMENT.md`](CAM_ANALYZER_CHAINE_TRAITEMENT.md).
> Spécificités **projet** ENA_CASA (données/calibration/rig) : [`projects/ENA_CASA.md`](projects/ENA_CASA.md).

---

# État courant & RESTE À FAIRE

> Absorbe l'ex-`CAM_ANALYZER_TOPDOWN_STATUS.md` (archivé). Photo au **2026-07-21**. Le détail
> historique est dans le journal daté plus bas ; ici = **où on en est + ce qui reste**.

## Cause racine (audit 2026-07-15) — et son traitement

Le basculement `6509cc2` a mis la position en **100 % pinhole** (échelle correcte mais **bruitée
±20 %** via hauteur de bbox) → orientation, fusion 360°, fantômes, stationnés en héritent. Traité
depuis : estimateur de pitch (`homography_estimator.py`, désaccord 14,55→**3,05 m** ×5, k1 écarté),
Kalman+RTS (`trajectory_smoother.py` → `world_en`), ground calib 2a (⚑ OFF), recalage ortho 2b
(rapport seul). **La position sous-jacente était la cause — pas 360°/fantômes/orientation.**

## FAIT (synthèse par thème — détail = journal daté)

Position/échelle (pinhole→pitch ×5, Kalman+RTS, ground calib 2a flag OFF) · Tracking 360° + fusion
(verrou de chaîne gid, enchaînement fin de Live, trajectoires fusionnées) · Fantômes/reconstitution
(comblement ≤6 s, héritage mesures, stationnés ancrés position monde) · Filtres reflets/artefacts ·
Cap/orientation (consensus axial, fondu ratio↔trajectoire) · Marquages monde SAM3 (⚑) · Intersections
/branches apprises · Ortho/recalage IGN + mini-carte orientable · Live/complétion + préemption ·
Levier antenne GPS · UI toolbar par familles + bascules ⚑ génériques.

## RESTE À FAIRE (priorisé — qualité/cohérence vue de dessus)

**P1 — le cœur (position) :**
1. **Métrique A/B objective** (préalable/instrument) : exposer `distance_source` par détection +
   un désaccord chiffré (RMS reprojection stationnés, ou sol⟷pinhole⟷ortho) dans l'UI/rapport. C'est
   ce qui permet de **valider** P1.2/P1.3 sans « à l'œil » — et c'est une **brique commune** réutilisable.
2. **Terminer 2a (pitch)** : corriger le placement mixte **G7**, puis basculer `auto_ground_calib`
   ON sur une session ENA, **mesurer** l'A/B, décider du défaut.
3. **Appliquer l'offset ortho 2b** (~5,1 m mesuré) derrière un **nouveau flag** (aujourd'hui rapport seul).
4. **Calibration jointe 2c** (pitch + échelle réconciliés avec l'ortho).
5. **Passe de validation NAVIGATEUR systématique** : la majorité des commits 07-17→07-20 sont
   **compile/parse-only** (« navigateur à valider »). Rejouer une session ENA (ex. `4da52df3`),
   relancer « Calculer les indicateurs » (recale les `world_en` avec l'antenne), vérifier à l'écran.

**P2 — compléments :** voie/vidéo ancré yolopv2 détectés (audit #3) · FOV réel 55↔97° à confirmer
(audit #4) · vitesse/distance unifiées par track (`track_speed_unified` = **stub, 0 consommateur**) ·
mask_geometry / YOLO-OBB (non implémenté) · dépassement depuis trajectoires monde par `global_track_id`.

## Gaps vérifiés dans le code (2026-07-21 — audit de reprise)

| # | Constat (fichier) | Gravité | Statut |
|---|---|---|---|
| **G7** | `auto_ground_calib` ON → `ground_ego` retombe **silencieusement** sur pinhole hors portée (`multicam_tracker.py:204`) → **placement MIXTE** sans indication → **fausse tout A/B** du flag. Corriger avant/avec la métrique (clé = `distance_source`). | Haute | vérifié |
| **G8** | `_run_global_tracking` avale les échecs de `learn_branches`/`aggregate_markings` (`except non-blocking`) → clés `results_summary` **périmées en silence**. | Moyenne | rapporté |
| **G2** | Bloc SAM3 inline **mort** dans `process_session_task` + `_use_sam3_fallback` **jamais défini** (`tasks.py:1336`) = `NameError` latent, masqué car le garde est toujours faux (SAM3 tourne via la tâche enchaînée). | Basse | vérifié (mort par design) |
| **G4** | Marque de traçabilité au FOV **codé en dur** `{front:60,rear:60,left:90,right:90}` (`tasks.py:1562`) divergent du `DEFAULT_FOV_V_DEG` réellement appliqué → la trace peut mentir. | Basse | rapporté |
| ~~G3~~ | *(affirmé par l'audit : `fov_v_used` non écrit par la passe inline)* — **RÉFUTÉ** : `tasks.py:1268` l'écrit bien par caméra. Fausse alerte conservée pour mémoire. | — | réfuté |

## Non-régression (OBLIGATOIRE à chaque modif) — voir procédure détaillée en fin de doc

CHANGELOG + 1 commit atomique · `py_compile` + `manage.py check` · **parse esprima** du JS · **sync**
`staticfiles/` si JS · migrations sur **les DEUX bases** (Windows + WSL2) · **restart WSL2** si Python ·
pas de tests destructifs (user id=1 = Fabien réel, `transaction.atomic()`) · pas de `cd` en préfixe ·
**une amélioration comparable = un flag ⚑** (`utils/features.py`), jamais de `if` ad hoc.

---

## 2026-07-21

| Commit | Quoi | Pourquoi | Validation/annulation |
|---|---|---|---|
| *(doc)* | **Refactoring documentation** : 6 docs → **3 piliers** (README/CHAINE/CHANGELOG) + `projects/ENA_CASA.md` (spécificités projet façonnées manifeste). `DISTANCE_DESIGN`/`TOPDOWN_STATUS`/`CONTEXT` **archivés** (`archive/`) après absorption. Correction dérive CHAINE (date + étape [4] + 2b). Consignation des gaps G7/G8/G2/G4. | La carte de référence (CHAINE) avait dérivé derrière le changelog ; docs redondants → mises à jour multiples à chaque changement. App générique vs spécificités projet mélangées. | Aucun code touché ; `git revert` du commit doc. Contenu vivant préservé (absorbé), reste dans `git log` + `archive/`. |

## 2026-07-20

| Commit | Quoi | Pourquoi | Validation/annulation |
|---|---|---|---|
| `4069c82` | **Passes détection débloquées après complétion** : `mark_completed(yolo_detect/yolopv2_lanes)` avant le `continue` « caméra déjà couverte » | Après « Compléter l analyse », front/left/rear restaient « en cours » — le continue sautait le mark_completed de fin de boucle, la passe restait started | 8 passes réparées (running/failed→completed) ; restart WSL pour charger le fix |
| `6266444` | **Mini-carte ne fige plus** (rafLoop try/finally re-planifie toujours + validateur `_okLL` coords) + **declutter marquages** (stop_line/crossing ≤18 m seulement, « line » bruitées retirées) + **point rouge = antenne** (`antennaPoint`, arrière-droit) | Figement du playback près des marquages (throw dans le dessin tuait la boucle rAF) ; marquages « n'importe comment » ; point rouge lu comme l antenne mais au centre | Coords stockées valides (0/392 hors zone) → figement = redraw+fragilité ; représentation corrigée, chaîne juste |
| `fd8998d` | **Filtre fantômes géants** (`is_giant_reflection` : bbox >50 % image + conf <0,55) — tracker (exclusion, ⚑ artifact_filter) + JS (masquage immédiat vidéo+top-down) | Le critère cinématique ne captait pas les reflets géants fragmentés (bbox 90-99 %, conf basse) | Vérifié reflet arrière 595 s : 22/32 dets captées, vrais véhicules épargnés |
| `552dd24` | **Levier antenne sur la route virtuelle** (gabarit de voie `_sm` + marqueur initial via `antennaCorrect`) + boutons zoom mini-carte descendus (30 px) + **toolbar en 3 sections encadrées** (Calibration/Vue/Analyse) | Navette dessinée sur la ligne centrale : le gabarit de voie utilisait le GPS BRUT (antenne) alors que navette+objets sont au centre véhicule ; zoom masqué par le badge ; toolbar plate brouillonne | Audit chaîne complet (tracker/prediction/marking_world/branches/estimator déjà corrigés, origines cohérentes) ; déplacement 1,00 m vérifié ; tous boutons conservés (IDs) |
| `034912c` | **Étape 2b — recalage absolu ortho** (`ortho_markings.py`) : mosaïque tuiles IGN z19 + géo-transform Web Mercator exacte + SAM3 passages piétons sur l ortho + matching avec crossings caméra → offset par intersection ; tâche + bouton « Recalage ortho » + tracé orange sur mini-carte | L échelle/position absolue que 2a (angle) ne peut donner ; passages piétons ortho = vérité géoréférencée | Vérifié : géo-transform 0 cm, SAM3 2 crossings/intersection (conf 0,7), offset global 2,93 E/4,2 N m (~5,1 m) ; RAPPORT seul (offset non appliqué) ; validation visuelle ortho à faire |
| `48b46df` | **Étape 2a — placement par projection sol** (⚑ auto_ground_calib OFF) : `store_ground_calib` (pitch/hauteur par caméra, filtre qualité ≥6 obj + étalement ≤2,5 m) + `ground_ego`/`ground_projector_for` + branchement tracker avec fallback pinhole + auto-calcul dans _run_global_tracking | Intégrer le gain d angle (×5) derrière bascule pour A/B, sans casser le pinhole | avant 22°/1,53 m + droite 26,5°/1,6 m RETENUES, arrière/gauche REJETÉES (>2,5 m) ; tracking flag ON = 5212 tracks world_en 100% ; défaut OFF restauré ; A/B visuel ortho à faire |
| `8a19577` | **Estimator pitch×k1** (hauteur fixée physique, distorsion radiale testée) | Vérifier si le résiduel 3 m vient des dômes AXIS 110° non rectilinéaires | k1 SATURE la borne (+0,45) sans gain (désaccord 3,05→3,05) → PAS le levier ; le pitch reste le vrai gain (14,55→3,05 m ×5). Résiduel = ancrage pinhole + bruit bbox. Suite : intégrer le pitch seul derrière bascule pour A/B |
| `51b8b95` | **Branches resserrées** (span≥14 m, centreligne <8 m de la balise, ≥4 véh.) + **homography_estimator v1** (rapport seul : solve pitch/hauteur par étalement monde des statiques + ancrage pinhole) | Validation ortho : nappes diagonales = manœuvres de parking ; placement objets — mesuré baseline désaccord sol⟷pinhole 14,55 m → 3,0 m à pitch 21,5°/h 2,2 | RIEN branché sur le positionnement (flag futur) ; prochain levier = distorsion k1 |
| `7a2b36f` | **Bouton 🧭 cap navette en haut** (leaflet-rotate vendorisé, throttle 1,5°, persisté) + **Leaflet vendorisé local** (unpkg → vendors/, conformité assets locaux) | Demande utilisateur : mini-map orientée comme la vue caméra, façon GPS | esprima+check OK ; validation navigateur à faire |
| `91d85f7` | **Marquages SAM3 en monde** (⚑ world_markings, `marking_world.py`) : projection bord-bas 2-12 m via GroundProjector EXISTANT, agrégation multi-passages (amas+fusion+top-K), reclassement géométrique ∥corridor→line, affichage mini-map typé | Idée utilisateur : stop_line/crossing = bornes réelles d intersection + branche sans trafic ; 3 itérations mesurées (1498→196 segments, PCA corridor→bord bas) | stop_line 2e intersection à 74°⊥ (153 fr.) ✓ ; validation visuelle ortho à faire ; étape 2 = fusion + homography_estimator |
| `6053185` | **Interpolation SAM3 entre keyframes** (⚑ sam3_interp : morphing translation+échelle apparié par label+centroïde, fondu entrée/sortie, 2 chemins de rendu) + **cadence au profil** (`sam3_fps`, migration 0020 des 2 côtés, éditeur de profil) | Marquages visibles 1 frame/6 (clignotement) ; densifier SAM3 = coût ×2 du modèle le plus lourd — l interpolation est gratuite et exacte aux keyframes | py_compile+esprima+check OK ; validation visuelle navigateur à faire (virages = cas limite documenté) |
| `edd269e` | Branches **mutualisées par intersection physique** (lat/lon ~1 m près : 1 analyse/lieu, partagée entre passages) + ortho IGN `maxNativeZoom` 19 | Passages multiples du même carrefour → jeux de branches contradictoires superposés (« croix ») ; tuiles z20 absentes par endroits → fond vide | 28 fenêtres → 2 jeux distincts ; session réparée après restart pendant complétion |
| `0ead425` | **Levier antenne GPS** (⚑ antenna_lever, coin arrière droit ENA, config gps_antenna + 2 champs Calibration, appliqué Python+JS) + **branches apprises du trafic** (⚑ learned_branches, `intersection_branches.py`, filtre rectitude, 2 dominantes ≥3 véh., dessinées à la place de la bande symétrique, fallback conservé) + **fond ortho IGN 20 cm** (bouton 🛰 persisté) | Repère calé ~1 m à droite (GPS=antenne≠centre) ; bande perpendiculaire aveugle des 2 côtés ; largeurs de fond raster symboliques | Mesuré : déport 1,00 m ; 56 branches/28 fenêtres ; run 197 s 4631 tracks ; validation navigateur à faire (relancer Indicateurs pour recaler les world_en avec l antenne) |

## 2026-07-19

| Commit | Quoi | Pourquoi | Validé |
|---|---|---|---|
| `4672900` | **Anti-empilement live** : verrou de spawn atomique (cache.add 15 s) dans `live_cursor` + cooldown 30 s post-préemption (sortie silencieuse) dans la tâche | 1440 messages mesurés en file gpu (1427 live empilées par le POST curseur pendant le blocage) → drainage = 10 min de spam + watchdog re-déclenché | File assainie à chaud (LREM ciblé, 1433 retirés, 1 complétion + 1 indicateurs conservés) |
| `d0c70e9` | **Préemption batch > Live** : `_pause_live` avant chaque dispatch GPU, boucle live rend le slot si session PENDING/PROCESSING (check 3 s), `live_cursor` → 409 si batch en cours (le JS coupe le bouton), lancement batch coupe le Live côté client ; raisons d arrêt user/preempt (pas d enchaînement sur préemption) ; la complétion enchaîne elle-même le tracking global | Starvation : le Live persistant occupait l unique slot worker GPU → complétion > 5 min en file → watchdog « worker mort » → session failed → UI vide (diagnostic utilisateur exact) | session réparée (failed→completed, données intactes) ; zombie live à l ancien code → RESTART Celery requis |
| `a48fab0` | **Filtre artefacts cinématique** (⚑ artifact_filter, marqué jamais supprimé, exclu tracking+affichage) + **cap serveur des ancres** (consensus axial ratio sur toute la vie du track, ⚑ anchor_heading) + **prior cluster** (voisins <15 m, ⚑ heading_cluster) | Chantiers 1-2-3 validés en discussion : reflets détectés comme véhicules, cap des garés instable par frame | 91 artefacts marqués, 31/31 ancres avec cap (160,3°=axe rue) ; LIMITE : reflets « fantômes géants » fragmentés non couverts → raffinement candidat à venir |
| `699b072` | **Enchaînement auto fin de Live** : `_run_global_tracking` (cœur partagé) + passe pipeline « Tracking 360° » (GLOBAL_TRACKING, migration 0019 des 2 côtés) + arrêt Live immédiat (flag stop) + poller JS qui recharge détections et données dérivées à la fin | En sortant du Live, les nouvelles détections restaient en affichage « repli » jusqu à un « Calculer les indicateurs » manuel (validé utilisateur : auto pour le tracking ~90 s, TTC/PET reste manuel) | smoke test : 2844 tracks, passe visible completed ; navigateur à valider |
| `90ac4b1` | **Trajectoires fusionnées Kalman+RTS** : `trajectory_smoother.py` (générique, testé ×4,9) ; tracker écrit `world_en` lissé sur chaque détection (+fantômes) ; affichage = hiérarchie ancre > world_en > reconstruction (gardes par-frame réservées au repli) | Disparitions en vue de dessus pendant les manœuvres (G15) : reconstruction par frame/caméra + gardes anti-bruit jetaient l objet tracké | re-run tracking 93 s : 99 % des dets trackées du dépassement avec world_en, chaînes continues ; navigateur à valider |
| `d61652e` | **Routes perpendiculaires aux intersections** en vue de dessus : bande magenta ancrée sur la balise (repère GPS), orientée ⟂ au bearing_deg de la fenêtre, longueur 2×rayon, largeur 2 voies + axe pointillé | La route croisée n était portée que par les tuiles OSM (qui flottent vs repère GPS) → balise perçue décalée alors qu elle est bien placée (Distance min 2 m cohérent) ; demande utilisateur | parse OK ; navigateur à valider |
| `92553ce` | **Fix Live : `playheadT()`** — pas de globale currentTime, 12 gardes `typeof currentTime` silencieusement morts (curseur Live à 0, merge jamais exécuté, re-renders immédiats yaw/FOV/bascules inertes) ; + bouton Live persistant (localStorage) | Live sans effet visuel malgré une tâche serveur qui produisait (+840 s de couverture mesurés en cache/base) | parse OK ; à re-tester en lecture |
| `411c817` | **Mode LIVE — analyse au fil de la lecture** (étape 3) : `live_analysis_task` (boucle curseur+lookahead 15 s, modèles gardés chargés, zéro GPU si couvert, sortie après 90 s d inactivité, parité d inférence batch) + endpoint `live-cursor/` + bouton ⚡ Live (curseur 1,2 s, fusion incrémentale des détections 3 s) | Combler visuellement les trous d analyse pendant la lecture (discussion utilisateur : jouable et pas trop lourd — même mécanisme que la complétion, playhead = curseur de priorité) | compile/parse/route OK ; run GPU réel à déclencher (bouton) |

## 2026-07-18

| Commit | Quoi | Pourquoi | Validé |
|---|---|---|---|
| `6b43a0b` | **Complétion d analyse batch** (étape 2) : `process_session_task(completion_scope)` analyse les seules tranches manquantes via l itérateur fenêtré ; pas de wipe, pas de vidéo annotée ; `ignore_conflicts` aux bords ; endpoint `complete-analysis/` + boutons panneau pipeline avec ligne de couverture | Une session analysée « restreinte » ne pouvait produire un rapport plein-parcours qu en ré-analysant tout ; design complétion validé avec l utilisateur | compile/parse/route OK ; run GPU réel à déclencher via le bouton, puis « Indicateurs » pour souder |
| `6d518e5` | **Registre de couverture** (étape 1 analyse incrémentale) : `intervals.py` commun (testé) + `coverage.py` (get/add/reset/missing/rebuild_from_db) + consignation en fin de passe caméra + reset au wipe ; registre reconstruit pour les sessions existantes | Fondation de la complétion batch + du futur mode « analyse au fil de la lecture » | tests unitaires intervalles OK ; mesuré : sessions ENA couvertes à 22 %, 6512 s manquantes en 19 tranches pour le scope complet |
| `269cc1d` | **Éditeur de profil scindé** : modèles d ANALYSE (yolopv2 4 vues, modèle route, SAM3) toujours visibles (analysisModelsSection) ; section intersections = restriction + CRUD/carte seulement. + design « analyse incrémentale par complétion » consigné doc chaîne (scope=union des rapports, registre de couverture, coutures réparées par tracker 360°, vidéo annotée non patchée) | Le profil Dépassements ne pouvait pas configurer de modèle route (champs génériques enfermés dans la section intersections masquée) ; question archi utilisateur analyse vs rapport | IDs vérifiés par script ; navigateur à valider |
| `818036c` | **Doctrine calculs génériques** : YOLOPv2 gouverné par road_model_path (plus par report_type), fenêtres par intersections déclarées ; seule la couche segments/conflits/rendu branche sur le type de rapport ; profil Dépassements doté du modèle route (jamais eu) | Le rapport dépassements devait hériter de toutes les améliorations — calculs généraux, seule la sortie diffère (demande utilisateur) | compile+check OK ; ré-analyser une session dépassements pour valider |
| `41bef1a` | **Fenêtres d intersection converties en TEMPS VIDÉO** ((ts−offset)/scale dans recompute_intersection_windows) — convention : intersection_windows est en temps vidéo | Fenêtres bornées en temps GPS mais consommées en temps vidéo partout → décalage linéaire (scale 0,96 : +6 s→+335 s), passages ratés par l analyse restreinte, saut-vers-passage avant le centre (balise « décalée ») | mesuré : 28 fenêtres corrigées, 16 étaient VIDES de détections → ré-analyse session nécessaire |
| `65d5f38` | **Stationnés ANCRÉS en position monde** : ancre = médiane des observations du track (tracker, `stationary_anchors` {gid: [lat,lon]} dans results_summary) ; l affichage dessine les garés à position FIXE (bypass reconstruction par frame) ; cap toujours fourni par le ratio-bbox | Hors de l axe caméra, erreur de position ∝ gisement (erreur focale × \|bcx−cx\|) : le gisement balayé au passage de la navette faisait décrire un arc aux garés → jitter + rotation (diagnostic utilisateur : seuls ceux DANS l axe étaient stables) | 18 stationnés → 18 ancres persistées, coordonnées plausibles ; rendu navigateur à valider |

## 2026-07-17

| Commit | Quoi | Pourquoi | Validé |
|---|---|---|---|
| `e81fdf2` | **Fantômes : héritage des mesures** — dist_euclid_m géométrique (tooltip + couleur distance), class_name = majorité du track ; cap déjà hérité via la trace commune ; vitesse/TTC volontairement non fabriqués | Fantômes muets (tooltip vide, cyan, classe de la 1re frame) — question utilisateur héritage cap/mesures | vérifié en base : dépassement car/car, xy cohérents, d 2,5-2,7 m |
| `3fdbb41` | **Reconstitution de trajectoire des mobiles** : détections coupées au bord mais trackées DESSINÉES (le « masque » au contact de la navette) ; comblement fantôme étendu (trous ≤ 6 s, interpolation entre mesures réelles, zones derrière/à côté incluses — filtre lon≤0 supprimé) ; stationnés EXCLUS du comblement (bloc déplacé avant) | Le véhicule disparaissait pile pendant la phase de dépassement (garde bord d image) et les trous de trajectoire restaient vides sur la minimap (fill 1,2 s, avant seulement) | validé : trou G242 (1182,8→1184,4 s) comblé par 18 fantômes tous au bon gid |
| `318ff21` | **Tracking 360° : verrou de chaîne** (un track YOLO par caméra garde son gid, NN réservé aux chaînes nouvelles) ; **mesures dégradées** (bbox coupée au bord : prolonger/rejoindre un track existant, jamais créer) ; **recollement de tracklets** (stitching cinématique post-passe, prédiction depuis un fit linéaire sur la queue saine de l historique, garés jamais fusionnés) | Dépassement G432 (arrière→gauche→avant) : gid churnait (#166 = 6 gids), le véhicule au flanc disparaissait (latérale 100 % coupée au bord), tracklets arrière/avant jamais recollés (fin de track corrompue à <3 m) | validé 3 runs complets session 4da52df3 : dépassement rear #161 + front #144 = gid 242 unique ; bus front→rear 19 s/7 tracklets = gid 254 ; zéro churn |
| `556973f` | Commentaire Django `{# #}` multi-ligne affiché en texte brut dans le panneau (remplacé par `{% comment %}`) + **ordre chronologique** : bouton Calibration EN PREMIER (étape 1), puis Vue, puis Analyse | Piège connu (4e récidive) introduit par la réorganisation `a859656` ; demande utilisateur d ordre chronologique du workflow | vérifié : 26 IDs, 0 `{# #}` multi-ligne restant |
| `a859656` | **Barre vue de dessus réorganisée par familles** : VUE (360°/Préd/Garés/Voie·vidéo + Conf/Voie) · ANALYSE (Indicateurs/Comparer/debug) · panneau CALIBRATION repliable (synchro GPS, Sync .rec, yaw+FOV, H cam, sol) ; « Modes »→« Comparer » ; bouton Yaw dédié retiré (redondant, champs dans le panneau) | 18 contrôles en vrac, débordements, bouton 💾 invisible ; demande de regroupement clair (option « calibration repliée » choisie par l utilisateur) ; 360°/Préd PAS fondus dans Comparer (sémantique affichage ≠ comparaison d algorithmes) | aucun ID perdu (vérifié script) ; navigateur à valider |
| `db66027` | **FOV latéral réglable par session** (config['camera_fov'], input « FOV lat. » dans l éditeur Yaw, V dérivé de la table F1015 52↔97°H/30↔53°V) — dist_scale s ajuste SANS ré-annotation ; **tooltip top-down systématique** (classe·G·distance corrigée·vitesse rel.·TTC — l ancien affichait dist_euclid_m, champ homographie souvent absent → tooltips vides/partiels) | Distances latérales incohérentes (7-9 m pour des garés à ~3-4 m) : la vari-focale F1015 est probablement restée au réglage LARGE ~97°H, pas 55° supposé — un FOV réel plus grand que supposé SURESTIME les distances (contre-calcul #247 : 7,39 m@31°V → 4,11 m@53°V) ; tooltips erratiques (constat utilisateur) | smoke test dist_scale 0.556 OK ; à comparer 55↔97 à l écran |
| `6b07648` | **Rafraîchissement de fin des passes légères** : poller dédié aux PASSES (grâce ~10 s, arrêt quand plus aucune n est running, puis rechargement détections+sessions+panneau) ; runPasses distingue analyse lourde (polling session) et passe légère (polling passes) | Les passes découplées ne touchent pas session.status → le poller de session s arrêtait au 1er tick (status resté completed), rechargeait les ANCIENNES données et ne rafraîchissait plus — état « en cours » figé (distance, conflits — constat utilisateur) | parse esprima OK ; navigateur à valider |
| `1697158` | **Passe « Distance / vitesse / TTC » exécutable seule** : `compute_distance_task` (ré-annotation sur détections stockées, sans YOLO, FOV V courants + trace `fov_v_used`) + entrée `distance` dans le `dispatch_map` de `run_passes` | Le ▶ de la passe était un **bouton mort** : `distance` absent du dispatch → skip silencieux (succès renvoyé, rien lancé) — constat utilisateur | compile + check OK ; à lancer côté UI |
| `64b5e0f` | **Bascules ⚑ Modes** : mécanisme générique `wama/common/utils/feature_flags.py` + registre `utils/features.py` + endpoint `features/` + panneau auto-généré (vue de dessus). 4 bascules : correction FOV distances, bras de levier, cap ratio (live, effet immédiat) ; vitesse/distance unifiées par track (compute, chantier déclaré). Appliquées en UN point par côté (`camera_geometry` backend, `rebuildCamGeo` JS). + consignation des 3 leviers (unification track / cluster stationnés / YOLO-OBB) dans la doc chaîne | Pouvoir comparer AVEC/SANS chaque amélioration instantanément (demande utilisateur) ; abstraction réutilisable pour WAMA Data ; jamais de if ad hoc dispersé | compile + parse + smoke test bascules OK ; navigateur à valider |
| `4e78e78` | **Stationné vitesse-aware** (durée ≥ 4 s ET étalement/durée < 0,7 m/s, en plus du plafond 6 m) ; **hand-off couture** : gap toléré 1→2,5 s + gate croissant avec le trou (3,5 m + 1,5 m/s·Δt) ; **fondu ratio↔trajectoire pondéré par la vitesse** (ratio seul à l'arrêt, trajectoire seule ≥ 2 m/s, mélange axial entre les deux) | Véhicules ROULANTS marqués « garés » (étalement < 6 m sur un track bref) → cap ratio appliqué à tort ; perte du G à la couture avant↔latérale (véhicule coupé au bord exclu ~1-2 s > gap 1 s, constat #537/G313) ; demande de pondération par la vitesse (utilisateur) | compile + parse OK ; re-lancer « Calculer les indicateurs » puis valider navigateur |
| `6146c7a` | Fragment résiduel `ent` après l'accolade fermante de `ratioHeadingCandidates` (introduit par `558194c`) → `ReferenceError: ent is not defined` au chargement, **toute l'app UI morte** (sessions bloquées sur « chargement ») | Résidu d'édition non détecté par le comptage d'accolades (`ent` est un identifiant valide) — parse esprima ajouté à la procédure de non-régression | syntaxe re-validée par parse complet |

## 2026-07-16

| Commit | Quoi | Pourquoi | Validé |
|---|---|---|---|
| `558194c` | **Cap ratio-bbox + fusion** : cap des stationnés/lents estimé par le ratio largeur/hauteur de bbox (étendue apparente → \|θ\| vs ligne de visée, 2 candidats mod 180° départagés par continuité, EMA axiale) ; trajectoire prioritaire quand l'objet bouge. + docs CHAINE_TRAITEMENT & CHANGELOG | Cap des garés figé = axe de la rue → faux en stationnement perpendiculaire ; demande de confrontation trajectoire↔ratio (utilisateur) | math validée numériquement (face→0°, profil→90°) ; rendu navigateur à valider |
| `3dab195` | **Classe stable par track** (vote majoritaire pondéré confiance, backend `stable_class` + fallback vote live JS) ; **persistance des bascules** 360°/Préd/garés/Voie·vidéo (localStorage) | Gabarit qui sautait car↔truck au gré des frames ; bascules perdues au rechargement de page | compile + rendu à valider |
| `79a0315` | **Cap indépendant du sens de lecture** : points de trace horodatés, vecteur orienté par le signe de Δt ; purge de trace sur seek > 2 s | En lecture arrière, tous les caps s'inversaient à 180° (trace remplie dans l'ordre de lecture) | rendu à valider |
| `43cf064` | **Géométrie réelle du rig ENA** : homographie DÉBRANCHÉE de la vue de dessus (latéral pinhole avec focale HORIZONTALE réelle 110°/55°) ; FOV V réels 61°/31° (`DEFAULT_FOV_V_DEG`) + correction rétroactive ×3,6 des distances latérales (`dist_scale`, `fov_v_used`) ; **bras de levier caméras** (antenne GPS à l'arrière, caméra avant +4,5 m) ; yaw latéraux défauts ±75° ; silhouette navette étendue vers l'avant ; H cam défaut 2,4 m ; overlays latéraux corrigés | **Décalage DROIT systématique** : calibration homographie prouvée cassée (inversion de signe #546, profondeur non monotone #537) — c'était elle qui décalait tout à droite ; specs caméras + schéma d'implantation fournis par l'utilisateur | smoke tests numériques OK (#537→+4,8 m/27,6 m ; #499 garée→−10,7 m hors voie) ; rendu à valider |
| `0f8d215` | **6 correctifs cap/vitesses/yaw/hand-off** : lissage circulaire du cap ego (±2 fixes) ; fix wrap 359→1° (`_shuttle_pose_at`) ; vitesse de track EMA + rejet >15 m/s ; yaw caméras configurable (bouton 🧭 + endpoint `camera-yaw/`) ; ID global `G<n>` + badge 🅿 sur les vidéos ; « rel. » sur la vitesse ; gel du cap des stationnés + seuil 0,4→0,8 m ; badge d'état minimap | Objets qui tournent sur eux-mêmes (cap ego GPS bruité amplifié par bras de levier + wrap plein nord) ; garés « roulant » à 1-3 km/h ; hand-off 360° cassé ; boutons à l'effet invisible | smoke tests wrap/yaw OK ; rendu validé partiellement (l'utilisateur a ensuite signalé le décalage droit → `43cf064`) |
| `1508935` | Fantômes prédits masqués quand Prédiction OFF ; latéral = homographie rescalée *(⚠ ANNULÉ par `43cf064` — l'homographie s'est révélée biaisée à droite)* | Vue de dessus incohérente avec les vues caméra ; « prédiction activée par défaut » | fix 1 conservé ; fix 2 remplacé |

## Historique antérieur (contexte)

| Commit | Quoi |
|---|---|
| `7327b19` | Lissage EMA de la distance top-down (mitigation du « ramassis ») |
| `6509cc2` | Passage au positionnement pinhole en vue de dessus (cause racine identifiée par l'audit du 2026-07-15 : latéral bruité) |
| `dbeb939` | Audit complet dégradation vue de dessus (`docs/AUDIT_CAM_ANALYZER_VUE_DE_DESSUS_2026-07-15.md`) |
| `c469867`, `9961a4c` | Étapes antérieures du chantier vue de dessus (voir audit) |

## Procédure de non-régression (à chaque modification)

1. Commit atomique + entrée dans ce tableau (quoi/pourquoi/validation).
2. `python -m py_compile` sur les fichiers Python touchés + `python manage.py check`.
   Pour le JS : parse complet via esprima (le simple comptage d'accolades ne détecte pas
   les fragments résiduels d'édition — cf. hotfix du 2026-07-17) :
   `python -c "import esprima; esprima.parseScript(open('wama_lab/cam_analyzer/static/cam_analyzer/js/index.js', encoding='utf-8').read().replace('?.', '.').replace('??', '||'))"`
3. Si formule géométrique : smoke test numérique sur un cas réel documenté
   (référence : frame 6176, session `8cecc4a6`, véhicules #537/#499/#546).
4. Sync `staticfiles/` si JS/CSS.
5. Validation visuelle par l'utilisateur (navigateur) AVANT de considérer l'entrée « validée ».
