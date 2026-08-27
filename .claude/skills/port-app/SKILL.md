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
- 🔴 **LE SCORE NE MESURE PAS TOUT LE PORTAGE — mais il en mesure plus qu'on ne croit.**
  ⚠ Ce paragraphe a affirmé jusqu'au 2026-08-26 que « F6/F7/F8 : ZÉRO critère » et parlait d'un
  score « /40 ». **C'était faux depuis le 2026-07-30** : les 8 facettes sont couvertes (82
  critères le 26/08, dont F6:5 F7:5 F8:2), donc le contrat `BaseModelBackend`, la VRAM, le tirage
  `select_model`, les capacités canoniques, l'appariement entrée↔modèle, les prompts, les
  permissions et le nœud studio **sont mesurés**. Un skill qui déclare un mécanisme invisible
  invite la session suivante à le porter en aveugle — et à ne pas voir sa régression.
  Ce qui RESTE vrai : le score compte des **mécanismes détectés dans le code**, jamais des
  fonctionnalités finies. **Ne jamais déclarer un portage terminé sur le score seul** — pour ça,
  c'est l'inventaire de `common/README.md` qui fait foi. Chiffres à jour : `/conformite`.
- Lire la section de l'app dans `PROJECT_STATUS.md` (§20bis/§21/§31…) + l'état live `/apps/`
  (`get_conformity_summary`) — ne PAS se fier aux tables figées.
- Relire `WAMA_APP_GENERATION_ROUTE.md` pour la facette qu'on touche, et la recette des ports
  précédents. ⚠ **Les 10 apps sont portées** (97–100 % au 2026-08-26) : un « port » aujourd'hui
  est presque toujours un COMPLÉMENT sur une facette, pas une reprise à zéro. Vérifier ce qui
  manque RÉELLEMENT (`--app <nom> --verbose-ok`) avant d'ouvrir le chantier.
- **Documents de domaine — lire celui qui correspond au chantier :**

  | Tu touches… | Lire AVANT de coder |
  |---|---|
  | modèles, capacités, tirage, entrées acceptées | **`INPUT_MODEL_MATCHING.md`** + `common/utils/model_capabilities.py::CANONICAL_CAPABILITIES` |
  | chargement/déchargement d'un modèle, VRAM | `ROADMAP.md` §Gouvernance des ressources + `common/backends/base.py` |
  | prompts (traduction, enrichissement) | `WAMA_LLM.md` |
  | manifestes | `WAMA_MANIFEST_SPEC.md` + `WAMA_MANIFEST_ARCHITECTURE.md` |
  | conventions UI / boutons / file | `WAMA_APP_CONVENTIONS.md` |

- **Briques JS communes — les chercher, pas les réécrire.** ⚠ **Ne pas se fier à une liste
  recopiée** : celle qui figurait ici annonçait « 24 » en n'en nommant que 23, et il y en avait
  30 au 2026-08-26. La lister prend une seconde — `ls wama/common/static/common/js/` — et
  `WAMA_MECANISMES.md` dit lesquelles sont MORTES (`⚠ 0` consommateur), ce qu'aucune liste de
  noms ne dit.
  ⚠️ Avoir la brique ne suffit pas — **support ≠ adoption** : mesuré le 2026-08-26, **12 apps
  incluent `_new_item_card.html` et 8 chargent `wama-input-match.js`** (c'était 8 / 1 le 30/07 —
  l'écart se comble, il ne disparaît pas). Mesurer les DEUX côtés avant de conclure.

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
   **Tâche Celery d'item : brique `task_skeleton.run_item_task`** (A2a, 2026-08-12 — gardes,
   progress, chrono, statuts, ETA, console, notifications ; l'app ne fournit que sa glu
   `process(item, ctx)`). ⚠ les tâches d'ENRICHISSEMENT (analyze/enrich — ni statut ni
   progress) sont HORS contrat : ne pas les forcer dedans.
6. Manipulation directe : fabrique `queue_manipulation.py` (4 vues).
7. Modales : `WamaParams.render(context:'item')` — JAMAIS de modal hand-built ; NE PAS retirer
   les modales ⚙ (chemin d'édition du mode simplifié).
8. Inspecteur : `register_app_preview` + **`register_app_detail_spec` D'ABORD** (A3a — la
   registration en SPEC-donnée rend la facette `inspector` régénérable ; l'adapter code
   `register_app_detail` reste pour les logiques irréductibles) + `initFromSchema` ;
   contrat `.wama-card`. Un port qui adopte les briques 5+8 rend l'app jugeable par
   `app_regen_check` (strip-régénération, apps.py/urls.py compris).
9. ETA : `eta_estimator` + `WamaEta` ; temps réel persisté `ProcessingTimeMixin`.
10. Réglages user : `user_settings.py` ; toasts : `WamaApp.toast` (jamais alert()).
11. **Partage (F7, depuis 2026-07-31)** — mesuré par `shareable_models` + `scoped_reads` :
    `class Card(…, ScopedVisibility)` + `objects = ScopedManager()`, **ET IDEM SUR LE MODÈLE DE
    BATCH** (la file est bâtie à partir des batchs : une card partagée sans son batch n'apparaît
    pas), migration, puis chemins de LECTURE (progress/download/status) → `visible_or_404`
    (`common/utils/scoping.py`). Ce qui mute reste inchangé → lecture seule par construction.
    Détail : `PROFILES_PERMISSIONS §7.4bis`. **Ne pas porter à moitié** : une card visible dans la
    file mais qui 404 au clic est pire que pas de partage.
12. **Prompt (si l'app en a un)** : hériter de `PromptScoped` + déclarer
    `'model': '<app>.<Modèle>'` dans `PROMPT_TARGETS` + `apply_prompt_state()` dans la vue de
    sauvegarde = 3 lignes, le reste est générique (`WAMA_LLM.md`).
13. **Triade tool_api (`start_<app>`/`get_<app>_status`)** : entrée déclarative **`TRIAD_SPECS`**
    dans `tool_api.py` (A4, 2026-08-12 — fonctions CONSTRUITES à l'import par
    `_register_triads()`), pas de squelette recopié ; `add_to_<app>` reste de la glu. Une triade
    à VRAIE logique (routage, purge, clés spéciales — ex. transcriber) reste code main, assumée.

## 2. Pièges récurrents (chacun a déjà coûté une session)
- `{# #}` multi-ligne Django PAS strippé → toujours `{% comment %}`.
- JS/CSS modifiés → copier `wama/<app>/static/` → `staticfiles/<app>/`.
- Migrations : `manage.py migrate` DES DEUX côtés (WSL2 live + Windows copie).
- Python runtime modifié → restart process WSL2 requis (le signaler).
- Capacités UI : le MODÈLE déclare (`capabilities`), jamais de `show_if` hardcodé.
- Ne PAS adapter le studio à l'app : finir le port, pas écrire de colle (contrat uniforme).

## 3. Clôture
- Checklist de fin d'app : `TRANSCRIBER_REFERENCE_AUDIT.md §6` (le compte vit là-bas) + vérif `/apps/`.
- Validation empirique : `manage.py check` (venv WSL), page 200, endpoints unifiés ; si Playwright
  MCP disponible → `/smoke` sur les parcours de l'app.
- Consigner via `/palier` (PROJECT_STATUS + ROUTE si une facette a bougé).
