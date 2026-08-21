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

## PROMPT + RAG — la chaîne complète (état MESURÉ au 2026-08-21)

> ⚠ Cette section remplace l'ancienne « anticipation de l'architecture », périmée sur deux
> points : elle annonçait « PAS encore implémenté » (le RAG de l'assistant est livré) et
> **ChromaDB** (le stockage réel est **pgvector**, cf. `WAMA_MEMORY.md`).

### Le principe, en une phrase

Une demande utilisateur est complétée par **trois apports distincts** avant d'atteindre un
modèle : **QUI répond** (skill de rôle), **COMMENT écrire le prompt** (skill d'enrichissement)
et **CE QUE SAIT le laboratoire** (RAG). Les trois sont **déclarés**, jamais écrits en dur, et
chacun s'applique à un endroit différent de la chaîne.

### Les DEUX familles de skills — contrats opposés, ne pas confondre

| Famille | Fichiers | Destinataire | Contrat | Appliqué |
|---|---|---|---|---|
| **Rôle** | `assistant-*.md` | l'assistant lui-même | ne transforme rien : posture, domaine, interdits | prompt système (`assistant_engine`) |
| **Enrichissement** | `imager-image.md`, `composer-music.md`… | LLM d'enrichissement | transforme un prompt, **rend le prompt seul** | dans l'app, au lancement (`process_prompt_for`) |

Registre des rôles : `common/utils/assistant_skills.py::DOMAINES` (`general`, `science`,
`design`, `dev`). Registre des cibles d'enrichissement : `app_metadata.py::PROMPT_TARGETS`.

### Les DEUX chemins d'une demande — et pourquoi le RAG doit être aux deux endroits

**Chemin A — par l'assistant** (« propose-moi un logo pour le labo ») ✅ **livré 21/08**
```
demande → skill de RÔLE (design)  +  RAG labo (contexte)  →  l'assistant COMPOSE un prompt informé
       → outil create_image(prompt=…)  →  l'app enrichit (skill imager-image)  →  génération
```
Le contexte du laboratoire arrive **avant** la composition : l'assistant sait déjà ce qu'est
le labo, donc le prompt qu'il écrit le porte. C'est ce qui évite de tout redécrire à chaque
demande.

**Chemin B — directement dans l'app** (bouton ✨ de l'imager) ⏳ **le RAG y manque**
```
prompt tapé → l'app enrichit (skill imager-image)  →  génération
                        ↑ AUCUN contexte de laboratoire
```
Le hook RAG de l'enrichissement existe (`prompt_pipeline`, paramètre `rag`) mais il est
**`rag=False` par défaut et aucun appelant ne l'active** — donc l'utilisateur qui passe par
l'app plutôt que par l'assistant perd tout le contexte.

> **Arbitrage Fabien (21/08)** : il FAUT activer le RAG sur le chemin B. L'objection retenue
> jusqu'ici était « 5 s par génération, très visible » — **elle ne tient pas ici** : une
> génération d'image est **asynchrone (Celery) et dure 10 à 60 s**, l'utilisateur ne regarde
> pas l'écran. Ces 5 s sont visibles dans le **chat**, pas dans une tâche de fond. L'arbitrage
> actuel a écarté le RAG là où il coûte le moins et rapporte le plus.

### Les trois gardes du rappel de contexte (livrées, chemin A)

Elles valent pour tout branchement RAG, y compris le futur chemin B :
1. **DÉCLARÉ** — seuls les domaines marqués `rag=True` paient la recherche. Pas de vectoriel
   sur « où en est ma transcription ? ».
2. **DATA-GATED** — aucun extrait pertinent ⇒ prompt **inchangé**. On n'injecte jamais de
   bruit : un contexte hors-sujet dégrade plus qu'il n'aide.
3. **FAIL-SAFE** — toute panne du rappel rend `''`. Le RAG est un **bonus de contexte**, jamais
   une dépendance de la conversation.

Chaque extrait est injecté **avec sa référence** : un contexte sans provenance n'est pas
vérifiable par l'utilisateur, et l'assistant doit pouvoir le citer.

### Le MULTI-NIVEAU — la structure existe DÉJÀ, elle n'est pas à construire

Cible : `université → labo/service → équipe → utilisateur`, chaque niveau héritant des
niveaux au-dessus. **C'est exactement ce que `ScopedVisibility` + `OrgUnit` font déjà** —
il n'y a pas de mécanisme à écrire, seulement des données à peupler.

| Niveau visé | Mécanisme EXISTANT | Où |
|---|---|---|
| Utilisateur (privé) | `visibility='private'` + `user` | `common/models.py:190` |
| Équipe / labo / dépt / université | `visibility='unit'` + `scope_org_unit` | idem |
| Projet (⚠ **traverse** les orgs — partenaires externes) | `visibility='project'` + `scope_project` | idem |
| Public | `visibility='public'` | idem |

**L'héritage est déjà hiérarchique** : `OrgUnit` a un `parent` (institut → université →
département → labo → service → équipe), et `user_scope_org_ids()` (`common/models.py:167`)
remonte **tous les ancêtres** — un fragment partagé au LABO est donc visible d'un membre d'une
ÉQUIPE du labo, sans rien coder de plus. `scoped_visible_q()` (`:206`) compose les quatre
niveaux en un seul `Q`, et `recall()` l'applique : **le rappel est scopé par construction**,
il n'y a rien à re-garder côté assistant ni côté canal.

**Aujourd'hui, deux niveaux suffisent** (labo + utilisateur) : ce sont deux valeurs de
`visibility`, pas deux implémentations. Passer à quatre = peupler `OrgUnit` et renseigner les
affiliations des profils — **aucune migration, aucun code**.

⚠ **Piège connu** : sur `RagChunk`, la visibilité est **dénormalisée depuis la source**
(`common/models.py:704`). Changer la visibilité d'un document ne repropage donc pas seule aux
fragments déjà indexés — la réindexation fait foi.

### Reste à faire

| # | Chantier | Note |
|---|---|---|
| 1 | **RAG sur le chemin B** (enrichissement d'app) | l'arbitrage ci-dessus ; hook `rag` déjà présent, personne ne l'active |
| 2 | Sélecteur de domaine dans l'UI | `domaines_pour_ui()` prêt ; ⚠ touche `home.html`, fichier disputé |
| 3 | Domaine déduit du canal (passerelle) | salon `#dev` → domaine `dev` |
| 4 | Peupler `OrgUnit` + affiliations | débloque les 4 niveaux sans une ligne de code |
| 5 | Opt-in utilisateur par niveau (RGPD) | intention d'origine : base = privé, l'utilisateur ÉLARGIT |

## Voir aussi
- `ROADMAP.md §10.B` (traduction runtime) et `§16.6` (pipeline + vision méta).
- `WAMA_APP_CONVENTIONS.md §2bis.4` (contrat prompt targets), `§9.9` (héritage).
- `WAMA_APP_GENERATION_ROUTE.md` (briques communes ; remplace `COMMON_REFACTORING.md`, archivé `docs/archive/`).
