# UI_MECHANISMS_CONSOLIDATION.md — Inventaire des mécanismes de génération d'UI (TÂCHE 1)

> **But** : avant d'uniformiser les 10 apps généralistes en *schéma-driven* (→ manifests → chaîne
> de génération), recenser **empiriquement** les chemins CONCURRENTS de génération d'UI, désigner
> **une** référence par axe, et poser l'**ordre de convergence exécutable**.
> **Contraintes** : route existante, **zéro réinvention**, **zéro hardcoding/pansement**, uniformité.
> **Méthode** : tout ci-dessous est vérifié par `grep`/`read` (pas de mémoire). Date : 2026-07-01.

**Les 10 apps généralistes** : transcriber · synthesizer · describer · reader · converter · imager ·
anonymizer · enhancer · avatarizer · composer.

---

## 0. Résumé exécutif — l'état réel

Le **registre de modèles est déjà unique** (`ModelRegistry` + `ModelInfo`, un seul patron
`_discover_<app>_models()`). Le vrai gap n'est PAS là : il est dans **la génération des surfaces
d'édition** (modale item/batch + volet inspecteur) et dans **le vocabulaire des capacités**.

Correction empirique de deux idées reçues (issues de sessions à contexte chargé) :

1. **`WamaInspector.init` / `initFromSchema` ne sont PAS en concurrence avec `WamaParams.render`.**
   Ce sont **deux couches** : `WamaParams.render` **rend les champs** ; `WamaInspector` **câble** le
   volet (sélection de card, read/apply, actions, save). `initFromSchema` = variante de câblage qui
   **dérive** read/apply du schéma (moins de code) ; `.init` = câblage à callbacks **explicites**.
2. **`show_if` n'est pas un anti-pattern.** Déclaré dans `params.py` et piloté par la **valeur d'un
   autre champ** (ex. converter `media_type`, enhancer `engine`), c'est le mécanisme déclaratif
   **correct**. L'anti-pattern (cf. [[feedback_ui_from_model_capabilities]]) est le `show_if`
   **hardcodé en JS pour masquer un champ selon le MODÈLE** — remplacé par capacités-modèle.

**Le pattern le plus abouti n'est pas le transcriber seul** : ce sont **describer & reader**, qui
génèrent les champs des DEUX surfaces via `WamaParams.render` (`context:'panel'` **et** `'item'`) ET
câblent via `initFromSchema` (zéro champ hand-built, zéro callback explicite). Le transcriber génère
aussi les champs via `WamaParams` mais câble via `.init` explicite (plus de code). → **La cible de
convergence = pattern describer/reader** (transcriber reste la référence *sémantique*).

---

## 0bis. CARTE DES SOURCES DE VÉRITÉ (le « manifeste » réel de la chaîne de génération)

> Audit demandé par Fabien (2026-07-01) : ne pas se contenter d'observer *le comportement* de l'UI,
> mais **remonter TOUTES les sources de vérité** qui alimentent la génération. La chaîne existe déjà et
> contient tout (filtrage voix, gestion modèles, fichiers I/O) — **Transcriber est la plus avancée**.
> Le travail n'est pas de créer des mécanismes mais de **compléter les catalogues/registres** et de
> **remonter le legacy vers sa source**. Rien à « retirer ».

### A. Manifeste APP-LEVEL (une déclaration par app)

| # | Source de vérité | Fichier | Contenu | Consommateurs | État |
|---|---|---|---|---|---|
| A1 | **`APP_CATALOG`** | `common/app_registry.py` | label/icône/couleur, `input_extensions`, `input_types`, `output_types`, `batch_type`, `has_batch/url/youtube`, **matrice `conventions`**, `description_long` | nav, upload-validation, FileManager, `studio_node_ports` (méta-app), inspecteur `/apps/`, `get_conformity_summary()` | ⚠️ **`conventions` PÉRIMÉE** (voir §0ter) |
| A2 | **`APP_MODES` + `INPUT_TYPES`** | `common/utils/app_modes.py` | domaines→modes→inputs (+ ports de référence) | `WamaModes` (onglets/switch/champs), `studio_node_ports` | Déclaré : imager, enhancer, synthesizer, transcriber, anonymizer (5/10) |
| A3 | **`params.py`** | `<app>/params.py` | schéma `Param` (item/panel/batch), `dom_id`, `show_if`, `options_source`, `help_source/fallback` | `WamaParams.render`, `WamaInspector.initFromSchema` | **10/10 EXISTENT** (P0 fait — vérifié empiriquement 2026-07-11) MAIS imager+anonymizer ORPHELINS (aucun consommateur WamaParams) et synthesizer ne ponte que les `dom_id` |
| A4 | **`PROMPT_TARGETS`** | `common/utils/app_metadata.py` | champs-prompt + `kind` + modèle source | PromptPipeline, assistant, méta-app | imager, anonymizer, composer, assistant ; synthesizer=∅ (volontaire) ; describer=interne |
| A5 | **`tool_api.py`** | registre CENTRAL `wama/tool_api.py` (PAS de fichier par app) | fonctions exposées à l'assistant/méta-app | AI-Assistant, méta-app | TOOL_REGISTRY couvre les **10 apps** (avatarizer inclus — vérifié 2026-07-11 ; « sauf composer=False » était périmé) |

### B. Catalogue MODEL-LEVEL (une entrée par modèle) — « le registre »

| # | Source de vérité | Fichier | Contenu | Consommateurs | État |
|---|---|---|---|---|---|
| B1 | **`ModelRegistry._discover_<app>_models()`** | `model_manager/services/model_registry.py` | construit `ModelInfo` + **dict `capabilities`** = LA source | `ModelSyncService` → AIModel | ⚠️ **clés `capabilities` hétérogènes** par app (§0ter) |
| B2 | **`AIModel`** (DB, synced) | `model_manager/models.py` | `model_key`, `model_type`, `source`, **`capabilities`** (source UNIQUE filtrage voix/langues + sélection tâche + compat I/O + desc dynamique), `description`/`_short`, `vram`, `extra_info['eta']` | `_resolve_model` (prompt), `WamaModelCaps`, `WamaModelHelp` | ⚠️ `ModelSource.choices` **manque composer/reader/converter** |
| B3 | `model_config.py` / flags backend | `<app>/utils/model_config.py`, `backends/base.py` | déclarations brutes (supports_diarization/timestamps…) alimentant la découverte | `_discover_*` | Riche pour transcriber ; inégal ailleurs |
| B4 | **ETA** : `AIModel.extra_info['eta']` (a-priori) + `ModelRuntimeStat` (appris/hw) | `model_manager/models.py` | seeding ETA hardware-aware | `WamaEta` | ⚠️ composer : facteurs ETA encore **inline `data-*`** (non migrés ici) |

### C. Couche de RENDU (consommateurs, PAS des sources de vérité)
`WamaParams` (champs ← A3) · `WamaInspector` (volet ← A3) · `WamaModes` (onglets/modes ← A2) ·
`WamaModelCaps` (caps→UI ← B2) · `WamaModelHelp` (desc ← B2) · `WamaDetails`/`to_dict` (volet /apps/ ← A1).
**La règle manifeste** : ces consommateurs ne doivent lire QUE A/B, jamais du hardcode. Chaque hardcode
restant (ETA `data-*` composer, voix hand-built) = **une métadonnée à remonter vers A/B**, pas à supprimer.

---

## 0ter. Ce qui rend les sources de vérité INCOMPLÈTES (le vrai chantier « catalogue »)

1. **`APP_CATALOG.conventions` périmée** — les flags `inspector`/`modes`/`layout` ne sont `True` que pour
   **transcriber**, alors que l'audit empirique montre : inspecteur (initFromSchema) sur describer, reader,
   enhancer, synthesizer, avatarizer, composer ; modes sur enhancer, imager. Donc `get_conformity_summary()`
   **sous-déclare la réalité**. → Rendre le code conforme ET **remettre ces flags à jour** (ils doivent
   PILOTER, pas retracer). C'est une SoT qui ment aujourd'hui.
2. **Vocabulaire `capabilities` hétérogène** (B1→B2) — imager `{modalities,task}`, transcriber
   `{multilingual,supports_timestamps,native_diarization,supports_hotwords,languages_count}`, synthesizer
   `{supports_cloning}`, anonymizer `{task,classes,text_promptable}`, enhancer `{task,modalities,params}`.
   Sans convention commune, **`WamaModelCaps` ne peut pas piloter l'UI génériquement**. → normaliser le
   vocabulaire (documenté dans `AIModel.capabilities` : `languages`, `supports_*`, `classes`, `task`,
   `modalities`, `params`) et compléter chaque `_discover_*`.
3. **`ModelSource.choices` incomplet** — manque `composer`, `reader`, `converter` (la découverte écrit
   pourtant ces clés) → entrées cataloguées hors-enum (admin/validation aveugles).
4. **`description_short`/`description` non renseignés** pour la plupart → `help_source` (WamaModelHelp)
   inutilisable, d'où le repli `help_fallback` inline (enhancer, reader). → peupler au catalogue.
5. **ETA a-priori non peuplé** — `extra_info['eta']` vide pour composer ⇒ facteurs restés en `data-*`
   template. → migrer `gen_factor`/`overhead` vers `extra_info['eta']`, `WamaEta` les lira.

> **Conséquence pour P1** : porter une modale hand-built = (a) remonter ses métadonnées-widget vers A/B
> (ETA→B4, voix→B2.capabilities), (b) compléter le catalogue, (c) laisser `WamaParams`/`WamaModelCaps`
> rendre depuis la source. La modale devient alors 100 % générée SANS rien perdre.

---

## 0quater. Les deux MANAGERS (tracé à la demande de Fabien) + critique de consolidation

### App Manager — le tracker d'uniformisation
`common/views.py::apps_catalog_view` → `common/templates/common/apps.html`, rendu depuis **`APP_CATALOG`**
+ **`get_conformity_summary()`** (score de conformité/uniformisation par app). Exposé JSON par
`api_apps` (consommé par la méta-app studio). Endpoints frères : `api_voices` (SoT voix, `options_source='voices'`),
`api_app_modes` (SoT modes → WamaModes).
> **Boucle fermée** : le niveau d'uniformisation qu'affiche l'app manager n'est fiable QUE si
> `APP_CATALOG.conventions` l'est. Or elle est périmée (§0ter.1) ⇒ **le tracker sous-déclare
> l'avancement réel**. Réparer `conventions` = réparer le tracker.

### Model Manager — catalogue + automatisation (couches)
| Couche | Fichiers | Rôle |
|---|---|---|
| **Entrée / automatisation** | `prospector.py`, `prospect_agents.py`, `prospect_ollama.py`, `model_installer.py`, `update_checker.py`, `file_watcher.py` | Découverte auto (HF/GitHub/Ollama), installation, MAJ, veille disque — **l'automatisation « on fournit un accès, ça catalogue »** |
| **Découverte → catalogue** | `model_registry.py` (`_discover_*` → `ModelInfo`+`capabilities`) → `model_sync.py` → **`AIModel`** (DB) | B1→B2 |
| **Sélection / exécution** | `model_selector.py` (VRAM, granularité variante), `common/backends/manager.py` (cycle de vie backend, granularité moteur), `eta_estimator.py` | Deux couches **complémentaires** (pas redondantes) |
| **Mémoire VRAM** | `memory_manager/monitor/tracker/cleaner.py` | Runtime |

### Critique — ce qui est « éclaté » (à consolider)

| # | Divergence (vérifiée) | Preuve | Consolidation |
|---|---|---|---|
| **C1** | **Capacité modèle éclatée sur 2 champs `AIModel`** : `capabilities` (lu par WamaModelCaps UI + `_resolve_model` prompt) **vs** `extra_info` (lu par `model_selector._supports` : `requires`/`classes`, + porte `eta`) | `model_selector.py` lit `ei.get('classes')` ; `wama-model-caps.js` lit `.capabilities` | **`capabilities`** = faits de capacité (langs, supports_*, classes, task, modalities) ; **`extra_info`** = opérationnel (eta a-priori, install, requires runtime). Faire lire `model_selector` depuis `capabilities`. |
| **C2** | Vocabulaire `capabilities` **hétérogène** : `languages`(array) vs `languages_count`(int) vs `multilingual`(bool) ; keys ad-hoc par app | §0ter.2 | Vocabulaire canonique unique, documenté dans `AIModel` + module de constantes partagé. |
| **C3** | `ModelSource.choices` manque **composer/reader/converter** | `models.py` vs `_discover_composer/reader_models` | Compléter l'enum (migration légère). |
| **C4** | `APP_CATALOG.conventions` **périmée** ⇒ app manager sous-déclare | §0ter.1 | Remettre à jour + en faire le pilote. |
| **C5** | **Descriptions multi-sources** : `APP_CATALOG.description` (one-liner) + `_DESCRIPTION_LONG` (fusionné) + `AIModel.description`/`_short` | app_registry.py, models.py | Tolérable (app-level vs model-level), mais documenter la frontière. |

> **NON-divergences confirmées** (pour ne pas les « corriger » à tort) : `BackendManager` vs
> `model_selector` = couches propres ; `WamaInspector`(câblage) vs `WamaParams`(rendu) = couches propres.

### Plan B1/B2 (premier maillon choisi par Fabien — normaliser le catalogue)
1. **Vocabulaire `capabilities` canonique** — définir + documenter (`languages:[]`, `supports_{diarization,timestamps,hotwords,streaming,cloning}`, `classes:[]`, `task`, `modalities:[]`, `context_length`) dans un module partagé + docstring `AIModel.capabilities`.
2. **Normaliser chaque `_discover_<app>_models()`** pour émettre ce vocabulaire (remplacer `languages_count`/`multilingual` par `languages`, etc.) — sans changer la structure, juste les clés/complétude.
3. **Compléter `ModelSource.choices`** (composer, reader, converter) — migration.
4. **Réconcilier C1** : déplacer les faits de capacité vers `capabilities` ; pointer `model_selector._supports` sur `capabilities` (compat : lire les deux le temps de la transition).
5. **Peupler** `description_short` + `extra_info['eta']` là où c'est bon marché (débloque `help_source` et l'ETA composer).
6. **Re-sync** (`ModelSyncService.full_sync`) + vérif : `WamaModelCaps` filtre voix/langues sur le vocabulaire normalisé, identique à aujourd'hui.

---

## 0quinquies. Pilier transverse — traduction / enrichissement / RAG (À GÉNÉRALISER, jamais par app)

> Rappel Fabien (2026-07-01) : ne pas oublier, dans la chaîne de génération, la **traduction
> intelligente entrée/sortie**, le **RAG généralisé** (connexion médiathèque) et **l'enrichissement de
> prompt automatisé** — **généralisés**, pas spécifiques aux apps. Vérifié : c'est un pilier DÉJÀ bâti,
> centralisé et métadonnée-driven (`PROMPT_PIPELINE.md`). Une app **déclare** (`PROMPT_TARGETS`) ; la
> pipeline traduit/enrichit/complète/RAG — **zéro code par app**.

### Sources de vérité du pilier (à ajouter à la carte §0bis)
| # | SoT | Fichier | Rôle |
|---|---|---|---|
| A4 (élargi) | `PROMPT_TARGETS` | `common/utils/app_metadata.py` | déclare, par app, champs-prompt + `kind` (+ `enrich`, `when`, `reference_field`, `source`) |
| A6 | Pipeline | `common/utils/prompt_pipeline.py` | orchestre détection langue → routing → traduction → enrichissement → référence (+ hook RAG commenté) |
| A7 | Décideur langue | `common/utils/lang_routing.py` | `routing_for_model(caps, type, in, out)` → {direct, input/output_translate, pivot} ; `_TYPE_LANG_DEFAULT` |
| A8 | Traducteur | `common/utils/translator.py` | `TranslatorService` (translategemma/Ollama), cache, glossaire do-not-translate |
| A9 | Enrichissement | `common/utils/prompt_enrichment.py` | `enrich_generative()` — OFF par défaut (`WAMA_PROMPT_ENRICH`) |
| A10 | Référence/RAG | `common/utils/reference_comprehension.py` (+ `apply_rag` à venir) | compréhension multimodale ; **point de branchement RAG = l'étape enrich** |
| **Driver** | **`AIModel.capabilities['languages']`** (B2) | — | **décide si/dans quel sens traduire** — d'où le lien direct avec B1/B2 |

### État (ce qui est bâti vs à faire)
- ✅ **Traduction ENTRÉE** (user→modèle, direct si natif), **enrichissement** (OFF), **référence** : bâtis.
- 🟠 **Traduction SORTIE** (résultat→langue choisie par l'user) : logique présente dans `lang_routing`
  (`output_translate`/`output_pivot`) mais **câblage UI générique par-run à faire** (déclarer une
  capacité commune « langue de sortie » + l'appliquer post-génération).
- 🟠 **Couverture `PROMPT_TARGETS`** partielle (imager/anonymizer/composer/assistant ; describer=interne ;
  synthesizer=∅ volontaire) → compléter là où pertinent.
- ⏳ **RAG généralisé** : différé (Fabien 2026-06), archi anticipée — branchement = étape `enrich`,
  ChromaDB, **héritage université→labo→équipe→individuel = même pattern que batch→item**, opt-in RGPD.

### Principe de généralisation (invariant manifeste)
Les trois (traduction, enrichissement, RAG) s'injectent dans **UNE** pipeline déclarée par
`PROMPT_TARGETS` — **aucune surface nouvelle par app**. Toute app qui a un champ-prompt le **déclare**
et hérite du pilier. → **B1/B2 (peupler `capabilities['languages']`) est la fondation de la traduction**
(aujourd'hui repli par type ; précis dès que les modèles déclarent leurs langues).

---

## 1. Tableau maître — conformité par app (7 axes)

Légende : 🟢 conforme cible · 🟠 partiel · 🔴 absent · — non applicable (variante déclarée)

| App | A. params.py | B. Modale `WamaParams` `item` | C. Volet : champs `WamaParams` `panel` | D. Câblage volet | E. `WamaModelCaps` | F. `show_if` déclaratif | G. `WamaModes` |
|-----|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **describer** | 🟢 | 🟢 | 🟢 | `initFromSchema` | 🔴 | 🔴 | 🔴 |
| **reader** | 🟢 | 🟢 | 🟢 | `initFromSchema` | 🔴 | 🔴 | 🔴 |
| **transcriber** | 🟢 | 🟢 | 🟢 | `.init` (explicite) | 🔴 | 🔴 | 🟠 (chargé) |
| **converter** | 🟢 | 🟢 | — (bandeau, édition en modale) | `.init` (sélection) | 🔴 | 🟢 | 🔴 |
| **enhancer** | 🟢 | 🟢 | 🟠 (HTML + `initFromSchema`) | `initFromSchema` | 🔴 | 🟢 | 🟢 (onglets domaine) |
| **synthesizer** | 🟢 | 🔴 (hand-built) | — (volet = compose, déclaré) | `initFromSchema` | 🟢 (options voix) | 🔴 | 🟠 (déclaré APP_MODES) |
| **avatarizer** | 🟢 | 🔴 (hand-built) | 🔴 (hand-built) | `initFromSchema` | 🔴 | 🔴 | 🔴 |
| **composer** | 🟢 | 🔴 (hand-built) | 🔴 (hand-built) | `initFromSchema` | 🔴 | 🔴 | 🔴 |
| **imager** | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟠 (switch de mode) |
| **anonymizer** | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟠 (déclaré APP_MODES) |

**Comptes** : modale schéma-driven **5/10** (transcriber, describer, reader, converter, enhancer) ·
volet à champs générés **3/10** (transcriber, describer, reader) · `params.py` **8/10** (manquent
imager, anonymizer).

---

## 2. Axe A — Registre de modèles & vocabulaire de capacités

| Mécanisme | Apps | Référence | À déprécier | Notes |
|---|---|---|---|---|
| `ModelRegistry` + `ModelInfo` (dataclass), `capabilities: Dict`, un `_discover_<app>_models()` par app | **toutes** | ✅ **conserver** (déjà unique) | rien | `model_registry.py:105` — conteneur uniforme. |

**Le problème n'est pas le conteneur, ce sont les CLÉS** de `capabilities` — hétérogènes par app,
sans vocabulaire partagé :

| App | Clés `capabilities` observées (`model_registry.py`) |
|---|---|
| imager | `modalities`, `task` |
| describer | `modalities` |
| anonymizer | `task`, `classes`, `text_promptable` |
| transcriber | `multilingual`, `supports_timestamps`, `native_diarization`, `supports_hotwords`, `languages_count` |
| synthesizer | `supports_cloning` |
| enhancer | `task`, `modalities`, `params` |

> ⚠️ Conséquence : **`WamaModelCaps` ne peut pas piloter l'UI génériquement** tant que les clés ne
> suivent pas une convention. **Action** : normaliser un vocabulaire (`modalities`, `task`,
> `languages`, `supports_*`, `params`) documenté dans `app_metadata.py`, et migrer chaque
> `_discover_*` dessus (sans changer la structure — seulement les noms de clés + complétude).

---

## 3. Axe B — Aide/description de modèle (`help_source` vs `help_fallback`)

Ce sont **deux champs COMPLÉMENTAIRES** du même `Param` (`param_schema.py:54-57`), pas deux
mécanismes rivaux :

| Mécanisme | Sémantique | Apps (dans `params.py`) | Statut |
|---|---|---|---|
| `help_source` | select de MODÈLE → desc courte/longue + VRAM **depuis le catalogue** (`AIModel.description_short`/`description`), rendu par `wama-model-help.js` | **0/10** actuellement | ✅ **Référence** — mais **non adopté** |
| `help_fallback` | dict inline `{option: texte}` pour backends **hors catalogue** (moteurs maison) | enhancer, reader | 🟠 repli légitime |

**Finding** : le chemin préféré (`help_source` → catalogue) **existe dans le code mais aucun
`params.py` ne l'utilise** ; seul le repli inline est employé. L'adoption suppose de **déclarer les
modèles au catalogue** avec `description_short`/`description` renseignés (déjà amorcé pour les moteurs
audio enhancer, commit `83121f1`).

**Cible** : `help_source` partout où le modèle est au catalogue ; `help_fallback` réservé aux moteurs
qui n'y seront jamais. **Action** : compléter le catalogue, puis basculer les selects de modèle sur
`help_source`.

---

## 4. Axe C — Capacités-modèle → visibilité UI

| Mécanisme | Portée | Apps | Verdict |
|---|---|---|---|
| `WamaModelCaps.init` (`wama-model-caps.js`) | **niveau option** (`opt.hidden` selon le modèle sélectionné) | synthesizer (filtre voix par moteur) | ✅ Référence pour options |
| `show_if` déclaratif (`params.py`, piloté par valeur d'un autre champ) | **niveau champ**, mais **par valeur de champ**, pas par capacité-modèle | converter, enhancer | ✅ légitime (conditionnel intra-schéma) |
| `show_if` **hardcodé JS** (masquer un champ selon le modèle) | niveau champ | ancien enhancer (supprimé) | 🔴 **anti-pattern**, ne pas réintroduire |

**Gap identifié** : `WamaModelCaps` **ne masque que des options**, pas des **champs entiers** selon
les capacités du modèle. Il manque un **niveau-champ piloté par capacités-modèle** (ex. masquer
« diarisation » si `capabilities.supports_diarization === false`). **Action** : étendre
`WamaModelCaps` pour cacher/afficher des **champs** en lisant les `capabilities` normalisées (axe A),
et l'exposer déclarativement (ex. `Param.caps_require={'supports_diarization': True}`), **sans jamais
hardcoder** — cf. [[feedback_ui_from_model_capabilities]].

---

## 5. Axe D — Modale « Paramètres » (item/batch)

| Mécanisme | Apps | Référence | À déprécier |
|---|---|---|---|
| `WamaParams.render(host, schema, {context:'item'})` — champs générés du schéma unique | transcriber, describer, reader, converter, enhancer (**5/10**) | ✅ **Référence** | — |
| **Modale hand-built** (markup JS/HTML manuel) | synthesizer, avatarizer, composer (**3/10**) | — | 🔴 **à porter** |
| **Pas de modale schéma** (params.py absent) | imager, anonymizer (**2/10**) | — | 🔴 créer |

Preuves : transcriber `index.html:305` · describer `index.html:519` · reader `reader.js:369` ·
converter `converter.js:806` · enhancer `index.js:252` + `audio-enhancer.js:481` (portage FULL,
commit `770785d`).

**Note (corrigée)** : la **coquille** de la modale (wrapper, titre, footer/boutons) est déjà
**générée automatiquement en JS** dans plusieurs apps — `enhancer.createSettingsModal()`
(`index.js:199-258`) et `reader` (`reader.js:346-369`) bâtissent la coquille en template literal
**puis** appellent `WamaParams.render(host, schema, {context:'item', values})` **puis** câblent les
boutons. Ce **chemin de construction automatisé existe déjà** ; il n'est simplement pas encore extrait
en UN helper commun. → Cible = **extraire ce builder en `WamaParams.renderSettingsModal({id, title,
schema, values, actions})`** (PAS un partial Django `_settings_modal.html`), puis y basculer les apps.

**Trois chemins de construction de modale** (à converger vers le 1er) :
- **Auto-build JS (coquille + champs)** : enhancer, reader → ✅ référence à extraire en commun.
- **Coquille statique en template + `WamaParams.render`** : transcriber, describer, converter.
- **Full hand-built (coquille ET champs)** : synthesizer, avatarizer, composer → à porter.

---

## 6. Axe E — Volet inspecteur (rendu des champs + câblage)

Deux sous-décisions distinctes.

### 6a. Rendu des champs du volet

| Mécanisme | Apps | Verdict |
|---|---|---|
| `WamaParams.render(host, schema, {context:'panel'})` | transcriber, describer, reader (**3**) | ✅ **cible** |
| Champs **hand-built** dans le HTML du volet | enhancer, avatarizer, composer (**3**) | 🔴 à porter |
| **Volet ≠ éditeur** (variante déclarée) | converter (bandeau, édition en modale) · synthesizer (volet = zone *compose*) | — légitime, **à documenter comme capacité** |

### 6b. Câblage du volet (sélection de card, read/apply, actions, save)

| Mécanisme | Apps | Verdict |
|---|---|---|
| `WamaInspector.initFromSchema(...)` — read/apply **dérivés du schéma** | describer, reader, synthesizer, avatarizer, composer, enhancer (**6**) | ✅ **cible** (le moins de code, aligné manifeste) |
| `WamaInspector.init(...)` — callbacks read/apply **explicites** | transcriber, converter (**2**) | 🟠 fonctionnel mais **plus de code** → migrer vers `initFromSchema` |

> **Combinaison cible = pattern describer/reader** : `WamaParams.render(panel)` **+**
> `initFromSchema`. Le transcriber (référence sémantique) génère les champs mais câble en `.init`
> explicite : le faire converger vers `initFromSchema` supprime son câblage sur-mesure.

Preuves : describer `index.html:517,549` · reader `reader.js:713` · transcriber `index.js:1382`
(`.init`) · converter `index.html:359` (`.init`, sélection seule) · composer `index.html:378` ·
avatarizer `index.html:755`.

---

## 7. Axe F — Schéma `params.py`

| Statut | Apps |
|---|---|
| 🟢 présent | transcriber, synthesizer, describer, reader, converter, enhancer, avatarizer, composer (**8/10**) |
| 🔴 absent | **imager**, **anonymizer** (**2/10**) |

C'est le **socle** de tous les autres axes : sans `params.py`, ni modale ni volet schéma-driven
possibles. → imager & anonymizer sont la **priorité 0**.

---

## 8. Axe G — Onglets de domaine / modes (`WamaModes`)

| Élément | État |
|---|---|
| Schéma `APP_MODES` (`common/utils/app_modes.py`) déclare | imager, enhancer, synthesizer, transcriber, anonymizer (**5**) |
| Consommé **en direct** dans un template | enhancer (onglets domaine image/vidéo/audio, live) · imager (switch de mode) · transcriber (chargé) |
| À généraliser | **imager** (domaine + modes), **anonymizer** (yolo/sam3) |

`WamaModes` (`wama-modes.js`) génère onglets/switch depuis le schéma déclaratif → même mécanisme que
`WamaParams` pour les champs. Réf = **enhancer** (multi-domaine complet).

---

## 9. Ordre de convergence exécutable

Chaque étape = route existante, brique commune, **aucun** nouveau mécanisme.

**P0 — Socle manquant (débloque tout le reste)** ✅ FICHIERS FAITS / ⚠ CONSOMMATION À FAIRE
1. ~~`imager/params.py` + `anonymizer/params.py`~~ — les 2 fichiers EXISTENT (dérivés via
   `derive_from_model`, vérifié empiriquement 2026-07-11) mais restent ORPHELINS : aucun
   `WamaParams.render` ne les consomme (modales toujours hand-built). Le vrai reste-à-faire
   P0→P1 = brancher la consommation, pas écrire les fichiers.

**P1 — Modales schéma-driven (le BLOCKER manifeste)**
1bis. **D'ABORD extraire le builder commun** `WamaParams.renderSettingsModal({id, title, schema,
   values, actions})` depuis le pattern DÉJÀ AUTOMATISÉ d'enhancer/reader (`createSettingsModal` +
   `WamaParams.render` + câblage boutons). Ne rien réinventer : factoriser l'existant.
2. Puis basculer les 3 hand-built dessus : synthesizer (⚠️ conserver `WamaModelCaps` voix), avatarizer,
   composer (⚠️ ETA `data-*` par option — voir blocage métadonnée-widget ci-dessous).
3. imager + anonymizer : modale via le builder commun (schéma P0 livré).
4. Converger aussi les variantes à coquille statique (transcriber, describer, converter) vers le
   builder commun (optionnel, cosmétique).

> **Blocage à trancher avant de porter composer/synthesizer** : leurs modales portent des
> métadonnées de widget que `WamaParams` ne rend pas encore — `data-gen-factor`/`data-overhead` par
> option (ETA composer), filtrage voix `WamaModelCaps` (synthesizer), affichages couplés. Retirer ces
> comportements = interdit sans validation. Options : (a) migrer ces métadonnées au catalogue modèle
> (manifeste-pur), (b) étendre le schéma `Param` (`option_meta`/`live_display`), (c) les déclarer
> exceptions bespoke. Décision produit — cf. [[feedback_ui_from_model_capabilities]].

**P2 — Volets à champs générés** — remplacer les champs hand-built du volet par
`WamaParams.render(context:'panel')` :
6. enhancer, avatarizer, composer. (converter & synthesizer restent variantes déclarées — cf. 6a.)

**P3 — Uniformiser le câblage** vers `initFromSchema` : ✅ **FAIT** (2026-07-08/10)
7. ~~transcriber + converter : `.init` → `initFromSchema`~~ — migrés (PROJECT_STATUS §21.3 pt 3
   et §21.4) ; plus AUCUNE app sur `.init` legacy (audit 2026-07-11 : 8/10 en initFromSchema,
   imager+anonymizer pas encore câblés du tout).

**P4 — Capacités : normaliser puis piloter l'UI** :
8. Vocabulaire `capabilities` unifié dans `_discover_*` (axe A).
9. `WamaModelCaps` niveau-CHAMP piloté par capacités normalisées (axe C) ; migrer les `show_if`
   « par modèle » restants dessus.
10. Selects de modèle → `help_source` (catalogue) au lieu de `help_fallback` là où le modèle y est
    déclaré (axe B) ; compléter le catalogue au passage.

**P5 — Domaines/modes** :
11. anonymizer (+ synthesizer, déclaré mais inerte) : brancher `WamaModes` sur `APP_MODES` déjà déclaré. (imager ✅ câblé — vérifié 2026-07-09/11 ; enhancer ✅.)

**Invariant de sortie** : chaque app = `params.py` (source unique) → modale + volet générés par
`WamaParams` → câblés par `initFromSchema` → capacités normalisées pilotant la visibilité → modes via
`WamaModes`. Reste app-spécifique : `process()`, pages d'édition dédiées, shell de modale.

---

## 10. Vérification empirique (traçabilité)

- `params.py` présents : `ls wama/*/params.py` → 8 fichiers (hors imager/anonymizer).
- `param_schema.py:54-57` : `help_source`/`help_fallback` = 2 champs `Param` complémentaires.
- Modale `WamaParams context:'item'` : transcriber:305, describer:519, reader.js:369,
  converter.js:806, enhancer index.js:252 + audio-enhancer.js:481.
- Volet `WamaParams context:'panel'` : transcriber:300, describer:517, reader:156.
- Câblage : `.init` = transcriber index.js:1382, converter index.html:359 ; `initFromSchema` =
  describer:549, reader.js:713, composer:378, avatarizer:755, synthesizer:827, enhancer:864/879.
- `WamaModelCaps` : `wama-model-caps.js` + seul consommateur synthesizer index.html:857.
- `show_if` déclaratif : converter/params.py (media_type), enhancer/params.py (engine).
- `capabilities` clés hétérogènes : `model_registry.py` lignes 273, 393, 467/492, 567-573, 641, 824.
- `APP_MODES` : `app_modes.py:35` (imager, enhancer, synthesizer, transcriber, anonymizer) ;
  consommateurs templates = enhancer, imager, transcriber.

> Lié : [[project_ui_mechanisms_consolidation]], [[project_manifest_generation_priority]],
> [[project_schema_driven_ports]], [[feedback_ui_from_model_capabilities]],
> [[feedback_modales_vs_inspecteur_mode_simplifie]].
