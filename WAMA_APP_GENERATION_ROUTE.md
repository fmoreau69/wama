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
- **Adoption réelle — RE-MESURÉE le 2026-08-31** (balayage exhaustif des 10 apps, fichier:ligne
  au §S2ter ; la table qui vivait ici datait du 06/08 et disait 3/10 là où le parc est à 10/10) :

  | Surface | Mesure 31/08 | Le vrai déficit |
  |---|---|---|
  | déclencheur ⚙ commun (`WamaQueueActions.onSettings`) | **10/10** | — |
  | **cycle complet** de modale item (`WamaParams.settingsModal`) | **2/10** (anonymizer, imager) | 8 apps réécrivent ouvrir→rendre→sauver→fermer à la main. ⚠ Ne pas confondre les deux lignes : c'est la confusion déclencheur/cycle qui a rendu toutes les tables précédentes fausses |
  | rendu batch `context:'batch'` (WamaParams) | **10/10** | la coquille de modale reste à la main hors anonymizer/imager ; le GÉNÉRATEUR émet désormais l'ouvreur de lot complet (§S2ter) |
  | chips métadonnée (`card_chips`) | **10/10** (11 décorateurs, 6 noms — §S2ter) | l'assiette `values` (JSON) n'est passée que par converter |
  | `gear_data` (property modèle) | **10/10** | — |
  | `WamaModelCaps` (show_if depuis caps) | synthesizer seul | — |
  | **réglages utilisateur persistés** (`user_settings`) | **8/10** | anonymizer + enhancer persistent en TABLE Django maison (`UserSettings`) — architecture différente, pas un oubli |
- **Manifeste** : `params` = `{primary, schemas}` **multi-schémas depuis le palier params**
  (trou #10 clos — « un seul params_attr » écrit ici avait survécu à sa résorption) ; ne
  distingue pas **déclaré vs câblé** (c'est le round-trip qui le révèle).

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

#### 🔴 F4b — La DERNIÈRE JAMBE manquante : les OPTIONS du select ne viennent pas du catalogue (mesuré 2026-08-31)

> **La route n'est PAS à double sens — et le dire ainsi était une erreur de ma part (recadrage
> Fabien, 31/08).** Le sens est unique et il est celui écrit ci-dessus : *déclaration d'app
> (`<APP>_MODELS`) → `_discover_<app>_models()` → catalogue `AIModel` (source unique, enrichi de
> ce que l'app ignore : licence, VRAM MESURÉE, provenance, `composition`, état d'installation)*.
> Ce qui manque n'est pas une inversion, c'est **une NON-ADOPTION de la dernière jambe** — la même
> maladie que « `select_model()` adoptée par 2/10 » tracée trois lignes plus haut, jamais comptée
> pour les OPTIONS. Le catalogue sert déjà les MÉTA (aide, VRAM, capacités, grisage) ; il ne sert
> pas encore **l'inventaire proposé à l'utilisateur**.

**Mesure (balayage des 10 apps, `file:line` à l'appui)** — d'où vient la LISTE d'options :

| Source de la liste | Apps |
|---|---|
| **Catalogue** (`get_registry_models`) | **imager, domaine VIDÉO seulement** (`imager/views.py:183`) — **1/10** |
| Constante en dur de l'app | synthesizer (`common/tts/constants.py:25`, 4 entrées) · avatarizer (emprunte la même) · enhancer (`models.py:39`) · composer (`COMPOSER_MODELS`) · reader (`models.py:18`) · imager-image (`diffusers_backend.SUPPORTED_MODELS`) |
| Classes de backend | transcriber (`backends/manager.py:51`) |
| **Scan disque** (hors catalogue) | anonymizer (`utils/model_manager.py:317`) |
| Aucun select | describer, converter (N/A) |

⚠ **`get_registry_models` (`model_selector.py:377`) est la SEULE brique catalogue→options, et elle
n'a qu'UN consommateur applicatif** (vérifié par grep exhaustif). Elle existe, elle marche, elle
n'est pas câblée.

**La PREUVE que c'est bien la jambe qui manque, et pas un défaut de conception** : les
« re-clés par app » de [`INPUT_MODEL_MATCHING.md §5`](INPUT_MODEL_MATCHING.md) — synthesizer
`ENGINE_CATALOG_KEYS` (xtts_v2↔coqui-xtts), enhancer suffixe `_fp16`, transcriber
`_backend_for_model_key`, anonymizer double clé `type/fichier`. **Ces tables de traduction
n'existent QUE parce que les valeurs d'option ne sont pas les clés du catalogue.** Si les options
venaient du catalogue, il n'y aurait rien à re-clé. Elles sont la cicatrice du raccourci, pas une
pièce de l'architecture — et elles disparaissent avec lui.

**Le BLOQUANT technique à traiter en premier (sinon le câblage ne montrera rien)** : `model_sync`
réécrit `capabilities` EN ENTIER depuis la découverte (`model_sync.py:206`). Un modèle installé
par la prospection et catalogué par le **balayage générique des snapshots HF** naît donc avec
`capabilities={}` et `backend_ref=''` — invisible d'un filtre par capacité. Vécu le 31/08 :
Kokoro-ONNX, chatterbox et Audio8 sont au catalogue, licenciés, avec `composition`… et sans une
seule capacité. **Il faut que le manifeste puisse POSER les capacités d'un modèle qu'aucune app ne
déclare**, et que le sync les préserve — exactement le partage déjà en vigueur pour
`composition`/`license` (projetés par le manifeste, préservés par le sync) ; `capabilities` est le
seul champ resté du côté « découverte seule ».

**Route CIBLE (4 maillons, rien à inventer)** :
`manifeste model (identity + capabilities + composition.runtime)` → `catalogue AIModel` (la
découverte gardant les FAITS : présence, format, taille, VRAM mesurée) → `get_registry_models`
**filtré par CAPACITÉ** (`task`/`modalities`/`inputs`, jamais par `source` — un modèle sert
plusieurs surfaces : l'avatarizer emprunte le parc TTS, l'assistant vocalise, le studio et le Lab
consomment) → `params.py` déclare `options_source: "catalog"` → `WamaParams` rend le select
(mécanisme `OPTION_SOURCES`, `wama-params.js:340`, **déjà déclaratif et déjà extensible**).
Au lancement, le backend est dispatché par `composition.runtime.engine` — deux précédents qui
tournent : `AudioCppBackend` (Music3) et `KokoroOnnxBackend` (31/08).

**Ordre de portage** (chaque étape livrable seule) : ① socle sans changement d'UI (capacités au
manifeste + filtre par capacité + source `catalog`) ; ② **synthesizer** (pilote — ⚠ piège :
`VoiceSynthesis.tts_model` porte `choices=`, donc *toute liste dans un champ de modèle exige une
migration* : preuve par l'absurde que la liste ne doit pas y vivre) ; ③ **avatarizer** (valide le
multi-surface) ; ④ composer + reader (déjà rendus par WamaParams : seule la source change) ;
⑤ enhancer (7 modèles déclarés **4 fois**) ; ⑥ imager (aligner l'image sur la vidéo, replier les
8 `SUPPORTED_MODELS` sur `composition.runtime`) ; ⑦ transcriber (pont backend↔catalogue) ;
⑧ anonymizer (scan disque conservé en repli jusqu'à preuve) ; ⑨ surfaces transverses (assistant,
studio, Lab — `cam_analyzer` n'a **aucun** usage du catalogue : chantier à part).

##### ✅ Étapes ② et ③ LIVRÉES le 2026-09-01 (`fb9ecfd9`, `c8d35ee9`)

**Mesure d'entrée** : catalogue **7** moteurs TTS, app **4**. Les 3 invisibles étaient installés
et licenciés — dont **Kokoro-ONNX**, posé la veille par la chaîne (3,3 s de chargement contre
87,9 s pour le `.pt`) et inchoisissable. **Après** : 7 servis, `model_options_catalog` **VERT**
sur synthesizer (77/78) ET avatarizer (77/78) ; grille **6 ROUGE / 1 PARTIEL / 2 VERT / 1 N/A**.

- **Espace de clés unifié** : la valeur stockée est la clé catalogue ENTIÈRE
  (`synthesizer:kokoro`) — **103 lignes réelles migrées** (98 `VoiceSynthesis` + 5 `AvatarJob`,
  migrations `synthesizer/0019` et `avatarizer/0012`, transformation PURE). `engine_for_model`
  reste tolérant au suffixe nu, définitivement. Les tables de re-clé perdent leur raison d'être.
- **Dispatch par `composition.runtime.engine` désormais UNIFORME** — il ne l'était pas : les 3
  modèles orphelins en portaient un, les 4 déclarés par une app n'en avaient **aucun**. La
  découverte sait le dire, en lisant `SYNTHESIZER_MODELS[*]['engine']` (aucun 5ᵉ lieu de
  déclaration) ; `model_sync` n'écrase plus `composition` par une absence — **la règle « ne
  jamais écraser un fait curé par une absence » que la clôture du 31/08 signalait manquante**.
  Le service TTS n'ayant pas Django, le moteur déclaré lui est **passé** (champ `engine` du
  contrat HTTP).

⚠ **Deux demi-jambes du socle trouvées EN PORTANT** — le socle du 31/08 les avait laissées
ouvertes sans que rien ne rougisse : (1) **`Param.options_query` n'existait pas** — le lecteur
(`_optionQuery`) et l'endpoint étaient livrés, mais **aucun schéma ne pouvait l'émettre** ;
(2) `ui_meta._engines()` se disait « ce que le select propose RÉELLEMENT » en dérivant d'une
liste en dur — 4 moteurs là où l'utilisateur en voit 7, privant les 3 nouveaux de descriptif et
d'appariement, **en silence**. *Une jambe livrée aux deux bouts et absente au milieu se voit
seulement quand on s'en sert.*

⚠⚠ **Retirer `choices=` n'est pas un geste local** : le champ perd aussi `get_FOO_display()`
(4 appelants en 500, attrapés par les tests) **et** toute option pour un select rendu par
`WamaParams` depuis `derive_from_model` — l'avatarizer, que je croyais hors périmètre, se
serait ouvert sur une **liste déserte**. *Un select vide ne lève pas.* Suivre TOUS les lecteurs
du champ, pas seulement l'app qu'on porte.

~~**Reste ouvert** : 2 des 7 moteurs (`chatterbox-tts`, `transformers-remote-code`) n'ont
**aucun backend** — leur grisage relève de l'arbitrage « défaut constaté ».~~
✅ **TRANCHÉ le 02/09 (Fabien) : pas de grisage à la main — un SYSTÈME qui VÉRIFIE.**
Inventaires de moteurs enregistrés par les producteurs (`common/backends/manager.py` :
`register_engine_inventory` — synthesizer y met `ENGINE_BACKENDS`, la table du dispatch
réel ; composer `audio-cpp`), verdict `backend_missing()` PERMISSIF (seul le POSITIVEMENT
inlançable — moteur déclaré qu'aucun inventaire ne sert — est condamné) et RELU à chaque
appel : **un backend ajouté ré-autorise tout seul**, rien à dégriser. Deux consommateurs :
`select_model` EXCLUT du tirage (un choix inlançable est toujours faux — vécu : chatterbox
prévu à curseur 50) ; le select AFFICHE grisé avec la raison (lister n'est pas pouvoir
choisir). ⚠ Composition des DEUX grisages mesurée au smoke : `wama-input-match` réécrivait
disabled/title à chaque change et effaçait le verdict serveur — marqueur
`data-backend-missing` émis par le fill, respecté par l'appariement. ⚠ Limite ASSUMÉE de
la permissivité : un modèle SANS moteur déclaré (Qwen3-TTS fraîchement tiré) n'a pas de
verdict — déclarer son `composition.runtime.engine` (manifeste) le fait entrer au système.

**Ce qu'il ne faut PAS casser** : la lecture BIDIRECTIONNELLE des capacités dans la card
(entrées⇄modèles, `WamaInputMatch` + `WamaModelCaps`, **8/8 câblées**, adoption SOLDÉE). Elle
n'est pas menacée — elle est *simplifiée* : mêmes clés partout, plus de traduction.

**Garde-fous pour que ça ne revienne jamais** (la demande de fond de Fabien : *« que n'importe
quelle nouvelle application fonctionne de la même façon dès sa construction »*) :
1. un **critère MESURÉ** dans `check_app_conformity` (« la liste de modèles dérive du catalogue »)
   — une règle de doc dérive, un critère de grille rougit tout seul ;
2. **`params_gen` émet `options_source: "catalog"`** pour le paramètre modèle → une app générée
   depuis son manifeste **naît conforme**, sans que personne y pense.

**Corollaire acté (Fabien, 31/08)** : filtrer par capacité fait hériter les PASSERELLES sans
effort (enhancer appelé depuis converter, TTS dans avatarizer…) — une passerelle demande une
capacité, elle n'a aucune liste à tenir.

##### Les TROIS indicateurs d'un modèle — aucun n'a été perdu (vérifié 2026-08-31)

Doute de Fabien : « la confiance était le niveau de confiance de la PROPOSITION ; à côté il y
avait la complexité d'intégration et la performance issue des benchmarks — j'ai l'impression
qu'on a mélangé les deux ». **Sa mémoire est juste, et les trois vivent, distincts :**

| Indicateur | Champ | Qui l'écrit | Ce qu'il dit |
|---|---|---|---|
| **Confiance de la proposition** | `AIModel.confidence` | bouton « Évaluer la confiance » → `assess_proposed` : un **jury multi-agents LLM** rend `{recommend, confidence 0-1, vram_fit, rationale, concerns}`, consolidé par vote | à quel point le jury croit à SA recommandation |
| **Complexité d'intégration** | `AIModel.update_complexity` | `write_candidate` à la prospection | install en place vs backend à créer |
| **Performance / qualité** | `benchmark_index` + `benchmark_meta` (tiers), `quality_index` (a priori) | `manage.py sync_benchmarks` — **Artificial Analysis + Arena** | mesure TIERCE, échelles jamais mélangées |

Le jury **consomme** le benchmark (il lui est donné dans son prompt) mais ne le remplace pas.
⚠ Ce qui a créé le malentendu est le **libellé du bouton** : « Évaluer la confiance » déclenche
le jury LLM (indicateur 1), pas la recherche de benchmarks (indicateur 3).

**🔴 Conséquence qui DÉBLOQUE Fabien** : il dit n'avoir « jamais pu compléter une recherche
benchmark, le PC crashe ». Ce n'est pas la recherche benchmark qui crashe — **`sync_benchmarks`
est PUREMENT RÉSEAU** (API Artificial Analysis avec clé gratuite + dataset Arena sur HF) :
**aucun GPU, aucun Ollama, aucun chargement de modèle**. C'est le **jury LLM** qui charge un
modèle sur l'Ollama hôte, et c'est LUI le déclencheur de crash connu. Les deux mécanismes ont
été confondus à cause du bouton. → `manage.py sync_benchmarks` peut tourner **sans risque**,
et il alimente l'étage qui manque au tirage automatique (voir ci-dessous).

##### Le tirage AUTOMATIQUE : ce qui manque n'est pas le mécanisme, c'est la DONNÉE et l'INTENTION

- **La performance est DÉJÀ dans le classement** (`_rank_key`, 4 étages jamais mélangés :
  sous-indice de domaine → benchmark tiers → a priori → VRAM ; règle de lot — on ne compare
  que si TOUT le lot porte le signal). Ce n'est donc pas un trou de mécanisme.
- **Mais le parc TTS n'a aucun indice** → le classement retombe sur `vram_gb`, c'est-à-dire
  « le plus gros qui tient » : mesuré, une demande TTS nue rend `bark` (4 Go) et non `kokoro`
  (0,5 Go). Pour une PREVIEW RAPIDE c'est l'inverse du besoin. **Remède immédiat et sans
  risque : `sync_benchmarks`.**
- ~~**L'INTENTION manque au contrat commun**~~ → **✅ LIVRÉE le 2026-09-02** (curseur de
  qualité CONTINU 0-100, `select_model(quality_intent=…)` — détail au §brique
  d'auto-sélection ci-dessus).
  Le prototype `precision_level` 0-100 de l'anonymizer (`params.py:107`) reste app-local :
  il pilote AUSSI des couplages propres à l'app (chemin de floutage au-delà de 50) qui ne
  doivent pas monter au commun — son ralliement au curseur commun = chantier séparé.
- **Modèles réputés DÉFAILLANTS** (bark saturé, vibevoice-asr « voix au ralenti » — constats
  de Fabien) : le levier EXISTE et il est déjà documenté comme tel — `is_available=False` est
  une **décision humaine** que la découverte n'a pas autorité pour écraser (`model_sync`).
  Un modèle ainsi marqué sort du tirage ET des selects. ⚠ Manque une **raison déclarée**
  (« rendu saturé, écarté le … ») : sans elle, l'exclusion est muette et personne ne saura
  pourquoi dans six mois — à ajouter avec le portage.

##### ✅ La brique d'auto-sélection est LIVRÉE (2026-09-02) — le mécanisme, pas encore l'intention

`wama/common/utils/auto_model.py` (mécanisme `auto_model`) généralise les deux jumelles
`composer/utils/auto_model.py` + `imager/utils/auto_model.py` (structurellement identiques,
constat du handoff 01/09) — toutes deux recâblées dessus, il n'en reste que leur spécificité
légitime déclarée (correspondance mode→domaine imager, musique/ambiance composer).

- **Un domaine, deux usages** : le tirage « auto » lit le MÊME `options_query` que les
  options du select (`catalog_domain()` — zéro second lieu de vérité). Une app portée au
  catalogue a l'auto-sélection GRATUITE.
- **« auto » en 1ʳᵉ option + PRÉVISION sous le select** (décisions Fabien, 01/09) :
  `options_auto=True` au schéma (OPT-IN — ne le déclarer que si le lancement résout) →
  l'endpoint sert l'option et `auto_preview` (même chemin que le tirage réel), le JS
  affiche « Prévu : … — réévalué au lancement » quand la valeur est `auto`.
- **Réévaluation au lancement, DITE** : synthesizer (`workers.py`) et avatarizer
  (`workers.py`, mode pipeline) résolvent au lancement et consignent le choix dans la
  console de l'item. Adopteurs : synthesizer + avatarizer (via schéma), imager + composer
  (via leurs jumelles recâblées).
- **✅ L'INTENTION est entrée au contrat commun (2026-09-02) — en ÉCHELLE CONTINUE 0-100**
  (recadrage Fabien le jour même : *« l'intention n'est pas un branchement, c'est un poids
  dans le score »* — la 1ʳᵉ implémentation à 3 politiques discrètes ne savait désigner que
  3 candidats sur N ; remplacée dans la journée, migration de données pure `fast→15 /
  balanced→50 / precise→85`). Arbitrage : `select_model(quality_intent=0-100)` →
  `score = w·qualité + (1−w)·légèreté` (valeurs min-max du LOT, échelle des signaux au
  domicile unique `_quality_scalars` — partagée avec `_rank_key`) ; au-delà de
  `QUALITY_OFFLOAD_THRESHOLD` (80), budget ET résidence s'effacent — l'offload ou
  l'attente `AWAITING_RESOURCES` est le prix assumé. **Deux gardes mesurées** : une VRAM
  inconnue (None/0) vaut le PIRE coût (Audio8 vram=0 battait Kokoro 0,5 sur « rapide »
  par accident) ; à score égal, la qualité départage (sans quoi le score est PLAT à w=0,5
  quand le lot n'a que le proxy VRAM). Les positions NOMMÉES `QUALITY_PRESETS`
  (**Rapide 15 / Équilibré 50 / Qualité 85** — trio canonique acté, « Précis » écarté
  comme trop étroit ; le converter garde sa nuance en sous-libellé « Rapide (web) »)
  servent de graduations au slider et de presets aux LOTS/filemanager — même forme
  utilisateur partout, chaque usage DÉCLINE la valeur selon ses capacités (couche
  d'adaptation locale déclarée : modèles ici, encodage au converter, floutage anonymizer).
  UI : renderer commun `type='intent'` + partial `common/_intent_slider.html` (même
  contrat, liaison déléguée), tricolore par zone, visible seulement sur « auto »,
  PRÉVISION qui suit le curseur en direct. Adopteurs : synthesizer (toutes surfaces) et
  avatarizer (modale item) — champ `quality_intent` (IntegerField défaut 50) ; lecture
  POST par la brique (`read_quality_intent`, bornée, ne lève jamais). Ralliement
  converter/anonymizer = suite du portage (le commun est prêt).
- **La DONNÉE de qualité reste le maillon faible — et son plan est acté (Fabien, 02/09)** :
  tant que le parc d'une tâche n'a ni benchmark ni indice, le score pondère le proxy VRAM
  (= « le plus gros ≈ le meilleur », faux pour l'usage réel : XTTS/Kokoro, les plus
  utilisés, ne gagnent jamais). `sync_benchmarks` ne couvrira jamais tout le parc (bancs
  tiers = LLM/ASR/vision surtout). La source qui manque est la **MESURE INTERNE** — le
  sommet de l'échelle des signaux, aujourd'hui vide : **qualification nocturne
  COMPARATIVE** — le même job lancé sur TOUS les modèles capables de la tâche
  (`bench` + files nocturnes), sorties confrontées entre elles (contrôle **VLM** pour le
  visuel, métriques objectives quand elles existent), verdicts réingérés en indice par
  tâche. Prérequis : un hôte qui ne crashe plus la nuit (HWiNFO + chantier crashs) ;
  beaucoup d'usages avant que le critère soit solide — c'est une boucle d'accumulation,
  pas un one-shot. À câbler avec `WAMA_APPRENTISSAGE §A2-A4` (WAMA déclare/déclenche/
  réingère) et le mécanisme `bench` existant.
- **✅ Anonymizer RALLIÉ (02/09, même journée)** : `precision_level` passe au renderer
  commun `type='intent'` (volet = partial commun avec `step=5` — les 5 paliers moteur
  restent la vérité du curseur — et `extra_class='setting-button'` pour l'auto-persistance) ;
  les libellés anglais locaux (Quick/Balanced Quick/…) disparaissent au profit des zones
  canoniques. La DÉCLINAISON reste locale et intacte (`get_model_size_from_precision`
  n/s/m/l/x + seuil binaire 50 de segmentation) — c'est la couche d'adaptation voulue.
  Le champ garde son nom `precision_level` (frontière des DONNÉES : tasks et
  model_selector d'app le lisent).
- **⏳ Converter : PRÊT À CÂBLER — tout le commun est en place, il ne reste que SES
  fichiers** (occupés par une autre session au 02/09 — ne pas se télescoper). Le geste,
  quand le champ sera libre : ① presets de LOT/filemanager `Web (léger)/Équilibré/Maximum`
  → les positions `QUALITY_PRESETS` (15/50/85), relibellés « Rapide (web) / Équilibré /
  Qualité » (arbitrage Fabien : trio canonique, nuance locale en sous-libellé) ;
  ② le slider UNITAIRE 1-100 des cards → `intent_param(...)` au schéma (type='intent' —
  zones/tricolore/graduations gratuits), lecture POST par `read_quality_intent` ;
  ③ la DÉCLINAISON reste chez lui (valeur → réglages d'encodage par format) — même
  motif que l'anonymizer. Aucun mécanisme à créer : c'est une substitution de surface.
- **Ce qui n'est PAS dedans** : la comparaison prévision↔choix réel (la prévision
  n'est pas stockée ; le message de lancement dit le choix ET le curseur, pas l'écart).
- ⚠ **Demi-jambe trouvée EN VALIDANT à l'écran (constat Fabien : « je ne vois pas le
  modèle prévu »)** : `_bindOptionSources` ne vivait que dans `WamaParams.render` — donc
  les MODALES. Le select du VOLET, rendu SERVEUR (`tts_engine_choices()`), n'y passait
  jamais : la page émettait bien la requête `auto=1` (pour la modale), l'endpoint
  répondait juste, et le volet restait sur sa liste serveur. Même famille que les deux
  demi-jambes du 01/09 : *une jambe livrée aux deux bouts et absente au milieu ne se voit
  qu'en s'en servant* — et un smoke qui lit le DOM final tranche là où l'inspection du
  code ne voyait rien. Réglé au COMMUN : `WamaInspector.initFromSchema` lie les sources
  `catalog` du volet (`WamaParams.bindOptionSources` exposé, prédicat — les voix du volet
  restent rendues serveur, leurs optgroups clonés ne se remplacent pas).

##### ⚠ INVARIANT À NE PAS CASSER : lister ≠ pouvoir choisir

Rappel de Fabien (31/08), et c'est la règle d'`INPUT_MODEL_MATCHING §2` : le select **affiche
TOUS** les modèles du domaine — l'utilisateur garde l'information — et seuls les compatibles
sont **sélectionnables**, les autres étant **grisés AVEC LA RAISON** (« Incompatible avec votre
fichier de référence »), réversible d'un ✕. **Ne jamais transformer ce grisage en exclusion
serveur.** Concrètement pour l'étape (c) : la source `catalog` liste par CATÉGORIE + TÂCHE
(le domaine), **jamais** par `requires`/`available_inputs` — ces derniers restent le travail
d'affichage de `WamaInputMatch`/`WamaModelCaps`, côté client, sur la liste complète.
✅ Vérifié ce jour : aucune régression introduite — `input_match.py` et les briques JS n'ont pas
été touchées, et tous les appels existants passent `source`, donc rendent l'identique.

##### Avancement du socle (étape ①) et 2 découvertes qui changent la suite

- ✅ **(a) capacités posables par le manifeste, non effaçables par une découverte muette**
  (`model_sync` : un `{}` ne remplace plus un fait ; `write_back_model` : projection SOUS
  CONDITION, seulement si `backend_ref` vide ET capacités vides). Prouvé sur base live.
- ✅ **(b) requête par CAPACITÉ, tous producteurs** — `get_registry_models(source=None)`.
  Constat : la fonction était **déjà** un filtre de capacité complet (`task`, `modality`,
  `available_inputs`, `consumes`, `requires`) ; seul son ancrage `source` manquait d'ouverture.
- ✅ **(c) les options se tirent du CATALOGUE** — `api/models/options/` (par DOMAINE :
  task / model_type / modality / source ; refus 400 sans domaine) + clé `catalog` dans
  `OPTION_SOURCES` et **`options_query`** au schéma : une clé ne portant qu'une URL fixe ne
  pouvait pas savoir DE QUOI elle parle. La querystring entre dans la clé de cache (deux
  domaines sur une page ne se servent pas mutuellement leur liste). `staticfiles/`
  resynchronisé ; JS attesté au navigateur (`new Function` sur le fichier SERVI — aucun
  `node` dans l'environnement, c'est la seule attestation possible).
- ✅ **(d) les deux garde-fous** — critère de grille `model_options_catalog` (F4, 3 états :
  vert = `options_source: 'catalog'` · partiel = `get_registry_models` côté serveur ·
  rouge = liste en dur, avec `file:ligne`) ET `params_gen` qui **signale** (sans corriger —
  il rend le manifeste AU LITTÉRAL, l'injection ferait mentir le manifeste ; la détection
  s'appuie sur une liste de noms OBSERVÉE, elle ne devine pas).

**PHOTO DE DÉPART DU PORTAGE, MESURÉE le 2026-08-31** (et elle corrobore le balayage manuel
par un chemin indépendant) : **8 ROUGE** — anonymizer `models.py:43` · avatarizer
`models.py:12` · composer `model_config.py:38` · describer `model_config.py:44` · enhancer
`params.py:65` · reader `model_config.py:30` · synthesizer `models.py:11` · transcriber
`params.py:39` — **1 PARTIEL** (imager) · **1 N/A** (converter). Rejouable :
`manage.py check_app_conformity`.

**⚠ ALIAS DE VOCABULAIRE (arbitrage Fabien : « on modifie avec la taxonomie HFHub ou on gère
un alias ? »)** → **alias, et il existait déjà**. S'aligner sur HF effacerait des distinctions
voulues (`text-to-music` ≠ `text-to-audio`) et des tâches sans équivalent (`obb`, `lip-sync`).
`TASK_TO_PLATFORM_TAGS` se lit donc dans les DEUX SENS — `platform_tag()` (notre tâche → le
tag) et `canonical_task()` (un tag → notre tâche) — sans seconde table : ajouter une
plateforme reste une COLONNE. Mesuré : une requête `automatic-speech-recognition` rendait
**14 options polluées** (bark, kokoro, un débruiteur) faute de correspondance ; **5 vrais ASR**
après. *Deux vocabulaires pour un même fait ne divergent pas bruyamment : ils se rejoignent
sur un repli qui a l'air de marcher.*

**⚠ Ce qui reste AVANT le portage (étape ②)** : ① les VALEURS d'option devront être
réconciliées avec ce que chaque app dispatche — c'est `composition.runtime.engine` qui
répond ; ② durcir la règle en validation BLOQUANTE casserait aujourd'hui les 10 manifestes
(tous encore en dur) : on durcit APRÈS le portage — décision de séquencement, pas un oubli ;
③ l'INTENTION (latence ↔ qualité) manque au contrat commun — le curseur `precision_level` de
l'anonymizer en est le prototype, mais il pilote AUSSI des couplages propres à l'app
(chemin de floutage au-delà de 50) qui ne doivent PAS monter au commun.

**⚠ Découverte 1 — `matches_inputs` est PERMISSIF par choix documenté** :
`if task and caps.get('task') and caps.get('task') != task` → **un modèle qui ne DÉCLARE rien
n'est jamais exclu**. Sain pour SÉLECTIONNER (ne pas écarter l'inconnu), faux pour PEUPLER un
select : mesuré, une requête `text-to-speech` a fait remonter `LocateAnything-3B` (vision).
→ Arbitrage proposé (Fabien) : permissif pour la **sélection**, **strict** pour les **options**.
Conséquence vertueuse : *un modèle sans capacités déclarées n'apparaît nulle part* — la
déclaration devient obligatoire au lieu d'optionnelle, ce qui est l'objectif même du chantier.

**⚠⚠ Découverte 2 (leçon de MÉTHODE, vécue le jour même)** : ma première preuve du point (a)
était verte… et **falsifiée 67 secondes plus tard**. Le beat `model-manager-reconcile` a
re-effacé les capacités à 19:45:54 en tournant avec **l'ancien `model_sync` chargé en mémoire**
(workers de 15:39, correctif écrit après). Le piège était déjà consigné (« un contrôle vert
juste après un correctif de catalogue ne prouve rien ») — et il a quand même mordu.
**Le test qui tranche n'est pas de lancer le sync dans son shell, c'est de l'ENFILER dans le
WORKER** (`sync_models_task.delay()` + `.get()`) : c'est SON code qui écrase périodiquement.
Refait après le redémarrage de 21:43 → 100 modèles synchronisés **par le worker**, capacités
**préservées**. *Vérifier un correctif de données dans le process qui ne l'a pas chargé mesure
le passé.*

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
- Outils au registre (`TOOL_REGISTRY`) : **56**
- Outils décrits (`tool_descriptions()`, dérivé) : **56/56**
- Arguments documentés (types/choix/bornes/défauts) : **209**
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

**✅ Ajout du 2026-08-23 — les ACTIONS DE CARD sont sorties de ce chantier.** ⚙ Paramètres et
🗑 Supprimer ont rejoint `queue-actions.js` (déjà domicile de ⧉ Dupliquer) : **11 cards portées**,
six graphies résorbées par action, critères `settings_wiring` et `delete_wiring` verts 10/10, et
les deux gestes PROUVÉS au clic (`<app>.settings` et `<app>.duplicate_delete`, 7 OK / 0 échec).
⚠ **Ne pas confondre avec la ligne WamaParams ci-dessus** : la brique prend le BOUTON et la
DÉLÉGATION ; le CONTENU des modales est déjà schéma-driven partout (`WamaParams.render(host,
schema, {context:'item'})`), ce qui reste à porter est l'ORCHESTRATEUR `WamaParams.settingsModal()`
(2/10) — deux couches distinctes qu'un raccourci de lecture confond facilement.

**Prochaine brique sous-adoptée, MESURÉE le 2026-08-23 : `WamaApp.Poller` — 4 apps sur 10**
(transcriber, enhancer, imager, reader). C'est ce que le portage des actions a rendu visible :
le résidu que chaque app garde après une suppression (« arrêter le polling ») n'est pas une
spécificité, c'est la trace de cette brique non adoptée. Il disparaîtra à mesure de l'adoption —
et `WamaApp.emptyState`, adopté par 1 app avant que le converter ne le rejoigne, est le suivant
sur la même liste.

### §10.3 — Write-back (code-gen) depuis le manifeste — `access` ✅ (DB) + `identity`/`ports`/`capabilities`/`studio`/`modes`/`prompts`/`params` ✅ (2026-08-11) + `inspector` ✅ (A3) + `tool_api` ✅ (A4) ; `processing` = projection PARTIELLE assumée (urls comparable ; tasks A2b et models A5 en CREATE-ONLY — les corps/champs restants = marche B)

> ✅ **MARCHE B1 CLOSE (2026-09-02 soir)** — le corps des tâches se COMPOSE depuis le
> manifeste : `backends/__init__.ROUTES` de l'app (nature → callable au CONTRAT COMMUN des
> backends, normalisé le même jour sur les 5 du converter) monte au manifeste
> (`processing.backend_routes`, ingest `builtin/app.py`) ; `tasks_gen` remplace le stub
> `NotImplementedError` par le corps composé (résolution par la nature, valeurs effectives
> des COLONNES — modèle événementiel `ROADMAP §23.2quater` —, import RELATIF AU PAQUET :
> la jumelle résout ses copies sans citer un nom d'app). **Mesuré : la jumelle a converti
> un PNG réel en JPEG lisible (SUCCESS).** Une app sans `ROUTES` garde son trou marqué.
> Restes B : l'étalement du preset au clic côté généré ; `quick_convert`/profils (endpoints
> 501 de la jumelle) ; B2 (backends de modèles connus — 1er livré : Table Transformer).
>
> ✅ **B1 ÉTENDUE À UNE 2ᵉ APP — describer, 1ʳᵉ À MODÈLES IA (2026-09-03)** — le contrat
> gagne une SAVEUR déclarée par `backends/__init__.RESULT` (→ `processing.backend_result`) :
> `'file'` (défaut, pilote converter — le backend écrit `output_path`) / `'text'`
> (describer — le backend REND le texte : `callable(input_path, options, progress_callback,
> partial_callback, console) -> str`, la tâche le persiste dans la colonne `field` déclarée
> et publie l'aperçu PARTIEL). `NATURE_FIELD` (→ `processing.backend_nature_field`) nomme la
> colonne de nature (describer : `detected_type` ; défaut `media_type`). Portage source =
> TRADUIRE et REMPLACER : les 4 describers d'`utils/` sont devenus `backends/` ORM-free (la
> jumelle copie le paquet et l'exécute tel quel), `workers.py` = 5 lignes + glu
> (`run_item_task`), garde `WAMA_GPU_SAFE_MODE` sur la cascade Ollama AUTOMATIQUE.
> **Mesuré : `describer_01` (5/7 substitués) a DÉCRIT une photo réelle par le corps COMPOSÉ
> (BLIP poids réels, CPU forcé, SUCCESS + result_text).** Deux trous NOMMÉS par la jumelle :
> `views` — le gabarit v1 ne rend que la file à FK DIRECTE (converter), le describer a un
> batch à modèle de LIAISON → refus propre, la jumelle garde sa copie ; `models` — verdict
> `revert` (champs de RÉSULTAT hors spine : summary/coherence_*, trou marche B connu).
> La GRILLE mesure désormais la chaîne côté app (4 critères 03/09 : `backend_routes`,
> `task_skeleton`, `detail_spec`, `triad_specs`) — describer **100 %**, 2ᵉ plein score.

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
     `generated_from='converter'` → jumelles ÉNUMÉRABLES (nettoyage sûr, jamais orphelines)
     + badge « BAC À SABLE » dans l'UI. ⚠ Recalé 31/08 : « + l'id du run de génération »
     promis ici n'a JAMAIS été écrit (le registre porte label/created/stage/substituted) —
     contrat amendé plutôt que code ajouté, l'énumérabilité n'en a pas besoin.
  3. **Gating dev-only** (app_access) : invisibles des non-devs.
  4. **Cycle outillé, jamais manuel** : `manage.py app_sandbox` à QUATRE actions (recalé
     31/08 — « create/drop » écrit ici ignorait le cœur de S2) : `create <app>` /
     `drop <app_NN>` (migrate zero + retrait INSTALLED_APPS/urls/registres — symétrique et
     complet, écho staticfiles compris) / `list` / `substitute <label> <cible>` (7 cibles
     codegen, cf. jalon S2).
  5. **La jumelle RÉFÉRENCE le monde, elle ne le duplique pas** : même catalogue `AIModel`
     (lecture), mêmes briques common, mêmes workers — on régénère l'APP, pas la plateforme.
  6. **Diff normalisé** : dé-suffixer avant diff (étend le principe du harnais C — juger des
     artefacts NORMALISÉS, jamais du byte à byte) ; Playwright = pages côte à côte.
  7. **Pilote : `converter_01`** (app la plus simple, 100 % grille, pilote historique de C).
     ~~les facettes encore non-write-back (inspector/models/processing/tool_api)~~ — recalé
     31/08 : cette liste décrivait le matin du 18/08 ; `inspector` et `tool_api` sont
     projetés (A3b/A4), `models` est rendu depuis la facette `data`. Le principe, lui,
     tient : ce qui n'est pas généré apparaît comme manque VISIBLE de la jumelle — c'est
     le but, pas un préalable.
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
  **S2 — JALON (18/08, RECALÉ à l'audit du 31/08) : 7/7 substitutions TIENNENT** — apps,
  urls, models, params, tasks, views, templates, toutes `verdict: ok` au registre
  `wama/sandbox_apps.json` (⚠ c'est LUI le juge, pas ce paragraphe : les diffs copie↔généré
  y sont datés — ne plus recopier leurs tailles ici, elles bougent à chaque re-substitution
  et « 6/6 / views 1341 l. / templates 404 l. » écrits à cette place étaient tous trois
  devenus faux). ⑤ `views_gen` ÉCRIT (la pièce annoncée au cadrage
  A0) : UNE définition par callable du urls généré — idiomes conventionnels paramétrés par
  le manifeste (item + batch/FK DÉRIVÉS de la facette data, tâche processing.tasks,
  fabrique `make_queue_manipulation_views_direct`, briques begin_processing/stop_instance/
  duplicate_instance/apply_queue_sort_filter/console). Les STUBS 501 « TROU DE GLU » ont
  fondu depuis le 22/08 : `card_html`, `batch_preview`/`batch_create`, `consolidate` sont
  CONVENTIONNELS (trou #22 clos) — **seules les `extra_routes` hors-convention restent
  bouchées**, la page boote et le manque reste VISIBLE. v1 = forme FK-DIRECTE (converter) ;
  la forme à modèle de liaison est un trou déclaré.
  ⑥ `templates_gen` v1 ÉCRIT (multi-fichiers — `substitute` étendu, revert multi-fichiers) :
  index CONVENTIONNEL depuis les briques communes (_global_progress, _new_item_card avec
  `file_accept` RÉTRÉCI aux catégories du port travail, _queue_toolbar, boucle _batch_card)
  + card v3 COMPLÈTE émise du manifeste (5 sections wcv3, chips, cycle, ⬇ commun,
  preview unifiée, `data-param-*` pour TOUS les champs du schéma) — « card générique
  minimale, l'écart visuel est la mesure » a vécu : l'instrument a servi, l'écart est fermé.
  Restent COPIÉS (glu/marche B) : base.html, JS d'app,
  backends/, utils/. ~~params.py (write-back existant, cible à câbler)~~ → **câblée le
  2026-08-31** : cible `params` de `_SUBSTITUTABLE` (`codegen/params_gen.py`, constructeur
  partagé avec write_back). Motif : la jumelle tournait sur une COPIE d'avant le 18/08 —
  sans le contexte `'panel'`, le rendu du volet filtrait TOUT (0 champ, en silence) alors
  que le manifeste était à jour. *Un fichier que les vues générées consomment se substitue
  comme elles, sinon la jumelle mesure un schéma périmé.* La lecture VISUELLE côte à côte
  prévue ici A EU LIEU (Fabien, 29→31/08) : elle a produit S2bis, la card v3, l'inspecteur,
  la génération des RÉGLAGES (bloc ci-dessous) — batterie jumelle **11/11 sans skip**.
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

  **S2bis (2026-08-29) — trois manques de GABARIT, révélés par la lecture visuelle prévue au
  jalon ci-dessus.** Constat Fabien : « les cards du bac à sable ne sont pas cliquables,
  n'affichent rien, pas d'action — alors que le converter d'origine fonctionne ». Aucun des
  trois n'était un trou de glu, et c'est LA leçon : *une facette DÉCLARÉE au manifeste et non
  projetée est un manque de gabarit ; la marquer « TROU DE GLU » la rend invisible en la
  déclarant normale.* Même famille que `accepts_url` (19/08), déjà traitée au cas par cas.
  1. **Facette `inspector` non lue** (`detail_registered`, `preview_registered`, `detail_spec`)
     → `templates_gen` rend `WamaInspector.initFromSchema` + `WamaCycleButton.wire/autoSync`.
     La brique de cycle n'était PAS en cause : elle DÉLÈGUE l'appel HTTP à l'app par
     construction (chaque app a ses routes) — ce qui manquait était l'appelant.
  2. **Noms de routes SUPPOSÉS au lieu d'être lus** — 8 apps nomment l'arrêt `stop`, le
     converter `cancel` (mesuré sur les 9 manifestes) : `views_gen` ne connaissait que `stop`,
     donc la seule app qu'il sait générer entièrement recevait un 501 sur son ⏹. Idem pour
     l'édition d'item (`update` → `views.update_job`), déjà écrite un cran plus bas en
     `batch_update` sur les MÊMES `params_fields`. Table `urls_gen.ROUTE_ALIASES` +
     `resolve_route()` : le vocabulaire de routes a UN propriétaire, les deux gabarits le
     lisent. Le corps rendu reste la CONVENTION mesurée (`stop_instance` → FAILURE, idiome de
     describer/avatarizer/composer) ; anonymizer et converter remettent en PENDING —
     réconcilier ces politiques est un chantier de PORTAGE, pas l'affaire du gabarit.
  3. **Chemins écrits à la main en JS** (`"/converter/" + id + "/start/"`) : la substitution du
     bac à sable renomme les littéraux `{% url %}` mais PAS une chaîne construite — la jumelle
     POSTait donc sur l'app SOURCE. *Une jumelle qui agit sur son original ne mesure plus rien.*
     Corrigé en `{% url 'app:route' 0 %}` + `urlFor`. (Le 3ᵉ défaut de la même passe était une
     ARITÉ devinée : `csrfFetch(url, csrfToken, opts)` appelé à deux arguments → GET → 405.)
  4. **Vocabulaire d'ENTRÉE non lu** (même jour, 4ᵉ occurrence du motif — et la seule où j'ai
     annoncé un TROU au lieu d'un manque). `views_gen` laissait `media_type` vide à la création
     et portait un commentaire de 24 lignes affirmant qu'aucune déclaration ne dit les types
     d'entrée d'une app, ni aucun détecteur commun la nature d'un fichier. **Les deux existaient.**
     Mesuré : le vocabulaire est déclaré **DEUX fois et les deux sont d'accord sur 10/10 apps** —
     `APP_CATALOG['<app>']['input_types']` (→ `body.ports.inputs[].types`, `PORTS_FIELDS`) et
     `APP_MODES[app].domains[].accepts` (l'axe UX) ; le détecteur est `category_of_path`
     (`common/app_registry.py`), déjà utilisé par `media_probe` ; et `templates_gen.py:46`
     dérivait DÉJÀ le `accept=` de la dropzone d'`identity.input_extensions`. Corrigé : la vue
     générée projette le vocabulaire (`_TYPES_ENTREE`) et dérive la nature via `category_of_path`
     **CONTRAINTE à ce vocabulaire**, dans **LES DEUX** chemins de création (`upload` et
     `batch_create` — n'en doter qu'un est ce qui a produit les trois défauts ci-dessus) ; une
     extension hors vocabulaire laisse le champ VIDE et le DIT (`warning`), au lieu d'écrire une
     valeur plausible. 4 tests dans `common/tests_codegen_lot.py` (dont un qui mute le manifeste
     pour distinguer « dérivé » de « écrit en dur avec la bonne valeur ce jour-là »).
     *Un trou de formalisme s'annonce APRÈS avoir cherché la déclaration, jamais avant : poser un
     formalisme neuf par-dessus une déclaration existante en crée une seconde, qui divergera.*
     Cause racine traitée : la taxonomie n'était **sur aucune carte** → `Mecanisme('media_taxonomy')`
     (`WAMA_MECANISMES.md`).
  5. **L'« écart de DONNÉES sur 7/11 apps » annoncé le matin ÉTAIT MON CADRAGE, pas une donnée
     fausse** (mesure du soir, même jour — cette ligne REMPLACE la précédente, qui restait à lire
     comme un arbitrage dû). Il n'y a pas d'écart : **je comparais deux AXES différents comme s'ils
     n'en faisaient qu'un.** Les entrées d'une app se déclarent sur **trois** axes —
     **NATURE** (`input_types` / `input_extensions`, tous deux PLATS), **RÔLE**
     (`app_modes.INPUT_TYPES` → `studio_node_ports` → `body.ports.inputs[].group` :
     travail / référence / prompt) et **UX** (`APP_MODES[app].domains[].accepts` + slots
     `inputs[]` des modes). Chacune des deux « familles intelligibles » se résorbe par un axe :
     - `.pdf/.docx` chez composer/imager/synthesizer ne sont pas des entrées de travail :
       `TEXT_EXTENSIONS` (`common/app_registry.py:41`) **EST** la liste des formats de FICHIER
       BATCH (identique à `batch_parsers.py`, commentaire à l'appui) — rôle `prompt_file`. Le
       défaut est la **platitude** d'`input_extensions`, jamais sa valeur.
     - `.md/.txt/.csv` → `text` vs `document` : c'est l'**HOMONYME `text`** (sens « texte brut,
       le prompt » dans `input_types`/`accepts`/`INPUT_TYPES['prompt'].kind` ; sens « FICHIER
       texte » dans `category_of_path`). **Le code le savait déjà** : `studio_node_ports`
       (`app_registry.py:153`) doit écrire `c != 'text'` pour le sortir du port travail, et donne
       au port prompt le jeton `'prompt'` — **hors `MEDIA_CATEGORIES` (`:67`)**. Il a fallu
       inventer un mot pour ce que `text` ne pouvait plus dire.
     *Deux déclarations qui « divergent » sur des axes différents ne divergent pas : elles ne
     répondent pas à la même question. Avant d'appeler un écart une faute, vérifier que les deux
     mesures interrogent la MÊME chose.*
  6. **Défaut de la même passe, introduit et corrigé par moi** (`65a24354`) : `_TYPES_ENTREE`
     unissait TOUS les `ports.inputs[].types` sans regarder le `group` — le port de PROMPT entrait
     donc dans un vocabulaire de FICHIERS. Inoffensif sur le converter (aucun port prompt),
     **faux dès la 2ᵉ app portée** : imager `('image','prompt')→('image',)`, composer
     `('prompt',)→()`, synthesizer `('audio','prompt')→('audio',)`, avatarizer
     `('audio','image','prompt')→('audio','image')`. Correction : on saute `group == 'prompt'` et
     on ne retient qu'un jeton de `MEDIA_CATEGORIES` (repli `accepts` : même filtre + exclusion
     explicite de `text`). 2 tests (12→14 dans `common/tests_codegen_lot.py`), **vérifiés
     DISCRIMINANTS** en rejouant l'ancienne logique sur les mêmes manifestes mutés.
     ⏳ **Ce qui reste réellement ouvert** — reformulé le 2026-08-30 après une objection de Fabien
     (« je ne comprends pas ta formulation ») et **RECADRÉ par la mesure**, car la version
     précédente se lisait comme un défaut de la card d'entrée. Elle n'en est pas un.

     🟢 **Point de départ à ne pas perdre de vue : la card d'entrée commune est FONCTIONNELLE
     dans les 10 apps, et elle SAIT typer par slot.** `common/_new_item_card.html` porte un
     `file_accept` pour le slot de travail (`:94`) ET un `reference_accept` pour le slot de
     référence (`:170`, sous `{% if show_reference %}` `:158` — composer `audio/*` pour la
     mélodie, imager `image/*` pour l'image de référence), plus les modalités URL / médiathèque
     / lot / live. **Rien de ce qui suit ne demande de la toucher** — la brique a la case ; ce
     sont la DÉCLARATION et le GÉNÉRATEUR qui ne la remplissent pas (seuls **2 gabarits sur 10**
     passent `show_reference`, en littéral).

     - **(a) ⚠ RECTIFIÉ le 2026-08-30, question de Fabien** — *« pourquoi et comment le converter
       bac à sable a bien généré sa card d'entrée, qui est fonctionnelle pour l'import depuis
       l'explorateur Windows, si ses entrées ne sont pas déclarées ? Il y a quelque chose qui
       cloche. »* Il y avait bien quelque chose qui clochait : **ma phrase.** J'avais écrit
       « aucune déclaration ne le porte » — c'est FAUX, et la jumelle générée en est la preuve
       vivante. La chaîne est complète et entièrement déclarative :
       `APP_CATALOG['converter'].input_extensions` (`app_registry.py:536`) → projeté au manifeste
       (`manifests/builtin/app.py:212`, champ retenu par `IDENTITY_FIELDS` `:823`) →
       **LU par le générateur** (`codegen/templates_gen.py:46`,
       `accept = ','.join(ident['input_extensions'])`) → injecté en `file_accept`
       (`templates_gen.py:300`) → **68 extensions dans le sélecteur de
       `converter_01/index.html:31`**. L'import explorateur marche **PARCE QUE** c'est déclaré.
       ⚠⚠ **Et la mesure RETOURNE le constat que le paragraphe voulait faire.** En comparant la
       jumelle à sa source, c'est le littéral ÉCRIT À LA MAIN qui est en défaut :
       `converter/templates/converter/index.html:447` s'arrête à `.tex,.latex` — il **manque 14
       extensions** que l'app déclare et que le serveur convertit réellement (les 10 archives
       `.zip .tar .gz .tgz .bz2 .tbz2 .xz .txz .7z .rar`, plus `.fb2 .mobi .azw3 .azw` — recompte
       mécanique du 30/08 : **15**, `.qt` avait échappé au relevé manuel), alors
       que `input_types` déclare `'archive'` et que `converter/utils/format_router.py:44-49` en
       tient la table d'entrée. **Le sélecteur du converter RÉEL grise des fichiers que l'app
       sait traiter ; celui de la jumelle générée, non.** Un littéral dérive de sa déclaration,
       une génération ne le peut pas. *La déclaration n'était pas le maillon manquant : elle est
       le maillon le plus fiable des deux.*
       ✅ **CORRIGÉ le 2026-08-30 (①bis, même journée)** — par la déclaration, pas par le
       littéral : le gabarit passe `file_accept=current_app_spec.input_extensions|join:','`
       (`current_app_spec` était DÉJÀ posé sur toutes les pages par le context processor
       accounts — la route existait, rien à écrire côté vue) ; rendu vérifié : l'accept servi
       == les 60 extensions déclarées, à l'ensemble près. ⚠ **La mesure mécanique rectifie le
       compte relevé à la main : 15 extensions manquaient, pas 14** — `.qt` (extension vidéo
       DÉCLARÉE) manquait aussi au littéral et avait échappé au relevé. *Même un constat de
       dérive se recompte à l'instrument.* Et le geste demandé (« un contrôle mécanique, pas
       10 patchs ») est en place : `common/tests_catalogues.py::CardEntreeConformiteTest`
       confronte les `file_accept` des 12 cards au catalogue **dans les deux sens** (la card
       n'OFFRE rien d'indéclaré ; ne GRISE rien de déclaré), avec 2 écarts ASSUMÉS à faire
       décroître — avatarizer (slot voix = politique `VOICE_SAMPLE_EXTENSIONS`, avatar via
       galerie) et imager (`.md/.pdf/.docx` grisés, ci-dessous). Discriminance prouvée en
       rejouant le contrôle sur le littéral d'hier (15 manques rendus). Le JS du converter
       n'avait PAS de jumeau : `EXT_TO_TYPE` dérive déjà de `supportedFormats` serveur.
       Ce qui reste vrai, et qui est le SEUL manque : **trois** sources décrivent ce qu'une app
       accepte, et **aucune ne type PAR SLOT hors d'un mode** —
       1. `APP_CATALOG[app].input_extensions` — une liste **PLATE** par app, toutes entrées
          confondues (`app_registry.py:686` : imager = `TEXT_EXTENSIONS + IMAGE_EXTENSIONS`) —
          **déclarative, lue par le générateur, et la seule qui alimente une card générée** ;
       2. `APP_MODES[app].modes[].inputs[]` + `INPUT_TYPES[slot]['accept']` — le **SEUL** endroit
          qui type par slot (`work_image → 'image'`, `reference_voice → 'audio'`,
          `app_modes.py:62-74`). Il n'est déclarable que **sur un mode**, or **6 apps sur 10 ont
          `modes: []`** (imager, avatarizer, converter, composer, reader, describer) — et le
          fichier assume ce choix (`:91-93` : les modes d'imager ont été retirés « au profit d'UNE
          card d'entrée par domaine »). Son accesseur `resolve_inputs()` n'a **aucun consommateur**
          dans tout le dépôt ;
       3. les valeurs littérales du gabarit d'app — **la seule qui type par slot aujourd'hui**
          (`reference_accept` / `show_reference` : **2 apps sur 10**, composer et imager), et
          celle qui dérive, cf. les 15 extensions perdues du converter ci-dessus (corrigé ①bis).
       ⇒ Le manque n'est pas « la card ne déclare pas ses entrées » — elle les déclare, et ça
       marche jusque dans une app générée. C'est **« la déclaration n'a pas de case pour le SLOT,
       que la card sait pourtant déjà rendre »** : `inputs` est la seule clé du schéma
       d'`APP_MODES` à ne pas être portée par le DOMAINE, alors que tout le reste l'est
       (`accepts`, `variant`, `route_prefix`, et le routage `domain_for_category`).
     - **(b) Conséquence directe sur le portage — c'est là qu'est le vrai défaut.** Le générateur
       lit la source PLATE, et **rien d'autre** : `templates_gen.py:46` fabrique
       `accept = ','.join(input_extensions)` et `:300` l'injecte en **un seul `file_accept`**, sans
       jamais émettre `show_reference` ni `reference_accept`. Une app générée naît donc avec **un
       slot unique**, typé par l'union de toutes les extensions de l'app. ⚠ Ce n'est PAS « en
       dessous des apps écrites à la main » — sur le converter la jumelle est au contraire plus
       fidèle (a) ; c'est en dessous **sur le nombre de slots**, et sur ce seul point. Sur le
       converter c'est indolore (une seule entrée) ; dès la 2ᵉ app portée, le sélecteur de fichier
       du slot « image de travail » proposerait `.docx` et le slot de référence n'existerait pas.
       ⚠ **Mesure du 2026-08-30 (relevé des 12 cards, contrôle ①bis) — la déclaration PLATE est
       INCOHÉRENTE sur les slots de référence, et les deux apps qui en ont tranchent en sens
       inverse** : l'avatarizer INCLUT son image de référence dans `input_extensions`
       (`AUDIO + IMAGE`), le composer EXCLUT son audio de mélodie (`TEXT_EXTENSIONS` seul, alors
       que sa card offre `reference_accept='audio/*'`). Conséquence concrète côté composer : le
       menu « Envoyer vers… » du filemanager (bâti sur `input_extensions`) ne proposera jamais le
       composer pour un fichier audio, alors que la card l'accepte. Aucun des deux choix n'est
       « le bon » : c'est la preuve qu'une liste plate ne peut pas dire « travail » vs
       « référence » — exactement ce que la déclaration PAR SLOT résout.
       ⇒ **Ce qu'il faut réparer avant de porter au-delà du converter** : donner au manifeste une
       déclaration d'entrées PAR SLOT (le vocabulaire existe : `INPUT_TYPES`, cf. amendement ③
       du point 7) et faire émettre à `templates_gen` les paramètres que les gabarits manuels
       passent déjà. Ce n'est pas un chantier de card, c'est un chantier de DÉCLARATION.
       ✅ **LIVRÉ le 2026-08-30 — la moitié RÉFÉRENCE, et la frontière de l'autre moitié est
       MESURÉE.** Le geste suit la clé manquante identifiée ci-dessus : `inputs[]` se déclare
       désormais **au niveau DOMAINE** pour les apps sans switch (règle écrite dans l'encadré
       d'`app_modes.py` : un domaine à switch les laisse à ses modes — c'est ce que le switch
       fait varier). 7 domaines déclarés depuis les cards RÉELLES (composer
       `prompt+reference_melody+prompt_file`, imager ×2, avatarizer `prompt+work_audio` — PAS
       `reference_voice` : l'audio y est l'entrée de TRAVAIL, un slot référence aurait créé un
       port audio EN DOUBLE —, converter/reader/describer `work_file`). `studio_node_ports` lit
       les deux niveaux (3 lignes) → le composer gagne ENFIN son port `reference_melody` audio
       (l'incohérence mesurée ci-dessus se résout PAR LA DÉCLARATION : l'intake, le studio et
       l'appariement le voient sans une ligne), et `templates_gen` émet
       `show_reference`/`reference_accept`/`reference_label` DEPUIS LE PORT — le câblage
       d'attache reste un **TROU NOMMÉ** dans le JS généré (marche B), un 2ᵉ port référence non
       rendu est NOMMÉ aussi. 4 tests (`tests_codegen_templates::SlotDeReferenceGenereTest`,
       dont la chaîne complète déclare→dérive→émet sur le composer VIVANT — baseline : 0
       `show_reference` dans le gabarit sur HEAD) ; corpus régénéré (6 manifestes), roundtrip
       10/10 OK, suite 1216 OK.
       ~~🔴 L'autre moitié — typer le slot de TRAVAIL — est BLOQUÉE par l'homonyme `text` ;
       ne pas tenter ce rétrécissement avant l'arbitrage~~ → **ARBITRAGE TRANCHÉ (30/08,
       §S2bis.6bis : `text` retiré des natures) ET MOITIÉ LIVRÉE le jour même** :
       `templates_gen` RÉTRÉCIT `file_accept` aux catégories du port travail (+ formats de
       lot si `has_batch`), contrôle 2 sens `CardEntreeConformiteTest`. ⚠ L'interdit rouge
       qui vivait ici a survécu 24 h à sa levée (recalé à l'audit du 31/08) — *un interdit
       périmé lu au pied de la lettre ferait DÉFAIRE une livraison* ; le lever dans le
       commit qui livre, jamais après.
     - **(c)** → promu en section propre ci-dessous (`§S2bis.6bis`) : c'est un arbitrage, pas un
       reste de passe.
  7. **Compatibilité avec l'« intake universel »** (chantier d'une autre instance,
     `WAMA_LLM §Intake universel`) — **mesurée, pas supposée.** Le plan est bon dans sa structure
     (sas `temp/`, rôle = ROUTAGE et non colonne en base, outil de ciblage read-only, dialogue
     porté par le skill) mais ses étapes ⓪/① composent sur **exactement les deux déclarations
     PLATES** ci-dessus. Mesure (composition proposée vs composition par RÔLE) :
     `notes.txt` / un `.md` de protocole / `liste.csv` → par nature : avatarizer, composer, imager,
     <!-- ⚠ ne PAS réécrire « un `.md` de protocole » en nom de fichier inventé : `check_docs` lit
          tout nom suivi de l'extension Markdown, entre accents graves, comme une RÉFÉRENCE DE
          DOCUMENT et le compte cassé. Mesuré le 30/08 : l'exemple précédent ouvrait une 2ᵉ CIBLE
          DISTINCTE, donc franchissait le seuil du /reprise sans qu'aucune doc n'ait bougé — et ma
          première rédaction de cet avertissement l'a refait, en citant le motif entre accents. -->

     synthesizer = **100 % de faux positifs** (par extension jusqu'à 6 apps) ; **par rôle :
     aucune**. `rapport.pdf`/`memo.docx` → l'extension ajoute composer/imager/synthesizer (leurs
     `input_extensions` SONT `TEXT_EXTENSIONS`) ; par rôle : converter, describer, reader (port
     travail). `prise.wav` → le rôle **GAGNE** une réponse vraie que la nature rate : synthesizer,
     port `reference_voice`, groupe **référence** — le « fichier de référence » de l'énoncé.
     `donnees.trip` → invisible par extension (monde Data). D'où 4 amendements proposés :
     ⓪ ne pas dériver une allowlist de plus — ne rien filtrer DANS `temp/` ; ① `capabilities_for_path`
     compose sur `studio_node_ports` et rend **quel PORT de quelle app**, pas quelle app ;
     ③ réutiliser `INPUT_TYPES` comme LE vocabulaire de rôles (sa projection texte existe déjà :
     `-i/-p/-r/-o` de `BATCH_FORMAT`) au lieu d'un 3ᵉ enum ; ④ exclure les jumelles de bac à sable
     (`converter_01` est dans `APP_CATALOG`) des cibles de capacité.
  8. **La jumelle `converter_01` rendait 500 sur 🗑 — c'était le PARC, pas l'app.** Symptôme :
     « Suppression impossible », modale et inspecteur vides. `django-errors.log` : `TypeError:
     safe_delete_file() missing 1 required positional argument` à `converter_01/views.py, line
     276` — or sur disque `delete` est en **316** et l'appel est correct : le process servait un
     module PÉRIMÉ. `gunicorn_conf.py` n'a **pas** de `preload_app`, `workers=4`,
     `max_requests=1000` + jitter → après une régénération les workers se recyclent **un par un**
     et le parc est **MIXTE**. L'item avait de surcroît été créé par l'ancienne vue d'upload
     (`media_type`/`output_format` vides en base, jamais rétro-remplis) : d'où la card muette.
     *Corollaire de vérification : un smoke navigateur mesuré sur un parc non redémarré ne mesure
     pas le code qu'on vient d'écrire.* Redémarrer (`pkill -HUP -f "gunicorn wama.wsgi"`, sans
     danger faute de `preload_app`) **AVANT** la mesure, puis re-déposer un fichier.
  9. **`options_source` : DEUX familles de sources, un seul registre existait** (constat Fabien
     après re-dépôt : « la modale s'affiche, mais je vois options "formats" non déclaré »). Le
     resolver généré ne connaissait que les sources **ASYNCHRONES** (`OPTION_SOURCES` de
     `wama-params.js` — un endpoint par clé, aujourd'hui `voices` seul) ; toute autre clé tombait
     sur un `<option>` d'avertissement, donc pas de format de sortie, donc rien de lançable.
     ⚠⚠ **Et mon premier commentaire de correctif rangeait ça en TROU DU FORMALISME** — « rien, ni
     dans `Param` ni au manifeste, ne dit d'où viennent ces options ». **Faux** : la table
     `CONVERTER_OUTPUT_FORMATS` est posée sur **toutes** les pages par un processeur de contexte
     global (`accounts/context_processors.py:56`), et `converter.js` la lisait déjà. C'est la
     **4ᵉ fois cette semaine dans ce seul fichier** (après `accepts_url`, la facette `inspector`,
     puis le vocabulaire d'entrée du point 4) : *ce qui manque n'est pas la prudence, c'est le grep.*
     Corrigé au niveau COMMUN, pas dans le gabarit : 2ᵉ registre `PAGE_OPTION_SOURCES`
     (`wama-params.js`, sources **synchrones tirées des données de page**) + `resolvePageOptions()`
     exporté, `window.WAMA_OUTPUT_FORMATS` posé une fois dans `base.html`, et le resolver généré
     qui interroge **les deux registres** avant de se plaindre — en nommant la clé absente.
     Restent 2 clés non résolues et **assumées explicitement** (`SOURCES_NON_RESOLUES` du module de
     tests) : `backends` (transcriber) et `avatar_gallery` (studio, déclarée hors schéma d'app).
  10. **La barre de file n'était câblable que par une app — donc jamais par un gabarit.** Le
     partial `_queue_actions.html` reçoit des **ids** et son contrat dit « handlers JS de l'app » ;
     or un gabarit ne peut pas écrire de handler, il ne peut que passer une URL. La jumelle naissait
     donc avec ses trois boutons inertes. Corrigé par le **3ᵉ étage** de `queue-actions.js`
     (élément → lot → **FILE**) : `queueAction('data-queue-start-url')` / `('data-queue-clear-url')`,
     attributs émis par le partial **seulement si une URL est passée** — les apps qui gardent leur
     handler par id ne bougent pas (sinon : POST en double). Le ⬇ n'a besoin d'aucun JS
     (`download_all` = GET `FileResponse`) : le gabarit passe `download_url` et le partial rend un
     vrai `<a href>` au lieu du bouton `disabled` par construction (`composer/index.html:87` le
     faisait déjà — la variable existait, une seule app l'utilisait). Routes résolues par
     `resolve_route()` (point 2), jamais supposées.
     **Vérification** : `common/tests_codegen_templates.py` (module neuf — `templates_gen` n'en avait
     aucun), **prouvés DISCRIMINANTS en les rejouant dans un worktree sur HEAD** : 6/11 rouges avant
     correctif. Le 7ᵉ passait **à vide** (il bouclait sur une liste d'URLs vide = l'état défectueux)
     → assertion de cardinalité ajoutée. *Un test qui ne boucle sur rien atteste le néant.*
  11. **⚠⚠ LE BALAYAGE EXHAUSTIF DES 10 APPS A DÉMENTI MA PROPRE JUSTIFICATION** (demandé par
     Fabien le 29/08 : *« vérifier que je n'ai pas réinventé quelque chose du commun »*). J'avais
     écrit — dans le partial, dans le JS **et** dans le message de commit — que ces boutons « ont
     longtemps été DÉCORATIFS chez plusieurs apps », sur la foi d'**un** commentaire lu dans
     `imager/index.html:96`. Mesure :

     | ce qui est câblé à la main | ▶ | 🗑 | ⬇ |
     |---|---|---|---|
     | apps (12 barres incluses dans 10 apps) | **10/10** | **10/10** | **9/10** (composer passe `download_url`) |

     Le commentaire de l'imager parlait de l'imager **seul**, et sa ligne suivante dit que son JS
     « les branche désormais ». *J'ai lu un constat DATÉ et LOCAL comme l'état général du parc* —
     le défaut que `queue-actions.js` documente déjà trois fois (neuf noms de fonctions lus comme
     neuf comportements). **Le vrai constat est l'autre, et il ne change rien au correctif mais
     tout à sa raison** : ~22 handlers recopiés dans 10 apps pour deux actions qui font partout
     POST + rechargement. *Un nommage uniforme (les ids viennent d'un partial commun) peut cacher
     une duplication que rien ne signale — c'est le cas le plus trompeur, déjà rencontré au niveau
     LOT.* Il n'y avait donc pas de « bouton mort » à ranimer : il y avait 22 copies à résorber.
  12. **Et le balayage a trouvé le vrai défaut de MA brique : l'étage du bas était le plus pauvre.**
     `queueAction` était une copie de `batchAction` **amputée de `body` et de `followUp`**. Or le
     relevé des 10 `start_all` montre que la divergence y est RÉELLE, comme au niveau lot :
     6 rechargent, 3 insèrent + pollent (describer/transcriber/enhancer), et **le synthesizer
     PORTE ses réglages dans le POST** (`wama/synthesizer/views.py:922` lit `tts_model`, `language`,
     `voice_preset`, `speed`, `pitch`, `voice_reference` — « démarrer tout » y vaut « appliquer à
     tout »). Sans ces deux hooks, **4 apps sur 10 étaient inportables** et auraient gardé leur
     handler : *une brique dont le contrat est plus pauvre que le code qu'elle remplace ne résorbe
     rien, et ça ne se voit qu'à la migration suivante.* Les deux étages passent désormais par un
     seul `groupAction()` (les deux seules différences — le sélecteur et le `stopPropagation` de
     la card mère repliable — sont des paramètres), et le ▶ de file expose `onQueueStarted` /
     `onQueueStartBody`. 3 tests de PARITÉ, rouges 3/3 rejoués sur HEAD.
     ⚠⚠ **Et le hook ne suffisait PAS** (question de Fabien le jour même : *« est-ce que le
     synthesizer rentre proprement dans la brique ? »*). Non — et le défaut était **muet des deux
     côtés** : `JSON.stringify(new FormData())` vaut `"{}"`, donc un corps multipart (le seul moyen
     de porter `voice_reference`, un **fichier**) serait parti VIDE sans erreur ; et même avec un
     objet plat, `request.POST` reste vide sur un corps JSON, or la vue ne lit **que** `request.POST`.
     `post()` laisse désormais passer un `FormData` tel quel, **sans** `Content-Type` (la frontière
     multipart est posée par le navigateur ; l'écrire à la main casse le parsing Django).
     *Ouvrir un point d'extension ne suffit pas : il faut vérifier que ce qu'une app y mettrait
     PASSE réellement.* Le hook seul rendait le synthesizer portable **sur le papier**.
     ~~⏳ Reste : la brique le rend PORTABLE, pas encore RÉGÉNÉRABLE — piste d'une capacité
     `start_all_applique_les_reglages`~~ → **diagnostic DÉPASSÉ par une livraison côté
     SERVEUR (31/08, §S2ter)** : l'upload généré déroule la cascade de réglages du dépôt
     (défauts applicables du schéma ← user_settings ← POST) — le cas « un dépôt hérite des
     réglages » est couvert par la DÉCLARATION (le schéma), sans hook JS ni capacité
     nouvelle. La piste n'a plus d'objet ; ne pas la rouvrir.
     Effet de bord : le commentaire de `post()` affirmait que l'enhancer audio était « le seul cas
     mesuré » portant des réglages — il l'était **au niveau LOT**, périmètre du relevé du 27/08.
     *Un relevé vaut pour le périmètre où il a été fait ; l'écrire comme une propriété des apps le
     rend faux au premier étage suivant.*
     ✅ **FAIT le 2026-08-30** (ex-pending « le ⬇ de file rejoue en petit
     `common/_download_button.html` »). La brique reçoit `id` / `label` / `split`, sa branche
     `split=False` rend **un bouton + un menu ▾** (pas de `dropdown-toggle-split` : la rangée
     d'actions ne s'élargit pas), et se rend **même quand `ready` est faux** — c'était la
     condition pour que les 3 apps qui basculent `disabled` au runtime continuent de marcher.
     `_queue_actions.html` délègue derrière `{% if app and download_url %}` ; **sans `app`, le
     rendu est inchangé à l'octet près**, donc aucune app n'a eu à bouger.
     Le dropdown JS du transcriber (4 formats **codés en dur**, URL par
     `replace('start_all','download_all')`) est SUPPRIMÉ ; les formats viennent du catalogue.
     Attesté : 46 tests verts (dont 6 neufs, `common/tests_downloads.py`), 112 gabarits compilés,
     grille inchangée, et **fumée serveur** — les 4 `?format=` sont dans le HTML servi, les 10 apps
     répondent 200.
     ⚠ Deux gardes neuves plutôt qu'un commentaire : un test refuse `dropdown-toggle-split` sur la
     barre, un autre **balaie les JS d'app** à la recherche de `classList.add('dropdown-toggle')`.
     La duplication résorbée n'était pas un gabarit recopié mais un dropdown **reconstruit en JS** :
     aucun test de gabarit ne pouvait la voir.

     ⏳ **CE QUI RESTE — et le dénominateur JUSTE n'est pas 12** (rectifié le 2026-08-30, correction
     de Fabien : *« il y a les applications early binding et les late binding »*).

     🔴 **Le menu ▾ multi-format ne concerne QUE les apps `export_binding='late'`.** Ce n'est pas
     une nuance d'implémentation, c'est le sens du geste :

     | | où le format est choisi | ce que ⬇ doit rendre |
     |---|---|---|
     | **`early`** (7 apps) | **AVANT le traitement**, dans les paramètres — le fichier produit EST déjà au format voulu | **un bouton simple.** Un menu de formats y serait un mensonge : il n'y a rien à reformater au téléchargement |
     | **`late`** (3 apps) | **AU TÉLÉCHARGEMENT** — un master est produit, l'export en dérive | **le bouton + le menu ▾** |

     Ma première rédaction disait « les 7 autres n'ont qu'un format, y déléguer ne changerait rien
     à l'écran ». C'était **le bon écran pour la mauvaise raison** — donc une phrase qui aurait fait
     porter le menu à la première app early qui gagne un 2ᵉ format. ⚠ **Un critère qui coïncide avec
     le bon résultat n'est pas pour autant le bon critère** : le nombre de formats est une
     CONSÉQUENCE, `export_binding` est la CAUSE, et il est DÉCLARÉ (`app_registry.py`, défaut
     `'early'`) — donc il n'y avait pas à le déduire.
     ✅ **Rien à durcir dans le code** : l'équivalence `late ⟺ des formats déclarés` est déjà un
     INVARIANT MÉCANIQUE (`common/tests_catalogues.py:349`), donc `entries_for_app()` rend
     naturellement une liste vide sur une app `early` et le tag retombe sur le lien simple. Ajouter
     une garde ici mettrait la même règle à deux endroits. Et `common/utils/export_formats.py`
     énonce la distinction dès son 1ᵉʳ paragraphe : **c'est ma prose qui avait dérivé, pas le code**
     — le module que je venais de renommer portait la bonne réponse en tête.

     **Adoption réelle, sur le bon dénominateur : ~~1 barre sur 3~~ ✅ 3/3 (2026-08-30, 2ᵉ
     session — reader et describer PORTÉS, en commençant côté VUE comme exigé ci-dessous)** :
     leurs `download_all` lisent `?format=` (idiome transcriber : repli txt par item, jamais un
     ZIP en erreur ; sans query, comportement historique inchangé), les 2 gabarits passent
     `app=` + `download_url` (+ `download_ready=True` chez le describer, dont le bouton a
     toujours été actif — aucun toggle JS, contrairement à reader/transcriber), et les 2
     handlers JS `window.location` sont RETIRÉS (ils auraient détourné l'OUVERTURE du menu —
     remplacer, jamais juxtaposer) + `staticfiles/` resynchronisé. Garde attrapée en route :
     `PasDeRecidiveTests` a refusé mes deux `Content-Disposition` composés en f-string →
     `content_disposition_header` (la garde a mordu sur son auteur, c'est sa raison d'être).
     Fumée serveur : les 3 barres late servent EXACTEMENT leurs `export_formats` déclarés
     (reader txt/md/pdf/docx/json · describer txt/pdf/docx · transcriber txt/srt/pdf/docx).
     Le tableau ci-dessous reste la photo du 30/08 MATIN (avant portage) :

     | | mesuré le 30/08 |
     |---|---|
     | apps `export_binding='late'` | **3** — describer `txt/pdf/docx`, reader `txt/md/pdf/docx/json`, transcriber `txt/srt/pdf/docx` |
     | dont la vue `download_all` LIT `?format=` | **1** — le transcriber SEUL (`wama/transcriber/views.py:1256`) |
     | apps `export_binding='early'` (hors périmètre du menu) | **7** |
     | barres `_queue_toolbar` au total | **12** (imager et enhancer en ont 2) — dénominateur du markup, pas du menu |

     ⚠⚠ **Porter describer et reader aujourd'hui afficherait un menu que le serveur IGNORE** :
     `?format=` n'y est lu que par le download d'ITEM (`reader/views.py:441`, `describer/views.py:558`) ;
     leur `download_all` (`reader/views.py:559`, `describer/views.py:737`) construit le ZIP sans
     regarder la query. C'est exactement la famille « vert d'ADOPTION, faux en FONCTIONNEMENT »
     (`WAMA_VERIFICATION §Geste 14`). **Le portage de ces deux-là commence côté VUE.**
     ⚠ Le GÉNÉRATEUR est opté À DEUX NIVEAUX DISTINCTS (recalé à l'audit du 31/08 — « pas
     opté » écrit ici était devenu faux avec la card v3) : la BARRE de file passe
     `download_url` sans `app=` ni `download_ready` (lien toujours actif, voulu) ; la CARD
     générée, elle, appelle `{% download_button %}` avec `ready` dérivé du statut. Une app
     générée `late` devra déclarer les deux.

### §S2bis.6bis — ~~🔴 ARBITRAGE OUVERT~~ ✅ TRANCHÉ le 2026-08-30 : l'homonyme `text`

> **CLÔTURE (Fabien, 30/08, dernier message)** : après vérification du cas transcription (le
> texte brut d'un résultat est un CONTENU en base, qui devient un *document* à l'export via le
> `?format=` late-binding — jamais besoin d'une nature `text`), Fabien valide : *« text n'a a
> priori sa place nulle part [dans les natures d'entrée/sortie]. Dans ce cas, on parle de
> prompt pour une application de traduction, l'imager, le synthesizer, etc. »* — c'est la
> ligne 3 de la table (saisie = `prompt`, fichiers texte = `document`, `text` RETIRÉ), décidée
> comme **quick win du monde Médias, à faire tout de suite**, avec l'ajout de la nature
> `dataset` dans le même geste (plan de compatibilité, item B — le rayon ne se paie qu'une
> fois). ✅ **GESTE EXÉCUTÉ le jour même** (inventaire exhaustif site-par-site AVANT, 32
> fichiers, double et indivisible : sens prompt séparé PUIS nature basculée) — suite 1221 OK,
> roundtrip 10/10, grille sans recul (converter/describer/transcriber 100 %), corpus régénéré,
> `.trip/.wdat/.rec` → `dataset` (poussé par le monde via `register_category_extensions`),
> `.csv/.txt/.srt/.json` → `document`, describer normalisé À LA LECTURE (pas de migration).
> Bénéfice mesuré au passage : les 3 écarts `.md` du vocabulaire généré ont DISPARU, et le
> nœud Sortie du studio gagne `document/dataset/3d` (le `3d` manquait, bug latent). La moitié
> TRAVAIL de (b) — rétrécir `file_accept` par catégories — a été DÉBLOQUÉE puis **LIVRÉE le
> jour même de son déblocage** (`templates_gen`, lecture des catégories du port travail +
> formats de lot si `has_batch` ; contrôle 2 sens `CardEntreeConformiteTest`). **Smoke navigateur ✅ (même soir, parc RELANCÉ par Fabien)** :
> catalogue `/common/apps/` conforme (blocs Texte/Documents rendus via `prompt`, 201 badges,
> couleurs d'identité, 0 erreur console) · barres ⬇ reader/describer servent leurs menus
> `?format=` réels (5 et 3 formats, bouton describer actif) · `accept` du converter DÉRIVÉ vu
> du navigateur (60 jetons, `.zip` et `.qt` présents) · `wama-studio.js` SERVI au nouveau
> vocabulaire (`prompt`/`dataset`, ancien motif absent). ⚠ relevé annexe hors geste : 2
> ressources 403 sur `/reader/` (volet explorateur du compte de test) — à regarder un jour.
> Le reste de cette section = l'HISTORIQUE de l'arbitrage.

> Promu de « reste de passe (c) » à section propre le 2026-08-30, sur remarque de Fabien : *« ça
> semble un chantier à part entière ; une phrase pour une question qui semble complexe et
> fondamentale, ce n'est pas compréhensible »*. Il a raison, et une ligne dans une liste de restes
> laissait croire à un nettoyage de vocabulaire. **C'en est un de DONNÉES.**

**Le problème en une phrase :** le jeton `text` désigne **deux choses différentes** selon l'endroit
où on le lit, et aucune des deux ne peut céder la place à l'autre sans casser l'autre moitié.

| sens | où | exemple |
|---|---|---|
| **« texte brut / le prompt »** — une saisie, pas un fichier | `input_types`, `accepts`, `INPUT_TYPES['prompt'].kind` | imager déclare `input_types=('text','image')` = « on saisit un prompt, on joint une image » |
| **« FICHIER texte »** — une nature de média sur disque | `category_of_path`, `MEDIA_CATEGORIES` | `notes.txt` → catégorie `text` |

**Ce que ça produit déjà, mesuré :**
- `studio_node_ports` (`app_registry.py:153`) doit écrire `c != 'text'` pour empêcher le prompt
  d'entrer dans le port de travail, puis **inventer le jeton `'prompt'`, absent de
  `MEDIA_CATEGORIES` (`:67`)** — le code a fabriqué le mot qui manquait, sans le déclarer ;
- `common/utils/intake.py:10` consigne que `input_extensions` est « FAUX à 100 % sur
  `.txt`/`.md`/`.csv` » **pour cette raison précise** ;
- le repli du vocabulaire d'entrée (point 6 ci-dessus) a dû poser une « exclusion explicite de
  `text` » — une exception codée en dur, symptôme et non correctif.

**Pourquoi ce n'est PAS un renommage ordinaire — le rayon mesuré :** `MEDIA_CATEGORIES`,
`normalize_types`, les ports studio **en entrée ET en sortie**, `media_library.TYPE_GROUPS`,
`derive_category` / `_TEXT_OUTPUTS`, et surtout **`detected_type`, qui est STOCKÉ EN BASE** par le
**describer** (⚠ rectifié le 2026-08-30 : cette ligne l'attribuait au reader, qui n'en a AUCUNE
occurrence — mesuré ; le champ est `describer/models.py:90`, écrit par
`detect_type_from_extension` avec un vocabulaire LOCAL `image/video/audio/pdf/text`, **défaut
`'text'`**, et les vues du describer branchent dessus). Ce point le sort de la méthode
`/renommage-api` : ce n'est pas un grep tokenisé, c'est une **migration de données** — des lignes
existantes portent la valeur ambiguë, et il faut décider ce qu'elles deviennent avant de toucher
au code.

**Ce qui doit être arbitré, dans l'ordre :**
1. **Quel des deux sens garde le mot `text`** (l'autre prend un mot neuf — `prompt` existe déjà
   *de facto* côté ports, ce qui penche pour « `text` = fichier texte, `prompt` = saisie ») ;
2. **ce que deviennent les valeurs déjà en base** (migration de données : réécrire, ou laisser et
   interpréter au vol) ;
3. **où vit la taxonomie qui en découle** — ⚠ **RECTIFIÉ le 2026-08-30 (vérification de
   compatibilité monde Data, `WAMA_DATA_WORLD.md §compat`)** : cette ligne affirmait qu'elle est
   inter-mondes (`common/catalog/data_types.py`) et que l'arbitrage engage le Lab et le monde
   Data. **C'est faux, et mesurable** : `data_types.py` déclare 11 types de DONNÉE
   (geo_track/timeseries/…), d'**intersection VIDE** avec `MEDIA_CATEGORIES`, sans jeton `text`
   (0 occurrence taxonomique dans `wama_data/`), et aucun des 7 sites du rayon mesuré ci-dessus
   n'est hors de `wama/`. La taxonomie des NATURES vit dans `app_registry.py` — **le retrait de
   `text` est un chantier 100 % monde Médias**. Deux taxonomies parallèles coexistent (natures
   média / types de donnée) ; leur éventuel axe commun est l'item B du plan de compatibilité.

⛔ **Ne pas le trancher au fil d'un autre chantier** — et ne pas le confondre avec (b) ci-dessus,
qui est réparable sans lui : donner des entrées PAR SLOT au générateur ne demande pas de choisir
le sens de `text`, seulement de ne plus mélanger les slots.

**🧭🧭 RECADRAGE UNIVERSEL (Fabien, 2026-08-30, 2ᵉ passe — PRIME sur le bloc position
ci-dessous, jugé « trop étroit » car raisonné sur le cas .txt/.md/.csv) :**

> *« Il faut revenir au global, à l'universel. Comment gère-t-on tous les rôles et tous les
> types de fichiers média. C'est le seul moyen de trouver une réponse claire et universelle
> qui ne changera plus à l'avenir. »*

1. **Deux axes ORTHOGONAUX, aucun mot ne porte les deux.** La **NATURE** dit ce que le fichier
   EST (taxonomie des médias) ; le **RÔLE** dit ce qu'il FAIT dans un process (les ports :
   travail / référence / saisie / lot / config…). Toute entrée d'un process est un couple
   (nature, rôle). L'homonyme `text` n'existait que parce qu'un seul mot essayait de porter
   les deux axes.
2. **La taxonomie des natures, en langage naturel (Fabien)** : tout fichier est un *document*
   au sens large (« dès que du texte est enregistré dans un support » — une image aussi est un
   document). Parmi eux, les **documents textuels**, avec la distinction historique
   **« mis en forme »** (docx, pdf, tex…) vs **« bruts »** (txt, md, csv). Image, vidéo,
   audio, archive, 3D : autres natures. La sous-distinction formé/brut reste disponible si un
   consommateur en a besoin — son consommateur HISTORIQUE (reconnaître les fichiers batch)
   meurt avec les zones de rôle de la card v3.5.
3. **Le prompt est un RÔLE, pas une nature — et sa matérialisation est un passage, pas une
   ambiguïté** : le texte saisi (rôle saisie) DEVIENT un document textuel brut quand il entre
   en file (pour être exporté avec le résultat). Rôle à l'entrée, nature au stockage : les
   deux axes se relaient, ils ne se contredisent plus.
4. **Conséquence dérivée (et non plus « à arbitrer » cas par cas)** : dans le vocabulaire des
   NATURES, `text` disparaît (les fichiers texte sont des documents, éventuellement
   sous-typés bruts/formés) ; dans le vocabulaire des RÔLES, la saisie garde son jeton
   (`prompt`, déjà en place dans les ports).
   ⚠ **« Retirer `text` » retire un JETON de classement, jamais une capacité** (question de
   Fabien, 30/08 : « et les CSV/TSV/Excel du monde Data ? ») : un `.csv` reste accepté partout
   où il l'était — il est classé `document` au lieu de `text` côté Médias, et côté Data il ne
   passe DE TOUTE FAÇON pas par ce vocabulaire : le lecteur tabulaire
   (`wama_data/sources/tabular.py`) déclare ses propres extensions et produit des types de
   DONNÉE (`table`, `timeseries`… — `data_types.py`, intouchée). Un `.csv` a deux vies
   (document-média / source tabulaire-data) ; c'est le GESTE qui départage, pas le jeton. La table « 3 affectations » du bloc ci-dessous
   devient un DÉTAIL D'EXÉCUTION de ce cadre — sa ligne 3 en est la traduction mécanique.
   Restent les gestes déjà identifiés : migration `detected_type` (describer) et balayage du
   rayon mesuré plus haut.

**🧭 POSITION DE FABIEN (2026-08-30, session card v3.5 — une DIRECTION, pas encore le geste) :**
1. **« Le rôle `text` doit s'appliquer au texte brut et non aux documents texte. »** Donc :
   `text` = la SAISIE (le sens prompt) ; les fichiers `.txt/.md/.csv` sont des **documents**.
   ⚠ Le point 1 « ce qui doit être arbitré » ci-dessus notait un penchant CONTRAIRE — non pas
   une raison de fond, mais un MOINDRE-EFFORT : le code ayant déjà fabriqué `prompt` pour la
   saisie, garder `text` aux fichiers semblait le chemin court. La position de Fabien repose,
   elle, sur le SENS (l'exception de catégorie n'existait que pour le batch — point 2) : c'est
   elle qui prime. Les trois affectations possibles du mot, posées à plat :

   | option | la saisie s'appelle | `.txt/.md/.csv` sont | le mot `text` |
   |---|---|---|---|
   | penchant initial (moindre-effort) | `prompt` | `text` | = fichier |
   | position Fabien, au pied de la lettre | `text` | `document` | = saisie |
   | voie sûre (Claude) | `prompt` (inchangé) | `document` | **RETIRÉ** |

   Les deux dernières lignes partagent **LA décision de fond — les fichiers texte deviennent
   des documents** — et ne diffèrent que sur le MOT qui nomme la saisie. Réaffecter `text`
   (ligne 2) ferait changer de sens, en silence, tout code qui lit `'text'` aujourd'hui — *un
   renommage ne casse rien, il rend FAUX* ; le retirer (ligne 3) réalise la même intention sans
   ce risque : le rôle « texte brut » existe, il s'épelle `prompt`. **Reste à Fabien de trancher
   entre les lignes 2 et 3.**
2. **L'origine de l'exception est identifiée** — la catégorie `text` posée sur `.txt/.md/.csv`
   (le `prime sur document` de `_build_cat_of`, `app_registry.py:76-78`) servait à **différencier
   fichiers de travail et fichiers BATCH**. Malgré l'auto-détection, l'unification des deux dans
   le même encart « reste ambivalente dans certains cas » (Fabien). Or la card v3.5 **sépare les
   rôles de fichiers en zones explicites** (travail / référence / batch…) : le rôle redevient
   porté par LE GESTE de dépôt, et l'exception de catégorie perd sa raison d'être. *La séparation
   des rôles à l'UI et le sens du jeton se résolvent ensemble.*
3. **Conséquence directe si cette direction est confirmée** : `.txt/.md/.csv` redeviennent
   `document` dans `category_of_path` → la moitié TRAVAIL de (b) (rétrécir `file_accept` par les
   catégories du port) **se débloque** — le describer cesse d'être le contre-exemple.
4. **Ce qui reste à trancher AVANT le geste** (inchangé) : la migration des valeurs en base
   (`detected_type`), le sort du jeton `prompt` des ports (fusionne-t-il avec `text` ou
   subsiste-t-il ?), et le domicile inter-mondes de la taxonomie. Le rayon mesuré plus haut
   reste le rayon.

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
  niveau 3/10, absent imager) ; `register_batch_sync` ~~9/10~~ **10/10 depuis le 2026-08-28**
  (converter adopté avec `direct_fk=True`, `converter/apps.py:24` — re-mesuré 31/08).
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

### §S2ter — Génération des RÉGLAGES (30-31/08) + relevés d'adoption re-mesurés (31/08)

> Bloc écrit à l'AUDIT du 31/08 : quatre commits de codegen (30-31/08) avaient leur
> consignation dans `PROJECT_STATUS` mais AUCUNE trace ici — la partie la plus dense de
> `views_gen`/`templates_gen` était invisible de la route. Détail d'exécution :
> `PROJECT_STATUS §PALIER 2026-08-31`.

**Ce que le générateur émet désormais pour les RÉGLAGES (constats Fabien 31/08, tout mesuré
sur la jumelle — batterie 11/11 sans skip) :**
- **Hôte UNIQUE du volet** `{app}PanelParams` (`d-none`), rendu au CHARGEMENT du même schéma
  que la modale (context `'panel'`) puis MONTRÉ à la sélection — `panelContainer`
  d'initFromSchema y applique les valeurs de la card. Deux hôtes du même schéma
  dupliqueraient les ids `wp-panel-*` : un hôte, deux moments.
- **Resolver d'options PARTAGÉ** (`resolveOptions`) entre hôte du volet, modale d'élément et
  modale de lot — deux resolvers émis séparément avaient déjà divergé. `formats` sans
  `media_type` → UNION des familles (registre commun `wama-params.js`).
- **Ouvreur de modale de LOT** : `WamaQueueActions.onBatchSettings` → `settingsModal`
  contexte `'batch'` (la brique accepte `context` depuis le 31/08), gaté par la route
  `batch_update` ET la présence de params de contexte batch. Valeurs vides à l'ouverture :
  un lot APPLIQUE ses réglages, il ne les stocke pas.
- **Cascade de réglages du DÉPÔT** dans l'upload généré : défauts APPLICABLES du schéma
  (`param_schema.applicable_defaults`, filtre `show_if` au vocabulaire du moteur JS) ←
  `user_settings` persistés (⚠ `defaults` définit les clés LUES) ← POST non vide,
  re-persisté. La nature détectée n'est jamais écrasée.
- **`gear_data` par brique commune** (`card_gear`, accepte objets Param ET dicts — le `{}`
  muet sur dicts était le ⚙ nu) + **chips générés** (`card_chips`, assiette `values` pour
  les réglages en JSON) + idiome `params_storage` DÉRIVÉ (colonnes ↔ conteneur `options`,
  aplati par `_decorer` — la card, le volet et la modale lisent CE que `update` écrit).
- **Cible `params` substituable** (7ᵉ) : `params.py` généré du manifeste au littéral
  (`params_gen`, constructeur partagé avec write_back).

**Relevés d'adoption RE-MESURÉS le 31/08 (balayage exhaustif des 10 apps — chiffres à ne
recopier NULLE PART, re-mesurer)** :
- `WamaQueueActions.onSettings` (déclencheur) **10/10** · `WamaParams.settingsModal` (cycle
  complet) **2/10** — anonymizer, imager. ⚠ C'est la confusion déclencheur/cycle qui a
  rendu fausses TOUTES les tables précédentes de ce doc.
- `context:'batch'` **10/10** · chips **10/10** (11 décorateurs `_decorate_*`, 6 noms — le
  codegen génère un `_decorer` CONCURRENT : candidat brique) · `gear_data` **10/10** ·
  `initFromSchema`+`panelContainer` **10/10** · `reconcile_orphaned_running` **10/10**
  (bloc quasi identique — candidat brique) · `register_batch_sync` **10/10**.
- **`WamaImport` et `_app_scripts.html` : 0/10 dans le parc réel** — ces deux briques ne
  vivent que dans le gabarit généré et le banc. Une app générée et une app à la main ne
  chargent pas leur JS ni n'importent leurs fichiers par le même chemin : toute doc qui
  décrit la chaîne générée comme « la » voie décrit un parc de zéro app.
- **`_is_app_owned` (propriété des fichiers) : 1/10** — le converter SEUL protège les
  fichiers utilisateur seulement référencés ; l'avatarizer fait l'OPPOSÉ (rattachement par
  référence voulu). ⚠ **Arbitrage de PLATEFORME non pris** : se caler sur la majorité
  généraliserait la suppression de fichiers utilisateur ; se caler sur le converter sans le
  dire casserait la galerie avatarizer. À trancher AVANT de dériver la suppression dans le
  gabarit.
- **Le graphe transverse app→app n'est déclaré nulle part** : `common/` importe 6 apps
  médias, `inline_convert` (converter) sert 5 apps, `speakers` (transcriber) sert
  `document_export`/`llm_utils`, `voice_utils` (synthesizer) sert l'avatarizer et
  `voice_options`, `UserSettings` (anonymizer) sert la page de profil. **Régénérer une app
  sans ce graphe rompt ces arêtes en silence** — à déclarer (candidat : `requires`
  inter-apps au manifeste).

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

> **Passe de confirmation du 2026-08-22.** Les statuts ci-dessous ont été re-mesurés contre le
> code, pas relus. Résultat : **2 trous étaient CLOS sans que la table le dise** (19, 21), **1
> était faux sur ses chiffres ET sa liste** (2 — avatarizer n'avait jamais adopté la brique
> qu'on lui attribuait), **1 avait changé de camp** (24 : le générateur est normalisé, le trou
> est passé au parc existant). Les autres re-mesurés (23, 25, 26) sont **exacts** — 25 au
> détail près (4+2+1+1 = 8 doubles inclusions, inchangé).
>
> Leçon récurrente : une table de trous se périme **par le haut** — ce sont les lignes qu'on a
> refermées sans y revenir qui trompent, plus que celles qu'on n'a pas traitées. Re-mesurer
> avant de planifier, jamais l'inverse.

| # | Trou | Facette | Nature |
|---|---|---|---|
| 1 | ✅ **fait (2026-08-11, §10.1)** — describer `input_types` `text`→`document` : le port travail porte `document`, le port prompt fantôme a disparu | F2 | ✅ |
| 2 | ✅ **clos comme trou d'adoption — RE-MESURÉ 2026-08-31 : `context:'batch'` est à 10/10** (avatarizer compris, `index.html:367` — la ligne précédente « 5/10, avatarizer jamais » était périmée par le bas ; 3ᵉ recomptage de cette ligne, toujours faux). Le générateur émet désormais l'ouvreur de lot COMPLET (`onBatchSettings` + `settingsModal context:'batch'`, §S2ter). Le déficit RÉEL a changé de nom : le **cycle complet** `settingsModal` n'est qu'à **2/10** (8 apps gardent leur coquille + save maison) — c'est la ligne « cycle » de la table F3, pas celle-ci | F3 | ✅ re-qualifié |
| 3 | studio `renderNodeParams` appauvri (réinvente WamaParams en dégradant) | F3/F8 | réinvention à supprimer |
| 4 | ✅ **périmé (2026-07-30)** — le front consomme bien `?side=during` (`wama-inspector.js::_startDuring`). Trou RÉEL reformulé : l'**émission** de partiels n'existe que dans le composer (1/10) | F3b | adoption, pas frontend |
| 5 | `select_model()` : composer, transcriber, imager, **reader** (2026-07-31, `61a666f`). Reclaim VRAM ✅ **unifié** (cf. F4). Ce qui restait n'était PAS un trou : enhancer/avatarizer/synthesizer n'ont **aucune sélection automatique à faire** (l'utilisateur désigne, ou le modèle vit hors process) ; describer = unification différée par CLAUDE.md (Phase 4) ; anonymizer = `select_best_models()` couvre un **jeu de classes avec plusieurs modèles** là où la brique n'en choisit qu'un, et lit déjà le catalogue → sur-ensemble légitime | F4 | ✅ pour l'essentiel |
| 5b | **Capacités canoniques** ✅ (2026-07-31, `8ffac24`) : `inputs_required/optional` n'était produit que par **2 découvertes sur 9** → `WamaInputMatch` n'avait rien à comparer (c'est la cause de `input_match_ui` 9/10 KO, pas un défaut d'UI). Les 98 modèles portent désormais `task` + `modalities` + `inputs_*`, zéro clé hors `CANONICAL_CAPABILITIES`. ⚠ La canonicalisation se fait **à la DÉCOUVERTE**, pas dans les `model_config` d'app : frontière **délibérée** (l'app déclare en son vocabulaire, le catalogue est la source unique) | F4 | ✅ |
| 6 | **statuts non uniformes** → 3 tables d'alias | F5 | dette de schéma |
| 7 | ✅ **clos (2026-08-01)** — gating ré-appliqué **par nœud** au RUN (`studio/tasks.py:181`) ET sur toute la surface outils (`tool_accessible`, cf. F7). Le trou était plus large que décrit : `/api/v1/tools/run/` n'était gardé par RIEN (middleware aveugle à `/api/v1/`, auth DRF postérieure au middleware) et `tools/list` annonçait 43 outils à tous. Mesuré après correctif : 22/43 annoncés à un compte `recherche` seul, `create_image` → 403 | F7 | ✅ |
| 8 | **pas de test de contrat** sur la triade tool_api | F6 | robustesse |
| 9 | imager : ✅ résolu — alias `add_to_imager` (`tool_api.py:2042`, `functools.wraps(create_image)` + remap `generation_id`→`item_id`) | F6 | clos |
| 10 | ✅ **résolu (2026-08-11, palier params)** — la facette capte TOUS les `*PARAMS_JSON` (`{primary, schemas}`) ; imager 2 schémas, enhancer 2 schémas | F3 | ✅ |
| 19 | **Divergence store⟷réalité non détectée** (avis critique 2026-08-11) : l'apply est un geste explicite (voulu, sûreté §2.1) mais RIEN ne signale une dérive entre manifestes ingérés et registres — discipline Terraform : jamais d'apply auto, mais un plan/verify qui TOURNE et signale. Brancher `manifest_roundtrip --all` + `verify` dans les contrôles nocturnes (charpente §18 existante). → ✅ **CLOS — confirmé le 2026-08-22** : le scénario `common.consistency.manifest_roundtrip` est enregistré dans la charpente (`nightly_scenarios.py:338-340`, étage `consistency`, timeout 300 s) et `doc_facts` l'appelle aussi (`doc_facts.py:77`). La détection TOURNE ; l'apply reste un geste explicite, comme voulu | transverse | ✅ |
| 11 | `APP_MODES` (hand-maintained) à dissoudre : domaine=hint UI, mode=dérivé capacités | F2 | dette de conception |
| 12 | anonymizer : refactor yolo/SAM3 en sélecteur modèle groupé + switch capacités (pas un « mode ») | F2/F3 | refactor UX |
| 13 | avatarizer (rapide/qualité=param) + composer (music/bruitage=sélection modèle) : sortir du mécanisme modes | F2 | simplification |
| 14 | **ingest média** (`source_url`→fichier local). ✅ **Mécanisme commun bâti** (2026-07-22, `d8960e5`) : `common/utils/source_ingest.ensure_local_input(instance)`, piloté par une déclaration modèle `WAMA_INGEST = {source, target, mode: media\|audio\|smart, name_field?, size_field?, title_field?}` (stopgap). Les 2 wrappers describer/transcriber sont **fusionnés** dessus (le transcriber **crashait** sans ce maillon). Réutilise `url_ingest.fetch_url_content` / `video_utils.upload_media_from_url`/`download_youtube_audio`. **Reste (côté instance manifeste) :** capacité **F2** `accepts_url`/`accepts_local_path` (→ génère la card au lieu du `show_url` manuel) + **facette F5** `ingest:{…}` qui *projette* vers `WAMA_INGEST` (remplacer le stopgap). Adopter l'URL sur une app = déclarer `WAMA_INGEST` + appeler `ensure_local_input` en tête de tâche. **✅ EXTRACT fait 2026-07-23** : `extract_app` capte `capabilities.accepts_url` + `processing.ingest` (lit `WAMA_INGEST` du modèle d'item via DetailRegistry ; transcriber/describer remontent leur spec, apps sans ingest → None). Reste = la **projection write-back** (manifeste → `WAMA_INGEST`), avec le reste de l'app_gen. | F2/F5 | extract ✅, projection ⏳ |
| 16 | **drapeaux de `capabilities` non régénérables** (mesuré 2026-08-11, pilote converter) : la facette mélange 3 natures — (a) 4 scalaires déclaratifs (✅ projetés), (b) drapeaux d'ÉTAT de conformité (inspector, layout, during_preview… : `_conv()` écrasé par la grille — ils convergeront par la MESURE une fois le code de l'app régénéré, ne JAMAIS les projeter), (c) N/A déclarés (`None` dans `_conv`, ex. `model_help=None` du converter) qui SONT du déclaratif mais vivent dans l'appel `_conv(...)` — leur projection exigerait d'écrire un appel `_conv(model_help=None, …)`, à trancher | F2 | manifeste/frontière déclaré-mesuré |
| 18 | **Couverture tool_api hors catalogue** (audit 2026-08-11 : 43→46 outils ; re-vérifié RUNTIME 2026-08-17 : 46→**48**) : les 10 apps du catalogue ont leur triade COMPLÈTE (+ double triade enhancer/audio_enhancer, + verbes primaires aliasés) ; le **studio** est ✅ ; **model_manager LECTURE ✅ (2026-08-17)** — `list_ai_models` (filtres app/task/modality/downloaded, proposés exclus par défaut) + `get_ai_model` (fiche complète licence/auteur/capacités/empreintes), **transverses** (alignés sur l'ouverture du méta-catalogue à tous les selects via WamaModelHelp ; une future action d'ÉCRITURE serait gardée `model_manager`). Restent à trancher par usage réel : **wama_lab** (cam_analyzer, face_analyzer — 13 tâches Celery sans surface outil), **media_library en écriture** (import ; la lecture existe). ⚠ À VÉRIFIER (constat 17/08) : `/model-manager/api/models/db/` (source de WamaModelHelp) est sous le gating PAR CHEMIN de l'app model_manager (dev-only) — l'aide-modèle est-elle silencieusement INERTE pour un compte non-dev ? (le fetch avale l'échec sans erreur console). NB : la facette `tool_api` du manifeste ne capte que la triade canonique — la double triade enhancer lui est invisible (rattacher à #17) | F6 | couverture |
| 17 | **3 facettes dont l'extract ne capte pas (que) du déclaratif** (mesuré 2026-08-11) : `inspector` = booléens de PRÉSENCE (detail/preview_registered) — rien à projeter, le déclaratif réel est la spec Detail d'`apps.py` (même diagnostic que `studio` avant correction) ; `prompts.skills` = NOMS de fichiers `.md` sans contenu ; `tool_api` = présence de la triade + descriptions DÉRIVÉES (les fonctions elles-mêmes = code, tier difficile avec `processing`) | F3/F6 | trous d'extract |
| 15 | **`system_tools` non déclarés** (chromium, ffmpeg, rsvg…) — le volet **librairies** du manifeste est CLOS (2026-08-03/11 : `requires:{kind:library}` dans l'enveloppe, résolu et bloquant, kind + registre `Library` + `write_back_library` livrés, 1er lien transcriber→faster-whisper) ; ce qui manque encore est la déclaration des **outils système** et leur provisionneur commun (cf. `PROJECT_STATUS` §23.6, qui annonçait ce trou sans qu'il ait été reporté ici) | F4/F5 | manifeste |
| 20 | ✅ **clos (2026-08-13, le jour de sa découverte)** — Routes par-outil `/api/tools/*` NON gardées par le gating F7 : les **10** vues individuelles de `wama/tool_api.py` (« for manual testing ») appelaient les fonctions d'outil DIRECTEMENT — sans `execute_tool`, donc sans `tool_accessible` — et `app_id_for_path('/api/tools/…')` → None (segment `api`) : le middleware ne les couvrait pas non plus. Seul `@login_required` s'appliquait : tier + rôles contournés — **jumeau exact du trou #7** (même mécanique, autre surface). **Correctif** : les 10 vues passent par un adaptateur unique `_vue_outil` → `execute_tool` (LA porte : gating, sanitisation, coercition, bornes de choix), `forbidden` → 403. Mesuré : user sans rôle → 403 sur anonymizer/status, 200 sur converter (ouvert) et list-files (transverse) | F7 | ✅ |
| 21 | **Couche JS d'APPLICATION non générée** (mesuré 2026-08-22, converter_01) : le gabarit généré n'émet AUCUN bloc `app_scripts`, alors que le socle l'offre (`app_modern_base.html:294`). Le JS de l'app existe dans `static/` mais n'est jamais chargé → aucun écouteur posé, aucune voie d'import n'émet de requête, **zéro erreur console** (rien ne plante quand rien n'est chargé). C'est ce silence qui l'a rendu invisible au banc codegen, qui ne compare que des facettes projetables. Brique livrée : `common/_app_scripts.html` (noyau mesuré sur 10 apps + options). → ✅ **CLOS — confirmé le 2026-08-22** : `templates_gen.py:116-117` émet désormais `{% block app_scripts %}` + l'inclusion de `common/_app_scripts.html`, suivis des seules URL propres à l'app (lot, progression globale). L'avertissement « le générateur ne l'émet toujours pas » est PÉRIMÉ — il décrivait l'état d'avant le portage dans `templates_gen`. | F1/F3 | ✅ |
| 22 | ~~**`batch_create` encore bouchonné (501)**~~ → ✅ **CLOS le 2026-08-22**. Vue conventionnelle rendue par la fabrique (parse → création → `group_into_batches_by_nature`), zéro brique nouvelle. **Une URL n'y est PAS téléchargée** : la source est enregistrée et `ensure_local_input` la résout en tête de tâche — la requête ne part pas chercher N fichiers distants, et le seul chemin de téléchargement reste celui qui passe par la garde SSRF. Mesuré de bout en bout sur `converter_01` : 2 éléments créés, rattachés à un lot (`wama/common/tests_codegen_lot.py`, 8 tests). **Deux défauts trouvés en le câblant** : ① la 2ᵉ passe d'assemblage (`extra_routes`) ne consultait pas les corps conventionnels — une route déclarée en extra recevait un 501 alors que la fabrique savait la rendre (3ᵉ occurrence du motif « deux chemins, deux apps », après `WAMA_INGEST` et le `pk` de `batch_preview`) ; ② la clé d'ingest est `source`, pas `source_field`. | F1 | codegen |
| 23 | **`auto_wrap_orphans` sans variante FK-DIRECTE** : la brique commune suppose un modèle de LIAISON ; converter est la seule app à FK directe et réécrit une boucle de 6 lignes, désormais reproduite dans le gabarit généré. Motif écrit à 4 endroits (converter, avatarizer, synthesizer, codegen) → extraction justifiée. Même angle mort pour `build_batches_list`, que 9 apps sur 10 utilisent et qui ne couvre pas la FK directe (prefetch `items__work_attr`). | F1/F5 | brique |
| 24 | **Contrat de réponse d'`upload` non normalisé** : converter renvoie `job_id`, le gabarit généré `id`, d'autres `pk`. `converter.js` lisait `data.job_id` là où la vue générée renvoyait `id` → identifiant `undefined`, liste vide, pas de rechargement, **aucune card, sans erreur**. `wama-import.js` lit désormais les trois graphies (filet), mais la normalisation des vues reste à faire — l'affichage ne doit pas dépendre d'un nom de clé. **Précisé le 2026-08-22 :** le trou n'est plus côté GÉNÉRATEUR — `views_gen.py` renvoie uniformément `{'id': …}` sur toutes ses vues. → ✅ **CLOS côté parc aussi (constaté à l'audit du 2026-08-31)** : `grep "'job_id':" wama/*/views.py` = 0 occurrence — le converter a TRADUIT vers `id` avec la justification écrite (`converter/views.py:261-272`). Le filet à trois graphies de `wama-import.js` n'a plus de cas connu ; il reste comme ceinture, plus comme nécessité. | F1 | ✅ |
| 25 | **8 doubles inclusions de JS** (mesuré 2026-08-22) : `wama-model-help` ×4 (composer, converter, reader, transcriber), `wama-queue` ×2 (composer, describer), `wama-cycle-button` ×1 (composer), `console` ×1 (anonymizer) — tous DÉJÀ chargés globalement par `base.html`/`app_modern_base.html`. Même famille que le bug du player audio muet du 18/08 (deux BroadcastChannel). Disparaissent à l'adoption de `_app_scripts.html` — ⚠ **adoption à 0/10 dans le parc réel au 31/08** (le partial ne vit que dans le gabarit GÉNÉRÉ) : ce trou ne se refermera pas tout seul, il attend le portage. | F3 | dette |
| 26 | **Aucun critère ne voit une zone de dépôt que rien n'écoute** : la grille mesure la présence du markup, pas l'existence d'un écouteur. C'est ce qui a laissé converter_01 inerte sans qu'aucune mesure ne baisse. Critère à écrire : une app qui rend `[data-wama-nic]`/dropzone sans charger de voie d'import échoue. ~~Confirmé OUVERT le 2026-08-22~~ → ✅ **LE CRITÈRE EXISTE (constaté à l'audit du 31/08)** : `Criterion('import_wired', 'F2', « Voie d'import CHARGÉE par le gabarit (dépôt non inerte) »)`, `conformity_checker.py` — avec exactement les subtilités réclamées ici (`data-wama-depot`, exemption « aucune card d'entrée »). La ligne « confirmé ouvert » a survécu à l'écriture du critère qu'elle spécifiait — le réécrire aurait fait un doublon pur. Reste vrai le corollaire : ⚠ Devenu plus facile à écrire depuis : la card d'entrée commune porte `data-wama-depot` (`cree`\|`attache`), donc le critère peut distinguer « rien n'écoute » (défaut) de « le dépôt joint, le bouton primaire crée » (conception légitime d'avatarizer/imager) — distinction qu'aucune heuristique de DOM ne savait faire, et qui est la raison pour laquelle ce critère n'avait pas été écrit. **⚠ Le PATRON existe désormais (2026-08-23) : `settings_wiring`** mesure exactement cette forme — le markup ET l'écouteur, en exigeant les DEUX (`.settings-btn[data-id]` dans le gabarit + `WamaQueueActions.onSettings` déclaré), et rend `partial` quand un seul des deux est là (« bouton au contrat, mais AUCUN ouvreur déclaré — clic inerte »). Le critère de dépôt se calque dessus. Corollaire appris le même jour : un critère de ce genre est passé **vert 10/10 le jour de son écriture** — il faut donc l'accompagner d'un scénario qui CLIQUE, sinon il atteste une adoption qu'on prendra pour un fonctionnement. | F3 | grille |
| 27 | **`compact_preview` (reader) orphelin + 3e copie** : le filtre templatetag n'a plus d'appelant depuis le portage du 22/08 (le commun rend l'extrait), et la MÊME logique existe une troisième fois dans `reader/views.py::_compact_preview`, toujours utilisée pour la charge d'API. Candidat REMOVAL_LEDGER. Idem `imager` : `openImagePreview`/`openVideoPreview` sans appelant depuis le portage du mécanisme n°30. | F3 | dette |
| 28 | **La boucle codegen exige un REDÉMARRAGE** : `gunicorn_conf.py` n'a ni `reload` ni `preload_app`, donc aucune modification Python (`apps.py`, `views.py`, briques communes) n'est prise sans relance. Trois diagnostics de la session du 22/08 s'y sont heurtés — **un QUATRIÈME le 2026-08-23**, et sous une forme plus traître : `max_requests = 1000` recycle les workers **un par un**, donc la pile se retrouve MIXTE (mesuré : 2 workers sur 4 dataient d'avant la modification). Une route Python ajoutée existait donc pour la moitié des requêtes seulement, et un gabarit qui la référence rendait `NoReverseMatch` → **500 INTERMITTENT**. Coût : un A/B complet contre HEAD pour écarter une fausse régression. ⚠ **Une hypothèse « workers périmés » avait d'abord été REJETÉE à tort sur 6 sondes toutes vertes** — il en fallait 30 pour voir les 2/30 en 404 : sur un parc mixte, un petit échantillon ne décide rien. **Remède mesuré : `kill -HUP <maître>`** — sans `preload_app`, les workers réimportent l'application, le socket n'est pas lâché, et c'est instantané ; inutile de relancer la pile. Les gabarits, eux, se relisent à chaque requête — c'est ce décalage gabarit/Python qui fabrique le symptôme. À écrire dans la recette de génération — et à trancher : `reload = True` en dev ? | — | outillage |

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
