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

> **Pourquoi ces écarts existent — cadrage (Fabien, 2026-07-31).** Les applications ont été construites
> **au fur et à mesure, AVANT la centralisation des mécanismes**. Les divergences relevées dans ce
> document ne sont donc pas des erreurs de conception ni des régressions : ce sont les **traces d'une
> antériorité**. Chaque app a résolu son problème avec les moyens de son époque, puis la brique commune
> est arrivée après.
>
> Deux conséquences pratiques, qui doivent guider la lecture de tout ce document :
> 1. **Ne pas lire un écart comme une faute.** Le vocabulaire local d'une app (`total`/`done_count`
>    de l'avatarizer, `supports_cloning` du synthesizer, la cascade OCR du reader) était correct
>    quand il a été écrit. Le travail est de le **traduire** vers le contrat commun, pas de le corriger.
> 2. **Le danger n'est pas l'écart, c'est le DOUBLON silencieux.** Tant qu'une app fait « à sa façon »,
>    c'est visible et inoffensif. Le vrai risque naît quand la brique commune est posée **à côté** de
>    l'ancien mécanisme sans le retirer : deux listes à tenir (reclaim VRAM), deux sélecteurs qui
>    divergent (seuil de 10 Go du reader vs `vram_gb` du catalogue), ou un mécanisme **présent mais
>    inerte** (alias de classe sur `BaseModelBackend` ; `data-duplicate-url` posé sans la classe
>    `.duplicate-btn` attendue par `queue-actions.js`). **Porter = remplacer, jamais juxtaposer.**

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
- ~~**`GENERIC_APPS` re-déclare les E/S à la main** → redondance réelle~~ **RÉSORBÉE (2026-08-11,
  `b91f875`, §10.1)** : `GENERIC_APPS` **dérive** ses E/S de `studio_node_ports()` à l'import
  (`_fill_io_from_ports`, ordre = priorité préservé — la redéclaration manuelle avait fait perdre
  `archive` au converter). Une E/S déclarée à la main est un OVERRIDE : légitime si `io_scope`
  déclaré (imager V1 txt2img, enhancer média seul, avatarizer audio seul), sinon `studio_redundancy`
  la nomme `drift`. Les champs de **câblage runner** (`params_module/attr`, `input_kwarg`,
  `fixed_kwargs`, `auto_start`) restent déclarés — ce n'est pas de la redondance.
- **`INSTALLED_APPS`** (`settings.py:268`) = liste plate hand-maintenue, disjointe des registres.
- **Le manifeste `app`** (`manifests/builtin/app.py:76`) **agrège DÉJÀ les 4 registres + Django** en un body
  12 facettes ; **write-back PARTIEL** (`PROJECTED_FACETS`) : `access` s'écrit au runtime dans
  `AppAccessPolicy` (depuis `a75c01d`) et `identity` s'écrit en CODE dans `APP_CATALOG`
  (2026-08-11, pilote converter — entrée générée marquée `[manifest-gen app:<id>]`, réversible,
  `color` exclue car dérivée), les 8 facettes code restantes = code-gen de la couche mince
  déclarative (l'UI, elle, est générée au runtime par les briques une fois les registres
  alimentés). C'est la brique de convergence.

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
- **⚠ SURCHARGE `output_types` (à corriger proprement, 2026-07-22)** : 5 apps y mettent des FORMATS au lieu
  de catégories — composer `(wav,mp3)`, describer `(txt)`, reader `(txt,markdown)`, synthesizer `(mp3,wav)`,
  transcriber `(txt,srt,vtt,json)`. `normalize_types()` (def `:80`, appels `:139-140`, `:166`) est la BÉQUILLE qui rattrape. **MODÈLE
  PROPRE = 3 concerns SÉPARÉS, jamais surchargés :**
  | Concern | Nature | Ex. | Consommé par |
  |---|---|---|---|
  | **`output_type`** | catégorie média FIXE de l'app | transcriber=`text`, converter=`mirror/any` | ports, preview, routage |
  | **`output_format`** | mécanisme COMMUN hérité du converter (générique-par-catégorie ∪ app-spécifique) | txt/srt/vtt, wav/mp3 | sélecteur de téléchargement (toutes apps) |
  | **`domains`** | **hint DÉCLARATIF** (onglets), NON dérivé du type | imager Images/Vidéos ; converter aucun | onglets de domaine |
  Migration : `output_types`→catégories (composer/synth/describer/reader = formats génériques → gratuits via
  domaine converter ; transcriber srt/vtt/json = app-spécifiques, sourcés d'où ils vivent déjà, ex.
  `download_srt`). **Prérequis : tracer les consommateurs de formats BRUTS** (sélecteurs de téléchargement
  des 5 apps) — les consommateurs de catégorie normalisent déjà. UI inchangée.
- **Redondance** : `GENERIC_APPS.input_kinds/output_type` redéclare l'E/S ; sentinelle `'auto'` propre au
  studio (absente d'APP_CATALOG). `derive_io_from_ports()` (`projection.py:80`) prouve la reconstructibilité.
- **Manifeste** : ports captés via l'accesseur unique ; **typage de sortie = CAPACITÉ** (`export_binding`
  early/late), les formats restent au converter. **Cible : GENERIC_APPS devient projection des ports.**

**DÉCISION 2026-07-22 (Fabien) — DOMAINE vs MODE (deux affordances UI distinctes) :**
- **DOMAINE = onglets** : bifurcation de *but* (imager : Images/Vidéos ; enhancer : Image-Vidéo/Audio).
  **100% DÉCLARATIF (hint), NON dérivable du type** — corrigé 2026-07-22. Preuves : converter = multi-type
  mais **0 onglet** (sa multi-type est son mécanisme, pas des domaines) ; imager (image/vidéo = 2 onglets)
  vs enhancer (fusionne image+vidéo, audio séparé = 2 onglets) → mêmes modalités, groupement différent =
  décision UX. Le hint déclare la structure d'onglets *verbatim* → **UI inchangée par construction**. Piste
  fallback future (différée, données trop creuses 36/147) : jeux de modalités distincts des MODÈLES.
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
  - ~~modale batch JAMAIS rendue par WamaParams~~ — **PÉRIMÉ, mesuré 2026-08-06** : anonymizer,
    avatarizer et imager rendent `context:'batch'`. Ce qui reste écrit à la main est la **coquille**
    (`<div class="modal">` + titre + pied), jamais le CONTENU (généré du schéma).
  - le **studio a son PROPRE renderer** `renderNodeParams` (`wama-studio.js:348`) **appauvri** (pas de
    toggle/range/radio/show_if/advanced) — réinvention à supprimer (doit appeler WamaParams).
- **Adoption réelle** (le vrai déficit) :

  | Surface | Câblée sur | Reste |
  |---|---|---|
  | modale item (WamaParams) | converter, reader, enhancer (plein) ; transcriber, composer (partiel) ; **anonymizer + imager (générée intégralement, 2026-08-03/06)** | synthesizer, describer, avatarizer |
  | modale batch (`context:'batch'`) | anonymizer, avatarizer, **imager (2026-08-06)** | 7 apps |
  | chips métadonnée (`card_chips.py`) | reader, **anonymizer, imager (2026-08-06)** | 7 apps |
  | `WamaModelCaps` (show_if depuis caps) | **synthesizer seul** | — |
  | corps de modale commun `_settings_modal.html` | **sans objet depuis 2026-08-06** : la modale est GÉNÉRÉE (`WamaParams.settingsModal`, cycle complet + hooks) — le gabarit HTML prévu par la roadmap d'avril datait d'avant `WamaParams`. Reste à porter aux 8 autres apps | — |
  | **réglages utilisateur persistés** (`common/utils/user_settings.py`) | avatarizer, converter, describer, synthesizer, transcriber | **imager (modèle maison `UserSettings`, jamais écrit), anonymizer** |
- **Manifeste** : `params` capté (`app.py:212`) mais ⚠ **un seul `params_attr`** (rate les multi-schémas
  `IMAGE_+VIDEO_`, `MEDIA_+AUDIO_`) ; ne distingue pas **déclaré vs câblé** (c'est le round-trip qui le révèle).

### F3b — Inspecteur, preview & progression  ⟷ `SPEC §F3 (inspector)`
- **Inspecteur** : `DetailRegistry` + `build_detail` (dict canonique plat ; labels/sections en JS
  `DETAIL_SCHEMA`). **11 apps** enregistrées.
- **Preview** : `PreviewRegistry` + `unified_preview` ; **10/11** (imager exclu, décision documentée). Règle
  **entrée = port `travail` sinon `prompt`, JAMAIS `reference`** — **implémentée et vérifiée** via l'accesseur
  unique (`preview_utils.py:66-85`). Face sortie dérivée de l'adapter Detail (couplage Preview→Detail).
- **« PENDANT » (preview progressive)** : **chaîne COMPLÈTE** (composer `emit_streaming_peaks` →
  capacité `during_preview=True` `app_registry.py:455` → face `?side=during` `preview_utils.py:255`
  → **consommée par `wama-inspector.js` `_startDuring`** (polling 1300 ms, auto-arrêt en fin de run).
  ⚠ **Correction 2026-07-30** : ce doc affirmait « `media-preview.js` ne le consomme pas → maillon
  FRONTEND manquant ». C'était **faux** — le consommateur est l'inspecteur, `media-preview.js` ne fait
  que *rendre* la donnée qu'on lui passe. Le trou réel n'est pas le front mais l'**émission** :
  **1 app sur 10** (composer) publie un partiel ; les 9 autres n'ont rien à afficher. Mesuré par le
  critère `during_preview` (F3), qui exige émission app **ET** consommation front commune.
- **Filemanager** : **unifié** (réutilise `media-preview.js`), mais endpoint de données distinct.
- **ETA** : `WamaEta` (1 moteur, 3 niveaux carte/batch/global) + backend apprenant `eta_estimator` +
  `ModelRuntimeStat`. ~9 apps enregistrent `record_run` (reader/anonymizer = front sans apprentissage).
- **Manifeste** : inspector adapter (mapping champs→clés canoniques), preview binding sur port,
  capacité `during_preview/streaming`, profil ETA (unit + a-priori load/per_unit).

### F4 — Modèles IA  ⟷ `SPEC §F4`
- 🔴 **AVANT DE TOUCHER AUX CAPACITÉS OU AU TIRAGE — lire [`INPUT_MODEL_MATCHING.md`](INPUT_MODEL_MATCHING.md)**
  (appariement entrée↔modèle : vocabulaire canonique, `inputs_required`/`inputs_optional`, grisage UI
  `WamaInputMatch`). Ce document était **orphelin du graphe** jusqu'au 2026-07-30 : cité nulle part ici,
  alors que le skill `/port-app` annonce cette route comme « référence unique ». Conséquence vécue le
  30/07 : une session a réinventé des drapeaux de capacité ad hoc (`t2i`/`t2v`/`i2v`) faute d'avoir su
  que le vocabulaire canonique existait. **Une facette qui ne pointe pas vers son document de domaine
  produit exactement la duplication que la route combat.**
- **Catalogue** = `AIModel` (source unique), `capabilities` JSON canonique (`CANONICAL_CAPABILITIES`,
  `model_capabilities.py:30`). **Découverte** : `_discover_<app>_models()` importe le `model_config.py` de
  l'app et construit les capabilities (`model_registry.py`). **Déclaration app** : `<APP>_MODELS` + `*_DIR`.
- **Tirage runtime** : `settings.MODEL_PATHS → *_DIR → HF_HUB_CACHE (avant import) → cache_dir → from_pretrained`
  (backends imager conformes CLAUDE.md) — **indépendant de `select_model()`**.
- **Sélection VRAM-aware** `select_model()` (`model_selector.py:66`) : **adoptée par 2/10** — composer
  (`auto_model.py:43`) + **transcriber depuis 2026-07-24** (`transcriber/backends/manager.py`,
  `_select_backend_via_model_manager` = fin adaptateur, **fallback intégral** sur la priorité statique si
  catalogue vide/model_manager KO ; pont granularité backend↔model_key via `_backend_for_model_key`).
  anonymizer a **son propre** sélecteur (dupliqué). Converter = **pas de modèle** (ffmpeg/pandoc) →
  `models: null` doit être toléré.
- **Reclaim/coordination VRAM** — ✅ **UNIFIÉ 2026-07-31** (`1c31c94`). Le diagnostic « adopté 1/10 »
  était trompeur : le problème n'était pas l'adoption mais **TROIS mécaniques concurrentes**, dont deux
  dans le même fichier — (1) le registre `_VRAM_UNLOADERS`, (2) `MemoryManager._unload_<app>_model()` +
  `_unload_all_backends()` qui énuméraient les apps EN DUR (une app adoptant (1) était invisible de (2)
  et réciproquement ; le transcriber était dans les deux, logique écrite deux fois), (3)
  `resource_governor.release_vram(owner)`, **homonyme exact** de `MemoryManager.release_vram(exclude)`
  mais de sémantique opposée (effacer une ligne de comptabilité Redis vs décharger réellement).
  Trois des unloaders en dur (anonymizer, synthesizer, enhancer) faisaient un `gc.collect()` puis
  retournaient **`True`** : succès annoncé, rien libéré, **indétectable**.
  **Levier retenu** : `BaseModelBackend` enveloppant déjà `load`/`unload` à toute profondeur, il tient
  désormais un registre d'instances résidentes (`_LIVE_BACKENDS`, WeakSet) et **enregistre l'unloader de
  l'app à la première résidence réelle** → 6 apps couvertes **sans boilerplate**, présentes et futures.
  Déclaration explicite réservée au hors-contrat (describer/BLIP en variable de module,
  transcriber/pyannote), **dans l'`apps.py` de l'app** — auparavant le model_manager devait connaître
  les internes de chaque app. `unload_model()` route par préfixe d'app et répond `False` en l'absence
  d'unloader. Hors process (sous-processus) → `vram_reservation` (avatarizer).
  ⚠ Non applicable au synthesizer : il ne charge **rien** en process (aucun `torch`, aucun
  `from_pretrained` — tout part au service TTS).
- **Redondances** : `ModelType`/`ModelSource` dupliqués (`models.py` + `model_registry.py`) ; capabilities
  canonicalisées dans la découverte, pas dans les `model_config` d'app.
- **Manifeste** : `models.{consumes, selection:{strategy: select_model|app_custom|fixed, requires, classes,
  priority, prefer_loaded}, paths_key, capabilities_vocab}`.
- **Contrat de backend commun** (`common/backends/base.py::BaseModelBackend`) : cycle de vie
  `load/is_loaded/unload/process`, dépendances déclaratives (`REQUIRED_PACKAGES` → `missing_packages()` /
  `is_available()` / `pip_install_spec()`), et **déclaration automatique de l'empreinte VRAM** au gouverneur
  via `__init_subclass__` (cf. `ROADMAP.md` §Gouvernance des ressources). **ADOPTION 7/10 apps** — imager,
  **transcriber** (2026-07-29 : `SpeechToTextBackend` était un contrat CONCURRENT hérité d'`ABC`, ses
  3 moteurs échappaient donc à tout le mécanisme, + `PyannoteDiarizerBackend`), **anonymizer** (29/07 :
  aucun `backends/`, 3 porteurs de modèle rattachés par `DetectionBackend`), enhancer, reader, composer.
  ⚠ Règle : une app qui a besoin d'un contrat plus riche **spécialise** `BaseModelBackend` (verbe métier +
  capacités), elle n'en redéfinit JAMAIS un à côté. Le point de levier est la **classe intermédiaire** :
  `__init_subclass__` enveloppe les `load`/`unload` à n'importe quelle profondeur, donc rattacher
  l'intermédiaire couvre TOUS les backends concrets sans les toucher (3 classes → 7 backends le 29/07).
  ⚠ **Piège** : mapper le verbe historique par délégation (`def load_model(self, *a, **k): return
  self.load(*a, **k)`), JAMAIS par alias de classe (`load_model = load`) — l'alias capture la fonction
  avant l'enveloppe, et le mécanisme devient présent mais inopérant.
- **Modèles hors process** (sous-processus, service séparé) : l'héritage ne s'y applique pas — rien n'est
  résident dans le worker. Brique dédiée `resource_governor.vram_reservation(owner, gb)` (contextmanager).
  Adoptée par **avatarizer** (MuseTalk + CodeFormer en `subprocess`) ; reste le **service TTS**, dont la
  déclaration doit venir de l'intérieur du service. Cf. `PROJECT_STATUS.md` §0 (3quinquies).
- **⚠ À réintégrer depuis l'archive** : le détail par backend (ex-`BACKEND_CARTOGRAPHY.md`) n'a pas été
  re-tracé en profondeur ici — pointeur `docs/archive/BACKEND_CARTOGRAPHY.md` en attendant sa fusion en F4.

### F5 — Traitement / cycle de vie  ⟷ `SPEC §F5`
- **Spine item** : `ProcessingTimeMixin` (`common/models.py:19`) + `BatchMixin` (`:43`). Champs communs de
  fait, mais **noms divergents** (`input_file` vs `audio`) et **`error_message` absent de transcriber**.
- **Statuts NON uniformes** [dette réelle] : converter contraint (`STATUS_CHOICES`) / transcriber **libre** /
  reader `DONE/ERROR` → réconciliés à l'affichage par **3 tables d'alias dupliquées** (`detail_registry.
  normalize_status`, `batch_common._ALIAS`, `wama-cycle-button.js stateFor`). Pas d'enum commune.
- **Task Celery** : `@shared_task`, **dual-write progress** (cache + `.update`), seeding ETA `record_run`.
- **Reprise après crash worker** : `process_control.reconcile_orphaned_running()` (93329c4 puis
  32df89c = bascule en échec sur **preuve positive de mort** du worker propriétaire seulement) —
  adopté **8/11** (2026-07-29 : + imager ; manquent anonymizer, avatarizer, translator + apps lab).
- **Garde anti-BOUCLE-de-crash** : `process_control.refuse_crash_redelivery()` — un message
  `redelivered` vient d'un worker mort SANS acquitter (freeze/panic machine) ; le rejouer relance
  l'exécution qui a tué le worker, à CHAQUE démarrage. Distinct de la réconciliation ci-dessus, et
  **non couvert** par les gardes « statut terminal » / « task_id divergent » (le statut reste
  `RUNNING` ET le task_id est identique). Adopté **10 tâches / 42** (610bdd5) — cf. `PROJECT_STATUS` §0
  pour la liste des 32 restantes (dont cam_analyzer ×13 et les sous-tâches GPU de l'anonymizer).
- **Ressources GPU/CPU/RAM** : **`common/services/resource_governor.py` = domicile unique**
  (plafond allocateur CUDA par process, registre VRAM partagé Redis inter-process, table de
  priorités déclarative). Ne JAMAIS re-poser une limite de ressource dans une app ou un backend :
  la version d'origine, posée sur un seul chemin de chargement, laissait passer tous les backends
  qui font `.to('cuda')` en direct. Détail + reste-à-faire : `ROADMAP.md` §Gouvernance des ressources.
- **Rendu HTML→PDF** : brique commune `common/utils/html_render.py` (Chromium headless → WeasyPrint,
  1329638) — consommateur unique converter `document_backend`.
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
- ✅ **Point d'exécution UNIQUE (2026-08-01, `86889ca`)** — le studio ne court-circuite plus
  `execute_tool` : `create`/`start` passent par lui. La logique que le runner avait ré-implémentée chez
  lui est promue au commun : `sanitize_tool_args()` (coercition par schéma + filtre de signature) et
  `primary_arg_name()` (nom du 1er paramètre DÉRIVÉ de la signature → plus besoin de connaître
  `media_id`/`transcript_id`/`generation_id`). Deux briques dans `param_schema.py` :
  `schema_for_app()` (accesseur unique F3, résolution par le pointeur déclaratif) et
  `coerce_schema_values()` (délègue les bornes à `coerce_params`). Gains : l'assistant et l'API
  filtrent/coercent comme le studio (avant : `TypeError` sur argument inconnu) ; le studio applique
  enfin les **bornes** du schéma (son `_coerce` local typait sans clamper) ; le cas spécial
  `if tool_name == 'sam3_examples'` disparaît. ⚠ Reste à migrer : `manifests/builtin/app.py::_params`
  garde sa propre copie de la résolution (territoire d'une autre instance).
- **Trous** : garde MEDIA_ROOT dupliquée ~8× ; **pas de test de contrat** sur la triade (bug describer
  output_format→output_style découvert au runtime).
  - ✅ **CONTRAT ALIGNÉ (2026-08-02, `14332b8`) — 34/71 → 71/71 sur les 10 apps.** Avant : anonymizer
    3/17, converter 1/12, describer/transcriber/composer −3 ou −2 ; ces params étaient réglables dans
    l'UI mais **tombaient silencieusement** dès qu'on passait par un outil (le studio les jetait déjà,
    sans le dire).
    **Mécanique descriptive, aucune liste recopiée** : chaque `add_to_<app>` ouvre `**params`, et
    `schema_model_kwargs()` (params déclarés QUI SONT des champs du modèle — 27/37) +
    `schema_extra_params()` (transitoires → champ JSON de l'app, 10 pour `converter.options`) les
    appliquent. `sanitize_tool_args` accepte **signature ∪ noms du schéma** : un param ajouté au
    schéma devient transmissible **sans toucher à la signature** — c'était la dérive à éviter.
    Pièges traités : collision `describer output_format`↔`output_style` (kwarg public ≠ champ modèle) ;
    `converter.media_type` DÉTECTÉ depuis le fichier, exclu pour qu'un appelant ne l'écrase pas ;
    converter auto-démarre → `options` posé À LA CRÉATION, pas après coup.
  - ⚠ **3e copie restante** : `converter/views.py:229` re-liste **14 clés d'options en dur** avec son
    propre casting, alors que le schéma les déclare. À faire adopter `schema_extra_params()` (app en
    lecture seule pendant le chantier design des cards).
  - **Le chantier « supprimer `TOOL_DESCRIPTIONS` » est maintenant DÉBLOQUÉ** : il était nuisible tant
    que le contrat était rompu (on aurait annoncé à l'assistant des params que la fonction refuse).
  - ✅ **Tranché (2026-08-01)** : l'alias `add_to_imager` EXISTE (`tool_api.py:2088`, bloc « aliases
    normalisés » STUDIO_VISION 2026-07-12) — le runner studio fonctionne. Mais il n'a **pas de description**.
- ✅ **CHAÎNE CONCURRENTE SUPPRIMÉE (2026-08-02, `6650617`)** — `TOOL_DESCRIPTIONS` (dict manuel de
  278 lignes) remplacé par `tool_descriptions()`, **dérivé** : `APP_CATALOG` (phrase FR) + docstring +
  schéma + signature réelle. Mesuré : **43/43 outils décrits** (était 40/43), **157 arguments
  documentés** avec types/choix/bornes/défauts (le dict en décrivait 21 sur 71 params).
  `build_tools_list()` itère désormais le registre → le prompt de l'assistant est exhaustif **par
  construction**, et `start_composer` y est enfin. Le nom `TOOL_DESCRIPTIONS` reste importable via un
  `__getattr__` de module (PEP 562) et rend la version dérivée — `manifests/builtin/app.py` (autre
  instance) en bénéficie sans être modifié. **Convention de nommage de la triade rapatriée** dans
  `tool_api` (`app_id_for_tool`, `tool_role`, overrides) ; `accounts/permissions` ne garde que la
  DÉCISION d'accès.

  **Surface outils courante** (couche factuelle auto-générée, ROADMAP §16.9 ①) :

  <!-- WAMA:FAITS(outils) — généré par « python manage.py doc_facts », ne pas éditer -->
- Outils au registre (`TOOL_REGISTRY`) : **46**
- Outils décrits (`tool_descriptions()`, dérivé) : **46/46**
- Arguments documentés (types/choix/bornes/défauts) : **173**
<!-- /WAMA:FAITS(outils) -->
- 🔴 **PANNE TROUVÉE ET CORRIGÉE au passage — `describer.output_format`** (signalée par Fabien) :
  `output_style` est un **STYLE de description** (résumé / détaillée / synthèse scientifique / points
  clés / **compte-rendu de réunion**), PAS un format de fichier — celui-ci est choisi par
  l'utilisateur APRÈS le traitement. Le champ a été renommé (migration `0008`) sans alias sur le
  modèle et sans répercussion complète : `get_describer_status` faisait `desc.output_format` →
  **AttributeError dès qu'un utilisateur avait une description** (panne reproduite). De plus la
  validation était une liste EN DUR de 4 styles alors que le schéma en déclare 5 : `meeting` était
  proposé par l'UI et **refusé par l'outil**. Valeurs désormais dérivées du schéma, kwarg public
  renommé `output_style` (son nom entrait en collision de sens avec le `output_format` de
  reader/converter, qui désigne un vrai format de fichier).
  ⚠ **Reste** : `describer/utils/text_describer.py:128,172` lisent encore `description.output_format`
  → même AttributeError au traitement (app en lecture seule pendant le chantier cards).
- ~~⚠ CHAÎNE CONCURRENTE MESURÉE (2026-08-01) — `TOOL_DESCRIPTIONS` double `PARAMS_JSON`.~~ (soldé)
  Les params sont déclarés une fois, typés, dérivés du modèle Django (`params.py` → `derive_from_model`,
  consommé par les modales, l'inspecteur ET le studio via `params_module/params_attr`). `TOOL_DESCRIPTIONS`
  en est une **recopie manuelle en français**, non typée, qui dérive :
  - **21 / 71 params typés décrits (30 %)** — ex. transcriber : `generate_summary`, `summary_type`,
    `verify_coherence` invisibles pour l'assistant IA.
  - **`build_tools_list()` itère `TOOL_DESCRIPTIONS`, pas `TOOL_REGISTRY`** — malgré son docstring qui
    annonce « source unique → liste exhaustive → plus de divergence prompt↔registre ». L'assistant voit
    **40 outils sur 43**.
  - **Conséquence fonctionnelle réelle** : `start_composer` ET `add_to_composer` sont invisibles et
    `auto_start` n'est pas posé sur composer → **l'assistant peut créer une composition et suivre son
    statut, mais ne peut pas la lancer**. (imager s'en sort : `start_imager` est décrit.)
  - **Cible** : supprimer `TOOL_DESCRIPTIONS`, tirer la description des params du REGISTRE (`params.py`,
    via le pointeur déclaratif `GENERIC_APPS.params_module/params_attr`) — conformément à la chaîne
    `manifeste → ingest → registres → mécanismes` : le manifeste NE DOIT PAS être lu à l'exécution,
    il sert à valider/confronter les registres, qui restent la source des mécanismes.
- **Manifeste** : `prompts.{targets, skills}` + `tool_api.{add,start,status,descriptions}`.

### F7 — Permissions & scope données  ⟷ `SPEC §F7`
- **Gating d'app** (`permissions.py`) : 2 axes **tier** (`TIER_ORDER`, bypass dev/admin) + **rôles** (Groups
  `role:*`). `AppAccessPolicy` DB (DEFAULT = seed). **Point de décision unique `accessible()`** appliqué :
  nav (complet), studio **palette** (oui). Vues = décorateur `@app_access` au cas par cas (pas généralisé).
- **Surface OUTILS gardée ✅ (2026-08-01)** — `tool_accessible()` + `app_id_for_tool()` (`permissions.py`,
  pendant de `app_id_for_path` : dérive l'app de la triade F6, `TOOL_APP_OVERRIDE` pour les noms historiques
  `create_image`/`synthesize_text`/`compose_music`/`convert_file`, alias `audio_enhancer`→`enhancer`).
  **Mesuré : 40 outils gardés / 43, 3 transverses assumés** (`list_user_files`, `translate_text`,
  `switch_ui_mode`), 0 app inconnue. `TOOL_REGISTRY` a **4 consommateurs** : 2 d'EXÉCUTION (`execute_tool`
  et `generic_runner` qui le court-circuite via `getattr`), 1 de LISTAGE (`ListToolsView`), 1 de PROMPT
  (`build_tools_list`, qui itère en fait `TOOL_DESCRIPTIONS` — cf. divergence F6 ci-dessous).
  Garde appliquée aux 3 premiers :
  `execute_tool` (assistant IA + `POST /api/v1/tools/run/` → **403**, payload aligné sur
  `AppAccessMiddleware._deny`), `ListToolsView` (**`tools/list` filtré** — il annonçait des outils que
  `run` refuse), et la boucle de nœuds de `studio/tasks.py:181` (**clôt le trou #7**, le RUN ne repassait
  pas par `accessible()` et `generic_runner` court-circuite `execute_tool` via `getattr(tool_api, …)`).
  ⚠ Ce n'était pas un trou théorique : `AppAccessMiddleware` ne voit pas `/api/v1/…` (`app_id_for_path`
  → `None`) **et** l'auth DRF par token s'exécute APRÈS le middleware → un token contournait tier+rôles.
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

**Séquence prudente (préalable au code-gen) — c'est la « §10.x » que cite le code :**

### §10.1 — E/S : `GENERIC_APPS` = projection des ports — ✅ FAIT (2026-08-11, `b91f875`)
`_fill_io_from_ports()` dérive `input_kinds`/`primary_input`/`output_type` de `studio_node_ports()`
à l'import, **ordre préservé** (= priorité de résolution de l'entrée primaire). Champs de câblage
runner conservés déclarés. Rétrécissements de nœud déclarés par `io_scope` (imager V1 txt2img,
enhancer média, avatarizer audio) ; E/S manuelle sans `io_scope` → verdict `drift`
(`studio_redundancy`). Correctif de données appliqué : describer `input_types` `text`→`document`
(le `text` fabriquait un port prompt fantôme). Le converter, qui avait perdu `archive` dans la
redéclaration manuelle, le récupère par construction. Mesuré : 10/10 agree (7 derived / 3 narrowed).

### §10.2 — Adopter les briques sous-adoptées — 🔄 (chantier d'homogénéisation, indépendant du manifeste)
WamaParams sur les apps hand-built restantes + modale batch + studio→WamaParams (supprimer
`renderNodeParams`) ; chips ; `select_model()` ; **enum de statut commune** (tuer les 3 tables
d'alias) ; `during_preview` émission (9 apps).

### §10.3 — Write-back (code-gen) depuis le manifeste — `access` ✅ (DB) + `identity`/`ports`/`capabilities`/`studio`/`modes`/`prompts`/`params` ✅ (2026-08-11), reste 4 facettes (`inspector`, `models`, `processing`, `tool_api`)

**Palier `params` (soir, sur dev)** : extract MULTI-SCHÉMAS — tous les attributs `*PARAMS_JSON`
(trou #10 résorbé : imager IMAGE+VIDEO, enhancer MEDIA+AUDIO étaient invisibles), facette
`{primary, schemas}` (forme liste historique acceptée à l'ingest). Projecteur : un `params.py`
écrit MAIN est du code DÉRIVANT (`derive_from_model` + sources dynamiques) → comparaison
SÉMANTIQUE seulement (canonique JSON, tuples profonds) et JAMAIS de réécriture ; module absent →
fichier GÉNÉRÉ marqué (couche de démarrage, à raffiner en `derive_from_model` quand `processing`
génèrera le modèle) ; réversibilité = suppression du fichier marqué. Vérifié : 10/10 noop,
create bac à sable → égalité + `schema_for_app` vivant + idempotence. Roundtrip : **6/10 à 8/12**.

**PASSE INTÉGRÉE du pilote converter (2026-08-11 soir — la « régénération complète » de
l'étape 1)** : suppression EN UNE FOIS de toutes les déclarations régénérables (entrée
APP_CATALOG, entrée GENERIC_APPS, entrée APP_MODES, `params.py`) puis UN SEUL
`write_back(apply=True)` (bac à sable worktree, DB non touchée — `access` inchangé). Jugement
sur les 3 axes actés : **① manifeste** ré-extrait = **8 facettes + enveloppe IDENTIQUES** ;
seuls écarts = drapeaux de la matrice `conventions` dans `capabilities` (7) et `processing`
(anti_race/processing_time/statuses) — tous de la famille MESURÉE du trou #16, sans effet
mesurable ; **② grille** : **93 % (58/62), IDENTIQUE au baseline**, mêmes 4 rouges ;
**③ smoke** : `GET /converter/` 200, `schema_for_app` 17 params, nœud studio E/S dérivées +
`auto_start`, 5 domaines APP_MODES. **Sur le périmètre des 7 facettes, l'app régénérée est
indistinguable de l'app en place.** Ce qui vit encore hors manifeste : le code de `processing`/
`tool_api`/`inspector` (jamais supprimé dans ce test — c'est la marche gabarit ci-dessous).

**Orientation actée pour `processing` (avis critique 2026-08-11, comparaison k8s/Backstage/
ComfyUI/Twenty/Terraform)** : PAS « le LLM génère le fichier » — un **GABARIT** couvre le
squelette conventionnel (models.py/urls/tasks : la grille 72 critères prouve la convention),
le LLM ne génère QUE le corps des backends (la glu d'usage des librairies). Harnais de jugement
= le protocole du pilote (worktree + diff normalisé + grille + smoke), à ériger en process
outillé avant d'ouvrir cette marche.

**Plan d'exécution de la marche (cadré avec Fabien 2026-08-11 soir) — ordre C → A → B :**
- **C. Harnais outillé ✅ LIVRÉ (2026-08-11, 3ᵉ session)** : `manage.py app_regen_check <app>`
  (common/management/commands) érige le protocole de la passe intégrée en commande — gardes
  (fichiers cibles propres, branche ≠ dev/main sauf `--force`, corpus fidèle à l'extraction
  courante hors clés `_` diagnostiques) → baseline → strip (`strip_app_declarations`, nouveau
  geste de harnais dans `builtin/app.py` : retire AUSSI les entrées main, l'inverse assumé du
  contrat du moteur) → `write_back_app(corpus, apply=True, skip=('access',))` (kwarg `skip`
  ajouté : le harnais ne touche JAMAIS la DB) → re-mesure → verdict 3 axes → `git checkout`
  des cibles (sauf `--keep`). Mesure et apply tournent en SOUS-PROCESS FRAIS ancrés sur
  BASE_DIR (dans le process courant, modules params/registres périmés dès le strip ; l'ancrage
  permet `python <worktree>/manage.py …` depuis n'importe quel cwd). Axe ① tolère la famille
  MESURÉE seule (liste explicite `_MESURE_PATHS` : 11 drapeaux capabilities +
  processing.anti_race/processing_time/statuses — trou #16) ; axes ② (conv critère par
  critère, `evidence` exclue car porteuse de numéros de ligne) et ③ (HTTP, schema_for_app,
  nœud studio E/S dérivées, domaines APP_MODES) exigent l'égalité stricte. **Validé sur le
  pilote converter en worktree : VERDICT CONFORME, identique à la passe intégrée manuelle**
  (strip 4 cibles, 10 écarts mesurés tolérés = les 7 capabilities + 3 processing consignés,
  grille 93 % identique, smoke 200/17 params/studio/5 domaines) ; roundtrip 10 apps inchangé ;
  garde branche vérifiée (refus sur dev). Échec ⇒ exit ≠ 0 (chaînable en nightly, trou #19).
- **A. Gabarit (sans LLM)** : `common/manifests/codegen/` — templates du squelette conventionnel,
  trous alimentés PAR LE MANIFESTE : `models.py` (spine user/status/task_id/progress +
  ProcessingTimeMixin + champs DÉRIVÉS de la facette params — l'inverse de `derive_from_model`),
  `urls.py` (STANDARD_ENDPOINTS), `views.py` (fabriques communes : queue_manipulation, anti-race,
  batch unifié), `tasks.py` (gardes crash_redelivery + reconcile + eta), `apps.py` (Detail/
  PreviewRegistry = facette inspector), triade `tool_api` (conventionnelle). Fichiers marqués
  `[manifest-gen]`, mêmes contrats que le moteur commun.
- **B. LLM aux trous restants** (corps des backends) — deux facteurs actés DÈS MAINTENANT :
  1. **Modèle : MESURÉ, pas présumé.** Candidat pressenti par Fabien : `qwen3.6:35b` — vérifié
     2026-08-11 : **MoE** (`qwen35moe`, 36B totaux, 256 experts / 8 actifs, Q4_K_M, 23,9 Go
     tirés sur l'hôte) ⇒ les poids doivent résider (VRAM+RAM) mais l'offload CPU est TOLÉRABLE
     (seuls les experts actifs calculent) — cohabitation partielle avec WAMA envisageable, le
     banc mesurera le débit réel sous offload. Challengers `qwen3-coder:30b` (le verdict « trop
     lourd » de CLAUDE.md valait pour l'AGENTIQUE multi-tours — la génération one-shot est un
     autre profil), `gemma4:26b`/`e4b`. Banc indexé sur la TÂCHE canonique (« corps de backend
     depuis manifeste composé + skill »), jugé par le harnais C (compile + contrat
     BaseModelBackend + smoke) — jamais au jugé. Verdict inscrit dans
     `wama-dev-ai/config.py::select_model_for_role()` (chaînes de repli existantes).
  2. **Skill de génération : MISE À JOUR du registre de rôles wama-dev-ai EXISTANT** (cadré
     Fabien — pas de recréation) : `wama-dev-ai/prompts/` porte déjà system/architect/audit/
     debug/dev/librarian + runners (`run_librarian.py` = le patron). Évolution : `dev.txt`
     (générique, sans contrat WAMA) → rôle `codegen` contraint SUR LE MODÈLE DE `librarian.txt`
     (règles strictes, un artefact, jamais inventer) avec contrat `BaseModelBackend` + manifeste
     composé (`requires` app→model→library résolus) + 2-3 backends exemplaires en few-shot (le
     corpus est le matériel d'apprentissage, `ingest.py:43`) + interdits (pas d'import avant
     `HF_HUB_CACHE`, `cache_dir` obligatoire, vocabulaire de statuts canonique).
  Pilote : **transcriber** (composition complète librairie faster-whisper + tous ses modèles).

**Palier `prompts` → PROMPT_TARGETS** : variante ENTRÉE-VALEUR du moteur (l'entrée du registre
EST la liste `targets`, pas un dict de champs) — bornes par AST (lineno/end_lineno, robustes aux
3 idiomes : mono-ligne, fermeture main `    ],`, continuation pprint générée). Seul `targets` se
projette ; `skills` = noms de fichiers (rapport, trou #17) ; une entrée main (commentaires
d'intention) n'est JAMAIS régénérée. Vérifié : noop sur les 3 apps à targets (anonymizer,
composer, imager), create composer → égalité profonde, idempotence, réversibilité ciblée
(seule l'entrée générée serait retirée), roundtrip **7/N** (apps avec modes+prompts).

**Palier `modes` → APP_MODES** : la facette EST l'entrée (littéral profond domains→modes→
inputs/settings) ; comparaison en égalité PROFONDE (ordre des clés indifférent, ordre des LISTES
significatif), rendu pprint sur entrée générée, chirurgie REFUSÉE sur entrée main (multi-ligne
par nature — seule une entrée marquée se régénère). Vérifié : noop intact, create → égalité
profonde ré-extraite, idempotence, roundtrip **6/N** (5/N pour composer/describer/reader, sans
modes — N/A). Reste en code-gen (converter) : `params`, `inspector`, `processing`, `tool_api`
— cibles par-app (params.py, apps.py, urls/tasks/models), la marche suivante.

**Palier `studio` → GENERIC_APPS** : le moteur dict est GÉNÉRALISÉ (`_write_dict_fields`
paramétré par (chemin, assignation, rendu, ordre) — un seul moteur pour APP_CATALOG et
GENERIC_APPS). La facette studio est réduite au DÉCLARATIF (pointeur `params_module/params_attr`,
`auto_start`, `input_kwarg`/`fixed_kwargs`/`extra_params_spec`, rétrécissement `io_scope` + E/S
déclarées) ; les E/S dérivées des ports (`_io_derived`, §10.1) sont EXCLUES de l'extract comme de
la projection — même règle que la couleur. ⚠ Cette correction d'extract a RE-FORMÉ la facette des
10 manifestes (corpus régénéré au même commit) : l'ancienne facette recopiait les E/S effectives
sans distinguer dérivé/déclaré et perdait pointeur params + io_scope. Vérifié : diff studio
manifeste↔ré-extraction AUCUN après régénération, E/S re-dérivées à l'import, `studio_redundancy`
verdict `derived`, idempotence, roundtrip 10 apps **5/N projetables** fidélité OK.
Faire grandir `write_back_app` facette par facette, chaque incrément jugé par le diff
régénéré/existant (pilote de régénération : converter puis transcriber, acté 2026-08-11).

**Moteur commun APP_CATALOG** (branche `regen/converter`, bac à sable worktree) : les 3 facettes
code écrivent la MÊME entrée `APP_CATALOG` avec des champs DISJOINTS —
- `identity` → label/category/icon/url_name/description/input_extensions (`color` EXCLUE : dérivée
  par `_assign_derived_colors()`, l'écrire la figerait en override) ;
- `ports` → input_types/output_types par INVERSION de `studio_node_ports` (ordre = priorité §10.1,
  le port prompt redevient un `text` en queue ; ports `reference` ignorés — ils dérivent
  d'APP_MODES donc de la facette modes) ; comparaison en ESPACE DE FACETTE (`_io_sig`) pour ne pas
  fabriquer de fausses dérives sur la position du `text` ;
- `capabilities` → has_batch/batch_type/has_url_import/has_youtube, le DÉCLARATIF seul
  (`accepts_url` dérivé ; drapeaux mesurés exclus, cf. trou #16).

Contrats tenus (tous VÉRIFIÉS sur le pilote converter) : create = entrée générée marquée
`[manifest-gen app:<id>]` en position alphabétique / update = régénération entière si entrée
marquée (union des champs littéraux relus du FICHIER), chirurgie champ par champ si entrée main
(expression de constantes et multi-ligne REFUSÉES — jamais de mutilation) / noop ; garde
`compile()` avant toute écriture ; réversibilité marqueur-gated (une entrée main n'est JAMAIS
supprimée). ⚠ Vérité d'état lue dans le FICHIER (`ast.literal_eval`), pas dans le module importé
— en apply multi-facettes le module est périmé dès la 1re écriture. Mesuré : diff
identity/ports AUCUN, couleur re-dérivée identique, `studio_redundancy` verdict `derived`,
idempotence (triple noop), chirurgie main = 1 ligne (commentaires intacts), roundtrip 10 apps
**4/N projetables** fidélité OK. `PROJECTED_FACETS` (`builtin/app.py`) = registre des facettes
écrites ; `facet_report`/`codegen_required` le LISENT.

---

## 11. Trous prioritaires (liste actionnable, confrontée au code)

| # | Trou | Facette | Nature |
|---|---|---|---|
| 1 | ✅ **fait (2026-08-11, §10.1)** — describer `input_types` `text`→`document` : le port travail porte `document`, le port prompt fantôme a disparu | F2 | ✅ |
| 2 | modale **batch** rendue par WamaParams (`context:'batch'`) sur **3/10** (anonymizer, avatarizer, imager — cf. F3) ; reste 7 apps hand-built | F3 | adoption |
| 3 | studio `renderNodeParams` appauvri (réinvente WamaParams en dégradant) | F3/F8 | réinvention à supprimer |
| 4 | ✅ **périmé (2026-07-30)** — le front consomme bien `?side=during` (`wama-inspector.js::_startDuring`). Trou RÉEL reformulé : l'**émission** de partiels n'existe que dans le composer (1/10) | F3b | adoption, pas frontend |
| 5 | `select_model()` : composer, transcriber, imager, **reader** (2026-07-31, `61a666f`). Reclaim VRAM ✅ **unifié** (cf. F4). Ce qui restait n'était PAS un trou : enhancer/avatarizer/synthesizer n'ont **aucune sélection automatique à faire** (l'utilisateur désigne, ou le modèle vit hors process) ; describer = unification différée par CLAUDE.md (Phase 4) ; anonymizer = `select_best_models()` couvre un **jeu de classes avec plusieurs modèles** là où la brique n'en choisit qu'un, et lit déjà le catalogue → sur-ensemble légitime | F4 | ✅ pour l'essentiel |
| 5b | **Capacités canoniques** ✅ (2026-07-31, `8ffac24`) : `inputs_required/optional` n'était produit que par **2 découvertes sur 9** → `WamaInputMatch` n'avait rien à comparer (c'est la cause de `input_match_ui` 9/10 KO, pas un défaut d'UI). Les 98 modèles portent désormais `task` + `modalities` + `inputs_*`, zéro clé hors `CANONICAL_CAPABILITIES`. ⚠ La canonicalisation se fait **à la DÉCOUVERTE**, pas dans les `model_config` d'app : frontière **délibérée** (l'app déclare en son vocabulaire, le catalogue est la source unique) | F4 | ✅ |
| 6 | **statuts non uniformes** → 3 tables d'alias | F5 | dette de schéma |
| 7 | ✅ **clos (2026-08-01)** — gating ré-appliqué **par nœud** au RUN (`studio/tasks.py:181`) ET sur toute la surface outils (`tool_accessible`, cf. F7). Le trou était plus large que décrit : `/api/v1/tools/run/` n'était gardé par RIEN (middleware aveugle à `/api/v1/`, auth DRF postérieure au middleware) et `tools/list` annonçait 43 outils à tous. Mesuré après correctif : 22/43 annoncés à un compte `recherche` seul, `create_image` → 403 | F7 | ✅ |
| 8 | **pas de test de contrat** sur la triade tool_api | F6 | robustesse |
| 9 | imager : ✅ résolu — alias `add_to_imager` (`tool_api.py:2042`, `functools.wraps(create_image)` + remap `generation_id`→`item_id`) | F6 | clos |
| 10 | ✅ **résolu (2026-08-11, palier params)** — la facette capte TOUS les `*PARAMS_JSON` (`{primary, schemas}`) ; imager 2 schémas, enhancer 2 schémas | F3 | ✅ |
| 19 | **Divergence store⟷réalité non détectée** (avis critique 2026-08-11) : l'apply est un geste explicite (voulu, sûreté §2.1) mais RIEN ne signale une dérive entre manifestes ingérés et registres — discipline Terraform : jamais d'apply auto, mais un plan/verify qui TOURNE et signale. Brancher `manifest_roundtrip --all` + `verify` dans les contrôles nocturnes (charpente §18 existante) | transverse | détection (pas d'apply auto) |
| 11 | `APP_MODES` (hand-maintained) à dissoudre : domaine=hint UI, mode=dérivé capacités | F2 | dette de conception |
| 12 | anonymizer : refactor yolo/SAM3 en sélecteur modèle groupé + switch capacités (pas un « mode ») | F2/F3 | refactor UX |
| 13 | avatarizer (rapide/qualité=param) + composer (music/bruitage=sélection modèle) : sortir du mécanisme modes | F2 | simplification |
| 14 | **ingest média** (`source_url`→fichier local). ✅ **Mécanisme commun bâti** (2026-07-22, `d8960e5`) : `common/utils/source_ingest.ensure_local_input(instance)`, piloté par une déclaration modèle `WAMA_INGEST = {source, target, mode: media\|audio\|smart, name_field?, size_field?, title_field?}` (stopgap). Les 2 wrappers describer/transcriber sont **fusionnés** dessus (le transcriber **crashait** sans ce maillon). Réutilise `url_ingest.fetch_url_content` / `video_utils.upload_media_from_url`/`download_youtube_audio`. **Reste (côté instance manifeste) :** capacité **F2** `accepts_url`/`accepts_local_path` (→ génère la card au lieu du `show_url` manuel) + **facette F5** `ingest:{…}` qui *projette* vers `WAMA_INGEST` (remplacer le stopgap). Adopter l'URL sur une app = déclarer `WAMA_INGEST` + appeler `ensure_local_input` en tête de tâche. **✅ EXTRACT fait 2026-07-23** : `extract_app` capte `capabilities.accepts_url` + `processing.ingest` (lit `WAMA_INGEST` du modèle d'item via DetailRegistry ; transcriber/describer remontent leur spec, apps sans ingest → None). Reste = la **projection write-back** (manifeste → `WAMA_INGEST`), avec le reste de l'app_gen. | F2/F5 | extract ✅, projection ⏳ |
| 16 | **drapeaux de `capabilities` non régénérables** (mesuré 2026-08-11, pilote converter) : la facette mélange 3 natures — (a) 4 scalaires déclaratifs (✅ projetés), (b) drapeaux d'ÉTAT de conformité (inspector, layout, during_preview… : `_conv()` écrasé par la grille — ils convergeront par la MESURE une fois le code de l'app régénéré, ne JAMAIS les projeter), (c) N/A déclarés (`None` dans `_conv`, ex. `model_help=None` du converter) qui SONT du déclaratif mais vivent dans l'appel `_conv(...)` — leur projection exigerait d'écrire un appel `_conv(model_help=None, …)`, à trancher | F2 | manifeste/frontière déclaré-mesuré |
| 18 | **Couverture tool_api hors catalogue** (audit 2026-08-11 : 43→46 outils) : les 10 apps du catalogue ont leur triade COMPLÈTE (+ double triade enhancer/audio_enhancer, + verbes primaires aliasés) ; le **studio** est ✅ (2026-08-11 : `list_studio_pipelines`/`run_studio_pipeline`/`get_studio_run_status`, run=add+start fusionnés, brique partagée `launch_graph`). Restent NON pilotables par l'assistant, à trancher par usage réel : **model_manager** (lister modèles/capacités — lecture seule utile à l'assistant), **wama_lab** (cam_analyzer, face_analyzer — 13 tâches Celery sans surface outil), **media_library en écriture** (import ; la lecture existe), **translator** (couvert par `translate_text` sync — pas un trou). NB : la facette `tool_api` du manifeste ne capte que la triade canonique — la double triade enhancer lui est invisible (rattacher à #17) | F6 | couverture |
| 17 | **3 facettes dont l'extract ne capte pas (que) du déclaratif** (mesuré 2026-08-11) : `inspector` = booléens de PRÉSENCE (detail/preview_registered) — rien à projeter, le déclaratif réel est la spec Detail d'`apps.py` (même diagnostic que `studio` avant correction) ; `prompts.skills` = NOMS de fichiers `.md` sans contenu ; `tool_api` = présence de la triade + descriptions DÉRIVÉES (les fonctions elles-mêmes = code, tier difficile avec `processing`) | F3/F6 | trous d'extract |
| 15 | **`system_tools` non déclarés** (chromium, ffmpeg, rsvg…) — le volet **librairies** du manifeste est CLOS (2026-08-03/11 : `requires:{kind:library}` dans l'enveloppe, résolu et bloquant, kind + registre `Library` + `write_back_library` livrés, 1er lien transcriber→faster-whisper) ; ce qui manque encore est la déclaration des **outils système** et leur provisionneur commun (cf. `PROJECT_STATUS` §23.6, qui annonçait ce trou sans qu'il ait été reporté ici) | F4/F5 | manifeste |

---

## 12. Renvois & archive

- **Remplace** (archivés `docs/archive/`, consultables) : `UI_MECHANISMS_CONSOLIDATION.md` (mécanismes UI),
  `COMMON_REFACTORING.md` (briques communes), `GENERALIZATION_PLAN.md` (9 axes A→I), `BACKEND_CARTOGRAPHY.md`
  (contrat `BaseModelBackend`), `AUDIT_ROUTE_COMMUNE_2026-07-06.md` (audit prédécesseur route manifeste→app).
- **À réintégrer ici** (non re-tracé en profondeur par la cartographie du 2026-07-22) : le contrat
  `BaseModelBackend` (F4) et le détail des 9 axes de `GENERALIZATION_PLAN` (répartis dans F1–F8). Marqués
  `⚠ À RÉINTÉGRER` là où c'est le cas.
- **Chaînage manifeste** : chaque facette ci-dessus renvoie à `WAMA_MANIFEST_SPEC §Fx` (déclaration) et la
  carte `WAMA_MANIFEST_ARCHITECTURE §3` (facette→mécanisme). Toute évolution d'un mécanisme doit mettre à jour
  la facette correspondante ici ET son pendant manifeste.

---

## 13. PROPOSITION (non validée) — N archétypes déclarés, pas une UI générique

> Issue de la confrontation Twenty (`ROADMAP.md` §16.8), **posée pour discussion**, pas actée.

**Constat** : la génération actuelle ne sait produire que des apps partageant **le même gabarit d'UI**
(`GENERIC_APPS` + `build_generic_runner()`, 10/10). D'où la tentation de viser une « génération d'UI
quelconque ».

**Objection** : Twenty ne génère pas d'UI arbitraire non plus — il génère **dans une coquille**, à des
points d'extension déclarés, avec un contrat de composants. Et l'UI arbitraire est **contraire au
principe 2 de WAMA** (« l'utilisateur doit retrouver les mêmes gestes partout » — l'homogénéité est un
objectif de design). La bonne question n'est donc pas « gabarit ou pas », mais **un archétype contre
plusieurs archétypes déclarés + emplacements** (= principe 4, « spécificités déclarées »).

**Point encourageant : les archétypes existent DÉJÀ dans le code, non déclarés.**

| Archétype | Incarnation actuelle | État |
|---|---|---|
| File d'attente média | `GENERIC_APPS` + `build_generic_runner()` | déclaré, 10/10 |
| Canvas / overlays / mini-carte | `wama_lab/cam_analyzer` | **construit à la main** |
| Timeline / segments / heatmap | éditeur de correction Transcriber | **construit à la main** |

⇒ Le chantier n'est **pas** d'inventer une génération d'UI, mais d'**extraire et déclarer les
archétypes déjà présents**, comme cela a été fait pour F1–F8. À arbitrer avant tout engagement : c'est
un chantier de nature très différente de « générer des UI », et il ne doit pas être lancé par défaut.
