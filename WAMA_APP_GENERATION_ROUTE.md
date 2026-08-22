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
- **Le manifeste `app`** (`manifests/builtin/app.py`) **agrège DÉJÀ les 4 registres + Django** en un
  body 12 facettes ; **write-back : 10 facettes** (`PROJECTED_FACETS` — `access` DB +
  identity/ports/capabilities/studio/modes/prompts/params/inspector/tool_api en CODE marqué
  `[manifest-gen]`) **+ `processing` partiel** (urls.py régénérable, tasks.py mince — gabarits
  `common/manifests/codegen/`, §10.3 marches A — models.py A5 en CREATE-ONLY) ; les corps
  de backends et champs de résultat = marche B.
  L'UI, elle, est générée AU RUNTIME par les briques une fois les registres
  alimentés — **la vue d'ensemble du tunnel et l'INVARIANT de jointure (« rien ne lit le
  manifeste au runtime, un seul point de contact : les registres ») vivent dans
  `WAMA_MANIFEST_ARCHITECTURE.md §1`** (l'autre côté du tunnel — ne pas les redocumenter ici).

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
  via `__init_subclass__` (cf. `ROADMAP.md` §Gouvernance des ressources). Depuis le **2026-08-12**, cette
  déclaration porte aussi **l'identité du modèle** (clé d'owner `<backend>:<pid>#<model_key>`) et
  `process` est enveloppé à son tour pour horodater l'USAGE — c'est ce qui rend la RÉSIDENCE et
  l'INACTIVITÉ visibles d'un process à l'autre (`resident_models()` / `idle_models()`), là où
  `AIModel.is_loaded` ne pouvait rien dire : rien ne l'écrit, et un singleton Python ne traverse pas
  les process. **ADOPTION 7/10 apps** — imager,
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
  `tool_api.py:2065`). **Deux consommateurs du MÊME contrat** : l'assistant IA (`api/v1/views.py:18`) ET le
  studio (`build_generic_runner:149` fait `getattr(tool_api,f'add_to_{app}')` + filtre par
  `inspect.signature` + exige `item_id` en retour). **Le studio ne connaît aucune app en dur.**
  Depuis A4 (2026-08-12) : `start`/`status` d'une app portée sont CONSTRUITS à l'import depuis
  l'entrée déclarative `TRIAD_SPECS` (`tool_api.py:2152`, signature synthétisée — descriptions
  dérivées inchangées) ; `add_to_<app>` reste de la glu d'app (marche B). Converter + reader portés.
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
- Outils au registre (`TOOL_REGISTRY`) : **51**
- Outils décrits (`tool_descriptions()`, dérivé) : **51/51**
- Arguments documentés (types/choix/bornes/défauts) : **195**
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

### §10.3 — Write-back (code-gen) depuis le manifeste — `access` ✅ (DB) + `identity`/`ports`/`capabilities`/`studio`/`modes`/`prompts`/`params` ✅ (2026-08-11) + `inspector` ✅ (A3) + `tool_api` ✅ (A4) ; `processing` = projection PARTIELLE assumée (urls comparable ; tasks A2b et models A5 en CREATE-ONLY — les corps/champs restants = marche B)

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
  **Composition SEMÉE (2026-08-12)** : 8 libraries ajoutées au corpus (extraction mécanique
  importlib.metadata — le librarian LLM reste pour le mode `--repo`, lib non installée) →
  `requires` transcriber = **4 modèles + 9 libraries, 13/13 résolus**. Strates actées
  (SPEC §7.4-5) : socle plateforme (jamais cité) / libraries métier (requires) / outils
  système (trou #15). **Cible finale actée avec Fabien : générer une 11ᵉ app DE ZÉRO —
  Translator sur LibreTranslate** (librarian `--repo` = pilote 2 ; `translate_text` reste le
  verbe tool_api générique, LibreTranslate = backend dédié ; modes realtime + batch dans le
  schéma existant ; le PDF-mise-en-forme = pipeline STUDIO d'abord, app one-click ensuite si
  besoin) — après fin de la route + finalisation du portage.
  Micro-marche AVANT B ✅ LIVRÉE (2026-08-12, question Fabien) : `model` ajouté aux DOSSIERS
  de `manifest_export` — les modèles sont DÉRIVÉS des `requires` des apps (∪ refresh des déjà
  exportés, même logique que les libraries sans semis manuel) → **91 manifestes modèle écrits,
  0 refusé** (le lien `AIModel.source` 91/91 se retrouve exactement), corpus total **110**.
  Noms de fichiers assainis (`:` interdit sous Windows → `transcriber__whisper.json`,
  réversible ; garde anti-collision `__`). L'export fichier ne sert que la revue humaine et
  le few-shot du rôle codegen — la composition résout les requires par extraction LIVE.

- **S. BAC À SABLE — jumelle EXÉCUTABLE (actée Fabien 2026-08-18, marche suivante).** Constat :
  le harnais C régénère EN PLACE (strip→write-back→mesure→restore) — il juge des artefacts,
  jamais une app QUI TOURNE. Or la grille mesure le DÉCLARÉ, le roundtrip le PROJETABLE :
  seule une jumelle exécutable mesure le TOUT — c'est le meilleur détecteur des « trous »
  laissés hors mécanismes (l'écart visuel/fonctionnel entre l'app en place et sa régénérée
  EST la liste des trous). Principe : régénérer une app existante sous un identifiant
  distinct (`converter_01`) qui COEXISTE avec l'app en place → comparaison visuelle
  (Playwright côte à côte) + diff code, puis cycle **ajouter / tester / supprimer**.
  Contrats actés :
  1. **Identifiant** : suffixe `_NN` sur l'app label (`converter_01` — identifiant Python et
     slug URL valides, `/converter-01/`) ; tables Django séparées par construction (préfixe
     app_label) → ZÉRO collision de données avec l'app en place.
  2. **Marqueur déclaratif** : l'entrée APP_CATALOG de la jumelle porte
     `generated_from='converter'` + l'id du run de génération → jumelles ÉNUMÉRABLES
     (nettoyage sûr, jamais orphelines) + badge « BAC À SABLE » dans l'UI.
  3. **Gating dev-only** (app_access) : invisibles des non-devs.
  4. **Cycle outillé, jamais manuel** : `manage.py app_sandbox create <app>` / `drop <app_NN>`
     (drop = migrate zero + retrait INSTALLED_APPS/urls/registres — symétrique et complet).
  5. **La jumelle RÉFÉRENCE le monde, elle ne le duplique pas** : même catalogue `AIModel`
     (lecture), mêmes briques common, mêmes workers — on régénère l'APP, pas la plateforme.
  6. **Diff normalisé** : dé-suffixer avant diff (étend le principe du harnais C — juger des
     artefacts NORMALISÉS, jamais du byte à byte) ; Playwright = pages côte à côte.
  7. **Pilote : `converter_01`** (app la plus simple, 100 % grille, pilote historique de C) ;
     les facettes encore non-write-back (inspector/models/processing/tool_api) apparaîtront
     comme manques VISIBLES de la jumelle — c'est le but, pas un préalable.
  **✅ S1 LIVRÉE (2026-08-18)** — jumelle TÉMOIN opérationnelle : `manage.py app_sandbox
  create converter` → `converter_01` qui REND (page 200, reverse OK, tables `converter_01_*`
  migrées, badge catalogue, grille inchangée à 10 apps). Mécanisme : `common/sandbox.py`
  (registre `wama/sandbox_apps.json` GITIGNORÉ + injections boot settings/urls/permissions/
  app_registry, garde anti-registre-orphelin) + commande `app_sandbox` (create/drop/list,
  renommages mécaniques 4 familles + dossiers templates/static, migrations FRAÎCHES en
  sous-process). **3 pièges MESURÉS au pilote** : ① `related_name` des relations vers des
  modèles EXTERNES (User) = collision E304/E305 → suffixés par `_patch_related_names`
  (les relations INTERNES gardent leur nom — `batch.items` consommé par le code) ;
  ② œuf-poule du drop : une jumelle cassée bloque le boot du sous-process → `migrate zero
  --skip-checks` obligatoire ; ③ l'anonyme PASSE le gating (convention plateforme « tier
  anonyme », identique aux autres apps) — le dev-only ne vaut que pour les comptes
  authentifiés. **S2 EN COURS (2026-08-18)** : outil `app_sandbox substitute <label> <cible>`
  LIVRÉ — génère depuis le manifeste LIVE de la SOURCE (jamais modifiée), suffixe, écrit dans
  la jumelle, témoin préservé en `.temoin`, re-mesure (check + makemigrations + smoke),
  ÉCHEC → auto-revert COMPLET (migrations divergentes désappliquées/retirées — défaut du
  1er run corrigé). **Premiers verdicts converter_01** : `apps` ✅ tient (29 lignes d'écart) ·
  `urls` ✅ tient (82) · `models` ❌ TROU — schéma DIVERGENT, 155 lignes (le gabarit A5 ne
  dérive que la facette params ; le schéma réel porte ConversionProfile entier + champs
  batch/options) · `tasks` ❌ TROU — smoke KO, 226 lignes (la glu réelle dépasse le gabarit).
  **RE-VERDICTS (même journée)** — analyse des 2 « trous » : `tasks` était un FAUX négatif
  (collatéral de l'incohérence DB du revert models, réparée) — le gabarit A2b préserve le NOM
  de tâche que les vues importent et délègue au squelette commun : **✅ tient** (le corps =
  trou DÉCLARÉ marche B). `models` était le seul vrai trou → **comblé par la facette `data`**
  (marche S2) : spine de données INTROSPECTÉ — tous les modèles Django de l'app, champs
  sérialisés par `MigrationWriter.serialize` (LE sérialiseur des migrations : upload_to
  déconstructibles, choices, defaults callables — fidélité de schéma PAR CONSTRUCTION),
  manager par défaut capturé (ScopedManager — les vues appellent visible_to()), meta
  ordering/unique_together ; `models_gen` rend depuis `data` quand elle est là (repli
  squelette A5 pour la création DE ZÉRO). **Verdict mesurable atteint : makemigrations « No
  changes » sur la jumelle.** État pilote : **4/4 substitutions TIENNENT** (apps 29 l. d'écart
  · urls 82 · tasks 226 · models 145 — ces diffs = la GLU documentée : properties,
  WAMA_INGEST, corps des tâches), jumelle en service avec les 4 fichiers GÉNÉRÉS.
  2 pièges d'OUTIL mesurés/corrigés en route : sur-suffixage des related_name INTERNES sur
  code généré (kwargs alphabétiques : le `to=` vient APRÈS related_name → lire l'appel
  COMPLET à parenthèses équilibrées), et la famille de renommage `'src.` (réfs par app_label
  des FK sérialisées).
  **S2 — JALON FINAL (même journée) : 6/6 substitutions TIENNENT, la jumelle est une app
  ESSENTIELLEMENT GÉNÉRÉE qui tourne.** ⑤ `views_gen` ÉCRIT (la pièce annoncée au cadrage
  A0) : UNE définition par callable du urls généré — idiomes conventionnels paramétrés par
  le manifeste (item + batch/FK DÉRIVÉS de la facette data, tâche processing.tasks,
  fabrique `make_queue_manipulation_views_direct`, briques begin_processing/stop_instance/
  duplicate_instance/apply_queue_sort_filter/console) + STUBS 501 marqués TROU DE GLU pour
  le hors-convention (card_html, batch_preview/create, consolidate, extra_routes) — la page
  boote, la fonctionnalité manque VISIBLEMENT. v1 = forme FK-DIRECTE (converter) ; la forme
  à modèle de liaison est un trou déclaré. **views tient** (diff glu 1341 l.).
  ⑥ `templates_gen` v1 ÉCRIT (multi-fichiers — `substitute` étendu, revert multi-fichiers) :
  index CONVENTIONNEL depuis les briques communes (_global_progress, _new_item_card
  paramétrée d'identity.input_extensions, _queue_toolbar, boucle _batch_card) + card
  GÉNÉRIQUE minimale — l'écart visuel avec la vraie card EST la mesure. **templates tient**
  (diff 404 l.). Restent COPIÉS (glu/marche B) : base.html, card réelle, JS d'app, params.py
  (write-back existant, cible à câbler), backends/, utils/. Prochain geste : Playwright
  côte à côte /converter/ ↔ /converter_01/ (Fabien) = la lecture VISUELLE des trous.
  **ARBITRAGE GLU (question Fabien 18/08 : template générique complétable vs glu par app
  sur règles ?) — HYBRIDE, frontière MESURÉE :** ① PAS de template d'app copié-complété
  (un template copié dérive et devient une 2ᵉ source de vérité, irré-générable sans
  écraser les éditions) → le conventionnel est RENDU par les gabarits depuis le manifeste
  (re-rendable, comparable, diffable — c'est ce que S2 a prouvé). ② La glu restante est
  remplie PAR APP par le rôle LLM `codegen` CONTRAINT (marche B telle qu'actée : règles
  strictes façon librarian, contrat BaseModelBackend, manifeste composé requires
  app→model→library, few-shot = le corpus des 10 apps existantes — qui JOUE le rôle de
  « bibliothèque de templates » sans en être un — interdits explicites, jugé par le
  harnais, jamais auto-appliqué), en ne visant QUE les emplacements marqués `TROU DE GLU`
  (stubs 501, commentaires [manifest-gen]). ③ La frontière BOUGE par la mesure : une glu
  qui réapparaît semblable dans 2+ apps au diff du détecteur = candidate /brique ou
  gabarit (promotion vers le commun) — le bac à sable NOURRIT le commun, le template
  figé n'existe jamais.
  La cible « Translator DE ZÉRO » (ci-dessus) devient le cas « create sans generated_from » du
  même outil : le bac à sable est l'étape commune aux deux chemins (régénérer ≈ créer).

**Cadrage A0 — la convention RÉELLE, mesurée (2026-08-11, balayage 6 cibles × 10 apps) :**
- **urls.py** : AUCUNE app ne colle à `STANDARD_ENDPOINTS` — cette liste était une CIBLE que le
  manifeste affirmait comme réalité pour les 10 apps (mensonge d'extraction, corrigé en A1).
  `status` n'existe QUE chez converter ; la convention réelle est `progress` + `global_progress`.
  Noyau conventionnel réel (~26 routes) : cycle (index/upload/start/stop/download/delete/
  duplicate/start_all/clear_all/download_all) + `card_html`/`console`/`about`/`help` +
  manipulation (reorder/move_to_batch/remove_from_batch/consolidate) + famille `batch_*`.
  Déviants : anonymizer (suffixe `_media`, pas de manipulation), imager (batch inversé
  `import_batch`/`start_batch`), enhancer (surface DOUBLÉE `audio_*`), synthesizer
  (`synthesis_card_html`). Extras légitimes par app (quick_convert, profile_*, edit…) → À DÉCLARER.
- **tasks** : squelette convergent 10/10 — garde `refuse_crash_redelivery` sur la tâche
  principale, `reconcile_orphaned_running` TOUJOURS dans la vue index, `estimate()` en vue +
  `record_run` en tâche (jamais `ModelRuntimeStat` en direct). Trous d'ADOPTION sur les tâches
  secondaires (anonymizer 1/4, reader `analyze`, transcriber `enrich`) → bac « porter ».
- **apps.py** : 10/10 `register_app_detail(app, Model, callable)` — mais le callable est un
  mapping app-spécifique (kwargs de `build_detail`) : rendre `inspector` projetable exige de
  rendre la registration DÉCLARATIVE (detail_registry acceptant une spec-donnée) — bac
  « porter » AVANT gabarit. 3 idiomes preview (wrapper 6/10, `PreviewRegistry.register` bas
  niveau 3/10, absent imager) ; `register_batch_sync` 9/10 (converter = FK directe).
- **tool_api** : registre CENTRAL (`wama/tool_api.py::TOOL_REGISTRY`) — la cible du gabarit est
  une ENTRÉE de registre, pas un fichier par app. Triade conventionnelle stable ; 4 noms
  historiques rattrapés par alias `add_to_*` ; enhancer = triade doublée.
- **models.py** : 9/10 = spine `Item(ProcessingTimeMixin, ScopedVisibility)` +
  `Batch(BatchMixin, ScopedVisibility)` + table de liaison ; réglages en champs individuels
  9/10. **Le converter est LE déviant double (réglages `options` JSON + batch FK-direct sans
  BatchMixin)** ⇒ le pilote « squelette complet » se juge sur TRANSCRIBER (conforme au spine) ;
  converter reste le pilote des paliers registres/urls. Idiomes déviants → à déclarer
  (`params_storage`, liaison batch).
- **Frontière actée** : gabarit = noyau conventionnel MESURÉ ci-dessus ; le manifeste déclare
  les écarts légitimes ; les corps de backends = marche B. **Ordre des paliers A** : A1 routes
  réelles dans la facette `processing` (extraction URLconf + `extra_routes` déclarés) + gabarit
  `urls.py` ; A2 squelette `tasks.py` ; A3 `apps.py` (après detail déclaratif) ; A4 entrée
  triade tool_api ; A5 `models.py` (dernier : migrations + idiomes de stockage).

**Palier A1 ✅ LIVRÉ (2026-08-11, 3ᵉ session) — routes réelles + gabarit `urls.py`** :
- Paquet **`common/manifests/codegen/`** créé (`urls_gen.py`) : `ROUTE_TABLE` = noyau
  conventionnel MESURÉ (idiome du pilote, ~29 noms) ; `app_routes()` lit les routes RÉELLES de
  l'URLconf et sépare compressées/déclarées ; `render_urls()` régénère un fichier complet
  (JAMAIS partiel : une route non couverte, ou à vue inexprimable, refuse la génération).
- **Extraction corrigée** : `processing.endpoints` = routes réelles (le mensonge
  `STANDARD_ENDPOINTS` × 10 apps est corrigé ; la constante reste comme cible documentaire) +
  `extra_routes` in extenso pour toute déviation. **Canon de vue par IDENTITÉ d'attribut** du
  module `views` — pas par `__module__` : une vue de fabrique commune
  (make_queue_manipulation_views) porte le module de la fabrique, chemin runtime non
  importable ; leçon payée deux fois dans la session (E/S studio, domains liste).
- Projecteur `_project_processing` (cible urls SEULE — la facette reste `codegen_required`
  tant que models/tasks ne se génèrent pas) : mêmes contrats (main comparé sémantiquement
  name→(motif, vue) via ast, jamais réécrit ; absent → généré marqué ; marqué → régénéré).
  Strip et un_write_back étendus au fichier urls.py.
- **Rattrapage auto-critique (même session)** : 4 écarts LATENTS corrigés — ① include()/routes
  anonymes/doublons de nom ne sont plus SAUTÉS mais déclarés `view: None` (ils empoisonnent la
  couverture — les sauter aurait fait mentir l'axe ① du harnais : le fichier régénéré sans eux
  se ré-extrait identique au manifeste qui les ignorait) ; ② import des vues pointées corrigé
  (module porteur, pas un préfixe intermédiaire) ; ③ les extras gardent l'ORDRE de l'URLconf
  (l'ordre est la sémantique de résolution Django, l'alphabétique risquait un shadowing) ;
  ④ `validate_app_body` valide `extra_routes` (corpus = matériel d'apprentissage LLM,
  rejet à l'ingest). Aucun n'était actif sur les 10 apps (vérifié) ; harnais re-CONFORME.
- **Mesuré** : couverture COMPLÈTE 9/10 apps (converter 27/34 compressées + 7 déclarées ;
  synthesizer = 2 vues inexprimables `voice_preview_diagnostic`/`stream_test`, correctement
  refusées) ; fidélité roundtrip 10/10 OK ; corpus régénéré.

**Palier A2a ✅ LIVRÉ (2026-08-11, 3ᵉ session) — brique `task_skeleton` + 1er adopteur converter** :
- Constat A0 : le `tasks.py` d'une app existante contient de la GLU réelle → il ne peut pas
  passer le juge strip-régénération avant la marche B. Mais le squelette conventionnel était
  DUPLIQUÉ 10× avec dérive (tâches secondaires sans gardes : anonymizer 1/4, reader `analyze`,
  transcriber `enrich`). Règle maison appliquée : **brique commune d'abord**, le gabarit
  viendra rendre un fichier mince (brique + trou de glu pour B).
- **`common/utils/task_skeleton.run_item_task`** : close_old_connections → chargement item →
  `refuse_crash_redelivery` → progress 0 → `ensure_local_input` (no-op sans WAMA_INGEST) →
  chrono → glu `process(item, ctx)` → SUCCESS + progress 100 + `processing_seconds` →
  `record_run` + `notify_job` best-effort ; FAILURE + `error_field` + console ✗ sur exception.
  Contrat de glu : `ctx.progress`/`ctx.console`, retour `{fields, eta:(clé,taille,unité),
  label}` ; le nettoyage d'échec (fichiers temp) reste DANS la glu ; `progress_fn` déclarable
  (throttle transcriber) — jamais de `if app ==` dans la brique.
- **Converter porté** (TRADUIRE et REMPLACER) : `convert_media_task` = 5 lignes + glu
  `_convert` (routage format, presets, quick-convert in-place atomique). Critères de grille
  `crash_redelivery_guard` et `eta_seeded` reconnaissent la brique (`|run_item_task`).
- **Validé empiriquement** : exécution RÉELLE synchrone (job PNG→WebP de test : SUCCESS,
  progress 100, processing_seconds posé, sortie créée, artefacts nettoyés) ; grille converter
  93 % identique ; harnais CONFORME. ⚠ Prod : restart des workers Celery WSL2 requis pour
  charger le nouveau `tasks.py`.
- **2ᵉ adopteur : reader ✅ (même session)** — `read_document_task` porté (glu `_read` :
  extraction native PDF en chemin court, sélection backend OCR, mise en forme LLM). La
  pression d'universalité a élargi le contrat DÉCLARATIVEMENT (jamais de cas d'app dans la
  brique) : `ctx.progress(pct, msg=None)` + `progress_fn(item, pct, msg)` (le front reader
  polle un dict `{'pct','msg'}`), `console_success` (ligne ✓ personnalisée), retour anticipé
  = flux de succès standard, `_item_label` (conventions de nommage du spine). **ETA intact
  par construction** : la glu retourne (clé, taille, unité) — mêmes clés
  (`reader:fitz_direct`/`reader:<backend>`, `converter:<type>:<fmt>`), même `process_seconds`
  (chrono post-ingest), `load_seconds=None` — la continuité d'apprentissage
  (`ModelRuntimeStat`/EMA) est préservée, `estimate()` côté vues non touché.
- **Requalification de la « dérive » A0** : `analyze` (reader) et `enrich` (transcriber) ne
  sont PAS des tâches d'item sans gardes — c'est une autre ESPÈCE (enrichissement à la
  demande : ni statut ni progress, contrat `{'ok':…}`). Les forcer dans `run_item_task`
  corromprait l'état (FAILURE sur un item déjà SUCCESS). Hors contrat volontaire, documenté
  dans la brique. ~~La vraie dette gardes restante = tâches de traitement de l'anonymizer~~
  → **SOLDÉE le 2026-08-13** : ces deux tâches n'existent plus. Le second pipeline
  multi-modèles (chaîne Celery + transport Redis des masques) a été supprimé, `Anonymize`
  porte N modèles dans la tâche unique — qui, elle, a déjà les gardes. L'anonymizer n'a plus
  qu'un seul chemin d'exécution.
- **Le harnais a attrapé un écart RÉEL au passage** (reader NON CONFORME au 1er run) : les
  descriptions tool_api rendaient le défaut de schéma par `%r` — `ReadingItem.Backend.AUTO`
  (params main `derive_from_model`) vs `'auto'` (params régénéré littéral), deux surfaces
  pour une même valeur. Normalisé À LA SOURCE (`tool_api._describe_arg` : un défaut
  str-compatible se rend par sa valeur). Harnais reader ensuite **CONFORME** (strip 4 cibles,
  grille 87 % identique, smoke identique) — **2ᵉ app à passer le strip-régénération complet**.
**Vérification post-A5 (2026-08-12, 5ᵉ session) — régénération transcriber HORS ARBRE,
3ᵉ app CONFORME au harnais** : rendus des gabarits vers scratch + dry-run write_back + diff
vs réel (jamais d'écrasement). Registres 6/6 noop ; `app_name='wama.transcriber'` = ligne
INERTE (include racine à tuple) ; **piège CREATE-ONLY attrapé et corrigé** — la glu Celery
du transcriber vit dans workers.py (pas de tasks.py) : « absent » = aucune tâche déclarée
ne vit ailleurs, sinon création refusée ; tasks.py/models.py ajoutés au restore du harnais.
Skips ASSUMÉS : detail = adapter code (A3a), triade = vraie glu (routage `preprocess_audio`,
purge segments, aperçu partiel temps réel) — un vocabulaire de hooks déclaratifs
(`start_hook`/`task_router`/sources d'aperçu) reste possible, à trancher pendant B.

**Palier A5 ✅ LIVRÉ (2026-08-12) — gabarit `models_gen`, MARCHE A CLOSE (A1→A5)** :
la facette `processing` porte **`model_spec`** (spine MESURÉ par introspection Django —
identité des classes, user/fichier d'entrée/ingest, ordering, couverture params, batch +
liaison via `batch_sync.SYNCED`). `render_models` rend le squelette COMPLET : spine F5
(user, FileField, WAMA_INGEST, task_id/STATUS_CHOICES/progress/error_message, Meta,
`__str__`, `filename`) + champs d'option = l'INVERSE de `derive_from_model`
(select→CharField+choices, toggle→BooleanField, number/range→Integer/FloatField,
textarea→TextField) + Batch/liaison + TROU marqué pour les champs de RÉSULTAT (marche B).
Projecteur `_project_models` **CREATE-ONLY DURCI** : un models.py existant porte des
MIGRATIONS appliquées — jamais comparé, jamais réécrit ; `makemigrations` reste un geste
MAIN (le moteur ne touche jamais la base, invariant du harnais). **Juge du rendu** (pilotes
transcriber = spine conforme, + reader) : compile, **ZÉRO champ inventé** ; reader 13/18
couverts (5 restants = champs de résultat, le trou B exact), transcriber 15/38 (23 = glu
métier réelle : correction/résumé/segments — bac B). Harnais converter + reader re-CONFORMES
avec l'extraction enrichie ; roundtrip 10/10 ; grille inchangée ; validation `model_spec` à
l'ingest. Le juge complet du squelette neuf = pilote B (Translator).

**Palier A4 ✅ LIVRÉ (2026-08-12) — triades DÉCLARATIVES `TRIAD_SPECS`, facette `tool_api`
PROJETABLE ; A4 CLOS** : mesure A0 confirmée — `start_<app>`/`get_<app>_status` étaient un
squelette conventionnel dupliqué par app. **A4a** : entrée déclarative `TRIAD_SPECS`
(tool_api.py) + `_register_triads()` construit les fonctions à l'import (signature
SYNTHÉTISÉE `__signature__` : descriptions dérivées, `primary_arg_name`, `sanitize_tool_args`
strictement inchangés) ; `add_to_<app>` reste de la GLU (marche B) ; converter + reader
portés (TRADUIRE et REMPLACER) — **parité prouvée byte à byte** (baseline avant/après :
descriptions des 6 outils, signatures, statuts réels, chemins d'erreur) ; critère de grille
`tool_api` passé au registre RUNTIME (le littéral ne dit plus la vérité — présence ≠ vie).
**A4b** : la facette `tool_api` porte `triad_spec` (le déclaratif ; noms + descriptions =
famille mesurée) ; projecteur `_project_tool_api` = entrée-valeur `TRIAD_SPECS` (même moteur
que PROMPT_TARGETS, `_write_value_entry` généralisé `champ`/`main_reason`) ; strip +
`un_write_back` + harnais étendus (tool_api.py aux fichiers cibles) ; validation
`triad_spec` à l'ingest (leçon A1 ④) ; `tool_api` dans PROJECTED_FACETS (sans triad_spec =
skip motivé, précédent inspector). **Harnais : converter CONFORME 7 cibles strippées
(triad_entry compris), reader CONFORME 6 cibles** ; roundtrip 10/10 OK, converter **9/10
projetable** (ne reste que `processing` partiel) ; grille 10/10 identique ; corpus régénéré.

**Palier A3b ✅ LIVRÉ (2026-08-12) — gabarit `apps_gen`, facette `inspector` PROJETABLE ;
A3 CLOS** : `codegen/apps_gen.render_apps` rend le `ready()` complet depuis les déclarations
(batch_sync via le nouveau registre de mesure `batch_sync.SYNCED` → `processing.
batch_link_model` ; preview ; `detail_spec`) + `identity.verbose_name` (AppConfig, extrait,
non projeté vers APP_CATALOG). Rendu REFUSÉ pour une app à adapter code (transcriber —
jamais de fichier qui perdrait une logique) ; fichier main → noop (le runtime qu'il produit
EST la facette) ; `inspector` ajoutée à PROJECTED_FACETS. **Harnais : converter CONFORME
avec 6 cibles strippées (apps.py compris), reader CONFORME 5 cibles (batch_sync régénéré)** ;
roundtrip monte partout (converter 8/10 — reste `processing` partiel + `tool_api`). Limite
consignée : kwargs étendus de preview (describer/enhancer) non retenus par PreviewRegistry —
bac « porter » avant leur régénération.

> **Retombée inattendue de la facette `inspector` (2026-08-20)** — `detail_registry` s'est révélé
> être un **registre `app → modèle` universel**, donc bien plus qu'un mécanisme d'inspecteur : le
> **journal transversal** (`WAMA_MEMORY.md §9bis`) en DÉRIVE ses 12 sources, sans une ligne dans
> les apps ; une app qui enregistre son adapter y entre gratuitement. Même levier proposé pour
> **tool_api §9ter** (`list_my_items` / `get_item_detail` en remplacement des ~10
> `get_<app>_status` écrits à la main). Enseignement pour la route : **un registre `app → modèle`
> a plus de consommateurs que celui pour lequel on l'a écrit** — le déclarer largement (et non
> comme détail d'implémentation d'une facette) est ce qui rend ces retombées possibles.
>
> ⚠ Et un rappel de prudence gagné le même jour : `unified_detail` **est consommé** par
> `wama-inspector.js::fillDetail()` (l.328), qui dérive l'URL par
> `replace('/preview/', '/detail/')` — invisible à toute recherche du chemin. Ne pas conclure
> qu'un endpoint dort sans avoir cherché les URL **construites**.

**Palier A3a ✅ LIVRÉ (2026-08-12) — Detail/Preview DÉCLARATIFS (déblocage de la facette
`inspector`)** : `register_app_detail_spec(app, Model, spec)` dans `detail_registry` — la
registration devient une SPEC-donnée (mapping build_detail : champs/constantes,
`extra` étiquetés avec `display`, `extra_from_params` (JSON porteur ou champs individuels),
`aliases` canoniques) résolue par l'adapter GÉNÉRIQUE `detail_from_spec` ; l'adapter code
reste le chemin des logiques irréductibles (transcriber…). **2 adopteurs portés** (converter
spec 5 clés, reader spec avec const/`display`/engine_effective) — **parité prouvée sur 10
items RÉELS** (dicts identiques clé pour clé vs anciens closures). La facette `inspector`
porte désormais `detail_spec` + `preview` (champs PreviewRegistry, déjà des données) au lieu
de 2 booléens. Harnais converter + reader CONFORMES ; fidélité 10/10. **Reste A3b** : gabarit
`apps_gen.py` (ready() rendu depuis inspector.detail_spec/preview + batch_sync) — la facette
passera alors en projetable.

- **A2b ✅ (même session) — gabarit `tasks_gen.py`** : la facette `processing` porte désormais
  `tasks` (AST de tasks.py/workers.py — {function, task_name, lifecycle} ; heuristique
  lifecycle = `run_item_task` ou SUCCESS+FAILURE dans le segment ; limite connue :
  `transcribe_without_preprocessing` classée non-lifecycle par délégation interne — à
  raffiner par déclaration) et `item_model` (accesseur `DetailRegistry.get`). `render_tasks`
  rend le fichier MINCE (une tâche = 5 lignes `run_item_task` + trou de glu
  `NotImplementedError` marqué) ; projecteur `_project_tasks` **CREATE-ONLY** : un tasks.py
  existant — même marqué — n'est JAMAIS comparé ni régénéré (ses trous ont pu être remplis
  par B ; le régénérer effacerait les corps). Vérifié : rendu converter compile, critères
  grille (crash guard, ETA) satisfaits sur le rendu, fidélité 10/10, harnais converter et
  reader CONFORMES. **Le juge COMPLET de ce gabarit est le pilote B** (générer transcriber :
  gabarit → trous → LLM → harnais). A2 est CLOS ; adopteurs task_skeleton suivants au fil
  des chantiers d'app. **Harnais C : VERDICT CONFORME
  avec strip de 5 cibles dont urls.py** — le urls.py généré rend les 34 routes, grille 93 %
  identique, smoke identique, ré-extraction identique. Piège levé : les system checks Django
  chargent l'URLconf racine au démarrage de toute commande → `requires_system_checks = []`
  sur le harnais (la phase apply démarre urls.py strippé).

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

### §10.4 — Marche D (APRÈS B) — CAPACITÉS HÉRITÉES : l'app agrège, le studio est aussi une bibliothèque

> **ACTÉ avec Fabien le 2026-08-12 (5ᵉ session) — chantier NON démarré, séquencé APRÈS la
> marche B** (il en bénéficie : harnais et gabarits jugeront les shims comme le reste ; le
> construire avant serait de la généralisation par anticipation). Cadre : WAMA = **agrégateur
> de capacités** (vision Fabien) — l'homogénéité vient de capacités déclarées et composées,
> pas d'apps qui recopient les capacités des autres.

**La doctrine des trois espèces de chaînage** (classement par PROPRIÉTAIRE, pas par
complexité d'app — c'est elle qui lève l'incohérence « tout chaînage = studio ») :

| Espèce | Définition | Exemple | Domicile |
|---|---|---|---|
| **Agrément** | étape optionnelle qui ne change pas l'identité de l'app | denoise avant transcription | case à cocher DANS l'app, capacité HÉRITÉE d'ailleurs |
| **Métier** | la chaîne EST l'identité de l'app (UI dédiée) | transcription → diarisation → vérification → correction | dans l'app (l'éditeur de correction ne sera jamais un nœud studio) |
| **Production** | assemblage inter-apps, topologie variable, choix utilisateur | TTS → avatar | studio (précédent avatarizer : mode TTS RETIRÉ de l'app, le studio chaîne) |

**Le mécanisme — déclarer, pas coder** (presque toute la tuyauterie existe) :
1. **Capacités canoniques côté APPS** : le vocabulaire indexé sur la TÂCHE existe côté modèles
   (98 modèles en capacités canoniques) — le porter au niveau app : l'enhancer FOURNIT
   `denoise_audio`, le synthesizer `tts`… (`provides`).
2. **Arête `uses` au manifeste** : nouvelle espèce d'arête à côté de `requires` —
   `uses: {capability: denoise_audio, when: pre_input, optional: true}`. L'UI (case à cocher)
   s'auto-génère de la déclaration, métadonnée-driven comme le reste. Formalisme : SPEC §7.5.
3. **Réalisation par le PIVOT EXISTANT** : une capacité héritée = micro-pipeline (2 nœuds)
   exécuté par `launch_graph`/`execute_tool` — **le studio comme BIBLIOTHÈQUE, pas comme UI**.
   Aucun nouveau moteur (rappel : pas de Ray/Slurm — gouverneur + Celery).
4. **Articulation avec les hooks de triade (débat A4)** : le hook `pre_start` n'est PAS de la
   glu libre — c'est un **shim DÉRIVÉ de l'arête `uses`** (« appelle la capacité héritée »).
   Le 2ᵉ consommateur du vocabulaire de hooks est le système de capacités lui-même — ce qui
   lève l'objection n=1 qui avait fait assumer la triade transcriber en main.
5. **Interop wama-lab ↔ studio** : une `StudioPipeline` SAUVEGARDÉE référencée par une app
   comme capacité composite (construire dans le studio → enregistrer → intégrer dans l'app).
   Le maillon = **write-back du kind `pipeline`** (extract existe, projection à faire).

**Pilote désigné** : `preprocess_audio` du transcriber → capacité `denoise_audio` héritée de
l'enhancer. ⚠ PAS gratuit : le preprocessing fenêtré disque→disque a été construit contre un
OOM vécu ; le passage par la capacité change l'ordonnancement VRAM (gouverneur), l'ETA et
ajoute un intermédiaire — **A/B OBJECTIF obligatoire** (qualité + VRAM + durée), jamais au jugé.

**Portage wama-lab (séquence actée, du plus outillé au moins formalisé)** :
① modèles → catalogue `AIModel` + manifestes `model` (write-back + export corpus : FAITS) ;
② fonctions mathématiques → kind `function` (write-back `UserFunction` : FAIT ; vision
« fonction = card » du monde DATA) ; ③ pipelines → kind `pipeline` (write-back À FAIRE — LE
maillon de l'interop) ; ④ plugins de visualisation → monde DATA (dernier, le moins formalisé).

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
| 18 | **Couverture tool_api hors catalogue** (audit 2026-08-11 : 43→46 outils ; re-vérifié RUNTIME 2026-08-17 : 46→**48**) : les 10 apps du catalogue ont leur triade COMPLÈTE (+ double triade enhancer/audio_enhancer, + verbes primaires aliasés) ; le **studio** est ✅ ; **model_manager LECTURE ✅ (2026-08-17)** — `list_ai_models` (filtres app/task/modality/downloaded, proposés exclus par défaut) + `get_ai_model` (fiche complète licence/auteur/capacités/empreintes), **transverses** (alignés sur l'ouverture du méta-catalogue à tous les selects via WamaModelHelp ; une future action d'ÉCRITURE serait gardée `model_manager`). Restent à trancher par usage réel : **wama_lab** (cam_analyzer, face_analyzer — 13 tâches Celery sans surface outil), **media_library en écriture** (import ; la lecture existe). ⚠ À VÉRIFIER (constat 17/08) : `/model-manager/api/models/db/` (source de WamaModelHelp) est sous le gating PAR CHEMIN de l'app model_manager (dev-only) — l'aide-modèle est-elle silencieusement INERTE pour un compte non-dev ? (le fetch avale l'échec sans erreur console). NB : la facette `tool_api` du manifeste ne capte que la triade canonique — la double triade enhancer lui est invisible (rattacher à #17) | F6 | couverture |
| 17 | **3 facettes dont l'extract ne capte pas (que) du déclaratif** (mesuré 2026-08-11) : `inspector` = booléens de PRÉSENCE (detail/preview_registered) — rien à projeter, le déclaratif réel est la spec Detail d'`apps.py` (même diagnostic que `studio` avant correction) ; `prompts.skills` = NOMS de fichiers `.md` sans contenu ; `tool_api` = présence de la triade + descriptions DÉRIVÉES (les fonctions elles-mêmes = code, tier difficile avec `processing`) | F3/F6 | trous d'extract |
| 15 | **`system_tools` non déclarés** (chromium, ffmpeg, rsvg…) — le volet **librairies** du manifeste est CLOS (2026-08-03/11 : `requires:{kind:library}` dans l'enveloppe, résolu et bloquant, kind + registre `Library` + `write_back_library` livrés, 1er lien transcriber→faster-whisper) ; ce qui manque encore est la déclaration des **outils système** et leur provisionneur commun (cf. `PROJECT_STATUS` §23.6, qui annonçait ce trou sans qu'il ait été reporté ici) | F4/F5 | manifeste |
| 20 | ✅ **clos (2026-08-13, le jour de sa découverte)** — Routes par-outil `/api/tools/*` NON gardées par le gating F7 : les **10** vues individuelles de `wama/tool_api.py` (« for manual testing ») appelaient les fonctions d'outil DIRECTEMENT — sans `execute_tool`, donc sans `tool_accessible` — et `app_id_for_path('/api/tools/…')` → None (segment `api`) : le middleware ne les couvrait pas non plus. Seul `@login_required` s'appliquait : tier + rôles contournés — **jumeau exact du trou #7** (même mécanique, autre surface). **Correctif** : les 10 vues passent par un adaptateur unique `_vue_outil` → `execute_tool` (LA porte : gating, sanitisation, coercition, bornes de choix), `forbidden` → 403. Mesuré : user sans rôle → 403 sur anonymizer/status, 200 sur converter (ouvert) et list-files (transverse) | F7 | ✅ |
| 21 | **Couche JS d'APPLICATION non générée** (mesuré 2026-08-22, converter_01) : le gabarit généré n'émet AUCUN bloc `app_scripts`, alors que le socle l'offre (`app_modern_base.html:294`). Le JS de l'app existe dans `static/` mais n'est jamais chargé → aucun écouteur posé, aucune voie d'import n'émet de requête, **zéro erreur console** (rien ne plante quand rien n'est chargé). C'est ce silence qui l'a rendu invisible au banc codegen, qui ne compare que des facettes projetables. Brique livrée : `common/_app_scripts.html` (noyau mesuré sur 10 apps + options). ⚠ **Le générateur ne l'émet toujours pas** — le câblage de converter_01 est MANUEL (jumelle gitignorée) ; il reste à porter dans `templates_gen`. | F1/F3 | codegen ⏳ |
| 22 | ~~**`batch_create` encore bouchonné (501)**~~ → ✅ **CLOS le 2026-08-22**. Vue conventionnelle rendue par la fabrique (parse → création → `group_into_batches_by_nature`), zéro brique nouvelle. **Une URL n'y est PAS téléchargée** : la source est enregistrée et `ensure_local_input` la résout en tête de tâche — la requête ne part pas chercher N fichiers distants, et le seul chemin de téléchargement reste celui qui passe par la garde SSRF. Mesuré de bout en bout sur `converter_01` : 2 éléments créés, rattachés à un lot (`wama/common/tests_codegen_lot.py`, 8 tests). **Deux défauts trouvés en le câblant** : ① la 2ᵉ passe d'assemblage (`extra_routes`) ne consultait pas les corps conventionnels — une route déclarée en extra recevait un 501 alors que la fabrique savait la rendre (3ᵉ occurrence du motif « deux chemins, deux apps », après `WAMA_INGEST` et le `pk` de `batch_preview`) ; ② la clé d'ingest est `source`, pas `source_field`. | F1 | codegen |
| 23 | **`auto_wrap_orphans` sans variante FK-DIRECTE** : la brique commune suppose un modèle de LIAISON ; converter est la seule app à FK directe et réécrit une boucle de 6 lignes, désormais reproduite dans le gabarit généré. Motif écrit à 4 endroits (converter, avatarizer, synthesizer, codegen) → extraction justifiée. Même angle mort pour `build_batches_list`, que 9 apps sur 10 utilisent et qui ne couvre pas la FK directe (prefetch `items__work_attr`). | F1/F5 | brique |
| 24 | **Contrat de réponse d'`upload` non normalisé** : converter renvoie `job_id`, le gabarit généré `id`, d'autres `pk`. `converter.js` lisait `data.job_id` là où la vue générée renvoyait `id` → identifiant `undefined`, liste vide, pas de rechargement, **aucune card, sans erreur**. `wama-import.js` lit désormais les trois graphies (filet), mais la normalisation des vues reste à faire — l'affichage ne doit pas dépendre d'un nom de clé. | F1 | codegen |
| 25 | **8 doubles inclusions de JS** (mesuré 2026-08-22) : `wama-model-help` ×4 (composer, converter, reader, transcriber), `wama-queue` ×2 (composer, describer), `wama-cycle-button` ×1 (composer), `console` ×1 (anonymizer) — tous DÉJÀ chargés globalement par `base.html`/`app_modern_base.html`. Même famille que le bug du player audio muet du 18/08 (deux BroadcastChannel). Disparaissent à l'adoption de `_app_scripts.html`. | F3 | dette |
| 26 | **Aucun critère ne voit une zone de dépôt que rien n'écoute** : la grille mesure la présence du markup, pas l'existence d'un écouteur. C'est ce qui a laissé converter_01 inerte sans qu'aucune mesure ne baisse. Critère à écrire : une app qui rend `[data-wama-nic]`/dropzone sans charger de voie d'import échoue. | F3 | grille |
| 27 | **`compact_preview` (reader) orphelin + 3e copie** : le filtre templatetag n'a plus d'appelant depuis le portage du 22/08 (le commun rend l'extrait), et la MÊME logique existe une troisième fois dans `reader/views.py::_compact_preview`, toujours utilisée pour la charge d'API. Candidat REMOVAL_LEDGER. Idem `imager` : `openImagePreview`/`openVideoPreview` sans appelant depuis le portage du mécanisme n°30. | F3 | dette |
| 28 | **La boucle codegen exige un REDÉMARRAGE** : `gunicorn_conf.py` n'a ni `reload` ni `preload_app`, donc aucune modification Python (`apps.py`, `views.py`, briques communes) n'est prise sans relance. Trois diagnostics de la session du 22/08 s'y sont heurtés. Les gabarits, eux, se relisent à chaque requête. À écrire dans la recette de génération — et à trancher : `reload = True` en dev ? | — | outillage |

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
