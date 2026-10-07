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
Règle intangible : **on ne compare que des valeurs qui partagent la même échelle** ; jamais
deux échelles mélangées, jamais de min-max qui inventerait une équivalence
(`benchmark_sync.percentile_rank` : le rang, pas le score).

⚠⚠ **PRÉCISION DU 2026-09-26 (demande de Fabien) — « la même échelle » ne veut pas dire
« tout le lot ».** Cette règle s'appliquait jusque-là en TOUT OU RIEN : un seul modèle non
mesuré faisait tomber l'étage pour tout le monde, et le dernier repli est la **VRAM**,
c'est-à-dire la TAILLE. Mesuré sur le tirage de développement : `albert:gpt-oss-120b`, sans
score coding, suffisait à faire préférer `qwen3.6:35b` (coding 41,9 — 23 Go) à
`qwen3.8:latest` (coding **58,2** — 17 Go), meilleur *et* plus léger. Un étage se juge
désormais sur le **sous-ensemble qu'il couvre** : le modèle non mesuré perd sa place au
classement, il ne la fait plus perdre aux autres. La règle des deux échelles est intacte —
l'étage banc tiers exige toujours une échelle UNIQUE sur le sous-ensemble mesuré.
⭐ *Un lot ne se juge pas au modèle qu'on n'a pas mesuré.*

⚠ **Et LOCAL ≠ DISTANT sur l'axe de la VRAM** (même demande). Un modèle distant a
`vram_gb = 0` : le repli en faisait mécaniquement le **pire** du lot, et le terme de coût du
curseur le pénalisait comme s'il était le plus lourd. Ce sont deux absences différentes —
« pas mesuré » (inconnu, prudence — garde du 02/09) et « n'en consomme pas ici » (hors
sujet). La distinction se lit maintenant sur le champ DÉCLARÉ `AIModel.execution`
(`model_selector.is_cloud`), jamais devinée d'un `vram_gb`.

⭐⭐ **ET LE SÉLECTEUR N'ARBITRE PAS local/distant — l'UTILISATEUR le définit** (recadrage de
Fabien, 26/09). `UserProfile.cloud_policy` a trois niveaux (100 % local / cloud si WAMA est
saturé / cloud autorisé), appliqués **à l'ADMISSION** par `allowed_cloud_keys` →
`select_model(cloud_keys=…)`, et `dev_cloud_keys` y ajoute la souveraineté
(`external_sources.hosting == 'sovereign'`). Un distant qui atteint le classement a donc
**déjà** été autorisé : lui opposer là une préférence pour le local trancherait une seconde
fois, ailleurs, une question déjà tranchée. *(Écrit puis retiré le même jour : j'avais encodé
exactement cette préférence cachée.)* Son coût sur la carte est donc **0** — une mesure, pas
une faveur.

⭐ **LE RANG CENTILE EST BRANCHÉ (2026-09-26, demande de Fabien)** — c'est l'étage qui
permet de comparer un modèle local et un distant sans rien inventer. `percentile_rank` était
écrit depuis le **2026-09-01** pour exactement cette question, calculé et **stocké** à chaque
synchro… et la sélection ne le lisait pas : mesuré le 26/09, **55 modèles mesurés sur 55** en
portent un, sur 11 échelles. Un lot mixte (Albert en `aa_intelligence_index`, Anthropic en
`arena_elo_text`, Ollama en `aa_intelligence_index`) tombait donc d'un cran — et le cran
d'après est la TAILLE. Ordre des étages : sous-indice de domaine → **valeur brute à échelle
unique** → **rang centile (inter-échelles)** → a priori → VRAM (local seulement). Le rang vient
APRÈS la valeur brute, jamais avant : à échelle unique, le score exact dit plus que le rang. Il
ne perd personne au passage (il est écrit en même temps que `benchmark_index`, donc il couvre
le même sous-ensemble). ⚠ Ses deux réserves restent entières et se redisent partout où il
sert : il est **ordinal**, et il dépend de la **population de son banc**.

**L'étage a priori a désormais des valeurs DÉCLARÉES, avec leur source** (2026-10-03, décision de
Fabien) : `model_quality.DECLARED_PRIORS`, lu par la synchro quand la découverte ne dit rien.
Né de la musique : aucun des six modèles de `text-to-music` ne portait de signal, le tirage
classait par VRAM (MiniMax-Music3, 13 Go, devant YuE2). Sources : la table WildSongBench de la
fiche de YuE2 (AUTO-ÉVALUATION des auteurs) pour YuE2, MiniMax Music 3 et ACE-Step 1.5 ; les
votes humains de Music Arena pour les MusicGen, instrumentaux et absents de SongBench — **peu
de duels** (22 contre ACE-Step, 51 small contre medium), donc des RANGS, et l'écart de small est
un choix écrit comme tel. ⚠ **Une table couvre une tâche ENTIÈRE ou rien** : la sélection ne
classe que les notés, et une synchro d'une autre instance a appliqué la table à moitié écrite —
pendant une heure, YuE2 a gagné même au curseur rapide. Mesuré après : rapide → MusicGen Small,
équilibré et qualité → YuE2, cover → YuE2. ⏳ Un banc tiers qui couvre YuE2 et MusicGen, ou une
mesure interne, PRIME dès qu'il existe.
**Recherché le 2026-10-05 — il n'existe pas** (sous forme lisible par machine) :
- l'API v2 d'Artificial Analysis (source `artificial_analysis`, déjà branchée) n'expose AUCUNE
  catégorie musique : elle documente cinq familles média (image, édition, image→vidéo, voix,
  vidéo) ; les chemins musicaux sondés rendent 404 ;
  ⚠ **Corrigé le 2026-10-07** : vrai de l'ancien contrat `data/*`, faux du contrat V2 (lu dans
  sa spécification OpenAPI, `artificialanalysis.ai/api/v2/openapi`, lors de la migration de
  `benchmark_sync`) — il publie en accès GRATUIT `media/music/instrumental/models/free`,
  `media/music/with-vocals/models/free` et `media/speech-to-text/models/free` (`aa_wer_index`).
  Non branchés, non appelés : reste à voir si YuE2/MusicGen y figurent ;
- ses classements musique n'existent que sur la PAGE web (votes humains) : en **instrumental**,
  MiniMax Music 3.0 = 1000 (ancre), **MusicGen = 881** (−119 Elo) ; en **chanté**, aucun modèle
  ouvert (ni YuE, ni ACE-Step, ni MusicGen) ;
- WildSongBench (fiche de YuE2) couvre YuE2, MiniMax Music 3 et ACE-Step — pas MusicGen.
MiniMax Music 3 est l'unique modèle commun aux deux échelles : il CORROBORE l'ordre déclaré
(MusicGen sous MiniMax Music 3, qui est sous YuE2) sans permettre de le MESURER (deux échelles,
deux protocoles — les raccorder serait un choix, pas une mesure). Les valeurs déclarées restent
donc telles quelles ; la corroboration est portée dans leur source (`DECLARED_PRIORS`).
⇒ La voie qui reste est la **mesure interne** (étage 3) : un évaluateur automatique de qualité
musicale tourné sur les sorties du composer — chantier à décider, pas un reste d'intégration.

⏳ **`AIModel.cost_tier` reste NON LU, et c'est délibéré** (question tranchée le 26/09,
demande initiale de Fabien de « brancher l'arbitrage honnête », retirée après mesure). Le
champ est bien renseigné par source (`external_sources` : albert `free` + souverain,
anthropic `metered`, claude_code `subscription`) mais **aucun consommateur ne l'ordonne**.
Le brancher dans le score du curseur demanderait d'inventer l'ordre ET des poids, et de
mettre des euros et des gigaoctets dans un même min-max — l'équivalence que cette même
section interdit. Or WAMA arbitre déjà « où partent mes données, à quel prix » **à
l'admission**. C'est là qu'un arbitrage de coût a son domicile : un niveau de `cloud_policy`
ou un ordre de sources, pas un second lieu qui divergerait du premier.

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
| **Q7** | **où tourne la nocturne comparative** | ② | R760xa ; l'hôte de dev ne joue plus aucun banc GPU. ⚠ **Précision de Fabien (2026-09-30)** : *« aujourd'hui la machine est stable »* — l'instabilité de l'hôte est résolue (`INFRA_WSL_VS_WINDOWS`), la condition « machine stable » de P4 ne bloque plus sur l'hôte actuel |
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

**P4 précisé (Fabien, 2026-09-30) — réévaluer ce qui a CHANGÉ, jamais rejouer le même test.** On
ne refait pas deux fois une évaluation identique : on change le corpus, on intègre des modèles.
Une évaluation déclarée est un TABLEAU **corpus × modèles × réglages** (c'est déjà ce que posent les
lots d'`asr_eval_corpus`), chaque case porte son résultat, et une case devient **PÉRIMÉE** quand son
modèle (nouveau, nouvelle version) ou son corpus change — l'état `STALE` du modèle pipeline
(`WAMA_APP_GENERATION_ROUTE §10.6`). La rythmique existe déjà — la campagne nocturne (`beat`) — et
elle ne recalcule que les cases périmées : un modèle intégré ajoute sa colonne, un corpus sa ligne,
le reste ne se rejoue pas. *On ne s'occupe que de tenir les modèles et les corpus à jour.* C'est ce
qui tranche la question de la « répétition » (`ROUTE §13.9`) : pas d'interface de récurrence pour ça.
⏳ Le lancement reste soumis à la décision du 28/09 (*à la demande seulement*, §9bis), à lever.

**Le premier geste rentable, si un seul** : **Q6, la porte d'entrée du corpus de Fabien.** C'est le
seul jeu de vérité humaine disponible, il débloque M3 (WER), la calibration de M1 et de M5, et le
finetuning ASR — quatre chaînons pour un import.

### 9bis — LES CORPUS OPEN DATA S'AJOUTENT À CELUI DE FABIEN (décision, 2026-09-27)

🔴 **Décision de Fabien** : *« pour le corpus, c'est plus simple de partir d'open data que d'en
constituer un […] Je n'ai que 2 audios + transcription corrigée manuellement, sans certitude que
la transcription soit exacte. Il vaut mieux partir de données certifiées depuis des datasets. Ça
pourrait rentrer dans les tests nocturnes et ne pas encombrer les tâches utilisateur. »*

⚠⚠ **Ça COMPLÈTE la source de vérité, ça ne la remplace pas** — et c'est le mécanisme du §4.1 qui
le dit : un indice porte une **échelle nommée** ET une **population**, « l'indice n'est comparable
qu'à l'intérieur d'elle ». Le corpus de Fabien et un jeu open data sont **deux populations**, donc
deux échelles qui **s'ajoutent**. Rien ne se substitue à rien — comme les bancs tiers et la mesure
interne coexistent au lieu de se remplacer.
**Deux surfaces, un seul mécanisme de mesure** : les audios de Fabien par le port
`reference_result` de la CARD (Q6, déjà tranchée) ; les jeux open data par les **tests nocturnes**,
pour ne pas encombrer les tâches utilisateur. *(Révisé le 2026-09-28 par Fabien : **à la demande
seulement** pour l'instant, par les LOTS du transcriber — voir « SUMM-RE évalué à la demande »
plus bas. Le nocturne reste une piste.)*
*J'avais écrit « ça change la source de vérité annoncée » — faux, et corrigé par Fabien.*

#### Ce qu'il faut d'un corpus pour COMPARER des moteurs : du LONG

Constat de Fabien : *« il faut des audios suffisamment longs. Pas 5 secondes. Plus le texte est
long, plus un modèle risque de faire des erreurs et c'est là qu'on peut réellement établir une
comparaison. »* Le seuil qui compte est **30 s** — la fenêtre de Whisper : au-delà, on teste le
fenêtrage, la dérive, les boucles de répétition et l'hallucination sur silence, c'est-à-dire ce
qui SÉPARE les moteurs. En deçà, tous se valent à peu près.

**Mozilla Data Collective ne répond PAS à ce besoin** (mesuré, 24 requêtes : réunion, entretien,
conférence, parlement, livre audio, téléphone…). Ce qui y est long est dans une autre langue
(portugais brésilien 140 h d'entretiens spontanés, manipuri/gujarati 25 h conversationnels,
arménien 20 h), d'un registre particulier (*English Stuttered Speech*), ou sous licence
commerciale avec des SOUS-TITRES — qui ne sont pas des transcriptions verbatim. Common Voice reste
à ~5 s l'énoncé.

**La route HuggingFace n'est pas à construire** : `common/tts/voice_refs.py` (`_try_voxpopuli`)
streame déjà `facebook/voxpopuli` par `datasets`, **sans authentification**, à travers le proxy.

**Candidats VÉRIFIÉS par l'API** (existence, accès, volumes — jamais cités de mémoire) :

| jeu | langue | ce que c'est | accès |
|---|---|---|---|
| **`distil-whisper/earnings22`** config `full` | EN | **125 appels d'actionnaires ENTIERS** (colonne `file_length`), 1,92 Go — le jeu long-form de référence | non *gated* ; ⚠ **licence non déclarée** en `cardData`, à vérifier avant usage |
| `distil-whisper/meanwhile` | EN | 64 monologues, 0,06 Go | non *gated* |
| `edinburghcstr/ami` | EN | **réunions réelles multi-locuteurs** — le registre du transcriber ; 22,1 Go, mais **découpé en énoncés** (12 643 au test) : `meeting_id` + `begin_time`/`end_time` permettent de RECONSTITUER la session | **CC-BY-4.0** |
| `BrunoHays/ESLO` | **FR** | corpus d'Orléans, entretiens sociolinguistiques spontanés — proche de l'usage SHS | ⚠ **CC-BY-NC-4.0** (à confronter à `LICENSING.md`) ; viewer en échec, script de chargement custom |
| `datasets-CNRS/ESLO-MD` | FR | idem | ⚠ CC-BY-NC-SA-4.0, viewer désactivé |

*Écartés* : `speechcolab/gigaspeech` et `kensho/spgispeech` sont *gated* ; `LIUM/tedlium` rend
**401**.

**VoxPopuli `fr` — MESURÉ, et il ne suffit pas** (12 lignes streamées du split `test`) : le texte
est bien là (`raw_text` ET `normalized_text`, plus `is_gold_transcript`, `gender`, `speaker_id`,
`accent`), mais **médiane 7,4 s, max 20,1 s, 0/12 au-dessus de 30 s**. C'est un corpus ASR
SEGMENTÉ. Il reste précieux (CC0, route câblée, texte de référence) pour le registre court ; il ne
répond pas à la question du long format. Une piste non tranchée : **recoudre** des segments
consécutifs d'une même session pour fabriquer du long — mais un long RECOUSU n'est pas un long
RÉEL, et il faudrait le déclarer comme tel (garde-fou A2 : « jeux synthétiques DÉCLARÉS »).

#### ⭐ Le français long format est RÉGLÉ — et c'est la recherche web qui l'a trouvé

Le paragraphe ci-dessus concluait « le point dur est le FRANÇAIS : les deux ESLO sont **NC** ».
**Périmé le jour même** : la clé Exa posée au profil, la toute PREMIÈRE requête réelle passée par
`engine_for(user)` a sorti trois candidats que ni mes requêtes Mozilla ni mes identifiants de
mémoire n'avaient atteints. Vérifiés ensuite par l'API HF, un par un :

| jeu | ce que c'est | licence | volumes |
|---|---|---|---|
| **`linagora/SUMM-RE`** | **conversations de RÉUNION en français** (corpus Linagora, article HAL/Inria) — le registre exact du transcriber | ✅ **CC-BY-SA-4.0**, non *gated* | 15,5 Go · **45 PISTES au split `test`** (+ 45 train, 50 dev) — ⚠ *corrigé le 2026-09-29 : une ligne est une piste de LOCUTEUR (micro-cravate, 48 kHz, ~21 min), pas une réunion ; 3-4 pistes par réunion, soit une douzaine de réunions au test* · colonnes `meeting_id`, `speaker_id`, `audio`, `segments`, `transcript` |
| `ggfox00000/stt-summre-fr-test` | miroir du split test de SUMM-RE, prêt pour l'ASR | CC-BY-SA-4.0 | 13,8 Go · 124 items |
| `ggfox00000/stt-cefc-fr-test` | miroir long format de **CEFC-Orfeo** (français parlé) | ⚠ `other` — à lire avant usage | 19,8 Go · 901 items · porte `duration_sec`, `n_segments`, `n_speakers` |

⇒ **SUMM-RE remplace ESLO** pour le français : même registre (parole spontanée, plusieurs
locuteurs, sessions entières), et une licence **CC-BY-SA** au lieu de **NC** — donc plus rien à
arbitrer contre `LICENSING.md`. Les ESLO restent une piste, plus une nécessité.

⭐ **Ce que cet épisode démontre, et qui vaut plus que le corpus** : l'outil de recherche web a
payé son intégration **à sa première requête réelle**, en atteignant ce qu'une session entière de
requêtes par mots-clés sur un seul catalogue n'avait pas trouvé. *Un catalogue interrogé de
l'intérieur ne rend que ce qu'il contient ; c'est la recherche qui dit ce qui existe ailleurs.*
⚠ Et la discipline tient quand même : un moteur rend des **pages**, pas des faits — les trois
lignes ci-dessus sont vérifiées à l'API (licence, accès, splits, colonnes), pas recopiées du
résultat de recherche.

🔚 **Reste ouvert** : l'anglais est réglé par `earnings22` (1,92 Go) ⚠ **licence non déclarée en
`cardData`**, à lire avant usage ; et la licence `other` du miroir CEFC-Orfeo.

#### ✅ SUMM-RE ÉVALUÉ À LA DEMANDE, PAR LES LOTS DU TRANSCRIBER (construit le 2026-09-29)

**Quatre décisions de Fabien (2026-09-28)** : *l'unité est la RÉUNION MIXÉE* (le cas d'usage réel
est un enregistrement de salle, pas une piste de micro-cravate) ; *à la demande SEULEMENT* — la
cadence nocturne écrite plus haut n'est pas retenue pour l'instant ; *normaliser les marques du
corpus ET les nombres* ; *stocker en médiathèque SYSTÈME*. Et une consigne : *« tout existe dans
le Transcriber pour évaluer les modèles. Il faut réutiliser l'existant. Ça fonctionne par
batch. »*

**Rien d'inventé en aval** — la commande `manage.py asr_eval_corpus summ-re` ne fait que préparer
des ENTRÉES et poser des cards ; le reste est la chaîne existante :

| étape | brique RÉUTILISÉE |
|---|---|
| plan : quelles pistes dans quels parquets, **sans télécharger l'audio** | lecture par plages HTTP (`HfFileSystem`) des seules colonnes `meeting_id`/`speaker_id` |
| mixage : pistes → 16 kHz, sommées, normalisées en crête ; référence = segments de toutes les pistes triés par début, SRT `[Locuteur NNN]` | le lecteur de référence du transcriber (`transcript_documents.parse_cues`) retire l'étiquette du texte mesuré |
| stockage : audio = nature **`speech`** (neuve : langue, locuteurs, corpus, partition, enregistrement), référence = nature `document` (`srt`/`vtt` admis) | `media_library/system_files.ingest_system_file` — **extrait** de `voice_refs.ingest_voice_file` (remplacement, retrait de l'ancien fichier, nom propre), la voix y délègue |
| comparaison : **un LOT par réunion**, une card par moteur, toutes DÉSIGNANT le même audio système (pas de copie) | `tool_api.add_to_transcriber` (→ `designate`), `batch_common.attach_to_batch`, `tool_api.start_transcriber` |
| mesure : référence posée sur le lot, mesurée à la fin de chaque card | `result_evaluation.attach_reference` → `evaluate` → `ResultEvaluation` → `internal_quality` (section « Qualité » du model_manager) |
| description du corpus | manifeste `dataset` écrit à la main, `manifests/datasets/summ-re.json` (source, révision épinglée, licence, langue, axes, signaux dérivés) |

**Protocole de mesure `text_v2`** (`common/services/text_metrics.py`) : le `_` du corpus lie des
mots (`du_coup`, `vingt_quatre`) sans en être un ; les nombres sont écrits en chiffres des DEUX
côtés dans la langue ENTENDUE (`text2num`, MIT) ; les hésitations restent COMPTÉES (verbatim).
Les lignes `text_v1` restent sur leur échelle — `§4.1` : un indice n'est comparable qu'à
l'intérieur de son protocole.

⚠ **Biais connu, commun à tous les moteurs d'un lot** : sur la parole SUPERPOSÉE, la référence
ordonne les mots par début de segment ; un moteur qui les rend autrement y perd des mots. Il
déplace le NIVEAU, pas le classement.
⚠ **Diarisation coupée** sur ces cards : elle ne change pas le texte mesuré, seulement le temps.
⚠ **Le Hub limite les appels** (429 vécu au 2ᵉ fichier, jeton compris) : la commande attend et
reprend ; la préparation est idempotente (une réunion déjà en médiathèque n'est pas retéléchargée,
une CONFIGURATION — moteur × prétraitement × filtre de parole — déjà posée sur un audio ne
l'est pas deux fois ; `--preprocess` / `--vad` en AJOUTENT au lot de la réunion). Les parquets sont
téléchargés un par un dans un dossier temporaire et supprimés après usage.

**Mesures complètes du 2026-09-29 (lots #498-500, 30 cards, `text_v2`)** — erreur par mot sur les
DEUX réunions valides (`007a_ECRH` 20 min, `012c_EBPZ` 19 min) :

| configuration | 007a | 012c | moyenne |
|---|---|---|---|
| Whisper | 28,5 % | 27,4 % | **28,0 %** |
| Whisper + débruitage IA, filtre de parole coupé | 28,1 % | 28,5 % | 28,3 % |
| Qwen3-ASR 1.7B | 30,2 % | 27,1 % | 28,7 % |
| Whisper + débruitage IA | 27,9 % | 29,7 % | 28,8 % |
| Qwen3-ASR 1.7B + débruitage IA | 31,6 % | 28,3 % | 30,0 % |
| Canary 1B v2 + débruitage IA | 38,4 % | 32,3 % | 35,4 % |
| Canary 1B v2 | 34,8 % | 42,5 % | 38,7 % |
| Whisper, filtre de parole coupé | 34,0 % | **95,5 %** | — (effondrement) |
| Parakeet TDT 0.6B v3 (± débruitage) | 98 % | 62-79 % | inutilisable |

- **Whisper et Qwen3-ASR se valent** (28-29 %) ; Canary est derrière ; le **débruitage IA ne change
  rien** pour Whisper et Qwen (±1 point), aide Canary sur une réunion et le dessert sur l'autre.
- ⚠ **Couper le filtre de parole de Whisper est dangereux** : sur `012c`, 95,5 % — Whisper s'est
  effondré (2 min de traitement au lieu de 14, texte inventé ou en boucle). Le mode « auto » du
  filtre ne le coupe que sur une parole lointaine détectée : c'est le bon réglage par défaut.
- **Complété le 2026-09-29 soir — 3 réunions valides (013c ajoutée) et NIVELLEMENT** (erreur par
  mot, moyenne 007a / 012c / 013c) : Whisper **28,8 %** · Whisper nivelé 29,6 % · Qwen3-ASR nivelé
  29,6 % · Qwen3-ASR 30,8 % · Canary nivelé 33,0 % · Canary 37,0 % · Parakeet 83-91 %. Le
  **nivellement** : neutre pour Whisper (+0,8), léger gain pour Qwen (−1,2), net gain pour Canary
  (−4,0). Sur FLEURS-CS (locuteurs différents, sauts de niveau entre phrases), il fait baisser
  l'erreur par CARACTÈRE de 3-4 points pour les trois moteurs et remonte la part de parole
  transcrite de Whisper (65 → 71 %) ; l'erreur par mot baisse pour Qwen (42,1 → 39,5 %) et
  Canary, pas pour Whisper. ⇒ Il reste une OPTION (coupée par défaut) : utile aux moteurs autres
  que Whisper et aux enregistrements à grands écarts de niveau. Détail FLEURS-CS (réglage des
  langues) : `TRANSCRIBER_CORRECTION §5quater`.
- **Pourquoi ~28 % — décomposé** (question de Fabien, 29/09 ; Whisper, Qwen, Canary sur 007a et
  012c) : les **omissions font l'essentiel** (17-24 % des mots de la référence), les mots
  réellement mal entendus seulement **6-9 %**, les ajouts 1-3 % (Canary 11 % sur 012c). Retirer
  des DEUX côtés hésitations et acquiescements (`euh`, `ben`, `ouais`, `mh`…) ne rend que 4-6
  points. Le reste : des passages **non transcrits du tout** — 7 à 15 % du temps de parole de
  chaque locuteur n'est recouvert par aucun segment produit (tours courts, parole superposée :
  17 % du temps sur 007a) — et le style normalisé des moteurs (`ne` ajouté). ⚠ **Ce n'est PAS le
  niveau** : sur 007a, le locuteur le plus FORT du mixage (−23,7 dBFS) a la plus forte erreur
  locale (60 %), un locuteur 6 dB plus faible la plus basse (31 %). ⇒ Le chiffre mesure l'écart
  entre une transcription VERBATIM de parole spontanée et ce que rendent les moteurs ; les 5 %
  annoncés pour ces modèles (`nemo_asr_backend.py:5`) sont mesurés sur de la parole LUE.
- **Un modèle DISTANT dans les mêmes lots — Albert (DINUM) `whisper-large-v3`, 2026-09-30** (cards
  #1072-1074, `asr_eval_corpus --engines albert:whisper-large-v3`, même chaîne, même référence ;
  1ᵉʳ moteur d'app distant, `ROADMAP §8d 4b`) — configuration identique à la ligne « Whisper »
  (sans prétraitement ni nivellement, filtre de parole « auto ») :

  | réunion | Whisper local | Albert | écart |
  |---|---|---|---|
  | 007a | 28,5 % | 32,6 % | +4,1 |
  | 012c | 27,4 % | 31,3 % | +3,9 |
  | 013c | 30,5 % | 30,9 % | +0,4 |
  | **moyenne** | **28,8 %** | **31,6 %** | **+2,8** |

  Le MÊME modèle rend donc environ 3 points de plus chez Albert : ce qui diffère est la CHAÎNE —
  le Whisper local passe par notre filtre de parole et nos réglages de décodage, Albert par les
  siens (inconnus). Albert fait MIEUX que le Whisper local SANS filtre (34,0 % · 95,5 % · 36,1 %) :
  il se place entre les deux réglages locaux. **D'où vient l'écart — décomposé** (détail de
  `ResultEvaluation`, substitués / omis / ajoutés, réunion par réunion) :

  | réunion | local + filtre | Albert | local sans filtre |
  |---|---|---|---|
  | 007a | S350 · D1255 · I142 | S368 · D1508 · I120 | S309 · D1682 · I90 |
  | 012c | S257 · D581 · I73 | S201 · D808 · I30 | S206 · D2965 · I1 |
  | 013c | S226 · D955 · I82 | S208 · D1022 · I49 | S234 · D1206 · I55 |

  Albert reconnaît aussi bien (substitués du même ordre) mais **omet 70 à 250 mots de plus** par
  réunion. Ses segments durent 22 à 25 s et couvrent 92 à 97 % de l'audio (ceux du local : 1 à
  2 s) : il ne découpe visiblement PAS la parole en amont comme notre filtre. ⚠ Cause DÉDUITE, pas
  mesurée — puis **RÉFUTÉE par la mesure le 2026-10-01** (GO de Fabien) : le worker ne passait le
  filtre qu'au moteur NOMMÉ `whisper` ; il passe désormais par la capacité `supports_vad_filter`,
  qu'Albert déclare (même VAD Silero, réglages par défaut, temps replacés sur l'audio d'origine).
  Cards #1232-1242 (compte `evaluation`, mêmes lots, « filtre = auto ») ; les anciennes #1072-1082,
  qui avaient tourné SANS filtre malgré leur `vad_mode='auto'`, sont réétiquetées `off` (ce
  qu'elles ont exécuté). Variante ≤ 30 s par envoi mesurée sans écrire en base (même lecture de
  référence, même fonction d'erreur ; étalonnage : les 11 valeurs stockées retrouvées à 0,1 près) :

  | | Albert sans filtre | Albert filtre (un envoi) | Albert filtre (≤ 30 s / envoi) | Whisper local |
  |---|---|---|---|---|
  | SUMM-RE (3) | 31,6 % | 31,7 % | 32,2 % | 28,8 % |
  | FLEURS-CS (8) | 44,5 % | **39,8 %** | 40,3 % | 45,1 % |

  Omis en réunion, filtre compris : 1535 · 803 · 1094 (sans : 1508 · 808 · 1022) — le découpage ne
  les réduit pas, et les segments restent de 22 à 27 s sur une parole déjà condensée. ⇒ L'écart
  est dans le DÉCODAGE d'Albert (faisceau, conditionnement : non exposés par son API), pas dans
  notre chaîne. Le filtre reste actif pour Albert (il aide l'audio multilingue, ne coûte rien en
  réunion) ; l'envoi par morceaux, sans gain, a été retiré du code. ⚠ FLEURS reste très dispersé
  (seed353 : 25,4 sans filtre, 30,7 avec, 42,9 par morceaux) : huit enregistrements ne tranchent
  pas un écart de quelques points. ⚠ Le compte `evaluation` est « 100 % local » : il ne peut pas
  rejouer Albert (refus voulu de `cloud_access`) — profil et clé à décider par Fabien.
  En regard : **0 Go de VRAM locale** et 5 à 8 s pour
  19-26 min d'audio (mesuré à l'appel direct). ⚠ Trois réunions : un ordre de grandeur, pas un
  verdict ; et, pour de vrais entretiens, l'audio QUITTE la machine — sans objection
  (`ROADMAP §8d` ③, TRANCHÉ par Fabien le 2026-10-02 : le cloud est un choix de l'utilisateur, et
  Albert est l'hébergement souverain de la DINUM).
  **FLEURS-CS, même soir** (8 enregistrements fr/en, cards #1075-1082, comparées aux cards Whisper
  « langues = auto » des mêmes lots, mesures en base) : erreur par mot **44,5 %** (Albert) contre
  **45,1 %** (Whisper local) — un match nul EN MOYENNE, mais très dispersé d'un enregistrement à
  l'autre (Albert −25,7 points sur seed266, +25,7 sur seed397). Remesuré le 30/09 : ce sont les
  valeurs d'APRÈS les correctifs de langue du 29/09 (sur les 15 lots, Whisper « auto » = 41,9 %,
  comme au rapport) — le 45,1 % égal au « avant » des 15 lots est une coïncidence. Sur ces 8 lots,
  Qwen3-ASR « auto » + nivellement fait **21,1 %** : Albert est loin de la meilleure configuration
  locale ; accord de langue par segment 48 %
  contre 46 %. Albert n'annonce qu'UNE langue par fichier (il transcrit d'un seul tenant, et son
  `language` TRADUIRAIT : il ne lui est jamais imposé). ⇒ Sur la parole spontanée (réunions),
  Albert est ~3 points derrière ; sur la parole lue qui change de langue, à égalité sans filtre et
  devant avec (39,8 %, 2026-10-01) — gratuit en GPU, pas un remplaçant de qualité supérieure.
- ⚠ **`008a_EARH` ÉCARTÉE** : la piste du locuteur 028 n'est « transcrite » que par des jetons
  (`sil`, `w_1 w_2 … w_14`, 1 768 jetons) alors que sa parole est dans l'audio — tous les moteurs
  y faisaient 66-69 %. `asr_eval_corpus` écarte désormais toute réunion dont une piste est masquée
  (`is_masked_transcript`) et prend la suivante (`013c_EAPD`).
- ⚠ **Card #741** marquée « crash machine » à tort : un message RE-LIVRÉ périmé (1ʳᵉ exécution
  tombée pendant une relance de WAMA) a écrasé la relance réussie. Corrigé dans
  `process_control.refuse_crash_redelivery` (`73d33b56`), card rétablie.

**Premières mesures (2026-09-29, réunion `007a_ECRH`, 20 min, 4 locuteurs, `text_v2`)** — partielles,
une réunion, sans prétraitement : Whisper **28,5 %** · Qwen3-ASR 1.7B **30,2 %** · Canary 1B v2
**34,8 %** · Parakeet TDT 0.6B v3 **98,7 %**.
- **Ce que contient l'erreur de Whisper** (décomposée, #740) : 1 747 erreurs sur 6 121 mots, dont
  **72 % de SUPPRESSIONS** ; les substitutions — les mots réellement mal entendus — ne font que
  **5,7 %** des mots. Les mots perdus sont d'abord des acquiescements et hésitations (`ouais` 82,
  `euh` 78, `ben` 38, `mh` 27, `ah` 24, `quoi` 23, `hein` 16) : la référence en porte 262
  hésitations, Whisper 50. Les retirer des DEUX côtés ne ramène qu'à 25,8 % (diagnostic, pas un
  protocole) : le reste tient à la **parole superposée — 17 % du temps de parole** (2,9 min sur
  17,2), où un moteur ne rend qu'une voix — et au style « propre » de Whisper (il AJOUTE le `ne` de
  négation que le locuteur n'a pas dit, 14 fois). ⇒ Le chiffre est juste au sens VERBATIM
  (doctrine du transcriber) ; il mesure surtout l'écart entre une transcription verbatim et le
  style normalisé des moteurs, beaucoup moins des erreurs d'audition.
- **Parakeet v3 décroche sur ce registre** — ce n'est PAS le découpage de WAMA : mesuré sur CPU, même
  extrait de 120 s, **99,7 % en une passe, 97,8 % en passes de 30 s** ; il glisse en ANGLAIS (*« For
  the bibliothek municipality… »*) et perd l'essentiel. Sa langue est DÉTECTÉE, sans consigne
  possible (seul Canary reçoit la sienne, `nemo_asr_backend.py:234`). Ses 5,38 % annoncés sont
  mesurés sur de la parole LUE ; sur de la réunion spontanée mixée, il n'est pas utilisable en l'état.

**Diarisation mesurée (2026-09-30, SUMM-RE 007a/012c/013c, 53 min de parole, Whisper, cards
#1009-#1014)** — mesure `diar_v1` (`common/services/diarization_metrics.py`), rangée sous le
DIARISEUR, pas sous l'ASR : **cpWER** (le WER où un mot prêté au mauvais locuteur compte comme
erreur, locuteurs appariés au mieux) et **DER** (sur le temps, par `pyannote.metrics`, collier 0,
chevauchements comptés).

| pipeline | WER | cpWER | dû aux locuteurs | DER | = manquée | + fausse alarme | + confusion |
|---|---|---|---|---|---|---|---|
| pyannote 3.1 | 28,9 % | **36,8 %** | 7,8 pts | **39,7 %** | 24,3 | 10,2 | **5,1** |
| pyannote community-1 | 28,7 % | 37,1 % | 8,5 pts | 40,0 % | 24,5 | 9,8 | 5,6 |

- **Aucun écart significatif** entre les deux pipelines sur ce corpus (3 réunions : un écart de
  0,3 point n'est pas un classement). Le défaut reste **3.1** ; community-1 ne se justifie pas ici.
  Le nombre de locuteurs est retrouvé partout (4/4, 3/3, 4/4). Vitesse équivalente : 13-17 s par
  réunion de 20 min une fois chargé (community-1 se charge en 2 s).
- ⭐ **La diarisation n'est pas le problème** : la CONFUSION de locuteur ne fait que ~5 % du temps de
  parole. L'essentiel du DER est de la **parole MANQUÉE (24 %)** — des passages que l'ASR n'a pas
  segmentés, déjà vus dans le WER (omissions, parole superposée). Le DER d'une card mesure la
  CHAÎNE (segments ASR étiquetés par le diariseur), pas le diariseur seul — d'où ses trois parts.
- Pour « qui a dit quoi », ~8 points de cpWER s'ajoutent au WER : c'est le coût réel des
  attributions de locuteur pour un compte rendu.
- Relancer : `manage.py asr_eval_corpus summ-re --meetings 3 --user <login> --engines whisper
  --diarization speaker-diarization-3.1 speaker-diarization-community-1 [--start|--report]`.

**Prétraitement × filtre de voix sur un entretien LONG enregistré à distance (2026-09-30, lot
#489, 2 h 22, Whisper, référence Sonal nettoyée de Fabien)** — question de Fabien : le
prétraitement rendait le DÉBUT plus fidèle, couper le VAD améliorerait-il ?

| card | prétraitement | VAD | WER | mots produits (réf. 17 594) | suppressions |
|---|---|---|---|---|---|
| #724 | non | auto | 44,5 % | 21 177 | 858 |
| #1048 | non | coupé | **42,8 %** | 20 905 | 902 |
| #725 | oui | auto | 81,0 % | 5 383 | 12 375 |
| #1049 | oui | coupé | 82,6 % | 5 719 | 11 985 |

- ⭐ **Le DÉBRUITAGE efface la parole de cet enregistrement, pas le filtre de voix** : VAD coupé ou
  non, le prétraitement perd ~70 % des mots, sur tout l'entretien (trous de 60 à 104 s). L'hypothèse
  « débruitage puis VAD qui saute les passages » est RÉFUTÉE par #1049. Ce qu'a vu Fabien est
  exact mais LOCAL : sans prétraitement, Whisper invente au tout début (*« je danse, j'enregistre,
  je mange »* pour *« je lance l'enregistrement »*). Même sens que le lot #443 (entretien propre,
  32 → 37 %) et que SUMM-RE (013c : 30,5 → 39,2 %) : **le prétraitement reste à réserver aux fonds
  très bruyants**, ce que dit déjà son aide (`transcriber/params.py`).
- Couper le VAD sans prétraitement gagne 1,7 point ici, alors qu'il avait effondré Whisper sur
  SUMM-RE 012c (95,5 %) : pas de réglage universel, c'est le rôle du mode « auto ».
- ⚠ **Les ~4 400 ajouts restants viennent surtout du STYLE de la référence** : elle est nettoyée,
  pas verbatim — 0 « euh » (Whisper 11), 60 « oui » (305), 14 « ok » (98), répétitions retirées
  (`est` +168, `on` +140). Le WER de ~43 % surestime donc l'erreur réelle face à une référence
  verbatim ; il se compare entre moteurs, pas dans l'absolu.
- **Mesure corrigée le même jour** : 4 extraits Sonal sur 21 étaient VIDES dans la référence
  (~8 min) ; ce que Whisper y entendait comptait en ajouts (1 128 mots). La lecture déclare
  désormais les plages transcrites (`covered_spans`) et l'évaluation commune ne compare que
  celles-là (`result_evaluation._restricted`, commit `04bc371d`) — #724 : 51,3 → 44,5 %.
- ⚠ #1048 a été interrompue par une relance de WAMA (14:25) : tâche perdue, card restée
  « en cours » jusqu'à sa relance à la main. Ce qui a relancé WAMA n'est pas identifié.

**Suite, même jour — l'ORDRE « nivellement → débruitage → VAD » (hypothèse de Fabien).** Sans
toucher au worker : l'audio est nivelé par la brique commune (`speech_leveling.level_file`), puis
confié à des cards du même lot (mêmes réglages, même référence).

| card | traitements (dans l'ordre) | VAD | WER | cpWER | audio retiré par le VAD |
|---|---|---|---|---|---|
| #1048 | aucun | coupé | 42,8 % | 58,3 % | 0 |
| **#1070** | **nivellement** | **coupé** | **39,6 %** | **55,6 %** | 0 |
| #1051 | nivellement | auto → resté ACTIF | 78,6 % | 85,3 % | **75 %** |
| #1050 | nivellement → débruitage | auto → resté actif | 80,7 % | 89,6 % | 62 % |

- ⭐ **Le nivellement AIDE Whisper (−3,2 points) quand le VAD ne s'en mêle pas** — les ajouts
  baissent (4 213 → 3 291). Même sens que le gain mesuré pour Qwen et Canary sur SUMM-RE.
- **Le débruitage reste destructeur même sur audio nivelé** (#1050 ≈ #725) : l'ordre ne le sauve pas.
- ⚠⚠ **Le VAD placé après le nivellement ne se comporte PAS mieux** : il retire 75 % de l'audio.
  Et le garde-fou du mode « auto » (`speech_activity.vad_rejects_speech`) l'a laissé actif, parce
  qu'il n'écoute que **3 fenêtres de 2 min** : rejoué, il donne 0,413 gardé contre un seuil de
  0,6 × 0,618 = 0,371 (non rejeté, de justesse) ; sur **12 fenêtres**, 0,371 contre 0,405 → rejeté.
  Sur l'audio d'origine il rejette nettement (0,354 contre 0,697 × 0,6). **La décision « auto »
  dépend de l'endroit où tombent 3 fenêtres** — et elle n'est écrite dans la console que quand
  elle COUPE le VAD (`workers._vad_filter_for`), jamais quand elle le garde.
- ✅ **Fait le même jour** : sonde échantillonnée selon la durée (`bd81913e`), décision « auto »
  écrite dans les deux cas (`05732b53`). Corpus du banc tranché par Fabien : **les deux**.
- Ordre dans le worker (`workers.py:486-498`) aujourd'hui : débruitage → nivellement → VAD (dans
  le moteur). Ne pas l'inverser avant le banc : sur cet entretien, c'est le VAD, pas l'ordre, qui
  décide du résultat. → voir le banc ci-dessous.

**BANC DES PRÉTRAITEMENTS (2026-09-30 → 10-01, 72 cards Whisper, commande `asr_eval_corpus`)** —
demande de Fabien : fixer l'ordre sur des audios de qualité MOYENNE, et vérifier si une
dégradation CONTRÔLÉE (`audio_degradation`, déterministe) prédit ce que donne un corpus RÉEL
(CFPP2000, 3 entretiens à domicile de 47-70 min, `manifests/datasets/cfpp.json`). Configurations :
1 rien · 2 nivellement · 3 débruitage · 4 débruitage → nivellement (ordre actuel du worker) ·
5 rien, VAD coupé · 6 nivellement, VAD coupé · 7 nivellement → débruitage (audio nivelé
d'avance, `--leveled-input`). VAD « auto » sauf 5 et 6. WER de corpus (Σ erreurs / Σ mots) :

| condition (3 enregistrements chacune) | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| **CFPP réel** | 34,4 | 30,4 | 88,7 | 87,3 | **29,3** | 29,8 | 34,8 |
| SUMM-RE champ lointain | 40,3 | **36,5** | 56,0 | 57,3 | 41,5 | 38,0 | 43,4 |
| SUMM-RE bruit 15 dB | **33,2** | 37,4 | 41,1 | 41,1 | 35,6 | 35,6 | 38,6 |
| SUMM-RE propre | **28,9** | 29,4 | 31,8 | 30,3 | 49,7 | 29,4 | 31,3 |

- ⭐⭐ **Le débruitage (DeepFilterNet) EFFACE une parole enregistrée BAS** : deux entretiens CFPP
  sont à −53/−55 dBFS de parole active (crêtes −28/−26 dBFS) ; débruités, il ne reste que 0-3 %
  de signal actif (console : « gardé 10/3 % », « 3/0 % ») → **100 % d'erreur**. Nivelés
  D'ABORD, les mêmes entretiens débruités font 32,7 et 27,0 %. L'entretien CFPP à niveau normal
  (−29 dBFS) perd moins (63 %). Le champ lointain synthétique (−45 dBFS) montre le même
  mécanisme en plus doux (56 %).
- ⭐ **Ordre** : nivellement → débruitage bat débruitage → nivellement sur **8 des 12
  enregistrements**, massivement sur les audios bas ou dégradés (CFPP 34,8 contre 87,3 ; champ
  lointain 43,4 contre 57,3), un peu moins bien sur l'audio propre (31,3 contre 30,3). L'ordre
  proposé par Fabien est donc le bon QUAND on débruite. Mais **aucune configuration avec
  débruitage ne bat le nivellement seul** : sur ces corpus, le débruitage DeepFilterNet n'apporte
  rien. ⚠ « Débruitage » = ce que fait le prétraitement du transcriber, et RIEN D'AUTRE
  (`transcriber/utils/audio_preprocessor.py:52-82` : DeepFilterNet + normalisation de crête). Ce
  n'est pas l'AMÉLIORATION de l'enhancer (remarque de Fabien, 2026-10-01) → mesurée ci-dessous.
- ⭐ **Le nivellement aide sur le réel** : CFPP 34,4 → 30,4, et sur les **3 entretiens** (−4,6 ;
  −6,0 ; −2,1). Même sens sur le champ lointain (3/3). Avec un bruit stationnaire à 15 dB il est
  mitigé (1 réunion +10,6, les 2 autres −0,2 et −1,8) ; neutre sur l'audio propre.
- **VAD coupé** : aide CFPP sur les 3 entretiens (−3,5 ; −9,6 ; −2,9) alors que la sonde « auto »
  a GARDÉ le filtre partout (il retirait 2 à 14 % de l'audio). Sur SUMM-RE, effet mitigé, et
  catastrophique sur une réunion propre (012c, 95,5 %) : le « auto » reste le bon défaut, son
  seuil ne voit que les rejets massifs.
- ⭐ **Validation de la dégradation contrôlée** : le profil `far_field` reproduit CFPP pour le
  nivellement (aide, 3/3), le débruitage (nuit) et l'ordre (nivellement d'abord sauve le
  débruiteur) ; il ne reproduit PAS l'effet du VAD. Le profil `noise_snr15` ne ressemble pas à ces
  enregistrements réels (qui sont bas et distants, pas bruités). ⇒ `far_field` peut entrer dans les
  tests d'évaluation pour les questions de niveau et de débruitage ; le VAD se juge sur du réel.
  Trois enregistrements par condition : des tendances, pas des lois.
- 🔜 **Décisions proposées à Fabien** : (a) passer l'ordre du worker à nivellement → débruitage
  quand les deux sont demandés ; (b) ne jamais débruiter un audio non nivelé (le débruitage seul
  sur un enregistrement bas rend un texte vide sans prévenir) ; (c) garder le débruitage en
  option, réservée aux fonds très bruyants — rien ne le justifie sur ces corpus.
- ⚠ Deux relances de WAMA pendant les traitements (30/09 14:25 et 20:51) ont coupé une tâche
  GPU chacune (#1048, #1118, relancées à la main) ; la file elle-même a survécu (sauvegarde
  RDB de Redis : 35 messages retrouvés).

**Suite (2026-10-01) — l'AMÉLIORATION de l'enhancer, Resemble Enhance.** Remarque de Fabien : *« À
la base c'est amélioration ou amélioration + débruitage ; le débruitage n'est qu'une option. »*
Le banc ci-dessus n'avait mesuré que le débruitage DeepFilterNet. 36 cards de plus (Whisper,
VAD auto) sur des audios améliorés d'avance par la brique de l'enhancer (`run_audio_enhancement`,
réglages par défaut de l'app : force 0,5, 64 évaluations ; `asr_eval_corpus --enhance-input`).
Sonde préalable : Resemble CONSERVE le niveau d'une parole enregistrée bas (−49 dBFS en entrée
comme en sortie), ≈ 14 × le temps réel. WER de corpus :

| condition | rien | nivellement | DFN | nivel. → DFN | **amélioration** | nivel. → amélioration | amélioration + débruitage | nivel. → amélioration + débruitage |
|---|---|---|---|---|---|---|---|---|
| CFPP réel | 34,4 | **30,4** | 88,7 | 34,8 | 51,7 | 51,4 | 73,3 | 58,7 |
| SUMM-RE champ lointain | 40,3 | **36,5** | 56,0 | 43,4 | 87,2 | 89,3 | 92,7 | 95,3 |
| SUMM-RE propre | **28,9** | 29,4 | 31,8 | 31,3 | 30,8 | 31,6 | 35,9 | 35,6 |

- ⚠⚠ **L'amélioration Resemble NUIT à l'ASR dès que l'audio est dégradé** — et plus encore avec son
  débruitage. Deux mécanismes, lus dans les sorties : (1) **DÉRIVE DE LANGUE** — sur l'audio
  amélioré, Whisper n'entend plus du français : 11 des 12 cards champ lointain sortent en tout ou
  partie en anglais, gallois, breton, danois (*« I'm Jane, you're Lester… »* sur une réunion
  française), 3 cards CFPP aussi (mode amélioration + débruitage) ; (2) **CONTENU ALTÉRÉ** — même
  détecté français, le texte boucle ou se substitue (CFPP 5 : 67,8 %, boucles *« C'est mon frère.
  C'est mon frère. »*). Le modèle GÉNÉRATIF restaure une parole qu'il ne comprend pas, et en
  change les sons. Sur l'audio PROPRE, il est à peu près neutre.
- Le nivellement préalable ne le sauve pas (contrairement au débruitage DeepFilterNet, que le
  nivellement sauvait : son défaut était le NIVEAU, celui de Resemble est le CONTENU).
- ⇒ **Le meilleur prétraitement mesuré reste le nivellement seul** (VAD « auto ») ; sur le réel,
  nivellement + VAD coupé fait aussi bien. L'amélioration de l'enhancer sert l'ÉCOUTE humaine,
  pas la transcription — à ne pas brancher en prétraitement de l'ASR.
- Non mesuré : Resemble avec la langue IMPOSÉE (isolerait l'effet acoustique de la dérive de
  langue) ; d'autres réglages de Resemble (force, évaluations).
- 🔜 Décisions (a)-(c) ci-dessus inchangées ; s'y ajoute (d) : ne pas proposer l'amélioration
  de l'enhancer comme prétraitement du transcriber.

**Suite (2026-10-01, soir) — trois moteurs de plus, exécutables, PAS encore évalués.** LinTO FR
(NeMo), FrWhisper et Kyutai STT 1B fr/en sont intégrés par les rôles (chaîne et trous :
`PROSPECTION_PIPELINE.md §Session du 2026-10-01 (soir)`), essayés sur GPU, sélectionnables
dans une card du transcriber. Trois points qui CONDITIONNENT leur lecture, à poser avant la
campagne :
- ⚠ **Biais d'entraînement de LinTO** : sa fiche cite CFPP2000 et FLEURS parmi ses données ;
  seul SUMM-RE (déclaré « exclusivement pour l'évaluation ») le mesure sans biais. Son score CFPP
  ne se compare pas aux autres ; FLEURS-CS est bâti sur la partie TEST de FLEURS — à vérifier
  avant de retenir son score multilingue.
- **FrWhisper** : horodatage grossier (souvent un segment par fenêtre de 30 s) → son WER se lit,
  son cpWER/DER pénalise d'abord ses repères de temps.
- **Kyutai** : 345 s pour 5 min d'audio (plus lent que le temps réel), une passe ≤ 300 s.
- ⚠ Une première mesure de Kyutai avait tourné sur un audio à 16 kHz pris pour du 24 kHz
  (`decode_audio` garde la fréquence native d'un WAV) — texte lisible mais faux ; corrigé par
  `decode_audio_at`, avant toute campagne.

**Campagne (2026-10-02) — MESURÉE : aucun des trois ne bat Whisper sur les réunions.** 66 cards
du compte `wama_evaluation`, dans les lots existants (même référence que les autres moteurs),
langue « Auto », VAD auto, sans débruitage ; WER moyen par enregistrement :

| moteur | SUMM-RE (3) | SUMM-RE nivelé | FLEURS-CS fr+en (8) | FLEURS-CS nivelé |
|---|---|---|---|---|
| *rappel* Whisper large-v3 | 28,8 | 29,6 | 45,1 | 37,4 |
| *rappel* Qwen3-ASR 1.7B | 30,8 | 29,6 | 35,7 | **21,1** |
| Kyutai STT 1B fr/en | 45,4 | 49,8 | 40,2 | **27,5** |
| LinTO FR | 43,7 | 43,4 | 48,3 | 47,5 |
| FrWhisper | 58,0 | 60,7 | 63,1 | 59,0 |

- **L'écart est d'OMISSION** (réunions, sans prétraitement, rapporté aux mots de la référence) :
  omis 33,8 % LinTO / 32,8 % Kyutai / 39,8 % FrWhisper, contre 20,6 % Whisper ; mal reconnus
  9,5 / 9,2 / 16,8 %, contre 6,1 %. ⚠ Agréger en filtrant le NOM de la référence emporte aussi
  les variantes dégradées (même référence) et la réunion écartée 008a — filtrer sur l'AUDIO de
  la card (`'__' not in audio`).
- **Kyutai, nivelé, est le 2ᵉ sur l'audio multilingue** (27,5 %, derrière Qwen3-ASR 21,1 %) —
  le nivellement l'aide là comme il aide Qwen3-ASR ; sur les réunions il le dessert (45 → 50 %).
- **LinTO** : mesuré d'abord à 61 % (passes de 600 s recopiées de Parakeet le 01/10) ; il est
  entraîné sur des énoncés ≤ 30 s et OMETTAIT la moitié des mots en passe longue. Passes de 30 s
  coupées dans une pause (`8f2243e`) → 43,7 %. Score SUMM-RE seul valable (CFPP/FLEURS vus).
- **Trois défauts d'INTÉGRATION trouvés par la campagne, pas par les essais** — une card isolée
  passait, la FILE tombait : (1) Kyutai après LinTO dans le même worker, « Inplace update to
  inference tensor » → génération en `inference_mode` (`341af61`) ; (2) LinTO réutilisé après
  Kyutai, « illegal memory access » qui corrompt le contexte CUDA et fait tomber TOUTE la file —
  passait avec `CUDA_LAUNCH_BLOCKING=1` (course entre flux) → décodage NeMo sans graphes CUDA
  (`8ef3557`) ; (3) le worker ne décharge pas en fin de card : les modèles de moteurs différents
  COHABITENT, ce que ni un smoke ni une card seule ne montrent — et FrWhisper comme Kyutai
  RECHARGEAIENT leur modèle à chaque card sans libérer le précédent : la mémoire s'empilait
  jusqu'au manque (19:53 et 20:18, ~19 Go alloués par PyTorch ; relevé par une autre instance,
  vérifié au journal) → `load()` réutilise un modèle déjà chargé, comme NeMo. ⭐ *Un essai par modèle ne dit
  rien d'une file de modèles différents : seule une campagne mélangée l'éprouve.*
- Non mesuré : CFPP (LinTO biaisé, et les entretiens longs coûtent ~1 h de GPU par card Kyutai).

#### ⏳ Rapports d'évaluation GÉNÉRÉS — à construire sur l'exemple de la transcription (demande de Fabien, 2026-10-03)

Le rapport « Évaluation des moteurs de transcription » a été fait À LA MAIN du 29/09 au 02/10 :
rédigé dans Claude Docs, chiffres relevés en base par des scripts de session, puis figé en page
WAMA (`/reports/transcription/`, menu « Présentations & annexes » › Rapports). La demande : que
WAMA le **génère** à chaque campagne. C'est la SORTIE LISIBLE du tableau corpus × modèles × réglages
de P4 (ci-dessus) : une case recalculée la nuit → le rapport se régénère.

**Ce qui existe et se réutilise (ne pas réécrire)** :
| brique | ce qu'elle apporte |
|---|---|
| `result_evaluation` (`ResultEvaluation`, `batch_evaluation`, configurations `config_params`) | les mesures par card, rangées par modèle et par configuration, à l'échelle d'UN lot |
| `asr_eval_corpus` (`--user wama_evaluation`, un lot par enregistrement) | la campagne elle-même ; son `--report` donne déjà un tableau texte |
| `docs_catalog.render_markdown` | Markdown → HTML neutralisé |
| `fact_tags` (`WAMA:FAIT`) | le principe : un CHIFFRE s'injecte depuis la source, il ne se recopie pas |
| `wama.views.REPORTS` + `/reports/<slug>/` | le lieu de publication : un rapport s'ajoute par sa déclaration, le menu le liste |
| `scripts/reports/` (générateur + enveloppe de la page) | la GRAINE : rendu, graphiques HTML/CSS, enveloppe |

**Ce qui a été fait à la main, et qu'il faut transformer en briques** :
1. **Agrégat d'une CAMPAGNE** (plusieurs lots) : moyenne par enregistrement, par corpus × modèle ×
   configuration, et décomposition omis / mal reconnus / ajoutés (`detail` des mesures). N'existe
   qu'à l'échelle d'un lot (`batch_evaluation`) → `campaign_evaluation(surface, lots)` dans
   `result_evaluation`, mêmes configurations. ⚠ Piège vécu : filtrer par NOM de référence emporte les
   variantes dégradées (même référence) et l'enregistrement écarté (008a) — filtrer par l'AUDIO.
2. **Rapport sans réseau** : `asr_eval_corpus --report` replanifie le corpus sur Hugging Face avant
   de lire la base (échec le 02/10, proxy en 503) → le rapport ne lit QUE la base.
3. **Graphiques** : aucune bibliothèque de graphiques n'est vendorisée ; ceux du rapport sont dessinés
   en HTML/CSS (étendue + moyenne, barres groupées, barres par condition, lisibles sur téléphone et en
   thème sombre) → une brique COMMUNE de graphiques (gabarits partiels), pas un dessin par rapport.
4. **Texte** : résumé, « quel réglage choisir », limites — écrit par Claude. Génération : par la
   chaîne LLM de WAMA, chiffres injectés mécaniquement (jamais écrits par le modèle), relecture
   humaine avant publication — même geste que « Valider » des propositions de modèle.
5. **Publication** : aujourd'hui `REPORTS` est un dict dans le code ; un rapport GÉNÉRÉ doit se déclarer
   sans éditer le code (enregistrement en base ou manifeste), daté, versionné, l'ancien gardé.
6. **Déclenchement** : à la fin d'une campagne, puis par la nocturne de P4 (cases périmées seules).

**Où vivent les rapports** : pour l'instant une catégorie « Rapports » dans le menu « Présentations &
annexes » de l'accueil (2026-10-03). Quand ils seront générés et nombreux, une page dédiée qui les
liste depuis la même déclaration (filtre par domaine, date, modèle), le menu ne gardant que les
derniers — décision à prendre à ce moment-là, pas avant.

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
