# PROMPT_PIPELINE.md — Pipeline de prompts commune (§10.B / §16.6)

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
- assistant IA : ses tools dispatchent les tâches Celery → skills appliqués by design ;
- wama-dev-ai : importe le même module (`PROMPT_SKILLS_DIR` dans son `config.py`).

Règles DANS LE CODE (mécanisme, pas skills) : clause de langue d'émission + préservation
verbatim des mots-clés forcés (`glossary`). Contrat : `wama/common/prompt_skills/README.md`.
Comblé au passage : `generate_video_task` (imager) n'appelait PAS la pipeline (variables
locales `_prompt`/`_negative`, la base garde l'original) ; composer `enrich=True` (le blocage
« consignes visuelles » est levé par `composer-music.md`).

## Hooks à venir
- **RAG** (`apply_rag`, commenté dans `prompt_pipeline`) : récupération depuis store **ChromaDB** +
  embeddings **bge-m3**. No-op tant que la fondation `wama/rag/` + l'indexation (§8c) n'existent pas.
- **QC** : câbler `qc.py` en post-génération dans les apps (seul consommateur actuel = la
  commande de bench `bench_describer`).

## Réglages (`wama/settings.py`)
- `WAMA_PROMPT_ENRICH` (env, **défaut ON depuis 2026-07-30**) — **kill switch plateforme**, plus
  l'interrupteur maître. `=0` coupe l'enrichissement pour tout le monde (incident ressources, debug).
- `UserProfile.prompt_enrich` (défaut `True`) — **le vrai interrupteur**. L'utilisateur n'a pas à
  connaître la chaîne derrière son prompt, mais il peut la couper. Arbitrage : `enrichment_enabled(user)`.
- `WAMA_PROMPT_ENRICH_MODEL` (env, optionnel) — modèle d'enrichissement (défaut `llm_chat` =
  `qwen3.5:9b`). **Choix mesuré** (bench 2026-07-29) : `qwen3.5:4b` est plus léger/rapide mais viole
  la clause de langue 3/3 sur prompt court et dérive le sujet → ne pas basculer. Détail dans le
  docstring de `prompt_enrichment.py`.

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

## RAG — anticipation de l'architecture (PAS encore implémenté, prochain gros chantier)

> Décision (Fabien, 2026-06) : **différer l'implémentation** (l'harmonisation UI/modes/cards est la
> priorité et fournit le socle), mais **anticiper l'archi** pour ne pas se peindre dans un coin.

- **Point de branchement = l'étape `enrich` de CETTE pipeline.** Enrichir un prompt = récupérer du
  contexte documentaire (ChromaDB, cf. Lescot) en plus de la passe LLM. Zéro nouvelle surface : le RAG
  s'injecte dans l'enrichissement déjà déclaré par `PROMPT_TARGETS`.
- **Niveaux (hiérarchie d'héritage)** : `université → labo/service → équipe → individuel`, **extensible
  vers le haut** (national, global, général). Chaque niveau **hérite** des niveaux au-dessus — c'est le
  **MÊME pattern d'héritage que batch→item (`WAMA_APP_CONVENTIONS §9.9`)**, réutilisable.
- **Opt-in utilisateur** : base = RAG **individuel** ; l'utilisateur **choisit** d'activer les niveaux
  supérieurs (équipe/labo/université) → cohérent RGPD (rien de partagé par défaut).
- **Stockage** : ChromaDB (par niveau / collection). Glossaire do-not-translate Lescot (cf. roadmap Translator).

## Voir aussi
- `ROADMAP.md §10.B` (traduction runtime) et `§16.6` (pipeline + vision méta).
- `WAMA_APP_CONVENTIONS.md §2bis.4` (contrat prompt targets), `§9.9` (héritage).
- `WAMA_APP_GENERATION_ROUTE.md` (briques communes ; remplace `COMMON_REFACTORING.md`, archivé `docs/archive/`).
