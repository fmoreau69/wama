# GENERALIZATION_PLAN.md — Masterplan d'uniformisation des apps WAMA

> **But** : ne perdre aucun axe de vue. L'uniformisation est **multi-axes** ; le contrat backend
> (modèles) n'en est qu'un. **App de référence full-stack : Transcriber.** Cible : un modèle d'app
> **métadonnée-driven** — chaque app = une *déclaration* (capacités + catalogue + contrat backend +
> prompt targets + scénarios de test) + un minimum de code spécifique ; la couche **commune** consomme
> ces déclarations.
>
> Docs détaillés : [`COMMON_REFACTORING.md`](COMMON_REFACTORING.md) (briques + recette),
> [`BACKEND_CARTOGRAPHY.md`](BACKEND_CARTOGRAPHY.md) (contrat backend),
> [`WAMA_APP_CONVENTIONS.md`](WAMA_APP_CONVENTIONS.md) (conventions UI + §22 volet droit),
> [`PROMPT_PIPELINE.md`](PROMPT_PIPELINE.md). État chantiers : [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

## Les axes et leur état (mesuré 2026-06-24)

| Axe | Brique de référence | État | Reste |
|-----|---------------------|------|-------|
| **A. Coque applicative** | `common/templates/common/app_modern_base.html` | ✅ 10/10 apps l'étendent | piloter specs par capacités d'app |
| **B. File + batch** | briques `_card_*/_new_item_card/_queue_actions`, batch universel, `batch-import.js`, `queue_duplication` ; **formalisme de card = [`CARD_DESIGN.md`](CARD_DESIGN.md)** (réf = converter `_job_card.html`) | ⚠️ fonctionnel partout mais **briques communes = transcriber seul** ; formalisme card figé (converter=réf) | **plus gros reste** : refondre les files sur les briques + card commune server-rendered |
| **C. Inspecteur volet droit** | `wama-inspector.js` (sélection item/batch/global) + form éditable (§10/§22) + `wama-inspector-autofill.js` | ⚠️ transcriber + catalogues (model_manager,/apps) | brancher l'inspecteur **éditable** par app |
| **D. Plomberie JS** | `wama-app-base.js` (`WamaApp`: Poller, csrfFetch, escapeHtml…) | ❌ transcriber seul | substrat à diffuser |
| **E. Progression + ETA** | `_global_progress.html` + `wama-eta.js` | ✅ 10/10 apps | RAS |
| **F. Chargement/déchargement modèles** | `common/backends/base.py::BaseModelBackend` + `manager.py::BackendManager` + `select_model` + deps | ✅ **fondation complète** (contrat + manager commun + hook install + 5 apps) | rollout : adoption par app + tests génériques |
| **G. Pipeline de prompts** | `common/utils/app_metadata.py::PROMPT_TARGETS` | 🔄 partiel | étendre |
| **H. Tests fonctionnels nocturnes** | `common/services/nightly_tests.py` | 🔄 charpente + 2 gabarits ; **dépend de F** | scénarios par app → 1 générique |
| **I. Capacités d'app** | déclaration (`has_realtime`, `instant_preview`, `has_edit_page`, `batch_type`, types E/S…) dans `APP_CATALOG`/metadata | 🔄 amorcé | **le liant** : formaliser pour piloter A→H |

Légende : ✅ large · 🔄 en cours · ⚠️ extrait mais peu adopté · ❌ non diffusé.

## Lecture stratégique
- **A et E déjà larges** → bonne base.
- **B, C, D ne vivent que dans le Transcriber** : les 9 autres apps **fonctionnent** (files, duplication,
  etc.) mais avec **leur propre markup/JS** → pas homogènes ni métadonnée-driven. Travail = **refactoring**
  vers les briques communes, pas ajout de features.
- **F (modèles) est indépendant des axes UI** → menable en parallèle.

## Séquencement recommandé
1. **Fondations transverses** (substrat consommé par tous) : **D** (`wama-app-base.js`), **F** (contrat
   backend), **I** (capacités d'app).
2. **Conformance par app** ensuite (et non axe-par-axe en surface) : pour chaque app, brancher **B+C+D**
   en une passe → app pleinement conforme, validable de bout en bout (et testable via **H**).
3. **A/E** = acquis ; **G** au fil de l'eau.

## Où on en est (curseur)
- **F = fondation COMPLÈTE** : `BaseModelBackend` + **manager commun** `BackendManager` + **hook installeur**
  (`ensure_backend_deps`/`pip_install_packages` = boucle prospection) + **5 apps conformes** (transcriber
  réf, imager, enhancer, reader, composer ; archétypes ABC/stateful/stateless). Hors-contrat assumés :
  GlmOcr, describer. À wrapper pendant leur passe UI : anonymizer (⚠️ intouché — Cam Analyzer réutilise
  ses modèles), synthesizer. **Reste F = rollout** (adoption manager par app + tests `model_loaded`
  génériques), pas fondation. Détail : `BACKEND_CARTOGRAPHY.md`.
- **Prochaine bascule UI** : prendre **enhancer** (déjà conforme côté F) comme 2ᵉ référence full-stack
  pour prouver **B+C+D** hors transcriber.

## Principe unificateur
Tout converge vers **I (capacités d'app)** : une fois les capacités déclarées, l'UI (A/B/C), les tests
(H), l'inspecteur (C) et la sélection de modèle (F) se **génèrent** depuis les métadonnées — même logique
que l'inspecteur passé de HTML-par-app à schéma `WamaDetails`.
