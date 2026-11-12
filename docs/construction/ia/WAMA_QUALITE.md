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
(`benchmark_sync.py`, échelles AA / Arena / Open ASR / MTEB) < **mesure interne** (~~vide aujourd'hui~~
branchée le 2026-10-14 : `model_selector._internal_values`, `model_selector.py:195`, lu en tête de
`_quality_scalars` `:283` — §4.1 / §5 ⑨ ; corrigé le 2026-10-31).
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

⭐⭐ **BANCS FIABLES DÈS LA SOURCE (2026-10-10, demande de Fabien : « compléter les sources de
benchmark et régler les problèmes dès la prospection/installation, de façon universelle et
centralisée — ensuite l'évaluation interne »).** Mesuré ce jour-là par une synchronisation à
blanc du catalogue : **27 modèles sur ~160 installés ou distants avaient un banc**. Trois trous
STRUCTURELS, tous dans `benchmark_sync` (aucun chiffre ne manquait d'abord) :
1. **la chaîne** — la synchro ne tournait qu'au bouton ou après une prospection : un modèle
   installé n'avait pas de banc. ✅ Mis en file à l'INSTALLATION (`model_installer.queue_benchmarks`,
   dans le corps unique des deux chemins d'installation), synchro chaque nuit (`benchmarks-refresh`),
   cache disque des sources (`logs/benchmarks/source_*.json`, 24 h — le quota gratuit d'AA est de
   100 requêtes par jour) ;
2. **l'identité** — l'appariement exigeait « famille + version », règle née pour les LLM : 21
   modèles média (`kokoro`, `canary-1b-v2`, `vibevoice-asr`…) étaient innommables alors que des
   sources publient le dépôt exact. ✅ Appariement par **DÉPÔT exact** (`platform_ref`, modèle canonique
   d'une quantification — `quantized_base` depuis le 2026-10-27, `hf_id` avant —, clé `huggingface:` / `proposed:hf:`) avant la famille + version, source par source — inchangée
   par ailleurs. Mesuré avant/après : **0 appariement déplacé ou perdu**, 3 gagnés (Canary,
   Parakeet sur Open ASR français ; bge-m3 d'Albert sur MTEB), innommables 21 → 8 ;
3. **les sources** — ✅ les **classements des jeux de référence OFFICIELS du Hub**
   (`/api/datasets?filter=benchmark:official`, 49 jeux ; `/api/datasets/<jeu>/leaderboard` rend
   dépôt, valeur, sens, `verified`, source) : olmOCR-Bench, MDPBench, Real5-OmniDocBench,
   ParseBench pour l'OCR ; ✅ la musique d'AA (chansons, instrumental). Total mesuré : **31**
   installés appariés (LightOnOCR-2 d'Albert, 83,2 sur olmOCR-Bench), et parmi les candidats
   GLM-OCR (75,2).
4. **la fiabilité** — ✅ chaque banc porte `provenance` (`independent` : même protocole pour tous —
   AA, Arena, Open ASR, MTEB ; `verified` ; `self_declared` : ce qu'un auteur publie) et
   `matched_by` (`alias` / `repo` / `identity`), affichés au détail du model manager. Une valeur
   auto-déclarée porte l'index seulement si aucun banc indépendant n'apparie le modèle (dernière
   priorité), et **n'a pas de rang centile** : le rang est l'étage qui compare des échelles
   différentes, il ne met pas la parole d'un auteur au niveau d'une mesure tierce.

Ce qui reste, et pourquoi :
- **aucune source tierce neutre** pour la détection, la segmentation, l'agrandissement, le
  débruitage, la synchronisation labiale, la voix (hors Elo AA) — c'est l'évaluation INTERNE
  (§3, matrice), qui reprendra le patron du transcriber (lot d'évaluation avec référence) ;
- ⚠ AA `speech-to-text` (gratuit) **non branché, mesuré** : `aa_wer_index` n'y prend que 4
  valeurs (Whisper Large v2 et v3 y valent tous deux 0) — une note qui ne distingue rien ;
- des **équivalences à confirmer par un humain** (`ALIAS`) : `ollama:glm-ocr:latest` ↔
  `zai-org/GLM-OCR` (la page Ollama ne nomme pas le dépôt d'origine), `composer:minimax-music3`
  ↔ « MiniMax Music 3.0 » ; « MusicGen » chez AA ne dit pas sa taille — jamais apparié ;
- ⚠ **identité fausse à la source** : `reader:olmocr` déclare `allenai/olmOCR-7B-0225-preview`
  (olmOCR v1, février 2025) sous le nom « olmOCR-2 7B » — le 82,4 d'olmOCR-Bench est celui de
  `allenai/olmOCR-2-7B-1025`. La mise à niveau passe par l'assistant (prospection, installation).
  ✅ *(2026-10-29, décision de Fabien)* olmOCR-2 installé par l'outil de l'assistant depuis sa
  proposition de successeur (`huggingface:allenai/olmOCR-2-7B-1025`, poids pleins BF16), servi par
  le backend olmOCR comme sa fiche le prescrit (1288 px, consigne v4 de la boîte à outils, en-tête
  YAML retiré) ; la ligne `reader:olmocr` dit désormais ce qu'elle est (v1 « preview »).
  ⚠ *Même jour, plus tard (ajouté le 2026-10-31)* : la v1 est RETIRÉE (`REMOVAL_LEDGER R190`,
  succession `supersede_model`) — `reader:olmocr` n'est plus une ligne active, son identifiant est
  redirigé vers olmOCR-2 (`reader/utils/model_config.py:69-71`, `RETIRED_IDS`).
  ⚠ Il n'a AUCUNE note : le classement officiel d'olmOCR-Bench sur le Hub ne liste aucun olmOCR, son
  82,3 n'est que sur sa fiche — le tirage ne le retient donc pas (choix manuel possible). Le remède
  est la mesure interne ; une note déclarée depuis une fiche serait un mécanisme neuf (décision).
- ⚠ **couverture partielle d'un lot** : un étage se juge sur le sous-ensemble couvert (règle du
  26/09), donc un SEUL modèle noté passe devant les autres à tout curseur — c'est ce qui fait
  tirer GLM-OCR (seul porteur d'un a priori structurel) au reader, qualité max comprise.
  Compléter les sources réduit ce cas ; il ne l'annule pas.
  📏 **Mesuré le 2026-10-29** (question de Fabien : « olm-ocr n'est jamais prévu, toujours
  glm-ocr »), tirage réel du compte de Fabien, budget fixé, curseur 0 / 50 / 100 — le curseur est
  INERTE dans cinq apps, un seul modèle du lot portant un banc tiers :
  reader → glm-ocr (75,2 sur olmOCR-Bench, seul noté ; chandra-ocr-2 installé n'a pas hérité du
  85,8 de son modèle d'origine — sa ligne n'a pas de `quantized_base`, alors que la carte du dépôt
  GGUF déclare `base_model:quantized:datalab-to/chandra-ocr-2` ; olmOCR n'a aucune note et sa
  fiche est encore la v1 « preview » — *v1 retirée le même jour, R190, cf. ci-dessus*) ; transcriber et describer → whisper (seul noté, et c'est
  aussi le meilleur MESURÉ sur entretiens) ; composer → minimax-music3 (banc AA par `ALIAS` depuis
  le 10/10 : il écrase les a priori déclarés — **régression** du constat du 03/10 plus bas,
  « rapide → MusicGen Small, qualité → YuE2 ») ; enhancer → 4xNomosUni. Vivant : synthesizer,
  avatarizer, imager, anonymizer.
  ⚠ Écrire « un étage ne classe que s'il compare au moins deux modèles » a été ESSAYÉ ce jour et
  retiré sans commit : le tirage retombait sur la TAILLE (FrWhisper, 7,4 Go et aucune note, devant
  Whisper). Le remède est la **mesure interne sur corpus** (§4.1, catégorisée §4.4 — l'OCR
  imprimé et manuscrit ne se comparent pas ensemble), Fabien le rappelle : *« une mesure réelle
  sur un corpus est nécessaire pour un tirage automatique de qualité »*.
  ✅ **Le même jour, l'héritage des versions QUANTISÉES** (décision de Fabien : *« il faut bien
  faire hériter la note aux versions quantisées, mais garder la précision qu'ils sont quantisés
  au tirage »*). L'héritage existait (`quantized_base`, appariement par dépôt depuis le 27/10) ;
  le LIEN n'était posé que si l'installation le recevait de la prospection. Désormais
  `provenance.huggingface_identity` le lit sur la carte (étiquette `base_model:quantized:`), avec
  la reprise sur 429 de la prospection, et ne le retient que si le dépôt porte le NOM COMPLET du
  modèle d'origine (`prospector.names_the_same_model`, le filtre strict des variantes) — le Hub
  déduit `quantized` des fichiers et nommait le socle d'un affinage (`Qwen3-Embedding-4B-GGUF` →
  `Qwen3-4B-Base`, `olmOCR-2-7B-1025-FP8` → `Qwen2.5-VL-7B-Instruct`). 17 lignes reliées par
  `set_identity` (passage à blanc relu avant), `sync_benchmarks` : chandra-ocr-2 Q6_K hérite du
  85,8. La PRÉCISION (`AIModel.quantization`, relevée par la synchronisation d'Ollama qui la lisait
  déjà pour l'a priori) est dite dans la prévision : « Prévu : … · Q6_K (4.8 Go) ». Remesuré :
  reader → glm-ocr (F16) au curseur 0, chandra-ocr-2 (Q6_K) à 50 et 100. Composer, transcriber
  inchangés.
  ✅ **Le même jour, les TABLEAUX OFFICIELS comme sources de bancs** (décision de Fabien : *« pour 2,
  les tableaux officiels »*) — `benchmark_sync` lit le classement français de Linagora et des
  tableaux d'auteurs déclarés et figés à un commit (`PROSPECTION_PIPELINE §Session du 2026-10-29`
  point 5). 30 notes neuves : olmOCR-2 a son 82,3 sur l'échelle d'olmOCR-Bench (le « mécanisme
  neuf » attendu plus haut est celui-là), Kyutai et LinTO un WER français, 27 YOLO leurs scores
  COCO/ImageNet/DOTA. olmOCR v1 est RETIRÉ, olmOCR-2 lui succède (`succession.py`, R190).
  Remesuré : reader → glm-ocr à 0 et 25, chandra-ocr-2 de 50 à 100 (olmOCR-2 classé derrière,
  82,3 contre 85,8, et plus lourd). Transcriber → whisper à tous les crans : ce n'est plus « le
  seul noté », c'est sa PRIORITÉ déclarée (`options_resolution`, whisper → vibevoice → qwen), tirée
  de la mesure sur entretiens — les notes ne la remplacent pas, et c'est voulu.

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
unique** → **valeur sur une échelle COMMUNE** (ajouté le 2026-10-30, décision de Fabien : des
porteurs différents, mais une échelle que tout le lot mesuré porte aussi — l'Arena derrière un
porteur AA ; la synchro écrit toutes les échelles d'un modèle, `benchmark_meta['scales']`, lues par
`benchmark_sync.common_scale_values`) → **rang centile (inter-échelles)** → a priori → VRAM (local
seulement). Le rang vient
APRÈS la valeur brute, jamais avant : à échelle unique, le score exact dit plus que le rang. Il
ne perd personne au passage (il est écrit en même temps que `benchmark_index`, donc il couvre
le même sous-ensemble). ⚠ Ses deux réserves restent entières et se redisent partout où il
sert : il est **ordinal**, et il dépend de la **population de son banc**.
⭐ **Et chaque modèle s'y lit dans la population la PLUS PARTAGÉE du lot (2026-11-06, demande de
Fabien)** — l'étage lisait le seul rang du PORTEUR. Mesuré ce jour sur le tirage de l'assistant :
douze modèles notés comparaient trois populations, AA v5 (93 modèles, surtout frontière : Gemma 4
31B au 2,2ᵉ centile), AA v4 périmé (570) et l'Arena (302 : DeepSeek V4 Flash au 72,2ᵉ), alors que
l'Arena en notait huit et classait Gemma (1 443) devant DeepSeek (1 432) — le tirage retenait
DeepSeek. La synchro écrit désormais le rang de CHAQUE échelle indépendante (`scales[*]
.percentile_rank`, dans la population de sa source) ; `benchmark_sync.shared_percentile_values`
lit pour chacun le rang de l'échelle qui note le plus de modèles du lot (à égalité, la priorité des
sources), le rang du porteur pour une ligne synchronisée avant. C'est la règle de l'échelle
commune prolongée au sous-ensemble qu'une échelle couvre : deux modèles notés sur une même échelle
s'y comparent dans la même population, donc dans l'ordre de leurs valeurs ; le rang ne fait le
pont qu'avec ceux qu'elle ne note pas. Après la synchro réelle : Gemma 79,5 (Arena), DeepSeek 72,2,
le tirage revient à `albert:gemma-4-31b-it`. Gardes : `tests_signal_scale_subset.SharedPopulationRankTest`.
⏳ Reste vu au passage : le sous-indice `coding` (tirage de développement) n'est plus porté que
par des notes AA v4 PÉRIMÉES — AA v5 ne publie pas cette famille (`legal`, `engineering`…), donc
`ilaas:qwen-3.6-35b-instruct` (v4, 41,9) l'emporte sur une note qu'aucune source ne confirme plus.
✅ **Soldé pour le sous-indice le 2026-11-08** (question de Fabien : « pourquoi ce n'est pas qwen3.8
ou gemma 31b qui sont appelés ? Il faut utiliser les meilleurs modèles disponibles pour le codegen
et l'écriture des backends »). Mesuré sur son compte : deux candidats au niveau développement
(qwen-3.6, périmée depuis le 02/11, et gpt-oss par déclaration), qwen3.8 27B et gemma-4-31b dehors
faute de `coding` — AA v5 ne publie plus cette famille (`logs/benchmarks/source_aa.json` : 94
entrées, aucune `coding`). Deux corrections : l'étage du sous-indice ne lit plus une note PÉRIMÉE
(`model_selector._quality_scalars`) — il ne classe que ceux qu'il couvre, donc une note périmée
seule y excluait toutes les mesures fraîches ; et le plancher de développement lit, sans score
coding frais, le rang centile de l'échelle la plus partagée du lot (`development_models.
DEV_RANK_FLOOR` = 55, étalonné sur les modèles que le plancher coding jugeait : même verdict sur
chacun). Le tirage passe de qwen-3.6 à gemma-4-31b (79,5ᵉ centile Arena), devant qwen3.8 (75,5ᵉ)
et DeepSeek V4 Flash (72,2ᵉ). Gardes : `tests_development_models.DevelopmentLevelReadsALivingMeasureTest`.
⚠ Une note périmée garde sa place aux étages inter-échelles (décision du 02/11) : la question du
2026-11-07 ci-dessous reste ouverte pour eux.
📏 **Remesuré le 2026-11-08 au soir** (revérification demandée par Fabien) : sur les lots INSTALLÉS
de chaque type, plus aucune note périmée ne passe devant une note fraîche — `llm` : qwen3.8 (75,5ᵉ,
Arena) puis les trois notes v4 périmées (50,2 / 47,0 / 33,3) ; `diffusion` : SDXL et SD 1.5,
périmés, derniers. La question du 07/11 n'a donc plus de cas ; la décision du 02/11 (gardée,
marquée, comparée) tient telle quelle.
⚠ **Défaut du 08/11 vu le 2026-11-09, corrigé** (rôle `backend` d'ACE-Step, Albert injoignable) :
le relais a tiré `ilaas:qwen-3.6-35b-instruct`, et non gemma-4-31b chez ILaaS. Deux causes, mesurées
sur le compte de Fabien : ① le RANG d'admission se lisait sur le lot DISPONIBLE — sans Albert,
l'échelle la plus partagée basculait de l'Arena vers AA v5 et il ne restait qu'UN candidat
(qwen-3.6), le qwen3.8 LOCAL compris était sorti ; ② à couverture ÉGALE (lot ILaaS : AA v5 et
l'Arena notent chacune gemma et qwen-3.8), la priorité des sources donnait AA v5 — 94 modèles,
surtout frontière : gemma au 2,1ᵉ centile, qwen-3.8 au 23,4ᵉ — et le 58,1ᵉ d'une note AA v4
périmée (570) passait devant. Corrigé : le rang se lit sur tout ce que le compte PEUT lancer, la
panne n'écartant qu'au tirage (`development_models.development_candidates`,
`allowed_cloud_keys(available_only=False)`) ; à couverture égale, la population la plus LARGE
départage (`benchmark_sync.shared_percentile_values`). Remesuré : Albert en panne, quatre candidats
(gemma, qwen-3.6, qwen-3.8 chez ILaaS, qwen3.8 local), tirage `ilaas:gemma-4-31b` ; Albert là,
`albert:gemma-4-31b-it`. Gardes : `tests_development_models.AnOutageDoesNotChangeTheRankTest`,
`tests_signal_scale_subset.SharedPopulationRankTest.test_at_equal_coverage_the_larger_population_wins`.
✅ **2026-11-07** — `AIModel.best_installed` (le référentiel « concurrence » de la prospection) se
disait « même règle d'étage que la sélection » et n'en recopiait que trois étages : ni rang centile
(absent depuis son branchement du 26/09), ni mesure interne, ni repli VRAM. Il LIT désormais
`_quality_scalars` (gardes `tests_signal_scale_subset.BestInstalledReadsTheSelectorLadderTest`).
Mesuré sur le catalogue : `llm` passe de qwen3.8, gemma4:12b, translategemma à gemma4:12b,
qwen3.5:4b, gemma4:e4b — le même défaut que le tirage local, désormais vu aussi par la prospection
(une note v4 PÉRIMÉE au 50ᵉ centile de 570 modèles passe devant une note v5 fraîche au 17ᵉ de 93) :
⏳ décision de Fabien en attente (les notes périmées dans les tirages, 2026-11-07). `diffusion`,
`speech`, `vision`, `ocr` changent aussi d'ordre ; `vlm`, `embedding`, `audio` non.
📏 **Ce ⏳ n'a plus de cas — remesuré le 2026-11-10** (demande de Fabien : « vérifie si 51de73718
couvre D1 »). D1, posée le 07/11, demandait si une note périmée peut décider d'un tirage ; deux
réponses proposées : **A** lire les catégories de l'Arena (`coding`, `french`, `math`… — le parquet
les porte, la synchro ne lit que `overall`) comme sous-indices frais ; **B** une note périmée ne
passe jamais devant une note fraîche. Ce qui l'a soldée, sans A ni B : `51de73718` (08/11, l'étage
du sous-indice ignore une note périmée — le tirage de développement) et `018dfc734` (09/11, à
couverture égale la population la plus large départage — qwen3.8 se lit sur l'Arena, 302 modèles,
et non plus sur AA v5, 94). Mesuré en lecture seule sur le catalogue : `llm` installés locaux —
qwen3.8 75,2 (Arena, frais) puis gemma4:12b 50,2, qwen3.5:4b 47,0, gemma4:e4b 33,3 (AA v4,
périmés), translategemma sans note ; `best_installed('llm')` dans le même ordre ; `select_model
(model_type='llm')` → qwen3.8 au curseur qualité (100), qwen3.5:4b à 15 et à 50 (le curseur
arbitre la taille, pas la note). ⏳ **Ce qui reste, sans urgence et à Fabien** : B n'est pas une
RÈGLE — aucune note périmée ne passe devant une fraîche aujourd'hui parce que les valeurs le
donnent, pas parce que l'étage l'interdit (décision du 02/11 : gardée, marquée, comparée) ; et A
rendrait au sous-indice `coding` une mesure fraîche, ce qui demande d'abord que l'étage du
sous-indice vérifie l'échelle de CHAQUE note (il ne regarde que l'échelle du porteur).
Le rang du porteur, lui, n'est plus écrit qu'une fois : c'est l'entrée de sa propre échelle.

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
  ✅ **Branchés le 2026-10-10** (musique seulement — `speech-to-text` mesuré non discriminant,
  cf. §0) : 13 modèles en chanté, 19 en instrumental ; YuE2 et ACE-Step n'y sont pas,
  « MusicGen » sans taille ne s'apparie à aucune variante, MiniMax Music 3.0 attend un `ALIAS`
  confirmé — les valeurs déclarées ci-dessous restent donc l'étage qui classe la musique ;
  ⚠ **faux le jour même, corrigé le 2026-11-10** : l'`ALIAS` confirmé (`966bd5f0b`, 10/10) a donné
  à MiniMax Music 3 une note AA (1 000, `aa_elo_music_with_vocals`) ; seul noté du lot, il prenait
  l'étage benchmark et les valeurs déclarées n'étaient plus lues — « Un étage classe s'il
  COMPARE », plus bas ;
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

🔧 **Un étage classe s'il COMPARE — régression du Composer réparée le 2026-11-10** (vue en
mesurant les trous de notation ; Fabien : *« Il ne faut rien casser du tirage des modèles du
composer. Ou si quelque chose est cassé, il faut le réparer. On ne laisse pas un tel piège en
suspens »*). Du 10/10 au 10/11, le tirage `text-to-music` rendait MiniMax Music 3 (13 Go) dès que
le curseur passait 80 (le budget cesse de borner) et à TOUTES les positions quand 13 Go étaient
libres : seul porteur d'une note de banc, il était seul classé, et le curseur ne choisit que parmi
les classés (`_best_by_vram`, `rankable`). Règle posée, celle de la mesure interne — « au moins
DEUX, sinon le seul mesuré gagnerait par défaut » (`model_selector._internal_values`) —, étendue à
chaque étage de qualité de `_quality_scalars` : un étage qui ne note qu'un modèle cède la place au
premier étage inférieur qui compare ; si aucun ne compare, il la garde (un modèle noté passe encore
devant un modèle que rien ne note) ; la VRAM n'est pas un étage de qualité. Mesuré avant/après sur
le catalogue, en lecture seule (1 395 tirages : chaque tâche, local / distant / les deux, cinq
positions, trois budgets, `coding` pour `llm` et `vlm`) : **24 changent, tous `text-to-music`** —
rapide → MusicGen Small, équilibré et qualité → YuE2, le comportement mesuré le 03/10. Tirage réel
du Composer (`resolve_auto_model`, VRAM libre du moment) : qualité 85 et 100 → YuE2 au lieu de
MiniMax, chanté compris ; 0 à 50 inchangés. Gardes : `tests_signal_scale_subset.
AStageRanksOnlyIfItComparesTest` ; le test qui disait « le sous-indice gagne dès qu'il couvre
quelqu'un » dit désormais « dès qu'il compare ».

⏳ **TROUS DE NOTATION, TROUS DE SÉLECTION — question ouverte de Fabien (2026-11-10), pour une
session neuve et le concile** (Q10, §8). *« Peut-on compléter les notes des modèles ? Mais le souci
de modèles sans notation reviendra forcément à mon avis. Donc il faut à la fois gérer les trous de
sélection et les trous de notation pour que le curseur ait une réponse honnête et alignée sur la
demande de l'utilisateur, sans omettre de modèle. »*
- **Ce que fait le code** (lu le 2026-11-10) : le curseur ne choisit que parmi les modèles qu'un
  étage note (`_best_by_vram` : `rankable = [m for m in pool if id(m) in values] or pool`) ; le tri
  les met derniers (`_rank_key`, `-inf`) ; rien ne dit à l'utilisateur qu'un modèle a été écarté
  faute de note. Un modèle sans note n'est donc jamais tiré quand un autre en a une — même au
  curseur rapide, où il serait le plus léger.
- **Relevé du catalogue** (lecture seule, par catégorie — un tirage réel filtre encore par tâche) :
  `llm` distants, 353 sans valeur sur 508 ; `llm` locaux installés, 1 sur 5 (translategemma) ;
  `diffusion` 9 sur 13 ; `speech` 15 sur 23 ; `upscaling` 4 sur 10 ; `vision` 30 sur 73 (lot classé à
  la VRAM). Lot `transcription` installé : 9 candidats, 6 classés — `linto_stt_fr_fastconformer_pc`
  porte une note Linagora (WER 12,96, meilleure que les 19,03 de kyutai, classé) mais aucun rang
  centile, et n'entre pas au classement (cause à établir : la valeur de l'auteur du banc,
  `LINAGORA_OWN_PREFIX`, ne reçoit pas de rang).
- **Deux trous, deux réponses à construire** : la **notation** — compléter (lignes OpenRouter à
  l'identité collée, ~69 gagnables, `PROSPECTION_PIPELINE` ; tableaux officiels des auteurs,
  `benchmark_sync` du 2026-10-29 ; a priori déclarés par tâche, `DECLARED_PRIORS` ; mesure interne),
  sachant que chaque prospection amène des modèles neufs sans note : le trou reviendra ; la
  **sélection** — ce que le curseur fait d'un modèle sans note : l'écarter (aujourd'hui), le placer
  à une valeur neutre, l'essayer pour le mesurer, et dans tous les cas le DIRE (l'étage qui a classé
  et les modèles écartés, rendus avec le choix).
- **Ce qui borne toute réponse** : on ne mélange jamais deux échelles, et « inconnu » n'est pas
  « mauvais » (`model_selector._rank_key`, docstring) ; un étage classe s'il compare (ci-dessus).
  Rien d'implémenté.

📜 **AVIS DU 2026-11-12 ET DÉCISIONS DE FABIEN** (session neuve, Opus 5.5 ; avis du concile à la
suite). Rien d'implémenté. Tout passe par le COMMUN — le sélecteur (`_quality_scalars`,
`intent_choice`, lus par toutes les apps et par `best_installed`), les méthodes M4/M8/M9, les
déclarations par tâche — et rien par une app : *« Ce que je ne veux pas, c'est un désalignement,
des pansements, ou des spécificités dans une app »* (Fabien). Une spécificité de modèle qui
apparaît en l'évaluant entre dans le commun.
- **Cas de départ : les effets sonores du Composer** (`text-to-audio`, `composer/utils/auto_model.py:46`).
  Aujourd'hui le lot n'a qu'un modèle (`composer:audiogen-medium`), sans banc ni a priori
  (`DECLARED_PRIORS` ne couvre que la musique) : curseur inerte par construction — un trou du
  catalogue, pas encore Q10. Avec les candidats de la veille du 11/11 (Stable Audio 3 Small-SFX
  et Medium, MOSS-SoundEffect v2, `PROSPECTION_PIPELINE §Veille 2026-11-11`), la seule note
  serait la table AUTO-DÉCLARÉE du rapport de Stable Audio 3 (FAD et CLAP sur des clips BBC de
  5 s : deux échelles) ; si elle note les deux Stable Audio 3, l'étage compare, et
  `rankable = [m for m in pool if id(m) in values] or pool` (`model_selector.py:491`) écarte
  AudioGen et MOSS à TOUTES les positions, curseur 0 compris — où la qualité ne pèse rien.
- **① SÉLECTION — borner l'inconnu, jamais lui inventer une valeur.** Hypothèse unique, dite
  telle quelle : un modèle sans note n'est ni meilleur que le meilleur mesuré du lot, ni pire que
  le pire. Avec `S = w·q + (1−w)(1−c)`, son score est l'intervalle `[(1−w)(1−c), w + (1−w)(1−c)]`,
  de largeur exactement `w` : *l'ignorance pèse le poids que l'utilisateur donne à la qualité.*
  Trois verdicts, aucun ne mélange deux échelles : **battu même au mieux** → écarté, dit ;
  **gagnant même au pire** → tiré, dit (c'est ce qui rend « rapide » honnête) ; **indéterminé** →
  PRUDENCE. Les relations d'ordre sans valeur resserrent les bornes sans placer le modèle :
  une quantisation ≤ son modèle d'origine (déjà écrit pour MiniMax, « borne haute »,
  `model_quality.py:122-123`), « Small ≤ Medium » déclaré par un auteur. Les modèles d'un étage
  INFÉRIEUR sont « inconnus » sur l'échelle de l'étage retenu, même règle. Chaque choix rend
  l'étage qui a classé, son échelle, sa population, les modèles non comparés et pourquoi.
  ✅ **Fabien : d'accord sur l'hypothèse** (le concile la confirme ou la borne autrement).
- **② Indéterminé → PRUDENCE, sans interface de plus** (décision de Fabien) : le meilleur modèle
  noté ; le modèle prévu est affiché, l'utilisateur choisit lui-même un modèle non noté s'il le
  veut. Les descriptions courtes et longues portent les notes pertinentes pour ce choix manuel —
  **CALCULÉES à l'affichage** depuis `benchmark_meta` et les mesures internes, avec échelle et
  population, dans l'aide commune des modèles (`WamaModelHelp`, `common/js/wama-model-help.js` :
  court sous le sélecteur, long en ⓘ) ; jamais recopiées dans `description_long` (un
  chiffre ne vit qu'à un endroit ; `describe_model`, `model_selector.py:1077-1085`, ne rend
  aujourd'hui que le texte).
- **③ NOTATION — le trou ne se supprime pas, il se borne dans le temps** : un modèle sans note est
  un ÉTAT daté (« à mesurer depuis… »). Ordre, du gratuit au coûteux : identité et héritage
  (`quantized_base`, alias) ; bancs tiers et tableaux officiels dès l'installation
  (`queue_benchmarks`) ; table d'auteur dans sa seule population ; **mesure d'entrée** — qui n'est
  pas un mécanisme neuf : c'est **P4 précisé** (§9, 2026-09-30 : tableau corpus × modèles ×
  réglages, cases PÉRIMÉES à l'arrivée d'un modèle, la nuit ne recalcule qu'elles), freiné par la
  décision du 28/09 (« à la demande seulement »). **Priorité de mesure** = les modèles en verdict
  « indéterminé » sur des tirages réels : ceux dont la mesure changerait une décision — le trou de
  sélection ordonne le comblement du trou de notation.
  ⚠ **Inquiétude de Fabien : la pertinence des corpus** (*« on risque d'introduire des notations
  imprécises »*). Bornes proposées : (a) une note ne vaut que dans sa population, jamais mélangée ;
  (b) un corpus n'est admis que DÉCLARÉ (`dataset`, Q1), avec sa catégorie (§4.4) et sa source de
  vérité (§1), et si possible confronté une fois à un verdict humain ; (c) le corpus le plus
  pertinent est l'USAGE de WAMA — corrections des utilisateurs comme références (déjà captées par
  le transcriber), jeu FIGÉ de prompts tirés de demandes réelles pour la génération ; (d) une
  tâche sans corpus admis n'a pas de mesure d'entrée, et le sélecteur le dit.
- **④ DEUX ÉCHELLES D'UNE TÂCHE — dissociées, jamais additionnées** (Fabien : *« on fait les 2 avec
  des scores dissociés qui rentrent dans le calcul s'ils existent »*). Aujourd'hui
  `_internal_values` s'abstient devant deux échelles comparables (`model_selector.py:225-226`) ;
  il faut donc une DÉCLARATION PAR TÂCHE, dans le commun, de l'échelle PRINCIPALE ; la seconde ne
  joue que par dominance (meilleur sur les deux → devant ; sinon la principale tranche). Effets
  sonores : **CLAP** principal (modèle entraîné sur des sons et leurs descriptions — le score dit
  si le son correspond au prompt, sans référence ; par fenêtres glissantes pour « l'instant où
  c'est demandé » ; M4, à calibrer contre l'humain), **FAD** seulement là où existe une référence
  réelle de la catégorie (compare un ENSEMBLE de sons générés à un ensemble de vrais sons ; ne juge
  pas un clip ; plus bas = mieux). ⚠ Une M4 « n'entre jamais dans `ResultEvaluation` » (M4 plus
  bas) : pour classer des modèles, CLAP doit tourner sur un jeu de prompts FIGÉ qui fait la
  population (`reference_set`) — décision.
- **⑤ Étoiles des utilisateurs → M8**, **répétabilité et reproductibilité → M9** (détail en §2).
- ⏳ **Question consignée pour plus tard, rien à faire — musique et paysages sonores** (Fabien) :
  plus la composition musicale se spécialise (partitions, paroles, covers), plus ses réglages
  divergent de ceux des ambiances ; *« en faire 2 domaines n'est pas envisageable, il s'agirait
  plutôt de 2 modes »* — peut-être un faux problème. ⚠ À rapprocher le jour venu de la décision
  écrite `composer/utils/model_choice.py:13-14` (« un auto par groupe, groupé côté serveur, pas de
  2 modes ») : le type musique/bruitage s'y DÉRIVE de la tâche du modèle ; ce « pas de 2 modes »
  visait un sélecteur de type à l'écran, pas le sens de « mode » de la doctrine domaines/modes.
- ⏳ **Publication, à terme** (Fabien) : quand la notation sera éprouvée sur assez de modèles,
  publier résultats et rapports d'évaluation — site web de WAMA qui présente la plateforme et
  compile ce qu'elle a appris. Intention portée par `WAMA_VISION_COMPLET §10.4` et
  `ROADMAP §30` ; les rapports générés existent déjà (§9bis, « Rapports d'évaluation GÉNÉRÉS »).

📜 **AVIS DU CONCILE DE WAMA (2026-11-12) — et sa lecture.** Dossier autonome (le problème, les
règles, A à E ci-dessus, sept questions), lancé par la délégation de l'assistant
(`assistant_engine._delegate_wave`, quatre agents `methodology` / `critique` / `dev` /
`methodology`, `decide: review`) : 366 s, parent Albert `gemma-4-31b-it`, avis d'Albert
gemma-4-31b, ILaaS gemma-4-31b, ILaaS qwen-3.8-27b (seul à avoir utilisé ses outils), Albert
deepseek-v4-flash, arbitre ILaaS qwen-3.6-35b. Verdict unanime : **« proposition correcte avec
corrections »**. ⚠ Un avis, pas une mesure : les agents n'ont pas lu le code — chaque point est
confronté ci-dessous. Rien d'implémenté ; les ✅ sont des corrections RETENUES dans la proposition,
pas des décisions de Fabien.

| point du concile | lecture |
|---|---|
| borner l'inconnu par l'étendue du LOT crée un biais local : un lot faible plafonne un excellent inconnu ; borner par la POPULATION du banc ne mélange pas les échelles (c'est elle qui DÉFINIT l'échelle) | ✅ **retenu** : la borne est l'étendue de la population de l'échelle retenue quand elle est connue (bancs tiers : cache des sources ; rang centile : 0-100 par construction), celle du lot sinon (a priori déclarés, mesure interne). L'intervalle s'élargit, donc plus d'« indéterminés » et plus de prudence — conforme au choix de Fabien. Pire cas restant, dit : un modèle hors de toute étendue connue |
| exiger ≥ 2 modèles notés pour appliquer l'hypothèse (correction « prioritaire » de l'arbitre) | ✅ déjà la règle « un étage classe s'il COMPARE » (`model_selector.py:308-314`) ; avec un seul noté l'étendue est un point, tout inconnu est indéterminé → prudence, le comportement d'aujourd'hui |
| ⭐ verdict « gagnant même au pire » seulement si le COÛT est MESURÉ (vitesse apprise sur cette machine, VRAM mesurée), sinon indéterminé | ✅ **retenu, point le plus utile** : le verdict repose ENTIÈREMENT sur le coût, et la provenance de la VRAM est déjà portée (`vram_provenance` : `declared` / `estimated` / `heuristic`…, `model_registry.py:350`) ; la vitesse apprise ne joue que si tout le lot en a une (`eta_estimator.comparable_speeds`). C'est la garde « pas mesuré n'est pas gratuit » (02/09) appliquée à la borne basse |
| un seuil de qualité minimal `q_min` contre les modèles « gratuits mais inutilisables » | ❌ **écarté** : une valeur inventée sur l'échelle. Le « cassé » se juge à l'ADMISSION — sans backend (`backend_missing`), défaut mesuré (`quality.defect`, `model_quality.py:150-160`) —, pas par la qualité |
| le verdict (2) tire SYSTÉMATIQUEMENT l'inconnu au curseur 0 et perpétue le trou | ❌ **faux**, corrigé par l'arbitre lui-même : à w = 0 l'intervalle est un point, l'inconnu n'est tiré que s'il est réellement le moins coûteux |
| boucle de rétroaction : un modèle jamais tiré n'est jamais « indéterminé », donc jamais mesuré → tirage forcé d'un inconnu 1 fois sur 10 | ❌ **le constat est faux et le remède écarté** : le verdict se calcule sur CHAQUE tirage, pour tout le lot, quel que soit le modèle retenu ; au curseur haut l'intervalle est large, c'est là que les inconnus sont indéterminés. Un tirage forcé serait une exploration sur le travail d'un utilisateur, à son insu (refusée : prudence) |
| ⭐ mesure d'entrée : un EFFECTIF minimal et une INCERTITUDE déclarée, sinon l'étage interne est plus bruité que le banc qu'il supplante | ✅ **retenu, sans N figé** (le concile proposait ≥ 30 items) : chaque note interne porte son intervalle de confiance (bootstrap sur les items), et la même logique d'intervalles s'y applique — deux modèles dont les intervalles se chevauchent sont INDÉTERMINÉS l'un par rapport à l'autre. C'est le « N passes non fixé » de Q3 enfin chiffré par la mesure elle-même, et « accumulation avant confiance » (§4.1) rendu mécanique |
| péremption du CORPUS lui-même (l'usage dérive) | ✅ retenu : un corpus porte sa date et sa catégorie, se revalide ; P4 rend déjà ses cases PÉRIMÉES quand le corpus change (§9) — ce qui manquait est la date de revalidation |
| la seconde échelle en FILTRE d'exclusion (seuil déclaré par tâche) plutôt que par dominance, trop rarement décisive | ✅ **tranché par Fabien le 2026-11-12 : dominance par défaut**, un seuil (EXIGENCE déclarée par tâche, comme une capacité) seulement quand il se justifie. La dominance ne demande aucun nombre |
| étoiles : randomiser l'ordre de présentation des deux sorties ; effectif minimal par paire ; plafonner le poids d'une personne très active ; agréger les duels de personnes DIFFÉRENTES (un avis voulait l'interdire, l'arbitre l'a contredit) | ✅ retenu (le duel est intra-personne, l'agrégat inter-personnes, c'est ce que propose M8) ; l'effectif se lit à l'intervalle, comme ci-dessus |
| répétabilité / reproductibilité : terminologie exacte, dispersions bien séparées ; mesurer AUSSI leur rapport (la sensibilité de la métrique : un CLAP stable sur des sorties qui varient, et l'inverse) ; pilote sur trois modèles avant de généraliser | ✅ retenu (M9). Références citées par les agents, **non vérifiées ici** : « Quantifying Variance in Evaluation Benchmarks » (arXiv 2406.10229), « The Silent Hyperparameter » (CISPA, 2026, effet du moteur d'inférence), la sensibilité du FID à la taille d'échantillon (attribuée à Heusel et al. 2017 — à confirmer, Chong & Forsyth 2020 la traite) |
| ⭐ la mesure d'entrée peut saturer la carte de 24 Go la nuit et retarder les tâches du matin : budget GPU dédié, priorité basse, créneau | ✅ juste, et déjà borné en partie : priorités nommées du worker `gpu`, gouverneur de ressources, Q7 (la nocturne comparative visait le R760xa), décision du 28/09 « à la demande seulement ». À dire dans P4 : la mesure d'entrée est la priorité la plus BASSE, dans un créneau déclaré |
| une quantisation peut casser une capacité précise sans baisser le score global | ✅ noté : « quantisée ≤ origine » reste une borne HAUTE valide, elle ne dit rien d'une capacité ; la population (catégorie) s'applique aussi aux variantes |
| à curseur 0 et coûts égaux, aucun départage défini | ✅ existe : epsilon de qualité, puis ordre du catalogue (`intent_choice`, `model_selector.py:547`) |

**Précisions du 2026-11-12 (questions de Fabien, après le concile).**
- **Pas deux échelles : N, en trois familles.** QUALITÉ — bancs tiers (Elo, indices AA, WER
  Open ASR, MTEB, olmOCR-Bench…), a priori, mesures internes par tâche (CLAP, FAD, WER, LPIPS…),
  plus tard la note des utilisateurs (M8) : elles CLASSENT, chacune dans sa population, jamais
  additionnées ; COÛT — VRAM, vitesse apprise : l'autre axe du curseur ; CARACTÉRISATION —
  répétabilité, reproductibilité (M9) : elles ne classent JAMAIS. La règle « principale +
  dominance » vaut pour N échelles de qualité d'une tâche : une PRINCIPALE déclarée ; un modèle
  passe devant s'il est au moins aussi bon sur toutes les autres et meilleur sur l'une ; sinon la
  principale tranche. La note des utilisateurs est une échelle de qualité de plus — sa place
  (avec les mesures internes ; principale d'une tâche subjective une fois remplie ?) reste
  ouverte jusqu'à M8. La RÉPLICABILITÉ (ACM : une autre équipe, ses propres moyens) n'est pas une
  note de modèle : elle vaudra pour nos mesures PUBLIÉES (`WAMA_VISION_COMPLET §10.4`).
- **L'intervalle de confiance n'est pas l'écart-type.** L'écart-type dit à quel point les items
  diffèrent, il ne baisse pas avec leur nombre ; l'incertitude de la note baisse avec lui
  (erreur type σ/√n, ≈ note ± 1,96·σ/√n à 95 %, Student si n est petit). **Méthode proposée : le
  BOOTSTRAP** (rééchantillonner les items avec remise ~1 000 fois, recalculer la métrique,
  percentiles 2,5 / 97,5), parce que plusieurs métriques ne sont pas des moyennes d'items (WER de
  corpus = erreurs totales / mots totaux ; FAD = statistique d'ensemble, sans valeur par item).
  Pour COMPARER deux modèles mesurés sur les mêmes références (la règle de population le
  garantit) : bootstrap APPARIÉ de la différence item par item — plus sensible que « intervalles
  disjoints », trop conservateur. Étoiles : bootstrap sur les duels. Bancs tiers : l'intervalle
  publié quand il existe (l'Arena en donne), sinon une valeur ponctuelle dite telle.
- **Deux incertitudes à ne pas confondre** : celle du CORPUS (intervalle sur les items) et celle
  du MODÈLE (dispersion entre passes = répétabilité). Pour un modèle stochastique elles se
  cumulent : la répétabilité dit combien de passes, l'intervalle combien d'items.

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

### M2 — Accord géométrique 🔄 (support par objet livré le 2026-10-16, `detections.support` ; F1 symétrique ⏳ — titre corrigé le 2026-10-31, il disait « ⏳ … jamais écrit »)
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
  🔄 **Premier morceau, 2026-10-16** : le SUPPORT de chaque objet pour des boîtes —
  `common/utils/detections.py::support` (regroupement par IoU ≥ `AGREEMENT_IOU` = 0,3), avec
  `boxes_at` qui ramène des documents pris à des tailles différentes à une même largeur. Son premier
  consommateur est le rapport des détecteurs de l'Anonymizer (`scripts/reports/build_anonymizer_report.py`,
  section « Agrandir une photo de foule avant de la détecter ? ») : une photo de foule et ses deux
  versions agrandies ×4 (SPAN, RealESR_G), passées à quatre détecteurs de visages et à SAM3. Mesuré :
  aucun agrandissement ne fait mieux que l'originale (88 % des visages confirmés au mieux, 85 % sur la
  version SPAN), mais réunir les trois images monte un détecteur à 97-99 %. L'accord n'est **rangé
  nulle part** : une mesure en `ResultEvaluation` donnerait aux détecteurs de visages une seconde
  échelle, et l'étage de mesure interne du sélecteur s'abstiendrait (« une échelle ou aucune »). Le F1
  symétrique deux à deux reste à écrire.

### M3 — Métrique à vérité terrain 🔄 (WER/CER `text_metrics`, cpWER/DER `diarization_metrics`, rappel/précision sur vraies boîtes `bench._bench_boxes`, LPIPS `bench._bench_upscale` livrés, rangés en `ResultEvaluation` ; mAP, PSNR/SSIM ⏳ — titre corrigé le 2026-10-31, il disait « ⏳ une seule vivante : la magnitude de correction »)
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

### M4 — Métrique sans référence 🔄 (mécanique commune + 1ʳᵉ mesure, 2026-10-22)
- **Mesure** : une propriété de la sortie seule. Image : qualité perceptive (NIQE, MUSIQ),
  similarité prompt ↔ image (CLIPScore) ; audio : DNSMOS pour un débruitage, intelligibilité pour
  une voix ; vidéo : constance temporelle (similarité entre trames successives) ; ASR : **confiance**
  du modèle (déjà lue par la heatmap du transcriber, en 2ᵉ priorité derrière la divergence).
- **Ne dit pas** : si la sortie répond à la demande. Une image nette hors sujet score haut.
- **Ancrage** : partiel (la sortie seule, parfois le prompt).
- **Coût** : un modèle léger par métrique (CLIP, DNSMOS) — donc du GPU, ou du CPU lent.
- **Code** : la confiance ASR ; et depuis le 2026-10-22 la **mécanique commune** d'une mesure
  sans référence — un process la DÉCLARE (`ProcessSpec.checks`), le registre la porte
  (`result_evaluation.register_check`), le squelette la joue après un lancement réussi, la ligne
  du process la garde, la bande des process et la face « Évaluation » la montrent. 1ʳᵉ mesure :
  la part de la PAROLE qu'une transcription couvre (`speech_activity.speech_coverage`, garde (b)
  du bloc « pourquoi Albert ne rend pas tout le texte », plus bas). Elle n'entre JAMAIS dans
  `ResultEvaluation` (mesure contre une référence, matière de l'indice ⑧).
  Gestes joués au navigateur depuis le 2026-10-27 : le scénario nocturne
  `transcriber.process_check_relaunch` (bande de la card + « Relancer avec » qui écrit le réglage
  proposé puis joue le ▶ du seul process, lancement intercepté) ; la face « Évaluation » d'un
  élément mesuré sans référence est gardée sur la route d'aperçu servie
  (`test_the_viewer_offers_the_evaluation_face_for_a_measure_alone`).

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
  le banc de légendage et le triage du smoke). *(Corrigé le 2026-10-31, mesuré : `describe_image_ollama`
  est devenu le client de vision COMMUN — describer `describer/backends/image_backend.py`,
  compréhension des références `common/utils/reference_comprehension.py`, outil de l'assistant
  `tool_api.py`, triage du smoke `common/services/ui_smoke.py:270`, banc de légendage `bench.py` —
  aucun usage comme JUGE.)*

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
- **Code** : ~~rien ; `bench.run_bench` produit la matière (une sortie par modèle) sans la confronter.~~
  `result_evaluation.batch_agreement` (`result_evaluation.py:625`, transcription, 2026-09-23 — cf.
  ci-dessus) ; rien pour les boîtes (M2 n'est rangé nulle part) ni hors lot *(corrigé le 2026-10-31)*.

### M7 — Signaux d'usage ✅ (captation générique livrée, gisement encore mince)
- **Mesure** : des **gestes** — `produit`, `echec`, `telecharge`, `corrige`, `relance`, `supprime` —
  captés par middleware sur les routes de file des 10 apps (`wama/common/middleware.py`,
  `WAMA_MEMORY.md §7bis`) et par le squelette de tâche (`task_skeleton`, `produit`/`echec`/`relance`),
  plus la correction du transcriber à la finalisation. Agrégés **par modèle** sur les exécutions à
  **un seul** modèle (`run_outcome.by_model` — ex-`par_modele`, renommé ; sur du multi-modèles, un geste ne dit pas lequel a
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
- 📜 **Forme proposée le 2026-11-12 : des ÉTOILES, lues comme des DUELS** (Fabien : 1 à 5 étoiles
  sur une échelle continue, fractions d'étoile comprises — *« explicite et précis »* ; laissé pour
  plus tard, après le travail en cours et si c'est vraiment pertinent). Une note absolue est la plus
  fragile qui soit (chacun son échelle ; le MOS d'écoute, note absolue sur 5, est critiqué pour sa
  faible fiabilité face aux tests par comparaison, MUSHRA/CMOS) : ne compter que l'écart d'étoiles
  d'une MÊME personne entre deux modèles sur une MÊME demande — un duel —, agrégé à la manière des
  arènes. Le cadre s'y prête : un lot « même prompt, une card par modèle » (motif du transcriber,
  §9bis). **Accord de Fabien** : une évaluation isolée ne fait pas foi, trop peu faussent un tirage
  (déjà la règle M7 et « accumulation avant confiance », §4.1). **Nuance retenue** : une échelle À
  PART (préférence humaine, population = les demandes réelles de WAMA) qui entre comme un étage aux
  mêmes règles, avec un écart SIGNIFICATIF (intervalles de confiance disjoints) plutôt qu'un seuil
  N — « seulement départager des modèles déjà notés » priverait de note les tâches qui en ont le
  plus besoin (musique, effets sonores : vérité nulle, matrice §3). Second usage : calibrer M4
  (CLAP) et M5 contre l'humain (§1).

### M9 — Auto-consistance ⏳
- **Mesure** : le **même** modèle, rejoué avec d'autres graines, températures ou paramètres ; la
  variance des sorties (M1/M2 entre les passes) est une **instabilité**, indépendante de toute
  référence. Pour l'ASR, deux passes à paramètres différents suffisent à alimenter M1
  (`TRANSCRIBER_CORRECTION.md §8.3` : « même modèle à paramètres différents »).
- **Ne dit pas** : si la sortie est bonne — un modèle peut être stablement faux.
- **Coût** : k inférences par item.
- **Code** : rien de dédié ; `bench` accepte `runs` pour la génération de texte (le débit, pas la
  variance des sorties).
- 📜 **Précisé le 2026-11-12 (idée de Fabien) : DEUX notes, RÉPÉTABILITÉ et REPRODUCTIBILITÉ**, au
  sens de la métrologie (VIM, ISO 5725 : mêmes conditions / conditions changées ; l'ACM, en 2020,
  dit repeatability / reproducibility / replicability selon l'équipe et les artefacts) :
  - **répétabilité** — même modèle, même entrée, mêmes réglages, même machine. Graine FIXÉE : le
    DÉTERMINISME (identique ou non — pas garanti même à température 0 : Atil et al., arXiv
    2408.04667 ; Blackwell et al., 2410.03492) ; graine LIBRE : la DISPERSION à température donnée ;
  - **reproductibilité** — une condition change : quantification (GGUF Q8 / BF16), moteur
    (Ollama / transformers), version de librairie ou d'environnement (multi-venv), GPU, local /
    distant ;
  - **la courbe par modèle** (Fabien) : dispersion en fonction de la température (de la guidance,
    du nombre de pas…), linéaire ou à seuil — un PLAN D'EXPÉRIENCE (`axes[]` : température ×
    graine × répétition, A1/A5 livrées), sur les réglages de tirage déjà déclarés par moteur
    (température, graine, top_p — 2026-10-22, `WAMA_VISION_COMPLET §1.5`) ;
  - **deux dispersions à ne pas confondre** : celle des SORTIES (distance entre deux passes, par la
    méthode de la tâche — M1, M2, distance CLAP, LPIPS) et celle du SCORE (écart-type d'un WER) ;
  - **ce ne sont PAS des notes de qualité** (un modèle peut être stablement faux ; en génération la
    variété est souvent voulue) : jamais dans l'échelle des signaux ; affichées sur la fiche du
    modèle, EXIGENCE possible à l'admission (stimuli reproductibles d'une expérience), et mesure
    du nombre de passes qu'une autre note exige (condition déjà posée par Q5) ;
  - **l'existant externe** : surtout des LLM, peu de modèles, rien de lisible par machine — Atil et
    al. (TARr@N / TARa@N sur 10 passes), τ-bench (pass^k : réussir k fois sur k), balayages de
    température (Renze & Guven, EMNLP Findings 2024 : pas d'effet significatif sur la justesse
    entre 0 et 1 ; « Hot or Cold? », arXiv 2506.07295 : le seuil de dégradation monte avec la
    taille). Aucun banc de répétabilité trouvé pour l'audio ou l'image : mesure INTERNE.

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
  accentué perdu entre deux nœuds — corrigé `822d991f`). ⏳ Manquent : la RÉFÉRENCE propagée
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
| `transcription` — transcriber | **humaine** : corrections finalisées (`corrected_segments_json`) ; corpus externe de Fabien (audio + auto + manuel, hors WAMA) | **M1** deux ASR (ou M9 deux réglages), heatmap 1ʳᵉ priorité | M5 cohérence LLM, **cantonnée** (bascule de langue, boucle de jeton, segment tronqué — jamais « incohérence sémantique ») | Open ASR **fr** (WER, sens bas) | profils de correction (`§8.4`), paramètres d'écoute, glossaire ; **finetuning ASR** sur les paires corrigées (§4.3) | M1 ✅ · M3 WER ✅ · corpus ✅ (chaînons ⑤ ⑥, 2026-09-23 — cette case disait ⏳ jusqu'au 2026-10-26) · M4 parole couverte ✅ (2026-10-22) |
| `captioning` — describer, banc, triage smoke | rare ; corrections de description (non captées : le describer n'appelle pas `corrige`) | M6 accord entre VLM (M1 non horodaté), **M10** légende ↔ éléments attendus | M5 VLM d'une autre famille | Arena **vision** (Elo) | consigne au modèle multilingue (langue de sortie), skill de domaine (aucun `PROMPT_TARGET` describer aujourd'hui), contenu RAG (vocabulaire du labo), traduction de sortie (`WAMA_LLM.md §2bis`, non branchée) | ⏳ |
| `ocr` — reader | **humaine** : texte corrigé ; par construction : rendu d'un document numérique → image → OCR (référence exacte, gratuite) | M1 non horodaté entre moteurs (docTR / olmOCR / glm-ocr) | M5 LLM (correction post-OCR — même risque de réécriture qu'en §8.2) | Arena **document** (LLM frontière ; nos moteurs n'y sont pas) ; **classements officiels du Hub** (olmOCR-Bench, MDPBench, Real5-OmniDocBench, ParseBench — valeurs DÉCLARÉES, 2026-10-10) | prétraitement, moteur par type de document, correction LLM bornée | ⏳ |
| `text-generation` — assistant, enrichissement, résumé/cohérence du transcriber, rôles wama-dev-ai | **par construction** : consignes à réponse vérifiable (rubrique M3, anglais, versionnée) ; humaine : corrections de résumé (non captées) | M6 entre LLM ; **M9** (température) ; M7 (relance, correction) | M5 LLM d'une autre famille (`qc.py`) | AA Intelligence Index, scores par famille d'épreuves (`benchmark_meta['family_scores']`, lus par `select_model(benchmark_family=…)`), Arena text | **skills** de rôle (`assistant-*.md`) et d'enrichissement (`<app>-<domaine>.md`), `prompt_contract` par modèle, contenu RAG, tier de modèle | ⏳ (débit ✅ depuis le 14/09, coût seulement) |
| `feature-extraction` — embeddings du RAG | **tierce** : jeu français déclaré (MTEB, 4 tâches) ; **interne** : paires question → passage attendues sur le corpus du labo | rappel croisé (deux modèles, mêmes requêtes : recouvrement des k premiers) | — | MTEB `mteb_fr_retrieval` | découpage (`chunking`), niveau de rappel, modèle | banc tiers ✅ · interne ⏳ |
| spécialisation `translation` — translategemma, `TranslatorService` | humaine (rare) | **M10** aller-retour ; M6 entre modèles multilingues | M5 LLM d'une autre famille | — (AA n'expose pas la traduction) | **glossaire** ne-pas-traduire, découpage, modèle | ⏳ |
| `text-to-speech` — synthesizer, service TTS | par construction : le texte d'entrée | **M10** voix → ASR qualifié → WER ; M4 intelligibilité | M5 (faible : un juge ne « voit » pas la prosodie) | AA Elo TTS, Arena TTS (XTTS : 919, seul du lot) | voix, moteur, paramètres ; M8 (subjectif) | ⏳ |
| `audio-enhance`, `denoise` — enhancer | **par construction** : bruiter un audio propre → SNR gagné, ou ASR-après vs ASR-avant | M4 DNSMOS | — | — | moteur, paramètres | ⏳ (gratuit à construire) |
| `detect`, `segment`, `obb`, `pose`, `classify` — anonymizer, cam_analyzer, face_analyzer, banc | **tierce/humaine** : jeux annotés déclarés (`dataset`) ; ⚠ aucune vérité sur les collisions de cam_analyzer (mesuré 13/09) ; **par construction** : le simulateur (`WAMA_APPRENTISSAGE.md §6.4`) | **M2** + **M6** support par objet ; M9 (seuils) | M5 VLM (« y a-t-il un visage ici ? ») — filet RGPD **secondaire** seulement | aucun flux tiers neutre (PwC mort, Roboflow = éditeur) — **mesure interne seule** | couverture de classes (`model_coverage`), seuils de confiance, concepts SAM3 (KIND `concept`, skill `anonymizer-detection.md`), **finetuning** détecteur sur données du labo (§4.3) | ~~M2 ⏳~~ rappel/précision sur WIDER FACE val ✅ (`bench --task detect-boxes`, 2026-10-10/11, lu au tri `model_coverage.py:315-320`) · rappel par contenant ✅ (`detect-recall`) · M2 support 🔄 (`detections.support`) · saturation ✅ (`bench`) *(corrigé le 2026-10-31)* |
| `depth-estimation` — cam_analyzer, banc | **par construction** : simulateur ; **aval** : `placement_spread` du re-calage du plan de sol (métrique de tâche déjà utilisée par l'app) | **M2** cartes (RMSE invariante d'échelle) | — | — | modèle, résolution d'entrée | banc ✅ (couverture, médiane, focale) · confrontation ⏳ |
| `text-to-image`, `image-to-image` — imager | quasi nulle (subjectif) | **M10** légende VLM ↔ prompt ; M4 CLIPScore, qualité perceptive ; M9 graines | M5 VLM d'une autre famille | AA Elo / Arena Elo (t2i, image edit) | **skill** `imager-image.md`, `prompt_contract` du modèle, prompt négatif, pas/guidance ; M8 | ⏳ |
| `text-to-video`, `image-to-video` — imager | quasi nulle | M10 sur trames-clés ; M4 constance temporelle | M5 VLM | AA / Arena Elo (t2v, i2v) | skill `imager-video.md`, contrat, paramètres ; M8 | ⏳ |
| `upscale` — enhancer, converter→enhancer | **par construction** : sous-échantillonner un original net → PSNR/SSIM/LPIPS exacts | M2-like (différence entre sorties) | — | — | moteur, échelle, paramètres | ✅ **LPIPS (2026-10-14)** : `bench --task upscale --benchmark upscale_div2k_val_v1 --record` — DIV2K val (100 PNG 2K), réduction bicubique du facteur du modèle, LPIPS AlexNet contre l'original ; échelle `internal_lpips_bicubic_x<N>_v1` (le facteur fait la population), vitesse en s/Mpx d'entrée dans la boucle d'ETA ; LUE au tri (Q3). PSNR/SSIM ⏳ (décision de Fabien : LPIPS d'abord). Mesuré en ×4 : SPAN 0,173 · RealESRGAN 0,244 · BSRGAN 0,255 · RealESR_G 0,300 · Swin2SR 0,326 · Animex 0,348 (×2 : BSRGAN 0,155). ⚠ Swin2SR ne passait qu'après la correction du jour : son `preprocessor_config.json` déclare `do_pad`/`pad_size: 8`, lu par `AIUpscaler` ; sa fidélité (PSNR, banc tiers du 06/10) ne se voit pas en LPIPS, qui pénalise le rendu doux |
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
  ⚠ **corrigé le 2026-10-14 à la mesure du code** : depuis le 2026-09-26 (demande de Fabien),
  TOUT étage se juge sur le SOUS-ENSEMBLE qu'il couvre (`_quality_scalars`) — un modèle non
  mesuré ne gagne pas par défaut et ne fait plus tomber les autres. L'étage interne suit la même
  règle, avec deux bornes de plus : au moins DEUX modèles du lot sur la même échelle ET le même
  jeu de références, et UNE seule telle échelle (deux — WER et CER, visages et plaques — et
  l'étage s'abstient : laquelle compte n'est pas à deviner) ;
- **en lecture d'abord** (cards, page du model_manager, volet droit), **dans le tri ensuite**
  (décision Q3), et **accumulation avant confiance** : un indice issu d'une passe sur trois
  échantillons est une anecdote. ✅ **Dans le tri depuis le 2026-10-14** (Q3 tranchée :
  générique) — `model_selector._internal_values`, EN TÊTE de l'échelle des signaux.

Domicile proposé : `benchmark_meta` porte déjà source, échelle, sens, rang, population — un indice
interne y trouve sa place sous une source `internal` ; `sync_benchmarks` n'y touche pas (il ne
réécrit que les sources tierces qu'il connaît). ⚠ À vérifier au code avant d'écrire : ce que
`synchronize` fait d'une clé de source inconnue (décision Q8).
✅ **Tranché par le code (2026-09-23 puis 2026-10-14)** : aucun domicile écrit — `synchronize`
remplace `benchmark_meta` entier ; la sélection LIT la note calculée (`internal_scores`, qui porte
désormais l'empreinte de son jeu de références, `reference_set`).

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

### 4.4 ⏳ La CATÉGORIE de l'entrée fait la population — chantier à part (Fabien, 2026-10-28)

> *« La qualité du résultat des modèles est dépendante du contenu de l'audio d'entrée : un livre
> audio, une réunion, une conférence, un entretien, une interview, ne donneront pas le même résultat
> pour un même modèle. On ne peut pas généraliser la qualité de la transcription audio quel que soit
> le contenu de l'audio d'entrée. Il faut catégoriser l'audio d'entrée pour pouvoir comparer les
> modèles correctement. C'est un chantier à part. »*

C'est la règle de population du §4.1 (« l'indice n'est comparable qu'à l'intérieur d'elle »)
appliquée à l'ENTRÉE : deux modèles ne se comparent que sur des entrées de la même catégorie, et le
modèle à tirer pour une card dépend de la catégorie de SON entrée.

**Déjà mesuré — le classement s'inverse d'une catégorie à l'autre, sur les mêmes modèles :**
- **registre** — campagne du 2026-10-02 (plus bas) : sur les réunions SUMM-RE, Whisper est 1ᵉʳ
  (28,8 %) et Kyutai 4ᵉ (45,4 %) ; sur l'audio multilingue FLEURS-CS nivelé, Qwen3-ASR est 1ᵉʳ
  (21,1 %), Kyutai 2ᵉ (27,5 %), Whisper 4ᵉ (37,4 %) ;
- **condition acoustique** — banc des prétraitements (§9bis) : le meilleur prétraitement n'est pas
  le même en champ lointain (nivellement 36,5 %), sous bruit (rien, 33,2 %) et sur l'audio propre
  (rien, 28,9 %) ; et l'amélioration Resemble est neutre sur l'audio propre mais détruit le champ
  lointain (87 %) ;
- **un défaut n'est pas universel** — Albert couvre 92 à 99 % de la parole d'une réunion proche du
  micro (SUMM-RE) et 56 % d'un entretien lointain (#2522) : « omet la parole lointaine » est un
  défaut de CETTE catégorie ;
- **une mesure sans catégorie compare mal** — le 2026-10-28, la couverture de la parole mesurée
  sur 462 transcriptions passées (`manage.py measure_checks`) aurait proposé de griser Whisper,
  Canary, Parakeet, Kyutai et LinTO, et pas Albert (bloc « pourquoi Albert ne rend pas tout le
  texte ») ; elle compare des entretiens à des réunions et à des livres, en plus de ses biais de
  moteur (filtre de parole propre à Whisper et Albert, segments NeMo plus courts).

**Deux dimensions, pas une** : le **registre** (entretien, interview, réunion, conférence/cours,
livre audio, sous-titrage… — ce que nomment les profils de `TRANSCRIBER_CORRECTION §8.4`) et la
**condition acoustique** (proche ou lointain, niveau, bruit, plusieurs langues). Le registre se
DÉCLARE (l'utilisateur sait ce qu'il dépose) ; la condition se MESURE en grande partie (la sonde
d'activité `speech_activity`, la sonde du VAD « auto » qui détecte une parole lointaine
— `workers._vad_filter_for` —, le niveau en dBFS du nivellement).

**Ce qui existe et se reprend — rien à réinventer** :
- la **population** de l'indice interne : `internal_quality.reference_set`, et
  `model_selector._internal_values`, qui s'ABSTIENT dès que le lot se compare sur plus d'un groupe
  — c'est ce qui arrivera quand le corpus d'évaluation mêlera les catégories, faute de savoir
  laquelle vaut pour la card ;
- les **corpus déclarés** en manifestes `dataset` (`manifests/datasets/`, SUMM-RE, CFPP,
  FLEURS-CS) avec leurs AXES (plan d'expérience, `WAMA_APPRENTISSAGE` A1/A5) — la dégradation
  acoustique y est déjà un axe ; le registre n'y est déclaré nulle part ;
- les **profils de réglages** (`ROADMAP §22.5`, `TRANSCRIBER_CORRECTION §8.4`) : un profil nomme
  déjà un registre (« Entretien (verbatim) », « Réunion (compte rendu) », « Sous-titrage ») ;
- le **défaut mesuré** (`quality.defect` du manifeste `model`, 2026-10-28) et sa chaîne
  proposer → valider : un défaut devra porter la catégorie où il a été mesuré ;
- la garde « une mesure doit se DÉCLARER comparable d'un modèle à l'autre »
  (`Check.compares_models`) : une mesure comparable l'est à catégorie égale.

**Ce qui manque — le chantier** :
1. un **vocabulaire** de catégories par tâche (registre déclaré, condition mesurée), dans un
   registre commun — la transcription d'abord ;
2. la catégorie **d'une card** : déclarée (choisie avec le profil, ou à part) et complétée par les
   sondes ; son domicile sur l'élément ;
3. les **corpus d'évaluation catégorisés** (un axe ou un champ du manifeste `dataset`), pour que
   la population d'un indice soit (échelle, références, CATÉGORIE) ;
4. le **tirage par catégorie** : `_internal_values` prend le groupe de la catégorie de la card au
   lieu de s'abstenir ;
5. le **défaut par catégorie** : `quality.defect` porte ses catégories ; grisé seulement pour elles
   (Albert : parole lointaine) ;
6. l'**universel** : toute tâche a des catégories d'entrée (OCR imprimé / manuscrit ; détection
   caméra 360° / embarquée ; agrandissement photo / scan). Le mécanisme est commun — une propriété
   DÉCLARÉE de l'entrée, par famille de tâches —, le vocabulaire est propre à chaque tâche.

**Décisions ouvertes (Fabien)** : le vocabulaire des registres ; catégorie déclarée seule, ou
complétée par les sondes ; son lien avec les profils (§22.5 : un profil POSE la catégorie, ou la
catégorie est un réglage à part) ; où la catégorie vit sur la card.

---

## 5. La chaîne fonctionnelle complète — douze chaînons, et l'état de chacun

| # | chaînon | ce qu'il fait | existe ? | où / ce qui manque |
|---|---|---|---|---|
| ① | **jeux d'échantillons déclarés** par tâche | un jeu = des entrées + éventuellement des références, **déclaré** (kind `dataset`, provenance réel / synthétique A2), versionné, en français quand ce sont des données du labo | ~~⏳~~ 🔄 | ~~rien de déclaré ; le banc prend un fichier à la main (`--media`)~~ *(corrigé le 2026-10-31)* : références de banc DÉSIGNÉES sous la racine des jeux (`bench --benchmark <nom>` → `<DATASETS>/benchmarks/<nom>/reference.json`, `bench.benchmark_reference` `bench.py:470` ; WIDER FACE val, DIV2K val) ; corpus ASR déclarés en manifestes `dataset` (`manifests/datasets/{summ-re,cfpp,fleurs-cs,madison-simulateur}.json`) ; pas encore « un jeu par tâche ». ⚠ Un jeu se choisit sur ce que le catalogue sait faire (leçon MTEB) |
| ② | **exécution comparative** | le même jeu sur **tous** les modèles capables de la tâche | ✅ partiel | `bench.run_bench` (~~7 tâches : detect/segment/obb/pose/classify, captioning, depth, text-generation. Un échantillon à la fois ; pas de lot~~ — *corrigé le 2026-10-31 : 12 protocoles, `bench.py:831-849`, dont 4 de qualité sur jeu annoté ou par construction : `detect-recall`, `detect-boxes`, `detect-speed`, `upscale` ; `detect-boxes`/`upscale` parcourent un JEU entier, `--limit` échantillonne, `SAMPLING` `:857`*) ; pas de nocturne (`nightly_scenarios` n'appelle pas `bench`) |
| ③ | **collecte des SORTIES** | persister ce que chaque modèle a produit (texte, boîtes, carte, fichier), pas seulement les mesures | ⏳ | le banc **jette** les sorties (boîtes) ou les garde en mémoire (texte) ; rien en base. Sans sorties conservées : ni confrontation différée, ni A/B humain, ni calibration |
| ④ | **confrontation** (M1-M2-M6-M9-M10) | désaccord chiffré entre sorties | 🔄 | M1 ✅ (texte horodaté) ; ~~M2, M6, M9, M10 ⏳~~ M6 ✅ transcription (`result_evaluation.batch_agreement`) ; M2 🔄 (`detections.support`) ; M9, M10 ⏳ *(corrigé le 2026-10-31)* — **calcul pur, constructible sans GPU** |
| ⑤ | **vérité terrain** — entrée et appariement | faire entrer les références (corrections, corpus externes, dégradations par construction) et les apparier aux entrées | 🔄 | corrections du transcriber ✅ (captées, `correction_magnitude`) ; **corpus externe ✅ (2026-09-23)** : la porte est le port `reference_result` de la CARD (appariement = la card elle-même : son audio + sa référence), posé sur un élément ou un lot — Q6 tranchée ; transcriptions externes lues (SRT, VTT, TXT, DOCX, Sonal) ; résultat d'un AUTRE outil comparable par le port `work_result` ; références par construction (upscale, denoise, OCR, TTS) ⏳ |
| ⑥ | **métriques** (M3, M4) | (sortie, référence) → nombre au sens déclaré | 🔄 | **WER/CER ✅** (`text_metrics`), mesure CONSERVÉE par élément (`ResultEvaluation` : modèle, échelle + protocole, sens, identité de la référence) par la brique `result_evaluation`, adoptée par le transcriber ; **rappel par CONTENANT ✅ (2026-10-10)** : `bench --task detect-recall --record` — une détection de la classe doit tomber dans un contenant connu (plaque ⊂ véhicule suivi), taux MANQUÉ rangé en `ResultEvaluation` (métrique `miss_<classe>`, protocole `containment_v1`, une ligne par modèle) ; mesure par le MÊME chemin que l'anonymizer (`detection_ensemble`) ; **rappel et précision sur VRAIES boîtes ✅ (2026-10-10)** : `bench --task detect-boxes --benchmark <nom> --record` — la référence DÉSIGNE l'annotation publiée et son format (`common/utils/dataset_formats`, lecteur WIDER FACE) en chemins relatifs sous la racine des jeux (`resolve_remote_root('DATASETS')`, déplaçable), appariement glouton à IoU 0,5, objets `invalid` du jeu ignorés, rappel par TAILLE d'objet ; ligne `ResultEvaluation` (protocole `boxes_iou50_v1`) ; 1er banc : WIDER FACE val (`faces_wider_val_v1`), 19 détecteurs mesurés le 2026-10-11 (meilleur rappel 82,4 %, `yolov9e-face-lindevs` ; `PROSPECTION_PIPELINE §Session du 2026-10-10`, blocs du 11/10) ; le choix automatique de l'anonymizer classe désormais les visages sur cette mesure ; **rapport GÉNÉRÉ** `/reports/anonymizer/` (`scripts/reports/build_anonymizer_report.py`) ; ⚠ comparer des détecteurs de PLAQUES en les DÉSIGNANT sur des cards n'était pas possible avant le 2026-11-07 (`REMOVAL_LEDGER R223`) : la tâche jugeait tout détecteur de plaques désigné incapable (`plate` ≠ `license_plate`, EgoBlur et RT-DETR illisibles par YOLO) et faisait tourner la couverture à sa place — le banc, qui passe par `detection_ensemble`, n'était pas touché, et aucune card n'en avait désigné un (mesuré le 2026-11-07) ; ⚠ l'IoU 0,5 pénalise un détecteur qui encadre la tête au lieu du visage — un critère de FLOUTAGE (couverture, union avec l'IoU) a été **écarté** le 2026-10-11 (Fabien : le gain vient de meilleurs modèles, pas d'un autre critère) ; **VITESSE ✅ (2026-10-11)** : le temps PROPRE d'un détecteur (copie locale, modèle chargé, chauffe écartée — `bench --task detect-speed`, et chaque passe `detect-boxes`/`detect-recall`) n'est PAS une métrique de qualité et n'entre pas en `ResultEvaluation` : il va dans la boucle d'ETA commune (`eta_estimator.record_run`, secondes par `image`, clé de catalogue, empreinte matérielle), comme les jetons du banc LLM. Le curseur rapide/qualité de TOUTES les apps la compare quand tout le lot est chronométré dans une seule unité (`comparable_speeds` → `model_selector.intent_choice`, sinon la VRAM comme avant) ; pour une classe mesurée de `couvrir_classes`, le premier modèle se choisit par la même règle entre rappel et vitesse, au-dessus d'un PLANCHER de rappel que l'app déclare (anonymizer `RECALL_FLOOR` = 90 % du meilleur : sans lui, « Rapide » retenait pour les visages un 2-en-1 qui en trouve 2,6 %). Mesuré le 11/10 : visages 43 à 174 ms par photo, plaques 38 à 431 ms par image de vidéo ; « Rapide » = `yolov9c-face-lindevs` (80 ms, 82,0 %) + EgoBlur plaques (79 ms). ⚠ La vitesse a d'abord été rangée dans `ResultEvaluation.detail` — un magasin parallèle à l'ETA, retiré le jour même (Fabien : *« on ne réinvente rien, on complète et on aligne »*). ⏳ l'ETA du mode auto reste apprise sous une clé unique (`anonymizer:img:auto`) quel que soit l'ensemble retenu ; **LPIPS ✅ (2026-10-14)** : `bench --task upscale --record` (agrandissement par construction, cf. la ligne `upscale` de la matrice §3) — métrique `lpips`, sens `lower`, protocole `bicubic_x<N>_v1`, détail `errors`/`reference_length` en images (le taux de corpus d'`internal_scores` est alors la moyenne) ; poids AlexNet aiguillés sous `MODEL_PATHS['vision']['lpips']` (pas le $HOME) ; mAP, PSNR ⏳ |
| ⑦ | **juge** (M5) | avis d'un modèle indépendant, **calibré** contre ⑤ | 🔄 | ~~`qc.py` et `vision_probe` présents, 0 consommateur ; calibration impossible tant que ⑤ est vide~~ *(corrigé le 2026-10-31)* `qc.py` : 0 consommateur (`assess_output_quality`, `common/utils/qc.py:27`, aucun appelant) ; aucun JUGE branché — `vision_probe` sert de client de vision commun, pas de juge ; calibration possible depuis que ⑤ porte des références (SUMM-RE, CFPP, Bonneuil, §9bis) |
| ⑧ | **agrégation → indice** | par (tâche, modèle) : valeur, échelle, sens, population, version, date → `benchmark_meta` source `internal` | 🔄 | ✅ **LECTURE livrée (2026-09-23)** : `model_manager/services/internal_quality.py` (étage 3, à côté de `model_quality` et `benchmark_sync`) agrège par modèle — taux de corpus, échelle `internal_<métrique>_<protocole>`, sens, rang parmi les modèles mesurés sur les MÊMES références, accumulation dite ; affichée dans la section « Qualité » du détail de modèle. **Rabattue à la lecture, pas écrite** : Q8 vérifiée au code, `sync_benchmarks` REMPLACE `benchmark_meta` entier (`benchmark_sync.synchronize`) — une clé `internal` y serait effacée ; et ne rien écrire garantit Q3 (hors du tri) par construction. Reste : la PROJECTION dans le tri, le jour où Q3 est tranchée. ✅ **Projection LUE (2026-10-14)** : Q3 tranchée, le tri lit `internal_scores` (étage ⑨) ; chaque échelle porte l'empreinte de son jeu de références (`reference_set`) pour que la sélection ne compare que des mesures d'une même population. Historique de cette ligne : la MATIÈRE existe (`ResultEvaluation`, 2026-09-23 : chaque ligne porte déjà modèle, métrique + protocole, sens, référence = population) ; l'agrégation par modèle d'UN lot existe (`batch_evaluation`, taux de corpus) ; reste l'agrégat INTER-lots vers `benchmark_meta` (Q8) — demande explicite de Fabien : « réutiliser cette évaluation comme note de chaque modèle » ; règle de lot déjà écrite dans `_quality_scalars` |
| ⑨ | **consommation** par la sélection et l'UI | 3ᵉ étage de l'échelle ; cards du model_manager ; heatmap (boucle B) | 🔄 | ✅ **l'étage est BRANCHÉ (2026-10-14, Q3 tranchée par Fabien : générique)** — `model_selector._internal_values`, EN TÊTE de `_quality_scalars` : au moins deux modèles du lot mesurés sur la même échelle ET le même jeu de références, une seule telle échelle (sinon l'étage s'abstient), le sens de l'échelle respecté. Effet mesuré ce jour sur les mesures en base : agrandisseurs ×4 (LPIPS, 1ᵉʳ adoptant — le curseur de l'enhancer était inerte), diarisation (DER, 2 modèles) ; transcription ABSTENUE (WER et CER sur les mêmes références : la métrique principale d'une tâche n'est pas déclarée), détecteurs abstenus dès qu'un lot couvre visages ET plaques. Historique : l'étage était **nommé** dans `_quality_scalars`, vide ; heatmap : divergence prévue en 1ʳᵉ priorité, **rien de branché** (§8.3). **1ʳᵉ projection dans un tri (2026-10-10, à confirmer par Fabien — Q3)** : `model_coverage.couvrir_classes` départage les détecteurs d'une classe par leur taux manqué mesuré, AVANT le proxy de spécialisation, et seulement quand le lot ENTIER de la classe est mesuré sur la même référence (règle de lot) ; rien n'est écrit au catalogue, la note reste calculée (`internal_scores`) |
| ⑩ | **diagnostic → levier** | attribuer un écart à un levier (modèle fixé, un facteur à la fois) | ⏳ | aucun outillage ; la table §4.2 est la carte |
| ⑪ | **variante + A/B objectif + adoption gouvernée** | proposer, mesurer sur le même jeu, valider (humain), journaliser | ⏳ | rien ; le contrat `PENDING_HUMAN_VALIDATION` de wama-dev-ai est le modèle |
| ⑫ | **surveillance et déclenchement** | M7 par modèle, régression N vs N+1 ; candidat au finetuning (A3/A4) | 🔄 | M7 ✅ captation ; agrégation `by_model` (ex-`par_modele`) ✅ ; rien ne lit ces agrégats ; A2/A3/A4 ⏳ |

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
| gestes d'usage | `wama/common/services/run_outcome.py`, `wama/common/middleware.py`, `wama/common/utils/task_skeleton.py` | ⑫ M7 ; `correction_magnitude` (⑥ minimal) ; `by_model` (ex-`par_modele`) |
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
  *(Règle du 15/09 — levée DE FAIT depuis la stabilisation de l'hôte, 2026-09-28/30, cf. Q7 : les
  bancs WIDER (11/10), LPIPS (14/10) et les campagnes ASR (§9bis) ont été joués sur la RTX 4090 de
  l'hôte. Daté le 2026-10-31 ; aucune décision écrite ne lève la règle, à confirmer par Fabien.)*
- ~~**Le corpus de vérité humaine est quasi vide** (§2 M3) et le corpus externe n'a pas de porte.~~
  *(Corrigé le 2026-10-31 : le corpus de vérité humaine du labo reste MINCE — 2 audios de Fabien —,
  mais la porte existe, port `reference_result`, Q6 tranchée le 2026-09-23,
  `result_evaluation.attach_reference` `result_evaluation.py:712` ; et des corpus open data la
  complètent, SUMM-RE / CFPP / FLEURS-CS / Bonneuil, §9bis.)*
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
| **Q1** | **où vivent les jeux d'échantillons** : manifestes `dataset` (provenance A2) pointant vers la médiathèque ? un dossier de référence sous `AI-models` ? | ① | manifeste `dataset` + fichiers en médiathèque (déjà la voie d'entrée des médias, copie et dédup) ; un jeu par tâche, petit, français, versionné. 🔄 **Appliqué de fait (constaté le 2026-10-31)** : manifestes `dataset` + médiathèque SYSTÈME (`media_library/system_files.py`, `ingest_system_file`) pour les corpus ASR (2026-09-29) ; racine déplaçable des jeux pour les bancs (`mirror_sync.resolve_remote_root('DATASETS', 'WAMA_DATASETS_ROOT')`, lue par `bench.benchmark_reference`, 2026-10-10) — décision générale à confirmer par Fabien |
| **Q2** | **persistance des sorties du banc** : une table (`BenchRun` : tâche, jeu, modèle, version, sortie sérialisée ou chemin, mesures) ou des fichiers seuls | ③ ④ ⑧ | une table — c'est ce que confrontent ④ et ce que lit ⑧ ; les fichiers lourds (images, audio) en médiathèque, la ligne pointe. ✅ **Tranché pour les MESURES (Fabien, 2026-09-23)** : table COMMUNE `ResultEvaluation` (une ligne par élément et métrique, le résultat COURANT — la sortie, elle, reste dans l'élément de l'app). La persistance des sorties d'un banc HORS des apps (③) reste ouverte |
| **Q3** | **l'indice interne entre-t-il dans le TRI**, ou reste-t-il en lecture (phase 1) | ⑨ | lecture d'abord, tri quand une tâche a ≥ N passes sur le même jeu (N à fixer) — même règle que le rang centile. 🔄 **Appliquée à UN cas le 2026-10-10, à confirmer** : le choix des détecteurs d'une classe par l'anonymizer (lot entier mesuré sur la même référence, une passe) — sans elle, le curseur « Équilibré » retenait un YOLO plaques au rappel mesuré de 13 % devant EgoBlur (59,5 %). Revenir en arrière = retirer le terme ~~`_mesure`~~ `measured` (`measured_miss_rates`, `model_coverage.py:193`, `:315-320` — relocalisé le 2026-10-31) de `couvrir_classes`. ✅ **TRANCHÉ par Fabien le 2026-10-14 : « étage 3 générique »** — la mesure interne entre dans le tri de TOUTES les sélections (`model_selector._internal_values`, en tête de l'échelle), avec la règle de population (même échelle, même jeu de références, ≥ 2 modèles) et une seule échelle comparable par lot. Le cas de l'anonymizer (`couvrir_classes`) reste le sien. Le « N passes » n'a pas été fixé : une passe complète sur un jeu figé suffit (le jeu EST la population). Déclencheur : le curseur de l'enhancer, inerte faute de toute note de qualité au catalogue |
| **Q4** | **M8 (vote A/B humain)** : geste ajouté, contraire au principe de `§16.7` — l'admettre pour les tâches subjectives seulement ? | M8, génératifs | admettre, **opt-in**, cantonné aux tâches sans vérité (image, musique, voix), jamais dans le flux normal. ⏳ *Forme proposée le 2026-11-12* : des étoiles (1 à 5, continues) lues comme des duels d'une même personne sur une même demande, échelle à part, écart significatif exigé (M8) — reportée par Fabien après le travail en cours |
| **Q5** | **gouvernance de l'auto-amélioration** : humain toujours pour les consignes ; auto-ajustement borné pour les paramètres numériques ? | ⑪ | oui à la séparation ; l'auto-ajustement borné vient **en dernier**, après que M3/M9 aient prouvé la stabilité de la mesure |
| **Q6** | **porte d'entrée des corpus externes** (audio + transcription tierce + correction manuelle de Fabien) : médiathèque ? commande d'import ? formats acceptés (SRT, VTT, TXT, DOCX ?) | ⑤, calibration de tout juge | ✅ **Tranché (Fabien, 2026-09-23)** : les jeux vivent comme n'importe quel média d'app ; la porte est la CARD — ses ports du RÉSULTAT `reference_result` (comparer la sortie) et `work_result` (reprendre un résultat fait ailleurs), `INPUT_MODEL_MATCHING §6.7` ; l'appariement audio ↔ texte EST la card (plus de convention de nom) ; formats SRT, VTT, TXT, MD, DOCX, PDF, exports Sonal compris (`TRANSCRIBER_CORRECTION §10`) |
| **Q7** | **où tourne la nocturne comparative** | ② | R760xa ; l'hôte de dev ne joue plus aucun banc GPU. ⚠ **Précision de Fabien (2026-09-30)** : *« aujourd'hui la machine est stable »* — l'instabilité de l'hôte est résolue (`INFRA_WSL_VS_WINDOWS`), la condition « machine stable » de P4 ne bloque plus sur l'hôte actuel |
| **Q8** | **domicile de l'indice interne** : `benchmark_meta` source `internal` (vérifier ce que `synchronize` fait d'une source inconnue) ou champ dédié | ⑧ | `benchmark_meta`, après vérification ; un champ de plus serait une 3ᵉ échelle de plus à ne pas mélanger. ✅ **Vérifié (2026-09-23)** : `synchronize` REMPLACE `benchmark_meta` des modèles appariés — `benchmark_meta` n'est PAS un domicile sûr sans le modifier. En phase lecture, aucun domicile : la note est calculée à la lecture (`internal_quality`). La question renaît avec Q3. ✅ **Close avec Q3 (2026-10-14)** : le tri LIT la note calculée, rien n'est écrit — aucun domicile n'est nécessaire |
| **Q9** | **la consistance de lignée** dans M6 : pondérer l'accord par la diversité des familles (deux YOLO ≠ un YOLO + un DETR) — déclarer la famille où ? | M6 | `AIModel.extra_info['family']` existe pour les snapshots HF ; à généraliser, ou ignorer en phase 1 |
| **Q10** | **trous de notation et trous de sélection** (Fabien, 2026-11-10) : comment le curseur répond honnêtement, sans omettre de modèle, quand une partie du lot n'a aucune note — et comment compléter les notes, sachant que des modèles neufs en arriveront toujours sans | le curseur de toutes les apps, `best_installed` | 🔄 **avis du 2026-11-12 et décisions de Fabien** au §0 (« AVIS DU 2026-11-12 ») : bornes de l'inconnu et trois verdicts (hypothèse acceptée) ; indéterminé → prudence, notes calculées dans les descriptions ; mesure d'entrée = P4 ; échelle principale par tâche + dominance ; étoiles → M8, répétabilité / reproductibilité → M9. Avis du concile (« correcte avec corrections ») lu au §0, à la suite : bornes par la POPULATION de l'échelle, verdict « gagnant même au pire » sur coût MESURÉ seulement, intervalle de confiance sur toute note interne, date de revalidation du corpus, mesure d'entrée en priorité la plus basse. ✅ Fabien : dominance par défaut pour les autres échelles de qualité d'une tâche (N, pas deux), seuil seulement justifié ; intervalle par bootstrap (apparié pour comparer) |

---

## 9. Ordre de construction recommandé — paliers, du gratuit vers le coûteux

Chaque palier est **attestable sans GPU** jusqu'au P4 ; chacun livre une brique commune et sa garde.

| palier | contenu | méthodes | sans GPU ? | état (ajouté le 2026-10-31, d'après les §2, §5, §8 de ce document) |
|---|---|---|---|---|
| **P0** | trancher Q1, Q2, Q6, Q8 ; déclarer un premier jeu par tâche (transcription, détection, upscale, OCR) | — | oui | 🔄 Q6 ✅ (2026-09-23), Q8 ✅ close (2026-10-14), Q2 ✅ pour les mesures ; Q1 appliquée de fait ; jeux déclarés pour la transcription, la détection de visages et l'upscale — OCR ⏳ |
| **P1** | ③ persistance des sorties du banc ; ④ **M2** (appariement IoU, F1 symétrique, support), **M6** (isolement), M1 non horodaté, **M9** ; tests sur sorties synthétiques | M1 M2 M6 M9 | oui | 🔄 M6 ✅ (transcription), M2 support 🔄 ; ③, F1 symétrique, M1 non horodaté, M9 ⏳ |
| **P2** | ⑤ vérités **par construction** : upscale (sous-échantillonnage → PSNR/SSIM), denoise (bruitage → SNR), OCR (rendu → image) ; ⑥ métriques ; ⑧ schéma d'indice interne + affichage sur les cards (lecture seule) | M3 | oui (les métriques ; les modèles se jouent ailleurs) | 🔄 upscale par construction ✅ (LPIPS, 2026-10-14, au lieu de PSNR/SSIM) ; ⑧ en lecture ✅ (2026-09-23) ; denoise, OCR ⏳ |
| **P3** | ⑤ **porte d'entrée du corpus externe** (Q6) ; WER transcriber ; **calibration** de M1 et du juge de cohérence contre la correction humaine (`§8.5` : précision / rappel de chaque signal) ; branchement de la divergence dans la heatmap (boucle B) | M3 M5 | oui pour l'import et la WER ; la calibration du juge rejoue le LLM | 🔄 porte ✅ et WER ✅ (2026-09-23) ; calibration et heatmap ⏳ |
| **P4** | ② **nocturne comparative** sur machine stable : scénario `bench` par tâche, tous les modèles capables, jeu déclaré → ③ → ④ → ⑧ ; M10 pour TTS et génératifs | toutes | **non** | ⏳ (à la demande seulement, décision du 28/09 ci-dessous) |
| **P5** | ⑩ ⑪ boucle d'amélioration : A/B objectif d'un levier (skill, contrat, paramètre) sur le même jeu ; adoption gouvernée (Q5) ; journal | selon tâche | partiellement | ⏳ |
| **P6** | ⑨ l'indice entre dans le tri (Q3) ; ⑫ agrégats M7 lus par le model_manager ; A2/A3/A4 déclarés, déclencheur de finetuning ASR / détection (§4.3) | — | oui | 🔄 ⑨ ✅ (2026-10-14, `model_selector._internal_values`) ; ⑫ lecture des agrégats et A2/A3/A4 ⏳ |

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

**Le premier geste rentable, si un seul** : **Q6, la porte d'entrée du corpus de Fabien** *(✅ fait le
2026-09-23 — noté le 2026-10-31)*. C'est le
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
  `process_control.refuse_crash_redelivery` (`d5a5e471`), card rétablie.

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
  celles-là (`result_evaluation._restricted`, commit `17eea90b`) — #724 : 51,3 → 44,5 %.
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
- ✅ **Fait le même jour** : sonde échantillonnée selon la durée (`782fcb48`), décision « auto »
  écrite dans les deux cas (`da7a9a0b`). Corpus du banc tranché par Fabien : **les deux**.
- Ordre dans le worker (`workers.py:486-498`) aujourd'hui : débruitage → nivellement → VAD (dans
  le moteur). Ne pas l'inverser avant le banc : sur cet entretien, c'est le VAD, pas l'ordre, qui
  décide du résultat. → voir le banc ci-dessous. *(État du 30/09 — l'ordre est aujourd'hui
  nivellement → débruitage, déclaré par les process : `transcriber/function_specs.py:212-218`
  (`denoise` dépend de `level`), glu `workers.py:441-447` ; noté le 2026-10-31.)*

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
  ✅ *(constaté le 2026-10-31)* **(a) et (b) appliquées** : process déclarés `level` → `denoise`
  (`denoise` `depends_on=('level',)`, `transcriber/function_specs.py:215`), et la glu le dit — « on
  ne débruite jamais un audio non nivelé » (`workers.py:516-521`, `_level_step`). (c) reste un
  réglage par défaut (débruitage OPTIONNEL).
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
  de l'enhancer comme prétraitement du transcriber. *((a) et (b) appliquées depuis, cf. ci-dessus —
  noté le 2026-10-31.)*

**Suite (2026-10-21) — « sans nivellement 44,5 %, avec 65,2 % » sur le lot #489 : ce n'est PAS le
nivellement.** Question de Fabien, sur l'entretien de Bonneuil (141 min, même référence). Les deux
cards diffèrent de QUATRE choses à la fois :

| card | moteur | nivellement | filtre de parole | langues | WER | mots rendus (réf. 17 594) |
|---|---|---|---|---|---|---|
| #724 | Whisper large-v3 LOCAL | non | auto | auto | 44,5 % | 21 177 |
| #2522 | whisper-large-v3 ALBERT | oui | coupé | une seule | 65,2 % | 9 055 (9 036 suppressions) |

- La seule paire contrôlée sur cet audio reste #1048 / #1070 ci-dessus (Whisper local, filtre
  coupé) : **le nivellement y gagne 3,2 points** (42,8 → 39,6 %). Aucune card n'a nivelé cet
  audio avec Albert seul changé — la mesure « Albert sans nivellement » reste à faire (gratuite en
  GPU : le moteur est distant).
- L'écart de #2522 est dominé par les **mots manquants** : Albert rend la moitié du texte (216
  segments contre 4 296 en local), passage par passage (6 envois de 1 500 s, 30 à 42 segments chacun,
  `celery-default.log` 15:55:50 → 15:56:29). C'est le défaut d'omission déjà mesuré sur SUMM-RE
  (`albert_asr_backend.py`, en-tête : « Albert OMETTAIT 70 à 250 mots… l'écart est dans le décodage
  d'Albert »), ici beaucoup plus fort sur un entretien de 25 min par envoi.
- ✅ **MESURÉ le 2026-10-22 — pourquoi Albert ne rend pas tout le texte** (demande de Fabien : « on
  mesure d'abord »). Mêmes 10 premières minutes de Bonneuil, envoyées directement à l'API :

  | envoi | mots | temps couvert |
  |---|---|---|
  | 10 min en une requête (comme la card) | 484 | 43 % |
  | les mêmes, NIVELÉES | **262** | 21 % |
  | morceaux de 2 min | 492 | 45 % |
  | morceaux de 30 s | 552 | 45 % |
  | Whisper large-v3 LOCAL, filtre coupé (#1048) | **1 287** | — |

  - **Ce n'est PAS le quota** : toutes les requêtes ont répondu 200 ; un refus (429 persistant,
    HTTP ≠ 200) fait ÉCHOUER la transcription en le disant (`workers._transcribe_maybe_chunked` :
    `if not r.success: return r`), il ne laisse jamais tomber un morceau en silence. Les trous sont
    DANS des réponses réussies.
  - **Ce n'est pas la découpe** (10 min, 2 min, 30 s : même résultat), **ni un filtre de parole**
    côté serveur : le VAD Silero ne garde que 2 s de ces 10 min (parole lointaine), Albert en couvre
    258 s.
  - **C'est le décodage par fenêtres de 30 s** : au plus UN segment par fenêtre, qui commence près de
    son début (0, 28, 60, 93, 132, 163… s) et s'arrête avant sa fin ; des fenêtres entières ne rendent
    RIEN (270-300 s : 0 mot chez Albert, 55 en local). **56 % des mots** du Whisper local (722 sur
    1 287) tombent dans ces trous. Les entretiens proches du micro (SUMM-RE, 20 min) n'ont pas ce
    défaut : Albert y couvre 92 à 99 % du temps (#1072-#1234).
  - **Aucun réglage de l'API ne l'atteint** : `temperature=0.4` et un `prompt` de contexte rendent les
    mêmes mots, au mot près, sur trois fenêtres — le serveur décode à sa façon (sans le repli en
    température ni la recherche en faisceau du local), et ses segments ne portent ni `avg_logprob` ni
    `no_speech_prob` (champs `id, start, end, text, type, speaker`) : on ne peut même pas dire
    lesquels il juge douteux.
  - **Le nivellement aggrave chez Albert** (484 → 262 mots), alors qu'il aide le local (−3,2 points) :
    à ne pas proposer devant Albert.
  - **ILaaS n'offre pas de remplaçant** : ni sa passerelle LLM (6 modèles de conversation) ni sa
    passerelle RAG (OpenGateLLM, la même qu'Albert : bge-m3, reranker, gpt-oss-120b) ne sert de
    modèle de parole, bien que la route `/audio/transcriptions` existe — listes lues avec nos clés
    le 2026-10-22.
  - Le local lui-même tombe à ~5 000 mots sur cet audio dès que le filtre de parole est gardé ou que
    DeepFilterNet débruite (#173, #176, #1049-#1051) : l'omission sur parole lointaine n'est pas
    propre à Albert — elle l'est seulement quand rien de NOTRE côté ne l'explique.
  **Décision de Fabien, éléments** : rien à corriger côté WAMA dans l'appel ; trois voies — (a)
  écarter Albert du tirage automatique pour la parole lointaine ou longue ; (b) une GARDE mesurée
  et commune à tout moteur : comparer le temps COUVERT par les segments rendus au temps ACTIF du
  signal (la sonde `speech_activity` mesure déjà l'énergie) et, sous un seuil, le dire sur la card
  et proposer le moteur local ; (c) signaler le défaut à la DINUM (mesures ci-dessus, données de
  la session dans le dossier jetable, jamais versionnées : c'est l'entretien de Fabien).
  ✅ **(b) LIVRÉE le 2026-10-22** (Fabien : « on peut faire b ») — et montrée à DEUX endroits, la
  bande des process et la face « Évaluation » (« pourquoi pas les deux ? »). Précision demandée :
  le découpage en 30 s de WAMA ne concerne que Qwen3-ASR et Canary (`max_audio_seconds`) ; Albert
  reçoit des envois de 25 min, et les fenêtres de 30 s sont celles du décodage Whisper, chez lui
  comme chez nous. Calibrage, part de la PAROLE couverte par les segments (15 cards) :

  | cards | moteur | part couverte |
  |---|---|---|
  | #724, #1048, #1070 | Whisper local sans filtre | 0,87-0,92 |
  | #1072-1075, #1233-1234 | Albert, parole proche | 0,95-1,00 |
  | #2522 | Albert, parole lointaine | 0,56 |
  | #173, #176, #1049-1051 | Whisper local avec filtre de parole ou débruitage | 0,29-0,60 |

  Seuil `COVERAGE_FLOOR = 0,75`. Le Whisper local PERD lui aussi du texte (filtre, débruitage) :
  c'est pourquoi la garde est commune plutôt qu'un sort fait à Albert — (a) devient inutile. Chaîne :
  `speech_activity.speech_coverage` (mesure) → `result_evaluation.register_check('speech_coverage')`
  → déclarée sur le process `transcribe` (`ProcessSpec.checks`) → jouée par le squelette à la fin
  du lancement (`_measure_without_reference`), sur l'audio que le process a ÉCOUTÉ
  (`AppPipeline.input_of`) → gardée sur SA ligne, jamais dans `ResultEvaluation` (mesure contre une
  vérité, matière de l'indice) → montrée par la bande (taux + « Relancer avec » le modèle LOCAL que
  tirerait l'auto, `cloud_keys=[]`, quand la sortie venait d'un distant) et par la face
  « Évaluation », même sans référence. Mesurée en lecture seule sur les cards réelles : #2522
  0,558 (signalée, Whisper Large-v3 proposé), #724 0,90, #1072 1,00. ⏳ (c) reste à faire ;
  les cards transcrites avant le 2026-10-22 ne sont mesurées qu'à leur prochaine transcription.
  ✅ **GRISÉ le 2026-10-28** (Fabien : « griser avec la vraie raison, dans le commun, et bien sûr
  ne peut plus être sélectionné automatiquement ») — au-delà de (a) : `albert:whisper-large-v3`
  reste listé au select du Transcriber, grisé « omet la parole lointaine », l'explication au
  survol, et ne sort plus du tirage automatique ; lu aux deux endroits où `backend_missing` grise
  et exclut déjà (`select_model`, `get_registry_models` → `api_model_options`), donc pour TOUT
  modèle et toute app. Vu au navigateur sur le serveur en service le même jour (compte
  `wama_evaluation`) : option grisée sous « Cloud souverain · Albert API (DINUM) », la prévision
  « Automatique » sur un Whisper local. Une card qui porte déjà Albert n'est pas refusée au lancement.
  Hypothèse de Fabien à poser à la DINUM : le saut de fenêtre de Whisper (`no_speech_threshold`)
  plutôt qu'un filtre Silero — mesuré, Silero ne garderait que 2 s des 10 min, Albert en couvre 258 s.
  ✅ **Version SYSTÈME le soir même** (Fabien : « fais la version système », puis « la mesure
  propose, l'admin valide ») : le défaut ne vit plus dans le code (`DECLARED_DEFECTS`, retiré) mais
  sur la ligne du catalogue, porté par le manifeste `model` (`quality.defect` : libellé, raison,
  source datée → `extra_info['quality_defect']`, collant au sync ; dégrisé par la révocation) — celui
  d'Albert y a été projeté par la route (`write_back_model`), corpus régénéré. Une mesure sans
  référence qui se DÉCLARE comparable d'un modèle à l'autre (`Check.compares_models`) PROPOSE le
  défaut (« Propositions à valider », `model_quality.propose_defect`) quand, sur la même entrée et
  avec les mêmes réglages, un autre modèle passe le seuil ; un administrateur valide. Gardes :
  `model_manager/tests/tests_measured_defects.py` (15 tests, contre-épreuves rouges).
  ⚠⚠ **Mesuré le jour même : aucune mesure n'est encore comparable.** Les 462 transcriptions
  passées mesurées (`manage.py measure_checks`) ont déposé six propositions FAUSSES — Whisper,
  Canary, Parakeet, Kyutai, LinTO, VibeVoice — et aucune pour Albert ; un seuil plus strict n'y
  change rien (écart de 30 points : Whisper 12 cards, Canary 36). Causes : la couverture compare
  des CATÉGORIES d'audio différentes (§4.4) et porte des biais de moteur (filtre propre à Whisper et
  Albert, segments NeMo courts, un modèle qui couvre tout l'audio vaut 100 %), et des lignes
  anciennes portent « auto » au lieu du modèle tiré. Les six propositions ont été défaites (quatre
  rejetées, Kyutai et LinTO rétablis depuis le dump de 03:30) ; `speech_coverage` ne se déclare
  pas comparable ; le mécanisme attend la catégorisation de l'entrée (**§4.4, chantier à part**).
  Le défaut d'Albert reste, validé par Fabien.
- **Niveau mesuré avant / après nivellement** (hypothèse de Fabien : « le nivellement baisse peut-être
  le niveau global, faut-il normaliser vers 0 dB ? ») : parole active −25,8 → **−20,1 dBFS**, RMS
  −27,3 → −21,8 dBFS, crête +0,4 (l'original écrête déjà) → −0,2 dBFS. Le nivellement RELÈVE le
  niveau ; une normalisation de crête n'y ajouterait que 0,2 dB. Et Whisper (local comme chez
  Albert) est peu sensible au gain global : son spectrogramme log-mel est borné à 80 dB SOUS SON
  MAXIMUM — c'est le niveau RELATIF des passages qui compte, ce que fait le nivellement. ⚠ Ce qui
  bouge en revanche : le **plancher des silences monte de 14 dB** (−50,6 → −36,6 dBFS), les silences
  gardant le gain des mots voisins. Sur #1070 les ajouts ont pourtant BAISSÉ (4 213 → 3 291) ; à
  surveiller sur un audio au fond plus bruyant.
- ✅ **Garantie posée le jour même** (demande de Fabien : « être sûr qu'on n'abaisse jamais le
  niveau global ») : le niveau de parole ne sort jamais plus bas qu'il n'est entré — une parole
  déjà forte (−12 dBFS) sortait à −20 —, puis le signal monte jusqu'à une crête de 0,98
  (`speech_leveling.level_speech`, gardes `tests_speech_leveling`, rouges sur la brique d'avant).
  Sur Bonneuil, rien ne change (aucune baisse, crête déjà à −0,2 dBFS). ⚠ Les mesures du banc
  ci-dessus ont été faites AVANT : sur un audio fort, la brique d'aujourd'hui n'est plus celle
  mesurée — Whisper étant peu sensible au gain global, l'effet attendu est nul, NON remesuré.
- ✅ **L'écoute, posée le même soir** (demande de Fabien : « se rendre compte à l'oreille ») : le
  nivellement et le débruitage sont deux PROCESS déclarés du transcriber, qui gardent leur audio
  sur la card (`ROUTE §10.6` 4.6) — l'aperçu en a une face chacun, la page de correction propose
  « Écouter : Original / Nivellement / Débruitage ». Un débruiteur absent fait échouer SA ligne au
  lieu de rendre l'audio non débruité en silence. ⚠ Pour un banc, chaque version est désormais un
  fichier de la card : les comparer à l'oreille ne demande plus de les refaire.

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
  coupées dans une pause (`39203f4`) → 43,7 %. Score SUMM-RE seul valable (CFPP/FLEURS vus).
- **Trois défauts d'INTÉGRATION trouvés par la campagne, pas par les essais** — une card isolée
  passait, la FILE tombait : (1) Kyutai après LinTO dans le même worker, « Inplace update to
  inference tensor » → génération en `inference_mode` (`8d86ae0`) ; (2) LinTO réutilisé après
  Kyutai, « illegal memory access » qui corrompt le contexte CUDA et fait tomber TOUTE la file —
  passait avec `CUDA_LAUNCH_BLOCKING=1` (course entre flux) → décodage NeMo sans graphes CUDA
  (`345ca40`) ; (3) le worker ne décharge pas en fin de card : les modèles de moteurs différents
  COHABITENT, ce que ni un smoke ni une card seule ne montrent — et FrWhisper comme Kyutai
  RECHARGEAIENT leur modèle à chaque card sans libérer le précédent : la mémoire s'empilait
  jusqu'au manque (19:53 et 20:18, ~19 Go alloués par PyTorch ; relevé par une autre instance,
  vérifié au journal) → `load()` réutilise un modèle déjà chargé, comme NeMo. ⭐ *Un essai par modèle ne dit
  rien d'une file de modèles différents : seule une campagne mélangée l'éprouve.*
- Non mesuré : CFPP (LinTO biaisé, et les entretiens longs coûtent ~1 h de GPU par card Kyutai).

#### 🔄 Rapports d'évaluation GÉNÉRÉS — à construire sur l'exemple de la transcription (demande de Fabien, 2026-10-03) — *celui des détecteurs de l'Anonymizer est généré depuis `ResultEvaluation` (`scripts/reports/build_anonymizer_report.py`, 2026-10-11) ; celui de la transcription reste une graine recopiée (`build_transcription_report.py:10-12`) — statut corrigé le 2026-10-31, il disait ⏳*

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
| `common/reports.py::REPORTS` + `/reports/<slug>/` | le lieu de publication : un rapport s'ajoute par sa déclaration (dont les `apps` dont il parle), le menu le liste et l'onglet « À propos » de chaque app concernée le lie avec sa date (lue dans la page) — déplacé de `wama.views` le 2026-11-03 |
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
annexes » de l'accueil (2026-10-03), et depuis le 2026-11-03 (demande de Fabien) une ligne
« Rapports » dans l'onglet « À propos » de l'app dont ils parlent — c'est là que se pose la question
« pourquoi ce moteur ? ». ✅ Et depuis le 2026-11-05 (demande de Fabien : « le modèle, de même
qu'il porte une note d'évaluation interne, devrait faire le lien avec le rapport d'évaluation qui
le contient ») depuis CHAQUE modèle évalué : un rapport DIT dans sa page ce qu'il évalue, comme il
y dit sa date — `{clé de modèle: [échelle interne]}`, écrit par son générateur
(`shell_page.fill_shell(evaluations=)` ; celui de l'Anonymizer le tire de ses mesures, la graine de
la transcription le recopie comme ses graphiques) et lu par `common/reports.reports_evaluating`.
Chaque échelle de la « Mesure interne » du model manager mène au rapport qui la présente, la ligne
du modèle dans « Modèles et publications » aussi, et l'assistant le lit (`get_ai_model`,
`internal_quality[].reports`). Gardes : `tests_app_about.ReportsStateWhatTheyEvaluateTest` (ce que
le générateur écrit est ce que WAMA lit ; les modèles cités sont au catalogue, les échelles
internes), `ModelsAndPublicationsLinkTheirReportTest`, `tests_internal_quality.EachScaleLeadsToItsReportTest`
(une échelle que le rapport ne présente pas n'est pas liée). Quand ils seront générés et nombreux, une page dédiée qui les
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
- **2026-11-12** — Q10 : avis complémentaire et décisions de Fabien (§0, « AVIS DU 2026-11-12 »),
  M8 (étoiles lues comme des duels), M9 (répétabilité et reproductibilité, courbe par modèle),
  question des modes musique / paysages sonores, intention de publier les évaluations
  (`WAMA_VISION_COMPLET §10.4`, `ROADMAP §30`). Rien d'implémenté.
