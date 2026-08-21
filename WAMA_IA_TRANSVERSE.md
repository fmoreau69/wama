# WAMA_IA_TRANSVERSE.md — IA transverse : prompts, skills, RAG & chaîne complète (§10.B / §16.6)

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
| **DÉVELOPPEUR / workflow** | wama-dev-ai importe `PROMPT_SKILLS_DIR` (les mêmes fichiers) ; rôle `assistant-dev` ; outil `ask_claude_code` | ✅ |
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
chemin ci-dessus — le studio n'implémente **rien**, il hérite tout des apps. **wama-dev-ai** :
importe `PROMPT_SKILLS_DIR` (les mêmes fichiers de skills).

### 2bis. Traduction automatique ENTRÉE / SORTIE (vision §12) — l'entrée vit, la sortie n'est pas branchée

```
entrée : utilisateur (fr) ──routage──▶ [modèle gère fr ? DIRECT · sinon traduire fr→pivot] ──▶ modèle
sortie : modèle (pivot)   ──routage──▶ [output_translate ? traduire pivot→fr]              ──▶ utilisateur
```

- **ENTRÉE ✅** — vécue dans `process_prompt_for` (§2) : `lang_routing` DÉCIDE (capacités du
  modèle cible ; `_TYPE_LANG_DEFAULT` diffusion/music → EN), `translator` AGIT (translategemma,
  glossaire do-not-translate, passthrough si la langue est gérée → coût nul, silence si direct).
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
  fournisseurs **cloud** via `llm_chat` (LiteLLM, ROADMAP §8d — livré).
- **Apps** : `select_model()` (model_manager) — VRAM-aware, `prefer_loaded`, capacités requises ;
  les tiers de `llm_utils` s'appuient dessus.
- **Cible non atteinte** (§15 + ROADMAP §8d) : croiser **intention + fichiers d'entrée +
  résultats du RAG** pour choisir le modèle, et l'escalade cloud par *capacité* (VRAM saturée) —
  aujourd'hui seule l'escalade par **contexte** est vécue. C'est la ligne 5 du tableau §5.
- **Post-génération — QC** : la vision §15 s'arrête au dispatch, mais la chaîne réelle a un
  maillon prévu APRÈS le modèle : `qc.py::assess_output_quality` (validateur LLM indépendant,
  ROADMAP §16.5). **0 consommateur hors bench** (vérifié par grep — la carte des mécanismes le
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
État : le RAG est **VIDE par décision** (balayage initial purgé, 939 → 0) tant que les surfaces
du geste n'existent pas (jalon 14 de `WAMA_MEMORY.md`).

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
| 8 | Peuplement : `OrgUnit` + affiliations des profils | ❌ 0 en base | débloque le niveau labo SANS code (sync LDAP/SUPANN prévue) |
| 9 | Surfaces du geste RAG + page de gestion (défaut de niveaux, retrait) | ⏳ jalon 14 | placement à trancher avec Fabien |
| 10 | **Traduction de SORTIE** (§12 : `Traitement IA → Traduction sortie → Utilisateur`) | ❌ non branchée | décideur (`output_translate`) + acteur (`translate_output`) livrés, **zéro appelant** ; candidats = textes GÉNÉRÉS uniquement — jamais transcription/OCR (fidélité verbatim) |
| 11 | **Parseur STRUCTUREL de document** (§13 : texte / figures / images-texte → traitement → réassemblage, mise en page conservée) | ❌ | aujourd'hui : `batch_parsers` (texte brut) + `comprehend_files` (grounding) — la STRUCTURE est perdue ; brique commune prévue pour Describer + futur Translator ; Docling « à évaluer » (§16.2) est ce candidat |
| 12 | **QC post-génération** (§16.5 : validateur LLM indépendant après le modèle) | ❌ brique morte | `qc.py` : 0 consommateur hors bench (grep 22/08) — le maillon APRÈS le dispatch manque à toute la chaîne |

**Hors du scope de ce document (et où ça vit)** : i18n **statique** de l'UI (fichiers `.po`,
ROADMAP §10.A — traduction d'interface, pas de contenu) · boucle qualité `RunOutcome`
(`WAMA_MEMORY.md §7bis`, ROADMAP §16.7 — signaux d'usage, pas enrichissement de requête) ·
substrat mémoire/RAG (`WAMA_MEMORY.md`) · mécanique fine de la VRAM (`model_manager`,
`PROJECT_STATUS §0`).

## Voir aussi
- `ROADMAP.md §10.B` (traduction runtime) et `§16.6` (pipeline + vision méta).
- `WAMA_APP_CONVENTIONS.md §2bis.4` (contrat prompt targets), `§9.9` (héritage).
- `WAMA_APP_GENERATION_ROUTE.md` (briques communes ; remplace `COMMON_REFACTORING.md`, archivé `docs/archive/`).
