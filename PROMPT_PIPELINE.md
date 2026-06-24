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
| `app_metadata.py` | `PROMPT_TARGETS` (déclaration par app) + `process_prompt_for(...)`. Résout modèle (`AIModel`), `enrich`, `reference_field`. |
| `prompt_pipeline.py` | `process_prompt(...)` — orchestre détection langue → routing → traduction → enrichissement → fichiers de référence. Fail-safe. |
| `lang_routing.py` | DÉCIDEUR : `routing_for_model(caps, model_type, input_lang, …)` → `{direct, input_translate, input_pivot, …}`. `_TYPE_LANG_DEFAULT` (diffusion/upscaling/music/audio_gen → `['en']`). Inconnu → `['*']` (direct). |
| `translator.py` | ACTEUR : `TranslatorService` via `translategemma` (Ollama), cache, glossaire do-not-translate, découpage. Passthrough si même langue. |
| `prompt_enrichment.py` | « Upsampling » génératif : `enrich_generative()`. **OFF par défaut** (`settings.WAMA_PROMPT_ENRICH`). Une passe LLM légère, cache, garde longueur, fail-safe. |
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
| composer | `prompt` | generative | `default_model_type='music'` (MusicGen EN) |
| assistant | `message` | intent | `model_id=` dynamique (modèle Ollama résolu) |
| synthesizer | — | — | **aucun target** : `text_content` = contenu à dire (jamais traduit) |

## Garde-fous ressources (récurrent)
- **Traduction** : seulement si le modèle ne gère pas la langue ; passthrough/`direct` sinon → aucun chargement.
- **Enrichissement** : interrupteur maître `WAMA_PROMPT_ENRICH` (OFF) + garde longueur + cache.
- **Fichiers de référence** : data-gated (rien si pas de fichier).
- **Transparence** : messages console user-facing (🌐 traduit / ✨ enrichi / 📎 référence) ; **silence si direct**.

## Hooks à venir
- **RAG** (`apply_rag`, commenté dans `prompt_pipeline`) : récupération depuis store **ChromaDB** +
  embeddings **bge-m3**. No-op tant que la fondation `wama/rag/` + l'indexation (§8c) n'existent pas.
- **QC** : câbler `qc.py` en post-génération dans les apps.

## Réglages (`wama/settings.py`)
- `WAMA_PROMPT_ENRICH` (env, défaut OFF) — interrupteur maître de l'enrichissement.
- `WAMA_PROMPT_ENRICH_MODEL` (env, optionnel) — modèle d'enrichissement (défaut `llm_chat`).

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
- `COMMON_REFACTORING.md` (briques communes).
