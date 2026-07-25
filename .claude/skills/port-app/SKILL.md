---
name: port-app
description: Porter une app WAMA vers le standard schéma-driven (uniformisation) en suivant la route F1-F8 et les briques communes existantes. Utiliser quand l'utilisateur demande de porter/uniformiser une app (reader, converter, enhancer, anonymizer, synthesizer, imager, avatarizer…).
---

# /port-app — Portage d'une app vers le standard commun

Objectif : ZÉRO réinvention. Tout ce dont un port a besoin existe déjà en brique commune ; le
travail est de CONSOMMER, pas de créer. Référence unique : `WAMA_APP_GENERATION_ROUTE.md` (F1–F8).

## 0. Avant de commencer (obligatoire)
- Lire la section de l'app dans `PROJECT_STATUS.md` (§20bis/§21/§31…) + l'état live `/apps/`
  (`get_conformity_summary`) — ne PAS se fier aux tables figées.
- Relire `WAMA_APP_GENERATION_ROUTE.md` pour la facette qu'on touche, et la recette des ports
  précédents (Transcriber/Composer/Describer/Reader/Converter = 5 apps déjà portées).
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
