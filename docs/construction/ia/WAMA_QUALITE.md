# WAMA_QUALITE.md — la boucle qualité des modèles : confrontation, mesure interne, auto-amélioration

> **Référence unique du domaine « qualité des modèles et des résultats »** — créée le 2026-09-16 à la
> demande de Fabien : *« ce qu'il manque avant de lancer quoi que ce soit, c'est une cartographie
> complète des méthodes de confrontation des modèles par types de tâches/modèles, la définition
> précise des méthodes, et comment les utiliser à la fois pour la mesure interne (évaluer les
> modèles) et pour l'auto-amélioration quand c'est possible. La voie complémentaire est le
> réentraînement ou le finetuning hors de WAMA, contrôlé et exécuté depuis WAMA. »*
>
> Jusqu'ici ce domaine n'avait pas de fichier : le plan acté vivait dans
> `WAMA_APP_GENERATION_ROUTE.md §F4b` (« la donnée de qualité reste le maillon faible »), les
> garde-fous dans `ROADMAP.md §16.5`, l'ordre de construction dans `ROADMAP.md §16.7`, la
> divergence dans `wama/transcriber/TRANSCRIBER_CORRECTION.md §8`, et le récit dans les `§REPRISE`
> de `PROJECT_STATUS.md`. Ce fichier les **relie** ; il ne les recopie pas : chaque section renvoie
> à la source qui fait autorité sur son point, et ne porte que ce qui n'était écrit nulle part —
> la carte des méthodes, la matrice tâche × méthode, la chaîne fonctionnelle complète et ses
> décisions ouvertes.
>
> ⚠ **Rien de ce document n'est un chantier lancé.** Il précise la démarche pour y voir clair
> (état ✅/🔄/⏳ mesuré au code le 2026-09-16). Ce qui a été **retiré** en l'écrivant : « l'idée 3 »
> du 14/09 (une rubrique de tests par rôle pour les seuls LLM, reprise de llmfit) — trop étroite,
> et à côté de la route actée : elle survit ici comme UNE métrique objective possible (§2, M3),
> pas comme un chantier.
>
> Langue : ce document est en français (doc de construction). Les identifiants, les clés d'échelle
> et les prompts internes sont en **anglais** (`AGENTS.md §nommage` ; l'anglais est le pivot
> interne des consignes, `ROADMAP.md §10.B`). Les **données** du labo sont en français : c'est un
> fait sur les jeux d'échantillons, pas sur la langue des outils.

---

## 0. Où ça se place — trois boucles, une échelle, trois garde-fous, un ordre

**Trois boucles distinctes, à ne pas confondre** (elles partagent des méthodes, pas des verdicts) :

| boucle | question | ce qu'elle produit | consommateur |
|---|---|---|---|
| **A — qualité du MODÈLE** | ce modèle est-il meilleur que cet autre, sur cette tâche ? | un **indice par tâche et par modèle** (échelle nommée, population, version du protocole) | la **sélection** (`model_selector._quality_scalars`, 3ᵉ étage) et les cards du model_manager |
| **B — qualité du RÉSULTAT** | cette sortie-là répond-elle à la demande ? | un **signal d'attention** sur un item (à revoir / probablement juste) | l'utilisateur (heatmap, inspecteur), jamais un rejet automatique |
| **C — amélioration** | qu'est-ce qui, hors le modèle, ferait mieux ? | une **variante d'un levier** (skill, contrat, paramètre, contenu RAG, glossaire) ou un **déclenchement** d'apprentissage hors WAMA | l'humain qui valide ; WAMA qui déclare, déclenche, réingère |

**L'échelle des signaux** (déjà câblée pour A, `wama/model_manager/services/model_selector.py`
`_quality_scalars`) : *a priori structurel* (`model_quality.py`) < *banc tiers confronté*
(`benchmark_sync.py`, échelles AA / Arena / Open ASR / MTEB) < **mesure interne** (vide aujourd'hui).
Règle intangible : **on ne compare des valeurs que sur un lot où tout le monde porte la même
échelle** ; jamais deux échelles mélangées, jamais de min-max qui inventerait une équivalence
(`benchmark_sync.percentile_rank` : le rang, pas le score).

**Trois garde-fous non négociables** (`ROADMAP.md §16.5`, repris dans `wama/common/utils/qc.py`) :
1. **validateur indépendant du générateur** — autre famille de modèle, **ou contrôle
   déterministe** ; un modèle ne corrige jamais sa propre copie ;
2. **score relatif** — régression N vs N+1, détection d'écarts, escalade vers l'humain ; jamais une
   porte d'acceptation automatique ;
3. **jamais le seul filet RGPD** — pour l'anonymisation, le déterministe et l'audit humain sont le
   filet principal ; un juge automatique n'est qu'une alerte secondaire.

**L'ordre de construction** (`ROADMAP.md §16.7-4`, confirmé par Fabien le 2026-08-12 : *« si on le
fait mal, on risque d'introduire plus d'erreurs que de correction »*) : **des FAITS vers les
INFÉRENCES** — ① les gestes de l'utilisateur (`RunOutcome`), ② le désaccord entre systèmes
(divergence), ③ les métriques à vérité terrain, ④ le juge automatique **en dernier, et calibré
d'abord** là où une vérité humaine existe. *Métrique d'abord, boucle ensuite, autonomie en
dernier.* Un juge qui ne retrouve pas le verdict humain là où la vérité existe n'a pas à juger
là où elle n'existe pas (`run_outcome.correction_magnitude`).

---

## 1. Vocabulaire — cinq mots qu'on ne substitue pas l'un à l'autre

| mot | définition dans ce document | exemple |
|---|---|---|
| **confrontation** | mettre en regard deux sorties du **même travail** (deux modèles, deux réglages, une sortie et une référence) et rendre un **désaccord chiffré**, sans dire qui a raison | divergence de deux transcriptions du même passage |
| **vérité terrain** | une référence que l'on tient pour juste **indépendamment des modèles évalués** : humaine (correction), par construction (simulateur, dégradation synthétique d'un original), ou tierce (jeu publié) | la transcription corrigée à la main ; l'image haute résolution dont on dérive l'entrée basse résolution |
| **métrique** | une fonction déterministe **(sortie, référence) → nombre** au sens déclaré (plus haut / plus bas = mieux) | WER, IoU, PSNR |
| **juge** | un modèle (LLM, VLM) qui prononce un avis sur une sortie ; utile seulement **indépendant** et **calibré** | `qc.assess_output_quality`, `vision_probe.describe_image_ollama` |
| **indice** | l'agrégat par tâche et par modèle qui entre dans l'échelle des signaux : valeur, échelle, sens, population, version du protocole, date | `benchmark_meta` d'un `AIModel` |

**Les quatre sources de vérité, par ordre de confiance décroissante** :

1. **humaine** — corrections (`RunOutcome` signal `corrige`, `Transcript.corrected_segments_json`),
   choix explicites ; la seule qui vaille pour CALIBRER un juge ;
2. **par construction** — le simulateur émet ses étiquettes (`WAMA_APPRENTISSAGE.md §6.4`) ; une
   dégradation contrôlée d'un original (sous-échantillonner une image nette, bruiter un audio propre)
   fournit une référence exacte ET gratuite ;
3. **tierce** — bancs publiés (`benchmark_sync`), jeux étiquetés déclarés comme `dataset` ;
4. **consensus** — l'accord de N systèmes indépendants. ⚠ Ce n'est PAS une vérité : une majorité
   peut se tromper, et des modèles de même lignée se trompent pareil. C'est un **signal
   d'attention** (`wama/common/services/divergence.py`, en-tête), et au mieux un départage.

---

## 2. Les méthodes de confrontation — catalogue, définitions précises, état

Chaque méthode est définie par : ce qu'elle mesure, ce qu'elle **ne dit pas**, son ancrage à la
source (sans lequel elle mesure la fluidité et pas la fidélité, cf. `TRANSCRIBER_CORRECTION.md
§8.2`), son coût GPU, et son état dans le code. Les identifiants `M<n>` servent à la matrice §3.

### M1 — Divergence textuelle alignée ✅ (brique livrée)
- **Mesure** : sur deux sorties textuelles **segmentées et horodatées** du même média, alignement des
  segments par recouvrement temporel (≥ 30 %), puis désaccord par zone et global sur les **mots**
  (minuscules, ponctuation ignorée, apostrophe = séparateur). Un passage sans vis-à-vis compte
  comme divergence totale ; si un côté est plus de 2× plus fin, les rôles s'échangent.
- **Ne dit pas** : laquelle des deux a raison. Convergence sur un texte « incohérent » = la personne
  l'a probablement dit (deux systèmes n'hallucinent pas la même hésitation).
- **Ancrage** : sur l'audio, sans réécoute — deux systèmes ont entendu la même chose.
- **Coût** : nul (calcul pur) ; les deux passes ASR, elles, coûtent une inférence chacune.
- **Code** : `wama/common/services/divergence.py` (`divergence_texte`, alignement, seuils
  indicatifs `SEUILS`), `manage.py divergence_asr`. Trois pièges mesurés et corrigés :
  `TRANSCRIBER_CORRECTION.md §8.3`. Alignement rendu linéaire en pratique le 2026-09-23 (index des
  segments en face, résultat identique attesté par `tests_divergence`) : 1 h d'audio en 0,03 s —
  la condition pour l'utiliser à l'affichage (M6).
- **Extension due** : texte **non horodaté** (OCR par page ou par boîte ; description, résumé,
  génération : alignement par document entier, similarité de séquence de mots). Pas écrite.

### M2 — Accord géométrique ⏳ (nommé comme « prochain consommateur » de M1, jamais écrit)
- **Mesure** : pour des boîtes, masques, points-clés ou boîtes orientées produits par deux modèles
  sur la même image : appariement par IoU (seuil déclaré, 0,5 par défaut, affectation optimale),
  puis **F1 symétrique** (chaque sortie tour à tour référence). Segmentation : IoU de masques ;
  pose : similarité de points-clés (OKS) ; profondeur : erreur RMSE invariante d'échelle entre deux
  cartes + corrélation de rang.
- **Consensus à N** (voir M6) : pour chaque objet, le **support** = combien de modèles l'ont trouvé.
- **Ne dit pas** : si l'objet existe. Deux détecteurs de même lignée (YOLO v8 / v9) partagent leurs
  biais ; un support de 2/2 y vaut moins qu'un support de 2/2 entre familles différentes.
- **Ancrage** : sur l'image ; les sorties portent leurs coordonnées.
- **Coût** : nul pour la confrontation.
- **Code** : rien ; `bench._bench_detection` rend déjà les comptes et confiances mais **jette les
  boîtes** — première chose à changer (§5, chaînon ③).

### M3 — Métrique à vérité terrain ⏳ (une seule vivante : la magnitude de correction)
- **Mesure** : (sortie, référence) → nombre, sens déclaré. Par famille :
  transcription **WER/CER** ; OCR **CER** par page ; détection **mAP@0,5** ; classification
  exactitude / F1 ; recherche par embeddings **nDCG@10** sur un jeu déclaré ; agrandissement
  **PSNR / SSIM / LPIPS** ; débruitage audio **SNR gagné** ; profondeur **AbsRel / δ1** ;
  synchronisation labiale : métriques SyncNet (lib externe) ; **génération de texte contrainte** :
  rubrique déterministe (présence/absence, format, valeur exacte — ce que llmfit appelle
  `evaluate_response`) — valable UNIQUEMENT sur des consignes à réponse vérifiable, écrites par
  nous, en anglais, versionnées ; ce n'est pas une note de qualité de prose.
- **Ne dit pas** : rien au-delà du jeu de référence. Un modèle excellent sur le jeu et mauvais sur
  les données du labo est un jeu mal choisi (leçon MTEB du 02/09 : *un jeu se choisit sur ce que le
  catalogue a, pas sur ce que le banc propose*).
- **Ancrage** : total, par définition.
- **Coût** : nul pour la métrique ; la référence coûte (humaine) ou est gratuite (par construction).
- **Code** : `run_outcome.correction_magnitude` (distance sortie IA → correction humaine, sans
  interprétation) ; `divergence_asr` confronte déjà ASR et correction. ~~Aucune WER~~ — **WER et
  CER livrés le 2026-09-23** (`common/services/text_metrics.py`, mécanisme `text_metrics` ; même
  découpage en mots que M1). Aucune mAP, aucun PSNR dans le dépôt.
  **La porte d'entrée (Q6) est ouverte** au même moment : ports du RÉSULTAT
  (`INPUT_MODEL_MATCHING §6.7`), lecture des transcriptions externes, Sonal compris
  (`TRANSCRIBER_CORRECTION §10`). Reste l'adoption par le transcriber (stockage, surfaces, lot).
- ⚠ **Le corpus de vérité humaine du transcriber tenait en UN cas exploitable au 2026-08-13**
  (6 corrigés : 3 identiques à l'ASR, 1 cassé, 1 re-segmenté sans changement de texte). Et le jeu
  de Fabien (audio + transcription auto + transcription manuelle) **n'est pas dans WAMA** — ce sont
  des fichiers (§5, chaînon ⑤).

### M4 — Métrique sans référence ⏳
- **Mesure** : une propriété de la sortie seule. Image : qualité perceptive (NIQE, MUSIQ),
  similarité prompt ↔ image (CLIPScore) ; audio : DNSMOS pour un débruitage, intelligibilité pour
  une voix ; vidéo : constance temporelle (similarité entre trames successives) ; ASR : **confiance**
  du modèle (déjà lue par la heatmap du transcriber, en 2ᵉ priorité derrière la divergence).
- **Ne dit pas** : si la sortie répond à la demande. Une image nette hors sujet score haut.
- **Ancrage** : partiel (la sortie seule, parfois le prompt).
- **Coût** : un modèle léger par métrique (CLIP, DNSMOS) — donc du GPU, ou du CPU lent.
- **Code** : la confiance ASR uniquement.

### M5 — Juge modèle indépendant 🔄 (briques présentes, zéro consommateur)
- **Mesure** : un LLM ou un VLM d'une **autre famille** que le générateur note la sortie par rapport
  à la demande, en JSON strict, avec un drapeau « à revoir ». Pour le visuel : le VLM décrit la
  sortie, et la description est confrontée au prompt (présence des éléments demandés).
- **Ne dit pas** : rien de fiable **tant qu'il n'est pas calibré** : précision et rappel du juge se
  mesurent contre la vérité humaine (protocole `TRANSCRIBER_CORRECTION.md §8.5`), et l'hypothèse à
  réfuter y est écrite : le juge de cohérence signale des disfluences authentiques et rate les vrais
  mots mal reconnus. **Fidélité et fluidité sont anticorrélées sur de l'entretien.**
- **Ancrage** : aucun sur la source (le juge ne reçoit que du texte, jamais l'audio) — c'est le
  défaut structurel du §8.2, et la raison de son rang : dernier.
- **Coût** : une inférence LLM/VLM par item — sur cet hôte, une charge interdite (§7).
- **Code** : `wama/common/utils/qc.py` (`assess_output_quality`, garde-fous en tête) — 0 appelant,
  `bench` compris (re-vérifié le 27/08, `WAMA_LLM.md §5` ligne 12) ;
  `wama/model_manager/services/vision_probe.py` (description d'image par VLM local, consommée par
  le banc de légendage et le triage du smoke).

### M6 — Accord multi-modèles (consensus) 🔄 (transcription livrée le 2026-09-23)
- ✅ **Transcription** : `result_evaluation.batch_agreement` — cards d'une même entrée d'un lot,
  M1 deux à deux (moyenné dans les deux sens), médiane par moteur, le plus isolé SIGNALÉ à partir
  de trois, jamais un tri ; ligne « Accord entre moteurs » de la card mère quand le lot n'a pas de
  référence. L'app déclare `input_identity` + `disagreement` (`TRANSCRIBER_CORRECTION §10.3`).
  Calibration contre M3 : possible dès qu'un même lot porte une référence (les deux se lisent).
- **Mesure** : sur N ≥ 3 sorties du même travail, la **médiane des divergences deux à deux** par
  modèle (M1 ou M2 selon la tâche) → un **taux d'isolement** : à quelle fréquence ce modèle diverge
  du groupe. Par item : le support de chaque élément produit.
- **Ne dit pas** : qui a raison. Un modèle isolé peut être le seul bon (un spécialiste visage face à
  trois généralistes, cas mesuré le 2026-08-12 : le meilleur modèle était le plus petit).
- **Règle** : signal d'attention et départage **à égalité** seulement ; **jamais un tri seul** ; se
  calibre contre M3 là où une vérité existe (le transcriber, dès que le corpus le permet).
- **Code** : rien ; `bench.run_bench` produit la matière (une sortie par modèle) sans la confronter.

### M7 — Signaux d'usage ✅ (captation générique livrée, gisement encore mince)
- **Mesure** : des **gestes** — `produit`, `echec`, `telecharge`, `corrige`, `relance`, `supprime` —
  captés par middleware sur les routes de file des 10 apps (`wama/common/middleware.py`,
  `WAMA_MEMORY.md §7bis`) et par le squelette de tâche (`task_skeleton`, `produit`/`echec`/`relance`),
  plus la correction du transcriber à la finalisation. Agrégés **par modèle** sur les exécutions à
  **un seul** modèle (`run_outcome.par_modele` — sur du multi-modèles, un geste ne dit pas lequel a
  démérité).
- **Ne dit pas** : pourquoi. « Supprimé » ne veut pas dire « mauvais » (en-tête de
  `run_outcome.py`). Un taux de relance ou de correction **par modèle, sur assez d'exécutions, avec
  accord stable** est le seul usage légitime (garde-fou 2).
- **Ancrage** : sur l'humain — c'est la meilleure source, et la plus lente à remplir.
- **Code** : `wama/common/services/run_outcome.py`, `common/models.py::RunOutcome`.

### M8 — A/B humain explicite ⏳ (et une contradiction à trancher)
- **Mesure** : deux sorties côte à côte (cards), l'utilisateur choisit ; le choix, agrégé, est une
  préférence humaine directe — la méthode des arènes (Elo), chez nous, sur nos données.
- **Ne dit pas** : grand-chose à petit effectif ; utile sur les tâches à sortie subjective
  (image, musique, voix) où aucune métrique ne tranche.
- ⚠ `ROADMAP.md §16.7` a posé : *`RunOutcome` se nourrit de ce que l'utilisateur fait DÉJÀ, jamais
  d'un geste ajouté* (« les boucles qui demandent à l'utilisateur de noter le système meurent »).
  Un vote A/B est un geste ajouté. → **décision Q4** (§8).

### M9 — Auto-consistance ⏳
- **Mesure** : le **même** modèle, rejoué avec d'autres graines, températures ou paramètres ; la
  variance des sorties (M1/M2 entre les passes) est une **instabilité**, indépendante de toute
  référence. Pour l'ASR, deux passes à paramètres différents suffisent à alimenter M1
  (`TRANSCRIBER_CORRECTION.md §8.3` : « même modèle à paramètres différents »).
- **Ne dit pas** : si la sortie est bonne — un modèle peut être stablement faux.
- **Coût** : k inférences par item.
- **Code** : rien de dédié ; `bench` accepte `runs` pour la génération de texte (le débit, pas la
  variance des sorties).

### M10 — Aller-retour (round-trip) ⏳
- **Mesure** : chaîner deux modèles **indépendants** et mesurer la perte au retour : voix →
  ASR → WER contre le texte d'entrée (intelligibilité d'un moteur TTS, jugée par un ASR d'une autre
  famille) ; traduction aller puis retour → similarité ; image générée → légende par VLM → présence
  des éléments du prompt.
- **Ne dit pas** : lequel des deux maillons a perdu. Il faut un second maillon **déjà qualifié**
  (l'ASR par M3) pour attribuer la perte au premier.
- **Ancrage** : sur l'entrée (le texte, le prompt) — réel mais indirect.
- **Coût** : deux inférences par item.
- **Code** : rien de dédié. ✅ **Le transport existe** (vérifié le 2026-09-25) : le studio enchaîne
  les apps (`studio/tasks.py::run_pipeline_task`, ordre topologique ; `generic_runner`, triade
  create/start/poll), et `texte → synthesizer (audio) → transcriber (audio)` s'y câble — joué en
  réel ce jour-là, il a révélé un défaut du runner commun (chemin passé en URL encodée, un nom
  accentué perdu entre deux nœuds — corrigé `26fd7191`). ⏳ Manquent : la RÉFÉRENCE propagée
  (l'entrée du nœud amont devient le `reference_result` du nœud aval, que `result_evaluation`
  mesure déjà), et les jeux déclarés (chaînon ①).

**M10 appliqué à la parole — analyse critique (2026-09-25, proposition de Fabien, orientation actée).**
Deux boucles distinctes, qui n'ont PAS la même solidité :

1. **Texte → synthèse → ASR, pour classer les ASR** (vérité = le texte source, exacte et gratuite).
   ⚠ **Écart de domaine** : une voix de synthèse est propre, régulière, sans bruit, sans
   hésitation ni chevauchement — l'inverse d'un entretien. Les ASR y saturent (Whisper rend une
   phrase Kokoro mot pour mot, mesuré le 2026-09-24) : le classement discrimine peu et ne se
   transpose pas à l'oral spontané. ⚠ Biais de FAMILLE (un ASR peut mieux reconnaître les artefacts
   de son cousin TTS : Qwen3-ASR/Qwen3-TTS, VibeVoice). ⚠ Normalisation : un TTS lit « 12 » en
   « douze » — textes sans chiffres ni abréviations, ou normalisation des deux côtés
   (`comparable_words` ne traite pas les nombres).
   **Son vrai rôle : banc de NON-RÉGRESSION et de tests CIBLÉS** — pannes grossières (bascule de
   langue, hallucination sur silence, boucle de jetons, découpage des longs fichiers), **diarisation
   à vérité exacte** (chaque tour lu par une voix différente), termes du labo (mots-clés), fichiers
   longs, horodatage ; rapproché du terrain par **dégradation** (bruit, réverbération, chevauchements
   ajoutés). Il ne devient JUGE de classement qu'après **calibration** : même classement sur le
   corpus réel corrigé et sur le banc synthétique (corrélation de rangs) — sinon il reste un
   détecteur de pannes.
2. **Texte → TTS → ASR qualifié, pour juger les TTS** (le M10 de la matrice §3).
   🔴 **Règle anti-circularité** : l'ASR juge se QUALIFIE SUR DE LA PAROLE HUMAINE (corpus corrigé,
   M3), jamais sur de l'audio de synthèse — sinon il est choisi pour les voix qu'il jugera, et les
   favorise. C'est le « second maillon déjà qualifié » ci-dessus. Au mieux, **deux ASR de familles
   différentes**, et jamais de la famille du TTS jugé. Lecture **relative** (les erreurs propres de
   l'ASR pèsent à peu près pareil sur tous les TTS — à peu près seulement).
   ⚠ Le WER ne mesure que l'**intelligibilité** : une voix robotique bien articulée sort première,
   et le modèle de langue de l'ASR RÉPARE une synthèse pâteuse (le CER est plus sévère). À compléter :
   ressemblance de voix (clonage : empreinte vocale — le modèle d'empreinte de pyannote est déjà sur
   le disque), naturel (M4, prédicteur de note sans référence), prosodie (M8).

**Généralisation en pipelines d'évaluation** — même mécanique (deux nœuds + une évaluation dont la
référence est l'entrée du premier), valeur très inégale : vérité EXACTE d'abord — `upscale` /
`denoise` (dégrader un original → PSNR/SSIM), `ocr` (rendu → image → CER) ; puis TTS→ASR ; puis
**imager → describer**, le plus fragile : le WER n'y a aucun sens (décomposer le prompt en
questions vérifiables posées à un VLM), le juge hallucine (famille différente, calibré), et la
référence est la demande de l'UTILISATEUR, pas le prompt enrichi par l'imager ; l'esthétique reste
aux Elo tiers et à l'humain. Traduction aller-retour : faible (un aller-retour parfait n'atteste pas
l'aller). Composer, avatarizer : quasi rien.

**Ordre acté** : (1) qualifier les ASR sur le corpus réel corrigé ; (2) banc synthétique ASR en
non-régression et tests ciblés, calibré avant d'être juge ; (3) TTS jugés par l'ASR qualifié (+ un
second ASR, + ressemblance de voix) ; (4) boucles à vérité exacte (upscale, denoise, OCR) avant
imager→describer. **Garde-fous** : jeux synthétiques DÉCLARÉS comme tels (A2) ; **interdiction
d'entraîner** sur des sorties des modèles évalués (§4.3) ; textes du domaine du labo plutôt que
génériques.

---

## 3. La matrice tâche × méthode — ce qui s'applique, avec quelle vérité, et quel levier

Lignes = le vocabulaire `ModelTask` (`wama/model_manager/models.py`) plus deux familles hors
vocabulaire (attributs de visage, spécialisation traduction). Colonnes : la vérité terrain
**accessible** (source, §1), la confrontation **sans** vérité, le juge, le banc **tiers** déjà
apparié (`benchmark_sync.CATEGORIES`), le **levier** d'auto-amélioration hors modèle (§4.2), et
l'état de la mesure interne aujourd'hui.

| tâche (`ModelTask`) — apps | vérité terrain accessible | confrontation sans vérité | juge | banc tiers | levier hors modèle | état |
|---|---|---|---|---|---|---|
| `transcription` — transcriber | **humaine** : corrections finalisées (`corrected_segments_json`) ; corpus externe de Fabien (audio + auto + manuel, hors WAMA) | **M1** deux ASR (ou M9 deux réglages), heatmap 1ʳᵉ priorité | M5 cohérence LLM, **cantonnée** (bascule de langue, boucle de jeton, segment tronqué — jamais « incohérence sémantique ») | Open ASR **fr** (WER, sens bas) | profils de correction (`§8.4`), paramètres d'écoute, glossaire ; **finetuning ASR** sur les paires corrigées (§4.3) | M1 ✅ · M3 WER ⏳ · corpus ⏳ (chaînon ⑤) |
| `captioning` — describer, banc, triage smoke | rare ; corrections de description (non captées : le describer n'appelle pas `corrige`) | M6 accord entre VLM (M1 non horodaté), **M10** légende ↔ éléments attendus | M5 VLM d'une autre famille | Arena **vision** (Elo) | consigne au modèle multilingue (langue de sortie), skill de domaine (aucun `PROMPT_TARGET` describer aujourd'hui), contenu RAG (vocabulaire du labo), traduction de sortie (`WAMA_LLM.md §2bis`, non branchée) | ⏳ |
| `ocr` — reader | **humaine** : texte corrigé ; par construction : rendu d'un document numérique → image → OCR (référence exacte, gratuite) | M1 non horodaté entre moteurs (docTR / olmOCR / glm-ocr) | M5 LLM (correction post-OCR — même risque de réécriture qu'en §8.2) | Arena **document** (LLM frontière ; nos moteurs n'y sont pas) | prétraitement, moteur par type de document, correction LLM bornée | ⏳ |
| `text-generation` — assistant, enrichissement, résumé/cohérence du transcriber, rôles wama-dev-ai | **par construction** : consignes à réponse vérifiable (rubrique M3, anglais, versionnée) ; humaine : corrections de résumé (non captées) | M6 entre LLM ; **M9** (température) ; M7 (relance, correction) | M5 LLM d'une autre famille (`qc.py`) | AA Intelligence Index, scores par famille d'épreuves (`benchmark_meta['family_scores']`, lus par `select_model(benchmark_family=…)`), Arena text | **skills** de rôle (`assistant-*.md`) et d'enrichissement (`<app>-<domaine>.md`), `prompt_contract` par modèle, contenu RAG, tier de modèle | ⏳ (débit ✅ depuis le 14/09, coût seulement) |
| `feature-extraction` — embeddings du RAG | **tierce** : jeu français déclaré (MTEB, 4 tâches) ; **interne** : paires question → passage attendues sur le corpus du labo | rappel croisé (deux modèles, mêmes requêtes : recouvrement des k premiers) | — | MTEB `mteb_fr_retrieval` | découpage (`chunking`), niveau de rappel, modèle | banc tiers ✅ · interne ⏳ |
| spécialisation `translation` — translategemma, `TranslatorService` | humaine (rare) | **M10** aller-retour ; M6 entre modèles multilingues | M5 LLM d'une autre famille | — (AA n'expose pas la traduction) | **glossaire** ne-pas-traduire, découpage, modèle | ⏳ |
| `text-to-speech` — synthesizer, service TTS | par construction : le texte d'entrée | **M10** voix → ASR qualifié → WER ; M4 intelligibilité | M5 (faible : un juge ne « voit » pas la prosodie) | AA Elo TTS, Arena TTS (XTTS : 919, seul du lot) | voix, moteur, paramètres ; M8 (subjectif) | ⏳ |
| `audio-enhance`, `denoise` — enhancer | **par construction** : bruiter un audio propre → SNR gagné, ou ASR-après vs ASR-avant | M4 DNSMOS | — | — | moteur, paramètres | ⏳ (gratuit à construire) |
| `detect`, `segment`, `obb`, `pose`, `classify` — anonymizer, cam_analyzer, face_analyzer, banc | **tierce/humaine** : jeux annotés déclarés (`dataset`) ; ⚠ aucune vérité sur les collisions de cam_analyzer (mesuré 13/09) ; **par construction** : le simulateur (`WAMA_APPRENTISSAGE.md §6.4`) | **M2** + **M6** support par objet ; M9 (seuils) | M5 VLM (« y a-t-il un visage ici ? ») — filet RGPD **secondaire** seulement | aucun flux tiers neutre (PwC mort, Roboflow = éditeur) — **mesure interne seule** | couverture de classes (`model_coverage`), seuils de confiance, concepts SAM3 (KIND `concept`, skill `anonymizer-detection.md`), **finetuning** détecteur sur données du labo (§4.3) | M2 ⏳ · saturation ✅ (`bench`) |
| `depth-estimation` — cam_analyzer, banc | **par construction** : simulateur ; **aval** : `placement_spread` du re-calage du plan de sol (métrique de tâche déjà utilisée par l'app) | **M2** cartes (RMSE invariante d'échelle) | — | — | modèle, résolution d'entrée | banc ✅ (couverture, médiane, focale) · confrontation ⏳ |
| `text-to-image`, `image-to-image` — imager | quasi nulle (subjectif) | **M10** légende VLM ↔ prompt ; M4 CLIPScore, qualité perceptive ; M9 graines | M5 VLM d'une autre famille | AA Elo / Arena Elo (t2i, image edit) | **skill** `imager-image.md`, `prompt_contract` du modèle, prompt négatif, pas/guidance ; M8 | ⏳ |
| `text-to-video`, `image-to-video` — imager | quasi nulle | M10 sur trames-clés ; M4 constance temporelle | M5 VLM | AA / Arena Elo (t2v, i2v) | skill `imager-video.md`, contrat, paramètres ; M8 | ⏳ |
| `upscale` — enhancer, converter→enhancer | **par construction** : sous-échantillonner un original net → PSNR/SSIM/LPIPS exacts | M2-like (différence entre sorties) | — | — | moteur, échelle, paramètres | ⏳ (**le plus gratuit de tous** : référence exacte sans humain) |
| `text-to-music`, `text-to-audio` — composer | nulle | M4 similarité prompt ↔ audio (CLAP-like) ; M9 | M5 LLM sur étiquettes (faible) | — (AA : pas d'API musique) | skill `composer-music.md`, **`prompt_contract`** (MusicGen 30-80 mots vs MiniMax 250-450 : le contrat prime), paramètres ; M8 | ⏳ |
| `lip-sync` — avatarizer | par construction : l'audio d'entrée | métriques SyncNet (lib externe) ; M10 (lecture labiale, hors de portée) | M5 VLM (faible) | — | modèle, paramètres | ⏳ |
| attributs de visage — face_analyzer (DeepFace : âge, genre, expression) | **tierce** : jeux étiquetés déclarés | M6 entre moteurs | — | — | moteur par attribut | ⏳ |

Lecture de la matrice :
- **quatre tâches ont une vérité terrain GRATUITE, par construction** — `upscale`, `denoise`,
  `ocr` (rendu → image), `text-to-speech` (aller-retour) : c'est là que M3 se construit d'abord,
  sans corpus humain ;
- **une tâche a la seule vérité HUMAINE du dépôt** — `transcription` : c'est le banc de
  calibration de tout juge (§0) ; tout dépend du chaînon ⑤ (faire entrer le corpus) ;
- **les tâches génératives visuelles et sonores n'auront jamais de vérité** : elles vivent de
  M10, M4, M5 calibré et M8 — et de leurs bancs tiers (Elo), déjà appariés ;
- **la vision de détection n'a AUCUN banc tiers** : la mesure interne (M2, M6, jeux annotés) est
  sa seule source, ce qui en fait le deuxième chantier après le transcriber.

---

## 4. Les deux consommateurs des confrontations — et la voie complémentaire

### 4.1 Mesure interne : de la confrontation à l'indice

Un indice interne entre dans l'échelle des signaux **comme les bancs tiers y entrent**, avec les
mêmes règles, écrites dans `benchmark_sync.py` :
- une **échelle nommée** par (tâche, méthode, version de protocole) — `internal_wer_fr_v1`,
  `internal_iou_consensus_v1`… — avec sa **direction** (`'higher'`/`'lower'` = plus haut / plus bas est
  mieux ; clés `benchmark_meta` passées en anglais le 2026-09-19) ; jamais une valeur nue ;
- une **population** (les modèles mesurés sur le même jeu, dans la même passe) : l'indice n'est
  comparable qu'à l'intérieur d'elle ; le rang centile s'y lit ;
- une **version de protocole** : changer le jeu, le seuil d'IoU ou la rubrique change l'échelle —
  les anciennes valeurs ne se comparent plus (leçon `rubric_version` de llmfit) ;
- **règle de lot** : le tri par indice interne ne s'applique qu'à un lot **entièrement** mesuré ;
  sinon on redescend d'un étage (banc tiers, a priori, VRAM) ;
- **en lecture d'abord** (cards, page du model_manager, volet droit), **dans le tri ensuite**
  (décision Q3), et **accumulation avant confiance** : un indice issu d'une passe sur trois
  échantillons est une anecdote.

Domicile proposé : `benchmark_meta` porte déjà source, échelle, sens, rang, population — un indice
interne y trouve sa place sous une source `internal` ; `sync_benchmarks` n'y touche pas (il ne
réécrit que les sources tierces qu'il connaît). ⚠ À vérifier au code avant d'écrire : ce que
`synchronize` fait d'une clé de source inconnue (décision Q8).

### 4.2 Auto-amélioration : quand le levier n'est pas le modèle

Le mot d'ordre de Fabien : *« l'idée dans WAMA est l'auto-amélioration, pas seulement la
confrontation de modèles »*. Une confrontation qui dit « le modèle B fait mieux que A » ne dit pas
**pourquoi** ; or dans la chaîne réelle (`WAMA_LLM.md §2`), la sortie dépend d'au moins six leviers
qui ne sont pas le modèle. **Les leviers, tels qu'ils existent dans le code** :

| levier | où il se déclare | tâches qu'il touche | comment on le confronte |
|---|---|---|---|
| **skill d'enrichissement** `<app>-<domaine>.md` | `wama/common/prompt_skills/`, résolution `PROMPT_TARGETS` (`app_metadata.py`) | génération image / vidéo / musique / audio, concepts SAM3 | **même modèle, même entrée, deux versions du skill** → M10 / M4 / M5 / M8 ; le skill est le facteur, le modèle est fixé |
| **rôle** de l'assistant `assistant-*.md` | `common/utils/assistant_skills.py` | génération de texte (assistant) | idem, avec M3 (consignes vérifiables) et M7 (relances) |
| **contrat de prompt** du modèle `prompt_contract` | manifeste `model` → `AIModel.prompt_contract` (`WAMA_LLM.md` § skills, doctrine du 26/08) | tout ce qui passe par `process_prompt` | deux contrats → mêmes méthodes ; **le contrat prime sur le skill**, on le mesure en premier |
| **glossaire** ne-pas-traduire, **routage** de langue | `translator.py`, `lang_routing.py` | tout prompt traduit | M10 aller-retour, M5 |
| **contenu RAG** (niveau `user` / `unit`) | geste explicite (`WAMA_MEMORY.md §7ter`) ; hook B fermé pour les apps (`WAMA_LLM.md §5` ligne 4) | assistant ; apps quand le hook sera ouvert | **avec / sans** rappel sur la même consigne → M3 / M5 / M7 |
| **paramètres** d'app et **curseur** `quality_intent` | schémas de paramètres, `read_quality_intent` | toutes | M9 (balayage), puis M3/M2 selon la tâche ; c'est un A/B **objectif**, jamais visuel (règle du transcriber) |
| **profil** de correction (verbatim / CR / cours / sous-titrage) | `TRANSCRIBER_CORRECTION.md §8.4` (politique déclarée, pas variante de prompt) | transcription | M3 contre la correction humaine, par profil |
| **sélection** de modèle (échelle des signaux) | `model_selector` | toutes | c'est la boucle A elle-même |

**La boucle d'amélioration, chaînon par chaînon** (elle réutilise §5) :

```
mesure (indice interne, M7) ──▶ écart constaté (régression N vs N+1, modèle isolé, taux de relance)
   ──▶ DIAGNOSTIC : lequel des leviers explique l'écart ?  (modèle fixé, un facteur à la fois)
   ──▶ VARIANTE du levier (nouvelle version du skill / du contrat / du paramètre / du contenu RAG)
   ──▶ A/B OBJECTIF sur le même jeu (M3 si vérité, sinon M10/M4/M6, M8 si subjectif)
   ──▶ ADOPTION GOUVERNÉE ──▶ SURVEILLANCE (M7, régression) ──▶ retour à la mesure
```

**Qui décide de l'adoption — la règle proposée, à trancher (Q5)** :
- une variante de **skill, de rôle, de contrat** est du **texte de consigne** : elle se propose
  (diff), elle se mesure, elle se **valide par un humain** — jamais d'auto-application. C'est le
  contrat déjà posé pour wama-dev-ai (`PENDING_HUMAN_VALIDATION`, `AGENTS.md §Collaboration`) ;
  un LLM peut **rédiger** la variante, il ne l'installe pas ;
- une variante de **paramètre numérique** (seuil, pas, guidance) peut s'auto-ajuster **dans des
  bornes déclarées** par le schéma de paramètres, sur A/B objectif répété, avec journal — c'est le
  seul cas où l'autonomie est envisageable, et en dernier (`§16.7-4`) ;
- le **contenu RAG** ne s'auto-alimente jamais : l'entrée est un geste (`WAMA_MEMORY.md §7ter`).

### 4.3 La voie complémentaire : réentraînement / finetuning, hors WAMA, depuis WAMA

Cadre déjà tranché (`WAMA_APPRENTISSAGE.md §2`) : **WAMA n'entraîne pas ; il DÉCLARE, DÉCLENCHE
et RÉINGÈRE.** Un entraînement est un `pipeline` dont la sortie est un `model` ; pas de kind
nouveau. Ce que la boucle qualité y apporte, et rien d'autre :
- **la donnée d'entraînement est la vérité terrain de §1** — les paires (sortie IA → correction
  humaine) du transcriber sont le seul corpus du dépôt ; les jeux annotés de détection du labo, le
  simulateur, en sont les suivants. La boucle qualité **produit** ces paires (M7 `corrige`,
  chaînon ⑤) ; sans elle, il n'y a rien à finetuner ;
- **le déclencheur est un indice** : un modèle dont l'indice interne stagne sous les autres alors
  que ses corrections s'accumulent est le candidat ; la décision reste humaine ;
- **ce que WAMA déclare** : A2 provenance réel / synthétique propagée (interdiction d'entraîner sur
  du synthétique produit par le modèle évalué — barrière, pas consigne), A3 `trained_from`
  {dataset, pipeline, metrics, split}, A4 régime exécuté par WAMA / exporté ; **réingestion** par
  manifeste `model` + `ingest()` (connecteur MLflow, `§4` du même doc) ;
- **où ça a du sens**, par tâche : **ASR** (adaptation au français d'entretien, aux termes du labo)
  et **détection** (objets et scènes du labo) — les deux tâches qui ont, ou auront, une vérité ; pas
  les génératifs, qui n'en ont pas et dont le levier est le prompt ;
- **la mesure après réingestion** est la même qu'avant : le modèle finetuné entre dans le lot et se
  confronte (M3 sur un **split** tenu à l'écart de l'entraînement — c'est le champ `split` d'A3).

---

## 5. La chaîne fonctionnelle complète — douze chaînons, et l'état de chacun

| # | chaînon | ce qu'il fait | existe ? | où / ce qui manque |
|---|---|---|---|---|
| ① | **jeux d'échantillons déclarés** par tâche | un jeu = des entrées + éventuellement des références, **déclaré** (kind `dataset`, provenance réel / synthétique A2), versionné, en français quand ce sont des données du labo | ⏳ | rien de déclaré ; le banc prend un fichier à la main (`--media`). ⚠ Un jeu se choisit sur ce que le catalogue sait faire (leçon MTEB) |
| ② | **exécution comparative** | le même jeu sur **tous** les modèles capables de la tâche | ✅ partiel | `bench.run_bench` (7 tâches : detect/segment/obb/pose/classify, captioning, depth, text-generation). Un échantillon à la fois ; pas de lot ; pas de nocturne (`nightly_scenarios` n'appelle pas `bench`) |
| ③ | **collecte des SORTIES** | persister ce que chaque modèle a produit (texte, boîtes, carte, fichier), pas seulement les mesures | ⏳ | le banc **jette** les sorties (boîtes) ou les garde en mémoire (texte) ; rien en base. Sans sorties conservées : ni confrontation différée, ni A/B humain, ni calibration |
| ④ | **confrontation** (M1-M2-M6-M9-M10) | désaccord chiffré entre sorties | 🔄 | M1 ✅ (texte horodaté) ; M2, M6, M9, M10 ⏳ — **calcul pur, constructible sans GPU** |
| ⑤ | **vérité terrain** — entrée et appariement | faire entrer les références (corrections, corpus externes, dégradations par construction) et les apparier aux entrées | 🔄 | corrections du transcriber ✅ (captées, `correction_magnitude`) ; **corpus externe ✅ (2026-09-23)** : la porte est le port `reference_result` de la CARD (appariement = la card elle-même : son audio + sa référence), posé sur un élément ou un lot — Q6 tranchée ; transcriptions externes lues (SRT, VTT, TXT, DOCX, Sonal) ; résultat d'un AUTRE outil comparable par le port `work_result` ; références par construction (upscale, denoise, OCR, TTS) ⏳ |
| ⑥ | **métriques** (M3, M4) | (sortie, référence) → nombre au sens déclaré | 🔄 | **WER/CER ✅** (`text_metrics`), mesure CONSERVÉE par élément (`ResultEvaluation` : modèle, échelle + protocole, sens, identité de la référence) par la brique `result_evaluation`, adoptée par le transcriber ; mAP, PSNR ⏳ |
| ⑦ | **juge** (M5) | avis d'un modèle indépendant, **calibré** contre ⑤ | 🔄 | `qc.py` et `vision_probe` présents, 0 consommateur ; calibration impossible tant que ⑤ est vide |
| ⑧ | **agrégation → indice** | par (tâche, modèle) : valeur, échelle, sens, population, version, date → `benchmark_meta` source `internal` | 🔄 | ✅ **LECTURE livrée (2026-09-23)** : `model_manager/services/internal_quality.py` (étage 3, à côté de `model_quality` et `benchmark_sync`) agrège par modèle — taux de corpus, échelle `internal_<métrique>_<protocole>`, sens, rang parmi les modèles mesurés sur les MÊMES références, accumulation dite ; affichée dans la section « Qualité » du détail de modèle. **Rabattue à la lecture, pas écrite** : Q8 vérifiée au code, `sync_benchmarks` REMPLACE `benchmark_meta` entier (`benchmark_sync.synchronize`) — une clé `internal` y serait effacée ; et ne rien écrire garantit Q3 (hors du tri) par construction. Reste : la PROJECTION dans le tri, le jour où Q3 est tranchée. Historique de cette ligne : la MATIÈRE existe (`ResultEvaluation`, 2026-09-23 : chaque ligne porte déjà modèle, métrique + protocole, sens, référence = population) ; l'agrégation par modèle d'UN lot existe (`batch_evaluation`, taux de corpus) ; reste l'agrégat INTER-lots vers `benchmark_meta` (Q8) — demande explicite de Fabien : « réutiliser cette évaluation comme note de chaque modèle » ; règle de lot déjà écrite dans `_quality_scalars` |
| ⑨ | **consommation** par la sélection et l'UI | 3ᵉ étage de l'échelle ; cards du model_manager ; heatmap (boucle B) | 🔄 | l'étage est **nommé** dans `_quality_scalars`, vide ; heatmap : divergence prévue en 1ʳᵉ priorité, **rien de branché** (§8.3) |
| ⑩ | **diagnostic → levier** | attribuer un écart à un levier (modèle fixé, un facteur à la fois) | ⏳ | aucun outillage ; la table §4.2 est la carte |
| ⑪ | **variante + A/B objectif + adoption gouvernée** | proposer, mesurer sur le même jeu, valider (humain), journaliser | ⏳ | rien ; le contrat `PENDING_HUMAN_VALIDATION` de wama-dev-ai est le modèle |
| ⑫ | **surveillance et déclenchement** | M7 par modèle, régression N vs N+1 ; candidat au finetuning (A3/A4) | 🔄 | M7 ✅ captation ; agrégation `par_modele` ✅ ; rien ne lit ces agrégats ; A2/A3/A4 ⏳ |

**Ce que la chaîne impose, et qu'aucun chaînon ne peut ignorer** :
- **③ avant ④** : sans sorties conservées, chaque confrontation exige de rejouer les modèles, donc
  du GPU — c'est précisément ce qui est interdit ici ;
- **⑤ avant ⑦** : un juge non calibré est une opinion (§0) ;
- **⑧ avant ⑨** : un indice sans échelle nommée ni population ni version est un nombre qu'on
  triera à l'envers un jour (leçon WER du 02/09 : *un nombre ne se trie pas sans son sens*) ;
- **⑪ toujours gouverné** : une variante de consigne ne s'installe pas seule.

---

## 6. Ce qui existe déjà — inventaire mesuré (2026-09-16), à réutiliser, jamais à recréer

| brique | fichier | rôle dans la chaîne |
|---|---|---|
| banc par tâche | `wama/model_manager/services/bench.py`, commande `bench` | ② ; protocoles detect/segment/obb/pose/classify (comptes, confiance, saturation), captioning (texte), depth (couverture, médiane, focale), text-generation (débit, prefill, chargement → ETA) |
| divergence | `wama/common/services/divergence.py`, `manage.py divergence_asr` | ④ M1 (texte horodaté) ; confronte aussi ASR ↔ correction humaine |
| gestes d'usage | `wama/common/services/run_outcome.py`, `wama/common/middleware.py`, `wama/common/utils/task_skeleton.py` | ⑫ M7 ; `correction_magnitude` (⑥ minimal) ; `par_modele` |
| juge LLM | `wama/common/utils/qc.py` | ⑦ M5 (0 consommateur) |
| sonde vision | `wama/model_manager/services/vision_probe.py` | ⑦ M5 visuel ; banc de légendage ; triage du smoke (gardé par `WAMA_GPU_SAFE_MODE`) |
| bancs tiers | `wama/model_manager/services/benchmark_sync.py`, `sync_benchmarks` | l'étage 2 ; **le modèle du schéma d'indice** (échelle, sens, rang, population, alias déclarés) |
| a priori | `wama/model_manager/services/model_quality.py` | l'étage 1 |
| échelle des signaux, curseur | `wama/model_manager/services/model_selector.py` (`_quality_scalars`, `_best_by_vram`) | ⑨ |
| couverture de classes | `wama/common/services/model_coverage.py` | levier « quelle combinaison couvre les classes » (anonymizer, cam_analyzer) |
| durées apprises | `wama/model_manager/services/eta_estimator.py`, `ModelRuntimeStat` | le COÛT, par matériel (jamais une qualité) |
| skills et contrats | `wama/common/prompt_skills/` (+ `README.md`), `common/utils/app_metadata.py` (`PROMPT_TARGETS`), `AIModel.prompt_contract`, `common/services/skills_catalog.py` | les leviers de §4.2 |
| nocturne | `wama/common/nightly_scenarios.py`, `run_nightly_tests` | le cadre d'exécution de ② — sans scénario de banc aujourd'hui |
| apprentissage | `WAMA_APPRENTISSAGE.md §2-§4`, `common/manifests/builtin/dataset.py` (axes), kind `model` | §4.3 ; A2/A3/A4 à déclarer |

---

## 7. Contraintes de terrain — ce qui borne la démarche aujourd'hui

- **Aucune tâche GPU sur l'hôte de développement**, ni par Claude ni par Fabien (15/09 : *« sinon
  on crash systématiquement »*, série de crashs documentée dans `INFRA_WSL_VS_WINDOWS.md`). Donc :
  ② et ⑦ ne se **jouent** pas ici ; ③, ④, ⑥, ⑧ se **construisent** ici (calcul pur, schéma,
  tests contre des sorties synthétiques ou un faux service — comme le débit du 15/09). Les chiffres
  réels viendront d'une machine où le GPU ne tue pas l'hôte (R760xa).
- **Le corpus de vérité humaine est quasi vide** (§2 M3) et le corpus externe n'a pas de porte.
  Rien de ce qui dépend d'une calibration (⑦, M6 pondéré) n'est mûr.
- **Les bancs tiers ne couvriront jamais la détection** ni les tâches audio/vidéo de l'enhancer : la
  mesure interne y est la seule source.
- **Le vocabulaire de `RunOutcome` est fermé aux gestes existants** : toute méthode qui demanderait
  un geste nouveau (M8) est une décision, pas une extension.
- **Langue** : jeux d'échantillons en français (données), prompts et rubriques en anglais (outils),
  sortie vers la langue de l'utilisateur quand le mécanisme existera (`ROADMAP.md §10.B`, sortie non
  branchée).

---

## 8. Décisions ouvertes — à trancher avant d'écrire une ligne

| # | décision | ce qui en dépend | proposition |
|---|---|---|---|
| **Q1** | **où vivent les jeux d'échantillons** : manifestes `dataset` (provenance A2) pointant vers la médiathèque ? un dossier de référence sous `AI-models` ? | ① | manifeste `dataset` + fichiers en médiathèque (déjà la voie d'entrée des médias, copie et dédup) ; un jeu par tâche, petit, français, versionné |
| **Q2** | **persistance des sorties du banc** : une table (`BenchRun` : tâche, jeu, modèle, version, sortie sérialisée ou chemin, mesures) ou des fichiers seuls | ③ ④ ⑧ | une table — c'est ce que confrontent ④ et ce que lit ⑧ ; les fichiers lourds (images, audio) en médiathèque, la ligne pointe. ✅ **Tranché pour les MESURES (Fabien, 2026-09-23)** : table COMMUNE `ResultEvaluation` (une ligne par élément et métrique, le résultat COURANT — la sortie, elle, reste dans l'élément de l'app). La persistance des sorties d'un banc HORS des apps (③) reste ouverte |
| **Q3** | **l'indice interne entre-t-il dans le TRI**, ou reste-t-il en lecture (phase 1) | ⑨ | lecture d'abord, tri quand une tâche a ≥ N passes sur le même jeu (N à fixer) — même règle que le rang centile |
| **Q4** | **M8 (vote A/B humain)** : geste ajouté, contraire au principe de `§16.7` — l'admettre pour les tâches subjectives seulement ? | M8, génératifs | admettre, **opt-in**, cantonné aux tâches sans vérité (image, musique, voix), jamais dans le flux normal |
| **Q5** | **gouvernance de l'auto-amélioration** : humain toujours pour les consignes ; auto-ajustement borné pour les paramètres numériques ? | ⑪ | oui à la séparation ; l'auto-ajustement borné vient **en dernier**, après que M3/M9 aient prouvé la stabilité de la mesure |
| **Q6** | **porte d'entrée des corpus externes** (audio + transcription tierce + correction manuelle de Fabien) : médiathèque ? commande d'import ? formats acceptés (SRT, VTT, TXT, DOCX ?) | ⑤, calibration de tout juge | ✅ **Tranché (Fabien, 2026-09-23)** : les jeux vivent comme n'importe quel média d'app ; la porte est la CARD — ses ports du RÉSULTAT `reference_result` (comparer la sortie) et `work_result` (reprendre un résultat fait ailleurs), `INPUT_MODEL_MATCHING §6.7` ; l'appariement audio ↔ texte EST la card (plus de convention de nom) ; formats SRT, VTT, TXT, MD, DOCX, PDF, exports Sonal compris (`TRANSCRIBER_CORRECTION §10`) |
| **Q7** | **où tourne la nocturne comparative** | ② | R760xa ; l'hôte de dev ne joue plus aucun banc GPU |
| **Q8** | **domicile de l'indice interne** : `benchmark_meta` source `internal` (vérifier ce que `synchronize` fait d'une source inconnue) ou champ dédié | ⑧ | `benchmark_meta`, après vérification ; un champ de plus serait une 3ᵉ échelle de plus à ne pas mélanger. ✅ **Vérifié (2026-09-23)** : `synchronize` REMPLACE `benchmark_meta` des modèles appariés — `benchmark_meta` n'est PAS un domicile sûr sans le modifier. En phase lecture, aucun domicile : la note est calculée à la lecture (`internal_quality`). La question renaît avec Q3 |
| **Q9** | **la consistance de lignée** dans M6 : pondérer l'accord par la diversité des familles (deux YOLO ≠ un YOLO + un DETR) — déclarer la famille où ? | M6 | `AIModel.extra_info['family']` existe pour les snapshots HF ; à généraliser, ou ignorer en phase 1 |

---

## 9. Ordre de construction recommandé — paliers, du gratuit vers le coûteux

Chaque palier est **attestable sans GPU** jusqu'au P4 ; chacun livre une brique commune et sa garde.

| palier | contenu | méthodes | sans GPU ? |
|---|---|---|---|
| **P0** | trancher Q1, Q2, Q6, Q8 ; déclarer un premier jeu par tâche (transcription, détection, upscale, OCR) | — | oui |
| **P1** | ③ persistance des sorties du banc ; ④ **M2** (appariement IoU, F1 symétrique, support), **M6** (isolement), M1 non horodaté, **M9** ; tests sur sorties synthétiques | M1 M2 M6 M9 | oui |
| **P2** | ⑤ vérités **par construction** : upscale (sous-échantillonnage → PSNR/SSIM), denoise (bruitage → SNR), OCR (rendu → image) ; ⑥ métriques ; ⑧ schéma d'indice interne + affichage sur les cards (lecture seule) | M3 | oui (les métriques ; les modèles se jouent ailleurs) |
| **P3** | ⑤ **porte d'entrée du corpus externe** (Q6) ; WER transcriber ; **calibration** de M1 et du juge de cohérence contre la correction humaine (`§8.5` : précision / rappel de chaque signal) ; branchement de la divergence dans la heatmap (boucle B) | M3 M5 | oui pour l'import et la WER ; la calibration du juge rejoue le LLM |
| **P4** | ② **nocturne comparative** sur machine stable : scénario `bench` par tâche, tous les modèles capables, jeu déclaré → ③ → ④ → ⑧ ; M10 pour TTS et génératifs | toutes | **non** |
| **P5** | ⑩ ⑪ boucle d'amélioration : A/B objectif d'un levier (skill, contrat, paramètre) sur le même jeu ; adoption gouvernée (Q5) ; journal | selon tâche | partiellement |
| **P6** | ⑨ l'indice entre dans le tri (Q3) ; ⑫ agrégats M7 lus par le model_manager ; A2/A3/A4 déclarés, déclencheur de finetuning ASR / détection (§4.3) | — | oui |

**Le premier geste rentable, si un seul** : **Q6, la porte d'entrée du corpus de Fabien.** C'est le
seul jeu de vérité humaine disponible, il débloque M3 (WER), la calibration de M1 et de M5, et le
finetuning ASR — quatre chaînons pour un import.

---

## Voir aussi
- `docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F4b` — le plan acté de la
  qualification nocturne comparative (source de ce document, non recopiée)
- `docs/construction/suivi/ROADMAP.md §16.5` (garde-fous), `§16.7` (ordre, `RunOutcome`),
  `§16.2 « llmfit »` (ce qui a été retenu et retiré de l'outil tiers)
- `docs/construction/ia/WAMA_LLM.md` — les leviers (skills, contrats, RAG, routage) et l'état
  mesuré de la chaîne de prompt ; `§5` ligne 12 pour le QC mort
- `docs/construction/ia/WAMA_MEMORY.md §7bis` — captation des gestes (`RunOutcome`)
- `docs/construction/ia/WAMA_APPRENTISSAGE.md` — déclarer / déclencher / réingérer, A2-A4, simulateur
- `wama/transcriber/TRANSCRIBER_CORRECTION.md §8` — divergence, profils, protocole de calibration
- `wama/model_manager/PROSPECTION_PIPELINE.md` — les bancs tiers et leurs verdicts de source

## Journal
- **2026-09-16** — création (demande de Fabien du 15/09). Contenu : vocabulaire, catalogue des dix
  méthodes avec état au code, matrice tâche × méthode, les deux consommateurs et la voie
  finetuning, chaîne en douze chaînons, contraintes, neuf décisions, six paliers. Rien d'implémenté.
  L'« idée 3 » du 14/09 (rubrique LLM par rôle) est retirée comme chantier et absorbée dans M3.
