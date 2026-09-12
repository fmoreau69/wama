# Analyse initiale du projet « rapport intersections / insertions navette » — ARCHIVE

> **Document d'ORIGINE, versé le 2026-09-12 par Fabien** : *« ça peut te donner une idée d'où
> on est parti »*. C'est le cadrage technique fait **avant** le développement, suivi de
> « multiples aménagements » qui ont mené à l'état d'aujourd'hui.
>
> ⚠ **ARCHIVE — ne fait PAS autorité.** La référence vivante du domaine est
> `CAM_ANALYZER_CHAINE_TRAITEMENT.md` (chaîne + conception) et
> `CAM_ANALYZER_CHANGELOG.md` (état). Ce fichier n'est ni à mettre à jour ni à confronter au
> code : il sert à savoir **ce qui était prévu, et ce que l'expérience a déplacé**.
>
> ⭐ **Pourquoi il valait d'être gardé** : deux des verrous qu'il annonce comme « difficiles /
> à risque » sont EXACTEMENT ceux que la mesure a confirmés trois ans plus tard —
> la **distance absolue en monoculaire** (« fondamentalement imprécise sans calibration »,
> « la précision se dégrade fortement au-delà de 15 m ») et le **filtrage des garés**
> (« c'est un problème de temporalité »). Le §D.3 de la doc vivante mesure le premier à
> **±20 % au pinhole** et montre que le second est encore ouvert. *Un cadrage initial qui
> désigne juste ses propres risques mérite d'être relu quand on bute dessus.*

---

## Ce qui est facile ✅

| Élément | Approche |
|---|---|
| Détection de véhicules (YOLOv8) | Déjà dans le pipeline, fonctionne bien |
| Tracking multi-objets | ByteTrack/DeepSort — mature |
| Classification type véhicule (VL/PL/Moto…) | Intégré dans YOLO |
| Déclenchement par timecode/zone ±100 m | Logique simple si GPS dispo |
| Extraction des timecodes t0/t1/t2 | Découle du tracking une fois les détections fiables |

## Ce qui est faisable mais complexe ⚠️

**1. Véhicule « arrêté » vs « en mouvement » depuis une caméra embarquée.** C'est le problème
central du projet. La caméra bouge avec la navette → un véhicule à l'arrêt présente un flot
optique important dans l'image. Il faut compenser le mouvement propre de la caméra
(ego-motion). Options : *(bonne)* données de vitesse de la navette + calibration caméra pour
modéliser le flot optique attendu du fond, le résidu étant le mouvement propre des objets ;
*(alternative)* homographie entre frames consécutives sur les marquages au sol, puis flot
résiduel ; *(à éviter)* optical flow pur sans compensation — trop bruité, trop de faux
positifs. **Recommandation : vérifier dès maintenant si les données de vitesse de la navette
sont synchronisées avec les vidéos. C'est le levier le plus important pour la fiabilité.**

**2. Segmentation du réseau routier / position relative.** Pour savoir si un véhicule est dans
la voie de la navette ou la voie opposée, il faut segmenter la chaussée, la ligne centrale et
les zones d'intersection (zone de conflit). Options : segmentation sémantique (SegFormer,
DeepLabV3+ fine-tuné) — bonne précision, coûteuse sans données labellisées ; détection de
lignes (LaneNet, UFLDv2) + post-traitement — plus léger mais fragile aux intersections où les
lignes disparaissent ; **hybride recommandé** : segmentation road/non-road + détection de
marquages linéaires — les intersections étant justement les zones où les marquages
disparaissent, ce qui peut servir de signal.

**3. Distinguer « inséré dans la voie navette » vs « franchissement voie opposée ».** Nécessite
de connaître à chaque instant le côté de la ligne centrale où se trouve le véhicule. Faisable
si la segmentation de voie est robuste, mais les intersections sont précisément les zones où
c'est le moins fiable (absence de marquages, angles).

## Ce qui est difficile / à risque ❌

**1. Distance absolue (D0, distances en mètres).** Depuis une caméra monoculaire embarquée,
l'estimation de distance est **fondamentalement imprécise sans calibration**. L'idée des
marquages routiers (lignes 3 m / intervalles 0,33 m) est la meilleure approche disponible,
mais : elle ne fonctionne qu'en approche frontale (voie droite) ; la précision **se dégrade
fortement au-delà de 15 m** ; elle suppose la caméra bien fixée (angle constant).
**Recommandation phase 1 : travailler en distance relative / taille apparente du véhicule
(hauteur/largeur en pixels). Calibrer en phase avancée.**

**2. Reconstruction vue de dessus (bird's eye view) + TTC/PET.** La tâche la plus ambitieuse :
calibration complète (intrinsèque + extrinsèque), homographie sol → vue de dessus (IPM), et
hypothèse de sol plan (approximative en virage ou en pente). Faisable pour la droite,
beaucoup plus incertain en approche d'intersection. À réserver à la phase 3 et à bien valider
sur quelques cas avant de généraliser.

**3. Filtrer les véhicules garés vs arrêtés aux intersections.** **C'est un problème de
temporalité.** Un véhicule garé n'évoluera pas dans le champ de la caméra même sur une
séquence longue. Approche recommandée : track persistant + distance au centre d'intersection
+ heuristique « présent uniquement dans la zone ±100 m ».

## Questions critiques avant de démarrer

1. Données de vitesse synchronisées vidéo ? Format, fréquence, décalage temporel ?
2. Positions GPS des intersections connues ? Si oui, déclenchement automatique de l'analyse.
3. Résolution + framerate des caméras avant/arrière ? (crucial pour t0/t1/t2)
4. Calibration caméra disponible ? Sinon, à faire à partir des vidéos.
5. Volume de données : combien d'heures de vidéo, combien d'intersections ?
6. Traitement offline uniquement (pas temps réel) ? → simplifie beaucoup.
7. Les deux caméras (avant/arrière) sont-elles synchronisées entre elles ?

## Architecture recommandée pour la Phase 1

```
Entrée : vidéo caméra avant + données vitesse navette
  ↓ [1] Déclencheur intersection : GPS ou détection visuelle
  ↓ [2] Segmentation voie : road + ligne centrale + zone intersection
  ↓ [3] Détection + tracking véhicules (YOLOv8 + ByteTrack)
  ↓ [4] Ego-motion compensation → classification arrêt / mouvement relatif
  ↓ [5] Analyse événement : arrêté à l'intersection → position vs ligne centrale ;
        mise en mouvement → t0 ; franchit la ligne centrale → t1 ; complète → t2
  ↓ [6] Sortie rapport : timecodes, type d'interaction, distances approximées
```

**Recommandation globale** : phase 1 en trois sous-étapes — (1) prototypage ego-motion :
valider qu'on distingue arrêt/mouvement depuis la caméra avant avec les données de vitesse
navette, **c'est le verrou technique principal** ; (2) segmentation voie + détection
d'intersection ; (3) logique événementielle d'insertion.

---

## Ce que l'expérience a déplacé (relevé au versement, 2026-09-12)

| prévu ici | où ça en est réellement |
|---|---|
| une caméra avant | **quatre** caméras + **tracking global 360°** avec hand-off inter-caméras |
| ego-motion par flot optique compensé | pose navette par **GPS + cap**, filtre Kalman+RTS optionnel (⚑ `shuttle_filter`), et depuis le 2026-09-11 **accéléromètre en commande** (⚑ `imu_command`) |
| distance par marquages en approche frontale | **pinhole** (hauteur de bbox) + **projection sol** (⚑ `auto_ground_calib`) + homographie par passage piéton — le verrou de précision annoncé ici est **mesuré** : ±20 %, `§D.3` |
| garés par « présent uniquement dans la zone ±100 m » | filtre par **étalement + durée**, dont la mesure du 2026-09-11 montre qu'il **n'a jamais fonctionné** (77 garés sur 3887 véhicules) — chantier ouvert |
| BEV/TTC « phase 3 » | **fait**, TTC/PET par prédiction de trajectoire (`§F`) |
