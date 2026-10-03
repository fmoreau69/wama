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
| anonymizer | `sam3_prompt` | concept | `when={'field': 'target_mode', 'equals': 'description'}` (le mode de l'élément, 2026-09-27) |
| cam_analyzer | `sam3_markings_prompts` | concept | `when='sam3_markings_enabled'` (corrigé le 2026-09-27 : `use_sam3` n'existe pas sur la session), `domain='transport'`, `list_item_field='prompt'` (liste `{label,prompt}`) |
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
- `WAMA_GPU_SAFE_MODE` (env, défaut OFF — activé dans `.env` de l'hôte fragile le 2026-08-28,
  **levé le 2026-09-22** ; instabilité de l'hôte déclarée résolue le 2026-09-28) —
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
| **A. Hiérarchie ORGANISATIONNELLE** | qui appartient à quoi ? | arbre `OrgUnit` (`parent` : institut→université→département→labo→service→équipe) + affiliations du profil (`org_affiliations` — une **LISTE** : multi-labos, multi-équipes) | mécanisme ✅ (héritage ancêtres testé) · données ✅ **5 `OrgUnit` en base** (mesuré 2026-09-09 ; cette ligne annonçait **0**, chiffre du 22/08 jamais repris — le niveau `unit` a donc de quoi s'accrocher) |
| **B. Niveaux de PARTAGE du RAG** | qui peut rappeler ce document ? | `ScopedVisibility` porté par chaque fragment : `user` / `unit` / `project` / `public` | écriture `user`+`unit` ✅ (`project` ANNONCÉ, `public` plus tard) · lecture `rag_niveaux` ✅ : son RAG / labo / les deux / **rien** |
| **C. Niveaux d'ENRICHISSEMENT du prompt** (vision §10) | qu'ajoute-t-on au prompt avant le modèle ? | global (règles DANS le code : langue d'émission, glossaire verbatim) · métier (skills `<app>-<domaine>.md`) · organisationnel · utilisateur | global ✅ · métier ✅ · **organisationnel ❌** · **utilisateur ❌** |

### 0bis. Les SKILLS — deux natures de contrat, cinq familles (vision §9), état mesuré

**Rôle vs skill** (transversal) : le RÔLE fixe *qui répond* — un seul actif, `assistant-*.md`,
appliqué au prompt système ; les SKILLS disent *comment traiter* — composables, appliqués à
l'enrichissement. Contrats opposés : un skill de rôle ne transforme rien, un skill
d'enrichissement transforme un prompt et ne rend que lui. Les confondre coûte une passe LLM
inutile ou un assistant sans posture.

> ✅ **Cette distinction est CÂBLÉE depuis le 2026-08-27, pas seulement écrite ici** :
> `common/services/skills_catalog.py` déclare trois familles (`enrichissement` / `role` /
> `repli`), calcule *qui consomme quoi* en REJOUANT la résolution, et affiche les deux écarts
> muets ailleurs (skill orphelin, target sans skill). Mesuré le 2026-09-09 :
> **5 enrichissement · 5 rôle · 1 repli · 0 orphelin**, et 1 target orphelin
> (`assistant · message · intent`) qui est ATTENDU — ce kind ne fait que du routage de langue
> (§1). Le registre `skills` ne rend qu'un COMPTEUR (11) : lire ce total comme la structure fait
> conclure à un mélange qui n'existe pas.
>
> 📊 **ÉTENDU à CINQ familles le 2026-09-09** — la page catalogue les montre toutes
> (`services/skills_catalog.py`, `/common/skills/`) : `enrichissement` 5 · `role` 5 · `repli` 1 ·
> **`role_dev` 11** (`wama-dev-ai/prompts/*.txt`) · **`dev_agent` 14** (`.claude/skills/*/`).
> Chaque carte affiche son **mécanisme de sélection**, parce que c'est lui qui impose le format.
>
> 🔴 **FUSION DES DEUX FAMILLES DE DEV : ÉCARTÉE, et par la mesure.** On avait prévu de réunir
> `wama-dev-ai/prompts/` et `.claude/skills/` dans un seul dossier, au motif qu'ils travaillent
> tous deux sur le CODE. Relevé du 2026-09-09 : **5 des 11 consignes de rôle sont des gabarits
> `.format()`** — `architect {code}`, `audit {task,tools}`, `cartography {task,tools}`,
> `debug {code}`, `dev {files,task}`. Les porter au format SKILL.md casserait la substitution
> (`cli.py::_build_prompt`, la garde `{tools}` de `run_audit.py`) **et** le contrat du format,
> dont le corps est lu VERBATIM. Et le critère ci-dessous tranche dans le même sens :
> `consigne_role(nom)` sélectionne **par nom de rôle**, jamais par description — donc
> `role_dev` est de la nature de `prompt_skills/`, pas de celle de `.claude/skills/`. Le partage
> est **4 contre 1**, pas 2 contre 2. *Les quatre familles se rejoignent sur la PAGE, pas sur le
> disque.* Le doublon `cartography` ↔ `cartographie` y est désormais visible côte à côte : c'est
> là qu'on en décidera, pas par une chirurgie de fichiers.
>
> 🔒 **La frontière de FORMAT en découle, et c'est le consommateur FINAL qui la fixe**
> (tranché avec Fabien le 2026-09-09) : un modèle de diffusion, SAM3 ou MusicGen ne peuvent
> qu'**encaisser une chaîne** — ils ne savent pas choisir une consigne, donc c'est le CODE qui
> choisit pour eux (`resolve_skill`), et le fichier reste **nu** (il EST le system prompt). Un
> AGENT lit des descriptions et choisit — d'où le format SKILL.md à frontmatter, réservé aux
> consignes de DÉVELOPPEMENT (`.claude/skills/`, cf. `ROADMAP §16.7`). Deux formats, parce que
> deux mécanismes de SÉLECTION — pas deux goûts. Mettre un frontmatter sur `imager-image.md`
> n'apporterait rien : personne ne le choisit, il se calcule.

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
  ├─ prompt système : {LANGUE du profil} + RÔLE (role_instructions) + contexte WAMA (files)
  ├─ CONTEXTE LABO : laboratory_context(user, message, domaine)
  │     = recall() hybride scopé — SEULEMENT si le domaine déclare rag=True (science, design)
  │     3 gardes : DÉCLARÉ · DATA-GATED (rien de pertinent ⇒ prompt inchangé) · FAIL-SAFE ('')
  │     chaque extrait injecté AVEC sa référence ([transcriber:134] …)
  │
  └─ boucle LLM à outils (69 outils, gating F7) — c'est ICI que tout se rejoint :
       • charger_competence(domaine)  → l'ASSISTANT charge LUI-MÊME posture + contexte labo
         (jamais la surface : un adaptateur de canal ne devine pas le domaine)
       • memory_recall(query, niveaux=…) → recall() souvenirs + RAG, sélecteur de niveaux,
         HYBRIDE — résidence bge-m3 arbitrée par le GOUVERNEUR (~5 s à froid, ~350 ms résident)
       • add_to_<app> / start_<app> → tâches d'app ⇒ la pipeline d'app s'applique (§2)
  [le message lui-même : kind='intent' via process_prompt_for('assistant','message') —
   routage langue seul, pas d'enrichissement]
```

**Le pivot API — `wama/tool_api.py`** : `TOOL_REGISTRY`, **69 outils** *(mesuré 2026-09-12 ;
disait **51**, périmé — le compte vit ICI, c'est donc ici qu'il se re-mesure : `len(tool_descriptions())`)*
— dont **6 LECTURES TRANSVERSES** livrées le 2026-09-11 (`list_my_items`, `get_item_detail`,
`get_item_preview`, `list_registries`, `get_my_access`, `list_my_memories`), **3 VERBES DE
CYCLE** (`delete_item`, `duplicate_item`, `clear_my_queue`) et **`add_item_to_media_library`**
(2026-09-12 — 3ᵉ surface du geste médiathèque, cf. `CARD_DESIGN §2bis` : même brique que le
menu « … » et que la route d'app, donc mêmes refus) : chantier « compléter l'API »
(`ROADMAP §24.4① quater`).
⭐ Les trois `get_item_*` et les 3 verbes **réutilisent les surfaces de l'app** (`unified_detail`,
`unified_preview`, les vues `delete`/`duplicate`/`clear_all` résolues par `route_variants`) au
lieu de reprojeter ou de recopier des `reset_fields` : l'assistant voit et fait EXACTEMENT ce que
l'utilisateur voit et fait. Une projection propre à l'assistant divergerait, et on déboguerait
deux vérités.

🔴 **GARDE D'APP DES ÉCRITURES — à connaître avant d'ajouter un verbe.** Ces outils sont
**transverses par leur NOM** (`delete_item`, pas `delete_transcriber`) : `app_id_for_tool()` rend
`None`, donc **`tool_accessible()` les autorise à tous** ; et comme ils appellent la vue par une
requête synthétique, ils **court-circuitent aussi `AppAccessMiddleware`**. Les deux couches
habituelles sont donc ABSENTES : la garde est écrite dans leur corps (`_refus_app`), et c'est la
seule. *Éprouvé par un test qui vérifie d'abord que les deux couches sont bien inertes — sinon il
croirait tester la garde alors qu'autre chose protège.* — triades
`add_to_/start_/get_…_status` (déclaratives, marche A4) pour les apps + studio ; l'inventaire
complet et ses trous vivent dans `WAMA_APP_GENERATION_ROUTE.md §11` (trou #18), pas ici. Ce qui
appartient à CE document : les outils **IA-transverses** (gating `None` — aucune app ne les
garde) : `translate_text` (§2bis) · `memory_recall` (§3-4) ·
`charger_competence` (§0bis) · `list_ai_models`/`get_ai_model` (§2ter) · `list_user_files` ·
`switch_ui_mode` · `ask_claude_code` (garde développeur écrite DANS son corps, pas dans le
registre — ne pas « corriger ») · les outils **`dev_*`** (2026-09-22), qui ne sont PAS dans
`TOOL_REGISTRY` : annoncés aux seuls développeurs et RELAYÉS par `mcp_client` à la surface MCP
« wama-dev » (§1ter) · les **6 lectures transverses** et les **3 verbes de cycle**
du 2026-09-11 (ces derniers gardés par `_refus_app` dans leur corps, cf. le 🔴 ci-dessus) ·
et **`add_to_media_library`** depuis le **2026-09-11**.

> ⭐ **Pourquoi `add_to_media_library` a changé de régime** (décision Fabien, 2026-09-11 : « on
> rend commun et on porte sur les apps de façon universelle »). Il était gaté sur l'app
> `media_library` **du seul fait de son nom** — le motif `add_to_<app>` en déduisait une app —
> alors que son jumeau d'Intake `inspect_user_file` est transverse depuis toujours.
> ⚠ Mesuré AVANT de changer : `media_library` est gardée avec `roles: []`, donc le gate était
> **permissif en pratique**. Le défaut n'était pas un refus d'aujourd'hui : `AppAccessPolicy`
> est **éditable en base**, donc restreindre la médiathèque aurait cassé **en silence** un geste
> que toutes les apps sont censées offrir. *Une garde qui dépend d'une politique modifiable ne
> protège pas ce qu'elle a l'air de protéger — elle le rend fragile.* La garantie qui reste est
> l'**ownership** : l'asset est créé pour `user`, dans SA médiathèque.

À venir : ~~`list_my_items`/`get_item_detail`~~ ✅ livrés le 2026-09-11.
Toutes les surfaces (web, API v1 `/api/v1/assistant/chat/`, canaux
Discord/Matrix — ROADMAP §19) passent par ce même pivot : ajouter un outil ICI l'offre partout.

**Surface VOLET DROIT (22/09)** : le mini-chat de l'accordéon « Assistant » (`base.html` →
`common/_assistant_avatar.html`, `wama-assistant-chat.js`) est une 4ᵉ surface CLIENTE du même
moteur — même vue `ai_chat`, même fil `web` (`ai_chat_thread` le sert), mêmes réglages durables ;
la voix est la brique commune `wama-assistant-voice.js` (l'accueil l'utilise aussi). Détail et
état : `WAMA_VOLETS §5`.

⚠ **Contrat de surface** (ROADMAP §19 ①) : le tour d'assistant ne porte **jamais** d'audio — la
TTS est une **étape cliente post-réponse** (`wama-assistant-voice.js` appelle `/api/tts-kokoro/` après coup),
et les visèmes de l'avatar viendront d'un endpoint TTS distinct. C'est la contrepartie de « UN
cerveau, N surfaces » : le contrat commun ne porte que ce qui vaut pour toutes les surfaces —
un bot Discord n'a rien à faire d'un WAV en base64.

#### 1bis. Latence du tour web — MESURÉE le 2026-09-22, **4 leviers sur 5 câblés** (5 le 26/09)

> Constat de Fabien en testant l'assistant vocal (GPU de nouveau utilisable) : réponse ET
> vocalisation lentes. La chaîne est **strictement séquentielle** : `ai_chat` (LLM complet,
> `stream: False`) → affichage → `/api/tts-kokoro/` (WAV complet) → lecture/avatar. Rien ne
> commence avant que l'étape précédente ait FINI.

| maillon | mesure (`qwen3.5:4b`, modèle chaud, RTX 4090) | source |
|---|---|---|
| **réflexion du modèle** | même message : **12,7 s** avec `think` (défaut Ollama : 1 908 jetons dont **7 354 caractères de « pensée »** pour 244 de réponse) contre **2,4 s** sans (`think:false`, 344 jetons, réponse plus complète) | `_ollama_call` n'envoie pas `think` (`assistant_engine.py`) ; `ollama_chat()` de `llm_utils` le sait déjà (`think=False` pour les tâches courtes) |
| **prompt système** | **14 693 caractères ≈ 3 700 jetons** à chaque tour, dont **12 361** pour le prompt d'outils (71 outils) ; l'état des files (**dynamique**, 56 car.) est concaténé **AVANT** le bloc d'outils (fixe) → le cache de préfixe KV d'Ollama est invalidé dès qu'une file change | `run_assistant_turn` : ordre `base + rôle + labo + annonce + files + outils` |
| **pas de flux** | l'utilisateur voit la réponse **entière ou rien** ; la TTS ne démarre qu'après, sur le texte **entier** | `stream: False` ; `speakText` appelé dans `addMessage` |
| **TTS** | service `kokoro-onnx` chaud (port 8001, `read_timeout=30`) : coût ≈ longueur du texte ; un WAV base64 unique | `_tts_via_service` |

**Leviers, du moins coûteux au plus structurant** — 1, 2 et 4 **✅ câblés le 22/09** (décision
de Fabien : « purement amélioratif »), **5 ✅ le 26/09** ; seul 3 reste une question :
1. ✅ **Réflexion reliée au curseur Rapide ↔ Qualité** : `assistant_engine.thinking_wanted` —
   la réflexion (`think`) n'est demandée qu'à la position « quality » de la déclinaison commune
   à paliers (`preset_key_for_intent` : fast 15 / balanced 50 / quality 85) ; le défaut (50) est
   donc SANS réflexion. Vérifié sur deux tours réels (`qwen3.5:4b`, curseur par défaut) :
   conversation 5,4 s, tour à OUTIL 1,7 s avec l'appel `list_user_files` intact — le format JSON
   d'appel survit à `think:false`. Un modèle sans capacité `thinking` accepte l'option (mesuré).
2. ✅ **Prompt réordonné** : base + rôle + annonce + outils (FIXE) puis contexte labo + état des
   files (DYNAMIQUE) → le préfixe des jetons est stable d'un tour à l'autre.
3. ⏳ **Réduire le prompt d'outils** : 71 outils décrits à chaque tour ; ne lister que ceux du
   domaine chargé (`charger_competence`) ou les résumer — c'est l'écart « sous-agents » de
   `WAMA_HARNESS §9` (déclencheur : « le prompt système devient le poste de coût dominant »).
   Coût du levier : un outil non annoncé ne peut plus être appelé — il faut donc un chargement
   à la demande (le modèle demande « les outils de l'app X »), et un 2ᵉ tour LLM quand il se
   trompe de domaine. Gain : ~2 600 jetons de prompt par tour, c'est-à-dire du temps d'évaluation
   de prompt SEULEMENT quand le cache KV est froid (le levier 2 rend ce cas rare).
4. ✅ **TTS par phrases** : la première phrase part au service dès qu'elle est complète, la
   suivante est demandée PENDANT la lecture ; l'avatar met les morceaux en file (TalkingHead), le
   canal commun attend la fin d'un morceau avant le suivant. L'attente avant la première parole
   ne dépend plus de la longueur de la réponse.
   ⚠ **Domicile corrigé le 26/09** : ce levier vivait dans `home.html`, donc il n'existait QUE
   sur l'accueil. Il est dans la brique commune de voix (`speakStream`), et le volet droit en
   bénéficie sans une ligne de plus.
5. ✅ **Flux jeton par jeton (SSE) — câblé le 26/09.** Ollama reçoit `stream: true` **dès qu'un
   rappel est fourni**, et chaque fragment remonte jusqu'à l'écran et jusqu'à la voix.
   La voix parle par phrases pendant que le reste arrive.
   ⚠ **CETTE LIGNE ANNONÇAIT « 1ᵉʳ texte à 0,2 s, fin à 2,2 s, 2,0 s gagnées » — corrigé le
   2026-09-26 au soir.** C'était UN tour sur un serveur de développement éphémère, présenté comme
   la performance du levier. Remesuré **à travers la pile réelle** (Apache → gunicorn → Ollama),
   cache de préfixe chaud, trois longueurs de réponse :

   | réponse demandée | 1ᵉʳ fragment | fin du tour | ce que le flux fait gagner | caractères |
   |---|---|---|---|---|
   | très courte | 0,9 s | 0,9 s | 0,02 s | 2 |
   | moyenne | 0,86 s | 1,75 s | **0,89 s** | 555 |
   | longue | 0,91 s | 3,03 s | **2,12 s** | 1 411 |

   ⭐ **Ce que le tableau dit, et qu'un chiffre unique cachait** : le délai avant le 1ᵉʳ fragment
   est **CONSTANT** (~0,9 s à chaud, 3,7 à 10,7 s à froid) et le gain du flux **est la durée de
   génération**, donc proportionnel à la longueur de la réponse. Le flux ne réduit pas l'attente
   initiale — il supprime l'attente APRÈS elle. *Le poste dominant d'un tour court reste
   l'évaluation du prompt, c'est-à-dire la cible du levier 3.*
   - **Le point dur n'est pas le transport, c'est le PORTIER** (`_TokenGate`) : la réflexion du
     modèle (`<think>`) et les appels d'outils (JSON) arrivent par le MÊME canal que la réponse,
     et il faut trancher **fragment par fragment, sans attendre la fin** — y compris quand la
     balise est coupée en deux. Aucun de ces défauts ne lève d'exception : ils produisent un
     écran faux.
   - **Les trois surfaces ne changent pas**, et c'est CÂBLÉ, pas promis : sans rappel, aucun flux
     n'est demandé à Ollama. L'API v1 et la passerelle ne paient pas un flux qu'elles
     n'affichent pas — une contre-épreuve le verrouille.
   - ✅ **APACHE NE TAMPONNE PAS** (mesuré le 26/09 au soir, à travers le port 80 comme en
     direct sur gunicorn) : `Content-Type: text/event-stream`, `X-Accel-Buffering: no` propagé,
     **111 événements** reçus un par un des deux côtés. ⚠ C'était le risque qu'aucun test Django
     ne pouvait lever : un intermédiaire qui tamponne **annule le levier sans rien casser** — la
     réponse arrive complète, l'écran se remplit d'un coup, le code reste correct et le gain a
     disparu. La démo passera par Apache : il fallait le mesurer là.
   - **Le flux n'existe que sur le chemin LOCAL** : `llm_chat` (LiteLLM) rend un texte entier et
     l'abonnement Claude Code lance un process qui finit avant de parler. Un tour cloud reste
     synchrone, et la surface le sait (elle affiche son attente).
   - **Les ÉTAPES d'outils partent aussi**, dès qu'elles sont jouées — c'est ce que
     `WAMA_HARNESS §9 chantier 4` demandait (*ce qui est pénible n'est pas d'attendre, c'est
     d'attendre sans savoir*), obtenu par le même canal au lieu d'un mécanisme à part.
   - **Le store n'a pas eu besoin d'un autre contrat** : le tour PERSISTE comme avant, à la fin ;
     le flux ne fait que montrer plus tôt ce qui sera écrit. Un tour interrompu à mi-flux laisse
     donc le fil exactement dans l'état d'un tour interrompu tout court.
   - Gardes : `common/tests/tests_assistant_stream.py` (16).

**Et un rendu de chat au lieu de deux (26/09).** L'accueil portait SON propre rendu (282 lignes
de JavaScript écrit à la main) à côté de la brique du volet droit, pour le MÊME fil : deux
implémentations d'un même écran, donc deux endroits où corriger un défaut. L'accueil DÉCLARE
maintenant la brique commune en densité `full`, le volet en `compact`. Le message d'accueil et
le mot d'attente restent SERVIS (ils varient selon l'état de connexion), portés par un
`<template>` plutôt que figés dans le JavaScript. Une garde vérifie que les identifiants de
l'ancien rendu ont disparu — sans elle, laisser les deux en place passerait inaperçu.

**Le texte À DIRE est une brique (26/09)** — `common/utils/tts_text.py`. Il était écrit DEUX
FOIS, **sous le même nom de fonction** : la vue de vocalisation avait les emojis, le Markdown et
les respirations ; `synthesizer/utils/text_extractor.py` avait les URL et les e-mails. Aucun des
deux n'était faux ; ensemble ils faisaient un demi-vocabulaire, et le synthesizer — dont tout le
métier est de lire un document à voix haute — n'avait ni retrait d'emoji ni pause de fin de
ligne. ⚠ C'est le NOM DUPLIQUÉ qui rendait la chose invisible à un `grep`. Les six appelants du
synthesizer sont conservés : ce nom DÉLÈGUE. Gardes : `common/tests/tests_tts_text.py` (17), là où il
n'y en avait **aucune** — le défaut ne se voit qu'à l'oreille, le serveur répondant 200.

**La voix de l'assistant, trois constats du 2026-10-03** (échange réel de Fabien, fil #16) :
1. ✅ **L'assistant ne savait pas qu'il parle.** À « je n'entends pas ta vocalisation » il
   répondait « je communique uniquement par écrit » et proposait le Synthesizer, puis
   l'Avatarizer. Ce n'était pas le curseur « rapide » : RIEN dans son prompt (préambule, skill
   de rôle, bloc d'outils) ne décrivait la surface. Ajout d'une consigne de SURFACE web
   (`assistant_engine.WEB_VOICE_PROMPT`, sœur de `CHANNEL_FILES_PROMPT`) : il est lu à voix
   haute et animé par l'avatar, avec l'ÉTAT courant (voix active/coupée, avatar affiché/masqué)
   lu des réglages durables. Posée dans la partie FIXE du prompt. Garde :
   `tests_assistant_surfaces.WebVoicePromptTest`.
2. ✅ **« WAMA » lu « WAMAfreu ».** espeak-ng BALISE ses bascules de langue (`(en)wˈɑːmə(fr)`),
   et le tokenizer de `kokoro_onnx` les passe telles quelles au modèle. Le jumeau `.pt` n'avait
   pas le défaut (misaki : `remove-flags`) : il date du passage à l'ONNX (31/08). Le backend
   phonémise désormais lui-même (`kokoro_onnx_backend.phonemes_without_language_flags`). La
   langue et la voix, elles, étaient justes. ⏳ Le mot reste prononcé à l'anglaise : un LEXIQUE
   de prononciation (`tts_text`) est à décider. Garde : `tests_kokoro_onnx_phonemes` (dont un
   test qui échouera le jour où la librairie corrige en amont). 🔴 Service TTS à relancer.
3. ⏳ **Le moteur de la voix n'est pas TIRÉ.** `ASSISTANT_TTS_ENGINE` est une variable
   d'environnement : ni « auto », ni curseur, ni bascule selon la VRAM — le « XTTS qui prend la
   relève » n'a jamais existé (`ROADMAP` §microservice TTS). La voie cohérente est le tirage
   commun (`resolve_model_choice`, tâche `text-to-speech`), Kokoro en plancher rapide. Candidats
   mesurés le 03/10 : Qwen3-TTS 1.7B est INSTALLÉ et exécutable (le pin `transformers==4.57.3`
   de `qwen-tts` n'est qu'un avertissement de `pip check`) ; Kyutai TTS 1.6B (EN/FR, entrée
   texte en flux) et Voxtral TTS (CC BY-NC) sont hors catalogue.

#### 1ter. L'assistant agit sur le CODE — pour les développeurs et administrateurs (22/09)

Demande de Fabien : *« utiliser un modèle local ou cloud souverain, performant en code, pour
améliorer WAMA depuis l'assistant sans passer par Claude, sans trop de risque »*, réservé aux
rôles admin et dev. **Ce qui existait** : `ask_claude_code` (Claude seul, écriture sur intention
explicite) et la surface MCP `wama-dev` (`dev_tools.py` : rôles wama-dev-ai qui ÉCRIVENT UNE
PROPOSITION, bac à sable sur jumelles, process séparé §16) — que seul un client MCP externe
(Claude Code, IDE) pouvait consommer. **Câblé le 22/09** : l'assistant est CLIENT MCP de cette
surface (`common/services/mcp_client.py`, `ROADMAP §8d étape 5 moitié dev`) — un développeur
qui converse avec un modèle local voit les outils `dev_*` et peut lancer un rôle ou une jumelle ;
le serveur dev garde la porte.

**Bridage « qualité max » du travail sur le code — ✅ câblé le 22/09** (Fabien, après le test
réel : le 4b sans réflexion inventait des jumelles ; « brider en qualité max, limiter les modèles
possibles, de façon globale à wama-dev-ai, peut-être Albert avec gpt-oss »). Domicile UNIQUE :
`common/services/development_models.py`.
- **La règle est une mesure** : sous-indice coding du banc tiers ≥ **40** (relevé du parc :
  qwen3.8 58,2 · albert gemma-4-31b 43,4 · qwen3.6:35b 41,9 | gemma4:12b 31 · qwen3.5:4b 22,6 ·
  gemma4:e4b 9,4 — le plancher sépare ce que le banc du 13/08 avait confirmé de ce qui fabule).
  Sans score : exclu, sauf `albert:gpt-oss-120b`, déclaré (à retirer dès qu'il est mesuré).
- **Ce que ça change** : curseur à 100 (réflexion demandée), lot restreint, choix manuel sous le
  plancher REMPLACÉ, distants souverains (Albert) admis au tirage automatique dès « cloud si
  WAMA est saturé » (les tiers gardent la règle commune, « 100 % local » reste local), et sans
  modèle de niveau dev : **refus lisible**, jamais un petit modèle.
- **Où ça s'applique** : domaine `dev` de l'assistant (`AssistantDomain.development=True`) ;
  **bascule en cours de tour** dès que le modèle charge la compétence dev ou appelle un `dev_*`
  (la suite du tour passe au niveau dev, l'étiquette dit « · dev ») ; le **fil s'en souvient**
  (`conversation_store.last_loaded_domain`) pour les tours suivants ; et les **rôles
  wama-dev-ai** (`role_utils.resolve_model` : la chaîne de `config.py` finissait sur
  `fast`/`ultra_fast` dès que la VRAM manquait — plus de repli, une erreur qui dit pourquoi).
- Tenu par `tests_development_models` (plancher, remplacement, souverain, bascule, fil, refus).
- ⚠ gpt-oss-120b et le banc : mesuré le 22/09 (dry-run de `sync_benchmarks`), ce n'est pas une
  resynchronisation qui manque — le lecteur d'identité exige « famille + version » (aucune
  version dans ce nom → « sans identité lisible ») et aucune des deux sources chargées (882
  entrées AA, 670 Arena) ne le liste. La déclaration `DEV_UNSCORED_ALLOWED` fait foi.

**Le curseur de l'assistant vaut pour les tâches qu'il lance — ✅ câblé le 22/09** (idée de
Fabien : « l'utilisateur règle une fois le curseur et demande ses tâches à l'assistant, qui
applique le niveau demandé, en le rendant explicite »). `tool_api.relay_quality_intent`, appelé
par la boucle de l'assistant après tout outil `add_to_<app>` : l'élément créé reçoit
`quality_intent` du réglage de l'assistant, et le résultat porte `quality_intent` +
`quality_level` (palier), que la règle du prompt fait DIRE au modèle (« niveau Équilibré (55) »).
Frontière voulue (Fabien) : **seulement les apps dont le champ s'appelle `quality_intent`** —
l'anonymizer (`precision_level`, ses paliers) n'est pas relayé, et les apps sans champ le
recevront à leur portage. L'aide du curseur de l'assistant le dit aussi. Le studio et l'API
d'outils ne sont pas concernés (la boucle de l'assistant seule relaie). Tenu par
`tests_quality_relay`.

⏳ **Ce qui manque pour « une page d'édition en bac à sable avec
un guide de conception et d'intégration »** — trois décisions avant d'écrire :
1. **le rôle « améliorer »** — un pilote de plus sous `wama-dev-ai/`, sur le patron de son rôle
   `codegen` ; son nom de fichier n'est **pas écrit ici**, et c'est délibéré : un chemin qui
   n'existe pas encore est compté par `check_docs` comme une cible cassée, et le seuil est ZÉRO
   depuis le 2026-09-07. Matière =
   les docs de référence du domaine touché (`AGENTS.md`, `WAMA_APP_CONVENTIONS`, `ROUTE`) + le
   code RÉEL de la jumelle par AST ; sortie = un DIFF proposé dans `outputs/`, contrôlé
   mécaniquement (compile, imports résolus, `check_identifier_language`) ; **jamais appliqué** ;
2. **l'application sur la JUMELLE** : un outil `dev_sandbox_apply(proposition)` qui écrit le diff
   dans `<app>_NN` seulement, avec témoin et `revert` — c'est une ÉCRITURE, donc elle attend la
   marque d'écriture + confirmation de `WAMA_HARNESS §9 chantier 2` (« le jour où on ouvre
   l'ajout de capacité à un utilisateur, il faut une approbation ») ;
3. **la page** : le volet de la jumelle (les jumelles ont déjà leur badge « BAC À SABLE » au
   catalogue) avec le fil de l'assistant en domaine `dev`, la proposition à côté, les juges du
   bac à sable (AST, couple views↔templates, smoke habité) comme verdict — ⚠ le bac à sable est
   en chantier dans une AUTRE session (convergence par régénération, `ROUTE §10.3`) : la page
   se conçoit avec elle, pas à côté.

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
  exposé à l'assistant par **quatre** outils : deux LECTURES transverses (`list_ai_models` /
  `get_ai_model`, §1) et, depuis le **2026-09-19**, les **deux gestes du bouton** —
  `search_models` (= `seed_hf_search` : écrit des PROPOSITIONS, visibles et rejetables) et
  `install_model` (= `model_installer.request_install` : garde d'espace disque, choix de
  variante, idempotence, tâche de fond). Ces deux-là **écrivent**, donc ils sont gardés par
  l'app `model_manager` dans `TOOL_APP_OVERRIDE` — et non transverses comme les lectures.
  ⚠ `install_model` n'installe QUE ce qui est déjà proposé ou déjà au catalogue : l'entrée par
  descripteur nu a été retirée de l'endpoint le même jour, donc **une phrase en langage naturel
  ne peut pas faire télécharger un dépôt arbitraire**. `prepare_install_spec` n'existera pas :
  le spec est celui du candidat (détail : `PROSPECTION_PIPELINE.md`, session du 19/09).
- **Albert API (DINUM) — branchée le 2026-09-15** : `llm_chat(provider='albert')`. Albert parle
  le protocole OpenAI depuis sa propre adresse ; `llm_utils.OPENAI_COMPATIBLE_PROVIDERS` le route
  en `openai/<modèle>` (préfixe TOUJOURS posé : ses identifiants contiennent un « / ») avec
  l'adresse et la clé du registre `external_sources` (clé `albert`, `ALBERT_API_KEY` dans `.env`)
  — jamais `OPENAI_API_BASE`, qui détournerait aussi OpenAI. Modèle par défaut : `ALBERT_MODEL`,
  sinon `CLOUD_DEFAULT_MODELS['albert']`. Deux consommateurs : l'**assistant** (option « Albert »
  de `home.html` ; l'API v1 la reçoit par `provider` — ⚠ **PAS Discord**, figé sur `wama-dev-ai`
  par `gateway/core.py:208` ; affirmé à tort ici le matin même, corrigé le 15/09) et les **rôles
  wama-dev-ai** (`role_utils.call_llm` : `--provider albert`, ou `WAMA_DEV_AI_PROVIDER=albert`).
  ⚠ **Cadre en cours de REPRISE** : ces tables écrites à la main (`CLOUD_DEFAULT_MODELS`,
  `OPENAI_COMPATIBLE_PROVIDERS`, l'option de `home.html`) contredisent le métadonnée-driven. Elles
  seront remplacées par le REGISTRE DES FOURNISSEURS (ROADMAP §8d Phase 3, étape 4, décidé le
  15/09) — le serveur MCP (étape 2, livrée) donne à tous les cerveaux les mêmes outils.
  Preuve outillée : `manage.py llm_gateway_check --provider albert`. Gardes :
  `tests_llm_providers`, `tests_dev_ai_bridge.FournisseurDesRolesTest`.
  ✅ **Mesuré le 2026-09-15, clé réelle** : passerelle → `'OK'` (`openai/gpt-oss-120b`) ; rôle
  librarian `--dist requests --provider albert` → manifeste VALIDE, 0 divergence avec
  l'extraction mécanique, 1 min 08 ; tour d'assistant sans outils → réponse correcte.
  `GET /v1/models` : l'**id** à passer est la 1ʳᵉ colonne (`openai/gpt-oss-120b`,
  `qwen3-coder-30b-A3b-instruct`, `mistral-small-3-2-24b-instruct-2506`, `gemma-4-31b-it`,
  `deepseek-v4-flash-0731`…), les noms HF sont des alias ; `mistral-medium` (listé par la doc)
  n'est PAS ouvert à ce compte. Limites du compte : `GET /v1/me/info` (par modèle, RPM 10 à 500).
  ⚠ **Chat seulement** : whisper, bge-m3, rerank et OCR d'Albert ne passent pas par `llm_chat`.
  ⚠ **Choix EXPLICITE uniquement** : `select_model()` ignore toujours le cloud (ROADMAP §8d, 2ᵉ
  verrou) ; et Albert (SecNumCloud, sans conservation) compte-t-il comme local pour les données
  sensibles ? Non tranché (§8d ③).
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

### 2quater. OÙ WAMA PARLE À OLLAMA — la carte des appelants (MESURÉE 2026-09-07)

> **Pourquoi elle existe** (demande de Fabien) : « Ollama sert à plein d'endroits — apps,
> AI-Assistant, wama-dev-ai, pipeline LLM, prospection du model_manager. Il faut pouvoir
> vérifier partout avant de toucher, pour ne rien casser. » Cette carte est ce qu'on relit
> **avant** de modifier une brique d'appel. Le §2ter dit *quel modèle* est choisi ; celle-ci
> dit *par où l'appel passe*.

**Deux briques, et elles ne se confondent pas** :
- **l'ADRESSE** → `common/utils/ollama_host.ollama_base()` — annexe du mécanisme
  `external_sources`. Elle porte les **deux pièges vérifiés** que rien de générique ne sait
  faire : WSL2 → passerelle Windows (`127.0.0.1` y désigne la VM, pas l'hôte), et le
  contournement du proxy UGE (qui avale `172.x` et rend un `ReadTimeout` trompeur, « Ollama
  ne répond pas » alors qu'il tourne). ⚠ Le piège n°2 **effaçait des candidats valides** :
  `prospect_ollama()` purge quand la liste revient vide ;
- **le CLIENT** → `common/utils/llm_utils.ollama_chat()`, « point de passage de toutes les
  fonctions de ce module ». Le registre des sources externes, lui, ne déclare **jamais** le
  client — c'est écrit dans son périmètre.

**Les appelants, par famille** :

| famille | point d'appel | passe par |
|---|---|---|
| Pipeline LLM (traduction, enrichissement, skills) | `llm_utils.ollama_chat` → `/api/chat` | `ollama_base()` |
| AI-Assistant (web, API v1, canaux) | `services/assistant_engine.py` | `ollama_base()` |
| RAG / embeddings | `common/memory/embed.py` → `/api/embed`, `/api/tags` | `ollama_base()` |
| model_manager — **prospection** | `prospect_ollama` → `ollama_registry` + `update_checker` | `ollama_base()` |
| model_manager — bancs & registre | `benchmark_sync`, `model_registry` → `/api/show` | `ollama_base()` |
| model_manager — chargement | `memory_manager` → `/api/generate` | `ollama_base()` |
| **wama-dev-ai — les 5 rôles** | `role_utils.call_ollama` → `/api/chat` | `ollama_base()` (délégué, 2026-09-07) |
| wama-dev-ai — `run_audit` | `/api/ps`, `/api/generate`, `/api/show` | `ollama_base()` (délégué, 2026-09-07) |

**Règle de modification** : une brique d'appel se change après avoir relu **cette ligne-là**
du tableau *et* les appelants réels (`grep` natif — `rtk` compresse, il ne mesure pas). Les
familles ci-dessus sont **étanches** : rien dans `wama/` n'importe `role_utils`, et
`wama-dev-ai` n'importe pas `llm_utils` (vérifié sur tout le dépôt le 2026-09-07).

> ✅ **`role_utils.ollama_host()` DÉLÈGUE désormais à la brique commune** (2026-09-07, GO
> Fabien : « pas de chemins parallèles, une route unique, on globalise »). Il en portait une
> copie — alors que la brique commune a justement été **extraite de `run_librarian.py`** le
> 2026-08-02 comme « seule implémentation correcte du repo ». *Une brique qu'on extrait sans
> que son origine l'adopte laisse deux vérités derrière elle.* Les deux résolvaient la même
> adresse (mesuré des deux côtés : `http://172.21.96.1:11434`), mais la copie était en retard
> sur **trois points latents** : elle lisait `os.environ` BRUT au lieu du registre
> `external_sources` ; son `subprocess` n'avait **aucun timeout** ; et une passerelle
> introuvable retombait **en silence** sur la boucle locale. Import paresseux — `role_utils`
> reste importable sans Django (vérifié), et aucun repli n'a été ajouté : ce serait le second
> chemin qu'on retire.
>
> ✅ **`run_audit.py` a rejoint le commun le même jour** — et l'objection qui l'en tenait
> éloigné était FAUSSE. Je l'avais écrite ici : « il ne peut pas déléguer, il ne fait pas
> `django.setup()` ». Mesuré ensuite avec `DJANGO_SETTINGS_MODULE` **non défini**
> (`settings.configured is False`) : `ollama_base()` rend quand même la passerelle. `base_url()`
> est écrit pour ça — réglage Django → variable d'environnement → défaut déclaré, l'accès aux
> settings étant dans un `try`. **L'audit ne charge donc pas `INSTALLED_APPS`** : un import
> cassé dans une app ne peut pas l'empêcher de tourner, ce qui était la seule objection
> sérieuse (un outil de diagnostic ne doit pas dépendre du système qu'il diagnostique).
> Il lisait `127.0.0.1` brut et ne marchait que par accident d'environnement.
> *Une contrainte non re-mesurée devient une habitude — et j'en avais fait une ligne de doc.*
>
> ✅ Le doublon voisin est SOLDÉ lui aussi (2026-09-07) : `run_codegen` portait sa propre copie de
> `call_ollama`, `ollama_host` et de l'écriture de sortie. Fusionné — mais **pas remplacé** :
> il divergeait sur trois valeurs (`temperature` 0.2, `num_ctx` 32768, `timeout` 900 s) que le
> commun ne savait pas exprimer, et un remplacement sec aurait **tronqué sa matière** (jusqu'à
> 60 000 caractères, illisibles à `num_ctx=16384`). Le commun a gagné deux paramètres à défauts
> INCHANGÉS ; codegen passe les siens. *Avant de supprimer un doublon on compare ; s'il diverge,
> on fusionne — sinon la déduplication perd une capacité en silence.*

### 3. RAG — alimentation par GESTE, rappel par NIVEAUX (`WAMA_MEMORY.md §7ter`)

```
sortie d'app ──(si l'utilisateur veut)──▶ médiathèque ──(ACTION EXPLICITE)──▶ RAG
                                             add_to_rag(texte, niveau='user'|'unit')
                                               • plusieurs affiliations ⇒ NOMMER l'unité
                                               • ancêtre (dépt/univ) ⇒ REFUSÉ (niveaux 3/4 fermés)
                                               • embedding=NULL au geste → reindex par lot
rappel  : recall(rag_niveaux={'user','unit'}) — son RAG / celui du labo / les deux / RIEN
retrait : remove_from_rag — ce qui entre par un geste sort par un geste
```

Cas d'usage canonique (Fabien) : scan manuscrit → OCR reader → **ce texte** entre au RAG par le
geste → sert ensuite, p. ex., au compte-rendu tiré d'une transcription de réunion.

**SURFACES livrées le 2026-08-22** (jalon 14) : le geste est un bouton de l'**inspecteur** — donc
présent dans les 10 apps **sans une ligne par app**, et data-gaté sur la présence de texte — et la
page **« Mon RAG »** (`/common/rag/`) porte les défauts de niveaux, la liste, le retrait et l'état
des vecteurs. Les défauts vivent sur le profil et sont **lus au rappel** (`laboratory_context`),
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
| 9 | Surfaces du geste RAG + page de gestion (défaut de niveaux, retrait) | ✅ 2026-08-22 | **placement tranché : l'INSPECTEUR** (global, déjà nourri par `detail_registry` qui porte le texte ⇒ 10 apps sans une ligne par app, data-gaté) + page « Mon RAG » `/common/rag/` ; défauts sur le profil (`accounts.0015`), lus par `laboratory_context`. Reste : sélecteur **par requête** + entrée depuis la médiathèque — `WAMA_MEMORY.md §9quater` |
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
(`AGENTS.md`) — son intention vit dans le code et la fiche « langues » ; trou à combler le jour
où le sujet grossit, sans créer de doc concurrent d'ici là.

## Investigation web de l'assistant — design acté le 2026-08-29, ✅ LIVRÉ (⚠ moteur HORS SERVICE)

> ⚠ Ce titre disait « NON implémenté » jusqu'au 2026-09-26, alors que **sa propre table, juste
> en dessous, porte sept ✅ « LIVRÉ 29/08 »**. Un titre est ce qu'on lit en premier et ce qu'on
> cite : celui-ci a fait passer pour un chantier à ouvrir une brique en place depuis un mois.

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

### ⚠ État MESURÉ le 2026-09-26 (question de Fabien : « et le proxy ? ») — le moteur refuse

Trois mesures, depuis **WSL2** (le process qui exécute réellement gunicorn et Celery, et dont
l'environnement n'est pas celui de Windows) :

| ce qu'on croyait | ce que la mesure dit |
|---|---|
| le proxy va bloquer la recherche | **non** : le proxy de l'université est joignable ET l'accès direct fonctionne — un POST isolé vers le moteur rend `200` dans les deux cas |
| `requests` suit le proxy tout seul | **à moitié** : `.env` ne pose que `HTTP_PROXY`, donc pour une URL **HTTPS** `requests` ne trouvait **aucun** proxy et sortait en direct. Invisible tant que le direct marche ; le jour où le réseau se ferme, la médiathèque (qui passe par la brique) tiendrait et la recherche web tomberait seule |
| la recherche « ne trouve rien » | **elle n'a jamais lieu** : DuckDuckGo répond `200` avec 14 Ko de *« Unfortunately, bots use DuckDuckGo too. Please complete the following challenge »* — le parsing ne trouve aucun `result__a` et rendait une liste VIDE |

**Corrigé le 26/09** : les deux appels sortants passent par la brique commune
(`proxies_for('duckduckgo')` pour le moteur — sa source est au registre —, `outbound_proxies()`
pour la lecture de page), comme les connecteurs de la médiathèque depuis le 21/09 ; et un défi
anti-robot lève désormais `SearchEngineUnavailable` au lieu de se faire passer pour une
recherche sans résultat — l'assistant reçoit *« Recherche indisponible : le moteur a répondu par
un défi anti-robot »*. ⚠ Le réglage `WAMA_OUTBOUND_PROXY`, que la brique lit **en premier**,
n'était déclaré **nulle part** dans `settings.py` (`hasattr` = False) : cette branche ne pouvait
jamais jouer. Déclarée, vide par défaut.

### ✅ TRANCHÉ le 2026-09-26 — le moteur devient un CHOIX, plus une constante

Décision de Fabien : *« on ajoute les moteurs de recherche aux sources et on laisse
l'utilisateur sélectionner son moteur par défaut sur sa page profil »*. Ce que ça corrige tient
en une phrase : **un moteur écrit en dur est un point de panne que rien ne contourne** — celui
du 29/08 a tenu un mois.

**La forme, identique à celle des connecteurs de la médiathèque** (on ne réinvente pas un
patron pour une deuxième famille de connecteurs) :

| ce qui est déclaré | où |
|---|---|
| le moteur existe, son adresse, sa portée (donc son proxy), sa page de clé | registre `external_sources`, famille `recherche` |
| comment on l'interroge (corps de requête, forme de la réponse) | un adaptateur par moteur, `common/search_engines/` |
| qui peut l'employer | sa clé, posée **au profil** par chacun (`accounts.UserApiKey`) |
| lequel employer | préférence du profil → défaut d'instance (`WAMA_SEARCH_ENGINE`) → premier utilisable |

**Les trois moteurs ouverts** (mesurés le 26/09, tarifs et conditions vérifiés à la source) :

- **Exa** — 20 000 requêtes/mois offertes, sans carte bancaire ; recherche neuronale, forte
  pour « identifier / comprendre ». Le plus simple à ouvrir aujourd'hui.
- **Staan (Qwant + Ecosia)** — l'index **européen**, API ouverte en libre-service depuis 2026 ;
  1 000 requêtes/mois offertes puis **2 €/1 000**, données **sous juridiction UE**. Le plus
  aligné avec un labo public — et le seul qui ne dépende ni de Google ni de Bing.
- **SearXNG** — instance auto-hébergée, sans clé. ⚠ **Il n'a pas d'index** : il interroge les
  mêmes moteurs, depuis l'IP du labo (mesuré par des tiers en juillet 2026 : Google et Brave y
  opposent un défi, seul DuckDuckGo répond). Il apporte la vie privée, **pas** la fiabilité :
  il ne contourne pas le défi qui nous a bloqués, il le déplace.
- ~~Brave~~ — index indépendant et bon marché, mais **tier gratuit supprimé en février 2026** :
  carte bancaire obligatoire et crédit conditionné à une **attribution publique** sur le site.
  Deux frictions administratives réelles pour un labo ; écarté à ce stade, pas condamné.

⚠ **Sans configuration, rien ne change** : aucune clé posée et aucune instance déclarée
laissent DuckDuckGo seul utilisable — qui dit son défi. Une instance SearXNG **non déclarée**
n'est délibérément pas « utilisable » : sans cette règle, son adresse par défaut
(`127.0.0.1:8888`) ferait d'elle le moteur de toute installation neuve, et chaque recherche
mourrait sur une connexion refusée.

**Ce que ça a RETIRÉ** — `accounts/api_keys.py` filtrait la famille `llm` **en dur** : ouvrir
le mécanisme des clés personnelles aux moteurs a consisté à remplacer ce littéral par une
liste de familles déclarée. *Une brique qui nomme une famille en dur devra être modifiée à
chaque famille ; une brique qui lit le registre, jamais.* ⚠ `media` n'y entre PAS : les
connecteurs de la médiathèque ont leur propre stockage chiffré — les réunir est un chantier de
FUSION, pas un ajout, et le déclarer ici ferait deux domiciles pour une même notion.

🔚 **Reste à Fabien** : ouvrir un compte sur **Exa** et/ou **Staan** et poser la clé au profil
(rien d'autre à faire : la page, la sonde et le choix sont en place). Puis, le cas échéant,
décider du défaut d'instance.

**Incohérence relevée à résorber au passage** : DEUX routes de résolution vision coexistent —
`describer/backends/image_backend.py` (liste en dur `gemma4:12b/e4b`) court-circuite le tier
`image` de `llm_utils` (dont le TODO `vision_probe` pour peupler la capacité `vision` est écrit
dans `llm_utils.py` lui-même) ; et `reference_comprehension` importe une fonction privée du
describer (inversion de dépendance). Fixer = faire passer le describer par
`modele_par_tier(exige=['completion','vision'])` + peupler `vision` au catalogue.

> ⚠ **Chemin RECTIFIÉ le 2026-09-03** (le fichier a bougé de l'ancien module « image_describer »
> de `utils/` vers `backends/image_backend.py` — marche B1 du describer, `5b3f82f6` ; l'ancien
> chemin n'est délibérément PAS réécrit en toutes lettres ici : le citer en ferait une référence
> cassée de plus, piège documenté au skill `/reprise`). **L'incohérence n'est pas
> résorbée, elle a DÉMÉNAGÉ** — vérifié au code ce jour : la liste en dur vit désormais en
> `backends/image_backend.py:16`, et `common/utils/reference_comprehension.py:92` importe
> toujours `_best_ollama_vision_model`, la fonction privée. *Un renommage ne casse rien, il
> rend FAUX* : sans cette rectification, `check_docs` accusait une 2ᵉ cible distincte et le
> constat lui-même serait passé pour périmé alors qu'il tient.
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
✅ *2026-09-28 : la stabilisation est acquise (instabilité déclarée résolue par Fabien) — la
condition est levée ; la gouvernance reste (passes routées par le gouverneur, et une boucle de
fond se place hors de la plage réservée aux tests nocturnes, `WAMA_MEMORY §9bis.1`).*

### Vérification de la chaîne multi-surface (tracée au code le 2026-08-29, agent Explore)

**Ce qui tient** : la passerelle Discord (`wama/gateway/`) est LIVRÉE et arrive au MÊME
cerveau que le web — `core.py` → `conversation_turn` → `run_assistant_turn`, mêmes
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
   `core.py::_produced_files` lit les `tool_steps` (URLs `/media/…` résolues SOUS
   MEDIA_ROOT seulement, bornées en nombre et taille) et nourrit `Reply.files` — le
   code d'envoi de l'adaptateur n'est plus mort. 3 tests `gateway/tests.py`.
   ⚠⚠ **RECTIFIÉ le 2026-09-23 : ce « corrigé » était FAUX pendant 25 jours.** La fonction
   ne lisait que le PREMIER niveau du résultat (`contenu.get('output_url')`), forme qu'AUCUN
   outil ne produit : les dix `get_<app>_status` nichent la sortie sous `jobs[]`
   (`tool_api.py:320-328`). `Reply.files` restait donc TOUJOURS vide. Les 3 tests étaient
   verts parce qu'ils construisaient une forme SYNTHÉTIQUE au lieu de la forme mesurée des
   outils — *une mesure qui ignore une forme rend un verdict inverse.* Levé le 23/09 :
   descente bornée (profondeur 4, 1er élément d'une liste de conteneurs = le job le plus
   récent, tri `-id`), et un test appelle désormais le VRAI `get_imager_status`.
   Contre-épreuve mesurée : ancienne version `[]`, nouvelle `['…/rendu.png']`.
4. ⚠ `PROMPT_TARGETS['composer']` sans clé `'model'` → pas d'enrichissement à l'ingestion
   (le lancement rattrape — asymétrie non documentée avec imager, sans effet fonctionnel).
5. ✅ corrigé 29/08 : la docstring de `charger_competence` énumérait les domaines en dur
   (sans `investigation`) en contredisant l'annonce du même prompt — l'énumération est
   REMPLACÉE par un renvoi à l'annonce, qui ne peut plus dériver.

### ⭐ 2026-09-23 — QUATRE défauts DE PLUS, mesurés sur un échange Discord RÉEL

> Source : la conversation Discord #11 du 22/09 (`Conversation`/`ConversationTurn`, tours et
> `tool_steps` persistés — c'est le store qui a permis de mesurer au lieu de supposer).
> Fabien y demande une anonymisation, l'assistant la déclare lancée puis **terminée**, donne
> un lien `https://example.com/…` **inventé**, et refuse trois fois d'envoyer le fichier.
> *Aucun de ces quatre défauts n'était visible d'un test : ils vivaient dans ce que le
> modèle CROIT de sa surface.*

| # | ce que le modèle a fait | ce qui manquait | levé par |
|---|---|---|---|
| 1 | annonce « tâche lancée » puis « terminée » après un simple `add_to_anonymizer` | un ajout RANGE dans la file, `start_*` lance — rien ne le disait dans le résultat (l'item 647 dormait encore `queued`, progress 0, le lendemain) | `tool_api.relay_next_step` : le résultat porte `started: False` + le NOM du `start_*`, **dérivé** du rôle de l'outil et du registre (aucune liste d'apps à tenir), appliqué par la boucle à côté de `relay_quality_intent` |
| 2 | « je ne peux pas envoyer de fichiers par Discord » | FAUX depuis le 21/08 : la passerelle joint les sorties du tour. Le moteur ne recevait même pas sa `surface` | `surface` descend jusqu'à `run_assistant_turn` ; `CHANNEL_FILES_PROMPT` n'est posé que sur un CANAL, et `surface_attaches_files()` le LIT de `gateway.core.CHANNELS` (domicile unique, désormais lu aussi par `run_gateway`) — le moteur ne redéclare rien, donc l'adaptateur Matrix héritera de la consigne sans qu'on y pense |
| 3 | un lien `https://example.com/output/…` **fabriqué de toutes pièces** | aucune règle n'interdisait d'écrire une URL plausible ; le statut n'avait même pas été demandé | règle « NEVER INVENT A LINK » : une URL ne peut venir que d'un résultat d'outil de CE tour, sinon appeler `get_*_status` |
| 4 | « je ne peux pas lancer Claude Code » — juste après l'avoir lancé | `ask_claude_code` avait échoué et rendu 500 caractères de télémétrie (`{"duration_api_ms":0,…`) ; la raison, dans `result`, était tronquée | `claude_code._failure_message` lit le JSON même en échec (`result`, sinon `subtype`/`api_error_status`) et journalise la sortie ENTIÈRE |

⭐ **La leçon commune : une erreur illisible se propage en fausse incapacité.** Trois des
quatre « je ne peux pas » ne venaient pas d'un manque, mais d'une information que le modèle
n'avait pas — ou qu'il avait reçue sous une forme illisible. **Un petit modèle ne dit pas
« je ne comprends pas ce résultat » : il dit « je ne peux pas ».**

#### Puis DEUX de plus, révélés en remettant la chaîne en service le même jour

| # | mesure | ce qui n'allait pas | levé par |
|---|---|---|---|
| 5 | `start_anonymizer` → `property 'processed' of 'Media' object has no setter` | l'outil écrivait encore `media.processed = False` et filtrait `filter(processed=False)`, alors que l'**audit du 2026-07-11** a remplacé ce booléen par `status` en ne laissant `processed` qu'en property DÉRIVÉE. **Les DEUX branches étaient mortes** (AttributeError à l'unité, FieldError en lot) : l'assistant n'a jamais pu lancer une anonymisation. Le défaut #1 le cachait — on n'atteignait pas l'outil | l'outil passe par `begin_processing`, **la brique du bouton ▶ de la card** (anti-race obligatoire), et parle le vocabulaire canonique `status`. `wama/common/tests/tests_tool_api_start.py` : gardes ciblées + un contrôle GÉNÉRIQUE (« aucun `start_*` ne LÈVE sur file vide ») qui traverse les dix apps |
| 6 | le lien inventé est REVENU après le correctif #3, dans un tour **sans aucun appel d'outil** | ses propres fabrications sont dans l'historique du fil, qui lui est resservi à chaque tour. *Une règle de prompt ne défait pas un exemple qu'on remet sous les yeux du modèle* | `_strip_unsourced_urls` : une URL ne sort de la boucle que si elle figure dans un résultat d'outil **du tour** ou dans le message de l'utilisateur — jamais depuis l'historique, qui est ce qui recycle le mensonge. Le libellé reste, la mention « lien non vérifié — retiré » le dit, le retrait est journalisé |

⭐⭐ **Le vrai enseignement du 23/09 : une consigne de prompt n'est pas un contrôle.** Les
quatre premiers correctifs donnaient au modèle de meilleures INFORMATIONS ; il a menti quand
même, parce qu'il lisait ses propres mensonges. Ce qui tient, c'est ce que la SORTIE vérifie
(`_strip_unsourced_urls`) et ce que la DONNÉE porte (`next_step`) — pas ce que le prompt
demande. *Le même principe que `check_identifier_language` : une règle qui demande de se
souvenir n'est pas un contrôle.*

#### 2026-09-27 — la chaîne a servi, et l'usage a trouvé deux défauts de plus

> Fabien reçoit enfin sa photo dans Discord. Deux constats immédiats, tous deux mesurés par lui.

**① L'APERÇU N'EST PAS LE FICHIER.** Il enregistre l'image depuis le fil et obtient un **webp de
75 Ko** là où WAMA a envoyé un **JPEG de 445 203 octets**. Rien n'est recompressé de notre côté
(`discord.File` lit le fichier tel quel) : ce qu'on enregistre depuis l'aperçu est le **proxy
d'images** de Discord, redimensionné et ré-encodé. ⭐ *Un aperçu et un fichier se ressemblent à
l'écran et ne pèsent pas la même chose.*
Levé par `_caption_original` : l'URL de la pièce jointe n'existant qu'**après** le téléversement,
le message est ÉDITÉ pour la porter, avec le poids et la mention que l'aperçu est compressé.
⭐ C'est aussi le **lien de téléchargement qui manquait** — et il ne demande ni `WAMA_PUBLIC_URL`
(vide ; demandée à la DSI sous `wama.univ-eiffel.fr`), ni de faire circuler un secret WAMA dans
une messagerie, ce que la doctrine d'appariement refuse. ⚠ Ces URL de CDN portent une signature
courte : la légende le dit, plutôt que de laisser croire à une adresse pérenne.

**② AU-DELÀ DU PLAFOND, RIEN N'ARRIVAIT ET RIEN NE LE DISAIT.** `_produced_files` écartait le
fichier sans un mot. Théorique pour une image ; **le cas NORMAL pour une vidéo anonymisée** — la
réponse disait « c'est terminé », sans pièce jointe et sans explication. La fonction rend
désormais `(envoyables, trop_gros)` et le cœur ajoute une ligne à la `Reply` (nom, taille, où le
récupérer) : la mention voyage avec le texte, donc elle vaudra aussi pour Tchap.

⚠⚠ **ET LE PLAFOND LUI-MÊME EST À REPRENDRE** (question de Fabien : « d'où vient la limite ? »).
Mesuré : `_MAX_OUTPUT_BYTES = 24 Mo` est une constante **devinée** — son commentaire dit « limite
Discord la plus basse » et rien ne la mesure, alors que `discord.py` expose `guild.filesize_limit`
(qui tient compte du niveau de boost). Elle vit de surcroît dans `gateway/core.py`, dont la
docstring dit « le cœur, celui qui ne connaît AUCUN protocole » — c'est une borne de Discord dans
le module qui s'interdit de connaître Discord, quand le plafond ENTRANT (25 Mo) est, lui, dans
l'adaptateur. Les deux se contredisent d'ailleurs : 25 entrant, 24 sortant, deux raisonnements
sans rapport. ⏳ Décision à prendre : **qui filtre** — le cœur avec une borne générique, ou
l'adaptateur avec la borne que son protocole DÉCLARE ?

#### 2026-09-29 — un tour SANS outil qui cite un résultat est un tour INVENTÉ (contrôle, pas consigne)

> Fabien, depuis Discord : « l'image n'arrive plus, j'ai un lien qui ne marche pas ». Lu au fil
> persisté (skill `diagnostic-assistant`) : trois tours du 27/09, **zéro appel d'outil**, et
> pourtant « je lance l'anonymisation », « la tâche 648 est terminée », un lien. Aucune tâche
> n'existait ; « 648 » venait d'une erreur du 23/09 restée dans l'historique. Le « lien qui ne
> marche pas » était le libellé laissé par `_strip_unsourced_urls` — le garde-fou fonctionnait,
> mais le RESTE de la réponse partait. Modèle : `qwen3.5:4b`, tiré au curseur 50.

Deux contrôles, dans `assistant_engine` et `development_models` (commit `cf644976`) :
1. **Plancher de l'assistant OUTILLÉ** (`AGENT_CODING_FLOOR = 30`, décision de Fabien) : le tirage
   AUTOMATIQUE d'un tour connecté écarte un modèle MESURÉ sous le plancher (sous-indice coding du
   banc AA, qui inclut Terminal-Bench) — `qwen3.5:4b` (22,6) et `gemma4:e4b` (9,4) sortent,
   `gemma4:12b` (31) et `qwen3.8` (58,2) restent. Même domicile que le plancher dev, seuil plus bas ;
   un modèle NON mesuré n'est pas condamné, un choix MANUEL est respecté.
2. **Reprise d'un tour inventé** (`_invented_turn`) : aucun `tool_step` ET un lien retiré ⇒ le
   tour est rejoué UNE fois par un modèle mieux noté au banc (`escalation_model`) ; sans lui, ou si
   la reprise invente aussi, la réponse ENTIÈRE est remplacée par un aveu (« je n'ai exécuté aucune
   action »). Le signal est mesuré, pas deviné dans la langue — un tour sans outil qui ne cite rien
   (« bonjour ») n'est pas visé.
⚠ Limite connue : « je lance l'anonymisation » SANS lien ni outil n'est pas attrapé par (2) —
c'est le plancher (1) qui le prévient, a priori.

**Chaîne prouvée de bout en bout le 23/09 sur l'item réel 647** : `start_anonymizer` →
`RUNNING` → `SUCCESS` (`users/1/anonymizer/output/IMG-…_blurred_sam3.jpg`) →
`get_anonymizer_status` porte l'`output_url` → `_produced_files` ne rend QUE ce fichier-là
(pas les neuf jobs précédents) → la passerelle le joint.

### ⭐⭐ 2026-09-23 (suite) — la chaîne d'ADAPTATION du prompt SAM3 ne tenait pas

> Question de Fabien après le premier run réussi : *« sam3 n'a rien flouté. Est-ce que le
> prompt automatique est correct ? On avait mis en place un mécanisme d'adaptation. »*
> Il avait raison sur les deux points : le mécanisme existait, et il n'était pas appelé.

**① Le hook `concept` n'existait pas.** Tout était en place — le KIND `concept`
(`prompt_pipeline`), la déclaration `PROMPT_TARGETS['anonymizer']` (`kind: concept`,
`domain: detection`), le skill `anonymizer-detection.md`, `resolve_skill` qui le TROUVE,
`enrich_generative` qui sait l'appliquer, et l'appel `process_prompt_for` au lancement
(`anonymizer/tasks.py:203`). Mais Hook A est gardé par `kind == 'generative'` : **un target
`concept` ne pouvait pas l'atteindre**, même en déclarant `enrich: True`. Mesuré avant
correction : `enriched: False`, prompt inchangé. Le seul effet de la pipeline était une
traduction fr→en… d'un texte déjà anglais (la langue vient du PROFIL, pas du texte).
Levé : **Hook A bis** pour `kind == 'concept'`, + `enrich: True` à la déclaration.
Deux différences assumées avec le génératif — `allow_shorter=True` (adapter un concept, c'est
RACCOURCIR ; le garde-fou anti-dégénérescence rejetait la bonne sortie) et **pas
d'interrupteur maître** (couper l'enrichissement est un confort, couper l'adaptation rend la
détection muette).

**② Le skill lui-même prescrivait une forme que SAM3 n'ancre pas.** Il demandait « short noun
phrases separated by "and" » — et sa propre phrase d'exemple rend **zéro masque**. Mesuré,
même image, modèle chargé une fois, seul le prompt changeant :

| prompt | masques |
|---|---|
| `face` · `faces` · `human face` | **3** (0.93 / 0.89 / 0.88) |
| `all human faces` | 0 — le quantificateur |
| `face and person` | 1 (0.60, dégradé) |
| `faces and license plates` · `all human faces and vehicle license plates` | 0 — la conjonction |
| `Detect faces and license plates.` (ce qui partait) | 0 |

**SAM3 n'ancre qu'un groupe nominal simple à la fois.** Le contrat du skill est donc devenu
une LISTE de concepts, et `SAM3Processor.concepts()` / `_segment()` font **un appel par
concept** en réunissant les masques — ce qui est déjà, par construction, la forme du
cam_analyzer (`sam3_markings_prompts` itérée un par un). Un prompt sans masque est désormais
DIT (`AUCUN masque — rien ne sera flouté`) : il produisait jusque-là une sortie identique à
l'entrée, sans une ligne d'alerte.

**③ Et une valeur INVENTÉE finissait le travail.** Prompt corrigé, masques trouvés aux bonnes
coordonnées — et la photo sortait encore identique : **682 pixels changés sur 1,92 M**. Cause :
l'assistant avait passé `blur_ratio=2` (le schéma déclare `min=1, step=2`, noyau gaussien
IMPAIR, défaut 25 — et la description qu'il lit le dit). `normalize_blur_ratio` réécrivait 2
en 3 **en silence** : un noyau 3×3 ne floute rien. Levé par
`param_schema.unapplicable_numeric_values`, pendant numérique d'`invalid_choice_values`, posé
à la MÊME porte (`execute_tool`) : une valeur hors grille est refusée, le message nomme la
grille, le défaut de l'app, et invite à OMETTRE le paramètre.
⭐ *Une valeur corrigée en silence est une valeur qu'on n'a pas refusée.*

### ⭐⭐ 2026-09-23 (fin) — le souvenir de compétence d'un fil a désormais une SORTIE

> Relevé par Fabien depuis la page web : « Peux-tu anonymiser IMG-…jpg avec SAM3 ? » →
> `Network error: Unexpected token '<', "<html><hea"…`, avec un modèle « qui réfléchit »
> alors que le curseur n'avait pas bougé et que le modèle annoncé était `qwen3.5:4b`.

**La chaîne, mesurée.** Le fil web #12 a chargé `charger_competence('dev')` le **22/09 à
10:22** (question « Modification du code WAMA » — un choix légitime). Le lendemain, chaque
tour du MÊME fil repartait bridé : `development_model()` → `qwen3.6:35b` (23 Go),
`DEV_QUALITY_INTENT = 100` ≥ `QUALITY_OFFLOAD_THRESHOLD` → **le budget VRAM cesse de borner**
(comportement voulu : « l'offload est le prix assumé de la qualité »), `think` activé. Sur
3,6 Go libres, l'offload CPU a fait dépasser le `timeout = 120` de gunicorn → 504 → **page
HTML** → le front, qui faisait `await r.json()` sans regarder `r.ok`, affichait l'erreur du
PARSEUR au lieu de la raison.

⚠ Le défaut n'est PAS « dev est chargé par défaut » — le défaut est `general`, et
`resolve_domain` y retombe sur toute clé inconnue. Le défaut est qu'**aucun geste ne
permettait de QUITTER** le domaine une fois chargé.
⭐ *Un état qu'aucun geste ne peut quitter n'est pas une mémoire, c'est un piège.*

**Levé** (`conversation_store.last_loaded_domain`) : on remonte le fil du plus récent au plus
ancien, et le premier signal rencontré l'emporte — `charger_competence` REPREND la main, un
outil de la **triade d'app** (`add_` / `start_` / `get_*_status`) la RELÂCHE. Le signal est
DÉRIVÉ de `tool_role`, jamais listé : une app portée à la triade le fournit sans qu'on touche
à ce code. Se servir de WAMA n'est pas en écrire le code. Vérifié sur le fil réel : `'dev'`
→ `''`. 6 gardes (`wama/common/tests/tests_domain_memory.py`), dont la contre-épreuve de bout en
bout (le tour suivant change effectivement de modèle) et celle qui protège l'inverse (parler
du code sans lancer de tâche ne relâche rien).

**Et l'erreur illisible est traitée à part** : `WamaApp.jsonOrExplain` (brique commune
`wama-app-base.js`), consommée par les DEUX surfaces de l'assistant — la page d'accueil et
`wama-assistant-chat.js` faisaient chacune leur `r.json()` en aveugle. Un 504 dit désormais
« le serveur a mis trop de temps… un modèle trop gros pour la mémoire libre peut mettre
plusieurs minutes ». Attesté sans navigateur (parse V8 des fichiers de `staticfiles/`, global
créé, brique exposée).

⚠ **Deux questions restent OUVERTES, elles engagent Fabien** : ① le budget VRAM doit-il
s'effacer sur un chemin HTTP borné à 120 s, alors que le prix assumé de la qualité s'y solde
toujours par un 504 ? ② la PRÉVISION du modèle (`auto_preview`, `predict_model_choice`)
ignore le fil, donc le bridage : elle annonçait `qwen3.5:4b` pendant que le tour partait sur
le 35b. Le marqueur `· dev` existe, mais seulement sur la réponse.

⚠ **Restes signalés, non corrigés** : le cam_analyzer appelle `enrich_on_demand` directement
dans sa tâche (l'autre instance câblée du même mécanisme ; son `list_item_field` annonce un
« futur hook générique » dont Hook A bis est la version scalaire) — et il passe par
`enrich_generative` avec `allow_shorter=False`, donc un prompt de marquage que le skill
RACCOURCIRAIT serait silencieusement rejeté. Jamais mesuré. Et la pipeline traduit selon la
langue du PROFIL sans regarder le texte : un prompt déjà anglais paie un appel de traduction
inutile.

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
✅ **2026-09-28 — un fichier du sas est POINTÉ par les tâches qu'on lance dessus** (demande de
Fabien : *« ajoute l'assistant à l'étape 1 […] autant rendre les choses uniformes »*) :
`tool_api.add_to_*` passe par `media_paths.designate`, la brique des vues d'upload, au lieu de
recopier ; formats lus au catalogue. Et une garde de PROPRIÉTÉ qui manquait aux outils fichier
(`_resolve_user_path` → `readable_by`) : l'assistant pouvait recopier ou lire le fichier d'un
autre utilisateur. Détail : `ROADMAP §24.4 ① bis`. ⏳ Suite décidée le même jour : le dépôt SUR la
fenêtre de l'assistant (card d'entrée v4 en mode « sas », accordéon replié) — `CARD_DESIGN §11.11`.

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

### ⏳ CONTEXTE « JETABLE » — le 1er adopteur de `reference_field` est CHOISI (décision de Fabien, 2026-09-30)

> Proposition de Fabien : *« ajouter un port RAG contextuel directement dans la card d'entrée […]
> un fichier de RAG "jetable" pour sa card, sans forcément devoir gérer le RAG persistant. Ça
> permettrait de gérer dans le même temps le RAG "jetable" de l'assistant, comme dans Claude ou
> ChatGPT […] sans polluer le RAG du projet. Il ne faut que cette entrée n'apparaisse que pour les
> modèles qui gèrent le RAG. Sans lui, l'utilisateur doit organiser son RAG avant chaque tâche. »*
> Validée le même jour sur les points ci-dessous. **À implémenter APRÈS la fin du portage de la
> card v4** (imager, enhancer, transcriber), dans une session dédiée.

**Rien de neuf à inventer : la brique existe, il manquait son câblage.** `process_prompt`
(`reference_files=`) fait comprendre les fichiers (`reference_comprehension.comprehend_files` :
image → vision, document → lecteurs de lot, budgets bornés) et les replie dans le prompt en
`[Reference context]`, POUR CET APPEL — rien n'est écrit dans le RAG. Une app l'active en déclarant
`reference_field` dans `PROMPT_TARGETS` ; « choisir le 1er adopteur » était en attente (ci-dessus,
étape 4, et `§Vérification`). Il est choisi :

1. **Un port « Contexte (pour cette tâche) » dérivé des MODÈLES**, comme tout port de la card v4
   (`app_input_ports`) : un jeton de plus dans `INPUT_TYPES`, déclaré en `inputs_optional` par les
   seuls modèles qui lisent un contexte long (LLM/VLM — le describer, l'assistant, les ASR qui
   acceptent un contexte, ex. Qwen3-ASR). L'auto-ajustement fait le reste : pas de modèle
   compatible → pas d'onglet ; un contexte joint GRISE les modèles qui ne le liraient pas
   (`WamaInputMatch`), la surcharge au volet prime. Jamais un littéral par app.
2. **Jetable par construction** : le fichier est joint ou DÉSIGNÉ à la card (pointé, jamais
   recopié), lu au lancement par `comprehend_files`, et suit la card. Aucun `RagChunk`.
   **L'assistant** : même brique, durée de vie = la CONVERSATION (`conversation_store`), via son
   dépôt en mode « sas » (card v4, décision du 2026-09-28).
3. **Vers le RAG persistant : un GESTE, jamais automatique** (décision du 2026-08-21) — sur chaque
   fichier de contexte, « + Ajouter à mon RAG », même endpoint que l'inspecteur et le menu « … »
   (`/common/api/rag/ajouter/`), niveau par défaut du profil. 4ᵉ surface du geste
   (`WAMA_MEMORY §9quater`).
4. **1er adopteur : le DESCRIBER** (VLM/LLM : un document de domaine guide la description) ;
   **2ᵉ : l'ASSISTANT** (même brique, portée conversation).

**Limite connue, v2 de la même brique** : `comprehend_files` travaille sous budget. Pour un gros
document, découper et retrouver les passages utiles EN MÉMOIRE pour la durée de l'appel (comme
Claude/ChatGPT), toujours sans écrire dans le RAG.

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

**Précision de Fabien (29/08 soir) — le JUGE SYNTHÉTIQUE, un 3ᵉ étage NON construit** : un
VLM analyse le FICHIER DE SORTIE (vidéo anonymisée, image générée…) contre la DEMANDE
d'entrée et rend un verdict — un retour utilisateur SIMULÉ, dense là où les signaux réels
sont épars. Rien de tel n'existe (mesuré : `bench.py` juge des MODÈLES candidats, le triage
`ui_smoke` juge des CAPTURES d'UI — personne ne juge une SORTIE contre sa demande).
Architecture d'accueil évidente : les signaux RÉELS de `RunOutcome` (téléchargé/supprimé/
corrigé) sont épars mais VRAIS — ils sont le jeu de CALIBRATION du juge, pas son concurrent.
⚠ **Un signal isolé ne s'interprète PAS** (recadrage Fabien 29/08) : `supprimé` n'est pas un
rejet — l'utilisateur a pu télécharger son fichier PUIS faire le ménage. C'est la SÉQUENCE
par item qui porte le sens (`telecharge` puis `supprime` ≈ satisfait ; `supprime` sans
`telecharge` ≈ probable rejet ; `corrige`/`relance` = négatifs francs) — et même ainsi ce
sont des étiquettes BRUITÉES, jamais une vérité terrain ;
le juge est une passe LLM AUTOMATIQUE → GOUVERNÉE obligatoirement (leçon prospection +
crashs), nocturne plutôt qu'au fil de l'eau, et JAMAIS de rétroaction automatique sur les
paramètres sans métrique validée (un juge non calibré qui pilote une boucle DÉRIVE).
Chantier à ouvrir quand Fabien le décide — pas avant la stabilisation hôte *(acquise le
2026-09-28 : il ne reste que la décision de Fabien)*.

## Cartographie de l'assistant et de wama-dev-ai — préalable à l'app TRANSVERSALE (MESURÉE 2026-09-15)

> Demandée par Fabien avant d'aligner l'assistant sur le commun (`ROADMAP §8d Phase 3, 4c`) :
> « pour être sûr de ne rien perdre de mécanismes déjà en place, mais de les lui passer par le
> commun ». Relevé par 4 lectures du code, chaque ligne citée ouverte. Ce qui suit est un INDEX
> (où vit quoi, état) — le détail vit dans le code cité. Décisions prises le même jour : l'assistant
> devient une app **transversale** ; la brique `user_settings` devient **durable** (§23.3bis).

### A. Le moteur et ses surfaces

| mécanisme | où | état au 15/09 |
|---|---|---|
| tour sans état `run_assistant_turn` (garde abonnement, résolution du modèle, prompt, boucle d'outils ≤ 5) | `common/services/assistant_engine.py:562-743` | complet |
| tour avec historique SERVEUR `conversation_turn` (best-effort sur le stockage, jamais sur la réponse) | `assistant_engine.py:522-559` ; store `conversation_store.py`, `Conversation`/`ConversationTurn` `common/models.py:950-1026` | ⚠ **périmé au 15/09, corrigé le 2026-09-20 sur MESURE** : adopté par les **trois** surfaces — `views.py:166` (web), `api/v1/views.py:132` (api), `gateway/core.py:208` (canaux). Restent `conversations_of`/`clear` sans vue, et `matrix` sans producteur |
| routage `_llm_call` (local / abonnement / distant), clé personnelle + `cloud_refusal` + modèle ouvert par la clé | `assistant_engine.py:418-474` | ⚠ **trou** : un fournisseur SANS source déclarée (`openai`, `mistral`…) n'a ni garde ni clé personnelle (`:447`) — atteignable par l'API v1 et un POST forgé |
| rôles `_ROLE_TIER` → tier → `llm_utils.modele_par_tier` ; bascule de contexte long `_route_model_by_context` | `assistant_engine.py:102-109`, `:177-188`, `:261-287` | complet ; `debug` absent de l'UI (`views.py:52-58`) |
| appel Ollama `_ollama_call` | `assistant_engine.py:294-360` | complet, mais **4ᵉ implémentation** d'un chat Ollama (cf. §C) |
| prompt d'outils `WAMA_TOOLS_PROMPT`, contexte `_build_wama_context` | `assistant_engine.py:66-89`, `:222-258` | partiel : phrases FR et liste de 8 apps en dur |
| skills de rôle, annonce, `charger_competence`, rappel labo | `assistant_skills.py:84,100,123` ; `tool_api.py:2493` | complet — le DOMAINE est choisi par l'assistant, jamais déduit du canal |
| routage de langue `process_prompt_for('assistant')` | `assistant_engine.py:676-683` | local seulement |
| fournisseurs du sélecteur `chat_provider_choices` + `PROVIDER_SOURCES` | `assistant_engine.py:129-174` | web seulement ; dernière table à la main |
| surface WEB `ai_chat` → **`conversation_turn`** (fil serveur `web`) | `views.py:135-180` ; `home.html` | ⚠ **corrigé le 2026-09-20** : l'historique n'est plus dans le navigateur — `localStorage` est **sans lecteur et effacé** (`home.html:101-102`), seul le réglage de voix y reste (`:107,188`). Le choix de modèle se résout par le réglage durable + tirage auto (`:146-149`) |
| voix (Kokoro/service TTS, `WamaApp.Speech`), avatar, micro, étapes d'outil, `switch_mode`, accueil déclaré + mot d'attente | `views.py:207-445` ; `home.html:212-331,334-389,565` ; `assistant_skills.py:205-239` | complet, **web seulement** ; accueil déclaré seulement après « Effacer » (`home.html:138-146`) ; JS du chat inline (§19.6② : à sortir) |
| surface API v1 `AssistantChatView` → `run_assistant_turn`, historique fourni par le client | `api/v1/views.py:86-135` | complet ; aucun test |
| passerelle : appariement `ChannelLink`, `!lier/!delier/!code/!aide`, pièces jointes → espace WAMA, fichiers produits joints, réponses privées | `gateway/models.py`, `services.py`, `core.py:101-325`, `adapters/discord_bot.py` | complet ; **n'envoie ni fournisseur ni modèle** (`core.py:208`) ; Matrix, slash, rate-limit, notifications : ⏳ |
| `tool_api` : porte unique `execute_tool`, `tool_accessible`, `TOOL_APP_OVERRIDE` (None = transverse) | `tool_api.py:3224-3268,3770-3825` | complet |
| MCP : surface `wama` (outils) et `wama-dev` (process séparé) ; **n'expose pas le tour d'assistant** | `common/services/mcp_server.py`, `dev_tools.py` | complet ; non supervisé ; moteur client MCP ⏳ (étape 5) |
| Claude Code (abonnement) : env explicite sans `ANTHROPIC_API_KEY`, jeton personnel, `cloud_refusal`, lecture seule par défaut | `common/services/claude_code.py:102-237` | complet ; chemin CLI en dur (`:94`) |

**Divergences entre surfaces (à résorber par le commun)** : ~~historique~~ **RÉSORBÉ le 15/09, mesuré le 2026-09-20** (les 3 surfaces sur `conversation_turn` ; MCP n'exécute aucun tour, donc sans objet) ; point d'entrée (`run_assistant_turn` vs `conversation_turn`) ; choix du
modèle (web limité, API libre, Discord figé) ; domaine (API seule) ; fichiers entrants et produits
(Discord seul) ; commandes (Discord seul) ; coût affiché (`!code` seul) ; voix/avatar/étapes (web
seul) ; validation de `history` (API seule) ; découpage de longueur (Discord seul).

### B. Mémoire, RAG, prompts — ce que l'assistant consomme

- Substrat mémoire LIVRÉ (jalons 1-14 de `WAMA_MEMORY.md §10`, dont le 12 : `tool_api.py:2611,2660`).
  **L'assistant ne fait que LIRE** : aucun producteur `PROV_ASSISTANT` (`common/models.py:810`),
  projection conversation → souvenir ⏳ (`ROADMAP §19.5`), approbation sans outil, Hook B RAG jamais
  activé (`prompt_pipeline.py:178`), bascule d'embedder et index vectoriel ⏳.
- Préférences qu'il lit : `UserProfile.preferred_language`, `cloud_policy`, `rag_niveaux_rappel` ;
  `prompt_enrich` sans case dans l'UI.

### C. wama-dev-ai — ce qui recouvre le commun

- **L'assistant n'exécute AUCUN code de wama-dev-ai** : « wama-dev-ai » n'y est que le nom du
  fournisseur Ollama local (`assistant_engine.py:112,436-437`). Les vrais ponts : surface MCP `wama-dev`
  (rôles en sous-processus), import unique `memory.json` → `MemoryItem` (25 souvenirs non approuvés,
  `user=NULL`), catalogue de skills, `check_model_declarations`, et `role_utils` qui appelle
  `ollama_base`/`llm_chat`/`prompt_skills`.
- **Doublons à faire passer par le commun** : sélection (`config.py` `MODELS` + `MODEL_FALLBACK_CHAINS`
  + `select_model_for_role` vs `select_model` — adoption déjà décidée, ROADMAP l.1192-1195) ; **quatre**
  chats Ollama (`llm_utils.ollama_chat`, `_ollama_call`, `role_utils.call_ollama`, `core/llm.LLMClient`) ;
  deux mesures de VRAM copiées (`config.py:575`, `run_audit.py:341`) ; historique `core/history.py` vs
  `conversation_store` ; RAG en mémoire vive (`core/files.py`, `core/tools.py`) vs `recall()` ;
  `memory.json`/`write_memory` (écrit SANS approbation) vs `remember`/`approve` ; deux formats d'appel
  d'outils et trois boucles d'agent (5, 25, 80 tours).
- **Deux systèmes de RÔLES aux mêmes noms, résolus différemment** (dev, coder, architect, debug, fast,
  ultra_fast — noms décalés d'un cran pour fast/ultra_fast). wama-dev-ai a en plus audit, codegen,
  vision, prompt, translate, orchestrator, embed.
- **À ne pas perdre** : température par appel et réglages codegen (32 768 / 0,2 / 900 s) ;
  `num_predict=None` ; chaînes de repli qui résument une MESURE (audit sans Qwen, codegen) ; savoir-faire
  de l'audit (détection du « thinking » par `/api/show`, `num_ctx` selon VRAM, `keep_alive` + déchargement
  en `finally`, retries EOF) ; coopération du rôle `model` avec le gouverneur (à généraliser) ; principe
  des pilotes (faits calculés, `ingest.validate`, contrôle AST, `PENDING_HUMAN_VALIDATION`) ; `corpus.py`.
- **Dette à NE PAS reprendre** : la règle « muter `HF_HUB_CACHE` » encore dans `memory.json:33` (injectée
  au prompt d'audit) et dans le contrôle de `run_codegen.py:219-224` — interdite par `AGENTS.md` depuis le
  03/09 ; CLI interactive qui écrit sur disque (hors doctrine).

### D. Les mécanismes communs qui recevront l'assistant — et leurs frictions mesurées

| brique | où | friction pour l'assistant |
|---|---|---|
| catalogue d'apps | `app_registry.py:596-1100` ; régime transversal = `extra_links` à `gate` (`:509-517,552-558` — depuis le 2026-10-02 : surfaces déclarées par `register_surface`) | ⚠ le code dit « transversal = HORS `APP_CATALOG` » (contrat d'app de fichiers) ; une entrée sans `input_extensions`/`has_batch` vide le catalogue JS de TOUTES les apps (`accounts/context_processors.py:58-59,69-70`) ; aide par défaut écrite pour une file (`app_modern_base.html:236-244`) |
| accès | `permissions.py` `DEFAULT_APP_ACCESS`, `accessible`, `app_id_for_path` | ⚠ la garde par app ne voit que le 1ᵉʳ segment d'URL : `/api/ai-chat/`, API v1 et Discord y échappent (`:181`) ; app non déclarée = commune (`:275-276`) |
| schéma de réglages | `param_schema.py` (`derive_from_model` accepte un champ sans modèle Django `:166-167` ; `schema_for_app` exige `wama.<app_id>.params` `:355`) | défauts de volet non dérivés en commun (`applicable_defaults` = contexte `item` seul `:236`) |
| sélecteur de modèle | `wama-params.js` source `catalog` + `options_auto` + type `intent` ; `api_model_options` `model_manager/views.py:1172-1252` ; `auto_model.resolve_model_choice` | ⚠ l'endpoint n'a ni utilisateur ni `cloud_keys` (`:1205-1206`) : aucun modèle distant listé ni prévu ; la source `catalog` REMPLACE tout le select (`wama-params.js:511`) ; tirage sans source = `model_key` entier (`model_selector.py:575`) vs moteur `(provider, model)` |
| réglages utilisateur | `user_settings.py` (cache 30 j, 3 fonctions) — appelants : transcriber, avatarizer, synthesizer, converter (clé dynamique), composer, describer, imager, reader + générateur | bascule durable : garder `timeout=`, `None` écrit tel quel, clés à recopier (noms d'app avec `_`) ; `anonymizer.UserSettings` influence la TÂCHE (`anonymizer/tasks.py:192-240`) — pas un simple confort |
| volet droit | `volet.py`, `base.html:179-259` | un contenu dans `right_panel_top` est écrasé par la page qui surcharge le bloc ; pages `VOLET_AUCUN` sans aside ; mode simplifié masque les volets (`WAMA_VOLETS.md §7-§9`) |

### D-bis. La TAXONOMIE des modèles était imprécise — corrigée à la source (2026-09-16)

Trouvé par le smoke du sélecteur commun : le tirage « auto » retenait `ollama:glm-ocr:latest` (OCR)
pour une conversation, et la liste proposait `describer:blip` (légendage, `completion=False`).
**Cause mesurée, et ce n'était pas le sélecteur** : la découverte Ollama écrivait
`task='text-generation'` pour TOUT ce qui n'est pas un embedding (`model_registry:1942`) et en
déduisait `model_type='llm'` à la main — un OCR déclarait donc la même chose qu'un modèle de chat,
alors que WAMA le décrit précisément ailleurs (`reader:glm-ocr`, tâche `ocr`). Côté distant, mon
mappage rangeait en `vlm`/`captioning` des modèles de chat multimodaux qu'Ollama range, lui, en
`llm` + `vision`.

Corrigé à la source, même règle des deux côtés : **la TÂCHE est déclarée quand la source est
imprécise** (`model_registry.FAMILLES_OLLAMA`, `cloud_models.FAMILLES_DISTANTES` — déclaration
humaine, jamais devinée d'un nom) et **la CATÉGORIE s'en DÉRIVE** (`model_type_for_task`), dans les
deux chemins de découverte Ollama comme à l'écriture des lignes distantes. Impact mesuré : 1 ligne
sur 139 change (`ollama:glm-ocr:latest` → `ocr`), plus `albert:lightonocr-2-1b` → `ocr` ;
consommateurs de `model_type='llm'` : 4 (`llm_utils:152`, `assistant_engine:267`, schéma de
l'assistant, prospection), tous voulus. ⚠ Défaut trouvé et corrigé dans le même geste :
`model_type_for_task` rend une CHAÎNE là où `ModelInfo` attend un membre `ModelType` (le sync lit
`.value`) — deux modèles échouaient au sync en silence. Gardes : `tests_taxonomie_ollama`.

⏳ Ce qui reste du même défaut (dette ANCIENNE, `models.py:31-34`) : `ModelType` mélange encore
famille, modalité et tâche (`upscaling`, `lipsync`, `ocr` y sont des tâches) ; 12 modèles à
re-typer. Et `check_model_taxonomy` signale 4 tâches non déclarées (`diarization`, `face-analysis`,
`face-restoration`, `image-to-3d`) plus 1 modèle sans tâche — constat ANTÉRIEUR à ce geste.

### E. Constats périmés relevés (à corriger au fil du portage)

`WAMA_MEMORY.md:3-4`, `AGENTS.md` (ligne « Mémoire & RAG »), `ROADMAP §24.5.7`, `PROJECT_STATUS §6` : le
jalon 12 est LIVRÉ · `WAMA_MEMORY §5/§6.4/§7/§7ter` (`approve`, `expire`, HNSW, `indexer`) · ce document :
l.65 (enrichissement « OFF » — faux, `settings.py:884`), l.89-93/256/358-360 (pont wama-dev-ai → skills :
en place), l.255 (5 domaines avec `investigation`), l.406-409 (option `home.html` désormais dynamique,
registre des fournisseurs abandonné) · `ROADMAP §19.0/19.1/19.3/19.6④/19.7`, l.1432 (69 outils) · `AGENTS.md`
§Collaboration et `ROADMAP §6` (phases de wama-dev-ai) · `WAMA_VISION_COMPLET §12.3/§5.7` · docstrings
`assistant_engine.py:20-24`, `api/v1/views.py:96-99` (persistance « différée »), `conversation_store.py:4-8`,
`gateway/core.py:197`, `mecanismes.py:530` (« même store que la page web » — faux côté web).

## Voir aussi
- **`WAMA_HARNESS.md`** (2026-09-19) — l'état de l'art des HARNAIS d'agents et les écarts de WAMA,
  axe par axe. Domaine distinct de celui-ci : ce fichier dit **comment marche notre couche LLM**,
  l'autre dit **ce que font les autres et ce qui nous manque**. Il cite les lignes d'ici, il ne les
  recopie pas — notamment §A (divergences entre surfaces) et §2ter (tables de fournisseurs).
- `ROADMAP.md §10.B` (traduction runtime) et `§16.6` (pipeline + vision méta).
- `WAMA_APP_CONVENTIONS.md §2bis.4` (contrat prompt targets), `§9.9` (héritage).
- `WAMA_APP_GENERATION_ROUTE.md` (briques communes ; remplace `COMMON_REFACTORING.md`, archivé `docs/construction/archive/`).
