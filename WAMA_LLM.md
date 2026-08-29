# WAMA_LLM.md — la couche LLM : prompts, skills, RAG, mémoire & routage (§10.B / §16.6)

> **Renommé le 2026-08-25** — `PROMPT_PIPELINE.md` → `WAMA_IA_TRANSVERSE.md` → **`WAMA_LLM.md`**.
> Deux raisons, et la seconde est un critère déjà en vigueur dans le dépôt :
> ① « IA transverse » est devenu **ambigu** — les modèles APPRIS (`WAMA_APPRENTISSAGE.md`) sont
> eux aussi transverses aux trois mondes ; ② `PIPELINE` était **déjà pris deux fois** (le kind de
> manifeste `pipeline`, et « pipeline de prompts »), et *« un nom faux par COLLISION est pire qu'un
> nom faux par connotation »* (critère de D17, `WAMA_DATA_WORLD`).
>
> **Périmètre** : tout ce qui entoure un traitement côté **langage** — comprendre la demande,
> enrichir/traduire le prompt, rappeler du RAG et de la mémoire, choisir le modèle, exposer les
> skills, servir l'assistant sur ses N surfaces. **N'y entre PAS** : les modèles appris sur les
> données (→ `WAMA_APPRENTISSAGE.md`).

> **Renommé depuis `PROMPT_PIPELINE.md` le 2026-08-22** (décision Fabien : le nom ne couvrait
> plus le contenu — le fichier porte désormais les prompts, les SKILLS et la vue de CHAÎNE
> transverse). Le nom reprend la Partie IV de la vision : « IA transverse : rôle, skills,
> RAG, traduction et routage ». Domaine RAG+mémoire : `WAMA_MEMORY.md` (substrat).

> Système **centralisé et métadonnée-driven** qui traite tout prompt utilisateur de WAMA avant qu'il
> n'atteigne un modèle : **traduction si besoin**, **enrichissement**, **compréhension de fichiers de
> référence** (RAG à venir). Une seule pipeline, déclenchée par déclaration ; **zéro patch par app**.

## Principe
Une app **déclare** ses champs-prompt (et leur **KIND**) dans `app_metadata.PROMPT_TARGETS`. Au moment
du traitement, elle appelle `process_prompt_for(app, field, value, instance, user, console)` ; la
pipeline résout le modèle cible, décide du routing langue, traduit/enrichit/complète selon le KIND, et
renvoie le prompt transformé. Le KIND est déclaré **en un seul endroit**, découvrable par l'assistant
et la méta-app.

## Modules (`wama/common/utils/`)
| Module | Rôle |
|--------|------|
| `app_metadata.py` | `PROMPT_TARGETS` (déclaration par app) + `process_prompt_for(...)` (options `enrich=` / `glossary=` / `full=`). Résout modèle (`AIModel`), `enrich`, `reference_field`. Plus les briques d'ingestion : `enrich_instance_prompts()`, `effective_prompt()`, `detected_keywords()`, `apply_prompt_state()`. |
| `prompt_ingest.py` | **Branchement générique** de l'enrichissement à l'ingestion, déduit de `PROMPT_TARGETS[...]['model']`. Aucune app n'écrit de récepteur `post_save` ni de tâche Celery. |
| `models.PromptScoped` | Mixin apportant `prompt_processed` / `prompt_trace` / `prompt_keywords`. |
| `prompt_pipeline.py` | `process_prompt(...)` — orchestre détection langue → routing → traduction → enrichissement → fichiers de référence. Fail-safe. |
| `lang_routing.py` | DÉCIDEUR : `routing_for_model(caps, model_type, input_lang, …)` → `{direct, input_translate, input_pivot, …}`. `_TYPE_LANG_DEFAULT` (diffusion/upscaling/music/audio_gen → `['en']`). Inconnu → `['*']` (direct). |
| `translator.py` | ACTEUR : `TranslatorService` via `translategemma` (Ollama), cache, glossaire do-not-translate, découpage. Passthrough si même langue. |
| `prompt_enrichment.py` | « Upsampling » génératif : `enrich_generative()`. **ON par défaut** depuis 2026-07-30, piloté par la préférence utilisateur (`enrichment_enabled(user)`). Une passe LLM, cache, garde longueur, `keep_alive` paramétrable, fail-safe. |
| `reference_comprehension.py` | `comprehend_files()` multimodal (image→vision, doc→`batch_parsers`). Data-gated. Replie un bloc `[Reference context]`. |
| `qc.py` | `assess_output_quality()` — validateur LLM indépendant (post-génération, à câbler). |

## KINDs
| KIND | Usage | Traduction | Enrichissement |
|------|-------|-----------|----------------|
| `generative` | génération image/audio (SDXL/Flux/MusicGen) | si modèle EN-only | oui (si `enrich=True` + flag ON) |
| `concept` | concepts pour segmentation (SAM3) | vers concepts EN | non |
| `intent` | intention assistant (LLM) | rarement (modèle multilingue → direct) | non |
| `text` | texte brut | non | non |

## Câblages en place (`PROMPT_TARGETS`)
| App | Champ | KIND | Notes |
|-----|-------|------|-------|
| imager | `prompt` | generative | `enrich=True` |
| imager | `negative_prompt` | generative | pas d'enrich |
| anonymizer | `sam3_prompt` | concept | `when='use_sam3'` |
| cam_analyzer | `sam3_markings_prompts` | concept | `when='use_sam3'`, `domain='transport'`, `list_item_field='prompt'` (liste `{label,prompt}`) |
| composer | `prompt` | generative | `default_model_type='music'` (MusicGen EN) |
| assistant | `message` | intent | `model_id=` dynamique (modèle Ollama résolu) |
| synthesizer | — | — | **aucun target** : `text_content` = contenu à dire (jamais traduit) |

## Garde-fous ressources (récurrent)
- **Traduction** : seulement si le modèle ne gère pas la langue ; passthrough/`direct` sinon → aucun chargement.
- **Enrichissement** : interrupteur maître `WAMA_PROMPT_ENRICH` (OFF) + garde longueur + cache.
- **Fichiers de référence** : data-gated (rien si pas de fichier).
- **Transparence** : messages console user-facing (🌐 traduit / ✨ enrichi / 📎 référence) ; **silence si direct**.

## Skills de prompt par application (2026-07-08)

Les **consignes d'enrichissement** ne sont plus codées en dur : chaque app les DÉCLARE dans
`wama/common/prompt_skills/<slug(app)>-<slug(domain)>.md` — le résolveur **slugifie** (`_` → `-`,
ex. `cam_analyzer`+`transport` → `cam-analyzer-transport.md`) ; résolution `<app>-<domain>` →
`<app>` → `default-<kind>`, module `common/utils/prompt_skills.py`, **importable sans Django**.
Le domaine vient de `PROMPT_TARGETS` (`domain` statique ou `domain_field` lu sur l'instance,
ex. imager `output_type` image|video), repli sur le `model_type` du modèle cible.

**Toutes les sources d'appel convergent** (décision Fabien 2026-07-08) :
- pipeline au lancement de tâche (hook A, gaté `WAMA_PROMPT_ENRICH`) ;
- **à la demande** (bouton ✨) : `prompt_enrichment.enrich_on_demand(prompt, app=, domain=)` —
  PAS gaté par l'interrupteur maître (le clic vaut demande), même cache. Imager consommateur
  (son `utils/prompt_enhancer.py` dupliqué a été SUPPRIMÉ) ;
- assistant IA : ses tools dispatchent les tâches Celery → skills d'enrichissement appliqués
  by design. ⚠ **Cela ne couvre QUE l'enrichissement.** La posture de l'assistant lui-même
  (« qui répond, avec quelle rigueur, avec quel contexte de labo ») est une **autre famille**,
  livrée le 2026-08-21 : `assistant-*.md` + `common/utils/assistant_skills.py`. Confondre les
  deux a coûté un aller-retour — cf. la table des deux familles dans
  `prompt_skills/README.md` ;
- ⚠ **wama-dev-ai : PROMESSE NON TENUE.** Cette ligne affirmait « importe le même module ».
  Vérifié le 2026-08-21 : `PROMPT_SKILLS_DIR` est **déclaré** dans `wama-dev-ai/config.py:21`
  et **lu nulle part**. wama-dev-ai a ses propres consignes (`wama-dev-ai/prompts/*.txt`,
  8 fichiers réellement consommés) — ce qui est légitime (**le dev n'est pas l'usage**), mais
  le pont documenté ici n'existe pas. Soit on le construit, soit on retire la promesse.

Règles DANS LE CODE (mécanisme, pas skills) : clause de langue d'émission + préservation
verbatim des mots-clés forcés (`glossary`). Contrat : `wama/common/prompt_skills/README.md`.

**Doctrine 2026-08-26 (validée Fabien) — le CONTRAT DE SORTIE appartient au MODÈLE, pas à
l'app** : MusicGen attend 30-80 mots, MiniMax-Music3 attend 250-450 mots sectionnés avec tags
de paroles — même app, contrats opposés, que la résolution `<app>-<domain>` ne voit pas.
Cible : le manifeste `model` déclare `body.prompts.contract` (fait DÉCLARÉ, même route que
`license`/`platform_ref` — JAMAIS `AIModel.capabilities`, réécrit en entier par la découverte),
projeté par `write_back_model` puis injecté par le résolveur : skill d'app = la méthode,
modèle = son contrat. Méthode de construction en 4 étages (brief → précédence → contrat →
auto-validation) : `prompt_skills/README.md`. **CÂBLÉ le même jour** : colonne
`AIModel.prompt_contract` (migration 0014), projection manifeste, `_resolve_model` →
`process_prompt(prompt_contract=)` → `build_system` (le contrat PRIME sur le skill, cache
keyé par contrat). Data-gated : sans contrat déclaré, comportement d'avant à l'octet
(prouvé). Reste : déclarer les contrats dans les manifestes des modèles, au fil des adoptions.
Comblé au passage : `generate_video_task` (imager) n'appelait PAS la pipeline (variables
locales `_prompt`/`_negative`, la base garde l'original) ; composer `enrich=True` (le blocage
« consignes visuelles » est levé par `composer-music.md`).

## Hooks
- ✅ **RAG — BRANCHÉ** (`prompt_pipeline._rappel_rag`, jalon 6). ⚠ Cette entrée annonçait
  encore « ChromaDB + fondation `wama/rag/` inexistante » : **doublement périmé** — le
  substrat est **pgvector** (`RagChunk`, `common/memory/`) et le hook existe. Il reste
  **`rag=False` par défaut et aucun appelant ne l'active** : voir la section
  « PROMPT + SKILLS + RAG + MÉMOIRE — la chaîne complète » plus bas, qui fait autorité.
- **QC** : câbler `qc.py` en post-génération dans les apps (seul consommateur actuel = la
  commande de bench `bench --task`).

## Réglages (`wama/settings.py`)
- `WAMA_PROMPT_ENRICH` (env, **défaut ON depuis 2026-07-30**) — **kill switch plateforme**, plus
  l'interrupteur maître. `=0` coupe l'enrichissement pour tout le monde (incident ressources, debug).
- `UserProfile.prompt_enrich` (défaut `True`) — **le vrai interrupteur**. L'utilisateur n'a pas à
  connaître la chaîne derrière son prompt, mais il peut la couper. Arbitrage : `enrichment_enabled(user)`.
- `WAMA_PROMPT_ENRICH_MODEL` (env, optionnel) — modèle d'enrichissement (défaut `llm_chat` =
  `qwen3.5:9b`). **Choix mesuré** (bench 2026-07-29) : `qwen3.5:4b` est plus léger/rapide mais viole
  la clause de langue 3/3 sur prompt court et dérive le sujet → ne pas basculer. Détail dans le
  docstring de `prompt_enrichment.py`.
- `WAMA_GPU_SAFE_MODE` (env, défaut OFF — activé dans `.env` de l'hôte fragile, 2026-08-28) —
  mode « dépannage GPU » (domicile : `resource_governor` 2 bis, contexte :
  `INFRA_WSL_VS_WINDOWS §crashs`). Effet côté pipeline : traduction et enrichissement passent
  `keep_alive=pipeline_keep_alive()` → `'0'` (Ollama décharge sitôt la réponse) au lieu du défaut
  (~5 min de résidence pendant que la génération GPU monte en charge). L'enrichissement portait
  déjà `keep_alive='0'` en dur (choix mesuré 29/07) — la **traduction** était le trou.

## Quand l'enrichissement a lieu (2026-07-30)

| Étape | Ce qui s'y fait | Pourquoi là |
|---|---|---|
| **Ingestion** (création de la card) | **Enrichissement** — `enrich_instance_prompts()`, déclenché par un récepteur **générique** (`common/prompt_ingest.py`, `on_commit`) + tâche Celery commune | L'utilisateur VOIT et peut éditer/annuler ce qui partira ; la passe LLM ne recouvre plus le chargement du modèle de génération |
| **Lancement de la tâche** | **Traduction** + rattrapage d'enrichissement si absent | La traduction dépend du modèle cible, encore modifiable après le dépôt |

- `<field>_processed` = ce qui part au modèle ; `<field>` = **ce que l'utilisateur a tapé, jamais
  écrasé** (seule façon de revenir en arrière). `effective_prompt(instance, field)` arbitre.
  Convention **opt-in par modèle** : un modèle sans `_processed` garde le comportement d'avant.

### Ce qu'une app doit faire pour en bénéficier (2026-07-31)

**Trois lignes, aucun code.** Le reste est générique — il n'y a plus ni récepteur, ni tâche
Celery, ni logique d'état à écrire par app (c'était le cas jusqu'au 30/07 : ~20 lignes recopiées).

1. le modèle hérite du mixin commun **`PromptScoped`** (`common/models.py`) → apporte
   `prompt_processed`, `prompt_trace`, `prompt_keywords` ;
2. la déclaration `PROMPT_TARGETS` nomme le modèle : **`'model': '<app>.<Modèle>'`** → le
   branchement de l'enrichissement à l'ingestion en est **déduit** (`common/prompt_ingest.py`,
   connecté depuis `CommonConfig.ready()`) ;
3. la vue d'enregistrement appelle **`apply_prompt_state(instance, field, value, state)`** —
   l'arbitrage « dans quel champ écrire » est commun, pas réimplémenté.

Un modèle non migré est **ignoré** par le récepteur : l'app garde exactement son comportement
d'avant tant qu'elle n'a pas adopté le mixin.
- `prompt_trace` (JSON) trace `{enriched, source, language, keywords}` ; `prompt_keywords` conserve
  les mots-clés comme **donnée**.
- **VRAM** : `keep_alive='0'` sur le chemin critique (juste avant la diffusion), `'60s'` à
  l'ingestion — sinon un batch repaierait ~12 s de chargement par item.

## UI — champ prompt à deux états (`wama-prompt-enrich.js`, brique commune globale)

Un **seul** champ (jamais deux : deux champs éditables = deux sources de vérité, et l'enrichi
devient périmé en silence dès que l'original est modifié). Le champ contient toujours ce qui sera
envoyé ; sous lui : `✨ Enrichi · voir mon prompt · revenir au mien · ↻ ré-enrichir`. L'original
s'affiche en lecture seule. **Silence total si le prompt part tel quel.**

- L'état courant est porté par `data-prompt-state` (`user` | `processed`) et **posté** : le serveur
  sait dans quel champ écrire (`processed` → n'écrase pas l'original ; `user` → vide l'enrichi périmé).
- À la **création**, le front poste le prompt de l'utilisateur, pas l'enrichi affiché.
- **Mots-clés** ([[wama-prompt-chips]]) : `detected_keywords()` les RETROUVE en confrontant le prompt
  à la palette (dérivés, pas transmis) → aucun handler de création à patcher, et ils partent en
  glossaire donc sont préservés verbatim.
- Adopté par imager (4 champs) ; prêt pour composer et le studio, sans code par app.

## PROMPT + SKILLS + RAG + MÉMOIRE — la chaîne complète par surface (état MESURÉ au 2026-08-22)

> ⚠ Remplace la version du 2026-08-21, antérieure à DEUX corrections : l'entrée au RAG est
> devenue un **GESTE à niveaux** (le balayage a été purgé — `WAMA_MEMORY.md §7ter`) et le
> sélecteur de niveaux existe au rappel. **Méthode** : chaque ✅ ci-dessous a été confronté au
> CODE le 2026-08-22 (appelants relevés par grep, jamais déduits des docs) ; ce que la vision
> prévoit sans que le code l'ait est au §5 — jamais mélangé au réel.
>
> **Documents** (réponse à « a-t-on un document sur le RAG ? ») : prompts + skills = **CE
> document** · RAG + mémoire = **`WAMA_MEMORY.md`** (UN mécanisme, décision 2026-08-20) · la vue
> de chaîne transverse = **cette section**, en un seul exemplaire — pas de 3ᵉ document (« un
> domaine = un fichier »).

### 0. Les TROIS axes de « niveaux » — les confondre fait perdre le fil

Trois notions distinctes portent le mot « niveau » ; elles se croisent mais ne se recouvrent pas :

| Axe | Question à laquelle il répond | Mécanisme | État mesuré |
|---|---|---|---|
| **A. Hiérarchie ORGANISATIONNELLE** | qui appartient à quoi ? | arbre `OrgUnit` (`parent` : institut→université→département→labo→service→équipe) + affiliations du profil (`org_affiliations` — une **LISTE** : multi-labos, multi-équipes) | mécanisme ✅ (héritage ancêtres testé) · **données ❌ : 0 `OrgUnit` en base** |
| **B. Niveaux de PARTAGE du RAG** | qui peut rappeler ce document ? | `ScopedVisibility` porté par chaque fragment : `user` / `unit` / `project` / `public` | écriture `user`+`unit` ✅ (`project` ANNONCÉ, `public` plus tard) · lecture `rag_niveaux` ✅ : son RAG / labo / les deux / **rien** |
| **C. Niveaux d'ENRICHISSEMENT du prompt** (vision §10) | qu'ajoute-t-on au prompt avant le modèle ? | global (règles DANS le code : langue d'émission, glossaire verbatim) · métier (skills `<app>-<domaine>.md`) · organisationnel · utilisateur | global ✅ · métier ✅ · **organisationnel ❌** · **utilisateur ❌** |

### 0bis. Les SKILLS — deux natures de contrat, cinq familles (vision §9), état mesuré

**Rôle vs skill** (transversal) : le RÔLE fixe *qui répond* — un seul actif, `assistant-*.md`,
appliqué au prompt système ; les SKILLS disent *comment traiter* — composables, appliqués à
l'enrichissement. Contrats opposés : un skill de rôle ne transforme rien, un skill
d'enrichissement transforme un prompt et ne rend que lui. Les confondre coûte une passe LLM
inutile ou un assistant sans posture.

| Famille (vision §9) | Réalité dans le code | État |
|---|---|---|
| **Spécialisés MODÈLE** (format exact attendu par un modèle) | les KINDs de `PROMPT_TARGETS` (`concept` → concepts EN pour SAM3, `generative`…) + résolution du modèle cible par target | partiel — les KINDs couvrent le cas langue/forme, pas un gabarit par modèle |
| **DOMAINE** (app × métier) | `prompt_skills/<app>-<domaine>.md` (imager-image, composer-music, cam-analyzer-transport…) + rôles assistant `assistant-*` (`DOMAINES` : general, science, design, dev) | ✅ les deux registres vivent (`PROMPT_TARGETS`, `assistant_skills.DOMAINES`) |
| **DÉVELOPPEUR / workflow** | rôle `assistant-dev` ✅ ; outil `ask_claude_code` ✅ ; ⚠ wama-dev-ai a ses PROPRES consignes (`wama-dev-ai/prompts/*.txt`, 8 fichiers consommés) — il **n'importe PAS** `PROMPT_SKILLS_DIR` (cf. §« Skills de prompt », note du 21/08) | partiel |
| **INSTITUTIONNELS** (université, instances — « souvent couplés au RAG organisationnel ») | — | ❌ **substrat désormais prêt** (RAG niveau `unit`) ; aucun skill écrit, aucun contenu org indexé |
| **UTILISATEUR** (préférences, habitudes, formats favoris) | langue du profil + enrich on/off, c'est tout | ❌ pas de skill par utilisateur |

### 1. Assistant — UN cerveau, N surfaces (web `home.html`, API v1, canaux Discord/Matrix)

```
message utilisateur (+ domaine transmis par la surface, sinon 'general')
  │
  ├─ prompt système : {LANGUE du profil} + RÔLE (consigne_de_role) + contexte WAMA (files)
  ├─ CONTEXTE LABO : contexte_laboratoire(user, message, domaine)
  │     = recall() hybride scopé — SEULEMENT si le domaine déclare rag=True (science, design)
  │     3 gardes : DÉCLARÉ · DATA-GATED (rien de pertinent ⇒ prompt inchangé) · FAIL-SAFE ('')
  │     chaque extrait injecté AVEC sa référence ([transcriber:134] …)
  │
  └─ boucle LLM à outils (51 outils, gating F7) — c'est ICI que tout se rejoint :
       • charger_competence(domaine)  → l'ASSISTANT charge LUI-MÊME posture + contexte labo
         (jamais la surface : un adaptateur de canal ne devine pas le domaine)
       • memory_recall(query, niveaux=…) → recall() souvenirs + RAG, sélecteur de niveaux,
         HYBRIDE — résidence bge-m3 arbitrée par le GOUVERNEUR (~5 s à froid, ~350 ms résident)
       • add_to_<app> / start_<app> → tâches d'app ⇒ la pipeline d'app s'applique (§2)
  [le message lui-même : kind='intent' via process_prompt_for('assistant','message') —
   routage langue seul, pas d'enrichissement]
```

**Le pivot API — `wama/tool_api.py`** : `TOOL_REGISTRY`, **51 outils** — triades
`add_to_/start_/get_…_status` (déclaratives, marche A4) pour les apps + studio ; l'inventaire
complet et ses trous vivent dans `WAMA_APP_GENERATION_ROUTE.md §11` (trou #18), pas ici. Ce qui
appartient à CE document : les outils **IA-transverses** (gating `None` — aucune app ne les
garde), exactement **8** au 2026-08-22 : `translate_text` (§2bis) · `memory_recall` (§3-4) ·
`charger_competence` (§0bis) · `list_ai_models`/`get_ai_model` (§2ter) · `list_user_files` ·
`switch_ui_mode` · `ask_claude_code` (garde développeur écrite DANS son corps, pas dans le
registre — ne pas « corriger »). À venir : `list_my_items`/`get_item_detail` (jalon 12,
`WAMA_MEMORY.md §9ter`). Toutes les surfaces (web, API v1 `/api/v1/assistant/chat/`, canaux
Discord/Matrix — ROADMAP §19) passent par ce même pivot : ajouter un outil ICI l'offre partout.

⚠ **Contrat de surface** (ROADMAP §19 ①) : le tour d'assistant ne porte **jamais** d'audio — la
TTS est une **étape cliente post-réponse** (`home.html` appelle `/api/tts-kokoro/` après coup),
et les visèmes de l'avatar viendront d'un endpoint TTS distinct. C'est la contrepartie de « UN
cerveau, N surfaces » : le contrat commun ne porte que ce qui vaut pour toutes les surfaces —
un bot Discord n'a rien à faire d'un WAV en base64.

### 2. Apps — au lancement de la tâche Celery

Appelants **réels** de `process_prompt_for` (grep 2026-08-22) : **imager** (×2 chemins),
**composer**, **anonymizer**, l'**assistant** (§1) — et **cam_analyzer** via `enrich_on_demand`.
Les autres apps n'ont pas de champ prompt (`PROMPT_TARGETS` vide pour elles).

```
prompt tapé
  │  [INGESTION — si le modèle hérite de PromptScoped ET est nommé dans PROMPT_TARGETS :
  │   enrichissement générique on_commit (prompt_ingest) — l'utilisateur VOIT et peut annuler]
  │
  └─ process_prompt_for(app, field, value)          ← LE passe-plat unique
       ├─ détection langue → ROUTAGE (lang_routing : capacités du modèle cible)
       ├─ TRADUCTION si le modèle ne gère pas la langue (translategemma, glossaire verbatim)
       ├─ ENRICHISSEMENT si déclaré (skill <app>-<domaine>.md ; gaté user + kill-switch)
       ├─ FICHIERS DE RÉFÉRENCE (comprehend_files, data-gated)
       └─ ⚠ Hook B RAG : EXISTE dans process_prompt(rag=True) mais INATTEIGNABLE —
          process_prompt_for ne transmet PAS `rag` et PROMPT_TARGETS ne le déclare pas.
          Arbitrage Fabien 21/08 : À OUVRIR — une génération est asynchrone (10-60 s), les
          ~5 s du rappel y sont invisibles ; l'objection « latence » ne vaut que pour le chat.
  → modèle (keep_alive='0' sur le chemin critique)
```

**Bouton ✨** (à la demande) : `common/views` → `enrich_on_demand` — mêmes skills, PAS gaté (le
clic vaut demande). **Studio** : `generic_runner` → `execute_tool('add_to_<app>' / 'start_…')` →
chemin ci-dessus — le studio n'implémente **rien**, il hérite tout des apps. ⚠ **wama-dev-ai
n'entre PAS dans cette chaîne** : il a ses propres consignes (`wama-dev-ai/prompts/*.txt`) et
n'importe pas `PROMPT_SKILLS_DIR` — le pont est déclaré, jamais lu (note du 21/08 ci-dessus).

### 2bis. Traduction automatique ENTRÉE / SORTIE (vision §12) — l'entrée vit, la sortie n'est pas branchée

```
entrée : utilisateur (fr) ──routage──▶ [modèle gère fr ? DIRECT · sinon traduire fr→pivot] ──▶ modèle
sortie : modèle (pivot)   ──routage──▶ [output_translate ? traduire pivot→fr]              ──▶ utilisateur
```

- **ENTRÉE ✅** — vécue dans `process_prompt_for` (§2) : `lang_routing` DÉCIDE (capacités du
  modèle cible ; `_TYPE_LANG_DEFAULT` diffusion/music → EN), `translator` AGIT (translategemma,
  glossaire do-not-translate, passthrough si la langue est gérée → coût nul, silence si direct).
  L'assistant dispose du même acteur en **outil explicite** : `translate_text` (transverse, §1).
- **SORTIE ❌ non branchée** — mesuré le 2026-08-22 : le DÉCIDEUR existe (`routing_for_model`
  rend `output_translate`/`output_source`) et l'ACTEUR existe
  (`TranslatorService.translate_output`), mais **aucun appelant ne déclenche** — la pipeline
  force `has_text_output=False` (un prompt n'est pas une sortie), et rien dans le dépôt ne lit
  `output_translate` ni n'appelle `translate_output`. Même motif que le Hook B avant son
  branchement : brique complète, zéro consommateur.
- ⚠ **La sortie ne se traduit pas partout — deux natures de texte** : les textes **FIDÈLES**
  (transcription, OCR) ne se traduisent JAMAIS d'office — c'est la règle de fidélité verbatim du
  transcriber, une traduction est alors un NOUVEAU produit demandé explicitement. Les vrais
  candidats sont les textes **GÉNÉRÉS** (description, résumé), et seulement quand le modèle ne
  sait pas émettre la langue voulue — le describer obtient déjà le FR par consigne au modèle
  multilingue (route directe, coût nul).

### 2ter. Sélection & ROUTAGE du modèle — le « routage » du titre de la Partie IV

La vision §15 place la **sélection du modèle** au cœur de la chaîne (`…RAG → Sélection du modèle
→ traduction → adaptateur → dispatch`). Ce qui existe, mesuré :

- **Assistant** : rôle → tier (`_ROLE_TIER` → `modele_par_tier`, catalogue — plus de table de
  tags, elle mourait à chaque remplacement de modèle) + **escalade par taille de contexte**
  (`_route_model_by_context` : conversation trop longue ⇒ modèle à plus grande fenêtre) +
  fournisseurs **cloud** via `llm_chat` (LiteLLM, ROADMAP §8d — livré). Le CATALOGUE est
  exposé à l'assistant en lecture par deux outils transverses : `list_ai_models` /
  `get_ai_model` (§1).
- **Apps** : `select_model()` (model_manager) — VRAM-aware, `prefer_loaded`, capacités requises ;
  les tiers de `llm_utils` s'appuient dessus.
- **Cible non atteinte** (§15 + ROADMAP §8d) : croiser **intention + fichiers d'entrée +
  résultats du RAG** pour choisir le modèle, et l'escalade cloud par *capacité* (VRAM saturée) —
  aujourd'hui seule l'escalade par **contexte** est vécue. C'est la ligne 5 du tableau §5.
- **Post-génération — QC** : la vision §15 s'arrête au dispatch, mais la chaîne réelle a un
  maillon prévu APRÈS le modèle : `qc.py::assess_output_quality` (validateur LLM indépendant,
  ROADMAP §16.5). **0 consommateur, bench compris** (re-vérifié 2026-08-27 : `bench.py` n'appelle
  ni `qc` ni `assess_output_quality` — la carte des mécanismes le
  signale comme brique morte). Ligne 12 du tableau §5.

### 3. RAG — alimentation par GESTE, rappel par NIVEAUX (`WAMA_MEMORY.md §7ter`)

```
sortie d'app ──(si l'utilisateur veut)──▶ médiathèque ──(ACTION EXPLICITE)──▶ RAG
                                             ajouter_au_rag(texte, niveau='user'|'unit')
                                               • plusieurs affiliations ⇒ NOMMER l'unité
                                               • ancêtre (dépt/univ) ⇒ REFUSÉ (niveaux 3/4 fermés)
                                               • embedding=NULL au geste → reindex par lot
rappel  : recall(rag_niveaux={'user','unit'}) — son RAG / celui du labo / les deux / RIEN
retrait : retirer_du_rag — ce qui entre par un geste sort par un geste
```

Cas d'usage canonique (Fabien) : scan manuscrit → OCR reader → **ce texte** entre au RAG par le
geste → sert ensuite, p. ex., au compte-rendu tiré d'une transcription de réunion.

**SURFACES livrées le 2026-08-22** (jalon 14) : le geste est un bouton de l'**inspecteur** — donc
présent dans les 10 apps **sans une ligne par app**, et data-gaté sur la présence de texte — et la
page **« Mon RAG »** (`/common/rag/`) porte les défauts de niveaux, la liste, le retrait et l'état
des vecteurs. Les défauts vivent sur le profil et sont **lus au rappel** (`contexte_laboratoire`),
avec trois états distincts pour le sélecteur de lecture (`NULL` = tout le visible · `[]` = ne rien
rappeler · sélection). Détail et raisons du placement : `WAMA_MEMORY.md §9quater`.
État : le RAG reste **VIDE tant que personne n'a cliqué** (balayage initial purgé, 939 → 0) —
c'est voulu : il n'existe aucune autre porte d'écriture.

### 4. Mémoire — souvenirs, PAS le RAG (deux tables, cycles opposés)

`RunOutcome` (gestes captés par middleware) ──projection mécanique──▶ `MemoryItem` auto-approuvé ·
imports LLM (dev-ai : 25 souvenirs) ──▶ **NON approuvés** (invisibles au rappel, file de revue) ·
surfaces : journal `/common/journal/` + `memory_recall`. Producteur `PROV_ASSISTANT` : **aucun**
— un fil de conversation clos pourra se PROJETER en souvenir (jonction canaux §19.5, seul point
de rencontre entre les deux chantiers).

### 5. Ce que la VISION prévoit et que le code N'A PAS (confronté le 2026-08-22)

| # | Élément (vision) | État réel | Note |
|---|---|---|---|
| 1 | Niveau d'enrichissement ORGANISATIONNEL (§10) + skills INSTITUTIONNELS (§9) | ❌ | le substrat existe désormais (RAG niveau `unit`) ; aucun skill org écrit |
| 2 | Skills UTILISATEUR (§9-10 : habitudes, formats favoris) | ❌ | seules préférences réelles : langue, enrich on/off |
| 3 | Classification d'INTENTION amont pilotant skills + niveau de RAG (§11, §15) | partiel | le choix est aujourd'hui à l'ASSISTANT (`charger_competence` ✅) ; pas de classification auto, pas de sélecteur d'UI |
| 4 | RAG dans l'enrichissement d'app (chemin B) | ❌ **arbitré À FAIRE** (21/08) | ouvrir le passe-plat `rag` dans `process_prompt_for` + déclaration `PROMPT_TARGETS` |
| 5 | Sélection de MODÈLE croisant intention + fichiers + RAG (§15) | ❌ | la sélection réelle est tier/VRAM/contexte (§2ter) ; escalade cloud par VRAM saturée non vécue (§8d) |
| 6 | Adaptateur de FORMAT (§14 : compilation DÉTERMINISTE post-LLM, distincte de l'enrichissement) | partiel | seul cas vivant = le KIND `concept` (SAM3 : liste d'objets EN) ; pas de couche générique par modèle |
| 7 | RAG niveaux université / global (§11) | fermés **volontairement** | trajectoire v2 : user + labo d'abord, projet ensuite — décision Fabien |
| 8 | Peuplement : `OrgUnit` + affiliations des profils | ✅ 2026-08-22 | ⚠ mon diagnostic « sync LDAP **prévue** » était **faux** : l'auth LDAP ET la remontée SUPANN au profil marchaient déjà ; seul l'**arbre `OrgUnit`** manquait, sans commande pour le peupler. Livré : `manage.py sync_org_units` (`ou=structures`, bind anonyme, idempotent) + `rag_unite_defaut` — les rattachements MULTIPLES sont la norme (codes hérités `{IFSTTAR}` à côté des actuels). Niveau labo **opérationnel**, vérifié sur données réelles |
| 9 | Surfaces du geste RAG + page de gestion (défaut de niveaux, retrait) | ✅ 2026-08-22 | **placement tranché : l'INSPECTEUR** (global, déjà nourri par `detail_registry` qui porte le texte ⇒ 10 apps sans une ligne par app, data-gaté) + page « Mon RAG » `/common/rag/` ; défauts sur le profil (`accounts.0015`), lus par `contexte_laboratoire`. Reste : sélecteur **par requête** + entrée depuis la médiathèque — `WAMA_MEMORY.md §9quater` |
| 10 | **Traduction de SORTIE** (§12 : `Traitement IA → Traduction sortie → Utilisateur`) | ❌ non branchée | décideur (`output_translate`) + acteur (`translate_output`) livrés, **zéro appelant** ; candidats = textes GÉNÉRÉS uniquement — jamais transcription/OCR (fidélité verbatim) |
| 11 | **Parseur STRUCTUREL de document** (§13 : texte / figures / images-texte → traitement → réassemblage, mise en page conservée) | partiel — **la moitié RENDU existe** | le RÉASSEMBLAGE/mise en forme est VIVANT (rappel de Fabien, vérifié 22/08) : `common/utils/html_render.py` — brique commune HTML→PDF à **2 moteurs** (Chromium headless/Playwright PRÉFÉRÉ : CSS complet + JS ; WeasyPrint en repli sans dépendance navigateur), consommée par le converter — + `common/utils/document_export.py` (PDF/DOCX stylés : describer, reader). Ce qui MANQUE : le **PARSING** structurel (document → texte/figures/images-texte — `batch_parsers`/`comprehend_files` aplatissent tout) et l'aller-retour complet ; Docling (§16.2) reste le candidat du parsing |
| 12 | **QC post-génération** (§16.5 : validateur LLM indépendant après le modèle) | ❌ brique morte | `qc.py` : 0 consommateur, **bench compris** (re-vérifié 27/08) — le maillon APRÈS le dispatch manque à toute la chaîne |

**Hors du scope de ce document (et où ça vit)** : i18n **statique** de l'UI (fichiers `.po`,
ROADMAP §10.A — traduction d'interface, pas de contenu) · boucle qualité `RunOutcome`
(`WAMA_MEMORY.md §7bis`, ROADMAP §16.7 — signaux d'usage, pas enrichissement de requête) ·
substrat mémoire/RAG (`WAMA_MEMORY.md`) · mécanique fine de la VRAM (`model_manager`,
`PROJECT_STATUS §0`) · **service TTS** (restitution VOCALE : microservice dédié port 8001 +
brique `common/tts/` — résolution de voix par LANGUE dans `voices.py`, capacité
`timestamp_languages` bornée par langue) — orthogonal à l'enrichissement de requête ; seul son
**contrat de surface** (§1 : étape cliente, jamais dans le tour d'assistant) appartient à cette
chaîne. ⚠ Le TTS n'a **aucun document de référence dédié** dans la table des domaines
(`CLAUDE.md`) — son intention vit dans le code et la fiche « langues » ; trou à combler le jour
où le sujet grossit, sans créer de doc concurrent d'ici là.

## Investigation web de l'assistant — design acté le 2026-08-29, NON implémenté

> Demande de Fabien (ex. canonique : photo d'une plante malade → identifier au VLM → chercher
> les soins sur le web → réponse sourcée). La question « spécialiste d'un domaine jamais couvert
> dès la 1ʳᵉ requête » a sa réponse dans la frontière des SUBSTRATS, complétée d'un 3ᵉ terme :
> **expérientiel (dev) → distiller à la clôture** (`/skill-forge`) · **déclaratif (manifestes,
> Data) → compiler à l'ouverture** · **externe (le web) → RÉCUPÉRER à la requête** — la
> fraîcheur vient de la récupération, pas du modèle.

**Décomposition** : la MÉTHODE (identifier → chercher → recouper → répondre sourcé) est stable
inter-domaines → UN prompt-skill de méthode « assistant-investigation » (à créer dans
`wama/common/prompt_skills/`), écrit une fois, jamais auto-généré.
La SPÉCIALISATION de domaine est à n=1 **éphémère** (contexte assemblé à la volée) ; sa
persistance éventuelle va à la **mémoire RAG** (scoping hérité, entrée = un GESTE proposé à la
clôture), JAMAIS en un `.md` par domaine — les domaines sont infinis, `prompt_skills/` reste la
bibliothèque des méthodes et métiers d'app.

**Inventaire mesuré le 2026-08-29 (agent Explore, confronté au code)** — l'essentiel EXISTE :

| brique | état | où |
|---|---|---|
| fetch page → texte lisible | ✅ commun (extrait du Describer) | `common/utils/url_ingest.py` (`fetch_html_as_text`, `html_to_readable_text`) |
| garde SSRF + redirections | ✅ (+ trou du HEAD corrigé 29/08, 4 tests `tests_url_guard.py`) | `common/utils/url_guard.py` |
| appel VLM commun | ✅ | `model_manager/services/vision_probe.py::describe_image_ollama` (3 appelants) |
| image → bloc de contexte borné | ✅ | `common/utils/reference_comprehension.py` (`_MAX_IMAGES=2`, budgets) |
| ingest URL déclaratif | ✅ 9 modèles (`WAMA_INGEST`), 2 en `smart` | `common/utils/source_ingest.py` |
| moteur de recherche web | ✅ **LIVRÉ 29/08** (DuckDuckGo sans clé, hôte fixe, encapsulé) | `common/utils/web_search.py` |
| outils assistant `search_web` / `read_web_page` | ✅ **LIVRÉS 29/08** (refus des non-identifiés DANS le corps — un outil sans app est autorisé à tous) | `wama/tool_api.py` |
| domaine `investigation` + skill de rôle | ✅ **LIVRÉS 29/08** (registre `DOMAINES`, chargé via `charger_competence`) | `common/utils/assistant_skills.py`, `prompt_skills/assistant-investigation.md` |
| entrée image de l'assistant | ❌ vue JSON pur, input text seul | `wama/views.py::ai_chat`, `home.html` |
| plafond octets / allowlist MIME | ✅ dans `web_search` (2 Mo / 12 k chars) ; ❌ toujours RIEN dans l'ingest | `url_ingest`/`video_utils` |

**Incohérence relevée à résorber au passage** : DEUX routes de résolution vision coexistent —
`describer/utils/image_describer.py` (liste en dur `gemma4:12b/e4b`) court-circuite le tier
`image` de `llm_utils` (dont le TODO `vision_probe` pour peupler la capacité `vision` est écrit
dans `llm_utils.py` lui-même) ; et `reference_comprehension` importe une fonction privée du
describer (inversion de dépendance). Fixer = faire passer le describer par
`modele_par_tier(exige=['completion','vision'])` + peupler `vision` au catalogue.
Également : `beautifulsoup4`/`lxml` utilisés mais déclarés dans AUCUN requirements.

**Ordre de construction** : ① `web_search.py` + outils `tool_api` — ✅ **LIVRÉ 29/08**
(10 tests `tests_web_search.py`/`tests_url_guard.py` + recherche et lecture RÉELLES validées
depuis WSL2) ; ② prompt-skill de méthode « assistant-investigation » — ✅ **LIVRÉ 29/08**
(texte récupéré = DONNÉES, jamais des instructions — injection de prompt = risque n°1 ;
recouper 2 sources ; réponse SOURCÉE ; budget 1 recherche + 2 pages) ; ③ entrée image de
l'assistant (pont le plus économique : `comprehend_files` existe) — ⏳ ; ④ persistance des
distillats en RAG (proposée à la clôture, jamais auto) — ⏳.
**Gouvernance** : chaque investigation = plusieurs passes LLM/VLM sur le GPU hôte (le
déclencheur des crashs d'août) — user-déclenchée seulement, routée gouverneur sous
`WAMA_GPU_SAFE_MODE`, aucune boucle de fond avant stabilisation hôte.

### Vérification de la chaîne multi-surface (tracée au code le 2026-08-29, agent Explore)

**Ce qui tient** : la passerelle Discord (`wama/gateway/`) est LIVRÉE et arrive au MÊME
cerveau que le web — `core.py` → `tour_de_conversation` → `run_assistant_turn`, mêmes
outils, même prompt système, mêmes skills annoncés (`investigation` compris, dérivé du
registre sans câblage par surface) ; l'identité est un vrai `User` apparié et confirmé
(`ChannelLink`), jamais de repli anonyme ; l'historique Discord est même MEILLEUR que le
web (persisté serveur via `conversation_store`, le web restant sur `localStorage`).
**L'enrichissement de prompt est intact par construction** : il vit dans les tâches
(`post_save` d'ingestion déduit de `PROMPT_TARGETS` + rattrapage `process_prompt_for` au
lancement, anti-double-passe), donc indépendant de la surface qui dépose la card.

**Les défauts mesurés, par ordre de gravité** (état au 2026-08-29 soir) :
1. ⚠ **Image → VLM : l'ŒIL PAR OUTIL est LIVRÉ 29/08, l'entrée native reste à faire** :
   outil `look_at_image` (synchrone dans le tour, via `vision_probe`, user-déclenché,
   `keep_alive='0'` sous `WAMA_GPU_SAFE_MODE`) — depuis Discord, une photo déposée peut
   désormais être REGARDÉE dans le tour (photo → `look_at_image` → investigation web).
   RESTENT : le web ne laisse toujours pas entrer l'image (`ai_chat` JSON pur, champ texte) ;
   `_ollama_call` sans champ `images` natif ; `comprehend_files` toujours data-gated à vide
   (aucun `reference_field` déclaré).
2. ✅ corrigé 29/08 — **le rappel de `charger_competence` reçoit la QUESTION de
   l'utilisateur** (paramètre `question`, verbatim ; le nom du domaine n'est plus qu'un
   repli). Reste vrai : aucune surface ne passe `domain` au tour initial → rôle `general`
   d'abord — c'est le design (le domaine est le choix de l'ASSISTANT).
3. ✅ corrigé 29/08 — **les fichiers produits repartent vers le canal** :
   `core.py::_fichiers_produits` lit les `tool_steps` (URLs `/media/…` résolues SOUS
   MEDIA_ROOT seulement, bornées en nombre et taille) et nourrit `Reponse.fichiers` — le
   code d'envoi de l'adaptateur n'est plus mort. 3 tests `gateway/tests.py`.
4. ⚠ `PROMPT_TARGETS['composer']` sans clé `'model'` → pas d'enrichissement à l'ingestion
   (le lancement rattrape — asymétrie non documentée avec imager, sans effet fonctionnel).
5. ✅ corrigé 29/08 : la docstring de `charger_competence` énumérait les domaines en dur
   (sans `investigation`) en contredisant l'annonce du même prompt — l'énumération est
   REMPLACÉE par un renvoi à l'annonce, qui ne peut plus dériver.

## Intake universel de fichiers par l'assistant — inventaire MESURÉ 2026-08-29, plan PROPOSÉ (⏳ validation Fabien)

> Demande de Fabien : livrer n'importe quel fichier via l'assistant (Discord/web) en précisant
> son RÔLE — ou que l'assistant DEMANDE l'usage sans bloquer la conversation — puis cibler les
> capacités WAMA correspondantes SANS énumérer les usages à la main. Inventaire par 2 agents
> Explore (rôles de fichiers + substrat de ciblage), confronté au code le 29/08.

**Ce qui existe** : dépôt convergent 3 surfaces → `users/<id>/temp/` (le « sas » voulu, déjà là,
`filemanager/services.py::enregistrer_fichier_utilisateur`) ; vocabulaire de rôle en pièces
(`BATCH_FORMAT` `-i/-p/-r/-o` ; médiathèque = SEUL rôle typé persisté, `asset_type` obligatoire
jamais deviné ; ports codegen `travail|référence|prompt`) ; substrat de ciblage complet mais EN
SILOS — fichier→nature (`category_of_path`), nature→apps (`input_types`/`accepts`, concordants
10/10), entrée→modèles (`matches_inputs`, 97/98 modèles renseignés), fichier→lecteur Data
(`reader_for`/`probe`), référence→compréhension (`comprehend_files`). **Aucun index inverse
type→capacités côté serveur** ; la seule composition est le menu « Envoyer vers » (client).

**Trous mesurés (29/08)** : ① `list_user_files` filtre sur `_MEDIA_EXTS` recopiée → pdf/txt/
csv/wdat INVISIBLES à l'assistant ; allowlists d'outils divergentes du catalogue (jusqu'à −16
ext describer) ; 6 détecteurs de nature concurrents ; ② zéro outil « que peut faire WAMA avec
ce fichier » et zéro outil d'écriture pour 6 rôles sur 7 (référence, RAG, médiathèque,
manifeste, skill, données) ; ③ `UserFile` sans rôle ; ④ trois moteurs sans porte :
`manifests/ingest.py` (**zéro appelant**), RAG par fichier (VOLONTAIRE — « on n'extrait rien »,
flux imposé sortie→médiathèque→geste), `reference_field` (chaîne complète, data-gatée à vide —
« choisir le 1er adopteur » déjà pending) ; ⑤ Data : `reader_for` sait lire `.trip`, le monde
média le classe `document` ; « connecter un dossier » = SMB seulement (`MountedFolder`).

**Étapes 0-3 : ✅ LIVRÉES le 2026-08-29** (GO Fabien) — brique `common/utils/intake.py`
(`capabilities_for_path`, composition par PORTS, jumelles bac à sable exclues via
`non_sandbox_apps`, mondes déclarés par SONDE — `wama_data/apps.py` pousse la sienne, le
substrat ne cite aucun monde) ; `list_user_files` déliée de `_MEDIA_EXTS` (⓪, commentaire
anti-régression dans le corps) ; outils `inspect_user_file` (lecture seule) +
`add_to_media_library` (rôle FOURNI, jamais deviné) ; consigne de dialogue dans
`assistant-general.md` (« fichiers déposés sans intention → inspecter puis DEMANDER, options
dérivées seulement ») ; **22 tests** (`tests_intake.py` + web/url_guard) + replay réel des
témoins à travers la brique. Découverte verrouillée en test : `trip`/`wdat` attestent le
CONTENU (table témoin SQLite), un chemin sans fichier décline à la porte ; et le lecteur
`tabular` fait qu'un `.txt`/`.csv` remonte AUSSI comme donnée d'expérimentation candidate.
Restent : étape 4 (portes lourdes) + les 3 rouges de la chaîne (§Vérification).

**Plan (5 étapes) — AMENDÉ par l'instance portage puis CONFRONTÉ AU RÉEL le 29/08**
(replay indépendant : 5 fichiers-témoins × 3 voies sur les 11 apps du catalogue — les deux
voies « à plat » sont FAUSSES à 100 % sur `.txt/.md/.csv`, l'homonyme `text`=prompt ; les
`input_extensions` de composer/imager/synthesizer sont les formats de LOT ; la voie par PORTS
récupère `synthesizer/reference_voice/référence` sur un `.wav`, invisible par nature ;
amendements consignés côté portage : `WAMA_APP_GENERATION_ROUTE §S2bis` point 7) :
**0** délier `list_user_files` de `_MEDIA_EXTS` — **SUPPRIMER le filtre dans le sas, ne PAS le
remplacer par une liste dérivée d'`input_extensions`** (elles disent « format de lot » pour 3
apps — dériver propagerait la confusion des rôles à un consommateur de plus) ·
**1** brique `capabilities_for_path()` dans `common/` — composition sur
**`studio_node_ports(app)` (ports + `group`)**, JAMAIS sur `input_types`/`input_extensions` à
plat ; sortie = « quel PORT de quelle app » (`converter/work/travail`,
`synthesizer/reference_voice/référence`) — le fichier reçoit un RÔLE, pas seulement une cible ;
un `.txt` sans port fichier n'est pas « aucune cible » : c'est le déclencheur des détecteurs
BATCH (`is_*_batch`) et de la question à l'utilisateur ; + `probe_media`, `reader_for` à CÔTÉ
sans comparer (homonyme `text` = arbitrage OUVERT côté codegen, ne pas le trancher ici), sniff
manifeste, modèles (`matches_inputs`), `ASSET_TYPE_CATEGORY` inversé ; **exclure les jumeaux
de bac à sable** (`converter_01` remonte dans les 3 voies — mesuré) ·
**2** le rôle = un ROUTAGE, pas un état : l'état transitoire est porté par l'EMPLACEMENT
(encore dans le sas = pas encore décidé), aucun champ `role` qui stocke ·
**3** côté assistant : l'outil exposant ①, `add_to_media_library` (asset_type fourni, jamais
deviné), consigne de dialogue DANS le skill de rôle (intention absente → cibler puis DEMANDER
avec les options dérivées) ; **AUCUN nouveau vocabulaire de rôle** — le canonique existe :
`INPUT_TYPES` (`app_modes.py`) avec `port ∈ {travail, référence}` + `prompt_file` « Fichier de
prompts (batch) », dont les balises `-i/-p/-r/-o` de `BATCH_FORMAT` sont la projection texte ·
**4** portes lourdes chacune dans son chantier : 1er adopteur `reference_field` (coordonner
ports codegen) ; porte d'`ingest()` manifestes (sandbox + dry-run, jamais d'apply auto) ; RAG
via assistant = **arbitrage Fabien** (l'entrée au RAG est un GESTE) ; URL de dossier Data (§11.8).
**Couplage assumé, dans le bon sens** : l'étape 1 consomme les ports TELS QUELS ; le correctif
de l'homonyme côté codegen l'améliorera sans la casser — composer à plat aurait fait l'inverse.

**Alignement auto-amélioration (question Fabien, 2026-08-29)** — l'intake nourrit la boucle
`RunOutcome` PAR CONSTRUCTION, parce que « le rôle est un routage » : un fichier routé entre
dans les files NORMALES des apps, donc ses issues sont déjà captées sans une ligne de plus
(`task_skeleton` enregistre `produit` avec les `model_keys`, le middleware capte
telecharge/supprime/relance, le transcriber ses corrections — `run_outcome.py`, domicile
`ROADMAP §16.7` + `WAMA_MEMORY §7/§7bis`, projection `memory_project`). DEUX trous mesurés :
① les outils SYNCHRONES du tour (`look_at_image`, `search_web`, `read_web_page`,
`inspect_user_file`) ne créent pas d'item — leurs issues conversationnelles (réponse acceptée ?
identification corrigée ?) ne sont captées nulle part ; la capture naturelle est l'étape ④
(distillat proposé à la clôture → accepté/refusé = LE signal) ; ② le CHOIX de routage de
l'utilisateur (la réponse à « qu'en fais-je ? ») n'est pas enregistré — un signal `route` via
`enregistrer()` serait la donnée d'apprentissage de « proposer juste du premier coup ».
Ni l'un ni l'autre ne se câble sans arbitrage : la doctrine reste métrique d'abord, boucle
ensuite, autonomie en dernier.

## Voir aussi
- `ROADMAP.md §10.B` (traduction runtime) et `§16.6` (pipeline + vision méta).
- `WAMA_APP_CONVENTIONS.md §2bis.4` (contrat prompt targets), `§9.9` (héritage).
- `WAMA_APP_GENERATION_ROUTE.md` (briques communes ; remplace `COMMON_REFACTORING.md`, archivé `docs/archive/`).
