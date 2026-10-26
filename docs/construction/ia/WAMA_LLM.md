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
| composer | `prompt` | generative | `default_model_type='music'` (MusicGen EN), `model='composer.ComposerGeneration'` et `lyrics=True` (2026-10-04 : paroles balisées jamais traduites ni enrichies) |
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
- Adopté par imager (4 champs) et **composer** (2026-10-04 : mixin + migration `0018`, la modale
  rend le prompt à deux états avec son ✨, la tâche envoie `effective_prompt` sans seconde passe) ;
  prêt pour le studio, sans code par app.
- **Le déclencheur ✨ est celui de la brique** (`trigger`, + `modelSelect` : le modèle visé apporte
  son contrat) — composer depuis le 2026-10-04, **imager** depuis le 2026-10-05 (card et modale ;
  le bouton écrit dans l'app et son handler délégué, qui recopiait l'appel SANS le modèle visé,
  sont retirés). La brique DIT une erreur et un prompt vide (toast commun) et n'appelle pas deux
  fois pendant l'attente — ce que le bouton de l'imager faisait et que la brique taisait.
- ⚠ **Ce qui se poste depuis la modale = le texte AFFICHÉ + son état** — jamais l'original sous
  l'état `processed` : `apply_prompt_state` l'écrirait dans l'enrichi. C'est ce que faisait la
  modale de l'imager du 2026-08-05 au 2026-10-04 (enregistrer une card enrichie remplaçait
  l'enrichi par le texte tapé). La CRÉATION, elle, poste bien l'original (`addToQueue`).

### Paroles et contrat du modèle visé (2026-10-04)

- **Paroles épargnées** : une cible qui déclare `'lyrics': True` (composer) coupe sa valeur à la
  première ligne balisée (`[Verse]`, `[Chorus]`… — `tagged_lyrics`, la même découpe que les
  backends musicaux). Traduction et enrichissement ne voient que la **description** ; les paroles
  sont recollées **telles quelles**, au lancement (`process_prompt_for`), au ✨ et à l'ingestion
  (`enrich_prompt_value`). Si le modèle ne déclare pas la langue des paroles, la console le dit :
  depuis le 2026-10-05 c'est la langue DÉTECTÉE des paroles (`common/utils/text_language`,
  `langid`, mécanisme `content_language`) ; un verdict peu sûr retombe sur celle du profil.
  ⚠ Cette ligne disait la veille « aucune détection de langue d'un texte n'existe dans WAMA » —
  faux, un relevé borné à `common/` (l'heuristique morte du describer, retirée, et `langid`, déjà
  installé, existaient). Des paroles SEULES n'ont rien à enrichir, et c'est dit.
- **Contrat à l'ingestion** : l'enrichissement à l'ingestion reçoit le contrat du modèle choisi
  (avant : le skill seul — la forme MusicGen pour une card destinée à YuE2). Sous un « auto » dont
  un candidat porte un contrat, l'ingestion **s'abstient** : le lancement enrichit avec le
  contrat du modèle TIRÉ.
- Les contrats musicaux en découlent : le LLM n'écrit **jamais** de paroles (MiniMax-Music3 et
  YuE2 : la description seule ; sans paroles fournies, la pièce est instrumentale).
- **Réglage « Voix »** du composer (`vocals`, même jour — `composer/utils/vocals.py`) :
  `auto` (chanté si le prompt porte des paroles balisées), `instrumental` (paroles retirées),
  `song` (chanté ; sans paroles fournies, elles sont **écrites** — `write_lyrics_for`, skill
  `composer-lyrics`, dans une langue que le modèle chante : celle du profil, sinon l'anglais).
  C'est le SEUL chemin où un LLM écrit des paroles, et il faut le demander. Qui chante : la
  capacité `supports_vocals` du MODÈLE, déclarée par son manifeste (YuE2, MiniMax-Music3 ; ACE-Step
  aussi depuis le 2026-10-05, mais sans backend musical il est dit inlançable — contrat de tâche
  `text-to-music` devenu LIANT le même jour —, donc ni tiré ni proposé sans grisage) ; « Chanson »
  grise au sélecteur (volet et modale) les modèles qui ne chantent pas (`INPUT_MODEL_MATCHING §6.11`) ;
  sous « auto », le tirage ne retient que ceux-là quand la voix est voulue ; un modèle choisi qui
  ne chante pas reçoit la description seule, et la console le dit. Les paroles écrites sont
  **gardées sur la card** (champ `lyrics`, même jour) : éditables dans la modale ⚙ (« Paroles »,
  masqué en instrumental), rejouées telles quelles, jamais réécrites. Ordre de lecture : paroles
  balisées du prompt (priment, c'est dit), sinon celles de la card, sinon écrites (« Chanson »).
  `plan` et `render` surveillent `vocals`, `lyrics` et `prompt_processed` — et ajouter un réglage
  surveillé ne périme plus les cards déjà rendues (`process_runs._watched_changed`).
  ⚠ Revers assumé (relevé par la session pipeline) : sur une card rendue AVANT le 2026-10-04,
  poser des paroles ou changer la voix ne l'affiche pas périmée — sa photo ne portait pas ces
  réglages. Le ▶ de la card rejoue alors tout (`steps_to_run` : « tous à jour → tous ») et
  repose la photo ; seul le badge « périmé » manque.

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
| **C. Niveaux d'ENRICHISSEMENT du prompt** (vision §10) | qu'ajoute-t-on au prompt avant le modèle ? | global (règles DANS le code : langue d'émission, glossaire verbatim) · métier (skills `<app>-<domaine>.md`) · organisationnel · utilisateur | global ✅ · métier ✅ · **organisationnel ❌** · **utilisateur 🔄** (2026-10-20 : son skill de prompt passe devant le système pour lui, `§0bis` ; un skill partagé à l'unité se copie, il ne s'applique pas tout seul aux membres — l'opt-in du RAG) |

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
| **UTILISATEUR** (préférences, habitudes, formats favoris) | langue du profil + enrich on/off ; depuis le 2026-10-20, ses **skills de prompt** (`common.PromptSkill`, page `/common/skills/`) | 🔄 **un skill par utilisateur existe** (`ROADMAP §29`, piste 2 de Fabien) : il porte le NOM d'un skill de prompt et passe devant le système POUR SON AUTEUR (`resolve_skill(…, user=)`) ; il naît privé, se partage par une portée et se COPIE (il ne s'impose à personne), un admin seul le rend système (`services/user_skills`). ⏳ Les skills de RÔLE de l'assistant (`assistant_skills.DOMAINES`) restent des fichiers seuls |

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
         HYBRIDE — résidence de l'embedder (qwen3-embedding:4b depuis le 2026-10-19, WAMA_MEMORY §7)
         arbitrée par le GOUVERNEUR (~5 s à froid, mesuré encore avec le nouveau modèle)
       • add_to_<app> / start_<app> → tâches d'app ⇒ la pipeline d'app s'applique (§2)
  [le message lui-même : kind='intent' via process_prompt_for('assistant','message') —
   routage langue seul, pas d'enrichissement]
```

**Le pivot API — `wama/tool_api.py`** : `TOOL_REGISTRY`, **73 outils** *(mesuré 2026-10-04 — dont `search_docs` / `read_doc`, la doc de WAMA elle-même, `WAMA_MEMORY §7quinquies` ; 69 au 2026-09-12 ;
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

⭐ **`get_item_preview` porte TOUTES les faces depuis le 2026-10-20** (Fabien : *« que l'assistant bénéficie de la preview (y compris during, comparaison, etc) pour n'importe quelle tâche »*) : chaque face que l'aperçu commun annonce (`sides.faces`, `sides.after`), la vue d'une face Pendant (`variant`), `compare` (la Sortie face à `sides.compare_base`), et `look=true`, qui passe les IMAGES de la face à la passe de vision de `look_at_image` (`tool_api._vision_of`, une seule pour les deux outils). L'assistant regarde donc ce qui se construit QUAND on le lui demande ; une face absente est dite (le serveur repliait sur l'Entrée). ⏳ Restent : le chat web ne REND aucune face (JSON brut, liens `/media/` relatifs non cliquables) et l'assistant ne suit pas de lui-même un travail en cours — `ROUTE §F3b`.

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
   ⚠ **Les lèvres décalées (signalé par Fabien le 2026-10-13, `3cd73b6b`)** : le découpage en
   phrases était devenu GLOUTON — une réponse reçue d'un bloc partait en UN seul audio (232
   caractères mesurés), et l'avatar, qui estime le moment de chaque mot sur la durée de chaque
   morceau, accumulait l'erreur sur tout le morceau (pire reprise de phrase : 1,1 s). Le
   découpage rend maintenant le plus court groupe de phrases finies d'au moins 60 caractères
   (`takeSentences`), l'estimation compte les pauses de ponctuation et les chiffres, et la
   latence de sortie mesurée par le navigateur est compensée (`WamaAvatar.outputLatencyMs`).
   Mesuré : pire reprise 0,3 s, 8 reprises sur 9 sous 0,1 s. Gardes :
   `tests_assistant_voice_js` (`ReplyReceivedAtOnceIsSplitTest`, `AvatarLipTimingTest`).
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

**L'ÉCOUTE — conversation vocale avec l'assistant (2026-10-10, demande de Fabien).** Le HTTPS
venait de rendre le micro utilisable (`INFRA_WSL_VS_WINDOWS §HTTPS`) ; Fabien voulait « une
conversation naturelle avec l'assistant, en brique commune utilisable partout ». Constat de
départ : le micro de l'accueil était une DICTÉE par `webkitSpeechRecognition` — l'audio partait
chez Google, il fallait envoyer soi-même, et elle n'existait que sur l'accueil.
- **Brique** `common/static/common/js/wama-assistant-listen.js` (pendant de la voix : celle-là
  parle, celle-ci entend), montée par `base.html` sur les boutons que chaque chat DÉCLARE —
  `data-assistant-mic` (dictée : une phrase écrite dans la zone de saisie) et
  `data-assistant-talk` (conversation : chaque phrase part seule, la réponse est dite, l'écoute
  continue ; reprise d'une page à l'autre pendant la session). Accueil ET volet droit.
- **Découpage de la parole dans le navigateur, par l'énergie** : bruit de fond suivi en continu,
  début à +10 dB pendant 120 ms, fin après 900 ms de silence (1,3 s en dictée), 400 ms d'avance
  gardées. Envoi en WAV 16 kHz mono.
- **Transcription LOCALE** : `views.speech_to_text` (`/api/stt/`) → `service_client.stt_via_service`
  → `/stt` du service vocal (`tts_service.py`, Whisper `ASSISTANT_STT_MODEL` = `large-v3`, filtre
  de parole actif). Pas une tâche Celery (elle attendrait derrière le traitement GPU en cours),
  pas un chargement dans gunicorn (un Whisper par worker). **Mesuré** sur la pile réelle : phrase
  dite par la voix de l'assistant, rendue mot pour mot ; **1,2 s** à chaud pour 5 s de parole,
  **37 à 50 s** au premier appel (chargement, poids sur `/mnt/d`) — d'où un PRÉCHAUFFAGE dès
  que l'écoute s'ouvre, et `read_timeout` 90 s (sous les 120 s de gunicorn et d'Apache).
- **Reprendre la parole** : pendant que l'assistant réfléchit ou parle, une voix plus forte
  (+18 dB) et plus longue (350 ms) coupe sa voix ET interrompt son tour (`chat.abort()`, nouveau
  dans la brique de chat avec `isBusy()` ; `send()` rend désormais la promesse du tour).
  ⚠ **Depuis le 2026-10-13 (décision de Fabien, `39612df5`), la coupure attend la phrase
  COMPRISE** : transcrite, puis reconnue comme n'étant pas l'écho de l'assistant. L'annulation
  d'écho du navigateur peut ne pas couvrir ce que joue la page, et un écho le coupait au premier
  son. Prix assumé : il parle encore le temps de la transcription (1 à 2 s à chaud).
- **L'écho (2026-10-13, `62ffe380`)** : « … si vous avez besoin d'autre chose », fin d'une réponse
  encore jouée par le haut-parleur, est repartie comme réplique — l'assistant s'est répondu.
  Trois trous : l'écoute redevenait sensible dès la fin de l'audio pour la carte son (le
  haut-parleur joue encore pendant la latence de sortie) ; l'avance de 400 ms se remplissait de
  SA voix ; rien ne disait qu'une phrase était la sienne. La correction repose sur le TEXTE : la
  voix retient ses mots et jusqu'à quand elle est audible (`isAudible`, latence de sortie
  comprise) ; l'écoute oublie l'avance quand il se tait ; une phrase commencée pendant qu'il
  s'entendait et faite de ses mots dans l'ordre (≥ 80 %) est écartée (`isOwnSpeech`). Reprendre
  ses mots APRÈS qu'il s'est tu reste une réplique. ⏳ Jamais éprouvé au vrai micro.
  ⚠ **Seulement si le navigateur confirme l'annulation d'écho** (`getSettings().echoCancellation`) :
  sans elle l'assistant s'entendrait et s'interromprait — l'écoute est alors SOURDE pendant qu'il
  répond (chacun son tour), et le bouton le dit. Le serveur, lui, finit le tour interrompu et
  l'enregistre au fil.
- **VRAM, mesurée** : large-v3 occupe **4,1 Go** réels, mais le gouverneur en RÉSERVE **10**
  (`WhisperBackend.recommended_vram_gb`, valeur de repli — CTranslate2 alloue hors de PyTorch).
  Le service le DÉCHARGE donc après 10 min sans phrase (`WAMA_STT_IDLE_UNLOAD_S`). ⏳ Ramener la
  déclaration à la mesure est une décision à part : elle vaut aussi pour le transcriber.
- ⏳ **Restes** : le modèle d'écoute n'est pas TIRÉ (même constat que la voix, point 3 ci-dessus ;
  `large-v3-turbo` ou Kyutai STT 1B — conçu pour le temps réel, déjà au catalogue — seraient
  plus vifs) ; ~~le mode « Speak » du transcriber utilise encore la reconnaissance du
  navigateur~~ (rallié le 2026-10-12, bloc suivant) ; validation à l'oreille et au micro par
  Fabien (aucun test ne remplace un vrai micro).
- Gardes : `common/tests/tests_assistant_listen.py` (23 — vue, client, brique exécutée dans V8 ;
  contre-épreuve faite : sans `chat.abort()`, la reprise de parole passe au rouge). **54 au
  2026-10-13** (capture du Speak, écho, coupure après la phrase comprise ; mutations rouges).
- **Le « Speak » du transcriber écoute par la MÊME brique (2026-10-12, demande de Fabien :
  « aligner sur le commun, réutiliser »).** Le port « en direct » passait encore par
  `webkitSpeechRecognition` (audio chez Google, français imposé) et ouvrait le micro une seconde
  fois pour l'enregistrement. La brique gagne `capture(opts)` — l'écoute SANS chat : même micro,
  même découpage, même route `/api/stt/`, donc même moteur au profil et mêmes phrases fantômes
  retirées. Les phrases partent UNE PAR UNE (texte dans l'ordre de la parole, pas de rafale chez
  Albert) ; `record: true` garde l'enregistrement complet sur le MÊME flux, qui devient la card ;
  `onEnd` est appelé une fois, y compris quand une autre écoute (le chat) prend le micro.
  `transcriber.save_realtime` inscrit le moteur qui a écouté dans `used_backend` (`albert`,
  `whisper`) ; `model_key` reste vide — un texte découpé phrase à phrase n'est pas une mesure du
  modèle. ⚠ Différence assumée : le texte arrive phrase par phrase (après chaque silence), plus
  mot à mot comme avec Google. Gardes : même fichier de tests (capture dans V8, script servi,
  moteur inscrit sur la card).
  **Les réglages du transcriber (même jour, décision de Fabien)** : le texte en direct reste
  PROVISOIRE et le plus rapide possible — l'écoute de l'assistant, au profil, sans le modèle,
  le curseur, les mots-clés, le filtre de parole ni les langues du transcriber. La qualité vient
  de la RELANCE (↻) de la card sur l'audio enregistré, c'est-à-dire la transcription complète
  ordinaire : un seul chemin vers la qualité, aucun second chemin « avec réglages » phrase à
  phrase (B1, écarté : les réglages qui comptent — diarisation, langues multiples, découpage,
  nivellement — ont besoin de l'audio ENTIER, et un modèle lourd chargé au début d'une réunion
  ferait attendre). Pour que la relance suive l'auteur, `save_realtime` passe désormais par la
  cascade COMMUNE des dépôts (`_deposit_settings` → `user_settings.new_element_settings`) au lieu
  de construire la card à la main : elle avait les défauts du modèle et une diarisation FORCÉE.
  Gardes : préférences portées par la card, défauts sans préférence (diarisation active), le
  POST de Speak ne réécrit pas les préférences, la relance part dans la tâche ordinaire.

**Premier essai au vrai micro (2026-10-11) → l'écoute par ALBERT, et les phrases fantômes.**
Fabien a parlé à l'assistant depuis le bureau à distance (le micro passe, dans le navigateur de
l'hôte comme dans celui du poste) : « c'est long », et l'assistant a reçu trois « Sous-titrage
ST' 501 » et un « Merci. » qu'il n'avait pas dits. **Relevé des journaux** : la carte était prise
par d'autres traitements (un banc et des essais d'interface en cours) ; la première phrase a
attendu **90 s** la place que réserve le gouverneur (10 Go) et a échoué en 502, Whisper a mis
34 s à charger, les phrases suivantes 4 à 5 s au lieu de 1,2. Le tour de l'assistant lui-même
avait tiré `ollama:gemma4:12b` (résident, donc préféré par `prefer_loaded`) avec 1,5 Go de marge.
- **Le moteur se décide au PROFIL, pas par un réglage de plus** — `common/tts/speech_input.py` :
  le modèle de transcription DISTANT que le profil ouvre au tirage AUTOMATIQUE
  (`allowed_cloud_keys(automatic=True)` : seul « cloud autorisé » l'ouvre ; « 100 % local » et
  « cloud si saturé » restent en local), appelé par la porte commune `backend_instance_for_key`
  (garde `cloud_access`, clé posée). Le distant refuse, plafonne (Albert : 10 requêtes/min, ici
  SANS attente — `wait_on_rate_limit=False`) ou ne répond pas → le Whisper local prend la phrase.
  La vue rend `engine` ; l'info-bulle de la dictée dit qui écoute (« rien ne sort de WAMA » n'est
  plus affiché à tort). Le préchauffage n'envoie rien quand le distant écoute.
- **Le filtre de parole tourne dans le SERVICE VOCAL** (`/speech-only`, Silero, processeur), pas
  dans gunicorn : importer `faster_whisper` y coûte **52 à 66 s** (mesuré : `ctranslate2` importe
  `transformers`, lu depuis `/mnt/d`), une fois par worker — le service le paie une fois, en fond,
  à son démarrage. Service absent → l'extrait part tel quel.
- **Mesuré** (phrase de la voix locale, clé de Fabien) : silence et bruit → **rien n'est
  envoyé** ; une phrase → Albert **0,65 s** + filtre 0,5 s (dont un transcodage que l'audio du
  navigateur, déjà en 16 kHz, n'a pas). Sans filtre, Albert rend « Bye. » sur un simple son.
- **Phrases fantômes** : les génériques de sous-titres que Whisper invente sur du bruit
  (`Sous-titrage ST' 501`, Amara.org, Radio-Canada, « merci d'avoir regardé »…) sont retirés
  (`drop_phantom_phrases`), quel que soit le moteur — motifs ENTIERS et spécifiques : un
  « Merci. » réellement dit reste une réplique (contre-épreuve au test).
- ⏳ « Wama » est entendu « Ouame » (nom propre ; l'API accepte peut-être une amorce — non
  essayé) ; le tirage du modèle de l'ASSISTANT sous saturation (résident préféré malgré 1,5 Go
  libres) relève du curseur, pas de l'écoute — signalé, pas touché.
- Gardes : 39 tests au même fichier (moteur par profil, repli, préchauffage muet, porte commune,
  route `/speech-only`, filtre des fantômes et sa contre-épreuve, 429 sans attente).

**Remesuré le 2026-10-04 — « encore lent, même par Albert » (Fabien). RIEN de câblé, cinq
constats.** Mesures faites dans un processus neuf (script de mesure du scratchpad de session :
tour instrumenté, appels directs en flux, service de voix), jamais dans gunicorn.

| maillon | mesure | ce que ça dit |
|---|---|---|
| **Albert lui-même** | prompt RÉEL (19 534 car.) en flux : 1ᵉʳ texte 0,3 à 0,8 s, fin 0,6 à 1,9 s selon le modèle (`deepseek-v4-flash` 0,5 / 1,2 s) | le fournisseur n'est PAS le poste lent |
| **1ᵉʳ tour cloud d'un processus** | `import litellm` = **19,5 s** (venv sur `/mnt/d`) ; tour instrumenté : 29,7 s au 1ᵉʳ, **1,4 s** au 2ᵉ | chaque worker gunicorn (4) paie cet import à son premier tour cloud, donc après CHAQUE relance et à chaque recyclage (`max_requests`) |
| **pas de flux sur le chemin cloud** | `_llm_call` : le flux n'existe que pour Ollama | la voix attend la réponse entière ; gain = durée de génération (0,7 s ici, plus sur une réponse longue) |
| **voix : Kokoro ONNX sur le CPU** | `onnxruntime` n'offre que `CPUExecutionProvider` ; 1,3 s de calcul pour 3,1 s de son, 4 à 5 s pour 11 s ; 1ʳᵉ phonémisation 1,1 s | c'est le poste dominant de l'attente AVANT la première parole, et il croît avec la longueur de la phrase |
| **modèle local froid** | `qwen3.5:4b` : 6,5 puis 16,9 s au 1ᵉʳ texte, 0,1 s une fois chaud | chargement puis évaluation du prompt (levier 3) |

Deux défauts de mesure relevés au passage : la **durée d'un tour n'est écrite nulle part**
(`ConversationTurn` : question et réponse portent le même horodatage — on ne peut pas dire ce
que l'utilisateur a attendu) ; et hors avatar, `speakStream` ne demande la phrase suivante
qu'APRÈS la lecture de la précédente (chaîne séquentielle), donc une pause égale au temps de
calcul entre deux phrases — la ligne « demandée PENDANT la lecture » du levier 4 n'est vraie
qu'avec l'avatar, qui met en file.

✅ **Levier ① CÂBLÉ le 2026-10-04 (décision de Fabien : « on charge litellm au démarrage »)** —
`assistant_engine.warm_up()`, lancé en ARRIÈRE-PLAN par chaque worker gunicorn
(`gunicorn_conf.py`, `post_worker_init`) : `litellm` et le client OpenAI qu'il charge
paresseusement (≈ 20 s), l'index du catalogue des backends (≈ 5 s), la liste d'outils (1 s), les
imports du client MCP (1,5 s). Le site sert tout de suite ; un tour arrivé pendant le
préchauffage attend au pire ce qu'il aurait attendu sans lui. Mesuré dans un processus neuf,
premier tour RÉEL par Albert : **29,7 s avant, 2,9 s après** (1,3 s au tour suivant). Dans le
worker et non dans le maître : Django n'y est pas chargé, et l'ouverture du port serait
retardée de 20 s à chaque relance. Gardes : `tests_assistant_surfaces.WarmUpTest`.
⚠ Le profil a montré que le poste n'était pas le seul import : le premier tirage « auto »
importe TOUS les modules de backends (index du catalogue) — un coût de processus, pas de tour.
✅ **2026-10-26 — les PIPELINES des apps entrent au préchauffage, en tête** (étape `app_pipelines`,
`process_pipeline._load_declarations`). Plainte de Fabien : la correction d'une transcription
« charge mais ne s'affiche jamais ». Mesuré : la 1ʳᵉ demande de ses données par un worker neuf
coûtait **24 à 27 s**, dont 25,7 s de chargement des pipelines déclarés — par
`param_schema._params_location`, qui importe `studio.services.generic_runner`, dont l'import
DÉRIVE les ports de dix apps à travers l'inventaire des moteurs (7 978 `stat` sur `/mnt/d`).
Après l'étape : **0,8 s**. Ce n'est PAS une page de l'assistant : toute page d'app et toute
surface les lisent — d'où la tête de liste. ⚠ Le préchauffage entier mesure désormais **142 s**
par worker (litellm 42 s, catalogue des backends 83 s — « ≈ 5 s » le 04/10), quatre workers
ensemble : pendant ce temps, chaque page attend la machine. Deux restes, décisions : rendre
paresseuse la dérivation des ports du studio (`_fill_io_from_ports`, 17 s, retirée du `ready()`
le 20/10 pour la même raison et revenue par `_params_location`) ; et 20 s de
`torch.library._register_fake` qui relit le source de son appelant (`inspect.getframeinfo`)
pendant l'import des backends — un patch de venv (`patches/apply_patches.py`).

✅ **Levier ② CÂBLÉ le 2026-10-04 — la voix sur la carte graphique.** Ce n'était pas un choix : deux distributions du moteur ONNX cohabitaient et la version processeur masquait l'autre (`INFRA_WSL_VS_WINDOWS §onnxruntime`). Réparé, session construite avec la liste commune de fournisseurs, premier appel amorcé au chargement : 1,3 s → 0,18 s pour une phrase courte, 4,5 s → 0,53 s pour 11 s de son. Gardes : `tests_onnx_runtime`. 🔴 relancer le service de voix et les workers.

✅ **Levier ③ CÂBLÉ le 2026-10-04 — le flux sur le chemin cloud.** `llm_chat(on_delta=…)`
demande le flux au fournisseur (LiteLLM, `stream=True`) et `chat_with_source` le relaie ; le
portier `_TokenGate` vaut désormais pour tout fournisseur qui diffuse. Seul l'abonnement Claude
Code reste synchrone. Sans rappel, aucun flux n'est demandé : les apps et les rôles qui
appellent `llm_chat` ne changent pas (contre-épreuve). Mesuré sur deux tours réels par Albert,
processus préchauffé : premier fragment à 1,3 s et 2,1 s.
⚠ **Défaut trouvé par le tour à outil réel** : ce modèle écrit une phrase d'annonce PUIS
l'appel (« Je vérifie vos fichiers. {"tool": …} »), et le portier, qui décidait sur le premier
caractère, laissait partir le JSON à l'écran. Il retient maintenant toute accolade le temps de
savoir si elle ouvre un appel d'outil. Gardes : `tests_assistant_stream` (portier, flux cloud,
relais).

✅ **Levier ④ CÂBLÉ le 2026-10-04 — la phrase suivante demandée pendant la lecture.**
`speakStream` tient deux files : les demandes au service de voix partent l'une après l'autre
dès qu'une phrase est prête, la lecture suit la sienne.
⚠⚠ **Et un défaut plus grave, trouvé en écrivant le test** : chaque fragment du flux était
nettoyé séparément (`stripMarkdown`, qui retire les blancs de tête) — les mots arrivaient donc
COLLÉS, aucune fin de phrase n'était plus reconnue, et la voix ne partait qu'à la fin du tour,
sur un texte sans espaces. Tout tour en flux était touché (le modèle local depuis le 26/09).
Le nettoyage se fait maintenant sur la phrase prête. Gardes : `tests_assistant_voice_js`
(le script exécuté dans V8 ; la garde des mots collés est prouvée par mutation).

✅ **Levier ⑤ CÂBLÉ le 2026-10-04 — la durée du tour MESURÉE, apprise, puis décomptée** (idée
de Fabien : un décompte tiré du temps moyen par modèle, par l'ETA commune). `conversation_turn`
mesure l'attente jusqu'au premier texte visible et jusqu'à la fin, les écrit sur le tour
(`ConversationTurn.seconds_to_first_text`, `seconds_total`) et verse la première à l'ETA commune
(`eta_estimator.record_run`, moyenne mobile par modèle et par matériel, comptes de test
écartés). Au tour suivant, le moteur dit quel modèle il a retenu (événement interne `model`) et
la surface reçoit un événement `eta` que le chat décompte à la place du mot d'attente.
- **Clé d'estimation `assistant-turn:<clé du modèle>`**, distincte de la clé du modèle : celle-ci
  porte déjà son débit AU JETON (banc), qu'une durée de tour écraserait (une ligne par clé).
- **Aucun a priori** : rien n'est annoncé tant que rien n'a été mesuré, ni sous 2 s — un
  décompte inventé serait pire que pas de décompte. Mesuré par deux tours réels : Albert rend
  son premier texte en 1,1 à 1,9 s, donc AUCUN décompte ne s'affiche pour lui aujourd'hui ; il
  apparaîtra pour un modèle local froid ou un tour à outils.
- **Sans écouteur, rien n'est branché** (API, passerelle) : un écouteur demanderait le flux au
  modèle pour une surface qui ne l'affiche pas. Leur durée totale est écrite, pas apprise.
- ⏳ Une seule moyenne par modèle mêle réponse directe et tour à outils — à séparer si l'écart
  se voit. Le décompte est écrit dans le script du chat, pas par le composant `WamaEta` (pensé
  pour une progression en pourcentage, et chargé sur les seules pages d'app).
Gardes : `tests_assistant_stream.TurnWaitTest`, `tests_assistant_voice_js.ChatScriptParsesTest`.

**Mesuré EN SERVICE le 2026-10-05, sur trois tours RÉELS de Fabien par Albert** (durées lues
sur les tours) : premier texte à 5,97 s, 3,41 s et 1,69 s ; fin à 6,07 s, 4,46 s et 11,63 s.
Découpe d'un tour (processus préchauffé, même prompt) : **notre préparation 0,6 à 0,7 s, FIXE** ;
l'attente du premier texte chez le fournisseur 0,5 à 2,9 s, **variable d'un appel à l'autre** ;
le reste est la génération, que le flux rend utile. Les quatre workers ont journalisé leur
préchauffage à la relance du 05/10 (le doute du 04/10 sur le quatrième est levé).

✅ **La liste d'outils se construit UNE fois par processus (2026-10-05).** Question de Fabien :
*« pour les prompts d'outils, est-ce suffisant de lui donner une fois au démarrage ? »* Deux
choses distinctes portaient ce nom :
- **la CONSTRUIRE** — oui, une fois suffit, et c'était le gros de notre préparation : 0,51 s par
  tour (les descriptions d'arguments interrogent l'inventaire des backends) pour un texte qui ne
  dépend que du registre. `tool_api.build_tools_list` la garde en mémoire, clé = le registre
  (noms et fonctions). Préparation d'un tour : **0,74 s → 0,07 s**.
- **la DONNER au modèle** — non : un modèle n'a aucune mémoire d'un appel à l'autre, chaque appel
  doit porter ce qu'il doit savoir. Ce qui s'en approche est le cache de préfixe du fournisseur,
  déjà servi par le levier 2 du 22/09 (partie fixe d'abord). Coût MESURÉ de la liste côté Albert
  (10 990 caractères sur 19 511, 73 outils), six appels alternés : premier texte à 1,66 s de
  médiane avec, 1,14 s sans — environ 0,5 s, noyé dans une dispersion de 0,35 à 2,77 s.
⏳ Son idée de fond — n'annoncer qu'un index et charger les outils d'une app à la demande, comme
les skills — reste le levier ③ du 22/09 : gain ≈ 0,5 s par tour chez Albert, au prix d'un tour de
plus chaque fois que l'assistant doit d'abord charger. À décider sur l'usage, pas sur la latence.

✅ **Les cinq leviers du 2026-10-04 sont câblés.** Levier ANTÉRIEUR toujours ouvert : le ③
du 22/09 (réduire le prompt d'outils — 19 534 caractères de prompt par tour, mesuré ce jour).

✅ **La voix dit ce qui est écrit, et prend son temps (2026-10-18, défauts ENTENDUS par Fabien :
« les mots entre parenthèses ne sont pas lus », « les mots en majuscule sont lus lettre à lettre »,
« la voix pourrait prendre un peu plus son temps sur les ponctuations »).** Mesuré par un
ALLER-RETOUR (texte → Kokoro-ONNX, le moteur de l'assistant → Whisper → texte entendu), jamais à
l'intuition :
- **Les parenthèses** étaient lues côté serveur, mais sans respirer (« Le chat (gris et blanc) dort »
  entendu « Le chat gris est blanc d'or ») ; et le navigateur EFFAÇAIT le code en ligne — un
  second nettoyage, `stripMarkdown`, écrit dans `wama-assistant-voice.js` à côté de la brique
  serveur : « (`instant_preview`) » partait en « () ». Il est RETIRÉ ; la brique `tts_text` est le
  seul nettoyage, et la vue rend `spoken`, le texte effectivement dit, sur lequel l'avatar cale ses
  lèvres. Parenthèses et crochets se disent en INCISES, entre deux virgules (`say_incises`) ; le
  tiret bas d'un identifiant se dit comme une espace ; un bloc de code s'annonce (« bloc de code »)
  et n'est jamais coupé entre deux envois.
- **Les majuscules** : espeak-ng épelle les mots COURTS d'emphase (« UNE », « UN », « MOT », « CE »,
  « DIT », « NE » ; les longs passent). Liste FERMÉE de mots courants remis en minuscules
  (`say_emphasis`) — un sigle (RAG, GPU) reste un sigle : mis en minuscules, il se lirait comme un
  mot. Un LEXIQUE (`tts_text.SPOKEN_FORMS`) dit ce qui se prononce autrement : « WAMA », lu à
  l'anglaise par espeak quelle que soit sa casse, devient « Ouama ».
- **Les pauses** : `kokoro_onnx` sait allonger la pause après chaque marque (`sentence_pause`,
  `clause_pause`), mais seulement avec un modèle qui rend la durée de ses phonèmes ; le nôtre ne la
  rend pas (`has_timings` faux — mesuré : 3,58 s de son pour des pauses de 0, 0,25 et 0,8 s). Le
  texte est donc découpé là où il respire (`tts_text.pause_segments`), chaque segment synthétisé,
  et le silence posé entre eux (`kokoro_onnx_backend.process`, lu dans `options` du contrat
  uniforme). Deux RÉGLAGES de l'assistant (`assistant/params.py`, volet de l'accueil) : fin de
  phrase (défaut 0,4 s) et virgule, parenthèse, tiret (0,15 s) ; la vue les lit dans le réglage
  durable. L'accueil enregistre désormais TOUT son schéma (`WamaParams.read`) — il ne relisait que
  deux champs nommés à la main.
- Mesuré après : emphase et code dits mot pour mot, « Il dort — vraiment — » 1,83 s → 2,95 s.
- ✅ **Le même jour, pour TOUS les moteurs et dans le synthesizer** (demande de Fabien : « on aligne,
  on ne réinvente pas »). La boucle segment → silence a quitté `kokoro_onnx_backend.process` pour
  le CONTRAT des moteurs, `tts_base.TTSBackend.synthesize` — la porte qu'emprunte le service pour
  XTTS, Higgs, Bark, Qwen3-TTS comme pour kokoro (un segment sans rien à dire donne son silence
  sans appel ; le multi-voix de Higgs n'est jamais découpé ; la scène n'ouvre que le 1ᵉʳ segment ;
  borne `MAX_PAUSE_S`). Les deux réglages sont DÉCLARÉS une fois (`common/tts/constants.
  VOICE_PAUSE_SETTINGS` : libellé, bornes, aide), lus par le schéma de l'assistant et par celui du
  synthesizer — champs `VoiceSynthesis.sentence_pause` / `clause_pause` (`db_default`, migration
  `0030` appliquée ; défaut 0 = la voix du moteur ce jour-là — ⚠ **corrigé le 2026-10-20** :
  le synthesizer SUIT l'assistant, décision de Fabien, le défaut 0,4 / 0,15 s est déclaré dans
  `VOICE_PAUSE_SETTINGS` et le modèle en dérive `default`/`db_default`, migration `0031` ; les
  éléments déjà créés gardent leur 0), passés par `render_speech`
  dans `options` (synthèse ET aperçu — le silence entre deux segments longs devient la pause de fin
  de phrase). Volet et modale d'élément, PAS le lot : la modale de lot commune reposterait le défaut
  sur des filles aux pauses différentes (`MODES_QUEUE_UX §5ter`). Le volet a pu les recevoir parce
  que la session de portage a porté le front du synthesizer sur le schéma le même jour
  (`188f732b` : il construisait ses envois par listes de clés — reste transmis, mesuré à l'occasion).
  Le filtrage du texte (incises, emphase, lexique) n'avait rien à porter : le synthesizer passe par
  `text_for_speech` depuis le 2026-09-26. Gardes : `tests_tts_backend_pauses`, `synthesizer.tests`
  (+3), `synthesizer.tests_task` (+1), `tests_kokoro_onnx_phonemes` (+1) — neuf mutations rouges.
  Revérification le même jour : le contrat lit ses segments par le décodeur COMMUN
  (`audio_decode.decode_audio`, qui ne charge pas Django) au lieu d'un lecteur recopié, et la
  découpe par longueur de `render_speech` coupe aux phrases de `tts_text` (`…` compris) au lieu
  de sa propre regex. Page servie vérifiée : curseurs au volet, valeur postée à la création.
  ⏳ Même NATURE, encore à part : la regex des phrases recopiée dans le describer
  (`backends/audio_backend.py`, `text_backend.py`) ; et la découpe par LONGUEUR (`CHUNK_LIMITS` par
  moteur) vit dans le synthesizer, pas au contrat — l'avatarizer appelle le service sans elle
  (troncature kokoro au-delà de ~400 caractères, note de `speech_render`).
- ⏳ Le repli en-process (Kokoro .pt, service indisponible) parle sans les pauses réglées. ⏳ Un modèle ONNX qui rendrait
  les durées (export de `kokoro_onnx`) donnerait les pauses DANS le moteur et des horaires de mots
  MESURÉS pour les lèvres — piste, pas décidée. ⏳ Les nombres, dates et monnaies ne sont pas
  normalisés (espeak les lit lui-même) ; recettes publiques relevées : NVIDIA NeMo-text-processing
  (normalisation par grammaires, `pynini`), `kokorog2p` (phonémisation pour Kokoro, dictionnaire
  français) — à évaluer par la route `library`.
- Gardes : `tests_tts_text.HeardAsWrittenTest` / `PauseSegmentsTest`,
  `tests_kokoro_onnx_phonemes.VoicePausesAreSilencesBetweenSegmentsTest`,
  `tests_assistant_surfaces.VoicePausesTest`, `tests_assistant_voice_js` (code en ligne envoyé,
  bloc jamais coupé, lèvres sur `spoken`) — cinq contre-épreuves par mutation, toutes rouges.

✅ **On GLISSE un fichier sur le chat, comme dans Discord (2026-10-18, demande de Fabien : « on
glisse un fichier sans forcément préciser ce qu'on veut en faire, puis on le précise »).** Sur le
chat de l'accueil et le mini-chat du volet (toute page) : le fichier est déposé dans l'espace de
l'utilisateur par le geste partagé (`WamaFM.upload` → `/filemanager/api/upload/` →
`enregistrer_fichier_utilisateur`, celui de la passerelle et de l'API), montré en pastille sous la
saisie, puis envoyé AVEC le message — ou seul. Le message prend la graphie de Discord, sortie de la
passerelle dans `assistant_engine.message_with_deposits` (« [Fichiers déposés dans mon espace
WAMA : …] », puis le texte ou « Que puis-je en faire ? ») ; l'assistant inspecte
(`inspect_user_file`) et propose : fichier de travail ou de référence d'une app, lot, RAG
(`add_file_to_rag`)… Seuls les chemins LISIBLES par l'utilisateur entrent (`resoudre_chemin_lisible`) :
un chemin posté n'est pas un chemin à soi. Décision de Fabien : pastille puis envoi (pas d'envoi
au dépôt). Le dépôt « Mes Fichiers » de l'accueil simplifié passe par le même `WamaFM.upload`.
Gardes : `tests_assistant_deposit_settings` (message partagé, filtre, tour sans texte ; V8 : dépôt,
chemins envoyés puis effacés, ⚙ sur la modale commune) — cinq contre-épreuves par mutation, rouges.
⚠ **Le même jour, Fabien : « en mode normal, je ne peux pas faire glisser un fichier sur
l'assistant ».** Le fichier du BUREAU passait (smoke Playwright) ; celui de l'ARBRE du volet gauche,
visible seulement en mode normal, non : le glisser de l'arbre est un glisser jstree (souris, aucun
`drop` natif), et `filemanager.js` ne cherchait que des `.drop-zone` de card. Le chat se DÉCLARE
désormais cible de l'arbre (`data-fm-designate`) ; l'arbre lui remet les CHEMINS
(`filemanager:designate`) avant toute résolution d'app — l'accueil n'en déclare aucune — et le
fichier est désigné, jamais re-téléversé. Smoke : accueil et mini-chat du transcriber, chemin envoyé
avec le message ; gardes dans le même fichier, quatre mutations rouges.
⏳ Les trois zones de dépôt de l'accueil simplifié (Fichiers, Médiathèque, Reader) restent :
le chat en fait la généralisation ; les fondre ou non est une décision.

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

**Tous les cerveaux, les MÊMES outils (2026-10-23)** — Ollama, Albert, ILaaS, OpenRouter et l'API
Anthropic par la boucle commune (`run_assistant_turn`, liste du prompt pour tous, déclaration
NATIVE pour les seuls modèles mesurés, `ExternalSource.native_tools`) ; l'abonnement Claude Code
par le serveur MCP (surface `wama`, `claude_code.prepare`) — chaque appel par `execute_tool`, avec
les droits du compte, après la garde de son profil (`cloud_refusal`). La mesure :
`llm_gateway_check --tools` / `--provider claude_code` (`ROADMAP §8d` 5).
✅ *2026-10-26* : déclarés nativement chez **ILaaS** les cinq modèles mesurés 3/3 à sa sortie de
maintenance (`gemma-4-31b`, `llama-3.1-8b`, `mistral-small-4-119b`, `qwen-3.6-35b-instruct`,
`qwen-3.8-27b`) ; `mistral-medium-latest`, saturé (503), garde la liste du prompt. ⚠ `gemma-4-31b`
réussit chez ILaaS ce qu'il ratait chez Albert (`gemma-4-31b-it`, 0/3 le 11/10) : la
déclaration se fait par source ET par modèle.

> 🔓 **LEVÉ pour la CONVERSATION le 2026-10-12** (décision de Fabien : *« le bridage était valable
> tant qu'on n'avait pas d'API souveraine ; maintenant qu'on a Albert et ILaaS, on peut le
> lever »*). Mesuré le même jour (fil Discord #43, §2026-10-12 plus bas) : un seul `dev_run_role`
> faisait passer la conversation d'Albert au modèle local de niveau dev, réflexion imposée —
> 2 min 49 au premier appel, puis un délai dépassé. **La conversation garde son modèle et son
> curseur** ; ni le domaine dev, ni la compétence dev, ni un outil `dev_*` ne la font plus
> basculer. **Le niveau dev reste exigé des RÔLES wama-dev-ai** (`role_utils.resolve_model`), là où
> le code s'écrit, en tâche de fond. Le texte ci-dessous est la trace du 22/09.

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
- **ILaaS (fédération d'inférence de l'ESR) — déclarée le 2026-10-07**, source `ilaas`
  (`https://llm.ilaas.fr/v1`, protocole OpenAI, `hosting='sovereign'`). Elle délivre des clés
  d'**APPLICATION** (une par service, validée par un admin ILaaS) : la source se déclare donc
  `shareable`. Transcription : non branchée. Embeddings : service à part (`rag-api.ilaas.fr`,
  jeton à part — OpenGateLLM, la passerelle d'Albert), déclaré le 2026-10-13 en source
  `ilaas_rag` pour que sa clé se pose, sans que rien ne la lise ; la suite se tranche avec le
  routage des modèles cloud (`ROADMAP §8d`, plan « sélection automatique universelle », étape 7).
  **Mesurée le 2026-10-12, avec la vraie clé d'application** (posée sur la page Sources,
  partagée) :
  - `llm_gateway_check --provider ilaas` → « ✓ Passerelle OK » ; `mistral-small-4-119b` est bien
    l'identifiant SERVI, pas seulement le nom publié ;
  - `/models` ouvre **6 modèles** (`gemma-4-31b`, `llama-3.1-8b`, `mistral-medium-latest`,
    `mistral-small-4-119b`, `qwen-3.6-35b-instruct`, `qwen-3.8-27b`) et ne porte **que** `id`,
    `object`, `owned_by` : aucune tâche, aucune modalité. `default_remote_type='text-generation'`
    s'applique donc à tous — la vision éventuelle de gemma-4 ou des Qwen n'est PAS déclarée
    (⏳ à mesurer modèle par modèle, puis à déclarer, jamais à deviner d'un nom) ;
  - ⚠ **`/models` répond `{"data": []}` en HTTP 200 à ~1 lecture sur 2** (9/20, même clé, mêmes
    en-têtes, avec et sans proxy) — un serveur de leur répartiteur ne connaît pas la clé ; le
    chat, lui, répond 10/10. Prise pour une liste, la réponse vide avait vidé la clé de ses
    modèles à l'enregistrement, sans erreur. Corrigé dans la découverte, pour TOUTE source :
    une liste vide est relue (`cloud_models.LISTING_ATTEMPTS`), puis levée en erreur de
    découverte, qui garde la liste précédente (`tests_cloud_models.EmptyListingTest`). À
    signaler à ILaaS ;
  - joué par l'assistant (`conversation_turn`, `provider='ilaas'`) sur un compte SANS clé
    personnelle : clé partagée reçue (`cloud_access`), 6 modèles ouverts au choix comme au
    tirage, réponse correcte ;
  - attente sur 429 : non mesurée (aucun 429 sur 30 appels, aucun en-tête de limite) — la
    source garde `rate_limit_wait_s` à 0.
- **OpenRouter (agrégateur) — déclaré le 2026-10-10** (décision de Fabien), source `openrouter`
  (`https://openrouter.ai/api/v1`, protocole OpenAI, `hosting='third_party'`, `metered`, clé
  PERSONNELLE non partageable — crédits par compte). Ajout par le registre SEUL, sur la route
  tracée par ILaaS : routage `llm_chat`, fournisseur de l'assistant, contrôle de passerelle et
  sonde nocturne en dérivent. Ce qui lui est propre est dans la DÉCOUVERTE
  (`cloud_models.list_remote_models`) : sa liste ne porte pas de `type` mais les MODALITÉS
  (`architecture`) — seuls entrent les modèles qui répondent en TEXTE (`type_from_modalities` :
  chat, ou chat qui voit) ; le dépôt servi (`hugging_face_id`) devient un alias, donc l'identité ;
  un modèle à prix nul garde `cost_tier='free'` sur sa ligne. Mesuré sur la liste publique :
  **458 modèles**, 19 gratuits, 170 qui nomment leur dépôt, 7 qui produisent des images (exclus).
  Modèle par défaut : `openrouter/auto` (routeur d'OpenRouter). **Données (décision de Fabien,
  même jour)** : chaque requête porte `provider.data_collection = "deny"` — OpenRouter ne la
  route que vers des hébergeurs qui ne conservent pas les données et n'entraînent pas dessus (son
  défaut est `allow`) ; règle DÉCLARÉE sur la source (`ExternalSource.no_reuse_request_body`),
  transmise par `llm_chat` (`extra_body`). `zdr` (aucune conservation) n'est pas imposé.
  **Assoupli le 2026-10-12 (décision de Fabien : « partir des choix utilisateurs »)** : la règle
  suit le PLAFOND d'hébergement du profil, qui gagne un 4ᵉ cran, `third_party_all` (« jusqu'aux
  clouds commerciaux, même s'ils gardent ou réutilisent mes données ») — à ce cran seul, rien
  n'est ajouté (`cloud_models.data_reuse_accepted`, passé par `chat_with_source`) ; en dessous et
  sans utilisateur (clé d'instance), `deny` reste. Pas de migration (l'échelle n'a pas de
  `choices=`). La carte « Modèles cloud » du profil affiche à TOUS l'avertissement
  (`external_sources.DATA_REUSE_WARNING`) avant le choix. Motif mesuré le 12/10 : deux modèles
  `:free` (Gemma 4 31B, Nemotron 3 Super) n'ont qu'UN hébergeur, leur éditeur — si celui-ci garde
  les requêtes, `deny` les rend injoignables — **VÉRIFIÉ le soir même** avec la clé d'instance
  posée (compte sans crédit) : Nemotron 3 Super `:free` → 404 « No endpoints found matching your
  data policy (Free model training) » sous `deny`, « OK » en 1,1 s sans ; les deux Gemma 4
  `:free` → 429 de l'hébergeur dans les deux cas (file gratuite saturée). D'où
  `ExternalSource.free_models_need_data_reuse` : le tirage automatique ne retient ces gratuits
  qu'au dernier cran, et lit désormais le coût PAR MODÈLE (`ROADMAP §8d`, plan « sélection
  automatique universelle », étape 1). Gardes :
  `tests_llm_providers.DeclaredRequestBodyTest`, `tests_cloud_models.HostingCeilingTest`,
  `tests_cloud_models.FreeModelsOfAMeteredSourceTest`, `tests_api_keys.NiveauCloudTest`. Faits vérifiés le
  10/10 : un modèle est servi par un ou plusieurs hébergeurs (13 pour Gemma 4 31B, en partie
  quantifiés fp4), majoritairement américains, région UE réservée aux offres Business/Enterprise ;
  modèles gratuits limités à 20 req/min et 50 req/jour (1 000 au-delà de 10 crédits achetés).
  ⚠ **Non mesuré avec une clé** :
  `manage.py llm_gateway_check --provider openrouter` à jouer à la pose. ⚠ Le tirage AUTOMATIQUE
  n'ouvre ses modèles — gratuits compris, le coût s'arbitrant par source — qu'avec
  `cloud_metered_auto`. ⚠ À la pose d'une clé, ~450 lignes entrent au catalogue et ~170
  manifestes au corpus (provenance) : à décider s'il faut une liste restreinte.
- **Le coût se dit, calculé — 2026-10-10** (demande de Fabien : on distinguait local / distant /
  souverain, jamais gratuit / payant, sauf par accident dans le nom « Claude Code
  (abonnement) »). UN libellé, `external_sources.remote_origin_label` : *hébergement · fournisseur
  · coût* (« Cloud souverain · Albert API (DINUM) · gratuit (quota) »), le coût du MODÈLE s'il en
  déclare un, sinon celui de la source. Lu par l'intitulé de groupe des sélecteurs
  (`model_origin` — un fournisseur qui mêle gratuits et payants, OpenRouter, donne deux groupes),
  l'aide sous le sélecteur et la prévision « auto » (`AIModel.origin_label`, la seconde depuis
  le 2026-10-13) et le profil sous chaque fournisseur
  (`source_origin_label`). Vocabulaire des coûts : `external_sources.COST_TIERS`, dont
  `COST_TIER_CHOICES` dérive. Le nom de la source Claude Code perd « (abonnement) » ; ~~⚠ le
  libellé de l'énumération `ModelSource.CLAUDE_CODE` (admin seulement) le garde : le changer
  demande une migration~~ — ✅ 2026-10-22 : `ModelSource` ne porte plus aucun libellé, le champ
  plus de `choices=` (migration `model_manager/0027`, sans SQL) ; une source se nomme par
  `source_identity`.
- **La barre du model manager filtre par origine, coût et profil — 2026-10-16** (demande de
  Fabien ; 438 modèles OpenRouter facturés au catalogue, mesuré). Trois filtres : **Origine**
  (WAMA local · cloud privé · souverain · commercial, ou tous les distants — `AIModel.hosting`,
  la clé du même calcul que `origin_label`), **Coût** (`COST_TIERS`) et **Pour moi** —
  « ouverts par mon profil » / « tirables en automatique », rabattus à la lecture par
  `api_models_db` depuis `allowed_cloud_keys(automatic=False/True)`, jamais recalculés — et
  seulement quand la liste porte un distant : les sélecteurs des apps lisent cette API à chaque
  page, la règle y coûtait ~10 ms à chaud pour rien (mesuré à la revérification). Tri
  « origine, la plus proche d'abord » (`origin_rank`, le rang de `model_origin`) ; la recherche
  lit aussi l'origine (« souverain », « gratuit »). L'option « Distants (cloud) » du statut part :
  l'Origine la dit. Garde : `tests_cloud_models.FilterBarForMeTest`.
  **Le filtre « Source » NOMME ses sources — 2026-10-20** : il affichait la clé brute
  (`claude_code`, `face_analyzer`). Une lecture, `model_manager.models.source_identity` (une
  app par son identité, une plateforme par son nom au registre des sources). Le badge de card,
  l'inspecteur et la liste d'admin lisent le même nom. ⚠ **Corrigé le 2026-10-22** (Fabien :
  savoir si c'est l'API Claude ou l'abonnement) : un FOURNISSEUR s'y nommait par son seul nom,
  « Claude Code », qui ne dit pas l'abonnement ; il se nomme désormais par `remote_origin_label`
  (« Cloud commercial · Claude Code · abonnement »), la phrase des sélecteurs, et une card
  distante dit l'origine de SON modèle. Groupes dérivés — le monde d'une app, la famille d'une
  source au registre (`source_groups`) ; l'admin filtre par le même nom ; l'inspecteur dit
  l'origine, la plateforme, l'auteur et la licence ; `list_ai_models` / `get_ai_model` rendent
  `source` et `origin`. Le même jour (Fabien : « aligner ce qui ne l'est pas »), `ModelSource`
  devient un VOCABULAIRE sans libellés et le champ perd `choices=` — une source de plus ne
  demande plus de migration ; l'admin ne laisse plus changer une source, premier segment de la
  clé (`WAMA_APP_GENERATION_ROUTE §10.6 P1`). Gardes : `tests_source_identity`,
  `tests_model_platforms`, `tests_identity_route`.
- **Clés d'INSTANCE posées depuis WAMA — 2026-10-07** (décision de Fabien : *« c'est la page
  Sources externes qui doit gérer les clés système »*). Un admin pose la clé d'une source dans
  l'inspecteur de `/common/sources/` (`accounts.InstanceApiKey`, chiffrée comme les clés
  personnelles) ; `external_sources.api_key` la lit **avant** le `.env`, qui reste le repli du
  démarrage et de la ligne de commande. Une source `shareable` peut la **partager** : elle sert
  alors à tout compte qui n'a pas posé la sienne (`api_keys.key_for`, `cloud_models.
  allowed_cloud_keys`), la clé personnelle primant toujours ; Albert ne se déclare pas
  partageable (quotas par compte, décision du 15/09). Le profil affiche « Fournie par
  l'établissement ». Un seul geste d'enregistrement (`api_keys.store_key`) et un seul champ de
  saisie (`WamaKeyField`, `wama-key-field.js`) pour les deux écrans ; la découverte, l'union des
  modèles ouverts et la sonde nocturne lisent les deux natures de clé (`accounts.ProviderKey`).
  ⚠ `HF_TOKEN` reste au `.env` : la bibliothèque HuggingFace lit l'environnement elle-même.
  ✅ **2026-10-26 — la FORME d'une clé se contrôle dans ce geste** : une source déclare le début
  de ses clés (`ExternalSource.api_key_prefix`, mesuré sur des clés réelles : `sk-ant-oat`
  abonnement Claude Code, `sk-ant-api` API Anthropic) ; `api_keys.key_shape_error` refuse une
  clé sans ce début, ou coupée d'un espace ou d'un retour à la ligne — une copie tronquée. Vécu :
  le jeton d'abonnement d'un profil, tronqué au dépôt le 15/09, n'a été refusé (401) qu'au
  23/10, quand il a enfin atteint le CLI. `claude_code.prepare` le dit aussi avant l'appel, pour
  les jetons déposés avant le contrôle. Une source sans forme déclarée n'est pas contrôlée ; les
  clés du `.env` non plus (aucun écran). Garde : `tests_claude_subscription.TokenShapeTests`.
  Au passage, **chantier 5 de `WAMA_HARNESS.md`** : ① `OPENAI_COMPATIBLE_PROVIDERS` est remplacé
  par une dérivation (`llm_utils.openai_compatible_source`) ; ② le modèle par défaut d'un
  fournisseur DÉCLARÉ vit au registre (`ExternalSource.default_model`) — `CLOUD_DEFAULT_MODELS`
  ne garde que les fournisseurs sans source ; ③ (délais par fournisseur) reste à faire. Et
  `assistant_engine.SOURCE_PROVIDERS` connaît toute source `llm` : un modèle `ilaas:*` choisi au
  sélecteur serait sinon parti sur le moteur LOCAL.
  ⚠ **2026-10-12 — le champ de clé affichait le mot de passe WAMA** (relevé de Fabien : l'œil de
  « Clé de l'instance » HuggingFace, puis ILaaS, le montrait en clair). WAMA ne renvoie jamais une
  clé : c'est **Chrome** qui remplissait ce `type="password"`, `autocomplete="off"` y étant
  ignoré — un clic sur Enregistrer aurait posé le mot de passe comme clé d'API. `WamaKeyField`
  déclare désormais `new-password` (la seule valeur que Chrome ne remplit pas), donc profil et
  page Sources ensemble ; même défaut corrigé sur le jeton d'API du profil, la fenêtre « Ajouter
  un utilisateur » (le mot de passe de l'admin y devenait celui du nouveau compte) et le
  formulaire d'inscription ; la connexion déclare `current-password` (remplissage voulu). Tenu
  par `wama/common/tests/tests_password_autofill.py` : tout champ mot de passe des gabarits, du JS
  et des widgets Django DOIT déclarer `new-password` ou `current-password`. Même remède que les
  identifiants d'un dossier distant (`ROADMAP` §rclone, `3af80d55`).
- **Un fournisseur existe s'il est au registre — 2026-10-11** (chantier 5 de `WAMA_HARNESS.md`
  soldé). `llm_chat` refuse tout fournisseur hors registre avant l'appel
  (`llm_utils.declared_llm_source`) ; les six noms sans source (`openai`, `mistral`, `groq`,
  `gemini`, `grok`, `deepseek`) et `CLOUD_DEFAULT_MODELS` sont retirés (`REMOVAL_LEDGER` R113).
  Aucune clé n'était posée pour eux. La clé d'instance de la page sert désormais à TOUTE source
  déclarée appelée sans utilisateur (l'API Anthropic l'ignorait). ③ : l'attente après un 429 sans
  `Retry-After` se déclare par source quand elle est mesurée (`rate_limit_wait_s`, Albert 60 s) ;
  le DÉLAI reste celui de l'appelant, par décision (raisons au chantier 5).
- **Retirer une clé retire ce qu'elle ouvrait — 2026-10-11.** Au profil comme sur la page
  « Sources externes », les modèles distants qu'AUCUNE clé restante n'ouvre sont marqués
  indisponibles (`api_keys.forget_opened_models` → `cloud_models.retire_unlisted`) — marqués,
  jamais supprimés : une clé reposée les rend. Avant, la sonde nocturne ne rattrapait que les
  sources qui gardaient une clé, et les modèles de la dernière clé retirée restaient proposés.
  Une seule exception, depuis le 2026-10-22 : un ANCIEN NOM — un fournisseur qui renomme un modèle
  (même id à la casse près, ou id déclaré parmi les alias du nouveau) ne fait pas un modèle de
  plus. `cloud_models.drop_renamed`, appelée par `retire_unlisted`, le supprime, sauf s'il porte
  un historique d'exécution. Vérifié en direct chez Albert, appliqué : deux lignes
  (`…-A3b-…`, `openai/gpt-oss-120b`). Garde : `tests_cloud_models.RenamedModelTest`.
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
| **wama-dev-ai — les rôles** | `role_utils.call_ollama` → `llm_utils.llm_chat` (`ollama`) → `ollama_chat` (2026-10-20 ; un POST `/api/chat` propre avant) | `ollama_base()` |
| wama-dev-ai — `run_audit` | `/api/ps`, `/api/generate`, `/api/show` | `ollama_base()` (délégué, 2026-09-07) |

**Règle de modification** : une brique d'appel se change après avoir relu **cette ligne-là**
du tableau *et* les appelants réels (`grep` natif — `rtk` compresse, il ne mesure pas). Les
familles ci-dessus étaient **étanches** le 2026-09-07 (rien dans `wama/` n'importe `role_utils`,
`wama-dev-ai` n'importait pas `llm_utils`). ⚠ Ce n'est plus vrai depuis le 2026-09-15 : `role_utils`
appelle `llm_chat` pour un fournisseur distant (Albert), puis `chat_with_source` (13/10), et
depuis le 2026-10-20 pour le local aussi — wama-dev-ai passe par les briques de l'assistant, c'est
la route voulue. `wama/` n'importe toujours pas `role_utils`.

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

### 2quinquies. §Température — le modèle la porte, l'appel suit UNE règle (2026-10-21)

> Décisions de Fabien, le même jour : porter `vision_probe` sur `ollama_chat` ; *« le modèle doit
> porter l'information et le réglage doit apparaître si le modèle le permet »* ; une notion
> GÉNÉRALE à tout modèle qui tire, quel que soit son type ; sans réglage, **celle du modèle** ; les
> appels SANS réglage gardent 0,3 ; elle n'entre PAS dans le curseur rapide/qualité (celui-là
> choisit le modèle, celle-ci règle sa façon de tirer — et une température basse n'est pas une
> qualité : Higgs à 0,3 coupait la voix, GLM-OCR à 0,2 part en boucle).

**Mesuré avant** : aucun choix de modèle n'exposait de température ; `ollama_chat` imposait 0,3 à
qui ne disait rien, l'assistant 0,7 en local, la sonde de vision rien (le fichier de modèle : 1 pour
gemma4 et qwen3.5) — trois règles pour une même notion, et le distant suivait une quatrième
(`llm_chat` : rien d'envoyé, la valeur du fournisseur).

| étage | ce qui la porte |
|---|---|
| **la fiche** (catalogue) | `params` contient `temperature` quand le modèle la lit ; `recommended_temperature` = celle de l'éditeur ; `max_temperature` = la borne du moteur (`model_capabilities`). Ollama : tout modèle qui génère la lit, sa valeur vient du fichier de modèle (`/api/show`, même appel) ; une famille d'OCR garde ses `params` (son moteur la fixe à 0). Distant : un modèle de conversation la lit, Anthropic borne à 1, l'abonnement Claude Code ne la lit pas. Un modèle d'app la DÉCLARE (`default_temperature`, `sampling_caps_from_declaration`) ; BLIP déclare `params: []` |
| **l'appel** | `ollama_chat` / `llm_chat` : `None` = celle du MODÈLE, rien n'est envoyé — la même règle local et distant. Une tâche sans réglage passe `STEADY_TEMPERATURE` (0,3), par son nom : les cinq aides de haut niveau (défaut de leur signature), l'enrichissement, la traduction de prompts (`TranslatorService`), le juge `qc`, l'avis de prospection. La sonde de vision passe par `ollama_chat` (images dans le message) ; une absence de réglage y reste celle du modèle, comme avant |
| **le réglage** | `param_schema.temperature_param(<champ modèle>)`, type `temperature` : vide = celle du modèle ; lié au choix de modèle par trois `cap_from` (`INPUT_MODEL_MATCHING §7`) |
| **les apps** | describer (`vision_temperature`, `llm_temperature`), reader (`llm_temperature`), assistant (`temperature`, réglage d'utilisateur) — chacune la porte jusqu'à l'appel |

**Garde générale** : `tests_temperature.EveryCallNamesItsTemperatureTest` — tout appel de
`llm_chat` / `ollama_chat` / `chat_with_source` / `chat_with_catalog_model` dans `wama/`,
`wama_lab/`, `wama_data/` NOMME sa température (ou relaie `**kwargs`). Le défaut a bougé : un appel
muet aurait changé de température sans erreur, en rendant un texte plausible.

**Les VOIX (même jour, 2e vague)** : un moteur DÉCLARE sa température dans son corps
(`BaseModelBackend.default_temperature`), comme il déclare le clonage — `apply_engine_flags` en tire
la fiche (découverte ET synchronisation d'une ligne prospectée, `declared_engine_value`) et le moteur
lit le réglage par `sampling_temperature` (dans `options`, le contrat uniforme des voix, que
`render_speech` remplit). Higgs 0,7, Audio8 0,8, Bark 0,7 (ses deux étages) la lisent ; Kokoro et
Kokoro-ONNX ne tirent pas ; XTTS et Qwen3-TTS tirent mais ce moteur WAMA ne la leur transmet pas —
dit tel quel (`None`), le réglage se grise plutôt que d'être ignoré. Le synthesizer porte le réglage
(`temperature`, migration 0032), item et volet comme les pauses.

L'avatarizer aussi (`tts_temperature`, migration 0023 — la modale, avec la voix qu'elle règle).

**La MUSIQUE (3e vague)** : le contrat `MusicGenerationBackend.generate` porte `temperature` ;
AudioCraft (MusicGen, AudioGen) la lit (1,0, son défaut), YuE et audio.cpp tirent mais ce moteur
WAMA ne la leur transmet pas — déclaré `None`. Le composer porte le réglage (`temperature`,
migration 0024, au rendu seul) ; ses lignes de catalogue reçoivent la déclaration du moteur par la
même règle (`_composer_engine_flags` → `apply_engine_flags`).

**La REPRODUCTIBILITÉ dépend de la valeur (revérification du 2026-10-22, Fabien)** — et laisser
« celle du modèle » ne l'assure PAS : elle vaut le plus souvent plus que 0 (1 pour gemma4,
qwen3.5, MusicGen ; 0,7 Higgs ; 0,75 XTTS ; 0,9 Qwen3-TTS). Mesuré dans les librairies du venv
(`site-packages`) : à 0, Higgs
(`serve_engine.py:388`) et AudioCraft (`lm.py:381`) prennent le choix le plus probable ;
transformers REFUSE de tirer à 0 (`logits_process.py:282`) ; Bark divise par elle
(`bark/generation.py:482`). D'où, au contrat : `samples(t)` (0 = le choix le plus probable, la
règle appliquée par Audio8, XTTS et Qwen3-TTS) et deux faits de plus sur la fiche —
`min_temperature` (Bark : 0,1, le curseur s'y arrête, mode `min` de `cap_from`) et `reproducible`
(même résultat quel que soit le réglage : Kokoro, BLIP, YuE par sa graine fixe). Sous le curseur, une
ligne dit ce que la valeur DU MOMENT implique (`wama-params.js::_temperatureHint`) ; l'aide ajoute
qu'un modèle distant ne le garantit pas toujours, même à 0.

XTTS (0,75, le `config.json` de ses poids, ligne 149 — sous `AI-models`, hors dépôt ; transmis par
`tts_to_file` → `Xtts.inference`) et
Qwen3-TTS (0,9, `generation_config.json`, ses deux étages) lisent désormais le réglage.

**Restes, nommés** : audio.cpp (aucune option repérée — à mesurer sur le binaire) ; le transcriber
l'a RETIRÉE exprès (reconnaissance de la parole = reproductibilité) — décision de Fabien à prendre
avant de l'y remettre ; les jumelles du bac à sable (`translator_01`, `writer_01`) la recevront par
leur manifeste.

**Ses deux VOISINS, la GRAINE et le TOP P (2026-10-22)** — réglages proposés par Albert (avec
`max_tokens`, les pénalités et les séquences d'arrêt, laissés de côté : aucun n'est une façon de
TIRER). Fabien : *« certains modèles comme dans l'Imager portent déjà seed ou graine. Vérifie bien ce
qui existe déjà pour ne pas faire de doublon. On aligne tout parfaitement. »* **Mesuré avant** : la
graine vivait dans le SEUL imager (`seed`, type `number`, « vide = aléatoire » tenu par une exception
de sa vue, `SETTINGS_EMPTY_IS_VALUE` + `seed_cleared`), lue par les dix moteurs d'image et de vidéo ;
le top_p n'existait nulle part comme réglage, écrit en dur dans deux moteurs (Audio8, Higgs : 0,95).

| étage | graine (`seed`) | top_p (`top_p`) |
|---|---|---|
| **la fiche** | `params` ∋ `seed` : Ollama (tout modèle qui converse), un fournisseur compatible OpenAI (Albert, ILaaS, OpenRouter — `openai_compatible_source`, le prédicat même de l'appel : la fiche ne peut pas promettre ce que `llm_chat` n'envoie pas), les moteurs qui la DÉCLARENT (`reads_seed` — Audio8, Higgs, XTTS, Qwen3-TTS, Bark, AudioCraft, YuE ; tous les moteurs d'image et de vidéo, déclaré une fois sur `ImageGenerationBackend`) | `params` ∋ `top_p` et `recommended_top_p` : Ollama (fichier de modèle, `ollama_parameter`), un fournisseur compatible OpenAI, les moteurs qui le déclarent (`default_top_p` — Audio8 0,95, Higgs 0,95, XTTS 0,85, Qwen3-TTS 1,0, valeurs lues dans leurs librairies) |
| **ne la/le lit pas** | Kokoro ×2, audio.cpp (déclarés), l'API Anthropic (pas de graine), l'abonnement Claude Code | Bark, AudioCraft (il tire par `top_k=250`, `top_p=0` voulant dire « top_k »), YuE, Kokoro ×2, audio.cpp, l'API Anthropic (elle refuse un top_p à côté d'une température) |
| **l'appel** | `ollama_chat` / `llm_chat` / `chat_with_*` et les cinq aides prennent `seed` et `top_p` EXPLICITES, `None` = rien n'est envoyé ; au distant, à une source compatible OpenAI seulement. Un moteur les lit dans `options` (`sampling_seed` POSE la graine sur random, numpy et torch ; `sampling_top_p`) — la musique les reçoit par `sampling` (ex-`temperature`), comme la voix par `options` | idem |
| **le réglage** | `seed_param(<champ modèle>)`, type `seed`, vide = un tirage neuf, bouton 🎲 pour tirer une graine à GARDER | `top_p_param(<champ modèle>)`, type `top_p`, vide = celui du modèle, sa valeur dans le texte d'attente |

**Une règle « vide = un choix », commune** : `param_schema.EMPTY_IS_NONE_TYPES` (`temperature`,
`seed`, `top_p`) — `coerce_*` rend `None`, le volet le garde (`user_settings._EMPTY_IS_VALUE`), et
ce `None` posté l'emporte sur une préférence retenue à la naissance d'un élément. L'exception de
l'imager est retirée (elle n'existait que parce que sa graine était un `number`, dont le vide veut
dire « non fourni »). Ce sont des TYPES et non un champ `nullable` de `Param` : un champ de plus
réécrivait le schéma sérialisé de toutes les apps. Le générateur d'apps leur donne une colonne
nulle (`codegen/models_gen._champ_option` — la température y devenait un `CharField`).

**Les apps** : la graine et le top_p à côté de chaque température — describer (`vision_*`, `llm_*`,
migration 0018), reader (`llm_*`, 0015), assistant (réglages d'utilisateur), synthesizer (0033),
avatarizer (`tts_*`, 0024) ; le composer la graine seule (0025 : aucun de ses moteurs ne lit de top_p),
que YuE emploie pour sa partition ET son rendu (`plan_score(sampling=…)`) ; l'imager sa graine, devenue
la commune. Les apps passent `**sampling_of(item, '<préfixe>')` (les trois, `None` compris) aux appels
de langage, `sampling_options(item, …)` (les réglés seuls) aux moteurs.

**Sous la température**, la ligne de reproductibilité dit qu'une graine fixée rend aussi le tirage
reproductible, sous un modèle qui la lit. Les trois réglages sont AVANCÉS : rangés dans le groupe
« Avancé » replié, qui se forme désormais sur toute surface (`INPUT_MODEL_MATCHING §7`).

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
> de `utils/` vers `backends/image_backend.py` — marche B1 du describer, `41d31eb4` ; l'ancien
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
4. ✅ soldé 2026-10-04 : `PROMPT_TARGETS['composer']` nomme son modèle (`PromptScoped` adopté)
   — l'ingestion enrichit, avec le contrat du modèle choisi (§« Paroles et contrat »).
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

Deux contrôles, dans `assistant_engine` et `development_models` (commit `a79088e5`) :
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
⚠⚠ **RÉFUTÉ le 2026-10-05** (§ suivant) : le plancher ne prévenait rien — un modèle bien
au-dessus (`deepseek-v4-flash` par Albert) a inventé les mêmes tours sur le même fil. Le
« a priori » portait sur le MODÈLE ; la cause était ce qu'on lui SERVAIT.

#### 2026-10-05 — l'historique servi ne montrait AUCUN outil : le modèle imitait des réponses sans outil

> Fabien, depuis Discord : « flouter la plaque » sur une photo déposée, puis « quel est le
> statut ? » → « terminé (ID 649) » et un « 📥 Télécharger… » qui n'est pas un lien. Même
> symptôme que le 27/09, sur le même fil n° 11. Question posée : *qu'a-t-on cassé depuis ?
> le modèle ? les skills ?*

**Mesuré, dans cet ordre** (skill `diagnostic-assistant`) :
1. Les deux tours : `tool_steps` vides, aucune ligne `tool_call` au journal, aucun élément
   créé. « 649 » = « 648 » du 27/09 + 1. Le vrai floutage de la photo (item 1031) avait été
   lancé depuis la page web. La mention « (lien non vérifié — retiré) » n'était pas celle du
   filtre : le modèle l'avait RECOPIÉE des tours du 27/09 — aucune URL, donc `_invented_turn`
   restait muet.
2. Taux d'outils par modèle (tours d'assistant depuis le 20/09) : Albert « défaut » 20/21 ;
   `deepseek-v4-flash` **0/8**, web compris ; `qwen3.8` 9/12. Seul tour Discord réussi du fil :
   26/09 23:05 (`qwen3.8`, `get_anonymizer_status`, fichier joint).
3. **Rejeu réel** vers Albert (outils d'écriture bouchonnés, compte réel intact) : SANS
   historique, le même modèle et le même message appellent l'outil ; AVEC l'historique du fil,
   il reproduit les deux réponses du jour à l'identique, « ID 649 » compris.
4. Ni le fournisseur ni les skills : la réponse d'Albert arrive en `content` avec l'appel JSON
   attendu (`tool_calls` natif vide — hypothèse écartée par mesure), et le bloc d'outils est
   construit à chaque tour depuis le registre, compétence chargée ou non.

**La cause** : `conversation_store.history` ne servait que le TEXTE des réponses. Dans le
contexte du modèle, chaque « terminé » passé était une réponse donnée sans outil — dix
exemples à imiter contre une consigne. Le correctif du 23/09 (`_strip_unsourced_urls`) avait
nommé le mécanisme (« il lit ses propres mensonges ») mais pas sa moitié : *il ne lisait jamais
ses vérités non plus*, puisque les appels réels disparaissaient de l'historique. Un fil où une
fabrication entre ne pouvait donc plus guérir, quel que soit le modèle.

**Levé par trois contrôles** (`assistant_engine`, `conversation_store`) :
1. `history()` rend les `tool_steps` d'un tour d'assistant ; `_sanitize_history` les DÉPLIE
   comme la boucle les a joués — l'appel `{"tool": …}`, son résultat (tronqué à 600 caractères,
   par `_tool_result_message`, la forme UNIQUE de la boucle), puis la réponse. La borne porte
   sur les TOURS, avant dépliage (sinon un échange serait coupé entre appel et résultat).
2. Une réponse passée SANS outil qui porte la mention de lien retiré est remplacée, dans
   l'historique servi, par une note — elle cesse de servir d'exemple. La base n'est pas touchée.
3. La mention écrite par le modèle lui-même compte comme un lien retiré : `_invented_turn`
   reprend le tour.

**Mesure de l'effet**, même rejeu, 4 tirages par cas : texte seul **0/8** tours outillés ;
outils dépliés **8/8** (lancement : `add_to_anonymizer` + `start_anonymizer` ; statut :
`get_anonymizer_status`). Une annotation « aucun outil appelé » sur les réponses sans outil
n'ajoutait rien (8/8) : non retenue. ⚠ Un tirage isolé antérieur avait raté les deux tours
(10/12 au total) : le gain est un TAUX, pas une garantie — le contrôle de sortie (3) reste le
filet. Gardes : `tests_conversation.HistoryCarriesToolStepsTests`,
`tests_unsourced_links.InventedTurnTest.test_a_mark_copied_from_the_history_counts_as_an_invented_turn`,
chacune prouvée par mutation (4 mutations, 4 rouges).
⚠ Reste : un « je lance » SANS outil et SANS mention n'est toujours attrapé par aucun contrôle
de sortie — seul l'historique assaini le rend improbable.
**Et le remède sûr est à la portée de l'utilisateur** : `!oublier` (alias `!forget`, annoncé
dans `!aide`) efface le fil courant d'un canal — le « Effacer » du chat web, par la MÊME brique
`conversation_store.clear_thread` (la vue web y est ralliée : elle cherchait le fil puis
l'effaçait elle-même). Seul ce fil part ; garde d'identité d'abord. ⚠ La trace part avec lui,
comme côté web. Gardes : `gateway.tests.ForgetGestureTests` (2 mutations, 2 rouges).

**Puis, le soir même, sur un fil VIERGE (`!oublier`) : le modèle agit — et deux défauts de plus**
apparaissent derrière, chacun caché jusque-là par le précédent (la leçon du skill : *chaque
défaut en cachait un autre*). Fil n° 35 : `inspect_user_file` → `add_to_anonymizer` refusé par
le schéma (`target_mode='plate'`, `output_quality=90` — le refus dit les valeurs valides, le
modèle se corrige seul) → `add_to_anonymizer` (#1036) → `start_anonymizer` →
`get_anonymizer_status`.
1. **La réponse affichée était l'appel brut** `{"tool": "get_anonymizer_status", "args": {}}` :
   cinq outils pour une limite de cinq, et la sortie de boucle rendait `messages[-2]` — le texte
   du dernier APPEL. Levé : `MAX_TOOL_ITERATIONS` 5 → 8 (le parcours ordinaire en prend 4 ; une
   correction de réglage suffisait à l'épuiser), et la limite ouvre un dernier tour SANS outil
   (`_TOOL_LIMIT_PROMPT`) ; si le modèle veut encore un outil, la réponse est la TRACE des
   actions exécutées (`_TOOL_LIMIT_NOTICE`), jamais l'appel. Gardes `tests_unsourced_links.
   ToolLimitTest` (2 mutations, 2 rouges).
2. **La tâche #1036 a échoué** : « Input file not found: …/anonymizer/input/DSC05016_zjGuits.JPG ».
   Depuis le 28/09, `add_to_anonymizer` DÉSIGNE le fichier déposé (`media_paths.designate` :
   la card pointe `temp/`, rien n'est recopié) ; la tâche RECONSTRUISAIT l'entrée dans
   `anonymizer/input/` (`get_input_media_path`). Les dépôts par la page web passaient — leur
   fichier y est vraiment. Mesuré en base : #1036 est la SEULE card pointée de l'anonymizer ;
   une désignation depuis le gestionnaire de fichiers ou la médiathèque passe par la même brique
   (`received_inputs` → `designate`) et aurait échoué pareil — déduit, non rejoué. *Ce n'est donc pas l'assistant qui avait cessé de marcher le 27/09 :
   le 22/09, l'élément 647 avait été COPIÉ dans `input/`.* Levé : la tâche lit `media.file.path`
   (REMOVAL_LEDGER R104).

#### 2026-10-06 — « vous serez notifié dès la fin » devient VRAI : la fin d'une tâche revient dans son fil

> Fabien, depuis Discord, après un flou relancé plus fort (card #1047) : *« il ne me notifie pas
> lorsque la tâche est terminée. À voir si c'est le même problème dans l'assistant. »* Puis, au
> moment de construire : *« méticuleusement, en profondeur, aligné sur le fonctionnement de WAMA,
> on ne réinvente rien »*.

**Mesuré — la promesse était fausse sur TOUTES les surfaces** : le moteur faisait dire « vous serez
notifié dès la fin » (prompt d'outils, consigne COMPLETION NOTIFICATION) ; or la fin d'une tâche
n'envoyait au propriétaire qu'un e-mail (`notify_job`, compte SMTP incomplet dans `.env`), la cloche
de WAMA n'allait qu'aux collaborateurs, et aucune émission spontanée n'existait vers un canal
(`ROADMAP §19.2`, ⏳ depuis août).

**Ce qui est RÉUTILISÉ** (quatre sources lues avant d'écrire, `AGENTS.md §route`) :
| besoin | brique existante |
|---|---|
| une file persistée, relevée à intervalle | `common.Notification` + la cloche du web (dernier vu, 60 s) |
| d'où vient une tâche | le store de conversation : les étapes d'outils persistées |
| quel élément une étape a créé ou lancé | le contrat méta-app — création = clé uniforme `item_id` (`STUDIO_VISION §2`), lancement = argument principal (`primary_arg_name`, comme le Studio l'appelle) |
| le modèle d'un élément | `DetailRegistry` — sa clé EST la famille d'outils (`audio_enhancer` ≠ `enhancer`) |
| le résultat et son fichier | le geste « statut » : `get_<famille>_status` → `_produced_files` → légende de l'original |
| la fin d'une tâche | le squelette commun (`_notify`) |

**Ce qui est construit** :
1. `notify_job_end(item, app_id, …)` (`common/utils/notifications.py`) — LE point de fin, appelé par
   le squelette : e-mail + notification dans WAMA au propriétaire (`notify_on` seul,
   `UserProfile.wants_in_app_notification`), collaborateurs (E3). La notification DÉSIGNE son
   élément (`app` + `object_type` + `object_id`, migration `common 0028` en `db_default` : le code
   en service crée encore les siennes).
2. `tool_api.tool_family` / `items_of_step` — quel élément une étape a créé ou lancé, lu au contrat.
3. La passerelle relève les fins de tâche (`gateway/core.collect_job_follow_ups`, curseur
   `ChannelCursor`, migration `gateway 0002`), retrouve le fil d'origine, rejoue le statut, et
   l'adaptateur Discord poste (mention de la personne dans un salon partagé) puis enregistre
   l'échange AVEC son étape réelle — un « terminé » sans outil dans l'historique est l'exemple qui
   faisait inventer (§2026-10-05).
4. La promesse du prompt dit ce qui se passe : une notification dans WAMA ; sur un canal, « le
   résultat sera posté ici dès la fin ».

**Trois trous du contrat, trouvés en chemin** :
- `add_to_audio_enhancer` ne rendait pas `item_id` ; les quatre créateurs historiques encore OFFERTS
  au modèle (`create_image`, `synthesize_text`, `compose_music`, `convert_file`) ne l'avaient que
  par leur alias `add_to_*`. Rendu À LA SOURCE, alias réduits à des délégations ; garde
  `tests_tool_item_contract`, DÉRIVÉE du registre d'outils (le « 10/10 » de `STUDIO_VISION` était
  une mesure sans garde : elle comptait les apps, pas la branche audio).
- Le signal `post_save` de l'imager (R105) : depuis P6 il ne réagissait plus qu'aux gestes
  synchrones des vues — ⚠ il ne DOUBLAIT pas les fins de tâche, comme je l'ai d'abord écrit : le
  squelette pose les statuts par `QuerySet.update()`, qui ne déclenche aucun signal. *Écrit, puis
  mesuré, puis corrigé : une explication plausible n'est pas une mesure.*
- Trois tests de `tests_notifications` lisaient les alias d'administration du `.env` de la machine
  et rougissaient dès qu'on y déclarait `wama-admin@` : rendus hermétiques.

⚠ **Langue des identifiants** : trois `reponse` écrits dans l'adaptateur en IMITANT son idiome
(la faute qu'`AGENTS.md` nomme), relevés par `check_identifier_language` et renommés, avec au
passage quatre noms français du corps déplacé (`cible`, `chemin_relatif`…) : mesure code 2682 → 2675.
L'excédent restant sur les trois budgets ne vient d'aucun fichier de ce palier (relevé `--detail`).

**Gardes** (chacune prouvée par mutation — 20 mutations, 20 rouges) : `tests_notifications.JobEndNotificationTest`,
`tests_tool_item_contract`, `gateway.tests.JobFollowUpTests` + `DiscordFollowUpDeliveryTests`,
`imager.tests_task…test_the_end_is_notified_once_and_names_the_generation`.
⚠ Restent : une tâche lancée depuis le WEB ne poste rien dans Discord (décision de Fabien) ; une
relève arrêtée entre la lecture du curseur et l'envoi perd un message de fil (au plus une fois —
la cloche le garde) ; les runs du Studio notifient encore par `notify_job` seul (pas d'élément).

**Revérification de session (2026-10-06, demande de Fabien : « aligné, schéma-driven, rien
réinventé ? »)** — trois écarts trouvés à la relecture, corrigés, chacun prouvé par mutation :
1. **Le fichier joint venait du STATUT**, qui ne liste que les dix derniers éléments : le premier
   d'un lot de vingt lancé depuis Discord serait parti sans son fichier. La brique existait —
   `send_to.sorties_de(surface, instance)`, les sorties DÉCLARÉES d'un élément par l'adapter de
   détail (celle d'« Envoyer vers », de l'inspecteur, du Studio) : adoptée, avec le décodage que
   son contrat laisse à l'appelant (chemins encodés, `tests_send_to:399`). L'appel de statut reste,
   comme étape RÉELLE enregistrée au fil.
2. **`relay_next_step` lisait encore l'id d'un ajout par une liste de clés d'app**
   (`item_id or media_id or id`) — une seconde lecture du contrat, devenue inutile dès que chaque
   ajout rend `item_id` à la source : il passe par `items_of_step`. Son test portait une forme
   SYNTHÉTIQUE (`media_id` seul) que l'outil réel ne rend plus : calé sur la forme réelle.
3. **La boucle de relève de l'adaptateur n'avait aucune garde** (poster chaque fin retenue,
   survivre à une relève en échec) : ajoutées.
Vérifiés sans écart : aucune autre app ne RECONSTRUIT son chemin d'entrée (motifs `basename(<x>.file.name)`
et `app_media_dir(…,'input')` relus un à un : libellés, nommage de sortie, listes de dossiers) ;
pas de brique d'`AudioContext` commun — l'avatar en garde un PRIVÉ pour décoder, le lecteur crée
des contextes jetables, TalkingHead a le sien (`talkinghead.mjs:938`) : le son des notifications
n'en réinvente aucun. ⏳ Piste : UN contexte par page (`WamaApp.audioContext()`, passé à TalkingHead
par `opt.audioCtx`, ligne 926) — utile si les contextes se multiplient, sans objet aujourd'hui.

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

### ⭐ 2026-10-10 — trois défauts sous un tour d'installation (fil web n° 37, rejoué)

Le fil a été éprouvé par l'assistant : prospecter, puis installer trois OCR. Trois symptômes ont
été relevés, et chaque tour a été rejoué avec et sans son historique (skill
`/diagnostic-assistant`). Les outils d'écriture étaient bouchonnés ; aucune installation réelle.

1. **Réponse vide rendue comme un succès.** `prospect_models` avait tourné, puis le modèle local
   a rendu `''`, et le tour est parti en succès : l'utilisateur ne voyait rien.
   - Non reproduit au rejeu, avec la réflexion activée (`done_reason=stop`, 907 jetons).
   - **Contrôle** : une réponse finale vide est rejouée UNE fois. En local, c'est sans réflexion,
     qui peut avoir pris tout le budget. Le rappel du format d'appel est joint à cet essai seul
     (`_EMPTY_ANSWER_RETRY_PROMPT`). Vide encore, la réponse DIT les actions exécutées
     (`_EMPTY_ANSWER_NOTICE`), comme la limite d'outils.
   - Un tour passé resté vide est noté dans l'historique (`_HISTORY_EMPTY_PLACEHOLDER`) : resservi
     vide, il faisait croire au modèle que la demande précédente attendait encore sa réponse.
2. **gpt-oss sur Albert range son appel d'outil NATIF dans le raisonnement.**
   - Mesuré : `content` vide, `finish=stop`, `reasoning_content` terminé par les seuls arguments
     (`{"query": …, "k": 5}`), **sans le nom de l'outil**. `llm_chat` rendait « LLM returned empty
     response » et le tour finissait en 502. Le « Waiting for the result of the model search… »
     d'origine est la même famille.
   - Le motif est désormais nommé (`llm_utils.EMPTY_RESPONSE_ERROR`), et `_llm_call` en fait une
     réponse vide : le contrôle ① s'applique.
   - Taux du jour, sans historique : le 1ᵉʳ appel part vide environ 2 fois sur 3, et le nouvel
     essai rattrape environ une fois sur deux.
   - ✅ **Outils déclarés NATIVEMENT (2026-10-11)**, au fournisseur qui le déclare
     (`ExternalSource.native_tools` — Albert seul, MESURÉ) :
     - sonde d'abord : 2 outils puis les 81 du registre (56 Ko par requête) acceptés, appel
       rendu NOMMÉ (`finish=tool_calls`) ; ⚠ Albert rend une requête identique depuis un cache
       (0,5 s, mêmes jetons) — seul le 1ᵉʳ essai d'une sonde compte ;
     - la liste est CELLE du serveur MCP (`mcp_server.tools_for` : registre filtré par les droits,
       schémas dérivés des signatures), outils dev relayés compris (noms d'arguments seuls) ;
       la liste texte du prompt reste, pour tout fournisseur ;
     - `llm_chat(tools=…)` rend l'appel natif (flux compris, réassemblé par `index`) sous la forme
       texte `{"tool", "args"}` (`llm_utils.tool_call_text`) : la boucle est inchangée ;
     - mesuré en boucle réelle (fil n° 41) : **7 appels nommés sur 8, aucune réponse vide** (avant :
       ~2 sur 3 vides au 1ᵉʳ appel) ;
     - ⚠ effet de bord vu au même fil : les outils DEV, désormais saillants, ont été appelés hors
       propos (`dev_job_status` sur le `task_id` d'une installation) — l'appel d'un outil dev
       BASCULE le tour au niveau développement (local), qui a expiré sous charge. Contrôle posé :
       le résultat d'`install_model` porte son `next_step` (comment suivre). À surveiller : si le
       motif revient, ne déclarer les outils dev qu'en domaine dev.
     - 🔴 **RÉGRESSION LE SOIR MÊME — la déclaration vaut PAR MODÈLE, pas pour la source.** Posée
       pour Albert entier, elle a rendu l'assistant MUET : le tirage « auto » (curseur 80) prend
       `deepseek-v4-flash`, qui écrivait « je vais chercher le fichier » puis `finish=stop` sans
       `tool_calls` (fil web n° 32 : **zéro outil sur tout le fil**, alors que `DSC05016.JPG`
       était au sas). Matrice mesurée, même demande, 3 essais par case :
       | modèle Albert | outils natifs | liste du prompt |
       |---|---|---|
       | deepseek-v4-flash-0731 | **0/3** (annonce sans appel, ou vide) | 3/3 |
       | gemma-4-31b-it | **0/3** (vide) | 3/3 |
       | gpt-oss-120b | 3/3 | 3/3 |
       `ExternalSource.native_tools` devient le tuple des modèles MESURÉS (`('gpt-oss-120b',)`),
       lu par `assistant_engine._accepts_native_tools` ; rejeu par `run_assistant_turn`
       (écritures bouchonnées) : `list_user_files` → `add_to_anonymizer` → `start_anonymizer` →
       statut. ⭐ *Une mesure faite sur UN modèle ne se pose pas sur sa source.*
   - ✅ **Un succès RACONTÉ sur un refus (fil n° 41, deux fois de suite)** : « a bien été
     installé » alors que chaque `install_model` du tour avait été refusé — le récit entre dans
     l'historique, qui le resservira. **Contrôle sur la DONNÉE** (`_refusals_notice`) : un outil dont
     AUCUN appel n'a réussi pendant le tour, et dont le dernier a rendu une erreur, voit son refus
     joint à la réponse (« ⚠ Refusé par WAMA pendant ce tour — rien n'a été fait pour : … ») ; un
     outil échoué puis réussi n'y figure pas. Aucune lecture du sens du texte. Deux tests
     existants faisaient d'ailleurs répondre « le floutage est lancé » sur un outil REFUSÉ (compte
     sans accès) : ils éprouvaient la boucle, leur outil réussit désormais.
3. **Limite de débit d'Albert : 10 requêtes par minute et par clé.** Un tour à huit outils en
   fait neuf, et le 429 finissait le tour par son message brut.
   - **`llm_utils._completion`** : attente sur 429, reconnue par le statut ou le type LiteLLM.
     C'est une seule attente d'une fenêtre entière (60 s, ou `Retry-After`) : trois essais à 20 s
     d'écart ont tous été refusés.
   - C'est la brique commune : assistant et apps.
   - Les copies locales : l'ASR d'Albert garde son attente mais note et compte par la brique
     commune depuis le 14/10 (ci-dessous) ; le Hub dans le prospecteur reste à rallier.
   - **Bascule sur panne (2026-10-13, `ROADMAP §8d` étape 2).** Un échec qui dit le FOURNISSEUR
     saturé — 429, 5xx, connexion refusée, délai dépassé ; jamais une faute de la requête (clé
     refusée, modèle inconnu) — le NOTE dans le cache partagé (`llm_utils.provider_saturation` →
     `source_quota.note_saturation`, dans `cloud_models` jusqu'au 14/10) : pour la CLÉ employée
     s'il s'agit d'une limite de débit (durée : `Retry-After`, sinon l'attente de la source),
     pour toutes s'il s'agit d'une panne
     (3 min). Le tirage AUTOMATIQUE l'écarte le temps de la note (`allowed_cloud_keys`) : donc
     PARTOUT — assistant, apps, transcription distante, rôles de dev — sans qu'aucun ne le lise.
     L'assistant, premier utilisateur (`run_assistant_turn`) : modèle TIRÉ → pas d'attente d'une
     minute, le tirage est REJOUÉ sans la source et le tour continue en le DISANT (« ⟳ albert :
     limite de débit — relais par … », étiquette « · relais (…) ») ; une source n'est jamais
     reprise dans le même tour. Modèle CHOISI → rien ne bascule seul (décision de Fabien, 13/10) :
     l'erreur PROPOSE le relais que prendrait le tirage, et le chat web le joue en un clic
     (« Répondre avec … » : le message renvoyé avec ce modèle, pour lui seul).
     Gardes : `tests_cloud_failover`, `tests_llm_providers.ProviderSaturationNoteTest`,
     `tests_cloud_models.SaturatedSourceOutOfTheDrawTest`.
   - **Le relais garde le HARNAIS** (2026-10-13, question de Fabien : « comme Claude qui change
     de modèle en gardant le contexte ») : le tour continue sur les MÊMES messages — prompt
     système (consignes, compétence de rôle, contexte du labo tiré de la mémoire, état de WAMA),
     historique, outils déjà joués. Ne change que ce qui se règle par modèle : outils natifs,
     réflexion, étiquette. Un relais vers le LOCAL est préparé comme un départ local
     (`assistant_engine._prepare_local_model` : fenêtre de contexte, et traduction de la demande
     si le modèle ne déclare pas la langue) ; le dernier appel, après la limite d'outils, bascule
     aussi. Au journal : `[cloud] … noté saturé` et `[cloud] écartées du tirage`. ⚠ Avant de
     soupçonner un quota, lire le COMPTE du tour : le 13/10, un tour « passé en local » venait
     d'un compte de démonstration réglé en local seul. Gardes : `tests_cloud_failover` (dont le
     bouton « Répondre avec … », exécuté en V8).
   - **Quotas COMPTÉS (2026-10-14, `ROADMAP §8d` étape 3, décision de Fabien : « un
     fonctionnement unique, commun et centralisé »).** La note ci-dessus a déménagé dans la brique
     commune des services externes, `common/services/source_quota.py`, qui COMPTE aussi chaque
     appel servi — par (source, portée de la clé, modèle), en requêtes et en jetons, sur une
     fenêtre GLISSANTE d'une minute et d'un jour. Les plafonds viennent du registre des sources
     (`ExternalSource.quotas`, un `Quota` par limite, qui peut ne viser que certains modèles —
     les gratuits d'OpenRouter partagent 20 requêtes par minute) ou s'APPRENNENT au premier
     refus réel (ce qui a été servi sur la fenêtre devient le plafond de cette clé pour ce
     modèle ; une attente demandée de plus d'une minute vise la limite du jour). Le tirage
     automatique écarte le MODÈLE dont le quota est atteint AVANT le refus
     (`source_quota.unavailable_keys`, lu par `allowed_cloud_keys`). Comptent et notent par elle :
     le chat (`llm_chat`), la transcription d'Albert (sa propre attente gardée, désormais notée
     et comptée), les moteurs de recherche (un moteur qui refuse cède la recherche suivante au
     moteur utilisable suivant — aucun repli n'existait). **Pas encore** : le Hub de Hugging
     Face (33 appels dans 12 fichiers, sans point de passage commun — à créer d'abord),
     Artificial Analysis et GitHub dans la prospection. Mesuré le 14/10 : Albert annonce ses
     limites PAR MODÈLE (`/v1/me/info`), mais sous un numéro de routeur que `/v1/models` ne
     relie à aucun modèle — non lues ; ILaaS n'annonce rien. Gardes : `tests_source_quota`,
     `tests_cloud_models.QuotaOutOfTheDrawTest`, `tests_llm_providers` (compte et plafond appris).

**Et la donnée porte la correction des clés** : le modèle recomposait `reader:hf:org/dépôt` au
lieu de la clé `proposed:hf:org/dépôt` écrite par l'utilisateur. Le refus `not_found` de
`request_install` (bouton, outil, ligne de commande) et celui de `get_install_options` nomment
désormais les clés voisines (`model_installer.similar_model_keys` : même dépôt, même fin de clé,
même nom).

⚠ Le délai de qwen3.8 (~187 s au rechargement à 65 536 jetons de contexte) n'est pas reproduit :
chargement mesuré à 15 s au rejeu.

Tests :
- `tests_unsourced_links.EmptyAnswerTest` (5) ;
- `tests_assistant_stream.CloudRateLimitTest` (3) ;
- `tests_ollama_hub_gguf.SimilarKeysOnRefusalTest` (2).
Les contre-épreuves ont été jouées.

### ⭐ 2026-10-11 — ce que l'assistant ATTEINT : quatre trous du fil web n° 32

Le fil n° 32 ne contient AUCUN appel d'outil. La cause première était la déclaration native posée
pour toute la source Albert (régression, §2026-10-10 ci-dessus). Mais la lecture du fil a montré
quatre trous de PORTÉE, indépendants du modèle. Fabien a demandé de les traiter tous, « en restant
parfaitement aligné avec le fonctionnement de WAMA ; on ne réinvente rien ».

1. **Les faits viennent des outils.** `WAMA_TOOLS_PROMPT` disait : « question → répondre sans
   outil ». Cette règle contredisait `search_docs` et le skill de rôle. Invité à se présenter,
   l'assistant a affirmé l'anonymisation « en toute conformité avec la protection des données »,
   ce qui n'est écrit nulle part.
   - Remplacée par « FACTS COME FROM TOOLS » : `search_docs` pour WAMA, `memory_recall` pour ce
     que l'utilisateur a dit.
   - Ajout : aucune conformité affirmée sans résultat d'outil.
   - Ajout : « NEVER ANNOUNCE AN ACTION YOU DO NOT TAKE ».
   - Garde : tout outil nommé par une consigne existe au registre.
2. **`remember_fact`** — le premier producteur de `PROV_ASSISTANT` (`WAMA_MEMORY §6`, encadré du
   2026-10-11). Le souvenir est PROPOSÉ et validé sur « Mes souvenirs ». ⚠ La validation par le
   propriétaire non staff est une décision ouverte.
3. **`find_user_files`** — brique `common/services/user_files.py`.
   - Recherche par nom dans ce que montre l'arbre du gestionnaire, lu à sa déclaration
     (`_app_folders_config`, montages par `resolve_mount_path`).
   - Bornée par racine ; une racine tronquée est dite.
   - `designate` et `_resolve_user_path` acceptent `mounts/…`, copié à l'entrée
     (`MEDIA_STORAGE_TIERING §8`, encadré du 2026-10-11).
   - La « stratégie de recherche de fichiers » du prompt cherche par nom au lieu de parcourir
     des dossiers fixes.
   - ⚠ `filemanager.api_search` (25 dossiers à la main, sans montages) reste à rallier : le
     fichier est tenu par une autre instance.
4. **`open_page`** — brique `common/services/navigation.py`.
   - Pages du menu (apps du catalogue + surfaces), avec le droit du menu (`accessible_apps`) et
     sans la préférence d'affichage.
   - Le chat retient la page (`applyActions`) et la suit quand la réponse est dite
     (`followPendingPage`). Il ne suit jamais une adresse externe.
   - Le fil suit, puisque chaque chat le recharge.
   - ~~⚠ Le gestionnaire de fichiers, le journal, le calendrier et les catalogues ne sont déclarés
     nulle part comme pages.~~ Soldé le 2026-10-14 pour les pages du menu du compte (bloc
     ci-dessous). Le gestionnaire de fichiers reste hors de portée : c'est un volet, sans page.
     La `permission` d'un registre garde toujours l'actualisation, pas la lecture.

**Les pages du COMPTE (2026-10-14, demande de Fabien : « ajouter l'accès aux pages … du menu
profil depuis l'assistant … en fonction des droits de l'utilisateur comme pour toutes les autres
pages »).** Le menu du compte était du HTML écrit à la main (`header.html`, 18 entrées, une seule
conditionnée : Users, par `is_admin`) ; l'assistant n'en atteignait que Registres et Models,
parce que ce sont des surfaces.
- **Déclaration** `app_registry.register_account_page`, sœur de `register_surface` mais PAS une
  surface (une surface est une app : menu Applications, `/apps/`, abonnement). Chaque app déclare
  ses pages depuis son `ready()` — `accounts` (Profil, Users), `model_manager` (Fonctions,
  Librairies, Models), `common` (le reste, dont la cloche, ouvrable sans entrée de menu). Une page
  qui est aussi une surface y RENVOIE (`surface=`) : sa route n'est pas redite. Une page catalogue
  sans description prend celle de son registre (même route).
- **Le menu du compte est GÉNÉRÉ** de cette déclaration (`navigation.account_menu`, servi par
  `context_processors.user_role`) : le menu et l'assistant ne peuvent plus diverger. La
  déconnexion, un geste et pas une page, reste écrite au gabarit.
- **Le droit est celui de la requête RÉELLE** — `permissions.can_open_page` : la fermeture au
  visiteur (`middleware.visitor_refusal`, extraite du middleware qui l'appelle), la politique de
  l'app du chemin (`permissions.refused_app`, idem), puis le décorateur de la vue, que la page
  DÉCLARE (`public`, `account`, `admin`). Mesuré avant d'écrire : un seul refus par rôle (Users,
  `admin_required`) ; Registres, Models, Fonctions et Librairies relèvent de la politique
  `registries` et sont fermés au visiteur ; Apps, Skills, Licences, Backends, Formats médias et
  Sources sont ouverts à tous. Plusieurs pages montrent MOINS selon le rôle (Documentation,
  Sources, Models, Mes souvenirs) : c'est la page qui filtre, l'ouvrir reste permis.
- **Lectures** — chacune par la brique de sa page : `get_my_calendar` (`calendar.events_for`, la
  fenêtre par `calendar_window`, sortie de la vue), `list_my_notifications`
  (`notification_panel.notification_list`, sortie de la vue du panneau), `list_my_shares`
  (`sharing.shares_overview`), `list_my_rag` (`memory.index.list_rag`, qui porte désormais les
  deux filtres de la page), `get_my_profile` (les champs de `UserProfile` lus par leurs
  MÉTADONNÉES — libellé, valeur affichée — ; aucun secret : jeton et clés ont leurs tables). Le
  journal, les souvenirs, les droits, les registres et la documentation avaient déjà les leurs.
- **La page porte le nom de son entrée (2026-10-16, demande de Fabien).** L'en-tête commun des
  pages catalogue (`_catalog_header.html`) et le titre de l'onglet lisent libellé et icône de
  l'entrée de menu par la route de la requête (`app_registry.account_page_of`, tag
  `wama_catalog.page_heading`) : dix gabarits les recopiaient — l'icône identique dix fois sur dix,
  le titre en trois variantes pour la même page (« Licences » au menu, « Catalogue des licences »
  en titre, « - » ou « — » dans l'onglet). Quatre titres visibles changent donc : Licences,
  Fonctions, Librairies, Sources. Seule une page HORS menu (la lecture d'un doc) passe le sien.
  Le libellé d'un REGISTRE reste à part : il nomme le registre, pas la page (Skills montre les
  registres `skills` et `prompts`). Garde : `tests_catalog_heading`.
- **Briques UI** (2026-10-16) : la page du registre `ui_bricks` (`/common/ui-bricks/`) entre au
  menu, section WAMA, après Formats médias.
- Gardes : `common/tests/tests_account_pages.py` — la PARITÉ (chaque page déclarée × visiteur,
  compte de service de visiteur, membre, membre privé des registres par la politique,
  administrateur : la décision de l'assistant = la réponse de la vue), le menu généré et ses
  deux sections, `open_page` sur les pages du compte, les cinq lectures.
- ⚠ **Incohérence relevée, NON corrigée** : trois définitions d'« administrateur » coexistent —
  `accounts.views.is_admin` (superutilisateur ou groupe `admin`, celle de `admin_required` et du
  menu), le niveau de compte `admin` du profil (`permissions.user_tier`), et
  `can_manage_registries` (niveau développeur ou administrateur). Un compte de niveau « admin »
  hors du groupe `admin` n'ouvre pas Users. Décision à prendre, pas un défaut de ce chantier.
  → **Tranchée le 2026-10-21** : le niveau du profil est la seule définition
  (`PROFILES_PERMISSIONS §1.10`).

Tests : `tests_assistant_reach` — consignes, mémoire, fichiers et montages, pages, et le chat en
V8 sur le fichier servi.

**Rejeu réel** : `run_assistant_turn`, deepseek-v4-flash tiré en auto, sans historique, lectures
réelles, écritures bouchonnées.
- « mets à jour ta mémoire » → `remember_fact`, et la réponse dit « en attente de validation ».
- « flouter dsc05016.jpg » → `find_user_files` → `inspect_user_file` → `add_to_anonymizer`
  (« license plate ») → `start_anonymizer` → statut.
- « emmène-moi sur l'Anonymizer » → `open_page`. La réponse ajoute le lien malgré la consigne,
  sans gravité.
- ⚠ « présente-toi à une assemblée » : **0 appel de `search_docs` sur 4** (un seul
  `charger_competence`). Plus aucune conformité RGPD affirmée, mais un essai dit « tout se fait
  en local, sans rien quitter du labo », alors que le tour passe par Albert.
- **La consigne ne suffit pas pour ce modèle.** Le souvenir que l'utilisateur fait valider ne
  pèsera que si le modèle appelle `memory_recall`, puisque le domaine `general` ne rappelle rien
  (`rag=False`, voulu : pas de recherche à chaque tour). Le levier — injecter les souvenirs
  APPROUVÉS de l'utilisateur, en lexical, dans le prompt du domaine général — est une DÉCISION,
  signalée et pas prise.

### ⭐ 2026-10-12 — « tu disparais quand tu lances des tâches » : sept défauts sous un fil Discord (n° 43)

Fil lu en base (`tool_steps`), croisé avec les journaux d'Ollama, `wama.log` et `logs/dev_jobs/`.
Demande : OCR d'une photo, puis « renvoie-moi le texte », puis « corrige l'API via wama-dev-ai,
fais contrôler par Claude en Opus ». **Ce que l'utilisateur a lu comme une lacune d'API était
d'abord un OCR en échec maquillé en succès.**

| # | défaut mesuré | correctif |
|---|---|---|
| 1 | Card reader #1335 `SUCCESS` à **0 caractère** : Ollama 500 « token repeat limit reached » (glm-ocr sur une note manuscrite 1848×4000, photographiée couchée), `_ocr_image` journalisait et rendait `''` | l'erreur fait échouer la page ; une sortie en BOUCLE est coupée au premier passage (`trim_repetition`), et échoue si elle reste en boucle (`is_degenerate_output`, rapport de compression > 8 ; textes réels ≈ 2). ⚠ Pas de nouvel essai échantillonné : il répète le même paragraphe sans lever (mesuré). Cause racine : l'orientation, cf. plus bas |
| 2 | `{"tool": "get_item_preview", "app": …, "pk": 1335}` AFFICHÉ à l'utilisateur (Albert/deepseek, forme à plat sans `args`) | `_parse_tool_call` lit la forme à plat (au moins un argument) |
| 3 | `add_to_reader(mode=null)` → `NOT NULL` en base | la porte (`sanitize_tool_args`) traite `null` comme « non fourni » pour un paramètre à défaut |
| 4 | aucun outil ne lisait le CONTENU d'un résultat late-binding (seul l'aperçu tronqué à 300 car.) | `get_item_result` : le rendu du bouton ⬇ (`export_builder_for`), ownership dans le corps ; early-binding → `output_url`, que le canal joint |
| 5 | « délai dépassé » à 3 min pile sur Discord : sans flux, le délai httpx plafonnait la génération ENTIÈRE (réflexion du niveau dev comprise), le web n'étant coupé que par 180 s de silence | `_ollama_call` demande toujours le flux ; sans écouteur les fragments sont jetés |
| 6 | **deux messages perdus** (14:54, 15:09) : sessions Discord RENOUVELÉES à 14:58 et 15:16 (`on_ready`, pas `on_resumed`) — Discord ne rejoue rien ; aucune ligne ne disait la coupure (`log_handler=None`, journal de discord.py sans gestionnaire) | rattrapage des salons actifs après une nouvelle session (`discord_bot._catch_up`, ≤ 1 h, annoncé) ; `on_disconnect`/`on_resumed` journalisés ; journal `discord` → `gateway-discord.log`. ⏳ La CAUSE des coupures reste à lire au prochain épisode |
| 7 | rien ne disait quel modèle répondait ; un tour en erreur n'entrait pas au fil (outils joués perdus) ; `dev_run_role` refusait sans dire pourquoi ; `codegen` pris pour un rôle de modification générale ; `ask_claude_code` sans choix de modèle | `engine` au résultat + ligne `-# ☁️ albert · … · 4 s` sous chaque réponse de canal ; tour en erreur enregistré ; refus motivé (longueur, ligne) ; description de `codegen` (glu d'UNE tâche) ; `ask_claude_code(model=…)` |

**Suites du même jour (décisions de Fabien) :**
- **Bridage dev de la conversation LEVÉ** (§1ter) : c'est lui qui faisait passer le fil d'Albert
  à `qwen3.8` local avec réflexion dès un `dev_run_role`.
- **Redressement automatique des images avant l'OCR** — CAUSE RACINE de la card #1335 : la note
  était photographiée COUCHÉE (90°, sans étiquette EXIF) ; glm-ocr n'y lit rien, et la lit juste
  une fois redressée. `ocr_base.upright_image` : EXIF, puis le classifieur d'orientation de page
  de **docTR** (`mobilenet_v3_small_page_orientation`, 6 Mo, CPU, ~0,04 s ; confiance mesurée
  0,89-0,98 sur les quatre rotations). Appelé par le reader pour une image en entrée, par
  glm-ocr pour les pages d'un PDF ; l'original n'est jamais réécrit. Poids sous
  `DOCTR_CACHE_DIR`, posé une fois dans `settings.py`. ⚠ Le téléchargeur de docTR coupait à 81 %
  (empreinte refusée) : fichier récupéré par curl, empreinte vérifiée (`8e60325c…`), déposé à la
  main. Tesseract écarté : paquet système absent, docTR déjà au venv. Mesuré bout à bout :
  photo redressée → note lue, boucle coupée au premier passage (`trim_repetition`).
- **L'assistant reste disponible pendant le développement** (« il faut que l'assistant reste
  toujours disponible ») — trois points, gardés par `tests_dev_job_follow_up` :
  1. **fin de tâche ANNONCÉE, plus jamais suivie dans le tour** : le serveur de dev, qui possède
     les tâches, émet à leur fin une notification `app='dev'` (`dev_tools.notify_finished_jobs`,
     veilleur lancé par `run_mcp_server --surface dev`) ; la cloche du web l'affiche et la
     passerelle la poste dans le fil d'origine (`gateway.core._dev_job_follow_up`, étape
     `dev_job_status` réellement jouée) — le chemin des tâches d'app, pas un second. Un second
     `dev_job_status` d'une tâche en cours dans le même tour n'est plus relayé (contrôle de la
     boucle, `_already_polled`) ; le résultat d'un lancement le dit (`JOB_STARTED_NOTICE`) ;
  2. **Claude Code en tâche de fond** : `dev_claude_code(task, write, model)` sur la surface de
     dev, mêmes gardes que l'appel synchrone (`claude_code.prepare`), jeton dans l'environnement
     du process, jamais dans la fiche. `ask_claude_code` reste synchrone pour une QUESTION
     courte et refuse `write=true` en renvoyant vers `dev_claude_code` ;
  3. **chien de garde de la passerelle** (`discord_bot.watchdog_verdict`) : boucle sans
     battement 60 s → pile de tous les fils dans `gateway-discord.log` (la cause des coupures,
     enfin lisible) ; 300 s gelée ou 600 s déconnectée → le process se relance (`os.execv`).

### ⭐ 2026-10-13 — wama-dev-ai sur la route commune : le modèle tiré pour le COMPTE, la VRAM au gouverneur

Question de Fabien : *« on avait géré les choix de modèles via des workflows dans wama-dev-ai…
il faut automatiser au maximum à partir du model manager et des infos des registres pour ne pas
créer de chemin parallèle »*. Route déjà tracée, et suivie ici : `ROADMAP §8d` (« c'est à LUI
d'adopter la brique », décision du 15/09) et §C ci-dessous (« coopération du rôle `model` avec
le gouverneur, à généraliser »).

**État des lieux MESURÉ — trois couches de choix de modèle, de trois âges :**

| couche | où | lue par | état au 13/10 |
|---|---|---|---|
| `MODELS` (14 entrées : rôle, priorité, RAM), `MODEL_FALLBACK_CHAINS`, `select_model_for_role` (VRAM libre par nvidia-smi − 2 Go, filtrée par `/api/tags`) et **13 `WORKFLOWS`** — des enchaînements de MODÈLES (`standard` = dev → debug, `full` = dev → debug → architect, `ui` = vision → coder…) | `wama-dev-ai/config.py:91-501,654` | l'agent interactif `cli.py` (`run_task` joue un workflow : chaque modèle RÉÉCRIT chaque fichier en entier, pris dans `MODELS` sans mesure de mémoire ni chaîne, consignes pour dev/debug/architect seules) ; `run_audit.py` (chaîne `audit` MESURÉE le 20/08 : les Qwen échouent sur un long prompt d'outils) | un catalogue PARALLÈLE à `AIModel` ; jamais joint par WAMA (la surface ne lance que les six rôles, `dev_tools.ROLES`) |
| bridage « niveau développement » (22/09) | `development_models.development_model` → `select_model` | les six rôles (`role_utils.resolve_model`) | le sélecteur COMMUN, mais tiré SANS compte (`user=None`) — donc local seulement, profil cloud et clés ignorés ; un `provider` distant prenait le modèle par défaut du fournisseur ; le rôle `model` y échappait (chaîne de `config.py`, besoin VRAM de sa table) |
| gouverneur | `resource_governor` | le rôle `model` seul (attente en mode dépannage), `backend` (keep_alive) | l'AUDIT déchargeait TOUT Ollama au début et à la fin de chaque run — le modèle de l'assistant compris — et vidait par l'API web (mot de passe dans `.env`) un process qui ne tient pas la carte |

**Ce qui change :**
1. **La surface tire pour le compte, le rôle ne retire pas.** `dev_tools.role_model` →
   `development_model(user, requested, source=provider)` ; le rôle reçoit `--provider`/`--model`
   RÉSOLUS : un seul tirage, et le modèle que la fiche annonce est celui qui répond (`job['model']`).
   `provider` borne le tirage à ce fournisseur ; un choix sous le niveau est remplacé et
   `model_note` le dit ; sans modèle, refus AVANT tout lancement ; les arguments sont validés
   avant le tirage. Le compte SUIT le rôle dans son process (`development_models.ROLE_USER_ENV`,
   `role_user()`), et l'appel distant passe par `chat_with_source(user=…)` : SA clé, la garde
   cloud commune. **Mesuré pour le compte admin** (profil « cloud autorisé ») : tirage
   `ilaas:qwen-3.8-27b` ; rôle `integrator` joué bout à bout par ILaaS, aucune charge GPU,
   décision juste (« lire une note manuscrite » → reader, 0,93). Jusque-là : `qwen3.8` local, 17 Go.
2. **Une garde GPU commune** (`role_utils.local_llm_guard`) pour les six rôles et l'audit — la
   parade du rôle `model`, généralisée comme son README le demandait : besoin lu au CATALOGUE
   (`auto_model.vram_needed_gb`, la cascade commune), attente en mode dépannage, libération de
   la carte SEULEMENT sur accord (`release_reason` → `obtain_vram`, règle B1), et aucune sonde
   quand rien n'est à décider (`effective_free_gb` ouvre un contexte CUDA dans le process — le
   rôle `model` en ouvrait un à chaque run). `--force` et `--wait-max` (ex-`--attente-max`, rôle
   `model` seul) vivent dans `add_llm_arguments`.
3. **L'audit ne décharge plus personne.** `django.setup()` comme les rôles ; il libère SON modèle
   (`MemoryManager.unload_model`, ligne de résidence comprise) ; `--free-vram` est l'accord.
   Retirés avec leur périmètre : `_free_ollama_models`, `_free_wama_vram`, `--no-free-vram`,
   `--ask-password`, `WAMA_BASE_URL`/`WAMA_USERNAME`/`WAMA_PASSWORD` (`config.py`, `.env.example`).
   ⚠ Un `.env` local peut encore porter `WAMA_PASSWORD` : plus lu, à retirer à la main.

Gardes : `tests_development_models.RoleModelDrawnForTheAccountTest`,
`tests_dev_ai_bridge.RoleGpuGuardTest` et `RolesFollowTheCommonRouteTest`.

**Ce qui reste — le principe des workflows est ACTÉ, la mise en œuvre est à faire proprement :**
une étape ne nomme ni un modèle ni une chaîne ; elle DÉCLARE ce que la tâche exige, comme un
process d'app : capacités (`requires` : completion, vision, appel d'outils…), famille de banc
(`benchmark_family`), intention de qualité. Le sélecteur commun tire alors au catalogue `AIModel`
(VRAM, résidence, profil cloud, saturation — la session de routage, `ROADMAP §8d`). D'où :
- `MODELS`, `MODEL_FALLBACK_CHAINS` et `WORKFLOWS` de `config.py` sont le chemin parallèle à
  retirer, APRÈS avoir porté ce qu'ils résument de MESURÉ (`ROADMAP` l.5066 : sinon on perd une
  capacité) — la chaîne `audit` doit devenir une mesure portée par la ligne `AIModel` (« appel
  d'outils fiable sur ce build »), pas une liste écrite à la main ;
- `cli.py` et ses workflows ne sont joignables que du terminal et choisissent sans le bridage :
  les reprendre (workflows de RÔLES joués par la surface, en tâche de fond) ou les retirer est une
  décision de Fabien — c'est aussi le 3ᵉ concurrent de l'essai d'agent de code (Aider, OpenCode) ;
- hors route, consigné : un rôle lancé À LA MAIN avec `--provider <distant>` sans modèle prend le
  défaut du fournisseur (`role_utils.resolve_model`) ; deux mesures de VRAM copiées
  (`config.get_available_vram_gb`, `run_audit._get_free_vram_gb`) ; `effective_free_gb` ouvre un
  contexte CUDA — une sonde sans contexte, comme `total_vram_gb` depuis le 10/10, serait au
  gouverneur de l'offrir.

### 2026-10-20 — wama-dev-ai sur les briques de l'assistant : appel local, saturation, relais

Demande de Fabien : *« wama-dev-ai doit réutiliser ce qui a été mis en place pour l'assistant afin
d'optimiser la partie dev aussi »*. Le tirage et l'appel DISTANT étaient déjà communs (13/10) ;
un relevé du code en a nommé trois écarts, portés ce jour-là :
1. **Un souverain saturé restait tirable par un rôle.** `development_models.dev_cloud_keys` ouvre
   les souverains dès « cloud si WAMA est saturé » en les reprenant du choix MANUEL
   (`allowed_cloud_keys(automatic=False)`), qui n'écarte pas une source saturée ni un quota
   atteint — seul le tirage automatique le fait. L'exclusion vit désormais dans une fonction,
   `cloud_models.drop_unavailable`, que les deux tirages appellent. Garde :
   `tests_development_models.DevelopmentGradeTest.test_a_saturated_sovereign_source_leaves_the_development_draw`.
2. **L'appel local** : `role_utils.call_ollama` portait son POST `/api/chat` ; il passe par
   `llm_chat(provider='ollama')`, mêmes valeurs à l'octet (fenêtre, résidence, température, délai,
   aucun plafond, aucun proxy) et un échec lève toujours. Garde :
   `tests_dev_ai_bridge.FournisseurDesRolesTest.test_the_local_call_goes_through_the_common_brick_with_the_same_values`.
3. **La reprise d'un appel distant coupé** se lisait au TEXTE de l'erreur (`REMOTE_CUT`, une
   expression sur « Connection error | InternalServerError | timed out ») et rejouait toujours en
   local. Elle suit maintenant la NOTE que la brique pose (`llm_chat` → `source_quota`, la coupure
   reconnue par son type, `provider_saturation`) et rejoue le TIRAGE de développement du compte,
   qui écarte la source notée : un autre souverain ouvert à ce compte, ou un modèle local sous la
   garde GPU — le relais de l'assistant (`_failover_target`, `ROADMAP §8d` étape 2), pour les
   rôles (`role_utils._relay`). Gardes : `tests_dev_ai_app_role` (relais local, relais vers un
   autre souverain, et une erreur de la requête qui n'est pas relayée).

Restent, consignés au §C : le comptage des appels LOCAUX (ni les rôles ni l'assistant ne les
comptent, rien ne nourrit l'ETA d'un rôle), la boucle d'outils et l'extraction du JSON en
double (`core/tools.parse_tool_calls`, `role_utils.extract_json`), `cli.py` et l'audit sur
`config.py`, les deux sondes de VRAM copiées.

### ⭐ 2026-10-13 — « les tests bloquent-ils ma tâche ? » : l'assistant lit la place que montre la card

Fil Discord, OCR #1485 : *« Je pense que les tests en cours bloquent le traitement. Peux-tu me
confirmer ? »* — réponse : *« Je ne peux pas confirmer cette hypothèse »*. Lu en base
(`tool_steps`) : l'assistant avait appelé `get_reader_status`, qui rendait `RUNNING, 0 %` et rien
d'autre, pendant que la card affichait « ⏳ En file · 3 tâches avant ». **L'API ne lui donnait
pas ce que l'utilisateur voyait** — et la pastille elle-même se trompait. Question de Fabien :
*« le problème est peut-être simplement que l'API est à compléter ? »* — oui, et sans outil neuf
(un `explain_wait` proposé d'abord aurait été une 2ᵉ lecture de la file, à côté de celle de la
card). Deux corrections, à la source puis à l'API :

1. **La file globale lit ce que le worker TIENT** (`global_queue.held_messages`, table `unacked`
   du broker). La cause réelle : la campagne de tests de 04:30, plus longue que le délai de
   visibilité (6 h), RE-LIVRÉE au worker GPU relancé et rejouée l'après-midi — hors gouverneur,
   donc invisible de la file. **Mesuré sur un worker jetable** (mêmes versions) : en pool `solo`,
   la tâche EN COURS reste non acquittée jusqu'à sa fin ; au repos, un message à échéance (le
   report « faute de VRAM » du squelette) est tenu hors des listes. D'où trois cas : en cours non
   déclaré (compté, NOMMÉ s'il est système — « Évaluation de modèles » ; la campagne, elle, a
   quitté la file `gpu` le même jour et son titre avec elle, `REMOVAL_LEDGER R122`), orphelin
   d'un worker mort (écarté : délivré avant le démarrage noté au `worker_ready`,
   `note_consumer_ready`), différé (placé à son échéance). ⚠ Deux constats rectifiés au passage : `process_control.is_task_lost`
   (« une tâche qu'il exécute a été acquittée ») et `scripts/wama_services.sh` (« rien à
   redélivrer après un crash »).
2. **L'API porte la place** — la ligne de la pastille, par la même fonction (`place_of`) : `queue`
   dans chaque travail de `get_<app>_status` (générés par `TRIAD_SPECS`) et dans
   `get_item_detail`, avec `before` (ce qui passe avant, nommé si système, anonyme sinon — la règle
   du calendrier). La description d'outil le dit au modèle : « RUNNING à 0 % avec `queue` = en
   file, pas bloqué ». La file n'est lue que si un élément est en mouvement ; illisible, elle ne
   casse jamais la réponse.

Gardes : `tests_global_queue` (`HeldMessagesReadTest`, `HeldSnapshotTest`, `ConsumerReadyTest`,
`AssistantSeesTheQueueTest` — six contre-épreuves par mutation, toutes rouges). Le skill de
diagnostic envisagé n'est PAS fait : l'assistant n'avait rien à observer, le skill aurait raisonné
à vide ; à reconsidérer s'il se trompe encore en VOYANT l'état.
⏳ Restes : effectif au redémarrage de gunicorn ET du worker GPU (le démarrage noté n'existe
qu'à partir du prochain `worker_ready` ; d'ici là, un orphelin n'est écarté que par la règle « un
seul en cours »). ~~Les tâches déclarées au gouverneur hors file GPU (converter, file `default`)
restent comptées dans la file GPU, comme avant — consigné, non tranché.~~ ✅ Soldé le 2026-10-14 :
le gouverneur est au grain du PROCESS (`WAMA_APP_GENERATION_ROUTE §10.6` 4.5) — une conversion
CPU ne se déclare plus, le post-traitement IA se joue sur la file GPU.

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
   ✅ **Le geste sur un FICHIER existe depuis le 2026-10-14** (arbre de fichiers + outils de
   l'assistant `add_file_to_rag` / `add_item_to_rag`, dans `TOOL_REGISTRY` donc aussi à l'API v1
   et au MCP) : l'endpoint reçoit `path`, la brique (`memory.index.add_file_to_rag`) remonte une
   sortie à son élément et lit sinon un document déjà textuel. Le fichier de contexte d'une card
   n'aura qu'à l'appeler sur son chemin — rien à construire de plus pour cette 4ᵉ surface.
4. **1er adopteur : le DESCRIBER** (VLM/LLM : un document de domaine guide la description) ;
   **2ᵉ : l'ASSISTANT** (même brique, portée conversation).

✅ **Premier adopteur RÉEL : le Writer** (bac à sable, 2026-10-01 → 10-05) — avant le describer
prévu ci-dessus, parce que la route « app de zéro » l'a demandé. Deux cibles : `prompt` avec le
document de référence (lu pour son CONTENU), `style_instruction` avec le modèle de mise en page
(lu pour sa FORME). La cible déclare la lecture — `reference_reading: 'content' | 'form'`
(`app_metadata.PROMPT_TARGETS` → `process_prompt(reference_reading=)` →
`reference_comprehension.comprehend_files(reading=)`) : un HTML en `form` livre ses styles et son
squelette sans son texte, une image en `form` sa seule mise en page ; le bloc replié le dit au
modèle (« reproduire la mise en page, jamais le texte »). Une consigne VIDE accompagnée d'une
référence est traitée quand même. Le texte d'un HTML lu pour son contenu passe par la brique des
pages web (`url_ingest.html_to_readable_text`). Mesuré : forme du modèle reprise, aucun mot du
gabarit dans le document produit (`WAMA_APP_GENERATION_ROUTE §10.6`, position commune du 05/10).

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
| routage `_llm_call` (local / abonnement / distant), clé personnelle + `cloud_refusal` + modèle ouvert par la clé | `assistant_engine.py:418-474` | ~~⚠ **trou** : un fournisseur SANS source déclarée (`openai`, `mistral`…) n'a ni garde ni clé personnelle (`:447`) — atteignable par l'API v1 et un POST forgé~~ — **constat périmé, corrigé le 2026-10-11 sur mesure** : `_llm_call` refusait déjà un fournisseur non déclaré pour un utilisateur connecté ; depuis ce jour `llm_chat` le refuse aussi sans utilisateur (`declared_llm_source`, R113) |
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
  + `select_model_for_role` vs `select_model` — adoption déjà décidée, ROADMAP l.1192-1195 ; 🔄 **les six
  rôles l'ont adoptée le 2026-10-13**, tirée pour le compte par la surface ; restent `cli.py` et la
  chaîne mesurée de l'audit, cf. §« 2026-10-13 — wama-dev-ai sur la route commune ») ; **quatre**
  chats Ollama (`llm_utils.ollama_chat`, `_ollama_call`, `role_utils.call_ollama`, `core/llm.LLMClient`)
  — 🔄 **trois depuis le 2026-10-20** : `role_utils.call_ollama` passe par `llm_chat` (§« 2026-10-20 ») ;
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
  en `finally` — ✅ de SON seul modèle depuis le 2026-10-13, il déchargeait tout Ollama —, retries EOF) ;
  coopération du rôle `model` avec le gouverneur (✅ généralisée le 2026-10-13 : `local_llm_guard`) ; principe
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
