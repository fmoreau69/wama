# WAMA — Route vers l'auto-génération d'applications généralistes

> **CE DOCUMENT EST LA RÉFÉRENCE UNIQUE** de toute la chaîne menant à l'auto-génération d'apps
> généralistes (le côté « mécanismes réels » du tunnel). Il **remplace et consolide** 4 anciens docs,
> désormais dans `docs/archive/` : `UI_MECHANISMS_CONSOLIDATION.md`, `COMMON_REFACTORING.md`,
> `GENERALIZATION_PLAN.md`, `BACKEND_CARTOGRAPHY.md`. Ne plus créer de `.md` concurrent sur ce sujet
> (règle CLAUDE.md) — compléter CELUI-CI.
>
> **Chaînage avec les manifestes (manifeste ⟷ mécanismes)** — les 3 docs s'emboîtent, mêmes facettes F1–F8 :
> - **[`WAMA_MANIFEST_SPEC.md`](WAMA_MANIFEST_SPEC.md)** = ce que le manifeste **déclare** (schéma).
> - **[`WAMA_MANIFEST_ARCHITECTURE.md`](WAMA_MANIFEST_ARCHITECTURE.md)** = les **flux** (ingest/projection ;
>   §3 = la carte « facette → mécanisme »).
> - **CE doc** = la **réalité du terrain** : source de vérité, consommateurs, adoption, trous, `file:line`.
>
> **Légende d'état** : **[RÉEL]** vérifié dans le code · **[TR-ONLY]** brique existante non généralisée
> (souvent Transcriber) · **[VISÉ]** décrit/roadmap, pas implémenté. Confronté au code le **2026-07-22**
> (cartographie 5 traceurs). Les grilles de conformité SURESTIMENT — ce doc distingue déclaré de câblé.

---

## 0. Le diagnostic en une phrase

> **Les briques communes sont complètes et bien conçues, mais SOUS-ADOPTÉES ; l'identité d'une app est
> déclarée dans 4 registres tenus à la main que l'App Manager et les autres surfaces CONSOMMENT ; et
> `tool_api` est le pivot d'exécution partagé assistant⟷studio.** La convergence = faire du **manifeste
> `app` la source unique dont chacun (App Manager, studio, nav, assistant) tire ce dont il a besoin**, et
> des registres actuels des **projections** re-synchronisables.

Ce n'est donc PAS « deux sources qui se contredisent » : c'est **une source riche (APP_CATALOG + briques
communes) et des vues partielles/simplifiées (GENERIC_APPS, modales hand-built) à régénérer depuis elle**.

---

## 1. La carte des registres — « qui déclare, qui tire » (réponse à la question de fond)

**L'App Manager EXISTE** — c'est la surface qui gère/présente toutes les applications : `apps_catalog_view`
(`common/views.py:197` → `/apps/` → `common/apps.html`) + son API `api_apps` (`:170`), pilotée par
`APP_CATALOG` + `get_conformity_summary()` (live). **C'est un CONSOMMATEUR** : il lit les registres, il n'en
est pas la source. Ce qui manque n'est pas l'App Manager, mais **une source unique ÉCRIVABLE** que lui et les
autres surfaces tireraient — aujourd'hui l'identité + le câblage sont déclarés dans **4 registres tenus à la
main** (+ registration Django au runtime), que l'App Manager, le studio, la nav et l'assistant consomment
chacun de leur côté :

| Registre | Fichier:ligne | Déclare | Consommé par |
|---|---|---|---|
| `APP_CATALOG` | `common/app_registry.py:345` | identité, `input/output_types`, `input_extensions`, drapeaux batch, matrice `conventions` | **App Manager** (`/apps/` `common/views.py:197`), nav, `studio_node_ports`, manifeste, filemanager |
| `APP_MODES` / `INPUT_TYPES` | `common/utils/app_modes.py:43` / `:19` | domaines→modes→inputs typés, **ports de référence** | `studio_node_ports` (ports `reference` seulement), 5 apps |
| `GENERIC_APPS` | `studio/services/generic_runner.py:28` | contrat d'exécution studio : `primary_input`/`input_kinds`, pointeur `params_module/attr`, `output_type`, câblage runner | `build_generic_runner`, studio |
| `CONVERTER_OUTPUT_FORMATS` | `converter/utils/format_router.py` (ré-exporté `app_registry.py:800`) | formats de fichier de sortie par domaine | `output_formats.py`, apps early-binding |
| `AIModel` (DB) | `model_manager/models.py:49` | catalogue modèles + `capabilities` JSON | `select_model`, `WamaModelCaps`, découverte |
| **Modèle Django d'app** | `wama/<app>/models.py` | l'item (spine : user/status/task_id/progress…) | lié au runtime via `Detail/PreviewRegistry` dans `apps.py::ready()` |

**Points clés de la carte :**
- **`studio_node_ports()`** (`app_registry.py:127`) = **l'accesseur UNIQUE de ports** : construit les ports
  `travail`/`prompt` depuis `APP_CATALOG.input/output_types`, PUIS relit `APP_MODES` **uniquement** pour
  ajouter les ports `reference` (`:152-168`). C'est le point de jonction card⟷nœud⟷preview.
- **`GENERIC_APPS` re-déclare les E/S à la main** au lieu de les dériver d'`APP_CATALOG` → **redondance
  réelle** (déjà instrumentée : `manifests/projection.py` diffe les deux). Mais elle porte AUSSI des champs
  qu'`APP_CATALOG` n'a pas (`params_module/attr`, `input_kwarg`, `fixed_kwargs`, `auto_start`) = **câblage
  runner, PAS de la redondance** → à préserver.
- **`INSTALLED_APPS`** (`settings.py:259`) = liste plate hand-maintenue, disjointe des registres.
- **Le manifeste `app`** (`manifests/builtin/app.py:74`) **agrège DÉJÀ les 4 registres + Django** en un body
  12 facettes (extract-only). C'est la brique de convergence — reste le write-back (code-gen).

---

## 2–9. La route, facette par facette (alignée 1:1 sur le manifeste)

Pour chaque facette : **source de vérité** · **adoption réelle** · **trous/redondances** · **chaînage
manifeste** (ce que le kind `app` capte + cible de projection).

### F1 — Identité & enregistrement  ⟷ `SPEC §F1`
- **Source** : `APP_CATALOG` (`app_registry.py:345`). `color` = **DÉRIVÉ** (HSL par catégorie,
  `_assign_derived_colors:845`), pas déclaré. `description_long` fusionné à l'import (`:908`).
- **Trous** : la matrice `conventions` (`_conv:181`) **dérive** (flags périmés corrigés en commentaires) —
  la source vivante est `get_conformity_summary()` (`:863`), pas les listes figées.
- **Manifeste** : capté (`app.py:86-92`). ⚠ garder `color` marqué *dérivé* (projection, pas donnée saisie).

### F2 — Ports, typage E/S & capacités  ⟷ `SPEC §F2` (règle preview)
- **Source ports** : `studio_node_ports()` (accesseur unique). **Source typage sortie** (chaîne RÉELLE, PAS
  un trou) : `output_types`(APP_CATALOG) → `_domain_from_output_types` → `get_output_formats()` réutilise
  `CONVERTER_OUTPUT_FORMATS` → `output_format_params_for_app()` injecte les Param format/qualité **seulement
  si `export_binding='early'`** (`output_formats.py:90`), sinon choix au téléchargement (late). **Converter =
  source unique** des formats.
- **Redondance** : `GENERIC_APPS.input_kinds/output_type` redéclare l'E/S ; sentinelle `'auto'` propre au
  studio (absente d'APP_CATALOG). `derive_io_from_ports()` (`projection.py:80`) prouve la reconstructibilité.
- **Manifeste** : ports captés via l'accesseur unique ; **typage de sortie = CAPACITÉ** (`export_binding`
  early/late), les formats restent au converter. **Cible : GENERIC_APPS devient projection des ports.**

**DÉCISION 2026-07-22 (Fabien) — DOMAINE vs MODE (deux affordances UI distinctes) :**
- **DOMAINE = onglets** : bifurcation de *but* (imager : Images/Vidéos ; enhancer : Image-Vidéo/Audio).
  Déclaratif, en tête, persistant. Reste un **hint UI minimal** (onglets oui/non + labels), le contenu étant
  dérivable de la modalité du modèle.
- **MODE = boutons de switch dans l'inspecteur** : affinage des capacités **DÉRIVÉ du modèle sélectionné**
  (référence : anonymizer yolo/SAM3). **N'est PAS déclaré** — généré par `WamaModelCaps` + `show_if`.
- **`APP_MODES` (registre hand-maintained) SE DISSOUT dans les capacités** : le domaine devient un hint,
  le mode devient une projection des capacités-modèle. Verdicts par app :
  | app | domaine (onglets) | mode (switch) | action |
  |---|---|---|---|
  | imager | Images / Vidéos | dérivé modèle | garder domaine (hint) |
  | enhancer | Image-Vidéo / Audio | dérivé modèle | garder domaine (hint) |
  | anonymizer | — | yolo / SAM3 (dérivé) | **refactor** : sélecteur de modèle groupé + switch capacités |
  | avatarizer | — | — | **sortir du mécanisme** : rapide/qualité = simple paramètre |
  | composer | — | — (optionnel switch dérivé) | **sortir** : music/bruitage = MAJ UI auto par sélection modèle |
  Principe : **but qui change → domaine/onglet ; mêmes but, contrôles qui changent → mode/switch dérivé.**

### F3 — Paramètres & UI générée  ⟷ `SPEC §F3`
- **Source** : `params.py` `PARAMS_JSON` (dataclass `Param`, `param_schema.py:24`), **une seule source
  déclarative, 10/10 apps l'ont**. `coerce_params()` (`:147`) = validation serveur (bornes = le schéma).
- **Renderer commun** : `WamaParams` (`wama-params.js`) rend item/panel ; **MAIS** :
  - **modale batch JAMAIS rendue** par WamaParams (0 `context:'batch'`) → hand-built partout.
  - le **studio a son PROPRE renderer** `renderNodeParams` (`wama-studio.js:348`) **appauvri** (pas de
    toggle/range/radio/show_if/advanced) — réinvention à supprimer (doit appeler WamaParams).
- **Adoption réelle** (le vrai déficit) :

  | Surface | Câblée sur | Reste |
  |---|---|---|
  | modale item (WamaParams) | converter, reader, enhancer (plein) ; transcriber, composer (partiel) | imager, synthesizer, describer, avatarizer, anonymizer = **hand-built** |
  | modale batch | — | **aucune** (toutes hand-built) |
  | chips métadonnée (`card_chips.py`) | **reader seul** | 9 apps |
  | `WamaModelCaps` (show_if depuis caps) | **synthesizer seul** | — |
  | corps de modale commun `_settings_modal.html` | **n'existe pas** (seul le pied est factorisé) | — |
- **Manifeste** : `params` capté (`app.py:203`) mais ⚠ **un seul `params_attr`** (rate les multi-schémas
  `IMAGE_+VIDEO_`, `MEDIA_+AUDIO_`) ; ne distingue pas **déclaré vs câblé** (c'est le round-trip qui le révèle).

### F3b — Inspecteur, preview & progression  ⟷ `SPEC §F3 (inspector)`
- **Inspecteur** : `DetailRegistry` + `build_detail` (dict canonique plat ; labels/sections en JS
  `DETAIL_SCHEMA`). **11 apps** enregistrées.
- **Preview** : `PreviewRegistry` + `unified_preview` ; **10/11** (imager exclu, décision documentée). Règle
  **entrée = port `travail` sinon `prompt`, JAMAIS `reference`** — **implémentée et vérifiée** via l'accesseur
  unique (`preview_utils.py:66-85`). Face sortie dérivée de l'adapter Detail (couplage Preview→Detail).
- **« PENDANT » (preview progressive)** : **backend entièrement câblé** (composer `emit_streaming_peaks`,
  capacité `during_preview=True` `app_registry.py:455`, face `?side=during`) **MAIS `media-preview.js` ne le
  consomme pas** → **maillon FRONTEND uniquement** (le worker publie une onde que rien n'affiche).
- **Filemanager** : **unifié** (réutilise `media-preview.js`), mais endpoint de données distinct.
- **ETA** : `WamaEta` (1 moteur, 3 niveaux carte/batch/global) + backend apprenant `eta_estimator` +
  `ModelRuntimeStat`. ~9 apps enregistrent `record_run` (reader/anonymizer = front sans apprentissage).
- **Manifeste** : inspector adapter (mapping champs→clés canoniques), preview binding sur port,
  capacité `during_preview/streaming`, profil ETA (unit + a-priori load/per_unit).

### F4 — Modèles IA  ⟷ `SPEC §F4`
- **Catalogue** = `AIModel` (source unique), `capabilities` JSON canonique (`CANONICAL_CAPABILITIES`,
  `model_capabilities.py:30`). **Découverte** : `_discover_<app>_models()` importe le `model_config.py` de
  l'app et construit les capabilities (`model_registry.py`). **Déclaration app** : `<APP>_MODELS` + `*_DIR`.
- **Tirage runtime** : `settings.MODEL_PATHS → *_DIR → HF_HUB_CACHE (avant import) → cache_dir → from_pretrained`
  (backends imager conformes CLAUDE.md) — **indépendant de `select_model()`**.
- **Sélection VRAM-aware** `select_model()` (`model_selector.py:66`) : **complète mais adoptée par composer
  SEUL (1/10)** (`auto_model.py:43`). anonymizer a **son propre** sélecteur (dupliqué) ; transcriber sa
  logique de priorité. Converter = **pas de modèle** (ffmpeg/pandoc) → `models: null` doit être toléré.
- **Redondances** : `ModelType`/`ModelSource` dupliqués (`models.py` + `model_registry.py`) ; capabilities
  canonicalisées dans la découverte, pas dans les `model_config` d'app.
- **Manifeste** : `models.{consumes, selection:{strategy: select_model|app_custom|fixed, requires, classes,
  priority, prefer_loaded}, paths_key, capabilities_vocab}`.
- **⚠ À réintégrer depuis l'archive** : le contrat `BaseModelBackend` (ex-`BACKEND_CARTOGRAPHY.md`) n'a pas
  été re-tracé en profondeur ici — pointeur `docs/archive/BACKEND_CARTOGRAPHY.md` en attendant sa fusion en F4.

### F5 — Traitement / cycle de vie  ⟷ `SPEC §F5`
- **Spine item** : `ProcessingTimeMixin` (`common/models.py:19`) + `BatchMixin` (`:43`). Champs communs de
  fait, mais **noms divergents** (`input_file` vs `audio`) et **`error_message` absent de transcriber**.
- **Statuts NON uniformes** [dette réelle] : converter contraint (`STATUS_CHOICES`) / transcriber **libre** /
  reader `DONE/ERROR` → réconciliés à l'affichage par **3 tables d'alias dupliquées** (`detail_registry.
  normalize_status`, `batch_common._ALIAS`, `wama-cycle-button.js stateFor`). Pas d'enum commune.
- **Task Celery** : `@shared_task`, **dual-write progress** (cache + `.update`), seeding ETA `record_run`.
  **`start` anti-race conforme** (transaction.atomic + select_for_update + revoke, `converter/views.py:243`).
- **Endpoints** : converter⟷transcriber **~80% de recouvrement**, nommage non aligné (`cancel`↔`stop`,
  `update`↔`save_settings`) + endpoints spécifiques déclarés (`edit`, `realtime`, `waveform_peaks`…).
- **Batch = 2 schémas** : FK directe (converter `ConversionJob.batch`) vs through-model (transcriber
  `BatchTranscript`+`BatchTranscriptItem`). Comportement unifié par `BatchMixin`, schéma non. Helpers communs
  `group_into_batches_by_nature()`, `duplicate_instance()`, `safe_delete_file()`.
- **Manifeste** : `processing.{item_model + noms de champs réels, statuses + flag normalisation, task/queue/
  progress pattern, batch:{kind:fk|through}, endpoints: socle standard vs spécifiques}`.

### F6 — Prompts/IA & tool_api  ⟷ `SPEC §F6`
- **Prompts** : `PROMPT_TARGETS` (`app_metadata.py:26`) source unique + `process_prompt_for()` + skills
  (`resolve_skill` : `<app>-<domain>` → `<app>` → `default-<kind>`). Adopté sur les apps génératives
  (imager/composer/anonymizer/cam_analyzer/assistant) ; synthesizer=`[]` (choix), describer interne.
- **tool_api = LE pivot** : triade normalisée `add_to_<app>`/`start_<app>`/`get_<app>_status` (`TOOL_REGISTRY`
  `tool_api.py:2050`). **Deux consommateurs du MÊME contrat** : l'assistant IA (`api/v1/views.py:18`) ET le
  studio (`build_generic_runner:149` fait `getattr(tool_api,f'add_to_{app}')` + filtre par
  `inspect.signature` + exige `item_id` en retour). **Le studio ne connaît aucune app en dur.**
- **Trous** : garde MEDIA_ROOT dupliquée ~8× ; **pas de test de contrat** sur la triade (bug describer
  output_format→output_style découvert au runtime) ; **à vérifier** : imager expose `create_image`, le runner
  appelle `add_to_imager` (alias à confirmer).
- **Manifeste** : `prompts.{targets, skills}` + `tool_api.{add,start,status,descriptions}`.

### F7 — Permissions & scope données  ⟷ `SPEC §F7`
- **Gating d'app** (`permissions.py`) : 2 axes **tier** (`TIER_ORDER`, bypass dev/admin) + **rôles** (Groups
  `role:*`). `AppAccessPolicy` DB (DEFAULT = seed). **Point de décision unique `accessible()`** appliqué :
  nav (complet), studio **palette** (oui). **TROU : le RUN d'un pipeline studio ne ré-applique PAS
  `accessible()` par nœud** (ownership garanti par tool_api, mais pas le gating d'app). Vues = décorateur
  `@app_access` au cas par cas (pas généralisé).
- **Scope données** (`ScopedVisibility` : private/project/unit/public + `OrgUnit`/`Project`) = **orthogonal**
  au gating d'app. Consommé par médiathèque, `UserFunction`, `Manifest` sandbox.
- **Manifeste** : `access.{roles,public,min_tier}` (lit la DB via `_policy_for`) ; `data_scope` **absent par
  choix** (ScopedVisibility porte sur les données produites, pas sur l'app) — à trancher.

### F8 — Studio (orchestration)  ⟷ `SPEC §F8`
- **`GENERIC_APPS`** (~10 lignes/app) + `build_generic_runner()` : `create` via `getattr(tool_api,
  add_to_<app>)` + `inspect.signature` ; `poll` via `DetailRegistry.get(app)['model']`. **10/10 normalisées**,
  shim `runners.py` vidé.
- **Graphe** : `StudioPipeline.graph` (nodes/links JSON) + `StudioRun.node_states`. Un nœud référence l'app
  **par string**. `run_pipeline_task` : `topo_order()` DAG, nœuds source (`text_input`/`media_import`) et sink
  (`studio_output`→`UserAsset` médiathèque).
- **Trou** : `renderNodeParams` appauvri (cf. F3). **Cible : E/S du nœud DÉRIVÉES des ports**, pas re-saisies.
- **Manifeste** : `studio.{runnable, primary_input, input_kwarg, fixed_kwargs, auto_start}` — ports/output_type
  **lus depuis `ports`** (fin de la double saisie).

---

## 10. La cible de convergence (careful, ne rien perdre)

**Principe** : le manifeste `app` devient la **source unique dont chacun tire ce dont il a besoin** ; les
registres actuels deviennent des **projections re-synchronisables** (discipline ingest : idempotent /
réversible / `verify`). On préserve tout le riche, on régénère le simplifié.

**Séquence prudente (préalable au code-gen) :**
1. **E/S** : faire de `GENERIC_APPS.input_kinds/output_type` une **projection des ports** (`derive_io_from_
   ports`). Garder les champs de câblage runner. **Seul correctif de données : `document` aux ports describer.**
   Les autres « écarts » sont **légitimes** (avatarizer=image de référence, enhancer=2 domaines) ou de
   l'**incomplétude** (converter pas encore dans le studio).
2. **Adopter les briques sous-adoptées** (chantier d'homogénéisation, indépendant du manifeste) :
   WamaParams sur les 5 apps hand-built + modale batch + studio→WamaParams (supprimer `renderNodeParams`) ;
   chips ; `select_model()` ; **enum de statut commune** (tuer les 3 tables d'alias) ; `during_preview` frontend.
3. **Write-back** (code-gen) depuis le manifeste, en commençant par le sûr (`access` DB).

---

## 11. Trous prioritaires (liste actionnable, confrontée au code)

| # | Trou | Facette | Nature |
|---|---|---|---|
| 1 | `describer` : `document` absent des ports | F2 | correctif de données |
| 2 | modale **batch** jamais rendue par WamaParams (hand-built partout) | F3 | adoption |
| 3 | studio `renderNodeParams` appauvri (réinvente WamaParams en dégradant) | F3/F8 | réinvention à supprimer |
| 4 | **« pendant »** : backend câblé, `media-preview.js` ne consomme pas `?side=during` | F3b | frontend manquant |
| 5 | `select_model()` adopté par 1 app / 10 (2 sélecteurs concurrents) | F4 | adoption |
| 6 | **statuts non uniformes** → 3 tables d'alias | F5 | dette de schéma |
| 7 | gating d'app **non ré-appliqué au RUN** d'un pipeline studio | F7 | sécurité |
| 8 | **pas de test de contrat** sur la triade tool_api | F6 | robustesse |
| 9 | imager : `create_image` vs `add_to_imager` attendu par le runner | F6 | à vérifier |
| 10 | `params_attr` multiple (image/video, media/audio) non capté par le manifeste | F3 | manifeste |
| 11 | `APP_MODES` (hand-maintained) à dissoudre : domaine=hint UI, mode=dérivé capacités | F2 | dette de conception |
| 12 | anonymizer : refactor yolo/SAM3 en sélecteur modèle groupé + switch capacités (pas un « mode ») | F2/F3 | refactor UX |
| 13 | avatarizer (rapide/qualité=param) + composer (music/bruitage=sélection modèle) : sortir du mécanisme modes | F2 | simplification |

---

## 12. Renvois & archive

- **Remplace** (archivés `docs/archive/`, consultables) : `UI_MECHANISMS_CONSOLIDATION.md` (mécanismes UI),
  `COMMON_REFACTORING.md` (briques communes), `GENERALIZATION_PLAN.md` (9 axes A→I), `BACKEND_CARTOGRAPHY.md`
  (contrat `BaseModelBackend`).
- **À réintégrer ici** (non re-tracé en profondeur par la cartographie du 2026-07-22) : le contrat
  `BaseModelBackend` (F4) et le détail des 9 axes de `GENERALIZATION_PLAN` (répartis dans F1–F8). Marqués
  `⚠ À RÉINTÉGRER` là où c'est le cas.
- **Chaînage manifeste** : chaque facette ci-dessus renvoie à `WAMA_MANIFEST_SPEC §Fx` (déclaration) et la
  carte `WAMA_MANIFEST_ARCHITECTURE §3` (facette→mécanisme). Toute évolution d'un mécanisme doit mettre à jour
  la facette correspondante ici ET son pendant manifeste.
