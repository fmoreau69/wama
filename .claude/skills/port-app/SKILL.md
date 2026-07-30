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
