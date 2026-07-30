---
name: port-app
description: Porter une app WAMA vers le standard schéma-driven (uniformisation) en suivant la route F1-F8 et les briques communes existantes. Utiliser quand l'utilisateur demande de porter/uniformiser une app (reader, converter, enhancer, anonymizer, synthesizer, imager, avatarizer…).
---

# /port-app — Portage d'une app vers le standard commun

Objectif : ZÉRO réinvention. Tout ce dont un port a besoin existe déjà en brique commune ; le
travail est de CONSOMMER, pas de créer. Route d'ensemble : `WAMA_APP_GENERATION_ROUTE.md` (F1–F8).

> ⚠️ **La route n'est PAS auto-suffisante** : chaque domaine a son document de référence, et une
> facette qui ne pointe pas vers le sien laisse un trou. Vécu le 2026-07-30 : une session a
> réinventé un vocabulaire de capacités (`t2i`/`t2v`/`i2v`) parce que `INPUT_MODEL_MATCHING.md`
> n'était cité nulle part dans la route. **Si le domaine que tu touches figure ci-dessous, son
> document se lit AVANT le code — pas la peine de « voir d'abord ».**

## 0. Avant de commencer (obligatoire)

- 🔴 **`wama/common/README.md` = L'INVENTAIRE DES BRIQUES + LA RECETTE + LES PIÈGES.** À lire en
  premier, avant même la route : c'est le seul document qui liste les briques réellement
  disponibles avec leur API. Ne pas écrire une ligne avant d'y avoir cherché la brique.
- 🔴 **LE SCORE /40 NE MESURE PAS TOUT LE PORTAGE.** La grille `check_app_conformity` couvre
  **F1:3 · F2:5 · F3:6 · F4:1 · F5:25 — et F6/F7/F8 : ZÉRO critère** (mesuré 2026-07-30). Sont
  donc **invisibles au score** : contrat `BaseModelBackend`, déclaration VRAM, tirage
  `select_model`, capacités canoniques, `WamaInputMatch`, `WamaModelCaps`, enrichissement de
  prompt, navette, ETA… Une app peut gagner beaucoup sans bouger d'un point, et inversement.
  **Le score sert à repérer les régressions F1–F5, pas à déclarer un portage terminé** — pour ça,
  c'est l'inventaire de `common/README.md` qui fait foi.
- Lire la section de l'app dans `PROJECT_STATUS.md` (§20bis/§21/§31…) + l'état live `/apps/`
  (`get_conformity_summary`) — ne PAS se fier aux tables figées.
- Relire `WAMA_APP_GENERATION_ROUTE.md` pour la facette qu'on touche, et la recette des ports
  précédents (Transcriber/Composer/Describer/Reader/Converter = 5 apps déjà portées).
- **Documents de domaine — lire celui qui correspond au chantier :**

  | Tu touches… | Lire AVANT de coder |
  |---|---|
  | modèles, capacités, tirage, entrées acceptées | **`INPUT_MODEL_MATCHING.md`** + `common/utils/model_capabilities.py::CANONICAL_CAPABILITIES` |
  | chargement/déchargement d'un modèle, VRAM | `ROADMAP.md` §Gouvernance des ressources + `common/backends/base.py` |
  | prompts (traduction, enrichissement) | `PROMPT_PIPELINE.md` |
  | manifestes | `WAMA_MANIFEST_SPEC.md` + `WAMA_MANIFEST_ARCHITECTURE.md` |
  | conventions UI / boutons / file | `WAMA_APP_CONVENTIONS.md` |

- **Briques JS communes — les chercher, pas les réécrire** (`common/static/common/js/`, 24 à ce
  jour) : `wama-app-base` · `wama-params` · `wama-inspector` (+`-autofill`) · `wama-modes` ·
  `wama-model-help` · `wama-model-caps` · `wama-input-match` · `wama-new-item-card` ·
  `wama-cycle-button` · `wama-eta` · `wama-global-progress` · `wama-queue` · `queue-actions` ·
  `batch-import` · `wama-prompt-enrich` · `wama-prompt-chips` · `wama-shuttle` · `media-picker` ·
  `media-preview` · `wama-audio-player` · `wama-fm-notify` · `console` · `system-stats`.
  ⚠️ Avoir la card commune ne suffit pas : mesuré le 30/07, **8 apps incluent
  `_new_item_card.html` mais une seule charge `wama-input-match.js`**. Support ≠ adoption.

- **Le tirage « auto » se résout AU LANCEMENT, jamais au dépôt.** Il lit la VRAM libre ; entre la
  mise en file et l'exécution, plusieurs minutes peuvent passer. La vue ENREGISTRE `'auto'`, la
  tâche résout (`composer/tasks.py:50`, `imager/utils/auto_model.py`). Et vérifier qu'une option
  « Auto » existe vraiment dans le `<select>` : sans elle le formulaire poste toujours un modèle
  explicite et le tirage ne se déclenche **jamais** (cas vécu sur l'imager le 30/07).

- **Règle de vocabulaire** : avant d'introduire une clé, un drapeau ou un nom de fonction,
  chercher s'il existe déjà (`grep` du vocabulaire canonique). Un nom de fonction ne doit JAMAIS
  porter un type de média (`video_models_from_manifest` ⇒ faux ; `get_registry_models(modality=…)`
  ⇒ juste) : ce qui est typé dans le nom ne sera jamais réutilisé par une autre app.
- Périmètre : UNE app à la fois, finir à 100 % plutôt que porter partout avec des trous
  (recadrage Fabien 2026-07-02).

## 1. Ordre de port éprouvé (recette des 5 premiers)
1. Tri/filtre + toolbar : `common/utils/queue_view.py` + `_queue_toolbar.html`.
2. Card d'entrée `_new_item_card` en tête (ordre canonique : card → progression → toolbar → file) ;
   URL via `WAMA_INGEST` sur le modèle + `ensure_local_input()` (`common/utils/source_ingest.py`).
3. Card = partial serveur unique + endpoint `card_html` + `refreshCard` (⚠ RE-BIND des events par
   card après re-rendu — leçon describer).
4. Card mère batch = brique `_batch_card.html` + `build_batches_list()` (`batch_common.py`).
5. Anti-race : `begin_processing()` (`process_control.py`) sur start/start_all/batch_start ;
   réconciliation orphelins : `reconcile_orphaned_running` dans l'IndexView.
6. Manipulation directe : fabrique `queue_manipulation.py` (4 vues).
7. Modales : `WamaParams.render(context:'item')` — JAMAIS de modal hand-built ; NE PAS retirer
   les modales ⚙ (chemin d'édition du mode simplifié).
8. Inspecteur : `register_app_preview` + `register_app_detail` (adapters `apps.py`) +
   `initFromSchema` ; contrat `.wama-card`.
9. ETA : `eta_estimator` + `WamaEta` ; temps réel persisté `ProcessingTimeMixin`.
10. Réglages user : `user_settings.py` ; toasts : `WamaApp.toast` (jamais alert()).

## 2. Pièges récurrents (chacun a déjà coûté une session)
- `{# #}` multi-ligne Django PAS strippé → toujours `{% comment %}`.
- JS/CSS modifiés → copier `wama/<app>/static/` → `staticfiles/<app>/`.
- Migrations : `manage.py migrate` DES DEUX côtés (WSL2 live + Windows copie).
- Python runtime modifié → restart process WSL2 requis (le signaler).
- Capacités UI : le MODÈLE déclare (`capabilities`), jamais de `show_if` hardcodé.
- Ne PAS adapter le studio à l'app : finir le port, pas écrire de colle (contrat uniforme).

## 3. Clôture
- Checklist 18 points : `TRANSCRIBER_REFERENCE_AUDIT.md §6` + vérif `/apps/`.
- Validation empirique : `manage.py check` (venv WSL), page 200, endpoints unifiés ; si Playwright
  MCP disponible → `/smoke` sur les parcours de l'app.
- Consigner via `/palier` (PROJECT_STATUS + ROUTE si une facette a bougé).
