---
name: cam-analyzer
description: Travailler sur WAMA Lab Cam Analyzer — tracking 360°, projection sol, map-matching GPS, vue de dessus, marquages, indicateurs. Utiliser dès qu'une demande touche wama_lab/cam_analyzer (détection, calibration, recalage, overlays, mini-carte, rapport d'interactions), ou quand l'utilisateur parle de navette, intersections, ENA_CASA, ou de la toolbox tierce d'origine.
---

# /cam-analyzer — Chaîne d'analyse vidéo embarquée

## 1. Avant de toucher au code
- Lire `CAM_ANALYZER_CHAINE_TRAITEMENT.md` (chaîne + conception) et le handoff le plus récent —
  ⚠ **`PROJECT_STATUS.md §REPRISE <date>`**, PAS un `REPRISE_*.md` : il n'en existe aucun dans
  `wama_lab/cam_analyzer/` (vérifié 2026-08-26), le seul du dépôt est à la racine et date du 06/08.
- L'état vivant est le **CHANGELOG**, pas la doc de chaîne (qui décrit la cible).
- Vérifier la partition multi-instances : l'infra GPU/ressources est souvent tenue par une autre instance.

## 2. Modèle mental de la chaîne
Détection par caméra (YOLO + BoTSORT) → **tracking global 360°** (hand-off inter-caméras,
`global_track_id`) → **projection sol** (calibration 2a = angle par ego-motion ; 2b = position
absolue par marquages ortho) → **monde** (positions lat/lon) → indicateurs (TTC/PET, insertions).
Chaque étage consomme le précédent : une erreur de projection contamine tout l'aval, d'où la
règle des bascules.

## 3. Où vivent les mécanismes — et où écrire les nouveaux
- **Liste EXHAUSTIVE des traitements : `wama_lab/cam_analyzer/function_specs.py`** — chaque
  traitement y est déclaré en capacité (ports typés E/S, catégorie, coût), dans le même langage
  que les fonctions pures WAMA Data. **Ne jamais la recopier ailleurs** (règle « un domaine = un
  fichier de référence ») : la tenir à jour EST le geste. Ajouter un traitement sans l'y déclarer
  le rend invisible du catalogue, de `/model-manager/functions/` et du Studio.
- **Toute logique PURE et réutilisable va dans `wama_data/functions/<domaine>/`**, avec sa
  `FunctionSpec` **auto-déclarée en fin de module** (patron : `driving/gps_map_match.py`). PAS dans
  `cam_analyzer/utils/`. Domaines existants : `io`, `geometry`, `kinematics`, `driving`, `geo`.
- Ce qui reste couplé à `AnalysisSession` (lit/écrit la BDD, passe Celery) se déclare en
  `Binding.APP` dans `function_specs.py`, **à porter vers `PURE`** dès qu'on veut le chaîner —
  c'est la voie d'intégration à WAMA Data.
- **Une sortie non déclarée n'existe pas pour le système** : UI, chaînage et Studio se génèrent
  à partir des descriptions. Modifier ce qu'une fonction produit sans mettre à jour ses `outputs`
  est un bug de manifeste, pas un détail de doc.
- Signal d'alerte : un module de `common/` qui importe depuis une app = dépendance inversée,
  la brique est mal placée.

## 4. Règles non négociables
- **Toute amélioration comparable = un flag ⚑** déclaré dans `utils/features.py`, jamais un `if`
  ad hoc. Le panneau ⚑ Modes se génère depuis le registre — aucune UI à écrire.
- **A/B objectif, jamais visuel seul** : une bascule doit s'accompagner d'une métrique chiffrée
  (nombre d'appariements, dispersion résiduelle, écart moyen), affichée en console.
- **CHANGELOG obligatoire** : toute modif de comportement → entrée (quoi / pourquoi / validation
  et annulation), dans le MÊME commit.
- **Défaut OFF** pour une bascule non encore validée sur données réelles.

## 5. Distinguer ANALYSE et RAPPORT (piège récurrent)
Deux notions que le code a longtemps confondues (décorrélées le 2026-07-29) :
- `analysis_radius_m()` — borne le **traitement à venir** ; le changer n'invalide aucune donnée.
- `interest_radius_m()` — filtre le **rapport** ; se dérive de l'existant, donc se change SANS
  recalcul et peut dépasser le rayon d'analyse.
Corollaire : un profil restreint aux intersections laisse ~75 % de la timeline sans données. Avant
de conclure à un bug d'affichage, **vérifier la couverture** (`config['analyzed_ranges']`, ou en
base). Le nom d'un profil décrit le RAPPORT visé, pas le périmètre d'analyse.

## 5bis. 🔴 MESURER CE QUE FAIT LE CODE — le rejouer, jamais l'inférer du persisté

> Recadrage de Fabien, 2026-09-09 : *« Tu ne peux pas regarder directement ce que fait le code
> plutôt que de supposer ? Le pipeline de traitement existe, les fonctions existent. »* — après
> que **deux** analyses successives, menées sur les données PERSISTÉES, ont conclu faux sur le
> même sujet (le filtre des garés). Coût : une demi-session et deux consignations à rectifier.

**Pourquoi le persisté ment sur ce que le code fait** — trois raisons cumulables, toutes
vérifiées ce jour-là dans `multicam_tracker` :
1. il est **transformé** (`world_en` est la position LISSÉE, pas celle que le filtre juge) ;
2. il est **partiel** (pas de `world_en` pour les stationnés ni sous 5 observations) ;
3. il vient d'un **autre run** (le tracker rendait 5210 tracks, la base en portait 4352) —
   et `results_summary` peut être le résumé périmé d'un run interrompu.

**Le geste, quand la question porte sur un CALCUL** (qualification, seuil, score, filtre) :
1. **Instrumenter à la source** : compter DANS la boucle qui décide, par porte de sortie, et
   rendre ce compte (`results_summary` + une ligne console). C'est du code qui reste — un
   filtre qui écarte l'essentiel de ses candidats doit dire par où ils sortent.
2. **Rejouer la vraie fonction, écritures NEUTRALISÉES** — la plupart des passes de calcul
   sont CPU et rejouables (`annotate_global_tracks` : 94 s sur 1,2 M détections) :
   ```python
   DetectionFrame.save = lambda self, *a, **k: None   # AVANT tout appel
   AnalysisSession.save = lambda self, *a, **k: None
   res = annotate_global_tracks(session)              # lit le RETOUR, rien n'entre en base
   ```
   Compter les tentatives bloquées et le DIRE (237 318 ce jour-là) : c'est la preuve que la
   base est intacte, pas une intention.
3. Seulement ensuite, conclure — et si une analyse antérieure disait autre chose, la
   **rectifier là où elle a été écrite**, pas ailleurs.

⚠ **Le piège de la SÉLECTION, plus sournois que celui de l'instrument.** La 2ᵉ analyse fausse
ne venait pas d'un mauvais comptage : elle venait du choix des candidats. Sélectionner des
« garés » par un faible étalement retient mécaniquement les tracks COURTS (peu d'observations =
peu d'étalement), après quoi « ils sont courts » n'est plus une découverte mais une tautologie.
*Un comptage juste sur une population mal choisie rend un chiffre faux avec l'air d'un fait.*
Vérifier qu'aucun critère de sélection ne préjuge de ce qu'on va mesurer.

## 6. Pièges d'exécution (chèrement acquis)
- **Aucune charge GPU sous WSL2 sur le poste de dev** (crashs hôte, bug MS WSL #40732). Vaut aussi
  pour `manage.py shell` : `django.setup()` importe `torch.cuda` et le process meurt en silence
  → interroger la base en **`psql` direct**.
- **Aucun pane Leaflet personnalisé** sur la mini-carte : elle est pivotée (`setBearing`), le plugin
  de rotation ne gère que les panes standard → la géométrie disparaît. Utiliser `bringToBack()`.
- **Jamais d'édition du JS par script/regex** (>5 000 lignes) : édition ciblée, puis
  `bash scripts/check_js.sh` (node en espace utilisateur, `~/.local/opt/node`).
- JS/CSS modifié → copier vers `staticfiles/cam_analyzer/` ; template modifié → HUP gunicorn.
- Migrations **non versionnées** dans ce projet (`.gitignore`).

## 7. Validation
`manage.py check`, tests purs des fonctions déplacées, `check_js.sh`, puis **smoke navigateur** —
et si le navigateur n'a pas été ouvert, l'écrire noir sur blanc dans le CHANGELOG plutôt que de
laisser croire à une validation complète.
