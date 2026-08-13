# WAMA Common — la couche MANIFESTE (workflow de génération d'une app)

> **Ce document est LA référence du workflow d'auto-génération des applications généralistes.**
> Objectif final : une app = des **déclarations** (manifeste) → l'UI et les comportements sont
> **générés** par les briques communes — zéro hardcode par app, zéro divergence possible entre
> surfaces. Mis à jour le 2026-07-02 (audit empirique — cf. `UI_MECHANISMS_CONSOLIDATION.md`).
>
> **Règles cardinales (Fabien)** :
> 1. **Ne JAMAIS hardcoder une nouvelle implémentation dans une app** — si une brique manque,
>    on la crée dans `common/` d'abord, puis l'app la consomme.
> 2. **Finir quelques apps à 100 %** plutôt que porter partout avec des trous récurrents.
> 3. Toute divergence entre deux surfaces = un défaut de la **source** (schéma/catalogue),
>    jamais à rustiner dans la surface.

---

## 1. LA CHAÎNE DE GÉNÉRATION (vue d'ensemble)

```
DÉCLARATIONS (par app — le "manifeste")        AGRÉGATION (commune)             SURFACES GÉNÉRÉES
──────────────────────────────────────        ────────────────────             ─────────────────
A1 APP_CATALOG (common/app_registry.py) ───┬─→ /apps/ (app manager) ─────────→ nav, méta-app (studio),
   io types, batch, conventions, desc      │   get_conformity_summary()         validation upload
A2 APP_MODES (utils/app_modes.py) ─────────┼─→ WamaModes (JS) ───────────────→ onglets domaine + switch mode
A3 params.py (par app) ────────────────────┼─→ WamaParams.render(ctx) ───────→ champs MODALE (ctx 'item')
   Param: dom_id, show_if, options_source, │                                    champs VOLET (ctx 'panel')
   option_groups, help_source/fallback     ├─→ WamaInspector.initFromSchema ─→ câblage volet (read/apply/save)
A4 PROMPT_TARGETS (utils/app_metadata.py) ─┼─→ PromptPipeline ───────────────→ traduction/enrichissement/RAG
A5 tool_api.py (par app) ──────────────────┴─→ TOOL_REGISTRY ────────────────→ assistant IA, méta-app

B1 model_config.py / classes backend           (descriptions COURTE+LONGUE séparées,
   (déclaration des MODÈLES par app)            capacités canoniques, vram_gb, eta)
        │ découverte (_discover_<app>_models)
        ▼
B2 CATALOGUE AIModel (DB, model_manager) ──┬─→ WamaModelHelp ────────────────→ descriptif sous le select (+ ⓘ)
   = SOURCE UNIQUE DE LECTURE              ├─→ WamaModelCaps ────────────────→ options/champs selon capacités
   (sens : fichier → sync → DB → lecture)  ├─→ get_registry_models ──────────→ options des selects modèle
                                           └─→ model_selector / eta_estimator → sélection VRAM, ETA
```

**Le sens des flux est sacré** : les apps **déclarent** (fichiers) → le commun **agrège** → les
surfaces **se génèrent**. Une app ne lit jamais ses fichiers locaux pour afficher des méta-modèles :
elle lit le **catalogue**.

---

## 2. Inventaire des briques communes (vérifié 2026-07-02)

### Schéma & rendu des paramètres
| Brique | Fichier | Rôle |
|---|---|---|
| `Param` / `derive_from_model` | `utils/param_schema.py` | schéma déclaratif (dérivé du modèle Django + overrides UI) |
| `WamaParams.render(host, schema, {context, values, optionsResolver})` | `static/common/js/wama-params.js` | **génère les champs** : toggle/select/radio/text/textarea/number/range (avec bornes min/max), optgroups, `show_if`, aide modèle |
| `WamaParams.renderSettingsModal({…})` | idem | **génère la coquille** de modale per-item (pattern enhancer/reader) |
| `WamaParams.settingsModal({…})` | idem | **ORCHESTRE le cycle complet** d'une modale d'item : charger les valeurs → rendre (schéma + groupes) → greffer le pied (`footerTplId`) → afficher → lire → POST → toaster → enchaîner. Hooks d'app : `decorate(host,data)`, `collect(fd,host,data,restart)`, `onSaved(id,restart,resp)`, `errorOf(resp)`. Adoptée par anonymizer + imager (2026-08-06) ; **à porter aux autres apps** (elles réécrivent encore ce cycle). Délégation liée à LA MODALE, pas au document → pas d'accumulation de listeners à la réouverture |
| `ParamGroup` / `Param.group` / `Param.pills` / `columns` | `utils/param_schema.py` + `wama-params.js` | **sections déclarées** d'une surface de saisie (titre, icône, `show_if` de groupe, `collapsed`, 2 colonnes) ; `advanced` sans groupe → repli « Avancé » automatique. Les champs `advanced` AVEC groupe restent visibles dans leur section |
| `WamaInspector.init` / `initFromSchema` | `static/common/js/wama-inspector.js` | **câble** le volet : sélection card, read/apply dérivés du schéma, save |
| `_settings_modal_footer.html` | `templates/common/` | **pied de modale conforme** — Annuler / Enregistrer / Enregistrer & démarrer (+ slot gauche) ; convention `WAMA_APP_CONVENTIONS.md §6.5` (ex-MODAL_ACTIONS_AUDIT, archivé) |
| `_inspector_banner.html`, `_inspector_actions.html` | `templates/common/` | coquille du volet inspecteur |

### Modes & domaines
| Brique | Fichier | Rôle |
|---|---|---|
| `APP_MODES` + `WamaModes` | `utils/app_modes.py` + `wama-modes.js` | onglets domaine + switch mode **générés**. Un MODE se déclare ICI, jamais en HTML par app. Critère : un mode existe si le **comportement** diverge (entrées/réglages différents) — pas comme taxonomie de modèles (ça = `capabilities.task` + optgroups/filtre d'options). |

### Méta-modèles (catalogue)
| Brique | Fichier | Rôle |
|---|---|---|
| `AIModel` + sync | `model_manager/` | catalogue central. `description_short` (sous le select, **SANS VRAM**) + `description` (longue, overlay ⓘ) = **2 champs SÉPARÉS** (format transcriber). `capabilities` canoniques (`common/utils/model_capabilities.py`). **La VRAM vient TOUJOURS de `vram_gb`** (appendée par le JS). ETA a-priori dans `extra_info['eta']`. |
| `WamaModelHelp` | `wama-model-help.js` | descriptif modèle : `.init({selectId, helpId, meta, fallback})` ou `.fetchCatalogMeta(source)` (clés = id **nu**, préfixe retiré) |
| `WamaModelCaps` | `wama-model-caps.js` | filtre les options selon les capacités du modèle sélectionné |
| `get_voice_groups(user)` | `utils/voice_options.py` | groupes de voix per-user (format `optionsResolver`) — synthesizer + avatarizer |

### File / cards / entrées
| Brique | Fichier | Rôle |
|---|---|---|
| `_new_item_card.html` | `templates/common/` | **card d'entrée générée** : drop, URL/YouTube, batch, médiathèque (`show_media_library`), temps réel (`show_live`), **fichier de référence** (`show_reference` : chip retirable ✕ + zone requis/suggéré + ligne d'état). |
| `WamaInputMatch` | `static/common/js/wama-input-match.js` | **appariement entrées ⇄ modèles** (`INPUT_MODEL_MATCHING.md`) : entrée fournie → modèles incompatibles **grisés + raison** (jamais cachés), bascule auto, réversible par chip ; modèle choisi → slots requis (ambre, lancement gaté) / suggérés (info). Déclaratif : `capabilities.inputs_required/optional` (catalogue) + `INPUT_TYPES`. Pilote : composer (mélodie Melody). |
| `WamaFolderImport` | `static/common/js/wama-folder-import.js` (GLOBAL, base.html) | **import de DOSSIER récursif** (F2 `recursive_import`) — extraite du filemanager 2026-08-13 : `collect(dataTransfer)` (drop mixte fichiers/dossiers, `webkitGetAsEntry` + batching `readEntries`), `fromInput(fileList)` (input `webkitdirectory`), `files(liste)`. Adoption = 2 lignes dans le handler de drop + `folder_input_id=` sur `_new_item_card.html` (lien « importer un dossier »). Consommé : filemanager + 9 apps (slots mono-fichier avatarizer/imager = drop récursif sans lien dossier) ; composer non adopté (prompt-primaire, candidat N/A). |
| `wama-queue.js`, `_queue_actions.html`, `_card_progress.html`, `_card_state.html`, `_cycle_button.html` | | file (batch collapse), actions de file, barres de progression, **bouton cycle ▶/⏹/↻** (toujours VERT, seule l'icône change) |
| Recette « card rendue SERVEUR » | | LA règle card (CARD_DESIGN) : partial d'app (`_transcript_card` / `_generation_card` / `_description_card`) = SOURCE UNIQUE du markup + endpoint `<app>:card_html` + `refreshCard(id)` JS (remplace/insère + **re-bind si events par card**). Tue les rebuilds JS divergents. Consommé : transcriber, composer, describer (2026-07-04/05). |
| Parseur batch UNIFIÉ (superset) | `utils/batch_parsers.py` | 3 syntaxes auto-détectées : balises CLI (-i/-p/-r/-o/--option), tableur à EN-TÊTES (délimiteur sniffé , ; \| tab + alias FR modele/duree/voix…), positionnel hérité. + `build_batch_template(fields, example)` = template téléchargeable GÉNÉRÉ de la déclaration (A5-23). |
| `_queue_toolbar.html` + `utils/queue_view.py` | | **barre d'outils de file** : tri + filtre par statut (`apply_queue_sort_filter(request, batches_list, name_of=…)`, persistés en session — clés PARTAGÉES entre apps) + toggle Ligne/Mosaïque + `_queue_actions` (option `download_url` = lien ZIP direct). Contrat : entries avec `success/running/failure_count`. Consommé : transcriber, composer. |
| CSS mosaïque commun | `static/common/css/wama-inspector.css` | **contrat `.wama-card`** sur la racine de TOUTE card (individuelle, mère `.is-batch`, fille) ; filles = enfants **DIRECTS** du `.collapse[data-wama-batch-key]`. Fournit : grille, solitaire (batch replié = cellule, déplié = pleine largeur), **empilement vertical des `.row` internes** (sinon compression horizontale), fan-in, `.wama-layout-btn.active`, look pointillés `.wama-new-item-card`. |
| `wama-new-item-card.js` | `static/common/js/` | card d'entrée **DÉPLIABLE** (mécanisme synthesizer globalisé ; 1ʳᵉ étape vers la card miniaturisée en file) : `_new_item_card collapsible=True` → en-tête+prompt+bouton primaire visibles, zone médiane d'import repliée ; dépliage clic/focus/drag. Auto-init (`data-wama-nic`). Consommé : composer. |
| Compteur d'items sur l'ONGLET | `app_modern_base.html` | badge `#queueCount` sur l'onglet « File d'attente » (rendu si la vue passe `queue_count`) — remplace le titre doublon dans l'onglet. Ordre d'onglet canonique : card d'entrée → progression globale → `_queue_toolbar` → file. |
| `_global_progress.html` + `wama-eta.js` (+ `eta_estimator` serveur) | | barre globale + moteur ETA — **jamais d'ETA par app** |
| `queue_duplication.py`, `batch_parsers.py`, `batch_import.js`, `media-picker.js` (chargé globalement) | `utils/`, `static/` | duplication/suppression sûres, imports batch, médiathèque |
| `output_format_params_for_app` | `utils/output_formats.py` | params format/qualité de sortie (domaine + early/late binding déduits d'APP_CATALOG) |
| Réception « Envoyer vers app » | `static/common/js/wama-app-base.js` | listener `wama:fileimported` **GÉNÉRIQUE** (2026-07-31) : cible l'app via `window.WAMA_CURRENT_APP` (posé par `base.html` depuis `APP_CATALOG`). Il était recopié à l'identique dans **7 apps**, dont 3 l'avaient oublié. Une app qui sait intégrer l'item SANS recharger (reader : insertion de card) pose `detail.handled = true` ; le repli commun est reporté d'un tick pour rendre cette échappatoire possible. |

### Reclaim VRAM (une SEULE mécanique — 2026-07-31)
| Brique | Fichier | Rôle |
|---|---|---|
| Registre d'instances RÉSIDENTES | `backends/base.py` (`_LIVE_BACKENDS`, `unload_app_backends`) | `BaseModelBackend` enveloppe déjà `load`/`unload` à **toute profondeur d'héritage** : il tient donc un `WeakSet` des backends chargés et **enregistre l'unloader de l'app à la première résidence réelle**. Une app sous contrat n'a **rien à déclarer**. |
| `register_vram_unloader(name, fn)` | `model_manager/services/memory_manager.py` | déclaration EXPLICITE, réservée à ce qui échappe au contrat de backend : modèle en variable de module (describer/BLIP), pipeline caché (transcriber/pyannote). Plusieurs unloaders par app admis (`<app>` + `<app>-suffixe`). |
| `vram_reservation(owner, gb)` | `common/services/resource_governor.py` | modèles **HORS PROCESS** (sous-processus) — l'héritage ne s'y applique pas, rien n'est résident dans le worker. Adopté : avatarizer. |

> ⚠ **Deux `release_vram` homonymes, sémantiques opposées** — ne pas les confondre :
> `resource_governor.release_vram(owner)` efface une ligne de **comptabilité** Redis ;
> `MemoryManager.release_vram(exclude)` **décharge réellement** les modèles via le registre.
> Les unloaders codés en dur par app (`_unload_<app>_model`) ont été SUPPRIMÉS : ils formaient une
> seconde liste à tenir à jour, et trois d'entre eux (anonymizer, synthesizer, enhancer) faisaient
> un `gc.collect()` puis retournaient `True` — succès annoncé, VRAM non libérée, indétectable.

### Pilier prompts (JAMAIS par app)
`PROMPT_TARGETS` (déclaration) → `prompt_pipeline.py` (orchestre) → `lang_routing.py` (décide via
`capabilities['languages']`) → `translator.py` / `prompt_enrichment.py` / `reference_comprehension.py`
(+ point de branchement RAG). Voir `PROMPT_PIPELINE.md`.

### Briques historiques (toujours valides)
`app_base.html` — blocs : `title`, `extra_scripts`, `app_scripts`, `console_content_id`,
`console_hint_id`, `console_url`, `app_menu`, `app_content`. · `console.js` (auto-détection
`data-console-url`, refresh 4 s) · `console_utils.py` (`push_console_line`, `get_console_lines`,
`get_celery_worker_logs`) · `media_paths.py` (`upload_to_user_input/output`).

---

## 3. LA RECETTE de portage d'une app (checklist — rodée sur composer/avatarizer)

1. **`params.py`** : chaque param en contexte `("panel","item")` avec `dom_id` = **IDs legacy** des
   deux surfaces → le JS existant (fill/save) marche inchangé. Options dynamiques :
   `options_source` + `optionsResolver` fourni par la vue (per-user) — **jamais d'`<option>`
   hardcodées** dans un template.
2. **Modale** : champs hand-built → host `<div class="wama-params">` + `WamaParams.render(host,
   schema, {context:'item'})`. Coquille per-item → `renderSettingsModal`. **Pied** →
   `{% include 'common/_settings_modal_footer.html' with save_id=… %}`.
3. **Volet (P2)** : mêmes champs via `render(…, {context:'panel'})`, après **enrichissement du
   schéma** (placeholder, aides, formats/unités, `help_source`) pour que les deux surfaces
   héritent des mêmes richesses — la divergence devient impossible par construction.
4. **Endpoint save** : flag `restart` — « Enregistrer » sauve **sans** purger la sortie ni
   relancer ; « Enregistrer & relancer/démarrer » = comportement re-run.
5. **Descriptif modèle** : `WamaModelHelp` + meta du **catalogue** (jamais de texte local).
6. **Vérifications** : schéma (contexts/dom_id/choices), templates compilent, équilibre JS,
   **staticfiles copiés**, puis **test humain navigateur** (node absent de l'env).

---

## 4. PIÈGES connus (tous rencontrés en vrai — ne pas les répéter)

- **`{# … #}` multi-ligne n'est PAS strippé par Django** → nœud texte visible dans la page.
  Multi-ligne = `{% comment %}…{% endcomment %}`. (Récidivé 3× — vérifier CHAQUE commentaire.)
- **L'app charge-t-elle `wama-params.js` ?** (composer ne l'avait pas → modale vide, garde muet).
  Toujours un garde **bruyant** : `console.warn('[app] WamaParams absent…')`.
- **Nouvelle variable de contexte** = redémarrage serveur requis ; protéger le JS inline par
  `|default:"[]"` sinon `var x = ;` **tue tout le script** (modale vide).
- **Process WSL2** : toute modif Python (vues, registre, sync) → **redémarrer le serveur** —
  l'ancien code en mémoire peut **réécrire des données périmées** au prochain sync/refresh.
- **Statics** : toute modif `wama/<app>/static/` ou `common/static/` → copier dans
  `staticfiles/…`.
- **Retraits de code : ancres EXACTES uniquement** — jamais de regex « jusqu'au prochain
  repère » (a emporté ~450 lignes sur composer ; récupérées par git).
- **Sliders générés** : après un `value=` programmatique, `dispatchEvent(new Event('input'))`
  pour synchroniser l'affichage de valeur.

---

## 5. Références détaillées
`UI_MECHANISMS_CONSOLIDATION.md` (sources de vérité + état par app) · `MODEL_META_UNIFICATION_KICKOFF.md`
(méta-modèles) · `REMOVAL_LEDGER.md` (résidus/corrections tracés R*/F*) · `WAMA_APP_CONVENTIONS.md §6.5` (pied de modale)
(conventions boutons) · `WAMA_APP_CONVENTIONS.md` (checklist app) · `COMMON_REFACTORING.md` ·
`MODES_QUEUE_UX.md` (doctrine modes/file/cards) · `CARD_DESIGN.md` · `PROMPT_PIPELINE.md` ·
`GENERALIZATION_PLAN.md` (trajectoire manifeste).
