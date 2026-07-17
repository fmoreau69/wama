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

## 2026-07-17

| Commit | Quoi | Pourquoi | Validé |
|---|---|---|---|
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
