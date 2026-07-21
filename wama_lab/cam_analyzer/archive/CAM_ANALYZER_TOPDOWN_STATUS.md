> ⚠️ **ARCHIVÉ / SUPERSEDED (2026-07-21).** Contenu vivant absorbé dans `CAM_ANALYZER_CHANGELOG.md` (§ État courant & RESTE À FAIRE). Conservé pour provenance uniquement — NE PLUS METTRE À JOUR.

---

# Cam Analyzer — Vue de dessus : état des lieux & prompt de redémarrage

> **But de ce document** : repartir sur une session neuve avec le statut COMPLET de la qualité/cohérence
> de la vue de dessus (top-down), sans avoir à relire tout l'historique. À jour au **2026-07-21**.
> Sources autoritatives (à lire en premier, dans cet ordre) :
> 1. [`CAM_ANALYZER_CHANGELOG.md`](CAM_ANALYZER_CHANGELOG.md) — quoi/pourquoi/annulation, commit par commit
> 2. [`CAM_ANALYZER_CHAINE_TRAITEMENT.md`](CAM_ANALYZER_CHAINE_TRAITEMENT.md) — la chaîne complète
> 3. [`CONTEXT.md`](CONTEXT.md) — contexte métier (navette autonome ENA Navya, 4 caméras AXIS)
> 4. [`../../docs/AUDIT_CAM_ANALYZER_VUE_DE_DESSUS_2026-07-15.md`](../../docs/AUDIT_CAM_ANALYZER_VUE_DE_DESSUS_2026-07-15.md) — audit cause racine
> 5. [`CAM_ANALYZER_DISTANCE_DESIGN.md`](CAM_ANALYZER_DISTANCE_DESIGN.md) — design distances/FOV

---

## 1. Mission

Améliorer la **qualité et la cohérence de la vue de dessus** : placer justement, en coordonnées monde,
les objets détectés par les 4 caméras de la navette ENA Navya (avant/gauche/droite/arrière), leur
orientation, leurs trajectoires, les marquages et les intersections — sur un fond ortho géoréférencé.

## 2. Cause racine (audit 2026-07-15) — et comment elle a été traitée

**Basculement `6509cc2`** (position 100 % pinhole) : échelle correcte MAIS **bruitée** (distance issue de
la hauteur de bbox, ±20 % frame à frame) → orientation, fusion 360°, fantômes, stationnés, tous bâtis
au-dessus, héritaient du bruit. **Ce n'était pas 360°/fantômes/orientation qui étaient faux — c'était la
position sous-jacente.**

**Traité depuis** (recommandation #2 de l'audit = recalibrer l'homographie à la bonne échelle) :
- **Estimateur d'homographie** (`51b8b95`, `8a19577`) : résout pitch/hauteur par étalement monde des
  statiques + ancrage pinhole → désaccord sol⟷pinhole **14,55 m → 3,05 m à pitch 21,5°** (×5). k1
  (distorsion radiale) testé et **écarté** (sature sans gain) : le pitch est le vrai levier.
- **Projection sol 2a** (`48b46df`) : `store_ground_calib` (pitch/hauteur par caméra, filtre qualité).
- **Kalman + RTS** (`90ac4b1`) : `trajectory_smoother.py`, `world_en` lissé par détection.
- **Recalage ortho 2b** (`034912c`) : offset absolu par intersection via passages piétons SAM3 sur
  ortho IGN (mesuré ~5,1 m). **⚠ RAPPORT seul — offset NON appliqué.**

---

## 3. FAIT (par thème — traçable par commit)

| Thème | Commits clés | Résumé |
|---|---|---|
| **Position / échelle** | `6509cc2` `51b8b95` `8a19577` `48b46df` `90ac4b1` | Pinhole→estimateur pitch (×5) ; Kalman+RTS ; ground calib 2a (flag OFF) |
| **Tracking 360° + fusion** | `318ff21` `699b072` `90ac4b1` | Verrou de chaîne gid ; enchaînement auto fin de Live ; trajectoires fusionnées (99 % dépassement tracké) |
| **Fantômes / reconstitution** | `3fdbb41` `e81fdf2` `65d5f38` | Comblement trous ≤6 s ; héritage mesures ; **stationnés ancrés** (position monde fixe) |
| **Filtres reflets / artefacts** | `a48fab0` `fd8998d` | Filtre cinématique (91 artefacts) + **fantômes géants** (bbox >50 %, conf <0,55 : 22/32) |
| **Cap / orientation** | `a48fab0` `4e78e78` | Cap serveur consensus axial (garés) ; fondu ratio↔trajectoire pondéré vitesse |
| **Marquages monde** | `91d85f7` `6053185` `6266444` | SAM3 projetés en monde (⚑ world_markings) ; interpolation entre keyframes ; declutter |
| **Intersections / branches** | `0ead425` `edd269e` `51b8b95` `d61652e` | Branches apprises du trafic ; mutualisées par lieu ; routes ⟂ ancrées balise |
| **Ortho / recalage** | `0ead425` `034912c` `7a2b36f` | Fond ortho IGN 20 cm ; recalage 2b (mesuré) ; mini-carte orientable 🧭 (cap navette) |
| **Live / complétion** | `411c817` `6b43a0b` `699b072` `d0c70e9` `4672900` | Mode Live ; complétion batch ; préemption batch>Live ; anti-empilement file |
| **Antenne GPS** | `0ead425` `552dd24` `6266444` | Levier antenne (coin arrière-droit, déport 1,00 m) Python+JS ; route virtuelle recalée ; point rouge = antenne |
| **UI / toolbar** | `a859656` `556973f` `64b5e0f` `552dd24` | Barre par familles (Calibration/Vue/Analyse) ; ordre chronologique ; **bascules ⚑ génériques** (feature_flags) |

## 4. RESTE À FAIRE (priorisé — qualité/cohérence vue de dessus)

**P1 — Le cœur (position, la cause racine) :**
1. **Brancher les gains de position derrière bascule + A/B ortho** : intégrer le **pitch seul** (2a/2c)
   sur le positionnement (aujourd'hui flag OFF), comparer A/B sur l'ortho. `8a19577` `48b46df`.
2. **Appliquer l'offset ortho 2b** (aujourd'hui rapport seul, ~5,1 m mesuré) derrière un flag. `034912c`.
3. **Calibration jointe (2c)** : pitch + hauteur (k1 écarté) réconciliés avec le recalage ortho.

**P1 — Validation (le plus gros angle mort) :**
4. **Passe de validation NAVIGATEUR/visuelle systématique** : la majorité des commits 2026-07-17→07-20
   sont **compile/parse-vérifiés mais PAS validés à l'écran** (chaque entrée changelog note « navigateur
   à valider »). Rejouer une session ENA (ex. `4da52df3`), relancer « Calculer les indicateurs » pour
   recaler les `world_en` avec l'antenne, et vérifier visuellement : position/échelle, cap, fusion 360°,
   fantômes, stationnés, marquages SAM3 sur ortho, branches d'intersection.

**P2 — Compléments de qualité :**
5. **Voie/vidéo** (audit #3) : refaire l'overlay ancré sur les **marquages yolopv2 DÉTECTÉS** + largeur
   constante (le gabarit actuel `e11e1cd` est aveugle — lignes droites supposées).
6. **FOV réel** (audit #4, `db66027` `64b5e0f`) : vérifier 55↔97°H de la vari-focale F1015 à l'écran
   (probablement restée au réglage large → surestime les distances latérales).
7. **Vitesse/distance unifiées par track** (`64b5e0f`, chantier déclaré ⚑) : le `compute` reste à faire.
8. **mask_geometry / YOLO-OBB** (`7d5995e`, `64b5e0f`) : minAreaRect = orientation gratuite (OBB) — non implémenté.
9. **Détection de dépassement depuis les trajectoires monde** (chantier ouvert, cf. mémoire).

---

## 5. Contraintes & non-régression (OBLIGATOIRES)

- **CHANGELOG obligatoire** : toute modif de comportement (position/cap/distances/tracking/affichage) →
  entrée `CAM_ANALYZER_CHANGELOG.md` (quoi/pourquoi/annulation/validation) + 1 commit atomique.
- **Non-régression avant commit** : `python -m py_compile` (Python) ; **parse esprima** (JS — un résidu
  d'édition a déjà tué toute l'UI, cf. `6146c7a`) ; **sync** `cp .../static/cam_analyzer/js/index.js
  staticfiles/cam_analyzer/js/index.js` si le JS est touché ; `manage.py check`.
- **Migrations sur les DEUX bases** (Windows dev + WSL2 live via `wsl.exe -e bash -lc '... manage.py migrate'`).
- **Code Python → RESTART du process WSL2** pour charger le fix (le template/JS se recharge seul).
- **Pas de tests destructifs** : jamais de `delete()` en masse ; user id=1 = compte réel Fabien ;
  tests en `transaction.atomic()` + `set_rollback(True)`.
- **Pas de `cd` en préfixe** de commande shell (cwd déjà = racine ; pour WSL, `cd` DANS la chaîne `wsl.exe`).

## 6. Premier pas recommandé (session neuve)

1. Lire les 5 docs autoritatifs (§0). 2. Confirmer avec Fabien la priorité : **P1.1 (brancher le pitch
derrière bascule + A/B ortho)** est le levier de qualité le plus impactant (c'est la cause racine).
3. Rejouer une session ENA et faire la **passe de validation visuelle** (P1.4) pour établir la baseline
actuelle AVANT de brancher de nouveaux gains. 4. Une amélioration = un flag ⚑ (mécanisme `feature_flags`
`64b5e0f`) pour A/B, jamais de `if` ad hoc dispersé.
