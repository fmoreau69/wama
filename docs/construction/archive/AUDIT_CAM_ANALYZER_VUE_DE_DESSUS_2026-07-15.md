# Audit — dégradation du mouvement des objets en vue de dessus (cam_analyzer)

**Date :** 2026-07-15
**Contexte :** après `a417fb3` (synchro GPS stable), la vue de dessus s'est dégradée
(objets qui « sautent », orientation incohérente, ramassis en 360°, fantômes mal placés).
Cet audit reconstruit la chronologie et identifie la **cause racine**.

---

## 1. Point de référence stable

**`a417fb3` (2026-07-10)** — « synchro GPS avec échelle (gps_time_scale) ».
À ce stade : synchro GPS↔vidéo correcte, position des objets en vue de dessus via
**l'homographie** (`ground_xy`). L'homographie était **LISSE** mais **comprimée** (objet à
25 m projeté à ~7 m). Position stable mais échelle fausse.

---

## 2. Chronologie des changements cam_analyzer (depuis a417fb)

| Commit | Contenu | Risque de dégradation |
|--------|---------|-----------------------|
| cecacad | persistance slider confiance | — |
| 3007d67 | gabarit voie top-down + slider | — (visuel) |
| 5d5907f | auto largeur de voie | — |
| f43479c | auto GPS-sync + largeur à l'extraction | — |
| d31842c | bouton Sync .rec + **filtre distance objets** (g[1]>45, |g[0]|>20) | moyen (peut masquer) |
| 851a5ae | **filtre bord** + **empreintes** (orientées cap NAVETTE) | moyen |
| e0803c5 | **fusion 360°** multi-caméra | élevé |
| **f14e96d** | **recale distance homographie → pinhole** | **ÉLEVÉ (début du bruit)** |
| **6509cc2** | **position 100% pinhole** (distance+cap bbox, abandonne homographie) | **⛔ CAUSE RACINE** |
| 42a9aaf | fix persistance timeline | — |
| dbeda1f | persistance zoom | — |
| 4b958dd | filtre bord élargi 8px | faible-moyen |
| c5d09ba / a2ad43c | gabarit suit trajectoire GPS + lissage | — (visuel) |
| 59444c3 / 41e6dc4 / e2fe882 | Prédiction (PROSPECT) Phase A/B/C | — (isolé) |
| a4cbb17 / 46cc031 | renommage prospect→prediction | — |
| **faeb0f0** | **tracking global multi-caméra** + dedupe + trails via gid | élevé (dépend positions) |
| **c469867** | **fantômes** (comblement trous hand-off, interpolés) | élevé (dépend positions) |
| 08638b5 | optim prédiction 24× | — (perf) |
| **c1ab80b** | **orientation = cap PROPRE objet (via sa trace)** | élevé (trace = positions bruitées) |
| dfa2bf2 | cap lissé EMA + maintenu à l'arrêt | moyen (atténue mais sur base bruitée) |
| 9961a4c | détection stationnés (étalement position) + masquer garés | moyen (dépend positions) |
| e11e1cd | **Voie/vidéo** (projection pinhole AVEUGLE) | moyen (mauvaise approche, voir §4) |
| ca62ad3 | bande route pleine + filtres top-down cohérents | faible-moyen |
| 48b37b2 | pont segmentation→détection | — (isolé) |
| **7327b19** | **lissage temporel distance (EMA)** | ✅ MITIGATION de la cause racine |

---

## 3. Cause racine identifiée

**`6509cc2` (position 100 % pinhole)** est le basculement critique.

- **Avant** (homographie) : position **lisse** mais **comprimée** (échelle ×3-4 fausse).
- **Après** (pinhole) : **échelle correcte** MAIS **BRUITÉE** — la distance pinhole vient de
  la **hauteur du bbox**, qui tremble frame à frame de **±20 %**.

Mesure (track 549, frames 6186-6201) :
```
distance_m (pinhole, utilisé) : 25.6 → 22.1 → 21.2 → 23.0 → 21.1 → 25.0 → 22.7 …  (±20 %)
ground_xy  (homographie)      : 6.1  → 6.1  → 6.1  → 6.1  → 6.1  → 6.1  → 6.3  …  (stable)
```

**Conséquence en cascade** : toutes les briques construites APRÈS s'appuient sur cette
position bruitée :
- **Orientation** (`c1ab80b`) = direction de la trace → trace bruitée → orientation qui saute.
- **Fusion 360°** (`e0803c5`, `faeb0f0`) = objets de 4 caméras placés en monde → chacun
  bruité → désalignés → « ramassis ».
- **Fantômes** (`c469867`) = interpolés entre positions bruitées → placés de travers.
- **Stationnés** (`9961a4c`) = étalement de positions bruitées → détection instable.

**Ce n'est donc PAS 360°/fantômes/orientation qui sont faux en soi — c'est la position
sous-jacente qui est bruitée.**

---

## 4. Problème secondaire : « Voie/vidéo » (mauvaise approche)

`e11e1cd` projette un gabarit **aveugle** (lignes droites supposant une route droite devant,
via pinhole + hauteur caméra). Il **n'utilise pas les lignes détectées** → ne colle pas à la
route. **Besoin réel** : overlay normalisé à **largeur constante**, **ancré sur les lignes
centrales DÉTECTÉES (yolopv2)**, pour nettoyer débordements/trous. → à refaire.

---

## 5. Mitigation en place

`7327b19` — **lissage temporel de la distance par objet (EMA α=0.3)** dans `_drawCam`.
Réduit le jitter radial ±20 % → positions/trails/orientation/fusion plus stables. **À retester.**

---

## 6. Recommandations pour repartir propre

1. **Valider le socle d'abord** : mode détection simple (360° OFF, prédiction OFF), vérifier
   que l'orientation/position est stable après le lissage EMA (`7327b19`).
2. **Idéal (fond)** : la vraie solution est de **recalibrer l'homographie à la bonne échelle**
   (via les distances pinhole comme référence) → on récupère la LISSITUDE de l'homographie
   ET l'échelle correcte du pinhole. Meilleur que lisser le pinhole bruité.
3. **Voie/vidéo** : refaire ancré sur les marquages yolopv2 détectés + largeur constante.
4. **FOV pinhole** : la valeur 60° (vertical) est supposée ; à vérifier contre la vraie FOV
   des caméras (impacte latéral + distance).
5. **Re-vérifier 360°/fantômes/stationnés** une fois la position stabilisée.

---

## 7. Modules concernés (pour reprise)

- `wama_lab/cam_analyzer/static/cam_analyzer/js/index.js` : `_drawCam`, `updateTopDown`,
  `egoToLatLon`, gabarit, filtres, EMA distance/cap.
- `wama_lab/cam_analyzer/utils/multicam_tracker.py` : tracking global + fantômes + stationnés.
- `wama_lab/cam_analyzer/utils/prediction_adapter.py` : trajectoires monde + TTC/PET.
- `wama_lab/cam_analyzer/utils/segmentation_bridge.py` : masque → détection (isolé, sain).
- `wama/common/prediction/` : cœur SSM autonome (isolé, sain).
