# Audit « doc de construction ↔ code » — 2026-10-29

> **Rapport de travail, pas un document de référence.** Il sert à préparer la mise à jour de la doc
> de construction ; une fois les corrections appliquées, il n'a plus d'objet et peut être supprimé.
> Il vit sur la branche `claude/nifty-darwin-qfkqog`, jamais sur `dev` : il ne concurrence aucun
> `.md` de la table « Fichiers de référence par domaine » d'`AGENTS.md`.

**Base auditée** : `origin/dev` au commit `3b497863` (2026-10-29 17:18). Tout ce qui a été poussé
après n'est pas couvert. **Avant d'appliquer une ligne, revérifier sur le `dev` courant** : le code
a pu bouger, et une correction calée sur un code dépassé recrée exactement le défaut qu'on corrige.

## 1. Comment s'en servir dans une session locale (PyCharm)

Un fichier par lot (`L01.md` … `L15.md`), un tableau par document. Chaque ligne donne la ligne du
doc, le type d'écart, une citation courte (pour la retrouver par recherche), la preuve dans le code
(`fichier:ligne` ou commit) et une correction formulée pour être appliquée telle quelle.

Prompt type, un lot par session :

```
Lis audit/doc-construction-2026-10-29/README.md puis audit/doc-construction-2026-10-29/L08.md.
Pour chaque ligne du tableau de <document> :
  1. revérifie la preuve sur le code courant (la ligne citée a pu bouger depuis le 29/10) ;
  2. si l'écart tient, applique la correction proposée — en DATANT la correction
     (« corrigé le AAAA-MM-JJ, mesuré : … ») et sans retirer d'INTENTION (règle AGENTS.md) ;
  3. si l'écart ne tient plus, ne touche à rien et note-le.
Ne traite que les lignes de confiance « certaine » ; liste les « probable » à la fin pour moi.
Commit par chemins explicites (`git commit <chemins> -m …`), jamais depuis l'index partagé.
Ensuite : `python manage.py check_docs` et, si un bloc généré est concerné, `python manage.py doc_facts`.
```

Les `LIGNE_DECALEE` (166) sont mécaniques : une session peut les traiter en lot, document par
document, sans autre jugement que de revérifier le symbole à la ligne proposée.

## 2. Méthode

1. **Passe mécanique** (`mecanique.tsv`, 1 952 lignes brutes). C'est un script autonome qui
   reprend les règles de `check_docs` : résolution des chemins, filtre « intentionnel », journaux.
   Django n'est pas installé dans l'environnement d'audit, d'où ce script plutôt que la commande.
   Il ajoute trois contrôles que `check_docs` n'a pas :
   - **ligne décalée** : un `fichier:ligne` cité avec un symbole qui est défini ailleurs dans le
     fichier ;
   - **`fichier::symbole`** dont le symbole est absent du fichier ;
   - **symbole cité défini nulle part** dans le dépôt. Ce dernier contrôle est un candidat faible :
     le symbole peut appartenir à du code tiers, être une intention ou une clé de donnée.

   La colonne `excuse` reprend les exemptions de `check_docs` (journal, passage « supprimé /
   archivé / renommé / ~~barré~~ »).
2. **Passe sémantique** : 15 lots confiés à des sous-agents, lecture intégrale de chaque
   document, avec un même brief tiré d'`AGENTS.md`. Ce brief pose quatre règles :
   - une affirmation sur le code nomme la ligne qui la fonde ;
   - un constat contredit par le code a tort ;
   - une intention se garde : elle n'est signalée que si elle est désormais réalisée ;
   - un statut daté est une trace, pas un constat faux.

   Les candidats mécaniques ont été triés lot par lot.
3. **Contre-vérification** : 12 écarts parmi les plus lourds, pris dans 11 lots, revérifiés à la
   main sur le code. **12/12 confirmés**. Liste :
   - `privacy/gate.py` appelé par `llm_utils.py:827` ;
   - `card_layout = list|grid` ;
   - budgets de nommage 2627/132/1289 ;
   - recalage ortho 2b appliqué (`ego_pose.py:408`) ;
   - `staticfiles/` servi en DEBUG (`urls.py:84`) ;
   - `error_message` présent dans le transcriber ;
   - `batch-start-btn` tenu par `queue-actions.js:693` ;
   - `_internal_values` présent dans `model_selector` ;
   - enrichissement actif par défaut (`settings.py:1189`) ;
   - absence de `wama/rag/` ;
   - `os.environ['TTS_HOME']` posé dans `coqui_backend.py:62` ;
   - choix de backend ignoré en mode vidéo par face_analyzer (`views.py:113-119`).

**Périmètre** : les 31 documents de `docs/construction/` (hors `archive/`) et les 16 documents de
référence hors de cet arbre que déclare `wama/common/docs_catalog.py` (`AGENTS.md`, `CLAUDE.md`,
`README.md`, READMEs de module, docs du cam_analyzer, du transcriber, de l'enhancer, de l'imager,
du face_analyzer, `PROSPECTION_PIPELINE`, `wama-dev-ai`, `patches`, `AI-models`, `vendor`).
**Hors périmètre** :
- les docs **dérivées** `docs/dev/` et `docs/utilisateur/`, qui se régénèrent par `doc_facts` ;
- `CAM_ANALYZER_CHANGELOG.md`, qui est un journal ;
- les skills `.claude/skills/`.

**Limites** :
- Ni `check_app_conformity` ni le nocturne n'ont pu tourner : les verdicts « mesurés » de la
  grille n'ont pas été rejoués, seulement confrontés au code des critères.
- L'historique git de l'environnement commence au 2026-10-10 : les dates antérieures sont lues dans
  les commentaires du code.
- Les frontières de lots coupent `ROUTE` et `ROADMAP` en deux : une contradiction entre leurs deux
  moitiés a pu échapper.

## 3. Volume par document

| Document | Lot | statut perime | constat faux | chiffre perime | reference cassee | ligne decalee | contradiction docs | manque | total |
|---|---|---|---|---|---|---|---|---|---|
| `docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md` | L01, L02 | 33 | 16 | 6 | 7 | 57 | 5 | 1 | **125** |
| `docs/construction/suivi/ROADMAP.md` | L03, L04 | 18 | 8 | 1 | 8 | 46 | 2 | 1 | **84** |
| `docs/construction/suivi/PROJECT_STATUS.md` | L05, L06 | 51 | 4 | 1 |  |  | 2 |  | **58** |
| `docs/construction/architecture/WAMA_APP_CONVENTIONS.md` | L08 | 9 | 11 | 2 | 7 | 4 | 2 | 4 | **39** |
| `wama_lab/cam_analyzer/CAM_ANALYZER_CHAINE_TRAITEMENT.md` | L15 | 6 | 3 |  | 2 | 17 | 1 | 2 | **31** |
| `docs/construction/ia/WAMA_LLM.md` | L10 | 5 | 9 | 1 | 3 | 9 |  | 2 | **29** |
| `docs/construction/mondes/WAMA_DATA_WORLD.md` | L07 | 7 | 8 |  | 3 | 7 |  |  | **25** |
| `docs/construction/architecture/WAMA_MANIFEST_SPEC.md` | L09 | 6 | 7 |  | 2 | 4 |  | 1 | **20** |
| `AGENTS.md` | L14 | 2 | 6 | 5 | 3 | 2 | 1 | 1 | **20** |
| `docs/construction/ia/WAMA_QUALITE.md` | L11 | 9 | 6 | 1 | 2 |  | 1 |  | **19** |
| `docs/construction/ia/WAMA_HARNESS.md` | L10 | 9 | 2 | 1 |  | 4 |  |  | **16** |
| `docs/construction/suivi/REMOVAL_LEDGER.md` | L14 | 7 | 1 |  | 1 | 4 |  |  | **13** |
| `wama/model_manager/PROSPECTION_PIPELINE.md` | L11 | 10 |  |  | 2 |  |  |  | **12** |
| `docs/construction/exploitation/WAMA_COLLABORATION.md` | L13 | 5 | 3 |  | 3 |  | 1 |  | **12** |
| `docs/construction/mondes/WAMA_DATA_FUNCTION_CARDS.md` | L07 |  | 2 | 1 |  | 8 |  |  | **11** |
| `docs/construction/architecture/WAMA_VERIFICATION.md` | L08 | 7 |  |  | 3 |  | 1 |  | **11** |
| `docs/construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md` | L09 |  | 3 | 4 | 1 | 1 |  | 2 | **11** |
| `docs/construction/ia/WAMA_MEMORY.md` | L10 | 1 | 3 |  | 2 | 2 | 2 |  | **10** |
| `docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md` | L13 | 2 | 2 |  | 3 |  | 1 | 1 | **9** |
| `docs/construction/ui/CARD_DESIGN.md` | L12 | 6 | 2 |  |  |  |  |  | **8** |
| `docs/construction/exploitation/PROFILES_PERMISSIONS.md` | L13 | 3 | 4 |  | 1 |  |  |  | **8** |
| `wama/common/README.md` | L14 | 4 | 1 |  | 2 |  | 1 |  | **8** |
| `wama/transcriber/TRANSCRIBER_CORRECTION.md` | L15 | 4 | 2 |  | 1 |  |  | 1 | **8** |
| `docs/construction/architecture/WAMA_MECANISMES.md` | L09 |  | 1 | 1 | 4 |  |  | 1 | **7** |
| `README.md` | L14 |  | 5 | 1 |  |  | 1 |  | **7** |
| `wama_lab/cam_analyzer/README.md` | L15 | 1 | 1 | 1 |  |  |  | 4 | **7** |
| `docs/construction/mondes/WAMA_VISION_COMPLET.md` | L09 | 3 | 1 | 1 |  |  |  | 1 | **6** |
| `docs/construction/ui/INPUT_MODEL_MATCHING.md` | L12 | 3 | 2 |  | 1 |  |  |  | **6** |
| `wama/enhancer/README.md` | L15 | 3 |  | 2 | 1 |  |  |  | **6** |
| `docs/construction/ui/WAMA_VOLETS.md` | L12 | 1 | 2 | 1 | 1 |  |  |  | **5** |
| `docs/construction/ui/MODES_QUEUE_UX.md` | L12 | 2 | 2 |  |  |  | 1 |  | **5** |
| `docs/construction/exploitation/MEDIA_STORAGE_TIERING.md` | L13 | 3 | 1 |  |  |  | 1 |  | **5** |
| `AI-models/models/README.md` | L14 |  | 4 |  |  |  | 1 |  | **5** |
| `docs/construction/ia/WAMA_APPRENTISSAGE.md` | L11 | 1 | 2 |  |  |  | 1 |  | **4** |
| `wama-dev-ai/README.md` | L11 |  | 2 | 1 |  |  |  | 1 | **4** |
| `wama_lab/cam_analyzer/projects/ENA_CASA.md` | L15 | 1 | 1 |  | 1 |  |  | 1 | **4** |
| `wama_lab/face_analyzer/README.md` | L15 |  | 1 |  | 1 |  |  | 2 | **4** |
| `docs/construction/architecture/TRANSCRIBER_REFERENCE_AUDIT.md` | L08 | 2 |  |  |  |  |  | 1 | **3** |
| `patches/README.md` | L14 |  | 1 |  | 1 |  | 1 |  | **3** |
| `AI-models/README.md` | L14 |  | 2 |  |  |  | 1 |  | **3** |
| `wama/imager/README.md` | L15 |  | 2 |  |  |  | 1 |  | **3** |
| `docs/construction/mondes/STUDIO_VISION.md` | L09 |  |  |  |  | 1 |  |  | **1** |
| `docs/construction/ui/INSPECTOR_DETAIL_FIELDS.md` | L12 |  | 1 |  |  |  |  |  | **1** |
| `docs/construction/ui/BATCH_FORMAT.md` | L12 | 1 |  |  |  |  |  |  | **1** |
| `docs/construction/exploitation/LICENSING.md` | L13 |  | 1 |  |  |  |  |  | **1** |
| `CLAUDE.md` | L14 |  |  |  |  |  |  | 1 | **1** |
| `wama/common/backends/vendor/README.md` | L14 |  |  |  |  |  |  | 1 | **1** |
| **Total** | | **225** | **135** | **31** | **66** | **166** | **28** | **29** | **680** |

*(Comptes tirés automatiquement des tableaux des lots ; un écart cité deux fois, sous deux types,
compte deux fois. Le chiffre dit l'ordre de grandeur, pas une mesure au sens de la doctrine.)*

## 4. Par où commencer — l'ordre recommandé

### P1 — Ce qui fait COMMETTRE une erreur à la session suivante (à traiter d'abord)

Ce sont des gestes prescrits ou des constats de doctrine, lus par toute session en début de
travail.

1. **`WAMA_APP_CONVENTIONS.md` prescrit des gestes périmés (L08).** Deux d'entre eux sont
   nuisibles :
   - **§9.8** : câbler `.batch-start-btn` dans l'app provoque un **double POST**, car
     `queue-actions.js:693` tient déjà les actions de lot ;
   - **§15, l.2109** : le mémo écrit encore `os.environ['HF_HUB_CACHE']`, la formule qu'`AGENTS.md`
     a abandonnée et que `tests_hf_cache_routing.py:66` (budget 0) interdit.

   Les autres sont remplacés par des briques communes : `buildCard` côté client (§5.2), `#startAllBtn`
   dans le volet (§21), `TOOL_ICONS` dans `home.html` et l'ordre de `header.html` à la main (§16),
   wrapper `_console` recopié (§12.4).
2. **`AGENTS.md` (L14) et ses constats au présent :**
   - « RAG pas encore implémenté » (l.46), alors qu'il est livré dans `wama/common/memory/` ;
   - jalon 12 de la mémoire dit restant, alors qu'il est fait ;
   - adoption de `select_model` : « reste describer + anonymizer » est faux ;
   - `settings_modal_cycle` à « 9/10 » (l.648), contre 10/10 plus bas (l.931) ;
   - budgets de nommage 2653/132/1296, contre **2627/132/1289** dans
     `check_identifier_language.py:117-130` ;
   - « 100 critères », alors que le checker en déclare **113**
     (`conformity_checker.py:2409-2811`) ;
   - renvoi vers un `§S` de la ROUTE qui n'existe pas (l.69) ;
   - Wan dit `DEPRECATED` (L15).
3. **`AI-models/README.md` et `AI-models/models/README.md` (L14)** prescrivent :
   - « download on first use » ;
   - des `os.environ` dans le code ;
   - un script absent.

   Tout cela contredit la règle « par la route ». Mieux vaut **réécrire** ces deux fichiers que de
   les corriger ligne à ligne.
4. **`INFRA_WSL_VS_WINDOWS.md` « Piège n°2 » (L13)** : il affirme que `staticfiles/` n'est pas
   servi en DEBUG. C'est faux pour le serveur réel : gunicorn tourne avec `DEBUG=True`, et
   `wama/urls.py:84` sert `staticfiles/`. Le doc contredit aussi `AGENTS.md`, qui a raison.

### P2 — Les tableaux de pilotage et les points d'entrée de reprise

**C'est le défaut le plus répandu du corpus : les blocs datés récents sont justes, mais les
tableaux d'état, les titres de section et les listes de restes, écrits plus tôt, n'ont pas suivi.**
Une session qui lit le tableau avant le bloc reprend un chantier fini.

- **ROUTE §10.6 (L02)** :
  - préambule « modèle de conception, aucun code écrit » ;
  - table des marches au point 11 : P2 et P3 sans statut ; P6 « restent à un seul process :
    describer, reader, converter », alors que les dix apps déclarent un pipeline depuis le 13/10 ;
    P7a ne marque pas R2.
- **ROUTE §11 « Trous prioritaires » (L02)** :
  - #2 `settingsModal` « 2/10 », alors qu'il est à 10/10 ;
  - #4 partiels « 1/10 », alors que l'émission est quasi générale ;
  - #6, #14, #32 et #34 restent ouverts alors qu'ils sont livrés.
- **ROUTE F4b (L01)** : toujours titré 🔴 « la DERNIÈRE JAMBE manquante », alors que les 9 apps à
  modèles déclarent `options_source="catalog"`. Les états de facette F5 à F8 citent des trous
  fermés.
- **PROJECT_STATUS (L05, L06)** :
  - « Ordre de reprise recommandé » (l.759-765) envoie vers `wama/rag/`, qui n'existe pas ;
  - les titres de §1, §2bis, §6, §7, §14, §17, §18 et §20 sont périmés ;
  - 25 restes ⏳ des blocs récents sont faits, dont `--mcp-config` (l.19326) ;
  - les mentions « non poussé » des blocs d'octobre sont fausses : tout est sur `origin/dev`.
- **WAMA_HARNESS (L10)** :
  - axe 4 « 0 sous-agent », axe 10 « contexte non borné », écart 8 « aucun flux » ;
  - §9 « aucun chantier commencé », alors que les chantiers 1 et 5 sont soldés, le 2 en cours et
    le 4 câblé.
- **WAMA_QUALITE §0, M2, M3, M6, §5 et §7 (L11)** sont restés au 2026-09-16 : « mesure interne
  vide », « M6 : rien ». L'étage de mesure interne est pourtant branché depuis le 14/10.
- **WAMA_MEMORY (L10)** : l'en-tête dit « jalon 12 dû », ce que son propre §10 contredit.
- **WAMA_VERIFICATION §6 (L08)** : les phases restent 🔄/⏳ alors que le §3 du même document les
  clôt.

### P3 — Les livraisons récentes que plusieurs docs n'ont pas suivies

| livraison | date | docs qui disent encore le contraire |
|---|---|---|
| **Porte de confidentialité avant-cloud** (`wama/common/privacy/gate.py`, Presidio), branchée dans `llm_utils.py:827` et `claude_code.py` | 2026-10-28 | ROADMAP H2.4, §16.2, §16.3 Q2, §24.8, §24.9 (L03, L04) ; VISION §12.1 (L09) ; PROJECT_STATUS (L05) |
| **MCP de l'abonnement Claude Code** (`--mcp-config`, `claude_code.py:215`) | 2026-10-23 | ROADMAP §8d étape 5 : titre « ⏳ », « Discord figé » (L03) ; PROJECT_STATUS l.19326 (L06) ; WAMA_LLM « Discord figé » (L10) |
| **`settingsModal` 10/10** (le transcriber porté) | octobre | AGENTS.md:648, ROUTE F3 l.176 et §11 #2, `wama/common/README.md`, TRANSCRIBER_CORRECTION §10.5 (L01, L02, L14, L15) |
| **RAG / mémoire** (`wama/common/memory/`, injectée par `prompt_pipeline.py:31-70`) | sept. | AGENTS.md:46, CONVENTIONS §13, prose de MECANISMES, PROJECT_STATUS §1 et ordre de reprise (L05, L08, L09, L14) |
| **Les dix apps déclarent un pipeline** (`register_app_pipeline`) | 2026-10-13 | ROUTE §10.6 table des marches P6 (L02) |
| **Recalage ortho 2b appliqué côté serveur** (`ego_pose.py:408`) | 2026-09-28 | CAM_ANALYZER_CHAINE, cam_analyzer/README, ENA_CASA (L15) |
| **Garde de l'ajout de capacité** par `can_manage_registries` (et non plus `AppAccessPolicy.min_tier`) | 2026-10-14 | WAMA_HARNESS écart 1(a), WAMA_LLM §2ter (L10) |
| **Marches BIND A→E** (référentiel temporel, `Timestamper`, `wama-axis.js`) | sept. | WAMA_DATA_WORLD §6.1, §8.1-8.3 (L07) |

### P4 — Identifiants renommés que la doc cite encore sous leur ancien nom

- **WAMA_DATA_WORLD §9ter à §13 (L07)** : environ 80 lignes portent des noms d'avant la décision
  D28 (`charger`, `Ecart`, `autour`, `segment_autour_event`…). Le code est en anglais depuis le
  2026-08-26.
- **PROSPECTION_PIPELINE (L11)** : 22 identifiants renommés le 2026-08-29. Le rapport donne la
  table de correspondance.
- **ROADMAP (L03)** : plusieurs identifiants ont changé :
  - `aptitudes_of` et `options_aptitudes` sont devenus `abilities_of` et `options_abilities` ;
  - `COMPOSANTS_DECLARES` est devenu `composants_declares()` ;
  - `transcriber_backends_info` a été retiré (R86) ;
  - `chat_provider_choices`.

### P5 — Les blocs générés à régénérer (ne pas corriger à la main)

- **`WAMA_MECANISMES.md` (L09)** : il manque au bloc les 3 mécanismes ajoutés le 28/10, et ses
  comptes se contredisent. Le bloc semble avoir été retouché ou fusionné à la main. Relancer
  `doc_facts`.
- **`WAMA_DATA_WORLD §0` (L07)** : il est généré depuis `wama_data/modules.py`. La phrase
  « `ParamSpec` rendus seulement par le Studio, par son propre formulaire » est fausse depuis
  `f1c3d4e1` (le Studio passe par `WamaParams`). Il faut corriger la source dans `modules.py`, puis
  régénérer.

### P6 — Les 166 lignes décalées

Elles sont purement mécaniques : chaque lot les regroupe dans une sous-table qui donne la ligne
citée et la ligne actuelle. Elles se concentrent dans la ROUTE (57), la ROADMAP (46) et
CAM_ANALYZER_CHAINE (17).

**Recommandation d'outillage**, à décider par Fabien : `check_docs` ne détecte une ligne périmée
que si elle dépasse la fin du fichier. Le contrôle « symbole cité loin de la ligne citée » du
script d'audit, à ±12 lignes, en attrape 232, dont 137 hors passages excusés. Deux options :
- le porter dans `check_docs` ;
- préférer dans la doc la forme `fichier::symbole`, que ce même contrôle vérifie, à
  `fichier:ligne`, qui dérive à chaque édition.

## 5. Défauts du CODE repérés au passage (hors du sujet doc — à trier séparément)

| constat | preuve | source |
|---|---|---|
| **face_analyzer, mode vidéo** : le choix de backend d'émotion envoyé par l'interface est ignoré. La configuration de session ne lit pas `emotion_backend`, alors que le chemin temps réel le lit. *Comportement à confirmer dans l'interface.* | `wama_lab/face_analyzer/views.py:113-119`, à comparer avec `:760` | L15, revérifié |
| **`coqui_backend.py` pose `os.environ['TTS_HOME']` dans un backend**, contre la règle d'`AGENTS.md` (« la poser UNE FOIS dans `settings.py` — jamais dans un backend ») | `wama/common/backends/coqui_backend.py:62` | L14, revérifié |
| Docstring périmée de `wama/common/memory/__init__.py:11-13` (« AUCUN APPELANT … Hook B no-op ») | appelants `prompt_pipeline.py:56`, `tool_api.py` | L08 |
| Le Reader décrit « (Tesseract, PaddleOCR, EasyOCR) », ce qui contredit `reader/utils/model_config.py:3-6` | `app_registry.py:1686, 2172`, `manifests/apps/reader.json:1583` | L14 |
| Commentaire `app_modes.py:291` : « l'aperçu SSE de la card reste l'affordance temps réel », alors que la route SSE est retirée | `wama/common/utils/app_modes.py:291` | L12 |
| `fits_full_gpu` toujours sans appelant (⏳ R46) | `model_manager/services/memory_manager.py:401` | L11, L14 |

## 6. Comparaison WAMA / n8n (mise à jour)

> Remplace la comparaison faite en conversation le 23/10, qui reposait en partie sur `main`
> (figé au 12/10) et sur des constats de la doc que le code a dépassés. Les faits sur n8n viennent
> de sources web secondaires (versions 1.x/2.x discordantes) : à revérifier sur la doc officielle
> avant de les consigner dans `WAMA_HARNESS.md` ou `VISION §11.3`.

### 6.1 Ce qui a changé depuis la première comparaison (mesuré)

| point | première comparaison | état réel sur `dev` | preuve |
|---|---|---|---|
| Moteur d'exécution | « trois moteurs, trois vocabulaires » (cité du préambule de ROUTE §10.6) | **faux** : un vocabulaire d'états, une table d'exécution `ProcessRun` écrite par la file, le Studio et le cam_analyzer, un moteur de pipeline par app | `wama/common/services/process_pipeline.py`, `wama/common/models.py` (`ProcessRun`, `JOB_*`) |
| Nœuds du Studio | « pas de nœud au grain fin » (sous-entendu) | **faux** : nœuds intégrés, nœuds d'app, nœuds fonction pures ET sous-process d'app (grain modèle, façon ComfyUI) | `wama/studio/services/palette.py:24-81`, `wama/transcriber/function_specs.py` |
| Déclencheurs utilisateur | « aucun, seulement la maintenance Celery Beat » | **faux** : `ScheduledAction` — un geste (outil `tool_api` + arguments) programmé à une date, « dès que possible », « en heures creuses » ou en automatique, avec récurrence RFC 5545, exécuté par la porte `execute_tool` ; flux `.ics` abonnable | `wama/common/models.py` (`ScheduledAction`, `CalendarFeed`), `wama/common/services/scheduled_actions.py:544-594` (récurrence `rrulestr`, envoi par `tool_api.execute_tool`) |
| Pipeline du Studio pilotable de l'extérieur | non évoqué | **oui** : `run_studio_pipeline` est un outil — appelable par l'assistant, l'API et tout client MCP. Le modèle `ScheduledAction` accepte tout outil ; l'interface de programmation cible aujourd'hui le lancement d'une card (`scheduled_actions.start_tool_for`) — programmer un pipeline du Studio n'est pas vérifié | `wama/tool_api.py:1769`, `scheduled_actions.py:312` |
| MCP de l'abonnement Claude Code | « pas câblé » | **câblé le 2026-10-23** : `--mcp-config` + `--strict-mcp-config`, serveur `wama`, jeton par l'environnement, outils `mcp__wama__*` sous la porte `execute_tool` | `wama/common/services/claude_code.py:75-81, 215-223`, commit `087ac79a` |
| Assistant | agent outillé | + **sous-agents** (`delegate`) réglables « auto + curseur + manuel », règles d'effort proportionné | `wama/common/services/assistant_engine.py:1271`, commit `3b497863` |

### 6.2 Ce qui reste vrai

| axe | n8n | WAMA |
|---|---|---|
| Connecteurs vers d'autres services | centaines de nœuds natifs, nœud HTTP, nœuds MCP client/serveur | un canal (`wama/gateway/core.py:38`, `CHANNELS = ('discord',)`) ; stockages distants par rclone (Nextcloud, WebDAV, SMB, Drive, OneDrive) ; **pas encore de client MCP vers des serveurs externes** (`mcp_client.py` ne connaît que les surfaces `wama`/`wama-dev`) |
| Déclencheurs ÉVÉNEMENTIELS | webhooks, interrogation, formulaires, arrivée d'un mail | **aucun** : la programmation est TEMPORELLE (`ScheduledAction`) ; recherche de `webhook` dans `wama/`, `wama_data/`, `wama_lab/` : 0 hors tests |
| Contrôle de flux du graphe | IF/Switch, boucles, fusion, branche d'erreur | DAG acyclique, `NODE_KINDS = ('source', 'sink', 'app', 'function')` (`pipeline.py:42`), pas de nœud conditionnel |
| Exécution du graphe | parallélisme de workers, reprise, nouvelles tentatives | séquentielle (`wama/studio/tasks.py:423`, `for node in order`), premier échec = run en échec, pas de `STALE` au Studio |
| Sous-workflow | natif | nœud `pipeline` (sous-graphe) toujours ⏳ (`pipeline.py:40-42`) |

### 6.3 Ce qui distingue WAMA (inchangé, renforcé)

- **Une déclaration, plusieurs projections** : le `ProcessSpec` d'une app est à la fois une étape
  de sa card et un nœud du Studio ; les ports dérivent du catalogue ; un outil est à la fois geste
  de l'assistant, endpoint d'API, outil MCP et action programmable — **par la même porte**
  (`execute_tool`). Aucun outil comparé (n8n, ComfyUI, KNIME, Galaxy) n'a cette identité entre
  file, graphe, agent et calendrier.
- **Deux grains sur un même canvas** (app entière / sous-process), dérivés des mêmes déclarations.
- **IA là où elle est nécessaire** : génération d'UI et d'apps déterministe (schémas, `codegen`),
  l'IA réservée aux tâches qui l'exigent ; sous-agents proportionnés à la demande.
- **Gestion des modèles et du GPU** (catalogue, sélection VRAM-aware, installation par la route,
  gouverneur de ressources) — hors du périmètre de n8n.

### 6.4 Conséquence pratique (révisée)

L'intégration n8n ↔ WAMA est désormais **plus simple qu'en API REST** : WAMA est serveur MCP, et
n8n dispose de nœuds client MCP (à vérifier sur sa doc). Un workflow n8n peut donc appeler
directement `run_studio_pipeline` ou n'importe quel outil `add_to_<app>` sous les droits du
jeton de l'utilisateur. Ce que n8n apporterait : les **déclencheurs événementiels** et la
**publication multiplateforme** (le chantier « sortie validée » évoqué le 23/10). Ce que WAMA garde
seul : le lecteur de connaissances de laboratoire (client MCP en lecture, ouvert par orgUnit,
borné par `cloud_hosting_max`), cible arrêtée avec Fabien le 23/10.

## 7. Fichiers de ce dossier

| fichier | contenu |
|---|---|
| `L01.md` | `WAMA_APP_GENERATION_ROUTE.md`, l.1-3872 (§1, facettes F1-F8, §S2bis) |
| `L02.md` | `WAMA_APP_GENERATION_ROUTE.md`, l.3873-fin (§S2ter, §10.4-10.6, §11) |
| `L03.md` | `ROADMAP.md`, l.1-3914 (frise, horizons, §0-§16) |
| `L04.md` | `ROADMAP.md`, l.3915-fin (§17-§29) |
| `L05.md` | `PROJECT_STATUS.md`, en-tête et chapitres §0-§42 |
| `L06.md` | `PROJECT_STATUS.md`, blocs §REPRISE, PENDING, points d'entrée (priorité octobre) |
| `L07.md` | `WAMA_DATA_WORLD.md`, `WAMA_DATA_FUNCTION_CARDS.md` |
| `L08.md` | `WAMA_APP_CONVENTIONS.md`, `TRANSCRIBER_REFERENCE_AUDIT.md`, `WAMA_VERIFICATION.md` |
| `L09.md` | `WAMA_MANIFEST_SPEC.md`, `WAMA_MANIFEST_ARCHITECTURE.md`, `WAMA_MECANISMES.md`, `WAMA_VISION_COMPLET.md`, `STUDIO_VISION.md` |
| `L10.md` | `WAMA_LLM.md`, `WAMA_HARNESS.md`, `WAMA_MEMORY.md` |
| `L11.md` | `WAMA_QUALITE.md`, `WAMA_APPRENTISSAGE.md`, `PROSPECTION_PIPELINE.md`, `wama-dev-ai/README.md` |
| `L12.md` | `docs/construction/ui/*` (7 docs ; `WAMA_SCENES_3D` sans écart) |
| `L13.md` | `docs/construction/exploitation/*` (5 docs ; `LICENSING` quasi à jour) |
| `L14.md` | `AGENTS.md`, `CLAUDE.md`, `README.md`, `wama/common/README.md`, `REMOVAL_LEDGER.md`, `patches/`, `AI-models/`, `vendor/` READMEs |
| `L15.md` | cam_analyzer (CHAINE, README, ENA_CASA), `TRANSCRIBER_CORRECTION.md`, READMEs enhancer / imager / face_analyzer |
| `mecanique.tsv` | les 1 952 candidats bruts de la passe mécanique (colonne `excuse` : journal / intentionnel) |
| `BRIEF.md` | le brief donné aux 15 lots — pour rejouer l'audit dans un mois sur le même protocole |
| `doc_refs.py.txt` | le script de la passe mécanique (autonome, sans Django). Livré en `.txt` : ses identifiants sont en français et ne doivent pas entrer dans le budget de `check_identifier_language`. Pour le relancer : le copier hors du dépôt en `.py`, puis `python doc_refs.py <racine> <sortie.json>` |
